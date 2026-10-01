"""/ready asks the database; /health never does; and they must stay two routes (ops-05).

THE GAP THIS CLOSES
    `/health` returns 200 with no database call once the process is up — by
    design, and pinned by test_health_answers_before_the_slow_boot.py. So an
    external monitor pointed at it says "all fine" while Postgres or PostgREST
    is down and every screen fails. `/ready` does one bounded request to the
    database with the service-role key and answers 503 within five seconds when
    it cannot.

WHAT IS PINNED, AND THE ONE THING NOT TO "SIMPLIFY"
    1. A database that ACCEPTS the connection and then never answers — the
       realistic outage, far more so than a refusal — gives 503 in under five
       seconds, while /health on the same app with the same hung URL still gives
       200 at once. That pair is the finding's own verify line.
    2. The probe tells three failures apart (config, database, auth), because a
       rotated service-role key and a dead database need different people.
    3. It sends the service-role key to the place the code reads it from and asks
       for one row of the tenant table, nothing heavier.
    4. The answer is reused for a few seconds: the route is unauthenticated on a
       public repository and spends a database round trip.
    5. Nothing about the deployment — URL, key — appears in the body.
    6. Render's `healthCheckPath` stays on /health. Pointing it at /ready would
       make Render pull a healthy instance out of rotation on a database blip,
       turning one dependency's outage into the whole service's.
    7. The probe does not borrow the shared service client, whose timeout is the
       library's 120 s and which every other caller depends on.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main as main_module
from core import readiness

KEY = "eyJ-test-service-role-key-not-a-secret"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fresh_cache_and_key(monkeypatch):
    readiness.reset_cache()
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", KEY)
    yield
    readiness.reset_cache()


class _Fake:
    """A stand-in PostgREST that records what it was asked and answers as told."""

    def __init__(self, status: int = 200, body: bytes = b"[]"):
        self.status, self.body = status, body
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):                                # noqa: N802
                outer.requests.append({"path": self.path, "headers": dict(self.headers)})
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *a):                        # silence
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class _Hang:
    """Accepts every connection and then says nothing, ever. A database that is
    up enough to take the TCP handshake and too wedged to answer."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.held: list[socket.socket] = []
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.held.append(conn)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.sock.getsockname()[1]}"

    def close(self):
        self._stop = True
        for c in self.held:
            c.close()
        self.sock.close()


@pytest.fixture()
def fake():
    f = _Fake()
    yield f
    f.close()


@pytest.fixture()
def hang():
    h = _Hang()
    yield h
    h.close()


def _client() -> TestClient:
    # No context manager: entering it would run the lifespan and start the boot
    # thread, which these tests have no business with.
    return TestClient(main_module.app)


def _closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


# ── 1. the finding's own verify line ────────────────────────────────────────────

