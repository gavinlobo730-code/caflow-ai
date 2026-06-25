"""
Tests for the PUBLIC engagement-letter signing endpoints (no login).

A prospect opens a tokenized link, reviews the letter, and electronically accepts
(typed name + consent) or declines. The unguessable token is the credential; the
response must expose only a client-safe projection (no firm internals).
"""
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest

import routers.engagement_sign_public as esp
from routers.engagement_sign_public import view_letter, sign_letter, reject_letter, SignBody, RejectBody

FIRM = "firm-aaa"
TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"  # 43 chars, passes length guard


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db = db; self.t = table; self._op = "select"; self._payload = None; self._single = False

    def select(self, *a, **k):
        self._op = "select"; return self

    def insert(self, p):
        self._op = "insert"; self._payload = p
        self.db.inserts.setdefault(self.t, []).append(p); return self

    def update(self, p):
        self._op = "update"; self._payload = p
        self.db.updates.setdefault(self.t, []).append(p); return self

    def eq(self, *a, **k): return self
    def maybe_single(self): self._single = True; return self
    def single(self): self._single = True; return self

    def execute(self):
        if self._op == "select":
            rows = self.db.selects.get(self.t, [])
            return _Res(rows[0] if rows else None) if self._single else _Res(list(rows))
        if self._op == "insert":
            p = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Res(p)
        if self._op == "update":
            return _Res([self._payload])
        return _Res(None)


class FakeDB:
    def __init__(self):
        self.selects = {}; self.inserts = {}; self.updates = {}

    def table(self, name):
        return _Q(self, name)


class FakeRequest:
    def __init__(self, ip="203.0.113.5", ua="pytest-UA", xff=None):
        h = {"user-agent": ua}
        if xff:
            h["x-forwarded-for"] = xff
        self.headers = h
        self.client = type("C", (), {"host": ip})()


def _eng(**over):
    base = {
        "id": "E1", "firm_id": FIRM, "lead_id": "L1", "client_id": None,
        "status": "Sent", "engagement_number": "EL-2026-0001",
        "title": "GST Compliance — FY26",
        "content": "<h2>Engagement Letter</h2><p>Our fee is ₹5,000 per month.</p>",
        "recipient_name": "Patel Foods Pvt. Ltd.",
        "recipient_email": "owner@patelfoods.in",
        "sign_token": TOKEN,
    }
    base.update(over)
    return base


@contextmanager
def world(db):
    with patch.object(esp, "_db", return_value=db), \
         patch.object(esp, "_advance_lead") as adv, \
         patch("services.audit_service.log_event"):
        yield adv


# ── view ──────────────────────────────────────────────────────────────────────

def test_view_marks_sent_as_viewed():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Sent")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db):
        res = view_letter(TOKEN, FakeRequest())
    assert res["success"] is True
    assert res["data"]["status"] == "Viewed"
    assert res["data"]["firm_name"] == "Sharma & Co"
    assert any(u.get("status") == "Viewed" for u in db.updates["engagements"])
    assert any(e.get("event_type") == "viewed" for e in db.inserts.get("engagement_events", []))


def test_view_invalid_short_token_404():
    from fastapi import HTTPException
    db = FakeDB()
    with world(db):
        with pytest.raises(HTTPException) as exc:
            view_letter("short", FakeRequest())
    assert exc.value.status_code == 404


def test_view_unknown_token_404():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = []  # maybe_single → None
    with world(db):
        with pytest.raises(HTTPException) as exc:
            view_letter(TOKEN, FakeRequest())
    assert exc.value.status_code == 404


def test_view_projection_does_not_leak_internal_fields():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Viewed")]  # no Sent→Viewed write needed
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db):
        res = view_letter(TOKEN, FakeRequest())
    assert set(res["data"].keys()) == {
        "engagement_number", "title", "content", "status", "recipient_name",
        "firm_name", "signed_at", "signed_by_name", "rejected_at",
    }
    # Never leak ids, the token, IP, or email.
    for leaked in ("id", "firm_id", "lead_id", "client_id", "sign_token", "signed_ip", "recipient_email"):
        assert leaked not in res["data"]


# ── sign ──────────────────────────────────────────────────────────────────────

def test_sign_records_signature_and_advances_lead():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Viewed")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db) as adv:
        res = sign_letter(TOKEN, SignBody(signer_name="Rahul Patel", consent=True), FakeRequest())
    assert res["success"] is True
    assert res["data"]["status"] == "Signed"
    assert res["data"]["signed_by_name"] == "Rahul Patel"
    upd = db.updates["engagements"][-1]
    assert upd["status"] == "Signed"
    assert upd["signed_by_name"] == "Rahul Patel"
    assert upd["signed_ip"] == "203.0.113.5"
    assert upd["signed_user_agent"] == "pytest-UA"
    # Lead advanced forward-only to Engagement Signed, with a synthetic actor.
    adv.assert_called_once_with("L1", FIRM, "Engagement Signed",
                                {"auth_user_id": None, "email": "owner@patelfoods.in"})
    assert any(e.get("event_type") == "signed" for e in db.inserts.get("engagement_events", []))


def test_sign_requires_consent():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Viewed")]
    with world(db) as adv:
        res = sign_letter(TOKEN, SignBody(signer_name="Rahul", consent=False), FakeRequest())
    assert res["success"] is False
    assert "consent" in res["error"].lower()
    assert "engagements" not in db.updates
    adv.assert_not_called()


def test_sign_requires_name():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Viewed")]
    with world(db):
        res = sign_letter(TOKEN, SignBody(signer_name="   ", consent=True), FakeRequest())
    assert res["success"] is False
    assert "name" in res["error"].lower()


def test_sign_is_idempotent_when_already_signed():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Signed", signed_by_name="Rahul Patel")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db) as adv:
        res = sign_letter(TOKEN, SignBody(signer_name="Someone Else", consent=True), FakeRequest())
    assert res["success"] is True
    assert res["data"]["status"] == "Signed"
    assert res["data"]["signed_by_name"] == "Rahul Patel"   # unchanged
    assert "engagements" not in db.updates                  # no re-write
    adv.assert_not_called()


def test_sign_rejected_when_not_actionable():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Draft")]
    with world(db):
        res = sign_letter(TOKEN, SignBody(signer_name="Rahul", consent=True), FakeRequest())
    assert res["success"] is False
    assert "Draft" in res["error"]
    assert "engagements" not in db.updates


def test_sign_uses_forwarded_client_ip():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Viewed")]
    with world(db):
        res = sign_letter(TOKEN, SignBody(signer_name="Rahul", consent=True),
                          FakeRequest(xff="9.9.9.9, 10.0.0.1"))
    assert res["success"] is True
    assert db.updates["engagements"][-1]["signed_ip"] == "9.9.9.9"


# ── reject ────────────────────────────────────────────────────────────────────

def test_reject_records_rejection():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Sent")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db):
        res = reject_letter(TOKEN, RejectBody(reason="Fee too high"), FakeRequest())
    assert res["success"] is True
    assert res["data"]["status"] == "Rejected"
    upd = db.updates["engagements"][-1]
    assert upd["status"] == "Rejected"
    assert upd["rejection_notes"] == "Fee too high"
    assert any(e.get("event_type") == "rejected" for e in db.inserts.get("engagement_events", []))


def test_reject_blocked_when_already_signed():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Signed")]
    with world(db):
        res = reject_letter(TOKEN, RejectBody(reason="changed mind"), FakeRequest())
    assert res["success"] is False
    assert "engagements" not in db.updates
