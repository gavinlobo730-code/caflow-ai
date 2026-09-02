"""
FY-versioned section 195 withholding rates — the ACT side only.

WHAT THIS HOLDS, AND WHAT IT DELIBERATELY DOES NOT

    s.195 requires tax to be deducted from a sum paid to a non-resident "at the
    rates in force". Those come from Part II of the First Schedule to the
    Finance Act and, for the incomes it covers, s.115A — by the NATURE of the
    income, not by the kind of work done, which is what the resident sections
    (194C, 194J) key on.

    This module holds those Act rates, the surcharge bands and the cess. It
    holds NO DOUBLE-TAXATION-AVOIDANCE-AGREEMENT RATES AT ALL, and that is not
    an oversight — see "The treaty is a human step" below.

VERIFICATION STATUS — read before withholding real tax on this

    Same convention as domain/income_tax/statutory_rates.py, and it matters
    more here. FY 2025-26 is the last year this module's author could reconcile
    against a training-confirmed Finance Act. `RATES_BY_FY[fy].verified` is
    False for any entry carried forward on the standard "no change announced"
    assumption. A firm withholding on a verified=False year MUST confirm the
    figures against that year's Finance Act first.

    These rates move more often than the resident-section rates do. s.115A's
    royalty and fees-for-technical-services rate was 10% and became 20%; the
    foreign-company rate moved from 40% to 35%; s.111A moved from 15% to 20%
    and s.112/112A to 12.5%, all within recent Finance Acts. Treat every figure
    below as needing confirmation for the year you are withholding in.

CHARGEABILITY COMES FIRST, AND IS THE EXPENSIVE MISTAKE

    s.195 bites on "any sum chargeable under the provisions of this Act". The
    Supreme Court held in GE India Technology Centre (P) Ltd v. CIT (2010) 327
    ITR 456 that those words govern: there is no obligation to deduct from a
    payment that is not chargeable to tax in India at all.

    An ordinary import of goods, or a service that is not fees for technical
    services, is BUSINESS PROFITS of the non-resident. Without a permanent
    establishment in India, that is not chargeable here, and the right
    withholding is NIL — not 20%. Deducting 20% on a plain import takes a fifth
    of a foreign supplier's invoice for tax nobody owes, recoverable only by
    that supplier filing an Indian return.

    So NATURE_BUSINESS_PROFITS_NO_PE exists and resolves to zero. It is not a
    default: nothing infers it, and the caller must hold a no-PE declaration.

THE TREATY IS A HUMAN STEP, AND s.90(2) MAKES IT THE OPERATIVE RATE

    s.90(2) gives the assessee whichever of the Act and the treaty is MORE
    BENEFICIAL. India has agreements with over ninety countries; their royalty,
    FTS and interest articles differ, several have protocol and most-favoured-
    nation complications (see AO v. Nestle SA (2023), which held an MFN clause
    needs its own s.90(1) notification), and a number — the UAE and Singapore
    among them — have no fees-for-technical-services article at all, so what
    India would tax as FTS is business profits under the treaty and not taxable
    without a PE.

    None of that can be written from memory, and a wrong treaty rate is not a
    rounding error: too low disallows the WHOLE expenditure under s.40(a)(i),
    too high takes money off a supplier who can only get it back by filing here.

    So the treaty rate is recorded PER VENDOR by the CA who read the treaty
    (vendors.treaty_rate_bps, migration 309), exactly like the MSMED
    classification and the residential status before it. This module then
    applies s.90(2) to the two numbers it has. Where a vendor holds a Tax
    Residency Certificate but nobody has recorded the treaty rate, the engine
    REFUSES rather than falling back to the Act rate — falling back would
    silently over-deduct in precisely the case where the CA has already told us
    a treaty applies.

All rates are integer BASIS POINTS (2000 = 20.00%). Never float.
"""
from __future__ import annotations

from dataclasses import dataclass

