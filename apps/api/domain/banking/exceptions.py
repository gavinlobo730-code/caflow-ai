"""
Exception rules for bank transactions — what a partner should look at.

WHY THIS EXISTS INSTEAD OF AN APPROVAL QUEUE
    Every categorized bank transaction used to become a DRAFT journal that a
    Partner had to approve before it reached the books. For a firm with 50
    clients at ~300 statement lines a month that is 15,000 approvals, which
    nobody performs. What happens instead is rubber-stamping — and a queue that
    is rubber-stamped is worse than no queue, because it manufactures a record
    of a review that did not happen.

    It is also not how review works. A partner does not re-perform the junior's
    work; they test what is unusual. Risk-based review, not population review.
    So the default inverts: an ordinary transaction posts, and the ones carrying
    a reason to look wait or are flagged.

WHAT IS IN HERE AND WHAT IS NOT
    Pure functions over dictionaries. No database, no HTTP, no clock — every
    input including "today" is passed in, so each rule is unit-testable on its
    own and the whole set is deterministic. Gathering the context (what payees
    this client has seen before, which accounts it has used) belongs to
    services/bank_exception_service.py; deciding what to do with a flag belongs
    to the posting service.

NOTHING HERE GATES A POSTING — that is a product decision, not an oversight
    `blocking` is computed and, today, deliberately consumed by nobody. Bank
    allocation is the junior's work and it posts on their click; the platform
    does not hold a CA's books hostage to a threshold it invented. If a firm
    ever asks for a hard stop it can opt in, but the default is advisory and
    that is the whole point: this list exists so a partner can SEE what is
    unusual, not so the software can decide what is allowed.

    So `severity` — which orders the partner's list — is the field that matters.
    Read `blocking` as "if anyone ever wanted a gate, this is where it would
    reasonably sit", and do not wire it to the posting path without asking.

ON THRESHOLDS
    Materiality is a judgement, not a constant, so every threshold is policy
    passed in by the caller. The defaults here are a starting point for a small
    practice, deliberately conservative, and are meant to be overridden per
    client — not evidence that anyone decided ₹1,00,000 is material to a
    particular business.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Iterable, Optional


# ── policy ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExceptionPolicy:
    """Per-client thresholds. Paise throughout; bps where a rate reads better."""

    # A transaction at or above this waits for a partner. Deliberately the only
    # amount-driven hard stop: size is the one signal that is always meaningful
    # without knowing anything else about the business.
    materiality_paise: int = 10_000_000            # ₹1,00,000

    # A settlement that leaves the document short by more than this is a write-off
    # decision, not a clerical one. Small differences (bank charges deducted by
    # the remitter, rounding) are ordinary and must not drown the list.
    settlement_tolerance_paise: int = 10_000       # ₹100

    # Above this, a short settlement stops the posting rather than merely
    # flagging it — money is leaving the P&L on somebody's judgement.
    settlement_block_paise: int = 500_000          # ₹5,000

    # Cash out of a bank account at or above this is the classic risk, whatever
    # the client's size.
    cash_withdrawal_paise: int = 5_000_000         # ₹50,000

    # Two transactions this close together, same amount and payee, are worth a
    # second look before both hit the ledger.
    duplicate_window_days: int = 7


# ── the flags a rule can raise ────────────────────────────────────────────────

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class BankException:
    code: str
    severity: str            # high | medium | low — orders the partner's list
    message: str             # written for a CA, not for a log
    blocking: bool = False   # holds the posting rather than flagging it after
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TxnContext:
    """Everything a rule needs that is not on the transaction itself.

    Assembled once per batch by the service so the rules stay pure and the reads
    stay bounded — see CLAUDE.md, "Reporting performance"."""
    known_payees: frozenset = frozenset()        # payee names seen on earlier posted txns
    known_categories: frozenset = frozenset()    # categories this client has used before
    known_accounts: frozenset = frozenset()      # counter accounts this client has used
    matched_outstanding_paise: Optional[int] = None   # the document's open amount
    matched_document_no: Optional[str] = None
    matched_party_name: Optional[str] = None
    siblings: tuple = ()      # (id, iso_date, amount_paise, payee) of nearby transactions


def _amount_paise(txn: dict) -> int:
    return max(int(txn.get("debit_paise") or 0), int(txn.get("credit_paise") or 0))


def _is_outflow(txn: dict) -> bool:
    return int(txn.get("debit_paise") or 0) > 0


def _rupees(paise: int) -> str:
    """₹ with two decimals and Indian digit grouping — this text is read by a CA."""
    neg, paise = paise < 0, abs(int(paise))
    whole, frac = divmod(paise, 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"{'-' if neg else ''}₹{s}.{frac:02d}"


# ── the rules ─────────────────────────────────────────────────────────────────

def _above_materiality(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
                       today: date) -> Optional[BankException]:
    """Size alone. BLOCKING: the one signal that means something without knowing
    anything else about the business, and the one case where posting first and
    correcting later is genuinely worse than waiting."""
    amt = _amount_paise(txn)
    if amt < policy.materiality_paise:
        return None
    return BankException(
        code="above_materiality", severity="high", blocking=True,
        message=(f"{_rupees(amt)} is at or above this client's materiality of "
                 f"{_rupees(policy.materiality_paise)}."),
        detail={"amount_paise": amt, "threshold_paise": policy.materiality_paise})


def _short_settlement(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
                      today: date) -> Optional[BankException]:
    """Matched to a document, but not for what the document is owed.

    This is the "Settle difference" button seen from the other side: accepting it
    writes the shortfall off, which moves the P&L. Small gaps are ordinary — a
    remitter deducting charges, rounding — so the tolerance keeps those out of
    the list; a large one blocks."""
    outstanding = ctx.matched_outstanding_paise
    if outstanding is None:
        return None
    gap = outstanding - _amount_paise(txn)
    if abs(gap) <= policy.settlement_tolerance_paise:
        return None
    short = gap > 0
    doc = ctx.matched_document_no or "the matched document"
    return BankException(
        code="short_settlement" if short else "over_settlement",
        severity="high" if abs(gap) >= policy.settlement_block_paise else "medium",
        blocking=abs(gap) >= policy.settlement_block_paise,
        message=(f"{'Short of' if short else 'Exceeds'} {doc} by {_rupees(abs(gap))} — "
                 f"settling it {'writes that off' if short else 'leaves a credit'}."),
        detail={"gap_paise": gap, "outstanding_paise": outstanding,
                "document_no": ctx.matched_document_no})


def _weak_match(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
                today: date) -> Optional[BankException]:
    """Matched to a document on neither the amount nor the name.

    A match is convincing when the amount is exact or the party appears in the
    narration. With neither, something was accepted because it was the least bad
    option on the list, which is the moment a wrong invoice gets settled."""
    if not txn.get("matched_entity_id") or ctx.matched_outstanding_paise is None:
        return None
    exact = ctx.matched_outstanding_paise == _amount_paise(txn)
    party = (ctx.matched_party_name or "").strip().lower()
    narration = f"{txn.get('description') or ''} {txn.get('payee_name') or ''}".lower()
    named = bool(party) and party.split()[0] in narration
    if exact or named:
        return None
    return BankException(
        code="weak_match", severity="medium",
        message=(f"Matched to {ctx.matched_document_no or 'a document'} on neither the "
                 f"exact amount nor the party name."),
        detail={"document_no": ctx.matched_document_no, "party": ctx.matched_party_name})


def _new_payee(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
               today: date) -> Optional[BankException]:
    """First time this counterparty has appeared in the client's bank history."""
    payee = (txn.get("payee_name") or "").strip()
    if not payee or payee.lower() in ctx.known_payees:
        return None
    return BankException(
        code="new_payee", severity="low",
        message=f"First payment involving {payee} in this client's bank history.",
        detail={"payee": payee})


