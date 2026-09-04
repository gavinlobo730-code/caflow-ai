"""
Attendance as a contract: the five numbers, what they mean, and what is refused.

WHAT WAS BROKEN

app/payroll/attendance/page.tsx was the only thing that wrote public.attendance,
and it wrote it straight through PostgREST. Two consequences, and the second is
the serious one:

  1. NOTHING VALIDATED THE NUMBERS. The page computed
     `lop = max(0, working_days - days_present - casual - sick - earned)`, so a
     row whose days add up to MORE than the month contains — 26 present plus
     four days' casual leave in a 26-day month — quietly became zero loss of
     pay and a full month's salary. A floor turns a contradiction into a
     confident number instead of a question, which is the same species of fault
     as the 26/26 default itself.

  2. SAVE WROTE THE WHOLE ROSTER. The editor seeded a default row (26 working,
     26 present, no leave) for every employee with none, and saved
     `Object.values(attendance)` — touched or not. Pressing Save once wrote an
     explicit, confident full month for the entire firm, for that month.

     That erased the distinction migration 324 had just drawn. A row existed for
     everybody, so payroll_slips.attendance_entered read true for everybody, and
     the flag asserted that a human had confirmed something no human looked at.

THE IDENTITY, WHICH IS NOW ENFORCED RATHER THAN FLOORED

    days_present + casual + sick + earned + lop = working_days

Days present are days AT WORK. Casual, sick and earned leave are paid and are
counted separately. Loss of pay is the remainder — the days nobody was at work
and nobody is paying for. It is not decorative arithmetic:
routers/payroll.py::_compute_slip prorates on `working_days - lop_days`, so
every rupee of basic, HRA, DA, LTA and medical comes off this line.

`lop_days` may be OMITTED and is then derived, because it is the only one of
the five that is purely a remainder. Sent and inconsistent, it is REFUSED
rather than corrected: silently replacing a number a CA typed is how the
disagreement between what is on the screen and what is in the table starts.

WHAT "NOT ENTERED" MEANS HERE

Absence of a row. There is no third value and no flag on the row itself —
having none is what "not entered" is, and the moment a default row exists the
question cannot be asked again. Which is exactly what the bulk save did.

A CA who has genuinely established that somebody worked the whole month says so
by entering it, and the row then carries entered_by and entered_at (migration
326). "Confirmed present all month" and "nobody asked" stop being the same row.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

#: The leave heads that are PAID and therefore not loss of pay.
PAID_LEAVE_FIELDS = ("casual_leaves", "sick_leaves", "earned_leaves")
#: Every integer column a caller may set, in the order the identity reads.
DAY_FIELDS = ("working_days", "days_present", *PAID_LEAVE_FIELDS, "lop_days")

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class AttendanceError(ValueError):
    """A row that cannot be stored as given."""


def parse_month(period: str) -> tuple[int, int]:
    """"YYYY-MM" -> (year, month).

    public.attendance stores month and year as separate integers (migration
    027) while every payroll surface speaks "YYYY-MM". Splitting it in one
    place is what stops a caller reading `int(period[:4])` and silently
    accepting "2026-13".
    """
    m = _MONTH_RE.match((period or "").strip())
    if not m:
        raise AttendanceError(
            f"Month must look like '2026-08', got {period!r}.")
    return int(m.group(1)), int(m.group(2))


def days_in_month(period: str) -> int:
    year, month = parse_month(period)
    return calendar.monthrange(year, month)[1]


@dataclass(frozen=True)
class AttendanceRow:
    """One employee's month, with the identity already satisfied."""
    employee_id: str
    working_days: int
    days_present: int
    casual_leaves: int
    sick_leaves: int
    earned_leaves: int
    lop_days: int

    def as_write(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "working_days": self.working_days,
            "days_present": self.days_present,
            "casual_leaves": self.casual_leaves,
            "sick_leaves": self.sick_leaves,
            "earned_leaves": self.earned_leaves,
            "lop_days": self.lop_days,
        }


def _whole_number(raw, field: str, who: str) -> int:
    if raw is None:
        raise AttendanceError(f"{who}: {field} is required.")
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise AttendanceError(f"{who}: {field} must be a whole number of days.")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise AttendanceError(
            f"{who}: {field} must be a whole number of days, got {raw!r}.")
    if value < 0:
        raise AttendanceError(f"{who}: {field} cannot be negative.")
    return value


