"""
Presumptive taxation — IT Act 1961, sections 44AD, 44ADA and 44AE.

These schemes let a small business, a professional or a transporter declare a
statutory PERCENTAGE of turnover as income instead of computing profit from
books. They are not a rounding convenience: a taxpayer who opts in is relieved
of maintaining books under §44AA and of audit under §44AB, and the declared
figure IS the business income.

They matter more than their share of the statute suggests. A large part of an
Indian practice's client base — small traders, doctors, architects, lawyers,
lorry owners — files this way, so a product that cannot compute a presumptive
return cannot file for them at all.

All monetary values are integer paise. Never float. Percentages are applied as
integer arithmetic (paise * rate // 100), so a turnover ending in an odd paise
cannot introduce a fraction.

VERIFICATION STATUS
    Same contract as domain/income_tax/statutory_rates: `verified` is False for
    any FY whose figures could not be confirmed against primary legislation.
    An unverified year CARRIES FORWARD the last verified year's figures — the
    standard "no change announced" assumption — rather than guessing. A firm
    filing on an unverified year must confirm against that year's Finance Act
    first; that is a data change here, not a code change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

CRORE_PAISE = 1_00_00_000_00
LAKH_PAISE = 1_00_000_00


@dataclass(frozen=True)
class PresumptiveLimits:
    """The figures for one financial year."""
    fy: str
    verified: bool

    # ── §44AD — eligible business ────────────────────────────────────────────
    # 8% of turnover, or 6% of the part received through an account payee
    # cheque/draft/ECS/prescribed electronic mode by the §139(1) due date.
    s44ad_rate_percent: int
    s44ad_digital_rate_percent: int
    # The turnover ceiling, and the higher one available under the proviso to
    # §44AD(1) when cash receipts are within a small fraction of turnover.
    s44ad_turnover_limit_paise: int
    s44ad_enhanced_turnover_limit_paise: int

    # ── §44ADA — specified profession under §44AA(1) ─────────────────────────
    s44ada_rate_percent: int
    s44ada_receipts_limit_paise: int
    s44ada_enhanced_receipts_limit_paise: int

    # ── The cash test that unlocks both enhanced limits ─────────────────────
    # Expressed as a percentage of turnover / gross receipts.
    enhanced_limit_cash_receipts_percent: int

    # ── §44AE — goods carriages ─────────────────────────────────────────────
    # A heavy goods vehicle earns per TON of gross vehicle weight per month;
    # any other goods carriage earns a flat monthly amount. Either way a PART
    # of a month counts as a whole one.
    s44ae_heavy_per_ton_per_month_paise: int
    s44ae_other_per_month_paise: int
    s44ae_heavy_gvw_kg: int
    s44ae_max_goods_carriages: int


_FY_2025_26 = PresumptiveLimits(
    fy="2025-26",
    verified=True,
    s44ad_rate_percent=8,
    s44ad_digital_rate_percent=6,
    s44ad_turnover_limit_paise=2 * CRORE_PAISE,
    s44ad_enhanced_turnover_limit_paise=3 * CRORE_PAISE,
    s44ada_rate_percent=50,
    s44ada_receipts_limit_paise=50 * LAKH_PAISE,
    s44ada_enhanced_receipts_limit_paise=75 * LAKH_PAISE,
    enhanced_limit_cash_receipts_percent=5,
    # 1,000 rupees per ton per month; 7,500 rupees per month.
    s44ae_heavy_per_ton_per_month_paise=1_000_00,
    s44ae_other_per_month_paise=7_500_00,
    s44ae_heavy_gvw_kg=12_000,
    s44ae_max_goods_carriages=10,
)

# Carried forward, not guessed — see VERIFICATION STATUS above.
_FY_2026_27 = PresumptiveLimits(**{**_FY_2025_26.__dict__, "fy": "2026-27",
                                   "verified": False})

LIMITS_BY_FY: dict[str, PresumptiveLimits] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

LATEST_VERIFIED_FY = "2025-26"


def limits_for(fy: Optional[str] = None) -> PresumptiveLimits:
    """Limits for the given FY, falling back to the latest verified year for a
    year further out than anything seeded here."""
    from domain.income_tax.statutory_rates import current_fy
    fy = fy or current_fy()
    return LIMITS_BY_FY.get(fy, LIMITS_BY_FY[LATEST_VERIFIED_FY])


@dataclass(frozen=True)
class PresumptiveResult:
    """What a scheme produces, and why."""
    section: str
    eligible: bool
    presumptive_income_paise: int
    declared_income_paise: int
    turnover_limit_paise: int
    enhanced_limit_applied: bool
    # Why the scheme is unavailable, or what the CA still has to confirm.
    reasons: tuple[str, ...]
    workings: tuple[str, ...]


def _cash_within_threshold(cash_receipts_paise: int, total_paise: int,
                           percent: int) -> bool:
    """Whether cash receipts are within `percent` of total receipts.

    Compared by CROSS-MULTIPLICATION rather than by computing a percentage,
    so no division rounds a taxpayer across the boundary: a turnover of
    3,00,00,000 with cash of exactly 15,00,000 is 5.000%, and must qualify.
    """
    if total_paise <= 0:
        return True
    return cash_receipts_paise * 100 <= total_paise * percent


def compute_44ad(
    *,
    turnover_paise: int,
    digital_turnover_paise: int = 0,
    cash_receipts_paise: int = 0,
    declared_income_paise: Optional[int] = None,
    fy: Optional[str] = None,
) -> PresumptiveResult:
    """§44AD — presumptive income of an eligible business.

    Income is 8% of turnover, except the part received by account payee
    cheque, draft, ECS or a prescribed electronic mode by the §139(1) due date,
    which is 6%. Both are computed and added, because a business is usually
    part digital and part cash and the section applies each rate to its own
    slice rather than picking one.

    The ceiling is 2 crore, raised to 3 crore by the proviso to §44AD(1) where
    cash receipts do not exceed 5% of turnover.

    §44AD(1) permits declaring MORE than the presumptive figure ("or a sum
    higher than the aforesaid sum claimed to have been earned"), so
    declared_income_paise above the computed figure is honoured. Below it is
    NOT: §44AD(5) requires books and audit in that case, so it is refused here
    rather than quietly reduced.
    """
    lim = limits_for(fy)
    reasons: list[str] = []
    workings: list[str] = []

    digital = max(0, min(digital_turnover_paise, turnover_paise))
    other = turnover_paise - digital

    enhanced = _cash_within_threshold(
        cash_receipts_paise, turnover_paise, lim.enhanced_limit_cash_receipts_percent)
    ceiling = (lim.s44ad_enhanced_turnover_limit_paise if enhanced
               else lim.s44ad_turnover_limit_paise)
    if enhanced:
        workings.append(
            f"Cash receipts are within {lim.enhanced_limit_cash_receipts_percent}% "
            f"of turnover, so the proviso to §44AD(1) raises the ceiling to "
            f"{ceiling} paise."
        )

    eligible = turnover_paise <= ceiling
    if not eligible:
        reasons.append(
            f"Turnover of {turnover_paise} paise exceeds the §44AD ceiling of "
            f"{ceiling} paise, so the scheme is not available."
        )

    presumptive = (digital * lim.s44ad_digital_rate_percent // 100
                   + other * lim.s44ad_rate_percent // 100)
    if digital:
        workings.append(
            f"{digital} paise received through prescribed banking modes at "
            f"{lim.s44ad_digital_rate_percent}%."
        )
    if other:
        workings.append(
            f"{other} paise of remaining turnover at {lim.s44ad_rate_percent}%."
        )

    declared = presumptive
    if declared_income_paise is not None:
        if declared_income_paise < presumptive:
            eligible = False
            reasons.append(
                f"Income declared ({declared_income_paise} paise) is below the "
                f"presumptive figure ({presumptive} paise). §44AD(5) then "
                f"requires books under §44AA and audit under §44AB, so the "
                f"scheme cannot be used to declare less."
            )
        else:
            declared = declared_income_paise
            if declared > presumptive:
                workings.append(
                    f"A higher income of {declared} paise is declared, which "
                    f"§44AD(1) permits."
                )

    # Not derivable from figures — the CA has to confirm them.
    reasons.append(
        "§44AD is available only to a resident individual, HUF or partnership "
        "firm (not an LLP), and not to a profession under §44AA(1), a "
        "commission or brokerage earner, or an agency business — confirm "
        "before opting in."
    )
    return PresumptiveResult(
        section="44AD",
        eligible=eligible,
        presumptive_income_paise=presumptive,
        declared_income_paise=declared if eligible else 0,
        turnover_limit_paise=ceiling,
        enhanced_limit_applied=enhanced,
        reasons=tuple(reasons),
        workings=tuple(workings),
    )


def compute_44ada(
    *,
    gross_receipts_paise: int,
    cash_receipts_paise: int = 0,
    declared_income_paise: Optional[int] = None,
    fy: Optional[str] = None,
) -> PresumptiveResult:
    """§44ADA — presumptive income of a specified profession.

    50% of gross receipts, for a profession referred to in §44AA(1): legal,
    medical, engineering, architectural, accountancy, technical consultancy,
    interior decoration, and the professions notified under that sub-section.

    The ceiling is 50 lakh, raised to 75 lakh where cash receipts do not exceed
    5% of gross receipts.

    As with §44AD, declaring MORE is permitted and declaring LESS is not: under
    §44ADA(4) a professional declaring below the presumptive figure, whose
    income exceeds the maximum amount not chargeable to tax, must keep books
    and be audited.
    """
    lim = limits_for(fy)
    reasons: list[str] = []
    workings: list[str] = []

    enhanced = _cash_within_threshold(
        cash_receipts_paise, gross_receipts_paise,
        lim.enhanced_limit_cash_receipts_percent)
    ceiling = (lim.s44ada_enhanced_receipts_limit_paise if enhanced
               else lim.s44ada_receipts_limit_paise)
    if enhanced:
        workings.append(
            f"Cash receipts are within {lim.enhanced_limit_cash_receipts_percent}% "
            f"of gross receipts, so the ceiling is {ceiling} paise."
        )

    eligible = gross_receipts_paise <= ceiling
    if not eligible:
        reasons.append(
            f"Gross receipts of {gross_receipts_paise} paise exceed the §44ADA "
            f"ceiling of {ceiling} paise, so the scheme is not available."
        )

    presumptive = gross_receipts_paise * lim.s44ada_rate_percent // 100
    workings.append(
        f"{gross_receipts_paise} paise of gross receipts at "
        f"{lim.s44ada_rate_percent}%."
    )

    declared = presumptive
    if declared_income_paise is not None:
        if declared_income_paise < presumptive:
            eligible = False
            reasons.append(
                f"Income declared ({declared_income_paise} paise) is below the "
                f"presumptive figure ({presumptive} paise). §44ADA(4) then "
                f"requires books and audit, so the scheme cannot be used to "
                f"declare less."
            )
        else:
            declared = declared_income_paise

    reasons.append(
        "§44ADA applies only to a profession referred to in §44AA(1) — confirm "
        "the client's profession qualifies before opting in."
    )
    return PresumptiveResult(
        section="44ADA",
        eligible=eligible,
        presumptive_income_paise=presumptive,
        declared_income_paise=declared if eligible else 0,
        turnover_limit_paise=ceiling,
        enhanced_limit_applied=enhanced,
        reasons=tuple(reasons),
        workings=tuple(workings),
    )


@dataclass(frozen=True)
class GoodsCarriage:
    """One vehicle, for §44AE.

    months_owned counts every month or PART of a month the carriage was owned,
    which is what the section charges on — a vehicle bought on 28 March is
    owned for a part of March and that month is charged in full.
    """
    gross_vehicle_weight_kg: int
    months_owned: int


def compute_44ae(
    *,
    vehicles: list[GoodsCarriage],
    declared_income_paise: Optional[int] = None,
    fy: Optional[str] = None,
) -> PresumptiveResult:
    """§44AE — presumptive income from plying, hiring or leasing goods carriages.

    A HEAVY goods vehicle — gross vehicle weight over 12,000 kg — earns 1,000
    rupees per ton of that weight for every month or part of a month it is
    owned. Any other goods carriage earns 7,500 rupees a month on the same
    part-month basis.

    Note that 1,000 rupees per TON is exactly 1 rupee per kilogram, so a
    16,500 kg vehicle earns 16,500 rupees a month. The arithmetic is done in
    kilograms for that reason: converting to tons first would either truncate
    the half-ton or need a float.

    The scheme is unavailable to anyone owning more than 10 goods carriages at
    any time during the year — a ceiling on VEHICLES, not on turnover, which is
    what makes §44AE shaped differently from the other two.
    """
    lim = limits_for(fy)
    reasons: list[str] = []
    workings: list[str] = []

    eligible = len(vehicles) <= lim.s44ae_max_goods_carriages
    if not eligible:
        reasons.append(
            f"{len(vehicles)} goods carriages exceeds the §44AE limit of "
            f"{lim.s44ae_max_goods_carriages} at any time during the year."
        )

    presumptive = 0
    for i, v in enumerate(vehicles, start=1):
        months = max(0, v.months_owned)
        if v.gross_vehicle_weight_kg > lim.s44ae_heavy_gvw_kg:
            # 1,000 rupees per ton == 1 rupee per kg, so per-month income in
            # paise is the weight in kg times one rupee in paise, per ton.
            per_month = (v.gross_vehicle_weight_kg
                         * lim.s44ae_heavy_per_ton_per_month_paise // 1000)
            workings.append(
                f"Vehicle {i}: heavy goods vehicle, "
                f"{v.gross_vehicle_weight_kg} kg, {months} month(s) at "
                f"{per_month} paise."
            )
        else:
            per_month = lim.s44ae_other_per_month_paise
            workings.append(
                f"Vehicle {i}: goods carriage, {months} month(s) at "
                f"{per_month} paise."
            )
        presumptive += per_month * months

    declared = presumptive
    if declared_income_paise is not None:
        if declared_income_paise < presumptive:
            eligible = False
            reasons.append(
                f"Income declared ({declared_income_paise} paise) is below the "
                f"presumptive figure ({presumptive} paise); §44AE(7) then "
                f"requires books and audit."
            )
        else:
            declared = declared_income_paise

    return PresumptiveResult(
        section="44AE",
        eligible=eligible,
        presumptive_income_paise=presumptive,
        declared_income_paise=declared if eligible else 0,
        turnover_limit_paise=0,     # §44AE caps vehicles, not turnover
        enhanced_limit_applied=False,
        reasons=tuple(reasons),
        workings=tuple(workings),
    )
