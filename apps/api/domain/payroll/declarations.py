"""
Employee income-tax declarations — the employer's side of §192.

WHAT THIS IS FOR

Until now every employee was withheld on the new regime with nothing but the
§16(ia) standard deduction, because there was nowhere for anyone to declare
anything. That is the right DEFAULT and the wrong ANSWER: it over-withholds
from an old-regime employee with a home loan all year, and it leaves Annexure
II reporting four blanks that a CA has to fill in by hand in May.

Three distinct statutory objects live here. Keeping them apart is the whole
point of the module, because conflating any two of them is how payroll systems
get §192 wrong.

  1. THE REGIME INTIMATION TO THE EMPLOYER — governs WITHHOLDING only.

     CBDT Circular 04/2023 of 05-04-2023: the employer "shall seek information
     from each of its employees ... regarding their intended tax regime and
     each such employee shall intimate the same". Absent an intimation the
     employer withholds under §115BAC(1A) — the new regime — because
     §115BAC(1A) is the default for individuals since AY 2024-25.

     The same circular is express that this intimation "would not amount to
     exercising option in terms of sub-section (6) of section 115BAC and the
     person shall be required to do so separately".

  2. THE §115BAC(6) ELECTION — governs the RETURN.

     Form 10-IEA where there is business or professional income, the return
     itself where there is not. Modelled already, and separately, in
     domain/income_tax/regime_election.py. An employee who tells payroll "old
     regime" and never files Form 10-IEA is withheld on the old regime and
     assessed on the new one. This module therefore records the intimation and
     says plainly that it is not the election — it never sets one from the
     other.

  3. THE FORM 12BB STATEMENT — the evidence for what is claimed.

     Rule 26C prescribes Form 12BB and lists exactly four claims that need it:
     HRA under §10(13A), leave travel under §10(5), interest on borrowed
     capital under §24(b), and Chapter VI-A deductions. Each carries its own
     particulars — the landlord's PAN once the rent passes ₹1,00,000 a year,
     the lender's PAN for the home loan — and those particulars are the part a
     payroll system can actually check.

DECLARED IS NOT VERIFIED

Real practice runs in two halves and this module models both. For most of the
year the employee has DECLARED an intention and produced nothing; from around
January the employer collects proofs and withholds on what was actually
substantiated. §192(1) makes the employer liable for a correct deduction, so a
declaration that never grew a proof must stop reducing tax before the year ends
— otherwise the shortfall lands on the employer in Q4 with no salary left to
recover it from.

So every figure exists twice, declared and verified, and `EffectiveBasis`
decides which one a given month is entitled to use. Nothing here silently
promotes a declaration to a proof.

WHAT THIS MODULE DELIBERATELY DOES NOT COMPUTE

The tax. Chapter VI-A caps, the regime gate on those deductions, the §10(13A)
exemption formula, the §24(b) cap and the new regime's bar on setting a house
property loss against salary are all already implemented — correctly, and with
their own tests — in domain/income_tax/itr_engine.py. This module builds that
engine's request and reads its answer. Two implementations of the 80C cap would
drift, and the drift would be invisible: both numbers look reasonable.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from domain.income_tax.itr_engine import (
    Deductions80C, Deductions80D, HRADetails, ITRComputeRequest, ITREngine,
)

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Rule 26C, second proviso to the HRA row of Form 12BB: the landlord's PAN is
# required where the aggregate RENT PAID in the year exceeds ₹1,00,000. The
# threshold is on rent, not on the exemption claimed.
LANDLORD_PAN_RENT_THRESHOLD_PAISE: int = 1_00_000 * 100

REGIME_NEW = "new"
REGIME_OLD = "old"
VALID_REGIMES = (REGIME_NEW, REGIME_OLD)

# Status of the declaration as a whole.
STATUS_DRAFT = "draft"          # employee is still editing; no effect on payroll
STATUS_SUBMITTED = "submitted"  # declared, no proofs yet
STATUS_VERIFIED = "verified"    # CA has been through the proofs
VALID_STATUSES = (STATUS_DRAFT, STATUS_SUBMITTED, STATUS_VERIFIED)

# Status of one Chapter VI-A line.
ITEM_DECLARED = "declared"
ITEM_VERIFIED = "verified"
ITEM_REJECTED = "rejected"
VALID_ITEM_STATUSES = (ITEM_DECLARED, ITEM_VERIFIED, ITEM_REJECTED)

# The Chapter VI-A / §80 heads this module accepts, mapped to the ITR engine
# field each one feeds. A section outside this set is refused rather than
# quietly bucketed into "other deductions" — a rejected line the employee can
# see beats a deduction granted under a section nobody checked.
SECTION_80C = "80C"
SECTION_80CCD1B = "80CCD(1B)"
SECTION_80CCD2 = "80CCD(2)"
SECTION_80D_SELF = "80D-self"
SECTION_80D_PARENTS = "80D-parents"
SECTION_80TTA = "80TTA"
VALID_SECTIONS = (
    SECTION_80C, SECTION_80CCD1B, SECTION_80CCD2,
    SECTION_80D_SELF, SECTION_80D_PARENTS, SECTION_80TTA,
)

# Sections that survive §115BAC(2) — i.e. that still reduce tax under the new
# regime. §80CCD(2) (employer's NPS contribution) is the one Chapter VI-A head
# an ordinary salaried employee keeps; §80CCH(2) (Agniveer) and §80JJAA also
# survive but neither is a salary-payroll declaration, so neither is offered.
SECTIONS_ALLOWED_UNDER_NEW_REGIME = frozenset({SECTION_80CCD2})


@dataclass
class DeclarationItem:
    """One Chapter VI-A line: what was claimed, and what was proved."""
    section: str
    label: str = ""
    amount_declared_paise: int = 0
    amount_verified_paise: int = 0
    status: str = ITEM_DECLARED
    proof_reference: str = ""

    def effective_paise(self, *, verified_only: bool) -> int:
        """The figure payroll is entitled to withhold against.

        A REJECTED line is worth nothing on either basis — the CA looked at the
        proof and it did not support the claim.
        """
        if self.status == ITEM_REJECTED:
            return 0
        if verified_only:
            return self.amount_verified_paise if self.status == ITEM_VERIFIED else 0
        return max(self.amount_declared_paise, self.amount_verified_paise)


@dataclass
class Declaration:
    """One employee's §192 declaration for one financial year."""
    employee_id: str
    fy: str
    regime: str = REGIME_NEW
    status: str = STATUS_DRAFT

    # Form 12BB, Rule 26C — HRA under §10(13A)
    rent_paid_declared_paise: int = 0
    rent_paid_verified_paise: int = 0
    landlord_name: str = ""
    landlord_address: str = ""
    landlord_pan: str = ""
    rent_is_metro: bool = False

    # Form 12BB — leave travel concession under §10(5)
    lta_declared_paise: int = 0
    lta_verified_paise: int = 0

    # Form 12BB — interest on borrowed capital under §24(b)
    home_loan_interest_declared_paise: int = 0
    home_loan_interest_verified_paise: int = 0
    lender_name: str = ""
    lender_pan: str = ""

    # §192(2B) — other income and any house property loss the employee reports
    other_income_declared_paise: int = 0
    house_property_loss_declared_paise: int = 0  # positive number = a loss

    # The employer's half of the §10(13A) formula, filled in by payroll from
    # the year's payslips rather than retyped by the employee. The exemption is
    # the least of three limbs — the HRA actually received, 50%/40% of salary,
    # and rent less 10% of salary — and two of the three are the employer's
    # own figures. Left at zero the exemption computes to zero, which is the
    # safe direction: no relief granted on a basis nobody supplied.
    hra_basic_plus_da_paise: int = 0
    hra_received_paise: int = 0

    items: list[DeclarationItem] = field(default_factory=list)

    # Set when the CA finished going through the proofs.
    proofs_verified: bool = False

    @property
    def uses_new_regime(self) -> bool:
        return self.regime != REGIME_OLD

    def rent_paid(self, *, verified_only: bool) -> int:
        if verified_only:
            return self.rent_paid_verified_paise if self.proofs_verified else 0
        return max(self.rent_paid_declared_paise, self.rent_paid_verified_paise)

    def home_loan_interest(self, *, verified_only: bool) -> int:
        if verified_only:
            return self.home_loan_interest_verified_paise if self.proofs_verified else 0
        return max(self.home_loan_interest_declared_paise,
                   self.home_loan_interest_verified_paise)

    def total_for(self, section: str, *, verified_only: bool) -> int:
        return sum(i.effective_paise(verified_only=verified_only)
                   for i in self.items if i.section == section)


