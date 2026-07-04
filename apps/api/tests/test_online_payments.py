"""
Phase 4.6 — Online Payments.

Online payments NEVER create accounting. A gateway payment is recorded; on a
signature-VERIFIED capture the EXISTING receipt engine (receipt_service.
create_receipt_core) creates the receipt + allocation + journal + AR update,
AT MOST ONCE per payment. These tests cover:

  • provider abstraction (link creation, HMAC webhook verification)
  • payment links — exact outstanding, idempotency, no-outstanding rejection, firm isolation
  • webhook — valid/invalid signature, replay (same event), duplicate capture
    (same payment), failed + pending produce NO accounting
  • receipt integration — settlement reuses the engine (payment_mode='online'),
    AR reduced once, receipt_id seals idempotency
  • security — firm isolation, portal Pay-Now ownership gate
"""
import json
from datetime import date
from uuid import uuid4

import pytest

import services.payment_service as ps
from services.payments.mock import MockProvider

FIRM = "F1"
OTHER_FIRM = "F2"
CLIENT = "CL-1"
CUSTOMER = "CUST-1"
INVOICE = "INV-1"


# ── Minimal in-memory Supabase double ─────────────────────────────────────────

class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, db, table):
        self._db, self._table = db, table
        self._filters: list[tuple] = []
        self._neq: list[tuple] = []
        self._is: list[tuple] = []
        self._like: list[tuple] = []
        self._in = None
        self._op = "select"
        self._payload = None
        self._limit = None
        self._order = None
        self._count = None

    def select(self, *a, count=None):
        self._op, self._count = "select", count
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def eq(self, col, val):
        self._filters.append((col, val)); return self

    def neq(self, col, val):
        self._neq.append((col, val)); return self

    def is_(self, col, val):
        self._is.append((col, val)); return self

    def like(self, col, pattern):
        self._like.append((col, pattern)); return self

    def in_(self, col, vals):
        self._in = (col, list(vals)); return self

    def limit(self, n):
        self._limit = n; return self

    def order(self, col, desc=False):
        self._order = (col, desc); return self

    def _match(self, row) -> bool:
        if any(row.get(c) != v for c, v in self._filters):
            return False
        if any(row.get(c) == v for c, v in self._neq):
            return False
        for col, val in self._is:
            if val == "null" and row.get(col) is not None:
                return False
        for col, pattern in self._like:
            prefix = pattern.split("%")[0]
            if not str(row.get(col, "")).startswith(prefix):
                return False
        if self._in and row.get(self._in[0]) not in self._in[1]:
            return False
        return True

    def execute(self):
        rows = self._db.data.setdefault(self._table, [])
        if self._op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            if self._order:
                col, desc = self._order
                out.sort(key=lambda r: r.get(col) or "", reverse=desc)
            if self._limit is not None:
                out = out[: self._limit]
            return _Result(out, count=len(out) if self._count else None)
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                r = dict(p)
                r.setdefault("id", f"{self._table[:4]}-{uuid4().hex[:8]}")
                rows.append(r)
                inserted.append(dict(r))
            return _Result(inserted)
        if self._op == "update":
            updated = []
            for r in rows:
                if self._match(r):
                    r.update(self._payload)
                    updated.append(dict(r))
            return _Result(updated)
        return _Result([])


class FakeDB:
    def __init__(self):
        self.data: dict[str, list] = {}

    def table(self, name):
        return _Query(self, name)

    def seed(self, table, row):
        self.data.setdefault(table, []).append(dict(row))
        return row


def _seed_invoice(db, *, firm=FIRM, client=CLIENT, customer=CUSTOMER, iid=INVOICE,
                  total=100000, paid=0, status="issued"):
    db.seed("client_sales_invoices", {
        "id": iid, "firm_id": firm, "client_id": client, "customer_id": customer,
        "invoice_no": f"SINV-{iid}", "total_paise": total, "paid_paise": paid,
        "status": status, "deleted_at": None})
    db.seed("customers", {"id": customer, "firm_id": firm, "name": "Acme", "email": "a@acme.test", "phone": "9"})


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """Silence the non-accounting side effects the engine fires (audit/timeline/journal)."""
    # Explicit mock webhook secret (MockProvider now fails closed without one).
    monkeypatch.setenv("MOCK_WEBHOOK_SECRET", "test_mock_secret")
    monkeypatch.setattr("services.receipt_service.log_event", lambda *a, **k: None)
    monkeypatch.setattr("services.receipt_service._next_receipt_seq", lambda *a, **k: 1)
    monkeypatch.setattr("services.payment_service.log_event", lambda *a, **k: None)
    import services.timeline_service as ts
    monkeypatch.setattr(ts.timeline_service, "log_timeline_event", lambda *a, **k: None)
    import services.phase2_journal_service as js
    monkeypatch.setattr(js.phase2_journal_service, "journal_for_receipt", lambda *a, **k: "JE-mock")
    import services.period_validation_service as pv
    monkeypatch.setattr(pv.period_validation_service, "validate_posting_date", lambda *a, **k: None)


