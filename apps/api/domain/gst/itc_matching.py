"""
Matching a client's purchase bills against what GSTR-2B says — CGST §16(2)(aa).

WHY THIS IS A DOMAIN MODULE AND NOT A SCREEN
    It was a browser function. `reconcile()` in
    apps/web/app/gst/reconciliation/page.tsx matched in TypeScript, over a
    purchase register the CA had to export from this product and upload back
    into it, and threw the answer away on refresh. CLAUDE.md: computation,
    validation and statutory rules live in apps/api. So this is the rule, once,
    with no I/O in it — the service reads the books and persists; this decides.

WHAT §16(2)(aa) MAKES THIS FOR
    Since 01-01-2022, input tax credit is available only where the supplier has
    furnished the invoice in THEIR outward return and it has been communicated
    to the recipient — that communication IS GSTR-2B. So the question is not
    "do our books balance" but "for each bill we hold, did the supplier file
    it", and the answer decides how much credit may be taken this month.

THE FOUR ANSWERS, AND WHY THEY ARE FOUR AND NOT TWO
    matched            the bill and the 2B document agree, to the paisa
    amount_mismatch    both exist and the tax differs — SOMETHING is wrong with
                       one of the two documents, and the difference is the
                       amount at risk
    missing_in_2b      we hold a bill the supplier has not filed. The credit
                       cannot be taken; chase the SUPPLIER
    missing_in_books   the supplier filed a document we have no bill for. The
                       credit may be available and is not being claimed; chase
                       the DOCUMENT

    The last two are opposite problems with opposite actions, and a
    reconciliation that reports one figure for both is telling a CA to chase
    the wrong party.

MATCHING IS EXACT, THEN NARROWED — NEVER FUZZY ON THE AMOUNT
    The key is (supplier GSTIN, normalised document number). The number is
    normalised because a supplier writing "INV/2025-26/0042" and a data-entry
    hand writing "INV-2025-26-42" is the commonest cause of a false
    "missing_in_2b", and chasing a supplier who did file is a phone call that
    costs the CA their credibility. Case, spaces and the separators - / \\ .
    are folded, and leading zeros in the final numeric run are dropped.

    The AMOUNT is never fuzzy. A tolerance on the tax is a tolerance on the
    credit claimed, and Rule 36(4) is not a rule about being close.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

#: matched / amount_mismatch / missing_in_2b / missing_in_books
MatchStatus = str

_SEPARATORS = re.compile(r"[\s\-/\\.]+")


def normalise_document_number(raw: str) -> str:
    """The comparison key for an invoice or note number.

    Case and whitespace fold away; the separators - / \\ . are treated as
    SEGMENT boundaries, and a segment that is entirely digits loses its leading
    zeros. So "INV/2025-26/0042", "inv 2025 26 42" and "INV-2025-26-42" are one
    document.

    Per SEGMENT, and only where the segment is all digits. Stripping zeros out
    of the concatenated string would make "INV/2025-26/0042" and
    "INV/2025-26/42" differ (the run "2025260042" has no leading zero to
    strip), which is the exact pair this is for. And a segment like "S008400"
    is left alone: those zeros are part of a serial, not padding, and folding
    them risks a FALSE match — which is the expensive direction here, because
    it silently claims credit against the wrong supplier's document.
    """
    segments = _SEPARATORS.split(str(raw or "").strip().upper())
    out = []
    for seg in segments:
        if seg.isdigit():
            out.append(seg.lstrip("0") or "0")
        else:
            out.append(seg)
    return "".join(out)


@dataclass(frozen=True)
class BookBill:
    """One purchase bill, as the matcher needs it."""
    bill_id: str
    supplier_gstin: str
    bill_no: str
    bill_date: Optional[str]
    taxable_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise


@dataclass(frozen=True)
class PortalDocument:
    """One GSTR-2B document, as the matcher needs it. `key` is what
    domain.gst.gstr2b produced; this module does not re-parse anything."""
    section: str
    document_type: str
    supplier_gstin: str
    supplier_name: str
    document_number: str
    document_date: Optional[str]
    taxable_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int
    itc_available: str

    @property
    def tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise


@dataclass(frozen=True)
class Match:
    status: MatchStatus
    bill_id: Optional[str]
    document: Optional[PortalDocument]
    bill: Optional[BookBill]
    #: Book tax minus portal tax, in paise. Positive means the books claim more
    #: credit than 2B allows, which is the direction that draws a notice.
    difference_paise: int
    reason: str


@dataclass
class Reconciliation:
    matches: list[Match]

    def _of(self, status: MatchStatus) -> list[Match]:
        return [m for m in self.matches if m.status == status]

    @property
    def matched(self) -> list[Match]:
        return self._of("matched")

    @property
    def amount_mismatch(self) -> list[Match]:
        return self._of("amount_mismatch")

    @property
    def missing_in_2b(self) -> list[Match]:
        return self._of("missing_in_2b")

    @property
    def missing_in_books(self) -> list[Match]:
        return self._of("missing_in_books")

    def summary(self) -> dict:
        """The figures the screen prints, including the ones that decide the
        return: how much credit 2B actually allows, and how much of what the
        books claim is not supported by it."""
        allowed = sum(
            m.document.tax_paise for m in self.matches
            if m.document is not None and m.document.itc_available != "N")
        blocked_by_2b = sum(
            m.document.tax_paise for m in self.matches
            if m.document is not None and m.document.itc_available == "N")
        claimed = sum(m.bill.tax_paise for m in self.matches if m.bill is not None)
        at_risk = sum(
            m.bill.tax_paise for m in self.matches
            if m.bill is not None and m.status == "missing_in_2b")
        return {
            "matched_count": len(self.matched),
            "amount_mismatch_count": len(self.amount_mismatch),
            "missing_in_2b_count": len(self.missing_in_2b),
            "missing_in_books_count": len(self.missing_in_books),
            # The credit the books claim, and the part of it 2B does not
            # support. §16(2)(aa) makes the second figure the one that matters.
            "books_tax_paise": claimed,
            "portal_tax_paise": allowed + blocked_by_2b,
            "itc_available_per_2b_paise": allowed,
            "itc_blocked_by_2b_paise": blocked_by_2b,
            "itc_at_risk_paise": at_risk,
        }


def _key(gstin: str, number: str) -> tuple[str, str]:
    return (str(gstin or "").strip().upper(), normalise_document_number(number))


def reconcile(bills: Iterable[BookBill],
              documents: Iterable[PortalDocument]) -> Reconciliation:
    """Match the books against the portal. Pure — no I/O, no clock, no db.

    A document with no supplier GSTIN (an import — the document is a bill of
    entry and there is no supplier) can never key-match a purchase bill, so it
    is reported as missing_in_books rather than silently dropped: the credit is
    real and somebody has to account for it.
    """
    bills = list(bills)
    documents = list(documents)

    # Index once. A supplier CAN file two documents with the same number in one
    # period (an invoice and its amendment in b2ba), so the value is a queue and
    # each is consumed at most once — a second bill with the same number takes
    # the second document rather than re-matching the first.
    by_key: dict[tuple[str, str], list[int]] = {}
    for i, d in enumerate(documents):
        by_key.setdefault(_key(d.supplier_gstin, d.document_number), []).append(i)

    matches: list[Match] = []
    consumed: set[int] = set()

    for bill in bills:
        k = _key(bill.supplier_gstin, bill.bill_no)
        queue = by_key.get(k, [])
        candidates = [(i, documents[i]) for i in queue if i not in consumed]
        if not candidates:
            matches.append(Match(
                status="missing_in_2b", bill_id=bill.bill_id, document=None, bill=bill,
                difference_paise=bill.tax_paise,
                reason=("The supplier has not filed this invoice. §16(2)(aa) makes "
                        "the credit unavailable until they do — chase the supplier, "
                        "and hold the credit back this month.")))
            continue
        idx, doc = candidates[0]
        consumed.add(idx)
        diff = bill.tax_paise - doc.tax_paise
        if diff == 0 and bill.taxable_paise == doc.taxable_paise:
            reason = ""
            if doc.itc_available == "N":
                reason = ("The document matches, but GSTR-2B marks the credit "
                          "UNAVAILABLE — the figures agreeing does not make it "
                          "claimable.")
            matches.append(Match(status="matched", bill_id=bill.bill_id, document=doc,
                                 bill=bill, difference_paise=0, reason=reason))
        else:
            matches.append(Match(
                status="amount_mismatch", bill_id=bill.bill_id, document=doc, bill=bill,
                difference_paise=diff,
                reason=(f"The bill claims {abs(diff)} paise "
                        f"{'more' if diff > 0 else 'less'} tax than GSTR-2B carries. "
                        f"One of the two documents is wrong — the difference is the "
                        f"amount at risk.")))

    for i, doc in enumerate(documents):
        if i in consumed:
            continue
        matches.append(Match(
            status="missing_in_books", bill_id=None, document=doc, bill=None,
            difference_paise=-doc.tax_paise,
            reason=("The supplier filed this and there is no bill for it in the "
                    "books. The credit may be available and is not being claimed "
                    "— chase the document, not the supplier.")))

    return Reconciliation(matches=matches)


def defaulters(rec: Reconciliation) -> list[dict]:
    """Suppliers who have not filed, worst first — the list a CA chases from.

    Keyed on the GSTIN off the BILL, because the whole point of a defaulter is
    that no portal document exists to take a name from.
    """
    by_gstin: dict[str, dict] = {}
    for m in rec.missing_in_2b:
        if m.bill is None:
            continue
        row = by_gstin.setdefault(m.bill.supplier_gstin, {
            "supplier_gstin": m.bill.supplier_gstin,
            "unfiled_count": 0,
            "itc_at_risk_paise": 0,
            "bill_ids": [],
        })
        row["unfiled_count"] += 1
        row["itc_at_risk_paise"] += m.bill.tax_paise
        row["bill_ids"].append(m.bill.bill_id)
    return sorted(by_gstin.values(), key=lambda r: -r["itc_at_risk_paise"])
