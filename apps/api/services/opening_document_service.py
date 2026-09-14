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

