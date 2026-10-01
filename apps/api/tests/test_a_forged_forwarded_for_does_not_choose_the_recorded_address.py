"""The address a public endpoint acts on is one our own proxy wrote, not one the caller typed.

SECURITY-PRIVACY-25

WHAT WAS WRONG
    The demo-request limiter and the `signed_ip` stored beside an engagement
    letter's e-signature both took X-Forwarded-For's FIRST entry. Every proxy
    appends, so the header arrives as `<what the caller wrote>, <real client>,
    <proxy>` and the first entry is the caller's own: rotating it beat the limiter
    (its own comment called the value "spoofable"), and the address recorded next
    to a signature was whatever the signer typed.

WHAT THESE PIN
    * the client is the Nth entry from the RIGHT (N = TRUSTED_PROXY_HOPS, default
      1) and nothing to its left is ever read;
    * a header with fewer entries than hops, none, or an unreadable chosen entry
      falls back in the direction that is never attacker-controlled;
    * both real call sites ask that one function, and a forged leftmost entry
      changes neither the limiter's key nor the recorded signing address;
    * the raw chain is kept on the signing event, labelled unverified, so a wrong
      hop count can be corrected by a human afterwards;
    * nothing else in apps/api reads the header.

WHAT THEY CANNOT PIN
    How many proxies Render really puts in front of this service. That was
    recalled, not read, which is why the default is the conservative one and the
    count is a setting — see core/client_ip.py and render.yaml.
"""
from __future__ import annotations

import importlib
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import client_ip as cip

API_ROOT = Path(__file__).resolve().parents[1]


class _Req:
    """What `client_ip` needs: lower-case headers and a socket peer."""

    def __init__(self, xff=None, peer="172.16.0.9"):
        self.headers = {} if xff is None else {"x-forwarded-for": xff}
        self.client = type("C", (), {"host": peer})() if peer else None


