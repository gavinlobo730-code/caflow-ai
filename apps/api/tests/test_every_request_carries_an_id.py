"""Every request carries an id: in the response, in one JSON log line, on the Sentry event and in a 5xx's body (ops-11).

THE FINDING
    "Logging is `logging.basicConfig` plain text with no request ID, no firm id, and no per-request latency line
    besides gunicorn's access log." A CA reporting that something failed at 11:05 could be answered only by
    reading every line near 11:05 and guessing. The verify line: *a request with a chosen X-Request-ID shows the
    same ID in the log line, the response header and, for a forced 500, the error body and Sentry event.*

WHAT THESE TESTS HOLD, AS RULES AND NOT AS SPELLINGS
    * the id is on EVERY response — a 200, a 404, a refusal, a 500, a 413 — and a caller's own id is echoed back
      when it is safe to log and replaced when it is not (a line break, a quote, a space, too long, too short);
    * there is exactly ONE access line per request, JSON, naming the route TEMPLATE and never the path or the
      query string as requested (a token can be in either), the firm once authentication has learnt it, and
      nothing that identifies a person;
    * a successful health probe writes no line and a failing one does;
    * a server-side failure's body keeps the `{success, data, error}` envelope and names the id inside `error`;
      a 4xx the database spoke for does not need one;
    * the firm is bound through a SYNC dependency, which runs on a worker thread with a COPY of the context —
      the case a bare ContextVar would fail;
    * the real Sentry client, with a capturing transport, receives the id and the firm as tags, and the access
      logger produces no event and no breadcrumb;
    * the layer sits inside CORS and outside the body limit, and is not a `BaseHTTPMiddleware`.

WHAT CANNOT BE TESTED HERE
    That Render's log search finds the line, and that a log drain retains it. Those are the human steps in
    docs/operations/finding-one-request.md.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
from pathlib import Path

import pytest
import sentry_sdk
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

import main
from core import observability as obs
from core.auth import get_current_user
from core.request_context import (
    ACCESS_LOGGER,
    REQUEST_ID_HEADER,
    SCOPE_KEY,
    RequestContextFormatter,
    _REQUEST_ID,
    accept_or_generate,
    begin,
    bind_firm,
    clean_request_id,
    current,
    end,
    install_record_factory,
)
from middleware.request_context import QUIET_ROUTES, RequestContextMiddleware, access_line

class ApiError(Exception):
    """Shaped like supabase-py's APIError — a SQLSTATE the catch-all can speak for (the same double the
    unhandled-failure tests use)."""

    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__({"code": code, "message": message})


API_ROOT = Path(__file__).resolve().parents[1]
ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")

# A token-shaped value in the PATH and one in the QUERY, built so a grep of this file for a "secret" finds
# nothing real. The access line must contain neither.
PATH_SECRET = "pathsegment" + "9f8e7d6c"
QUERY_SECRET = "querytoken" + "1a2b3c4d"


@pytest.fixture(scope="module")
def client():
    """Routes added to the REAL app, so the real middleware order is what is tested."""
    @main.app.get("/__ops11__/ok/{item}")
    def _ok(item: str, user: dict = Depends(get_current_user)):      # sync: runs on a worker thread
        return {"success": True, "data": {"item": item}, "error": None}

    @main.app.get("/__ops11__/boom/{item}")
    def _boom(item: str, user: dict = Depends(get_current_user)):
        raise KeyError("client_id")

    @main.app.get("/__ops11__/refused")
    def _refused():
        raise ApiError("23514", 'violates check constraint "engagements_status_check"')

    @main.app.get("/__ops11__/forbidden")
    def _forbidden():
        raise HTTPException(status_code=403, detail="no")

    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _dev_auth(dev_header_auth):
    return None


def app_text(caplog) -> str:
    """What the APPLICATION logged. The test client's own library (`httpx`) logs the URL it was asked for, which
    is the test's doing and not the server's, so it is not part of what these assertions are about."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("caflow"))


def access_lines(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == ACCESS_LOGGER]


@pytest.fixture()
def logs(caplog):
    caplog.set_level(logging.INFO)
    return caplog


FIRM = {"X-Firm-Id": "firm-7f3a"}


# ── the header ─────────────────────────────────────────────────────────────────

