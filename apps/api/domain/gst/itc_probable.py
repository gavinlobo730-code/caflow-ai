"""Probable matches for the two documents `itc_matching` could not tie together
(gst-12) — SUGGESTIONS a CA confirms by correcting a document, never a link.

WHAT WAS MISSING
    `itc_matching.reconcile` is exact on purpose: the key is the supplier's
    GSTIN plus the folded document number, and the AMOUNT is never fuzzy,
    because a tolerance on the tax is a tolerance on the credit claimed. So a
    bill booked under a supplier GSTIN with one character wrong (or none at all)
    comes back as TWO unrelated rows — `missing_in_2b` for the bill and
    `missing_in_books` for the very document the supplier filed — and nothing
    on the screen says they are the same invoice. The CA then phones a supplier
    who DID file, which is exactly the call the number folding exists to save
    them, and hunts for a bill they already hold.

WHAT THIS DOES, AND THE LINE IT DOES NOT CROSS
    It reads the reconciliation's two leftover lists and proposes pairs. It
    writes nothing, links nothing and CHANGES NO CREDIT:

      * `reconcile` is not called again and not touched — the bill stays
        `missing_in_2b` and §16(2)(aa)'s per-document pass (`rule_36_4`) goes on
        withholding its credit, because that pass reads `purchase_bill_id`,
        which only an exact match writes;
      * nothing here is persisted, so there is no stored "probable" status for
        a later reader to mistake for a match;
      * the suggestion goes away when the CA corrects the bill (or the
        supplier's GSTIN) and re-runs the reconciliation, which is the only
        thing that can turn it into a match.

    The amount tolerance below (`AMOUNT_BAND_PAISE`) is therefore a tolerance on
    a HINT. It never reaches `reconcile`, and a test asserts that module still
    contains no tolerance at all.

THE THREE KINDS, AND WHY EACH NEEDS MORE THAN ITS OWN CLUE
    A single clue is what a coincidence looks like. Supplier invoice numbers
    differ by one digit all the time (INV-41, INV-42), a small supplier numbers
    from 1 and so does another, and two bills can share a round amount, so every
    kind below requires a second and usually a third fact to agree:

      supplier_gstin_differs   the folded number is the SAME and the GSTIN is not
                               — a typo, a registration in another State of the
                               same supplier (same PAN), or a supplier recorded
                               with no GSTIN at all. Needs the date not to
                               CONFLICT and either a related GSTIN or the
                               amounts to agree exactly.
      document_number_differs  the GSTIN is the SAME and the number is within a
                               typo of it (a dropped, doubled or transposed
                               character). Needs the date to agree AND the
                               amounts to agree (exactly, or within the band
                               with the date equal).
      amount_and_date_only     the GSTIN is the same, the number is unrelated,
                               and the DATE and the AMOUNTS both agree exactly.
                               The weakest kind, and always `possible`.

    NOT A KIND: same GSTIN, same number, tax a rupee out. That pair is already
    ONE `amount_mismatch` row — the key matched, so the two documents are linked
    and the difference is stated — and offering it here as well would present a
    finished link as a guess.

TWO GRADES, NO PERCENTAGE
    `strong` or `possible`, each with the sentences that earned it — the bank
    module's convention (a draft is `ready` or `proposed`, never a score). A
    number invites arithmetic on it, and this is a judgement a person makes.

WHAT IS COMPARED
    Invoices only. A credit note, a debit note and a bill of entry each have a
    different counterpart in the books (a purchase credit note, a debit note, a
    bill of entry), and none of them is a purchase BILL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from domain.gst import gstin as _gstin
from domain.gst.itc_matching import (
    BookBill, Match, PortalDocument, Reconciliation, normalise_document_number,
)

STRONG = "strong"
POSSIBLE = "possible"

KIND_GSTIN = "supplier_gstin_differs"
KIND_NUMBER = "document_number_differs"
KIND_AMOUNT = "amount_and_date_only"

#: A rupee, in paise. How far two figures may sit apart and still be called "the
#: same amount, give or take supplier rounding" — for a HINT only (see the
#: module docstring). Never read by the matcher.
AMOUNT_BAND_PAISE = 100

#: GSTIN edit distance at or under which two registrations read as one typed
#: twice. A GSTIN is fifteen characters; two substitutions or one swap is what a
#: slip of the hand produces, three is a different registration.
GSTIN_TYPO_DISTANCE = 2

#: Numbers shorter than this are not compared by closeness at all: "1" and "2"
#: are one edit apart and are not the same invoice.
MIN_NUMBER_LENGTH_TO_COMPARE = 4
#: Up to this many characters, one edit is "a typo"; beyond it, two.
SHORT_NUMBER_LENGTH = 6

NEVER_CHANGES_THE_CREDIT = (
    "This is a suggestion and changes nothing: the bill stays unmatched and its "
    "credit stays withheld under §16(2)(aa) until the document is corrected and "
    "the GSTR-2B reconciliation is run again.")

_EXACT, _BAND, _DIFFERS = "exact", "band", "differs"
_EQUAL, _UNKNOWN = "equal", "unknown"


@dataclass(frozen=True)
class Probable:
    """One bill and one 2B document that are probably the same invoice."""
    grade: str
    kind: str
    bill: BookBill
    document: PortalDocument
    #: What agrees and what does not, one sentence each.
    evidence: tuple[str, ...]
    #: What the CA is being asked to check.
    action: str

    def to_json(self) -> dict:
        b, d = self.bill, self.document
        return {
            "grade": self.grade,
            "kind": self.kind,
            "evidence": list(self.evidence),
            "action": self.action,
            "changes_credit": False,
            "bill_id": b.bill_id,
            "bill_no": b.bill_no,
            "bill_date": b.bill_date,
            "bill_supplier_gstin": b.supplier_gstin,
            "book_taxable_paise": b.taxable_paise,
            "book_tax_paise": b.tax_paise,
            "document_section": d.section,
            "document_type": d.document_type,
            "document_number": d.document_number,
            "document_date": d.document_date,
            "document_supplier_gstin": d.supplier_gstin,
            "document_supplier_name": d.supplier_name,
            "portal_taxable_paise": d.taxable_paise,
            "portal_tax_paise": d.tax_paise,
            "itc_available": d.itc_available,
        }


# ── small, pure comparisons ──────────────────────────────────────────────────

def edit_distance(a: str, b: str, limit: int) -> int:
    """Optimal-string-alignment distance (insert, delete, substitute, and swap
    of two adjacent characters), or `limit + 1` once it is certain to exceed
    `limit`. A transposition costs ONE — it is the commonest way a human gets a
    GSTIN or an invoice number wrong, and plain Levenshtein would charge two."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: Optional[list[int]] = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1
                    and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return min(prev[-1], limit + 1)


