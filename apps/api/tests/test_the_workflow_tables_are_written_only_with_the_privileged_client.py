"""POST-A-248: the workflow tables are written with the privileged client, and a write that names a template or a run by its
id alone checks first that it is the firm's.

THE DEFECT
    `authenticated` held INSERT, UPDATE, DELETE and TRUNCATE on all eleven `workflow_*` tables and the repository took
    `db_provider.request_db`, which under `USE_USER_JWT` (the production default) is the CALLER'S session. So any signed-in
    member of a firm could edit a template, change a run, mark an approval decided or forge a failure row straight over
    PostgREST. Migration 509 takes the grants off, which means the repository's writes can no longer be the caller's: they
    go through `_write_db()` (the privileged client), and row security is no longer the second lock.

WHAT MAKES THAT SAFE (and is held here)
    * every INSERT, UPDATE and DELETE in the repository is made through `_write_db`, derived from the source, so a write
      added next month on the old handle fails the guard;
    * no other module writes a workflow table;
    * `workflow_steps` and `workflow_action_logs` carry no `firm_id`, so for them the parent row IS the firm check: a write
      that names a template or a run by its id asks that it is the firm's, and a write that names no firm is refused;
    * `update_schedule_run` named no firm at all; it does now;
    * the engine and the scheduler pass the firm they hold.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from repositories import workflow_repository as wr
from repositories.workflow_repository import WorkflowOwnershipError
from tests.e2e_harness import FakeDB

API = Path(__file__).resolve().parents[1]
REPO_FILE = API / "repositories" / "workflow_repository.py"
FIRM_A, FIRM_B = "firm-a", "firm-b"
WRITES = ("insert", "update", "delete", "upsert")


# ── the source ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _chain_root(node: ast.AST):
    while isinstance(node, (ast.Call, ast.Attribute)):
        node = node.func.value if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _write_chains(tree: ast.AST):
    """(method name, write verb, line, handle it is rooted at) for each database write in the module; a chain not rooted at a
    handle bound to `_get_db()` or `_write_db()` (the in-memory dict `.update`) is not one."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        bound = {}
        for n in ast.walk(fn):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                    and n.value.func.id in ("_get_db", "_write_db")):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        bound[t.id] = n.value.func.id
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WRITES:
                root = _chain_root(n.func.value)
                if root in bound:
                    out.append((fn.name, n.func.attr, n.lineno, bound[root]))
    return out


def test_every_database_write_in_the_workflow_repository_goes_through_the_privileged_client():
    chains = _write_chains(ast.parse(REPO_FILE.read_text(encoding="utf-8")))
    assert len(chains) >= 20, f"the scan found {len(chains)} writes; it has stopped reading the repository"
    wrong = [c for c in chains if c[3] != "_write_db"]
    assert not wrong, f"these writes use the caller's session: {wrong}"


def test_the_scan_sees_a_write_on_the_old_handle(tmp_path):
    """Negative control: the same function applied to the pre-change shape reports it."""
    tree = ast.parse("def f():\n    db = _get_db()\n    db.table('workflow_templates').insert({}).execute()\n")
    assert _write_chains(tree) == [("f", "insert", 3, "_get_db")]


def test_no_other_module_writes_a_workflow_table():
    offenders = []
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/")) or path == REPO_FILE or "venv" in rel:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WRITES:
                c = n.func.value
                while isinstance(c, (ast.Call, ast.Attribute)):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "table"
                            and c.args and isinstance(c.args[0], ast.Constant)
                            and str(c.args[0].value).startswith("workflow")):
                        offenders.append(f"{rel}:{n.lineno}")
                    if isinstance(c, ast.Call):
                        if not isinstance(c.func, ast.Attribute):
                            break
                        c = c.func.value
                    else:
                        c = c.value
    assert not offenders, f"a module other than the repository writes a workflow table: {offenders}"


