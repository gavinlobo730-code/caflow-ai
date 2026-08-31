"""
Payroll statutory rates and ceilings, versioned by financial year.

WHY THIS MODULE EXISTS

routers/payroll.py carried these as bare literals — min(pf_wages_paise, 1500000)
for the EPF ceiling, gross_paise > 2100000 for ESI, and the professional tax
slabs inline. CLAUDE.md's annual-maintenance checklist records that as a known
gap: they change by EPFO / ESIC / state notification, they cannot be printed by
the coverage command every other registry answers to, and so they can only be
found by reading the code. This gives them the same shape as
domain/income_tax/statutory_rates.py and the rest.

THE FALLBACK IS THE SAME, AND SO IS ITS DANGER

rates_for() returns LATEST_VERIFIED_FY's values for a year it does not hold, so
a missing year is a confidently wrong number rather than an error. That is the
convention across every registry here; it is written down in CLAUDE.md and it
is why the annual sweep is a checklist somebody works.

WHAT THE EMPLOYER'S 12% ACTUALLY IS

Not one number. EPF & MP Act 1952 §6 sets the employee's contribution at 12% of
basic wages + DA + retaining allowance, and the employer matches it — but the
Employees' Pension Scheme 1995 (¶3) diverts part of the EMPLOYER's share to the
pension fund:

    EPS  = 8.33% of PF wages, capped at 8.33% of the 15,000 ceiling = 1,250
    EPF  = the employer's 12% MINUS whatever went to EPS

so at or below the ceiling the employer's share is 8.33% pension + 3.67% PF, and
above it the EPS amount stops rising while the EPF half absorbs the rest. The
employee's own 12% is never split — all of it is EPF.

Two further employer costs sit OUTSIDE the 12% and are not deducted from anyone:

    EDLI   0.5% of PF wages (EDLI ceiling 15,000, so at most 75) — EDLI 1976
    admin  0.5% of PF wages, subject to a MINIMUM PER ESTABLISHMENT of 500 a
           month, which is why it cannot be finally settled on one payslip;
           per-employee 0.5% is computed here and the floor is applied when the
           run is totalled. EDLI admin charges have been nil since 01-04-2017.

Getting this split wrong is not only a wrong trial balance. The EPFO's ECR file
carries EPF wages, EPS wages, the EPF contribution, the EPS contribution and the
difference between them as separate columns per member, so a flat 12% cannot
produce a valid return at all.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PFRates:
    """EPF & MP Act 1952, and EPS 1995."""
    wage_ceiling_paise: int          # §6 / EPS ¶3 — 15,000
    employee_rate_bps: int           # 12% = 1200 bps, all to EPF
    employer_rate_bps: int           # 12% total employer share
    eps_rate_bps: int                # 8.33% of PF wages, out of the employer's 12%
    eps_ceiling_paise: int           # EPS wages are capped separately — 15,000
    edli_rate_bps: int               # 0.5%
    edli_ceiling_paise: int          # 15,000
    admin_rate_bps: int              # 0.5%
    admin_minimum_paise: int         # 500 per ESTABLISHMENT per month


@dataclass(frozen=True)
class ESIRates:
    """ESI Act 1948 §2(9); rates from Notification of 13-06-2019."""
    wage_ceiling_paise: int          # 21,000 — gross ABOVE this is out of ESI
    employee_rate_bps: int           # 0.75%
    employer_rate_bps: int           # 3.25%


@dataclass(frozen=True)
class PayrollRates:
    fy: str
    pf: PFRates
    esi: ESIRates


_FY_2025_26 = PayrollRates(
    fy="2025-26",
    pf=PFRates(
        wage_ceiling_paise=15_000_00,
        employee_rate_bps=1200,
        employer_rate_bps=1200,
        eps_rate_bps=833,
        eps_ceiling_paise=15_000_00,
        edli_rate_bps=50,
        edli_ceiling_paise=15_000_00,
        admin_rate_bps=50,
        admin_minimum_paise=500_00,
    ),
    esi=ESIRates(
        wage_ceiling_paise=21_000_00,
        employee_rate_bps=75,
        employer_rate_bps=325,
    ),
)

# 2026-27 carries 2025-26's figures because no EPFO or ESIC notification has
# changed them. It is a SEPARATE entry rather than a fallback so that the
# coverage command reports the year as present, and so that changing one year
# cannot silently move another.
_FY_2026_27 = PayrollRates(fy="2026-27", pf=_FY_2025_26.pf, esi=_FY_2025_26.esi)

RATES_BY_FY: dict[str, PayrollRates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

# The last year a human checked these against the EPFO / ESIC notifications.
LATEST_VERIFIED_FY = "2026-27"


def rates_for(fy: str | None = None) -> PayrollRates:
    """Rates for an FY string ("2025-26"), falling back to the latest verified.

    Same convention — and the same hazard — as every other registry here: an
    unknown year returns last year's numbers rather than raising. See CLAUDE.md.
    """
    from domain.income_tax.statutory_rates import current_fy
    fy = fy or current_fy()
    if fy in RATES_BY_FY:
        return RATES_BY_FY[fy]
    return RATES_BY_FY[LATEST_VERIFIED_FY]
