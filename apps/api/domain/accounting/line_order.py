"""The order a voucher's lines are shown in — one rule, two implementations
(ACC-16).

WHAT WAS WRONG
    `journal_lines` had no ordering column, so a voucher's lines came back in
    whatever order Postgres returned them. That is not stable: a CA opening the
    same manual journal twice could see the debits and credits interleaved
    differently each time, and a four-line bank charge (expense, CGST, SGST,
    bank) had no reason to read in the order it was entered.

THE RULE
    1. `line_order` where the line has one — migration 384 records the position
       of each line in the array `post_journal_atomic` was called with, which
       IS the posting function's own intent. This is the whole answer for
       anything written from 384 onwards.
    2. Otherwise DEBITS BEFORE CREDITS. That is the convention every voucher in
       Indian practice is written in, and it is what makes an old entry read
       right without touching it.
    3. Then `created_at`, then `id`. Neither is meaningful on a batch insert —
       the rows usually share a timestamp and the id is a random uuid — but
       together they are TOTAL, which is the property that matters: the same
       voucher renders the same way on every read.

WHY THERE IS NO BACKFILL
    Migration 251 makes a posted line immutable. Writing an order onto every
    historic line would mean disabling that trigger against production, as a
    reviewable act, for a DISPLAY order. Deriving instead gets the same visible
    outcome — see the migration's own note.

ONE IMPLEMENTATION, AND THAT WAS CHECKED RATHER THAN ASSUMED
    A browser mirror was nearly written, on the reasonable-sounding ground that
    the client accounting screen reads `journal_lines` straight over PostgREST
    (CLAUDE.md, "The frontend's second data path"). It does — but only to SUM
    the debits into the amount column; it never renders a line. The one place a
    CA SEES a voucher's lines is the journal editor, which reads
    `GET /api/accounting/journal/{id}` and therefore reads this.

    So there is no TypeScript copy, deliberately. A second implementation of a
    rule nothing on that side needs is the drift this codebase keeps having to
    record. If a screen ever renders lines out of a direct PostgREST read, the
    rule has to be mirrored and pinned — PostgREST cannot express "debits
    before credits" as an ORDER BY, having neither expression ordering nor a
    boolean column to sort on — and `tests/fixtures/journal_line_order.json`
    is already the table for it.
"""
from __future__ import annotations

from typing import Any, Iterable

#: The columns a caller must select for this to work. A read that omits
#: `line_order` gets rule 2 for every line, including new ones — deterministic,
#: and quietly the wrong order. Named so a query can be checked against it.
REQUIRED_COLUMNS = ("line_order", "debit_paise", "created_at", "id")


def _key(row: dict) -> tuple:
    raw = row.get("line_order")
    try:
        ordered = raw is not None and int(raw) >= 0
    except (TypeError, ValueError):
        ordered = False
    return (
        # A line WITH an order sorts before one without. Within one voucher
        # they are all one or all the other — every posting writes its lines in
        # a single call — so this term only ever separates whole vouchers.
        0 if ordered else 1,
        int(raw) if ordered else 0,
        0 if int(row.get("debit_paise") or 0) > 0 else 1,
        str(row.get("created_at") or ""),
        str(row.get("id") or ""),
    )


def in_display_order(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The voucher's lines, in the order a CA should read them.

    Pure and total: it never raises on a missing or malformed field, because a
    display order that throws is worse than one that is merely conventional.
    """
    return sorted(rows, key=_key)
