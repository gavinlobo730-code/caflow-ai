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
from typing import Any, Callable, Optional

_logger = logging.getLogger("caflow.db.paging")

# PostgREST's default db-max-rows. Pages are requested at exactly this size, so
# a full page is the ambiguous case and a short one is unambiguous.
PAGE = 1000

# A page count no legitimate query should reach. Without it, a `make_query` that
# ignores the cursor loops forever on page one — a hang instead of a wrong
# answer, which is not an improvement.
MAX_PAGES = 1000


def fetch_all(
    make_query: Callable[[], Any],
    key: str = "id",
    *,
    label: str = "",
    stats: Optional[dict] = None,
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
    """
    out: list[dict] = []
    cursor: Any = None
    pages = 0

    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        page = q.order(key).limit(PAGE).execute().data or []
        pages += 1
        out.extend(page)

        if len(page) < PAGE:
            break

        if pages >= MAX_PAGES:
            # Loud, because silence is the failure mode this module exists to
            # remove. Returning what we have beats hanging, but it must be said.
            _logger.error(
                "fetch_all(%s) hit the %d-page cap at %d rows — the cursor is "
                "probably not advancing (is `%s` in the projection, and unique?)",
                label or "unlabelled", MAX_PAGES, len(out), key,
            )
            break

        cursor = page[-1].get(key)
        if cursor is None:
            _logger.error(
                "fetch_all(%s): last row has no `%s`, so paging cannot continue "
                "— returning %d rows, which may be incomplete.",
                label or "unlabelled", key, len(out),
            )
            break

    if stats is not None:
        stats["pages"] = pages
        stats["rows"] = len(out)
    return out
