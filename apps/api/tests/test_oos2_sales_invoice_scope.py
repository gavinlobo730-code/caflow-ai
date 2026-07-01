"""
Phase 5.1C — OOS-2 closure: sales-invoice mutation endpoints are firm-scoped.

The issue/update/cancel/delete endpoints fetch the invoice by the path id; under
service-role (RLS bypassed) that fetch was NOT firm-scoped, so a firm-A user who
knew a firm-B invoice id could mutate it (issue/edit/cancel/soft-delete). The fix
scopes the fetch (and the update) to the caller's firm, so a foreign invoice now
404s with no mutation. Same-firm behaviour is covered by the existing sales-cycle
regression suite.
"""
import pytest
from fastapi import HTTPException

from models.invoices import SalesInvoiceUpdateIn


class _Result:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, db, table):
        self.db, self.t = db, table
        self.f = []; self.iss = []; self.op = "select"; self.payload = None; self._limit = None

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, p): self.op = "insert"; self.payload = p; return self
    def update(self, p): self.op = "update"; self.payload = p; return self
    def delete(self): self.op = "delete"; return self
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
        if self.op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            if self._limit is not None: out = out[:self._limit]
            return _Result(out)
        if self.op == "update":
            up = [r for r in rows if self._match(r)]
            for r in up: r.update(self.payload)
            return _Result([dict(r) for r in up])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            for p in payload: rows.append(dict(p))
            return _Result(list(payload))
        if self.op == "delete":
            self.db.data[self.t] = [r for r in rows if not self._match(r)]
            return _Result([])
        return _Result([])


class FakeDB:
    def __init__(self): self.data = {}
    def table(self, n): return _Q(self, n)
    def seed(self, t, row): self.data.setdefault(t, []).append(dict(row)); return row


def _setup(monkeypatch, invoice_firm):
    """Seed an invoice owned by `invoice_firm`; force the real (non-mock) DB path."""
    import routers.sales_invoices as si
    import core.supabase_client as sc
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "id": "INV", "firm_id": invoice_firm, "client_id": "A", "status": "draft",
        "total_paise": 100000, "paid_paise": 0, "invoice_no": "S1", "deleted_at": None})
    monkeypatch.setattr(si, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    return si, db


_CALLER = {"firm_id": "F", "auth_user_id": "u", "email": "e@x.test"}


def test_oos2_issue_foreign_firm_404(monkeypatch):
    si, db = _setup(monkeypatch, invoice_firm="OTHER")
    with pytest.raises(HTTPException) as ei:
        si.issue_invoice("INV", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["client_sales_invoices"][0]["status"] == "draft"   # untouched


def test_oos2_update_foreign_firm_404(monkeypatch):
    si, db = _setup(monkeypatch, invoice_firm="OTHER")
    with pytest.raises(HTTPException) as ei:
        si.update_invoice("INV", SalesInvoiceUpdateIn(notes="hijack"), _CALLER)
    assert ei.value.status_code == 404
    assert db.data["client_sales_invoices"][0].get("notes") is None    # not mutated


def test_oos2_cancel_foreign_firm_404(monkeypatch):
    si, db = _setup(monkeypatch, invoice_firm="OTHER")
    with pytest.raises(HTTPException) as ei:
        si.cancel_invoice("INV", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["client_sales_invoices"][0]["status"] == "draft"


def test_oos2_delete_foreign_firm_404(monkeypatch):
    si, db = _setup(monkeypatch, invoice_firm="OTHER")
    with pytest.raises(HTTPException) as ei:
        si.delete_invoice("INV", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["client_sales_invoices"][0]["deleted_at"] is None    # not soft-deleted


def _stub_cancel_accounting(monkeypatch):
    """This file asserts tenant SCOPE only. Cancellation's accounting side-effects
    (FY-lock check + kernel reversal) are exercised in test_invoice_cancellation.py;
    stub them here so the same-firm path proves scope without the real services."""
    import services.period_validation_service as pvs
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(pvs.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(pjs.phase2_journal_service, "reverse_entry", lambda *a, **k: "REV")


def test_oos2_same_firm_cancel_succeeds(monkeypatch):
    si, db = _setup(monkeypatch, invoice_firm="F")
    # A realistic issued invoice carries its posted journal; cancel reverses it.
    db.data["client_sales_invoices"][0]["status"] = "issued"
    db.data["client_sales_invoices"][0]["journal_entry_id"] = "J1"
    _stub_cancel_accounting(monkeypatch)
    monkeypatch.setattr(si, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(si.timeline_service, "log_timeline_event", lambda *a, **k: None)
    si.cancel_invoice("INV", _CALLER)
    assert db.data["client_sales_invoices"][0]["status"] == "cancelled"   # same-firm still works
