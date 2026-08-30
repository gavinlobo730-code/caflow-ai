"""
Tax rates for entities that are not individuals — IT Act 1961.

domain/income_tax/statutory_rates carries the INDIVIDUAL slabs, and nothing
carried anything else. A partnership firm, an LLP and a company each pay tax on
a completely different basis from an individual and from each other, so a
practice serving any of them could not compute their liability at all.

WHAT EACH PAYS (verified against published sources for FY 2025-26 before being
written down, not recalled):

  FIRM or LLP     30% flat — no slabs, no exemption limit, from the first
                  rupee. Surcharge 12% where total income exceeds 1 crore,
                  with marginal relief. Cess 4%.

  DOMESTIC COMPANY, normal regime
                  25% where turnover or gross receipts in the reference year
                  did not exceed 400 crore, otherwise 30%. Surcharge 7% above
                  1 crore and 12% above 10 crore, with marginal relief.
                  Cess 4%.

  §115BAA         22%, for a domestic company that opts in and forgoes the
                  listed incentives. Surcharge a FLAT 10% whatever the income.
                  Cess 4%. Effective 25.168%.

  §115BAB         15%, for a new domestic manufacturing company. Surcharge a
                  flat 10%, cess 4%. Effective 17.16%.

TWO THINGS THAT ARE EASY TO GET WRONG

The 400 crore test does NOT look at the year being taxed. It looks at the
turnover of a year two back — for AY 2026-27, whose previous year is 2025-26,
the test year is 2023-24. Using the current year's turnover moves companies
across the 25%/30% boundary in the wrong direction and by a whole year.

The concessional surcharge is flat and unconditional. A normal company under 1
crore pays no surcharge at all; a §115BAA company at the same income pays 10%.
Reusing the normal brackets for a company that has opted in understates its tax
by a tenth.

All monetary values are integer paise. Never float.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from domain.income_tax.statutory_rates import (
    SurchargeBracket, apply_surcharge_with_marginal_relief, cess_paise, rates_for,
)

CRORE_PAISE = 1_00_00_000_00

EntityKind = Literal["firm", "llp", "domestic_company"]
CompanyRegime = Literal["normal", "115BAA", "115BAB"]


@dataclass(frozen=True)
class EntityTaxRates:
    fy: str
    verified: bool

    # Firms and LLPs are taxed identically; the LLP Act changes who they are,
    # not what they pay.
    firm_rate_percent: int
    firm_surcharge: tuple[SurchargeBracket, ...]

    company_rate_percent: int
    company_concessional_rate_percent: int
    company_turnover_limit_paise: int
    # How many years BEFORE the previous year the turnover test looks at.
    company_turnover_lookback_years: int
    company_surcharge: tuple[SurchargeBracket, ...]

    s115baa_rate_percent: int
    s115bab_rate_percent: int
    # Flat, and it applies from the first rupee — see the module docstring.
    concessional_surcharge_percent: int


_FY_2025_26 = EntityTaxRates(
    fy="2025-26",
    verified=True,
    firm_rate_percent=30,
    firm_surcharge=(SurchargeBracket(above_paise=1 * CRORE_PAISE, rate_percent=12),),
    company_rate_percent=30,
    company_concessional_rate_percent=25,
    company_turnover_limit_paise=400 * CRORE_PAISE,
    company_turnover_lookback_years=2,
    company_surcharge=(
        SurchargeBracket(above_paise=1 * CRORE_PAISE, rate_percent=7),
        SurchargeBracket(above_paise=10 * CRORE_PAISE, rate_percent=12),
    ),
    s115baa_rate_percent=22,
    s115bab_rate_percent=15,
    concessional_surcharge_percent=10,
)

# Carried forward, not guessed — same contract as statutory_rates.
_FY_2026_27 = EntityTaxRates(**{**_FY_2025_26.__dict__, "fy": "2026-27",
                                "verified": False})

RATES_BY_FY: dict[str, EntityTaxRates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

LATEST_VERIFIED_FY = "2025-26"


def entity_rates_for(fy: Optional[str] = None) -> EntityTaxRates:
    from domain.income_tax.statutory_rates import current_fy
    fy = fy or current_fy()
    return RATES_BY_FY.get(fy, RATES_BY_FY[LATEST_VERIFIED_FY])


def turnover_reference_fy(fy: str, rates: Optional[EntityTaxRates] = None) -> str:
    """The financial year whose turnover decides the 25% company rate.

    For FY 2025-26 (AY 2026-27) that is FY 2023-24 — two years back, not the
    year being taxed. Returned as a label so a caller fetches the right year's
    figure rather than reaching for the one in front of them.
    """
    rates = rates or entity_rates_for(fy)
    start = int(fy.split("-")[0]) - rates.company_turnover_lookback_years
    return f"{start}-{str(start + 1)[2:]}"


@dataclass(frozen=True)
class EntityTaxResult:
    entity: str
    regime: str
    fy: str
    rate_percent: int
    tax_before_surcharge_paise: int
    surcharge_paise: int
    cess_paise: int
    total_tax_paise: int
    turnover_reference_fy: Optional[str]
    workings: tuple[str, ...]


def compute_entity_tax(
    *,
    total_income_paise: int,
    entity: EntityKind,
    fy: Optional[str] = None,
    company_regime: CompanyRegime = "normal",
    turnover_in_reference_year_paise: Optional[int] = None,
) -> EntityTaxResult:
    """Tax for a firm, an LLP or a domestic company.

    `turnover_in_reference_year_paise` is the turnover of the year
    turnover_reference_fy names — NOT of the year being taxed. When it is not
    supplied for a normal-regime company the higher 30% rate is used, because
    the concession has to be established rather than assumed: guessing the
    lower rate understates a liability, which is the direction that produces a
    demand notice.
    """
    rates = entity_rates_for(fy)
    income = max(0, total_income_paise)
    workings: list[str] = []
    ref_fy: Optional[str] = None

    if entity in ("firm", "llp"):
        rate = rates.firm_rate_percent
        brackets = rates.firm_surcharge
        flat_surcharge = None
        workings.append(
            f"A {'partnership firm' if entity == 'firm' else 'limited liability partnership'} "
            f"is taxed at a flat {rate}% from the first rupee — no slabs and no "
            f"exemption limit."
        )
    elif entity == "domestic_company":
        ref_fy = turnover_reference_fy(rates.fy, rates)
        if company_regime == "115BAA":
            rate = rates.s115baa_rate_percent
            brackets = ()
            flat_surcharge = rates.concessional_surcharge_percent
            workings.append(
                f"§115BAA: {rate}%, with surcharge at a flat "
                f"{flat_surcharge}% whatever the income."
            )
        elif company_regime == "115BAB":
            rate = rates.s115bab_rate_percent
            brackets = ()
            flat_surcharge = rates.concessional_surcharge_percent
            workings.append(
                f"§115BAB: {rate}% for a new domestic manufacturing company, "
                f"with surcharge at a flat {flat_surcharge}%."
            )
        else:
            flat_surcharge = None
            brackets = rates.company_surcharge
            if turnover_in_reference_year_paise is None:
                rate = rates.company_rate_percent
                workings.append(
                    f"Turnover for {ref_fy} was not supplied, so the "
                    f"{rate}% rate applies. The "
                    f"{rates.company_concessional_rate_percent}% rate has to be "
                    f"established, not assumed."
                )
            elif turnover_in_reference_year_paise <= rates.company_turnover_limit_paise:
                rate = rates.company_concessional_rate_percent
                workings.append(
                    f"Turnover for {ref_fy} of "
                    f"{turnover_in_reference_year_paise} paise is within the "
                    f"{rates.company_turnover_limit_paise} paise limit, so "
                    f"{rate}% applies."
                )
            else:
                rate = rates.company_rate_percent
                workings.append(
                    f"Turnover for {ref_fy} exceeds the "
                    f"{rates.company_turnover_limit_paise} paise limit, so "
                    f"{rate}% applies."
                )
    else:
        raise ValueError(f"{entity!r} is not an entity this module rates")

    tax = income * rate // 100

    if flat_surcharge is not None:
        # Flat and unconditional, so no marginal relief: there is no threshold
        # to be pushed over.
        surcharge = tax * flat_surcharge // 100
    else:
        surcharge = apply_surcharge_with_marginal_relief(
            income, tax, brackets, None, lambda inc: inc * rate // 100)

    cess = cess_paise(tax + surcharge, rates_for(rates.fy))
    return EntityTaxResult(
        entity=entity,
        regime=company_regime if entity == "domestic_company" else "flat",
        fy=rates.fy,
        rate_percent=rate,
        tax_before_surcharge_paise=tax,
        surcharge_paise=surcharge,
        cess_paise=cess,
        total_tax_paise=tax + surcharge + cess,
        turnover_reference_fy=ref_fy,
        workings=tuple(workings),
    )
