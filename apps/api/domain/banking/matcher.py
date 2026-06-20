"""
Bank transaction match suggestion engine (Banking B.2.1) — SUGGESTIONS ONLY.

Given an unmatched bank transaction and a set of candidate entities (open sales
invoices / purchase bills / receipts / payments / journal entries), produce a
RANKED list of suggestions with a confidence score. No posting, no DB access —
the service fetches candidates and calls the pure ranker here, which keeps the
scoring logic unit-testable.

Confidence methodology (0–100):
  • Exact amount is the GATE — only equal-amount candidates are suggested
    (every priority tier in the spec requires an exact amount). Base = 50.
  • Date proximity:  same day +30, ≤3d +20, ≤7d +10, ≤30d +5.
  • Same customer/vendor (party name appears in the narration): +15.
  • Candidate's outstanding balance equals the amount (open invoice/bill): +15.
  • Settlement entities (invoice/bill) rank above a bare journal candidate: +5.
Labels: high ≥ 80, medium ≥ 50, else low.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Candidate:
    entity_type: str            # sales_invoice | purchase_bill | receipt | purchase_payment | journal_entry
    entity_id: str
    label: str                  # human label (e.g. "INV-2526-0001 · Acme Pvt Ltd")
    amount_paise: int
    entity_date: Optional[str] = None      # ISO
    party_name: Optional[str] = None
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


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except Exception:
        return None


def _confidence_label(score: int) -> str:
    return "high" if score >= 80 else "medium" if score >= 50 else "low"


def rank_suggestions(
    txn_amount_paise: int,
    txn_date: Optional[str],
    narration: Optional[str],
    candidates: list[Candidate],
    max_results: int = 5,
) -> list[Suggestion]:
    narr = (narration or "").lower()
    out: list[Suggestion] = []
    for c in candidates:
        if c.amount_paise != txn_amount_paise:
            continue  # exact-amount gate (all priority tiers require it)
        score, reasons = 50, ["exact amount"]

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

        if c.party_name and c.party_name.strip() and c.party_name.lower() in narr:
            score += 15; reasons.append("party in narration")

        if c.outstanding_paise is not None and c.outstanding_paise == txn_amount_paise:
            score += 15; reasons.append("matches outstanding balance")

        if c.entity_type in ("sales_invoice", "purchase_bill"):
            score += 5; reasons.append("open document")

        score = min(score, 100)
        out.append(Suggestion(
            entity_type=c.entity_type, entity_id=c.entity_id, label=c.label,
            amount_paise=c.amount_paise, confidence=score,
            confidence_label=_confidence_label(score), reasons=reasons,
        ))

    # Highest confidence first; settlement docs tie-break ahead of journals.
    _tier = {"sales_invoice": 0, "purchase_bill": 0, "receipt": 1, "purchase_payment": 1, "journal_entry": 2}
    out.sort(key=lambda s: (-s.confidence, _tier.get(s.entity_type, 3)))
    return out[:max_results]
