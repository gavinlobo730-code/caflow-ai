"""The two database functions that write the ledger are called through the privileged client, from one place (POST-A-317, step 2).

WHAT CHANGES, AND WHY IT IS SAFE TO SHIP BEFORE THE REVOKE
    `post_journal_atomic` (the posting kernel) and `settle_receipt_atomic` (a plain rupee customer receipt) were called with the
    REQUEST's own client, so a signed-in member who held any one posting permission could call either over PostgREST and post a
    balanced entry with any content. They are now called with the privileged client, after the route's own checks, through
    `services/ledger_door.ledger_rpc`; migration 546 then takes EXECUTE away from signed-in users. Shipped in this order because
    the old API against a revoked function fails soft and wrong (every posting is refused with 42501). Migration 545 (merged
    before this) lets the two functions carry the posting person into the audit triggers, which a privileged client would
    otherwise lose; the person travels in the payload as `audit_actor`, the auth id of the request's own token, because most of the
    `journal_for_*` helpers pass no `created_by` for it to ride on (an independent review of the first version found that).

WHAT THIS HOLDS
    * No `.rpc("<ledger function>")` call exists anywhere in the API but the door's own two, no string equal to either function's name is used as code outside the door and the two call sites, and each of the two call
      sites is a `ledger_rpc(db, "<name>", ..., firm_id=..., client_id=...)` that names its firm and its client.
    * Driven for real on the in-memory database: with a request client that REFUSES to call either function (as the revoked grant
      will) and a privileged client that records the call, a journal posting and a plain receipt both succeed, through the
      privileged client, with `created_by` the internal user id and the firm and client in the payload.
    * THE PERSON: with a verified person recorded for the request (`core/request_actor.py`, bound by `core.auth.get_current_user`) the
      payload carries `audit_actor` = their auth id; with none (a job), a blank or non-text id, or no privileged client (mock mode,
      local development), it carries nothing and the payload is exactly what the caller built. The door does not change the
      dictionaries it is handed, and refuses a payload that names another firm or client than the one it was told.
    * A posting that names no firm or no client is refused before the privileged client is touched, and a name that is not one of
      the two ledger functions is refused.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from core import db_provider, request_actor
from services import ledger_door
from services.ledger_door import ledger_client, ledger_rpc
from services.phase2_journal_service import phase2_journal_service
from tests.e2e_harness import FakeDB, seed_standard_coa

API = pathlib.Path(__file__).resolve().parent.parent
FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
USER = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
AUTH = "aaaaaaaa-1111-2222-3333-444444444444"
RPCS = ("post_journal_atomic", "settle_receipt_atomic")


class _Spy(FakeDB):
    """The privileged client: records each ledger call as it was made, then does what the in-memory function does (which, like the
    database wrapper of migration 545, removes the reserved key)."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, fn, params=None):
        if fn in RPCS:
            self.calls.append((fn, {k: (dict(v) if isinstance(v, dict) else v) for k, v in (params or {}).items()}))
        return super().rpc(fn, params)


class _Refusing:
    """The request's own client after migration 546: it reads and writes the tables, and may not call either ledger function."""

    def __init__(self, inner: FakeDB):
        self._inner = inner
        self.refused: list[str] = []

    def table(self, name):
        return self._inner.table(name)

    def rpc(self, fn, params=None):
        if fn in RPCS:
            self.refused.append(fn)
            raise AssertionError(f"the request's own client called {fn}: it must go through services.ledger_door.ledger_rpc")
        return self._inner.rpc(fn, params)             # every other function (the closure check, numbering) is the caller's to call


@pytest.fixture
def world(monkeypatch):
    privileged = _Spy()
    accounts = seed_standard_coa(privileged, FIRM, CLIENT)
    request = _Refusing(privileged)
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: privileged)
    return privileged, request, accounts


@pytest.fixture
def token():
    """A request whose authentication dependency has verified AUTH (the middleware begins the holder before any handler runs)."""
    handle = request_actor.begin()
    request_actor.bind(AUTH)
    yield
    request_actor.end(handle)


def _lines(accounts):
    bank, equity = list(accounts.values())[0], list(accounts.values())[1]
    return [{"account_id": bank, "debit_paise": 10_000, "credit_paise": 0},
            {"account_id": equity, "debit_paise": 0, "credit_paise": 10_000}]


