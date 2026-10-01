"""
Read the challans and returns FORM GST ITC-04 is derived from, and record a
return (GST-30).

`domain/gst/itc_04.py` is the rule and the reasoning. This module is the reads
and the one write, and it carries the same discipline as the rest of the sales
cycle:

  * EVERY READ AND WRITE CARRIES `.eq("firm_id", …)` — the service-role key
    bypasses RLS, so that filter is the isolation control and not a convenience;
  * EVERY SELECT LIST AND INSERT PAYLOAD IS WRITTEN OUT AT ITS CALL SITE, never
    shared through a name. `tests/test_backend_columns_exist_pg.py` resolves no
    variable and its budget of unreadable ones is exact, so a shared constant
    here is a select the schema check cannot see — on a brand-new table, where
    a typo survives longest;
  * NOTHING IS PAGED BY HAND (`core.db_paging`), and what crosses the wire is
    proportional to the ANSWER: one client's job-work challans for the year, the
    returns in it, and what is outstanding — read through the partial index
    migration 392 built for exactly that — rather than every challan the client
    ever raised.

IT POSTS NOTHING AND TOUCHES NO STOCK. A return of goods sent for job work is
not a supply and moves no journal; ITC-04 is furnished on the portal by the
principal. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all, fetch_all_in
from core.ist_clock import fy_bounds, ist_today
from domain.gst import delivery_challan as dc
from domain.gst import itc_04 as itc


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(str(r["id"]), r)
    return list(seen.values())


def _preceding_year_turnover(db, firm_id: str, client_id: str, fy_start: str) -> Optional[int]:
    """The aggregate turnover recorded for the PRECEDING financial year, or None.

    CONTEXT AND NOTHING ELSE. Rule 45(3)'s cadence turns on it AND on a limit
    this environment could not confirm, so it decides nothing here — see
    `itc_04_period`. None is a third state and is never 0: a client who turned
    over nothing and a client nobody recorded are different answers.
    """
    from services.client_gst_turnover_service import turnover_governing_period
    # NOT wrapped in a broad `except`: a failed read turned into None would say
    # "nobody recorded a turnover", which is a different fact from "the read
    # failed" — and the endpoint failing loudly is what the panel already words.
    return turnover_governing_period(db, firm_id, client_id, fy_start)


def statement(db, firm_id: str, client_id: str, financial_year: str,
              *, window: Optional[str] = None,
              as_at: Optional[date] = None) -> dict:
    """The ITC-04 working for one client and financial year.

    With no `window`, the windows of every reading are listed with how many rows
    each would carry — and NONE is chosen (see the domain module). With one, its
    Table 4 and Table 5A rows come back too. What is still outstanding, and the
    s.143 date for it, is always returned: it is a fact about today and not
    about a window.
    """
    as_at = as_at or ist_today()
    fy_start, fy_end = fy_bounds(financial_year)
    chosen = None
    if window:
        chosen = itc.find_window(financial_year, window)
        if chosen is None:
            raise ValueError(
                f"{window!r} is not a window of financial year {financial_year}. "
                "Use one of the keys listed under `readings`.")

    # 1. Job-work challans SENT in the year.
    in_year = fetch_all(
        lambda: db.table("delivery_challans").select(
            "id, document_no, document_date, reason, status, goods_kind, "
            "received_back_on, extended_to, consignee_name, consignee_gstin, "
            "place_of_supply, is_inter_state")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("reason", dc.REASON_JOB_WORK).in_("status", list(itc.SENT_STATUSES))
        .gte("document_date", fy_start).lte("document_date", fy_end),
        key="id", label="itc_04.challans")

    # 2. Returns that came back in the year (the challan may be an earlier year's).
    returns = fetch_all(
        lambda: db.table("delivery_challan_returns").select(
            "id, challan_id, challan_line_id, returned_on, quantity_returned, "
            "quantity_lost_or_wasted, job_worker_challan_no, job_worker_challan_date, "
            "nature_of_job_work")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .gte("returned_on", fy_start).lte("returned_on", fy_end),
        key="id", label="itc_04.returns")

    # 3. What is STILL OUT, whatever year it left in. The partial index from
    #    migration 392 (`idx_delivery_challans_outstanding`) is this predicate.
    outstanding = fetch_all(
        lambda: db.table("delivery_challans").select(
            "id, document_no, document_date, reason, status, goods_kind, "
            "received_back_on, extended_to, consignee_name, consignee_gstin, "
            "place_of_supply, is_inter_state")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("reason", dc.REASON_JOB_WORK).eq("status", "issued")
        .is_("received_back_on", "null")
        .lte("document_date", as_at.isoformat()),
        key="id", label="itc_04.outstanding")

    challans = _dedupe(in_year + outstanding)
    known = {str(c["id"]) for c in challans}

    # 4. The ORIGINAL challan of a return that is not already loaded.
    missing = {str(r["challan_id"]) for r in returns} - known
    if missing:
        challans = _dedupe(challans + fetch_all_in(
            lambda: db.table("delivery_challans").select(
                "id, document_no, document_date, reason, status, goods_kind, "
                "received_back_on, extended_to, consignee_name, consignee_gstin, "
                "place_of_supply, is_inter_state")
            .eq("firm_id", firm_id).eq("client_id", client_id),
            "id", missing, key="id", label="itc_04.original_challans"))

    # 5. Every return of an outstanding challan, whenever it came back.
    owed = {str(c["id"]) for c in outstanding}
    if owed:
        returns = _dedupe(returns + fetch_all_in(
            lambda: db.table("delivery_challan_returns").select(
                "id, challan_id, challan_line_id, returned_on, quantity_returned, "
                "quantity_lost_or_wasted, job_worker_challan_no, "
                "job_worker_challan_date, nature_of_job_work")
            .eq("firm_id", firm_id).eq("client_id", client_id),
            "challan_id", owed, key="id", label="itc_04.outstanding_returns"))

    lines = fetch_all_in(
        lambda: db.table("delivery_challan_lines").select(
            "id, challan_id, line_order, description, hsn_sac, quantity, unit, "
            "taxable_amount_paise, gst_rate_percent")
        .eq("firm_id", firm_id).eq("client_id", client_id),
        "challan_id", {str(c["id"]) for c in challans}, key="id",
        label="itc_04.lines")

    out = {
        "client_id": client_id,
        "financial_year": financial_year,
        "as_of": as_at.isoformat(),
        # BOTH READINGS, NEITHER CHOSEN. `decided` is False and stays False until
        # the limit is held; the recorded turnover is context, not an answer.
        "period": {
            **dc.itc_04_period(),
            "preceding_year_aato_paise": _preceding_year_turnover(
                db, firm_id, client_id, fy_start),
            "verified": itc.VERIFIED,
        },
        "readings": itc.window_counts(challans, lines, returns, financial_year),
        "selected_window": chosen.as_dict() if chosen else None,
        "table_4": None,
        "table_5a": None,
        "table_5b": {"derived": False, "reason": itc.TABLE_5B_NOT_DERIVED},
        "table_5c": {"derived": False, "reason": itc.TABLE_5C_NOT_DERIVED},
        # Still with the job worker TODAY, with the s.143 date for the balance.
        "outstanding": itc.balances(challans, lines, returns, as_at.isoformat()),
        "gaps": itc.statement_gaps(),
        "nothing_is_filed": True,
        "verified": itc.VERIFIED,
        "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    }
    if chosen is not None:
        out["table_4"] = itc.table_4(challans, lines, chosen)
        out["table_5a"] = itc.table_5a(challans, lines, returns, chosen)
    return out


def record_return(db, firm_id: str, client_id: str, challan_id: str, payload: dict,
                  actor_id: Optional[str] = None) -> dict:
    """Record one return of goods sent for job work.

    REFUSED, each in its own words and never clamped:
      * a line this client's challans do not hold (one fixed message — the
        response is not an existence oracle for another client's documents);
      * a challan that is not a job-work movement that has actually left
        (a draft has not, a cancelled one never did, and one already marked
        wholly received back has nothing left to return);
      * a date before the goods were sent, or in the future;
      * more than was sent — returned plus lost or wasted can never exceed the
        quantity on the line.

    When the returns have brought EVERY line of the challan back to nil it
    stamps `received_back_on` through the ONE existing write, so the legacy
    whole-challan door and this one stop the s.143 clock the same way.
    """
    not_found = HTTPException(status_code=404,
                              detail="That challan line was not found for this client.")
    ln = (db.table("delivery_challan_lines").select(
        "id, challan_id, quantity, description")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("id", payload["challan_line_id"]).limit(1).execute().data) or []
    # The path's challan must be the line's OWN: a mismatch is reported as the
    # same "not found" as a line that is not there, so neither is an oracle.
    if not ln or str(ln[0].get("challan_id")) != str(challan_id):
        raise not_found
    line = ln[0]
    ch = (db.table("delivery_challans").select(
        "id, client_id, document_no, document_date, reason, status, received_back_on")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("id", line["challan_id"]).limit(1).execute().data) or []
    if not ch:
        raise not_found
    challan = ch[0]

    if str(challan.get("reason")) != dc.REASON_JOB_WORK:
        raise HTTPException(status_code=422, detail=(
            "Only goods sent for JOB WORK are returned on ITC-04. This challan was "
            "issued for another reason, whose own clock (if any) is stopped on the "
            "challan itself."))
    if challan.get("received_back_on") or str(challan.get("status")) == "received_back":
        raise HTTPException(status_code=409, detail=(
            f"Challan {challan.get('document_no')} is marked wholly received back "
            "— there is nothing left on it to return."))
    if str(challan.get("status")) != "issued":
        raise HTTPException(status_code=409, detail=(
            f"Challan {challan.get('document_no')} is {challan.get('status')}: goods "
            "can only come back on a challan that has been issued."))

    returned_on = date.fromisoformat(str(payload["returned_on"])[:10])
    sent_on = date.fromisoformat(str(challan["document_date"])[:10])
    if returned_on < sent_on:
        raise HTTPException(status_code=422, detail=(
            f"The goods cannot have come back on {returned_on.isoformat()}, before "
            f"they were sent out on {sent_on.isoformat()}."))
    if returned_on > ist_today():
        raise HTTPException(status_code=422, detail=(
            "A return cannot be recorded for a date that has not happened. "
            "Record it when the goods are back."))

    already = (db.table("delivery_challan_returns").select(
        "id, quantity_returned, quantity_lost_or_wasted")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("challan_line_id", line["id"]).execute().data) or []
    sent = Decimal(str(line.get("quantity") or 0))
    back = sum((Decimal(str(r.get("quantity_returned") or 0)) for r in already), Decimal(0))
    lost = sum((Decimal(str(r.get("quantity_lost_or_wasted") or 0)) for r in already), Decimal(0))
    now_back = Decimal(str(payload.get("quantity_returned") or 0))
    now_lost = Decimal(str(payload.get("quantity_lost_or_wasted") or 0))
    room = sent - back - lost
    if now_back + now_lost > room:
        raise HTTPException(status_code=409, detail=(
            f"{line.get('description')}: {sent:.3f} were sent, {back:.3f} have come "
            f"back and {lost:.3f} are recorded lost or wasted, so at most {room:.3f} "
            f"more can be recorded. A return is refused rather than trimmed — the "
            f"quantity on the line is what the job worker was sent."))

    row = (db.table("delivery_challan_returns").insert({
        "firm_id": firm_id,
        "client_id": client_id,
        "challan_id": challan["id"],
        "challan_line_id": line["id"],
        "returned_on": returned_on.isoformat(),
        "quantity_returned": str(now_back),
        "quantity_lost_or_wasted": str(now_lost),
        "job_worker_challan_no": payload.get("job_worker_challan_no"),
        "job_worker_challan_date": payload.get("job_worker_challan_date"),
        "nature_of_job_work": payload.get("nature_of_job_work"),
        "notes": payload.get("notes"),
        "created_by": actor_id,
    }).execute().data or [{}])[0]

    # Has EVERY line of this challan now come back to nil? Then the clock stops,
    # by the same write the challan screen uses.
    stamped = False
    every_line = (db.table("delivery_challan_lines").select("id, quantity")
                  .eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("challan_id", challan["id"]).execute().data) or []
    all_returns = (db.table("delivery_challan_returns").select(
        "id, challan_line_id, quantity_returned, returned_on")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("challan_id", challan["id"]).execute().data) or []
    got: dict[str, Decimal] = {}
    for r in all_returns:
        got[str(r["challan_line_id"])] = got.get(str(r["challan_line_id"]), Decimal(0)) + Decimal(
            str(r.get("quantity_returned") or 0))
    if every_line and all(
            got.get(str(l["id"]), Decimal(0)) >= Decimal(str(l.get("quantity") or 0))
            for l in every_line):
        from services import sales_cycle_service
        last = max(str(r["returned_on"])[:10] for r in all_returns)
        sales_cycle_service.record_goods_back(db, firm_id, str(challan["id"]), last)
        stamped = True

    return {**row, "challan_marked_received_back": stamped}
