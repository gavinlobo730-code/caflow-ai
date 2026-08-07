"""
Finding the document the ranking missed (Tier 1.6).

WHY A SEARCH AND NOT JUST A LONGER LIST
    `rank_suggestions` offers the best five candidates within an amount band. It
    is right most of the time and useless the rest: when the bank line is
    ₹90,000 against a ₹1,00,000 invoice AND the customer also withheld a
    disputed amount, or when the settlement is against a document from four
    months ago, the right answer is simply not in the band. Today there is no
    way to reach it — a CA who KNOWS the invoice number cannot type it in.

    So this is the same candidate model with the amount band LIFTED and text,
    date and party filters added. Lengthening the ranked list would not help:
    the problem is not that the answer ranked sixth, it is that it was never
    fetched.

WHAT IS A FILTER AND WHAT IS A RULE
    A filter is the CA narrowing what they see. A rule is something the system
    must not offer whatever they type. Direction is a RULE: money arriving in
    the bank cannot settle a purchase bill, and showing one because the search
    box was empty would invite a wrong match that balances. The caller may
    narrow within what direction allows; it cannot widen past it.

    Fully-paid, draft, cancelled and soft-deleted documents are rules too — a
    draft invoice was never issued, so no journal exists for a bank line to
    settle against.

RANKING WITHOUT A BAND
    With the band gone, "closest amount" stops being a near-tautology and starts
    doing real work, so results are ordered by: exact amount first, then the
    smallest shortfall, then date proximity to the bank line. The TDS shape is
    still labelled, because that is the whole reason a short match is legitimate
    in India.

Pure and side-effect free. Integer paise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from .matcher import Candidate, detect_tds_rate_bps

# What each direction of a bank line can legitimately settle. Not a filter — a
# rule. See the module docstring.
CREDIT_TYPES = ("sales_invoice", "receipt", "journal_entry")
DEBIT_TYPES = ("purchase_bill", "purchase_payment", "journal_entry")

MAX_RESULTS = 100


def allowed_types(is_credit: bool) -> tuple[str, ...]:
    return CREDIT_TYPES if is_credit else DEBIT_TYPES


@dataclass(frozen=True)
class CandidateHit:
    """One search result, annotated the same way a ranked suggestion is.

    `difference_paise` is candidate − bank: 0 when they agree, positive when the
    bank line is SHORT of the document (the TDS / bank-charge shape). Negative
    means the bank line is LARGER, which is a real possibility once the band is
    lifted and which the UI must show rather than hide.
    """
    entity_type: str
    entity_id: str
    label: str
    amount_paise: int
    entity_date: Optional[str]
    party_name: Optional[str]
    party_id: Optional[str]
    outstanding_paise: Optional[int]
    difference_paise: int
    tds_rate_bps: Optional[int]

    @property
    def is_exact(self) -> bool:
        return self.difference_paise == 0

    @property
    def bank_line_is_short(self) -> bool:
        return self.difference_paise > 0


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _matches_text(c: Candidate, needle: str) -> bool:
    hay = " ".join(str(x or "") for x in (c.label, c.party_name, c.entity_id))
    return needle in hay.lower()


def search(candidates: Iterable[Candidate], *, bank_amount_paise: int,
           bank_date=None, is_credit: bool,
           q: Optional[str] = None,
           date_from: Optional[str] = None, date_to: Optional[str] = None,
           min_amount_paise: Optional[int] = None,
           max_amount_paise: Optional[int] = None,
           entity_type: Optional[str] = None,
           party_id: Optional[str] = None,
           limit: int = 25, offset: int = 0) -> tuple[list[CandidateHit], int]:
    """Filter, annotate and rank. Returns (page, total_matching).

    The total is of everything matching, not of the page — a CA needs to know
    that narrowing further would help, and a page count alone does not say that.
    """
    permitted = set(allowed_types(is_credit))
    needle = (q or "").strip().lower()
    d_from, d_to = _as_date(date_from), _as_date(date_to)
    bank_d = _as_date(bank_date)

    hits: list[CandidateHit] = []
    for c in candidates:
        # RULE, not filter: direction decides what can be settled at all.
        if c.entity_type not in permitted:
            continue
        # The caller may narrow WITHIN what direction allows, never past it.
        if entity_type and c.entity_type != entity_type:
            continue
        if party_id and c.party_id != party_id:
            continue
        if needle and not _matches_text(c, needle):
            continue
        cd = _as_date(c.entity_date)
        if d_from and (cd is None or cd < d_from):
            continue
        if d_to and (cd is None or cd > d_to):
            continue
        if min_amount_paise is not None and c.amount_paise < min_amount_paise:
            continue
        if max_amount_paise is not None and c.amount_paise > max_amount_paise:
            continue

        difference = c.amount_paise - int(bank_amount_paise)
        hits.append(CandidateHit(
            entity_type=c.entity_type, entity_id=c.entity_id, label=c.label,
            amount_paise=c.amount_paise, entity_date=c.entity_date,
            party_name=c.party_name, party_id=c.party_id,
            outstanding_paise=c.outstanding_paise,
            difference_paise=difference,
            # Only a SHORTFALL can be TDS — the bank line being LARGER than the
            # document is not a deduction, it is a different transaction. That
            # rule lives in detect_tds_rate_bps, which returns None for a
            # non-positive shortfall; repeating it here would be a second copy
            # to keep in step. test_a_bank_line_LARGER_..._is_never_called_tds
            # pins the behaviour from this side.
            tds_rate_bps=detect_tds_rate_bps(c.amount_paise, difference),
        ))

    def rank(h: CandidateHit):
        cd = _as_date(h.entity_date)
        day_gap = abs((cd - bank_d).days) if (cd and bank_d) else 10_000
        # Smallest gap either way, then the nearest date, then entity_id so the
        # order is total and two identical searches never disagree (without the
        # last term, paging could silently repeat or drop a row).
        #
        # No separate "exact first" term: an exact match has |difference| == 0,
        # which is already the minimum, so a flag would only restate it.
        return (abs(h.difference_paise), day_gap, h.entity_id)

    hits.sort(key=rank)
    total = len(hits)
    start = max(0, int(offset))
    size = max(1, min(int(limit), MAX_RESULTS))
    return hits[start:start + size], total


def describe(hit: CandidateHit) -> str:
    """Why this row is being offered, in words a CA can check."""
    if hit.is_exact:
        return "Exact amount"
    if hit.bank_line_is_short:
        if hit.tds_rate_bps is not None:
            return (f"Bank line is short by {_rupees(hit.difference_paise)} — "
                    f"consistent with {hit.tds_rate_bps / 100:g}% TDS")
        return f"Bank line is short by {_rupees(hit.difference_paise)}"
    return f"Bank line is larger by {_rupees(-hit.difference_paise)}"


def _rupees(paise: int) -> str:
    """Display only — never fed back into arithmetic."""
    p = abs(int(paise))
    return f"₹{p // 100:,}.{p % 100:02d}"
