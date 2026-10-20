"""An MCA filing recorded as filed in the MCA workspace closes the compliance obligation it stands for (POST-A-267).

WHAT WAS WRONG
    `routers/mca_workspace.py` recorded an AOC-4, MGT-7 or ADT-1 as filed and never mentioned `compliance_records`, so a
    company whose AOC-4 was filed on MCA21 in October read Filed in the workspace and Overdue on Deadlines, the Compliance
    tab and the firm dashboard. The GST workspace (POST-A-264), the ITR workspace and the TDS statements had the same
    split and were closed the same way; this is the MCA door.

WHAT IS HELD
    * recording a filing as filed closes the client's obligation for THAT FORM and THAT FINANCIAL YEAR, with the stated
      date and the SRN, through `mark_filed`, and nothing else on the calendar moves (another form, another year, another
      client, another firm, another kind of obligation);
    * an event form (DIR-12, INC-22, SH-7, CHG-1, CHG-4) has no obligation to close and the answer carries no block;
    * a filing with no stated date, or with no year, closes nothing and says why; the year is its `financial_year`, or only
      when that is blank the `period` the firm-level screen writes ("FY 2025-26"), and a filled-in year that is not a year
      is not rescued by the period;
    * the obligation is the CLIENT's and the filings are the COMPANIES': with several active companies it stays open until
      each has filed the form for the year, a filing names its company by `company_id` or by the CIN it carries, and a
      filing that names neither cannot be placed among several;
    * an obligation already Filed keeps its own date and number; no obligation, no compliance access, a date before the
      year ended or a failure closing it never fails the recording and is said in the answer;
    * the mapping from forms to obligation types is pinned to what the calendar generates, so a new MCA obligation cannot
      be added without saying which form closes it.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import routers.mca_workspace as mw
from domain import compliance_record_service as crs
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_obligation_service as cos
from services import mca_filing_closes_obligation as closes
from services import obligation_closure
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"
STATED, SRN = "2026-06-15", "T12345678"
OPEN = "Not Started"


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    d = FakeDB()
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [mw])
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(mw, "can_access_client", lambda user, client_id: True)
    yield d
    MOCK_COMPLIANCE_RECORDS.clear()


_COUNTER = {"n": 0}


def _id(prefix):
    _COUNTER["n"] += 1
    return f"{prefix}-{_COUNTER['n']}"


def _obligation(otype="MCA_AOC4", start="2025-04-01", end="2026-03-31", status=OPEN, client=CLIENT, ctype="MCA",
                firm=FIRM, **extra):
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": client, "compliance_type": ctype, "obligation_type": otype,
        "period_label": f"{otype} {start}", "period_start": start, "period_end": end, "due_date": "2026-10-30",
        "status": status, **extra})


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _company(db, name, *, active=True, client=CLIENT, firm=FIRM):
    return db.seed("mca_companies", {
        "id": _id("co"), "firm_id": firm, "client_id": client, "cin": f"U00000MH2020PTC{_COUNTER['n']:06d}",
        "company_name": name, "is_active": active})


def _filing(db, *, form="AOC-4", fy=FY, company=None, client=CLIENT, firm=FIRM, status="in_progress", **extra):
    return db.seed("mca_filings", {
        "id": _id("filing"), "firm_id": firm, "client_id": client, "company_id": (company or {}).get("id"),
        "form_type": form, "financial_year": fy, "status": status, "srn": None, "filed_date": None,
        "due_date": "2026-10-30", **extra})


def _file(filing, *, day=STATED, srn=SRN, user=None):
    return mw.update_filing_status(
        filing["id"], mw.UpdateFilingStatusRequest(status="filed", ca_approved=True, srn=srn, filing_date=day),
        current_user=user or USER)


def _answer(out):
    return out["data"]["compliance_obligation"]


# ── the filing closes its own obligation ────────────────────────────────────

def test_filing_an_aoc4_closes_the_aoc4_obligation_with_the_stated_date_and_srn(world):
    obligation = _obligation()
    out = _file(_filing(world))
    assert out["success"] is True and out["data"]["status"] == "filed", "the answer is still the filing"
    answer = _answer(out)
    assert answer["state"] == "closed" and answer["closed"] is True and answer["obligation_id"] == obligation["id"], answer
    now = _now(obligation)
    assert now["status"] == "Filed" and now["filed_date"] == STATED and now["acknowledgement_no"] == SRN


@pytest.mark.parametrize("form, otype", [("AOC-4", "MCA_AOC4"), ("MGT-7", "MCA_MGT7")])
def test_each_form_closes_its_own_obligation_and_not_the_other(world, form, otype):
    aoc4, mgt7 = _obligation("MCA_AOC4"), _obligation("MCA_MGT7")
    mine, other = (aoc4, mgt7) if otype == "MCA_AOC4" else (mgt7, aoc4)
    out = _file(_filing(world, form=form))
    assert _answer(out)["obligation_id"] == mine["id"]
    assert _now(mine)["status"] == "Filed" and _now(other)["status"] == OPEN


def test_nothing_else_on_the_calendar_moves(world):
    # Created BEFORE the target, so a match that ignored the year, the type, the kind or the owner would pick one first.
    earlier_year = _obligation(start="2024-04-01", end="2025-03-31")
    later_year = _obligation(start="2026-04-01", end="2027-03-31")
    other_client = _obligation(client="client-2")
    other_firm = _obligation(firm="firm-2")
    other_kind = _obligation(ctype="Income Tax")
    tax_audit = _obligation("TAX_AUDIT", ctype="Income Tax")
    itr = _obligation("ITR", ctype="Income Tax")
    target = _obligation()
    _file(_filing(world))
    assert _now(target)["status"] == "Filed"
    for untouched in (earlier_year, later_year, other_client, other_firm, other_kind, tax_audit, itr):
        assert _now(untouched)["status"] == OPEN, (untouched["obligation_type"], untouched["period_start"])


def test_the_window_must_be_the_years_own_first_and_last_day(world):
    short_end = _obligation(start="2025-04-01", end="2025-09-30")
    late_start = _obligation(start="2025-10-01", end="2026-03-31")
    out = _file(_filing(world))
    assert _answer(out)["state"] == "not_on_the_calendar"
    assert _now(short_end)["status"] == OPEN and _now(late_start)["status"] == OPEN


def test_the_year_is_the_filings_own_in_either_spelling(world):
    obligation = _obligation()
    out = _file(_filing(world, fy="2025-2026"))
    assert _answer(out)["state"] == "closed" and _now(obligation)["status"] == "Filed"


def test_an_adt1_closes_an_adt1_obligation_when_the_calendar_has_one_and_says_so_when_it_has_none(world):
    first = _file(_filing(world, form="ADT-1"))
    assert _answer(first)["state"] == "not_on_the_calendar" and "ADT-1 obligation for FY 2025-26" in _answer(first)["message"]
    obligation = _obligation("MCA_ADT1")
    second = _file(_filing(world, form="ADT-1"))
    assert _answer(second)["state"] == "closed" and _now(obligation)["status"] == "Filed"


def test_the_complete_route_closes_it_too(world):
    obligation = _obligation()
    f = _filing(world)
    out = mw.complete_filing(f["id"], mw.UpdateFilingStatusRequest(
        status="filed", ca_approved=True, srn=SRN, filing_date=STATED), current_user=USER)
    assert _answer(out)["closed"] is True and _now(obligation)["filed_date"] == STATED


# ── what does not close it ──────────────────────────────────────────────────

@pytest.mark.parametrize("form", ["DIR-12", "INC-22", "SH-7", "CHG-1", "CHG-4"])
def test_an_event_form_has_no_obligation_and_the_answer_carries_no_block(world, form):
    aoc4 = _obligation()
    out = _file(_filing(world, form=form))
    assert out["success"] is True and out["data"]["status"] == "filed"
    assert "compliance_obligation" not in out["data"]
    assert _now(aoc4)["status"] == OPEN, "an event filing must not close the annual obligation"


def test_a_direct_caller_asking_about_an_event_form_is_told_there_is_nothing_to_close(world):
    answer = closes.close_for_filed_filing(
        firm_id=FIRM, client_id=CLIENT, form_type="DIR-12", financial_year=FY, company_id=None, filed_date=STATED,
        srn=SRN, actor=USER, may_write_compliance=True, companies=[], filed_company_ids=[])
    assert answer["state"] == "an_event_filing" and answer["closed"] is False and "DIR-12" in answer["message"]


def test_an_mgt7a_is_matched_to_no_obligation_and_the_answer_says_so(world):
    """Whether a filed MGT-7A discharges the MCA_MGT7 obligation is a reading nobody has confirmed (POST-C-209): it is not
    assumed either way, and the screen that offers the form is told instead of left silent."""
    mgt7, aoc4 = _obligation("MCA_MGT7"), _obligation("MCA_AOC4")
    out = _file(_filing(world, form="MGT-7A"))
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = _answer(out)
    assert answer["state"] == "not_matched_to_an_obligation" and answer["closed"] is False
    assert "MGT-7A" in answer["message"] and "MGT-7" in answer["message"] and "Compliance" in answer["message"]
    assert _now(mgt7)["status"] == OPEN and _now(aoc4)["status"] == OPEN


def test_mgt7a_is_asked_about_and_matched_to_nothing_while_an_event_form_is_not_asked_about():
    assert closes.is_asked_about("MGT-7A") and not closes.has_an_obligation("MGT-7A")
    assert "MGT-7A" not in closes.OBLIGATION_FOR_FORM
    assert not set(closes.UNMATCHED_FORMS) & set(closes.OBLIGATION_FOR_FORM)
    assert all(closes.is_asked_about(f) for f in closes.OBLIGATION_FOR_FORM)
    assert not any(closes.is_asked_about(f) for f in mw._EVENT_FORMS)
    assert not closes.is_asked_about(None) and not closes.is_asked_about("")


@pytest.mark.parametrize("status", ["not_started", "in_progress", "overdue"])
def test_a_status_other_than_filed_closes_nothing_and_adds_no_block(world, status):
    obligation = _obligation()
    f = _filing(world)
    out = mw.update_filing_status(f["id"], mw.UpdateFilingStatusRequest(status=status, ca_approved=True), current_user=USER)
    assert out["success"] is True and "compliance_obligation" not in out["data"]
    assert _now(obligation)["status"] == OPEN


def test_a_filing_with_no_stated_date_closes_nothing_and_asks_for_it(world):
    obligation = _obligation()
    out = _file(_filing(world), day=None)
    assert out["success"] is True and out["data"]["status"] == "filed" and out["data"]["filed_date"] is None
    answer = _answer(out)
    assert answer["state"] == "not_closed" and "no filing date" in answer["message"] and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == OPEN and not _now(obligation).get("filed_date")


@pytest.mark.parametrize("day", ["", "   ", None])
def test_a_blank_date_is_no_date(world, day):
    _obligation()
    answer = closes.close_for_filed_filing(
        firm_id=FIRM, client_id=CLIENT, form_type="AOC-4", financial_year=FY, company_id=None, filed_date=day,
        srn=SRN, actor=USER, may_write_compliance=True, companies=[], filed_company_ids=[])
    assert answer["state"] == "not_closed" and "no filing date" in answer["message"]


@pytest.mark.parametrize("year", [None, "", "not-a-year", "2025-99"])
def test_a_filing_with_no_usable_year_is_left_to_the_calendar(world, year):
    obligation = _obligation()
    out = _file(_filing(world, fy=year))
    answer = _answer(out)
    assert answer["state"] == "not_closed" and "financial year" in answer["message"] and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_a_filing_that_names_no_client_or_firm_matches_nothing(world):
    """`find_all` drops an empty filter, which would read every client's calendar."""
    _obligation()
    for firm, client in (("", CLIENT), (FIRM, "")):
        answer = closes.close_for_filed_filing(
            firm_id=firm, client_id=client, form_type="AOC-4", financial_year=FY, company_id=None, filed_date=STATED,
            srn=SRN, actor=USER, may_write_compliance=True, companies=[], filed_company_ids=[])
        assert answer["state"] == "not_closed" and answer["closed"] is False


