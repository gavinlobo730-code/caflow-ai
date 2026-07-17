"""
Regression tests — hard-delete of DRAFT credit notes (bulk-select platform work).

delete_credit_note() must:
  * hard-delete a DRAFT (genuine DB row removal) and write an audit 'delete'
    event — the audit trail (create + delete events) survives independently
    of the row, since audit_log.entity_id is a bare text column, not an FK
  * REFUSE issued/applied credit notes (422) and never touch the row — these
    carry a posted journal and, if linked to an invoice, have already reduced
    that invoice's outstanding balance (CGST Act §34)
  * 404 on a missing/already-deleted credit note

Mirrors test_sales_invoice_delete.py's fake-DB pattern exactly.
"""
import pytest
from fastapi import HTTPException

from routers import credit_notes


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

    monkeypatch.setattr(credit_notes, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _FakeDB(recorder, holder["controller"]))
    monkeypatch.setattr(
        credit_notes, "log_event",
        lambda *a, **k: audit.append({"args": a, "kwargs": k}),
    )
    return recorder, holder, audit


def _cn_row(status):
    return {"id": "CN-1", "credit_note_no": "CN-2627-0001",
            "status": status, "total_paise": 1180, "client_id": "C1"}


class TestDeleteDraft:
    def test_draft_is_hard_deleted_and_audited(self, fake_db):
        recorder, holder, audit = fake_db

        def _ctl(event):
            if event["table"] == "credit_notes" and event["op"] == "select":
                return _Resp(data=[_cn_row("draft")])
            return _Resp(data=[{"id": "CN-1"}])

        holder["controller"] = _ctl
        resp = credit_notes.delete_credit_note("CN-1", _USER)

        assert resp["success"] is True
        assert resp["data"]["deleted"] is True

        hard_deletes = [e for e in recorder if e["table"] == "credit_notes" and e["op"] == "delete"]
        assert len(hard_deletes) == 1
        soft_updates = [e for e in recorder if e["table"] == "credit_notes" and e["op"] == "update"]
        assert soft_updates == [], "draft must be HARD-deleted, not soft-deleted via deleted_at"

        assert len(audit) == 1
        assert audit[0]["args"][3] == "delete"
        assert audit[0]["kwargs"]["old_data"]["credit_note_no"] == "CN-2627-0001"


class TestDeleteBlocked:
    @pytest.mark.parametrize("status,word", [
        ("issued", "issued"),
        ("applied", "applied"),
    ])
    def test_non_draft_cannot_be_deleted(self, fake_db, status, word):
        recorder, holder, audit = fake_db
        holder["controller"] = lambda e: (
            _Resp(data=[_cn_row(status)])
            if e["table"] == "credit_notes" and e["op"] == "select"
            else _Resp(data=[])
        )

        with pytest.raises(HTTPException) as ei:
            credit_notes.delete_credit_note("CN-1", _USER)

        assert ei.value.status_code == 422
        assert word in ei.value.detail
        mutations = [e for e in recorder if e["table"] == "credit_notes" and e["op"] in ("update", "delete")]
        assert mutations == []
        assert audit == []

    def test_missing_credit_note_404(self, fake_db):
        recorder, holder, audit = fake_db
        holder["controller"] = lambda e: _Resp(data=[])

        with pytest.raises(HTTPException) as ei:
            credit_notes.delete_credit_note("nope", _USER)

        assert ei.value.status_code == 404
        assert audit == []
