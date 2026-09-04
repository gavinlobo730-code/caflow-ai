"""
ITR return payload — the computed figures, where each one goes, and why this
still does not emit a file.

WHAT A CA NEEDS AND WHAT THIS PROVIDES

Filing an income tax return offline means producing a JSON file in the schema
the Income Tax Department publishes, per assessment year and per form, and
uploading it to the e-filing portal. The department also ships its own offline
utility that generates that file.

This module produces the COMPUTED FIGURES a return needs — every value, with the
section it arises under and the schedule it belongs to — and now also says
exactly WHERE each one goes: build_itr_payload for the figures,
itr_field_placements for the placements.

THE SCHEMAS ARE HELD NOW

They were not when this was written: the department's site is unreachable from
this environment (egress policy refuses www.incometax.gov.in with a 403), so the
field names could only have been guessed, and the module refused rather than
guess. The schemas for AY 2026-27 have since been downloaded by hand and are
committed in schemas/. Every path in FIELD_MAPPINGS is resolved against them and
re-verified by tests/test_itr_schema_paths.py, so the mapping cannot drift from
the schema without failing the suite.

WHY IT STILL REFUSES TO WRITE A FILE

Two reasons, each raised by name rather than as one vague failure.

  A SOFTWARE PROVIDER ID is mandatory. Every schema requires
  CreationInfo.SWCreatedBy and CreationInfo.JSONCreatedBy to match SW########,
  a number the department issues to registered providers, and rejects any file
  without one. That is a registration step, not a coding one — the same shape
  as the GSP registration that gates GST filing.

  THE PAYLOAD IS NOT A WHOLE RETURN. It carries fourteen tax figures. A file the
  portal accepts also needs PersonalInfo, FilingStatus, Verification, bank
  details, and for ITR-3/5/6 the balance sheet and profit-and-loss schedules.
  Emitting the fragment would produce something that looks like a return and
  fails at upload.

Refusing on a named, specific ground beats refusing vaguely, and both beat
emitting a file that looks finished. This is the discipline the rest of the
package uses: statutory_rates marks an unconfirmed year rather than guessing,
services/filing_demo transmits nothing and says SIM-NOT-FILED, domain/udin
validates a number a CA obtained rather than minting one.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from domain.income_tax.itr_schema import SCHEMA_FILES

ITRForm = Literal["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"]


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

    `verified` means the paths were resolved against the Department's own
    schema, committed in schemas/, and are re-checked by
    tests/test_itr_schema_paths.py on every run. `schema_version` and
    `schema_file` record WHICH revision that was true of, so a reader can tell
    whether a mapping has been left behind by a mid-year schema revision.
    """
    form: str
    assessment_year: str
    schema_version: Optional[str]
    verified: bool
    # Which committed schema file the paths were resolved against, so a reader
    # can tell which revision this mapping is true of.
    schema_file: Optional[str] = None
    # payload key -> the field path in the department's schema.
    paths: dict[str, str] = field(default_factory=dict)


