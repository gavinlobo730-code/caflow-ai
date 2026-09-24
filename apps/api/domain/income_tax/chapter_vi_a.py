"""Chapter VI-A — the deductions a CA claims BY SECTION, each with its own limit.

⚠️ EVERY FIGURE, WINDOW AND CONDITION HERE IS `[S]`-GRADED. Direct egress is
refused at this environment's proxy, so none of it was read off the Act or a
Finance Act; each constant is pinned EXACTLY by
`tests/test_a_chapter_vi_a_deduction_has_its_own_section.py`, so a later
correction is a deliberate edit with a failing test in front of it. `VERIFIED`
is False and every answer carries that.

WHAT WAS WRONG (IT-32)

    `itr_engine` modelled §80C, §80CCD(1B), §80D, §80TTA/§80TTB and §80G, and
    sent EVERYTHING ELSE through `other_deductions_paise` — one unlabelled
    figure, added with no ceiling and no section attribution. So an old-regime
    individual with an education loan, a disabled dependant, a specified
    illness, a disability, or rent and no HRA had the deductions MOST LIKELY TO
    BE QUESTIONED lumped into a single number with no audit trail and no cap
    check. The engine warned that no ceiling had been applied, which made the
    gap visible and did not close it.

THE THREE SHAPES, AND CONFUSING THEM IS THE COMMON ERROR

  * A FLAT DEDUCTION. §80DD and §80U give a FIXED amount — ₹75,000, or
    ₹1,25,000 for severe disability — and it does NOT depend on what was
    actually spent. A CA who spent ₹20,000 on a dependant with a 40% disability
    deducts ₹75,000; one who spent ₹3,00,000 deducts the same ₹75,000. Treating
    either as a reimbursement is the commonest mistake with them, in both
    directions.
  * A CAPPED EXPENDITURE. §80DDB, §80EE and §80EEA allow what was spent, up to
    a ceiling, and §80DDB is reduced by anything an insurer or employer paid.
  * AN UNCAPPED EXPENDITURE. §80E allows the WHOLE interest on an education
    loan with no monetary limit at all — but only for EIGHT assessment years,
    and only the interest.

  §80GG is a fourth shape of its own: the LEAST OF THREE, one of which is a
  percentage of a figure that depends on every other deduction, so it is
  computed like §80G — last, on what is left.

WHAT IS REFUSED RATHER THAN HALF-MODELLED

  * **§80JJAA is not computed.** 30% of additional employee cost for three
    assessment years is the easy half; the section turns on facts no ledger
    here holds — whether each new employee worked 240 days (150 for the
    notified businesses), whether their total emoluments stayed under ₹25,000 a
    month, whether they are enrolled in a recognised provident fund, and
    whether the whole of their emoluments was paid other than by an account
    payee cheque or bank transfer. It also requires a §44AB audit and a Form
    10DA report from an accountant. A figure computed without those is a
    disallowance waiting to happen on a deduction claimed for three years.
  * **The CERTIFICATES are named, never assumed.** Form 10-IA for §80DD and
    §80U, Form 10BA for §80GG, a specialist's prescription for §80DDB. Nothing
    in these books records one, so each answer says which document the claim
    rests on.
  * **Nothing here decides the REGIME.** §115BAC(2) disallows every section in
    this module, and `itr_engine` already computes Chapter VI-A only on the old
    regime. Re-testing it here would be a second answer to one question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from domain.money_text import rupees_paise, whole_rupees

#: No year in this module has been confirmed against a Finance Act from here.
VERIFIED = False

UNVERIFIED_NOTE = (
    "Every limit in this working is recorded from knowledge, not read off the "
    "Act — this environment refuses outbound requests, incometax.gov.in "
    "included. Each is pinned exactly by a test. Check the figures against the "
    "Finance Act before filing."
)

# ── §80E — interest on a loan for higher education ────────────────────────────
#: NO monetary limit. The whole interest is allowed; only the PERIOD is capped.
SECTION_80E_ASSESSMENT_YEARS = 8

# ── §80EE / §80EEA — additional interest on a housing loan ───────────────────
#: Both are CLOSED WINDOWS keyed on the SANCTION date, so which one a loan
#: qualifies under is fixed for the life of the loan — the fork shape the TDS
#: vocabulary and the capital-gains cutoff already take.
SECTION_80EE_LIMIT_PAISE = 50_000_00
SECTION_80EE_SANCTION_FROM = date(2016, 4, 1)
SECTION_80EE_SANCTION_TO = date(2017, 3, 31)

SECTION_80EEA_LIMIT_PAISE = 1_50_000_00
SECTION_80EEA_SANCTION_FROM = date(2019, 4, 1)
SECTION_80EEA_SANCTION_TO = date(2022, 3, 31)

# ── §80DD / §80U — disability, and these are FLAT ────────────────────────────
DISABILITY_LIMIT_PAISE = 75_000_00
SEVERE_DISABILITY_LIMIT_PAISE = 1_25_000_00

# ── §80DDB — treatment of a specified disease ────────────────────────────────
SECTION_80DDB_LIMIT_PAISE = 40_000_00
SECTION_80DDB_SENIOR_LIMIT_PAISE = 1_00_000_00

# ── §80GG — rent paid where no HRA is received ───────────────────────────────
SECTION_80GG_MONTHLY_PAISE = 5_000_00
SECTION_80GG_ANNUAL_PAISE = SECTION_80GG_MONTHLY_PAISE * 12
SECTION_80GG_INCOME_PCT = 25
SECTION_80GG_RENT_OVER_PCT = 10

FORM_10IA = (
    "Rests on a Form 10-IA certificate of disability from a prescribed medical "
    "authority. Nothing in these books records one — hold it on the file."
)
FORM_10BA = (
    "Rests on a Form 10BA declaration. §80GG is also unavailable where the "
    "assessee, their spouse, their minor child or their HUF owns a residence at "
    "the place where they ordinarily reside or work — a fact no ledger holds."
)
SPECIALIST_PRESCRIPTION = (
    "Rests on a prescription from a specialist, and is REDUCED by anything an "
    "insurer or an employer reimbursed."
)
SECTION_80JJAA_NOT_COMPUTED = (
    "§80JJAA is not computed. Its 30% of additional employee cost over three "
    "assessment years turns on facts these books do not hold — whether each new "
    "employee worked 240 days in the year (150 for the notified businesses), "
    "whether their emoluments stayed under ₹25,000 a month, whether they are in "
    "a recognised provident fund, and whether any part of their emoluments was "
    "paid otherwise than by account payee cheque or bank transfer — and it "
    "requires a §44AB audit with a Form 10DA report. Claim it from the audit "
    "working, not from here."
)


@dataclass(frozen=True)
class DeductionLine:
    """One section's answer, with what it was claimed on and what limited it."""
    section: str
    label: str
    claimed_paise: int
    allowed_paise: int
    #: The sentence naming the ceiling that bit, or why nothing did.
    basis: str
    #: What the claim rests on that nothing here can see.
    caveats: tuple = ()

    @property
    def restricted_paise(self) -> int:
        return max(self.claimed_paise - self.allowed_paise, 0)

    def to_dict(self) -> dict:
        return {
            "section": self.section, "label": self.label,
            "claimed_paise": self.claimed_paise,
            "allowed_paise": self.allowed_paise,
            "restricted_paise": self.restricted_paise,
            "basis": self.basis, "caveats": list(self.caveats),
        }


