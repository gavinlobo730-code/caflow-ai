"""The electronic credit ledger a GSTR-3B is set off against (gst-06).

WHAT WAS WRONG
    `compute_gstr3b` set Table 6 off against Table 4(C) of THIS return and
    nothing else. The electronic credit ledger is a RUNNING balance: credit a
    return leaves unspent is still in the ledger when the next one is filed,
    and CGST Act s.49(4) lets the whole of it pay output tax. So a client
    whose April closed holding Rs 36,54,961.65 of IGST credit opened May with
    it, and a May with Rs 1,00,000 of output tax owed the cash ledger NOTHING.
    The return computed May as though April had not happened and showed a
    Rs 1,00,000 cash payment — money the client pays out of the bank that the
    law does not ask of them, and under Rule 88B(1) also the base late
    interest is charged on.

WHAT THIS MODULE DECIDES
    Where the opening balance of a return window comes from, and what to say
    about it. It reads nothing and writes nothing; `services/
    gst_credit_ledger_service` fetches its three inputs and `compute_gstr3b`
    spends the balance it returns. Three sources, in this order:

      1. RECORDED       a CA keyed the balance from the portal for this exact
                        window. It wins over the chain, because the portal's
                        ledger is the truth the chain is only an estimate of
                        (a refund, an ITC-02 transfer, a return filed
                        elsewhere all move the real ledger and none of them
                        reaches a return saved here).
      2. PREVIOUS       the credit the immediately preceding return left
                        (`gstr3b_returns.credit_closing_*`), found by its
                        `credit_closing_as_of` being the day before this
                        window starts.
      3. NOT RECORDED   neither exists. The balance is NOT KNOWN, which is a
                        different thing from nil.

    **NOT KNOWN IS TREATED AS NIL FOR THE ARITHMETIC AND SAYS SO.** The
    direction decides it: assuming nothing is in the ledger can only OVER-state
    the cash a client pays (the credit they hold is simply unused, and carries),
    while assuming credit that is not there would leave tax unpaid and the
    interest running. So the balance is zero, `known` is False and a sentence
    travels with it — the same discipline `table_4a_gaps` applies to a nil row.
    `unreadable` is a FOURTH state, distinct from not recorded, because "nobody
    has said" sends a CA to key a balance and "we could not look" sends them to
    compute again.

WHAT IT DOES NOT DO
    It does not read the portal. The electronic credit ledger is a portal
    figure and this product cannot see it; every number here is either keyed by
    a person or carried from a return this product computed. The previous
    return's closing is what THAT return computed, and a return that was
    computed and never filed has not moved the portal's ledger at all — so a
    chained opening from an unfiled return is reported as provisional, in
    words, and never silently trusted.

    It does not carry credit across registrations: the ledger is per GSTIN
    (CGST s.49(1)), and a client with several holds one per registration. The
    service asks per GSTIN and this module never sees another.

    Cess credit is carried and spent under the same rule but only against
    cess (GST (Compensation to States) Act s.11(2) proviso) — `compute_gstr3b`
    keeps that head out of the s.49(5) ladder, and this module only holds the
    figure.

    Nothing here files, posts or pays. The balance changes a figure the CA
    reviews.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from domain.money_text import rupees_paise

HEADS = ("igst", "cgst", "sgst", "cess")

SOURCE_RECORDED = "recorded"
SOURCE_PREVIOUS_RETURN = "previous_return"
SOURCE_NOT_RECORDED = "not_recorded"
SOURCE_UNREADABLE = "unreadable"

# What `gstr3b_returns.credit_opening_source` may hold (migration 474's CHECK).
SOURCES = (SOURCE_RECORDED, SOURCE_PREVIOUS_RETURN, SOURCE_NOT_RECORDED,
           SOURCE_UNREADABLE)

# CGST s.49(4): the credit ledger moves when a return is FILED. Any other
# status is a working paper that has not yet changed the portal's balance.
_FILED = "submitted"


class CreditLedgerError(ValueError):
    """A balance that cannot be a balance: negative, or not a whole paise."""


@dataclass(frozen=True)
class CreditBalance:
    """The credit held per head, in integer paise. Never negative: a ledger
    that is owed to the department is a demand, not a balance."""

    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0

    def __post_init__(self) -> None:
        for head in HEADS:
            v = getattr(self, f"{head}_paise")
            if isinstance(v, bool) or not isinstance(v, int):
                raise CreditLedgerError(
                    f"The {head.upper()} credit must be a whole number of paise, "
                    f"not {v!r}.")
            if v < 0:
                raise CreditLedgerError(
                    f"The {head.upper()} credit cannot be negative "
                    f"({rupees_paise(v)}): a credit ledger holds what the "
                    f"department owes the taxpayer, and what the taxpayer owes it "
                    f"is a demand, which is not recorded here.")

    @property
    def total_paise(self) -> int:
        return (self.igst_paise + self.cgst_paise
                + self.sgst_paise + self.cess_paise)

    @property
    def is_nil(self) -> bool:
        return self.total_paise == 0

    def as_dict(self) -> dict:
        return {
            "igst_paise": self.igst_paise,
            "cgst_paise": self.cgst_paise,
            "sgst_paise": self.sgst_paise,
            "cess_paise": self.cess_paise,
            "total_paise": self.total_paise,
        }

    def minus(self, other: "CreditBalance") -> dict:
        """Signed difference per head (self minus other). A dict, not a
        CreditBalance, because it may be negative."""
        return {f"{h}_paise": getattr(self, f"{h}_paise") - getattr(other, f"{h}_paise")
                for h in HEADS}

    @classmethod
    def from_columns(cls, row: dict, prefix: str) -> "Optional[CreditBalance]":
        """Read `{prefix}_igst_paise` ... off a stored row.

        None unless ALL FOUR are present — migration 474 CHECKs them as a set,
        so a partial row cannot be written, and a reader that tolerated one
        would read a missing head as nil."""
        vals = [row.get(f"{prefix}_{h}_paise") for h in HEADS]
        if any(v is None for v in vals):
            return None
        return cls(*(int(v) for v in vals))


@dataclass(frozen=True)
class PreviousClosing:
    """What the return immediately before this window left in the ledger."""

    balance: CreditBalance
    period: str                 # MMYYYY of the return that left it
    status: str                 # draft | validated | ca_approved | submitted
    as_of: str                  # ISO date: the last day of that return's window

    @property
    def is_filed(self) -> bool:
        return (self.status or "").lower() == _FILED


@dataclass(frozen=True)
class RecordedOpening:
    """A balance a CA keyed from the portal for one window."""

    balance: CreditBalance
    note: Optional[str] = None
    recorded_at: Optional[str] = None


@dataclass(frozen=True)
class OpeningCredit:
    """The opening balance the set-off runs with, and where it came from."""

    balance: CreditBalance
    source: str
    window_start: str
    chain: Optional[PreviousClosing] = None
    recorded: Optional[RecordedOpening] = None
    # Per head, recorded minus chain — present only where BOTH exist and the
    # CA's figure moved the answer, so the screen can say by how much.
    recorded_minus_chain: Optional[dict] = None
    sentences: tuple = ()

    @property
    def known(self) -> bool:
        """False for not-recorded and unreadable: the balance in `balance` is
        then an ASSUMPTION of nil, not a reading."""
        return self.source in (SOURCE_RECORDED, SOURCE_PREVIOUS_RETURN)

    @property
    def label(self) -> str:
        """The source in words, so a screen holds no vocabulary of its own."""
        if self.source == SOURCE_RECORDED:
            return "Recorded from the portal"
        if self.source == SOURCE_PREVIOUS_RETURN and self.chain is not None:
            return f"Carried from the {_period_label(self.chain.period)} return"
        if self.source == SOURCE_UNREADABLE:
            return "Could not be read — assumed nil"
        return "Not recorded — assumed nil"

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "label": self.label,
            "known": self.known,
            "window_start": self.window_start,
            "balance": self.balance.as_dict(),
            "chain": None if self.chain is None else {
                "balance": self.chain.balance.as_dict(),
                "period": self.chain.period,
                "status": self.chain.status,
                "as_of": self.chain.as_of,
                "is_filed": self.chain.is_filed,
            },
            "recorded": None if self.recorded is None else {
                "balance": self.recorded.balance.as_dict(),
                "note": self.recorded.note,
                "recorded_at": self.recorded.recorded_at,
            },
            "recorded_minus_chain": self.recorded_minus_chain,
            "sentences": list(self.sentences),
        }


def _period_label(period: str) -> str:
    """042026 -> April 2026, for a sentence a CA reads."""
    p = (period or "").strip()
    if len(p) == 6 and p.isdigit() and 1 <= int(p[:2]) <= 12:
        names = ("January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December")
        return f"{names[int(p[:2]) - 1]} {p[2:]}"
    return p or "the earlier period"


def resolve_opening(*, window_start: "date | str",
                    previous: Optional[PreviousClosing],
                    recorded: Optional[RecordedOpening]) -> OpeningCredit:
    """Which balance the set-off opens with — see the module docstring.

    `window_start` is the first day of the return window. `previous` and
    `recorded` are what the service found; either may be None.
    """
    ws = window_start.isoformat() if isinstance(window_start, date) else str(window_start)

    if recorded is not None:
        sentences: list[str] = []
        diff = None
        if previous is not None:
            diff = recorded.balance.minus(previous.balance)
            if any(v != 0 for v in diff.values()):
                sentences.append(
                    f"The balance you recorded ({rupees_paise(recorded.balance.total_paise)}) "
                    f"differs from the {rupees_paise(previous.balance.total_paise)} the "
                    f"{_period_label(previous.period)} return left in the ledger. The "
                    f"recorded figure is used, because the portal's ledger is what a "
                    f"return is actually paid from; check that the difference is a "
                    f"refund, an ITC-02 transfer or a return filed elsewhere.")
            else:
                diff = None
        return OpeningCredit(balance=recorded.balance, source=SOURCE_RECORDED,
                             window_start=ws, chain=previous, recorded=recorded,
                             recorded_minus_chain=diff, sentences=tuple(sentences))

    if previous is not None:
        sentences = []
        if not previous.is_filed:
            sentences.append(
                f"This opening is carried from the {_period_label(previous.period)} "
                f"return, which is saved here as '{previous.status}' and not marked "
                f"as filed. The portal's credit ledger only moves when a return is "
                f"filed, so if that return was filed differently — or not yet — "
                f"record the balance the portal shows instead.")
        return OpeningCredit(balance=previous.balance, source=SOURCE_PREVIOUS_RETURN,
                             window_start=ws, chain=previous,
                             sentences=tuple(sentences))

    return OpeningCredit(
        balance=CreditBalance(), source=SOURCE_NOT_RECORDED, window_start=ws,
        sentences=(NOT_RECORDED_SENTENCE,))


NOT_RECORDED_SENTENCE = (
    "No opening balance of the electronic credit ledger is recorded for this "
    "return, and no earlier return saved here carries one forward. The set-off "
    "below assumes the ledger held NOTHING at the start of the period. If the "
    "portal shows credit brought forward, record it and compute again: credit "
    "in the ledger pays output tax before any cash is due (CGST Act s.49(4)), "
    "so this cash figure may be higher than what is actually payable. It cannot "
    "be lower.")

UNREADABLE_SENTENCE = (
    "The opening balance of the electronic credit ledger could not be read just "
    "now, so the set-off below assumes the ledger held NOTHING. Compute again "
    "before relying on the cash figure — it may be higher than what is payable.")


def unreadable(window_start: "date | str") -> OpeningCredit:
    ws = window_start.isoformat() if isinstance(window_start, date) else str(window_start)
    return OpeningCredit(balance=CreditBalance(), source=SOURCE_UNREADABLE,
                         window_start=ws, sentences=(UNREADABLE_SENTENCE,))


def ledger_block(opening: OpeningCredit, *, closing: CreditBalance,
                 window_end: str) -> dict:
    """The one block a return carries about the credit ledger.

    `closing` is what the set-off LEFT, computed by `compute_gstr3b` — this
    function only presents it beside the opening, so the two cannot be
    assembled differently by two callers. `window_end` becomes
    `closing_as_of`, the exact key the next return's chain looks up.
    """
    return {
        "opening": opening.as_dict(),
        "closing": closing.as_dict(),
        "closing_as_of": window_end,
        # Spent = opening + this return's own credit - closing is derivable by a
        # reader from the return's other figures; it is deliberately not a
        # second stored number here.
        "note": (
            "The electronic credit ledger is a running balance and is per GSTIN. "
            "The closing figure is what THIS return computed; it moves the "
            "portal's ledger only once the return is filed there."),
    }


def statement_columns(block: object) -> dict:
    """The ten `gstr3b_returns.credit_*` columns a saved return records, read off
    the `credit_ledger` block `gstr3b_from_books` served.

    A SAVE carries the block back unchanged and this is the one place that turns
    it into columns, so the API's save and anything else that stores a return
    cannot read the block two ways. It REFUSES a block that is not whole — a
    missing head read as nil would record a closing balance nobody computed, and
    the next return would open with it.

    `closing_as_of` is checked for being a date only; that it is the END OF THE
    WINDOW THE RETURN COVERS is the caller's check, because only the caller
    holds the registration's filing frequency.
    """
    if not isinstance(block, dict):
        raise CreditLedgerError("The credit-ledger statement is missing.")
    opening = block.get("opening")
    closing = block.get("closing")
    as_of = block.get("closing_as_of")
    if not isinstance(opening, dict) or not isinstance(closing, dict):
        raise CreditLedgerError("The credit-ledger statement must carry an opening and a closing balance.")
    source = opening.get("source")
    if source not in SOURCES:
        raise CreditLedgerError(
            f"The opening balance's source must be one of {', '.join(SOURCES)}, not {source!r}.")
    open_bal = opening.get("balance")
    if not isinstance(open_bal, dict) or not isinstance(closing, dict):
        raise CreditLedgerError("The opening balance is missing.")
    try:
        date.fromisoformat(str(as_of))
    except ValueError:
        raise CreditLedgerError(
            f"The closing balance's date must be written YYYY-MM-DD, not {as_of!r}.")
    out: dict = {}
    for prefix, src in (("credit_opening", open_bal), ("credit_closing", closing)):
        for h in HEADS:
            key = f"{h}_paise"
            if key not in src:
                raise CreditLedgerError(
                    f"The {prefix.split('_')[1]} balance has no {h.upper()} figure.")
        bal = CreditBalance(*(src[f"{h}_paise"] for h in HEADS))
        for h in HEADS:
            out[f"{prefix}_{h}_paise"] = getattr(bal, f"{h}_paise")
    out["credit_closing_as_of"] = str(as_of)
    out["credit_opening_source"] = source
    return out
