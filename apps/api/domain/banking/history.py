"""
Learning a coding from past decisions (Tier 1.4).

WHAT THIS DOES
    "Last time you saw this payee, you coded it to Rent." That is the whole
    idea, and it is most of what makes a bookkeeping tool feel like it is paying
    attention. The data has been there all along — every posted bank transaction
    records what a human decided — and nothing read it back.

THE LEARNING KEY IS THE HARD PART
    Matching on the raw narration does not work. An Indian UPI narration carries
    a UTR, so every line is unique: "UPI/412345678901/RAMESH KUMAR" and
    "UPI/998877665544/RAMESH KUMAR" are the same payee and share no key.

    So the key is, in order of confidence:
      1. payee_id      — a human linked this line to a customer/vendor (1.3)
      2. the NORMALISED counterparty from the narration parser (6.2), so
         'Acme Pvt. Ltd.' and 'ACME PRIVATE LIMITED' learn as ONE payee
    A transaction with neither teaches nothing and is skipped rather than
    guessed at.

WHY THIS RETURNS EVIDENCE, NOT A SCORE
    A bare "92% confident" is unauditable — a CA cannot tell whether that means
    eleven consistent decisions or one lucky guess. So the suggestion carries
    `times_seen`, `share_bps` and the ALTERNATIVES that lost. "Coded to Rent 8
    of the last 9 times, once to Repairs" is a claim someone can act on or
    dismiss on sight.

    Nothing here is applied automatically. It annotates the queue; a human still
    accepts it, exactly like a matching rule.

Pure and side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .narration import parse_narration, normalise_party_name

KEY_PAYEE_ID = "payee_id"
KEY_COUNTERPARTY = "counterparty"

# A counterparty shorter than this is not distinctive enough to learn from —
# "SBI" or "A/C" would collapse unrelated payees into one bucket.
MIN_KEY_LENGTH = 4


@dataclass(frozen=True)
class CodingOption:
    """One way this payee has been coded before."""
    account_id: Optional[str]
    category: Optional[str]
    times: int
    last_seen: Optional[str]

    @property
    def is_empty(self) -> bool:
        return not (self.account_id or self.category)


@dataclass(frozen=True)
class HistorySuggestion:
    """What history proposes, with the evidence for it."""
    key: str
    key_kind: str                 # KEY_PAYEE_ID | KEY_COUNTERPARTY
    account_id: Optional[str]
    category: Optional[str]
    times_seen: int               # how often the WINNING coding was used
    total_seen: int               # how many past codings were considered
    last_seen: Optional[str]
    alternatives: tuple[CodingOption, ...]

    @property
    def share_bps(self) -> int:
        """The winner's share of past codings, in basis points. Integer maths —
        a percentage is display, never a stored figure."""
        if self.total_seen <= 0:
            return 0
        return (self.times_seen * 10000) // self.total_seen

    @property
    def is_unanimous(self) -> bool:
        return self.times_seen == self.total_seen and self.total_seen > 0


def learning_key(txn: dict) -> Optional[tuple[str, str]]:
    """(kind, value) identifying the payee for learning, or None.

    payee_id wins when present: a human linked it, which is a stronger statement
    than anything inferred from a string.
    """
    payee_id = txn.get("payee_id")
    if payee_id:
        return (KEY_PAYEE_ID, str(payee_id))

    # A confirmed payee_name is a human's words; fall back to the parser's
    # counterparty only when there is no name. Both are normalised the same way,
    # so a typed 'Acme Pvt Ltd' and a parsed 'ACME PVT LTD' land in one bucket.
    raw = txn.get("payee_name") or parse_narration(txn.get("description")).counterparty
    key = normalise_party_name(raw)
    if len(key) < MIN_KEY_LENGTH:
        return None
    return (KEY_COUNTERPARTY, key)


def same_payee(a: dict, b: dict) -> bool:
    """Do these two transactions describe the same payee?"""
    ka, kb = learning_key(a), learning_key(b)
    return ka is not None and ka == kb


def summarise(history: Iterable[dict], key: tuple[str, str]) -> Optional[HistorySuggestion]:
    """Tally how a payee has been coded before and pick the winner.

    `history` is past transactions for the SAME payee — the caller does the
    filtering, because that is where the database lives. Rows carrying no coding
    at all are ignored: they record that a transaction existed, not what anyone
    decided about it.

    Ties break on recency. Two accounts used four times each is a real
    disagreement, and the more recent decision is the better guess — but the
    loser still appears in `alternatives`, so the CA sees the disagreement
    rather than a confident-looking coin flip.
    """
    tally: dict[tuple[Optional[str], Optional[str]], dict] = {}
    for row in history:
        account_id = row.get("account_id") or None
        category = row.get("category") or None
        if not (account_id or category):
            continue
        seen_at = str(row.get("posted_at") or row.get("transaction_date") or "")
        slot = tally.setdefault((account_id, category), {"times": 0, "last": ""})
        slot["times"] += 1
        if seen_at > slot["last"]:
            slot["last"] = seen_at

    if not tally:
        return None

    options = [
        CodingOption(account_id=k[0], category=k[1], times=v["times"],
                     last_seen=v["last"] or None)
        for k, v in tally.items()
    ]
    # Most used, then most recent. `or ""` keeps a missing date from crashing
    # the sort against a present one.
    options.sort(key=lambda o: (o.times, o.last_seen or ""), reverse=True)
    winner, rest = options[0], options[1:]
    total = sum(o.times for o in options)

    return HistorySuggestion(
        key=key[1], key_kind=key[0],
        account_id=winner.account_id, category=winner.category,
        times_seen=winner.times, total_seen=total, last_seen=winner.last_seen,
        alternatives=tuple(rest),
    )


def describe(suggestion: Optional[HistorySuggestion]) -> str:
    """A sentence a CA can judge on sight, rather than a score to trust."""
    if suggestion is None:
        return ""
    times, total = suggestion.times_seen, suggestion.total_seen
    if total == 1:
        return "Coded this way once before"
    if suggestion.is_unanimous:
        return f"Coded this way all {total} times before"
    return f"Coded this way {times} of the last {total} times"
