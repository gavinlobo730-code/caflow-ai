"""
Client-assignment scope on the AI Copilot router (/api/copilot).

The last of the original twelve "guards the body, not the record" routers.
Three endpoints (send_message, quick_chat, client_intelligence) already
guarded their context_id/client_id — this phase closes every other
row-addressed or query-param endpoint that reaches client-scoped data:
conversations (which carry context_id — "e.g., client_id"), messages
(scoped via their parent conversation, since ai_messages itself carries no
context_id). It also guarded recommendations, actions and summaries until
those routes were deleted as fake or dead (ai-10) — the last test below holds
that.

NOT fixed here — recorded as an open question in the audit doc:
compliance_intelligence / workflow_intelligence / relationship_intelligence
/ executive_dashboard. All four aggregate across the whole firm with no
per-client identifiers in their current output (confirmed by reading
domain/ai_copilot_service.py directly, not the aspirational Pydantic
response models in models/ai_copilot.py, which the actual implementations
do not return). Properly narrowing workflow failures/approvals would
require joining through workflow_instances (workflow_failures and
workflow_approvals carry instance_id, not client_id, per migration 068);
narrowing the two cached ones (compliance, executive) would require
changing the cache key, since ai_summaries today caches one firm-wide
summary shared across every caller regardless of assignment.
"""
import pytest
from fastapi import HTTPException

import routers.ai_copilot_v2 as cp
from models.ai_copilot import ConversationCreateIn, FeedbackIn

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test",
       "role": "Executive"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest. Patches assert_client_access and
    can_access_client on the router module."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(cp, "assert_client_access", _assert)
    monkeypatch.setattr(cp, "can_access_client", _can)
    return seen


class _FakeRepo:
    """Stands in for _repo() — enough of AICopilotRepository's surface for
    these tests, independent of _USE_MOCK/live-mode branching."""
    def __init__(self):
        self.conversations = {}
        self.messages = {}
        self.archived = []

    def get_conversation(self, firm_id, conversation_id):
        c = self.conversations.get(conversation_id)
        return dict(c) if c and c.get("firm_id") == firm_id else None

    def list_conversations(self, firm_id, user_id, is_archived=False, limit=30):
        return [dict(c) for c in self.conversations.values()
                if c["firm_id"] == firm_id and c["user_id"] == user_id]

    def archive_conversation(self, firm_id, conversation_id):
        c = self.conversations.get(conversation_id)
        if not c or c["firm_id"] != firm_id:
            return None
        c["is_archived"] = True
        self.archived.append(conversation_id)
        return dict(c)

    def get_message(self, firm_id, message_id):
        m = self.messages.get(message_id)
        return dict(m) if m and m.get("firm_id") == firm_id else None

    def list_messages(self, conversation_id, limit=100):
        return []

    def add_feedback(self, firm_id, message_id, user_id, rating, feedback_text=None, tags=None):
        return {"message_id": message_id, "rating": rating}

    def create_conversation(self, firm_id, user_id, data):
        return {"id": "NEW", "firm_id": firm_id, "user_id": user_id, **data}


@pytest.fixture
def repo(monkeypatch):
    r = _FakeRepo()
    monkeypatch.setattr(cp, "_repo", lambda: r)
    return r