def validate(decl: Declaration) -> list[str]:
    """Everything wrong with this declaration, in the employee's own terms.

    Returns problems, not warnings: each one is a reason the claim cannot be
    given effect as it stands.
    """
    problems: list[str] = []

    if decl.regime not in VALID_REGIMES:
        problems.append(
            f"Tax regime {decl.regime!r} is not one of {VALID_REGIMES}. Under "
            f"§115BAC(1A) the new regime is the default, so an unreadable "
            f"intimation is not the same as an old-regime one."
        )
    if decl.status not in VALID_STATUSES:
        problems.append(f"Status {decl.status!r} is not one of {VALID_STATUSES}.")

    for i in decl.items:
        if i.section not in VALID_SECTIONS:
            problems.append(
                f"Section {i.section!r} is not a head this payroll module can give "
                f"effect to (it accepts {', '.join(VALID_SECTIONS)}). Claim it in "
                f"the return instead of here — an unrecognised section granted as "
                f"a deduction is an under-deduction the employer answers for."
            )
        if i.status not in VALID_ITEM_STATUSES:
            problems.append(f"{i.section}: item status {i.status!r} is not valid.")
        if i.amount_declared_paise < 0 or i.amount_verified_paise < 0:
            problems.append(f"{i.section}: a negative amount cannot be declared.")
        if i.status == ITEM_VERIFIED and i.amount_verified_paise > i.amount_declared_paise:
            problems.append(
                f"{i.section}: ₹{i.amount_verified_paise / 100:,.2f} verified against "
                f"₹{i.amount_declared_paise / 100:,.2f} declared. A proof can support "
                f"less than was claimed, never more — raise the declaration first."
            )

    # Rule 26C: landlord's PAN once the year's rent passes ₹1,00,000.
    rent = max(decl.rent_paid_declared_paise, decl.rent_paid_verified_paise)
    if rent > LANDLORD_PAN_RENT_THRESHOLD_PAISE:
        pan = decl.landlord_pan.strip().upper()
        if not pan:
            problems.append(
                f"Rent of ₹{rent / 100:,.2f} exceeds ₹1,00,000, so Rule 26C requires "
                f"the landlord's PAN in Form 12BB before the §10(13A) exemption can "
                f"be allowed."
            )
        elif not PAN_RE.match(pan):
            problems.append(
                f"Landlord PAN {pan!r} is not a valid PAN (AAAAA9999A)."
            )
    if rent > 0 and not decl.landlord_name.strip():
        problems.append("Form 12BB needs the landlord's name against the rent claimed.")

    # Rule 26C: the lender's PAN is required for §24(b), with no threshold.
    interest = max(decl.home_loan_interest_declared_paise,
                   decl.home_loan_interest_verified_paise)
    if interest > 0:
        pan = decl.lender_pan.strip().upper()
        if not pan:
            problems.append(
                "Form 12BB requires the lender's PAN against interest claimed under "
                "§24(b). Unlike the landlord's, this one has no rent threshold — it "
                "is required whenever the claim is made."
            )
        elif not PAN_RE.match(pan):
            problems.append(f"Lender PAN {pan!r} is not a valid PAN (AAAAA9999A).")

    if decl.house_property_loss_declared_paise < 0:
        problems.append(
            "A house property loss is declared as a positive number. A negative "
            "figure here reads as income and would reduce tax the wrong way."
        )

    return problems