def _norm_gstin(value: str) -> str:
    return str(value or "").strip().upper()


def _pan_part(gstin: str) -> str:
    """Characters 3 to 12, the PAN inside a GSTIN. Taken by position and not
    through `gstin.pan_of`, which refuses a GSTIN whose check digit is wrong —
    and a wrong check digit is precisely the case being looked for."""
    g = _norm_gstin(gstin)
    return g[2:12] if len(g) == _gstin.GSTIN_LENGTH else ""


def _date_relation(book: Optional[str], doc: Optional[str]) -> str:
    if not book or not doc:
        return _UNKNOWN
    return _EQUAL if str(book)[:10] == str(doc)[:10] else _DIFFERS


def _amount_relation(bill: BookBill, doc: PortalDocument) -> str:
    """exact: taxable and tax both equal, and not both nil (two zeroes agreeing
    is not a clue). band: both within the rupee. differs: anything else."""
    if bill.taxable_paise <= 0 or doc.taxable_paise <= 0:
        return _DIFFERS
    d_taxable = abs(bill.taxable_paise - doc.taxable_paise)
    d_tax = abs(bill.tax_paise - doc.tax_paise)
    if d_taxable == 0 and d_tax == 0:
        return _EXACT
    if d_taxable <= AMOUNT_BAND_PAISE and d_tax <= AMOUNT_BAND_PAISE:
        return _BAND
    return _DIFFERS


def _numbers_are_close(a: str, b: str) -> bool:
    fa, fb = normalise_document_number(a), normalise_document_number(b)
    if fa == fb or min(len(fa), len(fb)) < MIN_NUMBER_LENGTH_TO_COMPARE:
        return False
    limit = 1 if min(len(fa), len(fb)) <= SHORT_NUMBER_LENGTH else 2
    return edit_distance(fa, fb, limit) <= limit