# ── Provider abstraction ──────────────────────────────────────────────────────

def test_mock_provider_create_link_deterministic():
    from services.payments import PaymentLinkRequest
    p = MockProvider()
    r = p.create_payment_link(PaymentLinkRequest(amount_paise=5000, reference_id="L9", description="x"))
    assert r.provider == "mock" and r.provider_link_id == "mock_link_L9" and r.short_url.endswith("/L9")


def test_mock_provider_webhook_signature_valid_and_tampered():
    p = MockProvider()
    headers, body = p.sign_webhook({"id": "evt1", "event": "payment.captured",
                                    "payload": {"payment": {"entity": {"id": "pay1", "amount": 5000}}}})
    assert p.process_webhook(headers, body).signature_verified is True
    # Tamper the body → signature must fail (no exception).
    assert p.process_webhook(headers, body + b" ").signature_verified is False


def test_mock_provider_fails_closed_without_secret(monkeypatch):
    # No hardcoded default → with no secret configured, nothing verifies.
    monkeypatch.delenv("MOCK_WEBHOOK_SECRET", raising=False)
    p = MockProvider()
    ev = p.process_webhook({"x-webhook-signature": "whatever"}, b'{"event":"payment.captured"}')
    assert ev.signature_verified is False
    assert p.verify_payment(order_id="o", payment_id="p", signature="x") is False


def test_get_provider_pins_to_configured(monkeypatch):
    from services.payments import get_provider
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    # The configured provider resolves…
    assert get_provider().name == "razorpay"
    assert get_provider("razorpay").name == "razorpay"
    # …but a mismatched path segment is rejected (webhook can't force mock).
    with pytest.raises(ValueError):
        get_provider("mock")


# ── Payment links (Deliverable D) ─────────────────────────────────────────────

def test_create_link_uses_exact_outstanding():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=30000)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "ca@f.test"})
    assert link["amount_paise"] == 70000 and link["status"] == "active"
    assert link["short_url"] and link["provider"] == "mock"


def test_create_link_is_idempotent_for_same_outstanding():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    a = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    b = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    assert a["id"] == b["id"]
    assert len(db.data["customer_payment_links"]) == 1


def test_create_link_new_when_outstanding_changes():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    a = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    db.data["client_sales_invoices"][0]["paid_paise"] = 40000   # outstanding now 60000
    b = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    assert a["id"] != b["id"] and b["amount_paise"] == 60000


def test_create_link_rejects_when_no_outstanding():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=100000, status="paid")
    with pytest.raises(Exception) as ei:
        ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    assert getattr(ei.value, "status_code", None) == 422


def test_create_link_firm_isolation():
    db = FakeDB(); _seed_invoice(db, firm=OTHER_FIRM)
    with pytest.raises(Exception) as ei:
        ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    assert getattr(ei.value, "status_code", None) == 404


# ── Webhook helpers ────────────────────────────────────────────────────────────

def _captured(db, link, *, event_id, payment_id, amount=None):
    """Build a signed 'payment.captured' webhook correlated to `link`."""
    entity = {"id": payment_id, "order_id": link.get("provider_order_id"),
              "payment_link_id": link.get("provider_link_id"),
              "amount": amount if amount is not None else link["amount_paise"]}
    payload = {"id": event_id, "event": "payment.captured", "payload": {"payment": {"entity": entity}}}
    return MockProvider().sign_webhook(payload)


def _event(db, link, *, event_type, event_id, payment_id):
    entity = {"id": payment_id, "order_id": link.get("provider_order_id"),
              "payment_link_id": link.get("provider_link_id"), "amount": link["amount_paise"]}
    payload = {"id": event_id, "event": event_type, "payload": {"payment": {"entity": entity}}}
    return MockProvider().sign_webhook(payload)


# ── Webhook + receipt integration (Deliverables E, I) ─────────────────────────

