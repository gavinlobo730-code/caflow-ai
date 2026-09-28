"""
A production copilot conversation was never auto-titled (sweep-misc-tools-12).

ai_copilot_repository.create_conversation defaults the title to
"New Conversation", and add_message._USE_MOCK branch titles it off the
first user message — but the REAL (Supabase) branch only called
increment_message_count and threw the RPC's own return value away, so
update_conversation_title (which has no other caller) was never invoked.
Every production conversation stayed "New Conversation" forever, however
many messages it held.

increment_message_count (migration 156) RETURNS the new message_count in
the same statement that increments it, precisely so a caller can act on it
without a second round trip. This fixture stands in for that RPC and for
the handful of PostgREST calls add_message/get_conversation/
update_conversation_title make, so the REAL branch can be exercised without
a live Supabase project — the mock branch (exercised by
test_ai_copilot.py::test_first_message_auto_titles_conversation) already
passed before this fix and is deliberately left alone.
"""
import pytest

import repositories.ai_copilot_repository as repo_mod
from repositories.ai_copilot_repository import AICopilotRepository


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"
        self.payload = None
        self.filters: list[tuple[str, object]] = []
        self.single_ = False

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single_ = True
        return self

    def _matching(self):
        rows = self.s.setdefault(self.t, [])
        return [r for r in rows if all(r.get(k) == v for k, v in self.filters)]

    def execute(self):
        if self.op == "insert":
            rows = self.s.setdefault(self.t, [])
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for item in items:
                rec = dict(item)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                inserted.append(rec)
            return _Resp(inserted)
        if self.op == "update":
            matches = self._matching()
            for row in matches:
                row.update(self.payload)
            return _Resp(matches)
        matches = self._matching()
        if self.single_:
            return _Resp(matches[0] if matches else None)
        return _Resp(matches)


class _Rpc:
    """Stands in for the increment_message_count SQL function (migration
    156): atomically increments message_count on the named conversation and
    RETURNS the new value as a bare scalar — which is exactly what
    PostgREST hands back for a scalar-returning function, and what
    `journal_period_lock_reason`'s own caller (manual_journal_service.
    _lock_reason) already relies on via `res.data`."""

    def __init__(self, store, fn, params):
        self.s, self.fn, self.p = store, fn, params

    def execute(self):
        assert self.fn == "increment_message_count", self.fn
        conv_id = self.p["conv_id"]
        for conv in self.s.setdefault("ai_conversations", []):
            if conv["id"] == conv_id:
                conv["message_count"] = (conv.get("message_count") or 0) + 1
                return _Resp(conv["message_count"])
        return _Resp(None)


class FakeDB:
    def __init__(self):
        self.store: dict[str, list[dict]] = {}

    def table(self, name):
        return _Query(self.store, name)

    def rpc(self, fn, params):
        return _Rpc(self.store, fn, params)


@pytest.fixture
def repo(monkeypatch):
    """Forces the REAL (non-mock) branch of the repository against a fake
    Supabase double, the same shape test_vendor_payment_concurrency.py uses
    for its router-level fakes."""
    fake = FakeDB()
    monkeypatch.setattr(repo_mod, "_USE_MOCK", False)
    monkeypatch.setattr(repo_mod, "_get_db", lambda: fake)
    return AICopilotRepository()


def test_first_user_message_titles_a_production_conversation(repo):
    conv = repo.create_conversation("firm-1", "user-1", {})
    assert conv["title"] == "New Conversation"

    repo.add_message("firm-1", conv["id"], "user", "What TDS filings are due this quarter?")

    updated = repo.get_conversation("firm-1", conv["id"])
    assert updated["title"] == "What TDS filings are due this quarter?"


def test_long_first_message_is_truncated_with_ellipsis(repo):
    conv = repo.create_conversation("firm-1", "user-1", {})
    long_text = "A" * 90

    repo.add_message("firm-1", conv["id"], "user", long_text)

    updated = repo.get_conversation("firm-1", conv["id"])
    assert updated["title"] == long_text[:60] + "..."


def test_second_user_message_does_not_retitle(repo):
    conv = repo.create_conversation("firm-1", "user-1", {})
    repo.add_message("firm-1", conv["id"], "user", "First question")
    repo.add_message("firm-1", conv["id"], "assistant", "Some answer")
    repo.add_message("firm-1", conv["id"], "user", "Second question, unrelated")

    updated = repo.get_conversation("firm-1", conv["id"])
    assert updated["title"] == "First question"


def test_assistant_only_first_message_does_not_title(repo):
    """Matches the mock branch's own `role == "user"` guard: a conversation
    whose first stored message is from the assistant is not titled off it."""
    conv = repo.create_conversation("firm-1", "user-1", {})

    repo.add_message("firm-1", conv["id"], "assistant", "Hello, how can I help?")

    updated = repo.get_conversation("firm-1", conv["id"])
    assert updated["title"] == "New Conversation"
