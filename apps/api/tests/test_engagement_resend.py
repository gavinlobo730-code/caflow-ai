"""
Tests for the engagement RESEND & signing-link management workflow:
  * POST   /{id}/resend            — resend the same letter, reuse token
  * GET    /{id}/signing-link      — copy the exact emailed signing URL
  * PATCH  /{id}/recipient         — change recipient (+ optional resend)
  * POST   /{id}/regenerate-link   — mint a new token, invalidating old links
  * GET    /{id}/pdf               — re-download the (deterministic) PDF

Core guarantees verified here:
  - resend reuses the existing sign_token (old links stay valid)
  - regenerate replaces the token (old links die, new link works)
  - last_sent_at + resend_count track send history; status never changes
  - signed / deleted / expired engagements are handled safely
  - every resend writes a chronological audit event
No financial arithmetic is involved, so these assert workflow behaviour only.
"""
import os
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest

import routers.engagement_letters as el
from routers.engagement_letters import (
    resend_engagement, get_signing_link, change_recipient,
    regenerate_link, download_engagement_pdf,
    ResendIn, RecipientIn, RegenerateLinkIn,
)

FIRM = "firm-aaa"
USER = {"auth_user_id": "u-mgr", "firm_id": FIRM, "role": "Manager", "email": "mgr@firm.in"}
ORIG_TOKEN = "ORIGtoken_abcdefghijklmnopqrstuvwxyz0123456789AB"   # 43+ chars


# ── Minimal fake Supabase client (mirrors test_engagement_email) ──────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db = db; self.t = table; self._op = "select"; self._payload = None; self._single = False

    def select(self, *a, **k): self._op = "select"; return self
    def insert(self, p):
        self._op = "insert"; self._payload = p
        self.db.inserts.setdefault(self.t, []).append(p); return self
    def update(self, p):
        self._op = "update"; self._payload = p
        self.db.updates.setdefault(self.t, []).append(p); return self
    def eq(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def single(self): self._single = True; return self
    def maybe_single(self): self._single = True; return self

    def execute(self):
        if self._op == "select":
            rows = self.db.selects.get(self.t, [])
            return _Res(rows[0] if rows else None) if self._single else _Res(list(rows))
        if self._op == "insert":
            p = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Res(p)
        if self._op == "update":
            if self.t == "engagements":
                rows = self.db.selects.get("engagements", [])
                base = dict(rows[0]) if rows else {}
                base.update(self._payload)
                return _Res([base])
            return _Res([self._payload])
        return _Res(None)


class FakeDB:
    def __init__(self):
        self.selects = {}; self.inserts = {}; self.updates = {}
    def table(self, name): return _Q(self, name)


def _eng(**over):
    base = {
        "id": "E1", "firm_id": FIRM, "lead_id": "L1", "client_id": None,
        "status": "Sent", "engagement_number": "EL-2026-0001",
        "title": "GST Compliance — FY26",
        "content": "<h2>Engagement Letter</h2><p>Our fee is ₹5,000 per month.</p>",
        "recipient_name": "Patel Foods Pvt. Ltd.",
        "recipient_email": "owner@patelfoods.in",
        "sign_token": ORIG_TOKEN,
        "sent_at": "2026-06-25T10:00:00+00:00",
        "last_sent_at": "2026-06-25T10:00:00+00:00",
        "resend_count": 0,
        "is_deleted": False,
        "expiry_date": None,
    }
    base.update(over)
    return base


@contextmanager
def world(db, email_result=(True, "resend-msg-1"), pdf=(b"%PDF-1.4 fake", "el.pdf")):
    email_mock = MagicMock(return_value=email_result)
    pdf_mock = MagicMock(return_value=pdf)
    with patch.object(el, "_db", return_value=db), \
         patch.object(el, "_advance_lead"), \
         patch.object(el, "log_event"), \
         patch("services.email_service.send_engagement_letter", email_mock), \
         patch("services.engagement_pdf_service.render_engagement_pdf", pdf_mock):
        yield email_mock, pdf_mock


def _last_update(db):
    return db.updates["engagements"][-1]


def _events(db, kind):
    return [e for e in db.inserts.get("engagement_events", []) if e.get("event_type") == kind]


# ── Resend once ────────────────────────────────────────────────────────────────

def test_resend_once_reuses_token_and_bumps_history():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with patch.dict(os.environ, {"FRONTEND_URL": "https://app.test"}):
        with world(db) as (email_mock, _):
            res = resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert res["success"] is True
    assert res["data"]["delivery"]["to"] == "owner@patelfoods.in"
    upd = _last_update(db)
    # History advanced; status untouched; token NOT rotated (reused).
    assert upd["resend_count"] == 1
    assert "last_sent_at" in upd
    assert "status" not in upd
    assert "sign_token" not in upd                 # existing token reused, not rewritten
    # The emailed link carries the ORIGINAL token, so old shares keep working.
    assert email_mock.call_args.kwargs["sign_url"].endswith(f"/sign/?t={ORIG_TOKEN}")
    assert len(_events(db, "resent")) == 1


def test_resend_does_not_change_status():
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Viewed")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db):
        res = resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert res["success"] is True
    assert "status" not in _last_update(db)


# ── Resend multiple times ────────────────────────────────────────────────────

def test_resend_multiple_times_increments_count():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db):
        resend_engagement("E1", body=ResendIn(), current_user=USER)
        resend_engagement("E1", body=ResendIn(), current_user=USER)
        resend_engagement("E1", body=ResendIn(), current_user=USER)
    # 1 → 2 → 3 across three resends (total sends = 4 incl. the original).
    counts = [u["resend_count"] for u in db.updates["engagements"]]
    assert counts == [1, 2, 3]
    assert len(_events(db, "resent")) == 3


