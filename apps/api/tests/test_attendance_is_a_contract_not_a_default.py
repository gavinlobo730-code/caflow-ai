"""
Attendance is something SOMEBODY ENTERED, and its five numbers have to add up.

WHAT WAS BROKEN — TWO THINGS, AND THE SECOND UNDID A FIX FROM LAST WEEK

app/payroll/attendance/page.tsx was the only writer of public.attendance, and it
wrote straight through PostgREST with nothing on the server in the way.

  1. NOTHING VALIDATED THE NUMBERS. The page computed

         lop = Math.max(0, working_days - days_present - casual - sick - earned)

     so a row whose days added up to MORE than the month contains — 26 present
     plus four days' casual leave in a 26-day month — quietly became zero loss
     of pay and a full month's salary. The floor turned a contradiction into a
     confident number. _compute_slip prorates on `working_days - lop_days`, so
     every rupee on the payslip comes off that line.

  2. SAVE WROTE THE WHOLE ROSTER. The editor seeded a default row (26 working,
     26 present, no leave) for every employee in the FIRM that had none, and
     saveAttendance() upserted `Object.values(attendance)` — touched or not.

     Migration 324 had just given payroll_slips an `attendance_entered` flag so
     a run could name the people nobody had entered anything for, and PR #410
     put those gaps on the screen. One press of Save made a row exist for
     everybody, so the flag read true for everybody, and it asserted that a
     human had confirmed something no human looked at. There was never a gap to
     report again.

WHAT IT DOES NOW

domain/payroll/attendance.py enforces the identity the frontend's own calcLOP
always implied, rather than flooring it:

    days_present + casual + sick + earned + lop = working_days

PUT /api/payroll/attendance writes ONLY the employees in the request, validates
the whole request and refuses the whole request, stamps entered_by/entered_at
(migration 326), and refuses a month whose run is already finalised.

NEGATIVE CONTROL
    Delete domain/payroll/attendance.py and revert the three endpoints: every
    test below fails, most at import. Keep the module but restore the
    `max(0, …)` floor in place of the raise, and the four over-count tests pass
    a full month's pay through.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.payroll import attendance as att
import routers.payroll as pr


# ── the identity ─────────────────────────────────────────────────────────────

def test_loss_of_pay_is_the_remainder_when_it_is_not_sent():
    """The only one of the five that is purely a remainder, so the only one a
    caller may leave out."""
    row = att.build_row({"employee_id": "e", "working_days": 26,
                         "days_present": 22, "casual_leaves": 2},
                        period="2026-08", who="Asha")
    assert row.lop_days == 2
    assert (row.days_present + row.casual_leaves + row.sick_leaves
            + row.earned_leaves + row.lop_days) == row.working_days


def test_paid_leave_is_not_loss_of_pay():
    """Casual, sick and earned leave are paid. Counting them as LOP would cut
    somebody's salary for taking leave they are entitled to."""
    full = att.build_row({"employee_id": "e", "working_days": 26, "days_present": 26},
                         period="2026-08", who="Asha")
    on_leave = att.build_row({"employee_id": "e", "working_days": 26,
                              "days_present": 24, "sick_leaves": 2},
                             period="2026-08", who="Asha")
    assert full.lop_days == on_leave.lop_days == 0


def test_days_that_add_up_to_more_than_the_month_are_refused():
    """THE HEADLINE. calcLOP's Math.max(0, …) made this a full month's pay."""
    with pytest.raises(att.AttendanceError) as e:
        att.build_row({"employee_id": "e", "working_days": 26, "days_present": 26,
                       "casual_leaves": 4}, period="2026-08", who="Asha")
    assert "Asha" in str(e.value)
    assert "more than the 26 working days" in str(e.value)


def test_a_sent_lop_that_contradicts_the_others_is_refused_not_corrected():
    """Silently replacing a number a CA typed is how what is on the screen and
    what is in the table start to disagree."""
    with pytest.raises(att.AttendanceError) as e:
        att.build_row({"employee_id": "e", "working_days": 26, "days_present": 20,
                       "lop_days": 2}, period="2026-08", who="Asha")
    assert "do not add up" in str(e.value)


def test_a_sent_lop_that_agrees_is_kept():
    row = att.build_row({"employee_id": "e", "working_days": 26, "days_present": 20,
                         "casual_leaves": 1, "lop_days": 5},
                        period="2026-08", who="Asha")
    assert row.lop_days == 5


