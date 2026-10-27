"""A PostgREST-shaped client that runs each call in a REAL database as a chosen role, for the tests that must see row security.

WHY IT EXISTS
    Every other double in this directory answers from Python, so row security, grants and the privileged-versus-signed-in split
    are invisible to it. The API runs under the caller's own sign-in (USE_USER_JWT, the production default), which means a
    function that reads or writes a table with the wrong client fails in production and passes against a double. The year
    lock's defect was exactly that (POST-A-314): `set_client_lock` was called with the caller's client, the table's only
    policy refused every row, and no test could see it.

    This is the smallest thing that lets the production function run unchanged against a real database as `authenticated`
    (with a user's token claims) or as `service_role`: it executes SQL through `psql` the way the pg tests already do, so it
    needs no PostgREST. It speaks only the calls the year-end code makes (`select`, `insert`, `update`, `delete`, `eq`,
    `in_`, `limit`, `order`, `single`, `maybe_single`, `rpc`) and RAISES on anything else, so a change to the code under test
    that reaches for a call this does not model fails loudly instead of being answered wrongly. POST-A-345 added `neq`, `gt`, `gte`,
    `lt`, `lte`, `is_`, `like`, `ilike`, `range` and a plain `or_` (comma-separated `column.op.value` terms, no nesting), which the
    reclassification and the ledger-finding code read through.

WHAT IT DOES NOT MODEL
    PostgREST's own parsing, its row cap, embedded selects (and a filter on an embedded table), nested `or_`/`and_` groups and `not_`.
    A dict or a list
    is written as JSON text; a JSON column is read back as the JSON the database returns.
    Equality filters, and `in_` over a plain list of values (an empty list matches nothing, as PostgREST's does).
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Optional


class SignedInError(Exception):
    """What PostgREST would have answered as an APIError: the database's message, and its SQLSTATE when psql printed one."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code


class _Resp:
    def __init__(self, data):
        self.data = data


