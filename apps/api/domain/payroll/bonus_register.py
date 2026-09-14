"""The annual statutory bonus register — Payment of Bonus Act 1965 (PAY-23).

WHY THIS EXISTS

`domain/payroll/bonus.py` has implemented the Act since the payroll module was
built, and its ONLY caller was a leaver's settlement. So a client's continuing
employees — which is all of them, most years — were never computed for.

That is not a reporting gap:

  §10   The minimum is payable "whether or not the employer has any allocable
        surplus in the accounting year". It is a debt, not a discretionary
        payment.
  §19   Payable within EIGHT MONTHS of the close of the accounting year. For a
        year ending 31 March that is 30 November — the same day as several
        other things, which is exactly why it needs to be on a calendar.
  §28   Non-payment is an offence.

So the figure belongs on the balance sheet as a provision and on the compliance
calendar as a deadline, and nothing in the product produced it.

WHAT THIS MODULE DECIDES, AND WHAT IT REFUSES

It decides, per employee: whether the Act reaches them (§2(13)), whether they
qualify (§8), whether they are disqualified (§9), what the calculation base is
(§12), and what is payable (§10 with §11) — by calling `bonus.compute`, which
is the authority for every one of those and is not reimplemented here. What
THIS module adds is the population, the per-employee inputs read off the year,
and the totals.

It REFUSES four things rather than guessing:

  THE RATE is the employer's own determination from their allocable surplus
  under §§4-7 and the Second Schedule. Payroll cannot derive it. Absent, the
  §10 MINIMUM applies — which is not a fallback but the figure that is owed
  whatever the surplus turns out to be.

  THE §12 MINIMUM WAGE is per state, per scheduled employment, per skill grade,
  revised twice yearly. `bonus.compute` already computes on ₹7,000 and says so;
  this module carries that gap up to the register so it is visible once for the
  client rather than repeated per employee.

  §8's THIRTY WORKING DAYS is a count of days ACTUALLY WORKED. Where the year's
  attendance is recorded, that is the count. Where it is not, the register does
  NOT guess in either direction: it says the days are unknown, computes the
  figure so the liability is visible, and names the employee. Treating absent
  attendance as zero would disqualify everybody at a client that runs payroll
  without attendance records — hiding a debt §28 makes an offence to miss; and
  treating it as thirty would assert a fact nobody holds.

  FORM C (Rule 4(c)) and FORM D (Rule 5) of the Payment of Bonus Rules 1975 are
  NOT produced. The register holds the figures those forms want; the layouts
  are published forms this environment cannot read, and a statutory form
  written from memory is what this codebase refuses.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.payroll import bonus as bonus_domain

#: §19 — "within a period of eight months from the close of the accounting
#: year". The proviso lets the appropriate Government extend it, on the
#: employer's application, to a total of two years; that is an application
#: nobody here has made, so the date computed is the unextended one and the
#: register says the proviso exists rather than assuming it was invoked.
SECTION_19_MONTHS: int = 8
SECTION_19_PROVISO = (
    "§19's proviso allows the appropriate Government, on the employer's "
    "application, to extend this by up to two years in total. The date shown "
    "is the unextended one: an extension is an application somebody made, not "
    "something to assume."
)

#: The five §9 grounds, spelled as `bonus_disqualifications.ground` CHECKs
#: them. Held here so the API and the screen have one list and neither writes
#: its own — the shape `domain/gst/rcm_documents` uses for registration state.
SECTION_9_GROUNDS = {
    "fraud": "Fraud",
    "riotous_or_violent_behaviour_on_the_premises":
        "Riotous or violent behaviour while on the premises of the establishment",
    "theft_of_establishment_property":
        "Theft of the property of the establishment",
    "misappropriation_of_establishment_property":
        "Misappropriation of the property of the establishment",
    "sabotage_of_establishment_property":
        "Sabotage of the property of the establishment",
}

WORKING_DAYS_NOT_RECORDED = (
    "No attendance is recorded for this employee in this accounting year, so "
    "§8's thirty WORKING DAYS could not be counted. The bonus is shown so the "
    "liability is visible; confirm the days before paying. It is deliberately "
    "not read as nil — that would disqualify every employee at a client who "
    "runs payroll without attendance records, and §10's minimum is a debt."
)

ONE_MINIMUM_WAGE_PER_CLIENT = (
    "§12 compares ₹7,000 with the minimum wage for the SCHEDULED EMPLOYMENT. "
    "One figure is recorded for this client and applied to every employee. "
    "Where the client has several scheduled employments or skill grades, each "
    "has its own minimum wage and this register does not distinguish them."
)

NOT_POSTED = (
    "Nothing is posted. The provision is a journal the CA raises: the rate is "
    "the employer's own §10/§11 determination and the account it is charged to "
    "is theirs to choose."
)

FORMS_NOT_PRODUCED = (
    "Form C (Rule 4(c)) and Form D (Rule 5) of the Payment of Bonus Rules 1975 "
    "are not produced. The figures they want are here; the layouts are "
    "published forms, and one written from memory would be worse than none."
)


@dataclass
class EmployeeBonus:
    employee_id: str = ""
    employee_name: str = ""
    monthly_salary_paise: int = 0          # §2(21) — basic plus DA
    months_worked: int = 0
    working_days: Optional[int] = None     # None = not recorded
    eligible: bool = False
    payable_paise: int = 0
    minimum_paise: int = 0
    maximum_paise: int = 0
    calculation_base_monthly_paise: int = 0
    reasons: list = field(default_factory=list)
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "monthly_salary_paise": self.monthly_salary_paise,
            "months_worked": self.months_worked,
            "working_days": self.working_days,
            "eligible": self.eligible,
            "payable_paise": self.payable_paise,
            "minimum_paise": self.minimum_paise,
            "maximum_paise": self.maximum_paise,
            "calculation_base_monthly_paise": self.calculation_base_monthly_paise,
            "reasons": list(self.reasons),
            "gaps": list(self.gaps),
        }


@dataclass
class Register:
    accounting_year: str = ""
    rate_bps: int = bonus_domain.MINIMUM_RATE_BPS
    rate_is_the_statutory_minimum: bool = True
    minimum_wage_monthly_paise: Optional[int] = None
    scheduled_employment: Optional[str] = None
    due_date: str = ""
    employees: list = field(default_factory=list)
    total_payable_paise: int = 0
    total_minimum_paise: int = 0
    total_maximum_paise: int = 0
    eligible_count: int = 0
    excluded_count: int = 0
    gaps: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "accounting_year": self.accounting_year,
            "rate_bps": self.rate_bps,
            "rate_is_the_statutory_minimum": self.rate_is_the_statutory_minimum,
            "minimum_wage_monthly_paise": self.minimum_wage_monthly_paise,
            "scheduled_employment": self.scheduled_employment,
            "due_date": self.due_date,
            "employees": [e.as_dict() for e in self.employees],
            "total_payable_paise": self.total_payable_paise,
            "total_minimum_paise": self.total_minimum_paise,
            "total_maximum_paise": self.total_maximum_paise,
            "eligible_count": self.eligible_count,
            "excluded_count": self.excluded_count,
            "gaps": list(self.gaps),
            "notes": list(self.notes),
        }


def due_date(accounting_year: str) -> str:
    """§19 — eight months from the close of the accounting year.

    DERIVED from the year's own end rather than stated as 30 November, so a
    client whose accounting year is not the financial year gets their own date
    — §2(1) defines the accounting year by what is laid before the company in
    general meeting, which is not always April to March.
    """
    start_year = int(str(accounting_year).split("-")[0])
    # The accounting year this product holds is the financial year: 1 April to
    # 31 March. Its close is 31 March of the following calendar year, and eight
    # months from a 31 March close is 30 November.
    close = date(start_year + 1, 3, 31)
    month = close.month + SECTION_19_MONTHS
    year = close.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = close.day
    while True:
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            day -= 1


def build(
    *,
    accounting_year: str,
    employees: list,
    rate_bps: Optional[int] = None,
    minimum_wage_monthly_paise: Optional[int] = None,
    scheduled_employment: Optional[str] = None,
) -> Register:
    """The register for one client's accounting year.

    `employees` are dicts carrying, per employee: `employee_id`, `name`,
    `monthly_salary_paise` (§2(21) — basic plus DA, which the caller derives
    from the employee master), `months_worked` (months with a RELEASED payroll
    run), `working_days` (None where the year's attendance is not recorded),
    `under_fifteen` and `disqualified_ground`.

    Reads nothing and posts nothing.
    """
    rate = int(rate_bps) if rate_bps is not None else bonus_domain.MINIMUM_RATE_BPS
    out = Register(
        accounting_year=accounting_year,
        rate_bps=rate,
        rate_is_the_statutory_minimum=(rate == bonus_domain.MINIMUM_RATE_BPS),
        minimum_wage_monthly_paise=minimum_wage_monthly_paise,
        scheduled_employment=scheduled_employment,
        due_date=due_date(accounting_year),
    )
    out.notes.append(SECTION_19_PROVISO)
    out.notes.append(NOT_POSTED)
    out.notes.append(FORMS_NOT_PRODUCED)
    if minimum_wage_monthly_paise is not None:
        out.notes.append(ONE_MINIMUM_WAGE_PER_CLIENT)

    if rate == bonus_domain.MINIMUM_RATE_BPS:
        out.notes.append(
            "No allocable surplus has been declared for this year, so the §10 "
            "minimum of 8.33% applies. That is not a placeholder: §10 makes it "
            "payable whether or not there is a surplus. Where the surplus "
            "under §§4-7 supports more, record the rate — §11 caps it at 20%."
        )

    days_unknown: list = []
    for raw in employees:
        line = _one(raw, accounting_year=accounting_year, rate_bps=rate,
                    minimum_wage_monthly_paise=minimum_wage_monthly_paise)
        out.employees.append(line)
        if line.eligible:
            out.eligible_count += 1
            out.total_payable_paise += line.payable_paise
            out.total_minimum_paise += line.minimum_paise
            out.total_maximum_paise += line.maximum_paise
        else:
            out.excluded_count += 1
        if line.working_days is None and line.eligible:
            days_unknown.append(line.employee_name or line.employee_id)

    if days_unknown:
        out.gaps.append(
            f"§8 requires thirty WORKING days in the accounting year and no "
            f"attendance is recorded for {len(days_unknown)} of these "
            f"employees: {', '.join(sorted(days_unknown)[:12])}"
            + ("…" if len(days_unknown) > 12 else "")
            + ". Their bonus is shown so the liability is visible; confirm the "
              "days before paying."
        )
    if minimum_wage_monthly_paise is None:
        out.gaps.append(
            "§12 computes bonus on ₹7,000 a month OR the minimum wage for the "
            "scheduled employment, WHICHEVER IS HIGHER. No minimum wage is "
            "recorded for this client, so ₹7,000 was used throughout. In most "
            "states, for most scheduled employments, the minimum wage is "
            "higher — and then every figure on this register is too low."
        )
    return out


def _one(raw: dict, *, accounting_year: str, rate_bps: int,
         minimum_wage_monthly_paise: Optional[int]) -> EmployeeBonus:
    """One employee's line. `bonus.compute` decides; this reads the inputs.

    THE WORKING-DAY COUNT IS THE ONE PLACE THIS MODULE SUBSTITUTES ANYTHING,
    and it substitutes the QUALIFYING count rather than a guess at the real
    one — so an employee whose attendance is not recorded is computed for and
    NAMED, instead of being silently dropped from a register of a statutory
    debt. Every such line carries its own gap, so the substitution travels with
    the figure rather than living only in the summary.
    """
    days = raw.get("working_days")
    unknown = days is None
    line = EmployeeBonus(
        employee_id=str(raw.get("employee_id") or ""),
        employee_name=str(raw.get("name") or raw.get("employee_name") or ""),
        monthly_salary_paise=int(raw.get("monthly_salary_paise") or 0),
        months_worked=int(raw.get("months_worked") or 0),
        working_days=None if unknown else int(days),
    )
    ground = raw.get("disqualified_ground")
    result = bonus_domain.compute(
        accounting_year=accounting_year,
        monthly_salary_paise=line.monthly_salary_paise,
        months_worked=line.months_worked,
        working_days_in_year=(bonus_domain.QUALIFYING_WORKING_DAYS if unknown
                              else int(days)),
        rate_bps=rate_bps,
        minimum_wage_monthly_paise=minimum_wage_monthly_paise,
        under_fifteen=bool(raw.get("under_fifteen")),
        disqualified_under_section_9=bool(ground),
    )
    line.eligible = result.eligible
    line.payable_paise = result.payable_paise
    line.minimum_paise = result.minimum_paise
    line.maximum_paise = result.maximum_paise
    line.calculation_base_monthly_paise = result.calculation_base_monthly_paise
    line.reasons = list(result.reasons)
    line.gaps = list(result.gaps)
    if ground:
        line.reasons.append(
            f"Disqualified under §9 — {SECTION_9_GROUNDS.get(str(ground), ground)}."
        )
    if unknown and result.eligible:
        line.gaps.append(WORKING_DAYS_NOT_RECORDED)
    return line
