"""
FY-versioned individual income-tax statutory rates — single source of truth.

IT Act 1961: Section 115BAC (new regime slabs), Section 16(ia) (standard
deduction), Section 87A (rebate), Section 2(29C) read with the Finance Act's
Part I First Schedule (surcharge), Section 111A/112A/112 (capital gains
rates, exemption, and surcharge cap).

Before this module, the same slab/rebate/surcharge numbers were hand-copied
into five independent places (domain/income_tax/itr_engine.py,
routers/payroll.py, and three frontend TypeScript files) and had already
drifted out of sync with each other (some FY 2024-25, some FY 2025-26,
one — apps/web/app/income-tax/deductions/page.tsx — with a 10x paise/rupee
scaling bug, audit finding F18). Every backend consumer now reads from
RATES_BY_FY below; frontend consumers should call a backend endpoint rather
than re-implement slabs (CLAUDE.md: zero business logic in the frontend).

All monetary values in integer paise. Never float.

VERIFICATION STATUS — read before relying on this for a real filing or a real
payroll run. FY 2025-26 is the last financial year this module's author could
verify against a training-confirmed Finance Act (Budget 2025, presented
February 2025). Today's date may fall in a later FY whose Finance Act this
module cannot independently confirm. `RATES_BY_FY[fy].verified` is False for
any entry the author could not verify against primary legislation — those
entries are populated by CARRYING FORWARD the last verified year's figures
(the standard "no change announced" assumption), not by guessing at new
numbers. A CA firm relying on this for a financial year with verified=False
MUST confirm the entry against the actual Finance Act / CBDT circulars for
that year before filing or withholding tax on its basis, and update
RATES_BY_FY accordingly — that is a pure data change, no code change needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from core.ist_clock import ist_today


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SlabBracket:
    """A progressive tax bracket. upto_paise=None means "and above" (top rate)."""
    upto_paise: int | None
    rate_percent: int


@dataclass(frozen=True)
class RebateRule:
    """Section 87A: full rebate (tax reduced to nil) up to threshold_paise total
    income, capped at max_rebate_paise.

    marginal_relief applies ONLY where the statute grants it: the proviso added
    by Finance Act 2023 (and re-based by Finance Act 2025) is expressly
    conditioned on income chargeable under Section 115BAC(1A) — the NEW regime.
    The old-regime rebate has no such proviso and is a hard cliff: total income
    of ₹5,00,001 loses the entire ₹12,500 rebate and pays full slab tax."""
    threshold_paise: int
    max_rebate_paise: int
    marginal_relief: bool


@dataclass(frozen=True)
class SurchargeBracket:
    """Surcharge applies once total income STRICTLY EXCEEDS above_paise."""
    above_paise: int
    rate_percent: int


@dataclass(frozen=True)
class FYTaxRates:
    fy: str  # "2025-26"
    verified: bool  # False = carried forward pending confirmation, see module docstring

    new_regime_slabs: tuple[SlabBracket, ...]
    old_regime_slabs_general: tuple[SlabBracket, ...]        # non-senior, < 60
    old_regime_slabs_senior: tuple[SlabBracket, ...]         # 60–79
    old_regime_slabs_very_senior: tuple[SlabBracket, ...]    # 80+

    new_regime_standard_deduction_paise: int   # Section 16(ia)
    old_regime_standard_deduction_paise: int

    new_regime_rebate: RebateRule
    old_regime_rebate: RebateRule

    surcharge_brackets: tuple[SurchargeBracket, ...]  # ordinary-income surcharge, both regimes
    new_regime_surcharge_cap_percent: int  # new regime never exceeds this (Finance Act 2023 dropped its 37% slab)

    # Surcharge on tax attributable to capital gains under Sections 111A
    # (STCG, listed equity), 112A (LTCG, listed equity) and — since Finance
    # Act 2022 — 112 (LTCG, ANY asset) is capped at this rate, even when the
    # assessee's overall income surcharge bracket is higher.
    capital_gains_surcharge_cap_percent: int

    # Capital gains tax rates (rates in basis points — 1250 = 12.50% — since
    # 112A/112 are not whole-percent rates). R3.1: migrated out of
    # itr_engine.py, where they lived as inline constants outside this
    # registry.
    stcg_111a_rate_bps: int          # Section 111A: STCG, listed equity (Budget 2024: 20%)
    ltcg_112a_rate_bps: int          # Section 112A: LTCG, listed equity (Budget 2024: 12.5%)
    ltcg_112a_exemption_paise: int   # Section 112A exemption threshold (₹1,25,000)
    ltcg_112_other_rate_bps: int     # Section 112: LTCG, any other asset (post-Budget 2024: 12.5%)

    cess_percent: int  # Health and Education Cess, on (tax + surcharge)


# ── FY 2025-26 (Finance Act 2025 / Budget 2025, Feb 2025) — VERIFIED ─────────

_FY_2025_26 = FYTaxRates(
    fy="2025-26",
    verified=True,
    new_regime_slabs=(
        SlabBracket(400_000_00, 0),
        SlabBracket(800_000_00, 5),
        SlabBracket(1_200_000_00, 10),
        SlabBracket(1_600_000_00, 15),
        SlabBracket(2_000_000_00, 20),
        SlabBracket(2_400_000_00, 25),
        SlabBracket(None, 30),
    ),
    # Old regime slabs have been unchanged since Finance Act 2023 (no FY has
    # touched them since new-regime-only changes began).
    old_regime_slabs_general=(
        SlabBracket(250_000_00, 0),
        SlabBracket(500_000_00, 5),
        SlabBracket(1_000_000_00, 20),
        SlabBracket(None, 30),
    ),
    old_regime_slabs_senior=(
        SlabBracket(300_000_00, 0),
        SlabBracket(500_000_00, 5),
        SlabBracket(1_000_000_00, 20),
        SlabBracket(None, 30),
    ),
    old_regime_slabs_very_senior=(
        SlabBracket(500_000_00, 0),
        SlabBracket(1_000_000_00, 20),
        SlabBracket(None, 30),
    ),
    new_regime_standard_deduction_paise=75_000_00,
    old_regime_standard_deduction_paise=50_000_00,
    new_regime_rebate=RebateRule(threshold_paise=1_200_000_00, max_rebate_paise=60_000_00,
                                 marginal_relief=True),   # 115BAC(1A) proviso, FA 2025
    old_regime_rebate=RebateRule(threshold_paise=500_000_00, max_rebate_paise=12_500_00,
                                 marginal_relief=False),  # statutory hard cliff — no proviso
    surcharge_brackets=(
        SurchargeBracket(5_000_000_00, 10),
        SurchargeBracket(10_000_000_00, 15),
        SurchargeBracket(20_000_000_00, 25),
        SurchargeBracket(50_000_000_00, 37),
    ),
    new_regime_surcharge_cap_percent=25,
    capital_gains_surcharge_cap_percent=15,
    stcg_111a_rate_bps=2000,
    ltcg_112a_rate_bps=1250,
    ltcg_112a_exemption_paise=125_000_00,
    ltcg_112_other_rate_bps=1250,
    cess_percent=4,
)


# ── FY 2026-27 — NOT YET VERIFIED (see module docstring) ─────────────────────
# Carried forward from FY 2025-26 unchanged. Confirm against Finance Act 2026 /
# CBDT circulars before relying on this for real filings or withholding.

_FY_2026_27 = FYTaxRates(
    fy="2026-27",
    verified=False,
    new_regime_slabs=_FY_2025_26.new_regime_slabs,
    old_regime_slabs_general=_FY_2025_26.old_regime_slabs_general,
    old_regime_slabs_senior=_FY_2025_26.old_regime_slabs_senior,
    old_regime_slabs_very_senior=_FY_2025_26.old_regime_slabs_very_senior,
    new_regime_standard_deduction_paise=_FY_2025_26.new_regime_standard_deduction_paise,
    old_regime_standard_deduction_paise=_FY_2025_26.old_regime_standard_deduction_paise,
    new_regime_rebate=_FY_2025_26.new_regime_rebate,
    old_regime_rebate=_FY_2025_26.old_regime_rebate,
    surcharge_brackets=_FY_2025_26.surcharge_brackets,
    new_regime_surcharge_cap_percent=_FY_2025_26.new_regime_surcharge_cap_percent,
    capital_gains_surcharge_cap_percent=_FY_2025_26.capital_gains_surcharge_cap_percent,
    stcg_111a_rate_bps=_FY_2025_26.stcg_111a_rate_bps,
    ltcg_112a_rate_bps=_FY_2025_26.ltcg_112a_rate_bps,
    ltcg_112a_exemption_paise=_FY_2025_26.ltcg_112a_exemption_paise,
    ltcg_112_other_rate_bps=_FY_2025_26.ltcg_112_other_rate_bps,
    cess_percent=_FY_2025_26.cess_percent,
)

RATES_BY_FY: dict[str, FYTaxRates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

LATEST_VERIFIED_FY = "2025-26"


def current_fy(today: date | None = None) -> str:
    """Indian FY runs April 1 – March 31."""
    d = today or ist_today()
    start_year = d.year if d.month >= 4 else d.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def rates_for(fy: str | None = None) -> FYTaxRates:
    """Rates for the given FY string ("2025-26"), defaulting to the current FY.
    Falls back to the latest verified FY (with its own fy label preserved on
    the *lookup key* only — the returned object still reports its true fy) if
    the requested year isn't in the registry at all yet (further in the future
    than anything seeded here)."""
    fy = fy or current_fy()
    if fy in RATES_BY_FY:
        return RATES_BY_FY[fy]
    return RATES_BY_FY[LATEST_VERIFIED_FY]


# ── Pure computation helpers (paise in, paise out; never float) ─────────────

def slab_tax_paise(taxable_income_paise: int, slabs: tuple[SlabBracket, ...]) -> int:
    """Progressive slab tax. Integer paise throughout; each bracket's tax is
    floor-divided individually (never round the whole result), matching how
    the IT department's own utilities compute per-slab tax."""
    if taxable_income_paise <= 0:
        return 0
    tax = 0
    lower = 0
    for bracket in slabs:
        upper = bracket.upto_paise if bracket.upto_paise is not None else taxable_income_paise
        if taxable_income_paise <= lower:
            break
        slice_paise = min(taxable_income_paise, upper) - lower
        if slice_paise > 0:
            tax += slice_paise * bracket.rate_percent // 100
        lower = upper
        if bracket.upto_paise is None:
            break
    return tax


