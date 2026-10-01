"""The house-property and salary worksheets' request models (TDS-INCOME-TAX-14, -15).

These are the API DOOR for `income_tax_worksheets.payload_json`, which is
free-shaped JSON in the database — the vocabulary is Python's and a CHECK cannot
read it — so the shape and every closed vocabulary are held HERE and re-held by
the domain modules, which refuse again (`WorksheetRefused`): a validator on one
door only is one write path from being none.

Every amount is an INTEGER in paise. The browser converts the rupees a CA types
with `lib/money/rupeeInput`, so nothing here parses a rupee string, and a
fractional paise is a 422 rather than a rounding.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.validators import validate_tan
from domain.income_tax import house_property as hp
from domain.income_tax import schedule_s as ss

#: A worksheet is a few properties or employers. The cap is a bound on the
#: request, not a statutory limit.
MAX_PROPERTIES = 50
MAX_EMPLOYERS = 20
MAX_LINES = 50


def _paise():
    """A fresh FieldInfo each time: one instance shared across fields is how
    pydantic metadata ends up merged between them."""
    return Field(default=0, ge=0)


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ── House property ──────────────────────────────────────────────────────────

class PropertyIn(_Strict):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    use: str
    share_bps: int = Field(default=10_000, ge=1, le=10_000)
    municipal_value_paise: int = _paise()
    fair_rent_paise: int = _paise()
    standard_rent_paise: Optional[int] = Field(default=None, ge=0)
    rent_receivable_paise: int = _paise()
    unrealised_rent_paise: int = _paise()
    unrealised_rent_rule_4_met: Optional[bool] = None
    vacant_part_of_year: bool = False
    municipal_tax_paid_paise: int = _paise()
    interest_paise: int = _paise()
    pre_construction_interest_paise: int = _paise()
    completion_fy: Optional[str] = None
    loan_taken_on: Optional[date] = None
    completed_on: Optional[date] = None
    loan_purpose: Optional[str] = None

    @field_validator("use")
    @classmethod
    def _use(cls, v: str) -> str:
        if v not in hp.USES:
            raise ValueError(f"use must be one of {', '.join(hp.USES)}")
        return v

    @field_validator("loan_purpose")
    @classmethod
    def _purpose(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        if v not in hp.PURPOSES:
            raise ValueError(f"loan_purpose must be one of {', '.join(hp.PURPOSES)}")
        return v

    @field_validator("completion_fy")
    @classmethod
    def _fy(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        from core.ist_clock import normalise_fy_label
        return normalise_fy_label(v, field="completion year")

    def to_domain(self) -> hp.Property:
        return hp.Property(**self.model_dump())


class HousePropertyPayload(_Strict):
    properties: list[PropertyIn] = Field(default_factory=list, max_length=MAX_PROPERTIES)

    def to_domain(self) -> list[hp.Property]:
        return [p.to_domain() for p in self.properties]


# ── Salary ──────────────────────────────────────────────────────────────────

class PerquisiteIn(_Strict):
    kind: str
    amount_paise: int = _paise()
    description: str = Field(default="", max_length=200)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ss.PERQUISITE_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ss.PERQUISITE_KINDS)}")
        return v


class ExemptionIn(_Strict):
    kind: str
    amount_paise: int = _paise()

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ss.EXEMPTION_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ss.EXEMPTION_KINDS)}")
        return v


class EsopIn(_Strict):
    description: str = Field(default="", max_length=200)
    shares: int = _paise()
    fmv_per_share_paise: int = _paise()
    exercise_price_per_share_paise: int = _paise()


class EmployerIn(_Strict):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    tan: Optional[str] = None
    is_previous_employer: bool = False
    salary_17_1_paise: int = _paise()
    perquisites: list[PerquisiteIn] = Field(default_factory=list, max_length=MAX_LINES)
    esop_exercises: list[EsopIn] = Field(default_factory=list, max_length=MAX_LINES)
    profits_in_lieu_17_3_paise: int = _paise()
    exemptions: list[ExemptionIn] = Field(default_factory=list, max_length=MAX_LINES)
    professional_tax_paise: int = _paise()

    @field_validator("tan")
    @classmethod
    def _tan(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        problem = validate_tan(v)
        if problem:
            raise ValueError(problem)
        return v.strip().upper()

    def to_domain(self) -> ss.Employer:
        return ss.Employer(
            key=self.key, name=self.name, tan=self.tan,
            is_previous_employer=self.is_previous_employer,
            salary_17_1_paise=self.salary_17_1_paise,
            perquisites=tuple(ss.PerquisiteLine(p.kind, p.amount_paise, p.description)
                              for p in self.perquisites),
            esop_exercises=tuple(
                ss.EsopExercise(e.description, e.shares, e.fmv_per_share_paise,
                                e.exercise_price_per_share_paise)
                for e in self.esop_exercises),
            profits_in_lieu_17_3_paise=self.profits_in_lieu_17_3_paise,
            exemptions=tuple(ss.ExemptionLine(x.kind, x.amount_paise)
                             for x in self.exemptions),
            professional_tax_paise=self.professional_tax_paise,
        )


class HraIn(_Strict):
    basic_salary_paise: int = _paise()
    hra_received_paise: int = _paise()
    rent_paid_paise: int = _paise()
    is_metro: bool = False

    def to_domain(self) -> ss.Hra:
        return ss.Hra(**self.model_dump())


class SalaryPayload(_Strict):
    employers: list[EmployerIn] = Field(default_factory=list, max_length=MAX_EMPLOYERS)
    hra: HraIn = Field(default_factory=HraIn)

    def to_domain(self) -> tuple[list[ss.Employer], ss.Hra]:
        return [e.to_domain() for e in self.employers], self.hra.to_domain()


#: kind -> payload model. The router dispatches on this and nothing else, so a
#: third kind is one entry here, one in the service and one in the migration's
#: CHECK — and a guard asserts the three agree.
PAYLOADS: dict[str, type[BaseModel]] = {
    "house_property": HousePropertyPayload,
    "salary": SalaryPayload,
}
