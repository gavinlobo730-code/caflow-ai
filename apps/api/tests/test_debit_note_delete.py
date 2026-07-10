"""
Regression tests — soft-delete of DRAFT debit notes (bulk-select platform work).

delete_debit_note() must:
  * soft-delete a DRAFT (set deleted_at) and write an audit 'delete' event
  * REFUSE issued debit notes (422) and never touch the row — once issued
    they carry a posted journal and, if linked to a bill, have already
    reduced that bill's payable (CGST Act §34)
  * 404 on a missing/already-deleted debit note

Mirrors test_sales_invoice_delete.py's fake-DB pattern exactly.
"""
import pytest
from fastapi import HTTPException

from routers import debit_notes


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

    monkeypatch.setattr(debit_notes, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _FakeDB(recorder, holder["controller"]))
    monkeypatch.setattr(
        debit_notes, "log_event",
        lambda *a, **k: audit.append({"args": a, "kwargs": k}),
    )
    return recorder, holder, audit


def _dn_row(status):
    return {"id": "DN-1", "debit_note_no": "DN-2627-0001",
            "status": status, "total_paise": 1180, "client_id": "C1"}


class TestDeleteDraft:
    def test_draft_is_soft_deleted_and_audited(self, fake_db):
        recorder, holder, audit = fake_db

        def _ctl(event):
            if event["table"] == "debit_notes" and event["op"] == "select":
                return _Resp(data=[_dn_row("draft")])
            return _Resp(data=[{"id": "DN-1"}])

        holder["controller"] = _ctl
        resp = debit_notes.delete_debit_note("DN-1", _USER)

        assert resp["success"] is True
        assert resp["data"]["deleted"] is True

        updates = [e for e in recorder if e["table"] == "debit_notes" and e["op"] == "update"]
        assert len(updates) == 1
        assert "deleted_at" in updates[0]["payload"]
        assert updates[0]["payload"]["deleted_at"] is not None
        hard_deletes = [e for e in recorder if e["table"] == "debit_notes" and e["op"] == "delete"]
        assert hard_deletes == [], "draft must be SOFT-deleted, never hard-deleted"

        assert len(audit) == 1
        assert audit[0]["args"][3] == "delete"
        assert audit[0]["kwargs"]["old_data"]["debit_note_no"] == "DN-2627-0001"


class TestDeleteBlocked:
    def test_issued_cannot_be_deleted(self, fake_db):
        recorder, holder, audit = fake_db
        holder["controller"] = lambda e: (
            _Resp(data=[_dn_row("issued")])
            if e["table"] == "debit_notes" and e["op"] == "select"
            else _Resp(data=[])
        )

        with pytest.raises(HTTPException) as ei:
            debit_notes.delete_debit_note("DN-1", _USER)

        assert ei.value.status_code == 422
        assert "issued" in ei.value.detail
        mutations = [e for e in recorder if e["table"] == "debit_notes" and e["op"] in ("update", "delete")]
        assert mutations == []
        assert audit == []

    def test_missing_debit_note_404(self, fake_db):
        recorder, holder, audit = fake_db
        holder["controller"] = lambda e: _Resp(data=[])

        with pytest.raises(HTTPException) as ei:
            debit_notes.delete_debit_note("nope", _USER)

        assert ei.value.status_code == 404
        assert audit == []
