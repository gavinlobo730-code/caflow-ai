"""
A recomputed TDS return revises the return it replaces.

WHAT WAS WRONG
    tds_returns is UNIQUE (client_id, return_type, financial_year, quarter)
    (migration 037) — one statement per quarter. create_return always INSERTed a
    fresh id, so the SECOND "Compute from Books" save for a quarter hit that key,
    and `except Exception as e: return api_response(False, None, str(e))` handed
    the raw PostgREST payload back in an HTTP 200. The screen did not read it,
    so the CA believed the recompute was saved.

WHAT IT DOES NOW, and each is asserted by calling the handler
    * a second save for the quarter REVISES the row in place and keeps its id
      (tds_deductions.tds_return_id and the screen both hold it);
    * the revision goes back to `pending` and the CA approval is CLEARED —
      changed figures must be approved again (owner decision, 27-09-2026);
    * the deductee lines are replaced, an empty list included, so a quarter
      with no deductees now does not keep the last computation's lines;
    * a FILED return is refused with a 409 that says a correction is a
      correction statement on TRACES, and is left untouched;
    * the quick-create form (no figures) on a period that already has a return
      answers with that return as it stands;
    * against a database, the same revision is an UPDATE of that id, and a
      unique violation that still gets through is a sentence, not a payload.
"""
from __future__ import annotations

import copy

import pytest
from fastapi import HTTPException

import core.supabase_client as sc
import routers.tds_workspace as tw
from routers.tds_workspace import (
    CreateReturnRequest, UpdateReturnStatusRequest, create_return,
    update_return_status,
)

PARTNER = {"firm_id": "F-rev", "id": "u-partner", "auth_user_id": "a1",
           "role": "Partner"}
CLIENT = "C-rev"


@pytest.fixture(autouse=True)
def _clean_store():
    tw._MOCK_RETURNS.clear()
    yield
    tw._MOCK_RETURNS.clear()


def _computed(**over) -> CreateReturnRequest:
    """What the client screen's saveComputed() sends."""
    base = dict(client_id=CLIENT, return_type="26Q", quarter="Q2",
                financial_year="2025-26",
                deductee_details=[{"deductee_pan": "ABCDE1234F", "section": "194C",
                                   "tds_paise": 20000}],
                total_deductions_paise=20000, total_deposits_paise=20000,
                deductee_count=1, validation_errors=[])
    base.update(over)
    return CreateReturnRequest(**base)


def _approve(return_id: str) -> None:
    res = update_return_status(return_id, UpdateReturnStatusRequest(
        status="ca_approved", ca_approved=True), PARTNER)
    assert res["success"] is True, res


# ── Mock store: the behaviour ───────────────────────────────────────────────

def test_a_second_save_revises_the_same_row_and_keeps_its_id():
    first = create_return(_computed(), PARTNER)["data"]["id"]
    second = create_return(_computed(total_deductions_paise=35000,
                                     total_deposits_paise=30000), PARTNER)
    assert second["success"] is True
    assert second["data"]["id"] == first
    assert list(tw._MOCK_RETURNS) == [first], "a second row was written"
    row = tw._MOCK_RETURNS[first]
    assert row["total_deductions_paise"] == 35000
    assert row["total_deposits_paise"] == 30000


def test_recomputing_an_approved_return_clears_the_approval():
    rid = create_return(_computed(), PARTNER)["data"]["id"]
    _approve(rid)
    assert tw._MOCK_RETURNS[rid]["ca_approved_by"] == PARTNER["id"]

    create_return(_computed(total_deductions_paise=35000), PARTNER)
    row = tw._MOCK_RETURNS[rid]
    assert row["status"] == "pending"
    assert row["ca_approved_by"] is None
    assert row["ca_approved_at"] is None


def test_the_deductee_lines_are_replaced_an_empty_list_included():
    rid = create_return(_computed(), PARTNER)["data"]["id"]
    create_return(_computed(deductee_details=[], total_deductions_paise=0,
                            total_deposits_paise=0, deductee_count=0), PARTNER)
    row = tw._MOCK_RETURNS[rid]
    assert row["fvu_json"] == {"deductees": []}
    assert row["deductee_count"] == 0


def test_a_filed_return_is_refused_and_left_as_it_was():
    rid = create_return(_computed(), PARTNER)["data"]["id"]
    filed = update_return_status(rid, UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn="123456789012345"), PARTNER)
    assert filed["success"] is True
    before = copy.deepcopy(tw._MOCK_RETURNS[rid])

    with pytest.raises(HTTPException) as e:
        create_return(_computed(total_deductions_paise=99999), PARTNER)
    assert e.value.status_code == 409
    assert "has already been filed (PRN 123456789012345)" in e.value.detail
    assert "correction statement on TRACES" in e.value.detail
    assert tw._MOCK_RETURNS[rid] == before


