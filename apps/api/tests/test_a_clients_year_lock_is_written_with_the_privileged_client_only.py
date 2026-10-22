"""A client's year lock is read and written with the privileged client, and nothing else writes the table (migration 532,
POST-A-314).

THE DEFECT
    `year_lock_service.set_client_lock` read and wrote `client_year_locks` with whatever client its caller handed it, and both
    year-end routes hand it the request's own (`get_supabase()`, the caller's sign-in under USE_USER_JWT, the production
    default). The table's only policy asked a token claim nobody carries, so the INSERT was refused AFTER the engagement had
    been written as locked. Migration 532 makes the signed-in role's read scoped to the caller's clients and takes its writes
    away: the lock is a Partner's act that the routes check and the audit log records, and the database refuses a signed-in
    write.

WHAT THIS HOLDS (the real-Postgres proof is `test_a_year_end_is_finalised_and_reopened_under_a_request_sign_in_pg.py`)
    * (behaviour) `set_client_lock` reads and writes through the privileged client where there is one and touches the request's
      client not at all; where there is no other (mock mode, a double) the request's own is used, and `None` stays `None`;
    * (source, derived from the AST of the whole API, not from a list of files) the only module that writes `client_year_locks`
      is `services/year_lock_service.py`, and each write there follows `db = _lock_table_db(db)` in the same function, so a
      second writer, or the next edit that drops the reassignment, fails here;
    * the lock is idempotent on the privileged client too: a second lock writes nothing and an unlock of an open year writes
      nothing.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core import db_provider
from services import year_lock_service as yls

API_ROOT = Path(__file__).resolve().parents[1]
WRITE_VERBS = {"insert", "update", "delete", "upsert"}
TABLE = "client_year_locks"
FIRM, CLIENT, FY = "F1", "C1", "2025-26"


class _Resp:
    def __init__(self, data):
        self.data = data


class _Db:
    """A PostgREST-shaped double that records which table was read or written and applies equality filters, so the idempotence
    checks of the code under test see the rows it wrote."""

    def __init__(self, name: str):
        self.name = name
        self.rows: list[dict] = []
        self.calls: list[tuple[str, str]] = []

    def table(self, name: str):
        return _Query(self, name)


class _Query:
    def __init__(self, db: _Db, table: str):
        self._db, self._table = db, table
        self._op, self._filters, self._payload = "select", [], None

    def select(self, *_a, **_k):
        self._op = "select"
        self._db.calls.append((self._table, "select"))
        return self

    def insert(self, row):
        self._op, self._payload = "insert", row
        self._db.calls.append((self._table, "insert"))
        return self

    def delete(self):
        self._op = "delete"
        self._db.calls.append((self._table, "delete"))
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def limit(self, _n):
        return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self._filters)

    def execute(self):
        if self._op == "insert":
            self._db.rows.append(dict(self._payload))
            return _Resp([dict(self._payload)])
        if self._op == "delete":
            gone = [r for r in self._db.rows if self._match(r)]
            self._db.rows = [r for r in self._db.rows if not self._match(r)]
            return _Resp(gone)
        return _Resp([dict(r) for r in self._db.rows if self._match(r)])


@pytest.fixture()
def clients(monkeypatch):
    request, privileged = _Db("request"), _Db("privileged")
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: privileged)
    monkeypatch.setattr(yls, "log_event", lambda *a, **k: None)
    return request, privileged


def _lock(db, lock=True):
    return yls.set_client_lock(db, FIRM, CLIENT, FY, lock=lock, actor_id="u1", actor_auth_id="a1", reason="r")


def test_the_lock_is_read_and_written_with_the_privileged_client_and_the_requests_is_not_touched(clients):
    request, privileged = clients
    _lock(request)
    assert privileged.calls == [(TABLE, "select"), (TABLE, "insert")], privileged.calls
    assert request.calls == [], f"the request's own client was used: {request.calls}"
    assert privileged.rows == [{"firm_id": FIRM, "client_id": CLIENT, "financial_year": FY, "locked_by": "u1", "reason": "r"}]


def test_the_unlock_is_read_and_written_with_the_privileged_client_and_the_requests_is_not_touched(clients):
    request, privileged = clients
    _lock(request)
    privileged.calls.clear()
    _lock(request, lock=False)
    assert privileged.calls == [(TABLE, "select"), (TABLE, "delete")], privileged.calls
    assert request.calls == [] and privileged.rows == []


def test_a_second_lock_and_an_unlock_of_an_open_year_write_nothing(clients):
    request, privileged = clients
    _lock(request, lock=False)
    assert privileged.calls == [(TABLE, "select")]
    _lock(request)
    privileged.calls.clear()
    _lock(request)
    assert privileged.calls == [(TABLE, "select")] and len(privileged.rows) == 1


def test_where_there_is_no_privileged_client_the_callers_own_is_used(monkeypatch):
    """Mock mode and the in-memory doubles have no service client (`service_db_or_none` is None): the caller's own is all there
    is, and `None` stays `None` rather than becoming an attribute error somewhere else."""
    request = _Db("request")
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: None)
    monkeypatch.setattr(yls, "log_event", lambda *a, **k: None)
    _lock(request)
    assert request.calls == [(TABLE, "select"), (TABLE, "insert")] and len(request.rows) == 1
    assert yls._lock_table_db(None) is None


def test_the_privileged_client_wins_over_the_requests(monkeypatch):
    request, privileged = _Db("request"), _Db("privileged")
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: privileged)
    assert yls._lock_table_db(request) is privileged
    assert yls._lock_table_db(None) is None, "None stays None even where a privileged client exists"


# ── the filters are now the only isolation ───────────────────────────────────────────────────────────────────────────

def test_a_lock_and_an_unlock_touch_exactly_one_clients_one_year_of_one_firm(clients):
    """The privileged client bypasses row security, so the `.eq("firm_id")`, `.eq("client_id")` and `.eq("financial_year")` of
    the three statements are the only thing that keeps a finalise or a reopen to ONE client's ONE year. Every other row that
    differs from the target in exactly one of the three is present, so a statement that drops any filter acts on another row."""
    request, privileged = clients
    others = [
        {"firm_id": FIRM, "client_id": CLIENT, "financial_year": "2024-25", "locked_by": "u9", "reason": "o1"},    # another year
        {"firm_id": FIRM, "client_id": "C2", "financial_year": FY, "locked_by": "u9", "reason": "o2"},             # another client
        {"firm_id": "F2", "client_id": CLIENT, "financial_year": FY, "locked_by": "u9", "reason": "o3"},           # another firm
    ]
    privileged.rows.extend(dict(r) for r in others)

    # the existence read looks at the target row only: the three neighbours must not make the lock look already taken
    _lock(request)
    assert [r["reason"] for r in privileged.rows] == ["o1", "o2", "o3", "r"], privileged.rows
    assert yls.is_client_year_locked(privileged, FIRM, CLIENT, FY) is True
    assert yls.is_client_year_locked(privileged, FIRM, CLIENT, "2023-24") is False
    assert yls.is_client_year_locked(privileged, FIRM, "C3", FY) is False
    assert yls.is_client_year_locked(privileged, "F3", CLIENT, FY) is False

    # the unlock removes the target and nothing else
    _lock(request, lock=False)
    assert [r["reason"] for r in privileged.rows] == ["o1", "o2", "o3"], privileged.rows

    # and an unlock of a year that is not locked leaves all three where they are
    _lock(request, lock=False)
    assert [r["reason"] for r in privileged.rows] == ["o1", "o2", "o3"], privileged.rows


# ── the source ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _doc_nodes(tree: ast.AST) -> set[int]:
    """The ids of the string constants that are docstrings (they may name the table; code may not use the name elsewhere)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def _uses_of_the_table_name(source: str):
    """(line, enclosing function or None, kind) for every use of the table's NAME in code: a string constant (not a docstring)
    that equals or contains it, in any spelling that reaches a database call: `.table("client_year_locks")`, `.from_(...)`, a
    variable, an f-string, raw SQL. Comments and docstrings are not code."""
    tree = ast.parse(source)
    docs = _doc_nodes(tree)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and TABLE in node.value and id(node) not in docs:
            parent = parents.get(node)
            direct = (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and parent.func.attr == "table"
                      and parent.args and parent.args[0] is node)
            yield node.lineno, enclosing(node), ("table-call" if direct else "other")


