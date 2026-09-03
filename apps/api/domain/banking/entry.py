"""
Bank entries — the voucher a statement line becomes, and the draft on it.

The design is docs/architecture/09-bank-entries.md. This module is the pure
half: no database, no HTTP. Everything here is a function of a row and of
what the other domain modules (rules, matcher, history, transfers) already
computed for it.

THREE THINGS LIVE HERE AND NOWHERE ELSE

  kind_for      Receipt / Payment / Contra — decided by the line's direction,
                never chosen. The one place that says so.
  entry_state   The Python twin of migration 322's bank_transaction_entry_state()
                trigger, for mock mode. The trigger is the authority on a real
                database; tests/test_bank_entry_state_parity_pg.py holds the two
                identical. Change both or neither.
  choose        Which proposal goes on the row, and at what grade. A rule
                outranks a document match outranks a transfer outranks history,
                and within each a READY grade outranks a PROPOSED one from a
                stronger source — the CA's time is spent on what the machine is
                least sure of, so the sure things must come first.

WHAT A GRADE MEANS
    ready     — can be passed as it stands, and IS passed by "Pass N ready".
    proposed  — a human should look. The reason says what the question is.
    None      — nothing defensible to propose; the line needs the CA.

    Never a percentage. A CA cannot audit "92% confident"; they can judge
    "coded this way 8 of the last 9 times" and "exact amount, only candidate".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .rules import RuleSuggestion
from .history import HistorySuggestion, describe as describe_history
from .matcher import _rupees, _rate_label
from .posting_map import TRANSFER, AUTO_COUNTER

RECEIPT, PAYMENT, CONTRA = "receipt", "payment", "contra"
KINDS = (RECEIPT, PAYMENT, CONTRA)

NEEDS_YOU, PROPOSED, READY, COVERED, PASSED, SET_ASIDE = (
    "needs_you", "proposed", "ready", "covered", "passed", "set_aside")
STATES = (NEEDS_YOU, PROPOSED, READY, COVERED, PASSED, SET_ASIDE)
# The states still needing anything from anyone. "covered" is not among them:
# the paying side carries the journal, and this side passes with it.
OPEN_STATES = (NEEDS_YOU, PROPOSED, READY)

SOURCE_RULE, SOURCE_DOCUMENT, SOURCE_HISTORY, SOURCE_TRANSFER = (
    "rule", "document", "history", "transfer")
SOURCES = (SOURCE_RULE, SOURCE_DOCUMENT, SOURCE_HISTORY, SOURCE_TRANSFER)
GRADE_READY, GRADE_PROPOSED = "ready", "proposed"

# A document match is READY when the amounts agree exactly, the ranker scored
# it at least this high (exact amount + the narration or the date agreeing),
# and no OTHER candidate also agrees exactly — two invoices of ₹50,000 open on
# the same day is a question, not an answer. The 90 is the threshold the
# screen used for its green button; it is now decided in one place.
DOCUMENT_READY_CONFIDENCE = 90
# Below this a candidate is not worth putting on the row at all — unless it is
# short by an amount that looks like TDS, which is a question worth asking.
DOCUMENT_PROPOSE_CONFIDENCE = 50
# History is READY only when it has never disagreed with itself over at least
# this many postings. One posting is a data point; three the same way is a habit.
HISTORY_READY_MIN_POSTINGS = 3

# The categories whose counter account the posting engine resolves itself,
# so a line carrying one is answered without a ledger. The same set the
# trigger names; mirrored here so the twin cannot drift by import.
_AUTO_COUNTER_CATEGORIES = frozenset(AUTO_COUNTER)


@dataclass(frozen=True)
class Draft:
    """What goes on the row. A proposal, never an answer: passing it is what
    applies it, and a rejected proposal leaves nothing to undo."""
    source: str
    grade: str
    label: str
    reason: str
    account_id: Optional[str] = None
    category: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    rule_id: Optional[str] = None
    gst_rate_bps: Optional[int] = None
    is_interstate: bool = False

    def as_columns(self) -> dict:
        """The bank_transactions columns this draft is stored in."""
        return {
            "draft_source": self.source, "draft_grade": self.grade,
            "draft_label": self.label, "draft_reason": self.reason,
            "draft_account_id": self.account_id, "draft_category": self.category,
            "draft_entity_type": self.entity_type, "draft_entity_id": self.entity_id,
            "draft_rule_id": self.rule_id,
            "draft_gst_rate_bps": self.gst_rate_bps,
            "draft_is_interstate": bool(self.is_interstate),
        }


EMPTY_DRAFT_COLUMNS: dict = {
    "draft_source": None, "draft_grade": None, "draft_label": None,
    "draft_reason": None, "draft_account_id": None, "draft_category": None,
    "draft_entity_type": None, "draft_entity_id": None, "draft_rule_id": None,
    "draft_gst_rate_bps": None, "draft_is_interstate": False,
}


# ── the kind ─────────────────────────────────────────────────────────────────

def kind_for(txn: dict) -> str:
    """Receipt for money in, Payment for money out, Contra between own
    accounts. A confirmed transfer pair, or the Transfer category (which is
    what picking a bank/cash ledger stores), is a contra whichever way the
    money moved."""
    if txn.get("transfer_pair_id") or txn.get("category") == TRANSFER:
        return CONTRA
    return RECEIPT if int(txn.get("credit_paise") or 0) > 0 else PAYMENT


# ── the state ────────────────────────────────────────────────────────────────

def entry_state(row: dict) -> str:
    """The Python twin of bank_transaction_entry_state(). Same branches, same
    order. Read the migration's comment for why each is where it is."""
    if row.get("match_status") == "posted":
        return PASSED
    if row.get("match_status") == "ignored":
        return SET_ASIDE
    if row.get("transfer_pair_id") and row.get("transfer_is_primary") is False:
        return COVERED
    if (row.get("account_id")
            or row.get("matched_entity_id")
            or bool(row.get("has_splits"))
            or (row.get("transfer_pair_id") and row.get("transfer_is_primary") is True)
            or (row.get("category") in _AUTO_COUNTER_CATEGORIES)):
        return READY
    if row.get("draft_error"):
        return NEEDS_YOU
    if row.get("draft_grade") == GRADE_READY:
        return READY
    if row.get("draft_grade") == GRADE_PROPOSED:
        return PROPOSED
    return NEEDS_YOU


