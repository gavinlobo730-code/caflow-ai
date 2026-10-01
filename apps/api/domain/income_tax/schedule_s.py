"""Schedule S — income chargeable under the head Salaries (TDS-INCOME-TAX-15).

WHAT WAS MISSING
    Gross salary was ONE typed figure. An HRA helper (`HRADetails`) existed and
    payroll has a perquisites module, but neither fed a Schedule S view:
    allowances, §17(2) perquisites including ESOP and RSU, §10 exemptions and a
    previous employer's salary were not itemised, so the return asks for the
    parts and the product held a total. A client with two employers in a year
    was the common case and the one it could not show.

    This module is the working, and the form's own shape: ONE BLOCK PER EMPLOYER
    — salary under §17(1), perquisites under §17(2), profits in lieu under
    §17(3), the exemptions under §10 — and the §16 deductions across them.

WHERE THE FIGURES COME FROM
    The CA keys them off each employer's Form 16 (Part B). That is the reason
    perquisites arrive as the TAXABLE VALUE the employer stated rather than as
    the Rule 3 valuation: `domain/payroll/perquisites.py` values what an
    EMPLOYER provides, for a client that runs payroll, and the client of a
    salaried return is the employee, whose Form 16 already carries the
    employer's valuation. The one perquisite that is computed here is the one
    an employee can check for themselves from the share price: ESOP and RSU,
    §17(2)(vi) — the fair market value on the date of exercise less what the
    employee paid.

THE RULES
    §15/§17(1)   Salary, wages, annuity, pension, gratuity, fees, commission,
                 advance, leave encashment — the employer's own line.
    §17(2)       Perquisites. ESOP and RSU: (FMV on exercise − exercise price)
                 × shares, never negative — a grant exercised below its price
                 gives no perquisite, it does not give a negative one.
    §17(3)       Profits in lieu of salary.
    §10          Exemptions. Each kind is listed with whether §115BAC(2) leaves
                 it standing, because the new regime withdraws most §10
                 allowances while leaving the retirement benefits. An exemption
                 the regime does not allow is reported and NOT deducted.
    §10(13A)     HRA, by `HRADetails.exemption_paise` (Rule 2A) — old regime
                 only, for the same reason.
    §16(ia)      The standard deduction, ONCE across every employer, and never
                 more than the salary it is taken from. The limit is the
                 regime's, read from `statutory_rates`.
    §16(iii)     Professional tax, old regime only (§115BAC(2) withdraws it).

WHAT FEEDS THE COMPUTATION, AND THE ONE SIMPLIFICATION IT CARRIES
    `engine_inputs` is what the computation's own boxes take. The engine has ONE
    salary box and takes the standard deduction off it itself, and HRA through
    its own fields, so the box is the gross LESS the other exemptions and the
    professional tax — and the standard deduction the engine then takes is the
    same figure this module takes. The reconciliation that holds, and is
    asserted: Schedule S's income chargeable under the head equals the engine's
    salary head LESS the HRA exemption, because the engine reports salary before
    HRA and takes HRA off gross total income separately. That is the engine's
    treatment and is left alone here; it is named so the two figures are not
    compared by eye.

NOT MODELLED, AND NAMED ON EVERY ANSWER (`NOT_MODELLED`)
    Deferment of tax on ESOP of an eligible start-up (§192(1C)); the §17(2)(vii)
    and (viia) tax on an employer's contributions above ₹7.5 lakh in aggregate
    (Form 16 states it, and the CA keys it as a perquisite); the §16(ii)
    entertainment allowance of a government employee; the cap on each §10
    exemption (gratuity, leave encashment, commuted pension and VRS each carry
    a limit this worksheet does not apply — the CA keys the EXEMPT amount);
    §89 relief for arrears; and foreign-employer salary.

⚠️ EVERY SECTION'S WORDING IS `[S]`-GRADED. Egress is refused here, so the Act
was not read: `VERIFIED` is False, and `tests/test_a_salary_worksheet_...` pins
each constant exactly.

All amounts are integer paise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.ist_clock import normalise_fy_label
from domain.income_tax.statutory_rates import rates_for
from domain.money_text import whole_rupees

VERIFIED = False

#: The perquisite kinds as Form 16 groups them. The value is the TAXABLE value
#: the employer stated.
PERQUISITE_KINDS: dict[str, str] = {
    "accommodation": "Rent-free or concessional accommodation",
    "motor_car": "Motor car",
    "concessional_loan": "Interest-free or concessional loan",
    "meals_gifts_other": "Meals, gifts, club and similar",
    "employer_contribution_above_limit":
        "Employer's contributions above ₹7.5 lakh — §17(2)(vii)/(viia)",
    "other": "Other perquisite",
}

#: §10 exemptions: key -> (label, still allowed under §115BAC(2)).
#: `[S]`-graded. The retirement benefits survive the new regime and the
#: allowances do not, with official-duty allowances the exception among the
#: allowances.
EXEMPTION_KINDS: dict[str, tuple[str, bool]] = {
    "gratuity_10_10": ("Gratuity — §10(10)", True),
    "leave_encashment_10_10aa": ("Leave encashment on retirement — §10(10AA)", True),
    "commuted_pension_10_10a": ("Commuted pension — §10(10A)", True),
    "vrs_10_10c": ("Voluntary retirement — §10(10C)", True),
    "official_duty_allowance_10_14_i":
        ("Allowance for expenses of official duty — §10(14)(i)", True),
    "lta_10_5": ("Leave travel concession — §10(5)", False),
    "education_hostel_10_14_ii":
        ("Children's education and hostel allowance — §10(14)(ii)", False),
    "other_10": ("Another §10 exemption (stated by the CA)", False),
}

NOT_MODELLED: tuple[str, ...] = (
    "Deferment of tax on the ESOP of an eligible start-up (§192(1C)) is not "
    "modelled: the perquisite is taxed in the year of exercise here.",
    "Each §10 exemption's own ceiling (gratuity, leave encashment, commuted "
    "pension, voluntary retirement) is not applied: key the EXEMPT amount.",
    "The §16(ii) entertainment allowance (government employees), §89 relief on "
    "arrears and salary from a foreign employer are not modelled.",
    "The engine reports salary before the HRA exemption and takes HRA off "
    "gross total income separately, so this schedule's income equals the "
    "engine's salary head less HRA — compare them that way.",
)


class WorksheetRefused(ValueError):
    """The schedule cannot be worked on what was entered; the message says
    which employer and what to change."""


@dataclass(frozen=True)
class EsopExercise:
    description: str
    shares: int
    fmv_per_share_paise: int
    exercise_price_per_share_paise: int


@dataclass(frozen=True)
class PerquisiteLine:
    kind: str
    amount_paise: int
    description: str = ""


@dataclass(frozen=True)
class ExemptionLine:
    kind: str
    amount_paise: int


@dataclass(frozen=True)
class Employer:
    key: str
    name: str
    tan: Optional[str] = None
    is_previous_employer: bool = False
    salary_17_1_paise: int = 0
    perquisites: tuple = ()
    esop_exercises: tuple = ()
    profits_in_lieu_17_3_paise: int = 0
    exemptions: tuple = ()
    professional_tax_paise: int = 0


@dataclass(frozen=True)
class Hra:
    """§10(13A), for the year as a whole — the sum over every employer's HRA
    and the basic salary it is measured against."""
    basic_salary_paise: int = 0
    hra_received_paise: int = 0
    rent_paid_paise: int = 0
    is_metro: bool = False


@dataclass
class EmployerResult:
    key: str
    name: str
    tan: Optional[str]
    is_previous_employer: bool
    salary_17_1_paise: int = 0
    perquisites_17_2_paise: int = 0
    esop_perquisite_paise: int = 0
    profits_in_lieu_17_3_paise: int = 0
    gross_salary_paise: int = 0
    exemptions_claimed_paise: int = 0
    exemptions_allowed_paise: int = 0
    professional_tax_allowed_paise: int = 0
    net_salary_paise: int = 0
    esop_lines: list = field(default_factory=list)
    workings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SalaryResult:
    fy: str
    use_new_regime: bool
    employers: list = field(default_factory=list)
    gross_salary_paise: int = 0
    exemptions_allowed_paise: int = 0
    hra_exemption_paise: int = 0
    professional_tax_paise: int = 0
    standard_deduction_paise: int = 0
    income_chargeable_paise: int = 0
    engine_inputs: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fy": self.fy, "use_new_regime": self.use_new_regime,
            "employers": [e.to_dict() for e in self.employers],
            "gross_salary_paise": self.gross_salary_paise,
            "exemptions_allowed_paise": self.exemptions_allowed_paise,
            "hra_exemption_paise": self.hra_exemption_paise,
            "professional_tax_paise": self.professional_tax_paise,
            "standard_deduction_paise": self.standard_deduction_paise,
            "income_chargeable_paise": self.income_chargeable_paise,
            "engine_inputs": dict(self.engine_inputs),
            "gaps": list(self.gaps), "caveats": list(self.caveats),
            "not_modelled": list(NOT_MODELLED),
            "verified": VERIFIED,
        }


def esop_perquisite_paise(e: EsopExercise) -> int:
    """§17(2)(vi): (fair market value on the date of exercise − the amount the
    employee paid) × the shares. NEVER negative: a grant exercised at or above
    its fair market value gives no perquisite, and a negative figure here would
    be a loss the section does not recognise, which would reduce salary a
    second time."""
    return e.shares * max(0, e.fmv_per_share_paise - e.exercise_price_per_share_paise)


def _validate(employers: list[Employer], hra: Hra) -> None:
    seen = set()
    for emp in employers:
        if emp.key in seen:
            raise WorksheetRefused(f"Two employers carry the key {emp.key!r}.")
        seen.add(emp.key)
        for label, value in (("salary under §17(1)", emp.salary_17_1_paise),
                             ("profits in lieu of salary", emp.profits_in_lieu_17_3_paise),
                             ("professional tax", emp.professional_tax_paise)):
            if value < 0:
                raise WorksheetRefused(f"{emp.name}: {label} cannot be negative.")
        for line in emp.perquisites:
            if line.kind not in PERQUISITE_KINDS:
                raise WorksheetRefused(
                    f"{emp.name}: perquisite kind {line.kind!r} is not one of "
                    f"{', '.join(PERQUISITE_KINDS)}.")
            if line.amount_paise < 0:
                raise WorksheetRefused(f"{emp.name}: a perquisite cannot be negative.")
        for line in emp.exemptions:
            if line.kind not in EXEMPTION_KINDS:
                raise WorksheetRefused(
                    f"{emp.name}: exemption kind {line.kind!r} is not one of "
                    f"{', '.join(EXEMPTION_KINDS)}.")
            if line.amount_paise < 0:
                raise WorksheetRefused(f"{emp.name}: an exemption cannot be negative.")
        for ex in emp.esop_exercises:
            if ex.shares < 0 or ex.fmv_per_share_paise < 0 or ex.exercise_price_per_share_paise < 0:
                raise WorksheetRefused(
                    f"{emp.name}: an ESOP exercise cannot carry a negative "
                    "quantity or price.")
    for label, value in (("basic salary", hra.basic_salary_paise),
                         ("HRA received", hra.hra_received_paise),
                         ("rent paid", hra.rent_paid_paise)):
        if value < 0:
            raise WorksheetRefused(f"{label} cannot be negative.")


def _hra_exemption(hra: Hra) -> int:
    """§10(13A) with Rule 2A — the same function the engine uses, so the two
    cannot disagree about it."""
    from domain.income_tax.itr_engine import HRADetails
    return HRADetails(
        basic_salary_paise=hra.basic_salary_paise,
        hra_received_paise=hra.hra_received_paise,
        rent_paid_paise=hra.rent_paid_paise,
        is_metro=hra.is_metro,
    ).exemption_paise()


def compute(employers: list[Employer], *, fy: str, use_new_regime: bool,
            hra: Optional[Hra] = None) -> SalaryResult:
    fy = normalise_fy_label(fy)
    hra = hra or Hra()
    _validate(employers, hra)
    rates = rates_for(fy)
    out = SalaryResult(fy=fy, use_new_regime=use_new_regime,
                       caveats=list(NOT_MODELLED))

    for emp in employers:
        r = EmployerResult(key=emp.key, name=emp.name, tan=emp.tan,
                           is_previous_employer=emp.is_previous_employer)
        r.salary_17_1_paise = emp.salary_17_1_paise
        r.perquisites_17_2_paise = sum(l.amount_paise for l in emp.perquisites)
        for ex in emp.esop_exercises:
            value = esop_perquisite_paise(ex)
            r.esop_lines.append({
                "description": ex.description, "shares": ex.shares,
                "fmv_per_share_paise": ex.fmv_per_share_paise,
                "exercise_price_per_share_paise": ex.exercise_price_per_share_paise,
                "perquisite_paise": value,
            })
            r.esop_perquisite_paise += value
            if ex.exercise_price_per_share_paise >= ex.fmv_per_share_paise and ex.shares:
                r.workings.append(
                    f"{ex.description or 'ESOP exercise'}: exercised at or above "
                    "its fair market value, so there is no perquisite.")
        r.profits_in_lieu_17_3_paise = emp.profits_in_lieu_17_3_paise
        r.gross_salary_paise = (r.salary_17_1_paise + r.perquisites_17_2_paise
                                + r.esop_perquisite_paise + r.profits_in_lieu_17_3_paise)

        for line in emp.exemptions:
            label, new_regime_ok = EXEMPTION_KINDS[line.kind]
            r.exemptions_claimed_paise += line.amount_paise
            if use_new_regime and not new_regime_ok:
                r.workings.append(
                    f"{label} is not allowed under §115BAC(2): "
                    f"₹{whole_rupees(line.amount_paise)} is not deducted.")
            else:
                r.exemptions_allowed_paise += line.amount_paise
        # An exemption cannot exceed the salary it exempts: a larger one is an
        # error in the keying, and deducting it would create a negative salary.
        if r.exemptions_allowed_paise > r.gross_salary_paise:
            out.gaps.append(
                f"{emp.name}: the exemptions keyed (₹{whole_rupees(r.exemptions_allowed_paise)}) "
                f"exceed this employer's gross salary (₹{whole_rupees(r.gross_salary_paise)}); "
                "they were limited to the gross. Check the figures against Form 16.")
            r.exemptions_allowed_paise = r.gross_salary_paise
        if use_new_regime:
            if emp.professional_tax_paise:
                r.workings.append(
                    "Professional tax is not allowed under §115BAC(2): not deducted.")
        else:
            r.professional_tax_allowed_paise = emp.professional_tax_paise
        r.net_salary_paise = max(
            0, r.gross_salary_paise - r.exemptions_allowed_paise
            - r.professional_tax_allowed_paise)
        out.employers.append(r)

    out.gross_salary_paise = sum(e.gross_salary_paise for e in out.employers)
    out.exemptions_allowed_paise = sum(e.exemptions_allowed_paise for e in out.employers)
    out.professional_tax_paise = sum(e.professional_tax_allowed_paise for e in out.employers)
    out.hra_exemption_paise = 0 if use_new_regime else _hra_exemption(hra)
    if use_new_regime and (hra.hra_received_paise or hra.rent_paid_paise):
        out.gaps.append(
            "House rent allowance is not exempt under §115BAC(2): no §10(13A) "
            "exemption is taken.")

    # The standard deduction is taken ONCE, against the salary after the other
    # exemptions and professional tax and before HRA — the base the engine
    # measures it on, so the two cannot differ.
    base = max(0, out.gross_salary_paise - out.exemptions_allowed_paise
               - out.professional_tax_paise)
    limit = (rates.new_regime_standard_deduction_paise if use_new_regime
             else rates.old_regime_standard_deduction_paise)
    out.standard_deduction_paise = min(limit, base)
    out.income_chargeable_paise = max(
        0, base - out.hra_exemption_paise - out.standard_deduction_paise)

    out.engine_inputs = {
        # The engine's ONE salary box.
        "gross_salary_paise": base,
        # And HRA through its own fields.
        "hra": {
            "basic_salary_paise": hra.basic_salary_paise,
            "hra_received_paise": hra.hra_received_paise,
            "rent_paid_paise": hra.rent_paid_paise,
            "is_metro": hra.is_metro,
        },
    }
    return out
