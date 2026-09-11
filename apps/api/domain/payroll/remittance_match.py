"""Which journal entry paid this statutory remittance? (Track F, phase F4)

WHAT THIS IS FOR

`public.statutory_remittances.journal_entry_id` (migration 365) is a LINK, not
a posting path. `services/bank_posting_service.post` already writes
Dr <liability> / Cr Bank when the CA passes the bank statement line, and it is
the one path for money movement — posting from the remittance record as well
would debit the statutory liability twice.

What the link buys is the one question the ledger cannot answer on its own:
**a liability nobody has paid and a liability that was paid but never tied back
look identical**. Both sit uncleared on ESI Payable at year end. This module
offers the CA the entries that could be the payment, so the second kind can be
matched and only the first kind is left to chase.

THE FIGURE TO MATCH ON IS WHAT LEFT THE BANK, NOT THE LIABILITY

This is the part that is easy to get backwards, and getting it backwards makes
the matcher miss exactly the remittances a CA most needs to find.

`statutory_remittances.amount_paise` is the CHALLAN's figure — migration 365
says so in as many words — and a challan can carry more than the liability.
Interest and damages under ESI Act s.39(5) are added at the portal, and they
are an EXPENSE, not a reduction of the payable:

    Dr  ESI Payable                      10,000
    Dr  Interest on Statutory Dues          500
      Cr  Bank                                     10,500

Matching the challan against the DEBIT TO ESI PAYABLE would fail on every late
remittance — which is to say, on every remittance that carried interest, which
is precisely the population a reconciliation is for. The entry TOTAL is what
left the bank, and a balanced entry's total is its credit side, so no account
has to be classified as a bank for this to work.

NOTHING IS EVER LINKED AUTOMATICALLY

A candidate is offered with a REASON SENTENCE and never a score — the same rule
the bank-entry drafts follow (docs/architecture/09). "Exact" here means the
amount and the account agree, not that the machine is confident; a CA who paid
two identical challans in one week has two exact candidates and is the only one
who can say which is which.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from domain.reporting.amount_words import indian_digits

#: How far either side of the recorded payment date to look.
#:
#: Seven days, and the number is a judgement rather than a rule: a challan paid
#: by net banking debits the same day, one paid by cheque clears over a few, and
#: a CA recording the challan date from the portal receipt may be a day out
#: either way. Wider would start offering the NEXT month's remittance as a
#: candidate for this one — ESI and PT are monthly, and two consecutive months'
#: payments are about thirty days apart, so seven each side stays well clear.
DEFAULT_WINDOW_DAYS = 7

EXACT = "exact"
NEAR = "near"


@dataclass(frozen=True)
class Candidate:
    """One journal entry that could be the payment, and why it is offered."""
    journal_entry_id: str
    entry_date: str
    reference_no: Optional[str]
    narration: Optional[str]
    #: The debit to THIS scheme's liability account — what the entry cleared.
    liability_debit_paise: int
    #: The entry's total, which for a payment entry is what left the bank.
    entry_total_paise: int
    days_apart: int
    grade: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "journal_entry_id": self.journal_entry_id,
            "entry_date": self.entry_date,
            "reference_no": self.reference_no,
            "narration": self.narration,
            "liability_debit_paise": self.liability_debit_paise,
            "entry_total_paise": self.entry_total_paise,
            "days_apart": self.days_apart,
            "grade": self.grade,
            "reason": self.reason,
        }


def _rupees(paise: int) -> str:
    """Paise as ₹ for a sentence a CA reads. Display only; the wire stays paise.

    DELEGATES the grouping. The first draft of this module used Python's own
    `f"{n:,}"`, which groups in threes — so ₹1,25,000 came out as "₹125,000",
    a figure no Indian document uses and one the browser (Intl.NumberFormat
    "en-IN") renders correctly two lines away on the same screen.
    `domain/reporting/amount_words.indian_digits` already exists for exactly
    this, with the same reasoning written on it.

    The paise are kept rather than truncated the way `indian_rupees` does:
    `indian_rupees` states a figure in a sentence about a return, where whole
    rupees is right; here the sentence is a comparison between a challan and a
    bank debit, and a difference of a few paise is the whole reason the two
    would not match.
    """
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    whole, part = divmod(abs(p), 100)
    return f"{sign}₹{indian_digits(whole)}.{part:02d}"


def _days_between(a: str, b: str) -> Optional[int]:
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except (ValueError, TypeError):
        return None


def _reason(*, exact: bool, days: int, entry_total: int, liability_debit: int,
            amount: int) -> str:
    when = ("dated the same day" if days == 0
            else f"dated {days} day{'s' if days != 1 else ''} away")

    if exact:
        base = f"{_rupees(entry_total)} left the bank, {when}."
    else:
        difference = entry_total - amount
        direction = "more" if difference > 0 else "less"
        base = (f"{_rupees(entry_total)} left the bank, {when} — "
                f"{_rupees(abs(difference))} {direction} than the challan.")

    # The interest case, named rather than left for the CA to work out from two
    # numbers. It is the ordinary shape of a LATE remittance, not an anomaly.
    if entry_total > liability_debit:
        base += (f" {_rupees(liability_debit)} of it cleared the liability; the "
                 f"rest went elsewhere — interest or damages on the challan, or "
                 f"another head paid on the same entry.")
    elif entry_total < liability_debit:
        base += (f" It debits {_rupees(liability_debit)} of the liability, more "
                 f"than left the bank, so part of it was settled another way.")
    return base


def candidates(
    *,
    amount_paise: int,
    paid_on: Optional[str],
    entries: list[dict],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[Candidate]:
    """Entries that could have paid a remittance, best first.

    `entries` are already filtered by the caller to posted entries of this
    client that DEBIT the scheme's own liability account — that filter is what
    makes a candidate a candidate at all, and it belongs in the query rather
    than here, where it would mean fetching the whole ledger to discard it.

    A remittance with no `paid_on` gets NOTHING back rather than everything.
    Without a date there is no window, and offering every entry that ever
    touched ESI Payable is not a shortlist — it is the ledger, re-presented as
    a suggestion.
    """
    if not paid_on:
        return []

    out: list[Candidate] = []
    for e in entries:
        entry_date = str(e.get("entry_date") or "")[:10]
        days = _days_between(entry_date, paid_on)
        if days is None or days > window_days:
            continue
        entry_total = int(e.get("entry_total_paise") or 0)
        liability_debit = int(e.get("liability_debit_paise") or 0)
        exact = entry_total == int(amount_paise or 0)
        out.append(Candidate(
            journal_entry_id=str(e.get("journal_entry_id") or e.get("id") or ""),
            entry_date=entry_date,
            reference_no=e.get("reference_no"),
            narration=e.get("narration"),
            liability_debit_paise=liability_debit,
            entry_total_paise=entry_total,
            days_apart=days,
            grade=EXACT if exact else NEAR,
            reason=_reason(exact=exact, days=days, entry_total=entry_total,
                           liability_debit=liability_debit,
                           amount=int(amount_paise or 0)),
        ))

    # Exact first, then nearest in time, then nearest in amount. Ties broken by
    # entry id so the order is stable — a list that reshuffles between two loads
    # of the same screen is one a CA stops trusting.
    out.sort(key=lambda c: (
        0 if c.grade == EXACT else 1,
        c.days_apart,
        abs(c.entry_total_paise - int(amount_paise or 0)),
        c.journal_entry_id,
    ))
    return out
