"""
Rule-based auto-categorization (Banking B.2.3) — SUGGESTIONS ONLY.

A rule fires when its pattern hits the line, the amount is within its range,
and the transaction type matches. The first active rule BY PRECEDENCE supplies
the suggestion. Rules never auto-post and never write anything HERE — they only
annotate the work queue; a rule a Manager has marked TRUSTED is passed by
`bank_entry_service`, which is a separate and deliberate decision.

WHAT A RULE CAN MATCH ON (migration 380, BANK-11)
    Until then it was one case-insensitive substring of the narration, and that
    failed a practice two ways. PRECEDENCE was creation order with no way to
    change it, so a broad rule written in April permanently shadowed the narrow
    one written in July — `by_precedence` reads the `priority` column now, with
    `created_at` as the tiebreak so nothing existing moves. And ONE PATTERN
    against ONE FIELD meant "NEFT from any of these three customers" was three
    rules, and a UTR or cheque number in `reference_no` — often the only stable
    part of a line whose narration the bank rewrites monthly — could not be
    matched at all. `match_field`, `match_operator` and `description_patterns`
    answer those; every default reproduces the old behaviour exactly.

    WHAT A RULE MAY PROPOSE IS THE LINE, and it has moved exactly twice, both
    times as an owner decision rather than as a side effect of better matching.
    A trusted rule posts unattended, so widening the PAYLOAD widens what
    happens with nobody watching. The PARTY was allowed (migration 404) because
    it labels the transaction and moves no figure. The TDS FLAG was allowed
    (D19, migration 413) because it does not even label — it routes the line to
    a human worklist, so it can only ADD review, never remove it.

    A TDS TREATMENT IS STILL REFUSED and the distinction is the whole point: no
    section, no rate, no base, no amount. A withholding decides a statutory
    liability under s.201 and belongs in front of a person however trusted the
    rule. A SPLIT LEG is still refused too, and for a different reason — a rule
    cannot know a future amount, so percentages are the only form that
    generalises and that is a feature nobody has specified.

WHAT A RULE CAN SUGGEST
    A rule carries three payload fields, all optional and all stored since
    migration 093/096: a controlled `suggested_category`, a `suggested_account_id`
    (the counter GL account), and a `suggested_narration`. `match_rule` returns
    all three. Returning only the category — which is what this module used to do —
    meant a rule could say "this is an Expense" but never "code it to Bank
    Charges", which is most of what a rule is for.

    Since migration 254 a rule also carries the GST treatment of a bank charge:
    the rate hiding inside the inclusive amount, and whether the supply is
    inter-state. Both are constant per bank and neither is inferable from the
    statement (see domain/banking/charge_gst), so the rule is where a CA states
    them once instead of re-typing them on every ₹590 charge.

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
    gst_rate_bps: Optional[int] = None
    is_interstate: bool = False
    # BANK-11 step 3, migration 404 — WHO the money went to or came from.
    # These LABEL the transaction and are not a journal leg: nothing in
    # posting_map.build_lines, the settlement or the reversal reads them, and
    # the settlement target is matched_entity_type/matched_entity_id, a
    # different pair. That is what makes them safe for a trusted rule to apply
    # unattended, and it is why a SPLIT LEG and a TDS treatment are still
    # refused — see the module header.
    payee_type: Optional[str] = None
    payee_id: Optional[str] = None
    # D19, migration 413 — the OTHER half of BANK-11 step 3, and the one
    # migration 404 refused. It is NOT a TDS treatment: there is no section,
    # no rate, no base and no amount here, and a trusted rule still cannot
    # decide a withholding. It says "a human must look at this one", which is
    # the opposite kind of thing — it can only ADD work for a person, never
    # remove it, and it moves no figure in any journal.
    #
    # The safety property is the party's, one step stronger. The party LABELS
    # the transaction; this does not even do that — it routes the line to a
    # worklist. A test asserts the posting map, the settlement and the reversal
    # never read it.
    flags_tds_decision: bool = False

    def is_empty(self) -> bool:
        # gst_rate_bps is deliberately NOT counted. It is a modifier on how the
        # counter account is booked, not a standalone proposal — a rule offering
        # a rate and nothing else has no account to code the taxable value to,
        # so it would only block a later rule that does. Migration 254 enforces
        # the same pairing with a CHECK.
        # The PARTY is deliberately NOT counted either, for gst_rate_bps'
        # reason turned around: a rule that names only a party proposes no
        # posting at all, so treating it as a payload would let it win
        # precedence over a later rule that does code the line — and the CA
        # would get a tagged transaction still sitting in the queue. A rule
        # that codes AND tags carries both.
        #
        # NOR IS THE TDS FLAG (D19), for the same reason a third time, and here
        # the consequence is sharper: a rule that ONLY flags proposes no posting,
        # so counting it would let it win precedence over a later rule that
        # actually codes the line — and the CA would get a line marked "needs a
        # TDS decision" still sitting uncoded in the queue, which is the worst
        # of both. A rule that codes AND flags carries both.
        return not (self.category or self.account_id or self.narration)


#: The party kinds a rule may name — migration 404's CHECK and migration 257's
#: are the same three, and a test reads BOTH files so a value added to one and
#: not the other fails in CI rather than at INSERT time on production.
PAYEE_TYPES: tuple[str, ...] = ("customer", "vendor", "other")

#: 'other' names a party this product does not hold — the electricity board,
#: the landlord — so there is nothing for an id to point INTO. The same pairing
#: bank_payee_service enforces on the human door.
PAYEE_TYPES_WITH_AN_ID: tuple[str, ...] = ("customer", "vendor")


#: Which text of the transaction a pattern is read against (migration 380).
#: 'any' is the three together — what a CA means by "this appears somewhere on
#: the line". The keys are the RULE's own values; the values are the keys of the
#: transaction dict the callers pass, so a caller that renames a field breaks
#: here rather than silently matching nothing.
MATCH_FIELDS: dict[str, tuple[str, ...]] = {
    "description": ("narration",),
    "reference_no": ("reference_no",),
    "payee_name": ("payee_name",),
    "any": ("narration", "reference_no", "payee_name"),
}

MATCH_OPERATORS: tuple[str, ...] = ("contains", "starts_with", "equals")


def _compares(operator: str, haystack: str, needle: str) -> bool:
    if operator == "starts_with":
        return haystack.startswith(needle)
    if operator == "equals":
        return haystack == needle
    return needle in haystack          # 'contains', and the fallback


def _text_matches(rule: dict, fields: dict) -> bool:
    """Does this rule's pattern (or any of its alternatives) hit the line?

    A rule with NO pattern at all matches every transaction, which is what it
    has always done and what makes an amount-only or direction-only rule
    possible. Everything else is OR over the alternatives and OR over the
    fields, so "any of these three customers, wherever the bank puts the name"
    is one rule.
    """
    patterns = [(rule.get("description_pattern") or "").strip().lower()]
    for extra in (rule.get("description_patterns") or []):
        text = (extra or "").strip().lower()
        if text:
            patterns.append(text)
    patterns = [p for p in patterns if p]
    if not patterns:
        return True

    field = (rule.get("match_field") or "description").strip().lower()
    keys = MATCH_FIELDS.get(field) or MATCH_FIELDS["description"]
    operator = (rule.get("match_operator") or "contains").strip().lower()
    if operator not in MATCH_OPERATORS:
        operator = "contains"

    haystacks = [(fields.get(k) or "").strip().lower() for k in keys]
    return any(_compares(operator, h, p) for h in haystacks if h for p in patterns)


def rule_matches(rule: dict, narration: str, amount_paise: int, is_debit: bool,
                 *, reference_no: str = "", payee_name: str = "") -> bool:
    """True if `rule` applies to a transaction. All present conditions must hold.

    `reference_no` and `payee_name` are keyword-only and default to empty, so
    every existing caller keeps compiling and keeps behaving identically — a
    rule left at `match_field = 'description'` never looks at them. A rule that
    DOES name one and is asked by a caller that did not supply it simply does
    not fire, which is the safe direction: a rule that may be trusted posts
    unattended, so failing to match is cheaper than matching wrongly.
    """
    if not rule.get("is_active", True):
        return False
    if not _text_matches(rule, {"narration": narration,
                                "reference_no": reference_no,
                                "payee_name": payee_name}):
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


def by_precedence(rules: list[dict]) -> list[dict]:
    """The evaluation order: `priority` ascending, then `created_at` (BANK-11).

    Precedence used to be creation order alone, with no way to change it, so a
    broad rule written in April permanently shadowed the narrow one written in
    July — `match_rule` takes the FIRST firing rule. `created_at` stays the
    tiebreak, so at the column's default of 100 the order is exactly what it
    was and no existing rule changes which transactions it wins.

    Sorted HERE as well as in the three queries that fetch rules, because the
    ordering is a property of the rules and not of one SQL statement: a caller
    that assembles a list itself (mock mode, a test double, a future in-memory
    path) gets the same answer.
    """
    return sorted(
        rules,
        key=lambda r: (int(r.get("priority") if r.get("priority") is not None else 100),
                       str(r.get("created_at") or ""),
                       str(r.get("id") or "")),
    )


def match_rule(narration: str, amount_paise: int, is_debit: bool,
               rules: list[dict], *,
               reference_no: str = "", payee_name: str = "") -> Optional[RuleSuggestion]:
    """The first active, matching rule that actually proposes something.

    Evaluated by `by_precedence` — priority first, then creation order. A rule
    that matches but carries no payload at all is skipped rather than
    swallowing the transaction: it would otherwise block a later, useful rule
    while contributing nothing.
    """
    for rule in by_precedence(rules):
        if not rule_matches(rule, narration, amount_paise, is_debit,
                            reference_no=reference_no, payee_name=payee_name):
            continue
        rate = rule.get("suggested_gst_rate_bps")
        suggestion = RuleSuggestion(
            rule_id=rule.get("id"),
            rule_name=rule.get("rule_name"),
            category=rule.get("suggested_category") or None,
            account_id=rule.get("suggested_account_id") or None,
            narration=rule.get("suggested_narration") or None,
            # `or None` would turn a deliberate 0 — "this charge carries NO GST" —
            # back into "the rule says nothing", which is a different answer.
            gst_rate_bps=int(rate) if rate is not None else None,
            is_interstate=bool(rule.get("suggested_is_interstate")),
            # Read off the rule as stored. The PAIR is checked by migration
            # 404's CHECK and the id is resolved against the real table at
            # APPLY time by bank_payee_service — the same door a human uses —
            # because payee_id is polymorphic and carries no foreign key
            # (migration 257 records why).
            payee_type=(rule.get("payee_type") or None),
            payee_id=(rule.get("payee_id") or None),
        )
        if not suggestion.is_empty():
            return suggestion
    return None


def suggest_category(narration: str, amount_paise: int, is_debit: bool,
                     rules: list[dict], *,
                     reference_no: str = "", payee_name: str = "") -> Optional[str]:
    """The firing rule's suggested_category (or None). Thin wrapper over
    `match_rule` — kept because the category alone is what most callers want."""
    hit = match_rule(narration, amount_paise, is_debit, rules,
                     reference_no=reference_no, payee_name=payee_name)
    return hit.category if hit else None
