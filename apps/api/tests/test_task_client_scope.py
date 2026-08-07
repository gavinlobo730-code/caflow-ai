"""
Client-assignment scope on the task routers.

`/api/tasks` is served by TWO routers. `tasks.py` had a guard on the list and on
create; `task_extras.py` imported no authz at all, so tags, dependencies and the
timeline of ANY client's task were readable and writable by anyone in the firm.
Guarding the tags on a task while leaving `PATCH` on the same task open would be
absurd, so both are covered here.

THREE THINGS THAT NEEDED A DIFFERENT ANSWER

  1. `POST /{task_id}/dependencies` names a SECOND task in the body. The
     response and the timeline event both echo that task's title, so checking
     only the task in the path leaks the other client's task by name.

  2. `GET /tags/all` is autocomplete, not a record — but a tag is free text
     somebody typed on a client's task. "acme-gst-migration" names a client as
     surely as a client_id does.

  3. The three `trigger-*` endpoints are firm-WIDE jobs, not rows. They get a
     403 rather than the 404 used everywhere else in this sweep: no id is
     involved and nothing is being hidden, so a "not found" would be a lie.
"""
import pytest
from fastapi import HTTPException

import routers.task_extras as te
import routers.tasks as tr
from core.authz import firmwide_roles_label
from repositories.task_extras_repository import TaskExtrasRepository

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "Executive"}
PARTNER = {"id": "p1", "firm_id": FIRM, "role": "Partner"}

