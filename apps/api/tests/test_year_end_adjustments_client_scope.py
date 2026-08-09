"""
Client-assignment scope on the year-end adjustments router.

Every endpoint is addressed by engagement_id and resolves through
_assert_engagement_scope (writes pass require_unlocked=True, live mode) /
_guard_locked_mock (writes, mock mode) — both already checked the
engagement belonged to the caller's FIRM (and, live-only, that it wasn't
locked), but neither ever checked the engagement's client against the
caller's ASSIGNMENT. list_adjustments didn't even check the engagement at
all. rbac("year_end", "read"/"write") is _AT_LEAST_EXECUTIVE and "approve"
is _AT_LEAST_MANAGER — both assignment-scoped roles under M3, so this was a
live gap on every endpoint.

Mock-mode tests drive the real router functions against
routers.year_end_adjustments._MOCK_ADJUSTMENTS / routers.year_end.
_MOCK_ENGAGEMENTS directly. Live-mode tests use the shared e2e FakeDB
harness (tests.e2e_harness), since year_end_adjustments.py locally imports
core.supabase_client.get_supabase per call rather than through its own
_db()-style indirection.
"""
import pytest
from fastapi import HTTPException

import routers.year_end_adjustments as yea
from routers.year_end import _MOCK_ENGAGEMENTS
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(yea, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    yea._MOCK_ADJUSTMENTS.clear()
    _MOCK_ENGAGEMENTS.clear()
    yield
    yea._MOCK_ADJUSTMENTS.clear()
    _MOCK_ENGAGEMENTS.clear()


def _seed_mock_engagement(engagement_id, client_id, status="draft"):
    _MOCK_ENGAGEMENTS[engagement_id] = {
        "id": engagement_id, "firm_id": FIRM, "client_id": client_id, "status": status,
    }


def _seed_mock_adjustment(engagement_id, adjustment_id, status="draft"):
    adj = {
        "id": adjustment_id, "engagement_id": engagement_id, "firm_id": FIRM,
        "status": status, "amount_paise": 1000, "debit_account_id": "acc-d",
        "credit_account_id": "acc-c", "description": "test",
        "adjustment_date": "2026-03-31",
    }
    yea._MOCK_ADJUSTMENTS.setdefault(engagement_id, []).append(adj)
    return adj


def _create_body():
    return yea.AdjustmentCreateIn(
        adjustment_type="accrual", description="Accrued expense",
        amount_paise=50000, debit_account_id="acc-d", credit_account_id="acc-c",
        adjustment_date="2026-03-31",
    )


# ══════════════════════════════════════════════════════════════════════════════
# _assert_engagement_client_mock / _guard_locked_mock
# ══════════════════════════════════════════════════════════════════════════════

def test_mock_client_check_refuses_another_clients_engagement(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as e:
        yea._assert_engagement_client_mock(EXEC_USER, "ENG-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_mock_client_check_allows_your_own_engagement(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    yea._assert_engagement_client_mock(EXEC_USER, "ENG-MINE")
    assert deny == [MINE]


def test_mock_client_check_is_permissive_when_engagement_is_missing(deny):
    """Mock mode has no engagement store worth enforcing tenancy against —
    matches this codebase's established mock-mode convention."""
    yea._assert_engagement_client_mock(EXEC_USER, "ENG-NOPE")
    assert deny == []


def test_mock_guard_checks_client_before_locked_status(deny):
    """An unassigned caller must not learn the engagement is locked — the
    client check has to run first."""
    _seed_mock_engagement("ENG-THEIRS", THEIRS, status="locked")
    with pytest.raises(HTTPException) as e:
        yea._guard_locked_mock(EXEC_USER, "ENG-THEIRS")
    assert e.value.status_code == 404, "a locked engagement leaked a 403 to an unassigned caller"
    assert deny == [THEIRS]


def test_mock_guard_still_blocks_a_locked_engagement_for_an_assigned_caller(deny):
    _seed_mock_engagement("ENG-MINE", MINE, status="locked")
    with pytest.raises(HTTPException) as e:
        yea._guard_locked_mock(EXEC_USER, "ENG-MINE")
    assert e.value.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# _assert_engagement_scope — live mode (e2e FakeDB)
# ══════════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [yea])
    return db


def test_live_scope_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as e:
        yea._assert_engagement_scope(db, "ENG-THEIRS", EXEC_USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_live_scope_returns_your_own_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    row = yea._assert_engagement_scope(db, "ENG-MINE", EXEC_USER)
    assert row["id"] == "ENG-MINE"
    assert deny == [MINE]


def test_live_scope_refuses_another_firms_engagement_before_the_client_check(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-ALIEN", "firm_id": "firm-2",
                                     "client_id": "c-x", "status": "draft"})
    with pytest.raises(HTTPException) as e:
        yea._assert_engagement_scope(db, "ENG-ALIEN", EXEC_USER)
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_engagements_use_the_identical_message(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as missing:
        yea._assert_engagement_scope(db, "ENG-NOPE", EXEC_USER)
    with pytest.raises(HTTPException) as hidden:
        yea._assert_engagement_scope(db, "ENG-THEIRS", EXEC_USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Engagement not found"


def test_live_scope_with_require_unlocked_checks_client_before_locked_status(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "locked"})
    with pytest.raises(HTTPException) as e:
        yea._assert_engagement_scope(db, "ENG-THEIRS", EXEC_USER, require_unlocked=True)
    assert e.value.status_code == 404, "a locked engagement leaked a 403 to an unassigned caller"


def test_live_scope_without_require_unlocked_allows_a_locked_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "locked"})
    row = yea._assert_engagement_scope(db, "ENG-MINE", EXEC_USER)
    assert row["status"] == "locked"
    with pytest.raises(HTTPException) as e:
        yea._assert_engagement_scope(db, "ENG-MINE", EXEC_USER, require_unlocked=True)
    assert e.value.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Every endpoint, driven through mock mode for real
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_an_adjustment_on_another_clients_engagement_is_refused(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    with pytest.raises(HTTPException):
        yea.create_adjustment("ENG-THEIRS", _create_body(), current_user=EXEC_USER)
    assert yea._MOCK_ADJUSTMENTS.get("ENG-THEIRS", []) == []


def test_creating_an_adjustment_on_your_own_engagement_still_works(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    out = yea.create_adjustment("ENG-MINE", _create_body(), current_user=EXEC_USER)
    assert out["data"]["engagement_id"] == "ENG-MINE"


def test_listing_adjustments_on_another_clients_engagement_is_refused(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    _seed_mock_adjustment("ENG-THEIRS", "ADJ-1")
    with pytest.raises(HTTPException):
        yea.list_adjustments("ENG-THEIRS", current_user=EXEC_USER)


def test_listing_adjustments_on_your_own_engagement_still_works(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    _seed_mock_adjustment("ENG-MINE", "ADJ-1")
    out = yea.list_adjustments("ENG-MINE", current_user=EXEC_USER)
    assert [a["id"] for a in out["data"]] == ["ADJ-1"]


def test_listing_adjustments_live_mode_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    db.seed("year_end_adjustments", {"id": "ADJ-1", "engagement_id": "ENG-THEIRS",
                                     "firm_id": FIRM, "status": "draft"})
    with pytest.raises(HTTPException):
        yea.list_adjustments("ENG-THEIRS", current_user=EXEC_USER)


def test_listing_adjustments_live_mode_still_works_for_your_own_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "ENG-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    db.seed("year_end_adjustments", {"id": "ADJ-1", "engagement_id": "ENG-MINE",
                                     "firm_id": FIRM, "status": "draft"})
    out = yea.list_adjustments("ENG-MINE", current_user=EXEC_USER)
    assert [a["id"] for a in out["data"]] == ["ADJ-1"]


def test_updating_an_adjustment_on_another_clients_engagement_is_refused(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    _seed_mock_adjustment("ENG-THEIRS", "ADJ-1")
    with pytest.raises(HTTPException):
        yea.update_adjustment("ENG-THEIRS", "ADJ-1",
                              yea.AdjustmentUpdateIn(description="changed"),
                              current_user=EXEC_USER)
    assert yea._MOCK_ADJUSTMENTS["ENG-THEIRS"][0]["description"] == "test"


def test_updating_an_adjustment_on_your_own_engagement_still_works(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    _seed_mock_adjustment("ENG-MINE", "ADJ-1")
    out = yea.update_adjustment("ENG-MINE", "ADJ-1",
                                yea.AdjustmentUpdateIn(description="changed"),
                                current_user=EXEC_USER)
    assert out["data"]["description"] == "changed"


def test_submitting_an_adjustment_on_another_clients_engagement_is_refused(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    _seed_mock_adjustment("ENG-THEIRS", "ADJ-1")
    with pytest.raises(HTTPException):
        yea.submit_adjustment("ENG-THEIRS", "ADJ-1", current_user=EXEC_USER)
    assert yea._MOCK_ADJUSTMENTS["ENG-THEIRS"][0]["status"] == "draft"


def test_submitting_an_adjustment_on_your_own_engagement_still_works(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    _seed_mock_adjustment("ENG-MINE", "ADJ-1")
    out = yea.submit_adjustment("ENG-MINE", "ADJ-1", current_user=EXEC_USER)
    assert out["data"]["status"] == "pending_review"


def test_approving_an_adjustment_on_another_clients_engagement_is_refused(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    _seed_mock_adjustment("ENG-THEIRS", "ADJ-1", status="pending_review")
    with pytest.raises(HTTPException):
        yea.approve_adjustment("ENG-THEIRS", "ADJ-1", current_user=MANAGER_USER)
    assert yea._MOCK_ADJUSTMENTS["ENG-THEIRS"][0]["status"] == "pending_review"


def test_approving_an_adjustment_on_your_own_engagement_still_works(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    _seed_mock_adjustment("ENG-MINE", "ADJ-1", status="pending_review")
    out = yea.approve_adjustment("ENG-MINE", "ADJ-1", current_user=MANAGER_USER)
    assert out["data"]["status"] == "approved"


def test_posting_an_adjustment_on_another_clients_engagement_is_refused(deny, monkeypatch):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    _seed_mock_adjustment("ENG-THEIRS", "ADJ-1", status="approved")
    monkeypatch.setattr(yea.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    with pytest.raises(HTTPException):
        yea.post_adjustment("ENG-THEIRS", "ADJ-1", current_user=MANAGER_USER)
    assert yea._MOCK_ADJUSTMENTS["ENG-THEIRS"][0]["status"] == "approved"


def test_posting_an_adjustment_on_your_own_engagement_still_works(deny, monkeypatch):
    _seed_mock_engagement("ENG-MINE", MINE)
    _seed_mock_adjustment("ENG-MINE", "ADJ-1", status="approved")
    monkeypatch.setattr(yea.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    out = yea.post_adjustment("ENG-MINE", "ADJ-1", current_user=MANAGER_USER)
    assert out["data"]["status"] == "posted"


def test_rejecting_an_adjustment_on_another_clients_engagement_is_refused(deny):
    _seed_mock_engagement("ENG-THEIRS", THEIRS)
    _seed_mock_adjustment("ENG-THEIRS", "ADJ-1", status="pending_review")
    with pytest.raises(HTTPException):
        yea.reject_adjustment("ENG-THEIRS", "ADJ-1", yea.AdjustmentRejectIn(reason="no"),
                              current_user=MANAGER_USER)
    assert yea._MOCK_ADJUSTMENTS["ENG-THEIRS"][0]["status"] == "pending_review"


def test_rejecting_an_adjustment_on_your_own_engagement_still_works(deny):
    _seed_mock_engagement("ENG-MINE", MINE)
    _seed_mock_adjustment("ENG-MINE", "ADJ-1", status="pending_review")
    out = yea.reject_adjustment("ENG-MINE", "ADJ-1", yea.AdjustmentRejectIn(reason="no"),
                                current_user=MANAGER_USER)
    assert out["data"]["status"] == "rejected"