def test_a_chosen_id_comes_back_in_the_header_and_is_in_the_log_line(client, logs):
    res = client.get("/__ops11__/ok/a", headers={REQUEST_ID_HEADER: "support-trace-0001", **FIRM})
    assert res.status_code == 200
    assert res.headers[REQUEST_ID_HEADER] == "support-trace-0001"
    (line,) = access_lines(logs)
    assert line["request_id"] == "support-trace-0001"


def test_a_request_with_no_id_is_given_one_and_it_is_the_one_in_the_line(client, logs):
    res = client.get("/__ops11__/ok/a", headers=FIRM)
    generated = res.headers[REQUEST_ID_HEADER]
    assert ID_SHAPE.match(generated)
    assert access_lines(logs)[0]["request_id"] == generated


def test_two_requests_get_two_ids(client):
    first = client.get("/__ops11__/ok/a", headers=FIRM).headers[REQUEST_ID_HEADER]
    second = client.get("/__ops11__/ok/a", headers=FIRM).headers[REQUEST_ID_HEADER]
    assert first != second


@pytest.mark.parametrize("path,headers,status", [
    ("/__ops11__/ok/a", FIRM, 200),
    ("/__ops11__/refused", {}, 400),
    ("/__ops11__/forbidden", {}, 403),
    ("/__ops11__/boom/a", FIRM, 500),
    ("/this/route/does/not/exist", {}, 404),
    ("/health", {}, 200),
])
def test_the_id_is_on_every_response_whatever_its_status(client, path, headers, status):
    res = client.get(path, headers=headers)
    assert res.status_code == status
    assert ID_SHAPE.match(res.headers.get(REQUEST_ID_HEADER, "")), res.headers


def test_a_request_too_large_for_the_body_limit_still_gets_an_id_and_a_line(client, logs):
    """The layer is OUTSIDE the body limit, so a refusal it makes is traced like any other."""
    res = client.post("/__ops11__/ok/a", content=b"x",
                      headers={"Content-Length": str(33 * 1024 * 1024), REQUEST_ID_HEADER: "too-large-0001"})
    assert res.status_code == 413
    assert res.headers[REQUEST_ID_HEADER] == "too-large-0001"
    assert [l["status"] for l in access_lines(logs)] == [413]


def test_the_header_is_readable_by_the_browser():
    from fastapi.middleware.cors import CORSMiddleware
    kwargs = next(m.kwargs for m in main.app.user_middleware if m.cls is CORSMiddleware)
    exposed = {h.lower() for h in kwargs["expose_headers"]}
    assert REQUEST_ID_HEADER.lower() in exposed, (
        "the web app is on another origin; without this a browser cannot read the id off a failed response")


def test_a_cross_origin_response_exposes_the_header(client):
    origin = main._ALLOWED_ORIGINS[0]
    res = client.get("/__ops11__/ok/a", headers={"Origin": origin, **FIRM})
    assert REQUEST_ID_HEADER.lower() in res.headers.get("access-control-expose-headers", "").lower()


# ── an id a caller sends is validated, never trusted ───────────────────────────

UNSAFE = [
    "short",                                  # under 8
    "x" * 65,                                 # over 64
    "has a space in it",
    'quote"inside-an-id',
    "back\\slash-id-12",
    "<script>alert(1)</script>",
    "semi;colon-id-123",
    "ünïcode-id-12345",
]


@pytest.mark.parametrize("sent", UNSAFE)
def test_an_unsafe_id_is_replaced_and_never_written_anywhere(client, logs, sent):
    # As bytes: a header value is latin-1 on the wire, and httpx refuses to encode a str that is not ASCII.
    res = client.get("/__ops11__/ok/a", headers={REQUEST_ID_HEADER: sent.encode("latin-1"), **FIRM})
    assert res.status_code == 200, "a bad id must not fail the request"
    assert res.headers[REQUEST_ID_HEADER] != sent
    assert ID_SHAPE.fullmatch(res.headers[REQUEST_ID_HEADER])
    assert sent not in app_text(logs) and sent not in json.dumps(access_lines(logs))


