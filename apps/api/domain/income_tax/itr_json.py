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

  THE PAYLOAD IS NOT A WHOLE RETURN. It carries the tax-computation totals, the
  Part B-TI income heads and the Chapter VI-A sections (IT-17). A file the
  portal accepts also needs PersonalInfo, FilingStatus, Verification, bank
  details, the per-transaction interiors of Schedule CG, HP and BP, and for
  ITR-3/5/6 the balance sheet and profit-and-loss schedules. Emitting the
  fragment would produce something that looks like a return and fails at
  upload.

Refusing on a named, specific ground beats refusing vaguely, and both beat
emitting a file that looks finished. This is the discipline the rest of the
package uses: statutory_rates marks an unconfirmed year rather than guessing,
services/filing_demo transmits nothing and says SIM-NOT-FILED, domain/udin
validates a number a CA obtained rather than minting one.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, get_args

from domain.income_tax.itr_schema import SCHEMA_FILES

ITRForm = Literal["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"]

#: The same seven as a tuple, DERIVED from the Literal rather than restated —
#: a second list is a second thing to keep in step, which is exactly how the
#: filing screen came to offer four (IT-23) while this module held field
#: mappings and a committed JSON schema for all seven. Every place that needs
#: to VALIDATE or OFFER a form reads this.
ITR_FORMS: tuple[str, ...] = get_args(ITRForm)


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


#: WHAT A CA KEYS INTO PART B-TI, HEAD BY HEAD (IT-17).
#:
#: The payload used to carry the fourteen TAX-COMPUTATION totals and stop, so
#: the figures this product computes head by head — salary, house property,
#: business, each capital-gains bucket, other sources and the brought-forward
#: set-off — had no field mapping at all and a CA transcribing into the
#: Department's utility had to find them by eye.
#:
#: Each is a TOTAL that Part B-TI itself carries. The per-transaction interiors
#: of Schedule CG, HP and BP are deliberately NOT mapped: those need a row per
#: asset, per property and per business, which this payload does not hold, and
#: an aggregate written into a row field is exactly the "right value, wrong
#: field" failure this module exists to refuse.
INCOME_HEAD_KEYS: tuple[str, ...] = (
    "salary", "house_property", "business_income",
    "capital_gains_short_term", "capital_gains_long_term",
    "capital_gains_total", "other_sources", "brought_forward_set_off",
)

#: THE CHAPTER VI-A SECTIONS, EACH IN ITS OWN BOX (IT-17 with IT-32).
#:
#: `total_deductions` was the only deduction figure mapped, and the form does
#: not take a total alone: Schedule VI-A has a line per section and the total is
#: their sum. IT-32 made the product compute them section by section, which is
#: what makes these mappable at all.
CHAPTER_VI_A_KEYS: tuple[str, ...] = (
    "deduction_80c", "deduction_80ccd1b", "deduction_80d", "deduction_80dd",
    "deduction_80ddb", "deduction_80e", "deduction_80ee", "deduction_80eea",
    "deduction_80g", "deduction_80gg", "deduction_80tta", "deduction_80u",
)

#: The label and the statutory reference for each head, in FORM order.
_INCOME_HEAD_LINES: tuple[tuple[str, str, str], ...] = (
    ("salary", "Income from Salary", "IT Act §15"),
    ("house_property", "Income from House Property", "IT Act §22"),
    ("business_income", "Profits and Gains of Business or Profession",
     "IT Act §28"),
    ("capital_gains_short_term", "Short-term Capital Gains", "IT Act §45"),
    ("capital_gains_long_term", "Long-term Capital Gains", "IT Act §45"),
    ("capital_gains_total", "Total Capital Gains", "IT Act §45"),
    ("other_sources", "Income from Other Sources", "IT Act §56"),
    # Not a HEAD but a Part B-TI line, and it sits with them because that is
    # where the form puts it — between the heads and gross total income.
    ("brought_forward_set_off", "Brought-forward losses set off",
     "IT Act §72 / §73 / §73A / §74 / §71B"),
)

