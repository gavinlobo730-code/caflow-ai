"""
Phase 5.1A — Audit remediation verification (C1 + H1–H4).

Proves each release-blocking finding is closed and behaviour is preserved:
  H1 — workload cross-firm user lookup → 404 (no PII disclosure)
  H2 — compliance_records list/get respect client-assignment scope
  H3 — receipt re-allocation recomputes paid_paise from scratch (no AR drift,
       idempotent, stable, reverts to issued on full de-allocation)
  H4 — bank settlement preview scoped to the txn's firm+client (no disclosure)

These exercise the real (non-mock) code paths via an in-memory Supabase double
and monkeypatched authz primitives (mock-mode authz is intentionally permissive).
"""
import pytest
from fastapi import HTTPException


# ── In-memory Supabase double (only the chains these endpoints use) ───────────

class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Q:
    def __init__(self, db, table):
        self.db, self.t = db, table
        self.f = []; self.neqs = []; self.iss = []; self.gtes = []
        self.op = "select"; self.payload = None; self.single = False; self._limit = None

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, p): self.op = "insert"; self.payload = p; return self
    def update(self, p): self.op = "update"; self.payload = p; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def neq(self, c, v): self.neqs.append((c, v)); return self
    def gte(self, c, v): self.gtes.append((c, v)); return self
    def is_(self, c, v): self.iss.append((c, v)); return self
    def or_(self, *_a, **_k): return self            # no-op for tests
    def limit(self, n): self._limit = n; return self
    def order(self, *a, **k): return self
    def maybe_single(self): self.single = True; return self

    def _match(self, row):
        if any(row.get(c) != v for c, v in self.f): return False
        if any(row.get(c) == v for c, v in self.neqs): return False
        for c, v in self.iss:
            if v == "null" and row.get(c) is not None: return False
        for c, v in self.gtes:
            if not (str(row.get(c, "")) >= str(v)): return False
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
            removed = len(rows) - len(keep)
            self.db.data[self.t] = keep
            return _Result([{} for _ in range(removed)])
        return _Result([])


class FakeDB:
    def __init__(self): self.data = {}
    def table(self, n): return _Q(self, n)
    def seed(self, t, row): self.data.setdefault(t, []).append(dict(row)); return row


# ── H1 — workload cross-firm user PII ─────────────────────────────────────────

def test_h1_cross_firm_user_lookup_404(monkeypatch):
    import routers.workload as wl
    db = FakeDB()
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    db.seed("users", {"id": "U-B", "firm_id": "FIRM-B", "full_name": "Bob", "email": "b@x.test", "role": "Executive"})
    with pytest.raises(HTTPException) as ei:
        wl.get_user_workload("U-B", {"firm_id": "FIRM-A"})
    assert ei.value.status_code == 404          # existence hidden, no PII leaked


def test_h1_same_firm_user_ok(monkeypatch):
    import routers.workload as wl
    db = FakeDB()
    monkeypatch.setattr(wl, "_get_db", lambda: db)
    db.seed("users", {"id": "U-A", "firm_id": "FIRM-A", "full_name": "Alice", "email": "a@x.test", "role": "Executive"})
    resp = wl.get_user_workload("U-A", {"firm_id": "FIRM-A"})
    assert resp["success"] is True and resp["data"]["user"]["id"] == "U-A"


# ── H2 — compliance assignment isolation ──────────────────────────────────────

def test_h2_list_drops_unassigned_clients(monkeypatch):
    import routers.compliance_records as cr
    import core.authz as authz
    monkeypatch.setattr(cr.compliance_record_service, "list_records",
                        lambda **k: [{"id": "1", "client_id": "A"}, {"id": "2", "client_id": "B"}])
    monkeypatch.setattr(authz, "effective_client_ids", lambda u: {"A"})   # caller assigned only to A
    out = cr.list_compliance_records(client_id=None, status=None, compliance_type=None,
                                     current_user={"firm_id": "F", "role": "Executive", "id": "u1"})
    assert {r["id"] for r in out["data"]} == {"1"}


def test_h2_list_firmwide_sees_all(monkeypatch):
    import routers.compliance_records as cr
    import core.authz as authz
    monkeypatch.setattr(cr.compliance_record_service, "list_records",
                        lambda **k: [{"id": "1", "client_id": "A"}, {"id": "2", "client_id": "B"}])
    monkeypatch.setattr(authz, "effective_client_ids", lambda u: None)    # firm-wide ⇒ no filter
    out = cr.list_compliance_records(client_id=None, status=None, compliance_type=None,
                                     current_user={"firm_id": "F", "role": "Partner", "id": "p1"})
    assert {r["id"] for r in out["data"]} == {"1", "2"}