@pytest.mark.parametrize("period,limit", [("2026-02", 28), ("2028-02", 29),
                                          ("2026-04", 30), ("2026-08", 31)])
def test_working_days_cannot_exceed_the_month_it_is_in(period, limit):
    """Bounded by THIS month's length, not by a constant. A 31-day working
    month in February is a typo, and it would prorate everybody's pay."""
    ok = att.build_row({"employee_id": "e", "working_days": limit,
                        "days_present": limit}, period=period, who="Asha")
    assert ok.working_days == limit
    with pytest.raises(att.AttendanceError) as e:
        att.build_row({"employee_id": "e", "working_days": limit + 1,
                       "days_present": limit + 1}, period=period, who="Asha")
    assert f"has {limit} days" in str(e.value)


def test_zero_working_days_is_refused():
    """_compute_slip floors working_days at 1 to avoid dividing by zero —
    because nothing upstream stopped a zero reaching it."""
    with pytest.raises(att.AttendanceError):
        att.build_row({"employee_id": "e", "working_days": 0, "days_present": 0},
                      period="2026-08", who="Asha")


def test_a_negative_day_count_is_refused():
    with pytest.raises(att.AttendanceError) as e:
        att.build_row({"employee_id": "e", "working_days": 26, "days_present": -1},
                      period="2026-08", who="Asha")
    assert "cannot be negative" in str(e.value)


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "26-08", "2026-8", "", None])
def test_a_month_that_is_not_a_month_is_refused(bad):
    """A caller reading int(period[:4]) would take '2026-13' and compute it."""
    with pytest.raises(att.AttendanceError):
        att.parse_month(bad)


# ── the whole request, refused whole ─────────────────────────────────────────

def test_every_problem_in_one_request_is_reported_together():
    """A bulk save covers a roster. Fixing the sheet one refusal at a time is
    forty round trips."""
    with pytest.raises(att.AttendanceError) as e:
        att.build_rows(
            [{"employee_id": "a", "working_days": 26, "days_present": 30},
             {"employee_id": "b", "working_days": 40, "days_present": 40}],
            period="2026-08", names_by_id={"a": "Asha", "b": "Bikram"})
    assert "Asha" in str(e.value) and "Bikram" in str(e.value)


def test_one_bad_row_stops_the_whole_write():
    """A partial write leaves some of a client-month saved and some not — and
    the ones that failed become indistinguishable from the ones nobody
    entered, which is the confusion this module exists to end."""
    with pytest.raises(att.AttendanceError):
        att.build_rows(
            [{"employee_id": "a", "working_days": 26, "days_present": 26},
             {"employee_id": "b", "working_days": 26, "days_present": 99}],
            period="2026-08")


def test_the_same_employee_twice_in_one_request_is_refused():
    """One of the two would silently win, and which one is an accident of
    ordering."""
    with pytest.raises(att.AttendanceError) as e:
        att.build_rows(
            [{"employee_id": "a", "working_days": 26, "days_present": 26},
             {"employee_id": "a", "working_days": 26, "days_present": 20}],
            period="2026-08", names_by_id={"a": "Asha"})
    assert "sent twice" in str(e.value)


def test_an_empty_request_is_refused():
    with pytest.raises(att.AttendanceError):
        att.build_rows([], period="2026-08")


# ── the cut-off ──────────────────────────────────────────────────────────────

def test_no_agreed_cutoff_is_not_the_same_as_being_on_time():
    state = att.cutoff_state("2026-08", None, date(2026, 9, 30))
    assert state == {"agreed": False, "due_on": None,
                     "days_overdue": 0, "overdue": False}


def test_the_cutoff_falls_in_the_month_after_the_payroll_month():
    """Nobody can report September's loss of pay before September happens."""
    assert att.cutoff_state("2026-08", 5, date(2026, 9, 1))["due_on"] == "2026-09-05"


def test_the_cutoff_rolls_into_the_next_year_from_december():
    assert att.cutoff_state("2026-12", 5, date(2027, 1, 1))["due_on"] == "2027-01-05"


def test_overdue_counts_the_days():
    state = att.cutoff_state("2026-08", 5, date(2026, 9, 9))
    assert state["overdue"] is True and state["days_overdue"] == 4


def test_the_cutoff_day_itself_is_not_overdue():
    assert att.cutoff_state("2026-08", 5, date(2026, 9, 5))["overdue"] is False


