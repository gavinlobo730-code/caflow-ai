"""
A GSTR-1 or GSTR-3B is recorded as filed on the date the CA STATED, never on
the day somebody got round to recording it (PRE-A-007).

WHAT WAS WRONG
    `gst_filing_record_service.record_filing` did
    `filed_date = filed_date or ist_today()`, and the two GST workspace screens
    (`markGSTR1Filed`, `markGSTR3BFiled`) sent no date at all. `filings.filed_date`
    is what `journal_period_lock_reason` quotes in its lock message and what the
    s.37(3) / s.39(9) / s.16(4) correction window is measured from, so a return
    filed on the portal on the 11th and recorded here on the 14th was stamped the
    14th: a date the software invented, presented as a fact about the portal.
    The compliance door (`compliance_record_service._filed_date_for`, gst-27)
    has required the date since; the workspace doors had not.

WHAT THIS ASSERTS
    * `record_filing` REFUSES a GSTR-1 or GSTR-3B with no date, a malformed one,
      one in the future and one before the period it declares ended, with the
      compliance door's own wording, and writes nothing. The set of returns it
      applies to is DERIVED from the map that says which returns lock a period,
      so a third return added to that map is covered the day it is added.
    * Any other filing type keeps today's behaviour (the date is a convenience
      there, because it closes no period).
    * Both status routes ask BEFORE the status moves. `record_filing` is called
      inside a `try` that logs and carries on, so a refusal raised from in there
      would be swallowed after the return had already moved to submitted: Filed,
      with no `filings` row and so no lock. The route refuses first, in the
      envelope every other refusal in these two routes uses, and the return is
      left exactly as it was.
    * A QRMP quarter is judged on the QUARTER's end (Rule 61A with the proviso
      to s.39(1)), not its first month's.
    * The calendar door (`PATCH /api/compliance/calendar/{id}/filed`) refuses a
      pre-period date BEFORE it writes the calendar row, for the same reason.
    * Every status other than "submitted" is unaffected: approving a return does
      not need a filing date, because nothing has been filed.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.gst_workspace as gw
from core.auth import get_current_user
from core.exceptions import ValidationError
from core.ist_clock import ist_today
from domain.gst import registrations
from services import gst_filing_record_service as filings
from services import period_lock_service
from services.gst_filing_record_service import (
    FILING_TYPE_FOR_RETURN, FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B,
    FiledDateRefused, record_filing,
)
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}
GSTIN = "27AAPFU0939F1ZV"       # checksum-valid (tests/fixtures/gstin.json)
JUNE = "062026"                 # June 2026 ends on 30 June 2026
LOCKING_TYPES = sorted(FILING_TYPE_FOR_RETURN.values())


# ══════════════════════════════════════════════════════════════════════════════
# record_filing — the one place a `filings` row is written
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def db():
    return FakeDB()


def _record(db, filing_type, **kw):
    kw.setdefault("period", JUNE)
    return record_filing(db, firm_id=FIRM, client_id=CLIENT,
                         filing_type=filing_type, **kw)


@pytest.mark.parametrize("filing_type", LOCKING_TYPES)
@pytest.mark.parametrize("missing", [None, "", "   "], ids=["none", "empty", "blank"])
def test_a_return_that_locks_a_period_is_not_recorded_without_its_date(
        db, filing_type, missing):
    with pytest.raises(FiledDateRefused) as e:
        _record(db, filing_type, filed_date=missing)

    assert "Say the date" in e.value.sentence and filing_type in e.value.sentence
    assert db.rows("filings") == [], "a row was written with an invented date"


@pytest.mark.parametrize("filing_type", LOCKING_TYPES)
def test_the_date_the_ca_stated_is_the_date_recorded(db, filing_type):
    row = _record(db, filing_type, filed_date="2026-07-11")

    assert row["filed_date"] == "2026-07-11"
    assert db.rows("filings")[0]["filed_date"] == "2026-07-11"
    assert ist_today().isoformat() != "2026-07-11", \
        "the premise: the stated date differs from today, or this proves nothing"


def test_the_returns_that_need_a_date_are_the_returns_that_lock_a_period():
    """Derived from the one map, so the set cannot drift from it."""
    assert filings.FILING_TYPES_THAT_LOCK_A_PERIOD == frozenset(FILING_TYPE_FOR_RETURN.values())
    assert {FILING_TYPE_GSTR1, FILING_TYPE_GSTR3B} <= filings.FILING_TYPES_THAT_LOCK_A_PERIOD


@pytest.mark.parametrize("filing_type", ["GSTR-9", "TDS-26Q", "ITR"])
def test_any_other_filing_type_keeps_todays_behaviour(db, filing_type):
    """It closes no period, so the date is a convenience there: omitted, today
    is recorded, exactly as before this change."""
    row = _record(db, filing_type, filed_date=None)

    assert row["filed_date"] == ist_today().isoformat()


@pytest.mark.parametrize("bad", ["11/07/2026", "2026-13-01", "2026-02-30", "yesterday"])
def test_a_malformed_date_is_refused_with_the_compliance_doors_wording(db, bad):
    with pytest.raises(FiledDateRefused) as e:
        _record(db, FILING_TYPE_GSTR3B, filed_date=bad)

    assert e.value.sentence == "filed_date must be YYYY-MM-DD"
    assert db.rows("filings") == []


def test_a_date_in_the_future_is_refused(db):
    with pytest.raises(FiledDateRefused) as e:
        _record(db, FILING_TYPE_GSTR1, filed_date="2999-01-01")

    assert e.value.sentence == "filed_date cannot be in the future"
    assert db.rows("filings") == []


def test_a_return_cannot_have_been_filed_before_its_period_ended(db):
    with pytest.raises(FiledDateRefused) as e:
        _record(db, FILING_TYPE_GSTR3B, filed_date="2026-06-29")

    assert "before the period it declares ended on 2026-06-30" in e.value.sentence
    assert db.rows("filings") == []


def test_the_last_day_of_the_period_is_not_before_it(db):
    """The compliance door's test is `filed < period_end`, and this mirrors it."""
    assert _record(db, FILING_TYPE_GSTR3B, filed_date="2026-06-30")["filed_date"] == "2026-06-30"


