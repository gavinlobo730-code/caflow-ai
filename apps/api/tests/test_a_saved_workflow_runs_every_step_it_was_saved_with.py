"""A SAVED WORKFLOW RUNS EVERY STEP IT WAS SAVED WITH, ONCE (POST-A-204, first slice).

WHAT WAS WRONG, measured on the code this replaced (each is a test below):

  * A template saved through POST /api/workflows/templates stored every step with
    `next_step_id = NULL`: a link names a step by id and no step has an id before
    it is stored. The engine reads a missing link as "the flow ends here", so a
    template of THREE steps ran the first, completed, and reported success.
    Every older multi-step test wired its links by hand with repo._create_step,
    which is why nothing noticed.
  * Pressing "run" on one workflow called fire_trigger with the template's
    trigger TYPE, so every active template of that type started with it (three
    runs from one press, two of them somebody else's workflow), and a paused
    template started nothing. The answer counted a repeat of a run that already
    existed as "started".
  * The idempotency check ignored status, so a FAILED or CANCELLED run held its
    key for ever and the same event could never start it again.
  * An approval that was the LAST step recorded no step to go on at, kept its own
    id as `current_step_id`, and so approving it ran the approval step again,
    created a second approval, and never completed. What ran after an approval
    ran in a second, weaker copy of the run loop: no action logs, no
    current_step_id, and the context of the earlier steps was gone.
  * Deleting a template that had ever run was a foreign-key error and a 500.
  * Replacing a template's steps while a run was working or waiting on an
    approval left that run pointing at a step that no longer existed.
  * A save sent the steps one request at a time (delete all, then insert one by
    one), so a failure part-way left a template with a fraction of its steps.

THE RULES THESE TESTS HOLD, not the spelling of the code that keeps them:

  * what a template is saved with is what it runs, in the order it was listed;
  * a person who runs a workflow runs THAT workflow;
  * a run that did not do its work does not block the same event from doing it;
  * a run that is waiting on a person finishes when the person answers, whatever
    the approval's position;
  * a refusal says why and what to do, in a 409, never a 500;
  * a save is all of its steps or none.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from domain.workflow import step_links
from tests._property import kernel

API = pathlib.Path(__file__).resolve().parent.parent

_USER = {
    "auth_user_id": "u-partner", "id": "u-partner", "firm_id": "firm-1",
    "email": "partner@test.example", "role": "Partner",
}
FIRM = _USER["firm_id"]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from main import app
    from core.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _client_belongs_to_firm(monkeypatch):
    """create_task's tenancy guard needs client_repo.find_by_id(client_id, firm_id)
    to resolve; the demo clients model no firm, so accept any id under this firm."""
    from repositories import client_repository
    monkeypatch.setattr(
        client_repository.client_repo, "find_by_id",
        lambda cid, fid=None: {"id": cid, "firm_id": FIRM},
    )


@pytest.fixture(autouse=True)
def _no_sleeping_between_retries(monkeypatch):
    monkeypatch.setattr("domain.workflow_engine_v2.time.sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def isolated_stores():
    """Each test starts from empty mock stores and puts the import-time seeds back
    afterwards (they are module globals shared by the whole session)."""
    from repositories import workflow_repository as wr
    from repositories.task_repository import MOCK_TASKS, TASK_INDEX
    stores = (wr.MOCK_TEMPLATES, wr.MOCK_STEPS, wr.MOCK_INSTANCES,
              wr.MOCK_ACTION_LOGS, wr.MOCK_EXECUTIONS, wr.MOCK_FAILURES,
              wr.MOCK_APPROVALS, wr.MOCK_SCHEDULES, MOCK_TASKS)
    snapshots = [list(s) for s in stores]
    index_snapshot = dict(TASK_INDEX)
    for s in stores:
        s.clear()
    TASK_INDEX.clear()
    yield
    for s, snap in zip(stores, snapshots, strict=True):
        s.clear()
        s.extend(snap)
    TASK_INDEX.clear()
    TASK_INDEX.update(index_snapshot)


@pytest.fixture
def repo():
    from repositories.workflow_repository import workflow_repo
    return workflow_repo


@pytest.fixture
def engine():
    from domain.workflow_engine_v2 import workflow_engine
    return workflow_engine


# ── Helpers ───────────────────────────────────────────────────────────────────

def task_step(title: str) -> dict:
    return {"step_order": 99, "step_type": "action", "name": title,
            "config": {"action_type": "create_task", "params": {"title": title}}}


def approval_step(name: str = "Partner sign-off") -> dict:
    return {"step_order": 99, "step_type": "approval", "name": name,
            "config": {"approver_role": "Partner", "title": name}}


def make_template(client, steps, name="Saved workflow", trigger_type="client_created",
                  is_active=True, conditions=None) -> dict:
    r = client.post("/api/workflows/templates", json={
        "name": name, "category": "compliance", "trigger_type": trigger_type,
        "trigger_config": {}, "conditions": conditions or {}, "steps": steps,
        "is_active": is_active,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def press(client, template, **payload) -> dict:
    payload.setdefault("client_id", "c-001")
    r = client.post(f"/api/workflows/templates/{template['id']}/trigger", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def pending_approval(client, instance_id: str) -> dict:
    approvals = client.get("/api/workflows/approvals").json()["data"]["approvals"]
    mine = [a for a in approvals if a["instance_id"] == instance_id]
    assert len(mine) == 1, f"expected exactly one pending approval, got {len(mine)}"
    return mine[0]


def approve(client, approval_id: str, decision: str = "approved"):
    r = client.post(f"/api/workflows/approvals/{approval_id}/respond",
                    json={"decision": decision, "response_notes": "ok"})
    assert r.status_code == 200, r.text


def task_titles() -> list[str]:
    from repositories.task_repository import MOCK_TASKS
    return [t["title"] for t in MOCK_TASKS]


# ══════════════════════════════════════════════════════════════════════════════
# 1. What a template is saved with is what it runs
# ══════════════════════════════════════════════════════════════════════════════

def test_a_three_step_template_made_through_the_api_runs_all_three(client, repo):
    tpl = make_template(client, [task_step("one"), task_step("two"), task_step("three")])
    run = press(client, tpl)["instances"][0]

    assert run["status"] == "completed", run
    assert run["steps_executed"] == 3, "the template ran only part of what it was saved with"
    assert sorted(task_titles()) == ["one", "three", "two"]
    logs = repo.list_action_logs(run["instance_id"])
    assert [(l["step_name"], l["status"]) for l in logs] == [
        ("one", "success"), ("two", "success"), ("three", "success")]


def test_the_steps_are_stored_in_the_order_they_were_listed_whatever_step_order_said(client):
    """step_order is the position in the list. The caller's number was always
    overwritten; it is now part of the contract."""
    steps = [dict(task_step("first"), step_order=7), dict(task_step("second"), step_order=3),
             dict(task_step("third"), step_order=5)]
    tpl = make_template(client, steps)
    assert [(s["step_order"], s["name"]) for s in tpl["steps"]] == [
        (0, "first"), (1, "second"), (2, "third")]


def test_each_stored_step_links_to_the_next_and_the_last_ends_the_flow(client):
    tpl = make_template(client, [task_step("a"), task_step("b"), task_step("c")])
    a, b, c = tpl["steps"]
    assert a["next_step_id"] == b["id"]
    assert b["next_step_id"] == c["id"]
    assert c["next_step_id"] is None


def test_replacing_the_steps_of_a_template_links_the_new_ones(client):
    tpl = make_template(client, [task_step("old")])
    r = client.patch(f"/api/workflows/templates/{tpl['id']}", json={
        "steps": [task_step("x"), task_step("y"), task_step("z")]})
    assert r.status_code == 200, r.text
    saved = r.json()["data"]
    assert [s["name"] for s in saved["steps"]] == ["x", "y", "z"]
    assert saved["steps"][0]["next_step_id"] == saved["steps"][1]["id"]
    run = press(client, saved)["instances"][0]
    assert run["steps_executed"] == 3
    assert "old" not in task_titles()


def test_a_patch_that_leaves_the_steps_out_leaves_the_steps_alone(client):
    tpl = make_template(client, [task_step("a"), task_step("b")])
    ids = [s["id"] for s in tpl["steps"]]
    r = client.patch(f"/api/workflows/templates/{tpl['id']}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    after = r.json()["data"]
    assert after["name"] == "Renamed"
    assert [s["id"] for s in after["steps"]] == ids


def test_a_template_read_back_and_saved_again_still_runs_every_step(client):
    """The builder will send back what it was given. Those steps carry the old
    steps' ids in their links, and the old steps are replaced, so a link kept
    as sent would point at nothing and end the flow after the first step."""
    tpl = make_template(client, [task_step("a"), task_step("b"), task_step("c")])
    echoed = [{k: s[k] for k in ("step_order", "step_type", "name", "config", "next_step_id",
                                 "true_branch_step_id", "false_branch_step_id", "description")}
              for s in tpl["steps"]]
    r = client.patch(f"/api/workflows/templates/{tpl['id']}", json={"steps": echoed})
    assert r.status_code == 200, r.text
    saved = r.json()["data"]
    assert press(client, saved)["instances"][0]["steps_executed"] == 3


def test_an_empty_step_list_is_a_template_with_no_steps_and_still_completes(client):
    tpl = make_template(client, [])
    assert tpl["steps"] == []
    run = press(client, tpl)["instances"][0]
    assert (run["status"], run["steps_executed"]) == ("completed", 0)


# ── The pure rule ─────────────────────────────────────────────────────────────

LINEAR_TYPES = ["action", "approval", "delay", "trigger"]


def follow(rows: list[dict]) -> list[str]:
    """The ids a run visits by following next_step_id alone from the first row."""
    by_id = {r["id"]: r for r in rows}
    seen, current = [], rows[0]["id"] if rows else None
    while current in by_id and current not in seen:
        seen.append(current)
        current = by_id[current]["next_step_id"]
    return seen


@st.composite
def straight_line(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    return [{"step_order": draw(st.integers(min_value=-5, max_value=500)),
             "step_type": draw(st.sampled_from(LINEAR_TYPES)),
             "name": f"step {i}", "config": {}, "description": None,
             "next_step_id": draw(st.sampled_from([None, None, "an-id-from-before-this-save"])),
             "true_branch_step_id": None, "false_branch_step_id": None}
            for i in range(n)]


@kernel()
@given(steps=straight_line())
def test_property_a_straight_line_is_followed_through_every_step_once_in_order(steps):
    rows = step_links.prepare(steps)
    assert len({r["id"] for r in rows}) == len(rows)
    assert [r["step_order"] for r in rows] == list(range(len(rows)))
    assert follow(rows) == [r["id"] for r in rows]
    assert rows[-1]["next_step_id"] is None
    assert all(r["true_branch_step_id"] is None and r["false_branch_step_id"] is None for r in rows)


@kernel()
@given(steps=straight_line())
def test_property_a_prepared_list_prepared_again_is_unchanged(steps):
    """Saving what was read back must not move anything: ids and resolvable
    links are kept, so the second pass finds the list already wired."""
    once = step_links.prepare(steps)
    assert step_links.prepare(once) == once


@kernel()
@given(steps=straight_line(), where=st.integers(min_value=0, max_value=39),
       kind=st.sampled_from(sorted(step_links.BRANCHING_TYPES)))
def test_property_a_list_with_a_branch_is_never_chained_through_it(steps, where, kind):
    """Which two steps a branch chooses between is not in the list order, so a
    list with one is stored with no invented path: no step is linked."""
    steps = [dict(s, next_step_id=None) for s in steps]
    steps[where % len(steps)]["step_type"] = kind
    rows = step_links.prepare(steps)
    assert all(r[f] is None for r in rows for f in step_links.LINK_FIELDS)


def test_a_link_between_steps_of_the_same_save_is_kept_not_replaced():
    """A direct caller (an installer, a test) that names its own ids and wires
    them is believed: only a link to a step that is NOT in this save is removed."""
    rows = step_links.prepare([
        {"id": "s1", "step_type": "action", "name": "a", "next_step_id": "s3"},
        {"id": "s2", "step_type": "action", "name": "b"},
        {"id": "s3", "step_type": "action", "name": "c"},
    ])
    assert [r["next_step_id"] for r in rows] == ["s3", None, None]


def test_a_link_to_a_step_that_is_not_in_the_save_is_removed():
    rows = step_links.prepare([
        {"step_type": "action", "name": "a", "next_step_id": "from-another-template"},
        {"step_type": "action", "name": "b"},
    ])
    assert rows[0]["next_step_id"] == rows[1]["id"]
    rows = step_links.prepare([
        {"step_type": "branch", "name": "a", "true_branch_step_id": "gone",
         "false_branch_step_id": "gone"},
        {"step_type": "action", "name": "b"},
    ])
    assert [(r["true_branch_step_id"], r["false_branch_step_id"], r["next_step_id"])
            for r in rows] == [(None, None, None)] * 2


def test_the_prepared_rows_name_only_columns_workflow_steps_has():
    """The bulk insert is built from these keys; one the table lacks would reject
    the whole batch. Checked against the production snapshot."""
    schema = json.loads((API / "tests/fixtures/production_schema_2026-09-03.json").read_text())
    columns = set(schema["workflow_steps"])
    row = step_links.prepare([{"step_type": "action", "name": "a"}])[0]
    assert set(row) <= columns, sorted(set(row) - columns)


# ══════════════════════════════════════════════════════════════════════════════
# 2. A person who runs a workflow runs THAT workflow
# ══════════════════════════════════════════════════════════════════════════════

def test_running_one_workflow_does_not_run_another_on_the_same_trigger(client, repo):
    a = make_template(client, [task_step("A-task")], name="A")
    b = make_template(client, [task_step("B-task")], name="B")

    answer = press(client, a)
    assert answer["instances_started"] == 1
    assert task_titles() == ["A-task"]
    assert repo.list_instances(FIRM, template_id=a["id"]) != []
    assert repo.list_instances(FIRM, template_id=b["id"]) == []


def test_an_event_still_starts_every_active_workflow_on_its_trigger(client, engine, repo):
    """The automatic path is unchanged: that IS the broadcast, by design."""
    make_template(client, [task_step("A-task")], name="A")
    make_template(client, [task_step("B-task")], name="B")
    paused = make_template(client, [task_step("P-task")], name="P", is_active=False)

    results = engine.fire_trigger(FIRM, "client_created", {"client_id": "c-9"}, client_id="c-9")

    assert sorted(task_titles()) == ["A-task", "B-task"]
    assert len(results) == 2
    assert repo.list_instances(FIRM, template_id=paused["id"]) == []


def test_a_paused_workflow_can_be_run_by_hand_and_does_not_run_by_itself(client, engine):
    """is_active governs whether a workflow starts on its own. A person who
    presses run has decided to. (The owner is asked to confirm this rule.)"""
    paused = make_template(client, [task_step("by-hand")], is_active=False)

    assert engine.fire_trigger(FIRM, "client_created", {"client_id": "c-2"}, client_id="c-2") == []
    assert task_titles() == []

    answer = press(client, paused, client_id="c-2")
    assert answer["instances_started"] == 1
    assert task_titles() == ["by-hand"]


def test_trigger_config_filters_events_and_not_a_persons_press(client):
    """trigger_config says which EVENTS start a template (here: only when a
    deadline is within 7 days). Nobody pressed an event; a person pressed run."""
    r = client.post("/api/workflows/templates", json={
        "name": "Due soon", "category": "compliance", "trigger_type": "gst_due",
        "trigger_config": {"days_before": 7}, "conditions": {}, "steps": [task_step("filing")]})
    tpl = r.json()["data"]
    assert press(client, tpl)["instances_started"] == 1
    assert task_titles() == ["filing"]


def test_a_workflow_whose_conditions_are_not_met_says_so_instead_of_an_empty_list(client):
    conditions = {"logic": "AND", "groups": [], "rules": [
        {"field": "score", "operator": ">", "value": "50", "value_type": "number"}]}
    tpl = make_template(client, [task_step("risky")], conditions=conditions)

    answer = press(client, tpl, score=10)
    assert answer["instances_started"] == 0
    [result] = answer["instances"]
    assert result["status"] == "not_started" and result["reason"] == "conditions_not_met"
    assert "conditions" in result["message"]
    assert task_titles() == []

    assert press(client, tpl, score=80)["instances_started"] == 1


def test_a_trigger_the_engine_does_not_recognise_is_said_and_not_silently_dropped(client, engine, monkeypatch):
    tpl = make_template(client, [task_step("x")])
    monkeypatch.setattr(engine, "_evaluate_trigger", lambda trigger_type, data: False)

    [result] = engine.start_manually(FIRM, tpl["id"], {"client_id": "c-1"}, client_id="c-1")

    assert (result["status"], result["reason"]) == ("not_started", "trigger_not_recognised")
    assert task_titles() == []


def test_pressing_the_same_run_twice_is_a_duplicate_and_is_not_counted_as_started(client, repo):
    tpl = make_template(client, [task_step("once")])
    first = press(client, tpl)
    second = press(client, tpl)

    assert first["instances_started"] == 1
    assert second["instances_started"] == 0
    [dup] = second["instances"]
    assert dup["status"] == "duplicate_skipped"
    assert dup["instance_id"] == first["instances"][0]["instance_id"]
    assert task_titles() == ["once"]
    assert len(repo.list_instances(FIRM, template_id=tpl["id"])) == 1


def test_a_start_for_a_template_that_does_not_exist_is_a_404_not_an_empty_success(client):
    r = client.post("/api/workflows/templates/no-such-template/trigger", json={})
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 3. A run that did not do its work does not block the same event
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status,holds_the_key", [
    ("pending", True), ("running", True), ("waiting_approval", True), ("completed", True),
    ("failed", False), ("cancelled", False),
])
def test_only_a_run_that_did_its_work_or_is_still_at_it_holds_its_key(repo, status, holds_the_key):
    inst = repo.create_instance(FIRM, "t-1", "client_created", {}, idempotency_key="k-1")
    repo.update_instance_status(FIRM, inst["id"], status)
    found = repo.check_idempotency(FIRM, "t-1", "client_created", "k-1")
    assert (found is not None) is holds_the_key


def test_a_failed_run_can_be_started_again_with_the_same_data(client, repo, monkeypatch):
    from repositories import client_repository
    tpl = make_template(client, [task_step("needs a real client")])

    monkeypatch.setattr(client_repository.client_repo, "find_by_id", lambda cid, fid=None: None)
    first = press(client, tpl)
    assert first["instances"][0]["status"] == "failed"
    assert task_titles() == []

    monkeypatch.setattr(client_repository.client_repo, "find_by_id",
                        lambda cid, fid=None: {"id": cid, "firm_id": FIRM})
    again = press(client, tpl)
    assert again["instances_started"] == 1, "the failed run blocked its own retry"
    assert again["instances"][0]["status"] == "completed"
    assert task_titles() == ["needs a real client"]
    statuses = sorted(i["status"] for i in repo.list_instances(FIRM, template_id=tpl["id"]))
    assert statuses == ["completed", "failed"]


def test_a_cancelled_run_can_be_started_again_but_one_waiting_on_a_person_cannot(client, repo):
    tpl = make_template(client, [approval_step()])
    first = press(client, tpl)["instances"][0]
    assert first["status"] == "waiting_approval"

    duplicate = press(client, tpl)
    assert duplicate["instances_started"] == 0
    assert duplicate["instances"][0]["status"] == "duplicate_skipped"

    r = client.post(f"/api/workflows/instances/{first['instance_id']}/cancel")
    assert r.status_code == 200, r.text
    again = press(client, tpl)
    assert again["instances_started"] == 1
    assert again["instances"][0]["status"] == "waiting_approval"
    assert len(repo.list_instances(FIRM, template_id=tpl["id"])) == 2


def test_the_loser_of_a_race_to_a_unique_key_is_a_duplicate_not_an_error(client, repo, monkeypatch):
    """With a unique index on the key, two simultaneous starts both pass the
    check and the database refuses the second with 23505. That is the first
    run having won."""
    tpl = make_template(client, [task_step("raced")])
    winner = repo.create_instance(FIRM, tpl["id"], "client_created", {}, client_id="c-1",
                                  idempotency_key="the-winners-key")

    class UniqueViolation(Exception):
        code = "23505"

    asked = []

    def check(firm_id, template_id, event, key):
        # Not there when the loser first looks, there once the winner has committed.
        asked.append(key)
        return None if len(asked) == 1 else winner

    def refuse(**_kw):
        raise UniqueViolation("duplicate key value violates unique constraint")

    monkeypatch.setattr(repo, "check_idempotency", check)
    monkeypatch.setattr(repo, "create_instance", refuse)
    answer = press(client, tpl, client_id="c-1")

    assert answer["instances_started"] == 0
    assert answer["instances"][0]["status"] == "duplicate_skipped"
    assert answer["instances"][0]["instance_id"] == winner["id"]
    assert len(asked) == 2


def test_any_other_database_refusal_on_starting_a_run_is_still_an_error(client, repo, monkeypatch):
    tpl = make_template(client, [task_step("x")])

    class Refused(Exception):
        code = "42501"

    def refuse(**_kw):
        raise Refused("permission denied")

    monkeypatch.setattr(repo, "create_instance", refuse)
    r = client.post(f"/api/workflows/templates/{tpl['id']}/trigger", json={"client_id": "c-1"})
    assert r.status_code == 500, "a refusal that is not a lost race was swallowed as a duplicate"


# ══════════════════════════════════════════════════════════════════════════════
# 4. A run waiting on a person finishes when the person answers
# ══════════════════════════════════════════════════════════════════════════════

def test_an_approval_that_is_the_last_step_completes_the_run_when_approved(client, repo):
    tpl = make_template(client, [approval_step()])
    run = press(client, tpl)["instances"][0]
    assert run["status"] == "waiting_approval"
    approval = pending_approval(client, run["instance_id"])

    approve(client, approval["id"])

    assert repo.get_instance(FIRM, run["instance_id"])["status"] == "completed"
    assert repo.list_approvals(FIRM, status="pending") == [], \
        "approving created another approval for the same step"
    assert len(repo.list_approvals(FIRM)) == 1


def test_the_steps_after_an_approval_are_logged_and_the_run_remembers_what_came_before(client, repo):
    tpl = make_template(client, [task_step("before"), approval_step("sign"), task_step("after")])
    run = press(client, tpl)["instances"][0]
    iid = run["instance_id"]
    approval_step_id = tpl["steps"][1]["id"]

    waiting = repo.get_instance(FIRM, iid)
    assert waiting["status"] == "waiting_approval"
    assert waiting["current_step_id"] == approval_step_id, "a waiting run is AT its approval step"
    from repositories.task_repository import MOCK_TASKS
    before_id = next(t["id"] for t in MOCK_TASKS if t["title"] == "before")
    assert waiting["context_data"]["task_id"] == before_id, \
        "what the steps before the approval made was not kept"

    approve(client, pending_approval(client, iid)["id"])

    done = repo.get_instance(FIRM, iid)
    assert done["status"] == "completed"
    assert task_titles().count("after") == 1
    logs = repo.list_action_logs(iid)
    assert [(l["step_name"], l["status"]) for l in logs] == [
        ("before", "success"), ("sign", "success"), ("after", "success")], \
        "the steps after an approval left no action log, or the approval step is still 'paused'"
    assert done["current_step_id"] == tpl["steps"][2]["id"]
    assert done["context_data"]["task_id"] != before_id, "the final step's result is in the context"


def test_two_approvals_in_a_row_are_answered_one_after_the_other(client, repo):
    tpl = make_template(client, [approval_step("first"), approval_step("second"), task_step("done")])
    iid = press(client, tpl)["instances"][0]["instance_id"]

    approve(client, pending_approval(client, iid)["id"])
    mid = repo.get_instance(FIRM, iid)
    assert mid["status"] == "waiting_approval"
    assert mid["current_step_id"] == tpl["steps"][1]["id"]
    assert task_titles() == []

    approve(client, pending_approval(client, iid)["id"])
    assert repo.get_instance(FIRM, iid)["status"] == "completed"
    assert task_titles() == ["done"]
    assert [l["status"] for l in repo.list_action_logs(iid)] == ["success", "success", "success"]


def test_a_rejected_approval_cancels_the_run_and_runs_nothing_after_it(client, repo):
    tpl = make_template(client, [approval_step(), task_step("never")])
    iid = press(client, tpl)["instances"][0]["instance_id"]
    approve(client, pending_approval(client, iid)["id"], decision="rejected")
    assert repo.get_instance(FIRM, iid)["status"] == "cancelled"
    assert task_titles() == []


def test_a_run_may_not_come_back_to_a_step_it_ran_before_the_approval(client, repo, engine):
    """The loop remembers what the run has done across the pause. A cycle through
    an approval used to start the visited set again from nothing, so it would
    ask for an approval for ever."""
    tpl = repo.create_template(FIRM, {"name": "Loop", "category": "general",
                                       "trigger_type": "client_created", "trigger_config": {},
                                       "is_active": True})
    start = repo._create_step(tpl["id"], dict(task_step("start"), step_order=0))
    gate = repo._create_step(tpl["id"], dict(approval_step(), step_order=1, next_step_id=start["id"]))
    repo._update_step(start["id"], {"next_step_id": gate["id"]})

    instance = repo.create_instance(FIRM, tpl["id"], "client_created", {}, client_id="c-1")
    engine._execute_steps(tpl, instance, {"client_id": "c-1"}, FIRM)
    assert repo.get_instance(FIRM, instance["id"])["status"] == "waiting_approval"

    engine.resume_after_approval(FIRM, instance["id"], approved=True, user_id="u1")

    after = repo.get_instance(FIRM, instance["id"])
    assert after["status"] == "failed"
    assert "cycle" in (after["error_message"] or "").lower()
    assert task_titles() == ["start"], "the first step ran a second time"


def _forget_which_step_paused(repo, iid):
    """A run whose log no longer says which step is waiting (a seeded or imported
    one), so the resume has to be told or fall back."""
    for log in repo.list_action_logs(iid):
        if log["status"] == "paused":
            log["status"] = "success"


def test_a_run_paused_by_the_older_code_is_resumed_at_the_step_it_recorded(client, repo, engine):
    """Before this change a paused run's current_step_id held the step AFTER the
    approval. With nothing else to go on, that is the step to resume at, and not
    the approval."""
    tpl = make_template(client, [approval_step(), task_step("after")])
    iid = press(client, tpl)["instances"][0]["instance_id"]
    _forget_which_step_paused(repo, iid)
    repo.update_instance_status(FIRM, iid, "waiting_approval", current_step_id=tpl["steps"][1]["id"])

    engine.resume_after_approval(FIRM, iid, approved=True, user_id="u1")

    assert repo.get_instance(FIRM, iid)["status"] == "completed"
    assert task_titles() == ["after"]


def test_the_router_hands_the_answered_approvals_step_to_the_resume(client, repo):
    """With no paused log, the approval that was answered names its own step, so
    the run goes on past it rather than asking for it again."""
    tpl = make_template(client, [approval_step(), task_step("after")])
    iid = press(client, tpl)["instances"][0]["instance_id"]
    _forget_which_step_paused(repo, iid)

    approve(client, pending_approval(client, iid)["id"])

    assert repo.get_instance(FIRM, iid)["status"] == "completed"
    assert task_titles() == ["after"]
    assert repo.list_approvals(FIRM, status="pending") == []


# ══════════════════════════════════════════════════════════════════════════════
# 5. A refusal says why, in a 409
# ══════════════════════════════════════════════════════════════════════════════

def test_a_template_that_has_run_cannot_be_deleted_and_the_answer_says_why(client):
    tpl = make_template(client, [task_step("x")])
    press(client, tpl, client_id="c-1")
    press(client, tpl, client_id="c-2")

    r = client.delete(f"/api/workflows/templates/{tpl['id']}")

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "2 runs" in detail and "history" in detail and "Pause it" in detail
    assert client.get(f"/api/workflows/templates/{tpl['id']}").status_code == 200


def test_the_sentence_counts_one_run_in_the_singular(client):
    tpl = make_template(client, [task_step("x")])
    press(client, tpl)
    assert "1 run on record" in client.delete(f"/api/workflows/templates/{tpl['id']}").json()["detail"]


def test_a_template_that_never_ran_is_deleted_as_before(client):
    tpl = make_template(client, [task_step("x")])
    r = client.delete(f"/api/workflows/templates/{tpl['id']}")
    assert r.status_code == 200, r.text
    assert client.get(f"/api/workflows/templates/{tpl['id']}").status_code == 404
    assert client.delete(f"/api/workflows/templates/{tpl['id']}").status_code == 404


def test_the_database_refusing_the_delete_over_a_run_is_the_same_409(client, repo, monkeypatch):
    """A run that starts between the count and the delete: the foreign key says
    23503 and the caller still gets the sentence, not a 500."""
    tpl = make_template(client, [task_step("x")])

    class ForeignKey(Exception):
        code = "23503"

    def refuse(firm_id, template_id):
        raise ForeignKey("update or delete on table violates foreign key constraint")

    monkeypatch.setattr(repo, "delete_template", refuse)
    r = client.delete(f"/api/workflows/templates/{tpl['id']}")
    assert r.status_code == 409, r.text
    assert "history" in r.json()["detail"]


def test_a_template_that_fails_to_delete_for_any_other_reason_is_still_an_error(client, repo, monkeypatch):
    tpl = make_template(client, [task_step("x")])

    class Other(Exception):
        code = "42501"

    def refuse(firm_id, template_id):
        raise Other("denied")

    monkeypatch.setattr(repo, "delete_template", refuse)
    r = client.delete(f"/api/workflows/templates/{tpl['id']}")
    assert r.status_code == 500, "only the foreign-key refusal is a 409"


@pytest.mark.parametrize("status", ["waiting_approval", "pending", "running"])
def test_steps_cannot_be_replaced_under_a_run_that_is_not_finished(client, repo, status):
    tpl = make_template(client, [approval_step()])
    iid = press(client, tpl)["instances"][0]["instance_id"]
    repo.update_instance_status(FIRM, iid, status)

    r = client.patch(f"/api/workflows/templates/{tpl['id']}", json={"steps": [task_step("new")]})

    assert r.status_code == 409, r.text
    assert "1 run still in progress" in r.json()["detail"]
    assert [s["name"] for s in client.get(f"/api/workflows/templates/{tpl['id']}").json()["data"]["steps"]] \
        == ["Partner sign-off"], "the steps were replaced despite the refusal"


def test_everything_but_the_steps_can_change_under_a_run_in_progress(client):
    tpl = make_template(client, [approval_step()])
    press(client, tpl)
    r = client.patch(f"/api/workflows/templates/{tpl['id']}", json={"name": "Renamed", "is_active": False})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/workflows/templates/{tpl['id']}/toggle").status_code == 200


def test_steps_can_be_replaced_once_the_runs_have_finished_or_been_cancelled(client):
    tpl = make_template(client, [approval_step()])
    iid = press(client, tpl)["instances"][0]["instance_id"]
    assert client.patch(f"/api/workflows/templates/{tpl['id']}",
                        json={"steps": [task_step("new")]}).status_code == 409
    assert client.post(f"/api/workflows/instances/{iid}/cancel").status_code == 200
    r = client.patch(f"/api/workflows/templates/{tpl['id']}", json={"steps": [task_step("new")]})
    assert r.status_code == 200, r.text
    assert [s["name"] for s in r.json()["data"]["steps"]] == ["new"]


def test_a_missing_template_is_a_404_for_every_one_of_these(client):
    assert client.patch("/api/workflows/templates/nope", json={"steps": [task_step("x")]}).status_code == 404
    assert client.delete("/api/workflows/templates/nope").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 6. A save is all of its steps or none (the database branch, against a recorder)
# ══════════════════════════════════════════════════════════════════════════════

class _Result:
    def __init__(self, data=None, count=None):
        self.data, self.count = data, count


class _Chain:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.payload, self.filters = "select", None, []

    @property
    def not_(self):
        self.negate = True
        return self

    negate = False

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("not_in" if self.negate else "in", column, list(values)))
        self.negate = False
        return self

    def limit(self, _n):
        return self

    def execute(self):
        return self.db.run(self)


class _Db:
    """Records every statement; fails the ones `fail` selects."""

    def __init__(self, fail=lambda chain: False, rows=None, count=0):
        self.calls, self.fail, self.rows, self.count = [], fail, rows or [], count

    def table(self, name):
        return _Chain(self, name)

    def run(self, chain):
        self.calls.append(chain)
        if self.fail(chain):
            raise RuntimeError("the database said no")
        if chain.op == "insert":
            rows = chain.payload if isinstance(chain.payload, list) else [chain.payload]
            return _Result([dict(r) for r in rows])
        return _Result(list(self.rows), self.count)


@pytest.fixture
def database(monkeypatch):
    """The repository's non-mock branch, pointed at a recorder."""
    from repositories import workflow_repository as wr

    def use(db):
        monkeypatch.setattr(wr, "_USE_MOCK", False)
        monkeypatch.setattr(wr, "_get_db", lambda: db)
        return db
    return use


