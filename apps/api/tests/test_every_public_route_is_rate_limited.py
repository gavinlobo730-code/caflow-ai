"""Every route a stranger can reach is rate limited per address, or is named with the limit that already covers it (ops-30).

THE FINDING
    "The in-process limiter has one call site (AI copilot) ... the demo-request form has its own per-IP
    limiter; the public engagement e-sign route has no limiter ... The operations angle: one noisy caller
    should not exhaust the single worker. Verify line: a load script hitting the e-sign and demo-request
    routes receives 429 after the configured rate from a single IP while an authenticated user's requests
    still succeed."

WHAT THIS ASSERTS
    * the window itself: `SlidingWindowLimiter.hit_or_wait` admits, refuses with a whole-second wait that is
      never below one, does not record a refusal, and leaves `hit` exactly as it was;
    * the dependency: its buckets, a refusal that is a 429 with `Retry-After` in the
      `{success, data, error}` envelope and that reaches the browser through CORS, an unknown bucket that is a
      programming error and not a free pass, and a caller keyed by `core.client_ip` (the Nth entry from the
      RIGHT of X-Forwarded-For) and never by the first one the caller typed;
    * END TO END on the real app, as the verify line says: a loop on the e-sign route and on the demo form is
      refused after the budget, another address is not, and a signed-in caller's request from the SAME address
      is untouched;
    * THE RULE, derived from the route table and not from a list of today's routes: every route that needs no
      login, and every route that needs a login but no account (an accept-invite, firm creation), carries a
      bucket or is named in `OWN_HANDLING` with where its limit lives, and each such claim is checked against
      that module's source so it cannot go stale; and no route that needs a staff, portal, employee or
      platform session carries a bucket at all.

WHAT CANNOT BE TESTED HERE
    That a flood from MANY addresses is stopped (the windows are per address, in this process, and the edge
    rules in docs/operations/edge-protection.md are NOT APPLIED), that Render forwards the client address in
    the shape `TRUSTED_PROXY_HOPS` assumes, and what happens with more than one worker.
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main
from core import auth as core_auth
from core import platform_auth, portal_auth
from core.rate_window import SlidingWindowLimiter
from middleware import public_rate_limit as prl
from middleware.public_rate_limit import BUCKETS, TooManyRequests, public_limit

API_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://caflow-ai.pages.dev"


# ═══ the window ═══════════════════════════════════════════════════════════════

class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_hit_or_wait_admits_then_says_how_long_to_wait():
    clock = _Clock()
    lim = SlidingWindowLimiter(3, 60, clock=clock)
    assert [lim.hit_or_wait("a") for _ in range(3)] == [None, None, None]
    clock.now += 10
    wait = lim.hit_or_wait("a")
    assert wait == 50, "the oldest event was 10 s ago in a 60 s window"
    clock.now += 0.2
    assert lim.hit_or_wait("a") == 50, "rounded UP: 49.8 s left is 50, never an early 49"


def test_the_wait_is_never_below_one_second():
    clock = _Clock()
    lim = SlidingWindowLimiter(1, 60, clock=clock)
    assert lim.hit_or_wait("a") is None
    clock.now += 59.999
    assert lim.hit_or_wait("a") == 1


def test_a_refused_event_is_not_recorded_so_hammering_does_not_extend_the_wait():
    clock = _Clock()
    lim = SlidingWindowLimiter(1, 60, clock=clock)
    assert lim.hit_or_wait("a") is None
    for _ in range(50):
        assert lim.hit_or_wait("a") is not None
    clock.now += 60.001
    assert lim.hit_or_wait("a") is None, "fifty refusals did not push the window out"


def test_the_window_expires_and_keys_do_not_share_a_budget():
    clock = _Clock()
    lim = SlidingWindowLimiter(2, 10, clock=clock)
    assert lim.hit_or_wait("a") is None and lim.hit_or_wait("a") is None
    assert lim.hit_or_wait("a") is not None
    assert lim.hit_or_wait("b") is None
    clock.now += 11
    assert lim.hit_or_wait("a") is None


def test_hit_still_answers_a_bool_exactly_as_before():
    lim = SlidingWindowLimiter(1, 60)
    assert lim.hit("a") is True
    assert lim.hit("a") is False


# ═══ the dependency ═══════════════════════════════════════════════════════════

def test_the_buckets_are_the_documented_figures():
    assert BUCKETS == {"esign": (120, 60), "invite": (120, 60), "form": (120, 60), "signup": (60, 3600)}


def test_an_unknown_bucket_is_a_programming_error_not_a_free_pass():
    with pytest.raises(KeyError):
        public_limit("nonsense")
    with pytest.raises(KeyError):
        prl.check("nonsense", object())


def _app_with(bucket: str) -> TestClient:
    app = FastAPI()          # NO handler registered: the fallback is still a correct 429
    router_dep = Depends(public_limit(bucket))

    @app.get("/x", dependencies=[router_dep])
    def _x():
        return {"success": True, "data": None, "error": None}

    return TestClient(app)


def test_a_refusal_is_a_429_with_retry_after_even_without_the_apps_own_handler():
    client = _app_with("esign")
    limit, window = BUCKETS["esign"]
    for _ in range(limit):
        assert client.get("/x").status_code == 200
    r = client.get("/x")
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= window


def test_the_keying_address_is_the_nth_from_the_right_never_the_first_one_typed():
    client = _app_with("form")
    limit, _ = BUCKETS["form"]
    # A caller rotating the LEFT of the chain is still one address: the proxy's entry is the last.
    for i in range(limit):
        r = client.get("/x", headers={"X-Forwarded-For": f"10.9.8.{i % 250}, 203.0.113.50"})
        assert r.status_code == 200
    assert client.get("/x", headers={"X-Forwarded-For": "10.1.1.1, 203.0.113.50"}).status_code == 429
    assert client.get("/x", headers={"X-Forwarded-For": "10.1.1.1, 198.51.100.9"}).status_code == 200


def test_the_log_line_names_the_bucket_and_never_a_path_or_an_address(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="caflow.public_rate_limit")
    client = _app_with("signup")
    limit, _ = BUCKETS["signup"]
    for _ in range(limit + 1):
        client.get("/x", headers={"X-Forwarded-For": "203.0.113.77"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "bucket signup" in text
    assert "203.0.113.77" not in text and "/x" not in text


# ═══ end to end, on the real app ═════════════════════════════════════════════

@pytest.fixture()
def real():
    return TestClient(main.app, raise_server_exceptions=False)


def test_a_loop_on_the_demo_form_options_is_refused_after_the_budget_and_another_address_is_not(real):
    limit, window = BUCKETS["form"]
    path = "/api/public/demo-request/options"
    mine = {"X-Forwarded-For": "203.0.113.5", "Origin": ORIGIN}
    codes = [real.get(path, headers=mine).status_code for _ in range(limit)]
    assert codes == [200] * limit
    refused = real.get(path, headers=mine)
    assert refused.status_code == 429
    assert 1 <= int(refused.headers["retry-after"]) <= window
    body = refused.json()
    assert body["success"] is False and body["data"] is None and "wait" in body["error"]
    assert refused.headers["access-control-allow-origin"] == ORIGIN, "the page must be able to read the refusal"
    assert real.get(path, headers={"X-Forwarded-For": "198.51.100.8"}).status_code == 200


def test_a_loop_on_the_esign_route_is_refused_after_the_budget(real, monkeypatch):
    import routers.engagement_sign_public as esp
    monkeypatch.setattr(esp, "_db", lambda: object())     # a one-character token never reaches the database
    limit, _ = BUCKETS["esign"]
    path = "/api/public/engagement-letters/x"
    hdr = {"X-Forwarded-For": "203.0.113.6", "Origin": ORIGIN}
    assert [real.get(path, headers=hdr).status_code for _ in range(limit)] == [404] * limit
    refused = real.get(path, headers=hdr)
    assert refused.status_code == 429 and refused.json()["success"] is False
    # The two POSTs on the same router share the address's window, because the limit is the router's.
    assert real.post(path + "/sign", json={"signer_name": "x", "consent": True}, headers=hdr).status_code == 429
    assert real.post(path + "/reject", json={}, headers=hdr).status_code == 429


def test_the_demo_forms_own_refusal_now_says_how_long_to_wait(monkeypatch):
    monkeypatch.setenv("DEMO_REQUEST_TO", "sales@example.com")
    import routers.demo_request as mod
    mod = importlib.reload(mod)
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: True)
    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)
    body = {"name": "A", "firm_name": "B", "email": "a@example.com"}
    hdr = {"X-Forwarded-For": "203.0.113.7"}
    assert [client.post("/api/public/demo-request", json=body, headers=hdr).status_code
            for _ in range(mod._PER_IP_MAX)] == [200] * mod._PER_IP_MAX
    r = client.post("/api/public/demo-request", json=body, headers=hdr)
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= mod._PER_IP_WINDOW_S


def test_a_signed_in_callers_request_from_the_same_address_is_untouched(real):
    """The verify line's other half. Spend the whole public budget for this address, then make an
    authenticated call from it."""
    user = {"id": "u1", "auth_user_id": "a1", "firm_id": "f1", "role": "Partner", "email": "p@example.com"}
    main.app.dependency_overrides[core_auth.get_current_user] = lambda: user
    try:
        hdr = {"X-Forwarded-For": "203.0.113.9"}
        limit, _ = BUCKETS["form"]
        for _ in range(limit + 1):
            real.get("/api/public/demo-request/options", headers=hdr)
        assert real.get("/api/public/demo-request/options", headers=hdr).status_code == 429
        r = real.get("/api/identity/permissions", headers=hdr)
        assert r.status_code == 200, r.text
    finally:
        main.app.dependency_overrides.pop(core_auth.get_current_user, None)


# ═══ the rule, derived from the route table ═══════════════════════════════════

#: A session that needs an ACCOUNT: staff, a client-portal contact, an employee, a platform admin.
ACCOUNT_PRINCIPALS = {
    core_auth.get_current_user,
    portal_auth.get_current_portal_client,
    portal_auth.get_current_portal_employee,
    platform_auth.require_platform_admin,
    platform_auth.is_platform_admin,
}

#: Routes with no login, or a login and no account, that are NOT behind `public_limit`, with where the
#: limit that covers each lives. Each claim is checked against that module's source below.
OWN_HANDLING = {
    ("GET", "/"): ("main", "root",
                   "answers a constant document; no database, no provider, nothing to spend"),
    ("GET", "/health"): ("main", "healthcheck",
                         "a deploy and uptime probe that answers from memory; a limiter on it could let a flood "
                         "take the health check down, which is the bug /health was rewritten to end"),
    ("GET", "/ready"): ("core.readiness", "CACHE_TTL_SECONDS",
                        "one bounded request, reused for five seconds under a lock (core/readiness), because it "
                        "is unauthenticated on a public repository"),
    ("POST", "/api/payments/webhook/{provider}"): (
        "services.payment_service", "_unsigned_per_ip",
        "signed by the gateway: a limiter in front of the signature check would let a flood lock the gateway "
        "out, so UNSIGNED requests are counted per address after it (security_privacy-23)"),
    ("POST", "/api/email/webhook/resend"): (
        "services.email_events_service", "_unsigned_per_ip",
        "signed by the provider and limited exactly as the payment webhook is, after the signature check"),
    ("POST", "/api/internal/scheduler/run-pending"): (
        "routers.scheduler_trigger", "_failures",
        "a shared token; only WRONG or missing tokens are counted per address, so the real caller is never "
        "throttled by anything a stranger does (ops-15)"),
    ("GET", "/api/portal/memberships"): (
        "routers.portal_self", "get_jwt_user",
        "a login but no account yet, and a read of the caller's OWN memberships: no token, no body, no write"),
}


def _tree_calls(dep, acc=None):
    acc = set() if acc is None else acc
    acc.add(dep.call)
    for d in dep.dependencies:
        _tree_calls(d, acc)
    return acc


def _product_routes():
    """The app's own routes, leaving out any a test module added to the shared `main.app` (the ops-11 test adds
    four, and which worker holds them depends on how modules were grouped)."""
    out = []
    for r in main.app.routes:
        if not isinstance(r, APIRoute):
            continue
        module = getattr(r.endpoint, "__module__", "") or ""
        if module.split(".")[0].startswith("test") or "tests" in module.split("."):
            continue
        out.append(r)
    return out


def _bucket_of(route) -> str | None:
    for call in _tree_calls(route.dependant):
        bucket = getattr(call, "_public_limit_bucket", None)
        if bucket:
            return bucket
    return None


def _routes_in_scope():
    """No login at all, or a login (`get_jwt_user`) and no account: the two states before somebody is a member."""
    scope = []
    for r in _product_routes():
        calls = _tree_calls(r.dependant)
        if calls & ACCOUNT_PRINCIPALS:
            continue
        scope.append(r)
    return scope


def _key(route):
    method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
    return method, route.path


def test_the_rule_finds_the_routes_it_is_about():
    """Vacuity guard: it must see the e-sign routes, the demo form, the accept-invites and the webhooks."""
    keys = {_key(r) for r in _routes_in_scope()}
    for needed in [("GET", "/api/public/engagement-letters/{token}"),
                   ("POST", "/api/public/engagement-letters/{token}/sign"),
                   ("POST", "/api/public/demo-request"),
                   ("POST", "/api/identity/accept-invite"),
                   ("POST", "/api/portal/employee/activation-session"),
                   ("POST", "/api/payments/webhook/{provider}"),
                   ("GET", "/health")]:
        assert needed in keys, f"{needed} was not derived as a route needing no account"
    assert len(keys) >= 12


def test_every_route_that_needs_no_account_is_limited_or_named_with_where():
    loose = []
    for r in _routes_in_scope():
        if _bucket_of(r) is None and _key(r) not in OWN_HANDLING:
            loose.append(f"{_key(r)[0]} {_key(r)[1]}  ({r.endpoint.__module__}.{r.endpoint.__name__})")
    assert not loose, (
        "these routes need no account and have NO per-address limit. Add `dependencies=[Depends(public_limit(...))]` "
        "(router-level where the whole router is public) or, if its limit lives elsewhere, name it in "
        "OWN_HANDLING with the reason:\n  " + "\n  ".join(loose))


def test_every_named_exception_is_still_a_route_with_no_bucket_and_its_claim_is_still_true():
    routes = {_key(r): r for r in _routes_in_scope()}
    for key, (module_name, symbol, reason) in OWN_HANDLING.items():
        assert key in routes, f"{key} is named in OWN_HANDLING but is no longer a route that needs no account"
        assert _bucket_of(routes[key]) is None, f"{key} now carries a bucket: drop it from OWN_HANDLING"
        assert len(reason) > 40, f"{key}: the reason is not a reason"
        mod = importlib.import_module(module_name)
        assert hasattr(mod, symbol) or symbol in inspect.getsource(mod), (
            f"{key} says its limit is {module_name}.{symbol} and that no longer exists")


def test_a_session_that_needs_an_account_is_never_behind_a_public_bucket():
    """The limiter is for the calls made before somebody is a member, and an authenticated caller's own
    requests are not its business."""
    offenders = []
    for r in _product_routes():
        if (_tree_calls(r.dependant) & ACCOUNT_PRINCIPALS) and _bucket_of(r):
            offenders.append(f"{_key(r)}")
    assert not offenders, f"a signed-in member's request is rate limited per address on: {offenders}"


def test_every_bucket_is_used_and_every_use_names_a_real_bucket():
    used = {_bucket_of(r) for r in _product_routes()} - {None}
    assert used == set(BUCKETS), f"unused buckets {set(BUCKETS) - used}, unknown {used - set(BUCKETS)}"


def test_the_whole_engagement_signing_router_is_limited_by_default():
    """The limit is the router's, so a route added to it next year is covered without anybody remembering."""
    import routers.engagement_sign_public as esp
    deps = [d.dependency for d in esp.router.dependencies]
    assert any(getattr(d, "_public_limit_bucket", None) == "esign" for d in deps)
    mine = [r for r in _product_routes() if r.path.startswith("/api/public/engagement-letters")]
    assert len(mine) >= 3 and all(_bucket_of(r) == "esign" for r in mine)


def test_the_limit_is_asked_before_the_login_on_every_route_that_has_both():
    """So a flood of expired sessions or bad tokens is refused before it costs a JWT check. FastAPI resolves a
    route's `dependencies` first, in the order written."""
    checked = 0
    for r in _routes_in_scope():
        if _bucket_of(r) and core_auth.get_jwt_user in _tree_calls(r.dependant):
            first = r.dependant.dependencies[0].call
            assert getattr(first, "_public_limit_bucket", None), f"{_key(r)}: the login is checked before the limit"
            checked += 1
    assert checked >= 4          # three accept-invites and firm creation


def test_the_handler_is_registered_for_the_exception_the_dependency_raises():
    assert main.app.exception_handlers[TooManyRequests] is prl.too_many_requests_handler
    assert issubclass(TooManyRequests, HTTPException)
