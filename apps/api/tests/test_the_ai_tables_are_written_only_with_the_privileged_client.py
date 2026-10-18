"""The AI tables are written with the privileged client, firm by firm, and a conversation is its owner's (POST-A-250).

THE DEFECT
    `ai_conversations`, `ai_messages`, `ai_summaries`, `ai_recommendations` and `ai_feedback` were written by
    `repositories/ai_copilot_repository.py` through `db_provider.request_db`, which under `USE_USER_JWT` (the production
    default) is the CALLER'S OWN session, and `authenticated` held INSERT, UPDATE and DELETE on all of them (migration 095)
    with a firm-isolation policy as the only control. Any signed-in member could write another member's conversation or plant
    an `assistant` message in it, and `AICopilotService._build_messages` replays the last eight stored turns into the next
    prompt as the model's own. On the API path the same hole had a second face: a conversation was looked up by firm and id
    alone, so any member who knew an id could read it, post into it or archive it.

WHAT IS HELD (migration 505 revokes the grants; its own test is the real-Postgres one)
    (The scan follows a chain that STARTS at `_get_db()` or `_write_db()`. A client held in a variable and written through
    later would be invisible to it; the repository has none, and the behavioural tests below would still catch it.)
    * every write the repository makes (insert, update, delete, rpc) is made through `_write_db()`, never `_get_db()`, and the
      reads stay on `_get_db()` so row security still narrows them. Source-level, from the AST of the module, so a new write
      method cannot take the other client;
    * every update names its firm, so the privileged client cannot write a row of another firm; the title update, which had no
      firm filter at all and leaned on row security, is the one that changed;
    * behaviourally, with a read client that refuses every write and a separate write client, each public write method
      reaches the write client and none touches the read one;
    * a conversation is found only by its owner: another member of the firm is told it is not found by the lookup, by archive
      and by the message route, and a conversation the caller owns is found as before.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import repositories.ai_copilot_repository as repo_mod
from repositories.ai_copilot_repository import AICopilotRepository
from tests.test_a_copilot_conversation_is_titled_from_its_first_message import FakeDB, _Query

REPO = Path(repo_mod.__file__)
WRITE_VERBS = {"insert", "update", "delete", "upsert", "rpc"}


def _chain_root(node: ast.AST) -> str | None:
    """The name of the function a call chain starts from (`_get_db()` / `_write_db()`), or None."""
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Name):
            return node.id
        else:
            return None


def _chain_text(node: ast.AST) -> str:
    return ast.unparse(node)


def _calls_in_methods() -> list[ast.Call]:
    tree = ast.parse(REPO.read_text(encoding="utf-8"))
    out: list[ast.Call] = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            out.extend(n for n in ast.walk(fn) if isinstance(n, ast.Call))
    return out


def test_every_write_the_repository_makes_goes_through_the_privileged_client():
    # A chain that starts at a database client. `r.update(updates)` on a mock-mode dict is a dict method, not a write.
    writes = [c for c in _calls_in_methods()
              if isinstance(c.func, ast.Attribute) and c.func.attr in WRITE_VERBS
              and _chain_root(c) in {"_get_db", "_write_db"}]
    assert writes, "the scan found no write at all: the collector is broken"
    wrong = [(c.lineno, _chain_root(c)) for c in writes if _chain_root(c) != "_write_db"]
    assert wrong == [], f"writes made through anything but _write_db(): {wrong}"


def test_every_read_stays_on_the_callers_own_session():
    reads = [c for c in _calls_in_methods()
             if isinstance(c.func, ast.Attribute) and c.func.attr == "select"]
    assert reads, "the scan found no read at all: the collector is broken"
    wrong = [(c.lineno, _chain_root(c)) for c in reads if _chain_root(c) != "_get_db"]
    assert wrong == [], f"reads made through anything but _get_db(): {wrong}"


def test_every_update_names_its_firm():
    updates = [c for c in _calls_in_methods()
               if isinstance(c.func, ast.Attribute) and c.func.attr == "update" and _chain_root(c) == "_write_db"]
    assert updates, "the scan found no update at all: the collector is broken"
    # an update is filtered by `.eq("firm_id", ...)` further along the SAME chain, which the parent call holds; the stale
    # query in upsert_summary is built in a variable first, so the whole method body is searched for its filter.
    tree = ast.parse(REPO.read_text(encoding="utf-8"))
    missing = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            body = ast.unparse(fn)
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute) and n.func.attr == "update" and _chain_root(n) == "_write_db"]:
                if not re.search(r"""\.eq\(['"]firm_id['"]""", body):
                    missing.append((fn.name, call.lineno))
    assert missing == [], f"updates with no firm filter in their method: {missing}"


def test_negative_control_the_scan_catches_a_write_on_the_callers_session():
    tree = ast.parse('def f():\n    _get_db().table("t").insert({}).execute()\n')
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "insert")
    assert _chain_root(call) == "_get_db"


