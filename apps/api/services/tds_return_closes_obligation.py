"""A TDS statement recorded as filed in the TDS workspace closes the quarterly obligation it stands for.

WHAT WAS WRONG
    The TDS workspace records a statement (`tds_returns`: one row per client, form and quarter) and the compliance calendar
    holds the obligation to furnish it (`compliance_records`, obligation type TDS24Q, TDS26Q or TDS27Q, one per client per
    quarter). Recording the PRN in the workspace moved the first and left the second at Not Started, so a quarter filed on
    28 October read Filed on the TDS screen and Overdue on Deadlines, the Compliance tab and the firm dashboard. It is the
    split the GST workspace (POST-A-264) and the ITR workspace had, found the same way; it is the third workspace closed,
    and POST-A-267 lists what remains.

WHAT THIS DOES
    Once the PRN is recorded it closes the matching obligation THROUGH `mark_filed` (see `services/obligation_closure`),
    with the filing date and the PRN the CA stated.

    THE OBLIGATION IS THE ONE FOR THE STATEMENT'S OWN QUARTER: same obligation type, same first day and same last day,
    both from `domain/tds/section_rates.quarter_dates`, the one quarterly calendar the due dates and the stored
    `quarter_end` already read. Nothing is inferred from the due date.

    The statement's routing key (`24Q`, `26Q`, `27Q`, `27EQ`) is NOT the Act's form number, which changes from FY 2026-27
    (`domain/tds/vocabulary`), and the obligation's type code is a stable internal key for the same reason
    (`compliance_obligation_service._tds_obligations`). Both are keyed on the routing key, so neither moves with the Act.

    The sentences name the statement the way the calendar's own title does (`vocabulary_for(fy).statement(kind)`: 26Q up to
    FY 2025-26, 140 from FY 2026-27), so a CA reading "TDS 140 Q1 FY 2026-27" is told about the obligation they see.

    Things it deliberately does not do, each said in the answer rather than silently:
      * Form 27EQ (tax collected at source) has no obligation on the calendar, so nothing is closed for it;
      * the monthly DEPOSIT obligations (`TDS_NON_SALARY_DEPOSIT`, `TDS_SALARY_DEPOSIT`) are not closed by a statement: a
        statement reports the deposits, it is not one, and a month can carry several challans under several sections;
      * it does not touch an obligation already Filed or Completed (its PRN and date are the CA's);
      * it does not act for a caller without compliance access, because closing an obligation is a compliance write and
        approving a return is a different permission, decided per person;
      * it never fails the recording. The PRN IS recorded; whatever stops the obligation closing is reported in the answer
        and to the error reporter, and the CA can still mark it from Compliance.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing the CA has already made on the portal. It transmits
    nothing.
"""
from __future__ import annotations

from typing import Any, Optional

from domain.tds import vocabulary
from domain.tds.section_rates import quarter_dates
from repositories.compliance_records_repository import compliance_records_repo
from services.obligation_closure import (
    ALREADY_FILED, FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, NOT_ON_THE_CALENDAR, answer, mark_filed_and_answer,
)

#: What the obligations are filed under on the calendar (`compliance_obligation_service._spec("TDS26Q", "TDS", ...)`).
COMPLIANCE_TYPE = "TDS"

#: The statement's routing key (`tds_returns.return_type`) to the obligation's stable type code. Pinned to the generator by
#: a test, so a code renamed there cannot leave this closing nothing.
OBLIGATION_FOR_STATEMENT = {"24Q": "TDS24Q", "26Q": "TDS26Q", "27Q": "TDS27Q"}

#: The statement's routing key to the vocabulary's kind, which names the form the PERIOD's Act uses. 27EQ is here for the
#: sentence that says it has no obligation; it is not in `OBLIGATION_FOR_STATEMENT`.
_KIND = {"24Q": vocabulary.SALARY, "26Q": vocabulary.RESIDENT_NON_SALARY, "27Q": vocabulary.NON_RESIDENT,
         "27EQ": vocabulary.TCS}


def _form(statement: str, financial_year: Optional[str]) -> str:
    """The form number the period's own Act gives this statement, or the routing key when the year cannot place it."""
    try:
        return vocabulary.vocabulary_for(str(financial_year or "")).statement(_KIND[statement])
    except (ValueError, KeyError):
        return statement


def close_for_filed_return(
    *, firm_id: str, client_id: str, return_type: Optional[str], quarter: Optional[str], financial_year: Optional[str],
    filed_date: Optional[str], prn: Optional[str], actor: Optional[dict], may_write_compliance: bool,
) -> dict[str, Any]:
    """Close the client's obligation for this statement and quarter, if it should be, and say what became of it.

    Returns `{state, closed, obligation_id, message}`; the message is a sentence for the CA. Ordinary reasons (no
    obligation, already filed, not allowed) are states, not exceptions. An unexpected failure reading the calendar
    propagates, and the router reports it without failing the recording.
    """
    if not firm_id or not client_id:
        return answer(NOT_CLOSED, "The TDS obligation was not matched: the return names no client.")
    if not may_write_compliance:
        return answer(NOT_ALLOWED, "Your access does not include Compliance, so the TDS obligation was left open. "
                                   "Someone with Compliance access can mark it filed there.")
    statement = str(return_type or "").strip().upper()
    if statement not in OBLIGATION_FOR_STATEMENT:
        form = _form(statement, financial_year) if statement in _KIND else (statement or "(none)")
        return answer(NOT_ON_THE_CALENDAR, f"The compliance calendar carries no obligation for Form {form}, so none was "
                                           "closed.")
    try:
        start, end, _due = quarter_dates(str(financial_year or ""), str(quarter or ""))
    except (ValueError, TypeError):
        return answer(NOT_CLOSED, f"The return's period ({quarter!r}, FY {financial_year!r}) is not one this can match to "
                                  f"the calendar, so the TDS obligation was left open. {FROM_COMPLIANCE}")
    what = f"TDS {_form(statement, financial_year)} {quarter} FY {financial_year} obligation"
    kind = OBLIGATION_FOR_STATEMENT[statement]

    matches = [r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                           compliance_type=COMPLIANCE_TYPE)
               if r.get("obligation_type") == kind
               and str(r.get("period_start") or "")[:10] == start
               and str(r.get("period_end") or "")[:10] == end]
    if not matches:
        return answer(NOT_ON_THE_CALENDAR, f"No {what} is on the compliance calendar, so none was closed.")
    open_ones = [r for r in matches if r.get("status") not in ("Filed", "Completed")]
    if not open_ones:
        return answer(ALREADY_FILED, f"The {what} was already recorded as filed, so it was left as it is.",
                      matches[0].get("id"))

    return mark_filed_and_answer(
        open_ones[0], what=what, operation="tds_return_closes_obligation.mark_filed", firm_id=firm_id,
        client_id=client_id, compliance_type=COMPLIANCE_TYPE, filed_date=filed_date, arn=prn, actor=actor)
