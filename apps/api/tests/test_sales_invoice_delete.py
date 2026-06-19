"""
Regression tests — soft-delete of DRAFT sales invoices (UX completion phase).

delete_invoice() must:
  * soft-delete a DRAFT (set deleted_at) and write an audit 'delete' event
  * REFUSE issued / partially_paid / paid / cancelled invoices (422) and never
    touch the row — these are legal records (CGST Act §31) with a posted journal
  * 404 on a missing/already-deleted invoice

These force the non-mock DB path with a recording fake Supabase client.
"""
import pytest
from fastapi import HTTPException

from routers import sales_invoices


# ---------------------------------------------------------------------------
# Recording fake Supabase query-builder
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, table, recorder, controller):
        self._table = table
        self._rec = recorder
        self._ctl = controller
        self._op = "select"
        self._payload = None
        self._filters = {}

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"; self._payload = payload; return self

    def update(self, payload):
        self._op = "update"; self._payload = payload; return self

    def delete(self):
        self._op = "delete"; return self

    def eq(self, col, val):
        self._filters[col] = val; return self

    # chainable no-ops
    def is_(self, *a, **k): return self
    def ilike(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def like(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def maybe_single(self): return self

    def execute(self):
        event = {"table": self._table, "op": self._op,
                 "payload": self._payload, "filters": dict(self._filters)}
        self._rec.append(event)
        return self._ctl(event)


class _FakeDB:
    def __init__(self, recorder, controller):
        self._rec = recorder
        self._ctl = controller

    def table(self, name):
        return _Query(name, self._rec, self._ctl)


_USER = {"firm_id": "F1", "auth_user_id": "u1", "email": "u@firm.test", "role": "Partner"}


@pytest.fixture
def fake_db(monkeypatch):
    recorder: list[dict] = []
    audit: list[dict] = []
    holder = {"controller": lambda event: _Resp(data=[])}

    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _FakeDB(recorder, holder["controller"]))
    monkeypatch.setattr(
        sales_invoices, "log_event",
        lambda *a, **k: audit.append({"args": a, "kwargs": k}),
    )
    return recorder, holder, audit


def _invoice_row(status):
    return {"id": "INV-1", "invoice_no": "SINV-2627-0001",
            "status": status, "total_paise": 6018, "client_id": "C1"}


# ---------------------------------------------------------------------------
# Draft → soft-deleted
# ---------------------------------------------------------------------------

class TestDeleteDraft:
    def test_draft_is_soft_deleted_and_audited(self, fake_db):
        recorder, holder, audit = fake_db

        def _ctl(event):
            if event["table"] == "client_sales_invoices" and event["op"] == "select":
                return _Resp(data=[_invoice_row("draft")])
            return _Resp(data=[{"id": "INV-1"}])

        holder["controller"] = _ctl
        resp = sales_invoices.delete_invoice("INV-1", _USER)

        assert resp["success"] is True
        assert resp["data"]["deleted"] is True

        # A soft-delete UPDATE was issued, setting deleted_at (no hard DELETE).
        updates = [e for e in recorder
                   if e["table"] == "client_sales_invoices" and e["op"] == "update"]
        assert len(updates) == 1
        assert "deleted_at" in updates[0]["payload"]
        assert updates[0]["payload"]["deleted_at"] is not None
        hard_deletes = [e for e in recorder
                        if e["table"] == "client_sales_invoices" and e["op"] == "delete"]
        assert hard_deletes == [], "draft must be SOFT-deleted, never hard-deleted"

        # Audit 'delete' event recorded with the invoice identity.
        assert len(audit) == 1
        assert audit[0]["args"][3] == "delete"          # action positional arg
        assert audit[0]["kwargs"]["old_data"]["invoice_no"] == "SINV-2627-0001"


# ---------------------------------------------------------------------------
# Non-draft → blocked
# ---------------------------------------------------------------------------

class TestDeleteBlocked:
    @pytest.mark.parametrize("status,word", [
        ("issued", "issued"),
        ("partially_paid", "partially-paid"),
        ("paid", "paid"),
        ("cancelled", "cancelled"),
    ])
    def test_non_draft_cannot_be_deleted(self, fake_db, status, word):
        recorder, holder, audit = fake_db
        holder["controller"] = lambda e: (
            _Resp(data=[_invoice_row(status)])
            if e["table"] == "client_sales_invoices" and e["op"] == "select"
            else _Resp(data=[])
        )

        with pytest.raises(HTTPException) as ei:
            sales_invoices.delete_invoice("INV-1", _USER)

        assert ei.value.status_code == 422
        assert word in ei.value.detail
        # The row must be untouched — no update/delete, no audit event.
        mutations = [e for e in recorder
                     if e["table"] == "client_sales_invoices" and e["op"] in ("update", "delete")]
        assert mutations == []
        assert audit == []

    def test_missing_invoice_404(self, fake_db):
        recorder, holder, audit = fake_db
        holder["controller"] = lambda e: _Resp(data=[])

        with pytest.raises(HTTPException) as ei:
            sales_invoices.delete_invoice("nope", _USER)

        assert ei.value.status_code == 404
        assert audit == []