def test_a_hung_database_is_503_within_five_seconds_and_health_is_still_200(hang, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", hang.url)
    c = _client()

    t0 = time.monotonic()
    ready = c.get("/ready")
    took = time.monotonic() - t0

    assert ready.status_code == 503
    assert took < 5.0, f"/ready took {took:.2f}s against a hung database; a monitor would time out first"
    body = ready.json()
    assert body["success"] is False
    assert body["data"]["status"] == "not_ready"
    assert body["data"]["failed"] == "database"
    assert body["data"]["reason"] == "timeout"
    assert body["error"], "a failure must carry a sentence"

    # The same app, the same hung URL: /health must not notice. If somebody
    # teaches /health to call Postgres this is the assertion that fails — it would
    # wait out the hang, and Render would pull a healthy instance on a DB blip.
    t0 = time.monotonic()
    health = c.get("/health")
    assert health.status_code == 200
    assert time.monotonic() - t0 < 1.0, "/health waited on the database"
    assert health.json()["data"]["status"] == "ok"


def test_a_refusing_host_is_503_unreachable(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", _closed_port_url())
    r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["data"]["failed"] == "database"
    assert r.json()["data"]["reason"] == "unreachable"


# ── 2. the three failures are told apart ────────────────────────────────────────

def test_a_database_that_answers_is_200_with_a_latency(fake, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    r = _client().get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["error"] is None
    data = body["data"]
    assert data["status"] == "ready"
    assert data["failed"] is None
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0
    assert data["reused"] is False


def test_a_rejected_service_key_is_an_auth_failure_not_a_database_one(fake, monkeypatch):
    fake.status, fake.body = 401, b'{"message":"Invalid API key"}'
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["data"]["failed"] == "auth", (
        "a rotated service-role key must not read as the database being down — "
        "restarting the database helps nobody")
    assert "key" in r.json()["error"].lower()


@pytest.mark.parametrize("status", [403, 404, 500, 502, 503])
def test_every_other_non_2xx_is_the_database_failing_with_the_code_in_the_reason(fake, monkeypatch, status):
    # 403 is the service role holding no GRANT on the probe table — the failure
    # "57 tables never granted to service_role" produced — and 5xx is PostgREST
    # or Postgres failing. Neither is an auth problem.
    fake.status, fake.body = status, b"{}"
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["data"]["failed"] == "database"
    assert r.json()["data"]["reason"] == f"http_{status}"


@pytest.mark.parametrize("unset", ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
def test_an_unset_connection_setting_is_a_config_failure_and_sends_nothing(fake, monkeypatch, unset):
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    monkeypatch.delenv(unset, raising=False)
    r = _client().get("/ready")
    assert r.status_code == 503
    assert r.json()["data"]["failed"] == "config"
    assert fake.requests == [], "a missing setting must not reach the network"


# ── 3. what it sends ────────────────────────────────────────────────────────────

def test_it_asks_for_one_row_of_the_tenant_table_with_the_service_role_key(fake, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    _client().get("/ready")
    assert len(fake.requests) == 1
    sent = fake.requests[0]
    assert sent["path"].startswith("/rest/v1/firms?"), sent["path"]
    assert "select=id" in sent["path"] and "limit=1" in sent["path"], (
        "a readiness probe must be a trivial read, not a report")
    h = {k.lower(): v for k, v in sent["headers"].items()}
    assert h["apikey"] == KEY
    assert h["authorization"] == f"Bearer {KEY}"


def test_the_probe_does_not_borrow_the_shared_service_client(fake, monkeypatch):
    """That client is shared, runs on the library's 120 s timeout, and a probe
    must not change either. If this route ever reaches for it, this raises."""
    import core.supabase_client as sc

    def _boom(*a, **k):
        raise AssertionError("the readiness probe used the shared service client")

    monkeypatch.setattr(sc, "_service_client", _boom)
    monkeypatch.setattr(sc, "get_service_supabase", _boom)
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    assert _client().get("/ready").status_code == 200


# ── 4. the cache ────────────────────────────────────────────────────────────────

def test_one_answer_is_reused_inside_the_ttl_and_says_so(fake, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    c = _client()
    first = c.get("/ready").json()["data"]
    second = c.get("/ready").json()["data"]
    assert len(fake.requests) == 1, (
        "two calls inside the TTL must cost ONE database round trip — this route "
        "is unauthenticated and would otherwise be a free query amplifier")
    assert first["reused"] is False and second["reused"] is True


def test_an_answer_is_not_reused_past_the_ttl(fake, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    now = [1000.0]
    clock = lambda: now[0]                                   # noqa: E731
    _, reused = readiness.check(clock)
    assert reused is False
    now[0] += readiness.CACHE_TTL_SECONDS - 0.1
    assert readiness.check(clock)[1] is True
    now[0] += 0.2
    assert readiness.check(clock)[1] is False
    assert len(fake.requests) == 2


def test_a_failure_is_cached_too_so_an_outage_is_not_hammered(monkeypatch):
    """The expensive case is the failing one — each probe can cost the full
    deadline — so it is the one that most needs to be rate-limited."""
    h = _Hang()
    try:
        monkeypatch.setenv("SUPABASE_URL", h.url)
        c = _client()
        t0 = time.monotonic()
        c.get("/ready")
        c.get("/ready")
        c.get("/ready")
        took = time.monotonic() - t0
        assert len(h.held) == 1, f"{len(h.held)} connections opened for three calls"
        assert took < 5.0, "the second and third call should have been instant"
    finally:
        h.close()


# ── 5. what it never says ───────────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ["ok", "auth", "down"])
def test_the_body_never_carries_the_url_or_the_key(fake, monkeypatch, scenario):
    if scenario == "auth":
        fake.status, fake.body = 401, b'{"message":"key %s rejected"}' % KEY.encode()
    url = _closed_port_url() if scenario == "down" else fake.url
    monkeypatch.setenv("SUPABASE_URL", url)
    text = _client().get("/ready").text
    assert KEY not in text
    assert url not in text
    assert "127.0.0.1" not in text


def test_the_envelope_is_the_products_own(fake, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", fake.url)
    body = _client().get("/ready").json()
    assert set(body) == {"success", "data", "error"}


# ── 6. the two routes stay two routes ───────────────────────────────────────────

def test_renders_health_check_stays_on_health_and_never_on_ready():
    text = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    paths = re.findall(r"^\s*healthCheckPath:\s*(\S+)\s*$", text, re.M)
    assert paths == ["/health"], (
        f"healthCheckPath is {paths}. It must be /health and only /health: Render "
        "reads it to decide whether to ROUTE to an instance, and a probe that "
        "needs the database would pull a healthy instance out on a database blip.")


def test_health_is_still_the_cheap_route_the_boot_test_pins():
    """Belt to test_health_answers_before_the_slow_boot's braces, stated from
    this side: no readiness code is reachable from the /health handler."""
    import inspect

    src = inspect.getsource(main_module.healthcheck)
    assert "readiness" not in src and "httpx" not in src and "supabase" not in src.lower()


def test_ready_is_unauthenticated_like_health():
    """A monitor has no JWT. Every route in this app that needs a caller declares
    it as a dependency, so the absence of any is what 'open' looks like — and it
    is the same shape /health has."""
    route = next(r for r in main_module.app.routes if getattr(r, "path", None) == "/ready")
    health = next(r for r in main_module.app.routes if getattr(r, "path", None) == "/health")
    assert route.dependant.dependencies == health.dependant.dependencies == []
    assert route.methods == {"GET"}