def test_a_header_carrying_a_line_break_cannot_forge_a_log_line():
    """The attack the validation exists for, asserted on the function the middleware calls: a CRLF or a
    fragment of JSON is not an id, and the value that replaces it is."""
    for hostile in ("good-id-0001\r\nINFO:caflow.access:{}", 'a-id-0001","status":200,"x":"', "id\n" * 5):
        assert clean_request_id(hostile) is None
        assert ID_SHAPE.fullmatch(accept_or_generate(hostile))


def test_the_id_validation_accepts_what_support_would_send():
    for good in ("req-2026-10-01-1105", "3f2504e0-4f89-11d3-9a0c-0305e82c3301", "A1b2C3d4", "a.b_c-d.e_f-12"):
        assert clean_request_id(good) == good


# ── a line break is a line break WHEREVER it sits, including the last character ─
#
# Python's `$` matches at the end of the string AND just before a trailing "\n", so `^…$` with `.match` accepts
# "abcdefgh\n". That is the one place a validator written to keep a line break out of a header and a log line
# lets one in, and the existing cases all put the break in the MIDDLE (found by review of ops-11). The rule is
# stated on the three validators this feature owns, with every break the standard library treats as one.

BREAKS = ["\n", "\r", "\r\n", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]


@pytest.mark.parametrize("br", BREAKS)
def test_an_id_with_a_line_break_as_its_last_character_is_not_an_id(br):
    for body in ("abcdefgh", "a" * 64, "req-2026-10-01-1105"):
        assert clean_request_id(body) == body, "the premise: the same text without the break is fine"
        assert clean_request_id(body + br) is None, repr(body + br)
        assert clean_request_id(br + body) is None, repr(br + body)
        replaced = accept_or_generate(body + br)
        assert replaced != body + br and ID_SHAPE.fullmatch(replaced) and replaced == replaced.strip()


@pytest.mark.parametrize("br", BREAKS)
def test_a_firm_with_a_line_break_as_its_last_character_is_not_bound(br):
    token = begin("abcdefgh")
    try:
        bind_firm("firm-001" + br)
        assert current().firm_id is None
        bind_firm("firm-001")
        assert current().firm_id == "firm-001", "the premise: the same text without the break binds"
    finally:
        end(token)


@pytest.mark.parametrize("br", BREAKS)
def test_a_method_with_a_line_break_as_its_last_character_is_not_written(br):
    def line(method):
        return access_line(request_id="abcdefgh", firm_id=None, method=method, route="/x", status=200,
                           duration_ms=1.0)

    assert json.loads(line("GET"))["method"] == "GET", "the premise"
    assert json.loads(line("GET" + br))["method"] == "OTHER"


def _drive(raw_header: bytes, inner=None):
    """Run the REAL middleware against a hand-built ASGI scope and return what it sent and what was logged.

    Not through TestClient: httpx refuses a header value with a line break before it reaches the app, and the
    server in front of production strips one, so the only way to put a trailing "\n" in front of this layer is
    to hand it the scope, which is exactly what a different server, or a test, can do."""
    install_record_factory()
    formatter = RequestContextFormatter("%(levelname)s:%(name)s:%(message)s")
    written: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            if record.name.startswith("caflow"):            # not asyncio's own DEBUG chatter
                written.append(formatter.format(record))

    async def app(scope, receive, send):
        logging.getLogger("caflow.test").warning("something happened mid-request")
        if inner:
            inner(scope)
        await send({"type": "http.response.start", "status": 200, "headers": [(b"x-other", b"1")]})
        await send({"type": "http.response.body", "body": b""})

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [(b"x-request-id", raw_header)]}
    handler = _Capture(level=logging.DEBUG)
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        asyncio.run(RequestContextMiddleware(app)(scope, receive, send))
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
    headers = dict(sent[0]["headers"])
    return headers, written, scope


@pytest.mark.parametrize("sent_id", [b"abcdefgh\n", b"a" * 64 + b"\n", b"abcdefgh\r\n", b"abcdefgh\r"])
def test_the_middleware_never_puts_a_line_break_in_the_header_or_a_log_line(sent_id):
    """The reviewer's reproduction, end to end through the layer: the id with the trailing break is replaced, the
    response header and every line written during the request name the REPLACEMENT, and no line contains a
    break of its own beyond the one that ends it."""
    headers, written, scope = _drive(sent_id)
    echoed = headers[b"x-request-id"]
    assert echoed != sent_id
    assert ID_SHAPE.fullmatch(echoed.decode("ascii")), echoed
    assert scope[SCOPE_KEY] == echoed.decode("ascii")
    assert len(written) == 2, written                      # the mid-request line and the access line
    for text in written:
        assert "\n" not in text and "\r" not in text, repr(text)
        assert f"request_id={echoed.decode()}" in text or echoed.decode() in text
    assert json.loads(written[1].split(":", 2)[2])["request_id"] == echoed.decode()