def _lit(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):                       # a json / jsonb value, as PostgREST sends one
        return "'" + json.dumps(value).replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _ident(name: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ValueError(f"not a plain identifier: {name!r}")
    return name


class SignedInDb:
    """`role='authenticated'` with a token whose `sub` is `auth_user_id`, or `role='service_role'` or `role='anon'` (no token)."""

    def __init__(self, dsn: str, *, role: str = "authenticated", auth_user_id: Optional[str] = None):
        self.dsn = dsn
        self.role = role
        self.auth_user_id = auth_user_id

    # ── the PostgREST surface ───────────────────────────────────────────────────
    def table(self, name: str) -> "_Query":
        return _Query(self, _ident(name))

    def rpc(self, fn: str, params: Optional[dict] = None) -> "_Rpc":
        return _Rpc(self, _ident(fn), params or {})

    # ── plumbing ────────────────────────────────────────────────────────────────
    def _prefix(self) -> str:
        if self.role == "service_role":
            return "SET ROLE service_role; "
        if self.role == "anon":
            return "SET ROLE anon; "
        claims = json.dumps({"sub": self.auth_user_id, "role": "authenticated"})
        return f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; "

    def _run(self, sql: str):
        done = subprocess.run(["psql", self.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", self._prefix() + sql],
                              capture_output=True, text=True)
        if done.returncode != 0:
            err = (done.stderr or "").strip()
            code = re.search(r"SQLSTATE[: ]+([0-9A-Z]{5})", err)
            raise SignedInError(err, code.group(1) if code else "")
        lines = [line for line in done.stdout.splitlines() if line.strip() and line.strip() != "SET"]
        return json.loads(lines[-1]) if lines else None


_COMPARE = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _condition(op: str, column: str, value: Any) -> str:
    """One PostgREST filter as a SQL condition. Raises on a shape this double does not model."""
    if op in _COMPARE:
        return f"{column} {_COMPARE[op]} {_lit(value)}"
    if op == "in":
        return f"{column} IN ({', '.join(_lit(x) for x in value)})" if value else "false"
    if op == "is":
        if value is None or str(value).lower() == "null":
            return f"{column} IS NULL"
        if str(value).lower() in ("true", "false"):
            return f"{column} IS {str(value).upper()}"
        raise ValueError(f"is_ takes null, true or false, not {value!r}")
    if op in ("like", "ilike"):
        return f"{column} {op.upper()} {_lit(value)}"
    if op == "or":
        terms = []
        for term in str(value).split(","):
            col, _, rest = term.strip().partition(".")
            inner_op, _, inner_value = rest.partition(".")
            terms.append(_condition(inner_op, _ident(col), inner_value))
        return "(" + " OR ".join(terms) + ")"
    raise ValueError(f"filter {op!r} is not modelled")


class _Query:
    def __init__(self, db: SignedInDb, table: str):
        self._db, self._table = db, table
        self._op = "select"
        self._cols = "*"
        self._rows: list[dict] = []
        self._values: dict = {}
        self._filters: list[tuple[str, str, Any]] = []
        self._limit: Optional[int] = None
        self._offset = 0
        self._order: list[str] = []
        self._one = False

    def select(self, cols: str = "*", **_ignored) -> "_Query":
        self._op, self._cols = "select", cols
        return self

    def insert(self, row) -> "_Query":
        self._op, self._rows = "insert", [row] if isinstance(row, dict) else list(row)
        return self

    def update(self, values: dict) -> "_Query":
        self._op, self._values = "update", dict(values)
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append(("eq", _ident(column), value))
        return self

    def in_(self, column: str, values) -> "_Query":
        self._filters.append(("in", _ident(column), list(values)))
        return self

    def neq(self, column: str, value: Any) -> "_Query":
        self._filters.append(("neq", _ident(column), value))
        return self

    def gt(self, column: str, value: Any) -> "_Query":
        self._filters.append(("gt", _ident(column), value))
        return self

    def gte(self, column: str, value: Any) -> "_Query":
        self._filters.append(("gte", _ident(column), value))
        return self

    def lt(self, column: str, value: Any) -> "_Query":
        self._filters.append(("lt", _ident(column), value))
        return self

    def lte(self, column: str, value: Any) -> "_Query":
        self._filters.append(("lte", _ident(column), value))
        return self

    def is_(self, column: str, value: Any) -> "_Query":
        self._filters.append(("is", _ident(column), value))
        return self

    def like(self, column: str, pattern: str) -> "_Query":
        self._filters.append(("like", _ident(column), pattern))
        return self

    def ilike(self, column: str, pattern: str) -> "_Query":
        self._filters.append(("ilike", _ident(column), pattern))
        return self

    def or_(self, expression: str) -> "_Query":
        self._filters.append(("or", "", expression))
        return self

    def range(self, start: int, end: int) -> "_Query":
        self._offset, self._limit = int(start), int(end) - int(start) + 1
        return self

    def limit(self, n: int) -> "_Query":
        self._limit = int(n)
        return self

    def order(self, column: str, desc: bool = False) -> "_Query":
        self._order.append(f"{_ident(column)} {'DESC' if desc else 'ASC'}")
        return self

    def single(self) -> "_Query":
        self._one = True
        return self

    def maybe_single(self) -> "_Query":
        self._one = "maybe"
        return self

    def _where(self) -> str:
        if not self._filters:
            return ""
        return " WHERE " + " AND ".join(_condition(op, c, v) for op, c, v in self._filters)

    def execute(self) -> _Resp:
        t = f"public.{self._table}"
        if self._op == "select":
            cols = self._cols if self._cols == "*" else ", ".join(_ident(c.strip()) for c in self._cols.split(","))
            inner = f"SELECT {cols} FROM {t}{self._where()}"
            if self._order:
                inner += " ORDER BY " + ", ".join(self._order)
            if self._limit is not None:
                inner += f" LIMIT {self._limit}"
            if self._offset:
                inner += f" OFFSET {self._offset}"
            rows = self._db._run(f"SELECT coalesce(json_agg(row_to_json(q)), '[]'::json) FROM ({inner}) q;")
        elif self._op == "insert":
            cols = list(self._rows[0])
            values = ", ".join("(" + ", ".join(_lit(r.get(c)) for c in cols) + ")" for r in self._rows)
            rows = self._db._run(f"WITH r AS (INSERT INTO {t} ({', '.join(_ident(c) for c in cols)}) VALUES {values} RETURNING *) "
                                 f"SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) FROM r;")
        elif self._op == "update":
            sets = ", ".join(f"{_ident(c)} = {_lit(v)}" for c, v in self._values.items())
            rows = self._db._run(f"WITH r AS (UPDATE {t} SET {sets}{self._where()} RETURNING *) "
                                 f"SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) FROM r;")
        elif self._op == "delete":
            rows = self._db._run(f"WITH r AS (DELETE FROM {t}{self._where()} RETURNING *) "
                                 f"SELECT coalesce(json_agg(row_to_json(r)), '[]'::json) FROM r;")
        else:                                                           # pragma: no cover - the verbs above are the whole surface
            raise AssertionError(self._op)
        if self._one:
            if len(rows) == 1:
                return _Resp(rows[0])
            if self._one == "maybe" and not rows:
                return _Resp(None)
            raise SignedInError(f"PGRST116: expected one row from {self._table}, got {len(rows)}", "PGRST116")
        return _Resp(rows)


class _Rpc:
    def __init__(self, db: SignedInDb, fn: str, params: dict):
        self._db, self._fn, self._params = db, fn, params

    def execute(self) -> _Resp:
        args = ", ".join(f"{_ident(k)} => {_lit(v)}" for k, v in self._params.items())
        return _Resp(self._db._run(f"SELECT to_json(public.{self._fn}({args}));"))
