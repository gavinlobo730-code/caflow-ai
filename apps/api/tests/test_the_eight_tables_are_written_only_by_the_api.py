"""Eight tables are written by the API's privileged client, firm by firm (POST-A-018, migration 513).

THE DEFECT
    `credit_note_allocations`, `invoice_sequences`, `scheduler_runs`, `task_dependencies`, `task_tags`, `task_templates`,
    `task_timeline_events` and `user_capacity` were granted write privileges to `authenticated` (migrations 095, 287) although
    no file in `apps/web` touches them, and three modules wrote them with the caller's own session (`request_db` is that session
    under `USE_USER_JWT`, the production default): the credit-note issue route (the application of a note to an invoice),
    `capacity_repository` and `task_extras_repository`. A firm-isolation row policy was the only control, so any signed-in
    member could set the firm's next invoice number, write or delete a credit-note application, edit workload capacity, relabel
    a task or forge an entry in a task's history, with no `rbac()` in the way.

WHAT IS HELD (migration 513 revokes the grants; its own test is the real-Postgres one)
    * (source, derived from the AST of the whole API, not a list of files) every write on one of the eight tables is made
      through a client that resolves to the privileged one: `db_provider.service_db`, `get_service_supabase`, or a module's own
      accessor that returns one of them. A write added anywhere, on a caller's session, fails here;
    * the browser touches none of the eight;
    * with a session that refuses every write beside a privileged client, each repository write reaches only the latter;
    * the privileged writes ask what the row policy used to: a dependency between tasks (the table has no firm of its own) is
      refused unless both tasks are the firm's and writes nothing; a tag is removed only for the firm it names; an event is
      never written for no firm; a capacity row is set only for a member of the firm; the credit-note application is written
      and deleted for the firm.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

import repositories.capacity_repository as capacity_mod
import repositories.task_extras_repository as extras_mod
import routers.workload as workload_router
from tests.e2e_harness import FakeDB, _Query

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]

EIGHT = ("credit_note_allocations", "invoice_sequences", "scheduler_runs", "task_dependencies", "task_tags",
         "task_templates", "task_timeline_events", "user_capacity")
WRITE_VERBS = {"insert", "update", "delete", "upsert"}
#: Calls that return the privileged client.
PRIVILEGED_CALLS = {"service_db", "get_service_supabase", "_service_client"}


# ── the scan ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _callee(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _privileged_names(tree: ast.Module) -> set[str]:
    """Names in this module that stand for the privileged client: aliases of an accessor (`_get_db = db_provider.service_db`)
    and functions that return one (`def _write_db(): return db_provider.service_db()`), followed to a fixed point so an accessor
    built on another is found."""
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                value = node.value
                target = _callee(value) if isinstance(value, (ast.Name, ast.Attribute)) else None
                if name not in names and target and (target in PRIVILEGED_CALLS or target in names):
                    names.add(name)
                    changed = True
            if isinstance(node, ast.FunctionDef) and node.name not in names:
                returns = [r.value for r in ast.walk(node) if isinstance(r, ast.Return) and r.value is not None]
                if returns and all(isinstance(r, ast.Call) and (_callee(r) in PRIVILEGED_CALLS or _callee(r) in names)
                                   for r in returns):
                    names.add(node.name)
                    changed = True
    return names


def _local_privileged(fn: ast.AST, privileged: set[str]) -> set[str]:
    """Variables assigned in this function from a privileged accessor: `svc = get_service_supabase()`."""
    out: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and (_callee(node.value) in PRIVILEGED_CALLS or _callee(node.value) in privileged)):
            out.add(node.targets[0].id)
    return out


def _writes_to_the_eight(source: str):
    """(function, line, table, verbs, privileged?) for every write on one of the eight tables in `source`."""
    tree = ast.parse(source)
    privileged = _privileged_names(tree)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        local = _local_privileged(fn, privileged)
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "table"
                    and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in EIGHT):
                continue
            verbs, up = [], node
            while True:
                parent = parents.get(up)
                if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call):
                    verbs.append(parent.attr)
                    up = parents[parent]
                else:
                    break
            written = [v for v in verbs if v in WRITE_VERBS]
            if not written:
                continue
            root = node.func.value
            while isinstance(root, (ast.Call, ast.Attribute)):
                root = root.func if isinstance(root, ast.Call) else root.value
            name = root.id if isinstance(root, ast.Name) else None
            ok = name is not None and (name in privileged or name in local or name in PRIVILEGED_CALLS)
            yield fn.name, node.lineno, node.args[0].value, written, ok


def _api_sources():
    for p in sorted(API_ROOT.rglob("*.py")):
        rel = p.relative_to(API_ROOT)
        if rel.parts[0] in {"tests", "scripts", "venv", ".venv", "migrations"}:
            continue
        yield p, p.read_text(encoding="utf-8")


def test_every_write_on_the_eight_tables_is_made_with_the_privileged_client():
    found, wrong = [], []
    for path, text in _api_sources():
        if not any(t in text for t in EIGHT):
            continue
        for fn, line, table, verbs, ok in _writes_to_the_eight(text):
            found.append((str(path.relative_to(API_ROOT)), fn, table))
            if not ok:
                wrong.append((str(path.relative_to(API_ROOT)), fn, line, table, verbs))
    assert wrong == [], f"writes made on a caller's session: {wrong}"
    # The rule must not be vacuous: the 13 writes known on 18-10-2026 across the 8 tables and 8 modules.
    assert len(found) >= 13, f"the scan found {len(found)} writes: the collector is broken: {found}"
    assert {t for _p, _f, t in found} >= {"credit_note_allocations", "invoice_sequences", "scheduler_runs",
                                           "task_dependencies", "task_tags", "task_templates",
                                           "task_timeline_events", "user_capacity"}


def test_negative_control_the_scan_catches_a_write_on_the_callers_session():
    bad = ("from core import db_provider\n_get_db = db_provider.request_db\n"
           "def f():\n    _get_db().table('task_tags').insert({}).execute()\n")
    assert [ok for *_x, ok in _writes_to_the_eight(bad)] == [False]
    good = ("from core import db_provider\n_get_db = db_provider.service_db\n"
            "def f():\n    _get_db().table('task_tags').insert({}).execute()\n")
    assert [ok for *_x, ok in _writes_to_the_eight(good)] == [True]
    local = "def f():\n    svc = get_service_supabase()\n    svc.table('invoice_sequences').upsert({}).execute()\n"
    assert [ok for *_x, ok in _writes_to_the_eight(local)] == [True]
    session = "def f():\n    db = get_supabase()\n    db.table('credit_note_allocations').delete().execute()\n"
    assert [ok for *_x, ok in _writes_to_the_eight(session)] == [False]
    accessor = ("from core import db_provider\n"
                "def _write_db():\n    return db_provider.service_db()\n"
                "def f():\n    _write_db().table('user_capacity').upsert({}).execute()\n")
    assert [ok for *_x, ok in _writes_to_the_eight(accessor)] == [True]


def test_the_browser_touches_none_of_the_eight_tables():
    import re
    pattern = re.compile(r"""\.from\(\s*['"](%s)['"]""" % "|".join(EIGHT))
    hits = []
    for p in (REPO_ROOT / "apps" / "web").rglob("*"):
        if p.suffix in {".ts", ".tsx"} and "node_modules" not in p.parts and ".next" not in p.parts:
            if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p.relative_to(REPO_ROOT)))
    assert hits == [], hits


