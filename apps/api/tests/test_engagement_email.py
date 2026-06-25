"""
Tests for engagement-letter email delivery ("Send to Client").

The DB-backed /send path actually emails the letter to the client (rendered
inline in the body, with a PDF copy attached) via the firm's email provider, and
only advances the letter to "Sent" when the email goes out. A failed delivery
leaves the letter in its current status so the CA knows it did not send.

No financial arithmetic is performed in this path — the fee is already rendered
upstream — so these tests assert delivery behaviour, not money math.
"""
import logging
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest

import routers.engagement_letters as el
from routers.engagement_letters import send_engagement, SendIn

FIRM = "firm-aaa"
USER = {"auth_user_id": "u-mgr", "firm_id": FIRM, "role": "Manager", "email": "mgr@firm.in"}


# ── Minimal fake Supabase client ──────────────────────────────────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db = db
        self.t = table
        self._op = "select"
        self._payload = None
        self._single = False

    def select(self, *a, **k):
        self._op = "select"; return self

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
            if self._single:
                return _Res(rows[0] if rows else None)
            return _Res(list(rows))
        if self._op == "insert":
            p = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Res(p)
        if self._op == "update":
            # Echo back the engagement row merged with the update so callers see
            # the new status; other tables just echo the payload.
            if self.t == "engagements":
                rows = self.db.selects.get("engagements", [])
                base = dict(rows[0]) if rows else {}
                base.update(self._payload)
                return _Res([base])
            return _Res([self._payload])
        return _Res(None)


class FakeDB:
    def __init__(self):
        self.selects = {}
        self.inserts = {}
        self.updates = {}

    def table(self, name):
        return _Q(self, name)


def _eng(**over):
    base = {
        "id": "E1", "firm_id": FIRM, "lead_id": "L1", "client_id": None,
        "status": "Generated", "engagement_number": "EL-2026-0001",
        "title": "GST Compliance — FY26",
        "content": "<h2>Engagement Letter</h2><p>Our fee is ₹5,000 per month.</p>",
        "recipient_name": "Patel Foods Pvt. Ltd.",
        "recipient_email": "owner@patelfoods.in",
    }
    base.update(over)
    return base


@contextmanager
def mock_send(
    db,
    email_result=(True, "resend-msg-1"),
    pdf=(b"%PDF-1.4 fake", "engagement-letter-EL-2026-0001.pdf"),
    pdf_raises=False,
):
    """Patch the send path: DB, lead-advance, audit log, email transport, PDF render."""
    email_mock = MagicMock(return_value=email_result)
    pdf_mock = MagicMock(side_effect=RuntimeError("pdf boom")) if pdf_raises \
        else MagicMock(return_value=pdf)
    with patch.object(el, "_db", return_value=db), \
         patch.object(el, "_advance_lead"), \
         patch.object(el, "log_event"), \
         patch("services.email_service.send_engagement_letter", email_mock), \
         patch("services.engagement_pdf_service.render_engagement_pdf", pdf_mock):
        yield email_mock, pdf_mock


# ── Happy path ────────────────────────────────────────────────────────────────

def test_send_emails_letter_and_advances():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with mock_send(db) as (email_mock, _):
        res = send_engagement("E1", current_user=USER)
    assert res["success"] is True
    assert res["data"]["engagement"]["status"] == "Sent"
    assert res["data"]["delivery"]["to"] == "owner@patelfoods.in"
    assert res["data"]["delivery"]["provider_message_id"] == "resend-msg-1"
    # Email actually attempted, with the rendered body + a PDF attachment.
    email_mock.assert_called_once()
    kwargs = email_mock.call_args.kwargs
    assert kwargs["to"] == "owner@patelfoods.in"
    assert kwargs["pdf_bytes"] == b"%PDF-1.4 fake"
    assert kwargs["firm_name"] == "Sharma & Co"
    assert kwargs["letter_html"].startswith("<h2>Engagement Letter</h2>")
    # Engagement persisted as Sent.
    assert any(u.get("status") == "Sent" for u in db.updates["engagements"])


def test_to_email_override_wins():
    db = FakeDB()
    db.selects["engagements"] = [_eng(recipient_email="default@x.in")]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with mock_send(db) as (email_mock, _):
        res = send_engagement("E1", body=SendIn(to_email="override@y.in"), current_user=USER)
    assert res["success"] is True
    assert email_mock.call_args.kwargs["to"] == "override@y.in"


