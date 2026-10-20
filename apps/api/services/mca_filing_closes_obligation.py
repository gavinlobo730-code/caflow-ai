"""An MCA filing recorded as filed in the MCA workspace closes the compliance obligation it stands for (POST-A-267).

WHAT WAS WRONG
    The MCA workspace records a filing (`mca_filings`: AOC-4, MGT-7, ADT-1 and the event forms) and the compliance
    calendar holds the obligation to file it (`compliance_records`, obligation types `MCA_AOC4` and `MCA_MGT7`, one per
    client per financial year). Recording the filing as filed moved the first and left the second at Not Started, so a
    company whose AOC-4 was filed on MCA21 in October showed Filed in the workspace and Overdue on Deadlines, the
    Compliance tab and the firm dashboard. The router did not mention `compliance_records` at all. It is the split the GST
    workspace (POST-A-264), the ITR workspace and the TDS statements had, and it is closed the same way.

WHAT THIS DOES
    Once the filing is recorded as filed it closes the matching obligation THROUGH `mark_filed` (see
    `services/obligation_closure`), with the date and the SRN the CA stated.

    THE OBLIGATION IS THE ONE FOR THE FILING'S OWN FORM AND FINANCIAL YEAR: the form's obligation type, and the year's
    own first and last day. Nothing is inferred from the due date, which moves with the AGM. The year is the filing's
    `financial_year`, or, only when that is blank, the `period` the firm-level screen writes ("FY 2025-26"); a filing
    whose `financial_year` is filled in but is not a year is not rescued by its period (`filing_year`).

    Things it deliberately does not do, each said in the answer rather than silently:
      * an EVENT form (DIR-12, INC-22, SH-7, CHG-1, CHG-4) has no obligation on the calendar, so there is nothing to close;
        the router does not ask about one, and a direct caller is told so;
      * an MGT-7A is matched to NO obligation, on purpose and said in the answer: whether it discharges the `MCA_MGT7`
        the calendar generates for every company is a reading nobody has confirmed (POST-C-209);
      * a filing with no stated date closes nothing. The date is a fact about MCA21 this product does not hold, and
        `mark_filed` would otherwise write today's, so it is asked for and not assumed. (`PUT .../complete` is the one
        route that stamps today on the FILING itself when none is given, so the calendar then carries the same date the
        filing does; the two cannot disagree, which is what the rule is for);
      * it does not close the obligation while another company of the same client still has this form to file: the
        obligation is per client and the filings are per company (`mca_companies` allows several per client), so closing
        it on the first would call the client filed with a company outstanding. Only ACTIVE companies count. A filing
        names its company by `company_id` or, failing that, by the CIN it carries (`company_cin`, which the firm-level
        screen writes); one that names neither, or whose CIN is none of the client's, cannot be placed among several, so
        it declines and says so. No screen offers a company choice on a new filing yet (the client tab's form sends none
        and the API stores none), so with several companies a filing made there is declined until the CA marks the
        obligation from Compliance;
      * it does not touch an obligation already Filed or Completed (its date and number are the CA's);
      * it does not act for a caller without compliance access, because closing an obligation is a compliance write and
        the MCA approval that got us here is a different permission, decided per person;
      * it never fails the recording. The filing IS recorded; whatever stops the obligation closing is reported in the
        answer and to the error reporter, and the CA can still mark it from Compliance;
      * a date earlier than the year the filing declares has ended is refused by `mark_filed` and said in the answer; the
        filing keeps the date the CA typed.
    Moving a filing back out of Filed does not reopen its obligation: that is a decision for the CA, and a closed
    obligation can only go on to Completed today (the reopening path is on the ledger).
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing the CA has already made on MCA21. It transmits
    nothing.
"""
from __future__ import annotations

import re
from typing import Any, Collection, Iterable, Optional, Sequence

from core.ist_clock import fy_bounds, normalise_fy_label
from repositories.compliance_records_repository import compliance_records_repo
from services.obligation_closure import (
    ALREADY_FILED, FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, NOT_ON_THE_CALENDAR, answer, mark_filed_and_answer,
)

#: The answer's `state`. The five shared words are `services.obligation_closure`'s; these three are the MCA ones.
AN_EVENT_FILING = "an_event_filing"
NOT_MATCHED_TO_AN_OBLIGATION = "not_matched_to_an_obligation"
WAITING_FOR_OTHER_COMPANIES = "waiting_for_other_companies"
WHICH_COMPANY_IS_UNKNOWN = "which_company_is_unknown"

