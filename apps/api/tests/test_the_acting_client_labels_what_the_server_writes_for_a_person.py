"""The privileged client labels each statement with the person the request acts for (POST-A-339, migration 547).

WHAT IS HELD
    * THE LABEL REALLY LEAVES THE CLIENT. A real supabase client (the library the API runs) is given a transport that records what it
      is asked to send; every one of the five verbs, a chain of filters, `single()` and `maybe_single()`, and `rpc` goes out with the
      header `x-acting-auth-user` carrying the person. This is the half of the claim that Python can prove; that the hosted API
      forwards the header to the database is what `/health` (`audit_actor`) says about a deployment, and what migration 547's
      probe returns.
    * THE NAME IS THE MIGRATION'S: `ACTING_HEADER` is the string migration 547's reader looks for, read from the migration text.
    * NO REQUEST, NO LABEL: a job has no person, so the client it gets is the plain one and nothing is sent.
    * `privileged_for(db)` answers the caller's own `db` where no database is configured (mock mode and the doubles), the privileged
      client where one is, and that client wrapped to label where a person is in flight.
    * A double without request headers is not broken by the label, and a wrapped client still hands out everything else it has.
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from postgrest.utils import SyncClient

from core import db_provider, request_actor
from core.acting_client import ACTING_HEADER, ActingClient, acting_as_request_person

API = Path(__file__).resolve().parents[1]
WHO = "99999999-0000-0000-0000-000000000001"


def _client(seen: list):
    """A real supabase client whose PostgREST session sends to a recording transport instead of the network."""
    from supabase import create_client

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"id": "1"}])

    client = create_client("http://db.test", "header.payload.signature")
    session = SyncClient(base_url=client.postgrest.session.base_url, headers=client.postgrest.session.headers,
                         transport=httpx.MockTransport(handler))
    client.postgrest.session = session
    return client


def _labels(seen) -> list[str | None]:
    return [r.headers.get(ACTING_HEADER) for r in seen]


@pytest.mark.parametrize("build", [
    lambda c: c.table("bank_accounts").select("*").eq("firm_id", "f").execute(),
    lambda c: c.table("bank_accounts").insert({"firm_id": "f"}).execute(),
    lambda c: c.table("bank_accounts").update({"is_active": False}).eq("id", "1").eq("firm_id", "f").execute(),
    lambda c: c.table("bank_accounts").upsert({"id": "1", "firm_id": "f"}).execute(),
    lambda c: c.table("bank_accounts").delete().eq("id", "1").execute(),
    lambda c: c.table("bank_accounts").select("id").eq("id", "1").limit(1).execute(),
    lambda c: c.table("bank_accounts").select("id").eq("id", "1").single().execute(),
    lambda c: c.table("bank_accounts").select("id").eq("id", "1").maybe_single().execute(),
    lambda c: c.from_("bank_accounts").select("*").execute(),
    lambda c: c.rpc("bank_register", {"p_firm_id": "f"}).execute(),
], ids=["select", "insert", "update", "upsert", "delete", "limit", "single", "maybe_single", "from_", "rpc"])
def test_every_statement_the_wrapped_client_makes_goes_out_labelled(build):
    seen: list = []
    build(ActingClient(_client(seen), WHO))
    assert len(seen) == 1 and _labels(seen) == [WHO], _labels(seen)


def test_the_plain_client_sends_no_label():
    seen: list = []
    _client(seen).table("bank_accounts").select("*").execute()
    assert _labels(seen) == [None]


def test_two_requests_never_share_a_label():
    """The label rides on the request builder, not on the shared session, so one person's statement cannot carry another's."""
    seen: list = []
    base = _client(seen)
    a, b = ActingClient(base, "aaaa"), ActingClient(base, "bbbb")
    a.table("bank_accounts").select("*").execute()
    b.table("bank_accounts").select("*").execute()
    base.table("bank_accounts").select("*").execute()
    assert _labels(seen) == ["aaaa", "bbbb", None]


def test_the_header_name_is_the_one_migration_547_reads():
    text = next(p for p in (API / "migrations").glob("547_a_plain_table_write_the_server_makes_for_a_person*.sql")
                if not p.name.endswith("_rollback.sql")).read_text()
    assert re.search(rf"->> '{re.escape(ACTING_HEADER)}'", text), "the migration reads another header than the client sends"
    assert ACTING_HEADER == ACTING_HEADER.lower(), "PostgREST lower-cases header names; an upper-case constant would never match"


# ── who the label names ──────────────────────────────────────────────────────────────────────────────────────────────
def test_with_no_request_in_flight_the_client_is_returned_as_it_is():
    sentinel = object()
    assert request_actor.current_auth_user_id() is None
    assert acting_as_request_person(sentinel) is sentinel


def test_with_a_person_in_flight_the_client_is_wrapped_and_names_that_person():
    token = request_actor.begin()
    try:
        request_actor.bind(WHO)
        wrapped = acting_as_request_person(object())
        assert isinstance(wrapped, ActingClient) and wrapped._who == WHO
    finally:
        request_actor.end(token)


def test_a_request_where_nobody_has_been_verified_yet_sends_no_label():
    token = request_actor.begin()
    try:
        sentinel = object()
        assert acting_as_request_person(sentinel) is sentinel
    finally:
        request_actor.end(token)


# ── privileged_for ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_privileged_for_answers_the_callers_own_double_when_no_database_is_configured(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    mine = object()
    assert db_provider.privileged_for(mine) is mine


def test_privileged_for_answers_the_privileged_client_with_a_database_and_labels_it_for_a_person(monkeypatch):
    from core import supabase_client
    plain = object()
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.test")
    monkeypatch.setattr(supabase_client, "get_service_supabase", lambda: plain)
    assert db_provider.privileged_for(object()) is plain            # a job: no person, the plain client
    token = request_actor.begin()
    try:
        request_actor.bind(WHO)
        got = db_provider.privileged_for(object())
        assert isinstance(got, ActingClient) and got._client is plain and got._who == WHO
    finally:
        request_actor.end(token)


# ── the wrapper is transparent to everything but the label ───────────────────────────────────────────────────────────
class _Builder:
    def __init__(self):
        self.calls = []

    def select(self, *a, **k):
        self.calls.append(("select", a, k))
        return self

    def eq(self, *a):
        self.calls.append(("eq", a))
        return self


class _Double:
    storage = "STORAGE"

    def table(self, name):
        self.last = _Builder()
        return self.last


def test_a_double_whose_builders_have_no_headers_is_not_broken_and_other_attributes_pass_through():
    double = _Double()
    wrapped = ActingClient(double, WHO)
    out = wrapped.table("bank_accounts").select("*").eq("id", "1")
    assert out is double.last and double.last.calls == [("select", ("*",), {}), ("eq", ("id", "1"))]
    assert wrapped.storage == "STORAGE"


def test_a_builder_whose_headers_are_not_a_mapping_is_left_alone():
    class Odd(_Builder):
        headers = "not a mapping"

    class D(_Double):
        def table(self, name):
            self.last = Odd()
            return self.last

    ActingClient(D(), WHO).table("x").select("*")                     # does not raise


# ── the probe: what /health says about the header reaching the database ──────────────────────────────────────────────
from core import audit_actor_probe as probe  # noqa: E402


@pytest.mark.parametrize("answer,word", [
    ({"role": "service_role", "header": probe.PROBE_LABEL}, "carried"),
    ({"role": "service_role", "header": None}, "not_seen"),
    ({"role": "service_role", "header": "someone else's label"}, "not_seen"),
    ({"role": "authenticated", "header": probe.PROBE_LABEL}, "wrong_role"),
    ({"role": None, "header": probe.PROBE_LABEL}, "wrong_role"),
    (None, "failed"),
    ([], "failed"),
    ("carried", "failed"),
])
def test_the_probe_names_what_the_database_saw(answer, word):
    assert probe.judge(answer) == word


class _Rpc:
    def __init__(self, data=None, raises=None):
        self._data, self._raises = data, raises
        self.headers = {}

    def execute(self):
        if self._raises:
            raise self._raises
        return type("R", (), {"data": self._data})()


class _ProbeClient:
    def __init__(self, data=None, raises=None):
        self._data, self._raises, self.asked = data, raises, None

    def rpc(self, fn, params=None, *a, **k):
        self.asked = (fn, params)
        self.sent = _Rpc(self._data, self._raises)
        return self.sent


def test_the_probe_asks_the_one_function_with_its_own_label_and_remembers_the_word():
    seen = _ProbeClient({"role": "service_role", "header": probe.PROBE_LABEL})
    assert probe.run(seen) == "carried" and probe.words() == "carried"
    assert seen.asked == ("audit_actor_probe", {}) and seen.sent.headers == {ACTING_HEADER: probe.PROBE_LABEL}


def test_a_probe_that_cannot_be_answered_is_failed_and_does_not_raise():
    assert probe.run(_ProbeClient(raises=RuntimeError("boom"))) == "failed" and probe.words() == "failed"


def test_with_no_database_the_probe_is_unchecked(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert probe.run() == "unchecked" and probe.words() == "unchecked"


def test_the_health_page_carries_the_word(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    monkeypatch.setattr(probe, "_state", {"words": "carried"})
    body = TestClient(main.app).get("/health").json()
    assert body["data"]["audit_actor"] == "carried", body


def test_the_watcher_asks_the_probe_when_the_schema_verdict_turns_healthy_later(monkeypatch):
    """A deploy that booted before migration 547 landed could not ask (the probe is a function that migration creates). The drift
    watcher is what learns the schema is in order, so it is what asks, and only until the answer is `carried`."""
    import main
    asked = []
    monkeypatch.setattr(probe, "run", lambda *a, **k: asked.append(1) or "carried")
    monkeypatch.setattr(probe, "_state", {"words": "unchecked"})
    monkeypatch.setattr(main, "_SCHEMA_DRIFT", {"checked": False, "missing": []})
    main._apply_schema_drift({"checked": True, "missing": ["a_function_the_code_names"]})
    assert asked == [], "asked while the schema is still short of a function"
    main._apply_schema_drift({"checked": False, "missing": []})
    assert asked == [], "asked before the schema was checked at all"
    main._apply_schema_drift({"checked": True, "missing": []})
    assert asked == [1]
    probe._state["words"] = "carried"
    main._apply_schema_drift({"checked": True, "missing": []})
    assert asked == [1], "asked again after the answer was already `carried`"
