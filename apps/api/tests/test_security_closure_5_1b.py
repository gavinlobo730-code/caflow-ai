"""
Phase 5.1B — Security closure verification (F1 + F2 + F3).

F1 — receipt allocation write-scope: a receipt can neither read nor mutate an
     invoice outside its (firm, client); cross-client/cross-firm attempts are
     rejected (422) or hidden (404) with NO accounting change.
F2 — compliance assignment isolation: get_client_health is assignment-gated;
     get_firm_summary is scoped to the caller's assigned clients.
F3 — bank settlement execution: _settle_doc is scoped to the txn's (firm, client);
     a foreign matched entity is not settled and its state is unchanged.

Exercises the real (non-mock) code paths via an in-memory Supabase double.
"""
import pytest
from fastapi import HTTPException


# ── In-memory Supabase double ─────────────────────────────────────────────────

class _Result:
    def __init__(self, data, count=None):
        self.data = data; self.count = count


class _Q:
    def __init__(self, db, table):
        self.db, self.t = db, table
        self.f = []; self.neqs = []; self.iss = []
        self.op = "select"; self.payload = None; self.single = False; self._limit = None

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, p): self.op = "insert"; self.payload = p; return self
    def update(self, p): self.op = "update"; self.payload = p; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def neq(self, c, v): self.neqs.append((c, v)); return self
    def is_(self, c, v): self.iss.append((c, v)); return self
    def limit(self, n): self._limit = n; return self
    def order(self, *a, **k): return self
    def maybe_single(self): self.single = True; return self
    def single(self): self.single = True; return self

    def _match(self, row):
        if any(row.get(c) != v for c, v in self.f): return False
        if any(row.get(c) == v for c, v in self.neqs): return False
        for c, v in self.iss:
            if v == "null" and row.get(c) is not None: return False
        return True

    def execute(self):
        rows = self.db.data.setdefault(self.t, [])
        if self.op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            if self._limit is not None: out = out[:self._limit]
            return _Result(out[0] if out else None) if self.single else _Result(out)
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in payload:
                r = dict(p); r.setdefault("id", f"{self.t[:3]}-{len(rows) + 1}")
                rows.append(r); ins.append(dict(r))
            return _Result(ins)
        if self.op == "update":
            up = []
            for r in rows:
                if self._match(r): r.update(self.payload); up.append(dict(r))
            return _Result(up)
        if self.op == "delete":
            keep = [r for r in rows if not self._match(r)]
            self.db.data[self.t] = keep
            return _Result([])
        return _Result([])


class FakeDB:
    def __init__(self): self.data = {}
    def table(self, n): return _Q(self, n)
    def seed(self, t, row): self.data.setdefault(t, []).append(dict(row)); return row


@pytest.fixture
def receipt_engine_quiet(monkeypatch):
    """Silence create_receipt_core's non-accounting side effects."""
    monkeypatch.setattr("services.receipt_service.log_event", lambda *a, **k: None)
    monkeypatch.setattr("services.receipt_service._next_receipt_seq", lambda *a, **k: 1)
    import services.phase2_journal_service as js
    monkeypatch.setattr(js.phase2_journal_service, "journal_for_receipt", lambda *a, **k: "JE")
    import services.timeline_service as ts
    monkeypatch.setattr(ts.timeline_service, "log_timeline_event", lambda *a, **k: None)
    import services.period_validation_service as pv
    monkeypatch.setattr(pv.period_validation_service, "validate_posting_date", lambda *a, **k: None)


# ── F1 — receipt allocation write scope ───────────────────────────────────────

