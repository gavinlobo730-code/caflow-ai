"""
One-time and variable earnings — incentive, bonus, ex-gratia, arrears.

WHAT WAS MISSING

Every earning a run could compute was a MONTHLY RATE out of the employee master
or a salary revision, prorated by attendance. There was nowhere to put an amount
decided once. The only way to pay a Diwali bonus was to inflate
special_allowance_paise for one month, and that is wrong in four separate ways
this module exists to keep apart:

  * it gets PRORATED by loss of pay, and a decided amount is not a rate;
  * it enters PF WAGES, which EPF Act §2(b) expressly excludes a bonus from;
  * it enters ESI WAGES, which ESI Act §2(22) excludes an annual payment from;
  * §192 PROJECTS it across the rest of the year, withholding tax every month
    on a bonus paid once. On a ₹50,000 bonus in April that is eleven phantom
    months of income in the projection.

THE THREE QUESTIONS, AND WHY THE ANSWERS DIFFER

Each earning answers three questions independently, and two payments a payslip
would print almost identically can answer them differently:

  PF wages    EPF Act §2(b) defines "basic wages" and excludes "any bonus,
              commission or any other similar allowance payable to the employee
              in respect of his employment". Incentive, bonus, ex-gratia and
              commission are therefore NOT PF wages. ARREARS are — they are the
              same basic and DA, paid late, and EPFO takes contributions on them
              in the month of payment.

  ESI wages   ESI Act §2(22) includes "any additional remuneration ... paid at
              intervals NOT EXCEEDING TWO MONTHS". That is an INTERVAL test, not
              a name test. A monthly or bi-monthly incentive is ESI wages; the
              same word attached to an annual payment is not. This is why
              `interval_months` is a field and not a footnote.

  §17(1)      IT Act §17(1)(iv) brings in fees, commissions and profits in lieu
              of or in addition to salary. Everything here is salary except a
              genuine reimbursement of expenditure, which is not the employee's
              income at all.

WHAT THIS MODULE DOES NOT DO: PROJECT

`interval_months` answers the ESI question and NOTHING ELSE. A quarterly
incentive is ESI wages under §2(22)'s two-month test if paid at two months or
less, and it is still added to the §192 projection ONCE, in the month it is paid.

That is deliberate and it is the conservative direction. §192(1) requires tax on
"the estimated income of the assessee under the head Salaries"; a variable
payment that has been made is a fact, and one that has not been made is a guess
about somebody else's discretion. Projecting a guess forward over-withholds all
year and refunds at assessment — and if the payment does not repeat, the
employee has funded the Revenue interest-free for eleven months. Including it
once, when paid, under-withholds by at most one month, which §192(3) then
corrects in the very next run because the run reads what has already been
deducted. One direction self-corrects and the other does not.

# Every amount is integer paise. Nothing here uses floating point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# The kinds a CA can record. Deliberately a closed set mirrored by migration
# 331's CHECK — an open text field would make the statutory defaults below
# unanswerable and would put whatever somebody typed on a Form 16.
KINDS = ("incentive", "bonus", "ex_gratia", "arrears",
         "commission", "reimbursement", "other")

# ESI Act §2(22): "any additional remuneration, if any, paid at intervals not
# exceeding two months". The line is at two, inclusive.
_ESI_MAX_INTERVAL_MONTHS = 2

# EPF Act §2(b): basic wages exclude bonus, commission "or any other similar
# allowance". Arrears are not an allowance — they are basic and DA paid late —
# so they are the one kind that defaults into PF wages.
_PF_WAGE_KINDS = frozenset({"arrears"})

# A reimbursement of expenditure is not the employee's income under §17(1);
# everything else recorded here is.
_NON_SALARY_KINDS = frozenset({"reimbursement"})


@dataclass(frozen=True)
class Defaults:
    """What the three statutory questions answer to, before a human overrides."""
    pf_wages: bool
    esi_wages: bool
    taxable: bool
    reason: str


def statutory_defaults(kind: str, interval_months: Optional[int] = None) -> Defaults:
    """Propose the three answers for a kind, with the sentence that justifies each.

    PROPOSE, not decide. The row stores what was saved (migration 331), because
    a slip has to stay readable after these defaults change and because the
    interval test genuinely differs between two clients paying "an incentive".
    """
    k = (kind or "").strip().lower()
    if k not in KINDS:
        raise ValueError(f"unknown earning kind: {kind!r}")

    if k in _NON_SALARY_KINDS:
        # Not wages under any of the three Acts — there is no remuneration in a
        # reimbursement, only a refund of money the employee laid out.
        return Defaults(
            pf_wages=False, esi_wages=False, taxable=False,
            reason="A reimbursement of expenditure is not remuneration: not PF "
                   "wages (EPF Act s.2(b)), not ESI wages (ESI Act s.2(22)), "
                   "and not salary under IT Act s.17(1).")

    pf = k in _PF_WAGE_KINDS

    # The interval test. NULL/None means paid once and not at an interval, which
    # falls the same side of the two-month line as an annual payment.
    esi = (interval_months is not None
           and 1 <= int(interval_months) <= _ESI_MAX_INTERVAL_MONTHS)

    if pf:
        pf_why = ("Arrears are basic and DA paid late, not an allowance, so they "
                  "are PF wages in the month of payment (EPF Act s.2(b)).")
    else:
        pf_why = ("EPF Act s.2(b) excludes bonus, commission and similar "
                  "allowances from basic wages, so this is not PF wages.")

    if esi:
        esi_why = (f"Paid every {int(interval_months)} month(s), which is within "
                   "the two-month interval in ESI Act s.2(22), so it is ESI wages.")
    elif interval_months is None:
        esi_why = ("Paid once rather than at an interval, so it is outside ESI "
                   "Act s.2(22)'s additional remuneration and is not ESI wages.")
    else:
        esi_why = (f"Paid every {int(interval_months)} months, beyond the two-month "
                   "interval in ESI Act s.2(22), so it is not ESI wages.")

    return Defaults(
        pf_wages=pf, esi_wages=esi, taxable=True,
        reason=f"{pf_why} {esi_why} Salary under IT Act s.17(1)(iv).")


@dataclass(frozen=True)
class Bundle:
    """One employee's one-time earnings for one month, already summed.

    Four totals rather than one, because the three statutory bases are what the
    ECR, the ESIC return and the §192 projection each read, and none of them can
    be derived back out of a single figure.
    """
    total_paise: int = 0
    pf_wages_paise: int = 0
    esi_wages_paise: int = 0
    taxable_paise: int = 0
    lines: tuple = field(default=())

    def __bool__(self) -> bool:
        return bool(self.lines)


EMPTY = Bundle()


def bundle(rows: Iterable[dict]) -> Bundle:
    """Sum one employee's earning rows into the four bases a slip needs.

    Reads what the ROW says, never re-deriving from `kind`: the row is the
    record of what a human decided, and migration 331 stores the three booleans
    for exactly that reason.

    Amounts are signed — a negative row recovers an earlier overpayment of the
    same kind, and it has to reduce the same bases it inflated.
    """
    total = pf = esi = taxable = 0
    lines = []
    for r in rows or ():
        amount = int(r.get("amount_paise") or 0)
        if amount == 0:
            continue
        total += amount
        if r.get("pf_wages"):
            pf += amount
        if r.get("esi_wages"):
            esi += amount
        if r.get("taxable"):
            taxable += amount
        lines.append({
            "kind": r.get("kind"),
            "label": r.get("label"),
            "amount_paise": amount,
        })
    return Bundle(total_paise=total, pf_wages_paise=pf, esi_wages_paise=esi,
                  taxable_paise=taxable, lines=tuple(lines))


def bundles_by_employee(rows: Iterable[dict]) -> dict:
    """Group a whole run's earning rows by employee id, then bundle each.

    One query per run, not one per employee — the same rule the attendance read
    follows (`_attendance_for`): a 200-employee run must not make 200 sequential
    round trips to Mumbai for a few kilobytes.
    """
    by_emp: dict[str, list] = {}
    for r in rows or ():
        emp = r.get("employee_id")
        if emp is None:
            continue
        by_emp.setdefault(str(emp), []).append(r)
    return {emp: bundle(rs) for emp, rs in by_emp.items()}


def validate(row: dict) -> list[str]:
    """Everything wrong with one earning row, as sentences a CA can act on.

    Whole-row, not first-failure: a CA fixing a form wants every problem at
    once, the same contract domain/payroll/attendance.py uses.
    """
    problems: list[str] = []

    kind = (row.get("kind") or "").strip().lower()
    if kind not in KINDS:
        problems.append(
            f"'{row.get('kind')}' is not an earning kind. One of: "
            + ", ".join(KINDS) + ".")

    amount = row.get("amount_paise")
    if amount is None:
        problems.append("An amount is required.")
    else:
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            problems.append("The amount must be a whole number of paise.")
            amount = None
        if amount == 0:
            # Refused rather than ignored: a zero-rupee earning is a row
            # somebody started and did not finish, not a decision to pay nothing.
            problems.append("A zero amount is not an earning. Remove the row "
                            "instead, or enter what is being paid.")

    interval = row.get("payment_interval_months")
    if interval is not None:
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            problems.append("The payment interval must be a whole number of months.")
            interval = None
        if interval is not None and not (1 <= interval <= 12):
            problems.append("A payment interval is between 1 and 12 months, or "
                            "blank for a payment made once.")

    for f in ("pf_wages", "esi_wages", "taxable"):
        if row.get(f) is None:
            problems.append(
                f"'{f}' has not been answered. Each earning has to say whether "
                "it is PF wages (EPF Act s.2(b)), ESI wages (ESI Act s.2(22)) "
                "and salary (IT Act s.17(1)) — the answers differ between two "
                "payments with the same name.")

    return problems


def divergence_note(row: dict) -> Optional[str]:
    """A sentence where a saved row disagrees with the statutory default.

    Not a refusal. A CA may know something the default cannot — a client whose
    "incentive" is contractual and paid with every wage cycle, or arrears of an
    allowance that was never PF wages to begin with. But a disagreement should
    be VISIBLE on the run rather than silent, because these three booleans are
    what the ECR and the ESIC return are built from.
    """
    kind = (row.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    d = statutory_defaults(kind, row.get("payment_interval_months"))
    differs = [
        name for name, saved, default in (
            ("PF wages", bool(row.get("pf_wages")), d.pf_wages),
            ("ESI wages", bool(row.get("esi_wages")), d.esi_wages),
            ("taxable", bool(row.get("taxable")), d.taxable),
        ) if saved != default
    ]
    if not differs:
        return None
    label = row.get("label") or kind
    return (f"{label}: {', '.join(differs)} recorded against the statutory "
            f"default. {d.reason}")
