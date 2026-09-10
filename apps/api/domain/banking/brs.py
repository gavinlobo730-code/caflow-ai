"""
The Bank Reconciliation Statement — the two-sided one an accountant means.

WHAT WAS THERE BEFORE, AND WHY IT IS NOT THIS

    `domain/banking/reconciliation.tie_out` proves one arithmetic identity:

        opening + reconciled deposits − reconciled withdrawals ± adjustments
          == the statement's closing balance

    Every row it knows about is a STATEMENT line: the reconciled, the
    unreconciled and the exceptions all come out of `bank_transactions`. Nothing
    in that module reads `journal_entries` or `journal_lines` at all.

    So a cheque issued and entered in the books but not yet presented at the
    bank has no row anywhere in it, and neither does a deposit banked but not
    yet credited. Those two are the whole substance of a BRS. The document the
    product printed under the title "Bank Reconciliation Statement" was a
    statement-line tick-off plus a difference — the wrong document, under the
    most recognisable accountant-facing title in the module.

WHAT A BRS IS

    Balance as per Cash Book (the books)                          X
      Add:  cheques issued but not yet presented                  +
      Less: cheques/deposits banked but not yet credited          −
      Add:  amounts credited by the bank, not yet in the books    +
      Less: amounts debited by the bank, not yet in the books     −
      = Balance as per Pass Book (the bank)                       Y

    All four are the same rule seen from two sources, and this module computes
    it that way rather than as four special cases:

        bank balance = book balance
                       + Σ (credit − debit) over BOOK entries the bank has not seen
                       + Σ (credit − debit) over BANK lines the books have not seen

    A book line's credit is money out of the account; a bank line's credit is
    money in. That is not an inconsistency to normalise away — it is what makes
    the same expression produce "add the unpresented cheque" and "deduct the
    bank charge". The four buckets below are that one sum, split for display.

WHAT MAKES AN ITEM "NOT SEEN BY THE BANK", AND WHY THE DATE DECIDES

    A statement line records `posted_journal_id` when the bank module posts it.
    So the entries the bank has seen are the ones some statement line points at
    — but only a statement line DATED ON OR BEFORE the as-at date.

    That qualifier is the whole reason a BRS can be produced for a past date. A
    cheque entered on 28 March and presented on 5 April IS linked, permanently,
    once April's statement is imported. At 31 March it must still be an
    unpresented cheque, because on 31 March the bank had not paid it. Dropping
    the date test would make every historical BRS change the moment the next
    month was imported — the working paper would stop agreeing with itself.

    It falls out for free here: `bank_txns` is already filtered to the period, so
    an entry linked only by a later line simply has no link in this window.

WHY A CAP ON THE LISTS AND NOT ON THE TOTALS

    The reconciling items are usually a handful. On an account nobody has ever
    reconciled they are EVERY book entry, which is proportional to transaction
    volume — the thing CLAUDE.md's reporting rule forbids putting on the wire.
    So the totals are computed over everything and are always exact, and the
    ITEM LISTS are capped, with `count` and `listed` saying what was dropped. A
    truncated list that claims to be complete would be worse than a slow one.
"""
from __future__ import annotations

from typing import Optional, Sequence

#: How many items of each bucket are listed. The totals ignore this.
LIST_CAP = 500