def test_a_date_before_the_year_ended_is_refused_at_the_door_and_nothing_is_stored(world):
    """It used to be stored on the filing while the calendar refused it, leaving the two disagreeing (POST-A-290): the door judges it
    first, by the rule the ITR acknowledgement applies, and a refused date changes nothing."""
    obligation = _obligation()
    filing = _filing(world)
    out = _file(filing, day="2026-03-30")
    assert out["success"] is False and out["data"] is None
    assert "cannot have been filed before the year ended on 2026-03-31" in out["error"] and "Nothing was changed" in out["error"]
    row = next(f for f in world.rows("mca_filings") if f["id"] == filing["id"])
    assert row["status"] == "in_progress" and row["filed_date"] is None and row["srn"] is None
    assert _now(obligation)["status"] == OPEN


def test_the_calendar_door_still_refuses_a_date_before_the_year_ended_when_something_else_asks(world):
    """The refusal at the door is the first line; `mark_filed` is the second, and a direct caller of the closer still gets it said."""
    obligation = _obligation()
    answer = closes.close_for_filed_filing(
        firm_id=FIRM, client_id=CLIENT, form_type="AOC-4", financial_year=FY, company_id=None, filed_date="2026-03-30", srn=SRN,
        actor=USER, may_write_compliance=True, companies=[], filed_company_ids=[])
    assert answer["state"] == "not_closed" and "before the period it declares ended on 2026-03-31" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_the_last_day_of_the_year_is_not_before_it_ended(world):
    obligation = _obligation()
    out = _file(_filing(world), day="2026-03-31")
    assert _answer(out)["closed"] is True and _now(obligation)["filed_date"] == "2026-03-31"


