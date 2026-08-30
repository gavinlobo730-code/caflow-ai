"""
ITR return payload — the computed figures, and why this does not emit a file.

WHAT A CA NEEDS AND WHAT THIS PROVIDES

Filing an income tax return offline means producing a JSON file in the schema
the Income Tax Department publishes, per assessment year and per form (ITR-1
Sahaj, ITR-2, ITR-3, ITR-4 Sugam, ITR-5, ITR-6), and uploading it to the
e-filing portal. The department also ships its own offline utility that
generates that file.

This module produces the COMPUTED FIGURES a return needs — every value, with
the section it comes from and the schedule it belongs to — as a structured
payload. What it deliberately does NOT do is write a file claiming to be an
ITR JSON.

WHY NOT, STATED PLAINLY

The schema is a real, versioned artefact with exact field names and nesting,
published by the department and revised every year. This codebase does not have
it: the department's site is unreachable from the environment this module was
written in (the network egress policy refuses www.incometax.gov.in with a 403),
so the field names could only have been written from memory.

A JSON file with invented field names is not a near-miss. It is either rejected
at upload — wasting a CA's time and teaching them the product cannot be trusted
— or, worse, accepted with values sitting in the wrong fields, which is a wrong
return filed under a client's name and a CA's signature.

So FIELD_MAPPINGS below carries verified = False, and generate_itr_json REFUSES
to emit while that holds. This is the discipline the rest of this package
already uses: statutory_rates marks an unconfirmed year rather than guessing at
its numbers, services/filing_demo transmits nothing and says SIM-NOT-FILED on
every response, and domain/udin validates a number a CA obtained rather than
minting one.

WHAT MAKES THIS FINISHABLE

The values are the hard part and they are done. Turning this into a real
generator is then a DATA change — fill in the department's field names against
the payload keys below, set verified = True, and the refusal lifts. No
computation moves.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

ITRForm = Literal["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6"]


@dataclass(frozen=True)
class PayloadValue:
    """One figure a return needs, with its provenance."""
    key: str
    label: str
    amount_paise: int
    # The schedule of the return this belongs in, as a CA would name it.
    schedule: str
    # The section the figure arises under, so it can be checked.
    reference: str


@dataclass(frozen=True)
class FieldMapping:
    """How this product's payload keys correspond to a form's JSON fields.

    `verified` is False for every form here, and until it is True for a form no
    file may be emitted for it. `schema_version` records which published schema
    a mapping was written against — an unverified mapping has none, because
    writing a version number beside unverified names would assert exactly the
    correspondence that has not been established.
    """
    form: str
    assessment_year: str
    schema_version: Optional[str]
    verified: bool
    # payload key -> the field path in the department's schema.
    paths: dict[str, str] = field(default_factory=dict)


# No mapping is verified, and none carries invented names: an EMPTY mapping is
# honest, while a plausible-looking one is not.
FIELD_MAPPINGS: dict[str, FieldMapping] = {
    form: FieldMapping(form=form, assessment_year="2026-27",
                       schema_version=None, verified=False, paths={})
    for form in ("ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6")
}


class SchemaNotVerified(RuntimeError):
    """Raised instead of emitting a file against an unverified schema."""


@dataclass(frozen=True)
class ITRPayload:
    form: str
    assessment_year: str
    values: tuple[PayloadValue, ...]
    schema_is_verified: bool
    can_emit_file: bool
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """The figures keyed by payload key — safe to display, export, or key
        into the department's own offline utility. NOT an ITR JSON, and never
        presented as one."""
        return {v.key: v.amount_paise for v in self.values}

    def by_schedule(self) -> dict[str, list[PayloadValue]]:
        out: dict[str, list[PayloadValue]] = {}
        for v in self.values:
            out.setdefault(v.schedule, []).append(v)
        return out


def build_itr_payload(
    *,
    form: ITRForm,
    assessment_year: str = "2026-27",
    gross_total_income_paise: int = 0,
    total_deductions_paise: int = 0,
    total_income_paise: int = 0,
    tax_on_total_income_paise: int = 0,
    rebate_87a_paise: int = 0,
    surcharge_paise: int = 0,
    cess_paise: int = 0,
    total_tax_paise: int = 0,
    tds_tcs_paise: int = 0,
    advance_tax_paid_paise: int = 0,
    self_assessment_tax_paise: int = 0,
    interest_234a_paise: int = 0,
    interest_234b_paise: int = 0,
    interest_234c_paise: int = 0,
) -> ITRPayload:
    """Assemble the figures a return needs.

    Every amount is integer paise, as everywhere else in this package. The
    RUPEE conversion the department's schema requires is deliberately not done
    here: rounding belongs at the payload boundary, and applying it before that
    boundary is known would bake in a convention that may not be the schema's.
    """
    mapping = FIELD_MAPPINGS.get(form)
    verified = bool(mapping and mapping.verified)

    values = [
        PayloadValue("gross_total_income", "Gross Total Income",
                     gross_total_income_paise, "Part B-TI", "IT Act §14"),
        PayloadValue("total_deductions", "Deductions under Chapter VI-A",
                     total_deductions_paise, "Schedule VI-A", "IT Act Chapter VI-A"),
        PayloadValue("total_income", "Total Income",
                     total_income_paise, "Part B-TI", "IT Act §5"),
        PayloadValue("tax_on_total_income", "Tax on Total Income",
                     tax_on_total_income_paise, "Part B-TTI", "IT Act §4"),
        PayloadValue("rebate_87a", "Rebate under §87A",
                     rebate_87a_paise, "Part B-TTI", "IT Act §87A"),
        PayloadValue("surcharge", "Surcharge",
                     surcharge_paise, "Part B-TTI", "Finance Act, First Schedule"),
        PayloadValue("cess", "Health and Education Cess",
                     cess_paise, "Part B-TTI", "Finance Act"),
        PayloadValue("total_tax", "Total Tax Liability",
                     total_tax_paise, "Part B-TTI", "IT Act §4"),
        PayloadValue("tds_tcs", "Tax Deducted / Collected at Source",
                     tds_tcs_paise, "Schedule TDS / TCS", "IT Act Chapter XVII-B"),
        PayloadValue("advance_tax_paid", "Advance Tax Paid",
                     advance_tax_paid_paise, "Schedule IT", "IT Act §208"),
        PayloadValue("self_assessment_tax", "Self-Assessment Tax",
                     self_assessment_tax_paise, "Schedule IT", "IT Act §140A"),
        PayloadValue("interest_234a", "Interest for late filing",
                     interest_234a_paise, "Part B-TTI", "IT Act §234A"),
        PayloadValue("interest_234b", "Interest for advance-tax default",
                     interest_234b_paise, "Part B-TTI", "IT Act §234B"),
        PayloadValue("interest_234c", "Interest for deferment of advance tax",
                     interest_234c_paise, "Part B-TTI", "IT Act §234C"),
    ]

    notes = [
        "These are the computed figures for the return. They are NOT an ITR "
        "JSON file and must not be presented as one.",
    ]
    if not verified:
        notes.append(
            f"No verified schema mapping exists for {form} AY "
            f"{assessment_year}, so no file can be generated. The department's "
            f"published schema fixes the exact field names and nesting, and "
            f"inventing them produces a file that is either rejected at upload "
            f"or — worse — accepted with values in the wrong fields."
        )
        notes.append(
            "Use the department's own offline utility to produce the file, "
            "keying these figures into it."
        )
    return ITRPayload(
        form=form, assessment_year=assessment_year, values=tuple(values),
        schema_is_verified=verified, can_emit_file=verified,
        notes=tuple(notes),
    )


def generate_itr_json(payload: ITRPayload) -> str:
    """Emit the ITR JSON file — or refuse, by name.

    Refusing is the point. A generator that produced *something* against an
    unverified schema would be worse than one that produces nothing: the file
    would look finished, and the failure would surface at the portal, or not at
    all.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
    """
    mapping = FIELD_MAPPINGS.get(payload.form)
    if not mapping or not mapping.verified or not mapping.paths:
        raise SchemaNotVerified(
            f"No verified ITR JSON schema mapping for {payload.form} AY "
            f"{payload.assessment_year}. The Income Tax Department's published "
            f"schema fixes the exact field names and nesting; this product "
            f"does not hold it, so a file cannot be generated. Produce the "
            f"file in the department's offline utility using the computed "
            f"figures from build_itr_payload, or supply a verified mapping — "
            f"that is a data change to FIELD_MAPPINGS, not a code change."
        )
    import json
    body: dict[str, Any] = {}
    for value in payload.values:
        path = mapping.paths.get(value.key)
        if path is None:
            continue
        cursor = body
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value.amount_paise
    return json.dumps(body, separators=(",", ":"), sort_keys=True)