@dataclass(frozen=True)
class ChapterVIAClaims:
    """What the CA says was spent. Every figure is the CA's; none is derived.

    `disability_is_severe` is a BOOL and not a percentage, because the Act's own
    test is a certified band (40% and 80%) rather than a number a form should
    invite somebody to type: a typed 79 and a typed 80 differ by ₹50,000 of
    deduction and the certificate is what decides it.
    """
    # §80E — the WHOLE interest, for eight assessment years.
    education_loan_interest_paise: int = 0
    #: Which of the eight this is. None means nobody said — allowed, and named.
    education_loan_year: Optional[int] = None

    # §80EE / §80EEA — additional housing-loan interest, by SANCTION date.
    housing_loan_extra_interest_paise: int = 0
    housing_loan_sanctioned_on: Optional[date] = None

    # §80DD — a dependant with a disability. FLAT.
    has_disabled_dependant: bool = False
    dependant_disability_is_severe: bool = False

    # §80U — the assessee's own disability. FLAT.
    assessee_is_disabled: bool = False
    assessee_disability_is_severe: bool = False

    # §80DDB — treatment of a specified disease.
    specified_disease_spend_paise: int = 0
    specified_disease_reimbursed_paise: int = 0
    #: The PATIENT's age band decides the ceiling, not the assessee's.
    patient_is_senior: bool = False

    # §80GG — rent paid with no HRA.
    rent_paid_paise: int = 0
    receives_hra: bool = False


@dataclass
class ChapterVIAResult:
    lines: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    @property
    def total_allowed_paise(self) -> int:
        return sum(l.allowed_paise for l in self.lines)

    def to_dict(self) -> dict:
        return {
            "lines": [l.to_dict() for l in self.lines],
            "total_allowed_paise": self.total_allowed_paise,
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            "verified": VERIFIED,
        }