#: The same for the Chapter VI-A sections, in the schema's own order.
_CHAPTER_VI_A_LINES: tuple[tuple[str, str, str], ...] = (
    ("deduction_80c", "Section 80C", "IT Act §80C"),
    ("deduction_80ccd1b", "Section 80CCD(1B) — NPS", "IT Act §80CCD(1B)"),
    ("deduction_80d", "Section 80D — health insurance", "IT Act §80D"),
    ("deduction_80dd", "Section 80DD — disabled dependant", "IT Act §80DD"),
    ("deduction_80ddb", "Section 80DDB — specified disease", "IT Act §80DDB"),
    ("deduction_80e", "Section 80E — education loan interest", "IT Act §80E"),
    ("deduction_80ee", "Section 80EE — housing loan interest", "IT Act §80EE"),
    ("deduction_80eea", "Section 80EEA — housing loan interest",
     "IT Act §80EEA"),
    ("deduction_80g", "Section 80G — donations", "IT Act §80G"),
    ("deduction_80gg", "Section 80GG — rent paid", "IT Act §80GG"),
    ("deduction_80tta", "Section 80TTA / 80TTB — interest",
     "IT Act §80TTA / §80TTB"),
    ("deduction_80u", "Section 80U — the assessee's disability", "IT Act §80U"),
)

#: "THE FORM HAS NO SUCH FIELD" AND "NOBODY HAS MAPPED IT" ARE DIFFERENT
#: ANSWERS, AND UNTIL IT-17 THEY WERE ONE.
#:
#: `itr_field_placements` reported `not_on_this_form: true` for any key with no
#: path, which was safe while the only two absences were real — §87A has no home
#: on ITR-5/6/7 and surcharge none on ITR-1/4. With twenty more keys it stops
#: being safe: an unmapped key would tell a CA the form has no box for their
#: house-property income, and they would leave it blank.
#:
#: So a deliberate absence is DECLARED, with the sentence saying why, and
#: anything else comes back as `not_mapped` — which a screen renders as work to
#: do rather than as an answer. `tests/test_itr_schema_paths.py` asserts every
#: key on every form is in exactly one of the three states, so a key added later
#: cannot silently read as an absence.
ABSENCE_REASONS: dict[str, dict[str, str]] = {}


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


# ── The head-wise and section-wise paths (IT-17) ─────────────────────────────
#
# Declared here rather than inside each FieldMapping literal above, and merged
# in below. Twenty keys across seven forms is 140 lines the tax-figure literals
# would have to carry, and the interesting fact about these is the SHAPE of the
# per-form absences — a firm has no salary head, ITR-1 and ITR-4 carry no
# capital-gains head at all — which a table shows and seven scattered dicts do
# not. Every path was resolved against the committed schema before being
# written, and tests/test_itr_schema_paths.py re-resolves all of them on every
# run, so this is no less checked than the literals above.
#
# ITR-7's Part B-TI is spelled `PartB_TI` with an UNDERSCORE where every other
# form uses `PartB-TI` with a hyphen. That is the Department's own schema, not a
# typo here, and it is why these are written out rather than composed from a
# per-form prefix.
_HEAD_PATHS: dict[str, dict[str, str]] = {
    "ITR-1": {
        "salary": "ITR.ITR1.ITR1_IncomeDeductions.IncomeFromSal",
        "house_property": "ITR.ITR1.ITR1_IncomeDeductions.TotalIncomeChargeableUnHP",
        "other_sources": "ITR.ITR1.ITR1_IncomeDeductions.IncomeOthSrc",
    },
    "ITR-2": {
        "salary": "ITR.ITR2.PartB-TI.Salaries",
        "house_property": "ITR.ITR2.PartB-TI.IncomeFromHP",
        "capital_gains_short_term": "ITR.ITR2.PartB-TI.CapGain.ShortTerm.TotalShortTerm",
        "capital_gains_long_term": "ITR.ITR2.PartB-TI.CapGain.LongTerm.TotalLongTerm",
        "capital_gains_total": "ITR.ITR2.PartB-TI.CapGain.TotalCapGains",
        "other_sources": "ITR.ITR2.PartB-TI.IncFromOS.TotIncFromOS",
        "brought_forward_set_off": "ITR.ITR2.PartB-TI.BroughtFwdLossesSetoff",
    },
    "ITR-3": {
        "salary": "ITR.ITR3.PartB-TI.Salaries",
        "house_property": "ITR.ITR3.PartB-TI.IncomeFromHP",
        "business_income": "ITR.ITR3.PartB-TI.ProfBusGain.TotProfBusGain",
        "capital_gains_short_term": "ITR.ITR3.PartB-TI.CapGain.ShortTerm.TotalShortTerm",
        "capital_gains_long_term": "ITR.ITR3.PartB-TI.CapGain.LongTerm.TotalLongTerm",
        "capital_gains_total": "ITR.ITR3.PartB-TI.CapGain.TotalCapGains",
        "other_sources": "ITR.ITR3.PartB-TI.IncFromOS.TotIncFromOS",
        "brought_forward_set_off": "ITR.ITR3.PartB-TI.BroughtFwdLossesSetoff",
    },
    "ITR-4": {
        "salary": "ITR.ITR4.IncomeDeductions.IncomeFromSal",
        "house_property": "ITR.ITR4.IncomeDeductions.TotalIncomeChargeableUnHP",
        "business_income": "ITR.ITR4.IncomeDeductions.IncomeFromBusinessProf",
        "other_sources": "ITR.ITR4.IncomeDeductions.IncomeOthSrc",
    },
    "ITR-5": {
        "house_property": "ITR.ITR5.PartB-TI.IncomeFromHP",
        "business_income": "ITR.ITR5.PartB-TI.ProfBusGain.TotProfBusGain",
        "capital_gains_short_term": "ITR.ITR5.PartB-TI.CapGain.ShortTerm.TotalShortTerm",
        "capital_gains_long_term": "ITR.ITR5.PartB-TI.CapGain.LongTerm.TotalLongTerm",
        "capital_gains_total": "ITR.ITR5.PartB-TI.CapGain.TotalCapGains",
        "other_sources": "ITR.ITR5.PartB-TI.IncFromOS.TotIncFromOS",
        "brought_forward_set_off": "ITR.ITR5.PartB-TI.BroughtFwdLossesSetoff",
    },
    "ITR-6": {
        "house_property": "ITR.ITR6.PartB-TI.IncomeFromHP",
        "business_income": "ITR.ITR6.PartB-TI.ProfBusGain.TotProfBusGain",
        "capital_gains_short_term": "ITR.ITR6.PartB-TI.CapGain.ShortTerm.TotalShortTerm",
        "capital_gains_long_term": "ITR.ITR6.PartB-TI.CapGain.LongTerm.TotalLongTerm",
        "capital_gains_total": "ITR.ITR6.PartB-TI.CapGain.TotalCapGains",
        "other_sources": "ITR.ITR6.PartB-TI.IncFromOS.TotIncFromOS",
        "brought_forward_set_off": "ITR.ITR6.PartB-TI.BroughtFwdLossesSetoff",
    },
    "ITR-7": {
        "house_property": "ITR.ITR7.PartB_TI.IncomeFromHP",
        "business_income": "ITR.ITR7.PartB_TI.ProfBusGain.ProfGainNoSpecBus",
        "capital_gains_short_term": "ITR.ITR7.PartB_TI.CapGain.ShortTerm.TotalShortTerm",
        "capital_gains_long_term": "ITR.ITR7.PartB_TI.CapGain.LongTerm.TotalLongTerm",
        "capital_gains_total": "ITR.ITR7.PartB_TI.CapGain.TotalCapGains",
        "other_sources": "ITR.ITR7.PartB_TI.IncFromOS.TotIncFromOS",
    },
}