def _unusual_account(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
                     today: date) -> Optional[BankException]:
    """Posted to a counter account this client has never used.

    Not wrong, but it is how a mis-click on a long dropdown shows up, and it is
    how an expense quietly lands somewhere it will not be found again."""
    acc = txn.get("account_id")
    if not acc or acc in ctx.known_accounts:
        return None
    return BankException(
        code="unusual_account", severity="low",
        message="Posted to a ledger account this client has not used before.",
        detail={"account_id": acc, "category": txn.get("category")})


_CASH_RE = re.compile(
    r"\b(atm|cash\s*w(?:d|dl|ithdrawal)?|self\s*(?:chq|cheque|withdrawal)|"
    r"cwdr|nfs/|by\s*cash)\b", re.IGNORECASE)


def _cash_withdrawal(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
                     today: date) -> Optional[BankException]:
    """Cash out at or above the threshold. BLOCKING: cash is the one movement
    that cannot be traced further once it has left, so the time to ask is before
    it is on the books, not after."""
    if not _is_outflow(txn):
        return None
    if not _CASH_RE.search(str(txn.get("description") or "")):
        return None
    amt = _amount_paise(txn)
    if amt < policy.cash_withdrawal_paise:
        return None
    return BankException(
        code="cash_withdrawal", severity="high", blocking=True,
        message=(f"Cash withdrawal of {_rupees(amt)}, at or above the "
                 f"{_rupees(policy.cash_withdrawal_paise)} threshold."),
        detail={"amount_paise": amt})


