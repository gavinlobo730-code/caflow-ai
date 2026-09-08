"""
One vocabulary for "filed", and it is public.filings — GST-14.

WHAT WAS WRONG
    Three screens could mark a GST return filed and they disagreed.

    The compliance tracker at /gst wrote filing_status, filed_date and
    arn_number straight into compliance_calendar over PostgREST — single row
    (apps/web/app/gst/page.tsx) and bulk. Three things follow from "straight
    over PostgREST", each worse than the last:

      * rbac() never ran, so a Reviewer could mark a client's GSTR-3B filed;
      * gst_filing_record_service.record_filing never ran, so nothing reached
        public.filings;
      * public.filings is the ONLY table journal_period_lock_reason (migration
        266) reads. A return marked filed from the tracker did NOT lock its
        period — the books could still move under a return already with the
        government, which is the entire thing the lock exists to prevent.

    The client GST workspace, which records a filing properly, showed the same
    return as a draft. Two screens, one return, opposite answers.

WHAT THIS ASSERTS
    That the tracker's mark-filed now goes through the API, writes the filings
    row, and therefore closes the period — and that where it does NOT close a
    period it SAYS SO, per compliance type, rather than ticking silently.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user
from services import period_lock_service

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}


@pytest.fixture
def app_db(monkeypatch):
    import routers.compliance as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    db.seed("firms", {"id": "F1", "name": "F1", "locked_financial_years": []})
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return app, db


def _calendar_row(db, ctype="GSTR3B", start="2026-06-01", end="2026-06-30"):
    return db.seed("compliance_calendar", {
        "id": "CAL1", "firm_id": "F1", "client_id": "C1",
        "compliance_type": ctype, "period_start": start, "period_end": end,
        "due_date": "2026-07-20", "filing_status": "pending",
        "filed_date": None, "arn_number": None})


def _mark(app, body=None):
    return TestClient(app, raise_server_exceptions=False).patch(
        "/api/compliance/calendar/CAL1/filed",
        json=body or {"filed_date": "2026-07-20", "arn": "AA2706260000001"})


# ── the defect ───────────────────────────────────────────────────────────────

def test_marking_a_gstr3b_filed_closes_its_period(app_db):
    """THE FINDING. Before this the tick wrote three columns on a calendar row
    and nothing else; the June books stayed editable under a June return that
    was already at the portal."""
    app, db = app_db
    _calendar_row(db)
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15") is None

    r = _mark(app)

    assert r.status_code == 200, r.text
    assert r.json()["data"]["filing_recorded"] is True
    reason = period_lock_service.lock_reason(db, "F1", "C1", "2026-06-15")
    assert reason is not None and "GSTR-3B" in reason


def test_the_filings_row_is_what_the_lock_reads(app_db):
    app, db = app_db
    _calendar_row(db)

    _mark(app)

    rows = db.rows("filings")
    assert len(rows) == 1
    row = rows[0]
    assert row["filing_type"] == "GSTR-3B"
    assert row["client_id"] == "C1"
    assert row["filed_date"] == "2026-07-20"
    assert row["period_start"] == "2026-06-01" and row["period_end"] == "2026-06-30"
    assert row["acknowledgement_number"] == "AA2706260000001"


def test_the_calendar_row_is_still_updated(app_db):
    """The tracker keeps working — this replaces HOW the tick is recorded, not
    the tick."""
    app, db = app_db
    _calendar_row(db)

    _mark(app)

    row = db.rows("compliance_calendar")[0]
    assert row["filing_status"] == "filed"
    assert row["filed_date"] == "2026-07-20"
    assert row["arn_number"] == "AA2706260000001"


def test_a_gstr1_tick_records_a_gstr1_filing(app_db):
    app, db = app_db
    _calendar_row(db, ctype="GSTR1")

    _mark(app)

    assert db.rows("filings")[0]["filing_type"] == "GSTR-1"


def test_marking_it_twice_leaves_one_filing_row(app_db):
    """Two rows claiming the same filing is a lie about the world, and the CA
    reads this table. record_filing is idempotent on (client, type, period)."""
    app, db = app_db
    _calendar_row(db)

    _mark(app)
    _mark(app, {"filed_date": "2026-07-21", "arn": "AA2706260000002"})

    rows = db.rows("filings")
    assert len(rows) == 1
    assert rows[0]["filed_date"] == "2026-07-21"


# ── a quarter is a quarter ───────────────────────────────────────────────────

def test_a_qrmp_quarter_locks_the_whole_quarter(app_db):
    """The calendar stores a QRMP obligation's real period. Deriving a MONTH
    from period_start would lock April and leave May and June — two filed
    months — editable, silently."""
    app, db = app_db
    _calendar_row(db, ctype="GSTR1", start="2026-04-01", end="2026-06-30")

    _mark(app, {"filed_date": "2026-07-13", "arn": "AA2706260000009"})

    for day in ("2026-04-15", "2026-05-15", "2026-06-15"):
        assert period_lock_service.lock_reason(db, "F1", "C1", day) is not None, day
    assert period_lock_service.lock_reason(db, "F1", "C1", "2026-07-15") is None


# ── what it deliberately does NOT lock, said out loud ────────────────────────

def test_a_gstr9_tick_is_recorded_and_says_it_locked_nothing(app_db):
    """GSTR-9 is the annual return. Furnishing it closes the CORRECTION WINDOW
    under §37(3)/§39(9)/§16(4) — compliance_engine.correction_window_closes()
    — which is a different rule; recording it here would freeze a whole
    financial year. The tick is real, the silence would not be."""
    app, db = app_db
    _calendar_row(db, ctype="GSTR9", start="2025-04-01", end="2026-03-31")

    # Filed EARLY, which is a real thing and the reason §16(4)'s window closes
    # at the earlier of 30 November and the date GSTR-9 was furnished. The date
    # is also in the past, because a filing date is a fact about the past and
    # the endpoint refuses a future one.
    r = _mark(app, {"filed_date": "2026-08-31", "arn": "AA2708260000001"})

    body = r.json()["data"]
    assert body["filing_recorded"] is False
    assert "annual return" in body["filing_not_recorded_reason"]
    assert "correction" in body["filing_not_recorded_reason"].lower()
    assert db.rows("filings") == []
    assert db.rows("compliance_calendar")[0]["filing_status"] == "filed"


def test_a_non_gst_obligation_says_why_too(app_db):
    app, db = app_db
    _calendar_row(db, ctype="TDS26Q")

    body = _mark(app).json()["data"]

    assert body["filing_recorded"] is False
    assert "TDS" in body["filing_not_recorded_reason"]


# ── the disagreement is reported, not hidden ─────────────────────────────────

def test_a_prepared_return_still_in_draft_is_reported_back(app_db):
    """The contradiction GST-14 names. Resolving it from here would mean
    approving a return without the Manager+ role and explicit ca_approved the
    workspace endpoint requires (CGST §37) — so it is SHOWN instead."""
    app, db = app_db
    _calendar_row(db)
    db.seed("gstr3b_returns", {"id": "R1", "firm_id": "F1", "client_id": "C1",
                               "period": "062026", "status": "draft"})

    body = _mark(app).json()["data"]

    assert body["workspace_return"] == {
        "id": "R1", "period": "062026", "status": "draft",
        "table": "gstr3b_returns"}


def test_a_return_already_submitted_there_is_not_reported(app_db):
    """No disagreement, nothing to say."""
    app, db = app_db
    _calendar_row(db)
    db.seed("gstr3b_returns", {"id": "R1", "firm_id": "F1", "client_id": "C1",
                               "period": "062026", "status": "submitted"})

    assert _mark(app).json()["data"]["workspace_return"] is None


# ── scope ────────────────────────────────────────────────────────────────────

def test_another_firms_row_is_not_found(app_db):
    app, db = app_db
    db.seed("compliance_calendar", {
        "id": "CAL1", "firm_id": "F2", "client_id": "C9",
        "compliance_type": "GSTR3B", "period_start": "2026-06-01",
        "period_end": "2026-06-30", "due_date": "2026-07-20",
        "filing_status": "pending"})

    assert _mark(app).status_code == 404
    assert db.rows("filings") == []


# ── the date is validated at the boundary ────────────────────────────────────

def test_a_malformed_filed_date_is_refused_before_it_reaches_the_column(app_db):
    """filings.filed_date is a DATE column. Without the shape check a typo is a
    500 out of Postgres rather than a 422 the CA can act on."""
    app, db = app_db
    _calendar_row(db)

    r = _mark(app, {"filed_date": "20-07-2026", "arn": "AA1"})

    assert r.status_code == 422
    assert db.rows("filings") == []
    assert db.rows("compliance_calendar")[0]["filing_status"] == "pending"


def test_a_filing_date_in_the_future_is_refused(app_db):
    """A return cannot have been filed tomorrow, and this is the field the
    audit reads to say when it went."""
    app, db = app_db
    _calendar_row(db)

    r = _mark(app, {"filed_date": "2099-07-20", "arn": "AA1"})

    assert r.status_code == 422
    assert db.rows("filings") == []