def test_the_middleware_still_echoes_an_id_that_is_safe():
    headers, written, _ = _drive(b"support-trace-0001")
    assert headers[b"x-request-id"] == b"support-trace-0001"
    assert "[request_id=support-trace-0001]" in written[0]


def test_a_validator_anchored_with_a_dollar_is_applied_with_fullmatch():
    """The RULE behind the cases above, derived from the source so a fourth validator in these two modules is
    covered the day it is written: a compiled pattern ending in `$` that is applied with `.match` or `.search`
    accepts a trailing newline. `.fullmatch` (or `\\Z`) does not."""
    offenders: list[str] = []
    seen = 0
    for rel in ("core/request_context.py", "middleware/request_context.py"):
        tree = ast.parse((API_ROOT / rel).read_text())
        anchored: set[str] = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "compile"
                    and node.value.args and isinstance(node.value.args[0], ast.Constant)
                    and isinstance(node.value.args[0].value, str)
                    and node.value.args[0].value.endswith("$")
                    and not node.value.args[0].value.endswith("\\$")):
                anchored.update(t.id for t in node.targets if isinstance(t, ast.Name))
        seen += len(anchored)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in anchored
                    and node.func.attr in {"match", "search"}):
                offenders.append(f"{rel}:{node.lineno} {node.func.value.id}.{node.func.attr}")
    assert seen >= 3, "the three validators were not found: this guard has gone blind"
    assert not offenders, f"a `$`-anchored pattern accepts a trailing newline under match/search: {offenders}"


# ── the line ───────────────────────────────────────────────────────────────────

def test_one_request_is_one_line_and_it_says_what_happened(client, logs):
    client.get("/__ops11__/ok/a", headers={REQUEST_ID_HEADER: "one-line-0001", **FIRM})
    lines = access_lines(logs)
    assert len(lines) == 1
    line = lines[0]
    assert set(line) == {"event", "request_id", "firm_id", "method", "route", "status", "duration_ms"}
    assert line["event"] == "request" and line["method"] == "GET" and line["status"] == 200
    assert isinstance(line["duration_ms"], (int, float)) and line["duration_ms"] >= 0
    assert line["firm_id"] == "firm-7f3a"


def test_the_line_names_the_route_template_and_never_the_path_or_the_query(client, logs):
    client.get(f"/__ops11__/ok/{PATH_SECRET}?token={QUERY_SECRET}", headers=FIRM)
    (line,) = access_lines(logs)
    assert line["route"] == "/__ops11__/ok/{item}"
    everything = app_text(logs)
    assert PATH_SECRET not in everything, "a path segment can be a credential"
    assert QUERY_SECRET not in everything, "a query string can be a credential"


def test_a_request_nothing_matched_is_logged_as_unmatched_not_as_its_path(client, logs):
    client.get(f"/wp-admin/{PATH_SECRET}")
    (line,) = access_lines(logs)
    assert line["route"] == "<unmatched>" and line["status"] == 404
    assert PATH_SECRET not in app_text(logs)


def test_an_unauthenticated_request_has_no_firm_key_rather_than_a_null_one(client, logs):
    client.get("/__ops11__/refused")
    (line,) = access_lines(logs)
    assert "firm_id" not in line


def test_the_line_carries_nothing_that_identifies_a_person(client, logs):
    client.get("/__ops11__/ok/a", headers={**FIRM, "X-User-Id": "user-name@example.com",
                                           "User-Agent": "A Browser/1.0", "X-Forwarded-For": "203.0.113.9"})
    (line,) = access_lines(logs)
    blob = json.dumps(line)
    for private in ("example.com", "A Browser", "203.0.113.9", "user-name"):
        assert private not in blob
    assert set(line) <= {"event", "request_id", "firm_id", "method", "route", "status", "duration_ms"}


