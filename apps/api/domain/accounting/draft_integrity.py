"""Does a DRAFT document add up to its own lines? Asked before the draft is issued (ledger POST-A-335).

WHY THE QUESTION IS ASKED AT ISSUE
    An invoice, a bill and the four notes are written as a draft, and the issue route posts the journal and the tax columns from the
    STORED header row. The API computes that header from the lines when it creates or edits a draft, so for a draft the API wrote the
    answer is always yes. But a draft is a row a signed-in member's own token can still change over PostgREST (the particulars are
    written by the caller's own client; only the settlement, the status and the journal link are the API's alone since migration 544),
    so the header the issue route reads may be one nobody computed. Two members of the accounting tier can then do, with the permission
    they already hold:

      * set the carried-over flag (`is_opening`) on a draft and issue it. A carried-over document is left out of GSTR-1 and GSTR-3B
        (`opening_documents.without_carried_over`) and, on a bill, out of the 2B reconciliation, Rule 37 and section 43B(h), so a taxed
        sale posts to Sales and GST Output and is declared nowhere. The API creates an opening document already issued and its only
        later update is `deleted_at`, so no legitimate draft carries the flag;
      * set a header total or a tax column to something its lines do not say, and have it posted.

    This module is the pure half: given the stored header and the lines read for it, it returns plain sentences for whatever does
    not hold, and nothing when everything does. `services/draft_integrity_service` reads the lines and refuses.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
    Only identities the creating code makes true by construction and that every stored document in production satisfied on
    24-10-2026 (read-only counts over all six tables, in every status):

      * the flag is clear;
      * the total is the sum of its parts, in the way the document's own create path adds them (an invoice: taxable + the three
        tax heads + cess + round-off; a bill: the same without round-off, but the taxable value alone on a reverse-charge bill, where
        the supplier charged no tax; a note: taxable + the three tax heads); `total_gst_paise` is the three heads;
      * a bill's net payable is its total less what was withheld;
      * the header's taxable value and tax heads are the sums over the lines (an invoice's discount too, and a bill's blocked-credit
        columns over the lines that carry `itc_eligible` false); in a foreign currency the header is in rupees and the lines are not,
        so the foreign-currency columns `txn_taxable` and `txn_total_gst` are compared with the lines instead.

    It does not recompute the tax from a rate, the discount from a percentage or the withholding from the vendor's section: those
    are decisions the create path takes with inputs the issue route does not have, and a mismatch there would be a refusal of a
    legitimate draft. It judges the document's arithmetic against itself, not against the world. A forged withholding that keeps
    the bill's total and net payable consistent is therefore not caught here, and a tamper with the lines AND the header together
    is not either; closing the draft's writers to the API alone is the second half of the ledger item.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, NamedTuple, Optional

from domain.money_text import rupees_paise

SALES_INVOICE = "sales_invoice"
PURCHASE_BILL = "purchase_bill"
CREDIT_NOTE = "credit_note"
DEBIT_NOTE = "debit_note"
PURCHASE_CREDIT_NOTE = "purchase_credit_note"
SALES_DEBIT_NOTE = "sales_debit_note"

KINDS = (SALES_INVOICE, PURCHASE_BILL, CREDIT_NOTE, DEBIT_NOTE, PURCHASE_CREDIT_NOTE, SALES_DEBIT_NOTE)

OPENING = "opening"
ARITHMETIC = "arithmetic"
LINES = "lines"


class Problem(NamedTuple):
    """One thing that does not hold: its kind (so the refusal can say what to do about it) and the sentence."""
    code: str
    text: str


#: What each kind is called in a sentence a person reads.
NAME_OF = {
    SALES_INVOICE: "invoice",
    PURCHASE_BILL: "bill",
    CREDIT_NOTE: "credit note",
    DEBIT_NOTE: "debit note",
    PURCHASE_CREDIT_NOTE: "credit note",
    SALES_DEBIT_NOTE: "debit note",
}

#: The kinds whose header carries a compensation-cess column, a rupee round-off and a foreign-currency pair.
_HAS_CESS = frozenset({SALES_INVOICE, PURCHASE_BILL})
_HAS_ROUND_OFF = frozenset({SALES_INVOICE})
_HAS_FOREIGN = frozenset({SALES_INVOICE, PURCHASE_BILL})


def _paise(row: Mapping[str, Any], column: str) -> int:
    """A stored amount; an absent or NULL column is nil, which is what the schema's own default says."""
    return int(row.get(column) or 0)


def _rupees(paise: int) -> str:
    return f"₹{rupees_paise(paise)}"


def _is_foreign(kind: str, header: Mapping[str, Any]) -> bool:
    if kind not in _HAS_FOREIGN:
        return False
    currency = (header.get("txn_currency") or "INR").strip().upper()
    return currency != "INR"


def _sum(lines: Iterable[Mapping[str, Any]], column: str) -> int:
    return sum(_paise(line, column) for line in lines)


def _opening_problems(kind: str, header: Mapping[str, Any]) -> list[Problem]:
    if not header.get("is_opening"):
        return []
    name = NAME_OF[kind]
    return [Problem(OPENING,
                    f"it is flagged as a carried-over (opening) {name}. An opening {name} is created already "
                    f"{'received' if kind == PURCHASE_BILL else 'issued'}, never issued from a draft, and is left out of the returns")]