@pytest.mark.parametrize("status", ["Filed", "Completed"])
def test_an_obligation_already_filed_keeps_its_own_date_and_number(world, status):
    obligation = _obligation(status=status, filed_date="2026-10-20", acknowledgement_no="THE-CAS-OWN-NUMBER")
    out = _file(_filing(world))
    answer = _answer(out)
    assert answer["state"] == "already_filed" and answer["closed"] is False and answer["obligation_id"] == obligation["id"]
    now = _now(obligation)
    assert now["status"] == status
    assert now["filed_date"] == "2026-10-20" and now["acknowledgement_no"] == "THE-CAS-OWN-NUMBER"


def test_no_obligation_on_the_calendar_files_and_says_so(world):
    out = _file(_filing(world))
    assert out["success"] is True and out["data"]["status"] == "filed"
    assert _answer(out)["state"] == "not_on_the_calendar" and "FY 2025-26" in _answer(out)["message"]


def test_a_caller_without_compliance_access_files_and_the_obligation_stays_open(world, monkeypatch):
    monkeypatch.setattr(mw, "can_user", lambda user, resource, action: not (resource == "compliance" and action == "write"))
    obligation = _obligation()
    out = _file(_filing(world))
    assert out["success"] is True and out["data"]["status"] == "filed"
    assert _answer(out)["state"] == "not_allowed" and "Compliance" in _answer(out)["message"]
    assert _now(obligation)["status"] == OPEN