# Schedule VI-A lives in a different place on the two simple forms: ITR-1 and
# ITR-4 fold it into IncomeDeductions, the rest give it a schedule of its own.
#
# `UsrDeductUndChapVIA` is the USER-ENTERED figure and `DeductUndChapVIA`, which
# sits beside it on ITR-1 and ITR-4, is what the utility computes after applying
# the caps. The user-entered one is what a CA keys, and it is the one mapped —
# the other is an output.
_VIA_ROOTS: dict[str, str] = {
    "ITR-1": "ITR.ITR1.ITR1_IncomeDeductions.UsrDeductUndChapVIA",
    "ITR-2": "ITR.ITR2.ScheduleVIA.UsrDeductUndChapVIA",
    "ITR-3": "ITR.ITR3.ScheduleVIA.UsrDeductUndChapVIA",
    "ITR-4": "ITR.ITR4.IncomeDeductions.UsrDeductUndChapVIA",
    "ITR-5": "ITR.ITR5.ScheduleVIA.UsrDeductUndChapVIA",
    "ITR-6": "ITR.ITR6.ScheduleVIA.UsrDeductUndChapVIA",
}

#: payload key -> the schema's own field name under the VI-A root.
_VIA_FIELDS: dict[str, str] = {
    "deduction_80c": "Section80C",
    "deduction_80ccd1b": "Section80CCD1B",
    "deduction_80d": "Section80D",
    "deduction_80dd": "Section80DD",
    "deduction_80ddb": "Section80DDB",
    "deduction_80e": "Section80E",
    "deduction_80ee": "Section80EE",
    "deduction_80eea": "Section80EEA",
    "deduction_80g": "Section80G",
    "deduction_80gg": "Section80GG",
    "deduction_80tta": "Section80TTA",
    "deduction_80u": "Section80U",
}

