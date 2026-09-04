"""
Applying a named salary structure to an employee.

WHAT WAS MISSING

public.salary_structures has existed since migration 054 and NO RUN HAS EVER
READ IT. A CA could create "Junior — 40/20", see it listed, and nothing would
ever apply it: every employee's basic, HRA and DA are keyed in one by one on the
employee master.

WHAT APPLYING ONE MEANS HERE, AND WHY

It writes a payroll_salary_revisions row (migration 300), not a live link on the
employee.

  * The run already reads revisions — _salary_in_force takes the latest one
    effective on or before the month — so a structure applied from 1 October
    starts in October and does not restate September, which is posted.
  * A live salary_structure_id would mean editing a structure silently
    restates every employee on it, including months already in the general
    ledger. Re-applying is an explicit act instead, and source_structure_id
    records which structure produced the revision.

THREE THINGS THE TABLE'S OWN SHAPE FORCES, AND EACH IS A REFUSAL

1. THE PERCENTAGES ARE OF GROSS, NOT OF "CTC".
   Migration 054 comments the columns "% of CTC". Read literally with an Indian
   CTC — which includes the employer's PF — the definition is circular: PF is
   12% of basic, and basic would be a percentage of a total that includes it.
   There is no fixed point for arbitrary rates and no way to say which of the
   two the CA meant.

   So a structure is applied to a stated MONTHLY GROSS, the figure the employee
   is told and the one every downstream computation already starts from. The
   caller names the gross; nothing is inferred.

2. `special_percent` CANNOT BE HONOURED ALONGSIDE A FIXED MEDICAL AMOUNT.
   medical_paise is an absolute rupee figure, so

       gross = gross×(basic+hra+da+lta+special)/100 + medical

   only holds when the percentages fall short of 100 by exactly medical/gross —
   which depends on the gross and therefore differs per employee. Special is the
   REMAINDER, and it is the remainder in paise, so the components sum to the
   gross exactly with nothing lost to rounding.

3. HRA AND DA ARE STORED AS PERCENTAGES OF BASIC, TO TWO DECIMALS.
   The employee master and payroll_salary_revisions carry hra_percent and
   da_percent as NUMERIC(5,2) of BASIC, while the structure states them as a
   percentage of gross. Converting is exact only when the ratio happens to land
   on two decimals — 20% of gross on a 40% basic is 50.00, but 17% on a 43%
   basic is 39.5348…, which stores as 39.53 and pays ₹1.85 less on a ₹50,000
   gross.

   That difference is REPORTED, per employee, with both figures. It is not
   silently rounded: HRA feeds §10(13A) and Annexure II, and a figure that is
   nearly right is the kind that reconciles for eleven months and fails in the
   twelfth.

# Every amount is integer paise. Nothing here uses floating point.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

#: Matches routers/payroll.py::_percent_of exactly. Two derivations of one
#: percentage drift, and this one has to reproduce that one to the paise or the
#: reproducibility check below is meaningless.
def percent_of(base_paise: int, percent) -> int:
    pct = Decimal(str(percent or 0))
    return int((Decimal(base_paise) * pct / 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


class StructureError(ValueError):
    """A structure that cannot be applied as stated."""


@dataclass(frozen=True)
class Component:
    """One head of pay, with what the structure asked for and what will be paid.

    They differ only for HRA and DA, and only because those are stored as a
    percentage of basic to two decimals. `intended_paise` is what the structure
    asks for; `paise` is what the stored figure will actually produce.
    """
    name: str
    paise: int
    intended_paise: int

    @property
    def drift_paise(self) -> int:
        return self.paise - self.intended_paise


@dataclass(frozen=True)
class Application:
    """What applying a structure at one gross comes to."""
    monthly_gross_paise: int
    basic_paise: int
    hra_percent_of_basic: Decimal
    da_percent_of_basic: Decimal
    lta_paise: int
    medical_paise: int
    special_allowance_paise: int
    components: tuple[Component, ...]

    @property
    def drifts(self) -> tuple[Component, ...]:
        """The heads whose stored two-decimal percentage cannot reproduce the
        structure's intended amount. Empty is the ordinary case."""
        return tuple(c for c in self.components if c.drift_paise != 0)

    def as_revision(self) -> dict:
        """The payroll_salary_revisions columns, ready to write."""
        return {
            "basic_paise": self.basic_paise,
            "hra_percent": str(self.hra_percent_of_basic),
            "da_percent": str(self.da_percent_of_basic),
            "lta_paise": self.lta_paise,
            "medical_paise": self.medical_paise,
            "special_allowance_paise": self.special_allowance_paise,
            # Not derived from a structure — anything else the CA had set is a
            # separate decision and applying a structure must not silently zero
            # it. The caller carries it forward.
            "other_allowances_paise": 0,
        }