def writes(db, table, op):
    return [c for c in db.calls if c.table == table and c.op == op]


def test_all_of_a_templates_steps_go_in_as_one_statement(repo, database):
    db = database(_Db())
    template = repo.create_template(FIRM, {
        "name": "T", "category": "general", "trigger_type": "client_created", "trigger_config": {},
        "steps": [task_step("a"), task_step("b"), task_step("c")]})

    [insert] = writes(db, "workflow_steps", "insert")
    assert isinstance(insert.payload, list) and len(insert.payload) == 3
    assert [r["step_order"] for r in insert.payload] == [0, 1, 2]
    assert insert.payload[0]["next_step_id"] == insert.payload[1]["id"]
    assert insert.payload[1]["next_step_id"] == insert.payload[2]["id"]
    assert insert.payload[2]["next_step_id"] is None
    assert all(r["template_id"] == template["id"] for r in insert.payload)
    assert [s["name"] for s in template["steps"]] == ["a", "b", "c"]


def test_the_bulk_insert_supplies_every_column_workflow_steps_requires(repo, database):
    schema = json.loads((API / "tests/fixtures/production_schema_2026-09-03.json").read_text())["workflow_steps"]
    db = database(_Db())
    repo.create_template(FIRM, {"name": "T", "category": "general", "trigger_type": "client_created",
                                "trigger_config": {}, "steps": [task_step("a")]})
    [row] = writes(db, "workflow_steps", "insert")[0].payload
    required = {c for c, d in schema.items() if d["nullable"] == "NO" and not d["default"]}
    assert required <= set(row), sorted(required - set(row))
    assert set(row) <= set(schema), sorted(set(row) - set(schema))


