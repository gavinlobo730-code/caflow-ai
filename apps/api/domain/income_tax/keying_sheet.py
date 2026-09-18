"""The keying sheet — every computed figure, and the box it goes in (IT-17).

WHAT WAS WRONG

    `itr_json.itr_field_placements` has said "this number goes in this field"
    since IT-17's first half, checked against the Department's own committed
    schemas. `POST /api/income-tax/itr/field-placements` exposed it — and a
    grep across `apps/web` returned NOTHING, so no screen reached it and a CA
    transcribing a return into the Department's offline utility was still doing
    it from memory. The same `capital_wip` / `fx_revaluation_service` /
    §115BAC(6) shape this repository keeps finding: built, tested, reachable
    from nowhere.

    And the answer covered the fourteen TAX-COMPUTATION totals alone. The
    figures the product computes head by head — salary after §16, each capital
    head after the brought-forward loss it absorbed, the Chapter VI-A sections
    IT-32 built — had no field mapping at all, which is most of Part B-TI and
    all of Schedule VI-A.

WHAT THIS MODULE IS FOR

    It turns a computation into the two dicts `build_itr_payload` now takes.
    It DERIVES NOTHING: every figure here was computed by `itr_engine`, and the
    module's whole job is to say which computed figure answers which payload
    key. A derivation here would be a second income-tax engine, reachable from
    a screen, agreeing with the first until it did not.

WHY IT READS THE SNAPSHOT'S `computation_json` AND NOT THE COLUMNS

    `tax_computation_snapshots` carries `gross_salary_paise`,
    `business_income_paise` and `other_income_paise` as columns, and every one
    of them is an INPUT. The form asks for income CHARGEABLE UNDER THE HEAD:
    salary after the §16(ia) standard deduction, business after the
    disallowances added back and the presumptive substitution, each capital
    head after the brought-forward loss §72/§74 let it absorb. Keying the
    inputs would put pre-relief figures under a heading that means something
    else — and the figures are only a few thousand rupees apart, which is the
    kind of wrong that survives a review.

    So the heads come off `income_heads_paise`, which the engine records at the
    point it computes gross total income, and which the compute endpoint now
    serves.

THE SHEET IS BUILT OVER A FILING'S PINNED SNAPSHOT

    `itr_filings.computation_snapshot_id` is what IT-30 made reachable, and it
    is the right source precisely because it is pinned: what a CA keys is then
    the computation that was reviewed, not whatever the screen last recomputed.
    A filing that pins NOTHING is allowed (the column is nullable, and a CA who
    computed outside the product has no snapshot) — that is REFUSED with a
    sentence naming the pin, not answered with an empty sheet.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from typing import Any, Optional

from domain.income_tax.itr_json import (
    CHAPTER_VI_A_KEYS, INCOME_HEAD_KEYS, build_itr_payload,
    itr_field_placements)

#: A filing with no pinned snapshot has no computation to key. Refused rather
#: than answered with zeros: a sheet of zeros reads as a computed return.
NO_SNAPSHOT_PINNED = (
    "This filing pins no computation snapshot, so there is nothing to key. "
    "Compute the return on the Tax Computation tab and pin the snapshot to the "
    "filing first."
)
NO_COMPUTATION_STORED = (
    "The pinned snapshot holds no stored computation, so the figures cannot be "
    "read back. Recompute on the Tax Computation tab — the snapshot it saves "
    "carries the whole working."
)

#: WHICH COMPUTED FIGURE ANSWERS WHICH SCHEDULE VI-A BOX.
#:
#: The five on the left are the engine's own long-standing per-section totals;
#: everything else comes off `chapter_vi_a_lines`, which IT-32 added and which
#: carries one entry per section with what limited it.
#:
#: §80CCD(2) — the EMPLOYER's contribution — is deliberately absent. It has its
#: own box (`Section80CCDEmployer`) and its own sub-section, it survives
#: §115BAC(2) where §80CCD(1B) does not, and folding the two would key one
#: figure into the other's field.
_VIA_FROM_RESULT: dict[str, str] = {
    "deduction_80c": "s80c_paise",
    "deduction_80ccd1b": "s80ccd_paise",
    "deduction_80d": "s80d_paise",
    "deduction_80g": "s80g_paise",
    "deduction_80tta": "s80tta_paise",
}

#: `chapter_vi_a_lines[].section` -> payload key. The section labels are the
#: module's own (`chapter_vi_a.compute` sets them), so this is a rename and not
#: a parse: a section it does not know is IGNORED rather than guessed into a
#: neighbouring box, and `unplaced_sections` names it.
_VIA_FROM_LINES: dict[str, str] = {
    "80E": "deduction_80e",
    "80EE": "deduction_80ee",
    "80EEA": "deduction_80eea",
    "80DD": "deduction_80dd",
    "80DDB": "deduction_80ddb",
    "80U": "deduction_80u",
    "80GG": "deduction_80gg",
}


def chapter_vi_a_from_computation(computation: dict) -> tuple[dict, list]:
    """The Schedule VI-A figures, by payload key, plus what could not be placed.

    A section with a computed ZERO is still placed: the form has a box for it
    and a nil in a box a CA looked at is a different statement from a box left
    blank. A section this module does not know is NOT placed and is named — the
    `table_4a_gaps` discipline, because a figure keyed into the wrong box is
    worse than a figure keyed by hand.
    """
    deductions = (computation or {}).get("deductions") or {}
    out: dict[str, int] = {}
    for key, source in _VIA_FROM_RESULT.items():
        value = deductions.get(source)
        if isinstance(value, int):
            out[key] = value
    unplaced: list[str] = []
    for line in (deductions.get("chapter_vi_a_lines") or []):
        section = str((line or {}).get("section") or "").strip().upper()
        key = _VIA_FROM_LINES.get(section)
        if key is None:
            if section:
                unplaced.append(section)
            continue
        out[key] = int((line or {}).get("allowed_paise") or 0)
    return out, sorted(set(unplaced))


def income_heads_from_computation(computation: dict) -> dict:
    """The Part B-TI heads, by payload key.

    Read off what the engine recorded, never re-derived. A key the computation
    does not carry is OMITTED rather than sent as zero — `build_itr_payload`
    leaves an omitted head off the sheet entirely, which is the honest answer
    where nobody holds the figure and is quite different from an instruction to
    key nil.
    """
    heads = (computation or {}).get("income_heads") or {}
    return {k: int(heads[k]) for k in INCOME_HEAD_KEYS
            if isinstance(heads.get(k), int)}


#: What the sheet cannot fill in, said once so three places quote one sentence.
INTEREST_IS_NOT_ON_THE_COMPUTATION = (
    "§234A, §234B and §234C are nil on this sheet — the computation does not "
    "carry them. They are computed on the Advance Tax screen, which asks the "
    "four facts the return itself cannot supply (the §139(1) due date, the "
    "date the return was furnished, the TDS credit and any §89/90/91 relief), "
    "and are keyed from there."
)
SELF_ASSESSMENT_TAX_HAS_NO_SOURCE = (
    "§140A self-assessment tax is nil on this sheet — no Challan 280 is "
    "recorded for this client and year. Record it on the Advance Tax screen "
    "(IT-13) and the figure lands here; until then it is keyed from the "
    "challan itself."
)
#: Where the figure DID come from. Said on the sheet rather than left to look
#: computed: §140A tax is the one total here that is not a derivation from the
#: return at all — it is a payment somebody made at a bank, and a CA checking
#: the sheet against Schedule IT needs to know it is the challans' own total
#: rather than a balancing figure.
SELF_ASSESSMENT_TAX_IS_THE_CHALLANS = (
    "§140A self-assessment tax on this sheet is the total of the {count} "
    "Challan 280 record(s) held for this client and year. Schedule IT declares "
    "each one separately with its own BSR code, date and serial number — this "
    "is their sum, not a row."
)


def tax_figures_from_computation(
    computation: dict,
    snapshot: dict,
    self_assessment_tax_paise: int = 0,
) -> dict:
    """The tax-computation totals, as `build_itr_payload` names them.

    The rename lives here, in one place, so the router and the screen hold none
    of it — and TWO of the fourteen come off the SNAPSHOT rather than the
    computation, which is not an inconsistency: `tds_deducted_paise` and
    `advance_tax_paid_paise` are what the CA told the computation, and the
    compute response reports only their SUM (`tds_and_advance_paise`), which the
    form keeps in two different schedules.

    `tax_on_total_income` is `tax_before_cess_paise`, which excludes BOTH
    surcharge and cess — the schema's `TaxPayableOnTotInc` is the same figure,
    and the two travel in their own boxes beside it.
    """
    c = computation or {}
    snap = snapshot or {}
    income = c.get("income") or {}
    tax = c.get("tax") or {}
    return {
        "gross_total_income_paise": int(income.get("gross_total_paise") or 0),
        "total_deductions_paise": int(income.get("total_deductions_paise") or 0),
        "total_income_paise": int(income.get("taxable_income_paise") or 0),
        "tax_on_total_income_paise": int(tax.get("tax_before_cess_paise") or 0),
        "rebate_87a_paise": int(tax.get("rebate_87a_paise") or 0),
        "surcharge_paise": int(tax.get("surcharge_paise") or 0),
        "cess_paise": int(tax.get("cess_paise") or 0),
        "total_tax_paise": int(tax.get("total_tax_paise") or 0),
        "tds_tcs_paise": int(snap.get("tds_deducted_paise") or 0),
        "advance_tax_paid_paise": int(snap.get("advance_tax_paid_paise") or 0),
        # Both nil, and both SAID rather than left to look computed — see the
        # two sentences above. A zero a CA has been told about is a box to fill
        # in; a zero they have not is a figure they will file.
        # PASSED IN, never read here. `services/self_assessment_service` totals
        # the challans; this module derives nothing and a test walks its AST to
        # keep it that way. A caller that holds no challans passes nothing and
        # gets the nil the gap above explains.
        "self_assessment_tax_paise": int(self_assessment_tax_paise or 0),
        "interest_234a_paise": 0,
        "interest_234b_paise": 0,
        "interest_234c_paise": 0,
    }


def keying_sheet(
    *,
    form: str,
    assessment_year: str,
    computation: Optional[dict],
    snapshot: Optional[dict] = None,
    self_assessment_tax_paise: int = 0,
    self_assessment_challan_count: int = 0,
) -> dict[str, Any]:
    """The whole sheet: every figure, its box, and what has no box.

    `gaps` is the honest half. A head the computation does not carry is simply
    absent from the sheet; a section this module could not place is NAMED; and
    where the schema has no field the placement itself says which of the two
    reasons applies — the form has no such box, or nobody has mapped it.
    """
    gaps: list[str] = []
    if not computation:
        return {
            "form": form, "assessment_year": assessment_year,
            "placements": [], "schema_is_verified": False,
            "notes": [], "gaps": [NO_COMPUTATION_STORED],
        }

    via, unplaced = chapter_vi_a_from_computation(computation)
    if unplaced:
        gaps.append(
            "No Schedule VI-A box is mapped for "
            + ", ".join(f"§{s}" for s in unplaced)
            + ". The figures are on the computation and have to be keyed by "
              "hand.")
    heads = income_heads_from_computation(computation)
    missing_heads = [k for k in INCOME_HEAD_KEYS if k not in heads]
    if missing_heads:
        gaps.append(
            "This computation records no figure for "
            + ", ".join(k.replace("_", " ") for k in missing_heads)
            + ", so those lines are not on the sheet. A firm, LLP or company "
              "is taxed on one figure and has no heads at all, which is the "
              "usual reason.")

    gaps.append(INTEREST_IS_NOT_ON_THE_COMPUTATION)
    # TWO SENTENCES, NOT ONE WITH A ZERO IN IT. "Nothing records a challan" and
    # "this is the total of the challans that are recorded" are different facts
    # and send a CA to different places; the count is what tells them apart,
    # never the amount — a challan recorded for nil is still a challan, and a
    # sheet reading "no challan is recorded" over a record somebody entered is
    # the kind of wrong that survives a review.
    if self_assessment_challan_count:
        gaps.append(SELF_ASSESSMENT_TAX_IS_THE_CHALLANS.format(
            count=self_assessment_challan_count))
    else:
        gaps.append(SELF_ASSESSMENT_TAX_HAS_NO_SOURCE)

    payload = build_itr_payload(
        form=form, assessment_year=assessment_year,
        income_heads_paise=heads, chapter_vi_a_paise=via,
        **tax_figures_from_computation(
            computation, snapshot or {},
            self_assessment_tax_paise=self_assessment_tax_paise))
    placements = itr_field_placements(payload)
    unmapped = [p["label"] for p in placements if p["not_mapped"]]
    if unmapped:
        gaps.append(
            "No field path is mapped on this form for "
            + ", ".join(unmapped)
            + ". That is work outstanding here, NOT a statement that the form "
              "has no box — find the field in the Department's utility and key "
              "it by hand.")
    return {
        "form": payload.form,
        "assessment_year": payload.assessment_year,
        "placements": placements,
        "schema_is_verified": payload.schema_is_verified,
        "notes": list(payload.notes),
        "gaps": gaps,
    }