def coded_by_a_human(row: dict) -> bool:
    """True when the CA has already answered the line themselves — the
    'ready' branch above that owes nothing to a draft. Passing such a line
    posts what they chose and applies no proposal over it."""
    return bool(
        row.get("account_id")
        or row.get("matched_entity_id")
        or row.get("has_splits")
        or (row.get("transfer_pair_id") and row.get("transfer_is_primary") is True)
        or (row.get("category") in _AUTO_COUNTER_CATEGORIES))


# ── grading each source ──────────────────────────────────────────────────────

def from_rule(hit: Optional[RuleSuggestion], account_name: Optional[str]) -> Optional[Draft]:
    """A rule the CA wrote. Always READY: a human already decided this."""
    if hit is None or hit.is_empty():
        return None
    if not (hit.account_id or hit.category):
        return None                        # a narration-only rule proposes no posting
    label = account_name or hit.category or ""
    reason = f"Rule “{hit.rule_name}”" if hit.rule_name else "A rule"
    return Draft(
        source=SOURCE_RULE, grade=GRADE_READY, label=label, reason=reason,
        account_id=hit.account_id, category=hit.category, rule_id=hit.rule_id,
        gst_rate_bps=hit.gst_rate_bps, is_interstate=bool(hit.is_interstate),
    )