#: What the obligation is filed under on the calendar (`compliance_obligation_service._roc_obligations`).
COMPLIANCE_TYPE = "MCA"

#: The annual form a filing is made on -> the obligation it discharges. ADT-1 is named in
#: `compliance_obligation_service.RETURN_OBLIGATION_TYPES` although nothing generates one yet, so a filing of it answers
#: "not on the calendar" until something does.
OBLIGATION_FOR_FORM = {"AOC-4": "MCA_AOC4", "MGT-7": "MCA_MGT7", "ADT-1": "MCA_ADT1"}


#: "2025-26", "2025-2026" or "FY 2025-26": the spellings a filing's year or period is written in.
_YEAR_SPELLING = re.compile(r"^\s*(?:FY\s*)?(\d{4}-\d{2}(?:\d{2})?)\s*$", re.IGNORECASE)


def _year_in(text: Any) -> Optional[str]:
    match = _YEAR_SPELLING.match(str(text or ""))
    if not match:
        return None
    try:
        return normalise_fy_label(match.group(1))
    except ValueError:
        return None


def filing_year(filing: dict) -> Optional[str]:
    """The financial year a filing declares, as `YYYY-YY`, or None.

    Its `financial_year`; and only when that is BLANK, the `period` ("FY 2025-26") that the firm-level MCA screen writes
    instead (it inserts the row itself and sets no `financial_year`; `services/filing_demo/mca._fy_bounds` reads the
    same pair). A `financial_year` that is filled in but is not a year answers None and is not rescued by the period: a
    filing that contradicts itself is not guessed at."""
    declared = filing.get("financial_year")
    if str(declared or "").strip():
        return _year_in(declared)
    return _year_in(filing.get("period"))


def company_of(filing: dict, companies: Sequence[dict]) -> Optional[str]:
    """The id of the company a filing is for, or None when it cannot be told.

    Its `company_id` when it has one. Otherwise its CIN (`company_cin`, then `cin`: the firm-level screen writes both
    and no company id) matched, case and space aside, to exactly one of the client's `companies`; a CIN that is none of
    theirs, or is shared by two, names nobody."""
    given = filing.get("company_id")
    if given:
        return str(given)
    # The first of the two columns that holds anything: a blank `company_cin` must not hide a CIN in `cin`.
    cin = next((c for c in (str(filing.get("company_cin") or "").strip(), str(filing.get("cin") or "").strip()) if c), "").upper()
    if not cin:
        return None
    held = [str(c.get("id")) for c in companies if str(c.get("cin") or "").strip().upper() == cin]
    return held[0] if len(held) == 1 else None


#: Annual forms the workspace records that NO obligation is matched to, on purpose: whether a filed MGT-7A discharges the
#: `MCA_MGT7` obligation the calendar generates for every company is a reading of the Companies Act and its Rules this
#: repository has not confirmed (POST-C-209), so it is not assumed in either direction. The screen that offers the form
#: is told so, in words, instead of saying nothing.
UNMATCHED_FORMS = frozenset({"MGT-7A"})


def has_an_obligation(form_type: Optional[str]) -> bool:
    """Whether a filing on this form stands for an obligation on the calendar at all (an event form does not)."""
    return form_type in OBLIGATION_FOR_FORM


def is_asked_about(form_type: Optional[str]) -> bool:
    """Whether the router asks this module about a filing on this form: the forms with an obligation, and the annual
    forms that are deliberately matched to none and say so. An event form is not asked about."""
    return form_type in OBLIGATION_FOR_FORM or form_type in UNMATCHED_FORMS


def companies_that_filed(filings: Iterable[dict], financial_year: Optional[str],
                         companies: Sequence[dict] = ()) -> set[str]:
    """The ids of the companies with a filing for `financial_year` among `filings` (rows of one form, already filtered
    to those recorded as filed). A row whose year is not a year, or whose company cannot be told (`company_of`), places
    no company."""
    try:
        wanted = normalise_fy_label(financial_year)
    except ValueError:
        return set()
    done: set[str] = set()
    for row in filings:
        company = company_of(row, companies)
        if company and filing_year(row) == wanted:
            done.add(company)
    return done


