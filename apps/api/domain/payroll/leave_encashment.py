"""
Leave encashment — IT Act §10(10AA).

THE DISTINCTION THAT DECIDES EVERYTHING

§10(10AA) exempts leave encashment received ON RETIREMENT, "whether on
superannuation or otherwise". Leave encashed WHILE STILL IN SERVICE is not
within the section at all: it is ordinary salary under §17(1), fully taxable,
and no part of the ₹25,00,000 is available against it.

That is the mistake this module exists to prevent. Both payments look identical
on a payslip — same leave, same rate, same line item — and exempting the
in-service one understates the employee's income by up to the whole amount.

  §10(10AA)(i)   A Central or State Government employee: the whole amount is
                 exempt. No formula, no limit.

  §10(10AA)(ii)  Anyone else: exempt to the LEAST of four figures —
                   1. the amount actually received;
                   2. ₹25,00,000 — raised from ₹3,00,000 by CBDT Notification
                      31/2023 of 24-05-2023, with effect from 01-04-2023, and
                      unchanged for twenty-five years before that;
                   3. ten months' average salary;
                   4. the cash equivalent of the leave standing to credit,
                      counted at no more than THIRTY DAYS for each completed
                      year of service.

Limb 4 is the one that bites in practice. An employer whose own leave policy
allows forty-five days a year, and who pays out on that basis, is paying more
than the section will exempt: the calculation is capped at thirty days a year
however generous the scheme, and the difference is taxable.

"Average salary" is the average of the last TEN MONTHS' basic and dearness
allowance (to the extent DA forms part of retirement benefits) plus commission
computed at a fixed percentage of turnover. Not the last month, and not gross.

The ₹25,00,000 is a LIFETIME limit aggregated across employers — the proviso to
§10(10AA)(ii) — so an employee who has encashed leave before has less of it
left. Like the gratuity limit, it is an input here and reported as a gap when
absent, because assuming the full limit is available under-taxes.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field

# §10(10AA)(ii), limb 2 — Notification 31/2023 w.e.f. 01-04-2023.
LIFETIME_CEILING_PAISE: int = 25_00_000 * 100

# limb 3 — ten months' average salary.
AVERAGE_SALARY_MONTHS: int = 10

# limb 4 — thirty days per completed year, whatever the employer's own scheme
# allows.
MAX_LEAVE_DAYS_PER_YEAR: int = 30

# The month is taken as thirty days when converting a monthly average salary to
# a daily rate for limb 4. (Contrast gratuity, where §4(2) fixes the divisor at
# twenty-six — the two are different statutes and the divisors are not
# interchangeable.)
DAYS_IN_MONTH: int = 30


@dataclass
class LeaveEncashmentResult:
    received_paise: int = 0
    exempt_paise: int = 0
    taxable_paise: int = 0

    limb_actual_paise: int = 0
    limb_statutory_paise: int = 0
    limb_ten_months_paise: int = 0
    limb_leave_credit_paise: int = 0

    days_allowed: int = 0
    gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compute(
    *,
    amount_received_paise: int,
    average_monthly_salary_paise: int,
    completed_years_of_service: int,
    leave_days_encashed: int,
    on_retirement: bool,
    is_government_employee: bool = False,
    exemption_already_used_paise: int | None = None,
) -> LeaveEncashmentResult:
    """How much of a leave encashment §10(10AA) exempts.

    `on_retirement` False means encashment during service — outside the section
    entirely, and fully taxable. It is a required argument rather than a
    defaulted one precisely because it decides the answer.
    """
    out = LeaveEncashmentResult()
    received = max(0, amount_received_paise)
    out.received_paise = received

    if not on_retirement:
        out.taxable_paise = received
        out.notes.append(
            "Encashed during service, so §10(10AA) does not apply: the section "
            "exempts encashment received ON RETIREMENT. This is ordinary salary "
            "under §17(1) and is fully taxable."
        )
        return out

    if is_government_employee:
        out.exempt_paise = received
        out.notes.append(
            "§10(10AA)(i) — a Central or State Government employee's leave "
            "encashment on retirement is wholly exempt. No formula and no limit."
        )
        return out

    limit = LIFETIME_CEILING_PAISE
    if exemption_already_used_paise is None:
        out.gaps.append(
            "The ₹25,00,000 under §10(10AA) is a LIFETIME limit aggregated across "
            "employers. Nothing is recorded about leave encashment exempted "
            "previously, so the full limit is assumed available. Where the "
            "employee has encashed before, the exemption here is smaller."
        )
    else:
        limit = max(0, LIFETIME_CEILING_PAISE - max(0, exemption_already_used_paise))

    avg = max(0, average_monthly_salary_paise)
    years = max(0, int(completed_years_of_service))

    # limb 4 — capped at thirty days per completed year however generous the
    # employer's own leave policy is.
    allowed_days = min(max(0, int(leave_days_encashed)),
                       MAX_LEAVE_DAYS_PER_YEAR * years)
    out.days_allowed = allowed_days
    if leave_days_encashed > allowed_days:
        out.notes.append(
            f"{leave_days_encashed} days were encashed but §10(10AA)(ii) counts "
            f"at most thirty days for each completed year — {allowed_days} days "
            f"here. The employer's scheme may be more generous; the exemption is "
            f"not."
        )

    out.limb_actual_paise = received
    out.limb_statutory_paise = limit
    out.limb_ten_months_paise = avg * AVERAGE_SALARY_MONTHS
    out.limb_leave_credit_paise = avg * allowed_days // DAYS_IN_MONTH

    out.exempt_paise = min(out.limb_actual_paise, out.limb_statutory_paise,
                           out.limb_ten_months_paise, out.limb_leave_credit_paise)
    out.taxable_paise = max(0, received - out.exempt_paise)
    return out
