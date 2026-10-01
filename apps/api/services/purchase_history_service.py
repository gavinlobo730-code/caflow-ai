"""Fetches what `domain/purchases/bill_history` decides. It decides nothing itself.

WHAT IT READS, AND WHERE THE TENANT LINE IS DRAWN
    The RECEIVED bills of one supplier of one client of one firm, newest first,
    at most `HISTORY_BILLS` of them, and those bills' lines. Every query carries
    `firm_id` — the service-role key bypasses RLS, so the app-layer filter is the
    isolation control — and the bills query carries `client_id` and `vendor_id`
    as well. A supplier of ANOTHER client with the same GSTIN or the same name is
    a different `vendors` row and is never read: what one client's CA decided
    about a landlord is not evidence about how another client should book theirs,
    and the accounts are not even the same accounts.

    `purchase_bill_lines` carries NO `firm_id` and is scoped through its parent
    bill (naming the column would be PGRST204 and no read at all), so the tenant
    check happens at the parent: the line ids are asked for with `bill_id IN` the
    ids the firm-and-client-scoped bills query returned, and for nothing else.

WHAT COUNTS AS A DECISION
    A bill that has left DRAFT and has not been cancelled or deleted. A draft is
    unfinished and is the CA's second thoughts in progress; a cancelled bill was
    withdrawn. A carried-over opening bill is excluded too
    (`opening_documents.without_carried_over`): it was raised in the system the
    client migrated from, so its lines carry no coding and its ITC flag is the
    column's default rather than anybody's judgement — counting it would teach
    "eligible, every time" from nothing.

BOUNDED, AND PAGED WHERE IT HAS TO BE
    The bills are `HISTORY_BILLS` rows at most, a single request well under the
    PostgREST cap. Their lines are NOT bounded by that — a hundred bills of a
    dozen lines is more than a page — so they go through `fetch_all_in`, and the
    ids travel in chunks because a hundred uuids in one `.in_()` is the URL that
    stops being a query.

NOTHING HERE WRITES. The route is a GET, the result is a proposal, and the editor
applies a suggestion only when the CA clicks it.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all_in
from domain.accounting import opening_documents
from domain.purchases import bill_history

_logger = logging.getLogger("caflow.purchase_history")


def _vendor_section(db, firm_id: str, client_id: str, vendor_id: str) -> Optional[str]:
    rows = (db.table("vendors").select("id, tds_section")
            .eq("id", vendor_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute().data) or []
    if not rows:
        # The same sentence the bill-create path gives for a vendor that is not
        # this client's, so the status code is not an oracle for which ids exist.
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
    return rows[0].get("tds_section")


def _bills(db, firm_id: str, client_id: str, vendor_id: str) -> list[dict]:
    rows = (db.table("purchase_bills")
            .select("id, bill_date, status, tds_section, is_opening")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("vendor_id", vendor_id)
            .is_("deleted_at", "null")
            .neq("status", "cancelled").neq("status", "draft")
            .order("bill_date", desc=True).order("id", desc=True)
            .limit(bill_history.HISTORY_BILLS)
            .execute().data) or []
    return opening_documents.without_carried_over(rows)


def _lines(db, bills: list[dict]) -> list[dict]:
    if not bills:
        return []
    dates = {b["id"]: b.get("bill_date") for b in bills}

    def one_page():
        return db.table("purchase_bill_lines").select("id, bill_id, hsn_sac, expense_account_id, itc_eligible, blocked_credit_reason")

    rows = fetch_all_in(one_page, "bill_id", dates.keys(), label="purchase_history.lines")
    # Only lines whose parent is in the scoped set: `fetch_all_in` asked for
    # exactly those ids, and this is the belt for a source that ignores a filter.
    return [{**r, "bill_date": dates[r["bill_id"]]} for r in rows if r.get("bill_id") in dates]


def _usable_accounts(db, firm_id: str, client_id: str, lines: list[dict]) -> dict[str, str]:
    """id -> label for the accounts these lines used that THIS client can still
    post to: of this firm, active, and either the client's own or a firm-level
    account (`client_id IS NULL`), the same line migration 360 draws."""
    wanted = {str(ln["expense_account_id"]) for ln in lines if ln.get("expense_account_id")}
    if not wanted:
        return {}

    def one_page():
        return (db.table("chart_of_accounts")
                .select("id, account_code, account_name, client_id, is_active")
                .eq("firm_id", firm_id))

    out: dict[str, str] = {}
    for r in fetch_all_in(one_page, "id", wanted, label="purchase_history.accounts"):
        if r.get("is_active") is False:
            continue
        if r.get("client_id") not in (None, client_id):
            continue
        code = (r.get("account_code") or "").strip()
        name = (r.get("account_name") or "").strip()
        out[str(r["id"])] = f"{code} · {name}" if code and name else (name or code)
    return out


def vendor_history(db, firm_id: str, client_id: str, vendor_id: str,
                   hsns: Iterable[str] = ()) -> dict:
    """What this supplier's earlier bills say, for the editor to show.

    Raises 404 for a supplier that is not this client's and 422 for a request
    that names more HSN/SAC codes than a bill has lines.
    """
    wanted = sorted({bill_history.clean_hsn(h) for h in (hsns or []) if bill_history.clean_hsn(h)})
    if len(wanted) > bill_history.MAX_HSNS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {bill_history.MAX_HSNS} HSN/SAC codes can be asked about at once.")

    supplier_section = _vendor_section(db, firm_id, client_id, vendor_id)
    bills = _bills(db, firm_id, client_id, vendor_id)
    lines = _lines(db, bills)
    usable = _usable_accounts(db, firm_id, client_id, lines)
    out = bill_history.build(lines, bills, usable, wanted, supplier_section)
    out["checked"] = True
    return out
