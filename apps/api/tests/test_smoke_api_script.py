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


def test_every_budget_is_set_and_sane():
    for c in smoke_api.checks("CID", "2026-04-01", "2027-03-31"):
        assert c.budget_s > 0, c.name
        # Above the 45s the frontend itself aborts at would be a budget that
        # permits a request the user never sees the result of.
        assert c.budget_s < 45, f"{c.name}: budget exceeds the client's own timeout"