def _receipt():
    return {"id": "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr", "firm_id": FIRM, "client_id": CLIENT, "customer_id": "cust-1",
            "receipt_no": "RC-1", "receipt_date": "2026-06-30", "amount_paise": 10_000, "tds_paise": 0,
            "unallocated_paise": 10_000, "payment_mode": "bank", "reference_no": "", "notes": ""}


def _settle(request):
    from services import receipt_service
    return receipt_service._settle_receipt_via_atomic_rpc(request, FIRM, CLIENT, _receipt(), [], {"id": USER})


def test_a_journal_is_posted_through_the_privileged_client_with_the_person_and_the_scope_in_the_payload(world):
    privileged, request, accounts = world
    entry_id = phase2_journal_service._create_journal(
        request, FIRM, CLIENT, "2026-06-30", "J-1", "test", "Journal", _lines(accounts), created_by=USER)
    assert entry_id
    assert request.refused == []
    assert [c[0] for c in privileged.calls] == ["post_journal_atomic"]
    payload = privileged.calls[0][1]["p_entry"]
    assert (payload["firm_id"], payload["client_id"], payload["created_by"]) == (FIRM, CLIENT, USER)
    assert "audit_actor" not in payload, "no request token (a job): the payload carries no person but created_by"


def test_a_plain_receipt_is_settled_through_the_privileged_client(world):
    privileged, request, accounts = world
    out = _settle(request)
    assert out
    assert request.refused == []
    assert [c[0] for c in privileged.calls] == ["settle_receipt_atomic"]
    entry = privileged.calls[0][1]["p_journal_entry"]
    assert (entry["firm_id"], entry["client_id"], entry["created_by"]) == (FIRM, CLIENT, USER)
    assert "audit_actor" not in entry


# ── the person ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_postings_payload_carries_the_auth_id_of_the_requests_token_even_when_the_helper_names_no_created_by(world, token):
    """Most `journal_for_*` helpers pass no `created_by`: the person must not depend on it."""
    privileged, request, accounts = world
    entry_id = phase2_journal_service._create_journal(request, FIRM, CLIENT, "2026-06-30", "J-2", "test", "Journal", _lines(accounts))
    assert entry_id and request.refused == []
    payload = privileged.calls[0][1]["p_entry"]
    assert payload["audit_actor"] == AUTH and not payload.get("created_by")


def test_a_receipts_payload_carries_the_auth_id_of_the_requests_token(world, token):
    privileged, request, accounts = world
    assert _settle(request)
    assert privileged.calls[0][1]["p_journal_entry"]["audit_actor"] == AUTH


@pytest.mark.parametrize("label,bound", [("nobody bound", None), ("a blank id", "  "), ("a non-text id", 5)])
def test_a_request_that_names_nobody_usable_adds_nothing(world, label, bound):
    privileged, request, accounts = world
    handle = request_actor.begin()
    try:
        request_actor.bind(bound)
        assert phase2_journal_service._create_journal(request, FIRM, CLIENT, "2026-06-30", "J-3", "test", "Journal", _lines(accounts), created_by=USER)
    finally:
        request_actor.end(handle)
    assert "audit_actor" not in privileged.calls[0][1]["p_entry"], label


@pytest.mark.parametrize("fn,key", [("post_journal_atomic", "p_entry"), ("settle_receipt_atomic", "p_journal_entry")])
def test_a_payload_cannot_name_its_own_actor_the_door_removes_the_key_and_puts_back_only_the_verified_person(world, token, fn, key):
    privileged, request, accounts = world
    out = ledger_rpc(request, fn, {key: {"firm_id": FIRM, "client_id": CLIENT, "audit_actor": "SOMEONE-ELSE"}},
                     firm_id=FIRM, client_id=CLIENT)
    assert out is not None
    assert privileged.calls[-1][1][key]["audit_actor"] == AUTH


@pytest.mark.parametrize("fn,key", [("post_journal_atomic", "p_entry"), ("settle_receipt_atomic", "p_journal_entry")])
def test_a_payload_that_names_an_actor_in_a_request_with_nobody_verified_loses_it(world, fn, key):
    """A job, a public route or a webhook has no person; a key a caller wrote must not stand in for one."""
    privileged, request, accounts = world
    ledger_rpc(request, fn, {key: {"firm_id": FIRM, "client_id": CLIENT, "audit_actor": "SOMEONE-ELSE"}}, firm_id=FIRM, client_id=CLIENT)
    assert "audit_actor" not in privileged.calls[-1][1][key]


