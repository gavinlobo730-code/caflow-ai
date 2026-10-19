"""An income-tax return whose acknowledgement is recorded in the ITR workspace closes the ITR obligation it stands for.

WHAT WAS WRONG
    The ITR workspace records a filing (`itr_filings`) and the compliance calendar holds the obligation to file it
    (`compliance_records`, obligation type `ITR`, one per client per financial year). Recording an acknowledgement in the
    workspace moved the first and left the second at Not Started, so a client whose return was filed on 24 July showed
    Filed on the tax screen and Overdue on Deadlines, the Compliance tab and the firm dashboard. It is the same split the
    GST workspace had (POST-A-264), found the same way: by filing a seeded year through the product's own doors.

WHAT THIS DOES
    Once the acknowledgement is recorded it closes the matching obligation THROUGH `mark_filed` (see
    `services/obligation_closure`), with the filing date and the acknowledgement number the CA stated.

    THE OBLIGATION IS THE ONE FOR THE RETURN'S OWN FINANCIAL YEAR: same type, same first day and same last day. Nothing
    is inferred from the due date, which moves with an audit or a §92E report.

    Things it deliberately does not do, each said in the answer rather than silently:
      * only an ORIGINAL return closes the obligation. A revised return (§139(5)) or an updated return (§139(8A)) is a
        correction of something already furnished, so it neither opens nor closes an obligation of its own; if the
        original was filed outside this product the CA marks the obligation from Compliance;
      * it does not touch an obligation already Filed or Completed (its acknowledgement and date are the CA's);
      * it does not act for a caller without compliance access, because closing an obligation is a compliance write and
        approving a return is a different permission, decided per person;
      * it never fails the recording. The acknowledgement IS recorded; whatever stops the obligation closing is reported
        in the answer and to the error reporter, and the CA can still mark it from Compliance.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing the CA has already made on the portal. It transmits
    nothing.
"""
from __future__ import annotations

from typing import Any, Optional

from core.ist_clock import fy_bounds
from repositories.compliance_records_repository import compliance_records_repo
from services.obligation_closure import (
    ALREADY_FILED, FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, NOT_ON_THE_CALENDAR, answer, mark_filed_and_answer,
)

#: A revised or an updated return. Its own word, because it is neither a closure nor a failure to close.
NOT_THE_ORIGINAL = "not_the_original"

#: What the obligation is filed under on the calendar (`compliance_obligation_service._spec("ITR", "Income Tax", ...)`).
COMPLIANCE_TYPE = "Income Tax"
OBLIGATION_TYPE = "ITR"


def close_for_filed_return(
    *, firm_id: str, client_id: str, financial_year: str, return_type: Optional[str], filed_date: Optional[str],
    acknowledgement_number: Optional[str], actor: Optional[dict], may_write_compliance: bool,
) -> dict[str, Any]:
    """Close the client's ITR obligation for `financial_year`, if it should be, and say what became of it.

    Returns `{state, closed, obligation_id, message}`; the message is a sentence for the CA. Ordinary reasons (no
    obligation, already filed, not allowed, a correction rather than the original) are states, not exceptions. An
    unexpected failure reading the calendar propagates, and the router reports it without failing the recording.
    """
    if not firm_id or not client_id:
        return answer(NOT_CLOSED, "The ITR obligation was not matched: the return names no client.")
    if not may_write_compliance:
        return answer(NOT_ALLOWED, "Your access does not include Compliance, so the ITR obligation was left open. "
                                   "Someone with Compliance access can mark it filed there.")
    kind = str(return_type or "original").strip().lower() or "original"
    if kind != "original":
        return answer(NOT_THE_ORIGINAL, f"This is a {kind} return, which corrects one already furnished and closes no "
                                        "obligation of its own. If the original was filed outside this product, the "
                                        "obligation can be marked filed from Compliance.")
    try:
        start, end = fy_bounds(financial_year)
    except ValueError:
        return answer(NOT_CLOSED, f"The return's financial year ({financial_year!r}) is not one this can match to the "
                                  f"calendar, so the ITR obligation was left open. {FROM_COMPLIANCE}")
    what = f"ITR obligation for FY {financial_year}"

    matches = [r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                           compliance_type=COMPLIANCE_TYPE)
               if r.get("obligation_type") == OBLIGATION_TYPE
               and str(r.get("period_start") or "")[:10] == start
               and str(r.get("period_end") or "")[:10] == end]
    if not matches:
        return answer(NOT_ON_THE_CALENDAR, f"No {what} is on the compliance calendar, so none was closed.")
    open_ones = [r for r in matches if r.get("status") not in ("Filed", "Completed")]
    if not open_ones:
        return answer(ALREADY_FILED, f"The {what} was already recorded as filed, so it was left as it is.",
                      matches[0].get("id"))

    return mark_filed_and_answer(
        open_ones[0], what=what, operation="itr_return_closes_obligation.mark_filed", firm_id=firm_id,
        client_id=client_id, compliance_type=COMPLIANCE_TYPE, filed_date=filed_date, arn=acknowledgement_number,
        actor=actor)