# ── the three kinds ──────────────────────────────────────────────────────────

def _gstin_differs(bill: BookBill, doc: PortalDocument) -> Optional[Probable]:
    """Same folded number, different (or absent) GSTIN."""
    book_g, doc_g = _norm_gstin(bill.supplier_gstin), _norm_gstin(doc.supplier_gstin)
    if not doc_g or book_g == doc_g:
        return None
    if (normalise_document_number(bill.bill_no)
            != normalise_document_number(doc.document_number)):
        return None
    if not normalise_document_number(bill.bill_no):
        return None

    date = _date_relation(bill.bill_date, doc.document_date)
    amount = _amount_relation(bill, doc)
    evidence = [f"The document number is the same ({doc.document_number})."]

    if not book_g:
        related = False
        evidence.append(
            "The supplier on the bill has no GSTIN recorded, so the bill cannot "
            "be keyed to anything GSTR-2B carries.")
    else:
        distance = edit_distance(book_g, doc_g, GSTIN_TYPO_DISTANCE)
        same_pan = bool(_pan_part(book_g)) and _pan_part(book_g) == _pan_part(doc_g)
        related = distance <= GSTIN_TYPO_DISTANCE or same_pan
        if distance <= GSTIN_TYPO_DISTANCE:
            evidence.append(
                f"The GSTIN on the bill ({book_g}) is {distance} character(s) "
                f"from the one GSTR-2B carries ({doc_g}).")
        if same_pan:
            evidence.append(
                f"Both GSTINs contain the same PAN ({_pan_part(doc_g)}): the "
                f"same supplier under a different State registration.")
        if _gstin.problem_with(book_g) and not _gstin.problem_with(doc_g):
            evidence.append(
                "The GSTIN on the bill fails its own check digit and the one on "
                "GSTR-2B does not.")

    if date == _DIFFERS and not (related and amount == _EXACT):
        return None
    if not (related or amount == _EXACT):
        return None

    evidence.extend(_date_and_amount_evidence(bill, doc, date, amount))
    strong = (related or not book_g) and amount == _EXACT and date == _EQUAL
    if not book_g:
        action = (
            f"Record the GSTIN {doc_g} on the supplier ({doc.supplier_name or 'this supplier'}) "
            f"if it is theirs, then run the GSTR-2B reconciliation again.")
    else:
        action = (
            f"Check the supplier's GSTIN on the bill: the books say {book_g} and "
            f"GSTR-2B says {doc_g}. If GSTR-2B is right, correct the supplier "
            f"record and run the reconciliation again — do not chase the supplier.")
    return Probable(STRONG if strong else POSSIBLE, KIND_GSTIN, bill, doc,
                    tuple(evidence), action)


def _number_differs(bill: BookBill, doc: PortalDocument) -> Optional[Probable]:
    """Same GSTIN, a number within a typo of the supplier's."""
    book_g, doc_g = _norm_gstin(bill.supplier_gstin), _norm_gstin(doc.supplier_gstin)
    if not book_g or book_g != doc_g:
        return None
    if not _numbers_are_close(bill.bill_no, doc.document_number):
        return None
    date = _date_relation(bill.bill_date, doc.document_date)
    amount = _amount_relation(bill, doc)

    if amount == _EXACT and date == _EQUAL:
        grade = STRONG
    elif amount == _EXACT and date == _UNKNOWN:
        grade = POSSIBLE
    elif amount == _BAND and date == _EQUAL:
        grade = POSSIBLE
    else:
        return None

    evidence = [
        f"The supplier is the same ({doc_g}).",
        f"The number on the bill ({bill.bill_no}) is within a typing slip of the "
        f"one the supplier filed ({doc.document_number}).",
    ]
    evidence.extend(_date_and_amount_evidence(bill, doc, date, amount))
    action = (
        f"Check the bill number: the books say {bill.bill_no} and the supplier "
        f"filed {doc.document_number}. The number is the supplier's own, so if "
        f"theirs is right, correct the bill and run the reconciliation again.")
    return Probable(grade, KIND_NUMBER, bill, doc, tuple(evidence), action)