def test_a_server_failure_is_logged_at_warning_never_error(client, logs):
    """ERROR would be a Sentry event of its own, untagged, beside the one the catch-all reports."""
    client.get("/__ops11__/boom/a", headers=FIRM)
    (record,) = [r for r in logs.records if r.name == ACCESS_LOGGER]
    assert record.levelno == logging.WARNING
    assert json.loads(record.getMessage())["status"] == 500


def test_a_method_that_is_not_a_token_is_not_written():
    line = json.loads(access_line(request_id="abcdefgh", firm_id=None, method='G"E\nT', route="/x",
                                  status=200, duration_ms=1.0))
    assert line["method"] == "OTHER"


# ── the health probes ──────────────────────────────────────────────────────────

def test_a_successful_health_probe_writes_no_line(client, logs):
    client.get("/health")
    assert access_lines(logs) == []


def test_a_failing_health_probe_is_logged(client, logs, monkeypatch):
    monkeypatch.setattr(main, "_SCHEMA_DRIFT", {"checked": True, "missing": ["x.y"]})
    res = client.get("/health")
    assert res.status_code == 503
    assert [l["status"] for l in access_lines(logs)] == [503]


def test_the_quiet_routes_are_the_two_probes_a_monitor_polls():
    assert QUIET_ROUTES == {"/health", "/ready"}


# ── a 5xx names the request in its body ────────────────────────────────────────

def test_a_forced_500_carries_the_id_in_the_header_the_body_and_the_log(client, logs):
    res = client.get(f"/__ops11__/boom/{PATH_SECRET}?token={QUERY_SECRET}",
                     headers={REQUEST_ID_HEADER: "forced-500-0001", **FIRM})
    assert res.status_code == 500
    assert res.headers[REQUEST_ID_HEADER] == "forced-500-0001"
    body = res.json()
    assert set(body) == {"success", "data", "error"}, "the envelope is {success, data, error} and stays so"
    assert body["success"] is False and body["data"] is None
    assert body["error"].startswith("Internal server error")
    assert "forced-500-0001" in body["error"]
    (line,) = access_lines(logs)
    assert line["request_id"] == "forced-500-0001" and line["status"] == 500
    # The traceback's own line is findable by the same id, and names the route, not the URL.
    (unhandled,) = [r for r in logs.records if r.getMessage().startswith("Unhandled exception for")]
    assert unhandled.request_id == "forced-500-0001" and unhandled.firm_id == "firm-7f3a"
    assert "/__ops11__/boom/{item}" in unhandled.getMessage()
    assert PATH_SECRET not in app_text(logs) and QUERY_SECRET not in app_text(logs)


def test_a_refusal_the_database_spoke_for_needs_no_reference(client):
    res = client.get("/__ops11__/refused", headers={REQUEST_ID_HEADER: "refused-0001-x"})
    assert res.status_code == 400
    assert "reference" not in res.json()["error"]
    assert res.headers[REQUEST_ID_HEADER] == "refused-0001-x"


def test_the_catch_all_behind_the_middleware_names_the_id_too():
    """`global_exception_handler` runs in Starlette's outermost layer, OUTSIDE the ContextVar's reach: the id
    arrives on the scope, which every layer shares."""
    scope = {"type": "http", "method": "GET", "path": "/x", "query_string": b"", "headers": [],
             SCOPE_KEY: "outer-layer-0001"}
    response = asyncio.run(main.global_exception_handler(Request(scope), KeyError("boom")))
    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "outer-layer-0001"
    assert "outer-layer-0001" in json.loads(response.body)["error"]


def test_a_failure_with_no_request_behind_it_still_answers_in_the_envelope():
    scope = {"type": "http", "method": "GET", "path": "/x", "query_string": b"", "headers": []}
    response = asyncio.run(main.global_exception_handler(Request(scope), KeyError("boom")))
    assert response.status_code == 500
    assert json.loads(response.body) == {"success": False, "data": None, "error": "Internal server error"}
    assert REQUEST_ID_HEADER not in response.headers


# ── the firm, through a sync dependency ────────────────────────────────────────