#: Which VI-A sections each form actually carries. ITR-5 and ITR-6 carry §80G
#: ALONE, which is not an omission in the schema: every other section in the
#: list reaches only an individual or a HUF, and a firm or a company claiming
#: §80DD would be claiming a deduction the Act does not give it. ITR-7 has no
#: Schedule VI-A at all — a §11/§12 trust computes its income under a different
#: régime entirely.
_VIA_PER_FORM: dict[str, tuple[str, ...]] = {
    "ITR-1": tuple(_VIA_FIELDS), "ITR-2": tuple(_VIA_FIELDS),
    "ITR-3": tuple(_VIA_FIELDS), "ITR-4": tuple(_VIA_FIELDS),
    "ITR-5": ("deduction_80g",), "ITR-6": ("deduction_80g",),
    "ITR-7": (),
}

_NO_SALARY_HEAD = (
    "This form has no salary head. A firm, LLP, company or trust is not an "
    "employee, so §15 cannot reach it and the schema carries no field."
)
_NO_CAPITAL_GAINS_HEAD = (
    "This form has no capital-gains head. ITR-1 and ITR-4 may not be used where "
    "there is a capital gain at all (beyond §112A long-term gains within the "
    "exemption, which go in Schedule 112A) — a client with one files ITR-2 or "
    "ITR-3."
)
_NO_BROUGHT_FORWARD_HEAD = (
    "This form has no brought-forward loss set-off head. ITR-1 and ITR-4 may "
    "not be used where a loss is carried forward or brought forward; ITR-7's "
    "Part B-TI computes a §11/§12 trust's income on a different basis."
)
_NO_BUSINESS_HEAD = (
    "This form has no business or profession head — ITR-1 and ITR-2 may not be "
    "used where there is one."
)
_VIA_IS_FOR_AN_INDIVIDUAL = (
    "This section reaches only an individual or a HUF, so the form a firm, LLP "
    "or company files carries no field for it."
)
_NO_SCHEDULE_VIA = (
    "This form has no Schedule VI-A. A trust or institution assessed under §11 "
    "and §12 computes its income on a different basis."
)


def _absences_for(form: str) -> dict[str, str]:
    """The keys this FORM genuinely has no field for, each with its reason.

    Everything NOT in here and not mapped comes back as `not_mapped`, which is
    a different answer and is rendered differently: see ABSENCE_REASONS.
    """
    out: dict[str, str] = {}
    heads = _HEAD_PATHS.get(form, {})
    if "salary" not in heads:
        out["salary"] = _NO_SALARY_HEAD
    if "business_income" not in heads:
        out["business_income"] = _NO_BUSINESS_HEAD
    for key in ("capital_gains_short_term", "capital_gains_long_term",
                "capital_gains_total"):
        if key not in heads:
            out[key] = _NO_CAPITAL_GAINS_HEAD
    if "brought_forward_set_off" not in heads:
        out["brought_forward_set_off"] = _NO_BROUGHT_FORWARD_HEAD
    carried = set(_VIA_PER_FORM.get(form, ()))
    for key in _VIA_FIELDS:
        if key not in carried:
            out[key] = (_NO_SCHEDULE_VIA if form == "ITR-7"
                        else _VIA_IS_FOR_AN_INDIVIDUAL)
    return out


# §87A and surcharge were the only two absences before IT-17, and they were
# recorded in the FIELD_MAPPINGS preamble rather than in data — which was fine
# while a reader could hold both in their head. They join the table now so the
# three-state test below has one place to look.
#
# THE THREE-STATE SPLIT FOUND TWO MORE THE MOMENT IT WAS WRITTEN, and both had
# been reported to a CA as "this form has no such field" — which for the first
# of them is flatly false and is the exact reading that makes somebody leave a
# box blank.
_TDS_AND_TCS_ARE_TWO_BOXES = (
    "This form keeps TDS and TCS in separate boxes — TaxPaid.TaxesPaid.TDS and "
    "TaxPaid.TaxesPaid.TCS — and this figure is their SUM, which no single box "
    "takes. Key the two separately; mapping the combined figure to either one "
    "would over-state it and leave the other nil."
)
_ITR7_HAS_NO_CHAPTER_VI_A = (
    "This form has no Chapter VI-A total. A trust or institution assessed "
    "under §11 and §12 computes its income on a different basis and the schema "
    "carries no Schedule VI-A at all."
)