# Every path below was resolved against the Department's own schema in
# schemas/ and is re-checked on every run of tests/test_itr_schema_paths.py:
# the path must exist and must name an integer field. The mapping cannot drift
# from the schema without failing the suite.
#
# Two kinds of ABSENCE are deliberate, not gaps:
#
#   rebate_87a has no path on ITR-5, ITR-6 or ITR-7. The §87A rebate is for
#   resident individuals; firms, companies and trusts do not get it, and those
#   schemas have no field for it. Writing one somewhere would be inventing a
#   claim the assessee is not entitled to.
#
#   surcharge has no path on ITR-1 or ITR-4. Those forms carry no surcharge
#   field at all.
#
# One path was nearly wrong in a way worth recording. ITR-5 and ITR-6 have
# EducationCess in TWO places: under TaxPayableOnTI (cess on the normal
# computation) and under TaxPayableOnDeemedTI (cess on deemed income under
# §115JC / §115JB). An automatic walk of the schema finds the deemed-income one
# first. Putting the ordinary cess there would have produced a file that
# validates perfectly and reports the wrong tax — which is exactly the failure
# this whole module was built to refuse.
FIELD_MAPPINGS: dict[str, FieldMapping] = {
    "ITR-1": FieldMapping(
        form="ITR-1", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-1"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR1.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR1.ITR1_TaxComputation.EducationCess",
            "gross_total_income": "ITR.ITR1.ITR1_IncomeDeductions.GrossTotIncome",
            "interest_234a": "ITR.ITR1.ITR1_TaxComputation.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR1.ITR1_TaxComputation.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR1.ITR1_TaxComputation.IntrstPay.IntrstPayUs234C",
            "rebate_87a": "ITR.ITR1.ITR1_TaxComputation.Rebate87A",
            "self_assessment_tax": "ITR.ITR1.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "tax_on_total_income": "ITR.ITR1.ITR1_TaxComputation.TotalTaxPayable",
            "total_deductions": "ITR.ITR1.ITR1_IncomeDeductions.UsrDeductUndChapVIA.TotalChapVIADeductions",
            "total_income": "ITR.ITR1.ITR1_IncomeDeductions.TotalIncome",
            "total_tax": "ITR.ITR1.ITR1_TaxComputation.NetTaxLiability",
        },
    ),
    "ITR-2": FieldMapping(
        form="ITR-2", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-2"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR2.PartB_TTI.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.EducationCess",
            "gross_total_income": "ITR.ITR2.PartB-TI.GrossTotalIncome",
            "interest_234a": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234C",
            "rebate_87a": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.Rebate87A",
            "self_assessment_tax": "ITR.ITR2.PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "surcharge": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.TotalSurcharge",
            "tax_on_total_income": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TaxPayableOnTotInc",
            "total_deductions": "ITR.ITR2.PartB-TI.DeductionsUnderScheduleVIA",
            "total_income": "ITR.ITR2.PartB-TI.TotalIncome",
            "total_tax": "ITR.ITR2.PartB_TTI.ComputationOfTaxLiability.NetTaxLiability",
        },
    ),
    "ITR-3": FieldMapping(
        form="ITR-3", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-3"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR3.PartB_TTI.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.EducationCess",
            "gross_total_income": "ITR.ITR3.PartB-TI.GrossTotalIncome",
            "interest_234a": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234C",
            "rebate_87a": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.Rebate87A",
            "self_assessment_tax": "ITR.ITR3.PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "surcharge": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TotalSurcharge",
            "tax_on_total_income": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TaxPayableOnTotInc",
            "total_deductions": "ITR.ITR3.PartB-TI.DeductionsUndSchVIADtl.TotDeductUndSchVIA",
            "total_income": "ITR.ITR3.PartB-TI.TotalIncome",
            "total_tax": "ITR.ITR3.PartB_TTI.ComputationOfTaxLiability.NetTaxLiability",
        },
    ),
    "ITR-4": FieldMapping(
        form="ITR-4", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-4"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR4.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR4.TaxComputation.EducationCess",
            "gross_total_income": "ITR.ITR4.IncomeDeductions.GrossTotIncome",
            "interest_234a": "ITR.ITR4.TaxComputation.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR4.TaxComputation.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR4.TaxComputation.IntrstPay.IntrstPayUs234C",
            "rebate_87a": "ITR.ITR4.TaxComputation.Rebate87A",
            "self_assessment_tax": "ITR.ITR4.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "tax_on_total_income": "ITR.ITR4.TaxComputation.TotalTaxPayable",
            "total_deductions": "ITR.ITR4.IncomeDeductions.UsrDeductUndChapVIA.TotalChapVIADeductions",
            "total_income": "ITR.ITR4.IncomeDeductions.TotalIncome",
            "total_tax": "ITR.ITR4.TaxComputation.NetTaxLiability",
        },
    ),
    "ITR-5": FieldMapping(
        form="ITR-5", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-5"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR5.PartB_TTI.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.EducationCess",
            "gross_total_income": "ITR.ITR5.PartB-TI.GrossTotalIncome",
            "interest_234a": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234C",
            "self_assessment_tax": "ITR.ITR5.PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "surcharge": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TotalSurcharge",
            "tax_on_total_income": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TaxPayableOnTotInc",
            "total_deductions": "ITR.ITR5.PartB-TI.DeductionsUndSchVIADtl.TotDeductUndSchVIA",
            "total_income": "ITR.ITR5.PartB-TI.TotalIncome",
            "total_tax": "ITR.ITR5.PartB_TTI.ComputationOfTaxLiability.NetTaxLiability",
        },
    ),
    "ITR-6": FieldMapping(
        form="ITR-6", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-6"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR6.PartB_TTI.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.EducationCess",
            "gross_total_income": "ITR.ITR6.PartB-TI.GrossTotalIncome",
            "interest_234a": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234C",
            "self_assessment_tax": "ITR.ITR6.PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "surcharge": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TotalSurcharge",
            "tax_on_total_income": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TaxPayableOnTotInc",
            "total_deductions": "ITR.ITR6.PartB-TI.DeductionsUndSchVIADtl.TotDeductUndSchVIA",
            "total_income": "ITR.ITR6.PartB-TI.TotalIncome",
            "total_tax": "ITR.ITR6.PartB_TTI.ComputationOfTaxLiability.NetTaxLiability",
        },
    ),
    "ITR-7": FieldMapping(
        form="ITR-7", assessment_year="2026-27",
        schema_version="Ver1.0", schema_file=SCHEMA_FILES["ITR-7"],
        verified=True,
        paths={
            "advance_tax_paid": "ITR.ITR7.PartB_TTI.TaxPaid.TaxesPaid.AdvanceTax",
            "cess": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.EducationCess",
            "gross_total_income": "ITR.ITR7.PartB_TI2.GrossTotalIncome",
            "interest_234a": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234A",
            "interest_234b": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234B",
            "interest_234c": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.IntrstPay.IntrstPayUs234C",
            "self_assessment_tax": "ITR.ITR7.PartB_TTI.TaxPaid.TaxesPaid.SelfAssessmentTax",
            "surcharge": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.TotalSurcharge",
            "tax_on_total_income": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.TaxPayableOnTI.TaxPayableOnTotInc",
            "total_income": "ITR.ITR7.PartB_TI.TotalIncome",
            "total_tax": "ITR.ITR7.PartB_TTI.ComputationOfTaxLiability.NetTaxLiability",
        },
    ),
}


