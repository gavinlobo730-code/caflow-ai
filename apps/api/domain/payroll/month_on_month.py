"""Why is this month's payroll bigger than last month's, and by whom (PAY-27).

WHAT WAS MISSING

    It is the first question anyone asks on the 3rd, and the product answered
    none of it. `payroll_runs` stores `total_gross_paise`,
    `total_one_time_paise` and the rest — the beginning of the answer — and no
    screen compared two months, so a CA who saw the payroll jump by ₹2.4 lakh
    exported both registers and diffed them in a spreadsheet.

THE TWO MONTHS ARE NOT HELD TO THE SAME STANDARD, AND THAT IS DELIBERATE

    The BASELINE must be a RELEASED run — PAY-04's rule, that a draft has paid
    nobody, so a draft baseline compares this month against something that
    never happened. The month being LOOKED AT may be any status, because the
    variance is most useful BEFORE release: catching a ₹2.4 lakh jump on the
    2nd is the whole point, and refusing to show it until the run is finalised
    would put the check after the moment it could prevent anything.

THE BASELINE IS THE PRECEDING CALENDAR MONTH AND IS NEVER REACHED PAST

    A client with no August run gets "no released run for August" rather than a
    silent comparison against July labelled last month. Reaching back is the
    kind of wrongness a CA cannot see: the figures are real, the arithmetic is
    right, and the sentence above them is false.

NO SINGLE CAUSE IS EVER NAMED

    A gross figure moves for several reasons at once — a joiner, a leaver, a
    revision, loss of pay, a one-time payment, a statutory change — and picking
    the largest and calling it THE reason is how a CA stops reading the rest.
    `reasons_for` returns every component that actually moved, each with its own
    delta, and an employee whose gross moved with no component movement this
    module can see is NAMED as unexplained rather than given a plausible label.

WHAT IT REFUSES

    * **No percentage is computed against a nil baseline.** A joiner's gross
      went from nothing to something and "∞%" is not a figure; the delta is the
      answer and the screen renders the rupees.
    * **Nothing is attributed to a statutory change.** PF, ESI and PT each move
      by their own notification and by the employee's own wage crossing a
      ceiling, and this module cannot tell those apart — so a PF movement is
      reported as a PF movement and the reason stops there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: PAY-04: a run that has actually paid somebody.
_RELEASED = ("finalized", "paid")

NO_BASELINE = (
    "There is no released payroll run for the preceding month, so there is "
    "nothing to compare against. A draft is not a baseline — it has paid "
    "nobody — and an earlier month is not the preceding one."
)

A_DRAFT_IS_STILL_WORTH_COMPARING = (
    "This month's run has not been released yet. The comparison is shown "
    "because catching a jump before the run is finalised is the point of it; "
    "the figures will move if the run is recomputed."
)

NO_SINGLE_CAUSE = (
    "Every component that moved is listed. A payroll total moves for several "
    "reasons at once, so no one of them is named as the reason."
)

STATUTORY_MOVEMENT_IS_NOT_EXPLAINED = (
    "A movement in PF, ESI or professional tax is reported as itself. Whether "
    "it is a rate change, a ceiling crossed or a wage revision is not derived "
    "here — the three look identical in the slip."
)

#: The components a variance is explained BY, in the order a payslip reads.
#: `gross_paise` and `net_paise` are the totals being explained and are
#: deliberately absent: listing a total among its own causes double-counts.
COMPONENTS: tuple[tuple[str, str], ...] = (
    ("basic_paise", "Basic"),
    ("hra_paise", "HRA"),
    ("da_paise", "DA"),
    ("lta_paise", "LTA"),
    ("medical_paise", "Medical"),
    ("special_allowance_paise", "Special Allowance"),
    ("other_allowances_paise", "Other Allowances"),
    ("one_time_earnings_paise", "Bonus / Incentive / Arrears"),
    ("pf_employee_paise", "PF (employee)"),
    ("esi_employee_paise", "ESI (employee)"),
    ("pt_paise", "Professional Tax"),
    ("tds_paise", "TDS"),
    ("loan_recovery_paise", "Loan Recovery"),
)

#: Not money, and reported separately for that reason: a CA reading "LOP 3
#: days" understands the gross movement beside it without being told a rupee
#: figure that is only an approximation of it.
DAY_FIELDS: tuple[tuple[str, str], ...] = (
    ("lop_days", "LOP days"),
    ("days_present", "Days present"),
)

JOINED = "joined"
LEFT = "left"
CHANGED = "changed"
UNCHANGED = "unchanged"


@dataclass
class EmployeeVariance:
    employee_id: str
    name: str
    status: str
    gross_paise: int = 0
    prior_gross_paise: int = 0
    net_paise: int = 0
    prior_net_paise: int = 0
    #: [(label, delta_paise)] — every component that actually moved.
    moved: list = field(default_factory=list)
    #: [(label, delta)] — days, which are not money.
    days_moved: list = field(default_factory=list)
    unexplained: bool = False

    @property
    def gross_delta_paise(self) -> int:
        return self.gross_paise - self.prior_gross_paise

    @property
    def net_delta_paise(self) -> int:
        return self.net_paise - self.prior_net_paise

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "status": self.status,
            "gross_paise": self.gross_paise,
            "prior_gross_paise": self.prior_gross_paise,
            "gross_delta_paise": self.gross_delta_paise,
            "net_paise": self.net_paise,
            "prior_net_paise": self.prior_net_paise,
            "net_delta_paise": self.net_delta_paise,
            "moved": [{"label": l, "delta_paise": d} for l, d in self.moved],
            "days_moved": [{"label": l, "delta": d} for l, d in self.days_moved],
            "unexplained": self.unexplained,
        }


@dataclass
class Variance:
    month: str
    prior_month: str
    comparable: bool = False
    gross_paise: int = 0
    prior_gross_paise: int = 0
    net_paise: int = 0
    prior_net_paise: int = 0
    headcount: int = 0
    prior_headcount: int = 0
    employees: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def gross_delta_paise(self) -> int:
        return self.gross_paise - self.prior_gross_paise

    @property
    def net_delta_paise(self) -> int:
        return self.net_paise - self.prior_net_paise

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "prior_month": self.prior_month,
            "comparable": self.comparable,
            "gross_paise": self.gross_paise,
            "prior_gross_paise": self.prior_gross_paise,
            "gross_delta_paise": self.gross_delta_paise,
            "net_paise": self.net_paise,
            "prior_net_paise": self.prior_net_paise,
            "net_delta_paise": self.net_delta_paise,
            "headcount": self.headcount,
            "prior_headcount": self.prior_headcount,
            # Largest ABSOLUTE movement first: a drop of ₹80,000 matters as
            # much as a rise of ₹80,000 and sorting on the signed value would
            # bury every leaver at the bottom.
            "employees": [e.to_dict() for e in sorted(
                self.employees,
                key=lambda e: (-abs(e.gross_delta_paise), e.name.lower()))],
            "changed_count": sum(1 for e in self.employees
                                 if e.status != UNCHANGED),
            "notes": list(self.notes),
        }


def preceding_month(month: str) -> str:
    """'2026-09' -> '2026-08'. The calendar's own predecessor, never a search.

    Derived rather than looked up, so a client whose first run is April gets
    March and is told there is nothing there — which is true — instead of the
    engine hunting backwards for a month it can compare.
    """
    text = str(month or "").strip()
    year, _, mon = text.partition("-")
    y, m = int(year), int(mon)
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def is_released(status: Optional[str]) -> bool:
    return str(status or "").strip().lower() in _RELEASED


def _by_employee(slips) -> dict:
    return {str(s.get("employee_id") or ""): s for s in slips
            if s.get("employee_id")}


def _name_of(slip: dict) -> str:
    return str((slip.get("payroll_employees") or {}).get("name") or "").strip()


def reasons_for(now: Optional[dict], before: Optional[dict]):
    """Every component that moved, and every day count that moved.

    Returns `(moved, days_moved)`. A component present in one month and absent
    in the other is read as nil on the absent side, which is what a joiner and
    a leaver are — the alternative is to skip it and report a gross movement
    with no cause.
    """
    moved, days = [], []
    for key, label in COMPONENTS:
        a = int((now or {}).get(key) or 0)
        b = int((before or {}).get(key) or 0)
        if a != b:
            moved.append((label, a - b))
    for key, label in DAY_FIELDS:
        a = float((now or {}).get(key) or 0)
        b = float((before or {}).get(key) or 0)
        if a != b:
            days.append((label, a - b))
    # Largest absolute movement first, inside the row as well as between rows.
    moved.sort(key=lambda m: (-abs(m[1]), m[0]))
    return moved, days


def compare(month: str, slips, prior_month: str, prior_slips,
            prior_released: bool) -> Variance:
    """This month against the preceding one, per head and in total.

    `prior_released` is the caller's answer and is REQUIRED rather than derived
    from the rows, because an empty list means two different things — a month
    with no run at all, and a released run with no employees — and only the
    caller can tell them apart.
    """
    out = Variance(month=month, prior_month=prior_month,
                   notes=[NO_SINGLE_CAUSE, STATUTORY_MOVEMENT_IS_NOT_EXPLAINED])

    now = _by_employee(slips)
    before = _by_employee(prior_slips) if prior_released else {}

    out.gross_paise = sum(int(s.get("gross_paise") or 0) for s in now.values())
    out.net_paise = sum(int(s.get("net_paise") or 0) for s in now.values())
    out.headcount = len(now)

    if not prior_released:
        out.notes.insert(0, NO_BASELINE)
        return out

    out.comparable = True
    out.prior_gross_paise = sum(int(s.get("gross_paise") or 0)
                                for s in before.values())
    out.prior_net_paise = sum(int(s.get("net_paise") or 0)
                              for s in before.values())
    out.prior_headcount = len(before)

    for employee_id in set(now) | set(before):
        a, b = now.get(employee_id), before.get(employee_id)
        if a is not None and b is None:
            status = JOINED
        elif a is None and b is not None:
            status = LEFT
        else:
            status = UNCHANGED
        row = EmployeeVariance(
            employee_id=employee_id,
            # The name comes off whichever month HAS the employee — a leaver
            # is not in this month's slips at all and would otherwise be an
            # unnamed row in the one report that exists to name them.
            name=_name_of(a or b or {}),
            status=status,
            gross_paise=int((a or {}).get("gross_paise") or 0),
            prior_gross_paise=int((b or {}).get("gross_paise") or 0),
            net_paise=int((a or {}).get("net_paise") or 0),
            prior_net_paise=int((b or {}).get("net_paise") or 0),
        )
        row.moved, row.days_moved = reasons_for(a, b)
        if status == UNCHANGED and (row.gross_delta_paise or row.net_delta_paise):
            row.status = CHANGED
        # A TOTAL THAT MOVED WITH NO COMPONENT BEHIND IT IS NAMED. It means a
        # figure this module does not list is doing the moving, and inventing a
        # label for it would be worse than the gap.
        if row.gross_delta_paise and not row.moved:
            row.unexplained = True
        out.employees.append(row)

    if any(e.unexplained for e in out.employees):
        out.notes.append(
            "One or more employees' gross pay moved with no component "
            "movement behind it. The figure is real; what explains it is not "
            "in the slip's own columns.")
    return out
