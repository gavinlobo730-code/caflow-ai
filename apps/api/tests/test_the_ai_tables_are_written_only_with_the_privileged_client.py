"""The AI tables are written with the privileged client, firm by firm, and a conversation is its owner's (POST-A-250, POST-A-257).

THE DEFECT
    `ai_conversations`, `ai_messages`, `ai_summaries`, `ai_recommendations` and `ai_feedback` were written by
    `repositories/ai_copilot_repository.py` through `db_provider.request_db`, which under `USE_USER_JWT` (the production
    default) is the CALLER'S OWN session, and `authenticated` held INSERT, UPDATE and DELETE on all of them (migration 095)
    with a firm-isolation policy as the only control. Any signed-in member could write another member's conversation or plant
    an `assistant` message in it, and `AICopilotService._build_messages` replays the last eight stored turns into the next
    prompt as the model's own. On the API path the same hole had a second face: a conversation was looked up by firm and id
    alone, so any member who knew an id could read it, post into it or archive it.

POST-A-257 REPEATS IT FOR THE INSIGHT AND MEMORY REPOSITORIES (migration 507): `ai_insights_repository` and
    `memory_repository` write `ai_insights`, `ai_memory_triggers`, the client and firm profiles, their history,
    `pattern_anomalies` and `year_end_reports`, all of which `authenticated` was granted writes on. The three source scans
    below run over all three repository files, so a write added to any of them on the caller's session fails here.

WHAT IS HELD (migrations 505 and 507 revoke the grants; their own tests are the real-Postgres ones)
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
REPOSITORY_FILES = [
    REPO,
    REPO.with_name("ai_insights_repository.py"),
    REPO.with_name("memory_repository.py"),
]
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


def _calls_in_methods(path: Path = REPO) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[ast.Call] = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            out.extend(n for n in ast.walk(fn) if isinstance(n, ast.Call))
    return out


def _db_chain(call: ast.Call, db_names=("_get_db", "_write_db", "_summary_read_db")) -> bool:
    """A call chain that starts at a database client: `_get_db()`, `_write_db()`, or a local bound to one of them."""
    return _chain_root(call) in set(db_names)


def _method_bindings(fn: ast.FunctionDef) -> dict[str, str]:
    """Locals bound to a database client inside one method: `db = _get_db()` and `write = _write_db()`."""
    out: dict[str, str] = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id in {"_get_db", "_write_db", "_summary_read_db"}):
            out[node.targets[0].id] = node.value.func.id
    return out


def _client_calls(path: Path):
    """(method, call, client) for every `.insert/.update/.delete/.upsert/.rpc/.select` call whose chain starts at a database
    client, where `client` is `_get_db` or `_write_db`, following one local alias per method."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            bound = _method_bindings(fn)
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]:
                root = _chain_root(call)
                client = root if root in {"_get_db", "_write_db", "_summary_read_db"} else bound.get(root or "")
                if client:
                    yield fn.name, call, client


@pytest.mark.parametrize("path", REPOSITORY_FILES, ids=lambda p: p.name)
def test_every_write_the_repository_makes_goes_through_the_privileged_client(path):
    # A chain that starts at a database client. `r.update(updates)` on a mock-mode dict is a dict method, not a write.
    writes = [(fn, c, client) for fn, c, client in _client_calls(path) if c.func.attr in WRITE_VERBS]
    assert writes, "the scan found no write at all: the collector is broken"
    wrong = [(fn, c.lineno, client) for fn, c, client in writes if client != "_write_db"]
    assert wrong == [], f"writes made through anything but _write_db(): {wrong}"


