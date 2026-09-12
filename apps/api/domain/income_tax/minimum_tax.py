"""
Minimum taxes — MAT under §115JB and AMT under §115JC to §115JF.

Both exist for the same reason: a taxpayer whose ordinary liability has been
reduced to little or nothing by incentives still pays a floor. Neither existed
in this codebase, so a company with large book profits and small taxable income
— the exact case MAT was written for — was computed as owing almost nothing.

They are NOT one rule with two names, and the differences are the whole
substance:

    MAT (§115JB)   COMPANIES. 15% of BOOK PROFIT — the profit in the profit and
                   loss account prepared under the Companies Act, adjusted by
                   Explanation 1 — not of taxable income. It does NOT apply to
                   a company that has opted into §115BAA or §115BAB: those
                   regimes trade the incentives away for a lower rate, so there
                   is nothing left for a floor to catch.

    AMT (§115JC)   EVERYONE ELSE — individual, HUF, firm, LLP, AOP, BOI. 18.5%
                   of ADJUSTED TOTAL INCOME, which is total income with the
                   §10AA, §35AD and Chapter VI-A Part C deductions added back.
                   It applies ONLY where such a deduction has been claimed; a
                   taxpayer who claimed none is outside the charge entirely.

THE THRESHOLD ASYMMETRY, WHICH IS EASY TO MISS AND EXPENSIVE

§115JEE exempts a taxpayer whose adjusted total income is within 20 lakh — but
only an individual, HUF, AOP, BOI or artificial juridical person. A FIRM or LLP
gets no such cushion: once it has claimed a triggering deduction, AMT applies at
any income. Extending the threshold to firms is the natural-looking mistake, and
it silently zeroes the liability of every small LLP that claims §35AD.

THE CREDIT IS THE POINT, NOT A FOOTNOTE

Paying a minimum tax is not a penalty; the excess over the ordinary liability
becomes a CREDIT — §115JAA for MAT, §115JD for AMT — carried forward up to
fifteen assessment years and set off in a year when ordinary tax exceeds the
minimum. Computing the floor without recording the credit turns a timing
difference into a permanent cost, which is a real loss to the client and
invisible in the year it happens.

All monetary values are integer paise. Never float.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from domain.income_tax.entity_rates import (
    CRORE_PAISE, CompanyRegime, EntityKind, entity_rates_for,
)
from domain.income_tax.statutory_rates import (
    apply_surcharge_with_marginal_relief, cess_paise, rates_for,
)

LAKH_PAISE = 1_00_000_00

#: Which regime the assessee is taxed under. "old" is the default parameter
#: value throughout this module and NOT a claim about which regime is more
#: common — since AY 2024-25 §115BAC is the default — but because AMT can only
#: arise on the old one for the assessees §115BAC reaches, so a caller that has
#: not thought about the regime is asking the question that has an answer.
Regime = Literal["old", "new"]

#: The assessees §115BAC(1A) reaches: "an individual or Hindu undivided family
#: or association of persons (other than a co-operative society), or body of
#: individuals, whether incorporated or not, or an artificial juridical
#: person". A FIRM OR LLP IS NOT AMONG THEM — they are taxed at a flat 30% with
#: no regime to choose, which is why the regime question is latent for the only
#: caller `compute_amt` has today.
_SECTION_115BAC_ASSESSEES = frozenset({
    "individual", "huf", "aop", "boi", "artificial_juridical_person"})


def _amt_is_disapplied_by_the_new_regime(
    assessee: MinimumTaxAssessee, regime: Regime,
) -> bool:
    """Chapter XII-BA does not apply to a person taxed under §115BAC.

    The EFFECT is settled and universally applied: an assessee on the new
    regime pays no alternate minimum tax, and earns no §115JD credit for that
    year either. It is why the regime choice for a professional claiming
    §10AA, §35AD or a Chapter VI-A Part C deduction is not simply a slab
    comparison.

    ⚠️ `[S]`-graded on the CITATION, not the effect. The disapplying provision
    is §115JEE — inserted with a cross-reference to the option under §115BAC —
    and the Finance Act 2023 restructured §115BAC so that the new regime became
    the default and the OPTION became the one to leave it (§115BAC(6)). Which
    sub-section the cross-reference now names could not be read: direct egress
    is refused at this environment's proxy. So the rule is written as the
    effect, with the section named and the sub-section deliberately not
    guessed.

    A firm or LLP is outside §115BAC entirely, so `regime` cannot disapply AMT
    for them however it is set — the safe direction, since it charges the tax
    rather than waiving it on a section that does not reach them.
    """
    return regime == "new" and assessee in _SECTION_115BAC_ASSESSEES


# Assessees §115JEE gives the adjusted-total-income cushion to. A firm or LLP
# is deliberately absent — see the module docstring.
_THRESHOLD_ELIGIBLE = frozenset({"individual", "huf", "aop", "boi",
                                 "artificial_juridical_person"})

MinimumTaxAssessee = Literal[
    "individual", "huf", "aop", "boi", "artificial_juridical_person",
    "firm", "llp", "domestic_company",
]


@dataclass(frozen=True)
class MinimumTaxRates:
    fy: str
    verified: bool
    mat_rate_percent: int              # §115JB — 15% of book profit
    amt_rate_percent_x10: int          # §115JC — 18.5%, held x10 to stay integer
    amt_threshold_paise: int           # §115JEE — 20 lakh
    credit_carry_forward_years: int    # §115JAA / §115JD — 15


_FY_2025_26 = MinimumTaxRates(
    fy="2025-26",
    verified=True,
    mat_rate_percent=15,
    # 18.5% cannot be an integer percent. Held as tenths of a percent so the
    # arithmetic stays in integers — paise * 185 // 1000 — rather than
    # introducing a float into a tax computation.
    amt_rate_percent_x10=185,
    amt_threshold_paise=20 * LAKH_PAISE,
    credit_carry_forward_years=15,
)

_FY_2026_27 = MinimumTaxRates(**{**_FY_2025_26.__dict__, "fy": "2026-27",
                                 "verified": False})

RATES_BY_FY: dict[str, MinimumTaxRates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

LATEST_VERIFIED_FY = "2025-26"


def minimum_tax_rates_for(fy: Optional[str] = None) -> MinimumTaxRates:
    from domain.income_tax.statutory_rates import current_fy
    fy = fy or current_fy()
    return RATES_BY_FY.get(fy, RATES_BY_FY[LATEST_VERIFIED_FY])


@dataclass(frozen=True)
class MinimumTaxResult:
    section: str                  # "115JB", "115JC", or "" where neither applies
    applies: bool
    base_paise: int               # book profit, or adjusted total income
    rate_description: str
    minimum_tax_before_surcharge_paise: int
    surcharge_paise: int
    cess_paise: int
    minimum_tax_paise: int
    reasons: tuple[str, ...]


def _not_applicable(section: str, reason: str, base: int) -> MinimumTaxResult:
    return MinimumTaxResult(
        section=section, applies=False, base_paise=base, rate_description="",
        minimum_tax_before_surcharge_paise=0, surcharge_paise=0, cess_paise=0,
        minimum_tax_paise=0, reasons=(reason,),
    )


def compute_mat(
    *,
    book_profit_paise: int,
    company_regime: CompanyRegime = "normal",
    fy: Optional[str] = None,
) -> MinimumTaxResult:
    """§115JB — 15% of BOOK PROFIT, for a domestic company.

    Book profit is the profit shown in the profit and loss account prepared
    under the Companies Act and then adjusted by Explanation 1 to §115JB(2).
    It is NOT taxable income, and the difference between them is the whole
    reason the section exists — a company with large accounting profits and
    small taxable income is what MAT was written to catch.

    This computes the CHARGE on a book profit supplied to it; deriving book
    profit itself from the Schedule III statements is a separate piece of work
    (Explanation 1 has some twenty adjustments, and Form 29B is a report an
    accountant signs).
    """
    rates = minimum_tax_rates_for(fy)
    entity = entity_rates_for(rates.fy)
    base = max(0, book_profit_paise)

    if company_regime in ("115BAA", "115BAB"):
        return _not_applicable(
            "115JB",
            f"§115JB does not apply to a company taxed under §{company_regime}: "
            f"that regime trades the incentives away for a lower rate, so there "
            f"is nothing left for a minimum tax to catch.",
            base,
        )

    tax = base * rates.mat_rate_percent // 100
    surcharge = apply_surcharge_with_marginal_relief(
        base, tax, entity.company_surcharge, None,
        lambda inc: inc * rates.mat_rate_percent // 100)
    cess = cess_paise(tax + surcharge, rates_for(rates.fy))
    return MinimumTaxResult(
        section="115JB", applies=True, base_paise=base,
        rate_description=f"{rates.mat_rate_percent}% of book profit",
        minimum_tax_before_surcharge_paise=tax, surcharge_paise=surcharge,
        cess_paise=cess, minimum_tax_paise=tax + surcharge + cess,
        reasons=(f"§115JB charges {rates.mat_rate_percent}% of book profit, "
                 f"which is the profit under the Companies Act as adjusted by "
                 f"Explanation 1 — not taxable income.",),
    )


def compute_amt(
    *,
    adjusted_total_income_paise: int,
    assessee: MinimumTaxAssessee,
    claimed_specified_deduction: bool,
    fy: Optional[str] = None,
    regime: Regime = "old",
) -> MinimumTaxResult:
    """§115JC — 18.5% of ADJUSTED TOTAL INCOME, for a non-corporate assessee.

    Adjusted total income is total income with the deductions under §10AA,
    §35AD and Chapter VI-A Part C (other than §80P) added back. The charge is
    conditioned on one of those having been CLAIMED: a taxpayer who claimed
    none is outside Chapter XII-BA entirely, not merely below its threshold.

    §115JEE's 20 lakh cushion is available only to an individual, HUF, AOP, BOI
    or artificial juridical person. A firm or LLP has none.

    `regime` — IT-21. §115BAC disapplies the whole of Chapter XII-BA for the
    assessees it reaches, and this had no way to say so. See
    `_amt_is_disapplied_by_the_new_regime` for the reasoning and its grade;
    the default is "old" because that is the only regime in which AMT can
    arise at all for those assessees, and because a firm or LLP — the only
    caller today — has no §115BAC to exercise.
    """
    rates = minimum_tax_rates_for(fy)
    entity = entity_rates_for(rates.fy)
    base = max(0, adjusted_total_income_paise)

    if assessee == "domestic_company":
        return _not_applicable(
            "115JC",
            "§115JC applies to non-corporate assessees. A company is charged "
            "the minimum tax under §115JB instead.",
            base,
        )

    if _amt_is_disapplied_by_the_new_regime(assessee, regime):
        return _not_applicable(
            "115JC",
            "§115BAC's regime disapplies Chapter XII-BA: an assessee taxed "
            "under it pays no alternate minimum tax, and carries forward no "
            "§115JD credit for the year either. Since AY 2024-25 that regime "
            "is the DEFAULT, so this is the ordinary case and the old regime "
            "is what has to be elected. A firm or LLP is unaffected — §115BAC "
            "does not reach them and AMT applies to them whatever they do.",
            base,
        )

    if not claimed_specified_deduction:
        return _not_applicable(
            "115JC",
            "No deduction under §10AA, §35AD or Chapter VI-A Part C has been "
            "claimed, so Chapter XII-BA does not apply at all — this is not a "
            "case of falling below the threshold.",
            base,
        )

    if assessee in _THRESHOLD_ELIGIBLE and base <= rates.amt_threshold_paise:
        return _not_applicable(
            "115JC",
            f"§115JEE exempts an assessee of this kind whose adjusted total "
            f"income is within {rates.amt_threshold_paise} paise. Note that a "
            f"firm or LLP gets no such cushion.",
            base,
        )

    tax = base * rates.amt_rate_percent_x10 // 1000
    # THE LADDER IS THE ASSESSEE'S OWN (IT-07). This passed
    # `entity.firm_surcharge` — the single 12%-above-₹1-crore bracket — for
    # every non-corporate assessee, so an individual, HUF, AOP, BOI or
    # artificial juridical person in AMT was surcharged at a firm's rate. The
    # individual ladder is 10 / 15 / 25 / 37 by income, and at ₹6 crore of
    # adjusted total income the difference is 25 percentage points of the tax.
    #
    # NO NEW-REGIME CAP, and that falls out of the branch above rather than
    # being a second decision: §115BAC disapplies Chapter XII-BA for exactly
    # the assessees the cap is about, so an individual who reaches this line
    # is on the OLD regime by construction and the full ladder is theirs.
    surcharge_brackets = (
        entity.firm_surcharge if assessee in ("firm", "llp")
        else rates_for(rates.fy).surcharge_brackets)
    surcharge = apply_surcharge_with_marginal_relief(
        base, tax, surcharge_brackets, None,
        lambda inc: inc * rates.amt_rate_percent_x10 // 1000)
    cess = cess_paise(tax + surcharge, rates_for(rates.fy))
    pct = rates.amt_rate_percent_x10 / 10
    reasons = [f"§115JC charges {pct}% of adjusted total income — total income "
               f"with the §10AA, §35AD and Chapter VI-A Part C deductions added "
               f"back."]
    if assessee in ("firm", "llp"):
        reasons.append(
            "A firm or LLP has no §115JEE threshold: once a triggering "
            "deduction is claimed, AMT applies at any income."
        )
    return MinimumTaxResult(
        section="115JC", applies=True, base_paise=base,
        rate_description=f"{pct}% of adjusted total income",
        minimum_tax_before_surcharge_paise=tax, surcharge_paise=surcharge,
        cess_paise=cess, minimum_tax_paise=tax + surcharge + cess,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class MinimumTaxOutcome:
    tax_payable_paise: int
    minimum_tax_applied: bool
    credit_generated_paise: int
    credit_expires_after_ay: Optional[int]
    reasons: tuple[str, ...]


def apply_minimum_tax(
    *,
    regular_tax_paise: int,
    minimum: MinimumTaxResult,
    assessment_year_end: Optional[int] = None,
    fy: Optional[str] = None,
) -> MinimumTaxOutcome:
    """The higher of the two is payable, and the excess becomes a credit.

    §115JAA (MAT) and §115JD (AMT) both carry the excess forward for fifteen
    assessment years, to be set off in a year when the ordinary liability
    exceeds the minimum. Charging the floor WITHOUT recording the credit turns
    a timing difference into a permanent cost — a real loss to the client, and
    invisible in the year it is incurred because the return still balances.
    """
    rates = minimum_tax_rates_for(fy)
    regular = max(0, regular_tax_paise)
    reasons: list[str] = []

    if not minimum.applies or minimum.minimum_tax_paise <= regular:
        if minimum.applies:
            reasons.append(
                f"Ordinary tax of {regular} paise is at least the §"
                f"{minimum.section} minimum of {minimum.minimum_tax_paise} "
                f"paise, so the ordinary liability stands and no credit arises."
            )
        return MinimumTaxOutcome(
            tax_payable_paise=regular, minimum_tax_applied=False,
            credit_generated_paise=0, credit_expires_after_ay=None,
            reasons=tuple(reasons + list(minimum.reasons)),
        )

    credit = minimum.minimum_tax_paise - regular
    expiry = (assessment_year_end + rates.credit_carry_forward_years
              if assessment_year_end is not None else None)
    reasons.append(
        f"§{minimum.section} minimum of {minimum.minimum_tax_paise} paise "
        f"exceeds ordinary tax of {regular} paise, so the minimum is payable "
        f"and the excess of {credit} paise becomes a credit under "
        f"§{'115JAA' if minimum.section == '115JB' else '115JD'}, available "
        f"for {rates.credit_carry_forward_years} assessment years."
    )
    return MinimumTaxOutcome(
        tax_payable_paise=minimum.minimum_tax_paise, minimum_tax_applied=True,
        credit_generated_paise=credit, credit_expires_after_ay=expiry,
        reasons=tuple(reasons + list(minimum.reasons)),
    )
