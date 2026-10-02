"""Every API response carries nosniff, JSON is not cached, HSTS is sent only where it is true, and no header a route set is overwritten (security_privacy-05).

THE FINDING
    "There is no Content-Security-Policy, HSTS, X-Frame-Options, X-Content-Type-Options or Referrer-Policy
    anywhere ... no header middleware in the API. Add an API middleware for nosniff, HSTS and Cache-Control:
    no-store on JSON." (The two sites' half is `apps/web/scripts/the-sites-send-security-headers.test.ts` and
    `test_the_two_sites_send_the_same_security_posture.py`.)

WHAT THESE TESTS HOLD, AS RULES
    * nosniff is on every response — a route's own, a 404, a CORS preflight that `CORSMiddleware` answers
      without reaching any route, and the 429 a public limiter raises;
    * `Cache-Control: no-store` is on JSON and ONLY on JSON, and a route's own Cache-Control, of any value the
      tree actually sets, survives untouched and is never duplicated (the payslip door says
      `private, no-store` on purpose);
    * HSTS needs BOTH production and a request that came in secure, is 30 days, and carries neither
      `includeSubDomains` nor `preload` — a local run, the container's own health check over plain http and a
      non-production deployment never get it;
    * the layer is pure ASGI, sits OUTSIDE CORS (it generates no response, so it has no CORS header to lose,
      and outside is what covers a preflight) and does not read a body.

WHAT CANNOT BE TESTED HERE
    That Render's edge forwards `X-Forwarded-Proto: https` (the deployed host's `curl -I` is the check, in
    `docs/operations/edge-protection.md`), and what a browser does with the header.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

import main
from middleware.security_headers import HSTS_VALUE, SecurityHeadersMiddleware, hsts_applies

API_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://caflow-ai.pages.dev"


def _toy_app(*, cache_control: str | None = None) -> FastAPI:
    """A small app behind the real middleware, with one route per kind of answer."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/json")
    def _json():
        return JSONResponse({"success": True, "data": None, "error": None})

    @app.get("/json-own")
    def _json_own():
        headers = {"Cache-Control": cache_control} if cache_control is not None else {}
        return JSONResponse({"ok": True}, headers=headers)

    @app.get("/pdf")
    def _pdf():
        return Response(b"%PDF-1.4", media_type="application/pdf")

    @app.get("/csv-own")
    def _csv_own():
        return Response("a,b\n", media_type="text/csv", headers={"Cache-Control": "private, max-age=60"})

    @app.get("/problem")
    def _problem():
        return Response("{}", media_type="application/problem+json")

    @app.get("/own-nosniff")
    def _own_nosniff():
        return Response("x", media_type="text/plain", headers={"X-Content-Type-Options": "kept-as-the-route-set-it"})

    @app.get("/empty", status_code=204)
    def _empty():
        return Response(status_code=204)

    return app


def _headers_of(client, path, **kw):
    return client.get(path, **kw).headers


# ═══ nosniff and Cache-Control ════════════════════════════════════════════════

def test_every_answer_is_nosniff_whatever_it_is():
    client = TestClient(_toy_app())
    for path in ("/json", "/pdf", "/csv-own", "/problem", "/empty", "/no-such-route"):
        assert client.get(path).headers.get("x-content-type-options") == "nosniff", path


def test_json_is_not_cached_and_a_file_is_left_to_its_route():
    client = TestClient(_toy_app())
    assert client.get("/json").headers["cache-control"] == "no-store"
    assert client.get("/problem").headers["cache-control"] == "no-store"      # a +json type is JSON
    assert "cache-control" not in client.get("/pdf").headers                  # a download decides for itself
    assert "cache-control" not in client.get("/empty").headers                # nothing to cache


def test_a_header_the_route_set_is_never_overwritten_or_doubled():
    client = TestClient(_toy_app(cache_control="private, no-store"))
    r = client.get("/json-own")
    assert r.headers.get_list("cache-control") == ["private, no-store"]
    assert client.get("/csv-own").headers.get_list("cache-control") == ["private, max-age=60"]
    assert client.get("/own-nosniff").headers.get_list("x-content-type-options") == ["kept-as-the-route-set-it"]


def _cache_control_values_the_tree_sets() -> set[str]:
    """Every literal value a router or service gives a Cache-Control header, read off the source."""
    values: set[str] = set()
    for path in list((API_ROOT / "routers").glob("*.py")) + list((API_ROOT / "services").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values, strict=True):
                    if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                            and k.value.lower() == "cache-control"
                            and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                        values.add(v.value)
    return values


def test_the_tree_does_set_cache_control_somewhere():
    """Vacuity guard: the next test is over what this finds, so it must find the payslip door's value."""
    assert "private, no-store" in _cache_control_values_the_tree_sets()


