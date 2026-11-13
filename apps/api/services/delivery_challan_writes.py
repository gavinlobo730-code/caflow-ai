"""The three writes of a delivery challan that have to be one transaction, and the one door to the database functions that make them so (ledger POST-A-419, migration 585).

WHY THIS IS ONE MODULE
    A challan was written as several requests, each its own transaction: a header and then one request per line (a line that failed left a draft whose header totalled more than the lines it held),
    a lot of goods back and then, in a second request, the stamp that the challan was received back (a cancel in between left a lot on a challan not marked back, and two lots that each fitted the
    line and not together both passed the check), and a draft's corrections as the header's compare-and-set and then one request per line (a draft issued in the gap was left an issued challan whose
    HSN code had just changed). Migration 585 made each of the three a database function that takes the challan's lock first and writes everything in the transaction the call is. This module is
    the one place that calls them: the sales-cycle service and the ITC-04 service call these three functions and none of them writes a challan's lines, a lot or a draft's corrections itself
    (`tests/test_the_challan_writes_go_through_the_database_functions.py` holds that over the source, and holds the names and the parameters to the migration).

WHO CALLS THEM
    The functions are executable by the API's privileged client alone (migration 585 revokes EXECUTE from the signed-in roles, and says so in its own self-check), so every call goes through
    `privileged_for`, as the call to `replace_draft_document_lines` does.

WHAT IT DOES NOT DO
    It decides nothing the sales-cycle service or the ITC-04 service decides: the pre-checks that give the person a sentence (an unknown line, a day before the goods went, a lot more than the line has
    left, a correction that is not a description or an HSN code) stay where they were and run first. The database function asks the same things again at the moment of the write, and this module
    words the answer when it loses a race (a refusal the pre-check could not have made), in a sentence that says nothing was written.

THE ONE WRITE THAT IS NOT A FUNCTION. A challan's status and plain fields are still written by one statement (`update_challan`, `issue_challan`), and migration 585 put a trigger on the table that refuses a cancel
while a lot is recorded on the challan, so that a lot committed between the API's read and its write cannot leave a cancelled challan with goods returned on it. `amend` runs that statement and words the
trigger's refusal, so that a lost race is a 409 in the API's own sentence and not a database error.

THE CODES. The functions raise `P0001` with a word for a refusal a person can act on, `P0002` for a row that is not there, and `22023` for a call made wrongly (a caller bug, which is not worded: it
is raised and logged as it is). The words are read off the error's text, as `services/draft_document_lines` reads its own.
"""
from __future__ import annotations

from typing import Callable

from fastapi import HTTPException

from core.db_provider import privileged_for


def _text(error: Exception) -> str:
    return str(error)


def _is_a_taken_number(error: Exception) -> bool:
    """Whether a database error is the unique index on a challan's number refusing a second one (23505). PostgREST's error carries the code as `.code`, and its text carries it too as `'code': '23505'`: a bare
    substring of the whole text would also match a row id that happens to contain those digits."""
    return getattr(error, "code", None) == "23505" or "'code': '23505'" in _text(error) or "duplicate key value" in _text(error)


def _number_taken(document_no: object) -> HTTPException:
    return HTTPException(status_code=409, detail=f"{document_no} is already used by another document for this client. A serial number identifies one document.")


def create(db, header: dict, lines: list) -> dict:
    """Write a draft challan and every line of it in one transaction; the challan as stored.

    `header` names its firm and client; the function sets the challan's own id, firm and client on every line. A number already used by another challan of the client (two requests with one number
    that both passed the check that asks first) is the 409 that check gives."""
    try:
        made = privileged_for(db).rpc("create_delivery_challan_atomic", {"p_header": header, "p_lines": lines}).execute().data
    except Exception as e:  # noqa: BLE001
        if _is_a_taken_number(e):
            raise _number_taken(header.get("document_no")) from e
        raise
    return (made[0] if isinstance(made, list) and made else made) or {}


