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
        it declines and says so. Both screens that create a filing offer the client's active companies and send the one
        chosen (POST-A-291), and the API refuses a new filing that names no company when the client has several, so a
        filing that cannot be placed is now only an old row or one written another way;
      * it does not touch an obligation already Filed or Completed (its date and number are the CA's);
      * it does not act for a caller without compliance access, because closing an obligation is a compliance write and
        the MCA approval that got us here is a different permission, decided per person;
      * it never fails the recording. The filing IS recorded; whatever stops the obligation closing is reported in the
        answer and to the error reporter, and the CA can still mark it from Compliance;
      * a date earlier than the year the filing declares has ended is refused by `mark_filed` and said in the answer; the
        filing keeps the date the CA typed.
    MOVING A FILING BACK OUT OF FILED REOPENS ITS OBLIGATION (POST-A-267, item 3; `reopen_for_unfiled_filing`), when the
    client no longer has the form recorded as filed for the year (`filing_record_stands`) and the person may reopen an
    obligation (`compliance.approve`, the reopen door's own tier), through `ComplianceRecordService.reopen_record`, so the
    audit row, the note on the obligation and the timeline are that door's. The reason kept is the workspace's own sentence
    about what was moved back. The other way round, the reopen door on the calendar refuses an MCA obligation while the
    filing behind it still stands, and names the workspace, so the two records cannot be made to disagree from either side.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing the CA has already made on MCA21. It transmits
    nothing.
"""
from __future__ import annotations

import re
from domain.practice.compliance_overdue import SETTLED, is_filed, is_settled
from typing import Any, Collection, Iterable, Optional, Sequence

from datetime import date
import os

from core.ist_clock import fy_bounds, ist_fy_label, normalise_fy_label
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


def _year_of_window(start: Any, end: Any) -> Optional[str]:
    """The financial year whose own first and last day an obligation's window is, or None (the same test the closer matches by)."""
    first, last = str(start or "")[:10], str(end or "")[:10]
    try:
        year = ist_fy_label(date.fromisoformat(first))
    except ValueError:
        return None
    return year if fy_bounds(year) == (first, last) else None


def open_years_for(firm_id: str, client_id: str, form_type: Optional[str]) -> Optional[list[dict[str, Any]]]:
    """The financial years the compliance calendar holds this client's obligation for `form_type` OPEN in, newest first (POST-A-291).

    Each is `{financial_year, due_date, status}`. Open means not Filed and not Completed, the closer's own test, so a year
    offered here is one a filing recorded as filed would close. An obligation whose window is not a financial year's own
    first and last day is not offered, because the closer could never match a filing to it. None when the form stands for
    no obligation on the calendar (an event form, or MGT-7A, which is matched to none on purpose): the screen then asks
    for the year as typed text, as it always did. The calendar is read for this client and this firm only."""
    if form_type not in OBLIGATION_FOR_FORM:
        return None
    wanted = OBLIGATION_FOR_FORM[form_type]
    years: dict[str, dict[str, Any]] = {}
    for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type=COMPLIANCE_TYPE,
                                              exclude_statuses=list(SETTLED)):
        if r.get("obligation_type") != wanted:
            continue
        year = _year_of_window(r.get("period_start"), r.get("period_end"))
        if year and year not in years:
            years[year] = {"financial_year": year, "due_date": str(r.get("due_date") or "")[:10] or None,
                           "status": r.get("status")}
    return [years[y] for y in sorted(years, reverse=True)]


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
    open_ones = [r for r in matches if not is_settled(r.get("status"))]
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


# ── taking a filing back out of Filed (POST-A-267, item 3) ──────────────────────────────────────────────────────────────────

#: The answer's `state` when a filing goes back out of Filed. Only REOPENED means this call moved the obligation.
REOPENED = "reopened"
NOT_FILED_ON_THE_CALENDAR = "not_filed_on_the_calendar"
STILL_FILED_IN_THE_WORKSPACE = "still_filed_in_the_workspace"

#: The obligation type -> the form whose filing stands behind it (the inverse of `OBLIGATION_FOR_FORM`).
FORM_FOR_OBLIGATION = {otype: form for form, otype in OBLIGATION_FOR_FORM.items()}


def _client_rows(firm_id: str, client_id: str, form_type: str) -> tuple[list[dict], list[dict]]:
    """The client's ACTIVE companies and its filings of `form_type` recorded as filed, read for this firm and client only.

    The mock deployment keeps both in the MCA router's own dictionaries (no database is configured there), which is where
    that router writes them; the database is read otherwise, with the privileged client naming the firm and the client."""
    if not os.environ.get("SUPABASE_URL"):
        from routers import mca_workspace as mw    # lazy: the mock store lives in the router that writes it
        companies = [c for c in mw._MOCK_COMPANIES.values()
                     if c.get("firm_id") == firm_id and c.get("client_id") == client_id and c.get("is_active", True)]
        filed = [f for f in mw._MOCK_FILINGS.values()
                 if f.get("firm_id") == firm_id and f.get("client_id") == client_id and f.get("form_type") == form_type
                 and f.get("status") == "filed"]
        return companies, filed
    from core.supabase_client import get_supabase
    from core.db_provider import privileged_for
    db = privileged_for(get_supabase())
    companies = (db.table("mca_companies").select("id,company_name,cin").eq("firm_id", firm_id)
                 .eq("client_id", client_id).eq("is_active", True).execute().data) or []
    filed = (db.table("mca_filings").select("id,company_id,company_cin,cin,financial_year,period").eq("firm_id", firm_id)
             .eq("client_id", client_id).eq("form_type", form_type).eq("status", "filed").execute().data) or []
    return companies, filed


def filing_record_stands(firm_id: str, client_id: str, obligation_type: str, financial_year: Optional[str]) -> bool:
    """Whether the MCA workspace still records, for this client and year, the filing the obligation stands for.

    True when a filing of the obligation's form for the year is recorded as filed and, for a client with several active
    companies, every one of them has one (the closer's own test for closing it). False for a type that is not an MCA one,
    a year that is not a year, or a client with no such filing: then reopening the calendar line leaves no record saying
    otherwise. A filing whose company cannot be placed among several counts for none, as in the closer."""
    form = FORM_FOR_OBLIGATION.get(obligation_type)
    if not form or not client_id:
        return False
    try:
        year = normalise_fy_label(financial_year)
    except ValueError:
        return False
    companies, filed = _client_rows(firm_id, client_id, form)
    for_the_year = [f for f in filed if filing_year(f) == year]
    if not for_the_year:
        return False
    if len(companies) <= 1:
        return True
    placed = companies_that_filed(for_the_year, year, companies)
    return all(str(c.get("id")) in placed for c in companies)


def year_of_obligation(record: dict) -> Optional[str]:
    """The financial year an MCA obligation's window is, or None when its window is not a year's own first and last day (the
    closer never matches a filing to such an obligation, so none stands behind it)."""
    return _year_of_window(record.get("period_start"), record.get("period_end"))


def reopen_for_unfiled_filing(
    *, firm_id: str, client_id: str, form_type: Optional[str], financial_year: Optional[str], new_status: str,
    actor: Optional[dict], may_reopen: bool,
) -> Optional[dict[str, Any]]:
    """Reopen the client's obligation for `form_type` and `financial_year` after a filing of it was moved back out of Filed,
    if it should be, and say what became of it; None for a form that stands for no obligation (an event form, MGT-7A).

    Returns `{state, closed: False, reopened, obligation_id, message}`. The obligation is reopened only when it is recorded
    as filed, the client no longer has the form recorded as filed for the year (another filing of the same company, or the
    companies still filed, keep it), and the person may reopen an obligation. Everything else is a state with a sentence; an
    unexpected failure propagates and the router reports it without failing the change to the filing."""
    if form_type not in OBLIGATION_FOR_FORM:
        return None
    from domain.compliance_record_service import compliance_record_service, REOPENED_STATUS
    from core.exceptions import ValidationError

    def said(state: str, message: str, obligation_id: Optional[str] = None) -> dict[str, Any]:
        return {**answer(state, message, obligation_id), "reopened": state == REOPENED}

    if not firm_id or not client_id:
        return said(NOT_CLOSED, "The filing names no client, so no obligation on the compliance calendar was matched to it.")
    try:
        year = normalise_fy_label(financial_year)
        start, end = fy_bounds(year)
    except ValueError:
        return said(NOT_CLOSED, f"The filing names no financial year this can match to the calendar, so no {form_type} "
                                "obligation was reopened.")
    what = f"{form_type} obligation for FY {year}"
    wanted = OBLIGATION_FOR_FORM[form_type]
    filed_ones = [r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                              compliance_type=COMPLIANCE_TYPE)
                  if r.get("obligation_type") == wanted
                  and str(r.get("period_start") or "")[:10] == start and str(r.get("period_end") or "")[:10] == end
                  and is_filed(r.get("status"))]
    if not filed_ones:
        return said(NOT_FILED_ON_THE_CALENDAR, f"The {what} is not recorded as filed on the compliance calendar, so there was "
                                               "nothing to reopen.")
    record = filed_ones[0]
    if filing_record_stands(firm_id, client_id, wanted, year):
        return said(STILL_FILED_IN_THE_WORKSPACE,
                    f"Another {form_type} filing of this client for FY {year} is still recorded as filed, so the {what} "
                    "stays filed.", record.get("id"))
    if not may_reopen:
        return said(NOT_ALLOWED, f"The {what} is still recorded as filed on the compliance calendar. Reopening it needs "
                                 "approval for Compliance, which your access does not include: someone who has it can reopen "
                                 "it from Compliance.", record.get("id"))
    reason = f"The {form_type} filing for FY {year} was moved back to {new_status.replace('_', ' ')} in the MCA workspace."
    try:
        compliance_record_service.reopen_record(record["id"], reason, firm_id=firm_id, actor=actor)
    except ValidationError as refusal:
        return said(NOT_CLOSED, f"The {what} was left as it is: {getattr(refusal, 'message', None) or refusal}",
                    record.get("id"))
    return said(REOPENED, f"The {what} was reopened on the compliance calendar: it is back at {REOPENED_STATUS}, with this "
                          "change kept as the reason.", record.get("id"))