# ── the endpoints, in mock mode ──────────────────────────────────────────────

CLIENT = "11111111-1111-1111-1111-111111111111"
USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "role": "Partner"}


@pytest.fixture()
def mock_mode(monkeypatch):
    monkeypatch.setattr(pr, "_db", lambda: None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)
    pr._MOCK_ATTENDANCE.clear()
    pr._MOCK_PAYROLL_SETTINGS.clear()
    yield
    pr._MOCK_ATTENDANCE.clear()
    pr._MOCK_PAYROLL_SETTINGS.clear()


def _put(rows, month="2026-08"):
    from models.payroll import AttendanceIn
    return pr.put_attendance(
        AttendanceIn(client_id=CLIENT, month=month, rows=rows), USER)


def test_only_the_employees_sent_are_written(mock_mode):
    """THE SECOND HALF OF THE HEADLINE. The old Save wrote the firm's whole
    roster; this writes two rows because two were sent."""
    res = _put([{"employee_id": "a", "working_days": 26, "days_present": 26},
                {"employee_id": "b", "working_days": 26, "days_present": 24,
                 "casual_leaves": 2}])
    assert res["success"] and res["data"]["saved"] == 2
    assert len(pr._MOCK_ATTENDANCE) == 2


def test_a_refused_row_writes_nothing_at_all(mock_mode):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _put([{"employee_id": "a", "working_days": 26, "days_present": 26},
              {"employee_id": "b", "working_days": 26, "days_present": 40}])
    assert e.value.status_code == 422
    assert pr._MOCK_ATTENDANCE == {}, "the good row must not be written either"


def test_a_saved_row_carries_when_it_was_entered(mock_mode):
    _put([{"employee_id": "a", "working_days": 26, "days_present": 26}])
    [row] = list(pr._MOCK_ATTENDANCE.values())
    assert row["entered_at"], "a figure that decides somebody's pay records when it was set"


def test_the_endpoint_reports_a_bad_month_rather_than_computing_it(mock_mode):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        pr.get_attendance(client_id=CLIENT, month="2026-13", current_user=USER)
    assert e.value.status_code == 422


def test_the_cutoff_is_patch_shaped_and_clears_explicitly(mock_mode):
    from models.payroll import PayrollSettingsIn
    pr.put_payroll_settings(PayrollSettingsIn(client_id=CLIENT, inputs_due_day=5), USER)
    assert pr._MOCK_PAYROLL_SETTINGS[("f1", CLIENT)]["inputs_due_day"] == 5
    pr.put_payroll_settings(PayrollSettingsIn(client_id=CLIENT, inputs_due_day=None), USER)
    assert pr._MOCK_PAYROLL_SETTINGS[("f1", CLIENT)]["inputs_due_day"] is None


def test_a_cutoff_day_that_does_not_exist_in_february_is_refused():
    """Capped at 28. A cut-off of the 30th would silently not exist in one
    month of every year."""
    from pydantic import ValidationError
    from models.payroll import PayrollSettingsIn
    with pytest.raises(ValidationError):
        PayrollSettingsIn(client_id=CLIENT, inputs_due_day=30)


def test_a_finalised_month_refuses_new_attendance():
    """Nothing downstream re-reads it: the slips are stored. Editing the inputs
    under a posted run makes them stop explaining the output, and the ECR's NCP
    days stop agreeing with the attendance somebody can now read."""
    import inspect
    src = inspect.getsource(pr.put_attendance)
    assert "_attendance_is_locked" in src
    assert "status_code=409" in src
    # And the lock is the released pair the rest of the codebase already names
    # — the ECR, the ESIC return, Form 16, the 24Q and migration 323's RLS all
    # draw the line in the same place.
    assert pr._PAYROLL_RELEASED == ("finalized", "paid")
    assert "_PAYROLL_RELEASED" in inspect.getsource(pr._attendance_is_locked)


def test_the_run_and_the_screen_read_attendance_the_same_way():
    """One query shape, and one place the firm filter lives. create_run's read
    omitted the firm filter entirely — the ids were already firm-scoped, but
    the service-role key bypasses RLS and CLAUDE.md makes that filter the
    primary isolation control."""
    import inspect
    assert "_attendance_for(" in inspect.getsource(pr.create_run)
    assert '.eq("firm_id", firm_id)' in inspect.getsource(pr._attendance_for)