def test_the_firm_set_on_a_worker_thread_reaches_the_line_the_middleware_writes(client, logs):
    """`get_current_user` is a sync def: FastAPI runs it on a worker thread with a COPY of the context. A bare
    ContextVar set there would never reach the middleware; the holder object is what makes this pass."""
    client.get("/__ops11__/ok/a", headers={"X-Firm-Id": "firm-on-a-thread"})
    assert access_lines(logs)[0]["firm_id"] == "firm-on-a-thread"


def test_a_firm_that_is_not_an_identifier_is_not_logged(client, logs):
    client.get("/__ops11__/ok/a", headers={"X-Firm-Id": 'Acme "Traders" Pvt'})
    assert "firm_id" not in access_lines(logs)[0]
    assert "Acme" not in app_text(logs)


def test_every_authentication_dependency_binds_the_firm():
    """The rule, over the principals that carry a firm. A new one that forgets is a request whose line cannot
    be found by firm."""
    need = {
        "core/auth.py": {"get_current_user"},
        "core/portal_auth.py": {"get_current_portal_client", "get_current_portal_employee"},
    }
    for rel, names in need.items():
        tree = ast.parse((API_ROOT / rel).read_text())
        found = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name in names:
                found[fn.name] = any(
                    isinstance(c, ast.Call) and getattr(c.func, "id", None) == "bind_firm" for c in ast.walk(fn))
        assert set(found) == names, f"{rel}: {names - set(found)} not found"
        assert all(found.values()), f"{rel}: does not bind the firm: {[n for n, ok in found.items() if not ok]}"


# ── the log record ─────────────────────────────────────────────────────────────

def test_a_record_written_during_a_request_carries_its_id_and_one_outside_does_not(client, logs):
    outside = logging.getLogger("caflow.test").makeRecord("caflow.test", logging.INFO, "f", 1, "m", (), None)
    assert outside.request_id is None and outside.request_context == ""
    client.get("/__ops11__/boom/a", headers={REQUEST_ID_HEADER: "record-0001-xx", **FIRM})
    inside = [r for r in logs.records if r.getMessage().startswith("Unhandled exception for")]
    assert inside and inside[0].request_id == "record-0001-xx"


def test_the_plain_format_gains_a_suffix_on_the_first_line_and_leaves_the_traceback_alone():
    fmt = RequestContextFormatter("%(levelname)s:%(name)s:%(message)s")
    try:
        raise ValueError("x")
    except ValueError:
        import sys
        record = logging.LogRecord("caflow.main", logging.ERROR, "f", 1, "it broke", (), sys.exc_info())
    record.request_context = " [request_id=abcdefgh firm_id=f1]"
    first, _, rest = fmt.format(record).partition("\n")
    assert first == "ERROR:caflow.main:it broke [request_id=abcdefgh firm_id=f1]"
    assert "Traceback" in rest and "request_id" not in rest


def test_a_line_from_before_the_factory_existed_formats_as_it_always_did():
    fmt = RequestContextFormatter("%(levelname)s:%(name)s:%(message)s")
    record = logging.LogRecord("caflow.main", logging.INFO, "f", 1, "plain", (), None)
    assert not hasattr(record, "request_context")
    assert fmt.format(record) == "INFO:caflow.main:plain"


def test_the_access_line_is_not_given_the_suffix_it_already_carries():
    fmt = RequestContextFormatter("%(levelname)s:%(name)s:%(message)s")
    record = logging.LogRecord(ACCESS_LOGGER, logging.INFO, "f", 1, '{"request_id":"abcdefgh"}', (), None)
    record.request_context = " [request_id=abcdefgh]"
    assert fmt.format(record) == f'INFO:{ACCESS_LOGGER}:{{"request_id":"abcdefgh"}}'


# ── Sentry: what a third party receives ────────────────────────────────────────

DSN = "https://publickey@o123.ingest.sentry.io/456"


@pytest.fixture()
def sent():
    """The REAL client with a transport that keeps what would have left (see test_the_posting_failure_alert_has_its_tags)."""
    events: list[dict] = []
    assert obs.init_error_reporting(DSN, environment="test", transport=events.append) is True
    try:
        yield events
    finally:
        sentry_sdk.flush()
        sentry_sdk.init()


