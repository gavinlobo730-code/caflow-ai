"""Form 26AS against the register, in the DEDUCTOR direction (TDS-21).

WHAT THIS ANSWERS, AND WHY IT IS NOT THE OTHER ONE

    A CA reconciles Form 26AS twice a year in two opposite directions, and they
    are different questions with different identities and opposite parties.

      * CLIENT AS DEDUCTEE — tax somebody else withheld FROM the client, which
        the client claims as a credit. Identity is the DEDUCTOR's TAN or name.
        `domain/income_tax/form26as_matcher.py` is that one and stays that one.
      * CLIENT AS DEDUCTOR — tax the client withheld from its OWN vendors,
        which shows in each vendor's 26AS under the client's TAN. Identity is
        the DEDUCTEE's PAN and the section. This module.

    Reusing the deductee matcher for this would mean putting a deductee's PAN
    into a field called `deductor_tan`, so every field name would say the
    opposite of what it holds — and its outcome sentences name the wrong party:
    "the deductor has not filed" is about somebody else there and about THIS
    CLIENT here. What transfers is the discipline, not the vocabulary:

      1. an exact-amount pass runs before any variance pass, so a weaker
         "amount differs" match cannot steal a row another matches exactly;
      2. every pass CONSUMES, so one 26AS row cannot be claimed twice; and
      3. totals are over the FULL population on each side, never the matched
         subset — a "books total" counting only matched rows makes the variance
         agree with itself by construction.

WHAT WAS THERE BEFORE

    `routers/tds_workspace.py::upload_form26as` built
    `{(pan, section): entry}` as a dict comprehension and compared every book
    row against that. Three consequences, all silent:

      * a quarter with TWO deductions for one vendor under one section keeps
        only the LAST 26AS row, and the earlier book row is then reported as an
        amount mismatch against a row that is not its counterpart;
      * nothing is consumed, so one 26AS row "matches" any number of book rows;
      * there was NO 26AS-side leftover at all. A row the portal shows and the
        register does not carry was never reported, and that is the direction
        where the client's own register is short.

WHY A MISSING PAN IS NOT MATCHED

    26AS is keyed on the deductee's PAN. A book row without one cannot be
    looked up in it, and matching two blank-PAN rows on section and amount
    would be a guess about which vendor — precisely the guess §206AA exists
    because nobody should make. Those rows are reported in their own bucket,
    named, and counted in the totals like any other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 26AS-side outcomes
STATUS_MATCHED = "matched"
STATUS_VARIANCE = "variance"
STATUS_MISSING_IN_BOOKS = "missing_in_books"
# books-side outcomes
STATUS_MISSING_IN_26AS = "missing_in_26as"
STATUS_NO_PAN = "no_pan"


def normalise_pan(value: Optional[str]) -> str:
    """Upper-cased and stripped, or "" where there is nothing usable.

    "PANNOTAVBL" is the placeholder TRACES and the FVU use for a deductee who
    gave no PAN. It is not an identity — every such deductee shares it — so it
    reads as absent here, which routes the row to STATUS_NO_PAN rather than
    matching it against another stranger's row.
    """
    pan = (value or "").strip().upper()
    return "" if pan in ("", "PANNOTAVBL", "PANAPPLIED", "PANINVALID") else pan


def normalise_section(value: Optional[str]) -> str:
    return (value or "").strip().upper()


@dataclass(frozen=True)
class PortalEntry:
    """One row the CLIENT's own deduction produced in a deductee's Form 26AS."""
    entry_id: str
    deductee_pan: str
    section: str
    tds_paise: int
    deductee_name: str = ""
    transaction_date: Optional[str] = None

    @property
    def key(self) -> tuple[str, str]:
        return (normalise_pan(self.deductee_pan), normalise_section(self.section))


@dataclass(frozen=True)
class BookDeduction:
    """One `tds_deductions` row — tax this client withheld from a vendor."""
    deduction_id: str
    deductee_pan: str
    section: str
    tds_paise: int
    deductee_name: str = ""
    transaction_date: Optional[str] = None
    document_no: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (normalise_pan(self.deductee_pan), normalise_section(self.section))


@dataclass(frozen=True)
class EntryOutcome:
    entry_id: str
    status: str
    deductee_pan: str
    section: str
    matched_deduction_id: Optional[str] = None
    form26as_paise: int = 0
    book_paise: int = 0
    reason: str = ""

    @property
    def diff_paise(self) -> int:
        """Signed: 26AS minus books. Positive = the portal shows more."""
        return self.form26as_paise - self.book_paise


@dataclass(frozen=True)
class DeductionOutcome:
    deduction_id: str
    status: str
    deductee_pan: str
    section: str
    book_paise: int = 0
    reason: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    entry_outcomes: list[EntryOutcome] = field(default_factory=list)
    deduction_outcomes: list[DeductionOutcome] = field(default_factory=list)
    total_26as_paise: int = 0
    total_books_paise: int = 0

    def _entries(self, status: str) -> list[EntryOutcome]:
        return [o for o in self.entry_outcomes if o.status == status]

    def _deductions(self, status: str) -> list[DeductionOutcome]:
        return [o for o in self.deduction_outcomes if o.status == status]

    @property
    def matched_count(self) -> int:
        return len(self._entries(STATUS_MATCHED))

    @property
    def mismatch_count(self) -> int:
        return len(self._entries(STATUS_VARIANCE))

    @property
    def missing_in_books_count(self) -> int:
        return len(self._entries(STATUS_MISSING_IN_BOOKS))

    @property
    def missing_in_26as_count(self) -> int:
        return len(self._deductions(STATUS_MISSING_IN_26AS))

    @property
    def no_pan_count(self) -> int:
        return len(self._deductions(STATUS_NO_PAN))

    @property
    def net_variance_paise(self) -> int:
        """Signed: 26AS minus books, over the FULL population on each side."""
        return self.total_26as_paise - self.total_books_paise


_MISSING_IN_BOOKS = (
    "The portal shows this deduction under the client's TAN and the register "
    "does not carry it. Either it was deducted outside PracticeSync, or it "
    "belongs to another deductee — check the PAN before adding it."
)
_MISSING_IN_26AS = (
    "The register carries this deduction and the portal does not show it. The "
    "quarterly statement is unfiled, still processing, or was filed with a "
    "different PAN — until it appears the DEDUCTEE cannot claim the credit."
)
_NO_PAN = (
    "This deduction has no deductee PAN, so there is nothing to look it up by: "
    "Form 26AS is keyed on the deductee's PAN. Record the PAN (s.206AA charges "
    "20% without one) and reconcile again."
)


def _variance_reason(entry: PortalEntry, book: BookDeduction) -> str:
    return (
        f"The portal shows {entry.tds_paise} paise and the register "
        f"{book.tds_paise}. One of the two is wrong: a short deposit is "
        "s.201(1A) interest, and an over-stated statement gives the deductee "
        "a credit the client never paid."
    )


def reconcile(entries: list[PortalEntry],
              deductions: list[BookDeduction]) -> ReconciliationResult:
    """Match portal rows against register rows, one-to-one, on PAN and section.

    Exact amount first, then variance, both consuming — see the module
    docstring for why that order and why consumption matters.
    """
    unconsumed: dict[tuple[str, str], list[BookDeduction]] = {}
    no_pan: list[BookDeduction] = []
    for d in deductions:
        if not normalise_pan(d.deductee_pan):
            no_pan.append(d)
            continue
        unconsumed.setdefault(d.key, []).append(d)

    entry_outcomes: list[EntryOutcome] = []
    matched_ids: set[str] = set()

    def _take(entry: PortalEntry, exact: bool) -> Optional[BookDeduction]:
        pool = [d for d in unconsumed.get(entry.key, [])
                if d.deduction_id not in matched_ids]
        if not pool:
            return None
        if exact:
            hit = next((d for d in pool if d.tds_paise == entry.tds_paise), None)
        else:
            # The closest by amount, so two variances against one identity do
            # not cross over and report two larger differences than they are.
            hit = min(pool, key=lambda d: (abs(d.tds_paise - entry.tds_paise),
                                           d.deduction_id))
        if hit is not None:
            matched_ids.add(hit.deduction_id)
        return hit

    # Sorted so the answer does not depend on the order the caller happened to
    # paste the rows in — two entries with one identity must resolve the same
    # way every run.
    ordered = sorted(entries, key=lambda e: (e.key, e.tds_paise, e.entry_id))
    pending: list[PortalEntry] = []
    for e in ordered:
        hit = _take(e, exact=True)
        if hit is None:
            pending.append(e)
            continue
        entry_outcomes.append(EntryOutcome(
            entry_id=e.entry_id, status=STATUS_MATCHED,
            deductee_pan=normalise_pan(e.deductee_pan),
            section=normalise_section(e.section),
            matched_deduction_id=hit.deduction_id,
            form26as_paise=e.tds_paise, book_paise=hit.tds_paise))

    for e in pending:
        hit = _take(e, exact=False)
        if hit is None:
            entry_outcomes.append(EntryOutcome(
                entry_id=e.entry_id, status=STATUS_MISSING_IN_BOOKS,
                deductee_pan=normalise_pan(e.deductee_pan),
                section=normalise_section(e.section),
                form26as_paise=e.tds_paise, reason=_MISSING_IN_BOOKS))
            continue
        entry_outcomes.append(EntryOutcome(
            entry_id=e.entry_id, status=STATUS_VARIANCE,
            deductee_pan=normalise_pan(e.deductee_pan),
            section=normalise_section(e.section),
            matched_deduction_id=hit.deduction_id,
            form26as_paise=e.tds_paise, book_paise=hit.tds_paise,
            reason=_variance_reason(e, hit)))

    deduction_outcomes = [
        DeductionOutcome(deduction_id=d.deduction_id, status=STATUS_NO_PAN,
                         deductee_pan="", section=normalise_section(d.section),
                         book_paise=d.tds_paise, reason=_NO_PAN)
        for d in no_pan
    ] + [
        DeductionOutcome(deduction_id=d.deduction_id,
                         status=STATUS_MISSING_IN_26AS,
                         deductee_pan=normalise_pan(d.deductee_pan),
                         section=normalise_section(d.section),
                         book_paise=d.tds_paise, reason=_MISSING_IN_26AS)
        for pool in unconsumed.values() for d in pool
        if d.deduction_id not in matched_ids
    ]

    return ReconciliationResult(
        entry_outcomes=sorted(entry_outcomes, key=lambda o: (o.deductee_pan,
                                                            o.section,
                                                            o.entry_id)),
        deduction_outcomes=sorted(deduction_outcomes,
                                  key=lambda o: (o.status, o.deductee_pan,
                                                 o.section, o.deduction_id)),
        # The FULL population on each side. Everything the portal showed, and
        # everything the register holds — the no-PAN rows included, because
        # they are real tax the client withheld.
        total_26as_paise=sum(e.tds_paise for e in entries),
        total_books_paise=sum(d.tds_paise for d in deductions),
    )