def test_resolves_email_from_lead_when_letter_has_none():
    db = FakeDB()
    db.selects["engagements"] = [_eng(recipient_email=None)]
    db.selects["leads"] = [{"email": "lead@patelfoods.in"}]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with mock_send(db) as (email_mock, _):
        res = send_engagement("E1", current_user=USER)
    assert res["success"] is True
    assert email_mock.call_args.kwargs["to"] == "lead@patelfoods.in"


# ── Failure paths leave the letter unsent ─────────────────────────────────────

def test_no_email_anywhere_fails_and_does_not_advance():
    db = FakeDB()
    db.selects["engagements"] = [_eng(recipient_email=None, lead_id=None, client_id=None)]
    with mock_send(db) as (email_mock, _):
        res = send_engagement("E1", current_user=USER)
    assert res["success"] is False
    assert "No email address" in res["error"]
    email_mock.assert_not_called()
    assert "engagements" not in db.updates  # status never changed
    assert any(e.get("event_type") == "send_failed"
               for e in db.inserts.get("engagement_events", []))


def test_delivery_failure_does_not_advance():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with mock_send(db, email_result=(False, None)) as (email_mock, _):
        res = send_engagement("E1", current_user=USER)
    assert res["success"] is False
    # The user sees a friendly, non-technical message — and the SAME message is
    # echoed in data.delivery.error. Internal config/provider details never leak.
    assert res["error"] == (
        "We couldn't send the engagement email right now. "
        "Please try again later or contact your administrator."
    )
    assert res["data"]["delivery"]["error"] == res["error"]
    for leak in ("RESEND_API_KEY", "Resend", "recipient address", "httpx"):
        assert leak not in res["error"]
    email_mock.assert_called_once()
    assert "engagements" not in db.updates   # engagement remains, status unchanged
    assert any(e.get("event_type") == "send_failed"
               for e in db.inserts.get("engagement_events", []))


def test_invalid_email_is_rejected():
    db = FakeDB()
    db.selects["engagements"] = [_eng(recipient_email="not-an-email")]
    with mock_send(db) as (email_mock, _):
        res = send_engagement("E1", current_user=USER)
    assert res["success"] is False
    assert "Invalid email" in res["error"]
    email_mock.assert_not_called()
    assert "engagements" not in db.updates


def test_pdf_failure_falls_back_to_body_only():
    db = FakeDB()
    db.selects["engagements"] = [_eng()]
    db.selects["firms"] = [{"name": "Sharma & Co"}]
    with mock_send(db, pdf_raises=True) as (email_mock, _):
        res = send_engagement("E1", current_user=USER)
    # The full letter is in the body, so a PDF failure must not block delivery.
    assert res["success"] is True
    assert email_mock.call_args.kwargs["pdf_bytes"] is None
    assert email_mock.call_args.kwargs["pdf_filename"] is None
    assert res["data"]["engagement"]["status"] == "Sent"


# ── Status guards ─────────────────────────────────────────────────────────────

def test_wrong_status_returns_409():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = [_eng(status="Sent")]
    with mock_send(db):
        with pytest.raises(HTTPException) as exc:
            send_engagement("E1", current_user=USER)
    assert exc.value.status_code == 409


def test_not_found_returns_404():
    from fastapi import HTTPException
    db = FakeDB()
    db.selects["engagements"] = []
    with mock_send(db):
        with pytest.raises(HTTPException) as exc:
            send_engagement("E1", current_user=USER)
    assert exc.value.status_code == 404


# ── PDF service ───────────────────────────────────────────────────────────────

def test_pdf_safe_substitutes_rupee_glyph():
    # ₹ (U+20B9) is absent from PDF core fonts; the PDF copy uses "Rs." instead.
    from services.engagement_pdf_service import _pdf_safe
    assert _pdf_safe("Professional fee is ₹5,000 per month") == \
        "Professional fee is Rs. 5,000 per month"
    assert _pdf_safe(None) == ""


def test_render_engagement_pdf_produces_pdf_bytes():
    pytest.importorskip("xhtml2pdf")
    from services.engagement_pdf_service import render_engagement_pdf
    pdf, filename = render_engagement_pdf(
        "<h2>Engagement</h2><p>Fee ₹5000</p>", "EL-2026-0001"
    )
    assert pdf[:4] == b"%PDF"
    assert filename == "engagement-letter-EL-2026-0001.pdf"


# ── Email helper ──────────────────────────────────────────────────────────────

