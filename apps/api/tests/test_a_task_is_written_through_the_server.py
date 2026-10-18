"""A task's status, assignee, client, due date and deletion are written through the server (POST-A-227).

WHAT WAS WRONG
    `lib/data/tasks.ts` wrote `tasks` straight over PostgREST. The PATCH route's rules were therefore skipped by the two
    screens that matter most: the status machine (a completed task stays completed; review is passed through), the check that
    an assignee belongs to the firm (the foreign keys only require a users row, so a cross-firm assignee id was accepted
    directly), the check that the client a task is moved to is one the caller may act on, the audit log, the timeline and the
    notification to a new assignee. The helpers also ignored the database's reply, so a refused write looked saved until the
    next load, and a delete of a task still linked to a reminder was refused by a foreign key the screen never read.

WHAT IS HELD HERE (no database)
    * the browser writes no `tasks` row any more;
    * a due date is a calendar date or nothing, and a blank is nothing (422 for a malformed one);
    * PATCH: an explicit null clears the due date and the assignee and nothing else; a value equal to what is held is not a
      change (the same status is not a transition); a client move needs the caller to act on the NEW client, which must be one
      of this firm; clearing an assignee is logged as an unassignment;
    * create writes both assignee columns, as every other creator of a task does;
    * DELETE: a task that is missing and one in a client the caller may not act on answer identically; it deletes with the
      firm named, removes the tags, dependencies and events that hang off it, and writes the whole row to the audit log; a
      foreign-key refusal is a 409 that says so;
    * the status machine is served, so a screen offers only the moves the server accepts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_direct_write_tables_are_role_guarded import WEB, _chains, _strip_comments  # noqa: E402

import routers.tasks as tr  # noqa: E402

FIRM = "firm-1"
MINE, THEIRS, NEW = "client-mine", "client-theirs", "client-new"
USER = {"id": "u1", "auth_user_id": "a1", "firm_id": FIRM, "role": "Manager", "email": "m@f.in", "full_name": "Maya"}


# ── the browser ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not in this checkout")
def test_the_browser_writes_no_task_row():
    import re
    writers = []
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, tail in _chains(_strip_comments(src)):
            if name == "tasks" and re.search(r"\.\s*(insert|upsert|update|delete)\s*\(", tail):
                writers.append(path.relative_to(WEB).as_posix())
    assert writers == [], writers


# ── the models ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [("2026-11-05", "2026-11-05"), ("", None), ("   ", None), (None, None)])
def test_a_due_date_is_a_date_or_nothing(raw, expected):
    assert tr.TaskCreate(client_id="c", title="t", due_date=raw).due_date == expected
    assert tr.TaskUpdate(due_date=raw).due_date == expected


@pytest.mark.parametrize("bad", ["05-11-2026", "2026-13-40", "tomorrow", "2026-11"])
def test_a_malformed_due_date_is_refused_by_name(bad):
    for model in (lambda: tr.TaskCreate(client_id="c", title="t", due_date=bad), lambda: tr.TaskUpdate(due_date=bad)):
        with pytest.raises(ValidationError) as e:
            model()
        assert "due_date" in str(e.value)


def test_an_empty_assignee_is_nobody():
    assert tr.TaskCreate(client_id="c", title="t", assigned_to="").assigned_to is None
    assert tr.TaskUpdate(assigned_to="").assigned_to is None
    assert "assigned_to" in tr.TaskUpdate(assigned_to=None).model_fields_set
    assert "assigned_to" not in tr.TaskUpdate().model_fields_set


# ── PATCH ────────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Repo:
    def __init__(self, task):
        self.task = dict(task)
        self.updates = []
        self.deleted = []
        self.delete_error = None

    def find_by_id(self, tid, firm_id=None, **_k):
        # A copy, as the real repository returns: the route compares what it read with what it wrote.
        return dict(self.task) if tid == self.task["id"] else None

    def update(self, tid, data):
        self.updates.append(dict(data))
        self.task.update(data)
        return dict(self.task)

    def delete(self, tid, *, firm_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((tid, firm_id))
        return True


@pytest.fixture()
def world(monkeypatch):
    task = {"id": "T1", "firm_id": FIRM, "client_id": MINE, "title": "File GSTR-1", "status": "todo",
            "priority": "medium", "assigned_to": "u-old", "assignee_id": "u-old", "due_date": "2026-11-05"}
    repo = _Repo(task)
    monkeypatch.setattr(tr, "task_repo", repo)
    audit, extras = [], []
    monkeypatch.setattr(tr, "log_event", lambda *a, **k: audit.append((a, k)))

    class _Extras:
        def log_event(self, **k):
            extras.append(k)

        def purge_task(self, tid, *, firm_id):
            extras.append({"purge": (tid, firm_id)})

    import repositories.task_extras_repository as ter
    monkeypatch.setattr(ter, "task_extras_repo", _Extras())
    from repositories.user_repository import user_repo
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, firm_id=None: {"id": uid, "firm_id": FIRM})
    from repositories.client_repository import client_repo
    monkeypatch.setattr(client_repo, "find_by_id",
                        lambda cid, firm_id=None: {"id": cid} if cid in (MINE, NEW) else None)
    monkeypatch.setattr(tr, "client_repo", client_repo)

    def _check(user, client_id, *, detail="Not found"):
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail=detail)
    monkeypatch.setattr(tr, "assert_client_access", _check)
    return repo, audit, extras


def _patch(**fields):
    return tr.update_task("T1", tr.TaskUpdate(**fields), USER)


def test_an_explicit_null_clears_the_due_date_and_the_assignee_and_nothing_else(world):
    repo, _audit, extras = world
    _patch(due_date=None, assigned_to=None, title=None)
    [applied] = repo.updates
    assert applied["due_date"] is None and applied["assigned_to"] is None and applied["assignee_id"] is None
    assert "title" not in applied                       # a null title does not wipe the title
    assert [e["event_type"] for e in extras if "event_type" in e] == ["unassigned"]


def test_a_field_that_is_absent_is_left_alone(world):
    repo, _a, _e = world
    _patch(priority="high")
    [applied] = repo.updates
    assert "due_date" not in applied and "assigned_to" not in applied and applied["priority"] == "high"


def test_a_blank_box_clears_exactly_as_a_null_does(world):
    repo, _a, _e = world
    _patch(due_date="", assigned_to="")
    [applied] = repo.updates
    assert applied["due_date"] is None and applied["assigned_to"] is None


def test_the_same_status_is_not_a_transition(world):
    repo, _a, _e = world
    _patch(status="todo", title="New title")            # a form sends the whole task
    [applied] = repo.updates
    assert "status" not in applied and applied["title"] == "New title"


def test_a_move_the_machine_does_not_allow_is_refused_in_words(world):
    repo, _a, _e = world
    with pytest.raises(HTTPException) as e:
        _patch(status="completed")                      # todo -> completed skips the work
    assert e.value.status_code == 400 and "todo" in e.value.detail and "completed" in e.value.detail
    assert repo.updates == []


def test_a_task_moves_to_another_client_only_if_the_caller_may_act_on_it(world):
    repo, audit, _e = world
    _patch(client_id=NEW)
    assert repo.updates[-1]["client_id"] == NEW
    assert any(k["new_data"] == {"client_id": NEW} for _a, k in audit)
    repo.updates.clear()
    for target in (THEIRS, "client-elsewhere-in-another-firm"):
        with pytest.raises(HTTPException) as e:
            _patch(client_id=target)
        assert e.value.status_code == 404 and e.value.detail == "Client not found"
    assert repo.updates == []


def test_the_same_client_is_not_a_move(world):
    repo, audit, _e = world
    _patch(client_id=MINE, priority="low")
    assert "client_id" not in repo.updates[-1]
    assert not any("client_id" in (k.get("new_data") or {}) for _a, k in audit)


def test_an_assignee_outside_the_firm_is_still_refused(world, monkeypatch):
    repo, _a, _e = world
    from repositories.user_repository import user_repo
    monkeypatch.setattr(user_repo, "find_by_id", lambda uid, firm_id=None: None)
    with pytest.raises(HTTPException) as e:
        _patch(assigned_to="stranger")
    assert e.value.status_code == 422 and repo.updates == []


# ── create ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_create_writes_both_assignee_columns(world, monkeypatch):
    created = []
    monkeypatch.setattr(tr.task_repo, "create", lambda data: created.append(data) or {"id": "N1", "title": "t", **data},
                        raising=False)
    monkeypatch.setattr(tr, "log_activity", lambda **_k: {})
    tr.create_task(tr.TaskCreate(client_id=MINE, title="t", assigned_to="u-new"), USER)
    [row] = created
    assert row["assigned_to"] == "u-new" and row["assignee_id"] == "u-new" and row["firm_id"] == FIRM


def test_create_without_an_assignee_writes_neither(world, monkeypatch):
    created = []
    monkeypatch.setattr(tr.task_repo, "create", lambda data: created.append(data) or {"id": "N1", "title": "t", **data},
                        raising=False)
    monkeypatch.setattr(tr, "log_activity", lambda **_k: {})
    tr.create_task(tr.TaskCreate(client_id=MINE, title="t", assigned_to=""), USER)
    assert not created[0].get("assignee_id") and not created[0].get("assigned_to")


# ── DELETE ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_task_that_is_missing_and_one_the_caller_may_not_act_on_answer_alike(world, monkeypatch):
    repo, _a, _e = world
    with pytest.raises(HTTPException) as missing:
        tr.delete_task("T-NONE", USER)
    repo.task["client_id"] = THEIRS
    with pytest.raises(HTTPException) as hidden:
        tr.delete_task("T1", USER)
    assert (missing.value.status_code, missing.value.detail) == (hidden.value.status_code, hidden.value.detail) \
        == (404, "Task not found")
    assert repo.deleted == []


def test_a_task_in_another_firm_answers_as_missing(world):
    repo, _a, _e = world
    repo.task["firm_id"] = "firm-2"
    with pytest.raises(HTTPException) as e:
        tr.delete_task("T1", USER)
    assert (e.value.status_code, e.value.detail) == (404, "Task not found") and repo.deleted == []


def test_a_delete_names_the_firm_purges_what_hangs_off_and_audits_the_whole_row(world):
    repo, audit, extras = world
    res = tr.delete_task("T1", USER)
    assert res["data"] == {"deleted": True, "id": "T1"}
    assert repo.deleted == [("T1", FIRM)]
    assert {"purge": ("T1", FIRM)} in extras
    [(args, kwargs)] = audit
    assert args[:4] == (FIRM, "task", "T1", "delete")
    assert kwargs["actor_id"] == "a1" and kwargs["old_data"]["title"] == "File GSTR-1"
    assert kwargs["old_data"]["due_date"] == "2026-11-05" and kwargs["old_data"]["assigned_to"] == "u-old"


def test_a_task_still_linked_to_a_reminder_is_refused_in_words_and_nothing_else_is_removed(world):
    repo, audit, extras = world
    repo.delete_error = RuntimeError('update or delete on table "tasks" violates foreign key constraint (23503)')
    with pytest.raises(HTTPException) as e:
        tr.delete_task("T1", USER)
    assert e.value.status_code == 409 and "reminder or a compliance record" in e.value.detail
    assert audit == [] and not [x for x in extras if "purge" in x]


def test_any_other_failure_is_not_dressed_up_as_a_conflict(world):
    repo, _a, _e = world
    repo.delete_error = RuntimeError("connection reset")
    with pytest.raises(RuntimeError):
        tr.delete_task("T1", USER)


def test_a_delete_asks_the_delete_tier_and_the_status_moves_ask_read():
    import ast
    tree = ast.parse((Path(tr.__file__)).read_text(encoding="utf-8"))
    deps = {}
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in ("delete_task", "status_transitions"):
            defaults = {a.arg: d for a, d in zip(fn.args.args[-len(fn.args.defaults):], fn.args.defaults, strict=True)}
            deps[fn.name] = ast.unparse(defaults["current_user"])
    assert deps == {"delete_task": "Depends(rbac('task', 'delete'))", "status_transitions": "Depends(rbac('task', 'read'))"}


def test_the_status_machine_is_served():
    from services.task_service import VALID_TRANSITIONS
    res = tr.status_transitions(USER)
    assert res["data"]["transitions"] == VALID_TRANSITIONS
    assert res["data"]["transitions"]["completed"] == []


# ── the repositories ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_task_delete_needs_the_firm():
    from repositories.task_repository import TaskRepository
    with pytest.raises(ValueError):
        TaskRepository().delete("T1", firm_id="")


def test_the_satellites_are_removed_with_the_privileged_client_and_the_firm(monkeypatch):
    import repositories.task_extras_repository as ter
    calls = []

    class _Q:
        def __init__(self, table):
            self.table_name, self.ops = table, []

        def delete(self):
            self.ops.append("delete")
            return self

        def eq(self, k, v):
            self.ops.append(f"eq {k}={v}")
            return self

        def or_(self, expr):
            self.ops.append(f"or {expr}")
            return self

        def execute(self):
            calls.append((self.table_name, tuple(self.ops)))
            return type("R", (), {"data": []})()

    class _Db:
        def table(self, name):
            return _Q(name)

    monkeypatch.setattr(ter, "_write_db", lambda: _Db())
    ter.TaskExtrasRepository().purge_task("T1", firm_id=FIRM)
    tables = {t: ops for t, ops in calls}
    assert set(tables) == {"task_tags", "task_timeline_events", "task_dependencies"}
    assert "eq firm_id=firm-1" in tables["task_tags"] and "eq firm_id=firm-1" in tables["task_timeline_events"]
    # A dependency has no firm of its own, so it goes where this task is either end of it. Two plain filters rather than one
    # `.or_()` with an f-string: the column scan can read a literal column name and cannot read a built expression.
    dependency_deletes = sorted(ops for t, ops in calls if t == "task_dependencies")
    assert dependency_deletes == [("delete", "eq depends_on_task_id=T1"), ("delete", "eq task_id=T1")]