def notices(decl: Declaration) -> list[str]:
    """Things the CA must know that are not defects in the declaration.

    Kept apart from `validate` on purpose: these do not block payroll, and a
    system that blocks on them trains people to click past the ones that matter.
    """
    out: list[str] = []

    if decl.regime == REGIME_OLD:
        out.append(
            "This employee intimated the OLD regime for withholding. CBDT Circular "
            "04/2023 is express that the intimation to the employer is not the "
            "§115BAC(6) option — where they have business or professional income "
            "they must still file Form 10-IEA by the §139(1) due date, or the "
            "return is assessed on the new regime whatever it says."
        )

    if decl.uses_new_regime:
        disallowed = sorted({
            i.section for i in decl.items
            if i.section not in SECTIONS_ALLOWED_UNDER_NEW_REGIME
            and i.effective_paise(verified_only=False) > 0
        })
        if disallowed:
            out.append(
                f"Declared under {', '.join(disallowed)} but withheld on the new "
                f"regime, where §115BAC(2) allows none of them. They are recorded "
                f"and reduce nothing. Only §80CCD(2) survives for a salaried "
                f"employee."
            )
        if max(decl.rent_paid_declared_paise, decl.rent_paid_verified_paise) > 0:
            out.append(
                "Rent is declared but the new regime allows no §10(13A) exemption, "
                "so it reduces nothing."
            )
        if max(decl.lta_declared_paise, decl.lta_verified_paise) > 0:
            out.append(
                "Leave travel is declared but the new regime allows no §10(5) "
                "exemption, so it reduces nothing."
            )
        if decl.house_property_loss_declared_paise > 0:
            out.append(
                "A house property loss is declared but §115BAC(2)(i) bars setting it "
                "against salary under the new regime, so it reduces nothing."
            )

    if not decl.proofs_verified and decl.status == STATUS_SUBMITTED:
        out.append(
            "Proofs are not verified. §192(1) makes the employer answerable for a "
            "correct deduction, so these figures must be substantiated before the "
            "year's last payroll — an unproved declaration left in place becomes a "
            "Q4 shortfall with no salary left to recover it from."
        )

    return out


