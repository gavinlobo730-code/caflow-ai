"""
Phase 5.1C — OOS-5 closure: by-id WRITE endpoints are firm-scoped.

The mutation endpoints on customers (update/deactivate), vendors
(update/deactivate), purchase bills (update/receive/cancel) and credit notes
(issue) located their target row by the path id alone. Under service-role
(RLS bypassed — see core/security_config.py) that means a firm-A user who knew
a firm-B id could mutate another firm's master data or post a journal against
it. The fix firm-scopes both the guard read and the UPDATE statement, so a
foreign-firm id now 404s with NO mutation.

These tests prove, per endpoint:
  * foreign-firm id ⇒ HTTP 404 AND the seeded row is left untouched (the
    security assertion — a cross-firm write must not land), and
  * same-firm id ⇒ the write succeeds (regression: legitimate use still works).
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerUpdateIn, VendorUpdateIn
from models.invoices import PurchaseBillUpdateIn


# --------------------------------------------------------------------------
# In-memory Supabase double (select/insert/update/delete + eq/is_/order/limit)
# --------------------------------------------------------------------------
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


_CALLER = {"firm_id": "F", "auth_user_id": "u", "email": "e@x.test"}


def _wire(monkeypatch, router_mod, db):
    """Force the real (non-mock) DB path and route the client to our FakeDB."""
    import core.supabase_client as sc
    monkeypatch.setattr(router_mod, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    # Silence audit side-effects so same-firm success paths don't hit real services.
    monkeypatch.setattr(router_mod, "log_event", lambda *a, **k: None)


# ==========================================================================
# customers — update / deactivate
# ==========================================================================
def _seed_customer(monkeypatch, firm):
    import routers.customers as cu
    db = FakeDB(); _wire(monkeypatch, cu, db)
    db.seed("customers", {"id": "CUST", "firm_id": firm, "client_id": "A",
                          "name": "orig", "is_active": True})
    return cu, db


def test_oos5_customer_update_foreign_firm_404(monkeypatch):
    cu, db = _seed_customer(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        cu.update_customer("CUST", CustomerUpdateIn(name="hijack"), _CALLER)
    assert ei.value.status_code == 404
    assert db.data["customers"][0]["name"] == "orig"          # not mutated


def test_oos5_customer_update_same_firm_ok(monkeypatch):
    cu, db = _seed_customer(monkeypatch, "F")
    resp = cu.update_customer("CUST", CustomerUpdateIn(name="hijack"), _CALLER)
    assert resp["success"] is True
    assert db.data["customers"][0]["name"] == "hijack"        # same-firm still works


def test_oos5_customer_delete_foreign_firm_404(monkeypatch):
    cu, db = _seed_customer(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        cu.delete_customer("CUST", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["customers"][0]["is_active"] is True       # not soft-deleted


def test_oos5_customer_delete_same_firm_ok(monkeypatch):
    cu, db = _seed_customer(monkeypatch, "F")
    resp = cu.delete_customer("CUST", _CALLER)
    assert resp["success"] is True
    assert db.data["customers"][0]["is_active"] is False


# ==========================================================================
# vendors — update / deactivate
# ==========================================================================
def _seed_vendor(monkeypatch, firm):
    import routers.vendors as ve
    db = FakeDB(); _wire(monkeypatch, ve, db)
    db.seed("vendors", {"id": "VEND", "firm_id": firm, "client_id": "A",
                        "name": "orig", "is_active": True})
    return ve, db


def test_oos5_vendor_update_foreign_firm_404(monkeypatch):
    ve, db = _seed_vendor(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        ve.update_vendor("VEND", VendorUpdateIn(name="hijack"), _CALLER)
    assert ei.value.status_code == 404
    assert db.data["vendors"][0]["name"] == "orig"


def test_oos5_vendor_update_same_firm_ok(monkeypatch):
    ve, db = _seed_vendor(monkeypatch, "F")
    resp = ve.update_vendor("VEND", VendorUpdateIn(name="hijack"), _CALLER)
    assert resp["success"] is True
    assert db.data["vendors"][0]["name"] == "hijack"


def test_oos5_vendor_delete_foreign_firm_404(monkeypatch):
    ve, db = _seed_vendor(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        ve.delete_vendor("VEND", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["vendors"][0]["is_active"] is True


def test_oos5_vendor_delete_same_firm_ok(monkeypatch):
    ve, db = _seed_vendor(monkeypatch, "F")
    resp = ve.delete_vendor("VEND", _CALLER)
    assert resp["success"] is True
    assert db.data["vendors"][0]["is_active"] is False


# ==========================================================================
# purchase bills — update / receive / cancel
# ==========================================================================
def _seed_bill(monkeypatch, firm, status="draft"):
    import routers.purchase_bills as pb
    db = FakeDB(); _wire(monkeypatch, pb, db)
    monkeypatch.setattr(pb.timeline_service, "log_timeline_event", lambda *a, **k: None)
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_purchase_bill", lambda **k: "JID")
    db.seed("purchase_bills", {"id": "BILL", "firm_id": firm, "client_id": "A",
                               "status": status, "total_paise": 100000})
    return pb, db


def test_oos5_bill_update_foreign_firm_404(monkeypatch):
    pb, db = _seed_bill(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        pb.update_purchase_bill("BILL", PurchaseBillUpdateIn(notes="hijack"), _CALLER)
    assert ei.value.status_code == 404
    assert db.data["purchase_bills"][0].get("notes") is None
    assert db.data["purchase_bills"][0]["status"] == "draft"


def test_oos5_bill_update_same_firm_ok(monkeypatch):
    pb, db = _seed_bill(monkeypatch, "F")
    resp = pb.update_purchase_bill("BILL", PurchaseBillUpdateIn(notes="hi"), _CALLER)
    assert resp["success"] is True
    assert db.data["purchase_bills"][0]["notes"] == "hi"


def test_oos5_bill_receive_foreign_firm_404(monkeypatch):
    pb, db = _seed_bill(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        pb.receive_purchase_bill("BILL", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["purchase_bills"][0]["status"] == "draft"   # no journal posted


def test_oos5_bill_receive_same_firm_ok(monkeypatch):
    pb, db = _seed_bill(monkeypatch, "F")
    resp = pb.receive_purchase_bill("BILL", _CALLER)
    assert resp["success"] is True
    assert db.data["purchase_bills"][0]["status"] == "received"


def test_oos5_bill_cancel_foreign_firm_404(monkeypatch):
    pb, db = _seed_bill(monkeypatch, "OTHER", status="received")
    with pytest.raises(HTTPException) as ei:
        pb.cancel_purchase_bill("BILL", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["purchase_bills"][0]["status"] == "received"  # not cancelled


def test_oos5_bill_cancel_same_firm_ok(monkeypatch):
    pb, db = _seed_bill(monkeypatch, "F", status="received")
    resp = pb.cancel_purchase_bill("BILL", _CALLER)
    assert resp["success"] is True
    assert db.data["purchase_bills"][0]["status"] == "cancelled"


# ==========================================================================
# credit notes — issue
# ==========================================================================
def _seed_cn(monkeypatch, firm, status="draft"):
    import routers.credit_notes as cn
    db = FakeDB(); _wire(monkeypatch, cn, db)
    monkeypatch.setattr(cn.timeline_service, "log_timeline_event", lambda *a, **k: None)
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_credit_note", lambda **k: "JID")
    db.seed("credit_notes", {"id": "CN", "firm_id": firm, "client_id": "A",
                             "status": status, "total_paise": 50000})
    return cn, db


def test_oos5_credit_note_issue_foreign_firm_404(monkeypatch):
    cn, db = _seed_cn(monkeypatch, "OTHER")
    with pytest.raises(HTTPException) as ei:
        cn.issue_credit_note("CN", _CALLER)
    assert ei.value.status_code == 404
    assert db.data["credit_notes"][0]["status"] == "draft"     # not issued


def test_oos5_credit_note_issue_same_firm_ok(monkeypatch):
    cn, db = _seed_cn(monkeypatch, "F")
    resp = cn.issue_credit_note("CN", _CALLER)
    assert resp["success"] is True
    assert db.data["credit_notes"][0]["status"] == "issued"