def test_h2_get_blocks_unassigned(monkeypatch):
    import routers.compliance_records as cr
    import core.authz as authz
    monkeypatch.setattr(cr.compliance_record_service, "get_record", lambda rid, firm_id=None: {"id": rid, "client_id": "B"})
    monkeypatch.setattr(authz, "can_access_client", lambda u, c: c == "A")
    with pytest.raises(HTTPException) as ei:
        cr.get_compliance_record("rec-1", {"firm_id": "F", "role": "Executive", "id": "u1"})
    assert ei.value.status_code == 404


def test_h2_get_allows_assigned(monkeypatch):
    import routers.compliance_records as cr
    import core.authz as authz
    monkeypatch.setattr(cr.compliance_record_service, "get_record", lambda rid, firm_id=None: {"id": rid, "client_id": "A"})
    monkeypatch.setattr(authz, "can_access_client", lambda u, c: c == "A")
    out = cr.get_compliance_record("rec-1", {"firm_id": "F", "role": "Executive", "id": "u1"})
    assert out["data"]["client_id"] == "A"


# ── H3 — receipt re-allocation AR drift (exact numbers) ───────────────────────

def _realloc(rc, paise):
    from models.invoices import ReceiptAllocationIn, ReceiptAllocationsUpdateIn
    allocs = [ReceiptAllocationIn(sales_invoice_id="INV", allocated_paise=paise)] if paise > 0 else []
    body = ReceiptAllocationsUpdateIn(allocations=allocs)
    return rc.update_allocations("R", body, {"firm_id": "F", "auth_user_id": "u", "email": "e@x.test"})


def test_h3_reallocation_never_drifts(monkeypatch):
    import routers.receipts as rc
    import core.supabase_client as sc
    db = FakeDB()
    db.seed("client_sales_invoices", {"id": "INV", "firm_id": "F", "total_paise": 100000, "paid_paise": 0, "status": "issued"})
    db.seed("receipts", {"id": "R", "firm_id": "F", "amount_paise": 100000})
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    monkeypatch.setattr(rc, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)

    def inv():
        return db.data["client_sales_invoices"][0]

    _realloc(rc, 100000)
    assert inv()["paid_paise"] == 100000 and inv()["status"] == "paid"
    # Re-allocate to a SMALLER amount — before the fix this inflated to 140000.
    _realloc(rc, 40000)
    assert inv()["paid_paise"] == 40000 and inv()["status"] == "partially_paid"
    # Repeated identical re-allocations are stable (idempotent).
    _realloc(rc, 40000)
    _realloc(rc, 40000)
    assert inv()["paid_paise"] == 40000 and inv()["status"] == "partially_paid"
    # Full de-allocation reverts to issued with zero paid.
    _realloc(rc, 0)
    assert inv()["paid_paise"] == 0 and inv()["status"] == "issued"
    # Exactly one allocation row persists after the final non-empty re-allocation.
    _realloc(rc, 70000)
    assert inv()["paid_paise"] == 70000 and len(db.data["receipt_allocations"]) == 1


# ── H4 — bank settlement preview scoping ──────────────────────────────────────

def test_h4_settlement_preview_blocks_foreign_entity():
    from services.bank_posting_service import bank_posting_service as svc
    db = FakeDB()
    db.seed("client_sales_invoices", {"id": "INV-A", "firm_id": "F", "client_id": "X",
                                      "invoice_no": "SINV-1", "total_paise": 100000, "paid_paise": 0})
    db.seed("client_sales_invoices", {"id": "INV-B", "firm_id": "OTHER", "client_id": "Y",
                                      "invoice_no": "SINV-9", "total_paise": 999999, "paid_paise": 0})
    own = {"category": "Customer Payment", "matched_entity_type": "sales_invoice",
           "matched_entity_id": "INV-A", "client_id": "X"}
    out = svc._settlement_preview(db, "F", own, 50000)
    assert out["label"] == "SINV-1" and out["total_paise"] == 100000 and out["allocate_paise"] == 50000

    # matched_entity_id points at another firm/client's invoice → nothing disclosed.
    foreign = {"category": "Customer Payment", "matched_entity_type": "sales_invoice",
               "matched_entity_id": "INV-B", "client_id": "X"}
    out2 = svc._settlement_preview(db, "F", foreign, 50000)
    assert out2["label"] is None and out2["total_paise"] == 0 and out2["allocate_paise"] == 0