def close_for_filed_filing(
    *, firm_id: str, client_id: str, form_type: Optional[str], financial_year: Optional[str],
    company_id: Optional[str], filed_date: Optional[str], srn: Optional[str], actor: Optional[dict],
    may_write_compliance: bool, companies: Sequence[dict], filed_company_ids: Collection[str],
) -> dict[str, Any]:
    """Close the client's obligation for `form_type` and `financial_year`, if it should be, and say what became of it.

    `companies` are the client's ACTIVE companies (`id`, `company_name`) and `filed_company_ids` the ones with this form
    recorded as filed for the year (`companies_that_filed`), the filing just recorded included; the router reads both.
    Returns `{state, closed, obligation_id, message}`; the message is a sentence for the CA. Ordinary reasons (no
    obligation, already filed, not allowed, another company to wait for) are states, not exceptions. An unexpected
    failure reading the calendar propagates, and the router reports it without failing the recording.
    """
    if not firm_id or not client_id:
        return answer(NOT_CLOSED, "The MCA obligation was not matched: the filing names no client.")
    if form_type in UNMATCHED_FORMS:
        return answer(NOT_MATCHED_TO_AN_OBLIGATION,
                      f"The {form_type} filing is not matched to an obligation on the compliance calendar, so none was closed. If "
                      f"this company owes the MGT-7 obligation for the year, it stays open until it is marked filed from "
                      f"Compliance.")
    if not has_an_obligation(form_type):
        return answer(AN_EVENT_FILING, f"The {form_type or 'filing'} filing is an event filing, which has no obligation on "
                                       "the compliance calendar, so none was closed.")
    if not may_write_compliance:
        return answer(NOT_ALLOWED, f"Your access does not include Compliance, so the {form_type} obligation was left "
                                   "open. Someone with Compliance access can mark it filed there.")
    try:
        year = normalise_fy_label(financial_year)
        start, end = fy_bounds(year)
    except ValueError:
        return answer(NOT_CLOSED, f"The filing names no financial year this can match to the calendar, so the {form_type} "
                                  f"obligation was left open. {FROM_COMPLIANCE}")
    what = f"{form_type} obligation for FY {year}"
    if not (filed_date or "").strip():
        return answer(NOT_CLOSED, f"The filing has no filing date, so the {what} was left open: the date it was filed "
                                  f"on MCA21 is asked for, not assumed. {FROM_COMPLIANCE}")

    wanted = OBLIGATION_FOR_FORM[form_type]
    matches = [r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                           compliance_type=COMPLIANCE_TYPE)
               if r.get("obligation_type") == wanted
               and str(r.get("period_start") or "")[:10] == start
               and str(r.get("period_end") or "")[:10] == end]
    if not matches:
        return answer(NOT_ON_THE_CALENDAR, f"No {what} is on the compliance calendar, so none was closed.")
    open_ones = [r for r in matches if r.get("status") not in ("Filed", "Completed")]
    if not open_ones:
        return answer(ALREADY_FILED, f"The {what} was already recorded as filed, so it was left as it is.",
                      matches[0].get("id"))
    record = open_ones[0]

    if len(companies) > 1:
        ids = {str(c.get("id")) for c in companies}
        if not company_id or str(company_id) not in ids:
            return answer(
                WHICH_COMPANY_IS_UNKNOWN,
                f"This client has {len(companies)} companies and the filing is not linked to one of them, so which "
                f"company it stands for cannot be told and the {what} was left open. {FROM_COMPLIANCE}",
                record.get("id"))
        waiting = sorted(str(c.get("company_name") or c.get("cin") or c.get("id")) for c in companies
                         if str(c.get("id")) not in {str(i) for i in filed_company_ids})
        if waiting:
            return answer(
                WAITING_FOR_OTHER_COMPANIES,
                f"This client has {len(companies)} companies. The {what} stays open until "
                f"{', '.join(waiting)} {'has' if len(waiting) == 1 else 'have'} also filed it. {FROM_COMPLIANCE}",
                record.get("id"))

    return mark_filed_and_answer(
        record, what=what, operation="mca_filing_closes_obligation.mark_filed", firm_id=firm_id, client_id=client_id,
        compliance_type=COMPLIANCE_TYPE, filed_date=filed_date, arn=srn, actor=actor)
