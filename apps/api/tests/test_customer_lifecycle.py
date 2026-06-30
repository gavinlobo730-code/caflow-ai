"""
Customer lifecycle — Active / Inactive / Deleted (CAFLOW lifecycle QA).

  * Deactivate (soft delete) flips is_active=False; the row and all history stay.
  * Reactivate flips it back via update_customer.
  * Permanent delete is allowed ONLY when there are no linked accounting records
    (invoices, receipts, credit notes, recurring templates, opening balance).
    Every FK to customers is ON DELETE CASCADE, so this guard — not the DB — is
    what protects the books; with dependencies the API must refuse with 409.
"""
import pytest
from fastapi import HTTPException

import routers.customers as cust
from models.parties import CustomerIn, CustomerUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
GSTIN_A = "27AAAAA0000A1Z5"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cust])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN_A})
    return db


def _new(db, **over):
    row = {"id": over.get("id", "CUST"), "firm_id": FIRM, "client_id": "CLI",
           "name": "Acme", "is_active": True, "opening_balance_paise": 0}
    row.update(over)
    return db.seed("customers", row)


# ── deactivate / reactivate ──────────────────────────────────────────────────

def test_deactivate_keeps_row_and_history(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST")
    db.seed("client_sales_invoices", {"customer_id": "CUST", "firm_id": FIRM})

    res = cust.delete_customer("CUST", permanent=False, current_user=CALLER)
    assert res["success"] and res["data"]["is_active"] is False
    row = next(r for r in db.rows("customers") if r["id"] == "CUST")
    assert row["is_active"] is False                       # still present
    assert len(db.rows("client_sales_invoices")) == 1      # history intact


def test_reactivate_via_update(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST", is_active=False)
    res = cust.update_customer("CUST", CustomerUpdateIn(is_active=True), CALLER)
    assert res["success"] and res["data"]["is_active"] is True


# ── dependency report ────────────────────────────────────────────────────────

def test_dependencies_none_allows_delete(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST")
    res = cust.get_customer_dependencies("CUST", CALLER)
    assert res["data"]["can_delete"] is True
    assert res["data"]["total"] == 0


@pytest.mark.parametrize("table", ["client_sales_invoices", "receipts", "credit_notes", "recurring_invoice_templates"])
def test_dependencies_block_when_records_exist(monkeypatch, table):
    db = _setup(monkeypatch)
    _new(db, id="CUST")
    db.seed(table, {"customer_id": "CUST", "firm_id": FIRM})
    res = cust.get_customer_dependencies("CUST", CALLER)
    assert res["data"]["can_delete"] is False
    assert res["data"]["total"] >= 1


def test_opening_balance_counts_as_dependency(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST", opening_balance_paise=500_00)
    res = cust.get_customer_dependencies("CUST", CALLER)
    assert res["data"]["can_delete"] is False
    assert res["data"]["dependencies"]["opening_balance"] == 1


# ── permanent delete guard ───────────────────────────────────────────────────

def test_permanent_delete_blocked_with_invoices(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST")
    db.seed("client_sales_invoices", {"customer_id": "CUST", "firm_id": FIRM})

    with pytest.raises(HTTPException) as ei:
        cust.delete_customer("CUST", permanent=True, current_user=CALLER)
    assert ei.value.status_code == 409
    # The customer (and its invoice) must NOT be touched.
    assert any(r["id"] == "CUST" for r in db.rows("customers"))
    assert len(db.rows("client_sales_invoices")) == 1


def test_permanent_delete_succeeds_when_clean(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST")
    res = cust.delete_customer("CUST", permanent=True, current_user=CALLER)
    assert res["success"] and res["data"]["deleted"] is True
    assert not any(r["id"] == "CUST" for r in db.rows("customers"))   # row gone


def test_permanent_delete_blocked_by_opening_balance(monkeypatch):
    db = _setup(monkeypatch)
    _new(db, id="CUST", opening_balance_paise=1)
    with pytest.raises(HTTPException) as ei:
        cust.delete_customer("CUST", permanent=True, current_user=CALLER)
    assert ei.value.status_code == 409
    assert any(r["id"] == "CUST" for r in db.rows("customers"))


def test_permanent_delete_unknown_customer_404(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        cust.delete_customer("NOPE", permanent=True, current_user=CALLER)
    assert ei.value.status_code == 404
