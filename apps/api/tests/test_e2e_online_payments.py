"""
Phase 5.2 WS-1 — Online payments E2E (ledger reconciliation).

The existing tests/test_online_payments.py proves the gateway plumbing (signature,
dedupe, idempotency, firm isolation) but MOCKS journal_for_receipt — so it never
proves the online-payment path posts real accounting. This E2E closes that gap:

  issue invoice (AR posted) → create_link → signed 'captured' webhook →
  receipt via the engine → REAL journal (Dr Bank / Cr AR)

Asserts the capture settles through the receipt engine, AR clears, the Bank
ledger is debited, and the trial balance ties out — plus a cross-firm leg
(no link for another firm's invoice).
"""
import pytest

import services.payment_service as ps
from services.payments.mock import MockProvider
from models.invoices import SalesInvoiceIn, InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
ACTOR = {"auth_user_id": "u1", "email": "ca@firma.test"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    import routers.receipts as rc
    import services.receipt_service as rs
    db = FakeDB()
    monkeypatch.setenv("MOCK_WEBHOOK_SECRET", "test_mock_secret")
    wire_e2e(monkeypatch, db, [si, rc, rs, ps])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "email": "buyer@acme.test", "state_code": "27",
                          "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    return si, db


def _issued_invoice(si):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        lines=[InvoiceLineIn(description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _captured(link, *, event_id, payment_id, amount=None):
    entity = {"id": payment_id, "order_id": link.get("provider_order_id"),
              "payment_link_id": link.get("provider_link_id"),
              "amount": amount if amount is not None else link["amount_paise"]}
    payload = {"id": event_id, "event": "payment.captured",
               "payload": {"payment": {"entity": entity}}}
    return MockProvider().sign_webhook(payload)


def test_online_payment_capture_posts_real_receipt_journal(monkeypatch):
    si, db = _setup(monkeypatch)
    inv = _issued_invoice(si)
    inv_id = inv["id"]

    # After issue: AR carries the full total; trial balance balanced.
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 1_180_000

    # Customer pays online via a hosted link for the exact outstanding.
    link = ps.create_link(db, FIRM, inv_id, actor=ACTOR)
    assert link["amount_paise"] == 1_180_000 and link["status"] == "active"

    headers, body = _captured(link, event_id="evt-1", payment_id="pay-1")
    out = ps.process_webhook(db, "mock", headers, body)
    assert out["ok"] and out["status"] == "captured"

    # Settled through the receipt engine (payment_mode online).
    assert len(db.rows("receipts")) == 1
    assert db.rows("receipts")[0]["payment_mode"] == "online"

    # Invoice fully paid; payment sealed; link marked paid.
    paid_inv = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert paid_inv["paid_paise"] == 1_180_000 and paid_inv["status"] == "paid"
    pay = db.rows("customer_payments")[0]
    assert pay["status"] == "captured" and pay["receipt_id"]
    assert db.rows("customer_payment_links")[0]["status"] == "paid"

    # REAL ledger reconciliation: receipt journal posted Dr Bank / Cr AR.
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 2_360_000  # invoice + receipt
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0                  # AR cleared
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 1_180_000        # Dr Bank = cash


def test_online_payment_duplicate_event_posts_one_journal(monkeypatch):
    si, db = _setup(monkeypatch)
    inv = _issued_invoice(si)
    link = ps.create_link(db, FIRM, inv["id"], actor=ACTOR)
    headers, body = _captured(link, event_id="evt-1", payment_id="pay-1")

    ps.process_webhook(db, "mock", headers, body)
    second = ps.process_webhook(db, "mock", headers, body)   # replay same event
    assert second.get("duplicate") is True

    assert len(db.rows("receipts")) == 1                       # no second receipt
    # Ledger has exactly one receipt journal (AR still net zero, not double-credited).
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 1_180_000


def test_online_payment_failed_event_no_accounting(monkeypatch):
    si, db = _setup(monkeypatch)
    inv = _issued_invoice(si)
    link = ps.create_link(db, FIRM, inv["id"], actor=ACTOR)
    entity = {"id": "pay-f", "payment_link_id": link.get("provider_link_id"),
              "amount": link["amount_paise"]}
    headers, body = MockProvider().sign_webhook(
        {"id": "evt-f", "event": "payment.failed", "payload": {"payment": {"entity": entity}}})
    out = ps.process_webhook(db, "mock", headers, body)
    assert out["ok"] and out["status"] == "failed"
    assert db.rows("receipts") == []                           # no receipt
    # AR untouched (only the issue journal exists).
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 1_180_000


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation leg
# --------------------------------------------------------------------------- #
def test_online_payment_link_foreign_firm_404(monkeypatch):
    si, db = _setup(monkeypatch)
    inv = _issued_invoice(si)
    with pytest.raises(Exception) as ei:
        ps.create_link(db, "FIRM-B", inv["id"], actor=ACTOR)   # invoice belongs to FIRM-A
    assert getattr(ei.value, "status_code", None) == 404