def test_the_sentry_event_for_a_forced_500_carries_the_request_id_and_the_firm(client, sent):
    res = client.get("/__ops11__/boom/a", headers={REQUEST_ID_HEADER: "sentry-id-0001", **FIRM})
    sentry_sdk.flush()
    assert res.status_code == 500
    assert sent, "a 500 must reach Sentry"
    for event in sent:
        assert event["tags"]["request_id"] == "sentry-id-0001", event.get("logger")
        assert event["tags"]["firm_id"] == "firm-7f3a"
    # What is NOT turned on to make this possible: no user, no request body, no locals.
    for event in sent:
        assert "user" not in event
        assert "data" not in event.get("request", {})
    assert sentry_sdk.get_client().options["send_default_pii"] is False


def test_the_access_logger_makes_no_sentry_event_and_no_breadcrumb(client, sent):
    """Sentry's logging integration turns an ERROR record into an event and an INFO one into a breadcrumb; the
    access logger is ignored, so neither happens whatever level the line is written at."""
    access = logging.getLogger(ACCESS_LOGGER)
    access.error('{"event":"request","status":500}')
    sentry_sdk.flush()
    assert sent == [], [e.get("logger") for e in sent]
    access.info('{"event":"request","status":200}')
    sentry_sdk.capture_message("a later event")
    sentry_sdk.flush()
    (event,) = sent
    crumbs = (event.get("breadcrumbs") or {}).get("values") or []
    assert all(c.get("category") != ACCESS_LOGGER for c in crumbs)
    # And a request's own two lines add nothing beside the 500's events.
    sent.clear()
    client.get("/__ops11__/ok/a", headers=FIRM)
    sentry_sdk.flush()
    assert sent == []


# ── where it sits, and what it is ──────────────────────────────────────────────

def test_the_layer_is_inside_cors_and_outside_the_body_limit():
    from fastapi.middleware.cors import CORSMiddleware
    from middleware.body_limit import BodySizeLimitMiddleware
    stack = [m.cls for m in main.app.user_middleware]            # index 0 is the OUTERMOST
    assert stack.index(CORSMiddleware) < stack.index(RequestContextMiddleware) < stack.index(BodySizeLimitMiddleware)


def test_the_layer_is_pure_asgi_not_a_base_http_middleware():
    """CLAUDE.md records what BaseHTTPMiddleware does to a chunked body; BodySizeLimitMiddleware is pure ASGI for
    the same reason."""
    assert not issubclass(RequestContextMiddleware, BaseHTTPMiddleware)
    src = (API_ROOT / "middleware" / "request_context.py").read_text()
    code = ast.parse(src)
    imported = {a.name for n in ast.walk(code) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "BaseHTTPMiddleware" not in imported


def test_no_log_call_in_main_passes_the_url_or_the_query():
    """The rule behind `_failure_response` logging the route: `request.url` is the raw path and the query."""
    tree = ast.parse((API_ROOT / "main.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and getattr(node.func.value, "id", "") in {"_logger", "logging", "logger"}:
            for arg in ast.walk(node):
                if isinstance(arg, ast.Attribute) and arg.attr in {"url", "query_params", "path_params"} \
                        and getattr(arg.value, "id", "") == "request":
                    offenders.append(node.lineno)
    assert not offenders, f"main.py logs a URL at line(s) {offenders}"


def test_the_container_does_not_also_write_the_raw_request_line():
    """gunicorn's `--access-logfile` is the raw request line — path AND query — once per request, which is what
    the JSON line replaces. Keeping both would keep the leak."""
    lines = (API_ROOT / "Dockerfile").read_text().splitlines()
    cmd = "\n".join(l for l in lines if l.strip().startswith("CMD"))     # not the comment explaining its absence
    assert "gunicorn" in cmd
    assert "--access-logfile" not in cmd
    assert "--error-logfile" in cmd, "the error log is still wanted"


def test_the_browsers_copy_of_the_id_shape_is_the_servers():
    """The Schedule III caption lesson: a mirror is pinned from the side that owns the rule, because a guard
    written in apps/web would compare the file with a copy of itself."""
    web = API_ROOT.parents[1] / "apps" / "web" / "lib" / "api" / "requestReference.ts"
    assert f"/{_REQUEST_ID.pattern}/" in web.read_text(), (
        "lib/api/requestReference.ts shows an id only when it has the shape the server issues; the two patterns "
        "have drifted")