@pytest.mark.parametrize("path", REPOSITORY_FILES, ids=lambda p: p.name)
def test_every_read_stays_on_the_callers_own_session_except_the_summary_cache(path):
    """Reads stay on the caller's session so row security narrows them, with ONE exception: `ai_summaries`, which no signed-in
    session may read at all since migration 512 (POST-A-260) because it holds the Partner's firm-wide dashboard under no
    scope key. Its read goes through `_summary_read_db()`, and nothing else does."""
    reads = [(fn, c, client) for fn, c, client in _client_calls(path) if c.func.attr == "select"]
    assert reads, "the scan found no read at all: the collector is broken"
    wrong = []
    for fn, c, client in reads:
        wanted = "_summary_read_db" if '"ai_summaries"' in ast.unparse(c) or "'ai_summaries'" in ast.unparse(c) else "_get_db"
        if client != wanted:
            wrong.append((fn, c.lineno, client, wanted))
    assert wrong == [], f"reads made through the wrong client (method, line, used, wanted): {wrong}"


def test_the_summary_cache_is_read_privileged_and_names_its_firm():
    """The one reader of `ai_summaries`: through the privileged client, firm and type and freshness named."""
    reads = [(fn, c) for fn, c, client in _client_calls(REPO)
             if c.func.attr == "select" and "ai_summaries" in ast.unparse(c)]
    assert [fn for fn, _c in reads] == ["get_summary"], "the cache has one reader; a second must be added here deliberately"
    text = ast.unparse(reads[0][1])
    assert text.startswith("_summary_read_db()")
    assert re.search(r"""\.eq\(['"]firm_id['"]""", ast.unparse(next(
        fn for cls in ast.parse(REPO.read_text(encoding="utf-8")).body if isinstance(cls, ast.ClassDef)
        for fn in cls.body if isinstance(fn, ast.FunctionDef) and fn.name == "get_summary")))


def test_the_summary_accessor_is_the_privileged_client():
    import inspect
    src = inspect.getsource(repo_mod._summary_read_db)
    assert "db_provider.service_db()" in src and "request_db" not in src


def _topmost_chain(fn: ast.FunctionDef, node: ast.Call) -> ast.AST:
    """The outermost call of the chain `node` sits in (`....update(x).eq(a).eq(b).execute()` for the `.update(x)` node)."""
    parents = {child: parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}
    top: ast.AST = node
    while True:
        up = parents.get(top)
        if isinstance(up, ast.Attribute) and parents.get(up) is not None and isinstance(parents.get(up), ast.Call):
            top = parents[up]
        else:
            return top


@pytest.mark.parametrize("path", REPOSITORY_FILES, ids=lambda p: p.name)
def test_every_update_names_its_firm(path):
    """On the update's OWN chain when it is written inline (`.update(x).eq("id", i).eq("firm_id", f).execute()`), and
    anywhere in the method when the chain is built in a variable first (the stale-summary query in upsert_summary)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    firm = re.compile(r"""\.eq\(['"]firm_id['"]""")
    updates = 0
    bad: list[tuple[str, int]] = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            bound = _method_bindings(fn)
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute) and n.func.attr == "update"]:
                root = _chain_root(call)
                if (root if root in {"_get_db", "_write_db"} else bound.get(root or "")) != "_write_db":
                    continue
                updates += 1
                top = _topmost_chain(fn, call)
                inline = isinstance(top, ast.Call) and isinstance(top.func, ast.Attribute) and top.func.attr == "execute"
                text = ast.unparse(top) if inline else ast.unparse(fn)
                if not firm.search(text):
                    bad.append((fn.name, call.lineno))
    assert updates, "the scan found no update at all: the collector is broken"
    assert bad == [], f"updates with no firm filter: {bad}"


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


# ── the insight and memory repositories, behaviourally (POST-A-257) ───────────────────────────────────────────────────

@pytest.fixture
def memory(monkeypatch):
    import repositories.memory_repository as mem_mod
    write = _WriteDB()

    class _ReadOnly(_ReadOnlyDB):
        pass

    read = _ReadOnly()
    read.store = write.store
    monkeypatch.setattr(mem_mod, "_USE_MOCK", False)
    monkeypatch.setattr(mem_mod, "_get_db", lambda: read)
    monkeypatch.setattr(mem_mod, "_write_db", lambda: write)
    return mem_mod.MemoryRepository(), write