from domain.income_tax.statutory_rates import current_fy


# ── Natures of income s.195 can be resolved for ──────────────────────────────
# Keys, not free text: a typo in a nature is a wrong rate, and the CHECK
# constraint on vendors.section_195_nature_of_income is generated from this set.

NATURE_ROYALTY = "royalty"
NATURE_FTS = "fees_for_technical_services"
NATURE_INTEREST = "interest"
NATURE_INTEREST_194LC = "interest_194lc"
NATURE_DIVIDEND = "dividend"
NATURE_LTCG_112 = "ltcg_112"
NATURE_LTCG_112A = "ltcg_112a"
NATURE_STCG_111A = "stcg_111a"
NATURE_BUSINESS_PROFITS_NO_PE = "business_profits_no_pe"
NATURE_OTHER_SUMS = "other_sums"

# The natures Rule 37BC lists. For these, and ONLY these, a non-resident
# without a PAN escapes the s.206AA 20% floor on furnishing six particulars:
# name, email, phone, address, TRC and the TIN of the country of residence.
# A resident gets no such relief, which is why the floor cannot be applied
# uniformly across both.
RULE_37BC_NATURES = frozenset({
    NATURE_INTEREST, NATURE_INTEREST_194LC, NATURE_ROYALTY, NATURE_FTS,
    NATURE_LTCG_112, NATURE_LTCG_112A, NATURE_STCG_111A,
})


@dataclass(frozen=True)
class NatureRule:
    """One nature of income: its Act rate and the provision it comes from."""
    rate_bps: int
    citation: str
    # True where the rate depends on whether the payee is a foreign company.
    # Only "other sums" does — everything else in s.115A is flat.
    company_rate_bps: int | None = None


@dataclass(frozen=True)
class SurchargeBand:
    """Surcharge applies once the sum STRICTLY EXCEEDS above_paise."""
    above_paise: int
    rate_percent: int


@dataclass(frozen=True)
class FY195Rates:
    fy: str
    verified: bool
    natures: dict[str, NatureRule]
    # Part II First Schedule. Two different ladders, and using the wrong one is
    # a large error: a foreign company's top surcharge is 5%, an individual's
    # is 37%.
    surcharge_non_corporate: tuple[SurchargeBand, ...]
    surcharge_foreign_company: tuple[SurchargeBand, ...]
    # s.111A/112/112A surcharge is capped even where the payee's band is higher
    # — the same cap statutory_rates.py applies to a resident's capital gains.
    capital_gains_surcharge_cap_percent: int
    cess_percent: int
    section_206aa_floor_bps: int


# ── FY 2025-26 ───────────────────────────────────────────────────────────────
# verified=False: the figures below are this author's best reconciliation and
# have NOT been confirmed line by line against the Finance Act 2025's Part II
# First Schedule. That is a deliberate refusal to overstate — see the module
# docstring. Confirming them is a pure data change: flip verified to True.