def test_a_qrmp_quarter_is_judged_on_the_end_of_the_quarter(db):
    """Rule 61A with the proviso to s.39(1): a quarterly return declares three
    months. A date after April but before the quarter's end is a monthly
    filer's June return and a quarterly filer's impossibility."""
    june_2025 = "062025"
    with pytest.raises(FiledDateRefused):
        _record(db, FILING_TYPE_GSTR1, period=june_2025, filed_date="2025-05-20",
                frequency=registrations.QUARTERLY)

    row = _record(db, FILING_TYPE_GSTR1, period=june_2025, filed_date="2025-07-13",
                  frequency=registrations.QUARTERLY)
    assert (row["period_start"], row["period_end"]) == ("2025-04-01", "2025-06-30")


def test_recorded_bounds_are_what_a_date_is_judged_against(db):
    """The compliance calendar stores a QRMP obligation's real window."""
    with pytest.raises(FiledDateRefused):
        _record(db, FILING_TYPE_GSTR1, filed_date="2026-05-20",
                bounds=("2026-04-01", "2026-06-30"))
    assert _record(db, FILING_TYPE_GSTR1, filed_date="2026-07-13",
                   bounds=("2026-04-01", "2026-06-30"))["filed_date"] == "2026-07-13"


def test_a_refusal_is_a_validation_error_on_filed_date():
    """So the obligation door's `except ValidationError` maps it to 422 as it
    does the same refusal from `_filed_date_for`."""
    err = FiledDateRefused("x")
    assert isinstance(err, ValidationError) and err.field == "filed_date"


def test_idempotent_refiling_still_keeps_one_row_and_the_latest_stated_date(db):
    _record(db, FILING_TYPE_GSTR1, filed_date="2026-07-11")
    _record(db, FILING_TYPE_GSTR1, filed_date="2026-07-12")

    assert [r["filed_date"] for r in db.rows("filings")] == ["2026-07-12"]


# ══════════════════════════════════════════════════════════════════════════════
# the two GST workspace status routes
# ══════════════════════════════════════════════════════════════════════════════

ROUTES = [
    ("gstr1", gw.update_gstr1_status, "gstr1_returns", FILING_TYPE_GSTR1),
    ("gstr3b", gw.update_gstr3b_status, "gstr3b_returns", FILING_TYPE_GSTR3B),
]


