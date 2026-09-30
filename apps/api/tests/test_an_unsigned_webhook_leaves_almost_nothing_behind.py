"""A stranger POSTing to the public payment webhook cannot grow our records.

SECURITY-PRIVACY-23

WHAT THE FINDING SAID, AND WHAT WAS ACTUALLY TRUE
    "For every bad-signature request process_webhook records an event row and
    calls log_event, which writes to the append-only audit_log."  Half of that is
    right. `audit_log.firm_id` is UUID NOT NULL and the call passed firm_id "", so
    Postgres refused the insert and `log_event` swallowed the error — no audit row
    was ever written, only a failed round trip and an ERROR log line per request.
    The table that genuinely grew without bound was `customer_payment_events`: one
    row per request, carrying the caller's own JSON as `raw_payload`, sized by
    nothing. The route also had no throttle.

WHAT THESE PIN
    * an unsigned request writes NOTHING to audit_log — not through `log_event`,
      and the two functions that handle it are asserted not to call it;
    * across a thousand of them at most UNSIGNED_SAMPLE_CAP event rows are kept,
      and what a kept row holds of the caller's values is bounded;
    * the 101st unsigned request from one address in a minute is 429, another
      address is unaffected, and the window expires;
    * a SIGNED delivery is never throttled — not even from an address that has
      exhausted its unsigned budget, because the limiter runs after the signature
      check and counts only failures;
    * a forged leftmost X-Forwarded-For does not buy a fresh budget (the key is
      `core.client_ip`'s, not the header's first entry);
    * an oversized body is 413 before anything is parsed or stored.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import routers.payments as pr
import services.payment_service as ps
from core.rate_window import SlidingWindowLimiter
from tests.test_online_payments import FakeDB

API_ROOT = Path(__file__).resolve().parents[1]
SECRET = "webhook-test-secret"
EVENTS = "customer_payment_events"


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setenv("MOCK_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("PAYMENT_PROVIDER", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    ps._reset_unsigned_state()
    yield
    ps._reset_unsigned_state()


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(ps, "log_event", lambda *a, **k: calls.append((a, k)))
    return calls


def _unsigned(i: int = 0, **extra) -> tuple[dict, bytes]:
    body = json.dumps({"id": f"evt-forged-{i}", "event": "payment.captured", **extra}).encode()
    return {"x-webhook-signature": "0" * 64}, body


def _signed(event_id: str = "evt-real-1") -> tuple[dict, bytes]:
    body = json.dumps({
        "id": event_id, "event": "payment.created",
        "payload": {"payment": {"entity": {"id": "pay_real_1", "order_id": "order_real_1"}}},
    }).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"x-webhook-signature": sig}, body


def _rows(db: FakeDB) -> list[dict]:
    return db.data.get(EVENTS, [])


# ── what an unsigned request leaves behind ───────────────────────────────────

def test_a_thousand_unsigned_posts_write_no_audit_row(audit_calls):
    db = FakeDB()
    for i in range(1000):
        h, b = _unsigned(i)
        out = ps.process_webhook(db, "mock", h, b, client_ip=f"198.51.100.{i % 250 + 1}")
        assert out["ok"] is False
    assert audit_calls == []
    assert ps.unsigned_total() == 1000


def test_the_handlers_of_an_unsigned_request_do_not_call_log_event():
    """The rule rather than the count: `log_event` is right for a VERIFIED capture
    (which has a firm) and wrong for a delivery that has none."""
    tree = ast.parse((API_ROOT / "services" / "payment_service.py").read_text(encoding="utf-8"))
    handlers = {n.name: n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name in ("process_webhook", "_refuse_unsigned")}
    assert set(handlers) == {"process_webhook", "_refuse_unsigned"}
    for name, fn in handlers.items():
        called = {c.func.id for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "log_event" not in called, (
            f"{name} calls log_event — an unsigned delivery has no firm, and "
            "audit_log is append-only with a NOT NULL firm_id")


def test_across_a_thousand_unsigned_posts_only_a_capped_sample_is_stored():
    db = FakeDB()
    for i in range(1000):
        h, b = _unsigned(i)
        ps.process_webhook(db, "mock", h, b, client_ip=f"198.51.100.{i % 250 + 1}")
    assert 1 <= len(_rows(db)) <= ps.UNSIGNED_SAMPLE_CAP
    assert all(r["signature_verified"] is False for r in _rows(db))


def test_what_a_stored_sample_keeps_of_the_callers_values_is_bounded():
    db = FakeDB()
    h, b = _unsigned(0, padding="x" * 100_000)
    ps.process_webhook(db, "mock", h, b, client_ip="198.51.100.1")
    [row] = _rows(db)
    assert len(json.dumps(row["raw_payload"])) < 1000
    assert row["raw_payload"].get("_truncated") is True

    long_id = json.dumps({"id": "e" * 10_000, "event": "payment.captured"}).encode()
    ps.process_webhook(db, "mock", {"x-webhook-signature": "0" * 64}, long_id, client_ip="198.51.100.2")
    assert max(len(r["provider_event_id"] or "") for r in _rows(db)) <= 128


def test_a_flood_is_a_handful_of_log_lines_not_a_thousand(caplog):
    caplog.set_level(logging.WARNING, logger="caflow.payment_service")
    db = FakeDB()
    for i in range(1000):
        h, b = _unsigned(i)
        ps.process_webhook(db, "mock", h, b, client_ip="198.51.100.9")
    lines = [r for r in caplog.records if "unsigned or badly signed" in r.getMessage()]
    assert 10 <= len(lines) <= 25, len(lines)
    assert all("198.51.100.9" in r.getMessage() for r in lines)


# ── the limiter ──────────────────────────────────────────────────────────────

def test_the_101st_unsigned_request_from_one_address_is_rate_limited():
    db = FakeDB()
    reasons = []
    for i in range(101):
        h, b = _unsigned(i)
        reasons.append(ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.50")["reason"])
    assert reasons[:100] == ["invalid_signature"] * 100
    assert reasons[100] == "rate_limited"
    # Somebody else is not in the same window.
    h, b = _unsigned(999)
    assert ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.51")["reason"] == "invalid_signature"


def test_the_window_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ps, "_unsigned_per_ip",
                        SlidingWindowLimiter(ps.UNSIGNED_PER_IP_MAX, ps.UNSIGNED_WINDOW_SECONDS,
                                             clock=lambda: now[0]))
    db = FakeDB()
    h, b = _unsigned()
    for _ in range(100):
        ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.50")
    assert ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.50")["reason"] == "rate_limited"
    now[0] += ps.UNSIGNED_WINDOW_SECONDS + 1
    assert ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.50")["reason"] == "invalid_signature"


def test_a_refused_request_does_not_extend_its_own_lockout(monkeypatch):
    """Counting the refusals would turn a rate limit into a ban: a caller who keeps
    hammering would never get back in."""
    lim = SlidingWindowLimiter(2, 60, clock=lambda: 0.0)
    assert [lim.hit("a"), lim.hit("a"), lim.hit("a"), lim.hit("a")] == [True, True, False, False]
    lim2 = SlidingWindowLimiter(2, 60, clock=iter([0, 0, 1, 2, 61, 61]).__next__)
    assert [lim2.hit("a"), lim2.hit("a"), lim2.hit("a"), lim2.hit("a")] == [True, True, False, False]
    assert lim2.hit("a") is True      # the two recorded at t=0 have aged out; refusals never counted


def test_the_limiter_table_is_bounded():
    lim = SlidingWindowLimiter(1, 60, max_keys=8, clock=lambda: 1.0)
    for i in range(1000):
        lim.hit(f"k{i}")
    assert len(lim._events) <= 8


# ── a signed delivery is never the limiter's business ────────────────────────

def test_a_signed_delivery_is_not_throttled_by_an_addresss_unsigned_history(monkeypatch):
    monkeypatch.setattr(ps, "_event_seen", lambda *a, **k: False)
    monkeypatch.setattr(ps, "_resolve_payment", lambda *a, **k: None)
    db = FakeDB()
    h, b = _unsigned()
    for _ in range(150):
        ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.50")
    assert ps.process_webhook(db, "mock", h, b, client_ip="203.0.113.50")["reason"] == "rate_limited"

    sh, sb = _signed()
    for _ in range(300):        # well past the unsigned budget, from the SAME address
        out = ps.process_webhook(db, "mock", sh, sb, client_ip="203.0.113.50")
        assert out == {"ok": True, "ignored": True}


# ── through the real route ───────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from main import app
    db = FakeDB()
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "_USE_MOCK", False)
    monkeypatch.setattr(ps, "_event_seen", lambda *a, **k: False)
    monkeypatch.setattr(ps, "_resolve_payment", lambda *a, **k: None)
    c = TestClient(app, raise_server_exceptions=False)
    c._fake = db                                              # type: ignore[attr-defined]
    return c


def _post(client, headers_body, xff=None):
    h, b = headers_body
    headers = dict(h)
    if xff:
        headers["X-Forwarded-For"] = xff
    return client.post("/api/payments/webhook/mock", content=b, headers=headers)


def test_the_route_refuses_the_101st_unsigned_post_with_429(client, audit_calls):
    codes = [_post(client, _unsigned(i), xff="203.0.113.77").status_code for i in range(101)]
    assert codes[:100] == [400] * 100
    assert codes[100] == 429
    assert audit_calls == []
    last = _post(client, _unsigned(101), xff="203.0.113.77")
    assert last.status_code == 429 and last.headers.get("retry-after") == "60"
    assert len(_rows(client._fake)) <= ps.UNSIGNED_SAMPLE_CAP


def test_forging_the_leftmost_forwarded_for_buys_no_fresh_budget(client):
    codes = [_post(client, _unsigned(i), xff=f"10.66.0.{i}, 203.0.113.88").status_code
             for i in range(101)]
    assert codes[100] == 429, "rotating the forged entry escaped the per-address limit"


def test_the_route_never_throttles_a_signed_delivery(client):
    for i in range(120):
        _post(client, _unsigned(i), xff="203.0.113.99")
    assert _post(client, _unsigned(999), xff="203.0.113.99").status_code == 429
    ok = _post(client, _signed(), xff="203.0.113.99")
    assert ok.status_code == 200 and ok.json()["data"]["ok"] is True


def test_an_oversized_body_is_refused_before_anything_is_parsed_or_stored(client, monkeypatch):
    called = []
    monkeypatch.setattr(ps, "process_webhook", lambda *a, **k: called.append(1) or {"ok": True})
    big = json.dumps({"id": "x", "event": "payment.captured", "pad": "x" * (pr.MAX_WEBHOOK_BODY_BYTES + 10)}).encode()
    res = client.post("/api/payments/webhook/mock", content=big,
                      headers={"x-webhook-signature": "0" * 64})
    assert res.status_code == 413
    assert called == [] and _rows(client._fake) == []
