"""
Full and final settlement — what an employee is owed when they leave.

WHY THIS IS A MODULE AND NOT A SCREEN

A leaver's last payment is not a payslip with a different date on it. It is a
composition of five or six separate entitlements, each with its own statute, its
own base and its own tax treatment, netted against what the employee owes back:

    salary to the last working day        §17(1), taxable in full
    leave encashment                      §10(10AA) — exempt only on retirement
    gratuity                              Gratuity Act §4, exempt under §10(10)
    statutory bonus                       Bonus Act §10/§11, taxable in full
    notice pay recovered                  a deduction, not negative salary
    loans and advances outstanding        a deduction

Getting the composition right matters more than any one component, because the
errors compound in one direction. Every component this module can compute is
computed by the module that owns its statute — gratuity.py, leave_encashment.py,
bonus.py — and this one only adds them up and says what it could not answer.

TWO THINGS IT DELIBERATELY REFUSES TO GUESS

  NOTICE PAY. Whether pay in lieu of notice may be recovered, and how much, is a
  matter of the employment contract and of the standing orders, not of statute.
  It is an input. What this module does assert is that recovery is a DEDUCTION
  from the settlement rather than a reduction of salary — the distinction
  decides the §17(1) figure that reaches Form 16, and netting it off salary
  understates the employee's income and the employer's TDS.

  THE TAX ON THE SETTLEMENT ITSELF. §192 withholding on a final payment needs
  the year's earlier salary and the year's earlier TDS, which is the payroll
  run's job (routers/payroll.py, the §192(3) true-up). This module reports the
  taxable and exempt split per component so that the run can withhold on it,
  and computes no tax of its own.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SettlementComponent:
    label: str
    gross_paise: int = 0
    exempt_paise: int = 0
    statute: str = ""

    @property
    def taxable_paise(self) -> int:
        return max(0, self.gross_paise - self.exempt_paise)


@dataclass
class Settlement:
    components: list[SettlementComponent] = field(default_factory=list)
    deductions: list[SettlementComponent] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def gross_paise(self) -> int:
        return sum(c.gross_paise for c in self.components)

    @property
    def exempt_paise(self) -> int:
        return sum(c.exempt_paise for c in self.components)

    @property
    def taxable_paise(self) -> int:
        """What belongs in §17(1) for the year. Deductions do NOT reduce this —
        recovering notice pay or a loan does not un-earn the salary."""
        return sum(c.taxable_paise for c in self.components)

    @property
    def deductions_paise(self) -> int:
        return sum(d.gross_paise for d in self.deductions)

    @property
    def net_payable_paise(self) -> int:
        """What actually leaves the bank. May be negative — an employee who owes
        more than the settlement covers is a real situation, and showing it as
        zero would hide a debt the employer still has to collect."""
        return self.gross_paise - self.deductions_paise


def build(
    *,
    salary_to_last_day_paise: int,
    gratuity=None,
    leave=None,
    bonus=None,
    notice_pay_recovered_paise: int = 0,
    loans_outstanding_paise: int = 0,
    other_recoveries_paise: int = 0,
) -> Settlement:
    """Compose a settlement from figures the statute-owning modules produced.

    `gratuity`, `leave` and `bonus` are the results from
    domain/payroll/gratuity.py, leave_encashment.py and bonus.py. Passing None
    for any of them means it does not arise — a resignation at three years has
    no gratuity, and that is not a gap.
    """
    s = Settlement()

    s.components.append(SettlementComponent(
        label="Salary to last working day",
        gross_paise=max(0, salary_to_last_day_paise),
        statute="§17(1)"))

    if gratuity is not None:
        s.components.append(SettlementComponent(
            label="Gratuity", gross_paise=gratuity.payable_paise,
            exempt_paise=gratuity.exempt_paise,
            statute="Payment of Gratuity Act §4; IT Act §10(10)"))
        s.gaps.extend(gratuity.gaps)

    if leave is not None:
        s.components.append(SettlementComponent(
            label="Leave encashment", gross_paise=leave.received_paise,
            exempt_paise=leave.exempt_paise, statute="IT Act §10(10AA)"))
        s.gaps.extend(leave.gaps)

    if bonus is not None:
        s.components.append(SettlementComponent(
            label="Statutory bonus", gross_paise=bonus.payable_paise,
            statute="Payment of Bonus Act §10/§11"))
        s.gaps.extend(bonus.gaps)

    if notice_pay_recovered_paise:
        s.deductions.append(SettlementComponent(
            label="Notice pay recovered",
            gross_paise=max(0, notice_pay_recovered_paise),
            statute="contract / standing orders — not statute"))
        s.gaps.append(
            "Notice pay is recovered as a DEDUCTION from the settlement, not as "
            "a reduction of salary. Netting it off salary would understate the "
            "§17(1) figure that reaches Form 16, and with it the TDS. Whether it "
            "is recoverable at all is a matter of the contract."
        )

    if loans_outstanding_paise:
        s.deductions.append(SettlementComponent(
            label="Loans and advances outstanding",
            gross_paise=max(0, loans_outstanding_paise)))
    if other_recoveries_paise:
        s.deductions.append(SettlementComponent(
            label="Other recoveries",
            gross_paise=max(0, other_recoveries_paise)))

    if s.net_payable_paise < 0:
        s.problems.append(
            f"The employee owes ₹{-s.net_payable_paise / 100:,.2f} more than the "
            f"settlement covers. Nothing is payable, and the balance is a debt to "
            f"be collected separately — it cannot be deducted from a salary that "
            f"has stopped."
        )

    return s