def test_email_send_uses_attachment_when_pdf_present():
    import services.email_service as es
    with patch.object(es, "_send_with_attachment", return_value=(True, "id-1")) as att, \
         patch.object(es, "_send", return_value=True) as plain:
        ok, mid = es.send_engagement_letter(
            to="c@x.in", recipient_name="Client", firm_name="F",
            engagement_number="EL-1", title="GST", letter_html="<p>the terms</p>",
            pdf_bytes=b"%PDF", pdf_filename="el.pdf",
        )
    assert ok is True and mid == "id-1"
    att.assert_called_once()
    plain.assert_not_called()
    # The letter html is embedded in the email body (3rd positional arg).
    assert "the terms" in att.call_args.args[2]


def test_email_send_body_only_when_no_pdf():
    import services.email_service as es
    with patch.object(es, "_send_with_attachment", return_value=(True, "x")) as att, \
         patch.object(es, "_send", return_value=True) as plain:
        ok, mid = es.send_engagement_letter(
            to="c@x.in", recipient_name="Client", firm_name="F",
            engagement_number="EL-1", title="GST", letter_html="<p>the terms</p>",
        )
    assert ok is True and mid is None
    plain.assert_called_once()
    att.assert_not_called()


# ── Transport layer: failures logged IN FULL server-side, never leaked to user ─
#
# Maps to the prompt's QA matrix: missing API key, invalid API key (provider
# rejection), and network failure each return False and write the full provider
# detail (status, error code/name, body) to the SERVER LOG only.

class _FakeResp:
    """Minimal stand-in for an httpx.Response from Resend."""

    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def test_send_missing_api_key_warns_and_returns_false(caplog):
    # QA: "Missing API key" — distinguishable in logs, no send attempted.
    import services.email_service as es
    with patch.object(es, "_RESEND_API_KEY", ""):
        with caplog.at_level(logging.WARNING):
            ok = es._send("client@x.in", "Subject", "<p>hi</p>")
    assert ok is False
    # The env var IS named in the server log (for the admin) …
    assert "RESEND_API_KEY" in caplog.text


def test_send_logs_full_provider_error_and_returns_false(caplog):
    # QA: "Invalid API key" / unverified domain — provider rejects with a body
    # that explains exactly why; that full detail must reach the server log.
    import services.email_service as es
    fake = _FakeResp(
        422,
        {"name": "validation_error", "statusCode": 422,
         "message": "The from address is not verified."},
        text='{"name":"validation_error","message":"The from address is not verified."}',
    )
    with patch.object(es, "_RESEND_API_KEY", "re_test"), \
         patch("httpx.post", return_value=fake):
        with caplog.at_level(logging.ERROR):
            ok = es._send("client@x.in", "Subject", "<p>hi</p>")
    assert ok is False
    blob = caplog.text
    assert "422" in blob
    assert "validation_error" in blob
    assert "not verified" in blob          # the provider body is captured verbatim


def test_send_network_error_logs_and_returns_false(caplog):
    # QA: "Network failure" — transport exception logged, non-fatal False return.
    import services.email_service as es

    def boom(*a, **k):
        raise RuntimeError("connection reset by peer")

    with patch.object(es, "_RESEND_API_KEY", "re_test"), \
         patch("httpx.post", side_effect=boom):
        with caplog.at_level(logging.ERROR):
            ok = es._send("client@x.in", "Subject", "<p>hi</p>")
    assert ok is False
    assert "connection reset by peer" in caplog.text


def test_send_with_attachment_logs_provider_error(caplog):
    import services.email_service as es
    fake = _FakeResp(
        401,
        {"name": "unauthorized", "statusCode": 401, "message": "Invalid API key"},
        text='{"name":"unauthorized","message":"Invalid API key"}',
    )
    with patch.object(es, "_RESEND_API_KEY", "re_bad"), \
         patch("httpx.post", return_value=fake):
        with caplog.at_level(logging.ERROR):
            ok, mid = es._send_with_attachment(
                "client@x.in", "Subject", "<p>hi</p>", b"%PDF", "f.pdf"
            )
    assert ok is False and mid is None
    assert "401" in caplog.text
    assert "Invalid API key" in caplog.text


def test_generic_failure_message_exposes_no_internals():
    # The user-facing copy must not name the env var, the provider, or transport.
    from services.email_service import GENERIC_SEND_FAILURE_MESSAGE
    for leak in ("RESEND_API_KEY", "Resend", "httpx", "API key"):
        assert leak not in GENERIC_SEND_FAILURE_MESSAGE
