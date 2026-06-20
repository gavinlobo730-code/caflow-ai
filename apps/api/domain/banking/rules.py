"""
Rule-based auto-categorization (Banking B.2.3) — SUGGESTIONS ONLY.

A rule fires when the narration contains its pattern, the amount is within its
range, and the transaction type matches. The first active rule (caller order)
that fires supplies a suggested category. Rules never auto-post and never write
anything — they only annotate the work queue.

Pure and side-effect free (unit-testable without a DB).
"""
from __future__ import annotations

from typing import Optional


def rule_matches(rule: dict, narration: str, amount_paise: int, is_debit: bool) -> bool:
    """True if `rule` applies to a transaction. All present conditions must hold."""
    if not rule.get("is_active", True):
        return False
    pattern = (rule.get("description_pattern") or "").strip().lower()
    if pattern and pattern not in (narration or "").lower():
        return False
    lo, hi = rule.get("amount_min_paise"), rule.get("amount_max_paise")
    if lo is not None and amount_paise < int(lo):
        return False
    if hi is not None and amount_paise > int(hi):
        return False
    txn_type = (rule.get("txn_type") or "any").strip().lower()
    if txn_type == "debit" and not is_debit:
        return False
    if txn_type == "credit" and is_debit:
        return False
    return True


def suggest_category(narration: str, amount_paise: int, is_debit: bool,
                     rules: list[dict]) -> Optional[str]:
    """First active, matching rule's suggested_category (or None). Rules are
    evaluated in the order given — the caller decides precedence."""
    for rule in rules:
        if rule_matches(rule, narration, amount_paise, is_debit):
            cat = rule.get("suggested_category")
            if cat:
                return cat
    return None