# ── One-off override address (does not persist) ──────────────────────────────

def test_resend_one_off_override_address():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db) as (email_mock, _):
        res = resend_engagement("E1", body=ResendIn(to_email="gmail@x.in"), current_user=USER)
    assert res["success"] is True
    assert email_mock.call_args.kwargs["to"] == "gmail@x.in"
    # recipient_email is NOT persisted by a one-off resend.
    assert "recipient_email" not in _last_update(db)


# ── Copy signing link ────────────────────────────────────────────────────────

def test_copy_signing_link_returns_exact_url():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    with patch.dict(os.environ, {"FRONTEND_URL": "https://caflow-ai.pages.dev"}):
        with world(db):
            res = get_signing_link("E1", current_user=USER)
    assert res["success"] is True
    assert res["data"]["sign_url"] == f"https://caflow-ai.pages.dev/sign/?t={ORIG_TOKEN}"
    assert res["data"]["sign_token"] == ORIG_TOKEN


def test_copy_signing_link_409_when_not_awaiting():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Signed")]
    with world(db):
        with pytest.raises(HTTPException) as exc:
            get_signing_link("E1", current_user=USER)
    assert exc.value.status_code == 409


# ── Download PDF ─────────────────────────────────────────────────────────────

def test_download_pdf_returns_pdf_response():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    with world(db) as (_, pdf_mock):
        resp = download_engagement_pdf("E1", current_user=USER)
    assert resp.media_type == "application/pdf"
    assert resp.body == b"%PDF-1.4 fake"
    assert "attachment" in resp.headers["content-disposition"]
    pdf_mock.assert_called_once()


def test_download_pdf_404_when_deleted():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng(is_deleted=True)]
    with world(db):
        with pytest.raises(HTTPException) as exc:
            download_engagement_pdf("E1", current_user=USER)
    assert exc.value.status_code == 404


# ── Change recipient (+ resend) ──────────────────────────────────────────────

def test_change_recipient_persists_without_resend():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    with world(db) as (email_mock, _):
        res = change_recipient("E1", RecipientIn(recipient_email="new@gmail.com"), current_user=USER)
    assert res["success"] is True
    assert _last_update(db)["recipient_email"] == "new@gmail.com"
    assert len(_events(db, "recipient_changed")) == 1
    email_mock.assert_not_called()             # no resend requested


def test_change_recipient_and_resend_uses_new_address():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db) as (email_mock, _):
        res = change_recipient(
            "E1", RecipientIn(recipient_email="new@gmail.com", resend=True), current_user=USER)
    assert res["success"] is True
    assert email_mock.call_args.kwargs["to"] == "new@gmail.com"
    # token reused even when resending to the new address
    assert email_mock.call_args.kwargs["sign_url"] is None or ORIG_TOKEN in (email_mock.call_args.kwargs["sign_url"] or "")
    assert len(_events(db, "resent")) == 1