def test_a_template_whose_steps_fail_to_save_is_taken_back_out(repo, database):
    db = database(_Db(fail=lambda c: c.table == "workflow_steps" and c.op == "insert"))
    with pytest.raises(RuntimeError):
        repo.create_template(FIRM, {"name": "T", "category": "general", "trigger_type": "client_created",
                                    "trigger_config": {}, "steps": [task_step("a"), task_step("b")]})
    [removed] = writes(db, "workflow_templates", "delete")
    assert ("eq", "firm_id", FIRM) in removed.filters
    assert len(writes(db, "workflow_templates", "insert")) == 1


def test_a_template_with_no_steps_makes_no_step_statement_at_all(repo, database):
    db = database(_Db())
    repo.create_template(FIRM, {"name": "T", "category": "general", "trigger_type": "client_created",
                                "trigger_config": {}, "steps": []})
    assert writes(db, "workflow_steps", "insert") == []


def test_replacing_steps_stores_the_new_set_before_removing_the_old(repo, database):
    db = database(_Db())
    repo._replace_steps("t-1", [task_step("n1"), task_step("n2")],
                        replacing=[{"id": "old-1"}, {"id": "old-2"}])

    kinds = [(c.table, c.op) for c in db.calls]
    assert kinds == [("workflow_steps", "insert"), ("workflow_steps", "delete")]
    [(_, _, old)] = [f for f in db.calls[1].filters if f[0] == "in"]
    assert old == ["old-1", "old-2"]
    assert ("eq", "template_id", "t-1") in db.calls[1].filters