def test_the_engine_and_the_scheduler_pass_the_firm_they_hold():
    engine = ast.parse((API / "domain" / "workflow_engine_v2.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(engine) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("log_action", "update_action_log")]
    assert len(calls) >= 5
    missing = [n.lineno for n in calls if "firm_id" not in {k.arg for k in n.keywords}]
    assert not missing, f"the engine writes a run's log without naming the firm at lines {missing}"
    update_logs = [n for n in calls if n.func.attr == "update_action_log"]
    assert all("instance_id" in {k.arg for k in n.keywords} for n in update_logs)

    sched = ast.parse((API / "jobs" / "scheduler.py").read_text(encoding="utf-8"))
    runs = [n for n in ast.walk(sched) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "update_schedule_run"]
    assert len(runs) == 2 and all("firm_id" in {k.arg for k in n.keywords} for n in runs)


# ── the behaviour, against the repository's database branch ───────────────────────────────────────────────────────────

class _Watched(FakeDB):
    """A FakeDB that remembers which verbs ran through it, so a test can tell the privileged handle from the caller's."""

    def __init__(self, label):
        super().__init__()
        self.label, self.writes = label, []

    def table(self, name):
        q = super().table(name)
        for verb in WRITES:
            original = getattr(q, verb)

            def watched(*a, _verb=verb, _orig=original, **k):
                self.writes.append((_verb, name))
                return _orig(*a, **k)
            setattr(q, verb, watched)
        return q


@pytest.fixture
def world(monkeypatch):
    privileged, callers = _Watched("privileged"), _Watched("caller")
    monkeypatch.setattr(wr, "_USE_MOCK", False)
    monkeypatch.setattr(wr, "_write_db", lambda: privileged)
    monkeypatch.setattr(wr, "_get_db", lambda: callers)
    # reads see the same rows the privileged handle holds, as they would in one database
    callers._tables = privileged._tables
    privileged.seed("workflow_templates", {"id": "T-A", "firm_id": FIRM_A, "name": "A's", "is_active": True, "version": 1})
    privileged.seed("workflow_instances", {"id": "I-A", "firm_id": FIRM_A, "template_id": "T-A", "status": "running"})
    privileged.seed("workflow_steps", {"id": "S-A", "template_id": "T-A", "step_order": 0})
    privileged.seed("workflow_schedules", {"id": "SC-A", "firm_id": FIRM_A, "template_id": "T-A", "run_count": 0})
    return privileged, callers


def _repo():
    return wr.WorkflowRepository()


def test_a_write_goes_through_the_privileged_handle_and_never_the_callers(world):
    privileged, callers = world
    _repo().create_instance(FIRM_A, "T-A", "client_created", {}, None, "k1")
    _repo().log_action("I-A", "S-A", "step", "task", {}, "running", firm_id=FIRM_A)
    _repo().log_execution("I-A", FIRM_A, "step_completed", {})
    assert {w for w in privileged.writes} >= {("insert", "workflow_instances"), ("insert", "workflow_action_logs"),
                                              ("insert", "workflow_executions")}
    assert callers.writes == [], "a workflow write used the caller's own session"


# every write that names a template or a run by its id, with the firm that does NOT own it
FOREIGN = [
    ("insert steps", lambda r: r._insert_steps("T-A", [{"id": "n", "step_order": 0, "step_type": "task", "name": "n",
                                                       "description": "", "config": {}, "next_step_id": None,
                                                       "true_branch_step_id": None, "false_branch_step_id": None}],
                                               firm_id=FIRM_B)),
    ("create step", lambda r: r._create_step("T-A", {"step_order": 1}, firm_id=FIRM_B)),
    ("replace steps", lambda r: r._replace_steps("T-A", [], replacing=[], firm_id=FIRM_B)),
    ("update step", lambda r: r._update_step("S-A", {"name": "x"}, firm_id=FIRM_B)),
    ("create instance", lambda r: r.create_instance(FIRM_B, "T-A", "e", {}, None, "k")),
    ("log action", lambda r: r.log_action("I-A", "S-A", "n", "task", {}, "running", firm_id=FIRM_B)),
    ("update action log", lambda r: r.update_action_log("L1", "success", firm_id=FIRM_B, instance_id="I-A")),
    ("log execution", lambda r: r.log_execution("I-A", FIRM_B, "e", {})),
    ("log failure", lambda r: r.log_failure(FIRM_B, "I-A", "S-A", "t", "m")),
    ("create approval", lambda r: r.create_approval(FIRM_B, "I-A", "S-A", "n", "Partner", "t", "d", {})),
    ("create schedule", lambda r: r.create_schedule(FIRM_B, "T-A", "n", "0 9 * * *")),
]


@pytest.mark.parametrize("name,call", FOREIGN, ids=[f[0] for f in FOREIGN])
def test_a_write_naming_another_firms_template_or_run_is_refused_and_writes_nothing(world, name, call):
    privileged, _ = world
    before = len(privileged.writes)
    with pytest.raises(WorkflowOwnershipError):
        call(_repo())
    assert len(privileged.writes) == before, f"{name}: something was written before the refusal"


UNNAMED = [
    ("insert steps", lambda r: r._insert_steps("T-A", [{"id": "n"}])),
    ("create step", lambda r: r._create_step("T-A", {"step_order": 1})),
    ("update step", lambda r: r._update_step("S-A", {"name": "x"})),
    ("log action", lambda r: r.log_action("I-A", "S-A", "n", "task", {}, "running")),
    ("update action log", lambda r: r.update_action_log("L1", "success", instance_id="I-A")),
    ("update schedule run", lambda r: r.update_schedule_run("SC-A", "success")),
]


@pytest.mark.parametrize("name,call", UNNAMED, ids=[u[0] for u in UNNAMED])
def test_a_write_that_names_no_firm_is_refused_not_let_through(world, name, call):
    with pytest.raises(WorkflowOwnershipError):
        call(_repo())


def test_the_owning_firm_still_writes_each_of_them(world):
    privileged, _ = world
    r = _repo()
    r.create_instance(FIRM_A, "T-A", "e", {}, None, "k")
    log = r.log_action("I-A", "S-A", "n", "task", {}, "running", firm_id=FIRM_A)
    assert r.update_action_log(log["id"], "success", firm_id=FIRM_A, instance_id="I-A")["status"] == "success"
    r.log_execution("I-A", FIRM_A, "e", {})
    r.log_failure(FIRM_A, "I-A", "S-A", "t", "m")
    r.create_approval(FIRM_A, "I-A", "S-A", "n", "Partner", "t", "d", {})
    r._create_step("T-A", {"step_order": 1}, firm_id=FIRM_A)
    assert r._update_step("S-A", {"name": "renamed"}, firm_id=FIRM_A)["name"] == "renamed"


def test_an_action_log_is_updated_only_through_its_own_run(world):
    """A log id belonging to another run is not touched, even by the firm that owns both: the update names the run."""
    privileged, _ = world
    privileged.seed("workflow_instances", {"id": "I-A2", "firm_id": FIRM_A, "template_id": "T-A", "status": "running"})
    log = _repo().log_action("I-A", "S-A", "n", "task", {}, "running", firm_id=FIRM_A)
    assert _repo().update_action_log(log["id"], "success", firm_id=FIRM_A, instance_id="I-A2") is None
    assert next(r for r in privileged.rows("workflow_action_logs") if r["id"] == log["id"])["status"] == "running"


def test_a_schedule_run_is_recorded_only_against_the_firms_own_schedule(world):
    privileged, _ = world
    assert _repo().update_schedule_run("SC-A", "success", None, firm_id=FIRM_B) is None
    assert next(r for r in privileged.rows("workflow_schedules") if r["id"] == "SC-A")["run_count"] == 0
    assert _repo().update_schedule_run("SC-A", "success", None, firm_id=FIRM_A)["run_count"] == 1
