"""Fetch the electronic credit ledger's opening balance for a return (gst-06).

`domain/gst/credit_ledger.py` is the rule and the reasoning. This module is the
three reads that feed it and the one write a CA makes, and it decides nothing
about which balance wins.

WHAT IT READS
    * ONE `gst_credit_ledger_openings` row — what a CA keyed from the portal for
      exactly this registration and window.
    * ONE `gstr3b_returns` row — the return whose `credit_closing_as_of` is the
      day BEFORE this window starts, for the same GSTIN. An exact date match,
      never "the latest earlier period": a registration that moves between
      monthly and quarterly filing would otherwise skip or repeat a month, and a
      gap (a month nobody saved) would silently chain across it.

A READ THAT FAILS IS `unreadable`, NEVER "NOT RECORDED". Both set the arithmetic
off against nil and both say so, but they send a person to different places: one
to key a balance, the other to try again. `opening_for` therefore never raises —
a failure to read an opening must not stop a CA preparing a return, and must not
read as a clean nil either.

THE WRITE IS A STATEMENT OF FACT ABOUT THE PORTAL, and is refused for a window
whose GSTR-3B is already filed. A filed return recorded the opening it was
computed with; changing the keyed figure afterwards would leave the table
disagreeing with a return nobody can revise (CGST s.39 with s.37). A
correction belongs in the NEXT window's opening.

# CA REVIEW REQUIRED — a keyed balance changes the cash figure on a return. It
# files nothing and posts nothing.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from core.observability import capture_soft_failure
from domain.gst import credit_ledger as ledger
from domain.gst.credit_ledger import CreditBalance, OpeningCredit

_logger = logging.getLogger("caflow.gst_credit_ledger")


def _day_before(window_start: str) -> str:
    return (date.fromisoformat(window_start) - timedelta(days=1)).isoformat()


def previous_closing(db, firm_id: str, client_id: str, gstin: str,
                     window_start: str) -> Optional[ledger.PreviousClosing]:
    """The credit the return ending the day before `window_start` left behind.

    None where no such return exists or it predates closing balances being
    recorded — which the caller reads as "no chain", not as nil.
    """
    as_of = _day_before(window_start)
    rows = (db.table("gstr3b_returns")
            .select("id, period, status, updated_at, credit_closing_as_of, "
                    "credit_closing_igst_paise, credit_closing_cgst_paise, "
                    "credit_closing_sgst_paise, credit_closing_cess_paise")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("gstin", gstin).eq("credit_closing_as_of", as_of)
            .limit(5).execute().data) or []
    usable = []
    for r in rows:
        bal = CreditBalance.from_columns(r, "credit_closing")
        if bal is not None:
            usable.append((r, bal))
    if not usable:
        return None
    # Two returns can only share a window end if one is monthly and one
    # quarterly for the same registration, which the (client, period, gstin)
    # key allows and no registration does. Prefer a filed one, then the latest
    # saved, so the answer is deterministic rather than arbitrary.
    usable.sort(key=lambda rb: ((rb[0].get("status") or "") == "submitted",
                                str(rb[0].get("updated_at") or "")),
                reverse=True)
    row, bal = usable[0]
    return ledger.PreviousClosing(balance=bal, period=str(row.get("period") or ""),
                                  status=str(row.get("status") or "draft"),
                                  as_of=as_of)


def recorded_opening(db, firm_id: str, client_id: str, gstin: str,
                     window_start: str) -> Optional[ledger.RecordedOpening]:
    rows = (db.table("gst_credit_ledger_openings")
            .select("id, igst_paise, cgst_paise, sgst_paise, cess_paise, note, updated_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("gstin", gstin).eq("window_start", window_start)
            .limit(1).execute().data) or []
    if not rows:
        return None
    r = rows[0]
    return ledger.RecordedOpening(
        balance=CreditBalance(int(r.get("igst_paise") or 0), int(r.get("cgst_paise") or 0),
                              int(r.get("sgst_paise") or 0), int(r.get("cess_paise") or 0)),
        note=r.get("note"),
        recorded_at=str(r.get("updated_at") or "") or None)


def opening_for(db, firm_id: str, client_id: str, gstin: str,
                window_start: str) -> OpeningCredit:
    """The opening balance for one registration's return window. Never raises."""
    try:
        return ledger.resolve_opening(
            window_start=window_start,
            previous=previous_closing(db, firm_id, client_id, gstin, window_start),
            recorded=recorded_opening(db, firm_id, client_id, gstin, window_start))
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="gstr3b.credit_ledger_opening",
                             firm_id=firm_id, client_id=client_id)
        return ledger.unreadable(window_start)


def window_is_filed(db, firm_id: str, client_id: str, gstin: str,
                    period_key: str) -> bool:
    """Is there a SUBMITTED GSTR-3B for this registration's window?"""
    rows = (db.table("gstr3b_returns").select("id, status")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("gstin", gstin).eq("period", period_key)
            .eq("status", "submitted").limit(1).execute().data) or []
    return bool(rows)


def record_opening(db, *, firm_id: str, client_id: str, gstin: str,
                   window_start: str, balance: CreditBalance,
                   note: Optional[str], recorded_by: Optional[str]) -> dict:
    """Key (or re-key) the portal's balance for one window.

    `db` must be the SERVICE client: `authenticated` has SELECT only on the
    table, so the one door that writes it is this route after `rbac` and
    `assert_client_access` have run. `recorded_by` is the INTERNAL user id
    (`created_by` / `posted_by` FK `public.users.id`).
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = (db.table("gst_credit_ledger_openings").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("gstin", gstin).eq("window_start", window_start)
                .limit(1).execute().data) or []
    if existing:
        row_id = existing[0]["id"]
        db.table("gst_credit_ledger_openings").update({
            "igst_paise": balance.igst_paise, "cgst_paise": balance.cgst_paise,
            "sgst_paise": balance.sgst_paise, "cess_paise": balance.cess_paise,
            "note": note, "recorded_by": recorded_by, "updated_at": now,
        }).eq("id", row_id).eq("firm_id", firm_id).execute()
        return {"id": row_id, "created": False}
    inserted = db.table("gst_credit_ledger_openings").insert({
        "firm_id": firm_id, "client_id": client_id, "gstin": gstin,
        "window_start": window_start,
        "igst_paise": balance.igst_paise, "cgst_paise": balance.cgst_paise,
        "sgst_paise": balance.sgst_paise, "cess_paise": balance.cess_paise,
        "note": note, "recorded_by": recorded_by,
    }).execute().data or []
    return {"id": (inserted[0].get("id") if inserted else None), "created": True}


def clear_opening(db, *, firm_id: str, client_id: str, gstin: str,
                  window_start: str) -> bool:
    """Take a keyed balance back. True where one existed.

    Removing it hands the window back to the chain (or to "not recorded") — it
    never means "the ledger was nil", which is a different statement and is
    made by keying a nil balance.
    """
    rows = (db.table("gst_credit_ledger_openings").select("id")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("gstin", gstin).eq("window_start", window_start)
            .limit(1).execute().data) or []
    if not rows:
        return False
    (db.table("gst_credit_ledger_openings").delete()
     .eq("id", rows[0]["id"]).eq("firm_id", firm_id).execute())
    return True