def test_resend_after_recipient_change_goes_to_new_email():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db) as (email_mock, _):
        change_recipient("E1", RecipientIn(recipient_email="new@gmail.com"), current_user=USER)
        res = resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert res["success"] is True
    assert email_mock.call_args.kwargs["to"] == "new@gmail.com"


def test_change_recipient_rejects_invalid_email():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    with world(db):
        with pytest.raises(HTTPException) as exc:
            change_recipient("E1", RecipientIn(recipient_email="not-an-email"), current_user=USER)
    assert exc.value.status_code == 422


# ── Regenerate link ──────────────────────────────────────────────────────────

def test_regenerate_link_replaces_token():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    with world(db):
        res = regenerate_link("E1", body=RegenerateLinkIn(), current_user=USER)
    assert res["success"] is True
    upd = _last_update(db)
    assert "sign_token" in upd
    assert upd["sign_token"] != ORIG_TOKEN          # a brand-new token
    assert len(upd["sign_token"]) >= 32
    assert len(_events(db, "link_regenerated")) == 1


def test_old_token_invalid_after_regeneration():
    # After regeneration the stored token differs from the original, so a public
    # lookup by the OLD token finds nothing (link invalidated).
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    with world(db):
        regenerate_link("E1", body=RegenerateLinkIn(), current_user=USER)
    new_token = db.updates["engagements"][-1]["sign_token"]
    assert new_token != ORIG_TOKEN
    assert db.selects["engagements"][0]["sign_token"] == new_token   # store rotated


def test_regenerate_and_resend_emails_new_link():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with patch.dict(os.environ, {"FRONTEND_URL": "https://app.test"}):
        with world(db) as (email_mock, _):
            res = regenerate_link("E1", body=RegenerateLinkIn(resend=True), current_user=USER)
    assert res["success"] is True
    new_token = db.selects["engagements"][0]["sign_token"]
    assert new_token != ORIG_TOKEN
    # The resent email carries the NEW token, not the old one.
    assert email_mock.call_args.kwargs["sign_url"].endswith(f"/sign/?t={new_token}")
    assert ORIG_TOKEN not in email_mock.call_args.kwargs["sign_url"]


def test_old_token_still_valid_after_normal_resend():
    # A normal resend must NEVER rotate the token (old links keep working).
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db):
        resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert db.selects["engagements"][0]["sign_token"] == ORIG_TOKEN
    assert all("sign_token" not in u for u in db.updates["engagements"])


# ── Signed / deleted / expired behaviour ─────────────────────────────────────

def test_cannot_resend_signed_engagement():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Signed")]
    with world(db):
        with pytest.raises(HTTPException) as exc:
            resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert exc.value.status_code == 409


def test_cannot_regenerate_signed_engagement():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Signed")]
    with world(db):
        with pytest.raises(HTTPException) as exc:
            regenerate_link("E1", body=RegenerateLinkIn(), current_user=USER)
    assert exc.value.status_code == 409


def test_cannot_resend_deleted_engagement():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng(is_deleted=True)]
    with world(db):
        with pytest.raises(HTTPException) as exc:
            resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert exc.value.status_code == 404


def test_expired_resend_needs_confirmation_then_force_sends():
    db = FakeDB()
    db.selects["engagements"] = [_eng(expiry_date="2020-01-01")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db) as (email_mock, _):
        # First attempt: blocked with a confirmation prompt, no email sent.
        res1 = resend_engagement("E1", body=ResendIn(), current_user=USER)
        assert res1["success"] is False
        assert res1["data"]["needs_confirmation"] is True
        assert res1["data"]["reason"] == "expired"
        email_mock.assert_not_called()
        # Second attempt with force: actually resends.
        res2 = resend_engagement("E1", body=ResendIn(force=True), current_user=USER)
    assert res2["success"] is True
    assert email_mock.call_count == 1
    assert _last_update(db)["resend_count"] == 1


def test_resend_delivery_failure_keeps_status_and_does_not_bump():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with world(db, email_result=(False, None)):
        res = resend_engagement("E1", body=ResendIn(), current_user=USER)
    assert res["success"] is False
    # No history bump on a failed send; a resend_failed event is recorded.
    assert all("resend_count" not in u for u in db.updates.get("engagements", []))
    assert len(_events(db, "resend_failed")) == 1
    assert len(_events(db, "resent")) == 0