def _header_problems(kind: str, header: Mapping[str, Any]) -> list[Problem]:
    """The header against itself: its total is its parts, its GST is the three heads, a bill's net payable is its total less the
    tax withheld."""
    found: list[Problem] = []
    taxable = _paise(header, "taxable_amount_paise")
    gst = _paise(header, "cgst_paise") + _paise(header, "sgst_paise") + _paise(header, "igst_paise")
    cess = _paise(header, "cess_paise") if kind in _HAS_CESS else 0
    round_off = _paise(header, "round_off_paise") if kind in _HAS_ROUND_OFF else 0
    if kind == PURCHASE_BILL and header.get("is_reverse_charge"):
        parts = taxable          # the supplier charged no tax: what is owed to them is the taxable value alone
        parts_say = "the taxable value alone, because the supplier charged no tax on a reverse-charge bill"
    else:
        parts = taxable + gst + cess + round_off
        parts_say = "the taxable value plus the tax" + (", cess" if kind in _HAS_CESS else "") + (
            " and round-off" if kind in _HAS_ROUND_OFF else "")
    total = _paise(header, "total_paise")
    if total != parts:
        found.append(Problem(ARITHMETIC, f"its total is {_rupees(total)} but {parts_say} come to {_rupees(parts)}"))
    if _paise(header, "total_gst_paise") != gst:
        found.append(Problem(ARITHMETIC,
                             f"its recorded GST is {_rupees(_paise(header, 'total_gst_paise'))} but its CGST, SGST and IGST come "
                             f"to {_rupees(gst)}"))
    if kind == PURCHASE_BILL:
        net, expected = _paise(header, "net_payable_paise"), total - _paise(header, "tds_paise")
        if net != expected:
            found.append(Problem(ARITHMETIC,
                                 f"its net payable is {_rupees(net)} but its total less the tax withheld is {_rupees(expected)}"))
    return found


def _foreign_problems(header: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> list[Problem]:
    """A document in a foreign currency: the header is in rupees and the lines are not, so the header's own currency totals
    (`txn_taxable`, `txn_total_gst`) are what the lines are compared with."""
    found: list[Problem] = []
    line_taxable = _sum(rows, "taxable_amount_paise")
    line_gst = _sum(rows, "cgst_paise") + _sum(rows, "sgst_paise") + _sum(rows, "igst_paise")
    if _paise(header, "txn_taxable") != line_taxable:
        found.append(Problem(LINES,
                             f"its taxable value in the document's currency is {_paise(header, 'txn_taxable')} but its lines come "
                             f"to {line_taxable} (smallest units)"))
    if _paise(header, "txn_total_gst") != line_gst:
        found.append(Problem(LINES,
                             f"its GST in the document's currency is {_paise(header, 'txn_total_gst')} but its lines come to "
                             f"{line_gst} (smallest units)"))
    return found


def _blocked_credit_problems(header: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> list[Problem]:
    """A bill's blocked-credit columns (CGST Act s.17(5)) against the lines marked as not eligible for input credit."""
    found: list[Problem] = []
    blocked = [r for r in rows if r.get("itc_eligible") is False]
    for label, column, line_column in (
        ("CGST", "ineligible_itc_cgst_paise", "cgst_paise"),
        ("SGST", "ineligible_itc_sgst_paise", "sgst_paise"),
        ("IGST", "ineligible_itc_igst_paise", "igst_paise"),
        ("cess", "ineligible_itc_cess_paise", "cess_paise"),
    ):
        if _paise(header, column) != _sum(blocked, line_column):
            found.append(Problem(LINES,
                                 f"its blocked-credit {label} is {_rupees(_paise(header, column))} but the lines marked as not "
                                 f"eligible for input credit carry {_rupees(_sum(blocked, line_column))}"))
    return found


def _line_problems(kind: str, header: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> list[Problem]:
    """The header against its lines."""
    if not rows:
        return [Problem(LINES, f"it has no lines, so nothing stands behind its {_rupees(_paise(header, 'total_paise'))}")]
    if _is_foreign(kind, header):
        return _foreign_problems(header, rows)
    found: list[Problem] = []
    checks = [("taxable value", "taxable_amount_paise"), ("CGST", "cgst_paise"), ("SGST", "sgst_paise"), ("IGST", "igst_paise")]
    if kind in _HAS_CESS:
        checks.append(("cess", "cess_paise"))
    if kind == SALES_INVOICE:
        checks.append(("discount", "discount_paise"))
    for label, column in checks:
        if _paise(header, column) != _sum(rows, column):
            found.append(Problem(LINES, f"its {label} is {_rupees(_paise(header, column))} but its lines come to "
                                        f"{_rupees(_sum(rows, column))}"))
    if kind == PURCHASE_BILL:
        found.extend(_blocked_credit_problems(header, rows))
    return found


def problems(kind: str, header: Mapping[str, Any], lines: Optional[Iterable[Mapping[str, Any]]]) -> list[Problem]:
    """What does not hold for this draft, as sentences with their kind; an empty list means it adds up and may be issued.

    `header` is the stored row exactly as the issue route read it and `lines` the document's stored lines (None or empty is a
    draft with no lines, which has nothing behind its figures)."""
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a document kind this check knows")
    return _opening_problems(kind, header) + _header_problems(kind, header) + _line_problems(kind, header, list(lines or []))


def refusal(kind: str, problem_list: list[Problem]) -> str:
    """The one sentence a refused issue is answered with. What to do about it depends on what was wrong: a figure that does not add
    up is put right by saving the draft again (the API works the figures out from the lines), a carried-over flag is not."""
    name = NAME_OF[kind]
    shown = "; ".join(p.text for p in problem_list[:3])
    more = f" (and {len(problem_list) - 3} more)" if len(problem_list) > 3 else ""
    advice = []
    if any(p.code == OPENING for p in problem_list):
        advice.append(f"Delete this draft and enter the {name} again if it is a current one.")
    if any(p.code != OPENING for p in problem_list):
        advice.append("Open the draft and save it again so its figures are worked out from its lines, then issue it.")
    return f"Cannot issue this {name}: {shown}{more}. " + " ".join(advice) + " Nothing was posted."