def _build_request(
    *,
    decl: Optional[Declaration],
    projected_annual_salary_paise: int,
    fy: Optional[str],
    verified_only: bool,
    employer_nps_paise: int = 0,
    salary_for_80ccd2_paise: Optional[int] = None,
    professional_tax_paise: int = 0,
    is_government_employee: bool = False,
) -> ITRComputeRequest:
    """Turn a declaration into an ITR engine request.

    THE ONE place declaration fields are mapped onto engine fields. Both the
    salary-only figure and the §192(2B) figure are built from here, so the two
    cannot disagree about what was claimed — a second copy of this mapping is
    exactly the drift this module exists to avoid.

    `decl` of None is not a special case: it is an employee on the default
    regime with nothing claimed, and it reproduces what payroll computed before
    declarations existed.
    """
    req = ITRComputeRequest(
        gross_salary_paise=max(0, projected_annual_salary_paise),
        fy=fy,
        use_new_regime=True if decl is None else decl.uses_new_regime,
        employer_nps_80ccd2_paise=max(0, employer_nps_paise),
        salary_for_80ccd2_paise=salary_for_80ccd2_paise,
        is_government_employee=is_government_employee,
    )
    if decl is None:
        return req

    # §16(iii) — professional tax actually deducted. The engine takes it as an
    # "other deduction", which it gates on the old regime, and that gate is the
    # point: §115BAC(2)(i) excludes section 16 apart from clause (ia), so PT
    # reduces nothing under the new regime.
    req.other_deductions_paise = max(0, professional_tax_paise)

    req.s80c = Deductions80C(
        other_paise=decl.total_for(SECTION_80C, verified_only=verified_only))
    req.nps_80ccd1b_paise = decl.total_for(SECTION_80CCD1B,
                                           verified_only=verified_only)
    req.s80d = Deductions80D(
        self_family_premium_paise=decl.total_for(SECTION_80D_SELF,
                                                 verified_only=verified_only),
        parents_premium_paise=decl.total_for(SECTION_80D_PARENTS,
                                             verified_only=verified_only),
    )
    # §80TTA(1) allows the deduction "in respect of any income by way of
    # interest on deposits in a savings account ... INCLUDED IN THE GROSS TOTAL
    # INCOME". So it is capped at the interest the employee actually reported
    # under §192(2B). Uncapped, an employee who claimed ₹10,000 of §80TTA and
    # reported no interest income got the relief on income never brought to
    # tax — a real under-deduction, and one that looks perfectly ordinary on
    # both the declaration and the payslip.
    req.savings_interest_80tta_paise = min(
        decl.total_for(SECTION_80TTA, verified_only=verified_only),
        max(0, decl.other_income_declared_paise),
    )
    # An employee may also route the employer's NPS contribution through a
    # declaration line; it adds to whatever payroll already knew.
    req.employer_nps_80ccd2_paise += decl.total_for(
        SECTION_80CCD2, verified_only=verified_only)

    req.hra = HRADetails(
        basic_salary_paise=decl.hra_basic_plus_da_paise,
        hra_received_paise=decl.hra_received_paise,
        rent_paid_paise=decl.rent_paid(verified_only=verified_only),
        is_metro=decl.rent_is_metro,
    )
    req.home_loan_interest_24b_paise = decl.home_loan_interest(
        verified_only=verified_only)
    return req


