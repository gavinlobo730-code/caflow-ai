"""
Bank transaction match suggestion engine (Banking B.2.1) — SUGGESTIONS ONLY.

Given an unmatched bank transaction and a set of candidate entities (open sales
invoices / purchase bills / receipts / payments / journal entries), produce a
RANKED list of suggestions with a confidence score. No posting, no DB access —
the service fetches candidates and calls the pure ranker here, which keeps the
scoring logic unit-testable.

Confidence methodology (0–100):
  • Exact amount: base = 50.
  • SHORT amount (candidate larger than the bank line, within the near-match
    band): base = 25, and the shortfall is reported. See below.
  • Date proximity:  same day +30, ≤3d +20, ≤7d +10, ≤30d +5.
  • Same customer/vendor (party name appears in the narration): +15.
  • Candidate's outstanding balance equals the amount (open invoice/bill): +15.
  • Settlement entities (invoice/bill) rank above a bare journal candidate: +5.
  • Shortfall that is exactly a common TDS rate on the candidate: +20.
Labels: high ≥ 80, medium ≥ 50, else low. A non-exact amount is capped below the
"high" threshold, so "high confidence" continues to mean the amounts agree.

WHY SHORT AMOUNTS ARE RANKED, NOT FILTERED
    This used to be an exact-amount GATE: `if c.amount_paise != txn_amount_paise:
    continue`. That is wrong for the single most common receipt in Indian
    practice — a customer settles a ₹1,00,000 invoice, withholds 10% TDS under
    s.194J, and remits ₹90,000. The invoice is settled in full; only the cash is
    short. Under the gate that transaction returned ZERO suggestions, so the one
    correct answer was the one answer the CA never saw.

    Short candidates are now ranked below exact ones and carry an explicit
    `difference_paise` plus a reason, so the CA sees the shortfall rather than
    having it silently applied. Accepting the match still goes through the normal
    settlement path, where the TDS amount is entered explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .narration import parse_narration, party_matches

# How far below a candidate's amount a bank line may fall and still be offered.
# 25% comfortably covers the highest routine withholding (20% under s.206AA)
# plus bank charges, without pulling in unrelated documents.
NEAR_MATCH_BAND_BPS = 2500

# Common TDS rates in basis points, withheld by the PAYER under Chapter XVII-B of
# the Income-tax Act, 1961: 0.1% (s.194Q, s.194-O), 1% and 2% (s.194C), 2%
# (s.194J — technical services), 5% (s.194H, s.194-I(a)), 10% (s.194J,
# s.194-I(b)), 20% (s.206AA — deductee has furnished no PAN).
#
# This list RECOGNISES the shape of a shortfall so it can be labelled. It never
# computes a liability and never decides a rate — the actual TDS figure is
# entered by the CA at settlement.
TDS_RATES_BPS: tuple[int, ...] = (10, 100, 200, 500, 1000, 2000)

# Deductors routinely round the withheld amount to whole rupees, so an exact
# basis-point match is not expected. ±₹1 absorbs that without admitting
# shortfalls that have nothing to do with TDS.
TDS_TOLERANCE_PAISE = 100

# A non-exact amount can never reach the "high" band (≥ 80).
NEAR_MATCH_CONFIDENCE_CAP = 75


@dataclass(frozen=True)
class Candidate:
    entity_type: str            # sales_invoice | purchase_bill | receipt | purchase_payment | journal_entry
    entity_id: str
    label: str                  # human label (e.g. "INV-2526-0001 · Acme Pvt Ltd")
    amount_paise: int
    entity_date: Optional[str] = None      # ISO
    party_name: Optional[str] = None
    party_id: Optional[str] = None         # customer / vendor id, for deep-linking
    outstanding_paise: Optional[int] = None


@dataclass
class Suggestion:
    entity_type: str
    entity_id: str
    label: str
    amount_paise: int
    confidence: int
    confidence_label: str
    reasons: list[str] = field(default_factory=list)
    # Lets the UI open the settlement modal already on the right party/document
    # instead of making the CA re-find what we just showed them.
    party_id: Optional[str] = None
    outstanding_paise: Optional[int] = None
    # candidate amount − bank amount. 0 when they agree; positive when the bank
    # line is SHORT of the document (the TDS / bank-charge shape).
    difference_paise: int = 0
    # The TDS rate the shortfall is consistent with, in basis points (None if it
    # doesn't look like TDS). A LABEL, never an instruction to deduct.
    tds_rate_bps: Optional[int] = None


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except Exception:
        return None


def _confidence_label(score: int) -> str:
    return "high" if score >= 80 else "medium" if score >= 50 else "low"


def _rupees(paise: int) -> str:
    """Display-only rupee rendering for a reason string. Integer paise in, never
    used for arithmetic."""
    return f"₹{int(paise) // 100:,}.{abs(int(paise)) % 100:02d}"


def _rate_label(rate_bps: int) -> str:
    """'1000' -> '10%', '10' -> '0.1%'. Display only."""
    whole, frac = divmod(int(rate_bps), 100)
    return f"{whole}%" if frac == 0 else f"{whole + frac / 100:g}%"


def near_match_floor_paise(candidate_amount_paise: int) -> int:
    """Lowest bank amount that may still be offered against `candidate_amount_paise`.

    Integer paise throughout (CLAUDE.md) — the band is applied in basis points and
    floor-divided, never via float percentages.
    """
    amount = int(candidate_amount_paise)
    if amount <= 0:
        return 0
    return amount - (amount * NEAR_MATCH_BAND_BPS) // 10000


def detect_tds_rate_bps(candidate_amount_paise: int, shortfall_paise: int) -> Optional[int]:
    """The TDS rate (bps) `shortfall_paise` is consistent with, or None.

    Compares the shortfall against each common rate applied to the candidate,
    allowing TDS_TOLERANCE_PAISE for whole-rupee rounding by the deductor. Returns
    the closest matching rate when several are within tolerance (only possible for
    very small amounts). Recognition only — this computes no liability.
    """
    amount = int(candidate_amount_paise)
    shortfall = int(shortfall_paise)
    if amount <= 0 or shortfall <= 0:
        return None
    best: Optional[int] = None
    best_delta: Optional[int] = None
    for rate_bps in TDS_RATES_BPS:
        expected = (amount * rate_bps) // 10000
        delta = abs(shortfall - expected)
        if delta <= TDS_TOLERANCE_PAISE and (best_delta is None or delta < best_delta):
            best, best_delta = rate_bps, delta
    return best


def rank_suggestions(
    txn_amount_paise: int,
    txn_date: Optional[str],
    narration: Optional[str],
    candidates: list[Candidate],
    max_results: int = 5,
) -> list[Suggestion]:
    parsed = parse_narration(narration)
    out: list[Suggestion] = []
    for c in candidates:
        difference = int(c.amount_paise) - int(txn_amount_paise)
        tds_rate_bps: Optional[int] = None

        if difference == 0:
            score, reasons = 50, ["exact amount"]
        elif difference > 0 and txn_amount_paise >= near_match_floor_paise(c.amount_paise):
            # Bank line is short of the document but within the near-match band.
            score, reasons = 25, [f"short by {_rupees(difference)}"]
            tds_rate_bps = detect_tds_rate_bps(c.amount_paise, difference)
            if tds_rate_bps is not None:
                score += 20
                reasons.append(f"shortfall = {_rate_label(tds_rate_bps)} TDS")
        else:
            # Over the document, or short by more than the band allows — not a
            # settlement of this document.
            continue

        days = _days_between(txn_date, c.entity_date)
        if days is not None:
            if days == 0:
                score += 30; reasons.append("same date")
            elif days <= 3:
                score += 20; reasons.append(f"within {days}d")
            elif days <= 7:
                score += 10; reasons.append(f"within {days}d")
            elif days <= 30:
                score += 5; reasons.append(f"within {days}d")

        # Party recognition now goes through the narration parser, which
        # normalises entity suffixes and compares the counterparty the bank
        # actually printed. The old test was `party_name.lower() in narration`,
        # so "Acme Pvt Ltd" never matched a narration reading "ACME PRIVATE
        # LIMITED" — a perfectly good match that simply never surfaced.
        # party_matches keeps that substring test as its first branch, so
        # nothing that matched before stops matching.
        if c.party_name and c.party_name.strip() and party_matches(c.party_name, parsed):
            score += 15
            reasons.append("party in narration")

        if c.outstanding_paise is not None and c.outstanding_paise == txn_amount_paise:
            score += 15; reasons.append("matches outstanding balance")

        if c.entity_type in ("sales_invoice", "purchase_bill"):
            score += 5; reasons.append("open document")

        # "high" must keep meaning "the amounts agree", so a short match is
        # capped below the high band no matter how much corroboration it gathers.
        score = min(score, 100 if difference == 0 else NEAR_MATCH_CONFIDENCE_CAP)
        out.append(Suggestion(
            entity_type=c.entity_type, entity_id=c.entity_id, label=c.label,
            amount_paise=c.amount_paise, confidence=score,
            confidence_label=_confidence_label(score), reasons=reasons,
            party_id=c.party_id, outstanding_paise=c.outstanding_paise,
            difference_paise=difference, tds_rate_bps=tds_rate_bps,
        ))

    # Highest confidence first; exact amounts ahead of short ones at equal
    # confidence; settlement docs tie-break ahead of journals.
    _tier = {"sales_invoice": 0, "purchase_bill": 0, "receipt": 1, "purchase_payment": 1, "journal_entry": 2}
    out.sort(key=lambda s: (-s.confidence, s.difference_paise != 0, _tier.get(s.entity_type, 3)))
    return out[:max_results]