def apply_rebate_87a(taxable_income_paise: int, tax_paise: int, rebate: RebateRule) -> int:
    """Section 87A. Returns the tax payable AFTER the rebate.

    At/below the threshold: rebate wipes out tax_paise entirely, capped at
    max_rebate_paise (some assessees' slab tax is already below the cap).
    Above the threshold, only when the rule grants marginal relief (new
    regime, 115BAC(1A) proviso): the extra tax payable never exceeds the
    extra income over the threshold — this is what stops a taxpayer earning
    ₹1 more than the threshold from owing tax on the entire slab structure
    instead of ~₹1 more tax. Where the statute grants no relief (old
    regime), crossing the threshold forfeits the rebate entirely — full
    slab tax is payable (the well-known ₹5,00,001 cliff).
    """
    if taxable_income_paise <= rebate.threshold_paise:
        return max(0, tax_paise - min(tax_paise, rebate.max_rebate_paise))
    if not rebate.marginal_relief:
        return tax_paise
    excess_income_paise = taxable_income_paise - rebate.threshold_paise
    return min(tax_paise, excess_income_paise)


def resolve_surcharge_bracket(total_income_paise: int, brackets: tuple[SurchargeBracket, ...],
                              cap_percent: int | None) -> tuple[int, int]:
    """Returns (rate_percent, bracket_threshold_paise) for the highest bracket
    total_income_paise falls into, or (0, 0) if below every bracket. Exposed
    (not just used internally) so a caller that needs to apply the SAME
    resolved bracket to more than one tax component (e.g. ordinary tax and a
    separately-capped capital-gains tax) only resolves it once."""
    rate = 0
    threshold = 0
    for b in sorted(brackets, key=lambda x: x.above_paise):
        if total_income_paise > b.above_paise:
            rate = b.rate_percent
            threshold = b.above_paise
    if cap_percent is not None:
        rate = min(rate, cap_percent)
    return rate, threshold


