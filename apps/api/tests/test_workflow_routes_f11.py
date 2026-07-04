"""
R2.7 — F11/F12 route-level regression tests.

F11: the legacy Phase-2 workflows router's GET /{workflow_id} catch-all
shadowed every single-segment GET under /api/workflows — /templates,
/instances, /approvals, /schedules, /analytics, /failures, /executions all
404'd. The legacy router (three endpoints of hardcoded, never-persisted data
with zero frontend callers) was deleted; these tests pin every previously
shadowed route as reachable, end to end through the real FastAPI app.

F12: a trigger must produce a REAL task (task_repo row), skipped statuses for
unimplemented actions, and working schedule/approval/cancel write paths (the
four router→repo signature mismatches meant none of these had ever been
exercised end to end).
"""
import pytest
from fastapi.testclient import TestClient

_USER = {
    "auth_user_id": "u-partner", "id": "u-partner", "firm_id": "firm-1",
    "email": "partner@test.example", "role": "Partner",
}


@pytest.fixture
def client():
    # The REAL main.app — route registration ORDER is exactly what F11 is
    # about, so a per-router test app would prove nothing. Auth is overridden
    # the same way every other route-level suite does it.
    from main import app
    from core.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _client_belongs_to_firm(monkeypatch):
    """create_task's tenancy guard (R2.7 adversarial-review finding) needs
    client_repo.find_by_id(client_id, firm_id) to resolve — the demo
    MOCK_CLIENTS dataset doesn't model firm_id per client at all, so every
    lookup here would otherwise 404 regardless of the id passed. Stub it to
    accept any id under this suite's firm, matching how other route-level
    suites isolate this exact dependency."""
    from repositories import client_repository
    monkeypatch.setattr(
        client_repository.client_repo, "find_by_id",
        lambda cid, fid=None: {"id": cid, "firm_id": _USER["firm_id"]},
    )


@pytest.fixture(autouse=True)
def clear_workflow_state():
    """Isolate each test AND restore the import-time seeds afterwards — the
    mock stores are module globals shared across the whole pytest session
    (e.g. system templates seeded at import that other suites assert on)."""
    from repositories import workflow_repository as wr
    from repositories.task_repository import MOCK_TASKS, TASK_INDEX
    stores = (wr.MOCK_TEMPLATES, wr.MOCK_STEPS, wr.MOCK_INSTANCES,
              wr.MOCK_ACTION_LOGS, wr.MOCK_EXECUTIONS, wr.MOCK_FAILURES,
              wr.MOCK_APPROVALS, wr.MOCK_SCHEDULES, MOCK_TASKS)
    snapshots = [list(s) for s in stores]
    task_index_snapshot = dict(TASK_INDEX)
    for s in stores:
        s.clear()
    TASK_INDEX.clear()
    yield
    for s, snap in zip(stores, snapshots):
        s.clear()
        s.extend(snap)
    TASK_INDEX.clear()
    TASK_INDEX.update(task_index_snapshot)


_HEADERS: dict = {}  # auth comes from the dependency override