_FY_2025_26 = FY195Rates(
    fy="2025-26",
    verified=False,
    natures={
        NATURE_ROYALTY: NatureRule(
            2000, "s.115A(1)(b) — royalty from Government or an Indian concern"),
        NATURE_FTS: NatureRule(
            2000, "s.115A(1)(b) — fees for technical services"),
        NATURE_INTEREST: NatureRule(
            2000, "s.115A(1)(a) — interest from Government or an Indian concern"),
        NATURE_INTEREST_194LC: NatureRule(
            500, "s.194LC — concessional rate on approved foreign-currency "
                 "borrowing and long-term bonds"),
        NATURE_DIVIDEND: NatureRule(
            2000, "s.115A(1)(a)(i) — dividend other than u/s 115-O"),
        NATURE_LTCG_112: NatureRule(
            1250, "s.112 — long-term capital gains"),
        NATURE_LTCG_112A: NatureRule(
            1250, "s.112A — LTCG on listed equity, above the s.112A threshold"),
        NATURE_STCG_111A: NatureRule(
            2000, "s.111A — short-term capital gains on listed equity"),
        NATURE_BUSINESS_PROFITS_NO_PE: NatureRule(
            0, "GE India Technology Centre (P) Ltd v. CIT (2010) 327 ITR 456 — "
               "s.195 reaches only a sum CHARGEABLE under the Act, and business "
               "profits of a non-resident with no permanent establishment in "
               "India are not chargeable here"),
        NATURE_OTHER_SUMS: NatureRule(
            3000, "Part II First Schedule — sums chargeable at the rates in "
                  "force, non-corporate payee",
            company_rate_bps=3500),
    },
    surcharge_non_corporate=(
        SurchargeBand(50_00_000_00, 10),
        SurchargeBand(1_00_00_000_00, 15),
        SurchargeBand(2_00_00_000_00, 25),
        SurchargeBand(5_00_00_000_00, 37),
    ),
    surcharge_foreign_company=(
        SurchargeBand(1_00_00_000_00, 2),
        SurchargeBand(10_00_00_000_00, 5),
    ),
    capital_gains_surcharge_cap_percent=15,
    cess_percent=4,
    section_206aa_floor_bps=2000,
)

_FY_2026_27 = FY195Rates(
    fy="2026-27",
    verified=False,
    natures=_FY_2025_26.natures,
    surcharge_non_corporate=_FY_2025_26.surcharge_non_corporate,
    surcharge_foreign_company=_FY_2025_26.surcharge_foreign_company,
    capital_gains_surcharge_cap_percent=_FY_2025_26.capital_gains_surcharge_cap_percent,
    cess_percent=_FY_2025_26.cess_percent,
    section_206aa_floor_bps=_FY_2025_26.section_206aa_floor_bps,
)

RATES_BY_FY: dict[str, FY195Rates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

# Nothing here is verified against primary legislation yet, so this names the
# most recent year whose figures were at least reconciled rather than carried
# forward. It is NOT a claim that they were checked against the Finance Act —
# .verified says that, and it is False for both years.
LATEST_VERIFIED_FY = "2025-26"

# Every nature the registry can price. The migration's CHECK constraint and the
# frontend's dropdown are both generated from this, so a nature can only be
# added in one place.
ALL_NATURES = tuple(_FY_2025_26.natures)


def rates_are_verified(fy: str | None = None) -> bool:
    """Whether somebody has confirmed this year's figures against the Finance
    Act. Currently False for every year — see the module docstring.

    Exists so callers do not each reach into `.verified` and so a caller CANNOT
    accidentally ask about the year it fell back to: rates_for() substitutes
    LATEST_VERIFIED_FY for a missing year, and a fallback is by definition not
    a confirmation of the year that was asked about.
    """
    key = fy or current_fy()
    entry = RATES_BY_FY.get(key)
    return bool(entry and entry.verified)


def coverage() -> list[dict]:
    """Which years the registry holds and whether each was confirmed.

    For the annual maintenance sweep and for the API that shows a firm the same
    thing without reading source. Sorted, so a missing year is visible as a gap
    in the sequence rather than by counting.
    """
    return [
        {"fy": fy, "verified": RATES_BY_FY[fy].verified,
         "natures": len(RATES_BY_FY[fy].natures)}
        for fy in sorted(RATES_BY_FY)
    ]


def rates_for(fy: str | None = None) -> FY195Rates:
    """The s.195 rates for one FY.

    Falls back to LATEST_VERIFIED_FY for a year the registry does not hold —
    the same shape as every other rate registry here, and the same trap
    CLAUDE.md warns about: a missing year is not an error, it is last year's
    rates returned confidently. `.fy` on the result tells you which year you
    actually got.
    """
    key = fy or current_fy()
    if key in RATES_BY_FY:
        return RATES_BY_FY[key]
    return RATES_BY_FY[LATEST_VERIFIED_FY]
