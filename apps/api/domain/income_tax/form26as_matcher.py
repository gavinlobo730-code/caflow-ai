"""
Form 26AS ↔ books matching engine.

Form 26AS is the taxpayer's *credit* statement: it lists tax that OTHER people
deducted out of payments made TO this taxpayer (Part A/A1/A2 TDS, Part B TCS),
plus tax the taxpayer paid directly (Part C advance/self-assessment). It is
issued under IT Act s.285BB read with Rule 114-I. (The older s.203AA, which
several docstrings in this codebase still cite, was OMITTED by the Finance Act
2020 with effect from 01-06-2020 and replaced by s.285BB.)

Why the matching rules are shaped the way they are:

  * IT Act s.199(1) — credit for tax deducted is given to the person from whose
    income the deduction was made.
  * Rule 37BA(1) — that credit is given "on the basis of information relating to
    deduction of tax furnished by the deductor to the income-tax authority". The
    deductor's TDS return, surfaced as 26AS, is therefore the operative record.
    A credit sitting in the client's books that does NOT appear in 26AS is not
    claimable until the deductor corrects their return — which is the single
    most consequential thing a 26AS reconciliation can tell a CA, and the reason
    this engine reports the books→26AS direction as well as 26AS→books.
  * Booking status — TRACES marks each row F (final: challan matched), O
    (overbooked), U (unmatched: the deductor has not correctly deposited or
    quoted the challan) or P (provisional: government deductor, pending
    verification). Only F is a settled credit. s.205 bars a direct demand on the
    deductee for tax that WAS deducted, but that is a defence at assessment, not
    a credit in the return, so a non-final row is surfaced separately rather
    than being counted as clean.

This module is pure: it takes two lists and returns a result. It touches no
database, no clock and no environment, so mock mode and production run exactly
the same matching logic.

# CA REVIEW REQUIRED — reconciliation output must be reviewed before filing
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── Identity formats ───────────────────────────────────────────────────────────
# TAN: 4 alpha (3-letter city code + first letter of the deductor's name),
# 5 numeric, 1 alpha. It is NOT derivable from a PAN and shares no characters
# with one — which is why a books-side TAN has to be recorded, not computed.
TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# TRACES booking status: only 'F' is a final, claimable credit.
FINAL_BOOKING_STATUS = "F"

# Match bases, strongest first. The engine never falls back to "closest amount"
# with no identity agreement — that produces confident wrong answers.
BASIS_TAN = "tan"
BASIS_NAME = "name"

_LEGAL_FORM_EXPANSIONS = (
    # Abbreviation → expansion. Expanded (never dropped): "Acme Pvt Ltd" and
    # "Acme LLP" are different legal persons with different TANs, so collapsing
    # the legal form would merge two real deductors into one.
    (r"\bPVT\b", "PRIVATE"),
    (r"\bLTD\b", "LIMITED"),
    (r"\bCO\b", "COMPANY"),
    (r"\bCORP\b", "CORPORATION"),
    (r"\bINDIA\b", "INDIA"),
)


def normalise_tan(value: Optional[str]) -> Optional[str]:
    """Upper-case and strip a TAN, returning None unless it is well-formed.

    A malformed TAN is treated as ABSENT rather than as a matchable key, so two
    rows carrying the same typo do not match each other on it.
    """
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned if TAN_RE.match(cleaned) else None


def normalise_pan(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned if PAN_RE.match(cleaned) else None


def normalise_name(value: Optional[str]) -> str:
    """Case, punctuation and abbreviation normalisation only.

    Legal-form words are expanded to a canonical spelling but never removed —
    see _LEGAL_FORM_EXPANSIONS. Returns "" for a name that normalises to
    nothing, and "" never matches (see _index_by_name).
    """
    if not value:
        return ""
    text = re.sub(r"[^A-Za-z0-9&\s]", " ", value).upper()
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    for pattern, replacement in _LEGAL_FORM_EXPANSIONS:
        text = re.sub(pattern, replacement, text)
    return re.sub(r"\s+", " ", text).strip()


# ── Inputs ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Form26ASEntry:
    """One TDS/TCS row off the taxpayer's Form 26AS."""
    entry_id: str
    tds_paise: int
    deductor_name: str = ""
    deductor_tan: Optional[str] = None
    transaction_date: Optional[str] = None      # ISO yyyy-mm-dd
    amount_credited_paise: int = 0
    booking_status: Optional[str] = None
    part: Optional[str] = None
    record_type: Optional[str] = None

    @property
    def is_final(self) -> bool:
        """True only for TRACES booking status 'F'.

        A blank status is NOT assumed final: 26AS text pasted without the status
        column is missing the information, and reading absence as "settled" is
        the optimistic direction, which is the wrong way for a tax credit to
        fail.
        """
        return (self.booking_status or "").strip().upper() == FINAL_BOOKING_STATUS