def test_a_failed_insert_leaves_the_old_steps_alone(repo, database):
    db = database(_Db(fail=lambda c: c.op == "insert"))
    with pytest.raises(RuntimeError):
        repo._replace_steps("t-1", [task_step("n1")], replacing=[{"id": "old-1"}])
    assert writes(db, "workflow_steps", "delete") == [], "the old steps were removed anyway"


def test_a_failed_removal_of_the_old_steps_takes_the_new_ones_back_out(repo, database):
    seen = {"deletes": 0}

    def fail_first_delete(chain):
        if chain.op == "delete":
            seen["deletes"] += 1
            return seen["deletes"] == 1
        return False

    db = database(_Db(fail=fail_first_delete))
    with pytest.raises(RuntimeError):
        repo._replace_steps("t-1", [task_step("n1"), task_step("n2")], replacing=[{"id": "old-1"}])

    inserted = [r["id"] for r in writes(db, "workflow_steps", "insert")[0].payload]
    taken_back = writes(db, "workflow_steps", "delete")[1]
    [(_, _, ids)] = [f for f in taken_back.filters if f[0] == "in"]
    assert ids == inserted


def test_the_idempotency_check_asks_for_one_row_and_leaves_out_runs_that_did_not_run(repo, database):
    """It used to be maybe_single(), which raises when two rows share a key (a
    failed run and its retry). The recorder has no maybe_single, so a return to
    it fails here."""
    db = database(_Db(rows=[{"id": "i-1", "status": "completed"}]))
    found = repo.check_idempotency(FIRM, "t-1", "client_created", "k")
    assert found == {"id": "i-1", "status": "completed"}
    [query] = db.calls
    assert ("not_in", "status", ["failed", "cancelled"]) in query.filters
    assert ("eq", "firm_id", FIRM) in query.filters


def test_no_run_holding_the_key_is_none_in_the_database_branch_too(repo, database):
    database(_Db(rows=[]))
    assert repo.check_idempotency(FIRM, "t-1", "client_created", "k") is None


def test_counting_a_templates_runs_is_a_count_filtered_by_firm_and_status(repo, database):
    db = database(_Db(count=7))
    assert repo.count_instances(FIRM, "t-1", ("running", "pending")) == 7
    [query] = db.calls
    assert ("eq", "firm_id", FIRM) in query.filters
    assert ("eq", "template_id", "t-1") in query.filters
    assert ("in", "status", ["running", "pending"]) in query.filters
    assert repo.count_instances(FIRM, "t-1") == 7
    assert not [f for f in db.calls[1].filters if f[1] == "status"]