def build_row(raw: dict, *, period: str, who: str) -> AttendanceRow:
    """One employee's submitted row, or a refusal naming them and the field.

    Named rather than positional in the error because a bulk save covers a whole
    roster: "days do not add up" is unactionable across forty people.
    """
    month_length = days_in_month(period)

    working = _whole_number(raw.get("working_days"), "working_days", who)
    if not 1 <= working <= month_length:
        raise AttendanceError(
            f"{who}: working_days is {working}, and {period} has {month_length} "
            f"days. It must be between 1 and {month_length} — a payroll month "
            f"cannot be longer than the month.")

    present = _whole_number(raw.get("days_present"), "days_present", who)
    leaves = {f: _whole_number(raw.get(f, 0), f, who) for f in PAID_LEAVE_FIELDS}
    accounted = present + sum(leaves.values())

    sent_lop = raw.get("lop_days")
    derived = working - accounted
    if sent_lop is None:
        # The only one of the five that is purely a remainder, so the only one
        # a caller may leave out.
        if derived < 0:
            raise AttendanceError(
                f"{who}: {present} days present plus {sum(leaves.values())} days' "
                f"leave is {accounted} days, which is more than the {working} "
                f"working days in the month. Nothing is left for loss of pay, so "
                f"one of those numbers is wrong.")
        lop = derived
    else:
        lop = _whole_number(sent_lop, "lop_days", who)
        if present + sum(leaves.values()) + lop != working:
            raise AttendanceError(
                f"{who}: the days do not add up. {present} present + "
                f"{sum(leaves.values())} leave + {lop} loss of pay = "
                f"{present + sum(leaves.values()) + lop}, but the month has "
                f"{working} working days. Leave loss of pay out and it will be "
                f"worked out, or correct one of the others.")

    return AttendanceRow(
        employee_id=str(raw.get("employee_id") or "").strip(),
        working_days=working, days_present=present, lop_days=lop,
        casual_leaves=leaves["casual_leaves"],
        sick_leaves=leaves["sick_leaves"],
        earned_leaves=leaves["earned_leaves"],
    )


def build_rows(raw_rows: list[dict], *, period: str,
               names_by_id: dict[str, str] | None = None) -> list[AttendanceRow]:
    """The whole request, validated whole and refused whole.

    WHOLE-REQUEST REFUSAL IS THE POINT. A partial write leaves a client-month
    where some employees were saved and some were not, with nothing on the
    screen saying which — and the ones that failed are then indistinguishable
    from the ones nobody entered, which is the exact confusion this module
    exists to end. Every problem is collected and reported together so the CA
    fixes the sheet once.
    """
    if not raw_rows:
        raise AttendanceError("No attendance rows were sent.")

    names = names_by_id or {}
    seen: set[str] = set()
    rows: list[AttendanceRow] = []
    problems: list[str] = []

    for raw in raw_rows:
        emp_id = str(raw.get("employee_id") or "").strip()
        who = names.get(emp_id) or emp_id or "an unnamed row"
        if not emp_id:
            problems.append("A row has no employee_id.")
            continue
        if emp_id in seen:
            problems.append(
                f"{who}: sent twice in one request. One of the two would "
                f"silently win, so neither is written.")
            continue
        seen.add(emp_id)
        try:
            rows.append(build_row(raw, period=period, who=who))
        except AttendanceError as e:
            problems.append(str(e))

    if problems:
        raise AttendanceError(" ".join(problems))
    return rows


def cutoff_state(period: str, inputs_due_day: int | None, today) -> dict:
    """Where this client-month stands against its agreed cut-off.

    `today` is a date, passed in rather than read here: core.ist_clock owns
    what "today" is and a domain module that asked the clock itself could not
    be tested for the day after a cut-off.

    Returns `agreed: False` when no cut-off is recorded, which is not the same
    as being on time. A firm that has not agreed a date with this client has
    not agreed one — see migration 326 for why there is no default.
    """
    if not inputs_due_day:
        return {"agreed": False, "due_on": None, "days_overdue": 0, "overdue": False}

    year, month = parse_month(period)
    # The cut-off falls in the month AFTER the payroll month: nobody can report
    # September's loss of pay before September has happened.
    due_year, due_month = (year + 1, 1) if month == 12 else (year, month + 1)
    from datetime import date
    due = date(due_year, due_month, min(int(inputs_due_day),
                                        calendar.monthrange(due_year, due_month)[1]))
    overdue_by = (today - due).days
    return {"agreed": True, "due_on": due.isoformat(),
            "days_overdue": max(0, overdue_by), "overdue": overdue_by > 0}