def reconciling_items(
    book_lines: Sequence[dict],
    bank_txns: Sequence[dict],
    *,
    as_of: str,
    statement_balance_paise: Optional[int] = None,
    list_cap: int = LIST_CAP,
) -> dict:
    """The BRS for one bank account as at one date.

    `book_lines` are the journal lines on the account's GL account from posted,
    undeleted entries dated on or before `as_of`; `bank_txns` are the statement
    lines for the account dated on or before `as_of`. Both are supplied by the
    caller — this module reads no database, so the SQL twin
    (`public.bank_reconciling_items`, migration 356) can produce the identical
    answer from the same rows.

    `statement_balance_paise` is what the BANK says the balance is: the closing
    balance a CA typed onto the reconciliation, or the running balance on the
    last statement line. It is evidence from outside this computation, so when
    it is absent the answer says the statement could not be proved rather than
    inventing a zero.
    """
    seen_by_bank = {str(t["posted_journal_id"]) for t in bank_txns
                    if t.get("posted_journal_id")}

    book_balance = sum(int(l.get("debit_paise") or 0) - int(l.get("credit_paise") or 0)
                       for l in book_lines)

    unseen = [l for l in book_lines if str(l.get("entry_id")) not in seen_by_bank]
    bank_only = [t for t in bank_txns if not t.get("posted_journal_id")]

    # Money OUT of the account per the books that the bank has not paid yet.
    unpresented = _bucket(
        [l for l in unseen if int(l.get("credit_paise") or 0) > 0],
        amount=lambda l: int(l["credit_paise"]), kind="book", cap=list_cap)
    # Money IN per the books that the bank has not credited yet.
    in_transit = _bucket(
        [l for l in unseen if int(l.get("debit_paise") or 0) > 0],
        amount=lambda l: int(l["debit_paise"]), kind="book", cap=list_cap)
    # At the bank, not in the books: interest and direct credits...
    bank_credits = _bucket(
        [t for t in bank_only if int(t.get("credit_paise") or 0) > 0],
        amount=lambda t: int(t["credit_paise"]), kind="bank", cap=list_cap)
    # ...charges, standing instructions, returned cheques.
    bank_debits = _bucket(
        [t for t in bank_only if int(t.get("debit_paise") or 0) > 0],
        amount=lambda t: int(t["debit_paise"]), kind="bank", cap=list_cap)

    computed = (book_balance
                + unpresented["total_paise"] - in_transit["total_paise"]
                + bank_credits["total_paise"] - bank_debits["total_paise"])

    out = {
        "as_of": as_of,
        "book_balance_paise": book_balance,
        "unpresented_cheques": unpresented,
        "deposits_in_transit": in_transit,
        "bank_credits_not_in_books": bank_credits,
        "bank_debits_not_in_books": bank_debits,
        "computed_bank_balance_paise": computed,
        "statement_balance_paise": None,
        "difference_paise": None,
        "agrees": None,
        "gap": None,
    }
    if statement_balance_paise is None:
        out["gap"] = (
            "The balance the bank states at this date is not known — the "
            "statement carries no running balance and none was typed in — so "
            "this statement reconciles the books to a figure nothing has "
            "confirmed.")
        return out

    stated = int(statement_balance_paise)
    out["statement_balance_paise"] = stated
    out["difference_paise"] = stated - computed
    out["agrees"] = out["difference_paise"] == 0
    return out


def _bucket(rows: Sequence[dict], *, amount, kind: str, cap: int) -> dict:
    """One side of the statement: its items, its exact total, and what was cut.

    Ordered by date then id, and the id tie-break is a plain code-point compare
    so the SQL twin can reproduce it with COLLATE "C". Sorting a display list by
    something the database orders differently is how two implementations of one
    report start disagreeing on page two.
    """
    # A book row is identified by its LINE, not its entry: one entry can carry
    # two lines on the bank account, and two rows sharing a sort key make the
    # order unstable — which is how two implementations of one report start
    # disagreeing on page two. `entry_id` stays what the bank-link test uses.
    key = "line_id" if kind == "book" else "id"
    date_key = "entry_date" if kind == "book" else "transaction_date"
    ordered = sorted(rows, key=lambda r: (str(r.get(date_key) or ""), str(r.get(key) or "")))
    total = sum(amount(r) for r in ordered)
    listed = [{
        "id": str(r.get(key)),
        "date": str(r.get(date_key) or ""),
        # A cheque number is what makes an unpresented cheque findable, and it is
        # the column Tally's BRS leads with.
        "reference_no": r.get("reference_no"),
        "particulars": (r.get("narration") if kind == "book" else r.get("description")) or "",
        "amount_paise": amount(r),
        "source": kind,
    } for r in ordered[:cap]]
    return {
        "items": listed,
        "total_paise": total,
        "count": len(ordered),
        "listed": len(listed),
    }