def annual_tax_paise(**kwargs) -> int:
    """Tax on a year's projected salary, given what the employee declared.

    Everything statutory is the ITR engine's: the regime gate on Chapter VI-A,
    the 80C/80D/80CCD caps, the §10(13A) formula, the §24(b) cap, §87A, the
    surcharge and its marginal relief, and the new regime's bar on a house
    property loss. This module only decides WHICH declared figures the engine
    is allowed to see.

    Excludes §192(2B) other income — see `withholding_tax_paise`.
    """
    return ITREngine().compute(_build_request(**kwargs)).total_tax_paise


def withholding_tax_paise(**kwargs) -> int:
    """Annual tax to withhold, after §192(2B).

    §192(2B) lets an employee report other income so the employer withholds on
    it too. Its proviso is the constraint: doing so "shall not ... have the
    effect of reducing the tax deductible except where the loss under the head
    'Income from house property' has been taken into account". Other income may
    only push the withholding UP; only a house property loss may pull it down.

    ON THE `max()` BELOW — it does not currently bind, and that is worth saying
    rather than implying otherwise. Tax is monotonic in income here (marginal
    relief caps how fast tax rises, it never reverses the rise), and this module
    does not credit tax deducted by anyone else, which is the case the proviso
    was really written against. The guard is a floor that holds the invariant
    if either of those changes — a third-party TDS credit, or a deduction keyed
    to other income — because the failure it prevents is an under-deduction the
    employer answers for under §192(1), and it would be invisible on the
    payslip. `tests/test_it_declarations.py` pins the monotonicity it rests on.
    """
    salary_only = annual_tax_paise(**kwargs)

    decl = kwargs.get("decl")
    if decl is None:
        return salary_only

    other = max(0, decl.other_income_declared_paise)
    hp_loss = max(0, decl.house_property_loss_declared_paise)
    if other == 0 and hp_loss == 0:
        return salary_only

    req = _build_request(**kwargs)
    req.other_income_paise = other
    req.house_property_income_paise = -hp_loss
    with_other = ITREngine().compute(req).total_tax_paise

    if hp_loss > 0:
        # The proviso's express exception: a house property loss MAY reduce the
        # withholding. Under the new regime the engine has already refused to
        # set it off (§115BAC(2)(i)), so this cannot cut the tax there.
        return with_other
    return max(salary_only, with_other)