def test_the_in_memory_ledger_functions_remove_the_reserved_key_as_the_real_ones_do(world, token):
    """Migration 545's wrappers remove it before the body; a double that kept it would store a column the table does not have."""
    privileged, request, accounts = world
    entry_id = phase2_journal_service._create_journal(
        request, FIRM, CLIENT, "2026-06-30", "J-STRIP", "test", "Journal", _lines(accounts), created_by=USER)
    assert entry_id and all("audit_actor" not in row for row in privileged.rows("journal_entries"))
    _settle(request)
    assert all("audit_actor" not in row for row in privileged.rows("journal_entries"))


def test_with_no_privileged_client_the_payload_is_exactly_what_the_caller_built_even_with_a_token(monkeypatch, token):
    seen = []

    class _Db(FakeDB):
        def rpc(self, fn, params=None):
            if fn in RPCS:
                seen.append(params)
            return super().rpc(fn, params)

    db = _Db()
    accounts = seed_standard_coa(db, FIRM, CLIENT)
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: None)
    assert phase2_journal_service._create_journal(db, FIRM, CLIENT, "2026-06-30", "J-4", "test", "Journal", _lines(accounts), created_by=USER)
    assert seen and "audit_actor" not in seen[0]["p_entry"], "the in-memory double must see the payload unchanged"


def test_the_door_does_not_change_the_payload_it_was_handed(world, token):
    privileged, request, accounts = world
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-06-30", "reference_no": "J-9", "narration": "t",
             "entry_type": "Journal", "created_by": USER}
    params = {"p_entry": entry, "p_lines": _lines(accounts)}
    before = {"p_entry": dict(entry), "p_lines": [dict(l) for l in params["p_lines"]]}
    ledger_rpc(request, "post_journal_atomic", params, firm_id=FIRM, client_id=CLIENT)
    assert params == before and "audit_actor" not in entry, "the caller's own dictionaries were written to"


def test_the_request_actor_is_the_bound_person(token):
    assert request_actor.current_auth_user_id() == AUTH


def test_there_is_no_request_actor_without_a_request_and_binding_one_does_nothing():
    assert request_actor.current_auth_user_id() is None
    request_actor.bind(AUTH)                              # a job, or a test with no request: nothing to record into
    assert request_actor.current_auth_user_id() is None


def test_the_holder_is_shared_with_the_copy_a_worker_thread_runs_in():
    """A sync dependency runs on a worker thread whose contextvar context is a COPY: what it binds must still be seen by the handler."""
    import contextvars
    handle = request_actor.begin()
    try:
        contextvars.copy_context().run(request_actor.bind, AUTH)
        assert request_actor.current_auth_user_id() == AUTH
    finally:
        request_actor.end(handle)


def test_the_authentication_dependency_records_the_person_it_verified(monkeypatch):
    import core.auth as auth
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda tok: {"sub": AUTH, "email": "m@x.test", "iat": 4_000_000_000})
    monkeypatch.setattr(auth, "get_service_supabase", lambda: object())
    monkeypatch.setattr(auth, "_get_user_and_firm", lambda sb, uid: ({"id": USER, "firm_id": FIRM, "role": "Manager", "is_active": True}, {}))
    handle = request_actor.begin()
    try:
        out = auth.get_current_user(authorization="Bearer a.b.c")
        assert out["auth_user_id"] == AUTH
        assert request_actor.current_auth_user_id() == AUTH
    finally:
        request_actor.end(handle)