@pytest.mark.parametrize("value", sorted(_cache_control_values_the_tree_sets()))
def test_every_cache_control_the_tree_sets_reaches_the_caller_unchanged(value):
    client = TestClient(_toy_app(cache_control=value))
    assert client.get("/json-own").headers.get_list("cache-control") == [value]


# ═══ HSTS: only where it is true, and not as strong as it could be ═══════════

def _scope(scheme="http", xfp: list[str] | None = None):
    headers = [(b"x-forwarded-proto", v.encode()) for v in (xfp or [])]
    return {"type": "http", "scheme": scheme, "headers": headers}


def test_hsts_needs_production_and_a_secure_request(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert hsts_applies(_scope("https"))
    assert hsts_applies(_scope("http", ["https"]))
    assert not hsts_applies(_scope("http"))                                   # nothing says it was secure
    assert not hsts_applies(_scope("http", ["http"]))
    # The RIGHT-most entry is the one the nearest proxy wrote; the left of it is whatever the caller sent.
    assert hsts_applies(_scope("http", ["http, https"]))
    assert not hsts_applies(_scope("http", ["https, http"]))
    for env in ("development", "staging", "test", ""):
        monkeypatch.setenv("APP_ENV", env)
        assert not hsts_applies(_scope("https", ["https"])), env
    monkeypatch.delenv("APP_ENV")
    assert not hsts_applies(_scope("https", ["https"]))                       # unset is not production here


def test_the_hsts_value_is_modest_and_binds_no_other_host():
    assert HSTS_VALUE.startswith("max-age=")
    seconds = int(HSTS_VALUE.split("=")[1].split(";")[0])
    assert 86400 <= seconds <= 31536000, "30 days is the deliberate first step; raising it is a decision"
    lowered = HSTS_VALUE.lower()
    assert "includesubdomains" not in lowered, "no one has shown every sibling hostname is https-only"
    assert "preload" not in lowered, "a preload entry is permanent"


def test_the_header_is_sent_on_a_secure_production_request_and_on_no_other(monkeypatch):
    client = TestClient(_toy_app())
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get("/json", headers={"X-Forwarded-Proto": "https"}).headers["strict-transport-security"] == HSTS_VALUE
    assert "strict-transport-security" not in client.get("/json").headers
    monkeypatch.setenv("APP_ENV", "development")
    assert "strict-transport-security" not in client.get("/json", headers={"X-Forwarded-Proto": "https"}).headers


def test_a_route_that_sets_its_own_hsts_keeps_it(monkeypatch):
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def _x():
        return JSONResponse({}, headers={"Strict-Transport-Security": "max-age=1"})

    monkeypatch.setenv("APP_ENV", "production")
    r = TestClient(app).get("/x", headers={"X-Forwarded-Proto": "https"})
    assert r.headers.get_list("strict-transport-security") == ["max-age=1"]


# ═══ on the real app ═════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def real():
    return TestClient(main.app, raise_server_exceptions=False)


def test_the_real_apps_health_answer_is_nosniff_and_not_cached(real):
    r = real.get("/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_a_cors_preflight_the_middleware_answers_itself_is_nosniff_and_keeps_its_cors_headers(real):
    r = real.options("/api/clients", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_a_refusal_the_app_builds_still_carries_the_cors_header_and_the_security_headers(real):
    """A 404 is built inside every layer; it must come out with both sets."""
    r = real.get("/api/no-such-route", headers={"Origin": ORIGIN})
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_dev_and_test_runs_never_get_hsts_from_the_real_app(real, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    assert "strict-transport-security" not in real.get("/health", headers={"X-Forwarded-Proto": "https"}).headers


def test_the_real_app_sends_hsts_in_production_behind_a_tls_terminator(real, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    r = real.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"] == HSTS_VALUE


# ═══ where it sits, and what it is ═══════════════════════════════════════════

def test_the_layer_is_outside_cors_because_it_generates_nothing():
    from fastapi.middleware.cors import CORSMiddleware
    stack = [m.cls for m in main.app.user_middleware]            # index 0 is the OUTERMOST
    assert SecurityHeadersMiddleware in stack
    assert stack.index(SecurityHeadersMiddleware) < stack.index(CORSMiddleware)


def test_the_layer_is_pure_asgi_and_never_reads_a_body():
    assert not issubclass(SecurityHeadersMiddleware, BaseHTTPMiddleware)
    src = (API_ROOT / "middleware" / "security_headers.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "BaseHTTPMiddleware" not in imported
    # It wraps `send` and never calls `receive`: a chunked body is the other layers' business.
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "receive"]
    assert not calls
    assert "http.request" not in src.replace('"""', "").split("class SecurityHeadersMiddleware", 1)[1]


def test_it_leaves_a_websocket_or_lifespan_scope_alone():
    import asyncio
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    mw = SecurityHeadersMiddleware(inner)

    async def go():
        await mw({"type": "lifespan"}, None, None)
        await mw({"type": "websocket"}, None, None)

    asyncio.run(go())
    assert seen == ["lifespan", "websocket"]