def test_the_permission_asked_is_compliance_write_per_person(world, monkeypatch):
    asked = []
    monkeypatch.setattr(mw, "can_user", lambda user, resource, action: asked.append((resource, action)) or True)
    _obligation()
    _file(_filing(world))
    assert ("compliance", "write") in asked and ("mca", "approve") in asked


def test_a_filing_the_caller_may_not_record_closes_nothing(world):
    obligation = _obligation()
    f = _filing(world)
    executive = {**USER, "id": "u2", "role": "Executive"}
    with pytest.raises(HTTPException) as refused:
        _file(f, user=executive)
    assert refused.value.status_code == 403
    assert _now(obligation)["status"] == OPEN


def test_a_filing_without_the_cas_confirmation_closes_nothing(world):
    obligation = _obligation()
    f = _filing(world)
    out = mw.update_filing_status(f["id"], mw.UpdateFilingStatusRequest(status="filed", filing_date=STATED), current_user=USER)
    assert out["success"] is False
    assert _now(obligation)["status"] == OPEN


def test_moving_a_filing_back_out_of_filed_does_not_reopen_the_obligation(world):
    obligation = _obligation()
    f = _filing(world)
    _file(f)
    out = mw.update_filing_status(f["id"], mw.UpdateFilingStatusRequest(status="in_progress", ca_approved=True), current_user=USER)
    assert out["success"] is True and out["data"]["status"] == "in_progress"
    assert _now(obligation)["status"] == "Filed", "reopening is the CA's decision, as with the GST and ITR workspaces"


# ── several companies under one client ──────────────────────────────────────

def test_with_two_companies_the_obligation_stays_open_until_each_has_filed(world):
    a, b = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    obligation = _obligation()
    first = _file(_filing(world, company=a))
    answer = _answer(first)
    assert answer["state"] == "waiting_for_other_companies" and "Beta Pvt Ltd" in answer["message"]
    assert "Alpha" not in answer["message"].split("stays open until")[1]
    assert _now(obligation)["status"] == OPEN
    second = _file(_filing(world, company=b), day="2026-06-16", srn="T99999999")
    assert _answer(second)["state"] == "closed"
    now = _now(obligation)
    assert now["status"] == "Filed" and now["filed_date"] == "2026-06-16" and now["acknowledgement_no"] == "T99999999"


def test_the_waiting_message_names_every_company_still_to_file(world):
    a = _company(world, "Alpha Pvt Ltd")
    _company(world, "Beta Pvt Ltd"), _company(world, "Gamma Pvt Ltd")
    _obligation()
    answer = _answer(_file(_filing(world, company=a)))
    assert answer["state"] == "waiting_for_other_companies"
    assert "Beta Pvt Ltd, Gamma Pvt Ltd have also filed it" in answer["message"]