def test_the_credit_note_application_is_written_and_deleted_for_the_firm():
    tree = ast.parse((API_ROOT / "routers" / "credit_notes.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "issue_credit_note")
    chains = [ast.unparse(n) for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"
              and "credit_note_allocations" in ast.unparse(n)]
    assert len(chains) == 2, chains
    assert all(c.startswith("_write_db()") for c in chains), chains
    delete = next(c for c in chains if ".delete()" in c)
    assert ".eq('firm_id', firm_id)" in delete, delete


# ── behaviour ────────────────────────────────────────────────────────────────────────────────────────────────────────
class _NoWriteQuery(_Query):
    def insert(self, *_a, **_k):
        raise AssertionError("a write reached the caller's own session")

    update = delete = upsert = insert


class _SessionDB(FakeDB):
    """The caller's own session: it can read what the other holds and refuses every write."""
    def __init__(self, backing: FakeDB):
        super().__init__()
        self._tables = backing._tables

    def table(self, name):
        return _NoWriteQuery(self, name)


@pytest.fixture()
def extras(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(extras_mod, "_write_db", lambda: db)
    monkeypatch.setattr(extras_mod, "_get_db", lambda: _SessionDB(db))
    db.seed("tasks", {"id": "T-F1-A", "firm_id": "F1"})
    db.seed("tasks", {"id": "T-F1-B", "firm_id": "F1"})
    db.seed("tasks", {"id": "T-F2", "firm_id": "F2"})
    return db


def test_a_dependency_between_own_tasks_is_written_with_the_privileged_client(extras):
    dep = extras_mod.task_extras_repo.add_dependency("T-F1-A", "T-F1-B", firm_id="F1")
    assert dep["task_id"] == "T-F1-A" and len(extras.rows("task_dependencies")) == 1


@pytest.mark.parametrize("task,depends_on", [("T-F1-A", "T-F2"), ("T-F2", "T-F1-A")])
def test_a_dependency_naming_another_firms_task_is_refused_and_writes_nothing(extras, task, depends_on):
    with pytest.raises(ValueError):
        extras_mod.task_extras_repo.add_dependency(task, depends_on, firm_id="F1")
    assert extras.rows("task_dependencies") == []


def test_a_dependency_is_removed_only_when_its_task_is_the_firms(extras):
    row = extras.seed("task_dependencies", {"id": "D1", "task_id": "T-F2", "depends_on_task_id": "T-F1-A"})
    with pytest.raises(ValueError):
        extras_mod.task_extras_repo.remove_dependency("T-F2", row["id"], firm_id="F1")
    assert len(extras.rows("task_dependencies")) == 1
    own = extras.seed("task_dependencies", {"id": "D2", "task_id": "T-F1-A", "depends_on_task_id": "T-F1-B"})
    assert extras_mod.task_extras_repo.remove_dependency("T-F1-A", own["id"], firm_id="F1") is True
    assert [r["id"] for r in extras.rows("task_dependencies")] == ["D1"]


def test_a_tag_is_removed_only_for_the_firm_it_names(extras):
    extras.seed("task_tags", {"id": "G1", "firm_id": "F2", "task_id": "T-F2", "tag": "urgent"})
    assert extras_mod.task_extras_repo.remove_tag("T-F2", "urgent", firm_id="F1") is False
    assert len(extras.rows("task_tags")) == 1
    assert extras_mod.task_extras_repo.remove_tag("T-F2", "urgent", firm_id="F2") is True


def test_the_firm_of_a_tag_removal_is_required():
    with pytest.raises(TypeError):
        extras_mod.task_extras_repo.remove_tag("T", "urgent")                                   # type: ignore[call-arg]
    with pytest.raises(TypeError):
        extras_mod.task_extras_repo.add_dependency("A", "B")                                    # type: ignore[call-arg]
    with pytest.raises(TypeError):
        extras_mod.task_extras_repo.remove_dependency("A", "D")                                 # type: ignore[call-arg]


def test_tags_and_events_are_written_with_the_privileged_client(extras):
    extras_mod.task_extras_repo.add_tag("F1", "T-F1-A", "Urgent ")
    extras_mod.task_extras_repo.log_event("T-F1-A", "tag_added", firm_id="F1", actor_id="u1")
    assert [r["tag"] for r in extras.rows("task_tags")] == ["urgent"]
    assert [r["firm_id"] for r in extras.rows("task_timeline_events")] == ["F1"]


def test_an_event_is_never_written_for_no_firm(extras):
    with pytest.raises(ValueError):
        extras_mod.task_extras_repo.log_event("T-F1-A", "tag_added", firm_id=None)
    assert extras.rows("task_timeline_events") == []


# ── capacity ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def capacity(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(capacity_mod, "_USE_MOCK", False)
    monkeypatch.setattr(capacity_mod, "_write_db", lambda: db)
    monkeypatch.setattr(capacity_mod, "_get_db", lambda: _SessionDB(db))
    db.seed("users", {"id": "U1", "firm_id": "F1"})
    db.seed("users", {"id": "U2", "firm_id": "F2"})
    return db


def test_a_members_capacity_is_set_with_the_privileged_client(capacity):
    out = capacity_mod.capacity_repo.upsert("F1", "U1", {"weekly_capacity_hours": 30, "max_concurrent_tasks": 9})
    assert out["firm_id"] == "F1" and out["user_id"] == "U1"
    assert len(capacity.rows("user_capacity")) == 1


@pytest.mark.parametrize("user_id", ["U2", "nobody"])
def test_capacity_for_someone_who_is_not_a_member_of_the_firm_is_refused(capacity, user_id):
    with pytest.raises(ValueError):
        capacity_mod.capacity_repo.upsert("F1", user_id, {})
    assert capacity.rows("user_capacity") == []


def test_the_route_answers_a_stranger_with_the_same_not_found_as_a_missing_person(capacity):
    body = workload_router.CapacityUpdate(user_id="U2", weekly_capacity_hours=30, max_concurrent_tasks=9)
    caller = {"firm_id": "F1", "id": "U1", "role": "Partner"}
    with pytest.raises(HTTPException) as ei:
        workload_router.set_capacity(body, caller)
    assert ei.value.status_code == 404 and ei.value.detail == "User not found"
