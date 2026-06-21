"""
Phase 5.1C — read-path sweep (OOS-4 + siblings).

The by-id READ detail endpoints (get_invoice, get_purchase_bill, get_customer,
get_vendor, get_credit_note) fetched tenant rows by id with no firm scope —
under service-role (RLS bypassed) that disclosed another firm's data to anyone
who knew the id. These tests prove each now firm-scopes the fetch: a foreign-firm
id ⇒ 404; a same-firm id ⇒ returned.
"""
import pytest
from fastapi import HTTPException


class _Result:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.t = db, table
        self.f = []; self.iss = []; self.op = "select"; self._limit = None

    def select(self, *a, **k): return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def is_(self, c, v): self.iss.append((c, v)); return self
    def order(self, *a, **k): return self
    def limit(self, n): self._limit = n; return self

    def _match(self, row):
        if any(row.get(c) != v for c, v in self.f): return False
        for c, v in self.iss:
            if v in (None, "null") and row.get(c) is not None: return False
        return True

    def execute(self):
        rows = self.db.data.setdefault(self.t, [])
        out = [dict(r) for r in rows if self._match(r)]
        if self._limit is not None: out = out[:self._limit]
        return _Result(out)


class FakeDB:
    def __init__(self): self.data = {}
    def table(self, n): return _Q(self, n)
    def seed(self, t, row): self.data.setdefault(t, []).append(dict(row)); return row


CALLER = {"firm_id": "F", "auth_user_id": "u", "email": "e@x.test"}


def _wire(monkeypatch, router_mod, db):
    import core.supabase_client as sc
    monkeypatch.setattr(router_mod, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)


def test_oos4_get_invoice_foreign_firm_404(monkeypatch):
    import routers.sales_invoices as si
    db = FakeDB(); _wire(monkeypatch, si, db)
    db.seed("client_sales_invoices", {"id": "INV", "firm_id": "OTHER", "client_id": "A", "deleted_at": None})
    with pytest.raises(HTTPException) as ei:
        si.get_invoice("INV", CALLER)
    assert ei.value.status_code == 404


def test_get_purchase_bill_foreign_firm_404(monkeypatch):
    import routers.purchase_bills as pb
    db = FakeDB(); _wire(monkeypatch, pb, db)
    db.seed("purchase_bills", {"id": "BILL", "firm_id": "OTHER", "client_id": "A"})
    with pytest.raises(HTTPException) as ei:
        pb.get_purchase_bill("BILL", CALLER)
    assert ei.value.status_code == 404


def test_get_customer_foreign_firm_404(monkeypatch):
    import routers.customers as cu
    db = FakeDB(); _wire(monkeypatch, cu, db)
    db.seed("customers", {"id": "CUST", "firm_id": "OTHER", "name": "Acme"})
    with pytest.raises(HTTPException) as ei:
        cu.get_customer("CUST", CALLER)
    assert ei.value.status_code == 404


def test_get_customer_same_firm_ok(monkeypatch):
    import routers.customers as cu
    db = FakeDB(); _wire(monkeypatch, cu, db)
    db.seed("customers", {"id": "CUST", "firm_id": "F", "name": "Acme"})
    resp = cu.get_customer("CUST", CALLER)
    assert resp["success"] is True and resp["data"]["id"] == "CUST"


def test_get_vendor_foreign_firm_404(monkeypatch):
    import routers.vendors as ve
    db = FakeDB(); _wire(monkeypatch, ve, db)
    db.seed("vendors", {"id": "VEND", "firm_id": "OTHER", "name": "Supplier"})
    with pytest.raises(HTTPException) as ei:
        ve.get_vendor("VEND", CALLER)
    assert ei.value.status_code == 404


def test_get_credit_note_foreign_firm_404(monkeypatch):
    import routers.credit_notes as cn
    db = FakeDB(); _wire(monkeypatch, cn, db)
    db.seed("credit_notes", {"id": "CN", "firm_id": "OTHER", "client_id": "A"})
    with pytest.raises(HTTPException) as ei:
        cn.get_credit_note("CN", CALLER)
    assert ei.value.status_code == 404