@dataclass(frozen=True)
class BookCredit:
    """One TDS credit recorded in the client's books.

    This is tax deducted FROM the client by a customer — in this codebase it
    reaches the ledger as the `Dr TDS Receivable` leg of a receipt
    (services/phase2_journal_service.receipt_journal_lines). It is emphatically
    NOT a row of `tds_deductions`, which records tax the client deducted from
    ITS OWN vendors and which appears in the vendor's 26AS, never the client's.
    """
    credit_id: str
    tds_paise: int
    deductor_name: str = ""
    deductor_tan: Optional[str] = None
    deductor_pan: Optional[str] = None
    credit_date: Optional[str] = None           # ISO yyyy-mm-dd
    source: str = "receipt"
    reference: str = ""


# ── Outputs ────────────────────────────────────────────────────────────────────

# 26AS-side outcomes
STATUS_MATCHED = "matched"
STATUS_VARIANCE = "variance"
STATUS_MISSING_IN_BOOKS = "missing_in_books"
# books-side outcome
STATUS_NOT_IN_26AS = "not_in_26as"


@dataclass(frozen=True)
class EntryOutcome:
    entry_id: str
    status: str
    matched_credit_id: Optional[str] = None
    basis: Optional[str] = None
    variance_paise: int = 0                     # signed: 26AS minus books
    needs_confirmation: bool = False
    reason: str = ""


@dataclass(frozen=True)
class CreditOutcome:
    credit_id: str
    status: str
    matched_entry_id: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class DeductorSummary:
    """Per-deductor rollup — where a CA actually works.

    Quarterly 26AS rows rarely line up one-for-one with individual receipts, so
    the common real outcome is "this deductor's total agrees, the line detail
    does not". That is a materially different conversation from "this deductor's
    total is short", and the line-level statuses alone cannot tell them apart.
    """
    key: str
    label: str
    tan: Optional[str]
    entry_count: int
    credit_count: int
    total_26as_paise: int
    total_books_paise: int

    @property
    def variance_paise(self) -> int:
        """Signed: 26AS minus books. Positive = 26AS shows more than the books."""
        return self.total_26as_paise - self.total_books_paise


@dataclass(frozen=True)
class ReconciliationResult:
    entry_outcomes: list[EntryOutcome] = field(default_factory=list)
    credit_outcomes: list[CreditOutcome] = field(default_factory=list)
    by_deductor: list[DeductorSummary] = field(default_factory=list)

    # Totals are over the FULL populations on each side, never over the matched
    # subset — a "books total" that only counts matched rows makes the variance
    # agree with itself by construction.
    total_26as_paise: int = 0
    total_books_paise: int = 0

    @property
    def matched_count(self) -> int:
        return sum(1 for o in self.entry_outcomes if o.status == STATUS_MATCHED)

    @property
    def mismatch_count(self) -> int:
        return sum(1 for o in self.entry_outcomes if o.status == STATUS_VARIANCE)

    @property
    def missing_in_books_count(self) -> int:
        return sum(1 for o in self.entry_outcomes if o.status == STATUS_MISSING_IN_BOOKS)

    @property
    def not_in_26as_count(self) -> int:
        return sum(1 for o in self.credit_outcomes if o.status == STATUS_NOT_IN_26AS)

    @property
    def needs_confirmation_count(self) -> int:
        return sum(1 for o in self.entry_outcomes if o.needs_confirmation)

    @property
    def net_variance_paise(self) -> int:
        """Signed: 26AS minus books."""
        return self.total_26as_paise - self.total_books_paise

    @property
    def variance_paise(self) -> int:
        """Absolute variance — the figure the summary row and UI have always shown."""
        return abs(self.net_variance_paise)