_TAX_FIGURE_ABSENCES: dict[str, dict[str, str]] = {
    "ITR-1": {"surcharge": "ITR-1 carries no surcharge field."},
    "ITR-4": {"surcharge": "ITR-4 carries no surcharge field."},
    "ITR-5": {"rebate_87a": "§87A is for a resident individual; a firm or LLP "
                            "does not get it and the schema has no field."},
    "ITR-6": {"rebate_87a": "§87A is for a resident individual; a company does "
                            "not get it and the schema has no field."},
    "ITR-7": {"rebate_87a": "§87A is for a resident individual; a trust or "
                            "institution does not get it and the schema has no "
                            "field."},
}

for _form, _mapping in FIELD_MAPPINGS.items():
    _mapping.paths.update(_HEAD_PATHS.get(_form, {}))
    _root = _VIA_ROOTS.get(_form)
    if _root:
        _mapping.paths.update({
            _key: f"{_root}.{_VIA_FIELDS[_key]}"
            for _key in _VIA_PER_FORM.get(_form, ())
        })
    ABSENCE_REASONS[_form] = {
        **_absences_for(_form), **_TAX_FIGURE_ABSENCES.get(_form, {}),
        "tds_tcs": _TDS_AND_TCS_ARE_TWO_BOXES,
    }
ABSENCE_REASONS["ITR-7"]["total_deductions"] = _ITR7_HAS_NO_CHAPTER_VI_A



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
    income_heads_paise: Optional[dict] = None,
    chapter_vi_a_paise: Optional[dict] = None,
) -> ITRPayload:
    """Assemble the figures a return needs.

    Every amount is integer paise, as everywhere else in this package. The
    RUPEE conversion the department's schema requires is deliberately not done
    here: rounding belongs at the payload boundary, and applying it before that
    boundary is known would bake in a convention that may not be the schema's.
    """
    mapping = FIELD_MAPPINGS.get(form)
    verified = bool(mapping and mapping.verified)

    # A KEY THIS MODULE DOES NOT KNOW IS AN ERROR, NOT A SHRUG. These arrive as
    # dicts rather than as twenty more keyword arguments, which means a caller's
    # typo would otherwise be dropped in silence — a head simply missing from
    # the keying sheet, on a return the CA then transcribes believing it
    # complete.
    heads = dict(income_heads_paise or {})
    via = dict(chapter_vi_a_paise or {})
    for supplied, known, what in ((heads, INCOME_HEAD_KEYS, "income head"),
                                  (via, CHAPTER_VI_A_KEYS, "Chapter VI-A")):
        unknown = sorted(set(supplied) - set(known))
        if unknown:
            raise ValueError(
                f"unknown {what} key(s): {', '.join(unknown)}. "
                f"Known: {', '.join(known)}")

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

    # THE HEADS AND THE SECTIONS GO FIRST, because that is the order of the
    # form: Part B-TI is filled head by head, Schedule VI-A section by section,
    # and only then Part B-TTI. A keying sheet a CA works down should walk the
    # form, not this module's own history.
    #
    # A KEY NOT SUPPLIED IS OMITTED, NEVER EMITTED AS ZERO. The fourteen above
    # default to 0 and always appear, which is right for them — every return has
    # a tax figure even when it is nil. A head is different: a zero on a keying
    # sheet is an INSTRUCTION to key zero, and a caller that simply does not
    # hold the house-property figure must not be telling the CA it is nil.
    heads_first = [
        PayloadValue(key, label, heads[key], "Part B-TI", ref)
        for key, label, ref in _INCOME_HEAD_LINES if key in heads
    ] + [
        PayloadValue(key, label, via[key], "Schedule VI-A", ref)
        for key, label, ref in _CHAPTER_VI_A_LINES if key in via
    ]
    values = heads_first + values

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
    absences = ABSENCE_REASONS.get(payload.form, {})
    out: list[dict] = []
    for value in payload.values:
        path = (mapping.paths.get(value.key) if mapping else None)
        reason = absences.get(value.key)
        out.append({
            "key": value.key,
            "label": value.label,
            "schedule": value.schedule,
            "reference": value.reference,
            "amount_paise": value.amount_paise,
            "amount_rupees": _to_rupees(value.amount_paise),
            "json_path": path,
            # THREE STATES, NOT TWO (IT-17). `not_on_this_form` means the form
            # genuinely has no such field and the reason says which rule of the
            # Act puts it out of reach — a firm has no salary head, §87A is for
            # a resident individual. `not_mapped` means nobody has resolved the
            # path, which is work to do and must never be shown to a CA as an
            # absence: they would leave the box blank.
            "not_on_this_form": path is None and reason is not None,
            "absence_reason": reason if path is None else None,
            "not_mapped": path is None and reason is None,
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