@pytest.fixture
def world(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [gw])
    d.seed("clients", {
        "id": CLIENT, "firm_id": FIRM, "client_name": "Acme Industries",
        "legal_name": "Acme Industries Private Limited",
        "gstin": GSTIN, "state_code": "27",
        "gst_filing_frequency": "monthly", "gst_registration_date": None,
        "gst_registration_type": None, "composition_category": None,
    })
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    return d


def _save(kind):
    if kind == "gstr1":
        return gw.save_gstr1(gw.SaveGSTR1Request(
            client_id=CLIENT, period=JUNE, gstin=GSTIN,
            payload_json={"b2b": []}, summary_json={},
            total_taxable_paise=10_000_00), current_user=USER)["data"]
    return gw.save_gstr3b(gw.SaveGSTR3BRequest(
        client_id=CLIENT, period=JUNE, gstin=GSTIN, payload_json={},
        summary_json={}, tax_liability_paise=10_000_00,
        itc_claimed_paise=2_000_00, net_tax_paise=8_000_00),
        current_user=USER)["data"]


def _submit(fn, return_id, **kw):
    return fn(return_id, gw.UpdateStatusRequest(
        status="submitted", ca_approved=True, acknowledge_stale=True, **kw),
        current_user=USER)


def _row(db, table, return_id):
    return [r for r in db.rows(table) if r["id"] == return_id][0]


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
def test_submitting_without_a_date_is_refused_and_nothing_moves(world, kind, fn, table, ftype):
    saved = _save(kind)

    out = _submit(fn, saved["id"], arn="AA270626123456A")

    assert out["success"] is False
    assert "Say the date" in out["error"] and ftype in out["error"]
    row = _row(world, table, saved["id"])
    assert row["status"] == "draft", "the status moved on a refused request"
    assert not row.get("submitted_at") and not row.get("arn"), "partly recorded"
    assert world.rows("filings") == [], "a lock was written for an invented date"


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
def test_submitting_with_a_date_records_the_filing_under_that_date(world, kind, fn, table, ftype):
    saved = _save(kind)

    out = _submit(fn, saved["id"], arn="AA270626123456A", filed_date="2026-07-11")

    assert out["success"] is True
    assert _row(world, table, saved["id"])["status"] == "submitted"
    (f,) = world.rows("filings")
    assert f["filing_type"] == ftype and f["filed_date"] == "2026-07-11"
    assert f["period_start"] == "2026-06-01" and f["period_end"] == "2026-06-30"
    assert ist_today().isoformat() != "2026-07-11", "the premise: not today's date"
    # ...and the lock quotes the date the CA stated.
    reason = period_lock_service.lock_reason(world, FIRM, CLIENT, "2026-06-15")
    assert reason is not None and "11 Jul 2026" in reason


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
@pytest.mark.parametrize("bad,fragment", [
    ("11/07/2026", "YYYY-MM-DD"),
    ("2999-01-01", "future"),
    ("2026-06-10", "before the period it declares ended on 2026-06-30"),
], ids=["malformed", "future", "before-the-period-ended"])
def test_a_date_that_cannot_be_true_is_refused_before_the_status_moves(
        world, kind, fn, table, ftype, bad, fragment):
    saved = _save(kind)

    out = _submit(fn, saved["id"], filed_date=bad)

    assert out["success"] is False and fragment in out["error"]
    assert _row(world, table, saved["id"])["status"] == "draft"
    assert world.rows("filings") == []


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
def test_approving_needs_no_filing_date_because_nothing_has_been_filed(
        world, kind, fn, table, ftype):
    saved = _save(kind)

    out = fn(saved["id"], gw.UpdateStatusRequest(
        status="ca_approved", ca_approved=True, acknowledge_stale=True),
        current_user=USER)

    assert out["success"] is True
    assert _row(world, table, saved["id"])["status"] == "ca_approved"
    assert world.rows("filings") == []


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
def test_a_date_sent_with_a_status_that_files_nothing_is_not_judged(
        world, kind, fn, table, ftype):
    """A stale field in the body must neither stamp a filing nor refuse an
    approval: the date is read on the move to submitted and on no other."""
    saved = _save(kind)

    out = fn(saved["id"], gw.UpdateStatusRequest(
        status="ca_approved", ca_approved=True, acknowledge_stale=True,
        filed_date="not a date"), current_user=USER)

    assert out["success"] is True and world.rows("filings") == []


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
def test_a_return_the_caller_may_not_see_is_not_found_before_the_date_is_asked(
        world, kind, fn, table, ftype):
    """The date is asked after the read, so a missing or foreign return reads
    as 'Not found' whatever the request carried."""
    out = _submit(fn, "no-such-return")

    assert out == {"success": False, "data": None, "error": "Not found"}