@pytest.fixture(autouse=True)
def _default_hops(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("xff,hops,expected", [
    # A forged leftmost entry is never the answer.
    ("6.6.6.6, 203.0.113.9", 1, "203.0.113.9"),
    ("6.6.6.6, 7.7.7.7, 8.8.8.8, 203.0.113.9", 1, "203.0.113.9"),
    # Two trusted proxies: the client is the second from the right.
    ("6.6.6.6, 203.0.113.9, 172.70.0.1", 2, "203.0.113.9"),
    ("6.6.6.6, 203.0.113.9, 172.70.0.1", 1, "172.70.0.1"),
    # Fewer entries than hops: the chain is all ours, the leftmost is the answer.
    ("203.0.113.9", 2, "203.0.113.9"),
    ("203.0.113.9", 1, "203.0.113.9"),
    # Spellings proxies write.
    ("6.6.6.6, 203.0.113.9:44321", 1, "203.0.113.9"),
    ("6.6.6.6, [2001:db8::1]:443", 1, "2001:db8::1"),
    ("6.6.6.6, 2001:DB8:0:0:0:0:0:1", 1, "2001:db8::1"),
    (" 6.6.6.6 ,  203.0.113.9 ,", 1, "203.0.113.9"),
])
def test_the_client_is_counted_from_the_right(monkeypatch, xff, hops, expected):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", str(hops))
    assert cip.client_ip(_Req(xff)) == expected


def test_a_chain_of_a_hundred_entries_is_read_from_its_right_end(monkeypatch):
    chain = ", ".join(f"10.1.{i // 250}.{i % 250 + 1}" for i in range(100)) + ", 203.0.113.9"
    assert cip.client_ip(_Req(chain)) == "203.0.113.9"


def test_no_header_means_a_direct_connection_so_the_peer_is_the_client():
    assert cip.client_ip(_Req(None, peer="198.51.100.4")) == "198.51.100.4"


def test_with_no_proxy_configured_the_header_is_never_read(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert cip.client_ip(_Req("6.6.6.6, 203.0.113.9", peer="198.51.100.4")) == "198.51.100.4"


def test_an_entry_that_is_not_an_address_falls_back_to_the_peer():
    # A proxy that writes a hostname or "unknown" gives the limiter nothing to key
    # on and the record nothing true to store; the socket peer is at least real.
    assert cip.client_ip(_Req("6.6.6.6, unknown", peer="198.51.100.4")) == "198.51.100.4"


def test_nothing_at_all_is_none():
    assert cip.client_ip(_Req(None, peer=None)) is None


@pytest.mark.parametrize("value", ["", "  ", "two", "-1", "9", "99", "1.5", "inf"])
def test_an_unusable_hop_count_falls_to_the_default_never_to_a_larger_number(monkeypatch, value):
    """Too LARGE a count reads into the caller's own entries, which is the defect;
    so an unreadable value must land on the small side."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", value)
    assert cip.trusted_proxy_hops() == 1
    assert cip.client_ip(_Req("6.6.6.6, 203.0.113.9")) == "203.0.113.9"


def test_the_evidence_is_the_raw_chain_capped_at_its_right_end():
    assert cip.forwarded_for_evidence(_Req("6.6.6.6, 203.0.113.9")) == "6.6.6.6, 203.0.113.9"
    assert cip.forwarded_for_evidence(_Req(None)) is None
    long = "9.9.9.9, " * 200 + "203.0.113.9"
    kept = cip.forwarded_for_evidence(_Req(long))
    assert len(kept) == 256 and kept.endswith("203.0.113.9")


# ── the demo-request limiter ─────────────────────────────────────────────────

def _demo_app(monkeypatch):
    monkeypatch.setenv("DEMO_REQUEST_TO", "sales@example.com")
    import routers.demo_request as mod
    mod = importlib.reload(mod)        # its windows are module-level state
    monkeypatch.setattr(mod.email_service, "_send", lambda *a, **k: True)
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app), mod


DEMO_BODY = {"name": "CA Priya", "firm_name": "Raghavan & Associates", "email": "priya@example.com"}


def test_rotating_the_leftmost_entry_does_not_walk_round_the_limit(monkeypatch):
    client, mod = _demo_app(monkeypatch)
    codes = [
        client.post("/api/public/demo-request", json=DEMO_BODY,
                    headers={"X-Forwarded-For": f"10.99.0.{i}, 203.0.113.7"}).status_code
        for i in range(mod._PER_IP_MAX + 3)
    ]
    assert codes[: mod._PER_IP_MAX] == [200] * mod._PER_IP_MAX
    assert set(codes[mod._PER_IP_MAX:]) == {429}, (
        "a caller who rotates the forged entry escaped the per-address limit")
    # A genuinely different caller is unaffected.
    other = client.post("/api/public/demo-request", json=DEMO_BODY,
                        headers={"X-Forwarded-For": "10.99.0.1, 198.51.100.4"})
    assert other.status_code == 200


def test_the_limiter_key_is_the_trusted_entry(monkeypatch):
    client, mod = _demo_app(monkeypatch)
    client.post("/api/public/demo-request", json=DEMO_BODY,
                headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.7"})
    assert list(mod._by_ip) == ["203.0.113.7"]


# ── the signing evidence ─────────────────────────────────────────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.t = db, table
        self._op, self._payload, self._single = "select", None, False

    def select(self, *a, **k):
        return self

    def insert(self, payload, *a, **k):
        self._op, self._payload = "insert", payload
        self.db.inserts.setdefault(self.t, []).append(payload)
        return self

    def update(self, payload, *a, **k):
        self._op, self._payload = "update", payload
        self.db.updates.setdefault(self.t, []).append(payload)
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        if self._op == "select":
            rows = self.db.selects.get(self.t, [])
            return _Res(rows[0] if rows else None) if self._single else _Res(list(rows))
        return _Res(self._payload if isinstance(self._payload, list) else [self._payload])


class _DB:
    def __init__(self):
        self.selects, self.inserts, self.updates = {}, {}, {}

    def table(self, name):
        return _Q(self, name)


def _sign(xff, peer="172.16.0.9"):
    import routers.engagement_sign_public as esp
    from routers.engagement_sign_public import SignBody, sign_letter

    db = _DB()
    db.selects["engagements"] = [{
        "id": "E1", "firm_id": "F1", "lead_id": "L1", "client_id": None, "status": "Viewed",
        "engagement_number": "EL-2026-0001", "title": "GST Compliance — FY26",
        "content": "<p>Our fee is 5,000 per month.</p>", "recipient_name": "Patel Foods",
        "recipient_email": "owner@patelfoods.in", "sign_token": "T" * 40,
    }]
    with patch.object(esp, "_db", return_value=db), \
         patch.object(esp, "_advance_lead"), patch.object(esp, "_revert_lead"), \
         patch("services.audit_service.log_event"):
        res = sign_letter("T" * 40, SignBody(signer_name="Rahul", consent=True), _Req(xff, peer))
    assert res["success"] is True
    return db


def test_a_forged_leftmost_entry_is_not_the_recorded_signing_address():
    db = _sign("6.6.6.6, 198.51.100.4")
    assert db.updates["engagements"][-1]["signed_ip"] == "198.51.100.4"


def test_with_no_proxy_header_the_peer_is_recorded():
    db = _sign(None, peer="198.51.100.4")
    assert db.updates["engagements"][-1]["signed_ip"] == "198.51.100.4"


def test_the_raw_chain_is_kept_on_the_signing_event_as_unverified_evidence():
    db = _sign("6.6.6.6, 198.51.100.4")
    signed = [e for e in db.inserts.get("engagement_events", []) if e.get("event_type") == "signed"]
    assert len(signed) == 1
    meta = signed[0].get("metadata") or {}
    assert meta.get("ip") == "198.51.100.4"
    assert meta.get("forwarded_for") == "6.6.6.6, 198.51.100.4"


# ── the rule, not the two call sites ─────────────────────────────────────────

def test_one_module_reads_the_header():
    readers = []
    for path in API_ROOT.rglob("*.py"):
        if set(path.parts) & {"tests", ".venv", "venv", "__pycache__", "migrations", "node_modules"}:
            continue
        code = re.sub(r'"""(?:.|\n)*?"""', "", path.read_text(encoding="utf-8", errors="replace"))
        code = "\n".join(l.split("#", 1)[0] for l in code.splitlines())
        if re.search(r"x-forwarded-for", code, re.I):
            readers.append(path.relative_to(API_ROOT).as_posix())
    assert readers == ["core/client_ip.py"], (
        f"{readers}: a second reader of X-Forwarded-For is a second opinion about who "
        "the caller is, and the first entry of it is the caller's own")
