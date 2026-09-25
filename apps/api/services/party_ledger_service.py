"""Who a control account is owed by, or owed to (ACC-13's other half).

Two paths, one rule. `public.party_ledger_as_at` (migration 419) is what
production runs — the answer is one row per party and the input is every line
ever posted to the account, so CLAUDE.md's reporting rule puts the aggregation
in the database. `domain/accounting/party_ledger.py` is the identical rule for
everything with no DATABASE_URL, and tests/test_party_ledger_parity_pg.py runs
every scenario through both.

The fallback is deliberate and not free: it reads every line on the account
into Python and then resolves the documents, which is exactly what the rule
forbids in production. It exists because mock mode and local dev have no SQL
functions at all, it logs loudly when it is reached, and it is the reason the
parity test exists — the same posture `stock_position_service` records.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.accounting import party_ledger as rule

_logger = logging.getLogger("caflow.party_ledger")


def _as_of(as_of: Optional[str]) -> str:
    return str(as_of)[:10] if as_of else ist_today().isoformat()


def _fetch_lines(db, firm_id: str, client_id: str, account_id: str, at: str) -> list[dict]:
    """Every posted line on this account up to the date, with its entry's
    source. Paged — PostgREST caps a response at ~1000 rows and says nothing
    when it does, so an unpaged read here is a breakdown that is silently
    short and still claims to foot."""
    def one_page():
        return (db.table("journal_lines")
                .select("id, account_id, debit_paise, credit_paise, "
                        "journal_entries!inner(id, firm_id, client_id, entry_date, "
                        "is_posted, deleted_at, source_type, source_id)")
                .eq("account_id", account_id)
                .eq("journal_entries.firm_id", firm_id)
                .eq("journal_entries.client_id", client_id)
                .eq("journal_entries.is_posted", True)
                .is_("journal_entries.deleted_at", "null")
                .lte("journal_entries.entry_date", at))
    return fetch_all(one_page, key="id", label="party_ledger.lines")


def _docs(db, firm_id: str, client_id: str, wanted: dict) -> dict:
    """source_id -> (party_id, kind), ONE read per document table.

    ⚠️ EIGHT LITERAL BLOCKS, not a loop over `rule.PARTY_SOURCES`, although
    the loop is four lines and this is forty. `tests/test_backend_columns_
    exist_pg` checks every `.select()` against the real schema as a STRING and
    a table reached through a VARIABLE is invisible to it — `db.table(t)` cost
    seven unreadable references and took all eight of these reads out of the
    check, on the resolution a breakdown that must foot depends on. Both that
    budget and the insert one are exact with no headroom, so it was a CI
    failure as well as a coverage hole. `domain/tally/party_identifiers`
    records paying the same price for the same reason, and records that
    RAISING the budget is the wrong answer where the coverage is recoverable.

    A test asserts these eight tables and columns ARE `rule.PARTY_SOURCES`, so
    the map stays the authority and the blocks cannot drift from it.

    Grouped by table rather than looked up per line: a thousand lines against
    one customer would otherwise be a thousand Singapore-to-Mumbai round trips
    for an answer that is one row.
    """
    out: dict[str, tuple[str, str]] = {}

    def take(rows, column, kind):
        for r in rows:
            pid = r.get(column)
            if pid:
                out[str(r["id"])] = (str(pid), kind)

    def ids(source_type):
        return sorted(wanted.get(source_type) or ())

    if (i := ids("sales_invoice")):
        take(fetch_all(lambda i=i: db.table("client_sales_invoices").select("id, customer_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.client_sales_invoices"),
             "customer_id", rule.CUSTOMER)
    if (i := ids("credit_note")):
        take(fetch_all(lambda i=i: db.table("credit_notes").select("id, customer_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.credit_notes"),
             "customer_id", rule.CUSTOMER)
    if (i := ids("sales_debit_note")):
        take(fetch_all(lambda i=i: db.table("sales_debit_notes").select("id, customer_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.sales_debit_notes"),
             "customer_id", rule.CUSTOMER)
    if (i := ids("receipt")):
        take(fetch_all(lambda i=i: db.table("receipts").select("id, customer_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.receipts"),
             "customer_id", rule.CUSTOMER)
    if (i := ids("purchase_bill")):
        take(fetch_all(lambda i=i: db.table("purchase_bills").select("id, vendor_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.purchase_bills"),
             "vendor_id", rule.VENDOR)
    if (i := ids("debit_note")):
        take(fetch_all(lambda i=i: db.table("debit_notes").select("id, vendor_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.debit_notes"),
             "vendor_id", rule.VENDOR)
    if (i := ids("purchase_credit_note")):
        take(fetch_all(lambda i=i: db.table("purchase_credit_notes").select("id, vendor_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.purchase_credit_notes"),
             "vendor_id", rule.VENDOR)
    if (i := ids("purchase_payment")):
        take(fetch_all(lambda i=i: db.table("purchase_payments").select("id, vendor_id")
                       .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", i),
                       key="id", label="party_ledger.purchase_payments"),
             "vendor_id", rule.VENDOR)
    return out


def _names(db, firm_id: str, customer_ids: set, vendor_ids: set) -> dict:
    """party_id -> name. Literal for `_docs`'s reason.

    ⚠️ LEFT-JOIN SEMANTICS IN PYTHON. debit_notes.vendor_id and
    purchase_credit_notes.vendor_id carry NO foreign key (migrations 145 and
    210), so a party id may name no master row. Its NAME is then unknown and
    its MONEY still counts — dropping it would break the invariant that the
    parts sum to the account, which is the one thing this report promises.
    """
    names: dict[str, str] = {}
    if customer_ids:
        for r in fetch_all(lambda i=sorted(customer_ids): db.table("customers")
                           .select("id, name").eq("firm_id", firm_id).in_("id", i),
                           key="id", label="party_ledger.customers"):
            names[str(r["id"])] = r.get("name") or "(unnamed)"
    if vendor_ids:
        for r in fetch_all(lambda i=sorted(vendor_ids): db.table("vendors")
                           .select("id, name").eq("firm_id", firm_id).in_("id", i),
                           key="id", label="party_ledger.vendors"):
            names[str(r["id"])] = r.get("name") or "(unnamed)"
    return names


def _resolve_parties(db, firm_id: str, client_id: str, lines: list[dict]) -> dict:
    """source_id -> (party_id, kind, name)."""
    wanted: dict[str, set[str]] = defaultdict(set)
    for ln in lines:
        je = ln.get("journal_entries") or {}
        st, sid = je.get("source_type"), je.get("source_id")
        if sid and st in rule.PARTY_SOURCES:
            wanted[st].add(str(sid))

    by_source = _docs(db, firm_id, client_id, wanted)
    customers = {pid for pid, kind in by_source.values() if kind == rule.CUSTOMER}
    vendors = {pid for pid, kind in by_source.values() if kind == rule.VENDOR}
    names = _names(db, firm_id, customers, vendors)
    return {sid: (pid, kind, names.get(pid, "(unnamed)"))
            for sid, (pid, kind) in by_source.items()}


def breakdown(db, firm_id: str, client_id: str, account_id: str,
              as_of: Optional[str] = None) -> dict:
    """One row per party, plus one per unattributable source kind."""
    if not client_id:
        raise HTTPException(status_code=422,
                            detail="client_id is required — a control account is client-owned")
    if not account_id:
        raise HTTPException(status_code=422, detail="account_id is required")
    at = _as_of(as_of)

    if db is None:
        return _envelope(at, account_id, rule.breakdown([]))

    if hasattr(db, "rpc"):
        try:
            res = db.rpc("party_ledger_as_at", {
                "p_firm": firm_id, "p_client": client_id,
                "p_account": account_id, "p_as_of": at,
            }).execute()
            out = getattr(res, "data", None)
            if isinstance(out, dict) and "rows" in out:
                return _from_sql(at, account_id, out)
            raise ValueError(
                f"party_ledger_as_at returned {type(out).__name__}, not a breakdown")
        except Exception as e:                                  # noqa: BLE001
            _logger.error("party_ledger_as_at failed (%s %s %s) — falling back to "
                          "the Python rule: %s", firm_id, client_id, account_id, e)

    lines = _fetch_lines(db, firm_id, client_id, account_id, at)
    parties = _resolve_parties(db, firm_id, client_id, lines)
    resolved = []
    for ln in lines:
        je = ln.get("journal_entries") or {}
        pid, kind, name = parties.get(str(je.get("source_id") or ""), (None, None, None))
        resolved.append({
            "source_type": je.get("source_type"),
            "party_id": pid, "party_kind": kind, "party_name": name,
            "debit_paise": ln.get("debit_paise"),
            "credit_paise": ln.get("credit_paise"),
        })
    return _envelope(at, account_id, rule.breakdown(resolved))


def _row(r) -> dict:
    return {
        "party_id": r.party_id,
        "party_name": r.party_name,
        "party_kind": r.party_kind,
        "unattributed_source": r.unattributed_source,
        "unattributed_reason": r.unattributed_reason,
        "debit_paise": r.debit_paise,
        "credit_paise": r.credit_paise,
        "balance_paise": r.balance_paise,
    }


def _envelope(at: str, account_id: str, b) -> dict:
    return {
        "as_of": at,
        "account_id": account_id,
        "rows": [_row(r) for r in b.rows],
        "attributed_paise": b.attributed_paise,
        "unattributed_paise": b.unattributed_paise,
        "total_paise": b.total_paise,
        "notes": b.notes,
    }


def _from_sql(at: str, account_id: str, out: dict) -> dict:
    """The SQL half returns the arithmetic; the REASONS are the domain
    module's, resolved here rather than restated in SQL — one authority for
    what a source kind means, so the two halves cannot disagree about it."""
    rows = []
    for r in out.get("rows") or []:
        src = r.get("unattributed_source") or None
        rows.append({
            "party_id": r.get("party_id"),
            "party_name": r.get("party_name") or "",
            "party_kind": r.get("party_kind"),
            "unattributed_source": src,
            "unattributed_reason": None if r.get("party_id") else rule.reason_for(src),
            "debit_paise": int(r.get("debit_paise") or 0),
            "credit_paise": int(r.get("credit_paise") or 0),
            "balance_paise": int(r.get("debit_paise") or 0) - int(r.get("credit_paise") or 0),
        })
    att, un = int(out.get("attributed_paise") or 0), int(out.get("unattributed_paise") or 0)
    notes = [rule.THE_PARTS_SUM_TO_THE_ACCOUNT]
    if any(r["unattributed_source"] == "bill_of_entry" for r in rows):
        notes.append(rule.BILL_OF_ENTRY_IS_NOT_A_PARTY)
    return {"as_of": at, "account_id": account_id, "rows": rows,
            "attributed_paise": att, "unattributed_paise": un,
            "total_paise": att + un, "notes": notes}