def test_the_memory_repository_writes_every_table_through_the_write_client(memory):
    r, write = memory
    trig = r.create_trigger("F1", "C1", "deadline_at_risk", "t", "w", [], "m", "a", 80.0, "high")
    assert r.acknowledge_trigger("F1", trig["id"], "U1")["status"] == "acknowledged"
    assert r.resolve_trigger("F1", trig["id"])["status"] == "resolved"
    assert r.dismiss_trigger("F1", trig["id"])["status"] == "dismissed"
    r.upsert_profile("F1", "C1", {"compliance_score": 60})
    second = r.upsert_profile("F1", "C1", {"compliance_score": 70})
    assert second["profile_version"] == 2, "the second upsert retires the first and numbers the next"
    r.upsert_firm_profile("F1", {"portfolio_compliance_score": 80})
    r.upsert_firm_profile("F1", {"portfolio_compliance_score": 85})
    r.create_anomaly("F1", "C1", "late_filing", "m", 1.0, 2.0, "2026-09")
    r.create_year_end_report("F1", "C1", "2025-26", {})
    assert {"ai_memory_triggers", "client_profiles", "client_profile_history", "firm_profiles",
            "pattern_anomalies", "year_end_reports"} <= set(write.store)
    assert len(write.store["client_profile_history"]) == 1, "the retired profile is snapshotted once"


def test_a_trigger_of_another_firm_is_not_touched_by_acknowledge_resolve_or_dismiss(memory):
    r, write = memory
    trig = r.create_trigger("F1", "C1", "deadline_at_risk", "t", "w", [], "m", "a", 80.0, "high")
    assert r.acknowledge_trigger("OTHER", trig["id"], "U1") is None
    assert r.resolve_trigger("OTHER", trig["id"]) is None
    assert r.dismiss_trigger("OTHER", trig["id"]) is None
    assert write.store["ai_memory_triggers"][0]["status"] == "active"


def test_the_retire_step_of_a_profile_upsert_does_not_touch_another_firms_profile(memory):
    r, write = memory
    r.upsert_profile("F1", "C1", {})
    mine = write.store["client_profiles"][0]
    write.store["client_profiles"].append({**mine, "id": "OTHERS", "firm_id": "F2", "is_current": True})
    r.upsert_profile("F1", "C1", {})
    others = next(p for p in write.store["client_profiles"] if p["id"] == "OTHERS")
    assert others["is_current"] is True and others["firm_id"] == "F2"


@pytest.fixture
def insights(monkeypatch):
    import repositories.ai_insights_repository as ins_mod
    write = _WriteDB()
    read = _ReadOnlyDB()
    read.store = write.store
    monkeypatch.setattr(ins_mod, "_USE_MOCK", False)
    monkeypatch.setattr(ins_mod, "_get_db", lambda: read)
    monkeypatch.setattr(ins_mod, "_write_db", lambda: write)
    return ins_mod.AIInsightsRepository(), write


def test_an_insight_is_created_and_its_status_changed_through_the_write_client(insights):
    r, write = insights
    row = r.create({"firm_id": "F1", "client_id": "C1", "category": "compliance", "severity": "high",
                    "title": "t", "description": "d", "status": "open"})
    assert write.store["ai_insights"][0]["firm_id"] == "F1"
    assert r.update_status(row["id"], "acknowledged", firm_id="F1")["status"] == "acknowledged"
    assert r.update_status(row["id"], "dismissed", firm_id="OTHER") is None
    assert write.store["ai_insights"][0]["status"] == "acknowledged"


def test_an_insight_with_no_firm_is_refused_before_it_is_written_privileged(insights):
    r, write = insights
    with pytest.raises(ValueError):
        r.create({"client_id": "C1", "title": "t", "description": "d", "severity": "high"})
    with pytest.raises(ValueError):
        r.update_status("anything", "dismissed", firm_id=None)
    assert "ai_insights" not in write.store