def test_f1_create_receipt_blocks_foreign_client_invoice(receipt_engine_quiet):
    from services.receipt_service import create_receipt_core
    db = FakeDB()
    db.seed("client_sales_invoices", {"id": "INV-B", "firm_id": "F", "client_id": "B",
                                      "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    data = {"client_id": "A", "customer_id": "C", "receipt_date": "2024-06-01", "amount_paise": 50000,
            "allocations": [{"sales_invoice_id": "INV-B", "allocated_paise": 50000}]}
    with pytest.raises(HTTPException) as ei:
        create_receipt_core("F", data, {"auth_user_id": "u", "email": "e@x.test"}, db)
    assert ei.value.status_code == 422
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0   # foreign invoice untouched
    assert db.data.get("receipts", []) == []                        # no orphan receipt


def test_f1_create_receipt_blocks_foreign_firm_invoice(receipt_engine_quiet):
    from services.receipt_service import create_receipt_core
    db = FakeDB()
    db.seed("client_sales_invoices", {"id": "INV-X", "firm_id": "OTHER", "client_id": "A",
                                      "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    data = {"client_id": "A", "customer_id": "C", "receipt_date": "2024-06-01", "amount_paise": 50000,
            "allocations": [{"sales_invoice_id": "INV-X", "allocated_paise": 50000}]}
    with pytest.raises(HTTPException) as ei:
        create_receipt_core("F", data, {"auth_user_id": "u", "email": "e@x.test"}, db)
    assert ei.value.status_code == 422
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0


def test_f1_create_receipt_same_client_ok(receipt_engine_quiet):
    from services.receipt_service import create_receipt_core
    db = FakeDB()
    db.seed("client_sales_invoices", {"id": "INV-A", "firm_id": "F", "client_id": "A",
                                      "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    data = {"client_id": "A", "customer_id": "C", "receipt_date": "2024-06-01", "amount_paise": 100000,
            "allocations": [{"sales_invoice_id": "INV-A", "allocated_paise": 100000}]}
    out = create_receipt_core("F", data, {"auth_user_id": "u", "email": "e@x.test"}, db)
    assert out["receipt_no"]
    inv = db.data["client_sales_invoices"][0]
    assert inv["paid_paise"] == 100000 and inv["status"] == "paid"   # legit same-client settle works


def test_f1_update_allocations_blocks_foreign_invoice(monkeypatch):
    import routers.receipts as rc
    import core.supabase_client as sc
    from models.invoices import ReceiptAllocationIn, ReceiptAllocationsUpdateIn
    db = FakeDB()
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    monkeypatch.setattr(rc, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    db.seed("receipts", {"id": "R", "firm_id": "F", "client_id": "A", "amount_paise": 100000})
    db.seed("client_sales_invoices", {"id": "INV-B", "firm_id": "F", "client_id": "B",
                                      "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    body = ReceiptAllocationsUpdateIn(allocations=[ReceiptAllocationIn(sales_invoice_id="INV-B", allocated_paise=50000)])
    with pytest.raises(HTTPException) as ei:
        rc.update_allocations("R", body, {"firm_id": "F", "auth_user_id": "u", "email": "e@x.test"})
    assert ei.value.status_code == 422
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0   # foreign invoice untouched


def test_f1_update_allocations_foreign_firm_receipt_404(monkeypatch):
    import routers.receipts as rc
    import core.supabase_client as sc
    from models.invoices import ReceiptAllocationIn, ReceiptAllocationsUpdateIn
    db = FakeDB()
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    monkeypatch.setattr(rc, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    db.seed("receipts", {"id": "R", "firm_id": "OTHER", "client_id": "A", "amount_paise": 100000})
    body = ReceiptAllocationsUpdateIn(allocations=[ReceiptAllocationIn(sales_invoice_id="INV", allocated_paise=10000)])
    with pytest.raises(HTTPException) as ei:
        rc.update_allocations("R", body, {"firm_id": "F", "auth_user_id": "u", "email": "e@x.test"})
    assert ei.value.status_code == 404


# ── F2 — compliance assignment isolation ──────────────────────────────────────

def test_f2_client_health_blocks_unassigned(monkeypatch):
    import routers.compliance_records as cr
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client", lambda u, c: c == "A")
    monkeypatch.setattr(cr.compliance_record_service, "get_client_health_score",
                        lambda cid, firm_id=None: {"client_id": cid, "health_score": 100})
    with pytest.raises(HTTPException) as ei:
        cr.get_client_health("B", {"firm_id": "F", "role": "Executive", "id": "u"})
    assert ei.value.status_code == 404


def test_f2_client_health_allows_assigned(monkeypatch):
    import routers.compliance_records as cr
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client", lambda u, c: c == "A")
    monkeypatch.setattr(cr.compliance_record_service, "get_client_health_score",
                        lambda cid, firm_id=None: {"client_id": cid, "health_score": 88})
    out = cr.get_client_health("A", {"firm_id": "F", "role": "Executive", "id": "u"})
    assert out["data"]["health_score"] == 88


def test_f2_firm_summary_scoped_to_assigned(monkeypatch):
    import routers.compliance_records as cr
    captured = {}

    def fake_summary(firm_id=None, allowed_client_ids=None):
        captured["allowed"] = allowed_client_ids
        return {"overdue": 0}

    monkeypatch.setattr(cr.compliance_record_service, "get_firm_summary", fake_summary)
    monkeypatch.setattr(cr, "effective_client_ids", lambda u: {"A"})       # non firm-wide ⇒ scoped
    cr.get_firm_summary({"firm_id": "F", "role": "Executive", "id": "u"})
    assert captured["allowed"] == {"A"}

    monkeypatch.setattr(cr, "effective_client_ids", lambda u: None)        # firm-wide ⇒ unscoped
    cr.get_firm_summary({"firm_id": "F", "role": "Partner", "id": "p"})
    assert captured["allowed"] is None


def test_f2_firm_summary_service_filters(monkeypatch):
    """The service-side scope actually drops other clients' records from the aggregate."""
    from domain.compliance_record_service import compliance_record_service as svc
    monkeypatch.setattr(svc, "list_records",
                        lambda firm_id=None: [{"client_id": "A", "status": "Overdue", "due_date": "2020-01-01"},
                                              {"client_id": "B", "status": "Overdue", "due_date": "2020-01-01"}])
    import domain.compliance_record_service as crs
    monkeypatch.setattr(crs.client_repo, "find_all", lambda firm_id=None: [])
    scoped = svc.get_firm_summary(firm_id="F", allowed_client_ids={"A"})
    assert scoped["overdue"] == 1            # only client A's overdue counted
    full = svc.get_firm_summary(firm_id="F", allowed_client_ids=None)
    assert full["overdue"] == 2              # firm-wide sees both


# ── F3 — bank settlement execution client scope ───────────────────────────────

def test_f3_settle_blocks_foreign_client_no_state_change():
    from services.bank_posting_service import bank_posting_service as svc
    db = FakeDB()
    db.seed("client_sales_invoices", {"id": "INV-A", "firm_id": "F", "client_id": "X",
                                      "invoice_no": "S1", "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    # Authorized: txn for client X settles X's invoice.
    own = {"category": "Customer Payment", "matched_entity_type": "sales_invoice",
           "matched_entity_id": "INV-A", "client_id": "X"}
    res = svc._settle(db, "F", own, 50000)
    assert res and res["allocated_paise"] == 50000
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 50000

    # Unauthorized: a txn for client Y cannot settle X's invoice; state unchanged.
    db.data["client_sales_invoices"][0]["paid_paise"] = 0
    foreign = {"category": "Customer Payment", "matched_entity_type": "sales_invoice",
               "matched_entity_id": "INV-A", "client_id": "Y"}
    res2 = svc._settle(db, "F", foreign, 50000)
    assert res2 is None
    assert db.data["client_sales_invoices"][0]["paid_paise"] == 0   # no accounting change on denial
