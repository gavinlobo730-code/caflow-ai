"""A PostgREST double that has the ROW CAP, for tests that exist to prove a read pages.

A double that returns everything from one `.execute()` cannot tell a paged read from an unpaged one, so it passes
against exactly the defect those tests are written for. This one answers at most `DB_MAX_ROWS` rows per request, the way
the hosted service does, supports the filters the paged reads use, and records the filters it was asked for.
"""
from __future__ import annotations

DB_MAX_ROWS = 1000


class _Resp:
    def __init__(self, data):
        self.data = data


class CappedQuery:
    def __init__(self, rows, log, selects=None):
        self._rows, self._log = rows, log
        self._selects = selects
        self._ops: list[tuple[str, str, object]] = []
        self._gt = None
        self._order = None
        self._limit = None

    # builder surface
    def select(self, cols="*", *_a, **_k):
        if self._selects is not None:
            self._selects.append(cols)
        return self
    def eq(self, col, v): self._ops.append(("eq", col, v)); return self
    def neq(self, col, v): self._ops.append(("neq", col, v)); return self
    def lt(self, col, v): self._ops.append(("lt", col, v)); return self
    def is_(self, col, v): self._ops.append(("is", col, None if v in (None, "null") else v)); return self
    def gt(self, col, v): self._gt = (col, v); return self
    def order(self, col, desc=False): self._order = col; return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        self._log.append(list(self._ops))
        rows = list(self._rows)
        for op, col, v in self._ops:
            if op == "eq":
                rows = [r for r in rows if r.get(col) == v]
            elif op == "neq":
                rows = [r for r in rows if r.get(col) != v]
            elif op == "lt":
                rows = [r for r in rows if r.get(col) is not None and str(r.get(col)) < str(v)]
            elif op == "is":
                rows = [r for r in rows if r.get(col) == v]
        if self._gt:
            col, v = self._gt
            rows = [r for r in rows if str(r.get(col)) > str(v)]
        if self._order:
            rows.sort(key=lambda r: str(r.get(self._order) or ""))
        return _Resp(rows[:min(self._limit or DB_MAX_ROWS, DB_MAX_ROWS)])


class CappedDB:
    """`tables` maps a table name to its rows; an unknown table is empty."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.requests: dict[str, list] = {}
        self.selects: dict[str, list] = {}

    def table(self, name):
        return CappedQuery(self._tables.get(name, []), self.requests.setdefault(name, []),
                           self.selects.setdefault(name, []))