def unsupported_credit_paise(result: ReconciliationResult,
                             credits: list[BookCredit]) -> int:
    """Book credits with no 26AS counterpart, in paise.

    Rule 37BA(1) gives credit on the basis of what the DEDUCTOR reported, so
    this is the amount the client cannot claim in the return as things stand —
    the deductor has to correct their TDS statement first. It is the number a CA
    needs before filing, and the previous implementation never computed it
    because it only ever iterated the 26AS side.
    """
    by_id = {c.credit_id: c for c in credits}
    return sum(
        by_id[o.credit_id].tds_paise
        for o in result.credit_outcomes
        if o.status == STATUS_NOT_IN_26AS and o.credit_id in by_id
    )


def provisional_credit_paise(entries: list[Form26ASEntry]) -> int:
    """TDS on 26AS rows whose TRACES booking status is not 'F' (final).

    The deductor has reported the deduction but the challan is unmatched,
    overbooked or provisional, so the credit is not settled. s.205 protects the
    deductee from a direct demand, but that is an assessment defence, not a
    credit available in the return.
    """
    return sum(e.tds_paise for e in entries if not e.is_final)


# ── The engine ─────────────────────────────────────────────────────────────────

def _entry_sort_key(entry: Form26ASEntry) -> tuple:
    return (entry.transaction_date or "", entry.entry_id)


def _date_distance(a: Optional[str], b: Optional[str]) -> int:
    """Crude ISO-date proximity, in days, used only to break ties.

    Returns a large sentinel when either date is missing so a dated candidate is
    always preferred to an undated one. Parsed by hand rather than via datetime
    because a malformed date must degrade to "unknown", not raise.
    """
    from datetime import date as _date
    def _parse(s: Optional[str]) -> Optional[_date]:
        if not s:
            return None
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(s))
        if not m:
            return None
        try:
            return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    da, db = _parse(a), _parse(b)
    if da is None or db is None:
        return 10 ** 6
    return abs((da - db).days)


def _candidate_sort_key(entry: Form26ASEntry, credit: BookCredit) -> tuple:
    """Deterministic pick when several credits qualify: nearest date, then id."""
    return (_date_distance(entry.transaction_date, credit.credit_date), credit.credit_id)


def reconcile(
    entries: list[Form26ASEntry],
    credits: list[BookCredit],
    tolerance_paise: int = 0,
) -> ReconciliationResult:
    """Match 26AS rows against book credits, one-to-one, on identity first.

    Passes, in order — every pass consumes the credits it matches, so no book
    credit can be claimed by two 26AS rows:

      1. TAN agrees AND amount agrees (within tolerance)  → matched
      2. name agrees AND amount agrees                    → matched, confirm
      3. TAN agrees, amount differs                       → variance
      4. name agrees, amount differs                      → variance, confirm

    Exact-amount passes run before any variance pass so a weaker "amount
    differs" match cannot steal a credit that another row matches exactly.
    Anything left on the 26AS side is missing_in_books; anything left on the
    books side is not_in_26as.

    `tolerance_paise` defaults to 0 — a threshold that silently absorbs
    differences is a worse default than a small variance the CA can see and
    dismiss.
    """
    tolerance = max(0, int(tolerance_paise))
    ordered_entries = sorted(entries, key=_entry_sort_key)

    consumed: set[str] = set()
    outcomes: dict[str, EntryOutcome] = {}
    matched_credit_to_entry: dict[str, str] = {}

    def _pool(entry: Form26ASEntry, basis: str) -> list[BookCredit]:
        if basis == BASIS_TAN:
            tan = normalise_tan(entry.deductor_tan)
            if not tan:
                return []
            return [c for c in credits
                    if c.credit_id not in consumed and normalise_tan(c.deductor_tan) == tan]
        name = normalise_name(entry.deductor_name)
        if not name:
            return []
        return [c for c in credits
                if c.credit_id not in consumed and normalise_name(c.deductor_name) == name]

    def _run_pass(basis: str, require_amount: bool) -> None:
        needs_confirmation = basis == BASIS_NAME
        for entry in ordered_entries:
            if entry.entry_id in outcomes:
                continue
            pool = _pool(entry, basis)
            if require_amount:
                pool = [c for c in pool if abs(c.tds_paise - entry.tds_paise) <= tolerance]
            if not pool:
                continue
            best = min(pool, key=lambda c: _candidate_sort_key(entry, c))
            consumed.add(best.credit_id)
            matched_credit_to_entry[best.credit_id] = entry.entry_id
            variance = entry.tds_paise - best.tds_paise
            if require_amount:
                outcomes[entry.entry_id] = EntryOutcome(
                    entry_id=entry.entry_id,
                    status=STATUS_MATCHED,
                    matched_credit_id=best.credit_id,
                    basis=basis,
                    variance_paise=variance,
                    needs_confirmation=needs_confirmation,
                    reason=("Matched on deductor name and amount — confirm the TAN"
                            if needs_confirmation else "Matched on deductor TAN and amount"),
                )
            else:
                outcomes[entry.entry_id] = EntryOutcome(
                    entry_id=entry.entry_id,
                    status=STATUS_VARIANCE,
                    matched_credit_id=best.credit_id,
                    basis=basis,
                    variance_paise=variance,
                    needs_confirmation=needs_confirmation,
                    reason=(
                        f"Amount differs by {_rupees(abs(variance))} "
                        f"({'26AS higher' if variance > 0 else 'books higher'})"
                    ),
                )

    _run_pass(BASIS_TAN, require_amount=True)
    _run_pass(BASIS_NAME, require_amount=True)
    _run_pass(BASIS_TAN, require_amount=False)
    _run_pass(BASIS_NAME, require_amount=False)

    for entry in ordered_entries:
        if entry.entry_id in outcomes:
            continue
        outcomes[entry.entry_id] = EntryOutcome(
            entry_id=entry.entry_id,
            status=STATUS_MISSING_IN_BOOKS,
            reason=("No TDS credit in the books for this deductor — the income "
                    "may be unrecorded, or recorded without its TDS leg"),
        )

    credit_outcomes = [
        CreditOutcome(
            credit_id=c.credit_id,
            status=STATUS_MATCHED,
            matched_entry_id=matched_credit_to_entry[c.credit_id],
            reason="Matched to a 26AS row",
        )
        if c.credit_id in matched_credit_to_entry else
        CreditOutcome(
            credit_id=c.credit_id,
            status=STATUS_NOT_IN_26AS,
            reason=("Not reported by the deductor in 26AS — not claimable under "
                    "Rule 37BA(1) until the deductor corrects their TDS statement"),
        )
        for c in credits
    ]

    return ReconciliationResult(
        entry_outcomes=[outcomes[e.entry_id] for e in ordered_entries],
        credit_outcomes=credit_outcomes,
        by_deductor=_rollup(entries, credits),
        total_26as_paise=sum(e.tds_paise for e in entries),
        total_books_paise=sum(c.tds_paise for c in credits),
    )


