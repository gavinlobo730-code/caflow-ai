"""
Turn exception findings into the amendments a later return should carry.

domain/gst/exception_report.py says what moved after a period was filed. This
decides what to do about each finding, and produces entries ready for the
amendment tables in domain/gst/amendments.py.

Splitting the two is not tidiness. Finding drift is arithmetic and has one right
answer. Deciding how to declare it is judgement, and some of it belongs to the
CA rather than to us — keeping the decision layer separate is what makes it
possible to say clearly which findings this module resolves and which it
refuses to.

WHAT IT RESOLVES
    amount_changed  -> an amended entry carrying the corrected figures, keyed to
                       the ORIGINAL document number and date.
    reclassified    -> the same, into the amendment table of the section it was
                       ORIGINALLY filed in. An invoice filed as B2B and now an
                       export is amended in 9A (b2ba), not declared afresh in
                       expa: 9A supersedes the entry that exists.
    b2cs changes    -> an amended row in table 10, carrying the original month.

WHAT IT CARRIES FORWARD RATHER THAN AMENDING
    missing_from_return — an invoice dated in the filed period but raised after
    it was filed was never declared, so there is no entry to supersede. It is
    reported in the CURRENT period's ORDINARY table with its own original date.

    This one would otherwise fall through the floor: gstr1_from_books selects by
    date range, so the invoice is outside the current period's window as well as
    inside a closed one. Nothing would ever declare it.

WHAT IT REFUSES TO DECIDE
    missing_from_books — a document was declared and has since been cancelled.
    There is no single correct treatment: amend the entry to nil, or leave it
    and raise a credit note. The two produce different liabilities and different
    trails, and it depends on why it was cancelled. Surfaced as needs_decision
    with the figures, never resolved silently.
"""
from __future__ import annotations

from typing import Any

from domain.gst.amendments import (
    SECTION_TABLE, amendment_section_for, build_b2cs_amendment,
    build_invoice_amendment, build_note_amendment,
)

_HEADS = ("taxable_paise", "cgst_paise", "sgst_paise", "igst_paise", "cess_paise")

# A note amendment needs to know whether the counterparty is registered, which
# is exactly what separates the two original sections.
_NOTE_SECTIONS = ("cdnr", "cdnur")


def _corrected(finding: dict) -> dict:
    """The figures the amendment should declare.

    `books` on an amount_changed finding; for a reclassified one the delta is
    reported but the books side is what the amendment states, so both shapes
    fall back to reconstructing it from filed + delta.
    """
    books = finding.get("books")
    if isinstance(books, dict) and books:
        return {h: int(books.get(h, 0)) for h in _HEADS}
    filed = finding.get("filed") or {}
    delta = finding.get("delta") or {}
    return {h: int(filed.get(h, 0)) + int(delta.get(h, 0)) for h in _HEADS}


def _entry(section: str, group: str, node: dict, *, finding: dict, why: str) -> dict:
    return {
        "section": section,
        "group": group,
        "node": node,
        "table": SECTION_TABLE[section],
        "reason": why,
        "original_document": finding.get("doc_no") or "",
    }


def propose(exception_report: dict, *, original_period: str) -> dict:
    """Amendments for one filed period's drift.

    `original_period` is the MMYYYY the return was filed for — the month a B2CS
    amendment has to name in `omon`, and the period the CA is correcting.
    """
    report = exception_report or {}
    docs = report.get("documents") or {}

    entries: list[dict] = []
    carry_forward: list[dict] = []
    needs_decision: list[dict] = []

    for finding in docs.get("amount_changed") or []:
        section = amendment_section_for(finding.get("section") or "")
        if not section:
            continue
        entries.append(_entry(
            section, finding.get("counterparty") or "",
            _build_node(section, finding, _corrected(finding)),
            finding=finding,
            why="Figures changed after the return was filed.",
        ))

    for finding in docs.get("reclassified") or []:
        # The amendment goes in the table the document was ORIGINALLY filed
        # under. Declaring it in the new section's amendment table would amend
        # an entry that was never there.
        section = amendment_section_for(finding.get("filed_section") or "")
        if not section:
            continue
        entries.append(_entry(
            section, finding.get("counterparty") or "",
            _build_node(section, finding, _corrected(finding)),
            finding=finding,
            why=(f"Moved from {finding.get('filed_section')} to "
                 f"{finding.get('books_section')} after filing — amended in the "
                 f"table it was originally declared in."),
        ))

    for row in (report.get("b2cs") or {}).get("changed") or []:
        corrected = {h: int((row.get("books") or {}).get(h, 0)) for h in _HEADS}
        entries.append({
            "section": "b2csa",
            "group": "",
            "node": build_b2cs_amendment(
                original_month=original_period,
                supply_type=row.get("supply_type") or "",
                rate=row.get("rate"),
                place_of_supply=row.get("place_of_supply") or "",
                corrected=corrected,
            ),
            "table": SECTION_TABLE["b2csa"],
            "reason": "B2C-others totals changed after the return was filed.",
            "original_document": f"{original_period} · {row.get('place_of_supply') or ''}",
        })

    for finding in docs.get("missing_from_return") or []:
        carry_forward.append({
            "doc_no": finding.get("doc_no") or "",
            "doc_date": finding.get("doc_date") or "",
            "section": finding.get("section") or "",
            "counterparty": finding.get("counterparty") or "",
            **{h: int(finding.get(h, 0)) for h in _HEADS},
            "reason": ("Raised after the period was filed, so it was never declared. "
                       "There is no entry to amend — it belongs in this period's "
                       "ordinary table, with its own original date."),
        })

    for finding in docs.get("missing_from_books") or []:
        needs_decision.append({
            "doc_no": finding.get("doc_no") or "",
            "doc_date": finding.get("doc_date") or "",
            "section": finding.get("section") or "",
            **{h: int(finding.get(h, 0)) for h in _HEADS},
            "question": ("This document was declared in the filed return and is no "
                         "longer in the books. Amend the entry to nil, or leave it "
                         "and raise a credit note? The two produce different "
                         "liabilities, and which is right depends on why it was "
                         "cancelled."),
        })

    return {
        "original_period": original_period,
        "entries": entries,
        "carry_forward": carry_forward,
        "needs_decision": needs_decision,
        "counts": {
            "amendments": len(entries),
            "carry_forward": len(carry_forward),
            "needs_decision": len(needs_decision),
        },
        "rule": "CGST Act §37 — a filed GSTR-1 is corrected by amending it in a "
                "later period's return, never by revising it.",
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This proposes; nothing is
        # added to any return until the CA confirms it.
        "ca_review_required": True,
    }


def _build_node(section: str, finding: dict, corrected: dict) -> dict:
    """The right node shape for the section being amended."""
    doc_no = finding.get("doc_no") or ""
    doc_date = finding.get("doc_date") or ""
    if section in ("cdnra", "cdnura"):
        return build_note_amendment(
            original_no=doc_no, original_date=doc_date,
            corrected=corrected,
            place_of_supply=finding.get("counterparty") or "",
            unregistered_type="B2CS" if section == "cdnura" else None,
        )
    return build_invoice_amendment(
        original_no=doc_no, original_date=doc_date, section=section,
        corrected=corrected,
        place_of_supply=finding.get("counterparty") or "",
    )
