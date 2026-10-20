"""An MCA filing's date is judged before it is stored, by the rule the ITR acknowledgement applies (POST-A-290).

WHAT WAS WRONG
    `UpdateFilingStatusRequest.filing_date` was free text. A malformed value reached the DATE column and came back as "Unable to
    complete MCA operation" with no reason; a date in the future, or before the financial year the filing declares had ended, was stored
    on the filing while `mark_filed` refused it, so the filing said filed on a day the calendar would not accept and the obligation was
    left open with the reason in the answer. The ITR acknowledgement refused all three before storing anything.

WHAT IS HELD
    * a malformed, an impossible and a future date each come back as a sentence, and change nothing (the filing keeps its status,
      date and SRN; the calendar is untouched);
    * a date before the year an AOC-4 or an MGT-7 describes has ended comes back as a sentence naming the year and the day, and
      changes nothing; the last day of the year is not before it;
    * an ADT-1 (filed within days of an appointment) and an event form carry no such floor, and an MGT-7A is not asked;
    * a filing whose year is not a year is not judged on it;
    * the year-end comparison is ONE function (`year_end_not_yet_reached_on`) that the ITR acknowledgement and this door both ask.
"""
from __future__ import annotations

import pytest

import routers.itr_workspace as itr
import routers.mca_workspace as mw
from domain import compliance_record_service as crs
from core.ist_clock import ist_today
from mock_data import MOCK_COMPLIANCE_RECORDS
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"


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


_N = {"n": 0}


def _filing(db, *, form="AOC-4", fy=FY, period=None, status="in_progress"):
    _N["n"] += 1
    return db.seed("mca_filings", {
        "id": f"f-{_N['n']}", "firm_id": FIRM, "client_id": CLIENT, "company_id": None, "form_type": form, "financial_year": fy,
        "period": period, "status": status, "srn": None, "filed_date": None, "due_date": "2026-10-30"})


def _file(filing, day):
    return mw.update_filing_status(
        filing["id"], mw.UpdateFilingStatusRequest(status="filed", ca_approved=True, srn="T1", filing_date=day), current_user=USER)


def _unchanged(db, filing):
    row = next(f for f in db.rows("mca_filings") if f["id"] == filing["id"])
    assert (row["status"], row["filed_date"], row["srn"]) == ("in_progress", None, None), row


@pytest.mark.parametrize("day, words", [
    ("15/06/2026", "YYYY-MM-DD"), ("tomorrow", "YYYY-MM-DD"), ("2026-02-30", "YYYY-MM-DD"), ("2026-6-5", "YYYY-MM-DD"),
])
def test_a_date_that_is_not_a_date_is_a_sentence_and_changes_nothing(world, day, words):
    filing = _filing(world)
    out = _file(filing, day)
    assert out["success"] is False and words in out["error"] and "filing_date" in out["error"] and "Nothing was changed" in out["error"], out
    assert "filed_date" not in out["error"], "the field the screen sent is the one named"
    _unchanged(world, filing)


def test_a_date_in_the_future_is_a_sentence_and_changes_nothing(world):
    filing = _filing(world, fy="2024-25")
    tomorrow = ist_today().replace(year=ist_today().year + 1).isoformat()
    out = _file(filing, tomorrow)
    assert out["success"] is False and "cannot be in the future" in out["error"] and "filing_date" in out["error"], out
    _unchanged(world, filing)


@pytest.mark.parametrize("form", ["AOC-4", "MGT-7"])
def test_a_date_before_the_year_ended_is_a_sentence_naming_the_year_and_the_day(world, form):
    filing = _filing(world, form=form)
    out = _file(filing, "2026-03-30")
    assert out["success"] is False
    assert f"An {form} for FY 2025-26 cannot have been filed before the year ended on 2026-03-31" in out["error"], out
    _unchanged(world, filing)


@pytest.mark.parametrize("form", ["AOC-4", "MGT-7"])
def test_the_last_day_of_the_year_and_a_later_day_file(world, form):
    for day in ("2026-03-31", "2026-06-15"):
        out = _file(_filing(world, form=form), day)
        assert out["success"] is True and out["data"]["filed_date"] == day, (form, day, out)


def test_the_year_is_read_from_the_period_the_firm_level_screen_writes(world):
    """That screen inserts the row itself with `period` "FY 2025-26" and no `financial_year`."""
    filing = _filing(world, fy=None, period="FY 2025-26")
    assert _file(filing, "2026-03-30")["success"] is False
    assert _file(_filing(world, fy=None, period="FY 2025-26"), "2026-04-02")["success"] is True


@pytest.mark.parametrize("form", ["ADT-1", "DIR-12", "INC-22", "SH-7", "CHG-1", "CHG-4", "MGT-7A"])
def test_a_form_that_does_not_describe_a_finished_year_has_no_floor(world, form):
    out = _file(_filing(world, form=form), "2026-03-30")
    assert out["success"] is True and out["data"]["filed_date"] == "2026-03-30", (form, out)


@pytest.mark.parametrize("year", [None, "", "2025-99", "not-a-year"])
def test_a_filing_whose_year_is_not_a_year_is_not_judged_on_it(world, year):
    out = _file(_filing(world, fy=year), "2026-03-30")
    assert out["success"] is True, out


def test_the_date_that_is_stored_is_the_cleaned_one(world):
    """Spaces round a typed date are not part of it: what the rule judged is what the column holds."""
    filing = _filing(world)
    out = _file(filing, "  2026-06-15  ")
    assert out["success"] is True and out["data"]["filed_date"] == "2026-06-15"
    assert next(f for f in world.rows("mca_filings") if f["id"] == filing["id"])["filed_date"] == "2026-06-15"


def test_a_status_change_without_a_date_is_untouched(world):
    filing = _filing(world, status="not_started")
    out = mw.update_filing_status(filing["id"], mw.UpdateFilingStatusRequest(status="in_progress", ca_approved=True), current_user=USER)
    assert out["success"] is True and out["data"]["status"] == "in_progress"


def test_the_complete_route_stamps_today_and_is_judged_like_any_other_date(world):
    """`PUT .../complete` fills in today when none is given, so a filing for a year that has not ended is refused there too."""
    filing = _filing(world, fy="2030-31")
    out = mw.complete_filing(filing["id"], mw.UpdateFilingStatusRequest(status="filed", ca_approved=True, srn="T1"), current_user=USER)
    assert out["success"] is False and "cannot have been filed before the year ended on 2031-03-31" in out["error"], out


# ── one rule, asked by both doors ────────────────────────────────────────────

@pytest.mark.parametrize("year, day, expected", [
    ("2025-26", "2026-03-30", "2026-03-31"), ("2025-26", "2026-03-31", None), ("2025-26", "2026-04-01", None),
    ("2025-26", "2026-03-30T10:00:00+00:00", "2026-03-31"), ("2025-26", "2026-03-31T10:00:00+00:00", None),
    ("not-a-year", "2000-01-01", None), (None, "2000-01-01", None), ("", "2000-01-01", None), ("2025-99", "2000-01-01", None),
])
def test_the_year_end_rule(year, day, expected):
    assert crs.year_end_not_yet_reached_on(year, day) == expected


def test_the_itr_acknowledgement_and_the_mca_door_judge_the_same_day_alike(world):
    from fastapi import HTTPException
    for day in ("2026-03-30", "2026-03-31", "2026-04-01"):
        itr_refused = False
        try:
            itr._filed_after_the_year_it_declares(FY, day)
        except HTTPException:
            itr_refused = True
        mca_refused = _file(_filing(world), day)["success"] is False
        assert itr_refused == mca_refused == (day < "2026-03-31"), day