def _rupees(paise: int) -> str:
    """Format paise as rupees for a human-readable reason string.

    Sign is carried by the caller's wording, so this formats the magnitude —
    integer division on a negative paise value would floor, not truncate.
    """
    magnitude = abs(int(paise))
    return f"₹{magnitude // 100}.{magnitude % 100:02d}"


def _rollup(entries: list[Form26ASEntry],
            credits: list[BookCredit]) -> list[DeductorSummary]:
    """Group both sides by TAN where available, else by normalised name."""
    buckets: dict[str, dict] = {}

    def _bucket(tan: Optional[str], name: str, label: str) -> dict:
        key = f"tan:{tan}" if tan else (f"name:{name}" if name else "unidentified")
        b = buckets.setdefault(key, {
            "key": key, "label": label or "(unidentified)", "tan": tan,
            "entry_count": 0, "credit_count": 0,
            "total_26as_paise": 0, "total_books_paise": 0,
        })
        # A bucket first seen from an unnamed row still gets a label later.
        if b["label"] == "(unidentified)" and label:
            b["label"] = label
        if b["tan"] is None and tan:
            b["tan"] = tan
        return b

    for e in entries:
        b = _bucket(normalise_tan(e.deductor_tan), normalise_name(e.deductor_name),
                    (e.deductor_name or "").strip())
        b["entry_count"] += 1
        b["total_26as_paise"] += e.tds_paise
    for c in credits:
        b = _bucket(normalise_tan(c.deductor_tan), normalise_name(c.deductor_name),
                    (c.deductor_name or "").strip())
        b["credit_count"] += 1
        b["total_books_paise"] += c.tds_paise

    return [
        DeductorSummary(
            key=b["key"], label=b["label"], tan=b["tan"],
            entry_count=b["entry_count"], credit_count=b["credit_count"],
            total_26as_paise=b["total_26as_paise"],
            total_books_paise=b["total_books_paise"],
        )
        for b in sorted(buckets.values(), key=lambda x: (-abs(x["total_26as_paise"] - x["total_books_paise"]), x["key"]))
    ]
