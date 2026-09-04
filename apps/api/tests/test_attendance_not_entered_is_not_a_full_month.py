"""
"Nobody told us" and "a human confirmed a full month" are different facts.

WHAT WAS WRONG
    The run read attendance per employee and fell through to a default:

        attendance = (att_res.data or [None])[0]
        working_days = (attendance or {}).get("working_days", 26)
        days_present = (attendance or {}).get("days_present", 26)
        lop_days     = (attendance or {}).get("lop_days", 0)

    public.attendance's own columns default to 26 as well (migration 027). So a
    client who had sent NOTHING produced a run that paid every employee a full
    month, and a slip indistinguishable from one somebody had confirmed. The
    payslip PDF then printed "Working Days 26 / Days Present 26" to the
    employee as fact.

    It failed silently and in the employee's FAVOUR, which is the direction
    nobody reports. And it compounded with the ECR: a full-month default means
    no loss of pay, so NCP_DAYS = 0 looked consistent with the slip behind it.

WHAT IT DOES NOW
    The slip records `attendance_entered` (migration 324, nullable — see there
    for why there is no default), and the run returns `attendance_gaps` naming
    every employee nobody entered anything for.

    It WARNS rather than blocks, matching statutory_gaps exactly. A run is a
    draft: nothing is posted, nothing is paid, no journal exists until
    Finalize. Refusing to compute would stop a CA seeing the very figures that
    tell them what is missing.

NEGATIVE CONTROL
    Restore the per-employee read and drop the flag, and
    test_a_slip_records_that_nobody_entered_attendance and
    test_the_run_names_every_employee_nobody_entered_attendance_for both fail —
    the first with KeyError, the second because the list is absent.
"""
from __future__ import annotations

import pytest

import routers.payroll as pr


# ── the sentence ─────────────────────────────────────────────────────────────

def test_no_gap_when_attendance_was_entered():
    assert pr._attendance_gap({"name": "Asha"}, True) == []


def test_the_gap_names_the_employee_and_what_was_assumed():
    [gap] = pr._attendance_gap({"name": "Asha"}, False)
    assert gap.startswith("Asha:")
    assert "no attendance entered" in gap
    # The sentence has to say what the run DID, not merely that something is
    # missing — the whole defect is that a full month was paid quietly.
    assert "full month" in gap and "26-day default" in gap


def test_the_gap_falls_back_to_an_id_when_there_is_no_name():
    [gap] = pr._attendance_gap({"id": "emp-7"}, False)
    assert gap.startswith("emp-7:")


# ── the slip ─────────────────────────────────────────────────────────────────

def _emp(**kw):
    base = {"id": "e1", "name": "Asha", "basic_paise": 5000000,
            "hra_percent": 0.0, "da_percent": 0.0,
            "pf_applicable": False, "esi_applicable": False, "pt_applicable": False}
    base.update(kw)
    return base


def test_a_slip_with_no_attendance_still_computes_a_full_month():
    """The BEHAVIOUR is deliberately unchanged — this fix is about saying so,
    not about paying people differently. Changing the number as well would
    have been a silent pay cut on the same commit."""
    slip = pr._compute_slip(_emp(), None)
    assert slip["working_days"] == 26
    assert slip["days_present"] == 26
    assert slip["lop_days"] == 0
    assert slip["gross_paise"] == 5000000


def test_an_entered_attendance_row_is_still_honoured():
    slip = pr._compute_slip(_emp(), {"working_days": 26, "days_present": 24, "lop_days": 2})
    assert slip["days_present"] == 24
    assert slip["lop_days"] == 2
    assert slip["gross_paise"] < 5000000, "two days of loss of pay must reduce the gross"


# ── the run ──────────────────────────────────────────────────────────────────
#
# The attendance seeds carry firm_id because public.attendance requires it
# (NOT NULL, migration 027) and the run's read filters on it. That filter was
# added with migration 326: the ids were already firm-scoped, but the
# service-role key bypasses RLS and CLAUDE.md makes the app-layer firm filter
# the primary isolation control, not an optimisation.

import routers.payroll as payroll_mod  # noqa: E402
from tests.e2e_harness import FakeDB, wire_e2e  # noqa: E402

FIRM = "FIRM-ATT"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}


def _run_db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    return db


def _seed_employee(db, name, emp_id):
    return db.seed("payroll_employees", {
        "id": emp_id, "firm_id": FIRM, "client_id": "CLI", "name": name,
        "basic_paise": 5000000, "hra_percent": 0.0, "da_percent": 0.0,
        "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
        "special_allowance_paise": 0, "pf_applicable": False,
        "esi_applicable": False, "pt_applicable": False,
        "is_active": True, "status": "active",
    })


def test_the_run_names_every_employee_nobody_entered_attendance_for(monkeypatch):
    db = _run_db(monkeypatch)
    _seed_employee(db, "Asha", "e-asha")
    _seed_employee(db, "Bikram", "e-bikram")
    # Only Asha has attendance. Bikram is the silent full month.
    db.seed("attendance", {"firm_id": FIRM, "employee_id": "e-asha",
                           "month": 6, "year": 2026,
                           "working_days": 26, "days_present": 24, "lop_days": 2})

    out = payroll_mod.create_run(
        payroll_mod.PayrollRunIn(client_id="CLI", month="2026-06"), CALLER)
    assert out["success"] is True

    gaps = out["data"]["attendance_gaps"]
    assert len(gaps) == 1, f"exactly one employee had nothing entered: {gaps}"
    assert gaps[0].startswith("Bikram:")


def test_a_slip_records_that_nobody_entered_attendance(monkeypatch):
    db = _run_db(monkeypatch)
    _seed_employee(db, "Asha", "e-asha")
    _seed_employee(db, "Bikram", "e-bikram")
    db.seed("attendance", {"firm_id": FIRM, "employee_id": "e-asha",
                           "month": 6, "year": 2026,
                           "working_days": 26, "days_present": 24, "lop_days": 2})

    payroll_mod.create_run(
        payroll_mod.PayrollRunIn(client_id="CLI", month="2026-06"), CALLER)

    by_emp = {s["employee_id"]: s for s in db.rows("payroll_slips")}
    assert by_emp["e-asha"]["attendance_entered"] is True
    assert by_emp["e-bikram"]["attendance_entered"] is False, (
        "the slip must carry the fact, not just the run's response — the "
        "response is gone as soon as the page reloads")


def test_the_roster_is_read_in_one_query_not_one_per_employee(monkeypatch):
    """The read used to sit inside the per-employee loop, so a 200-employee run
    made 200 sequential round trips to Mumbai. CLAUDE.md's reporting rule is
    about answer size rather than round trips, but the same reasoning applies:
    apps/api runs in Singapore and Postgres is in Mumbai."""
    db = _run_db(monkeypatch)
    for i in range(8):
        _seed_employee(db, f"Employee {i}", f"e-{i}")

    seen = []
    original = db.table

    def counting_table(name):
        seen.append(name)
        return original(name)

    monkeypatch.setattr(db, "table", counting_table)
    payroll_mod.create_run(
        payroll_mod.PayrollRunIn(client_id="CLI", month="2026-06"), CALLER)

    assert seen.count("attendance") == 1, (
        f"eight employees must cost ONE attendance read, not eight: "
        f"{seen.count('attendance')}")