@pytest.mark.parametrize("kind,fn,table,ftype", ROUTES, ids=[r[0] for r in ROUTES])
def test_the_refusal_is_the_same_in_mock_mode(monkeypatch, kind, fn, table, ftype):
    """No database at all: the route refuses on the request, not on a table."""
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    gw._MOCK_GSTR1.clear()
    gw._MOCK_GSTR3B.clear()
    store = gw._MOCK_GSTR1 if kind == "gstr1" else gw._MOCK_GSTR3B
    store["R1"] = {"id": "R1", "firm_id": FIRM, "client_id": CLIENT,
                   "period": JUNE, "gstin": GSTIN, "status": "ca_approved"}
    monkeypatch.setattr(gw, "_visible_or_none", lambda user, rec: rec)

    refused = _submit(fn, "R1")
    assert refused["success"] is False and "Say the date" in refused["error"]
    assert store["R1"]["status"] == "ca_approved"

    filed = _submit(fn, "R1", filed_date="2026-07-11")
    assert filed["success"] is True and store["R1"]["status"] == "submitted"
    store.clear()


def test_a_qrmp_return_is_judged_on_its_quarter_through_the_route(world):
    """The registration's own frequency decides the period the date is judged
    against, so a quarterly GSTR-1 cannot be filed in the quarter's second
    month. The frequency rides on the CLIENT's primary registration."""
    for row in world.rows("clients"):
        row["gst_filing_frequency"] = "quarterly"
    saved = gw.save_gstr1(gw.SaveGSTR1Request(
        client_id=CLIENT, period="062025", gstin=GSTIN,
        payload_json={"b2b": []}, summary_json={}, total_taxable_paise=10_000_00),
        current_user=USER)["data"]

    early = _submit(gw.update_gstr1_status, saved["id"], filed_date="2025-05-20")
    assert early["success"] is False and "2025-06-30" in early["error"]
    assert _row(world, "gstr1_returns", saved["id"])["status"] == "draft"

    ok = _submit(gw.update_gstr1_status, saved["id"], filed_date="2025-07-13")
    assert ok["success"] is True
    (f,) = world.rows("filings")
    assert (f["period_start"], f["period_end"], f["filed_date"]) == \
        ("2025-04-01", "2025-06-30", "2025-07-13")


# ══════════════════════════════════════════════════════════════════════════════
# the calendar door — refused before the calendar row is written
# ══════════════════════════════════════════════════════════════════════════════

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}


@pytest.fixture
def calendar(monkeypatch):
    import routers.compliance as mod
    d = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: d)
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    d.seed("firms", {"id": "F1", "name": "F1", "locked_financial_years": []})
    d.seed("compliance_calendar", {
        "id": "CAL1", "firm_id": "F1", "client_id": "C1",
        "compliance_type": "GSTR3B", "period_start": "2026-06-01",
        "period_end": "2026-06-30", "due_date": "2026-07-20",
        "filing_status": "pending", "filed_date": None, "arn_number": None})
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False), d


def test_the_calendar_door_refuses_a_pre_period_date_and_writes_nothing(calendar):
    client, d = calendar

    r = client.patch("/api/compliance/calendar/CAL1/filed",
                     json={"filed_date": "2026-06-10", "arn": "AA1"})

    assert r.status_code == 422, r.text
    assert "before the period it declares ended on 2026-06-30" in r.text
    assert d.rows("compliance_calendar")[0]["filing_status"] == "pending", \
        "the tick was recorded and the period was not locked"
    assert d.rows("filings") == []


def test_the_calendar_door_still_records_a_date_after_the_period(calendar):
    client, d = calendar

    r = client.patch("/api/compliance/calendar/CAL1/filed",
                     json={"filed_date": "2026-07-20", "arn": "AA1"})

    assert r.status_code == 200, r.text
    assert d.rows("filings")[0]["filed_date"] == "2026-07-20"
