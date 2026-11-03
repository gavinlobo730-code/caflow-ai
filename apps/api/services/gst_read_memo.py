"""A memo of reads that cannot change while ONE amendment build runs (POST-A-265).

WHAT WAS WRONG
    A GSTR-1 build carries the amendments the period owes, which asks for each earlier filed period what has moved since it was filed, and
    each answer rebuilds that period's GSTR-1 from the books. Every rebuild made the same client-wide reads again (the client, its
    registrations, the year's turnover, whether its advances bear tax), the same reads of the books over a window one month wide (invoices
    twice, credit notes, debit notes, their lines, their customers) and, until this change, the whole ledger of the month (every entry
    dated in it and then every line of each). For a client with a year of returns that was about seventeen reads a period and a build
    that slowed with every month filed, on a host a continent from its database and against a browser that gives up at forty-five seconds.
    The earlier periods are now rebuilt four at a time; this removes the repeated reads.

WHAT IT IS
    A scope, opened by the one caller that rebuilds many periods of one client (`gst_amendment_service.outstanding_amendments`), inside
    which two kinds of read are remembered:
      * `remember(key, loader)` - a read keyed by what it asked for (the client row, its registrations, a year's turnover). Single flight:
        the first caller loads, a concurrent one waits for it and uses its answer; a loader that raises is not remembered, so every waiter
        asks again and sees its own failure, as it did before.
      * `window_rows(kind, firm, client, start, end, date_field, loader)` - rows of one table over a date window. With a window primed
        (`open(window=(lo, hi))`), a call for a span inside it loads (lo, hi) ONCE and answers each span by slicing on the date column,
        which is the comparison the query made (the columns are DATES and the bounds ISO dates, so the strings compare as the dates do);
        a span outside the window, or no window, loads exactly what it was asked for.
      * `rows_by_id(kind, ids, loader)` - rows looked up by id (customers; a document's lines): ids not yet held are loaded together, the
        ones already held are not asked for again, and an id the database did not return is remembered as absent.

WHAT IT IS NOT
    It is not a cache across requests and it holds nothing outside a scope: with no scope open every function here calls its loader and
    nothing is remembered, so every other caller of every reader it wraps behaves exactly as before. What it remembers is read-only for
    the length of one build (nothing in that build writes a client, a registration, a turnover figure or a document), and every value
    handed out is a COPY, so a caller that annotates a row cannot change what the next period reads.
"""
from __future__ import annotations

import contextvars
import copy
import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, Optional

_ACTIVE: contextvars.ContextVar[Optional["_Memo"]] = contextvars.ContextVar("gst_read_memo", default=None)


class _Cell:
    __slots__ = ("done", "value")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None


class _Memo:
    def __init__(self, window: Optional[tuple[str, str]]) -> None:
        self.window = window
        self._lock = threading.Lock()
        self._cells: dict[Any, _Cell] = {}
        #: how many reads were made and how many answered from the memo, for the tests and for a log line; never read for a decision
        self.loads = 0
        self.hits = 0

    def once(self, key: Any, loader: Callable[[], Any]) -> Any:
        while True:
            with self._lock:
                cell = self._cells.get(key)
                mine = cell is None
                if mine:
                    cell = self._cells[key] = _Cell()
            if not mine:
                cell.done.wait()
                if cell.done.is_set() and cell.value is not _FAILED:
                    with self._lock:
                        self.hits += 1
                    return cell.value
                continue                                    # the first caller failed: ask again, as if it had never been asked
            try:
                value = loader()
            except BaseException:
                cell.value = _FAILED
                with self._lock:
                    self._cells.pop(key, None)
                cell.done.set()
                raise
            with self._lock:
                self.loads += 1
            cell.value = value
            cell.done.set()
            return value


_FAILED = object()


@contextmanager
def scope(window: Optional[tuple[str, str]] = None) -> Iterator[_Memo]:
    """Open a memo for the code that runs inside (and in the threads it copies this context into). `window` is (first day, last day) as
    ISO dates: the span `window_rows` may load once and slice."""
    memo = _Memo(window)
    token = _ACTIVE.set(memo)
    try:
        yield memo
    finally:
        _ACTIVE.reset(token)


def active() -> Optional[_Memo]:
    return _ACTIVE.get()


def remember(key: Any, loader: Callable[[], Any]) -> Any:
    """`loader()`, remembered under `key` for the length of the scope; a copy each time. With no scope: `loader()`, remembered nowhere."""
    memo = _ACTIVE.get()
    if memo is None:
        return loader()
    return copy.deepcopy(memo.once(("remember", key), loader))


def window_rows(kind: str, firm_id: str, client_id: str, start: str, end: str, date_field: str,
                loader: Callable[[str, str], list[dict]]) -> list[dict]:
    """The rows of `loader(start, end)`, answered from one wider read when the scope has a window that holds [start, end]."""
    memo = _ACTIVE.get()
    if memo is None or memo.window is None or not (memo.window[0] <= start and end <= memo.window[1]):
        return loader(start, end)
    lo, hi = memo.window
    rows = memo.once(("window", kind, firm_id, client_id), lambda: list(loader(lo, hi)))
    return [dict(r) for r in rows if start <= str(r.get(date_field) or "")[:10] <= end]


def rows_by_id(kind: str, firm_id: str, ids: Iterable[str], loader: Callable[[list[str]], list[dict]],
               id_field: str = "id") -> list[dict]:
    """The rows for `ids` (those the database holds), loading only the ids this scope has not already asked for."""
    wanted = [i for i in dict.fromkeys(ids) if i]
    memo = _ACTIVE.get()
    if memo is None or not wanted:
        return loader(wanted) if wanted else []
    missing: list[str] = []
    for i in wanted:
        with memo._lock:
            held = ("by_id", kind, firm_id, i) in memo._cells
        if not held:
            missing.append(i)
    if missing:
        fetched = loader(missing)
        by = {}
        for r in fetched:
            by.setdefault(r.get(id_field), []).append(r)
        for i in missing:
            with memo._lock:
                cell = memo._cells.setdefault(("by_id", kind, firm_id, i), _Cell())
                cell.value = by.get(i, [])
                cell.done.set()
            memo.loads += 1
    out: list[dict] = []
    for i in wanted:
        with memo._lock:
            cell = memo._cells.get(("by_id", kind, firm_id, i))
        if cell is not None and cell.value:
            out.extend(dict(r) for r in cell.value)
            if i not in missing:
                memo.hits += 1
    return out
