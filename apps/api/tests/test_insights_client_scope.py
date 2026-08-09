"""
Client-assignment scope on the LEGACY /api/insights router.

insights.py is a second, older router over the same `ai_insights` table that
ai_insights.py serves under /api/ai-insights — and the frontend's
lib/api/index.ts calls THIS one. list_insights already narrowed with
filter_by_client, but update_insight_status is row-addressed by insight_id and
ai_insights_repo.update_status filters on firm_id alone, so an unassigned
Executive/Manager could acknowledge, resolve or dismiss another staff member's
client's insight by guessing an id. The sibling router's _assert_insight_scope
resolver had closed exactly this hole for its own ack/dismiss transitions; this
alias kept it open for the generic status transition.
"""
import pytest

import routers.insights as ins

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches can_access_client on the
    router module, mirroring the other *_client_scope.py test files in this
    sweep."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ins, "can_access_client", _can)
    return seen


def _seed(monkeypatch, row):
    """Stub the repository lookup the resolver uses."""
    monkeypatch.setattr(ins.ai_insights_repo, "find_by_id",
                        lambda iid, firm_id=None: row)


# ══════════════════════════════════════════════════════════════════════════════
# _assert_insight_scope
# ══════════════════════════════════════════════════════════════════════════════

def test_insight_scope_refuses_another_clients_record(deny, monkeypatch):
    _seed(monkeypatch, {"id": "I1", "client_id": THEIRS})
    assert ins._assert_insight_scope(USER, "I1") is None
    assert deny == [THEIRS]


def test_insight_scope_allows_your_own_record(deny, monkeypatch):
    row = {"id": "I1", "client_id": MINE}
    _seed(monkeypatch, row)
    assert ins._assert_insight_scope(USER, "I1") == row
    assert deny == [MINE]


def test_insight_scope_returns_none_for_a_missing_row(deny, monkeypatch):
    _seed(monkeypatch, None)
    assert ins._assert_insight_scope(USER, "nope") is None
    assert deny == []   # can_access_client never reached — nothing to check


# ══════════════════════════════════════════════════════════════════════════════
# update_insight_status
# ══════════════════════════════════════════════════════════════════════════════

def test_updating_status_of_another_clients_insight_is_refused(deny, monkeypatch):
    _seed(monkeypatch, {"id": "I1", "client_id": THEIRS})
    written = []
    monkeypatch.setattr(ins.ai_insights_repo, "update_status",
                        lambda *a, **kw: written.append(a) or {"id": "I1"})
    out = ins.update_insight_status("I1", "resolved", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Insight not found"
    assert not written   # refused BEFORE the update ever ran


def test_updating_status_of_your_own_insight_still_works(deny, monkeypatch):
    _seed(monkeypatch, {"id": "I1", "client_id": MINE})
    monkeypatch.setattr(ins.ai_insights_repo, "update_status",
                        lambda *a, **kw: {"id": "I1", "status": "resolved"})
    out = ins.update_insight_status("I1", "resolved", current_user=USER)
    assert out["success"] is True
    assert out["data"]["status"] == "resolved"


def test_a_missing_insight_and_a_hidden_one_read_identically(deny, monkeypatch):
    """No existence oracle: a wrong-client guess must be indistinguishable
    from an id that does not exist at all."""
    monkeypatch.setattr(ins.ai_insights_repo, "update_status", lambda *a, **kw: None)

    _seed(monkeypatch, None)
    missing = ins.update_insight_status("I1", "resolved", current_user=USER)

    _seed(monkeypatch, {"id": "I1", "client_id": THEIRS})
    hidden = ins.update_insight_status("I1", "resolved", current_user=USER)

    assert missing == hidden
    assert missing["error"] == "Insight not found"


def test_an_invalid_status_is_still_rejected_before_anything_is_resolved(deny, monkeypatch):
    """The scope guard must not have displaced the pre-existing validation."""
    _seed(monkeypatch, {"id": "I1", "client_id": MINE})
    out = ins.update_insight_status("I1", "bogus", current_user=USER)
    assert out["success"] is False
    assert "status must be one of" in out["error"]


# ══════════════════════════════════════════════════════════════════════════════
# list_insights — pre-existing filter_by_client, pinned so it cannot regress
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_drops_insights_outside_the_callers_book(monkeypatch):
    rows = [{"id": "I1", "client_id": MINE}, {"id": "I2", "client_id": THEIRS}]
    monkeypatch.setattr(ins.ai_insights_repo, "find_all", lambda **kw: rows)
    monkeypatch.setattr(ins, "filter_by_client",
                        lambda user, items, key="client_id":
                        [r for r in items if r.get(key) != THEIRS])
    out = ins.list_insights(client_id=None, status=None, current_user=USER)
    assert [r["id"] for r in out["data"]["insights"]] == ["I1"]
    assert out["data"]["total"] == 1
