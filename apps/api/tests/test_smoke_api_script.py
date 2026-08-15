"""
The smoke script must actually fail on the things it exists to catch.

A live check nobody can run offline is a check nobody trusts, and one that
passes when the system is broken is worse than none. These run the script's
decision logic against fabricated responses — no network, no credentials — so
the two failure modes it was written for are pinned:

    * a non-2xx response
    * a 2xx response that took longer than its budget

The second is the one every existing check is blind to. The waterfall ratchet
counts round trips, so a single 57-second request scores perfect on it; the
column checker reads source and never executes anything. Wall-clock is only
visible to something that actually calls the endpoint.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import smoke_api  # noqa: E402


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)


def test_a_healthy_fast_endpoint_passes():
    with _client(lambda req: httpx.Response(200, json={"ok": True})) as c:
        ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert ok, line
    assert "ok" in line


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
def test_every_non_2xx_fails(status):
    """403 and 503 are in this list deliberately: production served five 403s
    from /api/identity/permissions and a 503 from /health while every static
    check in the repo was green."""
    with _client(lambda req: httpx.Response(status, json={})) as c:
        ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert not ok
    assert str(status) in line


def test_a_failure_reports_the_reason_not_just_the_status():
    """The status code alone is not a diagnosis. /api/identity/permissions can
    403 because the user row is missing, the account is disabled, the firm is
    suspended, or MFA is unsatisfied — four different problems, one number. The
    server names which; printing it is the whole difference."""
    body = {"detail": "Multi-factor authentication required for this action."}
    with _client(lambda req: httpx.Response(403, json=body)) as c:
        ok, line = smoke_api.run_check(
            c, "http://x", smoke_api.Check("perms", "/api/identity/permissions", 8), "t")
    assert not ok
    assert "Multi-factor authentication required" in line


def test_the_reason_comes_from_this_repos_response_contract_too():
    """All API responses are {success, data, error} — the failure text lives in
    `error`, not `detail`, for everything that goes through api_response()."""
    body = {"success": False, "data": None, "error": "Deployed code depends on columns"}
    with _client(lambda req: httpx.Response(503, json=body)) as c:
        _ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert "Deployed code depends on columns" in line


@pytest.mark.parametrize("payload", [
    {"kwargs": {"text": "<html>502 Bad Gateway</html>"}},          # not JSON at all
    {"kwargs": {"json": ["a", "list"]}},                            # JSON, not an object
    {"kwargs": {"json": {"error": None, "detail": ""}}},            # present but empty
    {"kwargs": {"json": {}}},                                       # no fields
])
def test_an_unreadable_error_body_still_fails_cleanly(payload):
    """A proxy's HTML error page must not turn a reported failure into a crash —
    the check still has to say 502, which is the thing worth knowing."""
    with _client(lambda req: httpx.Response(502, **payload["kwargs"])) as c:
        ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert not ok
    assert "502" in line


def test_a_successful_response_body_is_never_read():
    """The reason field is for failures only. A 200 body is a client's ledger,
    and this script's output goes to a CI log."""
    ledger = {"success": True, "data": {"detail": "PRIVATE", "error": "PRIVATE"}, "error": None}
    with _client(lambda req: httpx.Response(200, json=ledger)) as c:
        ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert ok
    assert "PRIVATE" not in line


def test_the_reason_is_truncated():
    """A stack trace rendered into `detail` should not become the CI log."""
    with _client(lambda req: httpx.Response(500, json={"detail": "x" * 5000})) as c:
        _ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert len(line) < 400, "an unbounded error body reached the output"


def test_a_2xx_that_took_too_long_fails(monkeypatch):
    """The whole point. HTTP 200 in 57 seconds is a broken page, and nothing
    else in this repo can see it."""
    ticks = iter([0.0, 57.0])
    monkeypatch.setattr(smoke_api.time, "monotonic", lambda: next(ticks))
    with _client(lambda req: httpx.Response(200, json={})) as c:
        ok, line = smoke_api.run_check(
            c, "http://x", smoke_api.Check("cash-flow", "/api/accounting/cash-flow", 20), "t")
    assert not ok
    assert "OVER BUDGET" in line
    assert "57.00s" in line


def test_a_transport_failure_fails_rather_than_passing_silently():
    def boom(req):
        raise httpx.ConnectError("connection refused")
    with _client(boom) as c:
        ok, line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert not ok
    assert "TRANSPORT ERROR" in line