def _probe_app(monkeypatch):
    """The REAL application with two throwaway routes that depend on the real authentication dependency, one on a worker thread (a
    sync handler) and one on the loop (an async one), and answer with what the ledger door would read. The token decode and the
    user lookup are the only things replaced."""
    import main
    from fastapi import Depends
    from core import auth
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda tok: {"sub": AUTH, "email": "m@x.test", "iat": 4_000_000_000})
    monkeypatch.setattr(auth, "get_service_supabase", lambda: object())
    monkeypatch.setattr(auth, "_get_user_and_firm", lambda sb, uid: ({"id": USER, "firm_id": FIRM, "role": "Manager", "is_active": True}, {}))

    def sync_probe(user: dict = Depends(auth.get_current_user)):
        return {"seen": request_actor.current_auth_user_id()}

    async def async_probe(user: dict = Depends(auth.get_current_user)):
        return {"seen": request_actor.current_auth_user_id()}

    async def anonymous_probe():
        return {"seen": request_actor.current_auth_user_id()}

    n = len(main.app.router.routes)
    main.app.add_api_route("/__probe_actor_sync", sync_probe)
    main.app.add_api_route("/__probe_actor_async", async_probe)
    main.app.add_api_route("/__probe_actor_anonymous", anonymous_probe)
    return main.app, n


@pytest.mark.parametrize("path", ["/__probe_actor_sync", "/__probe_actor_async"])
def test_a_route_running_inside_the_real_middleware_reads_the_person_the_dependency_verified(monkeypatch, path):
    """Behaviour, not source text: the holder has to be begun before the route runs and still be there when it asks, on the loop and on
    the worker thread a sync dependency runs on. Ending it before the route (a one-line move in the middleware) loses the audit actor
    of every posting whose helper names no `created_by`, and the textual test below would not notice."""
    from fastapi.testclient import TestClient
    app, n = _probe_app(monkeypatch)
    try:
        body = TestClient(app).get(path, headers={"Authorization": "Bearer a.b.c"}).json()
        assert body == {"seen": AUTH}, body
    finally:
        del app.router.routes[n:]


def test_a_request_with_no_token_is_nobody_and_does_not_inherit_the_previous_requests_person(monkeypatch):
    from fastapi.testclient import TestClient
    app, n = _probe_app(monkeypatch)
    try:
        client = TestClient(app)
        assert client.get("/__probe_actor_sync", headers={"Authorization": "Bearer a.b.c"}).json() == {"seen": AUTH}
        assert client.get("/__probe_actor_anonymous").json() == {"seen": None}
    finally:
        del app.router.routes[n:]


def test_the_middleware_begins_and_ends_the_holder_around_every_request():
    import ast as _ast
    src = (API / "main.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    fn = next(n for n in _ast.walk(tree) if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_carry_user_token")
    text = _ast.get_source_segment(src, fn)
    assert "request_actor.begin()" in text and "request_actor.end(actor_handle)" in text, "the holder is not begun and ended with the request"
    assert text.index("request_actor.begin()") < text.index("await call_next("), "the holder must exist before the route runs"


# ── the door ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_with_no_privileged_client_the_callers_own_client_is_used(monkeypatch):
    db = FakeDB()
    accounts = seed_standard_coa(db, FIRM, CLIENT)
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: None)
    assert ledger_client(db, firm_id=FIRM, client_id=CLIENT) is db
    entry_id = phase2_journal_service._create_journal(
        db, FIRM, CLIENT, "2026-06-30", "J-2", "test", "Journal", _lines(accounts), created_by=USER)
    assert entry_id and len(db.rows("journal_entries")) == 1


@pytest.mark.parametrize("firm,client", [("", CLIENT), (FIRM, ""), (None, CLIENT), (FIRM, None)])
def test_a_posting_that_names_no_firm_or_no_client_is_refused_before_the_privileged_client_is_touched(monkeypatch, firm, client):
    touched = []
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: touched.append(1) or FakeDB())
    with pytest.raises(ValueError):
        ledger_client(FakeDB(), firm_id=firm, client_id=client)
    with pytest.raises(ValueError):
        ledger_rpc(FakeDB(), "post_journal_atomic", {"p_entry": {}, "p_lines": []}, firm_id=firm, client_id=client)
    assert touched == []


def test_a_name_that_is_not_a_ledger_function_is_refused(monkeypatch):
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: FakeDB())
    with pytest.raises(ValueError):
        ledger_rpc(FakeDB(), "numbered_document_atomic", {"p_entry": {}}, firm_id=FIRM, client_id=CLIENT)


