"""Opening documents — the bill-wise breakup of an opening balance (ACC-14).

`domain/accounting/opening_documents.py` is the rule; this fetches its inputs
and writes. Nothing here decides what an opening document may be, what it must
carry or how the reconciliation reads.

WHY THERE IS NO JOURNAL CALL IN THIS FILE
    There is deliberately no posting path. `opening_balance_service` already
    brings the client's opening AR and AP into the ledger as aggregates from
    `customers.opening_balance_paise` / `vendors.opening_balance_paise`, and a
    document that posted its own leg would put the same receivable in twice.
    Migration 391's header records why moving the source instead is a larger
    change than it looks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.accounting import opening_documents as od

_logger = logging.getLogger("caflow.opening_documents")

#: Every column the reconciliation and the screen read back. Named once so a
#: read that omits one cannot hand the rule a default it did not mean.
INVOICE_COLUMNS = (
    "id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date, "
    "total_paise, paid_paise, outstanding_paise, status, notes, is_opening, "
    "deleted_at"
)
BILL_COLUMNS = (
    "id, firm_id, client_id, vendor_id, bill_no, our_reference, bill_date, "
    "due_date, total_paise, net_payable_paise, paid_paise, outstanding_paise, "
    "status, is_opening, deleted_at"
)


def _invoices(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("client_sales_invoices").select(
            "id, firm_id, client_id, customer_id, invoice_no, invoice_date, "
            "due_date, total_paise, paid_paise, outstanding_paise, status, "
            "notes, is_opening, deleted_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("is_opening", True).is_("deleted_at", "null"),
        key="id", label="opening_invoices")


def _bills(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("purchase_bills").select(
            "id, firm_id, client_id, vendor_id, bill_no, our_reference, "
            "bill_date, due_date, total_paise, net_payable_paise, paid_paise, "
            "outstanding_paise, status, is_opening, deleted_at")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("is_opening", True).is_("deleted_at", "null"),
        key="id", label="opening_bills")


def _customers(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("customers").select("id, name, opening_balance_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="opening_customers")


def _vendors(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(
        lambda: db.table("vendors").select("id, name, opening_balance_paise")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        key="id", label="opening_vendors")


def _documents(db, firm_id: str, client_id: str, kind: str) -> list[dict]:
    return (_invoices(db, firm_id, client_id) if kind == od.RECEIVABLE
            else _bills(db, firm_id, client_id))


def _parties(db, firm_id: str, client_id: str, kind: str) -> list[dict]:
    return (_customers(db, firm_id, client_id) if kind == od.RECEIVABLE
            else _vendors(db, firm_id, client_id))


def _as_listing(row: dict, kind: str) -> dict:
    """One shape for both kinds, so the screen holds one table."""
    return {
        "id": row.get("id"),
        "kind": kind,
        "party_id": row.get(od.PARTY_COLUMN[kind]),
        "document_no": row.get(od.NUMBER_COLUMN[kind]),
        "document_date": str(row.get(od.DATE_COLUMN[kind]) or "")[:10] or None,
        "due_date": str(row.get("due_date"))[:10] if row.get("due_date") else None,
        "total_paise": int(row.get("total_paise") or 0),
        "paid_paise": int(row.get("paid_paise") or 0),
        "outstanding_paise": int(row.get("outstanding_paise") or 0),
        "status": row.get("status"),
    }


def listing(db, firm_id: str, client_id: str, kind: str) -> dict:
    """Every opening document of one kind, with the reconciliation beside it.

    The two travel together on purpose: a list of documents without the figure
    they are supposed to add up to is what lets an ageing schedule quietly stop
    footing to its own control account.
    """
    if kind not in od.KINDS:
        raise HTTPException(status_code=422,
                            detail=f"{kind!r} is not an opening document kind.")
    docs = _documents(db, firm_id, client_id, kind)
    parties = _parties(db, firm_id, client_id, kind)
    names = {p["id"]: p.get("name") for p in parties if p.get("id")}
    recs = od.reconcile(parties, docs, kind=kind)
    rows = [_as_listing(d, kind) for d in docs]
    for r in rows:
        r["party_name"] = names.get(r["party_id"])
    rows.sort(key=lambda r: (r.get("document_date") or "", r.get("document_no") or ""))
    return {
        "kind": kind,
        "documents": rows,
        "documents_paise": sum(r["outstanding_paise"] for r in rows),
        "opening_balance_paise": sum(int(p.get("opening_balance_paise") or 0)
                                     for p in parties),
        "reconciliation": [
            {
                "party_id": r.party_id,
                "party_name": r.party_name or names.get(r.party_id),
                "opening_balance_paise": r.opening_balance_paise,
                "documents_paise": r.documents_paise,
                "document_count": r.document_count,
                "difference_paise": r.difference_paise,
                "agrees": r.agrees,
                "sentence": r.sentence,
            }
            for r in recs
        ],
        "unreconciled_parties": sum(1 for r in recs if not r.agrees),
    }


def create(db, firm_id: str, client_id: str, *, kind: str, party_id: str,
           document_no: str, document_date: str, due_date: Optional[str],
           outstanding_paise: int, notes: Optional[str] = None,
           actor_id: Optional[str] = None) -> dict:
    """Record one opening document."""
    refusal = od.problem_with(
        kind=kind, party_id=party_id, document_no=document_no,
        document_date=document_date, due_date=due_date,
        outstanding_paise=outstanding_paise)
    if not refusal.ok:
        raise HTTPException(status_code=422, detail=" ".join(refusal.reasons))

    # The party has to be THIS client's. `client_sales_invoices.customer_id` is
    # a bare FK to `customers(id)`, so without this a document could be filed
    # against another client's customer and then age on this client's schedule.
    if kind == od.RECEIVABLE:
        party = (db.table("customers").select("id, name")
                 .eq("id", party_id).eq("firm_id", firm_id)
                 .eq("client_id", client_id).limit(1).execute().data) or []
    else:
        party = (db.table("vendors").select("id, name")
                 .eq("id", party_id).eq("firm_id", firm_id)
                 .eq("client_id", client_id).limit(1).execute().data) or []
    if not party:
        raise HTTPException(
            status_code=404,
            detail="That party is not recorded against this client.")

    row = od.row_for(
        kind=kind, firm_id=firm_id, client_id=client_id, party_id=party_id,
        document_no=document_no, document_date=document_date,
        due_date=due_date, outstanding_paise=int(outstanding_paise),
        notes=notes)
    if actor_id and kind == od.RECEIVABLE:
        row["created_by"] = actor_id

    if kind == od.RECEIVABLE:
        written = (db.table("client_sales_invoices").insert(row)
                   .execute().data) or []
    else:
        written = (db.table("purchase_bills").insert(row).execute().data) or []
    out = written[0] if written else row
    return _as_listing(out, kind) | {"party_name": party[0].get("name")}


def remove(db, firm_id: str, client_id: str, *, kind: str,
           document_id: str) -> dict:
    """Soft-delete an opening document.

    REFUSED once anything has been settled against it: the receipt or payment
    that settled it has already relieved the control account, and removing the
    document would leave that relief with nothing behind it. Only an opening
    document may be removed here at all — the check is on `is_opening`, so this
    endpoint can never reach an ordinary invoice or bill.
    """
    if kind not in od.KINDS:
        raise HTTPException(status_code=422,
                            detail=f"{kind!r} is not an opening document kind.")
    if kind == od.RECEIVABLE:
        rows = (db.table("client_sales_invoices").select(
            "id, is_opening, paid_paise, total_paise, invoice_no, deleted_at")
            .eq("id", document_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    else:
        rows = (db.table("purchase_bills").select(
            "id, is_opening, paid_paise, total_paise, bill_no, deleted_at")
            .eq("id", document_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    row = rows[0] if rows else None
    if not row or row.get("deleted_at") or not row.get("is_opening"):
        raise HTTPException(status_code=404, detail="Opening document not found.")
    if int(row.get("paid_paise") or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail=("Something has already been settled against this opening "
                    "document, and that settlement has relieved the control "
                    "account. Reverse the receipt or payment first."))

    # The payload is written INLINE at each call site rather than bound to a
    # local and reused: the column scan resolves no variable names, so a shared
    # `stamp` would make both writes invisible to it.
    now = datetime.now(timezone.utc).isoformat()
    if kind == od.RECEIVABLE:
        (db.table("client_sales_invoices").update({"deleted_at": now})
         .eq("id", document_id).eq("firm_id", firm_id).execute())
    else:
        (db.table("purchase_bills").update({"deleted_at": now})
         .eq("id", document_id).eq("firm_id", firm_id).execute())
    return {"id": document_id, "deleted": True}


# ── Bulk import (accounting-05) ─────────────────────────────────────────────────────
#
# `domain/accounting/opening_document_import` is the rule and decides what each
# row IS; everything below fetches its inputs, writes what it called new, and
# reports. The module header there carries the argument for the shape (judge
# every row, name each bad one, land the good ones, a re-upload creates nothing).

_INSERT_CHUNK = 100


def _import_parties(db, firm_id: str, client_id: str, kind: str) -> list[dict]:
    """The client's live customers or vendors, with the GSTIN a row may name."""
    if kind == od.RECEIVABLE:
        rows = fetch_all(
            lambda: db.table("customers")
            .select("id, name, gstin, opening_balance_paise, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id),
            key="id", label="opening_import_customers")
    else:
        rows = fetch_all(
            lambda: db.table("vendors")
            .select("id, name, gstin, opening_balance_paise, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id),
            key="id", label="opening_import_vendors")
    # An archived party is not a party a new document should be filed against,
    # and leaving it in would make a live party "ambiguous" with its own
    # archived namesake. Absent `is_active` reads as live (an in-memory double).
    return [r for r in rows if r.get("is_active", True)]


def _existing_for_import(db, firm_id: str, client_id: str, kind: str,
                         numbers: list[str], party_ids: list[str]) -> list[dict]:
    """Every live document that could share a key with a row in the file.

    A SALES number is unique per client whoever it belongs to, so those are
    fetched by number. A PURCHASE number is unique per vendor and compared
    without case, which PostgREST cannot filter on, so the bills of the vendors
    the file names are read and compared here — bounded by those vendors and by
    live, uncancelled bills, which is the population the unique index covers.
    """
    out: list[dict] = []
    if kind == od.RECEIVABLE:
        for i in range(0, len(numbers), _INSERT_CHUNK):
            chunk = numbers[i:i + _INSERT_CHUNK]
            out.extend(fetch_all(
                lambda chunk=chunk: db.table("client_sales_invoices")
                .select("id, invoice_no, customer_id, is_opening, total_paise, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("invoice_no", chunk).is_("deleted_at", "null"),
                key="id", label="opening_import_existing_invoices"))
    else:
        for i in range(0, len(party_ids), _INSERT_CHUNK):
            chunk = party_ids[i:i + _INSERT_CHUNK]
            out.extend(fetch_all(
                lambda chunk=chunk: db.table("purchase_bills")
                .select("id, bill_no, vendor_id, is_opening, total_paise, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("vendor_id", chunk).is_("deleted_at", "null")
                .neq("status", "cancelled"),
                key="id", label="opening_import_existing_bills"))
    return out


def _write_receivables(db, firm_id: str, client_id: str, verdicts: list,
                       actor_id: Optional[str]) -> list[dict]:
    """INSERT opening invoices in ONE statement, so the batch is atomic.

    The columns are written out LITERALLY, here, rather than through
    `od.row_for`: a payload built in a function this scanner cannot see makes the
    write invisible to `test_backend_columns_exist_pg` and to the NOT NULL check,
    and both budgets say to write the payload inline rather than raise them.
    `row_for` stays the definition — `tests/test_bulk_opening_documents.py` asserts
    these keys are exactly its keys, so the two cannot drift.
    """
    return (db.table("client_sales_invoices").insert([
        {
            "firm_id": firm_id,
            "client_id": client_id,
            "customer_id": v.party_id,
            "invoice_no": v.document_no,
            "invoice_date": v.document_date,
            "due_date": v.due_date,
            "taxable_amount_paise": 0,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 0,
            "total_gst_paise": 0,
            "total_paise": v.outstanding_paise,
            "status": od.OPEN_STATUS[od.RECEIVABLE],
            "is_opening": True,
            "notes": v.notes,
            "is_interstate": False,
            "created_by": actor_id,
        } for v in verdicts]).execute().data) or []


def _write_payables(db, firm_id: str, client_id: str, verdicts: list) -> list[dict]:
    """The purchase side of `_write_receivables`, for the same reasons.

    `net_payable_paise` is written alongside `total_paise` because migration 278
    generates `outstanding_paise` from it on this table — writing only the total
    would leave every opening bill outstanding at nil, invisible to AP ageing.
    """
    return (db.table("purchase_bills").insert([
        {
            "firm_id": firm_id,
            "client_id": client_id,
            "vendor_id": v.party_id,
            "bill_no": v.document_no,
            "bill_date": v.document_date,
            "due_date": v.due_date,
            "taxable_amount_paise": 0,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 0,
            "total_gst_paise": 0,
            "total_paise": v.outstanding_paise,
            "status": od.OPEN_STATUS[od.PAYABLE],
            "is_opening": True,
            "tds_paise": 0,
            "tds_rate_bps": 0,
            "net_payable_paise": v.outstanding_paise,
            "our_reference": v.notes,
        } for v in verdicts]).execute().data) or []


def _write(db, firm_id, client_id, kind, verdicts, actor_id):
    if kind == od.RECEIVABLE:
        return _write_receivables(db, firm_id, client_id, verdicts, actor_id)
    return _write_payables(db, firm_id, client_id, verdicts)


def bulk_create(db, firm_id: str, client_id: str, *, kind: str, rows: list,
                actor_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """Judge every row, write the new ones, and say what happened to each.

    ATOMIC PER CHUNK, NAMED PER ROW. Up to `_INSERT_CHUNK` documents go in one
    statement, so a chunk is all-or-nothing in the database. If a chunk is
    refused — a race with another upload on a unique index is the realistic way
    — it is retried one document at a time, so the failure is attributed to the
    row that caused it and its neighbours still land. One bad row never costs the
    other two hundred and ninety-nine.

    `dry_run` runs the whole judgement and writes nothing, and its reconciliation
    is PROJECTED over what would be recorded, so the CA sees whether the parties
    will foot to their opening balances before committing.
    """
    from domain.accounting import opening_document_import as imp

    if kind not in od.KINDS:
        raise HTTPException(status_code=422,
                            detail=f"{kind!r} is not an opening document kind.")
    if not rows:
        raise HTTPException(status_code=422, detail="The file has no rows to import.")
    if len(rows) > imp.MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail=(f"{len(rows)} rows is more than one import takes "
                    f"({imp.MAX_ROWS}). Split the file by party or by date and "
                    f"upload the parts — a re-upload skips what is already in."))

    parties = _import_parties(db, firm_id, client_id, kind)
    numbers = sorted({(r.document_no or "").strip() for r in rows
                      if (r.document_no or "").strip()})
    party_ids = sorted({p["id"] for p in parties if p.get("id")})
    existing = _existing_for_import(db, firm_id, client_id, kind, numbers, party_ids)
    verdicts = imp.plan(kind, rows, parties, existing)

    new = [v for v in verdicts if v.status == imp.NEW]
    written_ids: dict[int, str] = {}
    failed: dict[int, str] = {}
    if new and not dry_run:
        from core.exceptions import document_failure_detail
        for i in range(0, len(new), _INSERT_CHUNK):
            chunk = new[i:i + _INSERT_CHUNK]
            try:
                got = _write(db, firm_id, client_id, kind, chunk, actor_id)
                for v, row in zip(chunk, got):
                    written_ids[v.row] = str(row.get("id") or "")
                continue
            except Exception as chunk_error:                    # noqa: BLE001
                _logger.warning("opening-document chunk of %d refused (%s); "
                                "retrying one at a time", len(chunk),
                                type(chunk_error).__name__)
            for v in chunk:
                try:
                    got = _write(db, firm_id, client_id, kind, [v], actor_id)
                    written_ids[v.row] = str((got[0] if got else {}).get("id") or "")
                except Exception as one_error:                  # noqa: BLE001
                    failed[v.row] = document_failure_detail(
                        one_error, action="record this opening document")

    results = []
    for v in verdicts:
        status, problems = v.status, list(v.problems)
        if v.row in failed:
            status, problems = imp.REJECTED, [failed[v.row]]
        results.append({
            "row": v.row,
            "document_no": v.document_no,
            "status": ("would_create" if dry_run and status == imp.NEW else status),
            "problems": problems,
            "party_name": v.party_name,
            "outstanding_paise": v.outstanding_paise,
            "id": written_ids.get(v.row) or v.existing_id,
        })

    summary = imp.summarise(
        [v if v.row not in failed else
         imp.Verdict(row=v.row, document_no=v.document_no, status=imp.REJECTED,
                     problems=(failed[v.row],)) for v in verdicts])

    # The reconciliation the CA is going to read — after the write, or, for a
    # dry run, as it WOULD stand. Both go through `od.reconcile`, the one rule.
    if dry_run:
        docs = _documents(db, firm_id, client_id, kind)
        docs = docs + [{od.PARTY_COLUMN[kind]: v.party_id,
                        "outstanding_paise": v.outstanding_paise}
                       for v in new]
        recs = od.reconcile(parties, docs, kind=kind)
    else:
        recs = od.reconcile(parties, _documents(db, firm_id, client_id, kind), kind=kind)
    names = {p["id"]: p.get("name") for p in parties if p.get("id")}

    return {
        "kind": kind,
        "dry_run": dry_run,
        "received": summary.received,
        "created": 0 if dry_run else summary.new,
        "would_create": summary.new if dry_run else 0,
        "already_recorded": summary.already_recorded,
        "rejected": summary.rejected,
        "created_paise": 0 if dry_run else summary.new_paise,
        "would_create_paise": summary.new_paise if dry_run else 0,
        "rows": results,
        "reconciliation": [
            {
                "party_id": r.party_id,
                "party_name": r.party_name or names.get(r.party_id),
                "opening_balance_paise": r.opening_balance_paise,
                "documents_paise": r.documents_paise,
                "document_count": r.document_count,
                "difference_paise": r.difference_paise,
                "agrees": r.agrees,
                "sentence": r.sentence,
            } for r in recs],
        "unreconciled_parties": sum(1 for r in recs if not r.agrees),
    }


def reconciliation(db, firm_id: str, client_id: str) -> dict:
    """Everything the Opening Balances screen shows, in one read.

    Both party sides AND the accounts opened twice — the trial-balance import
    and the master records post into separate journal families that never
    reconcile against each other, so a bank balance entered on the master and
    imported on the trial balance is posted twice with nothing saying so.
    """
    return {
        od.RECEIVABLE: listing(db, firm_id, client_id, od.RECEIVABLE),
        od.PAYABLE: listing(db, firm_id, client_id, od.PAYABLE),
        "double_openings": double_openings(db, firm_id, client_id),
    }

# ── The other double count ──────────────────────────────────────────────────

def _opening_family_net(db, firm_id: str, client_id: str,
                        source_type: str) -> dict[str, int]:
    """Net (debit − credit) paise per account across one opening journal family.

    The same read `opening_balance_service._current_opening_net` makes for its
    own family, parameterised by the family — because the whole point here is
    to compare the two.
    """
    entries = fetch_all(
        lambda: db.table("journal_entries").select("id, source_type, client_id")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("source_type", source_type).is_("deleted_at", "null"),
        key="id", label=f"opening_family.{source_type}")
    ids = [e["id"] for e in entries if e.get("id")]
    net: dict[str, int] = {}
    for i in range(0, len(ids), 200):
        lines = (db.table("journal_lines")
                 .select("account_id, debit_paise, credit_paise, journal_entry_id")
                 .in_("journal_entry_id", ids[i:i + 200]).execute().data) or []
        for l in lines:
            acc = l.get("account_id")
            if not acc:
                continue
            net[acc] = (net.get(acc, 0)
                        + int(l.get("debit_paise") or 0)
                        - int(l.get("credit_paise") or 0))
    return net


def double_openings(db, firm_id: str, client_id: str) -> list[dict]:
    """Accounts this client's opening position was posted into TWICE.

    `opening_balance_service` posts the masters; `trial_balance_import_service`
    posts an imported trial balance; the two families are deliberately separate
    and neither will ever correct the other. A CA who enters the bank opening
    balance on the bank master AND imports a trial balance carrying a Bank row
    opens the account twice, and nothing said so.
    """
    master = _opening_family_net(db, firm_id, client_id, od.MASTER_SOURCE)
    tb = _opening_family_net(db, firm_id, client_id, od.TRIAL_BALANCE_SOURCE)
    ids = sorted(set(master) | set(tb))
    names: dict[str, Optional[str]] = {}
    for i in range(0, len(ids), 200):
        rows = (db.table("chart_of_accounts").select("id, account_name")
                .in_("id", ids[i:i + 200]).execute().data) or []
        names.update({r["id"]: r.get("account_name") for r in rows if r.get("id")})
    return [
        {"account_id": d.account_id, "account_name": d.account_name,
         "master_paise": d.master_paise,
         "trial_balance_paise": d.trial_balance_paise,
         "sentence": d.sentence}
        for d in od.double_openings(master, tb, names)
    ]

