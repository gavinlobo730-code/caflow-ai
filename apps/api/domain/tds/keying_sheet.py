"""The TDS keying sheet — every already-computed figure, grouped the way the
government's own Return Preparation Utility (RPU) groups them (TDS-16).

WHY THIS EXISTS RATHER THAN AN FVU/RPU FILE WRITER

    The natural next step after `tds_26q_from_books` / `tds_27q_from_books` /
    `tds_24q_from_books` compute a quarter's statement is to hand the CA a
    *file* they can run through NSDL/Protean's File Validation Utility (FVU)
    and upload. This module deliberately does NOT do that, and the reason is
    not laziness — it is the same "refuse and name the gap" discipline this
    codebase applies to every other statutory rate or format it cannot verify.

    A dedicated research pass (25-09-2026) tried to reach the primary
    specification — `tinpan.proteantech.in`'s own published "Data
    Structure"/"File Format" documents per form — and could not: this
    environment's egress is blocked broadly enough that even a general web
    search summarizer's own referenced pages (`incometaxindia.gov.in`,
    `docs.oracle.com`, `en.wikipedia.org`) all failed with `EGRESS_BLOCKED`.
    Every fact that pass recovered is therefore `[S]`-graded at best (a search
    engine's summary of somebody else's summary), and it recovered evidence
    that the format is UNDER ACTIVE REVISION for the very filing period this
    product would target first: RPU/FVU version 1.1 (for the renumbered Forms
    138/140/143/144, Tax Year 2026-27) is reported to have REMOVED three
    Challan Detail fields (Surcharge, Education Cess, Penalty/Others) that
    version 1.2, released weeks later, partially reinstated under different
    names. Writing a byte-exact serializer against a format that is
    demonstrably moving under our feet, from sources no better than a search
    summary, is exactly the "low-confidence guess dressed up as a
    specification" this codebase's own house style refuses to ship — a wrong
    field position gets the WHOLE statement rejected by the FVU, which is a
    worse outcome for a CA than an honestly incomplete keying sheet.

    What the same research DID corroborate with reasonable confidence — from
    three independently converging descriptions, and consistent with what
    `domain/tds/challan_mapping.py` and `domain/tds/deductor_26as.py` already
    assumed — is the STRUCTURE: one physical text line per logical record, a
    caret (`^`)-delimited (not comma-separated, not fixed-width) format, with
    a strict hierarchy: File Header, then one Batch Header per statement (the
    deductor's own identity), then one Challan Detail row per deposit, then
    one Deductee Detail row per deductee UNDER its own challan. That hierarchy
    is what this module organises the already-computed figures into — nothing
    about the file's bytes, only the grouping a CA keying into the real RPU
    screens (which follow the very same hierarchy) will need in the same
    order the RPU asks for it.

WHAT THIS MODULE DOES NOT DO

    It derives NOTHING. Every figure here was computed by
    `services.tds_return_service` (which in turn reads posted purchase bills,
    vendor advances or finalised payroll runs — never re-keyed). This module's
    only job is grouping deductee rows under the challan that paid them
    (`bsr_code` + `challan_no` + `challan_date`, already stamped on every
    deductee row by `domain/tds/challan_mapping.py`) and naming what still
    needs a human's own judgement — the FVU "Remarks" reason code for a
    lower/nil deduction, which is a published closed list this product does
    not hold (`tds_computer.py`'s own docstring already refuses to invent one,
    for the same reason).

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from __future__ import annotations

from typing import Any, Optional

RECORD_FILE_HEADER = "File Header (FH)"
RECORD_BATCH_HEADER = "Batch Header (BH) — deductor / responsible person"
RECORD_CHALLAN_DETAIL = "Challan Detail (CD)"
RECORD_DEDUCTEE_DETAIL = "Deductee Detail (DD)"

#: The one sentence that has to be on every sheet this module produces —
#: never buried, because the whole point of this module existing rather than
#: a file writer is that a CA must not mistake this for the government's own
#: upload file.
NO_FVU_FILE_IS_PRODUCED = (
    "This is a keying sheet, not the government's own statement file. Key "
    "these figures into NSDL/Protean's free Return Preparation Utility (RPU) "
    "yourself, in the order below — File Header and Batch Header once, then "
    "one Challan Detail block per deposit with its own Deductee Detail rows "
    "underneath — and validate the RPU's own output through the File "
    "Validation Utility before uploading. The exact field-by-field layout of "
    "the current RPU version is not held here; egress to the primary "
    "specification (tinpan.proteantech.in) is blocked in this environment, "
    "and independent evidence gathered 25-09-2026 shows the Challan Detail "
    "field list itself changed between RPU versions 1.1 and 1.2 for the "
    "current filing period. A wrong field position gets the return rejected "
    "by the FVU, so this sheet deliberately stops at grouping the figures "
    "rather than guessing their positions."
)

#: The FVU "Remarks" column is a published closed list of single-letter codes
#: (A/B/C/T/Y/... — see the module docstring) that says WHY a deduction was
#: nil or below the section's rate. This product records the STATUTORY REASON
#: in plain English (a §197 certificate number, or — on 27Q — a sentence
#: naming why §195 did not reach the payment) and never the FVU letter itself,
#: because guessing a letter from a list this codebase cannot confirm in full
#: would put a wrong code in a filed return.
REMARK_CODE_NOT_HELD = (
    "{count} deductee row(s) recorded a lower or nil deduction. The RPU's "
    "own 'Remarks' column needs one of its published single-letter reason "
    "codes (certificate under §197, threshold, transporter declaration, "
    "grossing-up, and others) — this product records WHY in plain English "
    "but does not hold the FVU's own code table, so pick the matching letter "
    "in the RPU yourself for each such row."
)

UNMATCHED_DEDUCTEES = (
    "{count} deductee row(s) carry no matching challan (no BSR code or "
    "challan number recorded against them) and are listed separately below, "
    "outside any Challan Detail block. A deductee row with no challan is a "
    "26AS entry that will read unmatched — resolve this before filing."
)

ORPHAN_CHALLAN_ROWS = (
    "{count} deductee row(s) reference a challan (BSR code {bsr_code}, "
    "number {challan_no}) that is not among the challans this statement "
    "read for the quarter. Listed under their own heading rather than "
    "silently dropped."
)


def _challan_key(bsr_code: Any, challan_no: Any, challan_date: Any) -> tuple:
    return (str(bsr_code or "").strip(), str(challan_no or "").strip(),
            str(challan_date or "").strip())


def build(data: dict) -> dict[str, Any]:
    """The whole sheet, built over what `tds_26q_from_books` / `tds_27q_from_books`
    / `tds_24q_from_books` already computed — `data` is exactly that dict.

    Deliberately takes the already-assembled RESPONSE dict rather than the
    `TDSxxPayload` dataclass: the response is what every caller already has in
    hand (the router returns it, the screen already fetched it), and reading
    it back rather than recomputing means this can never disagree with what
    the CA is already looking at on the Summary/Deductees/Challans tabs.
    """
    deductees = list(data.get("deductees") or [])
    challans = list(data.get("challans") or [])
    gaps: list[str] = []

    grouped: dict[tuple, list[dict]] = {}
    unmatched: list[dict] = []
    for d in deductees:
        key = _challan_key(d.get("bsr_code"), d.get("challan_no"), d.get("challan_date"))
        if not key[0] and not key[1]:
            unmatched.append(d)
            continue
        grouped.setdefault(key, []).append(d)

    challan_sections: list[dict[str, Any]] = []
    seen_keys: set[tuple] = set()
    for c in challans:
        key = _challan_key(c.get("bsr_code"), c.get("challan_no"), c.get("payment_date"))
        seen_keys.add(key)
        challan_sections.append({
            "record_type": RECORD_CHALLAN_DETAIL,
            "challan": c,
            "deductees": grouped.get(key, []),
        })

    # A deductee whose challan reference does not match any challan this
    # statement actually read — named rather than folded into `unmatched`,
    # because the CA needs a different fix (the challan register is short a
    # row) from a deductee with NO reference at all (nothing was deposited
    # against it yet).
    for key, rows in grouped.items():
        if key in seen_keys:
            continue
        challan_sections.append({
            "record_type": RECORD_CHALLAN_DETAIL,
            "challan": None,
            "challan_reference": {"bsr_code": key[0], "challan_no": key[1], "challan_date": key[2]},
            "deductees": rows,
        })
        gaps.append(ORPHAN_CHALLAN_ROWS.format(
            count=len(rows), bsr_code=key[0] or "—", challan_no=key[1] or "—"))

    if unmatched:
        gaps.append(UNMATCHED_DEDUCTEES.format(count=len(unmatched)))

    lower_or_nil = sum(
        1 for d in deductees
        if d.get("is_lower_deduction") or d.get("non_deduction_reason"))
    if lower_or_nil:
        gaps.append(REMARK_CODE_NOT_HELD.format(count=lower_or_nil))

    gaps.append(NO_FVU_FILE_IS_PRODUCED)

    return {
        "form": data.get("form"),
        "act": data.get("act"),
        "financial_year": data.get("financial_year"),
        "quarter": data.get("quarter"),
        "record_types": {
            "file_header": RECORD_FILE_HEADER,
            "batch_header": RECORD_BATCH_HEADER,
            "challan_detail": RECORD_CHALLAN_DETAIL,
            "deductee_detail": RECORD_DEDUCTEE_DETAIL,
        },
        # Batch Header, in RPU terms — the deductor's own identity, keyed once
        # per statement regardless of how many challans or deductees follow.
        "deductor": {
            "tan": data.get("tan"),
            "deductor_name": data.get("deductor_name"),
            "deductor_pan": data.get("deductor_pan"),
            "deductor_address": data.get("deductor_address"),
        },
        "challan_sections": challan_sections,
        "unmatched_deductees": unmatched,
        "deductee_count": len(deductees),
        "challan_count": len(challans),
        "gaps": gaps,
    }