def test_a_filing_that_names_no_company_cannot_be_placed_among_several(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    obligation = _obligation()
    answer = _answer(_file(_filing(world, company=None)))
    assert answer["state"] == "which_company_is_unknown" and "2 companies" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_a_filing_naming_a_company_the_client_does_not_hold_cannot_be_placed_either(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    stranger = _company(world, "Not Ours Pvt Ltd", client="client-2")
    obligation = _obligation()
    answer = _answer(_file(_filing(world, company=stranger)))
    assert answer["state"] == "which_company_is_unknown"
    assert _now(obligation)["status"] == OPEN


def test_one_company_or_none_closes_on_its_own_filing(world):
    a = _company(world, "Alpha Pvt Ltd")
    obligation = _obligation()
    assert _answer(_file(_filing(world, company=a)))["closed"] is True and _now(obligation)["status"] == "Filed"
    other = _obligation(client="client-3")
    assert _answer(_file(_filing(world, client="client-3", company=None)))["closed"] is True
    assert _now(other)["status"] == "Filed"


def test_a_company_that_is_no_longer_active_is_not_waited_for(world):
    a = _company(world, "Alpha Pvt Ltd")
    _company(world, "Wound Up Ltd", active=False)
    obligation = _obligation()
    assert _answer(_file(_filing(world, company=a)))["closed"] is True and _now(obligation)["status"] == "Filed"


def test_another_clients_or_firms_companies_are_not_waited_for(world):
    a = _company(world, "Alpha Pvt Ltd")
    _company(world, "Other Client Ltd", client="client-2")
    _company(world, "Other Firm Ltd", firm="firm-2")
    obligation = _obligation()
    assert _answer(_file(_filing(world, company=a)))["closed"] is True and _now(obligation)["status"] == "Filed"


def test_only_a_filing_of_this_form_this_year_recorded_as_filed_counts_for_the_other_company(world):
    a, b = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    # Beta has filed a different form this year, the same form last year, the same form this year but not yet recorded as
    # filed, and another client's firm has a filing of everything: none of those is Beta's AOC-4 for FY 2025-26.
    _filing(world, form="MGT-7", company=b, status="filed")
    _filing(world, form="AOC-4", fy="2024-25", company=b, status="filed")
    _filing(world, form="AOC-4", company=b, status="in_progress")
    _filing(world, form="AOC-4", company=b, status="filed", firm="firm-2")
    _filing(world, form="AOC-4", company=b, status="filed", client="client-2")
    obligation = _obligation()
    answer = _answer(_file(_filing(world, company=a)))
    assert answer["state"] == "waiting_for_other_companies" and "Beta Pvt Ltd" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_companies_that_filed_reads_the_year_in_either_spelling_and_ignores_what_places_no_company():
    rows = [
        {"company_id": "a", "financial_year": "2025-26"},
        {"company_id": "b", "financial_year": "2025-2026"},
        {"company_id": "c", "financial_year": "2024-25"},
        {"company_id": None, "financial_year": "2025-26"},
        {"company_id": "d", "financial_year": None},
        {"company_id": "e", "financial_year": "junk"},
    ]
    assert closes.companies_that_filed(rows, "2025-26") == {"a", "b"}
    assert closes.companies_that_filed(rows, "junk") == set()


# ── mock mode: the same answers from the in-memory stores ───────────────────

@pytest.fixture
def in_memory(world, monkeypatch):
    monkeypatch.setattr(mw, "_USE_MOCK", True)
    for store in (mw._MOCK_COMPANIES, mw._MOCK_FILINGS):
        store.clear()
    yield
    for store in (mw._MOCK_COMPANIES, mw._MOCK_FILINGS):
        store.clear()


def _mock_company(name, *, active=True, client=CLIENT, firm=FIRM):
    row = {"id": _id("co"), "firm_id": firm, "client_id": client, "company_name": name}
    if not active:
        row["is_active"] = False
    mw._MOCK_COMPANIES[row["id"]] = row
    return row


def _mock_filing(*, company=None, form="AOC-4", fy=FY, status="in_progress", client=CLIENT, firm=FIRM, **extra):
    row = {"id": _id("filing"), "firm_id": firm, "client_id": client, "company_id": (company or {}).get("id"),
           "form_type": form, "financial_year": fy, "status": status, "srn": None, "filed_date": None, **extra}
    mw._MOCK_FILINGS[row["id"]] = row
    return row


def test_mock_mode_closes_the_obligation_from_its_own_stores(in_memory):
    obligation = _obligation()
    out = _file(_mock_filing(company=_mock_company("Alpha Pvt Ltd")))
    assert _answer(out)["state"] == "closed" and _now(obligation)["status"] == "Filed"


def test_mock_mode_waits_for_the_other_active_company_of_this_client_and_firm_only(in_memory):
    a = _mock_company("Alpha Pvt Ltd")
    beta = _mock_company("Beta Pvt Ltd")
    _mock_company("Wound Up Ltd", active=False)
    _mock_company("Other Client Ltd", client="client-2")
    _mock_company("Other Firm Ltd", firm="firm-2")
    obligation = _obligation()
    first = _answer(_file(_mock_filing(company=a)))
    assert first["state"] == "waiting_for_other_companies"
    assert "Beta Pvt Ltd" in first["message"] and "Wound Up" not in first["message"] and "Other" not in first["message"]
    assert _now(obligation)["status"] == OPEN
    assert _answer(_file(_mock_filing(company=beta)))["state"] == "closed"
    assert _now(obligation)["status"] == "Filed"


def test_mock_mode_counts_only_this_forms_filed_filings_of_this_year(in_memory):
    a, b = _mock_company("Alpha Pvt Ltd"), _mock_company("Beta Pvt Ltd")
    _mock_filing(company=b, form="MGT-7", status="filed")
    _mock_filing(company=b, fy="2024-25", status="filed")
    _mock_filing(company=b, status="in_progress")
    _mock_filing(company=b, status="filed", client="client-2")
    _mock_filing(company=b, status="filed", firm="firm-2")
    _obligation()
    assert _answer(_file(_mock_filing(company=a)))["state"] == "waiting_for_other_companies"


# ── what the firm-level screen writes: a period and a CIN, no year and no company id ─────────────────────────

@pytest.mark.parametrize("text, year", [
    ("2025-26", "2025-26"), ("2025-2026", "2025-26"), ("FY 2025-26", "2025-26"), ("fy2025-26", "2025-26"),
    ("  FY  2025-2026 ", "2025-26"), ("FY2024-25", "2024-25"),
])
def test_the_year_a_filing_declares_is_read_in_every_spelling_the_screens_write(text, year):
    assert closes.filing_year({"financial_year": text}) == year
    assert closes.filing_year({"financial_year": None, "period": text}) == year
    assert closes.filing_year({"financial_year": "", "period": text}) == year
    assert closes.filing_year({"financial_year": "  ", "period": text}) == year


@pytest.mark.parametrize("filing", [
    {}, {"financial_year": None, "period": None}, {"period": "Apr-2026"}, {"period": "Q1 2025-26"},
    {"period": "2025"}, {"period": "FY 2025-28"}, {"financial_year": "2025-99"},
    # A year that is filled in but is not a year is not rescued by a period that is: the filing contradicts itself.
    {"financial_year": "2025-99", "period": "FY 2025-26"}, {"financial_year": "soon", "period": "FY 2025-26"},
])
def test_a_filing_that_declares_no_year_declares_none(filing):
    assert closes.filing_year(filing) is None


def test_a_year_that_is_filled_in_wins_over_the_period():
    assert closes.filing_year({"financial_year": "2024-25", "period": "FY 2025-26"}) == "2024-25"


def test_a_filing_the_firm_level_screen_added_closes_by_its_period(world):
    """The screen inserts the row itself with `period` "FY 2025-26" and no `financial_year`: the commonest way a filing
    gets here, and the one the first version of this change could never close."""
    obligation = _obligation()
    out = _file(_filing(world, fy=None, period="FY 2025-26", cin="U00000MH2020PTC000001",
                        company_cin="U00000MH2020PTC000001"))
    assert _answer(out)["state"] == "closed" and _now(obligation)["status"] == "Filed"


def test_a_period_that_is_another_year_does_not_close_this_years_obligation(world):
    this_year, last_year = _obligation(), _obligation(start="2024-04-01", end="2025-03-31")
    out = _file(_filing(world, fy=None, period="FY 2024-25"))
    assert _answer(out)["obligation_id"] == last_year["id"]
    assert _now(last_year)["status"] == "Filed" and _now(this_year)["status"] == OPEN


def test_a_filled_in_year_that_is_not_a_year_is_not_rescued_by_the_period(world):
    obligation = _obligation()
    answer = _answer(_file(_filing(world, fy="2025-99", period="FY 2025-26")))
    assert answer["state"] == "not_closed" and "financial year" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_a_period_that_is_not_a_year_leaves_the_obligation_to_the_calendar(world):
    obligation = _obligation()
    answer = _answer(_file(_filing(world, fy=None, period="Apr-2026")))
    assert answer["state"] == "not_closed" and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_mock_mode_closes_a_filing_that_names_only_a_period(in_memory):
    obligation = _obligation()
    out = _file(_mock_filing(fy=None, period="FY 2025-26"))
    assert _answer(out)["state"] == "closed" and _now(obligation)["status"] == "Filed"


@pytest.mark.parametrize("given, held, expected", [
    ({"company_id": "co-1"}, [{"id": "co-9", "cin": "X"}], "co-1"),
    ({"company_id": "co-1", "company_cin": "X"}, [{"id": "co-9", "cin": "X"}], "co-1"),
    ({"company_cin": "u00000mh2020ptc000001"}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], "co-1"),
    ({"company_cin": "  U00000MH2020PTC000001 "}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], "co-1"),
    ({"cin": "U00000MH2020PTC000001"}, [{"id": "co-1", "cin": "u00000mh2020ptc000001"}], "co-1"),
    ({"company_cin": "", "cin": "U00000MH2020PTC000001"}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], "co-1"),
    # A column that holds only spaces is as blank as an empty one and must not hide the CIN in the other.
    ({"company_cin": "   ", "cin": "U00000MH2020PTC000001"}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], "co-1"),
    ({"company_cin": None, "cin": "U00000MH2020PTC000001"}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], "co-1"),
    ({"company_cin": "U00000MH2020PTC000001", "cin": "U00000MH2020PTC000002"},
     [{"id": "co-1", "cin": "U00000MH2020PTC000001"}, {"id": "co-2", "cin": "U00000MH2020PTC000002"}], "co-1"),
    # A CIN that is none of the client's, one that two companies share, a blank one and none at all name nobody.
    ({"company_cin": "U99999MH2020PTC999999"}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], None),
    ({"company_cin": "U00000MH2020PTC000001"}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"},
                                                 {"id": "co-2", "cin": "U00000MH2020PTC000001"}], None),
    ({"company_cin": "  "}, [{"id": "co-1", "cin": ""}], None),
    ({}, [{"id": "co-1", "cin": "U00000MH2020PTC000001"}], None),
    ({"company_cin": "U00000MH2020PTC000001"}, [], None),
])
def test_a_filing_names_its_company_by_id_or_failing_that_by_the_cin_it_carries(given, held, expected):
    assert closes.company_of(given, held) == expected