def test_webhook_capture_creates_receipt_once_and_reduces_ar():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")

    out = ps.process_webhook(db, "mock", headers, body)
    assert out["ok"] and out["status"] == "captured"

    # exactly one receipt, created via the engine with online mode + allocation
    assert len(db.data["receipts"]) == 1
    rcpt = db.data["receipts"][0]
    assert rcpt["payment_mode"] == "online" and rcpt["amount_paise"] == 100000
    assert db.data["receipt_allocations"][0]["allocated_paise"] == 100000
    # AR reduced through the engine (not by the gateway)
    inv = db.data["client_sales_invoices"][0]
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"
    # payment sealed + link marked paid
    pay = db.data["customer_payments"][0]
    assert pay["receipt_id"] == rcpt["id"] and pay["status"] == "captured"
    assert db.data["customer_payment_links"][0]["status"] == "paid"


def test_webhook_duplicate_event_is_ignored():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")
    ps.process_webhook(db, "mock", headers, body)
    second = ps.process_webhook(db, "mock", headers, body)   # same event id
    assert second.get("duplicate") is True
    assert len(db.data["receipts"]) == 1                      # no second receipt


def test_webhook_second_capture_same_payment_no_second_receipt():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    h1, b1 = _captured(db, link, event_id="evt-1", payment_id="pay-1")
    h2, b2 = _captured(db, link, event_id="evt-2", payment_id="pay-1")  # different event, same payment
    ps.process_webhook(db, "mock", h1, b1)
    ps.process_webhook(db, "mock", h2, b2)
    assert len(db.data["receipts"]) == 1                      # receipt_id seal prevents a second
    assert len(db.data["customer_payments"]) == 1


def test_webhook_rejects_unconfigured_provider(monkeypatch):
    # Pinned: a webhook for a provider that isn't configured is refused outright.
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    db = FakeDB()
    out = ps.process_webhook(db, "mock", {"x-webhook-signature": "x"}, b'{"event":"payment.captured"}')
    assert out["ok"] is False and out["reason"] == "unknown_provider"
    assert db.data.get("customer_payment_events", []) == []   # nothing recorded for a rejected provider


def test_concurrent_capture_double_delivery_settles_once():
    # Simulate two workers that BOTH resolved the same payment with a stale
    # receipt_id=None view (the concurrency window). The atomic claim must let
    # only one settle.
    from services.payments.base import VerifiedEvent
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    db.seed("customer_payments", {
        "id": "P1", "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER,
        "invoice_id": INVOICE, "payment_link_id": link["id"], "amount_paise": 100000,
        "status": "created", "provider": "mock", "provider_payment_id": "pay-1"})
    stale = dict(db.data["customer_payments"][0])   # both workers hold this view
    ev = VerifiedEvent(provider="mock", event_id="e1", event_type="payment.captured",
                       status="captured", signature_verified=True,
                       provider_payment_id="pay-1", amount_paise=100000)
    ps._apply_event(db, dict(stale), ev, FIRM)   # worker A → claims + settles
    ps._apply_event(db, dict(stale), ev, FIRM)   # worker B → claim fails → no-op
    assert len(db.data["receipts"]) == 1
    assert db.data["customer_payments"][0]["receipt_id"] == db.data["receipts"][0]["id"]


def test_journal_failure_reverts_capturing_claim_not_stranded(monkeypatch):
    """F7 follow-up: journal_for_receipt now re-raises instead of swallowing
    posting failures (F7). A failure here must NOT strand the payment in the
    'capturing' sentinel forever — the claim must revert so a retry can settle."""
    import services.phase2_journal_service as js
    monkeypatch.setattr(js.phase2_journal_service, "journal_for_receipt",
                         lambda *a, **k: (_ for _ in ()).throw(ValueError("Required account not found: Bank")))

    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")

    with pytest.raises(ValueError):
        ps.process_webhook(db, "mock", headers, body)

    pay = db.data["customer_payments"][0]
    assert pay["status"] == "captured", "must revert to a claimable status, not stay 'capturing'"
    assert pay.get("receipt_id") is None
    assert db.data.get("receipts", []) == []
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0   # AR untouched

    # A retry (e.g. webhook redelivery) can now re-attempt settlement.
    js.phase2_journal_service.journal_for_receipt = lambda *a, **k: "JE-mock"
    from services.payments.base import VerifiedEvent
    ev = VerifiedEvent(provider="mock", event_id="evt-2", event_type="payment.captured",
                       status="captured", signature_verified=True,
                       provider_payment_id="pay-1", amount_paise=100000)
    ps._apply_event(db, dict(db.data["customer_payments"][0]), ev, FIRM)
    assert len(db.data["receipts"]) == 1
    assert db.data["customer_payments"][0]["receipt_id"] == db.data["receipts"][0]["id"]