def test_it_skips_cleanly_when_not_configured(monkeypatch, capsys):
    """Exit 0 and say so. A smoke check that fails closed on a machine with no
    credentials would be disabled within a week."""
    for var in ("SMOKE_BASE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY",
                "SMOKE_EMAIL", "SMOKE_PASSWORD", "SMOKE_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    assert smoke_api.main() == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "SMOKE_BASE_URL" in out, "say WHICH variables are missing"


def test_the_checks_cover_the_endpoints_that_actually_broke():
    """Pins the list against the incident rather than leaving it to taste:
    /health returned 503, /api/identity/permissions returned 403, and
    /api/accounting/cash-flow took 57s. All three must be exercised."""
    paths = " ".join(c.path for c in smoke_api.checks("CID", "2026-04-01", "2027-03-31"))
    for required in ("/health", "/api/identity/permissions", "/api/accounting/cash-flow"):
        assert required in paths, f"{required} is not covered"


def test_the_client_id_and_dates_reach_the_query_string():
    """A check that silently drops its scope would exercise an empty ledger and
    report a fast, meaningless pass — the volume is the point."""
    cs = {c.name: c.path for c in smoke_api.checks("CID-1", "2026-04-01", "2027-03-31")}
    cf = cs["accounting/cash-flow"]
    assert "client_id=CID-1" in cf
    assert "start_date=2026-04-01" in cf and "end_date=2027-03-31" in cf


# ── MFA-guarded routes ───────────────────────────────────────────────────────
#
# The smoke check signs in with a password grant, which yields an aal1 token by
# construction. main.py mounts identity (and assignments/practice/billing)
# behind _MFA_GUARD, so once REQUIRE_MFA is on for the smoke account's role that
# 403 is PERMANENT and CORRECT. Failing on it would leave a check nobody can
# ever make green — the state /health was in for weeks, which is exactly how
# real drift stayed invisible behind it.

def _perms_check():
    return next(c for c in smoke_api.checks("CID", "2026-04-01", "2027-03-31")
                if c.name == "identity/permissions")


def test_the_mfa_detail_string_matches_the_one_the_backend_actually_raises():
    """The script duplicates this literal because it runs standalone in CI with
    only httpx installed and cannot import the app. That duplication is only
    safe if something notices when the two drift — reword mfa_guard's detail and
    the smoke check would silently go red forever with no explanation."""
    source = (Path(__file__).resolve().parents[1] / "core" / "auth.py").read_text(encoding="utf-8")

    assert f'detail="{smoke_api.MFA_REQUIRED_DETAIL}"' in source, (
        "core/auth.py no longer raises smoke_api.MFA_REQUIRED_DETAIL verbatim — "
        "update the literal in scripts/smoke_api.py to match")


def test_the_identity_check_is_marked_mfa_guarded():
    """Pins the fact against main.py rather than leaving it to memory: if the
    identity router is ever taken out from behind _MFA_GUARD, this flag is wrong
    and the check should go back to demanding a 2xx."""
    main_py = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")

    assert "app.include_router(identity.router, dependencies=_MFA_GUARD)" in main_py, (
        "identity is no longer MFA-guarded — drop mfa_guarded=True from its Check")
    assert _perms_check().mfa_guarded is True


def test_an_mfa_guarded_route_refusing_an_aal1_token_is_not_a_failure():
    """The fix. Policy working correctly must not read as an outage."""
    body = {"detail": smoke_api.MFA_REQUIRED_DETAIL}
    with _client(lambda req: httpx.Response(403, json=body)) as c:
        ok, line = smoke_api.run_check(c, "http://x", _perms_check(), "t")

    assert ok, line
    assert "MFA-guarded" in line
    assert "authorised response not covered" in line, (
        "say what this did NOT verify — a pass that overstates its coverage is worse "
        "than a failure")


def test_a_403_for_any_other_reason_still_fails():
    """The exemption is narrow on purpose. /api/identity/permissions can 403
    because the user row is missing, the account is disabled, or the firm is
    suspended — all real outages, none of them MFA."""
    for detail in ("User not found in firm. Contact your firm administrator.",
                   "Account disabled. Contact your firm administrator.",
                   "Firm suspended", "Firm unavailable"):
        with _client(lambda req, d=detail: httpx.Response(403, json={"detail": d})) as c:
            ok, line = smoke_api.run_check(c, "http://x", _perms_check(), "t")
        assert not ok, f"a {detail!r} 403 was waved through as MFA"
        assert "403" in line


@pytest.mark.parametrize("status", [200, 401, 500, 503])
def test_the_exemption_applies_only_to_403(status):
    body = {"detail": smoke_api.MFA_REQUIRED_DETAIL}
    with _client(lambda req: httpx.Response(status, json=body)) as c:
        ok, _line = smoke_api.run_check(c, "http://x", _perms_check(), "t")
    assert ok is (200 <= status < 300)


def test_a_non_guarded_route_never_gets_the_exemption():
    """Only routes actually mounted behind _MFA_GUARD may use it. If /health
    started answering 403-with-that-detail, something is very wrong and must
    still fail."""
    body = {"detail": smoke_api.MFA_REQUIRED_DETAIL}
    with _client(lambda req: httpx.Response(403, json=body)) as c:
        ok, _line = smoke_api.run_check(c, "http://x", smoke_api.Check("h", "/health", 5), "t")
    assert not ok


def test_an_mfa_403_that_took_too_long_still_fails(monkeypatch):
    """The latency half of the check does not get waived along with the status.
    A guard that takes 40 seconds to say no is still a broken page."""
    ticks = iter([0.0, 40.0])
    monkeypatch.setattr(smoke_api.time, "monotonic", lambda: next(ticks))
    body = {"detail": smoke_api.MFA_REQUIRED_DETAIL}
    with _client(lambda req: httpx.Response(403, json=body)) as c:
        ok, line = smoke_api.run_check(c, "http://x", _perms_check(), "t")

    assert not ok
    assert "OVER BUDGET" in line


def test_every_budget_is_set_and_sane():
    for c in smoke_api.checks("CID", "2026-04-01", "2027-03-31"):
        assert c.budget_s > 0, c.name
        # Above the 45s the frontend itself aborts at would be a budget that
        # permits a request the user never sees the result of.
        assert c.budget_s < 45, f"{c.name}: budget exceeds the client's own timeout"