def test_with_two_companies_a_filing_the_firm_level_screen_added_is_placed_by_its_cin(world):
    """That screen sends a CIN and no company id; the CIN is how it says which company the filing is for."""
    a, b = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    obligation = _obligation()
    first = _answer(_file(_filing(world, fy=None, period="FY 2025-26", company_cin=a["cin"].lower(), cin=a["cin"])))
    assert first["state"] == "waiting_for_other_companies" and "Beta Pvt Ltd" in first["message"]
    assert _now(obligation)["status"] == OPEN
    second = _answer(_file(_filing(world, fy=None, period="FY 2025-26", company_cin=b["cin"], cin=b["cin"]),
                           day="2026-06-16", srn="T99999999"))
    assert second["state"] == "closed"
    assert _now(obligation)["acknowledgement_no"] == "T99999999"


def test_a_cin_that_is_none_of_the_clients_cannot_place_a_filing_among_several(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    obligation = _obligation()
    answer = _answer(_file(_filing(world, company_cin="U99999MH2020PTC999999")))
    assert answer["state"] == "which_company_is_unknown"
    assert _now(obligation)["status"] == OPEN


def test_the_same_company_filing_the_form_twice_does_not_stand_in_for_the_other(world):
    a, _ = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    _filing(world, company=a, status="filed")
    obligation = _obligation()
    answer = _answer(_file(_filing(world, company=a)))
    assert answer["state"] == "waiting_for_other_companies" and "Beta Pvt Ltd" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_other_companies_filings_are_placed_by_their_cin_and_period_too(world):
    a, b = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    # Beta's earlier AOC-4 was added on the firm-level screen: a period, a CIN, no year and no company id.
    _filing(world, fy=None, period="FY 2025-26", company_cin=b["cin"], status="filed")
    obligation = _obligation()
    assert _answer(_file(_filing(world, company=a)))["state"] == "closed"
    assert _now(obligation)["status"] == "Filed"


def test_companies_that_filed_places_rows_by_period_and_cin_when_it_is_given_the_companies():
    held = [{"id": "co-1", "cin": "U1"}, {"id": "co-2", "cin": "U2"}, {"id": "co-3", "cin": "U3"}]
    rows = [
        {"company_id": "co-1", "financial_year": "2025-26"},
        {"company_cin": "u2", "period": "FY 2025-26"},
        {"cin": "U3", "financial_year": "2024-25"},
        {"company_cin": "U9", "period": "FY 2025-26"},
    ]
    assert closes.companies_that_filed(rows, "2025-26", held) == {"co-1", "co-2"}
    assert closes.companies_that_filed(rows, "2025-26") == {"co-1"}, "without the companies a CIN places nobody"


# ── legacy rows and the complete route ──────────────────────────────────────

def test_a_legacy_filing_with_no_client_is_answered_that_it_names_none_and_nothing_is_read_for_nobody(world, monkeypatch):
    reported = []
    import core.observability as obs
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    obligation = _obligation()
    out = _file(_filing(world, client=None))
    answer = _answer(out)
    assert out["success"] is True and out["data"]["status"] == "filed"
    assert answer["state"] == "not_closed" and "names no client" in answer["message"]
    assert reported == [], "a filing with no client is an ordinary answer, not a failure"
    assert _now(obligation)["status"] == OPEN


def test_company_facts_reads_nothing_for_a_filing_with_no_client(world, monkeypatch):
    """The fake database matches a missing client to a missing client, which PostgREST does not (`client_id=eq.None` is an
    invalid uuid), so this double fails the test on ANY read instead."""
    import core.supabase_client as sc

    class _NoReads:
        def table(self, name):
            raise AssertionError(f"read {name} for a filing that names no client")
    monkeypatch.setattr(sc, "get_supabase", lambda: _NoReads())
    assert mw._company_facts(FIRM, {"client_id": None, "form_type": "AOC-4"}) == ([], set())
    assert mw._company_facts(FIRM, {"client_id": "", "form_type": "AOC-4"}) == ([], set())
    assert mw._company_facts(FIRM, {"form_type": "AOC-4"}) == ([], set())


@pytest.mark.parametrize("year, what", [("2025-2026", "FY 2025-26"), ("2025-26", "FY 2025-26")])
def test_a_direct_caller_may_hand_the_year_in_either_spelling_and_gets_the_canonical_label(world, year, what):
    _obligation()
    answer = closes.close_for_filed_filing(
        firm_id=FIRM, client_id=CLIENT, form_type="AOC-4", financial_year=year, company_id=None, filed_date=STATED,
        srn=SRN, actor=USER, may_write_compliance=True, companies=[], filed_company_ids=[])
    assert answer["closed"] is True and what in answer["message"]


@pytest.mark.parametrize("year", ["2025-99", "2025-27", "FY 2025-26", "twenty", ""])
def test_a_direct_caller_handing_in_something_that_is_not_a_canonical_year_closes_nothing(world, year):
    """`fy_bounds` reads the first four characters and ignores the rest, so '2025-99' would otherwise be taken as FY 2025-26."""
    obligation = _obligation()
    answer = closes.close_for_filed_filing(
        firm_id=FIRM, client_id=CLIENT, form_type="AOC-4", financial_year=year, company_id=None, filed_date=STATED,
        srn=SRN, actor=USER, may_write_compliance=True, companies=[], filed_company_ids=[])
    assert answer["state"] == "not_closed" and "financial year" in answer["message"]
    assert _now(obligation)["status"] == OPEN


def test_the_complete_route_stamps_today_on_the_filing_itself_so_the_calendar_carries_the_same_date(world, monkeypatch):
    """The one route that supplies a date when none is typed. It writes it on the FILING too, so the two cannot disagree."""
    from datetime import date
    monkeypatch.setattr(mw, "ist_today", lambda: date(2026, 6, 18))
    obligation = _obligation()
    f = _filing(world)
    out = mw.complete_filing(f["id"], mw.UpdateFilingStatusRequest(status="filed", ca_approved=True, srn=SRN),
                             current_user=USER)
    assert out["data"]["filed_date"] == "2026-06-18"
    assert _answer(out)["closed"] is True and _now(obligation)["filed_date"] == "2026-06-18"


# ── a failure never fails the recording ─────────────────────────────────────

def test_an_unexpected_failure_closing_the_obligation_does_not_fail_the_recording(world, monkeypatch):
    reported = []
    import core.observability as obs
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    monkeypatch.setattr(closes, "close_for_filed_filing",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("calendar read failed")))
    obligation = _obligation()
    out = _file(_filing(world))
    assert out["success"] is True and out["data"]["status"] == "filed" and out["data"]["srn"] == SRN
    answer = _answer(out)
    assert answer["state"] == "not_closed" and "Mark the obligation filed from Compliance" in answer["message"]
    assert reported and reported[0][1]["operation"] == "mca_workspace.close_the_obligation"
    assert _now(obligation)["status"] == OPEN