def _duplicate_suspect(txn: dict, ctx: TxnContext, policy: ExceptionPolicy,
                       today: date) -> Optional[BankException]:
    """Same amount, same payee, within the window.

    A genuine repeat (rent, an EMI) is common, so this is low severity and never
    blocks — the point is that the partner sees the pair, not that the app
    guesses which one is real."""
    amt = _amount_paise(txn)
    payee = (txn.get("payee_name") or "").strip().lower()
    if not amt or not payee:
        return None
    try:
        when = date.fromisoformat(str(txn.get("transaction_date"))[:10])
    except (TypeError, ValueError):
        return None
    window = timedelta(days=policy.duplicate_window_days)
    for sib_id, sib_date, sib_amt, sib_payee in ctx.siblings:
        if sib_id == txn.get("id") or sib_amt != amt:
            continue
        if (sib_payee or "").strip().lower() != payee:
            continue
        try:
            sib_when = date.fromisoformat(str(sib_date)[:10])
        except (TypeError, ValueError):
            continue
        if abs((sib_when - when).days) <= window.days:
            return BankException(
                code="duplicate_suspect", severity="low",
                message=(f"Another {_rupees(amt)} to {txn.get('payee_name')} on "
                         f"{sib_when.isoformat()} — within "
                         f"{policy.duplicate_window_days} days."),
                detail={"other_id": sib_id, "other_date": sib_when.isoformat()})
    return None


# Order is the order a reader meets them, before severity sorting.
RULES = (
    _above_materiality,
    _short_settlement,
    _weak_match,
    _cash_withdrawal,
    _duplicate_suspect,
    _new_payee,
    _unusual_account,
)


def evaluate(txn: dict, ctx: Optional[TxnContext] = None,
             policy: Optional[ExceptionPolicy] = None,
             today: Optional[date] = None) -> list[BankException]:
    """Every exception one transaction raises, worst first.

    A transaction with no flags returns [] and is the ordinary case — that is the
    whole point of the design, so the empty list is the answer most of the time.
    """
    ctx = ctx or TxnContext()
    policy = policy or ExceptionPolicy()
    today = today or date.today()
    found = [e for rule in RULES if (e := rule(txn, ctx, policy, today)) is not None]
    return sorted(found, key=lambda e: (SEVERITY_ORDER.get(e.severity, 9), e.code))


def blocks_posting(exceptions: Iterable[BankException]) -> bool:
    """Whether this set WOULD hold the transaction back, if anything did.

    No caller gates on this and none should without a decision to — see the
    module docstring. Kept because the judgement of which flags are severe
    enough to be worth stopping for is worth recording next to the rules that
    make them, rather than rediscovered later."""
    return any(e.blocking for e in exceptions)
