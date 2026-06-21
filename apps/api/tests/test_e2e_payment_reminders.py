"""
Phase 5.2 WS-1 — Payment reminders (collections) E2E.

Covers the collections workflow:
  • assess_invoice — the pure aging/overdue computation (integer paise);
  • send_invoice_reminder — manual single-invoice reminder with its guards
    (overdue-only, customer-email-required) and firm scoping;
  • invoice_reminder_history — firm-scoped reminder delivery history.

Negative tenant-isolation: a foreign-firm caller cannot remind on, or see the
reminder history of, another firm's invoice.
"""
from datetime import date

import pytest
from fastapi import HTTPException

import services.collections_service as col
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
T = date(2026, 6, 21)


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [col])
    monkeypatch.setattr(col, "_USE_MOCK", False)
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "name": "Acme", "email": "buyer@acme.test"})
    return db


# --------------------------------------------------------------------------- #
#  assess_invoice — pure aging/overdue computation
# --------------------------------------------------------------------------- #
def test_assess_not_due_invoice():
    m = col.assess_invoice({"total_paise": 100000, "paid_paise": 0, "status": "issued",
                            "due_date": "2026-07-01"}, today=T)
    assert m["is_overdue"] is False and m["outstanding_paise"] == 100000
    assert m["days_overdue"] <= 0                    # negative = days until due


def test_assess_overdue_90_plus():
    m = col.assess_invoice({"total_paise": 100000, "paid_paise": 0, "status": "issued",
                            "due_date": "2026-01-01"}, today=T)
    assert m["is_overdue"] is True
    assert m["days_overdue"] > 90 and m["aging_bucket"] == "90+"


def test_assess_partially_paid_outstanding_only():
    m = col.assess_invoice({"total_paise": 100000, "paid_paise": 40000, "status": "partially_paid",
                            "due_date": "2026-05-01"}, today=T)
    assert m["outstanding_paise"] == 60000 and m["is_overdue"] is True


def test_assess_paid_invoice_not_overdue():
    m = col.assess_invoice({"total_paise": 100000, "paid_paise": 100000, "status": "paid",
                            "due_date": "2026-01-01"}, today=T)
    assert m["is_overdue"] is False and m["outstanding_paise"] == 0
    assert m["aging_bucket"] is None


# --------------------------------------------------------------------------- #
#  send_invoice_reminder — workflow + guards
# --------------------------------------------------------------------------- #
def _overdue_invoice(db, iid="INV", due="2020-01-01", paid=0, status="issued"):
    return db.seed("client_sales_invoices", {
        "id": iid, "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST",
        "invoice_no": "SINV-1", "total_paise": 100000, "paid_paise": paid,
        "status": status, "due_date": due, "deleted_at": None})


def test_send_reminder_on_overdue_invoice(monkeypatch):
    db = _setup(monkeypatch)
    _overdue_invoice(db)
    # Stub the actual dispatch (email/PDF/delivery I/O) — we assert the workflow,
    # not the email transport.
    monkeypatch.setattr(col, "_dispatch_invoice_reminder", lambda *a, **k: True)
    out = col.send_invoice_reminder(FIRM, "INV", actor_id="u1", db=db)
    assert out["sent"] is True and out["to"] == "buyer@acme.test"
    assert out["reminder_number"] == 1


def test_send_reminder_rejected_when_not_overdue(monkeypatch):
    db = _setup(monkeypatch)
    _overdue_invoice(db, due="2099-01-01")          # not yet due
    with pytest.raises(HTTPException) as ei:
        col.send_invoice_reminder(FIRM, "INV", db=db)
    assert ei.value.status_code == 422


def test_send_reminder_requires_customer_email(monkeypatch):
    db = _setup(monkeypatch)
    db.rows("customers")[0]["email"] = None         # no email on file
    _overdue_invoice(db)
    monkeypatch.setattr(col, "_dispatch_invoice_reminder", lambda *a, **k: True)
    with pytest.raises(HTTPException) as ei:
        col.send_invoice_reminder(FIRM, "INV", db=db)
    assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
#  invoice_reminder_history — firm-scoped
# --------------------------------------------------------------------------- #
def test_reminder_history_is_firm_scoped(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "INV", "kind": "reminder"})
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "INV", "kind": "reminder"})
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "INV", "kind": "invoice"})   # not a reminder
    db.seed("invoice_deliveries", {"firm_id": "FIRM-B", "invoice_id": "INV", "kind": "reminder"})  # other firm

    hist = col.invoice_reminder_history(FIRM, "INV", db=db)
    assert len(hist) == 2
    assert all(h["firm_id"] == FIRM and h["kind"] == "reminder" for h in hist)


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_send_reminder_foreign_firm_404(monkeypatch):
    db = _setup(monkeypatch)
    _overdue_invoice(db)
    monkeypatch.setattr(col, "_dispatch_invoice_reminder", lambda *a, **k: True)
    with pytest.raises(HTTPException) as ei:
        col.send_invoice_reminder("FIRM-B", "INV", db=db)   # another firm's invoice
    assert ei.value.status_code == 404


def test_reminder_history_foreign_firm_empty(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("invoice_deliveries", {"firm_id": FIRM, "invoice_id": "INV", "kind": "reminder"})
    assert col.invoice_reminder_history("FIRM-B", "INV", db=db) == []