def disability_limit_paise(is_severe: bool) -> int:
    """§80DD and §80U share one ladder, so they share one function.

    FLAT, not a reimbursement: the section allows the amount whatever was
    actually spent. Two sections reading one table is why this is not written
    twice.
    """
    return SEVERE_DISABILITY_LIMIT_PAISE if is_severe else DISABILITY_LIMIT_PAISE


def housing_loan_section(sanctioned_on: Optional[date]) -> Optional[str]:
    """§80EE, §80EEA, or neither — decided by the SANCTION date alone.

    Both windows are shut. A loan sanctioned inside one keeps that section for
    its whole life, so this is a fork and not a migration: a 2020 loan is still
    §80EEA today, and a 2023 loan qualifies for neither however affordable the
    house was. None where no date was given, because the two limits differ by
    ₹1,00,000 and there is no safe default between them.
    """
    if sanctioned_on is None:
        return None
    if SECTION_80EE_SANCTION_FROM <= sanctioned_on <= SECTION_80EE_SANCTION_TO:
        return "80EE"
    if SECTION_80EEA_SANCTION_FROM <= sanctioned_on <= SECTION_80EEA_SANCTION_TO:
        return "80EEA"
    return None


def section_80gg_paise(rent_paid_paise: int, total_income_paise: int) -> tuple:
    """§80GG — the LEAST of three, and the answer says which one bit.

    (i)   ₹5,000 a month;
    (ii)  25% of total income;
    (iii) rent paid less 10% of total income.

    Limb (iii) goes NEGATIVE where the rent is under a tenth of income, and the
    section then allows nothing — clamped at zero rather than subtracted from
    the others. `total_income_paise` is gross total income reduced by every
    other Chapter VI-A deduction, which is why this is computed last, exactly as
    §80G is and for the same reason.
    """
    if rent_paid_paise <= 0:
        return 0, "No rent was claimed."
    cap_monthly = SECTION_80GG_ANNUAL_PAISE
    cap_income = total_income_paise * SECTION_80GG_INCOME_PCT // 100
    over_tenth = rent_paid_paise - (
        total_income_paise * SECTION_80GG_RENT_OVER_PCT // 100)
    over_tenth = max(over_tenth, 0)

    allowed = min(cap_monthly, cap_income, over_tenth)
    if allowed == over_tenth:
        which = (f"rent paid less 10% of total income "
                 f"(₹{rupees_paise(over_tenth)})")
    elif allowed == cap_income:
        which = f"25% of total income (₹{rupees_paise(cap_income)})"
    else:
        which = "₹5,000 a month"
    return allowed, f"§80GG allows the least of three; the least here is {which}."


def compute(claims: ChapterVIAClaims) -> ChapterVIAResult:
    """Every section except §80GG, which needs a figure this cannot see.

    §80GG is added by `add_section_80gg` once the caller knows total income
    after the rest of Chapter VI-A — the same two-step §80G already takes.
    """
    out = ChapterVIAResult()
    out.caveats.append(UNVERIFIED_NOTE)
    out.caveats.append(SECTION_80JJAA_NOT_COMPUTED)

    # ── §80E ────────────────────────────────────────────────────────────────
    if claims.education_loan_interest_paise > 0:
        amount = claims.education_loan_interest_paise
        basis = ("§80E allows the WHOLE interest with no monetary limit — only "
                 f"the PERIOD is capped, at {SECTION_80E_ASSESSMENT_YEARS} "
                 "assessment years from the year repayment began, or until the "
                 "interest is paid off, whichever is earlier.")
        caveats = ["Only INTEREST qualifies; a repayment of principal does not.",
                   "The loan must be from a financial institution or an approved "
                   "charitable institution, for the higher education of the "
                   "assessee, their spouse or children, or a student for whom "
                   "they are legal guardian."]
        year = claims.education_loan_year
        if year is None:
            out.gaps.append(
                f"§80E: nobody said which of the "
                f"{SECTION_80E_ASSESSMENT_YEARS} assessment years this is. The "
                f"deduction is allowed here, but it runs out and nothing in "
                f"these books counts the years.")
        elif year > SECTION_80E_ASSESSMENT_YEARS:
            amount = 0
            basis = (f"§80E is exhausted: this is year {year} and the section "
                     f"runs for {SECTION_80E_ASSESSMENT_YEARS} assessment years.")
        out.lines.append(DeductionLine(
            section="80E", label="Interest on a loan for higher education",
            claimed_paise=claims.education_loan_interest_paise,
            allowed_paise=amount, basis=basis, caveats=tuple(caveats)))

    # ── §80EE / §80EEA ──────────────────────────────────────────────────────
    if claims.housing_loan_extra_interest_paise > 0:
        section = housing_loan_section(claims.housing_loan_sanctioned_on)
        if section is None:
            out.lines.append(DeductionLine(
                section="80EE/80EEA",
                label="Additional interest on a housing loan",
                claimed_paise=claims.housing_loan_extra_interest_paise,
                allowed_paise=0,
                basis=("Neither section reaches this loan. §80EE needs a "
                       "sanction between 01-04-2016 and 31-03-2017 and §80EEA "
                       "between 01-04-2019 and 31-03-2022; both windows are "
                       "shut, and a loan sanctioned outside them qualifies for "
                       "neither.")))
            if claims.housing_loan_sanctioned_on is None:
                out.gaps.append(
                    "§80EE/§80EEA: no sanction date was given, and the date is "
                    "the ONLY thing that decides which section applies. The "
                    "limits differ by ₹1,00,000, so nothing was allowed rather "
                    "than one of the two being assumed.")
        else:
            limit = (SECTION_80EE_LIMIT_PAISE if section == "80EE"
                     else SECTION_80EEA_LIMIT_PAISE)
            out.lines.append(DeductionLine(
                section=section,
                label="Additional interest on a housing loan",
                claimed_paise=claims.housing_loan_extra_interest_paise,
                allowed_paise=min(claims.housing_loan_extra_interest_paise, limit),
                basis=(f"§{section} caps the additional interest at "
                       f"₹{whole_rupees(limit)}. Decided by the SANCTION date, "
                       f"which fixes the section for the life of the loan."),
                caveats=("This is ON TOP of §24(b), and the same interest "
                         "cannot be claimed under both.",)))

    # ── §80DD ───────────────────────────────────────────────────────────────
    if claims.has_disabled_dependant:
        amount = disability_limit_paise(claims.dependant_disability_is_severe)
        out.lines.append(DeductionLine(
            section="80DD",
            label="Maintenance and medical treatment of a dependant with a disability",
            claimed_paise=amount, allowed_paise=amount,
            basis=("A FLAT deduction, not a reimbursement: §80DD allows "
                   f"₹{whole_rupees(amount)} whatever was actually spent."),
            caveats=(FORM_10IA,
                     "A dependant means a spouse, child, parent, brother or "
                     "sister who is wholly or mainly dependent on the assessee, "
                     "and who has not themselves claimed §80U.")))

    # ── §80U ────────────────────────────────────────────────────────────────
    if claims.assessee_is_disabled:
        amount = disability_limit_paise(claims.assessee_disability_is_severe)
        out.lines.append(DeductionLine(
            section="80U", label="The assessee's own disability",
            claimed_paise=amount, allowed_paise=amount,
            basis=("A FLAT deduction, not a reimbursement: §80U allows "
                   f"₹{whole_rupees(amount)} whatever was actually spent."),
            caveats=(FORM_10IA,)))

    # ── §80DDB ──────────────────────────────────────────────────────────────
    if claims.specified_disease_spend_paise > 0:
        limit = (SECTION_80DDB_SENIOR_LIMIT_PAISE if claims.patient_is_senior
                 else SECTION_80DDB_LIMIT_PAISE)
        # Reduced FIRST, capped SECOND. The other order caps the gross spend and
        # then subtracts the reimbursement from an already-limited figure, which
        # under-allows wherever the spend exceeded the ceiling.
        net = max(claims.specified_disease_spend_paise
                  - claims.specified_disease_reimbursed_paise, 0)
        out.lines.append(DeductionLine(
            section="80DDB", label="Treatment of a specified disease",
            claimed_paise=claims.specified_disease_spend_paise,
            allowed_paise=min(net, limit),
            basis=(f"Reduced by ₹{rupees_paise(claims.specified_disease_reimbursed_paise)} "
                   f"reimbursed, then capped at ₹{whole_rupees(limit)}"
                   + (" (the PATIENT is a senior citizen)."
                      if claims.patient_is_senior else ".")),
            caveats=(SPECIALIST_PRESCRIPTION,)))

    # ── §80GG's own precondition, checked here so the caller cannot forget ──
    if claims.rent_paid_paise > 0 and claims.receives_hra:
        out.gaps.append(
            "§80GG was not computed: it is only for an assessee who receives NO "
            "house rent allowance. Where HRA is received, §10(13A) is the relief "
            "and it is already computed on the salary head.")

    return out


def add_section_80gg(result: ChapterVIAResult, claims: ChapterVIAClaims,
                     total_income_paise: int) -> ChapterVIAResult:
    """§80GG, once the caller knows income after every other deduction."""
    if claims.rent_paid_paise <= 0 or claims.receives_hra:
        return result
    allowed, basis = section_80gg_paise(claims.rent_paid_paise,
                                        total_income_paise)
    result.lines.append(DeductionLine(
        section="80GG", label="Rent paid where no house rent allowance is received",
        claimed_paise=claims.rent_paid_paise, allowed_paise=allowed,
        basis=basis, caveats=(FORM_10BA,)))
    return result