def apply_surcharge_with_marginal_relief(
    total_income_paise: int,
    tax_before_surcharge_paise: int,
    brackets: tuple[SurchargeBracket, ...],
    cap_percent: int | None,
    tax_at_income_fn,
) -> int:
    """Surcharge on tax_before_surcharge_paise, with marginal relief: the
    combined increase in (tax + surcharge) versus the amount payable at
    exactly the surcharge threshold can never exceed the increase in income
    over that threshold — otherwise crossing a surcharge threshold by ₹1
    could cost far more than ₹1 in extra tax.

    tax_at_income_fn(income_paise) -> int must return the SAME kind of tax
    (before surcharge) that tax_before_surcharge_paise is, evaluated at an
    arbitrary income level — the caller supplies it because the right "kind"
    of tax depends on context (plain slab tax for ordinary income).
    """
    rate, threshold = resolve_surcharge_bracket(total_income_paise, brackets, cap_percent)
    if rate == 0:
        return 0
    surcharge = tax_before_surcharge_paise * rate // 100
    total_with_surcharge = tax_before_surcharge_paise + surcharge
    tax_at_threshold = tax_at_income_fn(threshold)
    max_total = tax_at_threshold + (total_income_paise - threshold)
    if total_with_surcharge > max_total:
        total_with_surcharge = max(tax_at_threshold, max_total)
        surcharge = total_with_surcharge - tax_before_surcharge_paise
    return max(0, surcharge)


def cess_paise(tax_plus_surcharge_paise: int, rates: FYTaxRates) -> int:
    return max(0, tax_plus_surcharge_paise) * rates.cess_percent // 100