def from_documents(suggestions: Iterable[dict]) -> Optional[Draft]:
    """The ranked candidates the matcher produced (wire dicts, best first).

    READY needs an exact amount, a high score, and NO other exact candidate.
    A short line whose shortfall looks like TDS is PROPOSED with the question
    on it — it settles through the settlement modal, never in bulk, because
    someone has to say what the shortfall was.
    """
    ranked = [s for s in (suggestions or []) if s]
    if not ranked:
        return None
    best = ranked[0]
    exact = [s for s in ranked if int(s.get("difference_paise") or 0) == 0]
    conf = int(best.get("confidence") or 0)
    diff = int(best.get("difference_paise") or 0)
    label = str(best.get("label") or "")
    base = dict(source=SOURCE_DOCUMENT, label=label,
                entity_type=best.get("matched_entity_type"),
                entity_id=best.get("matched_entity_id"))

    if diff == 0 and conf >= DOCUMENT_READY_CONFIDENCE and len(exact) == 1:
        return Draft(grade=GRADE_READY, reason="exact amount, the only document that fits", **base)
    if diff == 0 and len(exact) > 1:
        return Draft(grade=GRADE_PROPOSED,
                     reason=f"{len(exact)} documents have exactly this amount — which one?",
                     **base)
    if diff > 0:
        rate = best.get("tds_rate_bps")
        why = (f"short by {_rupees(diff)} — TDS at {_rate_label(int(rate))}?"
               if rate else f"short by {_rupees(diff)} — bank charges, or TDS?")
        return Draft(grade=GRADE_PROPOSED, reason=why, **base)
    if conf >= DOCUMENT_PROPOSE_CONFIDENCE:
        return Draft(grade=GRADE_PROPOSED, reason="exact amount — confirm it is this one", **base)
    return None


def from_history(s: Optional[HistorySuggestion], account_name: Optional[str]) -> Optional[Draft]:
    """How this payee was coded before. The reason IS the evidence sentence."""
    if s is None or not (s.account_id or s.category):
        return None
    label = account_name or s.category or ""
    ready = bool(s.is_unanimous) and int(s.total_seen or 0) >= HISTORY_READY_MIN_POSTINGS
    return Draft(
        source=SOURCE_HISTORY, grade=GRADE_READY if ready else GRADE_PROPOSED,
        label=label, reason=describe_history(s),
        account_id=s.account_id, category=s.category,
    )


def from_transfer(pair: Optional[dict], this_id: str, other_account_name: Optional[str]) -> Optional[Draft]:
    """The counterpart line on another of the client's own accounts (the
    transfer service's wire dict). Written on BOTH sides, pointing at the
    other, so neither reads as unexplained; passing either side pairs them
    and posts the paying side."""
    if not pair:
        return None
    primary, counter = pair.get("primary_id"), pair.get("counterpart_id")
    if this_id not in (primary, counter):
        return None
    other = counter if this_id == primary else primary
    ready = pair.get("confidence") == "high" and bool(pair.get("is_unambiguous"))
    side = "to" if this_id == primary else "from"
    label = f"{side} {other_account_name}" if other_account_name else pair.get("summary") or "own account"
    return Draft(
        source=SOURCE_TRANSFER, grade=GRADE_READY if ready else GRADE_PROPOSED,
        label=label, reason=str(pair.get("summary") or "same amount on another own account"),
        category=TRANSFER, entity_type="bank_transaction", entity_id=other,
    )


# ── choosing ─────────────────────────────────────────────────────────────────

def choose(rule: Optional[Draft], document: Optional[Draft],
           transfer: Optional[Draft], history: Optional[Draft]) -> Optional[Draft]:
    """One draft per row. READY from any source beats PROPOSED from any
    source; within a grade, rule > document > transfer > history.

    Why a rule first: a human wrote it for this narration. Why a document
    before a transfer: settling a specific invoice is a stronger claim than
    "the same amount arrived in another account". Why history last: it is
    the only source that is an inference rather than a fact.
    """
    ranked = [d for d in (rule, document, transfer, history) if d is not None]
    for grade in (GRADE_READY, GRADE_PROPOSED):
        for d in ranked:
            if d.grade == grade:
                return d
    return None


def draft_changed(row: dict, draft: Optional[Draft]) -> bool:
    """Whether writing `draft` would change what the row already carries.
    Redraft writes only what changed, so a steady-state pass over three
    thousand open lines is three thousand reads and no writes."""
    want = draft.as_columns() if draft else EMPTY_DRAFT_COLUMNS
    for k, v in want.items():
        have = row.get(k)
        if k == "draft_is_interstate":
            have = bool(have)          # NOT NULL DEFAULT false; a missing key is false
        if have != v:
            return True
    return False
