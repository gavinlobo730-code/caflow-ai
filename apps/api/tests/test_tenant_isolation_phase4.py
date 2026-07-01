"""
Production Readiness Phase 4 — tenant isolation (audit H15/L4) and error-text
non-disclosure (M11).

The backend uses the SERVICE_ROLE key, which BYPASSES RLS, so the ONLY thing
stopping a firm-A user from reading firm-B data via a guessed client_id/vendor_id
is an explicit .eq("firm_id", ...) on every query. These tests drive the real
router functions against a shared DB seeded with TWO firms and assert firm A can
never see firm B's rows.
"""
import pytest
from fastapi import HTTPException

import routers.customers as cu
import routers.vendors as ve
import routers.sales_invoices as si
import routers.credit_notes as cn
from models.parties import VendorIn
from tests.e2e_harness import FakeDB, wire_e2e

# Firm A is the attacker; firm B owns the data. Firm B's client id is "known/guessed".
A = {"firm_id": "FIRM-A", "id": "ua", "auth_user_id": "aa", "email": "a@x.test", "role": "Partner"}
B = {"firm_id": "FIRM-B", "id": "ub", "auth_user_id": "ab", "email": "b@x.test", "role": "Partner"}
CLI_B = "CLI-B"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, ve, si, cn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    # Firm B's data, all under client CLI-B.
    db.seed("customers", {"id": "CUST-B", "firm_id": "FIRM-B", "client_id": CLI_B, "name": "B Cust", "is_active": True})
    db.seed("vendors",   {"id": "VEND-B", "firm_id": "FIRM-B", "client_id": CLI_B, "name": "B Vend",
                          "is_active": True, "state_code": "27"})
    db.seed("client_sales_invoices", {"id": "INV-B", "firm_id": "FIRM-B", "client_id": CLI_B,
                                      "customer_id": "CUST-B", "invoice_no": "B-1", "invoice_date": "2025-06-01",
                                      "status": "issued", "total_paise": 1000, "paid_paise": 0, "credited_paise": 0})
    db.seed("credit_notes", {"id": "CN-B", "firm_id": "FIRM-B", "client_id": CLI_B, "customer_id": "CUST-B",
                             "credit_note_no": "BCN-1", "credit_note_date": "2025-06-02", "status": "issued",
                             "total_paise": 500})
    db.seed("purchase_bills", {"id": "BILL-B", "firm_id": "FIRM-B", "client_id": CLI_B, "vendor_id": "VEND-B",
                               "bill_no": "BB-1", "bill_date": "2025-06-01", "status": "received",
                               "net_payable_paise": 5000})
    return db


# ── Cross-tenant LIST reads must return nothing for the foreign firm ───────────
def test_list_customers_cross_tenant_blocked(monkeypatch):
    db = _setup(monkeypatch)
    assert ve is not None
    assert cu.list_customers(CLI_B, True, A)["data"] == []          # firm A sees nothing
    assert any(c["id"] == "CUST-B" for c in cu.list_customers(CLI_B, True, B)["data"])  # firm B sees it


def test_list_vendors_cross_tenant_blocked(monkeypatch):
    db = _setup(monkeypatch)
    assert ve.list_vendors(CLI_B, True, A)["data"] == []
    assert any(v["id"] == "VEND-B" for v in ve.list_vendors(CLI_B, True, B)["data"])


def test_list_invoices_cross_tenant_blocked(monkeypatch):
    db = _setup(monkeypatch)
    a = si.list_invoices(CLI_B, None, None, None, None, None, None, None, 50, 0, A)
    assert a["data"] == []
    b = si.list_invoices(CLI_B, None, None, None, None, None, None, None, 50, 0, B)
    assert any(i["id"] == "INV-B" for i in b["data"])


def test_list_credit_notes_cross_tenant_blocked(monkeypatch):
    db = _setup(monkeypatch)
    assert cn.list_credit_notes(CLI_B, None, A)["data"] == []
    assert any(c["id"] == "CN-B" for c in cn.list_credit_notes(CLI_B, None, B)["data"])


def test_vendor_outstanding_cross_tenant_404(monkeypatch):
    db = _setup(monkeypatch)
    # Firm A guessing firm B's vendor id → 404 (firm-scoped lookup), never its payables.
    with pytest.raises(HTTPException) as ex:
        ve.get_vendor_outstanding("VEND-B", A)
    assert ex.value.status_code == 404
    # Firm B gets its real outstanding (bill 5000, no payments).
    out = ve.get_vendor_outstanding("VEND-B", B)
    assert out["data"]["outstanding_paise"] == 5000


# ── M11: DB error text is never echoed to the client ──────────────────────────
def test_create_vendor_does_not_leak_db_error(monkeypatch):
    db = _setup(monkeypatch)
    SECRET = "duplicate key value violates unique constraint \"vendors_pkey_SECRET_internal\""

    real_table = db.table
    def boom(name):
        q = real_table(name)
        if name == "vendors":
            orig_insert = q.insert
            def _insert(*a, **k):
                raise RuntimeError(SECRET)
            q.insert = _insert
        return q
    monkeypatch.setattr(db, "table", boom)

    resp = ve.create_vendor(VendorIn(client_id=CLI_B, name="X", gstin="27AAAAA0000A1Z5"), A)
    assert resp["success"] is False
    assert "SECRET" not in (resp["error"] or "")          # raw DB text not disclosed
    assert "constraint" not in (resp["error"] or "").lower() or "data constraint" in (resp["error"] or "").lower()