def test_the_quick_create_form_opens_the_existing_return_as_it_stands():
    rid = create_return(_computed(), PARTNER)["data"]["id"]
    _approve(rid)
    before = copy.deepcopy(tw._MOCK_RETURNS[rid])

    res = create_return(CreateReturnRequest(
        client_id=CLIENT, return_type="26Q", quarter="Q2",
        financial_year="2025-26"), PARTNER)
    assert res["success"] is True
    assert res["data"]["id"] == rid
    assert tw._MOCK_RETURNS[rid] == before, (
        "a request carrying no figures erased a computed statement or reset "
        "an approval over figures that did not move")


def test_a_different_quarter_is_still_its_own_return():
    q2 = create_return(_computed(), PARTNER)["data"]["id"]
    q3 = create_return(_computed(quarter="Q3"), PARTNER)["data"]["id"]
    assert q2 != q3
    assert len(tw._MOCK_RETURNS) == 2


def test_the_refusal_names_the_form_the_periods_own_act_uses():
    """A FY 2026-27 26Q is Form 140 under the Income-tax Act 2025 — the
    routing key is kept beside it, never replaced (translate at the
    boundary)."""
    assert tw._statement_label("26Q", "2026-27") == "Form 140 (26Q)"
    assert tw._statement_label("26Q", "2025-26") == "Form 26Q"


# ── Against a database: the same revision is an UPDATE of that id ─────────

class _PgError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__({"code": code, "message": message})


class _Q:
    def __init__(self, db, table):
        self.db, self.table_name = db, table
        self.filters: dict = {}
        self.op, self.payload = "select", None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def limit(self, _n):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def execute(self):
        self.db.calls.append((self.op, dict(self.filters), self.payload))
        if self.op == "insert" and self.db.insert_error:
            raise self.db.insert_error
        rows = [r for r in self.db.rows
                if all(r.get(k) == v for k, v in self.filters.items())]
        if self.op == "update":
            for r in rows:
                r.update(self.payload)
        return type("R", (), {"data": [dict(r) for r in rows]})()


class _DB:
    def __init__(self, rows=(), insert_error=None):
        self.rows = [dict(r) for r in rows]
        self.calls: list = []
        self.insert_error = insert_error

    def table(self, name):
        assert name == "tds_returns"
        return _Q(self, name)


@pytest.fixture
def against(monkeypatch):
    def _use(db):
        monkeypatch.setattr(tw, "_USE_MOCK", False)
        monkeypatch.setattr(sc, "get_supabase", lambda: db)
        monkeypatch.setattr(tw.period_validation_service, "validate_posting_date",
                            lambda *_a, **_k: None)
        monkeypatch.setattr(tw, "log_event", lambda *_a, **_k: None)
        return db
    return _use


def _stored(**over):
    row = {"id": "R-1", "firm_id": "F-rev", "client_id": CLIENT,
           "return_type": "26Q", "financial_year": "2025-26", "quarter": "Q2",
           "status": "ca_approved", "prn": None, "ca_approved_by": "u-partner",
           "ca_approved_at": "2026-09-20T10:00:00+00:00",
           "total_deductions_paise": 20000, "total_deposits_paise": 20000,
           "deductee_count": 1, "validation_errors": []}
    row.update(over)
    return row


def test_against_a_database_the_existing_id_is_updated_not_inserted(against):
    db = against(_DB([_stored()]))
    res = create_return(_computed(total_deductions_paise=35000), PARTNER)
    assert res["success"] is True
    assert res["data"]["id"] == "R-1"
    ops = [c[0] for c in db.calls]
    assert "insert" not in ops
    (_, filters, payload), = [c for c in db.calls if c[0] == "update"]
    assert filters == {"id": "R-1", "firm_id": "F-rev"}
    assert payload["status"] == "pending"
    assert payload["ca_approved_by"] is None and payload["ca_approved_at"] is None
    assert payload["total_deductions_paise"] == 35000


def test_against_a_database_a_filed_return_is_a_409_and_nothing_is_written(against):
    db = against(_DB([_stored(status="filed", prn="PRN-7")]))
    with pytest.raises(HTTPException) as e:
        create_return(_computed(), PARTNER)
    assert e.value.status_code == 409
    assert "PRN-7" in e.value.detail
    assert [c[0] for c in db.calls] == ["select"]


def test_a_unique_violation_that_still_gets_through_is_a_sentence(against):
    """Two saves racing past the lookup. The backstop names the statement and
    what to do; it never hands back the index name or the payload."""
    against(_DB([], insert_error=_PgError(
        "23505", 'duplicate key value violates unique constraint '
                 '"tds_returns_client_id_return_type_financial_year_quarter_key"')))
    with pytest.raises(HTTPException) as e:
        create_return(_computed(), PARTNER)
    assert e.value.status_code == 409
    assert "Form 26Q for Q2 FY 2025-26" in e.value.detail
    assert "_key" not in e.value.detail


def test_any_other_failure_is_a_sentence_and_not_the_exception_text(against):
    against(_DB([], insert_error=RuntimeError("pool exhausted at 10.1.2.3")))
    res = create_return(_computed(), PARTNER)
    assert res["success"] is False
    assert "10.1.2.3" not in res["error"]
    assert "Could not save Form 26Q for Q2 FY 2025-26" in res["error"]
