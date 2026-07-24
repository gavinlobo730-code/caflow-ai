"""
Task #234 — audit-pass-3 cross-tenant isolation gaps (round 3): AI Copilot
client intelligence, engagement letters, /api/timeline, task-extras
(tags/dependencies/timeline), time-tracking.

Same root cause as tasks #230/#231: a caller-supplied client_id/task_id/
entry_id used in a read or write path without checking it belongs to the
caller's own firm. Fixed by wiring core.authz.assert_client_access (for
client_id-scoped endpoints) or an explicit firm_id-scoped repository lookup
(for task_id/entry_id-scoped endpoints, mirroring tasks.py's own
update_task pattern).
"""
import asyncio

import pytest
from fastapi import HTTPException

import core.authz as authz
import routers.ai_copilot_v2 as copilot_router
import routers.engagement_letters as engagement_router
import routers.timeline as timeline_router
import routers.task_extras as task_extras_router
import routers.time_tracking as time_tracking_router
from routers.engagement_letters import EngagementIn
from routers.task_extras import AddTagBody, AddDependencyBody
from routers.time_tracking import EntryUpdate
from tests.e2e_harness import FakeDB

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p1", "id": "u1", "email": "p1@f1.test"}


@pytest.fixture
def enforced(monkeypatch):
    """Force the real (non-mock) client-ownership enforcement path. C1
    belongs to F1 (every fixture user's firm); C-OTHER belongs to F2."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_belongs(client_id, firm_id):
        if client_id == "C-OTHER":
            return firm_id == "F2"
        return firm_id == "F1"
    monkeypatch.setattr(authz, "_client_belongs_to_firm", fake_belongs)
    yield


# ── AI Copilot client intelligence ───────────────────────────────────────────

def test_client_intelligence_rejects_another_firms_client(enforced):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(copilot_router.client_intelligence("C-OTHER", PARTNER_F1))
    assert ei.value.status_code == 404


def test_client_intelligence_accepts_own_firms_client(enforced, monkeypatch):
    async def fake_get_client_intelligence(firm_id, client_id):
        return {"client_id": client_id, "firm_id": firm_id}
    monkeypatch.setattr(
        copilot_router._service(), "get_client_intelligence", fake_get_client_intelligence
    )
    result = asyncio.run(copilot_router.client_intelligence("C1", PARTNER_F1))
    assert result["success"] is True
    assert result["data"]["client_id"] == "C1"


# ── Engagement letters ────────────────────────────────────────────────────────

def test_create_engagement_rejects_another_firms_client(enforced):
    body = EngagementIn(title="Sneaky Engagement", client_id="C-OTHER")
    with pytest.raises(HTTPException) as ei:
        engagement_router.create_engagement(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_engagement_accepts_own_firms_client(enforced):
    body = EngagementIn(title="Legit Engagement", client_id="C1")
    result = engagement_router.create_engagement(body, PARTNER_F1)
    assert result["success"] is True
    assert result["data"]["engagement"]["client_id"] == "C1"


def test_create_engagement_rejects_foreign_lead(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(engagement_router, "_db", lambda: db)
    db.seed("leads", {"id": "lead-foreign", "firm_id": "F2"})
    body = EngagementIn(title="Sneaky Lead Engagement", lead_id="lead-foreign")
    with pytest.raises(HTTPException) as ei:
        engagement_router.create_engagement(body, PARTNER_F1)
    assert ei.value.status_code == 404
    assert db.rows("engagements") == []


def test_create_engagement_accepts_owned_lead(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(engagement_router, "_db", lambda: db)
    db.seed("leads", {"id": "lead-owned", "firm_id": "F1"})
    body = EngagementIn(title="Legit Lead Engagement", lead_id="lead-owned")
    result = engagement_router.create_engagement(body, PARTNER_F1)
    assert result["success"] is True
    assert len(db.rows("engagements")) == 1


def test_generate_engagement_does_not_leak_foreign_client_pan(monkeypatch):
    """Defense-in-depth: even if a stale cross-firm client_id/lead_id somehow
    existed on an engagement row already, /generate must not render another
    firm's PAN/GSTIN/name into the letter content."""
    db = FakeDB()
    monkeypatch.setattr(engagement_router, "_db", lambda: db)
    eng = db.seed("engagements", {
        "firm_id": "F1", "client_id": "client-foreign", "status": "Draft",
        "content": "Dear {{client_name}} (PAN {{client_pan}}, GSTIN {{client_gstin}}).",
        "fee_amount_paise": 0, "recipient_name": None,
    })
    db.seed("clients", {
        "id": "client-foreign", "firm_id": "F2",
        "client_name": "Firm B Secret Client", "pan": "SECRT1234P", "gstin": "27SECRT1234P1Z5",
    })
    result = engagement_router.generate_engagement(eng["id"], PARTNER_F1)
    rendered = result["data"]["rendered_content"]
    assert "Firm B Secret Client" not in rendered
    assert "SECRT1234P" not in rendered


# ── /api/timeline ──────────────────────────────────────────────────────────────