def record_lot(db, firm_id: str, client_id: str, challan_id: str, lot: dict, *, document_no: object) -> dict:
    """Record one lot of goods back from a job worker, and stamp the challan received back when it brings every line to nil, in one transaction.

    Returns `{"lot": <the row>, "challan_marked_received_back": bool, "received_back_on": <day or None>}`. The caller has judged the day (`delivery_challan.goods_back_problem`) and
    has asked, in words, everything the function asks again; what is worded here is a request that lost a race: the challan was cancelled or marked back, or another lot took the room, between
    that read and this write. Nothing is recorded in any of them."""
    try:
        got = privileged_for(db).rpc("record_challan_lot_atomic", {
            "p_firm_id": firm_id, "p_client_id": client_id, "p_challan_id": challan_id, "p_lot": lot}).execute().data
    except Exception as e:  # noqa: BLE001
        text = _text(e)
        if "challan_not_issued" in text:
            raise HTTPException(status_code=409, detail=(
                f"Challan {document_no} was changed by another request while this lot was being recorded, and is no longer an issued challan, so nothing was recorded. "
                "Reload the challan and look at its status.")) from e
        if "lot_exceeds_line" in text:
            raise HTTPException(status_code=409, detail=(
                f"Another lot was recorded against this line of challan {document_no} while this one was being recorded, so there is no longer room for it, and nothing was recorded. "
                "Reload the challan and look at what has come back.")) from e
        if "challan_not_job_work" in text:
            raise HTTPException(status_code=422, detail=(
                "Only goods sent for JOB WORK are returned on ITC-04. This challan was issued for another reason, whose own clock (if any) is stopped on the challan itself.")) from e
        if "challan_not_found" in text or "line_not_found" in text:
            raise HTTPException(status_code=404, detail="That challan line was not found for this client.") from e
        raise
    return (got[0] if isinstance(got, list) and got else got) or {}


def correct_draft(db, firm_id: str, client_id: str, challan_id: str, header: dict, fixes: list, *, document_no: object) -> int:
    """Write a draft's header fields and the description and HSN code of its lines together, in one transaction, held to a draft; the number of lines corrected.

    An absent key leaves the column and a present one writes it, null included. A challan that was issued or cancelled between the caller's read and this write is the 409 the caller's own
    compare-and-set gives (a draft's other amendments are last-write-wins, as they always were), and nothing is written."""
    try:
        done = privileged_for(db).rpc("correct_draft_challan_lines_atomic", {
            "p_firm_id": firm_id, "p_client_id": client_id, "p_challan_id": challan_id, "p_header": header, "p_fixes": fixes}).execute().data
    except Exception as e:  # noqa: BLE001
        text = _text(e)
        if "challan_not_draft" in text or "line_not_found" in text or "duplicate_fix" in text:
            raise HTTPException(status_code=409, detail=f"Challan {document_no} was changed while it was being amended. Reload it and look at its status.") from e
        if "challan_not_found" in text:
            raise HTTPException(status_code=404, detail="Delivery challan not found") from e
        if _is_a_taken_number(e) and header.get("document_no"):
            raise _number_taken(header.get("document_no")) from e
        raise
    return int(done or 0)


def amend(query, *, when_a_lot_stops_it: Callable[[], HTTPException], document_no: object = None):
    """Run `query` (an update of a challan's row, built by the caller and not yet executed) and return its answer; the trigger's refusal of a cancel while a lot is recorded (`challan_has_lots`) is the
    exception `when_a_lot_stops_it` makes, which the caller words from the lot the trigger found; a number another request just took (when the amendment renumbers the challan: `document_no`) is the
    duplicate sentence."""
    try:
        return query.execute()
    except Exception as e:  # noqa: BLE001
        if "challan_has_lots" in _text(e):
            raise when_a_lot_stops_it() from e
        if document_no and _is_a_taken_number(e):
            raise _number_taken(document_no) from e
        raise
