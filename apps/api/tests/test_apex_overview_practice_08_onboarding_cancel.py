"""
apex-overview-practice-08 (sweep-client-misc-03's remaining work): the
lifecycle onboarding workflow had GET (list), POST (create) and PATCH on an
individual TASK, and no way to remove an unwanted workflow once created — a
duplicate-click already got its own confirm-dialog fix, but there was still
no cleanup path, and nothing stopped two DELIBERATE "New Onboarding" clicks
from giving one client two workflows in progress at once.

`PATCH /api/lifecycle/onboarding/{workflow_id}/status` (this file's subject)
soft-cancels a workflow, mirroring this router's own convention for a status
change — `update_proposal_status` / `update_renewal_status` both PATCH a
`.../status` sub-route rather than DELETE a row — and `onboarding_workflows.
status` has carried 'cancelled' in its own CHECK constraint since migration
059 with nothing ever having written it.

`create_onboarding` also gained a server-side guard: creating a SECOND
workflow for a client that already has one `in_progress` is refused (409)
rather than only warned about client-side.
"""
import pytest
from fastapi import HTTPException

import routers.lifecycle as lc

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "Partner"}


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    # can_access_client() is unconditionally permissive under _USE_MOCK
    # (core/authz.py), so no assignment fixture is needed here — only that
    # this router's own `_db()` returns None (mock mode).
    monkeypatch.setattr(lc, "_db", lambda: None)
    monkeypatch.setattr(lc, "_MOCK_ONBOARDING_WORKFLOWS", [])
    monkeypatch.setattr(lc, "_MOCK_ONBOARDING_TASKS", [])
    monkeypatch.setattr(lc.timeline_service, "log", lambda *a, **k: None)


def _create() -> dict:
    return lc.create_onboarding(lc.OnboardingIn(client_id=CLIENT), current_user=USER)["data"]


# ── Create ───────────────────────────────────────────────────────────────────

def test_create_starts_an_in_progress_workflow_with_the_default_tasks():
    wf = _create()
    assert wf["status"] == "in_progress"
    assert wf["client_id"] == CLIENT
    assert len(wf["tasks"]) == len(lc._DEFAULT_ONBOARDING_TASKS)


# ── The duplicate-workflow guard ─────────────────────────────────────────────

def test_a_second_workflow_is_refused_while_the_first_is_in_progress():
    _create()
    with pytest.raises(HTTPException) as ei:
        _create()
    assert ei.value.status_code == 409
    assert "already has an onboarding workflow in progress" in ei.value.detail
    # And nothing was actually created — still exactly one workflow.
    assert len(lc._MOCK_ONBOARDING_WORKFLOWS) == 1


def test_a_second_workflow_is_allowed_once_the_first_is_cancelled():
    wf = _create()
    lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="cancelled"), current_user=USER)
    wf2 = _create()
    assert wf2["status"] == "in_progress"
    assert wf2["id"] != wf["id"]
    assert len(lc._MOCK_ONBOARDING_WORKFLOWS) == 2


def test_a_second_workflow_for_a_different_client_is_never_blocked():
    _create()
    other = lc.create_onboarding(lc.OnboardingIn(client_id="client-2"), current_user=USER)["data"]
    assert other["status"] == "in_progress"


# ── Cancel ───────────────────────────────────────────────────────────────────

def test_cancel_soft_cancels_the_workflow():
    wf = _create()
    out = lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="cancelled"), current_user=USER)
    assert out["data"]["status"] == "cancelled"
    # And the row itself was updated, not just the response echoed back.
    stored = next(w for w in lc._MOCK_ONBOARDING_WORKFLOWS if w["id"] == wf["id"])
    assert stored["status"] == "cancelled"


def test_cancel_is_not_a_hard_delete():
    wf = _create()
    lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="cancelled"), current_user=USER)
    assert any(w["id"] == wf["id"] for w in lc._MOCK_ONBOARDING_WORKFLOWS), (
        "the row is gone — this must be a soft cancel (status change), never "
        "a hard delete")


def test_cancelling_an_already_cancelled_workflow_is_refused():
    wf = _create()
    lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="cancelled"), current_user=USER)
    with pytest.raises(HTTPException) as ei:
        lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="cancelled"), current_user=USER)
    assert ei.value.status_code == 409
    assert "already cancelled" in ei.value.detail


def test_a_status_other_than_cancelled_is_refused():
    wf = _create()
    with pytest.raises(HTTPException) as ei:
        lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="completed"), current_user=USER)
    assert ei.value.status_code == 422
    # And the workflow's own status is untouched by the refused request.
    stored = next(w for w in lc._MOCK_ONBOARDING_WORKFLOWS if w["id"] == wf["id"])
    assert stored["status"] == "in_progress"


def test_cancelling_a_workflow_that_does_not_exist_404s():
    with pytest.raises(HTTPException) as ei:
        lc.update_onboarding_status("no-such-workflow", lc.OnboardingStatusIn(status="cancelled"), current_user=USER)
    assert ei.value.status_code == 404


def test_cancelling_another_firms_workflow_404s():
    wf = _create()
    other_firm_user = {"id": "u2", "firm_id": "firm-2", "role": "Partner"}
    with pytest.raises(HTTPException) as ei:
        lc.update_onboarding_status(wf["id"], lc.OnboardingStatusIn(status="cancelled"), current_user=other_firm_user)
    assert ei.value.status_code == 404
    # And it really is untouched — a leaked existence check must not also be
    # a leaked write.
    stored = next(w for w in lc._MOCK_ONBOARDING_WORKFLOWS if w["id"] == wf["id"])
    assert stored["status"] == "in_progress"