def _amount_and_date(bill: BookBill, doc: PortalDocument) -> Optional[Probable]:
    """Same GSTIN, same day, same amounts, a number nothing alike."""
    book_g, doc_g = _norm_gstin(bill.supplier_gstin), _norm_gstin(doc.supplier_gstin)
    if not book_g or book_g != doc_g:
        return None
    if (normalise_document_number(bill.bill_no)
            == normalise_document_number(doc.document_number)):
        return None
    if _numbers_are_close(bill.bill_no, doc.document_number):
        return None  # that is `document_number_differs`'s, with its own grade
    if (_date_relation(bill.bill_date, doc.document_date) != _EQUAL
            or _amount_relation(bill, doc) != _EXACT):
        return None
    evidence = [
        f"The supplier is the same ({doc_g}).",
        *_date_and_amount_evidence(
            bill, doc, _EQUAL, _EXACT),
        f"The numbers are unlike — the bill says {bill.bill_no or '(none)'} and "
        f"the supplier filed {doc.document_number}.",
    ]
    action = (
        f"Compare the two invoices: the same supplier filed a document dated "
        f"{doc.document_date} for the same amounts under number "
        f"{doc.document_number}. If it is the same invoice, correct the bill "
        f"number and run the reconciliation again; if not, both stand.")
    return Probable(POSSIBLE, KIND_AMOUNT, bill, doc, tuple(evidence), action)


def _date_and_amount_evidence(bill: BookBill, doc: PortalDocument,
                              date: str, amount: str) -> list[str]:
    out: list[str] = []
    if date == _EQUAL:
        out.append(f"The date is the same ({doc.document_date}).")
    elif date == _DIFFERS:
        out.append(f"The dates differ — the bill is dated {bill.bill_date} and "
                   f"the document {doc.document_date}.")
    else:
        out.append("One of the two documents carries no date, so the date could "
                   "not be compared.")
    if amount == _EXACT:
        out.append("The taxable value and the tax agree to the paisa.")
    elif amount == _BAND:
        out.append(
            "The taxable value and the tax are within ₹1 of each other — "
            "supplier rounding, if it is the same invoice.")
    else:
        out.append("The amounts differ.")
    return out


# ── the entry points ─────────────────────────────────────────────────────────

_KINDS = (_gstin_differs, _number_differs, _amount_and_date)
_RANK = {STRONG: 0, POSSIBLE: 1}


def suggest(rec: Reconciliation) -> list[Probable]:
    """Probable pairs among the reconciliation's two leftover lists.

    PURE, and it never mutates `rec`. A bill appears against every document it
    could be and a document against every bill — one-to-one is the CA's call,
    and picking a winner for them is the guess this module is here to avoid.
    Strongest first, then the larger credit, so the first row is the one most
    worth a look.
    """
    bills = [m.bill for m in rec.missing_in_2b if m.bill is not None]
    docs = [m.document for m in rec.missing_in_books
            if m.document is not None and m.document.document_type == "invoice"
            and m.document.supplier_gstin]
    return suggest_between(bills, docs)


def suggest_between(bills: Iterable[BookBill],
                    documents: Iterable[PortalDocument]) -> list[Probable]:
    bills, documents = list(bills), list(documents)

    # Candidate pairs come from two indexes and not a B x D scan: a client with
    # a few hundred unmatched documents on each side is the case this has to
    # survive, and the three kinds can each be reached from one of them.
    by_number: dict[str, list[PortalDocument]] = {}
    by_gstin: dict[str, list[PortalDocument]] = {}
    for d in documents:
        by_number.setdefault(normalise_document_number(d.document_number), []).append(d)
        by_gstin.setdefault(_norm_gstin(d.supplier_gstin), []).append(d)

    out: list[Probable] = []
    seen: set[tuple[str, int]] = set()
    for bill in bills:
        candidates: list[PortalDocument] = []
        candidates.extend(by_number.get(normalise_document_number(bill.bill_no), []))
        candidates.extend(by_gstin.get(_norm_gstin(bill.supplier_gstin), []))
        for doc in candidates:
            key = (bill.bill_id, id(doc))
            if key in seen:
                continue
            seen.add(key)
            for kind in _KINDS:
                got = kind(bill, doc)
                if got is not None:
                    out.append(got)
                    break  # one answer per pair — the first kind that fits
    out.sort(key=lambda p: (_RANK[p.grade], -p.bill.tax_paise,
                            p.bill.bill_no, p.document.document_number))
    return out
