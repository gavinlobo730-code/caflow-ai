"""
A list that stops at a number says it stopped.

WHY THIS MODULE EXISTS
    A screen asked for "the latest 100" and was handed 100 rows. Whether the
    firm had 100 or 4,000 behind them, the answer looked the same, and every
    heading, tile and "N entries" caption beside it was computed from the
    window as though it were the whole. `core/db_paging` answers the opposite
    question (read EVERY row, because a figure is built from them); this one is
    for a list a person scrolls, where reading every row would be the wrong
    cost and the right answer is "here are the latest N, and there are more".

THE RULE
    Ask the database for ONE ROW MORE than the window (`probe`). If that extra
    row comes back, more exist: `split` hands back the window and `True`. Never
    a row count, for the reason `db_paging` gives: a count beside an embedded
    relation or a row-level filter is the figure that goes wrong first.

    A caller that narrows the rows AFTER the read (`filter_by_client` drops the
    clients a person is not assigned to) still takes `has_more` from the read,
    not from what is left. A scoped person can therefore see a short window
    with "more" set, which is true: more rows exist and the person may or may
    not be allowed to see them. The reverse, a short window reported complete
    because the filter ate the overflow, is the silent cap this fixes.

    `MAX_LIST_LIMIT` is the ceiling a caller may ask for. It is served to the
    screen (`max_limit`) so the browser never carries its own copy.
"""
from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")

DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500


def probe(limit: int) -> int:
    """How many rows to fetch for a window of `limit`: one more than it."""
    return limit + 1


def split(rows: Sequence[T], limit: int) -> tuple[list[T], bool]:
    """(the window, whether more rows exist beyond it).

    `rows` is what a read made with `probe(limit)` returned."""
    rows = list(rows)
    return rows[:limit], len(rows) > limit