# ── behaviour: the read client refuses every write, the write client takes them ───────────────────────────────────────

class _ReadOnlyQuery(_Query):
    def insert(self, *_a, **_k):
        raise AssertionError("a write reached the caller's own session")

    def update(self, *_a, **_k):
        raise AssertionError("a write reached the caller's own session")

    def delete(self, *_a, **_k):
        raise AssertionError("a write reached the caller's own session")


class _ReadOnlyDB(FakeDB):
    def table(self, name):
        q = _ReadOnlyQuery(self.store, name)
        return q

    def rpc(self, *_a, **_k):
        raise AssertionError("a function call reached the caller's own session")


class _WriteQuery(_Query):
    def is_(self, key, value):
        self.filters.append((key, None if value in (None, "null") else value))
        return self


class _WriteDB(FakeDB):
    def table(self, name):
        return _WriteQuery(self.store, name)


@pytest.fixture
def repo(monkeypatch):
    write = _WriteDB()

    class _Both(_ReadOnlyDB):
        """Reads see what the write client stored (one store), writes through here are refused."""

    read = _Both()
    read.store = write.store
    monkeypatch.setattr(repo_mod, "_USE_MOCK", False)
    monkeypatch.setattr(repo_mod, "_get_db", lambda: read)
    monkeypatch.setattr(repo_mod, "_write_db", lambda: write)
    return AICopilotRepository(), write


def test_each_write_method_reaches_the_write_client_and_none_touches_the_read_one(repo):
    r, write = repo
    conv = r.create_conversation("F1", "U1", {})
    r.add_message("F1", conv["id"], "user", "hello")
    r.add_message("F1", conv["id"], "assistant", "hi")
    assert r.archive_conversation("F1", conv["id"], user_id="U1") is not None
    r.upsert_summary("F1", "executive", None, {"content": "x"})
    rec = r.create_recommendation("F1", {"title": "t"})
    assert r.update_recommendation_status("F1", rec["id"], "dismissed", "U1") is not None
    msg_id = write.store["ai_messages"][0]["id"]
    r.add_feedback("F1", msg_id, "U1", 5)
    assert {t for t in write.store} >= {
        "ai_conversations", "ai_messages", "ai_summaries", "ai_recommendations", "ai_feedback"}


def test_the_title_update_is_firm_scoped(repo):
    r, write = repo
    conv = r.create_conversation("F1", "U1", {})
    assert r.update_conversation_title("OTHER-FIRM", conv["id"], "hijacked") is None
    assert write.store["ai_conversations"][0]["title"] == "New Conversation"
    assert r.update_conversation_title("F1", conv["id"], "mine")["title"] == "mine"


# ── a conversation is its owner's ─────────────────────────────────────────────────────────────────────────────────────

def test_another_member_does_not_find_the_conversation(repo):
    r, _ = repo
    conv = r.create_conversation("F1", "OWNER", {})
    assert r.get_conversation("F1", conv["id"], user_id="OWNER")["id"] == conv["id"]
    assert r.get_conversation("F1", conv["id"], user_id="SOMEONE-ELSE") is None
    assert r.get_conversation("OTHER-FIRM", conv["id"], user_id="OWNER") is None


def test_another_member_cannot_archive_it(repo):
    r, write = repo
    conv = r.create_conversation("F1", "OWNER", {})
    assert r.archive_conversation("F1", conv["id"], user_id="SOMEONE-ELSE") is None
    assert write.store["ai_conversations"][0]["is_archived"] is False
    assert r.archive_conversation("F1", conv["id"], user_id="OWNER")["is_archived"] is True


