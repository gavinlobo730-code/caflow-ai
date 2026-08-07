"""
Transfer auto-detection (Tier 1.5) — pairing the two halves of one movement.

WHAT THIS PREVENTS
    Move ₹5,00,000 from the current account to the deposit account and it lands
    on TWO statements: a debit on one, a credit on the other. They are one real
    movement of cash seen twice.

    Coded independently — as they must be today — that becomes two journals and
    ₹10,00,000 of apparent activity, with the second one usually landing in
    whatever expense or income account looked plausible. It is the single
    easiest way to silently overstate both sides of a P&L from a bank feed.

WHY DETECTION IS ONLY HALF THE FEATURE
    `posting_map.build_transfer_lines` already writes the COMPLETE double entry
    for a transfer: Dr the destination account, Cr the source. So posting both
    sides of a detected pair would double-count exactly the thing this exists to
    prevent — the fix is not just to find the pair but to make sure only ONE of
    them ever produces a journal. That is why a pair has a primary side; see
    migration 258 and bank_posting_service.

WHAT COUNTS AS A PAIR
    Exact same amount, opposite directions, DIFFERENT accounts belonging to the
    same client, within a few days of each other. All four are required:

      * exact amount — integer paise, no tolerance. A transfer that arrives
        short is a transfer plus a bank charge, which is two facts, and pairing
        them as one would bury the charge.
      * opposite directions — two debits are not a transfer however well they
        match.
      * different accounts — a debit and credit on the SAME account is not a
        movement between accounts, it is two unrelated lines.
      * a date window — inter-bank settlement takes a day or two, but a match
        three weeks apart is a coincidence, not a transfer.

AMBIGUITY IS REPORTED, NOT RESOLVED
    A client with three ₹50,000 movements on one day has no single correct
    pairing, and picking one silently would be worse than picking none. Each
    suggestion carries how many other candidates its two sides had; the UI shows
    that, and a human decides.

Pure and side-effect free. Integer paise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

# Inter-bank settlement is usually same-day or next-day; NEFT batches and
# weekends stretch it. Beyond this a same-amount opposite pair is more likely a
# coincidence than a transfer.
DEFAULT_WINDOW_DAYS = 4


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _amount(txn: dict) -> tuple[int, bool]:
    """(amount_paise, is_credit). A bank line has exactly one non-zero side."""
    debit = int(txn.get("debit_paise") or 0)
    credit = int(txn.get("credit_paise") or 0)
    return max(debit, credit), credit > 0


@dataclass(frozen=True)
class TransferPair:
    """Two bank lines that look like one movement.

    `primary_id` is the side that will carry the journal — the OUTFLOW, because
    a transfer is naturally described from the account the money left. The
    counterpart never gets a journal of its own; it is the same cash.
    """
    primary_id: str            # the debit side (money leaving)
    counterpart_id: str        # the credit side (money arriving)
    amount_paise: int
    primary_date: Optional[date]
    counterpart_date: Optional[date]
    primary_account_id: str
    counterpart_account_id: str
    # How many OTHER lines each side could equally have paired with. Both zero
    # means the pairing is unambiguous.
    primary_alternatives: int
    counterpart_alternatives: int

    @property
    def day_gap(self) -> int:
        if not (self.primary_date and self.counterpart_date):
            return 0
        return abs((self.counterpart_date - self.primary_date).days)

    @property
    def is_unambiguous(self) -> bool:
        return self.primary_alternatives == 0 and self.counterpart_alternatives == 0

    @property
    def confidence(self) -> str:
        """Deliberately coarse. A percentage here would imply a precision the
        underlying evidence — an amount and a date — does not have."""
        if not self.is_unambiguous:
            return "low"
        return "high" if self.day_gap <= 1 else "medium"


def _eligible(txn: dict) -> bool:
    """Can this line be part of a newly-detected pair at all?

    A posted line's coding is already decided, an ignored one was deliberately
    set aside, and an already-paired one is spoken for.
    """
    if txn.get("posted_journal_id") or txn.get("posted_at"):
        return False
    if txn.get("match_status") in ("posted", "ignored"):
        return False
    if txn.get("transfer_pair_id"):
        return False
    # A line already matched to an invoice/bill is settling a document, which is
    # not a transfer between own accounts.
    if txn.get("matched_entity_id"):
        return False
    return True


def _can_pair(out: dict, inb: dict, window_days: int) -> bool:
    """Do these two lines describe the same movement?"""
    out_amt, out_credit = _amount(out)
    in_amt, in_credit = _amount(inb)
    if out_credit or not in_credit:
        return False                       # need exactly one out and one in
    if out_amt <= 0 or out_amt != in_amt:
        return False                       # exact paise, no tolerance
    if out.get("bank_account_id") == inb.get("bank_account_id"):
        return False                       # same account is not a movement
    if not (out.get("bank_account_id") and inb.get("bank_account_id")):
        return False                       # cannot tell the accounts apart
    d_out, d_in = _as_date(out.get("transaction_date")), _as_date(inb.get("transaction_date"))
    if not (d_out and d_in):
        return False
    return abs((d_in - d_out).days) <= window_days


def detect(txns: Iterable[dict], *, window_days: int = DEFAULT_WINDOW_DAYS) -> list[TransferPair]:
    """Every transfer pair visible in this set of transactions.

    Each line appears in AT MOST ONE pair. Pairs are taken best-first — smallest
    date gap, then a deterministic tiebreak on id — so the same input always
    yields the same pairing rather than one that depends on row order.
    """
    rows = [t for t in txns if _eligible(t)]
    outs = [t for t in rows if not _amount(t)[1]]
    ins = [t for t in rows if _amount(t)[1]]

    # Every possible pairing first, so ambiguity can be counted BEFORE any
    # greedy choice removes the evidence of it.
    candidates: list[tuple[int, str, str, dict, dict]] = []
    for o in outs:
        for i in ins:
            if _can_pair(o, i, window_days):
                gap = abs((_as_date(i["transaction_date"]) - _as_date(o["transaction_date"])).days)
                candidates.append((gap, str(o.get("id")), str(i.get("id")), o, i))

    out_options: dict = {}
    in_options: dict = {}
    for _, oid, iid, _o, _i in candidates:
        out_options[oid] = out_options.get(oid, 0) + 1
        in_options[iid] = in_options.get(iid, 0) + 1

    candidates.sort(key=lambda c: (c[0], c[1], c[2]))

    used: set = set()
    pairs: list[TransferPair] = []
    for gap, oid, iid, o, i in candidates:
        if oid in used or iid in used:
            continue
        used.add(oid)
        used.add(iid)
        pairs.append(TransferPair(
            primary_id=oid, counterpart_id=iid,
            amount_paise=_amount(o)[0],
            primary_date=_as_date(o.get("transaction_date")),
            counterpart_date=_as_date(i.get("transaction_date")),
            primary_account_id=str(o.get("bank_account_id")),
            counterpart_account_id=str(i.get("bank_account_id")),
            # Minus one: its own pairing is not an "alternative".
            primary_alternatives=out_options.get(oid, 1) - 1,
            counterpart_alternatives=in_options.get(iid, 1) - 1,
        ))
    return pairs


def describe(pair: TransferPair) -> str:
    """A sentence a CA can judge on sight."""
    when = ("same day" if pair.day_gap == 0
            else f"{pair.day_gap} day{'s' if pair.day_gap > 1 else ''} apart")
    if pair.is_unambiguous:
        return f"Matching transfer out and in, {when}"
    return (f"Possible transfer, {when} — other lines match this amount too, "
            "so check which two belong together")