@pytest.mark.parametrize("fn,key", [("post_journal_atomic", "p_entry"), ("settle_receipt_atomic", "p_journal_entry")])
@pytest.mark.parametrize("entry", [
    {"firm_id": "other-firm", "client_id": CLIENT}, {"firm_id": FIRM, "client_id": "other-client"}, {"firm_id": FIRM}, {"client_id": CLIENT}, {},
], ids=["another firm", "another client", "no client", "no firm", "an empty entry"])
def test_a_payload_that_names_another_scope_than_the_one_the_door_was_told_is_refused(monkeypatch, fn, key, entry):
    spy = _Spy()
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: spy)
    with pytest.raises(ValueError):
        ledger_rpc(spy, fn, {key: entry}, firm_id=FIRM, client_id=CLIENT)
    assert spy.calls == []


def test_the_door_has_no_default_for_the_scope():
    for fn in (ledger_door.ledger_client, ledger_door.ledger_rpc):
        params = inspect.signature(fn).parameters
        for name in ("firm_id", "client_id"):
            assert params[name].default is inspect.Parameter.empty and params[name].kind is inspect.Parameter.KEYWORD_ONLY, (fn.__name__, name)


# ── the rule over the API's own source ───────────────────────────────────────────────────────────────────────────────
def _python_files():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).parts
        if rel[0] in ("tests", "venv", ".venv", "node_modules") or "__pycache__" in rel:
            continue
        yield path, "/".join(rel)


def _parsed():
    for path, rel in _python_files():
        try:
            yield rel, ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def test_no_rpc_call_names_a_ledger_function_by_literal_anywhere_but_the_door():
    sites = []
    for rel, tree in _parsed():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rpc" and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value in RPCS):
                sites.append((rel, node.args[0].value))
    assert sorted(sites) == [("services/ledger_door.py", "post_journal_atomic"), ("services/ledger_door.py", "settle_receipt_atomic")], (
        f"a ledger function is called on a client directly, not through services/ledger_door.ledger_rpc: {sites}")


def test_a_string_equal_to_a_ledger_function_is_code_only_in_the_door_and_the_two_call_sites():
    where = {}
    for rel, tree in _parsed():
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in RPCS and id(node) not in docs:
                where.setdefault(rel, []).append(node.lineno)
    assert sorted(where) == ["services/ledger_door.py", "services/phase2_journal_service.py", "services/receipt_service.py"], where


def test_each_of_the_two_call_sites_is_a_ledger_rpc_call_naming_its_firm_and_its_client():
    sites = []
    for rel, tree in _parsed():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "ledger_rpc":
                sites.append((rel, node))
    assert sorted(r for r, _n in sites) == ["services/phase2_journal_service.py", "services/receipt_service.py"], [(r, n.lineno) for r, n in sites]
    names = {r: n.args[1].value for r, n in sites if len(n.args) > 1 and isinstance(n.args[1], ast.Constant)}
    assert names == {"services/phase2_journal_service.py": "post_journal_atomic", "services/receipt_service.py": "settle_receipt_atomic"}, names
    for rel, node in sites:
        assert {k.arg for k in node.keywords} >= {"firm_id", "client_id"}, f"{rel}:{node.lineno} does not name its firm and its client"


def test_negative_control_the_old_shape_is_what_the_rules_catch():
    old = ast.parse('result = db.rpc("post_journal_atomic", {"p_entry": e})').body[0].value
    assert isinstance(old.func, ast.Attribute) and old.func.attr == "rpc" and old.args[0].value in RPCS


# ── /health says who is calling (so a deployment can be shown to be running the door before the signed-in grant is taken away) ──

def test_the_door_says_who_calls_in_one_word(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    assert ledger_door.door_words() == "server"
    monkeypatch.delenv("SUPABASE_URL")
    assert ledger_door.door_words() == "caller"
    monkeypatch.setenv("SUPABASE_URL", "")
    assert ledger_door.door_words() == "caller"


def test_health_carries_the_door_word_and_it_follows_the_configuration(monkeypatch):
    """Called without entering the TestClient context (that would run the lifespan and its boot thread), as the other health tests do."""
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "_SCHEMA_DRIFT", {"checked": True, "missing": []})
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    body = TestClient(main.app).get("/health").json()
    assert body["success"] is True and body["data"]["ledger_door"] == "server"
    monkeypatch.delenv("SUPABASE_URL")
    assert TestClient(main.app).get("/health").json()["data"]["ledger_door"] == "caller"
