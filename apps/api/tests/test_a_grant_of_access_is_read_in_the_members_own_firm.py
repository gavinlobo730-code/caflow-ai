"""The API reads a member's grants of access in the member's own firm only (migration 530's other half).

WHAT WAS WRONG
    `user_client_assignments` and `user_permissions` are keyed by a member (`users.id`, a global key) and carry a `firm_id`.
    The API reads them with the privileged client, which bypasses row security, and four of its readers looked a row up by the
    member alone: `core.authz.assigned_client_ids`, `core.authz.is_client_assigned`, `core.auth._permission_overrides` and the
    "already linked" probe of `assignment_repository.create`. Migration 530 closes the database's doors (a Partner of one firm
    can no longer write a grant that names a member of another, and the three SQL functions ignore such a row), but a row that
    is already in either table would have kept granting through every route, because these readers do not go through those
    functions. A Partner of firm G could have planted (G, a member of firm F, a client of F), and F's member would have passed
    `can_access_client` for that client on every endpoint.

WHAT THIS HOLDS
    * each of the four readers filters on the member's firm (a recording double shows the `.eq("firm_id", ...)` that reaches
      the query), and the knowledge base's assignment probe hands it the firm; a reader that cannot name the firm runs no query
      and answers none, and the firm has no default in the two functions that take it;
    * the RULE, over the source: every read of either table in `apps/api` (outside the tests) sits in a function that names a
      `firm_id`, so the next reader added without a firm fails here, and the check is shown to fail on a snippet that has none.

Runs in the mock-mode job: no database is needed.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


API_ROOT = Path(__file__).resolve().parents[1]
FIRM = "f-1"
OTHER = "f-2"


class _Recorder:
    """Records the filters of a query chain and answers with the rows it was given."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.eqs: list[tuple[str, str]] = []
        self.tables: list[str] = []
        self.inserted: list[dict] = []

    def table(self, name):
        self.tables.append(name)
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self.eqs.append((column, value))
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, row):
        self.inserted.append(row)
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


def test_the_assigned_clients_of_a_member_are_read_in_their_firm(monkeypatch):
    import core.authz as authz
    rec = _Recorder([{"client_id": "c-1"}])
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_db", lambda: rec)
    assert authz.assigned_client_ids({"id": "u-1", "firm_id": FIRM}) == {"c-1"}
    assert ("user_id", "u-1") in rec.eqs and ("firm_id", FIRM) in rec.eqs, rec.eqs


def test_one_assignment_probe_is_read_in_the_members_firm(monkeypatch):
    import core.authz as authz
    rec = _Recorder([{"id": "a-1"}])
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_db", lambda: rec)
    assert authz.is_client_assigned("u-1", "c-1", FIRM) is True
    assert ("firm_id", FIRM) in rec.eqs and ("user_id", "u-1") in rec.eqs and ("client_id", "c-1") in rec.eqs, rec.eqs


def test_the_knowledge_base_probe_hands_the_assignment_check_the_firm(monkeypatch):
    import core.authz as authz
    import services.knowledge_service as ks
    seen: list[tuple] = []
    monkeypatch.setattr(authz, "is_client_assigned", lambda *a, **k: seen.append((a, k)) or True)
    assert ks.is_assigned(FIRM, "u-1", "c-1") is True
    assert seen and FIRM in (list(seen[0][0]) + list(seen[0][1].values())), seen


def test_the_permission_overrides_of_a_member_are_read_in_their_firm():
    from core.auth import _permission_overrides
    rec = _Recorder([{"resource": "assignment", "action": "write", "granted": True}])
    assert _permission_overrides(rec, "u-1", FIRM) == {"assignment:write": True}
    assert ("user_id", "u-1") in rec.eqs and ("firm_id", FIRM) in rec.eqs, rec.eqs


def test_the_sign_in_lookup_hands_the_override_read_the_members_own_firm(monkeypatch):
    """The call site, not only the reader: `_get_user_and_firm` is what every request goes through, and a call that dropped the
    firm would fail CLOSED (no overrides, so every per-person grant and block silently falls back to the role)."""
    import core.auth as auth
    seen: list[list[tuple[str, str]]] = []

    class _Query:
        def __init__(self, name):
            self.name, self.eqs = name, []

        def select(self, *_a, **_k):
            return self

        def eq(self, column, value):
            self.eqs.append((column, value))
            return self

        def maybe_single(self):
            return self

        def execute(self):
            if self.name == "users":
                data = {"id": "u-1", "firm_id": FIRM, "role": "Manager", "full_name": "M", "is_active": True,
                        "sessions_revoked_at": None}
            elif self.name == "firms":
                data = {"is_active": True, "deleted_at": None}
            elif self.name == "user_permissions":
                seen.append(self.eqs)
                data = [{"resource": "assignment", "action": "write", "granted": True}]
            else:
                raise AssertionError(f"the sign-in lookup queried {self.name!r}")
            return SimpleNamespace(data=data)

    class _Db:
        def table(self, name):
            return _Query(name)

    monkeypatch.setattr(auth, "_user_lookup_cache", {})
    user, _firm = auth._get_user_and_firm(_Db(), "auth-1")
    assert user["permission_overrides"] == {"assignment:write": True}, user
    assert seen == [[("user_id", "u-1"), ("firm_id", FIRM)]], seen