def test_list_timeline_events_rejects_another_firms_client(enforced, monkeypatch):
    monkeypatch.setattr(timeline_router, "_USE_MOCK", False)
    with pytest.raises(HTTPException) as ei:
        timeline_router.list_timeline_events(client_id="C-OTHER", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_list_timeline_events_scopes_by_firm_even_when_client_owned(enforced, monkeypatch):
    """Even with client ownership confirmed, the events query itself must
    still filter by firm_id -- proves the added .eq("firm_id", ...) is wired,
    not just the assert_client_access guard."""
    db = FakeDB()
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(timeline_router, "_USE_MOCK", False)
    db.seed("client_timeline_events", {"client_id": "C1", "firm_id": "F1", "category": "compliance"})
    db.seed("client_timeline_events", {"client_id": "C1", "firm_id": "F2", "category": "compliance"})
    result = timeline_router.list_timeline_events(
        client_id="C1", category=None, severity=None, financial_year=None,
        limit=50, offset=0, current_user=PARTNER_F1,
    )
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["firm_id"] == "F1"


# ── Task extras (tags / dependencies / timeline) ─────────────────────────────

def _seed_task(db, task_id, firm_id):
    return db.seed("tasks", {"id": task_id, "firm_id": firm_id, "title": "t"})


def test_get_tags_rejects_another_firms_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    _seed_task(db, "task-foreign", "F2")
    with pytest.raises(HTTPException) as ei:
        task_extras_router.get_tags("task-foreign", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_add_tag_rejects_another_firms_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    import repositories.task_extras_repository as extras_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(extras_repo_module, "_get_db", lambda: db)
    _seed_task(db, "task-foreign", "F2")
    with pytest.raises(HTTPException) as ei:
        task_extras_router.add_tag("task-foreign", AddTagBody(tag="urgent"), current_user=PARTNER_F1)
    assert ei.value.status_code == 404
    assert db.rows("task_tags") == []


def test_add_tag_accepts_own_firms_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    import repositories.task_extras_repository as extras_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(extras_repo_module, "_get_db", lambda: db)
    _seed_task(db, "task-owned", "F1")
    result = task_extras_router.add_tag("task-owned", AddTagBody(tag="urgent"), current_user=PARTNER_F1)
    assert result["success"] is True
    assert len(db.rows("task_tags")) == 1


def test_add_dependency_rejects_foreign_dependency_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    import repositories.task_extras_repository as extras_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    monkeypatch.setattr(extras_repo_module, "_get_db", lambda: db)
    _seed_task(db, "task-owned", "F1")
    _seed_task(db, "task-foreign", "F2")
    body = AddDependencyBody(depends_on_task_id="task-foreign")
    with pytest.raises(HTTPException) as ei:
        task_extras_router.add_dependency("task-owned", body, current_user=PARTNER_F1)
    assert ei.value.status_code == 404
    assert db.rows("task_dependencies") == []


def test_remove_tag_rejects_another_firms_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    _seed_task(db, "task-foreign", "F2")
    with pytest.raises(HTTPException) as ei:
        task_extras_router.remove_tag("task-foreign", "urgent", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_remove_dependency_rejects_another_firms_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    _seed_task(db, "task-foreign", "F2")
    with pytest.raises(HTTPException) as ei:
        task_extras_router.remove_dependency("task-foreign", "dep-1", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_get_task_timeline_rejects_another_firms_task(monkeypatch):
    db = FakeDB()
    import repositories.task_repository as task_repo_module
    monkeypatch.setattr(task_repo_module, "_get_db", lambda: db)
    monkeypatch.setattr(task_repo_module, "_USE_MOCK", False)
    _seed_task(db, "task-foreign", "F2")
    with pytest.raises(HTTPException) as ei:
        task_extras_router.get_timeline("task-foreign", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


# ── Time tracking ──────────────────────────────────────────────────────────────

def _wire_time_tracking_db(monkeypatch, db):
    import repositories.time_tracking_repository as tt_repo_module
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: db)


def test_stop_timer_rejects_another_firms_entry(monkeypatch):
    db = FakeDB()
    _wire_time_tracking_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": "F2", "user_id": "u2", "started_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(HTTPException) as ei:
        time_tracking_router.stop_timer(entry["id"], current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_update_entry_rejects_another_firms_entry(monkeypatch):
    db = FakeDB()
    _wire_time_tracking_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": "F2", "user_id": "u2", "started_at": "2026-01-01T00:00:00Z", "hourly_rate_paise": 100000})
    with pytest.raises(HTTPException) as ei:
        time_tracking_router.update_entry(entry["id"], EntryUpdate(hourly_rate_paise=999999999), current_user=PARTNER_F1)
    assert ei.value.status_code == 404
    # Confirm the foreign entry's rate was never touched.
    assert db.rows("time_entries")[0]["hourly_rate_paise"] == 100000


def test_delete_entry_rejects_another_firms_entry(monkeypatch):
    db = FakeDB()
    _wire_time_tracking_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": "F2", "user_id": "u2", "started_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(HTTPException) as ei:
        time_tracking_router.delete_entry(entry["id"], current_user=PARTNER_F1)
    assert ei.value.status_code == 404
    assert len(db.rows("time_entries")) == 1


def test_stop_timer_accepts_own_firms_entry(monkeypatch):
    db = FakeDB()
    _wire_time_tracking_db(monkeypatch, db)
    entry = db.seed("time_entries", {"firm_id": "F1", "user_id": "u1", "started_at": "2026-01-01T00:00:00Z"})
    result = time_tracking_router.stop_timer(entry["id"], current_user=PARTNER_F1)
    assert result["success"] is True
    assert result["data"]["entry"]["ended_at"] is not None
