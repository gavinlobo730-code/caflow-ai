"""
Income Tax Return computation engine.
IT Act 1961 — Section 80C, 80CCD, 80D, 80G (with its Section 80G(4)
qualifying limit and Section 80G(5D) cash bar), 80TTA, 80TTB, 10(13A),
24(b), 87A, and the Section 71(3)/74 refusal to set a capital loss off
against any other head.

Slab/rebate/surcharge rates come from domain.income_tax.statutory_rates — the
single, FY-versioned source of truth (Tier 2 R2.3). See that module's
docstring for which financial years are verified against a confirmed Finance
Act versus carried forward pending confirmation.

All monetary values in integer paise. Never float.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from domain.reporting.amount_words import indian_rupees
from domain.income_tax.statutory_rates import (
    FYTaxRates, apply_rebate_87a, apply_surcharge_with_marginal_relief,
    cess_paise, rates_for, resolve_surcharge_bracket, slab_tax_paise,
)
from domain.income_tax.entity_rates import compute_entity_tax
from domain.income_tax.loss_set_off import (
    apply_brought_forward_losses, BroughtForwardLoss,
)
from domain.income_tax.minimum_tax import apply_minimum_tax, compute_amt, compute_mat


# ── Constants (all paise) ─────────────────────────────────────────────────────
# Chapter VI-A deduction limits are stable across recent Finance Acts (unlike
# the slabs/rebate/surcharge in statutory_rates.py) — kept here rather than
# FY-versioned unless a specific limit is found to have changed.

# IT Act Section 80C — aggregate limit
LIMIT_80C_PAISE: int = 150_000 * 100

# IT Act Section 80CCD(1B) — additional NPS
LIMIT_80CCD1B_PAISE: int = 50_000 * 100

# IT Act Section 80CCD(2) — employer's NPS contribution, capped at a % of
# "salary" (basic + DA). Deductible under BOTH regimes (Section 115BAC(2)(i)
# specifically carves this out of the new regime's blanket Chapter VI-A
# disallowance) — unlike every other limit in this file, which applies to
# old-regime filers only.
#
# PENDING STATUTORY VERIFICATION (R3.10): Budget 2024/Finance Act 2024 is
# understood to have raised the new-regime cap for NON-government
# employees from 10% to 14% of salary, matching what government employees
# already had — but that specific change is not independently confirmed
# against the Act's own text from anything in this repository (no prior
# implementation of this section existed anywhere to port a verified
# baseline from, unlike R3.1b's capital-gains rates). The long-established,
# not-in-question 10%/14% government-vs-other split is used here in BOTH
# regimes until the newer regime-dependent enhancement for non-government
# employees is confirmed — the conservative direction (a filer may be
# entitled to a slightly larger 80CCD(2) deduction under the new regime
# than this computes), never the dangerous one (over-claiming a deduction).
LIMIT_80CCD2_GOVT_PERCENT: int = 14
LIMIT_80CCD2_OTHER_PERCENT: int = 10

# IT Act Section 80D limits
LIMIT_80D_SELF_PAISE: int = 25_000 * 100
LIMIT_80D_SELF_SENIOR_PAISE: int = 50_000 * 100
LIMIT_80D_PARENTS_PAISE: int = 25_000 * 100
LIMIT_80D_PARENTS_SENIOR_PAISE: int = 50_000 * 100

# IT Act Section 80TTA (savings interest for non-senior)
LIMIT_80TTA_PAISE: int = 10_000 * 100

# IT Act Section 80TTB (all interest for senior citizen)
LIMIT_80TTB_PAISE: int = 50_000 * 100

# IT Act Section 24(b) — home loan interest self-occupied
LIMIT_24B_PAISE: int = 200_000 * 100

# IT Act Section 71(3A) — the most house-property LOSS that may be set off
# against income under any other head in a year, under the OLD regime. It is
# ₹2,00,000 like §24(b) above and is a different rule about a different thing:
# §24(b) caps a DEDUCTION for interest, §71(3A) caps a SET-OFF of the
# resulting loss. Keeping one constant for both invited the next reader to
# "simplify" two independent limits into one. Under the NEW regime §115BAC(2)
# allows no such set-off at all, so this limit does not apply there.
LIMIT_SET_OFF_71_3A_PAISE: int = 200_000 * 100


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Deductions80C:
    """IT Act Section 80C eligible investments."""
    ppf_paise: int = 0
    elss_paise: int = 0
    lic_paise: int = 0
    nsc_paise: int = 0
    home_loan_principal_paise: int = 0
    tuition_fees_paise: int = 0
    fd_5yr_paise: int = 0
    sukanya_samriddhi_paise: int = 0
    ulip_paise: int = 0
    # Anything eligible under §80C that is not one of the named buckets above —
    # a term deposit with a scheduled bank, NPS under §80CCD(1), stamp duty on
    # a house, and so on. §80C(2) runs to twenty-odd clauses and enumerating
    # them all as fields would still miss one; the aggregate limit in §80CCE
    # applies to the total either way, which is what total_paise feeds.
    other_paise: int = 0

    def total_paise(self) -> int:
        return (self.ppf_paise + self.elss_paise + self.lic_paise
                + self.nsc_paise + self.home_loan_principal_paise
                + self.tuition_fees_paise + self.fd_5yr_paise
                + self.sukanya_samriddhi_paise + self.ulip_paise
                + self.other_paise)


@dataclass
class Deductions80D:
    """IT Act Section 80D — health insurance premiums."""
    self_family_premium_paise: int = 0
    self_family_is_senior: bool = False
    parents_premium_paise: int = 0
    parents_is_senior: bool = False

    def eligible_paise(self) -> int:
        self_limit = LIMIT_80D_SELF_SENIOR_PAISE if self.self_family_is_senior else LIMIT_80D_SELF_PAISE
        parents_limit = LIMIT_80D_PARENTS_SENIOR_PAISE if self.parents_is_senior else LIMIT_80D_PARENTS_PAISE
        return min(self.self_family_premium_paise, self_limit) + min(self.parents_premium_paise, parents_limit)


# IT Act Section 80G(4) — the qualifying limit. Donations in the "subject to
# qualifying limit" category qualify only up to ten per cent of adjusted
# gross total income; the excess "shall be ignored".
LIMIT_80G_QUALIFYING_PERCENT: int = 10

# IT Act Section 80G(5D) — no deduction at all for a donation of any sum
# EXCEEDING ₹2,000 unless it was paid by a mode other than cash. Exactly
# ₹2,000 in cash is still allowed; ₹2,001 is not.
LIMIT_80G_CASH_PAISE: int = 2_000 * 100


@dataclass
class Donation80G:
    """One donation claimed under IT Act Section 80G.

    `deduction_pct` (100 or 50) and `subject_to_qualifying_limit` are two
    INDEPENDENT facts about the donee, and the section's four categories are
    their product: 100% without limit (Section 80G(1)(i) — the PM National
    Relief Fund, the National Defence Fund and the rest of that list), 50%
    without limit, 100% subject to the limit, and 50% subject to the limit
    (the residual case — an approved fund or institution under
    Section 80G(2)(a)(iv)). Only `deduction_pct` existed before, which could
    not express the difference at all, so every donation was deducted at its
    percentage with no ceiling: ₹9,00,000 at 50% gave a ₹4,50,000 deduction
    against a ₹10,00,000 salary.

    The default is True — subject to the limit — because that is the
    residual category the section itself puts an unlisted donee in, and
    because it is the direction that cannot over-claim. A donation to a fund
    listed in Section 80G(1)(i) has to be marked.

    `paid_in_cash` is deliberately tri-state. Section 80G(5D) turns on the
    MODE of payment, which is a fact about the transaction that no caller in
    this repository supplies today (routers/income_tax.py's Donation80GInput
    has no such field). None means "not stated": the deduction is allowed,
    because denying every donation a CA has ever entered is not a defensible
    default either, and compute() raises a warning naming the amount so the
    silence is visible. A zero for "paid by cheque" and a zero for "nobody
    said" must not be the same number.
    """
    description: str
    amount_paise: int
    deduction_pct: int  # 100 or 50
    subject_to_qualifying_limit: bool = True
    paid_in_cash: Optional[bool] = None

    def disallowed_by_80g_5d(self) -> bool:
        """Section 80G(5D): a cash donation over ₹2,000 gets no deduction."""
        return bool(self.paid_in_cash) and self.amount_paise > LIMIT_80G_CASH_PAISE

    def mode_of_payment_unstated(self) -> bool:
        """Over ₹2,000 and nobody said how it was paid — the one case where
        Section 80G(5D) could change the answer and the input cannot say."""
        return self.paid_in_cash is None and self.amount_paise > LIMIT_80G_CASH_PAISE

    def deduction_before_qualifying_limit_paise(self) -> int:
        """Amount × percentage, i.e. the deduction BEFORE Section 80G(4)'s
        ceiling is applied to the aggregate. Never the final figure for a
        donation subject to the qualifying limit — deliberately not called
        `eligible_paise`, because a method with that name returning a
        pre-ceiling number is exactly how the ceiling got skipped."""
        if self.disallowed_by_80g_5d():
            return 0
        return self.amount_paise * self.deduction_pct // 100


def compute_80g_deduction(
    donations: list[Donation80G], adjusted_gti_paise: int,
) -> tuple[int, list[str]]:
    """Section 80G deduction for a year's donations, and the warnings that
    explain any amount the section refused.

    Section 80G(4): where the aggregate of the donations in the categories
    that carry a qualifying limit exceeds ten per cent of adjusted gross
    total income, "the amount in excess ... shall be ignored". The ceiling
    applies to the AGGREGATE of those donations, and Section 80G(1) then
    applies 100% or 50% to what qualifies.

    FLAGGED, not guessed: where the ceiling bites AND the limited donations
    carry different percentages, the section does not say which of them the
    qualifying amount is made up of. Long-standing practice adjusts the
    ceiling against the 100% donations first, as more beneficial to the
    assessee; this function apportions the qualifying amount pro rata by
    donation instead, which can never exceed the most-beneficial figure, and
    warns when the choice actually changed the answer. Adopting the
    most-beneficial ordering is a one-line change here once somebody
    confirms it against the section rather than against a textbook."""
    warnings: list[str] = []
    allowed = [d for d in donations if not d.disallowed_by_80g_5d()]

    refused = [d for d in donations if d.disallowed_by_80g_5d()]
    if refused:
        total_refused = sum(d.amount_paise for d in refused)
        warnings.append(
            f"Section 80G(5D): ₹{total_refused // 100:,} of donations was paid in cash in "
            f"sums exceeding ₹2,000. No deduction is allowed for those donations."
        )

    unstated = sum(d.amount_paise for d in allowed if d.mode_of_payment_unstated())
    if unstated:
        warnings.append(
            f"Section 80G(5D): ₹{unstated // 100:,} of donations exceeds ₹2,000 per donation "
            f"and no mode of payment is recorded. The deduction below assumes they were not "
            f"paid in cash — a cash donation over ₹2,000 gets no deduction at all."
        )

    # Category A/B — deductible without any qualifying limit.
    deduction = sum(d.deduction_before_qualifying_limit_paise()
                    for d in allowed if not d.subject_to_qualifying_limit)

    limited = [d for d in allowed if d.subject_to_qualifying_limit]
    gross_limited = sum(d.amount_paise for d in limited)
    if not gross_limited:
        return deduction, warnings

    ceiling = max(0, adjusted_gti_paise) * LIMIT_80G_QUALIFYING_PERCENT // 100
    qualifying = min(gross_limited, ceiling)

    if qualifying >= gross_limited:
        deduction += sum(d.deduction_before_qualifying_limit_paise() for d in limited)
        return deduction, warnings

    # The ceiling bites. Apportion it pro rata; integer division floors, so
    # the sum of the parts never exceeds the qualifying amount.
    for d in limited:
        share = d.amount_paise * qualifying // gross_limited
        deduction += share * d.deduction_pct // 100
    warnings.append(
        f"Section 80G(4): donations subject to the qualifying limit total "
        f"₹{gross_limited // 100:,}, of which only ₹{qualifying // 100:,} qualifies — "
        f"10% of adjusted gross total income (₹{max(0, adjusted_gti_paise) // 100:,}). "
        f"A donation to a fund listed in Section 80G(1)(i), such as the PM National Relief "
        f"Fund, carries no qualifying limit and should be marked as not subject to it."
    )
    if len({d.deduction_pct for d in limited}) > 1:
        warnings.append(
            "Section 80G(4) caps the aggregate of the limited donations but does not say "
            "how the qualifying amount is split between the 100% and 50% categories. It has "
            "been apportioned pro rata here; practice commonly adjusts it against the 100% "
            "donations first, which would give a larger deduction. CA review required."
        )
    return deduction, warnings


@dataclass
class HRADetails:
    """IT Act Section 10(13A) — House Rent Allowance."""
    basic_salary_paise: int = 0
    hra_received_paise: int = 0
    rent_paid_paise: int = 0
    is_metro: bool = False

    def exemption_paise(self) -> int:
        """Min of: actual HRA, 50%/40% of basic, rent paid minus 10% of basic."""
        if self.rent_paid_paise == 0:
            return 0
        pct_basic = 5000 if self.is_metro else 4000  # basis points
        half_basic = self.basic_salary_paise * pct_basic // 10000
        rent_minus_ten = max(0, self.rent_paid_paise - self.basic_salary_paise * 1000 // 10000)
        return min(self.hra_received_paise, min(half_basic, rent_minus_ten))


def _assessment_year_for(fy: str | None) -> str | None:
    """The assessment year an FY is assessed in — FY 2025-26 -> AY 2026-27.

    Used only to test whether a brought-forward loss has run out of years; a
    label this cannot parse gives None, and loss_set_off then falls back to the
    row's own is_expired flag rather than guessing the loss is still alive.
    """
    text = str(fy or "").strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    start = int(text[:4]) + 1
    return f"{start}-{str(start + 1)[2:]}"


@dataclass
class ITRComputeRequest:
    """Full income + deduction inputs for ITR computation."""
    # Income heads (all paise)
    gross_salary_paise: int = 0
    other_income_paise: int = 0        # interest, dividend etc
    house_property_income_paise: int = 0   # negative = loss
    business_income_paise: int = 0
    # Add-backs to business income accepted by the CA in the computation
    # workspace: §40A(3) cash payments, §43B liabilities unpaid by the §139(1)
    # due date, and anything else disallowed. A disallowance INCREASES taxable
    # business income — before this field existed the workspace recorded them,
    # displayed them, and changed the computed tax by exactly nothing.
    disallowances_paise: int = 0
    # Presumptive business income under §44AD / §44ADA / §44AE, computed by
    # domain.income_tax.presumptive and supplied here as the already-determined
    # figure. When set, it REPLACES business_income_paise rather than adding to
    # it: under a presumptive scheme the statutory percentage IS the business
    # income, and §44AD(2) / §44ADA(3) / §44AE(6) deem every deduction under
    # §30 to §38 already allowed. Adding book profit on top would tax the same
    # business twice.
    presumptive_income_paise: Optional[int] = None
    # IT-10. Brought-forward losses from earlier years, as
    # brought_forward_losses holds them. Each is set off ONLY against the head
    # its own section reaches — §72 business, §73 speculation, §71B house
    # property, §74 capital — by domain.income_tax.loss_set_off, which is where
    # the rules and their reasons live. Before this field existed the workspace
    # recorded them, the screen displayed them, and the computed tax moved by
    # exactly nothing.
    brought_forward_losses: list = field(default_factory=list)
    capital_gains_stcg_paise: int = 0
    capital_gains_ltcg_paise: int = 0      # equity, 12.5% (Section 112A)
    capital_gains_ltcg_other_paise: int = 0  # property, debt MF etc, 12.5%/20%
    exempt_income_paise: int = 0

    # WHO IS BEING ASSESSED. "individual" takes the slab path below; "firm",
    # "llp" and "domestic_company" take the flat entity rate in
    # domain.income_tax.entity_rates and then the §115JB/§115JC minimum.
    #
    # Defaulted to "individual" so every existing caller is unchanged — but
    # `entity_type` is the field the API actually resolves this from, because
    # the mapping (a PROPRIETORSHIP is an individual; a trust is refused) is
    # statutory knowledge and belongs in apps/api, not on a screen.
    assessee_kind: str = "individual"

    # Company only. §115BAA (22%) and §115BAB (15%) are ELECTIONS, and their
    # surcharge is a flat 10% whatever the income — reusing the normal
    # brackets for a company that has opted in understates its tax by a tenth.
    company_regime: str = "normal"
    # The 25%/30% test looks at the turnover of a year TWO BACK, not the year
    # being taxed — entity_rates.turnover_reference_fy names it. Absent, the
    # higher rate is used: the concession has to be established rather than
    # assumed.
    turnover_in_reference_year_paise: Optional[int] = None
    # §115JB book profit (a company) and §115JC's trigger (a firm or LLP).
    # Book profit is NOT taxable income — the gap between them is the whole
    # reason §115JB exists — so it cannot be derived here and is supplied.
    book_profit_paise: Optional[int] = None
    claimed_specified_deduction: bool = False
    # The AY the MAT/AMT credit is measured from, for its fifteen-year expiry.
    assessment_year_end: Optional[int] = None

    # Regime
    use_new_regime: bool = True
    is_senior_citizen: bool = False       # 60-80 years
    is_very_senior_citizen: bool = False  # > 80 years

    # WAS THIS ASSESSEE RESIDENT IN INDIA THIS YEAR (IT Act §6)?
    #
    # Defaulted True because this engine was ALREADY assuming it, silently, in
    # two places: §87A reaches "an individual, being a resident" and is granted
    # here unconditionally, and §80G's adjusted-GTI base deliberately omits the
    # §§115A/115AB/115AC/115AD income a non-resident can have (see that
    # comment). Making the assumption a field states it rather than changing
    # it — and gives the basic-exemption absorption below the test its own
    # provisos require, without inventing residence for callers that never
    # said. A caller that knows better can now say so.
    #
    # NOT derived from the client record: `clients` has no residential status
    # column, and §6 turns on days present in India, which no ledger holds.
    is_resident: bool = True

    # Financial year (e.g. "2025-26"); defaults to the current FY. See
    # domain.income_tax.statutory_rates for which years are verified.
    fy: Optional[str] = None

    # Deductions (only applicable under old regime except standard deduction
    # and 80CCD(2))
    s80c: Deductions80C = field(default_factory=Deductions80C)
    nps_80ccd1b_paise: int = 0
    # Section 80CCD(2) — employer's NPS contribution. Available under both
    # regimes. `salary_for_80ccd2_paise` is "salary" (basic + DA) the cap is
    # computed against; if not supplied, gross_salary_paise is used as an
    # approximation (exact only when allowances are a small share of gross).
    employer_nps_80ccd2_paise: int = 0
    is_government_employee: bool = False
    salary_for_80ccd2_paise: Optional[int] = None
    s80d: Deductions80D = field(default_factory=Deductions80D)
    donations_80g: list[Donation80G] = field(default_factory=list)
    savings_interest_80tta_paise: int = 0
    hra: HRADetails = field(default_factory=HRADetails)
    home_loan_interest_24b_paise: int = 0
    other_deductions_paise: int = 0

    # TDS already deducted (for net payable computation)
    tds_deducted_paise: int = 0
    advance_tax_paid_paise: int = 0


@dataclass
class ITRComputeResult:
    """Computed ITR result — all amounts in paise."""
    # Income summary
    #: What the brought-forward losses actually relieved, and the per-loss
    #: working behind it — which section reached which head, and what is
    #: carried forward still.
    brought_forward_set_off_paise: int = 0
    brought_forward_set_off: list = field(default_factory=list)
    gross_total_income_paise: int = 0
    total_deductions_paise: int = 0
    taxable_income_paise: int = 0

    # Deduction breakdown
    deduction_80c_paise: int = 0
    deduction_80ccd_paise: int = 0
    deduction_80ccd2_paise: int = 0
    deduction_80d_paise: int = 0
    deduction_80g_paise: int = 0
    deduction_80tta_paise: int = 0
    deduction_hra_paise: int = 0
    deduction_24b_paise: int = 0
    standard_deduction_paise: int = 0

    # Tax computation
    tax_before_cess_paise: int = 0
    surcharge_paise: int = 0
    cess_paise: int = 0
    total_tax_paise: int = 0
    rebate_87a_paise: int = 0

    #: How much of the basic exemption the slab income did not use and the
    #: special-rate capital gains absorbed — the proviso to §111A(1), the
    #: proviso to §112(1)(a)(ii) and the second proviso to §112A(2). Zero for
    #: an assessee the provisos do not reach, and zero where the slab income
    #: already used the whole exemption.
    basic_exemption_absorbed_paise: int = 0
    #: Per-section working behind that figure, so a CA can see WHICH gain the
    #: exemption was set against — the statute gives no order and this engine
    #: takes the highest rate first, which is a choice a reader is entitled to
    #: check. One string per bucket that absorbed anything.
    basic_exemption_absorption: list = field(default_factory=list)

    #: THE CAPITAL-GAINS WORKING, ROW BY ROW — and the reason it is here is
    #: that until now it was not anywhere. The two fields above were computed,
    #: documented as existing "so a CA can see WHICH gain the exemption was set
    #: against", and then read by nothing: `grep -rn basic_exemption
    #: apps/api/routers apps/web` returned nothing at all. So a CA saw ₹20,800
    #: of tax on a ₹5,00,000 STCG with no account of the ₹4,00,000 that
    #: vanished, and could not check the highest-rate-first allocation the
    #: engine made on their behalf. CLAUDE.md: a figure the computer gets right
    #: and no screen shows is not a fixed bug.
    #:
    #: One row per special-rate section, always all three, so a zero row is
    #: visibly zero rather than absent. Keys: section, gross_paise,
    #: exempt_paise (§112A's annual exemption, nil on the other two),
    #: absorbed_paise, charged_paise, rate_percent, tax_paise.
    capital_gains_lines: list = field(default_factory=list)
    #: §§111A + 112A + 112 together, before surcharge and cess — the figure
    #: that is added to the slab tax AFTER the §87A rebate, never inside it.
    capital_gains_tax_paise: int = 0

    #: What the caller sent as §10 exempt income, echoed back.
    #:
    #: The engine does not use it and must not: §10 income does not enter total
    #: income, so the TAX is right without it. But `ITRComputeRequest` has
    #: declared the field since the beginning, the client Tax Computation tab
    #: renders an "Exempt Income (₹)" input, the router accepts it and passes
    #: it in — and `compute()` never read it, so a CA typed a figure into a
    #: live field, it changed nothing, and nothing said so. Echoing it is the
    #: honest half of the fix: the figure IS reportable (Schedule EI), it is
    #: simply not taxable, and a screen can now say which.
    exempt_income_reported_paise: int = 0

    # Payable
    tds_and_advance_paise: int = 0
    net_payable_paise: int = 0  # negative = refund

    # Entity assessees (firm / LLP / domestic company). Empty or zero on the
    # individual path, which is why they are separate fields rather than
    # overloading regime/rate: a reader must be able to tell which charge ran.
    assessee_kind: str = "individual"
    entity_rate_percent: int = 0
    turnover_reference_fy: Optional[str] = None
    entity_workings: list[str] = field(default_factory=list)

    # §115JB (company) / §115JC (firm, LLP). The credit is the point: §115JAA
    # and §115JD carry the excess forward for fifteen assessment years, and
    # charging the floor WITHOUT recording the credit turns a timing difference
    # into a permanent cost that is invisible in the year it is incurred.
    minimum_tax_section: str = ""
    minimum_tax_applies: bool = False
    minimum_tax_paise: int = 0
    minimum_tax_applied: bool = False
    minimum_tax_credit_paise: int = 0
    minimum_tax_credit_expires_after_ay: Optional[int] = None
    minimum_tax_reasons: list[str] = field(default_factory=list)

    # Meta
    regime: str = "new"
    fy: str = ""
    rates_verified: bool = True  # False -> see domain.income_tax.statutory_rates
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


def _stamp_rate_provenance(result, requested_fy: str, rates) -> None:
    """Record whether the rates used are the rates for the year that was ASKED.

    `rates_for()` FALLS BACK: a year the registry does not hold silently returns
    `LATEST_VERIFIED_FY`'s figures, still flagged `verified=True` — because that
    flag describes the entry it came from, not the request. Copying it straight
    onto the result made the response assert that a Finance Act had been checked
    for a year nobody had entered.

    So `rates_verified` now means what a reader assumes it means: the rates are
    the verified rates FOR `requested_fy`. A substituted year is false, and says
    so in `warnings` with both years named, because "your 2024-25 computation was
    run at 2025-26 rates" is the sentence a CA needs — a bare false flag is not.

    This is not a refusal. The fallback is deliberate (CLAUDE.md, "the trap that
    makes this list necessary") and several callers depend on getting a number.
    What was wrong was claiming it had been checked.
    """
    requested = (requested_fy or "").strip()
    result.fy = rates.fy
    if requested and requested != rates.fy:
        result.rates_verified = False
        result.warnings.append(
            f"No rates are held for FY {requested}; this was computed at "
            f"FY {rates.fy} rates. Slabs, surcharge, rebate and the entity and "
            f"minimum-tax rates all move by Finance Act, so treat every figure "
            f"as indicative until FY {requested} is added to the registries.")
        return
    result.rates_verified = rates.verified


# ── Engine ────────────────────────────────────────────────────────────────────

class ITREngine:
    """
    Compute ITR tax liability from income and deduction inputs.
    IT Act 1961 — all computation in integer paise.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """

    def compute(self, req: ITRComputeRequest) -> ITRComputeResult:
        # A firm, an LLP and a company are each taxed on a completely different
        # basis from an individual and from each other. Running them through the
        # slabs below charged nil to ₹4 lakh with a ₹60,000 §87A rebate on a
        # company that owes 22%/25%/30% from the first rupee.
        if req.assessee_kind in ("firm", "llp", "domestic_company"):
            return self._compute_entity(req)

        rates = rates_for(req.fy)
        result = ITRComputeResult()
        result.regime = "new" if req.use_new_regime else "old"
        _stamp_rate_provenance(result, req.fy, rates)

        # 1. Standard deduction on salary (IT Act Section 16(ia)). F17 fix:
        # this used to apply the NEW regime's ₹75,000 to both regimes — the
        # old regime's standard deduction has been ₹50,000 since Finance Act
        # 2019 and was never revised alongside the new-regime increases.
        std_ded_limit = (rates.new_regime_standard_deduction_paise if req.use_new_regime
                         else rates.old_regime_standard_deduction_paise)
        std_ded = min(std_ded_limit, req.gross_salary_paise)
        result.standard_deduction_paise = std_ded

        # 2. Gross Total Income
        # House property: capped at -2,00,000 if self-occupied (Section 71)
        # House property loss, and whether it may be set off at all.
        #
        # OLD regime: §71(3A) caps the set-off against other heads at
        # ₹2,00,000 for the year.
        # NEW regime: §115BAC(2) does not allow the set-off against any other
        # head AT ALL. A loss under this head simply gives no relief this year.
        #
        # The distinction is worth up to ₹2,00,000 of income, and the new
        # regime has been the DEFAULT since AY 2024-25 — so applying the old
        # regime's cap to a new-regime filer understated the tax on the return
        # most people now file.
        if req.house_property_income_paise < 0 and req.use_new_regime:
            house_property = 0
        else:
            house_property = max(req.house_property_income_paise,
                                 -LIMIT_SET_OFF_71_3A_PAISE)
        salary_after_std_ded = max(0, req.gross_salary_paise - std_ded)

        # Disallowed expenditure is added back to business income: the expense
        # was taken in the books but is not deductible, so taxable business
        # income is higher by that amount (§40A(3), §43B and the rest).
        #
        # A presumptive figure REPLACES both. §44AD(2), §44ADA(3) and §44AE(6)
        # deem every deduction under §30 to §38 to have been allowed in
        # computing the presumptive income, so there is nothing left to
        # disallow — adding back a §40A(3) cash payment to a presumptive
        # return would charge tax on an expense the section has already
        # accounted for, and would do it invisibly because both numbers look
        # reasonable on their own.
        if req.presumptive_income_paise is not None:
            business_income = max(0, req.presumptive_income_paise)
        else:
            business_income = req.business_income_paise + max(0, req.disallowances_paise)

        # Capital gains are computed separately (special rates).
        #
        # IT Act Section 71(3): where the net result under the head "Capital
        # gains" is a loss, the assessee is NOT entitled to set it off
        # against income under any other head — Section 74 carries it
        # forward for eight assessment years instead. Each head is therefore
        # floored at zero here, for gross total income and for the
        # special-rate tax alike. A negative figure used to flow straight
        # into both: a ₹5,00,000 short-term capital loss entered against a
        # ₹20,00,000 salary cut the year's tax from ₹1,92,400 to ₹88,400,
        # relief the section expressly denies, and it also produced NEGATIVE
        # tax on the capital-gains line, which reduced the tax on the salary
        # a second time.
        stcg = max(0, req.capital_gains_stcg_paise)
        ltcg = max(0, req.capital_gains_ltcg_paise)
        ltcg_other = max(0, req.capital_gains_ltcg_other_paise)
        # Brought-forward losses (IT-10), set off head by head. This happens
        # AFTER each capital head is floored at zero above: §71(3) denies a
        # current-year capital loss any relief against other income, and a
        # negative head reaching this point would let a brought-forward loss
        # appear to create one.
        #
        # house_property is passed through max(0, …) for the same reason and
        # for one more: where the head is already a LOSS this year, there is no
        # income under it for §71B to reach, and the brought-forward loss stays
        # carried forward rather than deepening a loss.
        if req.brought_forward_losses:
            set_off = apply_brought_forward_losses(
                losses=[l if isinstance(l, BroughtForwardLoss) else BroughtForwardLoss(**l)
                        for l in req.brought_forward_losses],
                business_income_paise=max(0, business_income),
                house_property_income_paise=max(0, house_property),
                stcg_paise=stcg, ltcg_paise=ltcg, ltcg_other_paise=ltcg_other,
                assessment_year=_assessment_year_for(req.fy),
            )
            # Only the POSITIVE part of each head is offered to the set-off, so
            # a head that was negative keeps its own figure.
            business_income = (set_off.business_income_paise if business_income > 0
                               else business_income)
            house_property = (set_off.house_property_income_paise if house_property > 0
                              else house_property)
            stcg, ltcg, ltcg_other = (set_off.stcg_paise, set_off.ltcg_paise,
                                      set_off.ltcg_other_paise)
            result.brought_forward_set_off_paise = set_off.total_set_off_paise
            result.brought_forward_set_off = [
                {
                    "loss_type": ln.loss_type, "section": ln.section,
                    "offered_paise": ln.offered_paise,
                    "set_off_paise": ln.set_off_paise,
                    "carried_forward_paise": ln.carried_forward_paise,
                    "against": list(ln.against), "reasons": list(ln.reasons),
                }
                for ln in set_off.lines
            ]
            result.warnings.extend(set_off.warnings)

        ordinary_income = (
            salary_after_std_ded
            + req.other_income_paise
            + house_property
            + business_income
        )
        gti = ordinary_income + stcg + ltcg + ltcg_other

        # 3. Chapter VI-A deductions (only for old regime for most)
        #
        # TWO ACCUMULATORS, NOT ONE, AND THE SPLIT IS THE POINT. §10(13A) HRA
        # is an EXEMPTION that never enters salary, and §24(b) interest is a
        # deduction in computing income under the head "house property"
        # (§22-27). Neither is in Chapter VI-A. Both used to be added to the
        # same running total as §80C and the rest, which left the arithmetic
        # right and two REPORTED figures wrong: gross total income was
        # overstated by their sum, and so was the total this engine labels
        # "Deductions under Chapter VI-A" — the figure itr_json.py writes into
        # SCHEDULE VI-A of the return (itr_json.py:337). An inflated
        # Schedule VI-A with no section behind it is what a §143(1)(a)
        # adjustment is for.
        #
        # `head_reliefs` reduces the income; `deductions` is Chapter VI-A. The
        # sum of the two is what taxable income is computed on, so no tax
        # figure moves — this splits a presentation, it does not change a
        # charge.
        deductions = 0
        head_reliefs = 0

        # 80CCD(2) — employer NPS, deductible under BOTH regimes (see the
        # LIMIT_80CCD2_* constants' docstring for the government/other cap
        # split and its verification status).
        cap_percent = (LIMIT_80CCD2_GOVT_PERCENT if req.is_government_employee
                       else LIMIT_80CCD2_OTHER_PERCENT)
        salary_base_80ccd2 = (req.salary_for_80ccd2_paise if req.salary_for_80ccd2_paise is not None
                              else req.gross_salary_paise)
        d80ccd2 = min(req.employer_nps_80ccd2_paise, salary_base_80ccd2 * cap_percent // 100)
        result.deduction_80ccd2_paise = d80ccd2
        deductions += d80ccd2

        # SAY SO WHEN THE UNVERIFIED CONSERVATIVE CHOICE ACTUALLY COSTS
        # SOMETHING. The 10% above is the pre-2024 figure and the LIMIT_80CCD2_*
        # docstring explains why it is still used in both regimes: the
        # Budget 2024 enhancement to 14% for a NON-government employee under
        # §115BAC(1A) could not be confirmed against the Act's text from this
        # environment (egress is refused at the proxy), and under-claiming is
        # the safe direction. Safe is not the same as invisible. Until now the
        # engine simply computed the smaller figure and said nothing, so a CA
        # who knows the 14% number saw a deduction they could not account for
        # and no reason for it.
        #
        # Raised only where it BITES — a non-government employee, on the new
        # regime, whose employer contribution exceeds 10% of salary. Anywhere
        # else the two percentages give the same answer and a warning would be
        # noise.
        if (req.use_new_regime and not req.is_government_employee
                and req.employer_nps_80ccd2_paise > salary_base_80ccd2 * cap_percent // 100):
            at_stake = (min(req.employer_nps_80ccd2_paise,
                            salary_base_80ccd2 * LIMIT_80CCD2_GOVT_PERCENT // 100)
                        - d80ccd2)
            if at_stake > 0:
                result.warnings.append(
                    f"§80CCD(2) is allowed here at {cap_percent}% of salary. The "
                    f"Finance (No. 2) Act 2024 is understood to have raised this "
                    f"to {LIMIT_80CCD2_GOVT_PERCENT}% for an employee taxed under "
                    f"§115BAC(1A), which would allow a further "
                    f"₹{indian_rupees(at_stake)} — but that amendment is not verified "
                    f"against the Act's own text from this deployment, so the "
                    f"lower figure is used. Check the current §80CCD(2) proviso "
                    f"before filing.")

        if not req.use_new_regime:
            # 80C
            s80c_total = req.s80c.total_paise()
            s80c_eligible = min(s80c_total, LIMIT_80C_PAISE)
            result.deduction_80c_paise = s80c_eligible
            deductions += s80c_eligible

            # 80CCD(1B) — additional NPS (both regimes allow employer NPS but not employee 80CCD)
            nps_eligible = min(req.nps_80ccd1b_paise, LIMIT_80CCD1B_PAISE)
            result.deduction_80ccd_paise = nps_eligible
            deductions += nps_eligible

            # 80D
            d80d = req.s80d.eligible_paise()
            result.deduction_80d_paise = d80d
            deductions += d80d

            # 80TTA / 80TTB
            if req.is_senior_citizen or req.is_very_senior_citizen:
                tta_ttb = min(req.savings_interest_80tta_paise, LIMIT_80TTB_PAISE)
            else:
                tta_ttb = min(req.savings_interest_80tta_paise, LIMIT_80TTA_PAISE)
            result.deduction_80tta_paise = tta_ttb
            deductions += tta_ttb

            # HRA exemption (Section 10(13A)). NOT Chapter VI-A: §10 exempts
            # the allowance from total income altogether, so it never enters
            # salary in the first place. It reduces the income — see
            # `head_reliefs` above.
            hra_exempt = req.hra.exemption_paise()
            result.deduction_hra_paise = hra_exempt
            head_reliefs += hra_exempt

            # Section 24(b) — home loan interest. NOT Chapter VI-A either:
            # §24 is inside the head "Income from house property" (§§22-27),
            # which is why the return puts it in Schedule HP and not in
            # Schedule VI-A.
            d24b = min(req.home_loan_interest_24b_paise, LIMIT_24B_PAISE)
            result.deduction_24b_paise = d24b
            head_reliefs += d24b

            # ANYTHING ELSE THE CA CLAIMS, WITH NO SECTION ATTACHED.
            #
            # This IS Chapter VI-A — it is the catch-all for the heads this
            # engine does not model — so it belongs in `deductions`. But
            # nothing here can check it, and that is worth saying out loud
            # rather than leaving as an uncapped addition: §80CCE caps §80C,
            # §80CCC and §80CCD(1) at ₹1,50,000 BETWEEN THEM, and §80E, §80DD,
            # §80DDB, §80U and §80GG each carry a limit of their own. An §80C
            # item routed through here escapes the §80CCE cap entirely, which
            # is the failure worth naming because `Deductions80C` has no field
            # for several §80C(2) clauses and a CA has nowhere else to put
            # them — except `s80c.other_paise`, which exists and IS inside the
            # cap.
            if req.other_deductions_paise > 0:
                deductions += req.other_deductions_paise
                result.warnings.append(
                    f"₹{indian_rupees(req.other_deductions_paise)} is claimed as "
                    f"'other deductions' with no section stated, so no ceiling "
                    f"could be applied to it. §80CCE caps §80C, §80CCC and "
                    f"§80CCD(1) at ₹1,50,000 between them, and §80E, §80DD, "
                    f"§80DDB, §80U and §80GG each carry their own limit. If any "
                    f"part of this is an §80C item, claim it under §80C instead "
                    f"— that total is inside the cap.")

            # 80G — computed LAST, because its own ceiling is a percentage
            # of what is left after every other deduction.
            #
            # IT Act Section 80G(4) caps the qualifying amount at 10% of
            # gross total income "as reduced by any portion thereof on which
            # income-tax is not payable under any provision of this Act and
            # by any amount in respect of which the assessee is entitled to
            # a deduction under any other provision of this Chapter" — what
            # is conventionally called adjusted gross total income. Read
            # with Section 112(2) and Section 111A(2), which require the
            # capital gains charged at those special rates to be taken out
            # of gross total income before any Chapter VI-A deduction is
            # computed at all, the base is:
            #
            #     gross total income
            #   − the long-term capital gains in it        (Section 112(2))
            #   − the short-term gains charged u/s 111A    (Section 111A(2))
            #   − every other Chapter VI-A deduction allowed  (Section 80G(4))
            #
            # `ordinary_income` is already gross total income less all three
            # capital-gains buckets, so the base is it less the deductions
            # accumulated above. HRA under Section 10(13A) and the interest
            # under Section 24(b) are in that running total although neither
            # is a Chapter VI-A deduction; both are exemptions/deductions
            # that reduce the head income and so are already outside gross
            # total income properly computed. Subtracting them here puts
            # them where they belong rather than double-counting them.
            #
            # NOT subtracted, and deliberately: income of a non-resident
            # chargeable under Sections 115A/115AB/115AC/115AD, and a share
            # of AOP/BOI profit on which no tax is payable under Section 86,
            # are excluded from the base by their own sections. This engine
            # models a resident assessee and has no input for either, and
            # inventing a figure nobody supplied would move the ceiling in
            # the direction that over-claims. If either is ever added as an
            # input it belongs in this subtraction.
            adjusted_gti = max(0, ordinary_income - head_reliefs - deductions)
            d80g, warnings_80g = compute_80g_deduction(req.donations_80g, adjusted_gti)
            result.deduction_80g_paise = d80g
            deductions += d80g
            result.warnings.extend(warnings_80g)

        # Gross total income is §14's figure: the heads AFTER each head's own
        # computation, and before Chapter VI-A. So the §10(13A) exemption and
        # the §24(b) interest come off it, and only Chapter VI-A is reported as
        # a deduction — which is what Schedule VI-A carries.
        result.gross_total_income_paise = gti - head_reliefs
        result.total_deductions_paise = deductions

        # 4. Taxable income
        # Capital gains are excluded from deductions (Section 112A/111A)
        # `head_reliefs + deductions` is what the single accumulator used to
        # hold, so this line computes exactly what it computed before.
        ordinary_taxable = max(0, ordinary_income - head_reliefs - deductions)
        taxable_income = ordinary_taxable + stcg + ltcg + ltcg_other
        result.taxable_income_paise = taxable_income

        # 5. Tax computation (ordinary/slab income only)
        slabs = self._slabs_for(rates, req.use_new_regime, req.is_senior_citizen, req.is_very_senior_citizen)
        tax = slab_tax_paise(ordinary_taxable, slabs)

        # Special rate capital gains (add on top of slab tax; never eligible
        # for Chapter VI-A deductions or §87A rebate/marginal relief below —
        # see the F17 fix note ahead of the rebate step). Rates are FY-versioned
        # in statutory_rates.py (R3.1) rather than inline here.
        # IT Act Section 112A: LTCG on equity, less the exemption. The
        # exemption is annual, applied once to the year's aggregate 112A
        # gain — see capital_gains_engine.compute_capital_gains, which is
        # per-transfer and says so. Taken BEFORE the basic-exemption
        # absorption below, and the order does not matter: absorbing first
        # and exempting second gives the same charged base, because both
        # steps floor at zero.
        ltcg_112a_taxable = max(0, ltcg - rates.ltcg_112a_exemption_paise)

        # THE BASIC EXEMPTION THE SLAB INCOME DID NOT USE ABSORBS INTO THESE
        # GAINS. IT Act proviso to §111A(1), proviso to §112(1)(a)(ii) and
        # second proviso to §112A(2) — three provisos in identical words:
        # where "the total income as reduced by such capital gains is below
        # the maximum amount which is not chargeable to income-tax", the
        # gains "shall be reduced by the amount by which the total income as
        # so reduced falls short of" it, and the tax is computed on the
        # balance.
        #
        # Omitting this was not a rounding difference. ₹5,00,000 of §111A
        # STCG and no other income was charged ₹1,04,000 — 20% on the whole
        # gain plus cess — where the Act charges ₹20,800, because the first
        # ₹4,00,000 is the exemption nothing else had used. It reached a
        # screen when 714c1c84 wired capital gains into the client
        # computation tab.
        charged = self._absorb_basic_exemption(
            req, rates, ordinary_taxable, result,
            [("§111A (STCG on equity)", stcg, rates.stcg_111a_rate_bps),
             ("§112A (LTCG on equity)", ltcg_112a_taxable, rates.ltcg_112a_rate_bps),
             ("§112 (LTCG on other assets)", ltcg_other, rates.ltcg_112_other_rate_bps)],
        )
        # IT Act Section 111A: STCG on equity
        stcg_tax = charged[0] * rates.stcg_111a_rate_bps // 10000
        ltcg_taxable = charged[1]
        ltcg_tax = ltcg_taxable * rates.ltcg_112a_rate_bps // 10000
        # IT Act Section 112: LTCG on any other asset
        ltcg_other_tax = charged[2] * rates.ltcg_112_other_rate_bps // 10000

        # THE WORKING, KEPT RATHER THAN DISCARDED. Every figure below already
        # existed as a local; nothing here recomputes anything, which is the
        # point — a second derivation for display is how the display and the
        # tax come to disagree. `gross - exempt - absorbed == charged` on every
        # row by construction, and a test asserts it.
        result.capital_gains_lines = [
            {"section": "§111A (STCG on equity)",
             "gross_paise": stcg, "exempt_paise": 0,
             "absorbed_paise": stcg - charged[0], "charged_paise": charged[0],
             "rate_percent": rates.stcg_111a_rate_bps / 100, "tax_paise": stcg_tax},
            {"section": "§112A (LTCG on equity)",
             "gross_paise": ltcg,
             "exempt_paise": min(ltcg, rates.ltcg_112a_exemption_paise),
             "absorbed_paise": ltcg_112a_taxable - charged[1],
             "charged_paise": charged[1],
             "rate_percent": rates.ltcg_112a_rate_bps / 100, "tax_paise": ltcg_tax},
            {"section": "§112 (LTCG on other assets)",
             "gross_paise": ltcg_other, "exempt_paise": 0,
             "absorbed_paise": ltcg_other - charged[2], "charged_paise": charged[2],
             "rate_percent": rates.ltcg_112_other_rate_bps / 100,
             "tax_paise": ltcg_other_tax},
        ]
        result.exempt_income_reported_paise = max(0, req.exempt_income_paise)

        # 6. Rebate u/s 87A — reduces slab tax only, never special-rate CG tax.
        # Pre-existing, deliberately conservative position: the CBDT's own ITR
        # utility has historically disallowed an 87A rebate claim against
        # 111A/112A income, a contested point across rulings — not revisited
        # here, since F17 only asked for correct MARGINAL RELIEF, not a
        # change to what the rebate applies against.
        # F17 fix: previously a cliff in BOTH regimes — now marginal relief
        # applies above the threshold, but only under the new regime, where
        # the 115BAC(1A) proviso grants it. The old regime's rebate is a
        # statutory hard cliff (crossing ₹5,00,000 by ₹1 forfeits the whole
        # ₹12,500) — encoded on the RebateRule as data, not a code branch.
        rebate_rule = rates.new_regime_rebate if req.use_new_regime else rates.old_regime_rebate
        rebate = tax - apply_rebate_87a(taxable_income, tax, rebate_rule)
        result.rebate_87a_paise = rebate
        ordinary_tax_after_rebate = max(0, tax - rebate)
        capital_gains_tax = stcg_tax + ltcg_tax + ltcg_other_tax  # Sections 111A + 112A + 112
        result.capital_gains_tax_paise = capital_gains_tax
        result.tax_before_cess_paise = ordinary_tax_after_rebate + capital_gains_tax

        # 7. Surcharge (IT Act Section 2(29C)). F17 fixes:
        #  (a) marginal relief on the slab-tax component, so crossing a
        #      surcharge threshold by a few rupees costs a few rupees, not a
        #      jump to the full new rate on the whole tax amount;
        #  (b) capital-gains surcharge capped at 15% even when the assessee's
        #      overall bracket is higher — Sections 111A/112A since Finance
        #      Act 2019, extended to Section 112 LTCG on ANY asset by Finance
        #      Act 2022. Computed SEPARATELY from ordinary income's
        #      surcharge, both using the SAME resolved bracket (driven by
        #      total taxable income).
        # Marginal relief applies only to the slab-tax component: the
        # discontinuity it exists to smooth is a slab phenomenon, and the
        # "tax at threshold income" baseline is well-defined only for tax
        # that scales with income. Every flat-rate CG component (111A, 112A,
        # 112) instead gets the flat capped bracket rate — one consistent
        # treatment for all special-rate tax.
        new_cap = rates.new_regime_surcharge_cap_percent if req.use_new_regime else None
        slab_tax_at = lambda income: slab_tax_paise(income, slabs)  # noqa: E731
        ordinary_surcharge = apply_surcharge_with_marginal_relief(
            taxable_income, ordinary_tax_after_rebate,
            rates.surcharge_brackets, new_cap, slab_tax_at,
        )
        cg_rate, _ = resolve_surcharge_bracket(
            taxable_income, rates.surcharge_brackets, rates.capital_gains_surcharge_cap_percent)
        cg_surcharge = capital_gains_tax * cg_rate // 100
        surcharge = ordinary_surcharge + cg_surcharge
        result.surcharge_paise = surcharge

        # 8. Health and Education Cess @ 4% on (tax + surcharge)
        result.cess_paise = cess_paise(result.tax_before_cess_paise + surcharge, rates)
        result.total_tax_paise = result.tax_before_cess_paise + surcharge + result.cess_paise

        # 9. Net payable / refund
        result.tds_and_advance_paise = req.tds_deducted_paise + req.advance_tax_paid_paise
        result.net_payable_paise = result.total_tax_paise - result.tds_and_advance_paise

        # 10. Warnings
        if req.use_new_regime and (req.s80c.total_paise() > 0 or req.nps_80ccd1b_paise > 0):
            result.warnings.append(
                "Section 80C/80CCD(1B) deductions are not available under the new regime "
                "(Section 80CCD(2), employer NPS, is — see the deductions breakdown)"
            )
        if req.use_new_regime and req.donations_80g:
            # Same silence as the 80C case above: donations were entered,
            # nothing was deducted, and nothing said why.
            total_donated = sum(d.amount_paise for d in req.donations_80g)
            result.warnings.append(
                f"₹{total_donated // 100:,} of Section 80G donations gives no deduction under "
                f"the new regime — Section 115BAC(2) allows no Chapter VI-A deduction except "
                f"Section 80CCD(2)/80CCH(2)/80JJAA."
            )
        if req.house_property_income_paise < 0:
            loss = -req.house_property_income_paise
            if req.use_new_regime:
                result.warnings.append(
                    f"House property loss of ₹{loss // 100:,} is NOT set off against "
                    f"other income under the new regime (Section 115BAC(2)). It gives "
                    f"no relief this year."
                )
            elif loss > LIMIT_SET_OFF_71_3A_PAISE:
                result.warnings.append(
                    f"House property loss capped at ₹2,00,000 (Section 71(3A)). Excess "
                    f"loss ₹{(loss - LIMIT_SET_OFF_71_3A_PAISE) // 100:,} carried forward."
                )
        if req.disallowances_paise > 0:
            result.warnings.append(
                f"₹{req.disallowances_paise // 100:,} of disallowed expenditure has "
                f"been added back to business income."
            )

        # A capital loss dropped silently is its own trap — the figure the
        # CA entered simply vanishes from the computation. Name each one,
        # the section that refuses it, and the amount that goes forward.
        capital_loss_heads = (
            ("Short-term capital loss", req.capital_gains_stcg_paise),
            ("Long-term capital loss on listed equity/equity MF (Section 112A)",
             req.capital_gains_ltcg_paise),
            ("Long-term capital loss on other assets (Section 112)",
             req.capital_gains_ltcg_other_paise),
        )
        any_loss = False
        for label, amount in capital_loss_heads:
            if amount < 0:
                any_loss = True
                result.warnings.append(
                    f"{label} of ₹{-amount // 100:,} is not set off against income under any "
                    f"other head (Section 71(3)). It is carried forward for eight assessment "
                    f"years (Section 74) — this computation does not maintain that carry-forward."
                )
        if any_loss and (stcg or ltcg or ltcg_other):
            # Section 70(2) lets a short-term loss be set off against ANY
            # capital gain and Section 70(3) lets a long-term loss be set
            # off against a long-term gain, both WITHIN the head. This
            # engine does not do it: the three buckets carry different
            # rates and a different exemption, so which gain a loss is set
            # against changes the tax, and the section does not choose.
            # Flooring each bucket independently can therefore tax a gain a
            # loss in another bucket should have absorbed — never the
            # reverse. The CA enters the net figure per head.
            result.warnings.append(
                "Sections 70(2)/70(3) allow a capital loss to be set off against capital gains "
                "of the right kind WITHIN the head. This computation does not apply that "
                "set-off — each head was taken at its own figure, floored at zero. Enter the "
                "already-net figure per head where an intra-head set-off applies."
            )

        return result

    # ── The entity charge (firm, LLP, domestic company) ───────────────────────

    #: Inputs that exist only for an individual. Supplied non-zero on an entity
    #: request they are REFUSED rather than ignored: a screen that sends an
    #: ₹80C figure and gets a tax back has been told the deduction was allowed.
    _INDIVIDUAL_ONLY = (
        ("gross_salary_paise", "Income under the head Salaries does not arise "
                               "for a {what}"),
        ("nps_80ccd1b_paise", "§80CCD(1B) is not available to a {what}"),
        ("employer_nps_80ccd2_paise", "§80CCD(2) is not available to a {what}"),
        ("savings_interest_80tta_paise", "§80TTA is not available to a {what}"),
        ("home_loan_interest_24b_paise", "§24(b) interest against salary does "
                                         "not arise for a {what}"),
    )

    def _compute_entity(self, req: ITRComputeRequest) -> ITRComputeResult:
        """A firm, an LLP or a domestic company.

        WHAT IS DIFFERENT FROM THE SLAB PATH, and every one of these is a
        number rather than a nicety:

          * a FLAT rate from the first rupee — no slabs and no exemption limit
            (30% for a firm or LLP; 22%/25%/30%/15% for a company by regime and
            by the turnover of a year TWO BACK);
          * no §16(ia) standard deduction — there is no salary;
          * no §87A rebate — §87A reaches "an individual, being a resident";
          * no §80C/§80D/§80TTA/§10(13A), which are individual reliefs;
          * a §115JB or §115JC MINIMUM, and the credit the excess creates.

        WHAT IS THE SAME: §80G, which §80G(1) gives to "any assessee"; the
        §80G(4) ceiling of 10% of adjusted gross total income; and §71(3A)'s
        ₹2,00,000 cap on setting a house-property loss against other heads,
        which binds every assessee (the NEW-REGIME denial does not — §115BAC
        reaches only an individual or HUF).

        CAPITAL GAINS ARE REFUSED, NOT CHARGED AT THE FLAT RATE. §111A (20%),
        §112A (12.5% over ₹1,25,000) and §112 (12.5%) charge "the assessee",
        any assessee, and they OVERRIDE the flat rate for those components. A
        company's listed-equity LTCG is 12.5%, not 25% or 30% — so folding it
        into total income here would over-tax by more than double, on the one
        figure a CA is least likely to re-derive. The split is not modelled for
        a non-individual and the refusal says so, in the house shape: refuse
        rather than produce a confident wrong number.
        """
        rates = rates_for(req.fy)
        result = ITRComputeResult()
        _stamp_rate_provenance(result, req.fy, rates)
        result.assessee_kind = req.assessee_kind
        # A COMPANY has a regime (§115BAA, §115BAB, or the normal rates). A
        # firm or LLP has none — there is one rate and no election — so this is
        # blank rather than "new" or "old", which are §115BAC's values and mean
        # nothing here.
        result.regime = req.company_regime if req.assessee_kind == "domestic_company" else ""

        word = self._entity_word(req.assessee_kind)
        for field_name, template in self._INDIVIDUAL_ONLY:
            if int(getattr(req, field_name, 0) or 0) != 0:
                result.validation_errors.append(
                    template.format(what=word)
                    + ". Remove it, or compute this client as an individual.")
        if req.s80c.total_paise() > 0:
            result.validation_errors.append(
                f"§80C is a deduction for an individual or HUF (§80C(1)) and is "
                f"not available to a {word}.")
        if req.s80d.self_family_premium_paise or req.s80d.parents_premium_paise:
            result.validation_errors.append(
                f"§80D is a deduction for an individual or HUF and is not "
                f"available to a {word}.")
        if req.hra.hra_received_paise or req.hra.rent_paid_paise:
            result.validation_errors.append(
                "§10(13A) house rent allowance is a salary exemption and does "
                "not arise here.")
        cg = (max(0, req.capital_gains_stcg_paise)
              + max(0, req.capital_gains_ltcg_paise)
              + max(0, req.capital_gains_ltcg_other_paise))
        if cg:
            result.validation_errors.append(
                "Capital gains are charged at their own rates under §111A, "
                "§112A and §112 — which override the flat rate a "
                f"{word} otherwise pays — and that split is not modelled for a "
                "non-individual assessee. "
                "Nothing is computed rather than charging them at the entity "
                "rate, which would more than double the tax on a listed-equity "
                "long-term gain.")
        if result.validation_errors:
            return result

        # ── Gross total income. No salary, no standard deduction. ──────────
        if req.presumptive_income_paise is not None:
            business_income = max(0, req.presumptive_income_paise)
        else:
            business_income = req.business_income_paise + max(0, req.disallowances_paise)
        # §71(3A) caps the set-off of a house-property loss against other heads
        # at ₹2,00,000 for EVERY assessee. §115BAC's outright denial is an
        # individual/HUF rule and deliberately does not run here.
        house_property = max(req.house_property_income_paise, -LIMIT_SET_OFF_71_3A_PAISE)
        gti = req.other_income_paise + house_property + business_income
        result.gross_total_income_paise = gti

        # ── Deductions: §80G and whatever Chapter VI-A Part C the CA entered ──
        deductions = max(0, req.other_deductions_paise)
        if req.donations_80g:
            adjusted_gti = max(0, gti - deductions)
            d80g, warnings_80g = compute_80g_deduction(req.donations_80g, adjusted_gti)
            result.deduction_80g_paise = d80g
            deductions += d80g
            result.warnings.extend(warnings_80g)
        result.total_deductions_paise = deductions

        total_income = max(0, gti - deductions)
        result.taxable_income_paise = total_income

        # ── The charge ─────────────────────────────────────────────────────
        entity = compute_entity_tax(
            total_income_paise=total_income,
            entity=req.assessee_kind,          # type: ignore[arg-type]
            fy=rates.fy,
            company_regime=req.company_regime,  # type: ignore[arg-type]
            turnover_in_reference_year_paise=req.turnover_in_reference_year_paise,
        )
        result.entity_rate_percent = entity.rate_percent
        result.turnover_reference_fy = entity.turnover_reference_fy
        result.entity_workings = list(entity.workings)
        result.tax_before_cess_paise = entity.tax_before_surcharge_paise
        result.surcharge_paise = entity.surcharge_paise
        result.cess_paise = entity.cess_paise
        result.total_tax_paise = entity.total_tax_paise

        # ── The minimum, and the credit it creates ─────────────────────────
        if req.assessee_kind == "domestic_company":
            if req.book_profit_paise is None:
                result.warnings.append(
                    "§115JB was not tested: book profit under Explanation 1 to "
                    "§115JB(2) has not been supplied. It is the profit in the "
                    "Companies Act accounts as adjusted, not taxable income, so "
                    "it cannot be derived from the figures above — and a company "
                    "with large book profits and small taxable income is exactly "
                    "what the section was written to catch.")
                minimum = None
            else:
                minimum = compute_mat(
                    book_profit_paise=req.book_profit_paise,
                    company_regime=req.company_regime,  # type: ignore[arg-type]
                    fy=rates.fy,
                )
        else:
            minimum = compute_amt(
                adjusted_total_income_paise=(
                    req.book_profit_paise
                    if req.book_profit_paise is not None else total_income),
                assessee=req.assessee_kind,  # type: ignore[arg-type]
                claimed_specified_deduction=req.claimed_specified_deduction,
                fy=rates.fy,
                # IT-21. §115BAC disapplies Chapter XII-BA for the assessees it
                # reaches, and this request has always known which regime is in
                # force. A firm or LLP — the only assessee that reaches this
                # branch today — is outside §115BAC, so the value changes
                # nothing for them; it is passed so that the day an individual
                # or HUF does reach it, the answer is right rather than
                # silently charging a tax the section waives.
                regime="new" if req.use_new_regime else "old",
            )

        if minimum is not None:
            result.minimum_tax_section = minimum.section
            result.minimum_tax_applies = minimum.applies
            result.minimum_tax_paise = minimum.minimum_tax_paise
            outcome = apply_minimum_tax(
                regular_tax_paise=entity.total_tax_paise,
                minimum=minimum,
                assessment_year_end=req.assessment_year_end,
                fy=rates.fy,
            )
            result.minimum_tax_applied = outcome.minimum_tax_applied
            result.minimum_tax_credit_paise = outcome.credit_generated_paise
            result.minimum_tax_credit_expires_after_ay = outcome.credit_expires_after_ay
            result.minimum_tax_reasons = list(outcome.reasons)
            result.total_tax_paise = outcome.tax_payable_paise
            if outcome.minimum_tax_applied:
                # The charge is the minimum, not the ordinary computation. The
                # component fields describe the MINIMUM so that the three add
                # up to the total the CA is asked to pay.
                result.tax_before_cess_paise = minimum.minimum_tax_before_surcharge_paise
                result.surcharge_paise = minimum.surcharge_paise
                result.cess_paise = minimum.cess_paise

        # ── Paid, and left to pay ──────────────────────────────────────────
        result.tds_and_advance_paise = req.tds_deducted_paise + req.advance_tax_paid_paise
        result.net_payable_paise = result.total_tax_paise - result.tds_and_advance_paise
        return result

    @staticmethod
    def _entity_word(kind: str) -> str:
        return {"firm": "partnership firm", "llp": "limited liability partnership",
                "domestic_company": "company"}.get(kind, kind)

    # ── Slab selection ────────────────────────────────────────────────────────

    @staticmethod
    def _basic_exemption_paise(slabs) -> int:
        """The "maximum amount which is not chargeable to income-tax".

        Read off the SLABS rather than stated as a constant, because that is
        what the phrase means and it is the only reading that stays right by
        itself: it moves with the regime (₹4,00,000 under §115BAC(1A) against
        ₹2,50,000 under the old one), with age under the old regime
        (₹3,00,000 at 60, ₹5,00,000 at 80), and with every Finance Act that
        widens the nil band. A constant here would be a second copy of a
        number statutory_rates.py already holds, and would go stale in April
        without anything failing.

        Walks the leading nil-rate brackets rather than taking the first,
        so a future table that splits the nil band in two is still read
        whole.
        """
        limit = 0
        for bracket in slabs:
            if bracket.rate_percent != 0:
                break
            if bracket.upto_paise is None:      # a wholly nil table
                return limit
            limit = bracket.upto_paise
        return limit

    def _absorb_basic_exemption(self, req: ITRComputeRequest, rates: FYTaxRates,
                                ordinary_taxable: int, result: ITRComputeResult,
                                buckets: list) -> list[int]:
        """Set the unused basic exemption against the special-rate gains.

        `buckets` is [(label, base_paise, rate_bps), ...]; returns the charged
        base for each, in the SAME order, so the caller keeps its own names for
        them.

        APPLIED ONCE, NOT THREE TIMES. Each of the three provisos reads "the
        total income as reduced by SUCH capital gains", so taking all three at
        face value in isolation would set the same exemption against each
        bucket and relieve up to three times what the Act gives. The exemption
        is one amount; ordinary income has first call on it (it is the income
        the slabs are charged on) and what survives is what the gains may
        absorb. That is also how the department's own utility computes it.

        WHO IT REACHES. All three provisos say "in the case of an individual
        or a Hindu undivided family, being a RESIDENT". A firm, an LLP and a
        company never arrive here — they take the entity-rate path long before
        this — so the test that remains is `assessee_kind == "individual"` and
        `is_resident`. A non-resident individual with Indian capital gains is
        charged on the whole gain, which is what the provisos' own words do.

        ALLOCATED HIGHEST RATE FIRST. The statute fixes no order between the
        three, so the allocation is the assessee's to choose and the engine
        takes the one most beneficial to them. Ordered by the RESOLVED rate
        rather than by section number: §111A is 20% and §112/§112A are 12.5%
        today, but that is a Finance Act's arrangement and not a fact about
        the sections — reading the rate keeps this right if a later Act
        reverses them. Ties keep the caller's order, which is stable.
        """
        charged = [max(0, int(base)) for _, base, _ in buckets]
        if not any(charged):
            return charged
        if req.assessee_kind != "individual" or not req.is_resident:
            return charged

        slabs = self._slabs_for(rates, req.use_new_regime,
                                req.is_senior_citizen, req.is_very_senior_citizen)
        # "the total income as reduced by such capital gains" — the slab
        # income, which is total income less every special-rate bucket.
        unused = self._basic_exemption_paise(slabs) - max(0, ordinary_taxable)
        if unused <= 0:
            return charged

        order = sorted(range(len(buckets)), key=lambda i: (-buckets[i][2], i))
        for i in order:
            if unused <= 0:
                break
            take = min(unused, charged[i])
            if take <= 0:
                continue
            charged[i] -= take
            unused -= take
            result.basic_exemption_absorbed_paise += take
            result.basic_exemption_absorption.append(
                f"{buckets[i][0]}: ₹{indian_rupees(take)} of the unused basic exemption "
                f"set against this gain, and tax charged on the balance.")
        return charged

    @staticmethod
    def _slabs_for(rates: FYTaxRates, use_new_regime: bool, senior: bool, very_senior: bool):
        """Which of the FY's slab tables applies. Old regime distinguishes
        senior (60-79, wider nil band) and very-senior (80+, wider still)
        citizens; the new regime does not (Finance Act 2023 onwards)."""
        if use_new_regime:
            return rates.new_regime_slabs
        if very_senior:
            return rates.old_regime_slabs_very_senior
        if senior:
            return rates.old_regime_slabs_senior
        return rates.old_regime_slabs_general


itr_engine = ITREngine()