def test_creating_an_assignment_looks_for_the_pair_in_the_callers_firm_only(monkeypatch):
    import repositories.assignment_repository as repo
    rec = _Recorder([])
    monkeypatch.setattr(repo, "_USE_MOCK", False)
    monkeypatch.setattr(repo, "_db", lambda: rec)
    repo.assignment_repo.create(FIRM, "u-1", "c-1")
    assert ("firm_id", FIRM) in rec.eqs and ("user_id", "u-1") in rec.eqs and ("client_id", "c-1") in rec.eqs, rec.eqs
    assert rec.inserted == [{"firm_id": FIRM, "user_id": "u-1", "client_id": "c-1"}], rec.inserted


# ── a reader that cannot name the firm answers "none" and never "from every firm" ───────────────────────────────────

def test_a_member_with_no_firm_has_no_assigned_clients_and_no_query_is_run(monkeypatch):
    import core.authz as authz
    rec = _Recorder([{"client_id": "c-1"}])
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_db", lambda: rec)
    assert authz.assigned_client_ids({"id": "u-1"}) == set()
    assert authz.assigned_client_ids({"id": "u-1", "firm_id": ""}) == set()
    assert rec.tables == [], "a read ran without a firm"


def test_the_assignment_probe_has_no_default_firm_and_says_no_without_one(monkeypatch):
    import inspect

    import core.authz as authz
    assert inspect.signature(authz.is_client_assigned).parameters["firm_id"].default is inspect.Parameter.empty
    rec = _Recorder([{"id": "a-1"}])
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_db", lambda: rec)
    assert authz.is_client_assigned("u-1", "c-1", None) is False
    assert authz.is_client_assigned("u-1", "c-1", "") is False
    assert rec.tables == []


def test_the_permission_overrides_have_no_default_firm_and_are_none_without_one():
    import inspect

    from core.auth import _permission_overrides
    assert inspect.signature(_permission_overrides).parameters["firm_id"].default is inspect.Parameter.empty
    rec = _Recorder([{"resource": "assignment", "action": "write", "granted": True}])
    assert _permission_overrides(rec, "u-1", None) == {}
    assert _permission_overrides(rec, "u-1", "") == {}
    assert rec.tables == []


# ── the rule, over the source ───────────────────────────────────────────────────

ACCESS_TABLES = ("user_client_assignments", "user_permissions")


def reads_without_a_firm(source: str) -> list[str]:
    """The functions of `source` that call `.table("<access table>")` and never name a `firm_id`."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    bad: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in ACCESS_TABLES):
            continue
        scope = node
        while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = parents[scope]
        segment = ast.get_source_segment(source, scope) or ""
        if "firm_id" not in segment:
            bad.append(getattr(scope, "name", "<module>"))
    return bad


def test_the_rule_fails_on_a_reader_that_names_no_firm():
    assert reads_without_a_firm('def f(db, u):\n    return db.table("user_client_assignments").select("*").eq("user_id", u).execute()\n') == ["f"]
    assert reads_without_a_firm('def f(db, u, firm_id):\n    return db.table("user_permissions").select("*").eq("firm_id", firm_id).execute()\n') == []
    assert reads_without_a_firm('def f(db):\n    return db.table("customers").select("*").execute()\n') == []


def test_every_reader_of_a_grant_of_access_in_the_api_names_a_firm():
    problems: list[str] = []
    scanned = 0
    for path in sorted(API_ROOT.rglob("*.py")):
        rel = path.relative_to(API_ROOT)
        if rel.parts[0] in {"tests", "scripts", "migrations", "venv", ".venv"} or "__pycache__" in rel.parts:
            continue
        text = path.read_text()
        if not any(t in text for t in ACCESS_TABLES):
            continue
        scanned += 1
        problems += [f"{rel}::{name}" for name in reads_without_a_firm(text)]
    assert scanned >= 5, f"only {scanned} modules mention the two tables: the scan reads nothing"
    assert not problems, (
        "these functions read user_client_assignments or user_permissions with the privileged client and name no firm_id: a "
        "row another firm's Partner wrote for the member would count (migration 530): " + ", ".join(problems))