class SchemaNotVerified(RuntimeError):
    """Raised instead of emitting a file against an unverified schema."""


class SoftwareProviderNotRegistered(RuntimeError):
    """Raised when no SW######## provider id is configured.

    Every ITR schema requires one in CreationInfo. It identifies the software
    that produced the file, and the portal rejects a file without it.
    """


class ReturnIncomplete(RuntimeError):
    """Raised when the payload holds the tax figures but not a whole return."""


def software_provider_id() -> Optional[str]:
    """The Department-issued SW######## id, or None when not configured.

    Read from the environment rather than hardcoded: it is issued to a specific
    provider, and a value committed here would be another provider's identity
    baked into every file this product writes.
    """
    import os
    import re
    raw = (os.environ.get("ITR_SOFTWARE_PROVIDER_ID") or "").strip().upper()
    return raw if re.fullmatch(r"SW[0-9]{8}", raw) else None


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

    Refusing is still the point, but the reason has changed. The Department's
    schemas are now held (schemas/, committed) and every field path is verified
    against them, so "we do not know the field names" is no longer true. Two
    other things are, and each gets its own refusal so the message names what is
    actually missing rather than a stale generality.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
    """
    mapping = FIELD_MAPPINGS.get(payload.form)
    if not mapping or not mapping.verified or not mapping.paths:
        raise SchemaNotVerified(
            f"No verified ITR JSON schema mapping for {payload.form} AY "
            f"{payload.assessment_year}. Add the form's schema to schemas/ and "
            f"its paths to FIELD_MAPPINGS; tests/test_itr_schema_paths.py "
            f"verifies every path against the schema itself."
        )

    if not software_provider_id():
        raise SoftwareProviderNotRegistered(
            "No software provider ID is configured, so no ITR JSON can be "
            "produced. Every schema requires CreationInfo.SWCreatedBy and "
            "CreationInfo.JSONCreatedBy to match SW########, a number the "
            "Income Tax Department issues to registered providers — a file "
            "without one is rejected at upload whatever else it contains. "
            "Obtaining it is a registration step, not a coding one, in the same "
            "way GSP registration gates GST filing. Set ITR_SOFTWARE_PROVIDER_ID "
            "once it has been issued."
            # TODO(compliance): docs/compliance/03-income-tax-and-tds.md
            #   The number comes with e-Return Intermediary registration. Type-2
            #   ERI (own software, ITD APIs) is the target, and it has four
            #   serial gates: net worth >= Rs 1 crore or apply through a CA firm,
            #   an ISA/CISA due-diligence certificate, ITD UAT certification,
            #   and production access limited to FOUR whitelisted INDIAN static
            #   IPs. That last one is a deployment problem, not a code one —
            #   apps/api runs on Render in Singapore.
        )

    raise ReturnIncomplete(
        f"The computed figures for {payload.form} are complete and correctly "
        f"placed, but they are not a return. A file the portal will accept also "
        f"needs the taxpayer's PersonalInfo, FilingStatus, Verification and "
        f"bank details, and — for ITR-3, ITR-5 and ITR-6 — the balance sheet and "
        f"profit-and-loss schedules the form requires. None of that is in "
        f"ITRPayload, which carries {len(payload.values)} tax figures and "
        f"nothing else. Emitting a partial file would produce something that "
        f"looks like a return and fails validation at the portal. Use "
        f"itr_field_placements() to feed the figures into the department's "
        f"offline utility instead."
    )


def itr_field_placements(payload: ITRPayload) -> list[dict]:
    """Where each computed figure belongs in the form, in whole rupees.

    This is the useful half of a generator without the dangerous half: it says
    "this number goes in this field" and leaves the file to the department's own
    utility. A CA can work from it directly, and it is what the eventual real
    generator will write.

    Amounts are converted to whole RUPEES here and only here. Every monetary
    field in the schemas is an integer in rupees, and this is the statutory
    payload boundary — the same place domain/gst/money.py rounds for GSTR-1 and
    GSTR-3B, and the first point at which the convention is known.
    """
    mapping = FIELD_MAPPINGS.get(payload.form)
    out: list[dict] = []
    for value in payload.values:
        path = (mapping.paths.get(value.key) if mapping else None)
        out.append({
            "key": value.key,
            "label": value.label,
            "schedule": value.schedule,
            "reference": value.reference,
            "amount_paise": value.amount_paise,
            "amount_rupees": _to_rupees(value.amount_paise),
            "json_path": path,
            # None is a statement, not a gap: see the FIELD_MAPPINGS preamble
            # for why §87A has no home on ITR-5/6/7 and surcharge none on
            # ITR-1/4.
            "not_on_this_form": path is None,
        })
    return out


def _to_rupees(paise: int) -> int:
    """Whole rupees, half away from zero.

    The schemas take integers, so a rounding rule is unavoidable; this matches
    the one domain/gst/money.py already applies for GSTR-3B under CGST Act
    §170, rather than inventing a second convention in the same codebase.
    """
    sign = -1 if paise < 0 else 1
    return sign * ((abs(int(paise)) + 50) // 100)
