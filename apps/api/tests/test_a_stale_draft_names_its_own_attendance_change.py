"""GET /api/payroll/runs/{run_id}/slips says when a draft's attendance has
moved since the slip was computed (apex-payroll-yearend-04, the code half).

WHAT WAS WRONG
    `attendance` can be entered or corrected for a wage month AFTER that
    month's payroll run was computed — a confirmed real case: a slip
    generated with `days_present=26` while the matching attendance record was
    entered later showing 24. Nothing on the Register tab said the slip no
    longer matched the attendance behind it; `recomputeRun()` was a manual
    button with no prompt telling a CA it was needed.

WHAT THIS PINS
    `_stamp_attendance_staleness` marks each slip
    `attendance_changed_since_compute` — True only when this employee's
    attendance row for the SAME wage month was entered or amended (
    `attendance.entered_at`, falling back to `created_at` for a row that
    predates migration 326) strictly AFTER the slip's own `created_at`.

    ONLY FOR A RUN STILL DRAFT OR REVIEW. A finalised or paid run is
    immutable (PAY-04/PAY-21) and recompute is refused on it outright, so the
    flag would name a staleness nothing can act on — every slip on a released
    run reads False regardless of what attendance says.
"""
from __future__ import annotations

import routers.payroll as pay
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-STALE"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}


def _db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pay])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme"})
    return db


def _run_and_slip(db, *, status="draft", slip_created_at="2026-09-01T10:00:00+00:00"):
    db.seed("payroll_runs", {"id": "R1", "firm_id": FIRM, "client_id": "CLI",
                            "month": "2026-09", "status": status})
    db.seed("payroll_employees", {"id": "E1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Asha", "status": "active"})
    db.seed("payroll_slips", {"id": "S1", "run_id": "R1", "employee_id": "E1",
                             "gross_paise": 5_000_000, "net_paise": 4_500_000,
                             "created_at": slip_created_at})


# ── the unit: _stamp_attendance_staleness ────────────────────────────────────

def test_attendance_entered_after_the_slip_flags_it(monkeypatch):
    db = _db(monkeypatch)
    run = {"month": "2026-09", "status": "draft"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 24,
                          "entered_at": "2026-09-05T09:00:00+00:00"})
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is True


def test_attendance_entered_before_the_slip_does_not_flag_it(monkeypatch):
    db = _db(monkeypatch)
    run = {"month": "2026-09", "status": "draft"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-05T10:00:00+00:00"}]
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 26,
                          "entered_at": "2026-09-01T09:00:00+00:00"})
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is False


def test_a_row_with_no_entered_at_falls_back_to_created_at(monkeypatch):
    """A row that predates migration 326 carries no author and no entered_at."""
    db = _db(monkeypatch)
    run = {"month": "2026-09", "status": "draft"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 24, "entered_at": None,
                          "created_at": "2026-09-05T09:00:00+00:00"})
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is True


def test_no_attendance_row_at_all_is_not_flagged(monkeypatch):
    db = _db(monkeypatch)
    run = {"month": "2026-09", "status": "draft"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is False


def test_a_released_run_is_never_flagged_however_stale_attendance_is(monkeypatch):
    """PAY-04/PAY-21: a finalised or paid run is immutable and recompute is
    refused on it — the flag must not point at an action that does not exist."""
    db = _db(monkeypatch)
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 24,
                          "entered_at": "2026-12-01T09:00:00+00:00"})
    for status in ("finalized", "paid"):
        slips[0].pop("attendance_changed_since_compute", None)
        pay._stamp_attendance_staleness(db, {"month": "2026-09", "status": status}, slips)
        assert slips[0]["attendance_changed_since_compute"] is False, status


def test_a_review_run_is_still_asked_since_it_is_not_yet_released(monkeypatch):
    db = _db(monkeypatch)
    run = {"month": "2026-09", "status": "review"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 24,
                          "entered_at": "2026-09-05T09:00:00+00:00"})
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is True


def test_another_employees_attendance_does_not_flag_this_one(monkeypatch):
    db = _db(monkeypatch)
    run = {"month": "2026-09", "status": "draft"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    db.seed("attendance", {"employee_id": "E2", "year": 2026, "month": 9,
                          "days_present": 24,
                          "entered_at": "2026-09-05T09:00:00+00:00"})
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is False


def test_an_unparseable_month_refuses_to_flag_rather_than_crashing(monkeypatch):
    db = _db(monkeypatch)
    run = {"month": "not-a-month", "status": "draft"}
    slips = [{"employee_id": "E1", "created_at": "2026-09-01T10:00:00+00:00"}]
    pay._stamp_attendance_staleness(db, run, slips)
    assert slips[0]["attendance_changed_since_compute"] is False


# ── the endpoint, end to end ──────────────────────────────────────────────────

def test_the_endpoint_serves_the_flag_on_a_draft_run(monkeypatch):
    db = _db(monkeypatch)
    _run_and_slip(db, status="draft")
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 24,
                          "entered_at": "2026-09-05T09:00:00+00:00"})
    data = pay.get_run_slips("R1", CALLER)["data"]
    assert len(data) == 1
    assert data[0]["attendance_changed_since_compute"] is True


def test_the_endpoint_serves_false_when_nothing_changed(monkeypatch):
    db = _db(monkeypatch)
    _run_and_slip(db, status="draft")
    data = pay.get_run_slips("R1", CALLER)["data"]
    assert data[0]["attendance_changed_since_compute"] is False


def test_the_endpoint_never_flags_a_finalized_run(monkeypatch):
    db = _db(monkeypatch)
    _run_and_slip(db, status="finalized")
    db.seed("attendance", {"employee_id": "E1", "year": 2026, "month": 9,
                          "days_present": 24,
                          "entered_at": "2026-12-25T09:00:00+00:00"})
    data = pay.get_run_slips("R1", CALLER)["data"]
    assert data[0]["attendance_changed_since_compute"] is False