def _pct(structure: dict, key: str) -> Decimal:
    try:
        return Decimal(str(structure.get(key) or 0))
    except Exception:
        raise StructureError(f"{key} is not a percentage: {structure.get(key)!r}")


def _as_percent_of_basic(amount_paise: int, basic_paise: int) -> Decimal:
    """The two-decimal percentage of basic that comes nearest `amount_paise`.

    NUMERIC(5,2) is the column, so two decimals is the whole precision
    available — this returns the best of it and the caller checks whether the
    best is exact.
    """
    if basic_paise <= 0:
        return Decimal("0.00")
    return (Decimal(amount_paise) * 100 / Decimal(basic_paise)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def apply_structure(structure: dict, monthly_gross_paise: int) -> Application:
    """Derive one employee's pay heads from a structure at a stated gross.

    Refuses rather than approximates. The three refusals are the ones the
    table's own shape forces — see the module docstring.
    """
    gross = int(monthly_gross_paise or 0)
    if gross <= 0:
        raise StructureError(
            "A monthly gross is required to apply a structure — the percentages "
            "are of something, and nothing here can infer what.")

    basic_pct = _pct(structure, "basic_percent")
    hra_pct = _pct(structure, "hra_percent")
    da_pct = _pct(structure, "da_percent")
    lta_pct = _pct(structure, "lta_percent")
    for name, pct in (("basic", basic_pct), ("HRA", hra_pct),
                      ("DA", da_pct), ("LTA", lta_pct)):
        if pct < 0:
            raise StructureError(f"{name} percentage cannot be negative.")
    if basic_pct <= 0:
        raise StructureError(
            "Basic must be more than 0% — every statutory computation in this "
            "system starts from it: PF, gratuity, HRA exemption and bonus.")

    stated = basic_pct + hra_pct + da_pct + lta_pct
    if stated > 100:
        raise StructureError(
            f"Basic, HRA, DA and LTA come to {stated}% of gross, which is more "
            f"than the whole of it. Special allowance is the remainder and "
            f"cannot be negative.")

    medical = int(structure.get("medical_paise") or 0)
    if medical < 0:
        raise StructureError("The medical allowance cannot be negative.")

    basic = percent_of(gross, basic_pct)
    hra_intended = percent_of(gross, hra_pct)
    da_intended = percent_of(gross, da_pct)
    lta = percent_of(gross, lta_pct)

    # The two that have to survive a round trip through a percentage OF BASIC.
    hra_stored_pct = _as_percent_of_basic(hra_intended, basic)
    da_stored_pct = _as_percent_of_basic(da_intended, basic)
    hra_actual = percent_of(basic, hra_stored_pct)
    da_actual = percent_of(basic, da_stored_pct)

    # Special is the REMAINDER in paise, of what will ACTUALLY be paid — so the
    # heads sum to the gross exactly whether or not HRA drifted. Computing it
    # from the intended figures would make the gross itself wrong.
    special = gross - basic - hra_actual - da_actual - lta - medical
    if special < 0:
        raise StructureError(
            f"The fixed medical allowance of {medical} paise does not fit: "
            f"basic, HRA, DA and LTA already come to {gross - medical - special} "
            f"paise of a {gross}-paise gross. Lower the percentages or the "
            f"medical amount.")

    return Application(
        monthly_gross_paise=gross,
        basic_paise=basic,
        hra_percent_of_basic=hra_stored_pct,
        da_percent_of_basic=da_stored_pct,
        lta_paise=lta,
        medical_paise=medical,
        special_allowance_paise=special,
        components=(
            Component("Basic", basic, basic),
            Component("HRA", hra_actual, hra_intended),
            Component("DA", da_actual, da_intended),
            Component("LTA", lta, lta),
            Component("Medical", medical, medical),
            Component("Special allowance", special, special),
        ),
    )


def drift_note(who: str, application: Application) -> list[str]:
    """One sentence per head whose stored percentage cannot pay the intended
    amount, naming both figures.

    Reported rather than rounded away: HRA feeds §10(13A) and Annexure II, and a
    figure that is nearly right is the kind that reconciles for eleven months
    and fails in the twelfth.
    """
    return [
        f"{who}: {c.name} works out to {c.intended_paise} paise from the "
        f"structure, but it is stored as a percentage of basic to two decimals, "
        f"which pays {c.paise} paise — {abs(c.drift_paise)} paise "
        f"{'more' if c.drift_paise > 0 else 'less'} a month. The difference goes "
        f"to special allowance, so the gross is unchanged."
        for c in application.drifts
    ]
