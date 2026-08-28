"""
Books-integrity reconciliation engine (task #244).

Generalizes the manual SQL audit performed by hand on 2026-07-25 (which found
a ₹38.14L inventory-ledger drift and a ₹15,036.14 gap from 5 sales invoices
whose COGS journal silently never posted) into a standing, reusable set of
checks. Both the daily scheduled job (jobs/scheduler.py) and the on-demand
"Verify Books" endpoint (routers/reconciliation.py) call run_reconciliation()
below, so there is exactly one code path producing findings — a CA pressing
"Verify Books" sees the same checks the nightly sweep already ran.

REPORT-ONLY, DELIBERATELY. Unlike services/balance_cache_service.py's
audit_and_heal — which safely self-heals because a derived cache is a PURE
function of the ledger and can never be made worse by recomputing it — a
genuine finding here (a missing journal, a drifted inventory cache) needs the
same human judgement today's manual fixes required (was this money actually
missing, or already covered somewhere else? does correcting it need its own
GL entry, or would that double-count?). Findings are persisted for a CA to
review and act on deliberately; nothing here writes a correcting entry.

Reuses domain.reporting.sources.SupabaseLedgerSource — the SAME paginated,
retried, firm/client-scoped posted-ledger fetch the live P&L/Balance Sheet
reports use — so "the posted ledger" can never mean something different
here than what the CA is already looking at on screen.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from domain.reporting.sources import SupabaseLedgerSource

_logger = logging.getLogger("caflow.reconciliation")

_PAGE = 1000


def _paginate_all(make_query, key: str = "id") -> list[dict]:
    """Keyset-paginate a Supabase query to completion — an un-paged .execute()
    silently caps at PostgREST's ~1000-row default limit (the same class of
    bug documented in services/tds_return_service.py's own copy of this).

    EVERY CALLER MUST SELECT `key`. Line for line below, the cursor advances by
    rows[-1][key] — so a select that omits it works perfectly up to the 1000th
    row and then raises KeyError. The failure therefore appears only on a
    client busy enough to need the second page, which is the client whose
    numbers most need to be right. tests/test_paginated_selects_carry_their_key.py
    checks every call site."""
    out: list[dict] = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(_PAGE).execute().data or []
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        cursor = rows[-1][key]
    return out


def _find_account_id(db, firm_id: str, client_id: str, account_name: str) -> Optional[str]:
    """EXACT account_name match (firm-wide or this client's own), never ILIKE
    substring — mirrors services/tds_return_service.py's
    _find_account_by_exact_name for the same reason: "Trade Receivables" and
    a hypothetical near-namesake must never resolve ambiguously. Confirmed
    live (task #244 follow-up) that this client's chart also carries an
    UNUSED "Accounts Receivable"/"Accounts Payable" pair (system_account_key
    'ar'/'ap', zero posted lines) alongside the real "Trade Receivables"/
    "Trade Payables" accounts (system_account_key NULL, everything actually
    posts here) — system_account_key lookup alone would silently resolve to
    the wrong, empty account for this exact pair. Not fixed here (a separate,
    pre-existing chart-of-accounts seeding question); flagged, and this
    reconciliation depends only on the exact name real postings use."""
    resp = (
        db.table("chart_of_accounts").select("id")
        .eq("firm_id", firm_id)
        .or_(f"client_id.eq.{client_id},client_id.is.null")
        .eq("account_name", account_name)
        .eq("is_active", True)
        .limit(1).execute()
    )
    return resp.data[0]["id"] if resp.data else None


def _account_balance(entries, account_id: Optional[str]) -> int:
    """Net DEBIT balance (debit - credit) for one account across a set of
    already-fetched posted JournalEntry objects — no extra DB round trip."""
    if not account_id:
        return 0
    total = 0
    for entry in entries.values():
        for line in entry.lines:
            if line.account_id == account_id:
                total += line.debit_paise - line.credit_paise
    return total


def _finding(check_name: str, severity: str, summary: str, *, amount_paise: Optional[int] = None, **details) -> dict:
    return {
        "check_name": check_name, "severity": severity, "summary": summary,
        "amount_paise": amount_paise, "details": details,
    }


# ── Individual checks — each takes (db, firm_id, client_id, entries) and ────
# returns a list of finding dicts. `entries` is the client's full posted
# ledger (dict[id -> JournalEntry]), fetched once by run_reconciliation and
# shared across checks that need it, to avoid re-fetching the same data.

def check_trial_balance(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """The most basic invariant: total debits must equal total credits across
    every posted entry. A break here means something bypassed the posting
    kernel's own balance guard entirely (see migration 243's DB-level
    backstop, added specifically to make this structurally harder)."""
    total_debit = sum(line.debit_paise for e in entries.values() for line in e.lines)
    total_credit = sum(line.credit_paise for e in entries.values() for line in e.lines)
    if total_debit != total_credit:
        return [_finding(
            "trial_balance", "critical",
            f"Trial balance is out by {abs(total_debit - total_credit)} paise — "
            "total debits do not equal total credits across posted entries.",
            amount_paise=total_debit - total_credit,
            total_debit_paise=total_debit, total_credit_paise=total_credit,
        )]
    return []


def check_missing_cogs_journals(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """Every posted sales invoice with inventory ('good') lines must have a
    matching Dr COGS / Cr Inventory journal (see
    domain/inventory_service.py::apply_sale_to_inventory /
    post_cogs_journal_entry, reference_no = f"{invoice_no}-COGS"). This is
    the exact bug class found by hand on 2026-07-25: the stock ledger
    correctly recorded 5 invoices' goods leaving, but their COGS journal
    silently never posted."""
    ledger_rows = _paginate_all(lambda: (
        db.table("inventory_stock_ledger").select("id, source_id, value_delta_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("source_type", "sales_invoice").eq("movement_type", "sale")
    ))
    if not ledger_rows:
        return []
    by_invoice: dict[str, int] = {}
    for row in ledger_rows:
        sid = row.get("source_id")
        if sid:
            by_invoice[sid] = by_invoice.get(sid, 0) + abs(int(row["value_delta_paise"] or 0))
    by_invoice = {k: v for k, v in by_invoice.items() if v > 0}
    if not by_invoice:
        return []

    invoices = _paginate_all(lambda: (
        db.table("client_sales_invoices").select("id, invoice_no")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .in_("id", list(by_invoice.keys()))
    ))
    invoice_no_by_id = {i["id"]: (i.get("invoice_no") or i["id"]) for i in invoices}

    posted_refs = {e.reference_no for e in entries.values() if e.reference_no}

    findings = []
    for invoice_id, cogs_paise in by_invoice.items():
        invoice_no = invoice_no_by_id.get(invoice_id, invoice_id)
        if f"{invoice_no}-COGS" not in posted_refs:
            findings.append(_finding(
                "missing_cogs_journal", "critical",
                f"Sales invoice {invoice_no} sold inventory (₹{cogs_paise/100:.2f} cost) "
                "but no matching COGS journal was ever posted to the GL.",
                amount_paise=cogs_paise, invoice_id=invoice_id, invoice_no=invoice_no,
            ))
    return findings


def check_missing_inventory_receipt_journals(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """Mirror of check_missing_cogs_journals for the purchase side: every
    posted purchase bill with inventory lines must have a matching Dr
    Inventory / Cr [expense] capitalisation journal (reference_no =
    f"{purchase_bill_journal_ref(bill_id)}-INV", or the pre-fix
    f"{bill_no}-INV" for older bills — see
    domain/inventory_service.py::apply_purchase_to_inventory /
    reverse_purchase_stock, which itself tries both patterns for the same
    reason)."""
    from services.phase2_journal_service import purchase_bill_journal_ref

    ledger_rows = _paginate_all(lambda: (
        db.table("inventory_stock_ledger").select("id, source_id, value_delta_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("source_type", "purchase_bill").eq("movement_type", "purchase")
    ))
    if not ledger_rows:
        return []
    by_bill: dict[str, int] = {}
    for row in ledger_rows:
        sid = row.get("source_id")
        if sid:
            by_bill[sid] = by_bill.get(sid, 0) + abs(int(row["value_delta_paise"] or 0))
    by_bill = {k: v for k, v in by_bill.items() if v > 0}
    if not by_bill:
        return []

    bills = _paginate_all(lambda: (
        db.table("purchase_bills").select("id, bill_no")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .in_("id", list(by_bill.keys()))
    ))
    bill_no_by_id = {b["id"]: (b.get("bill_no") or b["id"]) for b in bills}

    posted_refs = {e.reference_no for e in entries.values() if e.reference_no}

    findings = []
    for bill_id, receipt_paise in by_bill.items():
        bill_no = bill_no_by_id.get(bill_id, bill_id)
        candidates = (f"{purchase_bill_journal_ref(bill_id)}-INV", f"{bill_no}-INV")
        if not any(ref in posted_refs for ref in candidates):
            findings.append(_finding(
                "missing_inventory_receipt_journal", "critical",
                f"Purchase bill {bill_no} received inventory (₹{receipt_paise/100:.2f}) "
                "but no matching Inventory capitalisation journal was ever posted to the GL.",
                amount_paise=receipt_paise, bill_id=bill_id, bill_no=bill_no,
            ))
    return findings


def check_inventory_cache_drift(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """service_catalogue's cached stock_qty_units/avg_cost_paise (what the
    Inventory tab displays) must match its item's own last
    inventory_stock_ledger row (the authoritative, append-only chain) —
    the exact ₹38.14L drift found and corrected by hand on 2026-07-25.
    _insert_and_cache (domain/inventory_service.py) keeps these in lockstep
    on every live write, so drift here means either the cache/ledger fell
    out of sync some other way (a data-load, a direct write bypassing the
    normal code path) or the ledger's own running-total chain itself
    diverged from what its rows' individual deltas sum to — this check
    catches the SYMPTOM (cache vs. ledger) either way; distinguishing the
    two root causes is a manual follow-up, same as it was this time."""
    items = _paginate_all(lambda: (
        db.table("service_catalogue").select("id, name, stock_qty_units, avg_cost_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good")
    ))
    if not items:
        return []

    ledger_rows = _paginate_all(
        lambda: (
            db.table("inventory_stock_ledger")
            .select("id, service_catalogue_id, running_qty_units, running_avg_cost_paise, created_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
        ),
        key="id",
    )
    last_by_item: dict[str, dict] = {}
    for row in ledger_rows:
        sid = row["service_catalogue_id"]
        prev = last_by_item.get(sid)
        if prev is None or row["created_at"] > prev["created_at"]:
            last_by_item[sid] = row

    drifted = []
    total_drift_paise = 0
    for item in items:
        last = last_by_item.get(item["id"])
        if last is None:
            continue  # no ledger history at all — a separate, pre-existing setup gap, not drift
        cached_qty = float(item.get("stock_qty_units") or 0)
        cached_avg = int(item.get("avg_cost_paise") or 0)
        true_qty = float(last["running_qty_units"] or 0)
        true_avg = int(last["running_avg_cost_paise"] or 0)
        if cached_qty != true_qty or cached_avg != true_avg:
            drift_paise = round(cached_qty * cached_avg) - round(true_qty * true_avg)
            total_drift_paise += drift_paise
            drifted.append({
                "service_catalogue_id": item["id"], "name": item.get("name"),
                "cached_qty": cached_qty, "cached_avg_cost_paise": cached_avg,
                "ledger_qty": true_qty, "ledger_avg_cost_paise": true_avg,
                "drift_paise": drift_paise,
            })

    if not drifted:
        return []
    return [_finding(
        "inventory_cache_drift", "critical",
        f"{len(drifted)} inventory item(s) have a cached stock value that doesn't match "
        f"their own ledger history — net overstatement of {total_drift_paise} paise.",
        amount_paise=total_drift_paise, items=drifted[:100], item_count=len(drifted),
    )]


def check_ar_subledger_vs_gl(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """GL Trade Receivables balance must equal the sum of outstanding issued
    sales invoices (total - paid - credited + debit notes)."""
    account_id = _find_account_id(db, firm_id, client_id, "Trade Receivables")
    if not account_id:
        return []
    gl_paise = _account_balance(entries, account_id)

    invoices = _paginate_all(lambda: (
        db.table("client_sales_invoices")
        .select("id, total_paise, paid_paise, credited_paise, debit_note_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "issued")
    ))
    subledger_paise = sum(
        int(i.get("total_paise") or 0) - int(i.get("paid_paise") or 0)
        - int(i.get("credited_paise") or 0) + int(i.get("debit_note_paise") or 0)
        for i in invoices
    )
    diff = gl_paise - subledger_paise
    if diff != 0:
        return [_finding(
            "ar_subledger_vs_gl", "warning" if abs(diff) < 100_000 else "critical",
            f"GL Trade Receivables ({gl_paise} paise) does not match the sum of outstanding "
            f"sales invoices ({subledger_paise} paise) — off by {diff} paise.",
            amount_paise=diff, gl_paise=gl_paise, subledger_paise=subledger_paise,
        )]
    return []


def check_ap_subledger_vs_gl(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """Mirror of check_ar_subledger_vs_gl for Trade Payables / purchase bills."""
    account_id = _find_account_id(db, firm_id, client_id, "Trade Payables")
    if not account_id:
        return []
    gl_paise = -_account_balance(entries, account_id)  # AP is credit-normal

    bills = _paginate_all(lambda: (
        db.table("purchase_bills")
        .select("id, net_payable_paise, paid_paise, debited_paise, credit_note_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .in_("status", ["received", "partially_paid", "paid"])
    ))
    subledger_paise = sum(
        int(b.get("net_payable_paise") or 0) - int(b.get("paid_paise") or 0)
        - int(b.get("debited_paise") or 0) + int(b.get("credit_note_paise") or 0)
        for b in bills
    )
    diff = gl_paise - subledger_paise
    if diff != 0:
        return [_finding(
            "ap_subledger_vs_gl", "warning" if abs(diff) < 100_000 else "critical",
            f"GL Trade Payables ({gl_paise} paise) does not match the sum of outstanding "
            f"purchase bills ({subledger_paise} paise) — off by {diff} paise.",
            amount_paise=diff, gl_paise=gl_paise, subledger_paise=subledger_paise,
        )]
    return []


def check_bank_reconciliation_discrepancies(db, firm_id: str, client_id: str, entries) -> list[dict]:
    """A COMPLETED bank reconciliation must still be true.

    Completing a reconciliation freezes a snapshot of exactly which transactions
    were reconciled and for how much (bank_reconciliation_service._compute_report,
    stored on completion). That snapshot is a certification: the CA asserted this
    period ties out.

    Nothing stopped the underlying data moving afterwards. A reconciled
    transaction's journal can be reversed, or the transaction can be detached
    from the session — and the completed reconciliation goes on claiming a
    tie-out that is no longer true, silently, because the frozen report is
    exactly what makes it immune to noticing.

    This is the check QuickBooks calls the Reconciliation Discrepancy Report.
    It compares each completed session's snapshot against live data and reports
    what has moved since. It reads only; the CA decides what to do (which, now
    that Tier 2.5 exists, may be to reopen the period and redo it).

    Deliberately NOT flagged: a session that has been reopened and is back in
    progress. Its snapshot is preserved in reopen_history precisely because it
    no longer describes a current certification, so comparing against it would
    manufacture findings for a period someone is already fixing.
    """
    sessions = _paginate_all(lambda: (
        db.table("bank_reconciliations")
        .select("id, account_no, period_start, period_end, status, snapshot, completed_at")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "completed")
    ))
    if not sessions:
        return []

    # Every transaction still attached to any of these sessions, keyed by id.
    session_ids = [s["id"] for s in sessions]
    live_txns = _paginate_all(lambda: (
        db.table("bank_transactions")
        .select("id, reconciliation_id, debit_paise, credit_paise, posted_journal_id")
        .eq("firm_id", firm_id).in_("reconciliation_id", session_ids)
    ))
    live_by_id = {t["id"]: t for t in live_txns}

    findings: list[dict] = []
    for s in sessions:
        snap = s.get("snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:
                snap = None
        if not isinstance(snap, dict):
            continue  # completed before snapshots existed — nothing to compare
        period = f"{str(s.get('period_start'))[:10]} → {str(s.get('period_end'))[:10]}"
        label = f"{s.get('account_no') or 'bank account'} {period}"

        for line in snap.get("reconciled") or []:
            txn_id = line.get("id")
            live = live_by_id.get(txn_id)

            if live is None or live.get("reconciliation_id") != s["id"]:
                findings.append(_finding(
                    "bank_reconciliation_discrepancy", "critical",
                    f"A transaction reconciled in the completed reconciliation for {label} "
                    "is no longer attached to it — that period's tie-out is no longer true.",
                    reconciliation_id=s["id"], transaction_id=txn_id,
                    reason="detached", description=line.get("description"),
                ))
                continue

            snap_debit = int(line.get("debit_paise") or 0)
            snap_credit = int(line.get("credit_paise") or 0)
            if (int(live.get("debit_paise") or 0) != snap_debit
                    or int(live.get("credit_paise") or 0) != snap_credit):
                delta = ((int(live.get("debit_paise") or 0) - snap_debit)
                         - (int(live.get("credit_paise") or 0) - snap_credit))
                findings.append(_finding(
                    "bank_reconciliation_discrepancy", "critical",
                    f"A transaction reconciled in the completed reconciliation for {label} "
                    "has changed amount since it was certified.",
                    amount_paise=delta,
                    reconciliation_id=s["id"], transaction_id=txn_id, reason="amount_changed",
                    snapshot_debit_paise=snap_debit, snapshot_credit_paise=snap_credit,
                    live_debit_paise=int(live.get("debit_paise") or 0),
                    live_credit_paise=int(live.get("credit_paise") or 0),
                ))

            # The posting behind the line: reversed after the fact means the cash
            # movement the reconciliation certified has been undone in the books.
            je_id = live.get("posted_journal_id") or line.get("posted_journal_id")
            if je_id and je_id not in entries:
                findings.append(_finding(
                    "bank_reconciliation_discrepancy", "critical",
                    f"The journal behind a transaction reconciled in the completed "
                    f"reconciliation for {label} is no longer posted — it was reversed or "
                    "deleted after the period was certified.",
                    reconciliation_id=s["id"], transaction_id=txn_id,
                    journal_entry_id=je_id, reason="journal_not_posted",
                ))

    return findings


_CHECKS = [
    check_trial_balance,
    check_missing_cogs_journals,
    check_missing_inventory_receipt_journals,
    check_inventory_cache_drift,
    check_ar_subledger_vs_gl,
    check_ap_subledger_vs_gl,
    check_bank_reconciliation_discrepancies,
]


def run_reconciliation(db, firm_id: str, client_id: str, *, trigger: str, triggered_by: Optional[str] = None) -> dict:
    """Run every check for one client, persisting a reconciliation_runs row
    and one reconciliation_findings row per discrepancy (migration 244).

    trigger: "scheduled" (jobs/scheduler.py) or "manual" (the on-demand
    "Verify Books" endpoint). Never raises for an individual check's own
    failure — one broken check must not hide the others' results, and must
    itself become a visible finding rather than a silent gap in coverage.
    """
    run = (
        db.table("reconciliation_runs")
        .insert({
            "firm_id": firm_id, "client_id": client_id, "trigger": trigger,
            "status": "running", "triggered_by": triggered_by,
        })
        .execute()
    )
    run_id = run.data[0]["id"]

    try:
        entries = SupabaseLedgerSource(db)._entries(firm_id, client_id)
    except Exception as e:
        from core.observability import capture_posting_failure
        capture_posting_failure(e, operation="run_reconciliation.fetch_ledger", firm_id=firm_id, client_id=client_id)
        db.table("reconciliation_runs").update({
            "status": "failed", "error": str(e),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", run_id).execute()
        return {"run_id": run_id, "status": "failed", "error": str(e)}

    all_findings: list[dict] = []
    checks_run = 0
    for check_fn in _CHECKS:
        checks_run += 1
        try:
            all_findings.extend(check_fn(db, firm_id, client_id, entries))
        except Exception as e:
            from core.observability import capture_posting_failure
            capture_posting_failure(
                e, operation=f"reconciliation_check.{check_fn.__name__}",
                firm_id=firm_id, client_id=client_id,
            )
            all_findings.append(_finding(
                f"{check_fn.__name__}.execution_error", "critical",
                f"The '{check_fn.__name__}' check itself failed to run: {e}",
            ))

    if all_findings:
        rows = [
            {"run_id": run_id, "firm_id": firm_id, "client_id": client_id, **f}
            for f in all_findings
        ]
        for i in range(0, len(rows), 500):
            db.table("reconciliation_findings").insert(rows[i:i + 500]).execute()
        _logger.error(
            "reconciliation run %s (firm=%s client=%s trigger=%s) found %d finding(s)",
            run_id, firm_id, client_id, trigger, len(all_findings),
        )

    db.table("reconciliation_runs").update({
        "status": "completed", "checks_run": checks_run,
        "findings_count": len(all_findings),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", run_id).execute()

    return {
        "run_id": run_id, "status": "completed", "checks_run": checks_run,
        "findings_count": len(all_findings), "findings": all_findings,
    }


def run_reconciliation_for_firm(db, firm_id: str) -> dict:
    """Run reconciliation for every client of a firm — the unit the nightly
    scheduler job runs (jobs/scheduler.py), mirroring
    services/balance_cache_service.py's own audit_and_heal_firm. One bad
    client's run must not abort the firm-wide sweep."""
    clients = db.table("clients").select("id").eq("firm_id", firm_id).execute().data or []
    checked = 0
    findings_total = 0
    per_client: list[dict] = []
    for c in clients:
        cid = c["id"]
        try:
            result = run_reconciliation(db, firm_id, cid, trigger="scheduled")
        except Exception as e:  # one bad client must not abort the whole firm sweep
            from core.observability import capture_posting_failure
            capture_posting_failure(e, operation="run_reconciliation_for_firm", firm_id=firm_id, client_id=cid)
            per_client.append({"client_id": cid, "error": str(e)})
            continue
        checked += 1
        findings_total += result.get("findings_count", 0)
        per_client.append({
            "client_id": cid, "status": result["status"],
            "findings_count": result.get("findings_count", 0),
        })
    return {"clients_checked": checked, "findings_total": findings_total, "clients": per_client}
