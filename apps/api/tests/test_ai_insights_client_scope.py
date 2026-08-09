"""
Client-assignment scope on the ai_insights router (Chapter 17 AI insight feed).

list_insights took client_id from the query string and never checked it when
supplied; when omitted it returned every insight in the FIRM unfiltered — now
narrowed with filter_by_client (the tally_migration.py-shaped gap).
generate_insights is row-addressed by client_id in the PATH and had no check
at all. ack_insight/dismiss_insight are row-addressed by insight_id and
checked only firm_id — new _assert_insight_scope resolver closes that gap.
insight_feed returns NAMED insight rows firm-wide with no narrowing at all —
confined via effective_client_ids threaded into get_insight_feed as
allowed_client_ids. cross_client_patterns is EXEMPT (a hardcoded stub with no
real client data — see the ratchet's EXEMPT reason).
"""
import pytest
from fastapi import HTTPException

import routers.ai_insights as ai
import repositories.ai_insights_repository as repo_mod

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access/
    can_access_client on the router module, mirroring the other
    *_client_scope.py test files in this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ai, "assert_client_access", _assert)
    monkeypatch.setattr(ai, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_insights — client_id from the query string, or firm-wide narrowing
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_insights_is_refused(deny, monkeypatch):
    monkeypatch.setattr(ai, "get_all_insights", lambda **kw: [])
    with pytest.raises(HTTPException) as e:
        ai.list_insights(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_insights_still_works(deny, monkeypatch):
    monkeypatch.setattr(ai, "get_all_insights", lambda **kw: [{"id": "i1", "client_id": MINE}])
    out = ai.list_insights(client_id=MINE, current_user=USER)
    assert out["data"] == [{"id": "i1", "client_id": MINE}]
    assert deny == [MINE]


def test_listing_without_a_client_id_is_narrowed_to_the_assigned_book(deny, monkeypatch):
    """No client_id supplied — the firm-wide result must be narrowed with
    filter_by_client rather than handed back unfiltered."""
    monkeypatch.setattr(
        ai, "get_all_insights",
        lambda **kw: [{"id": "mine", "client_id": MINE}, {"id": "theirs", "client_id": THEIRS}],
    )
    monkeypatch.setattr(
        ai, "filter_by_client", lambda user, rows: [r for r in rows if r["client_id"] != THEIRS],
    )
    out = ai.list_insights(client_id=None, current_user=USER)
    assert [r["id"] for r in out["data"]] == ["mine"]
    assert deny == []   # assert_client_access is never called without a client_id


# ══════════════════════════════════════════════════════════════════════════════
# generate_insights — row-addressed by client_id in the PATH
# ══════════════════════════════════════════════════════════════════════════════

def test_generating_insights_for_another_clients_is_refused(deny, monkeypatch):
    monkeypatch.setattr(ai, "generate_insights_for_client", lambda cid, firm_id: [])
    with pytest.raises(HTTPException) as e:
        ai.generate_insights(THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_generating_insights_for_your_own_client_still_works(deny, monkeypatch):
    monkeypatch.setattr(ai, "generate_insights_for_client", lambda cid, firm_id: [{"id": "x"}])
    out = ai.generate_insights(MINE, current_user=USER)
    assert out["data"]["generated"] == 1
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_insight_scope + ack_insight/dismiss_insight — row-addressed
# ══════════════════════════════════════════════════════════════════════════════

def _patch_find_by_id(monkeypatch, row):
    monkeypatch.setattr(repo_mod.ai_insights_repo, "find_by_id", lambda insight_id, firm_id=None: row)


def test_insight_scope_refuses_another_clients_insight(deny, monkeypatch):
    _patch_find_by_id(monkeypatch, {"id": "AI-THEIRS", "client_id": THEIRS})
    assert ai._assert_insight_scope(USER, "AI-THEIRS") is None
    assert deny == [THEIRS]


def test_insight_scope_allows_your_own_insight(deny, monkeypatch):
    row = {"id": "AI-MINE", "client_id": MINE}
    _patch_find_by_id(monkeypatch, row)
    assert ai._assert_insight_scope(USER, "AI-MINE") == row
    assert deny == [MINE]


def test_insight_scope_returns_none_for_a_missing_row(deny, monkeypatch):
    _patch_find_by_id(monkeypatch, None)
    assert ai._assert_insight_scope(USER, "nope") is None
    assert deny == []   # can_access_client is never reached — nothing to check


def test_acknowledging_another_clients_insight_is_refused(monkeypatch):
    monkeypatch.setattr(ai, "_assert_insight_scope", lambda user, iid: None)
    out = ai.ack_insight("AI-THEIRS", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Insight not found"


def test_acknowledging_your_own_insight_still_works(monkeypatch):
    monkeypatch.setattr(ai, "_assert_insight_scope", lambda user, iid: {"id": iid, "client_id": MINE})
    monkeypatch.setattr(ai, "acknowledge_insight", lambda iid, firm_id: {"id": iid, "status": "acknowledged"})
    out = ai.ack_insight("AI-MINE", current_user=USER)
    assert out["data"]["status"] == "acknowledged"


def test_dismissing_another_clients_insight_is_refused(monkeypatch):
    monkeypatch.setattr(ai, "_assert_insight_scope", lambda user, iid: None)
    out = ai.dis_insight("AI-THEIRS", current_user=USER)
    assert out["success"] is False
    assert out["error"] == "Insight not found"


def test_dismissing_your_own_insight_still_works(monkeypatch):
    monkeypatch.setattr(ai, "_assert_insight_scope", lambda user, iid: {"id": iid, "client_id": MINE})
    monkeypatch.setattr(ai, "dismiss_insight", lambda iid, firm_id: {"id": iid, "status": "dismissed"})
    out = ai.dis_insight("AI-MINE", current_user=USER)
    assert out["data"]["status"] == "dismissed"


# ══════════════════════════════════════════════════════════════════════════════
# insight_feed — firm-wide, confined via effective_client_ids
# ══════════════════════════════════════════════════════════════════════════════

def test_insight_feed_threads_effective_client_ids_into_the_domain_call(monkeypatch):
    captured = {}

    def _fake_feed(firm_id, limit, allowed_client_ids):
        captured["allowed"] = allowed_client_ids
        return []

    monkeypatch.setattr(ai, "get_insight_feed", _fake_feed)
    monkeypatch.setattr(ai, "effective_client_ids", lambda user: {MINE})
    ai.insight_feed(limit=20, current_user=USER)
    assert captured["allowed"] == {MINE}
