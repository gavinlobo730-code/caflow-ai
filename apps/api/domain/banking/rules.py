"""
Rule-based auto-categorization (Banking B.2.3) — SUGGESTIONS ONLY.

A rule fires when the narration contains its pattern, the amount is within its
range, and the transaction type matches. The first active rule (caller order)
that fires supplies the suggestion. Rules never auto-post and never write
anything — they only annotate the work queue.

WHAT A RULE CAN SUGGEST
    A rule carries three payload fields, all optional and all stored since
    migration 093/096: a controlled `suggested_category`, a `suggested_account_id`
    (the counter GL account), and a `suggested_narration`. `match_rule` returns
    all three. Returning only the category — which is what this module used to do —
    meant a rule could say "this is an Expense" but never "code it to Bank
    Charges", which is most of what a rule is for.

Pure and side-effect free (unit-testable without a DB).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RuleSuggestion:
    """What a firing rule proposes. Every field is a suggestion for a human to
    accept — nothing here is applied automatically."""
    rule_id: Optional[str]
    rule_name: Optional[str]
    category: Optional[str]
    account_id: Optional[str]
    narration: Optional[str]

    def is_empty(self) -> bool:
        return not (self.category or self.account_id or self.narration)


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


def match_rule(narration: str, amount_paise: int, is_debit: bool,
               rules: list[dict]) -> Optional[RuleSuggestion]:
    """The first active, matching rule that actually proposes something.

    Rules are evaluated in the order given — the caller decides precedence. A
    rule that matches but carries no payload at all is skipped rather than
    swallowing the transaction: it would otherwise block a later, useful rule
    while contributing nothing.
    """
    for rule in rules:
        if not rule_matches(rule, narration, amount_paise, is_debit):
            continue
        suggestion = RuleSuggestion(
            rule_id=rule.get("id"),
            rule_name=rule.get("rule_name"),
            category=rule.get("suggested_category") or None,
            account_id=rule.get("suggested_account_id") or None,
            narration=rule.get("suggested_narration") or None,
        )
        if not suggestion.is_empty():
            return suggestion
    return None


def suggest_category(narration: str, amount_paise: int, is_debit: bool,
                     rules: list[dict]) -> Optional[str]:
    """The firing rule's suggested_category (or None). Thin wrapper over
    `match_rule` — kept because the category alone is what most callers want."""
    hit = match_rule(narration, amount_paise, is_debit, rules)
    return hit.category if hit else None
