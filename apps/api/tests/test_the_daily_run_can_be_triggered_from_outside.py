"""The 06:00 IST run can be started by something other than the process it runs in (ops-15).

WHAT WAS WRONG
    The daily sweep fires from an in-process timer, so it runs only if the process is alive at
    06:00. On the free tier it is asleep unless something wakes it, and the only thing that did
    was a GitHub Actions cron that started 3.5 to 5.5 hours late. Boot-time catch-up makes the
    day COMPLETE; it cannot make it PUNCTUAL, and a restart at 06:00 during a deploy loses the
    timer for the day. `POST /api/scheduler/run` could not be the external trigger: it needs a
    person's JWT, which expires hourly (the wake workflow's own header records why that was
    abandoned).

WHAT IS ASSERTED
    * with no token configured the endpoint is a 503 and runs nothing — never an open door — and
      so is a configured token shorter than 32 characters;
    * a missing or wrong token is a 401 and runs nothing; the comparison is constant-time on
      bytes (a non-ASCII value is a 401, not a 500); wrong ones from one address are throttled
      to a 429 with Retry-After while the right one still passes (only failures are counted);
    * the right token starts the run (once, in the background) and answers in the standard
      envelope; a GET is a 405;
    * it has no human-JWT dependency (read off the route's own dependency tree), and the token is
      never written to a log line;
    * `GET /api/scheduler/status` says whether the trigger is configured, as a boolean and never
      the value;
    * the variable is declared in render.yaml with `sync: false`;
    * the route is mounted on the real app.

WHAT CANNOT BE ASSERTED HERE
    That an external scheduler exists and calls it. That is the human step (see the answer to the
    finding), and the finding's own verify line — scheduler_runs rows starting between 06:00 and
    06:10 IST on fourteen consecutive days without the wake workflow — is an outcome over time.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.scheduler_trigger as trig
from routers.scheduler_trigger import router

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
GOOD = "t" * 40
URL = "/api/internal/scheduler/run-pending"


@pytest.fixture
def started(monkeypatch):
    """Replace the run itself: what is asserted is whether the endpoint STARTS one."""
    calls: list[dict] = []

    def fake(*, background=True):
        calls.append({"background": background})
        return {"started": True, "reason": "started in background", "pending": 3}

    monkeypatch.setattr("jobs.scheduler.run_pending_now", fake)
    trig._reset_failures()
    yield calls
    trig._reset_failures()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _post(client, token=None, **kw):
    headers = {} if token is None else {"X-Scheduler-Token": token}
    return client.post(URL, headers=headers, **kw)


# ── never an open door ───────────────────────────────────────────────────────

def test_with_no_token_configured_every_caller_gets_503_and_nothing_runs(client, started, monkeypatch):
    monkeypatch.delenv("SCHEDULER_TRIGGER_TOKEN", raising=False)
    for token in (None, "", GOOD, "anything"):
        r = _post(client, token)
        assert r.status_code == 503, (token, r.status_code)
    assert started == []


def test_a_blank_configured_token_is_the_same_as_none(client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", "   ")
    assert _post(client, "   ").status_code == 503
    assert _post(client, "").status_code == 503
    assert started == []


def test_a_configured_token_that_is_too_short_is_refused_as_misconfiguration(client, started, monkeypatch):
    short = "x" * (trig.MIN_TOKEN_LENGTH - 1)
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", short)
    r = _post(client, short)
    assert r.status_code == 503, "the correct token of a too-short secret must not be accepted"
    assert started == []
    assert trig.token_configured() is False
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", "x" * trig.MIN_TOKEN_LENGTH)
    assert trig.token_configured() is True


# ── who is let in ────────────────────────────────────────────────────────────

def test_a_missing_or_wrong_token_is_401_and_runs_nothing(client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    assert _post(client).status_code == 401
    assert _post(client, "").status_code == 401
    assert _post(client, "t" * 39).status_code == 401
    assert _post(client, "t" * 41).status_code == 401
    assert _post(client, "u" * 40).status_code == 401
    assert started == []


def test_a_user_bearer_token_is_not_a_scheduler_token(client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    r = client.post(URL, headers={"Authorization": f"Bearer {GOOD}"})
    assert r.status_code == 401, "the token is read from X-Scheduler-Token only"
    assert started == []


def test_the_right_token_starts_one_run_in_the_background(client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    r = _post(client, GOOD)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["error"] is None
    assert body["data"] == {"started": True, "reason": "started in background", "pending": 3}
    assert [c["background"] for c in started] == [True]


def test_surrounding_whitespace_in_the_header_is_forgiven_and_in_the_middle_is_not(client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    assert _post(client, f"  {GOOD}  ").status_code == 200
    assert _post(client, "t" * 20 + " " + "t" * 19).status_code == 401


def test_a_get_is_not_a_trigger(client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    r = client.get(URL, headers={"X-Scheduler-Token": GOOD})
    assert r.status_code == 405
    assert started == []


def test_the_comparison_is_constant_time_on_bytes_so_a_non_ascii_value_is_a_401_not_a_500(monkeypatch):
    """`hmac.compare_digest` on two `str`s raises TypeError for a non-ASCII one; on bytes it does
    not. A 500 here would be an unauthenticated way to make the route throw."""
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    trig._reset_failures()

    class _Req:
        headers: dict = {}
        client = None

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        trig.require_trigger_token(_Req(), "tök€en" * 8)
    assert exc.value.status_code == 401
    src = (API / "routers" / "scheduler_trigger.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "compare_digest"]
    assert len(calls) == 1
    assert all(isinstance(a, ast.Call) and a.func.attr == "encode" for a in calls[0].args), (
        "both sides of the comparison must be bytes")
    compares = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
                and any(isinstance(op, ast.Eq) for op in n.ops)
                and {"provided", "expected"} <= {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}]
    assert compares == [], "the secret must not be compared with =="


# ── what a stranger can cost ────────────────────────────────────────────────

def test_wrong_tokens_from_one_address_are_throttled_and_the_right_one_still_passes(
        client, started, monkeypatch):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    codes = [_post(client, "wrong" * 8).status_code for _ in range(trig.FAILED_PER_IP_MAX + 3)]
    assert codes[: trig.FAILED_PER_IP_MAX] == [401] * trig.FAILED_PER_IP_MAX
    assert set(codes[trig.FAILED_PER_IP_MAX:]) == {429}
    limited = _post(client, "wrong" * 8)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) == trig.FAILED_WINDOW_SECONDS
    # Only failures are counted: the real caller is never throttled by what a stranger does.
    assert _post(client, GOOD).status_code == 200
    assert len(started) == 1


def test_a_stranger_leaves_a_log_line_and_the_token_is_never_in_it(client, started, monkeypatch, caplog):
    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    wrong = "w" * 40
    with caplog.at_level(logging.DEBUG):
        _post(client, wrong)
        _post(client, GOOD)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "refused" in text
    assert wrong not in text and GOOD not in text


# ── no human in the loop ─────────────────────────────────────────────────────

def _dependency_names(route) -> set[str]:
    names: set[str] = set()

    def walk(dep):
        names.add(getattr(dep.call, "__name__", repr(dep.call)))
        for sub in dep.dependencies:
            walk(sub)

    walk(route.dependant)
    return names


def test_the_route_has_no_human_jwt_dependency():
    route = next(r for r in router.routes if r.path == URL)
    names = _dependency_names(route)
    assert "require_trigger_token" in names
    assert not names & {"get_current_user", "get_jwt_user", "mfa_guard", "require_mfa"}, names
    assert not any("rbac" in n or n == "dependency" for n in names), names


def test_it_is_mounted_on_the_real_app_with_no_mount_guard_that_would_ask_for_a_login():
    from main import app
    matches = [r for r in app.routes if getattr(r, "path", "") == URL]
    assert len(matches) == 1 and "POST" in matches[0].methods
    names = _dependency_names(matches[0])
    assert not names & {"get_current_user", "get_jwt_user", "mfa_guard", "require_client_access"}, names


# ── what the status screen can say ───────────────────────────────────────────

def test_the_status_endpoint_says_whether_the_trigger_is_configured_and_never_the_value(monkeypatch):
    import jobs.scheduler as sched
    from core.auth import get_current_user
    from routers.scheduler_status import router as status_router
    monkeypatch.setattr(sched, "_USE_MOCK", True)
    app = FastAPI()
    app.include_router(status_router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "m", "firm_id": "F1", "role": "Manager", "email": "m@firm.com"}
    c = TestClient(app, raise_server_exceptions=False)

    monkeypatch.delenv("SCHEDULER_TRIGGER_TOKEN", raising=False)
    off = c.get("/api/scheduler/status")
    assert off.status_code == 200 and off.json()["data"]["external_trigger_configured"] is False

    monkeypatch.setenv("SCHEDULER_TRIGGER_TOKEN", GOOD)
    on = c.get("/api/scheduler/status")
    assert on.json()["data"]["external_trigger_configured"] is True
    assert GOOD not in on.text


# ── the manifest ─────────────────────────────────────────────────────────────

def test_the_token_is_declared_in_the_manifest_and_is_not_synced_from_it():
    lines = (REPO / "render.yaml").read_text(encoding="utf-8").splitlines()
    i = next(n for n, line in enumerate(lines) if line.strip() == "- key: SCHEDULER_TRIGGER_TOKEN")
    assert lines[i + 1].strip() == "sync: false", "a secret is set in the dashboard, never in the file"
    assert "value:" not in lines[i + 1]