def test_the_mock_branch_agrees_about_the_owner(monkeypatch):
    monkeypatch.setattr(repo_mod, "_USE_MOCK", True)
    r = AICopilotRepository()
    conv = r.create_conversation("F-MOCK", "OWNER", {})
    assert r.get_conversation("F-MOCK", conv["id"], user_id="SOMEONE-ELSE") is None
    assert r.archive_conversation("F-MOCK", conv["id"], user_id="SOMEONE-ELSE") is None
    assert r.get_conversation("F-MOCK", conv["id"], user_id="OWNER") is not None


# ── the routes ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    from core.permissions import rbac  # noqa: F401  (the dependency is overridden by identity below)

    def _as(user_id):
        # The routes call rbac("task", "read"); the header-auth test mode answers for the user named.
        return TestClient(app, headers={"Authorization": f"Bearer test-{user_id}"})

    yield _as


def test_the_message_route_resolves_a_conversation_by_its_owner(monkeypatch):
    """The send route looks the conversation up WITH the caller's id, which is what makes another member's id a 404."""
    import routers.ai_copilot_v2 as v2

    seen = {}

    class _Repo:
        def get_conversation(self, firm_id, conversation_id, user_id=None):
            seen["call"] = (firm_id, conversation_id, user_id)
            return None

    monkeypatch.setattr(v2, "_repo", lambda: _Repo())
    from fastapi import HTTPException
    import asyncio
    with pytest.raises(HTTPException) as err:
        asyncio.run(v2.send_message(
            "CONV-1", v2.MessageIn(content="hi"),
            current_user={"firm_id": "F1", "auth_user_id": "U-CALLER", "role": "Partner"}, _limit=None))
    assert err.value.status_code == 404
    assert seen["call"] == ("F1", "CONV-1", "U-CALLER")


def test_get_archive_and_feedback_resolve_by_the_owner_too(monkeypatch):
    import routers.ai_copilot_v2 as v2

    calls = []

    class _Repo:
        def get_conversation(self, firm_id, conversation_id, user_id=None):
            calls.append(("get", firm_id, conversation_id, user_id))
            return None

        def get_message(self, firm_id, message_id):
            return {"id": message_id, "conversation_id": "CONV-1"}

        def archive_conversation(self, firm_id, conversation_id, user_id=None):
            calls.append(("archive", firm_id, conversation_id, user_id))
            return None

    monkeypatch.setattr(v2, "_repo", lambda: _Repo())
    from fastapi import HTTPException
    user = {"firm_id": "F1", "auth_user_id": "U-CALLER", "role": "Partner"}
    for fn, arg in ((v2.get_conversation, "CONV-1"), (v2.archive_conversation, "CONV-1")):
        with pytest.raises(HTTPException) as err:
            fn(arg, current_user=user)
        assert err.value.status_code == 404
    with pytest.raises(HTTPException) as err:
        v2.rate_message("MSG-1", v2.FeedbackIn(rating=5), current_user=user)
    assert err.value.status_code == 404
    assert [c for c in calls if c[3] != "U-CALLER"] == [], calls
    assert {c[0] for c in calls} == {"get"}, "the lookup comes first on every route and refuses before any archive"


def test_the_archive_write_itself_is_scoped_to_the_owner_not_only_the_lookup_before_it(monkeypatch):
    """Defence in depth: the lookup before the write already refuses a stranger, and the UPDATE still names the owner, so a
    conversation that changed hands between the two is not archived by the wrong person."""
    import routers.ai_copilot_v2 as v2

    seen = {}

    class _Repo:
        def get_conversation(self, firm_id, conversation_id, user_id=None):
            return {"id": conversation_id, "firm_id": firm_id, "user_id": user_id, "context_id": None}

        def archive_conversation(self, firm_id, conversation_id, user_id=None):
            seen["archive"] = (firm_id, conversation_id, user_id)
            return {"id": conversation_id}

    monkeypatch.setattr(v2, "_repo", lambda: _Repo())
    user = {"firm_id": "F1", "auth_user_id": "U-CALLER", "role": "Partner"}
    out = v2.archive_conversation("CONV-1", current_user=user)
    assert out["success"] is True
    assert seen["archive"] == ("F1", "CONV-1", "U-CALLER")
