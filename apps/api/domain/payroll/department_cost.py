"""What each department costs, for one payroll month (PAY-27).

WHAT WAS MISSING

    `payroll_employees.department` has been collected since the module was
    built and `domain/payroll/register.py` carries it as a column, and nothing
    ever grouped by it. So "what does the factory cost me against the office"
    — the question a client asks their CA before they ask anything else about
    payroll — was a spreadsheet pivot every month.

COST IS BOTH DEBITS, AND THE TWO ARE REPORTED APART

    PAY-25 established that the payroll accrual has TWO debits: Schedule III
    Division I Part II presents Employee Benefits Expense as (a) salaries and
    wages and (b) contribution to provident and other funds, and the posting
    splits gross from the employer's PF, EDLI, administrative charge and ESI.

    What a department COSTS is both of them — the employer bears both — so the
    total is their sum. But they are also reported separately, because the two
    answer different questions: "what do I pay them" and "what does employing
    them cost on top", and a single blended figure lets a reader take it for
    either. It is also what makes the departmental total tie to the P&L: the
    two columns are the two accounts.

    NET PAY IS NOT COST and is deliberately absent. Net is what leaves the
    bank; the employee's own PF, ESI, professional tax and TDS are the
    employer's cost too, paid to somebody else. A department table built on net
    understates the cost by exactly the employee's statutory deductions.

AN EMPLOYEE WITH NO DEPARTMENT IS ITS OWN ROW

    Never folded into another department and never dropped. `department` is
    nullable with no default, so a client who has never used it has every
    employee here — and a table that silently omitted them would not sum to the
    run, which is the one property that makes it checkable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: The employer's own side, which PAY-25 posts to `Contribution to Provident
#: and Other Funds` (5016). The administrative CHARGE is a fee rather than a
#: contribution and is grouped here anyway, because it is remitted on the same
#: challan and is universally presented with PF — PAY-25's own reasoning.
EMPLOYER_COST_FIELDS: tuple[str, ...] = (
    "pf_employer_paise",
    "esi_employer_paise",
    "edli_paise",
    "pf_admin_paise",
)

NOT_RECORDED = "(no department recorded)"

NET_IS_NOT_COST = (
    "Cost is gross pay plus the employer's own contributions. Net pay is what "
    "leaves the bank — the employee's PF, ESI, professional tax and TDS are "
    "the employer's cost too, paid to somebody else — so a department table "
    "built on net understates the cost by exactly those deductions."
)

TWO_DEBITS = (
    "Salaries and the employer's contributions are shown apart because they "
    "are two debits and two accounts (Schedule III Division I Part II (a) and "
    "(b)), which is what lets this table be checked against the profit and "
    "loss account."
)

UNRECORDED_IS_ITS_OWN_ROW = (
    "Employees with no department recorded are their own row, never folded "
    "into another and never dropped — the table has to sum to the run."
)


@dataclass
class DepartmentCost:
    department: str
    headcount: int = 0
    gross_paise: int = 0
    employer_contribution_paise: int = 0

    @property
    def cost_paise(self) -> int:
        return self.gross_paise + self.employer_contribution_paise

    def to_dict(self) -> dict:
        return {
            "department": self.department,
            "headcount": self.headcount,
            "gross_paise": self.gross_paise,
            "employer_contribution_paise": self.employer_contribution_paise,
            "cost_paise": self.cost_paise,
        }


@dataclass
class DepartmentSplit:
    month: str
    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def total_cost_paise(self) -> int:
        return sum(r.cost_paise for r in self.rows)

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            # Largest cost first — the question is which department costs most.
            # Ties broken on the NAME so the order is total and the table does
            # not reshuffle between two reads of the same month.
            "rows": [r.to_dict() for r in sorted(
                self.rows, key=lambda r: (-r.cost_paise, r.department.lower()))],
            "total_gross_paise": sum(r.gross_paise for r in self.rows),
            "total_employer_contribution_paise": sum(
                r.employer_contribution_paise for r in self.rows),
            "total_cost_paise": self.total_cost_paise,
            "total_headcount": sum(r.headcount for r in self.rows),
            "notes": list(self.notes),
        }


def employer_contribution_of(slip: dict) -> int:
    """The employer's own side of one slip.

    One definition, so the department table and anything else that asks cannot
    disagree about whether the administrative charge is in it.
    """
    return sum(int(slip.get(f) or 0) for f in EMPLOYER_COST_FIELDS)


def split(slips, month: str) -> DepartmentSplit:
    """One row per department, from the same joined slips the register reads."""
    out = DepartmentSplit(month=month,
                          notes=[TWO_DEBITS, NET_IS_NOT_COST,
                                 UNRECORDED_IS_ITS_OWN_ROW])
    by_name: dict = {}
    for slip in slips:
        emp = slip.get("payroll_employees") or {}
        name = str(emp.get("department") or "").strip() or NOT_RECORDED
        row = by_name.get(name)
        if row is None:
            row = by_name[name] = DepartmentCost(department=name)
        row.headcount += 1
        row.gross_paise += int(slip.get("gross_paise") or 0)
        row.employer_contribution_paise += employer_contribution_of(slip)
    out.rows = list(by_name.values())
    return out