def _make_template(client, steps=None, name="E2E Template"):
    r = client.post("/api/workflows/templates", json={
        "name": name,
        "category": "compliance",
        "trigger_type": "client_created",
        "trigger_config": {},
        "conditions": {},
        "steps": steps or [],
    }, headers=_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── F11: previously shadowed list routes must all be reachable ────────────────

@pytest.mark.parametrize("path", [
    "/api/workflows/templates",
    "/api/workflows/instances",
    "/api/workflows/approvals",
    "/api/workflows/schedules",
    "/api/workflows/analytics",
    "/api/workflows/failures",
    "/api/workflows/executions",
])
def test_single_segment_get_routes_reachable(client, path):
    """Every one of these 404'd before R2.7 (legacy /{workflow_id} captured
    the path segment). 200 proves the shadow is gone."""
    r = client.get(path, headers=_HEADERS)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"


def test_legacy_fake_workflow_routes_are_gone(client):
    """The legacy router returned hardcoded template data at /{id} and
    fabricated (never-persisted) tasks at /{id}/instantiate — deleted."""
    r = client.get("/api/workflows/wf-tpl-001", headers=_HEADERS)
    assert r.status_code == 404
    r = client.post("/api/workflows/wf-tpl-001/instantiate",
                    json={"client_id": "c-001"}, headers=_HEADERS)
    assert r.status_code == 404


# ── F12: trigger → instance completes → REAL task exists ─────────────────────

def test_trigger_creates_real_task(client):
    tpl = _make_template(client, steps=[{
        "step_order": 1,
        "step_type": "action",
        "name": "Create filing task",
        "config": {"action_type": "create_task",
                   "params": {"title": "File GSTR-3B", "priority": "high"}},
    }])
    r = client.post(f"/api/workflows/templates/{tpl['id']}/trigger", json={
        "client_id": "c-001", "trigger_data": {"client_id": "c-001"},
    }, headers=_HEADERS)
    assert r.status_code == 200, r.text
    fired = r.json()["data"]
    assert fired["instances_started"] == 1, fired
    run = fired["instances"][0]
    assert run["status"] == "completed", run

    # The task must EXIST in the task store — not a fabricated id (F12).
    from repositories.task_repository import MOCK_TASKS
    matching = [t for t in MOCK_TASKS if t.get("title") == "File GSTR-3B"]
    assert len(matching) == 1
    assert matching[0]["client_id"] == "c-001"
    assert matching[0]["firm_id"] == "firm-1"

    # And the instance list endpoint must show the completed run.
    r = client.get("/api/workflows/instances", headers=_HEADERS)
    instances = r.json()["data"]["instances"]
    assert any(i["status"] == "completed" for i in instances)


def test_unimplemented_action_logs_skipped_not_success(client):
    tpl = _make_template(client, name="Email template", steps=[{
        "step_order": 1,
        "step_type": "action",
        "name": "Send email",
        "config": {"action_type": "send_email", "params": {"to": "a@b.example"}},
    }])
    r = client.post(f"/api/workflows/templates/{tpl['id']}/trigger", json={
        "client_id": "c-001", "trigger_data": {},
    }, headers=_HEADERS)
    assert r.status_code == 200, r.text

    from repositories.workflow_repository import MOCK_ACTION_LOGS
    email_logs = [l for l in MOCK_ACTION_LOGS if l.get("step_name") == "Send email"]
    assert email_logs, "action must be logged"
    assert email_logs[-1]["status"] == "skipped", email_logs[-1]


# ── F12: the four previously-broken write paths ───────────────────────────────

def test_schedule_create_and_toggle_roundtrip(client):
    """create_schedule passed the whole payload dict as template_id and
    toggle_schedule passed a phantom third argument — both TypeErrors before."""
    tpl = _make_template(client, name="Scheduled template")
    r = client.post("/api/workflows/schedules", json={
        "template_id": tpl["id"],
        "name": "Nightly run",
        "cron_expression": "0 2 * * *",
    }, headers=_HEADERS)
    assert r.status_code == 200, r.text
    schedule = r.json()["data"]
    assert schedule["cron_expression"] == "0 2 * * *"
    assert schedule["is_active"] is True

    r = client.patch(f"/api/workflows/schedules/{schedule['id']}/toggle", headers=_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_active"] is False


def test_instance_cancel(client):
    """update_instance_status was called without firm_id — TypeError before."""
    tpl = _make_template(client, name="Approval template", steps=[{
        "step_order": 1,
        "step_type": "approval",
        "name": "Partner sign-off",
        "config": {"approver_role": "Partner", "title": "Approve filing"},
    }])
    r = client.post(f"/api/workflows/templates/{tpl['id']}/trigger", json={
        "client_id": "c-001", "trigger_data": {},
    }, headers=_HEADERS)
    assert r.status_code == 200, r.text
    run = r.json()["data"]["instances"][0]
    assert run["status"] == "waiting_approval"

    instance_id = run["instance_id"]
    r = client.post(f"/api/workflows/instances/{instance_id}/cancel", headers=_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "cancelled"


def test_approval_respond_persists_notes_and_responder_correctly(client):
    """respond_approval swapped responder_id and response_notes before —
    the responder's uuid landed in the notes column and vice versa."""
    tpl = _make_template(client, name="Approval flow", steps=[{
        "step_order": 1,
        "step_type": "approval",
        "name": "Partner sign-off",
        "config": {"approver_role": "Partner", "title": "Approve filing"},
    }])
    r = client.post(f"/api/workflows/templates/{tpl['id']}/trigger", json={
        "client_id": "c-001", "trigger_data": {},
    }, headers=_HEADERS)
    assert r.status_code == 200

    r = client.get("/api/workflows/approvals", headers=_HEADERS)
    approvals = r.json()["data"]["approvals"]
    assert approvals, "a pending approval must exist"
    approval_id = approvals[0]["id"]

    r = client.post(f"/api/workflows/approvals/{approval_id}/respond", json={
        "decision": "approved", "response_notes": "Looks correct, proceed.",
    }, headers=_HEADERS)
    assert r.status_code == 200, r.text
    responded = r.json()["data"]
    assert responded["response_notes"] == "Looks correct, proceed."
    # The responder must be the identity, never the notes text.
    assert responded["responder_id"] != "Looks correct, proceed."
