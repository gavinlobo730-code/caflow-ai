"""
Read every matching row, not the first thousand.

WHY THIS MODULE EXISTS
    PostgREST caps a response at roughly 1000 rows (`db-max-rows`) and reports
    nothing when it does — no error, no flag, no short-read signal. A query that
    should return 4,000 rows returns 1,000 and looks exactly like a query that
    matched 1,000. Every consumer downstream then computes a confident, wrong
    answer from a silently truncated set.

    This is audit C6, and by 2026-08-15 it had been found five separate times in
    this codebase:

      1. domain/reporting/sources.py   the ledger, truncating financial reports
      2. core/schema_guard.py          the column list, so /health reported 401
                                       existing columns as missing and returned
                                       503 on every boot
      3. domain/tally/migration_service.py (x3)  the import list, so a Tally
                                       import wrote 1000 records and reported
                                       success; the rollback could only undo
                                       1000; the preview showed the CA 1000
                                       items to approve as if it were all
      4. services/bank_register_service.py  the bank register, whose own
                                       docstring promises the running balance is
                                       "computed over the WHOLE account, always"
      5. the rest of the bank surface  queue, reconciliation, posting lists

    Each was fixed locally, which is why it kept coming back. The fix belongs in
    one place that the next person finds before writing the sixth one.

WHY KEYSET AND NOT OFFSET
    With OFFSET, page k re-scans the k x PAGE rows before it, so walking a whole
    table is quadratic. When reporting paged the ledger with OFFSET the embedded
    per-row aggregate ran ~91k times for a 12.8k-entry client and the deep pages
    tripped the database statement timeout. Keyset makes every page a bounded
    `WHERE key > :cursor ORDER BY key LIMIT n` seek that touches only its own
    page however deep it goes.

WHY THE STOP CONDITION IS A SHORT PAGE
    Never a row count. PostgREST's count can be unreliable alongside an embedded
    relation, and trusting it would reintroduce exactly the silent truncation
    this module exists to prevent. A page shorter than the limit is the only
    honest end-of-data signal.

    That signal carries one assumption, stated here because it is invisible at
    the call sites: PAGE must not EXCEED the server's `db-max-rows`. Each page is
    requested with an explicit `.limit(PAGE)`, so a full page means "the limit we
    asked for" rather than "whatever the server felt like returning". If the
    deployment ever lowered db-max-rows below PAGE, the first page would come
    back short, be read as end-of-data, and truncate silently — the exact bug
    this module exists to prevent, wearing its fix as a disguise. Lower PAGE if
    db-max-rows is lowered; never raise it above.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterator, Optional, Sequence, Union

_logger = logging.getLogger("caflow.db.paging")

# PostgREST's default db-max-rows. Pages are requested at exactly this size, so
# a full page is the ambiguous case and a short one is unambiguous.
PAGE = 1000

# A page count no legitimate query should reach. Without it, a `make_query` that
# ignores the cursor loops forever on page one — a hang instead of a wrong
# answer, which is not an improvement.
MAX_PAGES = 1000

# The wait before the n-th retry of a failed page is n times this. A module attribute so a test can make it nothing, and `_sleep` so a
# test can see it was asked for.
RETRY_BACKOFF_SECONDS = 0.3
_sleep = time.sleep


def _read_page(build: Callable[[], Any], *, retries: int, label: str, where: Any) -> list[dict]:
    """One page, asked again up to `retries` times in all on a failure, with a growing wait (POST-A-045).

    WHY A READ IS RETRIED HERE AND NOT A WRITE. The ledger source learned this in production: for a client with 12k+ posted entries one
    page hit a transient PostgREST 500 while every other page, and the SAME page moments later, succeeded, and before the retry that one
    failure aborted the whole report, which the screen rendered as "no posted journal entries". Asking a READ again changes nothing; a
    write asked again is a duplicate, so nothing in this module writes. `retries=1` (the default) asks once and raises the failure as it
    came, which is what every caller had before. `build` returns a FRESH builder each attempt, because a builder that raised mid-execute
    is not one to reuse."""
    attempts = max(1, int(retries))
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return build().execute().data or []
        except Exception as exc:  # noqa: BLE001 — a transient PostgREST or network failure is asked again; the last one is raised
            last = exc
            if attempt < attempts:
                _logger.warning("read %s failed at %s (attempt %d of %d), asking again: %s",
                                label or "unlabelled", where, attempt, attempts, exc)
                _sleep(RETRY_BACKOFF_SECONDS * attempt)
    if attempts > 1:
        _logger.error("read %s failed at %s after %d attempts: %s", label or "unlabelled", where, attempts, last)
    raise last  # type: ignore[misc]


def iter_pages(
    make_query: Callable[[], Any],
    key: str = "id",
    *,
    label: str = "",
    stats: Optional[dict] = None,
    page_size: Optional[int] = None,
    retries: int = 1,
    strict: bool = False,
) -> Iterator[list[dict]]:
    """The pages of the rows `make_query` matches, one list per request, in keyset order over `key`.

    THE SAME READ AS `fetch_all`, handed back a page at a time. `fetch_all` is this function with every page appended to one list, which is
    right for an answer and wrong for a FILE: an export of a ledger that wrote each page as it came would hold one page in memory, and one
    that called `fetch_all` held the whole table. Everything `fetch_all` says about `make_query`, the key, the short-page stop and the
    test-double tolerance holds here (it is one implementation). An empty page is not yielded. `stats` is filled when the generator has
    been read to its end, not before.

    `page_size` is the request size and the short-page test; it must not exceed the server's `db-max-rows` (the module docstring says why)
    and exists so a test can make pages small. `retries` asks a failed page again (`_read_page`); the default asks once. `strict` RAISES
    where the read would otherwise stop early and say so in the log (the page cap, a row without the key): right for a financial
    statement, which must fail rather than add up part of a ledger.

    `make_query` is called afresh for every page, so a caller may narrow its filter between pages (an IN list of the values not yet
    found): the cursor stays valid, because a narrower filter over `key > cursor` is a subset of what the cursor was measured against.
    """
    cursor: Any = None
    pages = 0
    rows = 0
    size = page_size or PAGE          # read when called, so a test that shrinks PAGE shrinks every reader

    unused: list = []                 # the first page's builder, built once to judge it and then used, so page one is ONE builder
    while True:
        if pages == 0:
            probe = make_query()
            if not (hasattr(probe, "gt") and hasattr(probe, "order") and hasattr(probe, "limit")):
                page = list(probe.execute().data or [])
                pages = 1
                rows += len(page)
                if page:
                    yield page
                break
            unused.append(probe)

        def build(cursor=cursor):
            q = unused.pop() if unused else make_query()
            if cursor is not None:
                q = q.gt(key, cursor)
            return q.order(key).limit(size)

        page = _read_page(build, retries=retries, label=label, where=f"{key} > {cursor!r}")
        pages += 1
        rows += len(page)
        if page:
            yield page

        if len(page) < size:
            break

        if pages >= MAX_PAGES:
            if strict:
                raise RuntimeError(f"read {label or 'unlabelled'} reached the {MAX_PAGES}-page cap at {rows} rows; nothing partial "
                                   "is returned")
            # Loud, because silence is the failure mode this module exists to
            # remove. Returning what we have beats hanging, but it must be said.
            _logger.error(
                "fetch_all(%s) hit the %d-page cap at %d rows — the cursor is "
                "probably not advancing (is `%s` in the projection, and unique?)",
                label or "unlabelled", MAX_PAGES, rows, key,
            )
            break

        cursor = page[-1].get(key)
        if cursor is None:
            if strict:
                raise RuntimeError(f"read {label or 'unlabelled'}: the last row of a full page has no `{key}`, so the rest cannot be "
                                   "read; nothing partial is returned")
            _logger.error(
                "fetch_all(%s): last row has no `%s`, so paging cannot continue "
                "— returning %d rows, which may be incomplete.",
                label or "unlabelled", key, rows,
            )
            break

    if stats is not None:
        stats["pages"] = pages
        stats["rows"] = rows


def fetch_all(
    make_query: Callable[[], Any],
    key: str = "id",
    *,
    label: str = "",
    stats: Optional[dict] = None,
    page_size: Optional[int] = None,
    retries: int = 1,
    strict: bool = False,
) -> list[dict]:
    """Every row `make_query` matches, read in keyset pages over `key`.

    `make_query` must return a FRESH query builder each call — builders are
    stateful and reusing one accumulates filters across pages. Its projection
    must include `key`, or the next cursor cannot be read from the last row.

    `key` must be unique and sortable. `id` is both, and ordering a uuid column
    is stable; a non-unique key would drop or repeat rows at page boundaries.

    `stats`: optional out-parameter filled with {"pages", "rows"}. The page COUNT
    is the number worth having when something is slow, since paging is
    sequential and wall-clock is roughly pages x round trip.

    A QUERY THAT CANNOT PAGE IS READ ONCE (engineering-30). Twelve services
    carried a private copy of this loop, and nine of them carried it for one
    reason beyond the loop: a hand-written test double that implements `.eq()`
    and `.execute()` and nothing else returns its whole, small fixture from a
    single `execute()`, which is already the right answer, and the double has no
    `.gt` / `.order` / `.limit` to page with. That tolerance lives here now, once,
    and it is test-double accommodation, said as such: a PostgREST builder always
    has all three, so production never takes the branch. It is judged on the FIRST
    page's builder only, so a real query cannot slip into it halfway.
    """
    out: list[dict] = []
    for page in iter_pages(make_query, key, label=label, stats=stats, page_size=page_size, retries=retries, strict=strict):
        out.extend(page)
    return out


#: A column to order by, ascending; or (column, descending).
OrderTerm = Union[str, tuple[str, bool]]


def fetch_all_ordered(
    make_query: Callable[[], Any],
    order: Sequence[OrderTerm],
    *,
    label: str = "",
    stats: Optional[dict] = None,
    page_size: Optional[int] = None,
) -> list[dict]:
    """Every row the query matches, in a stated order that is made TOTAL by ending in `id`, read in OFFSET pages (POST-A-045).

    WHY THIS IS NOT `fetch_all`. Some reads need every row in an order of their own and not in `id` order: the stock ledger's stored
    running totals were chained in (movement date, recorded at) order and the screen shows them that way, and the stock position and
    ageing walks read movements in that order. `fetch_all`'s keyset needs one unique column to seek past, which a date is not.

    WHY THE ORDER ENDS IN `id`. OFFSET pages are only consistent when the order is total: rows that tie on every ordered column may come
    back in a different order on each request, so one can fall on both sides of a page boundary (read twice) or on neither (never read),
    silently. Ties are not rare here: an opening-stock batch inserts every item in ONE statement, so hundreds of rows share the movement
    date and the recorded-at instant. `id` is unique, so it is appended unless the caller already ordered by it, and the rows that tied
    are returned in `id` order, which is stable from request to request. What a total order does NOT cure is a write between two page
    requests: a row inserted (or deleted) ahead of the offset moves every later row by one, so one is read twice (or skipped). That was
    true of the loops this replaced too; the exact-once guarantee is for a table nobody writes to while it is read.

    WHAT OFFSET COSTS. Page k re-reads the k x `page_size` rows before it (the module docstring), so this is for reads whose size is a
    client's or an item's history, as the three callers' are, and not for a whole-tenant table. `make_query` returns a FRESH builder
    carrying the table, the projection and the filters and NO order (this applies it). A builder with no `.order`/`.range` (a test double)
    is read once, as `fetch_all` does. The stop condition is a short page, and the page cap is `MAX_PAGES`, said loudly when hit.
    """
    terms = [(o, False) if isinstance(o, str) else (str(o[0]), bool(o[1])) for o in order]
    if not any(column == "id" for column, _ in terms):
        terms.append(("id", False))
    probe = make_query()
    if not (hasattr(probe, "order") and hasattr(probe, "range")):
        if hasattr(probe, "order"):                                    # a double that sorts and cannot page: still in order
            for column, desc in terms:
                probe = probe.order(column, desc=desc)
        out = list(probe.execute().data or [])
        if stats is not None:
            stats.update(pages=1, rows=len(out))
        return out
    out: list[dict] = []
    position, pages, size = 0, 0, page_size or PAGE
    unused = [probe]                  # page one is the builder already made, so a reader counted per builder is read once
    while True:
        q = unused.pop() if unused else make_query()
        for column, desc in terms:
            q = q.order(column, desc=desc)
        page = q.range(position, position + size - 1).execute().data or []
        pages += 1
        out.extend(page)
        position += len(page)
        if len(page) < size:
            break
        if pages >= MAX_PAGES:
            _logger.error("fetch_all_ordered(%s) hit the %d-page cap at %d rows; the rest were not read",
                          label or "unlabelled", MAX_PAGES, len(out))
            break
    if stats is not None:
        stats.update(pages=pages, rows=len(out))
    return out


def fetch_window(
    make_query: Callable[[], Any],
    order_field: str,
    *,
    count: int,
    start: int = 0,
    desc: bool = True,
    id_desc: bool = False,
) -> list[dict]:
    """Up to `count` rows from position `start` of the query, in a stated total order, read in requests the server will honour.

    WHY THIS IS NOT `fetch_all`. A screen that shows a WINDOW of a register (the latest N, then the next N) needs the rows in the
    order the screen shows them, a caller's `order_field` and not `id`, and only as many as the window holds. `fetch_all` returns every
    row in `id` order. What the two share is the fault this module exists for: PostgREST answers at most `PAGE` rows to one request
    and says nothing when it cuts a response short, so a window of 2,000 asked for in one `.range()` came back 1,000 long over a client
    with 1,500 rows, and a caller that decides "more rows exist" from the answer being longer than the window read `False`
    (the TDS register lists, found by review). Each request here asks for a size the server will honour.

    The order is `order_field` (descending when `desc`) and then `id` (ascending, or descending when `id_desc`, for a list that has always
    broken a tie newest-id-first), which is unique, so consecutive requests neither repeat a row nor skip one. `make_query` returns a FRESH builder carrying the table, the projection and the filters, as for `fetch_all`. The
    stop condition is a short page and nothing else, for the reason `fetch_all` gives.
    """
    out: list[dict] = []
    position = start
    while len(out) < count:
        size = min(PAGE, count - len(out))
        ordered = make_query().order(order_field, desc=desc)
        ordered = ordered.order("id", desc=True) if id_desc else ordered.order("id")
        page = (ordered.range(position, position + size - 1).execute().data) or []
        out.extend(page)
        position += len(page)
        if len(page) < size:
            break
    return out


# How many values one `IN (...)` list carries. A PostgREST filter travels in
# the URL, and a uuid is ~37 characters once quoted and comma-separated, so 150
# is ~5.5 KB — well inside every proxy's limit.
IN_CHUNK = 150


def fetch_all_in(
    make_query: Callable[[], Any],
    column: str,
    values,
    key: str = "id",
    *,
    label: str = "",
    chunk: int = IN_CHUNK,
) -> list[dict]:
    """`fetch_all` over `column IN values`, however many values there are.

    WHY
        A PostgREST `.in_()` filter is part of the URL. Sent whole, an id list
        proportional to the ledger stops being a query and becomes a 400 from
        the gateway, BEFORE PostgREST sees it — which the client reports as an
        APIError, so the whole endpoint 500s. Measured on 28-09-2026: the
        §43B(h) report sent every one of a client's 755 purchase bill ids in
        one list, a 29,651-character URL, and failed for every financial year
        (and with it Form 3CD clauses 22/26 and the book-to-tax add-back, which
        both read it). A client with 40 bills was fine, which is why no test
        and no small demo client ever saw it.

    `make_query` returns a FRESH builder WITHOUT the IN filter; this adds it
    per chunk. The chunks are disjoint value sets on one column, so no row can
    come back twice. Values are de-duplicated and sorted first so the same set
    always produces the same requests.
    """
    wanted = sorted({str(v) for v in (values or []) if v is not None})
    out: list[dict] = []
    for i in range(0, len(wanted), chunk):
        part = wanted[i:i + chunk]
        out.extend(fetch_all(lambda part=part: make_query().in_(column, part),
                             key, label=label))
    return out