TASKS = {
    "T-MINE": {"id": "T-MINE", "firm_id": FIRM, "client_id": MINE,
               "title": "File GSTR-1", "status": "todo"},
    "T-MINE-2": {"id": "T-MINE-2", "firm_id": FIRM, "client_id": MINE,
                 "title": "Reconcile bank", "status": "todo"},
    "T-THEIRS": {"id": "T-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                 "title": "Acme merger due diligence", "status": "todo"},
}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong task's client."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(te, "assert_client_access", _check)
    monkeypatch.setattr(tr, "assert_client_access", _check)
    return seen


@pytest.fixture(autouse=True)
def tasks(monkeypatch):
    monkeypatch.setattr(te.task_repo, "find_by_id",
                        lambda tid, firm_id=None, **_k: TASKS.get(tid))
    monkeypatch.setattr(tr.task_repo, "find_by_id",
                        lambda tid, firm_id=None, **_k: TASKS.get(tid))


@pytest.fixture
def reached(monkeypatch):
    """Every repository call the task-extras handlers can make, spied. A guard
    that refuses AFTER the write has happened is not a guard."""
    hit = []
    for name in ("get_tags", "add_tag", "remove_tag", "get_dependencies",
                 "add_dependency", "remove_dependency", "get_timeline",
                 "log_event", "get_firm_tags"):
        monkeypatch.setattr(te.task_extras_repo, name,
                            (lambda n: lambda *a, **k: hit.append(n) or {})(name))
    return hit


# ══════════════════════════════════════════════════════════════════════════════
# task_extras — everything hangs off a task, so everything checks the task
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_task_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        te._assert_task_scope(USER, TASKS["T-THEIRS"])
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_the_guard_reads_the_client_off_the_row_it_was_given(deny):
    """Not the id, the row — every caller has already loaded it, and a second
    fetch would be a second query for an answer that is on the desk."""
    te._assert_task_scope(USER, TASKS["T-MINE"])
    assert deny == [MINE]


@pytest.mark.parametrize("fn,args", [
    ("get_tags", ()),
    ("add_tag", (te.AddTagBody(tag="urgent"),)),
    ("remove_tag", ("urgent",)),
    ("get_dependencies", ()),
    ("add_dependency", (te.AddDependencyBody(depends_on_task_id="T-MINE"),)),
    ("remove_dependency", ("dep-1",)),
    ("get_timeline", ()),
])
def test_every_task_endpoint_refuses_before_it_acts(fn, args, deny, reached):
    with pytest.raises(HTTPException) as e:
        getattr(te, fn)("T-THEIRS", *args, current_user=USER)
    assert e.value.status_code == 404
    assert reached == [], f"{fn} reached the repository despite the refusal"


@pytest.mark.parametrize("fn,args", [
    ("get_tags", ()),
    ("get_dependencies", ()),
    ("get_timeline", ()),
])
def test_your_own_task_still_works(fn, args, deny, reached):
    """Over-guarding is a real failure mode — the fix must not break the people
    the endpoint is for."""
    out = getattr(te, fn)("T-MINE", *args, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


def test_an_unknown_task_is_the_same_404_as_a_forbidden_one(deny):
    """The status code must not become an oracle for which task ids are real."""
    with pytest.raises(HTTPException) as missing:
        te.get_tags("no-such-task", current_user=USER)
    with pytest.raises(HTTPException) as hidden:
        te.get_tags("T-THEIRS", current_user=USER)
    assert missing.value.status_code == hidden.value.status_code == 404


# ── The dependency target is a second task, and it is echoed back ─────────────

def test_a_dependency_on_another_clients_task_is_refused(deny, reached):
    """The task in the PATH is mine; the one in the BODY is not. The response
    and the timeline event both carry dep_task["title"], so checking only the
    path would hand over another client's task by name."""
    with pytest.raises(HTTPException) as e:
        te.add_dependency("T-MINE",
                          te.AddDependencyBody(depends_on_task_id="T-THEIRS"),
                          current_user=USER)
    assert e.value.status_code == 404
    assert deny == [MINE, THEIRS], "the body's task was never checked"
    assert reached == [], "the dependency was written despite the refusal"


def test_a_dependency_between_two_of_your_own_tasks_is_allowed(deny, reached):
    out = te.add_dependency("T-MINE",
                            te.AddDependencyBody(depends_on_task_id="T-MINE-2"),
                            current_user=USER)
    assert out["success"] is True
    assert deny == [MINE, MINE]
    assert "add_dependency" in reached


# ── The firm's tag vocabulary ─────────────────────────────────────────────────

def test_the_tag_vocabulary_is_narrowed_to_your_clients(monkeypatch, reached):
    captured = {}
    monkeypatch.setattr(te.task_extras_repo, "get_firm_tags",
                        lambda firm_id, **kw: captured.update(kw) or [])
    monkeypatch.setattr(te, "effective_client_ids", lambda _u: {MINE})
    te.list_firm_tags(current_user=USER)
    assert captured == {"allowed_client_ids": {MINE}}


def test_a_firmwide_role_gets_the_whole_vocabulary(monkeypatch):
    """effective_client_ids returns None for a Partner, which is the repository's
    "no narrowing" signal — one query, exactly as before the fix."""
    captured = {}
    monkeypatch.setattr(te.task_extras_repo, "get_firm_tags",
                        lambda firm_id, **kw: captured.update(kw) or [])
    monkeypatch.setattr(te, "effective_client_ids", lambda _u: None)
    te.list_firm_tags(current_user=PARTNER)
    assert captured == {"allowed_client_ids": None}


# ══════════════════════════════════════════════════════════════════════════════
# tasks.py — the same prefix, so the same rule
# ══════════════════════════════════════════════════════════════════════════════

def test_editing_another_clients_task_is_refused(deny, monkeypatch):
    written = []
    monkeypatch.setattr(tr.task_repo, "update",
                        lambda *a, **k: written.append(a) or {})
    with pytest.raises(HTTPException) as e:
        tr.update_task("T-THEIRS", tr.TaskUpdate(title="renamed"),
                       current_user=USER)
    assert e.value.status_code == 404
    assert written == [], "the task was updated despite the refusal"


def test_editing_your_own_task_still_works(deny, monkeypatch):
    monkeypatch.setattr(tr.task_repo, "update",
                        lambda tid, updates: {**TASKS[tid], **updates})
    out = tr.update_task("T-MINE", tr.TaskUpdate(title="renamed"),
                         current_user=USER)
    assert out["data"]["task"]["title"] == "renamed"


# ── The three firm-wide jobs ──────────────────────────────────────────────────

@pytest.fixture
def jobs(monkeypatch):
    """The job modules themselves, spied. Each handler imports them INSIDE the
    function, so patching the source module is what actually intercepts them."""
    ran = []
    monkeypatch.setattr("services.escalation_service.escalation_service.run_all_escalations",
                        lambda *a, **k: ran.append("escalations") or {"ok": True})
    monkeypatch.setattr("jobs.scheduler.run_daily_jobs",
                        lambda *a, **k: ran.append("daily") or {"ok": True})
    monkeypatch.setattr("jobs.recurring_task_job.run_recurring_generation_job",
                        lambda *a, **k: ran.append("recurring") or
                        {"success": True, "count": 0, "tasks": []})
    return ran


@pytest.mark.parametrize("fn", [
    "trigger_escalations", "trigger_scheduler_run", "trigger_recurring_generation",
])
@pytest.mark.parametrize("role", ["Executive", "Reviewer", "Manager"])
def test_a_firmwide_job_is_refused_to_an_assignment_scoped_role(fn, role, jobs):
    """Manager is in this list deliberately: the M3 decision left only the
    Partner firm-wide, so a Manager is assignment-scoped like everyone else."""
    with pytest.raises(HTTPException) as e:
        getattr(tr, fn)(current_user={"id": "x", "firm_id": FIRM, "role": role})
    assert e.value.status_code == 403, "403, not 404 — no id, nothing hidden"
    assert jobs == [], f"{fn} ran the job across the whole firm anyway"


def test_the_refusal_names_the_roles_that_actually_qualify():
    """This message had already drifted once — it told a Manager the endpoint was
    open to Managers. It is derived from _FIRMWIDE_ROLES now, so it cannot."""
    with pytest.raises(HTTPException) as e:
        tr._assert_firmwide_job(USER, "Escalation processing")
    assert firmwide_roles_label() in e.value.detail
    assert "Managers" not in e.value.detail


@pytest.mark.parametrize("fn,expected", [
    ("trigger_escalations", "escalations"),
    ("trigger_scheduler_run", "daily"),
    ("trigger_recurring_generation", "recurring"),
])
def test_a_firmwide_role_still_runs_every_job(fn, expected, jobs):
    out = getattr(tr, fn)(current_user=PARTNER)
    assert out["success"] is True
    assert jobs == [expected]


# ══════════════════════════════════════════════════════════════════════════════
# The repository — where the narrowing and the traversal actually happen
# ══════════════════════════════════════════════════════════════════════════════

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
        self.filters = []

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        self.log.append((self.name, list(self.filters)))
        out = self.rows
        for kind, col, val in self.filters:
            out = [r for r in out if (r.get(col) == val if kind == "eq"
                                      else r.get(col) in val)]
        return _Res(out)


class _FakeDb:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def table(self, name):
        return _FakeTable(name, self.tables.get(name, []), self.log)


@pytest.fixture
def fake_db(monkeypatch):
    def _build(tables):
        db = _FakeDb(tables)
        monkeypatch.setattr("repositories.task_extras_repository._get_db",
                            lambda: db)
        return db
    return _build


TAG_ROWS = [
    {"firm_id": FIRM, "task_id": "T-MINE", "tag": "gst"},
    {"firm_id": FIRM, "task_id": "T-THEIRS", "tag": "acme-merger"},
    {"firm_id": "firm-2", "task_id": "T-OTHER-FIRM", "tag": "someone-else"},
]
TASK_ROWS = [{"id": t["id"], "client_id": t["client_id"]} for t in TASKS.values()]


def test_get_firm_tags_hides_tags_typed_on_clients_you_are_not_on(fake_db):
    fake_db({"task_tags": TAG_ROWS, "tasks": TASK_ROWS})
    repo = TaskExtrasRepository()
    assert repo.get_firm_tags(FIRM, allowed_client_ids={MINE}) == ["gst"]


def test_get_firm_tags_unnarrowed_keeps_the_single_query_path(fake_db):
    """None means "every client in the firm". It must not become a second query
    for the Partners and Managers who legitimately see everyone."""
    db = fake_db({"task_tags": TAG_ROWS, "tasks": TASK_ROWS})
    repo = TaskExtrasRepository()
    assert repo.get_firm_tags(FIRM) == ["acme-merger", "gst"]
    assert [name for name, _ in db.log] == ["task_tags"]


def test_get_firm_tags_with_an_empty_assignment_set_returns_nothing(fake_db):
    """An empty set is not "no filter" — it is "no clients"."""
    fake_db({"task_tags": TAG_ROWS, "tasks": TASK_ROWS})
    assert TaskExtrasRepository().get_firm_tags(FIRM, allowed_client_ids=set()) == []


# ── Cycle detection used to read every firm's dependency rows ─────────────────

DEP_ROWS = [
    {"task_id": "A", "depends_on_task_id": "B"},
    {"task_id": "B", "depends_on_task_id": "C"},
    # A different firm's chain. `task_dependencies` has no firm_id to filter on
    # (migration 063 scopes it through `tasks`), so the traversal's own bounds
    # are what keep these rows out.
    {"task_id": "X", "depends_on_task_id": "Y"},
    {"task_id": "Y", "depends_on_task_id": "Z"},
]


def test_a_dependency_that_closes_a_loop_is_detected(fake_db):
    fake_db({"task_dependencies": DEP_ROWS})
    assert TaskExtrasRepository()._detect_cycle("C", "A") is True


def test_a_dependency_that_does_not_close_a_loop_is_allowed(fake_db):
    fake_db({"task_dependencies": DEP_ROWS})
    assert TaskExtrasRepository()._detect_cycle("D", "A") is False


def test_the_traversal_never_reads_the_whole_dependency_table(fake_db):
    """It used to SELECT every row in `task_dependencies` — every firm's — to
    answer a question about two tasks in one firm."""
    db = fake_db({"task_dependencies": DEP_ROWS})
    TaskExtrasRepository()._detect_cycle("D", "A")
    assert db.log, "no query ran at all"
    for name, filters in db.log:
        assert filters, f"unfiltered read of {name}"
        assert any(kind == "in" and col == "task_id" for kind, col, _ in filters)


def test_the_traversal_reads_only_what_is_reachable(fake_db):
    """The other firm's chain is never asked for, because nothing in this firm
    points at it."""
    db = fake_db({"task_dependencies": DEP_ROWS})
    TaskExtrasRepository()._detect_cycle("D", "A")
    asked = {i for _n, filters in db.log for kind, _c, vals in filters
             if kind == "in" for i in vals}
    assert asked == {"A", "B", "C"}


def test_the_traversal_terminates_on_an_existing_loop(fake_db):
    """A cycle already in the data must not spin forever while looking for a
    different one."""
    db = fake_db({"task_dependencies": [
        {"task_id": "A", "depends_on_task_id": "B"},
        {"task_id": "B", "depends_on_task_id": "A"},
    ]})
    assert TaskExtrasRepository()._detect_cycle("Q", "A") is False
    assert len(db.log) <= 4
