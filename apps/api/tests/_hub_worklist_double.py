"""A PostgREST double just wide enough to RUN `hub_worklist_service`.

Not a general fake. It supports exactly the calls that module makes — the
`_python_twin` chain (`select`/`eq`/`in_`/`gt`/`is_`, then `fetch_all`'s
`gt`/`order`/`limit`/`execute`), the bounded name lookup and the client COUNT —
and nothing else, so it cannot quietly accept a filter the real client would
refuse.

⚠️ IT DELIBERATELY HAS NO `rpc`. `_rows` prefers the SQL function and falls back
to the twin only when the handle cannot do RPC or the call raises; a double with
an `rpc` attribute would send the mock suite down a path that does not exist
there, and one without it is what makes the twin the thing under test. The
`_pg` parity file feeds the SAME double from the seeded rows and compares it to
what Postgres answers, which is the only place both halves run on one input.

`tests/test_a_file_in_tests_is_a_test_or_a_named_helper.py` is why this is
`_hub_worklist_double.py` and not `hub_worklist_double.py`.
"""
from __future__ import annotations

from typing import Any, Optional


class _Result:
    def __init__(self, data: list[dict], count: Optional[int] = None):
        self.data = data
        self.count = count


class _Query:
    """⚠️ THE PROJECTION IS APPLIED AT `execute`, NOT AT `select`, and the first
    draft got that backwards. PostgREST filters server-side on the whole row
    and returns only the named columns, so `.select("id,client_id").eq(
    "firm_id", …)` is an ordinary, correct query — projecting first made the
    tenancy filter match nothing and every worklist came back empty. A double
    that is stricter than the thing it stands in for fails working code, which
    is the same class of defect as one that is laxer."""

    def __init__(self, rows: list[dict], *, counting: bool = False,
                 project: Optional[list[str]] = None):
        self._rows = rows
        self._counting = counting
        self._project = project
        self._limit: Optional[int] = None
        self._order: Optional[str] = None

    # ── filters ─────────────────────────────────────────────────────────────
    def eq(self, col: str, val: Any) -> "_Query":
        return self._with([r for r in self._rows if r.get(col) == val])

    def in_(self, col: str, vals: list) -> "_Query":
        wanted = set(vals)
        return self._with([r for r in self._rows if r.get(col) in wanted])

    def gt(self, col: str, val: Any) -> "_Query":
        return self._with([r for r in self._rows
                           if r.get(col) is not None and _cmp(r[col], val) > 0])

    def is_(self, col: str, what: str) -> "_Query":
        assert what == "null", f"the double only knows is_(col, 'null'), got {what!r}"
        return self._with([r for r in self._rows if r.get(col) is None])

    # ── paging ──────────────────────────────────────────────────────────────
    def order(self, col: str) -> "_Query":
        q = self._with(sorted(self._rows, key=lambda r: str(r.get(col))))
        q._order = col
        return q

    def limit(self, n: int) -> "_Query":
        q = self._with(self._rows)
        q._limit = n
        return q

    def execute(self) -> _Result:
        rows = self._rows[: self._limit] if self._limit is not None else self._rows
        # Only the named columns cross the wire. A service that reads a column
        # it did not select gets a KeyError here exactly as it would in
        # production, which a double returning whole rows would hide.
        out = [{k: r.get(k) for k in self._project} if self._project else dict(r)
               for r in rows]
        if self._counting:
            # PostgREST returns the FULL count in the header and at most
            # `limit` rows on the wire — the idiom `_client_count` relies on.
            return _Result(out, count=len(self._rows))
        return _Result(out)

    def _with(self, rows: list[dict]) -> "_Query":
        q = _Query(rows, counting=self._counting, project=self._project)
        q._limit, q._order = self._limit, self._order
        return q


def _cmp(a: Any, b: Any) -> int:
    """Numbers compare as numbers, ids as strings. `fetch_all`'s cursor is an
    id and `outstanding_paise > 0` is money, and one comparison cannot serve
    both — a string compare would put '9' after '10'."""
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        a = int(a)
        return (a > b) - (a < b)
    a, b = str(a), str(b)
    return (a > b) - (a < b)


class Double:
    """`{table: [row, ...]}`. Rows are dicts exactly as PostgREST returns them."""

    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str) -> "_Table":
        return _Table(self.tables.get(name, []))


class _Table:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def select(self, cols: str, count: Optional[str] = None) -> _Query:
        names = [c.strip() for c in cols.split(",") if c.strip() and c.strip() != "*"]
        return _Query([dict(r) for r in self._rows],
                      counting=count == "exact",
                      project=names or None)