def test_a_failure_reading_the_companies_does_not_fail_the_recording_either(world, monkeypatch):
    reported = []
    import core.observability as obs
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    monkeypatch.setattr(mw, "_company_facts", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("companies unreadable")))
    obligation = _obligation()
    out = _file(_filing(world))
    assert out["success"] is True and out["data"]["status"] == "filed"
    assert _answer(out)["state"] == "not_closed"
    assert reported == ["mca_workspace.close_the_obligation"]
    assert _now(obligation)["status"] == OPEN


def test_a_walk_that_stops_part_way_says_where_the_obligation_really_is(world, monkeypatch):
    reported = []
    monkeypatch.setattr(obligation_closure, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    real = crs.compliance_record_service.update_record

    def fail_on_the_last_step(record_id, data, **kw):
        if data.get("status") == "Filed":
            raise RuntimeError("write failed")
        return real(record_id, data, **kw)
    monkeypatch.setattr(crs.compliance_record_service, "update_record", fail_on_the_last_step)
    obligation = _obligation()
    out = _file(_filing(world))
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = _answer(out)
    assert answer["state"] == "not_closed" and "Ready To File" in answer["message"] and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Ready To File"
    assert reported == ["mca_filing_closes_obligation.mark_filed"]


def test_the_calendar_row_is_read_for_this_firm_and_client_only(world):
    mine = _obligation()
    theirs = _obligation(firm="firm-2")
    _file(_filing(world))
    assert _now(mine)["status"] == "Filed" and _now(theirs)["status"] == OPEN


# ── the mapping is the calendar's ───────────────────────────────────────────

def test_every_mca_obligation_the_calendar_generates_has_a_form_that_closes_it():
    generated = {spec["obligation_type"] for spec in cos._roc_obligations(FY)}
    assert generated == {"MCA_AOC4", "MCA_MGT7"}, "the calendar's MCA obligations changed; say which form closes the new one"
    assert generated <= set(closes.OBLIGATION_FOR_FORM.values())
    assert {spec["compliance_type"] for spec in cos._roc_obligations(FY)} == {closes.COMPLIANCE_TYPE}


def test_the_forms_that_close_an_obligation_are_the_workspaces_annual_forms_and_no_event_form_is_among_them():
    assert set(closes.OBLIGATION_FOR_FORM) == set(mw._ANNUAL_FORMS)
    assert not set(closes.OBLIGATION_FOR_FORM) & set(mw._EVENT_FORMS)
    assert set(closes.OBLIGATION_FOR_FORM.values()) <= set(cos.RETURN_OBLIGATION_TYPES)
    assert all(closes.has_an_obligation(f) for f in mw._ANNUAL_FORMS)
    assert not any(closes.has_an_obligation(f) for f in mw._EVENT_FORMS)


def test_only_the_move_to_filed_asks_the_closer():
    src = inspect.getsource(mw.update_filing_status)
    filed_branch = src.split('if body.status == "filed":', 2)[-1]
    assert "_answered_with_the_obligation(" in filed_branch
    assert src.count("_answered_with_the_obligation(") == 1
    assert "_close_the_obligation(" in inspect.getsource(mw._answered_with_the_obligation)