def _api_sources():
    for p in sorted(API_ROOT.rglob("*.py")):
        rel = p.relative_to(API_ROOT)
        if rel.parts[0] in {"tests", "scripts", "venv", ".venv", "migrations"}:
            continue
        yield rel, p.read_text(encoding="utf-8")


def _chain_verbs(call: ast.Call, parents: dict) -> list[str]:
    verbs, up = [], call
    while True:
        parent = parents.get(up)
        if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call):
            verbs.append(parent.attr)
            up = parents[parent]
        else:
            return verbs


def test_the_table_name_is_used_in_code_by_two_modules_and_only_the_year_lock_service_writes_it():
    """THE RULE, NOT A SPELLING OF IT: the name of the table is a string in code in exactly two modules, the year lock service
    (reads and writes) and the period lock service (the Python twin of the SQL functions, which only reads and is handed a
    client by its caller); every use in either is a literal `.table("client_year_locks")` call, so no alias, `from_`, variable,
    f-string or raw SQL can carry a write past this test; and every write is in `set_client_lock`, after
    `db = _lock_table_db(db)`."""
    uses, bad = [], []
    for rel, text in _api_sources():
        if TABLE not in text:
            continue
        for line, fn, kind in _uses_of_the_table_name(text):
            uses.append((str(rel), fn.name if fn else None, kind))
            if str(rel) not in ("services/year_lock_service.py", "services/period_lock_service.py"):
                bad.append((str(rel), line, "the table is named in code by a module that is neither the year lock service nor its twin"))
            elif kind != "table-call":
                bad.append((str(rel), line, "the table name is used in a spelling other than a literal `.table(...)` call"))
    assert bad == [], bad
    assert sorted({(r, f) for r, f, _k in uses}) == [
        ("services/period_lock_service.py", "_closure_from_tables"),
        ("services/year_lock_service.py", "is_client_year_locked"),
        ("services/year_lock_service.py", "set_client_lock"),
    ], uses


def test_every_write_is_in_set_client_lock_after_the_privileged_swap_and_the_twin_never_writes():
    for rel in ("services/year_lock_service.py", "services/period_lock_service.py"):
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        writes = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                    and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == TABLE):
                verbs = _chain_verbs(node, parents)
                if any(v in WRITE_VERBS for v in verbs):
                    fn = node
                    while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn = parents[fn]
                    writes.append((fn.name, node.lineno, fn))
        if rel.endswith("period_lock_service.py"):
            assert writes == [], f"the twin writes the table: {[(n, l) for n, l, _f in writes]}"
            continue
        assert sorted(n for n, _l, _f in writes) == ["set_client_lock", "set_client_lock"], [(n, l) for n, l, _f in writes]
        for name, line, fn in writes:
            assert _reassigns_the_lock_db_before(fn, line), f"{name}:{line} writes without `db = _lock_table_db(db)` above it"


def _reassigns_the_lock_db_before(fn: ast.AST, line: int) -> bool:
    """`db = _lock_table_db(db)` appears in `fn` above `line`."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and node.lineno < line and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "db"
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_lock_table_db"):
            return True
    return False