# ══════════════════════════════════════════════════════════════════════════════
# create_conversation
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_a_conversation_for_another_client_is_refused(deny, repo):
    body = ConversationCreateIn(context_type="client", context_id=THEIRS)
    with pytest.raises(HTTPException) as e:
        cp.create_conversation(body, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_creating_a_conversation_for_your_own_client_still_works(deny, repo):
    body = ConversationCreateIn(context_type="client", context_id=MINE)
    out = cp.create_conversation(body, current_user=USER)
    assert out["data"]["context_id"] == MINE
    assert deny == [MINE]


def test_creating_a_global_conversation_is_not_refused(deny, repo):
    body = ConversationCreateIn(context_type="global")
    out = cp.create_conversation(body, current_user=USER)
    assert out["data"]["context_type"] == "global"
    assert deny == [None]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_conversation_scope + get_conversation / archive_conversation
# ══════════════════════════════════════════════════════════════════════════════

def _seed_convs(repo):
    repo.conversations.update({
        "C-MINE": {"id": "C-MINE", "firm_id": FIRM, "user_id": "u1",
                   "context_id": MINE, "is_archived": False},
        "C-THEIRS": {"id": "C-THEIRS", "firm_id": FIRM, "user_id": "u2",
                     "context_id": THEIRS, "is_archived": False},
        "C-ALIEN": {"id": "C-ALIEN", "firm_id": "firm-2", "user_id": "u9",
                    "context_id": "c-x", "is_archived": False},
        "C-GLOBAL": {"id": "C-GLOBAL", "firm_id": FIRM, "user_id": "u1",
                     "context_id": None, "is_archived": False},
    })


def test_conversation_scope_refuses_another_clients_conversation(deny, repo):
    _seed_convs(repo)
    with pytest.raises(HTTPException) as e:
        cp._assert_conversation_scope(USER, "C-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_conversation_scope_returns_your_own_conversation(deny, repo):
    _seed_convs(repo)
    conv = cp._assert_conversation_scope(USER, "C-MINE")
    assert conv["id"] == "C-MINE"
    assert deny == [MINE]


def test_conversation_scope_allows_a_global_conversation(deny, repo):
    _seed_convs(repo)
    conv = cp._assert_conversation_scope(USER, "C-GLOBAL")
    assert conv["id"] == "C-GLOBAL"
    assert deny == [None]


def test_conversation_scope_refuses_another_firms_conversation_before_the_client_check(deny, repo):
    _seed_convs(repo)
    with pytest.raises(HTTPException) as e:
        cp._assert_conversation_scope(USER, "C-ALIEN")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_missing_and_hidden_conversations_use_the_identical_message(deny, repo):
    _seed_convs(repo)
    with pytest.raises(HTTPException) as missing:
        cp._assert_conversation_scope(USER, "C-NOPE")
    with pytest.raises(HTTPException) as hidden:
        cp._assert_conversation_scope(USER, "C-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Conversation not found"


def test_reading_another_clients_conversation_is_refused(deny, repo):
    _seed_convs(repo)
    with pytest.raises(HTTPException):
        cp.get_conversation("C-THEIRS", current_user=USER)


def test_reading_your_own_conversation_still_works(deny, repo):
    _seed_convs(repo)
    out = cp.get_conversation("C-MINE", current_user=USER)
    assert out["data"]["id"] == "C-MINE"


def test_archiving_another_clients_conversation_is_refused(deny, repo):
    _seed_convs(repo)
    with pytest.raises(HTTPException):
        cp.archive_conversation("C-THEIRS", current_user=USER)
    assert repo.archived == [], "the conversation was archived despite the refusal"


def test_archiving_your_own_conversation_still_works(deny, repo):
    _seed_convs(repo)
    out = cp.archive_conversation("C-MINE", current_user=USER)
    assert out["data"]["is_archived"] is True


def test_listing_conversations_narrows_out_a_since_revoked_client(deny, repo, monkeypatch):
    _seed_convs(repo)
    # Both belong to u1 (the caller), but context narrows to MINE only.
    repo.conversations["C-THEIRS"]["user_id"] = "u1"
    monkeypatch.setattr(cp, "filter_by_client",
                        lambda user, rows, key="client_id": [r for r in rows if r.get(key) != THEIRS])
    out = cp.list_conversations(is_archived=False, limit=30, current_user=USER)
    ids = {c["id"] for c in out["data"]["conversations"]}
    assert ids == {"C-MINE", "C-GLOBAL"}


# ══════════════════════════════════════════════════════════════════════════════
# _assert_message_scope + rate_message
# ══════════════════════════════════════════════════════════════════════════════

def test_message_scope_refuses_a_message_in_another_clients_conversation(deny, repo):
    _seed_convs(repo)
    repo.messages["M-THEIRS"] = {"id": "M-THEIRS", "firm_id": FIRM, "conversation_id": "C-THEIRS"}
    with pytest.raises(HTTPException) as e:
        cp._assert_message_scope(USER, "M-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_message_scope_returns_a_message_in_your_own_conversation(deny, repo):
    _seed_convs(repo)
    repo.messages["M-MINE"] = {"id": "M-MINE", "firm_id": FIRM, "conversation_id": "C-MINE"}
    msg = cp._assert_message_scope(USER, "M-MINE")
    assert msg["id"] == "M-MINE"
    assert deny == [MINE]


def test_message_scope_404s_when_the_message_itself_is_missing(deny, repo):
    _seed_convs(repo)
    with pytest.raises(HTTPException) as e:
        cp._assert_message_scope(USER, "M-NOPE")
    assert e.value.status_code == 404
    assert deny == [], "the conversation lookup ran for a message that doesn't exist"


def test_rating_a_message_in_another_clients_conversation_is_refused(deny, repo):
    _seed_convs(repo)
    repo.messages["M-THEIRS"] = {"id": "M-THEIRS", "firm_id": FIRM, "conversation_id": "C-THEIRS"}
    with pytest.raises(HTTPException):
        cp.rate_message("M-THEIRS", FeedbackIn(rating=5), current_user=USER)


def test_rating_a_message_in_your_own_conversation_still_works(deny, repo):
    _seed_convs(repo)
    repo.messages["M-MINE"] = {"id": "M-MINE", "firm_id": FIRM, "conversation_id": "C-MINE"}
    out = cp.rate_message("M-MINE", FeedbackIn(rating=5), current_user=USER)
    assert out["data"]["rating"] == 5


# ══════════════════════════════════════════════════════════════════════════════
# The recommendation, action and summary routes are GONE (ai-10)
# ══════════════════════════════════════════════════════════════════════════════
#
# The scope tests that stood here guarded `list_recommendations`,
# `act_recommendation`, `execute_ai_action` and `list_summaries`. All four routes
# were deleted because they were fake or dead (nothing generated a recommendation;
# the action route marked itself `executed` and did nothing; the summaries route
# filtered an in-memory fixture) — see the note at the foot of
# routers/ai_copilot_v2.py and tests/test_ai_surfaces_are_not_fake_or_dead.py.
# A route that does not exist cannot be reached across clients, which is the
# strongest scope guard there is; this asserts it stays that way.

def test_the_deleted_routes_stay_deleted():
    for name in ("list_recommendations", "act_recommendation",
                 "execute_ai_action", "list_summaries"):
        assert not hasattr(cp, name), f"{name} came back — see ai-10"
