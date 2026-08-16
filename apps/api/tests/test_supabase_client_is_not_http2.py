"""
The Supabase client must not speak HTTP/2.

WHAT HAPPENED
    postgrest 0.18's create_session hardcodes http2=True and h2 is in our
    requirements, so every Supabase call multiplexed over ONE HTTP/2 connection.
    core.supabase_client caches a single service-role client in a module global,
    and FastAPI runs our sync `def` endpoints in a threadpool — so many threads
    drove that one connection at once. The h2 state machine does not survive
    that; frames from different streams interleave and it ends up parsing a
    request's pseudo-headers as a response trailer:

        LocalProtocolError: Received pseudo-header in trailer
        {b':scheme', b':method', b':path', b':authority'}

    Production, GET /api/accounting/profit-loss, raised out of core.auth's firm
    status lookup — which then swallowed it and admitted the request (see
    test_auth_lookup_failure_is_not_a_403.py for that half).

WHY A TEST AND NOT JUST THE FIX
    The failure is load-dependent, so no functional test will ever reproduce it;
    what can be pinned is the property that prevents it. A dependency bump that
    reinstates http2=True, or a refactor that stops calling _force_http1, brings
    the whole class back silently — the app would work perfectly in every test
    and corrupt itself only under concurrent production traffic.
"""
from __future__ import annotations

import pytest

import core.supabase_client as sc


class _FakeSession:
    """Stands in for postgrest's httpx client."""

    def __init__(self):
        self.base_url = "https://example.supabase.co/rest/v1"
        self.headers = {"apikey": "k"}
        self.timeout = 30
        self.closed = False

    def close(self):
        self.closed = True


class _FakePostgrest:
    def __init__(self):
        self.session = _FakeSession()


class _FakeClient:
    def __init__(self):
        self.postgrest = _FakePostgrest()


def test_the_rebuilt_session_has_http2_off():
    client = sc._force_http1(_FakeClient())

    session = client.postgrest.session
    # httpx records the negotiated protocols on the transport's pool.
    pool = session._transport._pool
    assert pool._http2 is False, "HTTP/2 is still enabled — the concurrency bug is back"
    assert pool._http1 is True, "HTTP/1.1 must stay on, or nothing can talk to PostgREST"


def test_the_original_session_is_closed_rather_than_leaked():
    original = _FakeClient()
    leaked = original.postgrest.session

    sc._force_http1(original)

    assert leaked.closed, "the replaced session was left holding its connections"


def test_connection_settings_survive_the_rebuild():
    """A rebuild that dropped the auth headers or the base URL would break every
    query — loudly, but only at runtime."""
    client = sc._force_http1(_FakeClient())

    session = client.postgrest.session
    assert str(session.base_url).startswith("https://example.supabase.co")
    assert session.headers.get("apikey") == "k"


def test_a_client_without_a_postgrest_session_is_left_alone():
    """Defensive: supabase-py's internals are not ours. If the shape changes we
    log and carry on rather than refusing to start."""
    class _Shapeless:
        pass

    assert sc._force_http1(_Shapeless()) is not None


def test_postgrest_still_defaults_to_http2_so_this_fix_is_still_needed():
    """The canary. If a future postgrest turns http2 off itself, this fails and
    whoever sees it can delete _force_http1 instead of carrying it forever.
    """
    import inspect
    from postgrest._sync.client import SyncPostgrestClient

    src = inspect.getsource(SyncPostgrestClient.create_session)
    assert "http2=True" in src, (
        "postgrest no longer forces HTTP/2 — re-check whether "
        "core.supabase_client._force_http1 is still doing anything")


# ── the wiring, not just the helper ──────────────────────────────────────────
# Everything above tests _force_http1 in isolation, which would keep passing if
# someone deleted the CALL to it. These build the clients the app actually uses.
# create_client does no I/O — it only assembles objects — so this needs no
# network and no real project.

@pytest.fixture
def _fake_supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJfake.service.key")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "eyJfake.anon.key")
    monkeypatch.setattr(sc, "_client", None)   # the module-global singleton
    yield
    monkeypatch.setattr(sc, "_client", None)


def _http2_enabled(client) -> bool:
    return client.postgrest.session._transport._pool._http2


def test_the_shared_service_client_is_built_without_http2(_fake_supabase_env):
    """The one that mattered: cached in a module global and shared by every
    threadpool worker, which is precisely what HTTP/2 could not survive."""
    assert _http2_enabled(sc.get_service_supabase()) is False


def test_the_per_user_client_is_built_without_http2(_fake_supabase_env):
    """Shorter-lived, but a request can still fan out concurrent queries, and
    there is no reason for the two paths to differ."""
    assert _http2_enabled(sc.get_user_supabase("eyJfake.user.token")) is False


def test_the_per_user_client_still_carries_the_callers_token(_fake_supabase_env):
    """Rebuilding the session before postgrest.auth() would silently drop the
    JWT and quietly downgrade every RLS-scoped query to the anon role."""
    client = sc.get_user_supabase("eyJfake.user.token")

    assert "eyJfake.user.token" in client.postgrest.session.headers.get("Authorization", "")