def test_webhook_invalid_signature_rejected_no_accounting():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")
    out = ps.process_webhook(db, "mock", headers, body + b"tamper")
    assert out["ok"] is False and out["reason"] == "invalid_signature"
    assert db.data.get("receipts", []) == []
    assert db.data.get("customer_payments", []) == []
    # the failed attempt is recorded for audit, marked unverified
    assert db.data["customer_payment_events"][0]["signature_verified"] is False


def test_webhook_failed_status_no_accounting():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _event(db, link, event_type="payment.failed", event_id="evt-f", payment_id="pay-f")
    out = ps.process_webhook(db, "mock", headers, body)
    assert out["ok"] and out["status"] == "failed"
    assert db.data.get("receipts", []) == []
    assert db.data["customer_payments"][0]["status"] == "failed"
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0   # AR untouched


def test_webhook_pending_status_no_accounting():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _event(db, link, event_type="payment.authorized", event_id="evt-a", payment_id="pay-a")
    out = ps.process_webhook(db, "mock", headers, body)
    assert out["ok"] and out["status"] == "authorized"
    assert db.data.get("receipts", []) == []
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0


def test_webhook_partial_settlement_allocates_capped_to_outstanding():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=90000)   # only 10000 outstanding
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    assert link["amount_paise"] == 10000
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")
    ps.process_webhook(db, "mock", headers, body)
    inv = db.data["client_sales_invoices"][0]
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"


# ── Receipt-engine reuse proof (Deliverable E) ────────────────────────────────

def test_settlement_calls_existing_receipt_engine(monkeypatch):
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    captured_calls = []

    def _spy(firm_id, data, actor, db):  # same signature as receipt_service.create_receipt_core
        captured_calls.append((firm_id, data, actor))
        return {"id": "RCPT-1"}

    monkeypatch.setattr(ps, "create_receipt_core", _spy)
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")
    ps.process_webhook(db, "mock", headers, body)

    assert len(captured_calls) == 1
    firm_id, data, actor = captured_calls[0]
    assert firm_id == FIRM
    assert data["payment_mode"] == "online"
    assert data["allocations"] == [{"sales_invoice_id": INVOICE, "allocated_paise": 100000}]
    assert data["reference_no"] == "pay-1"
    assert actor["email"].startswith("online-payment:")


# ── Security (Deliverable J) ──────────────────────────────────────────────────

def test_history_is_firm_scoped():
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    # Another firm's link on (coincidentally) same invoice id must not leak.
    db.seed("customer_payment_links", {"id": "LX", "firm_id": OTHER_FIRM, "invoice_id": INVOICE,
                                       "client_id": "CLX", "customer_id": "CX", "amount_paise": 1,
                                       "provider": "mock", "status": "active"})
    hist = ps.history(db, FIRM, INVOICE)
    assert all(l["firm_id"] == FIRM for l in hist["links"])
    assert hist["outstanding_paise"] == 100000


# ── Router wiring: webhook + portal Pay-Now ───────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    import routers.payments as pr
    import routers.portal_data as pdr
    db = FakeDB(); _seed_invoice(db, total=100000, paid=0)
    # Drive the real router+service against the FakeDB.
    monkeypatch.setattr(pr, "_db", lambda: db)
    monkeypatch.setattr(pr, "_USE_MOCK", False)
    from core.portal_auth import get_current_portal_client
    app.dependency_overrides[get_current_portal_client] = lambda: {
        "portal": True, "client_id": CLIENT, "firm_id": FIRM, "email": "a@acme.test", "name": "Acme"}
    c = TestClient(app)
    c._fake = db  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.clear()


def test_webhook_route_valid_and_invalid_signature(client):
    db = client._fake  # type: ignore[attr-defined]
    link = ps.create_link(db, FIRM, INVOICE, actor={"auth_user_id": "u1", "email": "x"})
    headers, body = _captured(db, link, event_id="evt-1", payment_id="pay-1")

    ok = client.post("/api/payments/webhook/mock", content=body, headers=headers)
    assert ok.status_code == 200 and ok.json()["data"]["ok"] is True

    bad = client.post("/api/payments/webhook/mock", content=body + b"x", headers=headers)
    assert bad.status_code == 400


def test_portal_pay_ownership_gate(client, monkeypatch):
    import services.portal_data_service as pds
    # Not in scope → 404 (never reveals existence), engine never reached.
    monkeypatch.setattr(pds, "invoice_in_scope", lambda *a, **k: False)
    r = client.post(f"/api/portal/self/invoices/{INVOICE}/pay")
    assert r.status_code == 404
