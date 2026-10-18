"""An invoice has one live IRN record, and the records prepared for it are found by the invoice (POST-A-263).

THE DEFECT
    The invoice drawer found an invoice's e-invoice and e-way bill records by reading ALL of the client's, newest first, with no
    limit and no way to ask for one invoice's, and looking for its invoice among them. The read grew with the client's history
    and was cut silently at the database's row cap, so an older invoice's record was not found and the panel offered to prepare a
    new one. And nothing stopped that: `einvoice_records` had no uniqueness on the invoice it names and `create_einvoice_record`
    neither looked for an existing live record nor refused one, so an invoice could carry two, one of them a draft that is never
    recorded or cancelled.

WHAT IS HELD
    * both list routes accept `sales_invoice_id`, read at most one row more than the window and answer
      `{records, returned, has_more, limit, max_limit}` (the list-window rule), newest first with a tie-break on id;
    * a second LIVE e-invoice record for one invoice is refused with a 409 that says which record is there, a cancelled record does
      not count (an IRN cancelled on the portal is prepared again), a record naming no invoice is unconstrained, and the same
      refusal answers the unique index's violation (two requests at the same moment);
    * e-way bills are NOT constrained: an invoice may carry several (a second consignment, a new vehicle);
    * migration 518 says all of this to the database (the real-Postgres half is `test_518_..._pg.py`).
"""
from __future__ import annotations

import typing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.einvoice as einv
import routers.eway_bill as ewb
from core import list_window
from core.auth import get_current_user
from domain.income_tax import einvoice_service, eway_service

API = Path(__file__).resolve().parents[1]
FIRM = "firm-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "Partner"}


@pytest.fixture(autouse=True)
def _fresh_stores(monkeypatch):
    monkeypatch.setattr(einvoice_service, "_MOCK_RECORDS", {})
    monkeypatch.setattr(eway_service, "_MOCK_RECORDS", {})


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(einv.router)
    app.include_router(ewb.router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


def _irn(client, invoice_id="si-1", number="INV-1", **extra):
    return client.post("/api/einvoice/records", json={
        "client_id": "cl-1", "invoice_number": number, "invoice_date": "2026-07-06",
        "sales_invoice_id": invoice_id, **extra})


def _ewb(client, invoice_id="si-1"):
    return client.post("/api/eway-bill/records", json={
        "client_id": "cl-1", "invoice_number": "INV-1", "dispatch_from": "27", "ship_to": "29",
        "goods_description": "Laptops", "taxable_value_paise": 6000000, "sales_invoice_id": invoice_id})


# ── a second live record for one invoice ──────────────────────────────────────────────────────────────

def test_a_second_live_record_for_one_invoice_is_refused_and_names_the_one_that_is_there(client):
    first = _irn(client)
    assert first.status_code == 200
    second = _irn(client)
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert "already has an e-invoice record" in detail and "draft" in detail
    assert len(einvoice_service._MOCK_RECORDS) == 1, "the refused request still created a record"


def test_the_refusal_says_when_the_record_already_carries_its_irn(client):
    rid = _irn(client).json()["data"]["id"]
    client.post(f"/api/einvoice/records/{rid}/irn-generated", json={
        "irn": "IRN1", "ack_number": "A1", "ack_date": "2026-07-06"})
    detail = _irn(client).json()["detail"]
    assert "recorded with its IRN" in detail


def test_a_cancelled_record_does_not_count_and_the_invoice_is_prepared_again(client):
    rid = _irn(client).json()["data"]["id"]
    assert client.post(f"/api/einvoice/records/{rid}/cancel", json={"cancellation_reason": "wrong value"}).status_code == 200
    again = _irn(client)
    assert again.status_code == 200
    assert _irn(client).status_code == 409, "the prepared-again record is live and a third is refused"


def test_another_invoice_is_unaffected(client):
    assert _irn(client, "si-1").status_code == 200
    assert _irn(client, "si-2", "INV-2").status_code == 200


def test_a_record_that_names_no_invoice_is_unconstrained(client):
    for n in ("INV-9", "INV-10", "INV-11"):
        r = client.post("/api/einvoice/records", json={
            "client_id": "cl-1", "invoice_number": n, "invoice_date": "2026-07-06"})
        assert r.status_code == 200


def test_another_firms_record_for_the_same_invoice_id_is_not_this_firms(client, monkeypatch):
    assert _irn(client).status_code == 200
    other = {"id": "u9", "firm_id": "firm-2", "role": "Partner"}
    app = FastAPI()
    app.include_router(einv.router)
    app.dependency_overrides[get_current_user] = lambda: other
    c2 = TestClient(app, raise_server_exceptions=False)
    assert _irn(c2).status_code == 200


class _UniqueViolation(Exception):
    code = "23505"


def test_two_requests_at_the_same_moment_get_the_same_refusal(client, monkeypatch):
    """The lookup found nothing, then the other request's insert landed first and the index refused this one."""
    def boom(**_kw):
        raise _UniqueViolation("duplicate key value violates unique constraint uq_einvoice_records_one_live_per_invoice")
    monkeypatch.setattr(einvoice_service, "create_einvoice_record", boom)
    r = _irn(client)
    assert r.status_code == 409
    assert "already has an e-invoice record" in r.json()["detail"]


def test_any_other_failure_is_still_a_server_error(client, monkeypatch):
    def boom(**_kw):
        raise RuntimeError("the database went away")
    monkeypatch.setattr(einvoice_service, "create_einvoice_record", boom)
    assert _irn(client).status_code == 500


# ── e-way bills are not constrained ────────────────────────────────────────────────────────────────────

def test_an_invoice_may_carry_several_e_way_bills(client):
    for _ in range(3):
        assert _ewb(client).status_code == 200
    assert len(eway_service._MOCK_RECORDS) == 3


# ── the invoice's own records, in a window ────────────────────────────────────────────────────────────

def _seed_irn(n, invoice="si-1", client_id="cl-1"):
    for i in range(n):
        einvoice_service._MOCK_RECORDS[f"r{i:03d}"] = {
            "id": f"r{i:03d}", "firm_id": FIRM, "client_id": client_id, "sales_invoice_id": invoice if i % 2 == 0 else "other",
            "status": "draft" if i < n - 1 else "cancelled", "created_at": f"2026-07-{(i % 28) + 1:02d}T10:00:00+00:00"}


def test_the_list_filters_to_one_invoice_and_to_one_client(client):
    _seed_irn(6)
    einvoice_service._MOCK_RECORDS["x"] = {"id": "x", "firm_id": FIRM, "client_id": "cl-2", "sales_invoice_id": "si-1",
                                           "status": "draft", "created_at": "2026-07-30T10:00:00+00:00"}
    out = client.get("/api/einvoice/records?client_id=cl-1&sales_invoice_id=si-1").json()["data"]
    assert {r["sales_invoice_id"] for r in out["records"]} == {"si-1"}
    assert all(r["client_id"] == "cl-1" for r in out["records"])
    assert out["returned"] == len(out["records"]) == 3


def test_the_list_is_a_window_that_says_when_older_records_exist_and_never_returns_the_probe_row(client):
    _seed_irn(12)
    out = client.get("/api/einvoice/records?client_id=cl-1&limit=5").json()["data"]
    assert out["returned"] == 5 and out["has_more"] is True
    assert out["limit"] == 5 and out["max_limit"] == list_window.MAX_LIST_LIMIT
    created = [r["created_at"] for r in out["records"]]
    assert created == sorted(created, reverse=True), "newest first"


def test_a_window_that_holds_every_record_is_complete(client):
    _seed_irn(5)
    out = client.get("/api/einvoice/records?client_id=cl-1&limit=5").json()["data"]
    assert out["returned"] == 5 and out["has_more"] is False


def test_the_status_filter_still_works_beside_the_invoice_filter(client):
    _seed_irn(6)
    einvoice_service._MOCK_RECORDS["c1"] = {
        "id": "c1", "firm_id": FIRM, "client_id": "cl-1", "sales_invoice_id": "si-1", "status": "cancelled",
        "created_at": "2026-08-01T10:00:00+00:00"}
    out = client.get("/api/einvoice/records?client_id=cl-1&sales_invoice_id=si-1&status=cancelled").json()["data"]
    assert [r["id"] for r in out["records"]] == ["c1"]


@pytest.mark.parametrize("fn", [einv.list_records, ewb.list_eway_bills])
def test_the_limit_is_bounded_at_the_servers_ceiling(fn):
    hints = typing.get_type_hints(fn, include_extras=True)["limit"]
    meta = [m for m in hints.__metadata__ if hasattr(m, "metadata")]
    assert meta, "the limit parameter carries no Query bounds"
    bounds = {type(c).__name__: c for c in meta[0].metadata}
    assert (bounds["Ge"].ge, bounds["Le"].le) == (1, list_window.MAX_LIST_LIMIT)


def test_the_e_way_list_is_the_same_window(client):
    for _ in range(4):
        _ewb(client, "si-1")
    _ewb(client, "si-2")
    out = client.get("/api/eway-bill/records?client_id=cl-1&sales_invoice_id=si-1&limit=3").json()["data"]
    assert out["returned"] == 3 and out["has_more"] is True
    assert {r["sales_invoice_id"] for r in out["records"]} == {"si-1"}


# ── what the database is asked (the real path, with a recording double) ───────────────────────────────

class _Chain:
    """Records every call made on a PostgREST-style query chain and answers with `rows` on execute()."""

    def __init__(self, rows):
        self.calls, self._rows = [], rows

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, a, kw))
            return self
        return call

    def execute(self):
        class R:
            data = self._rows
        return R()


@pytest.mark.parametrize("module, fn, table", [
    (einvoice_service, "list_einvoices", "einvoice_records"),
    (eway_service, "list_eway_bills", "eway_bill_records"),
])
def test_the_real_read_asks_for_the_invoice_and_one_row_more_than_the_window(monkeypatch, module, fn, table):
    chain = _Chain([{"id": "a"}])
    tables = []

    class _Sb:
        def table(self, name):
            tables.append(name)
            return chain
    monkeypatch.setattr(module, "_USE_MOCK", False)
    monkeypatch.setattr(module, "_supabase", lambda: _Sb())
    out = getattr(module, fn)(FIRM, "cl-1", None, sales_invoice_id="si-1", limit=list_window.probe(100))
    assert out == [{"id": "a"}] and tables == [table]
    names = [c[0] for c in chain.calls]
    assert ("eq", ("sales_invoice_id", "si-1"), {}) in chain.calls
    assert ("limit", (101,), {}) in chain.calls
    assert names.count("order") == 2 and ("order", ("id",), {"desc": True}) in chain.calls, \
        "the order needs a tie-break on id so the same rows come back in the same order"


def test_the_real_read_without_an_invoice_does_not_filter_on_one(monkeypatch):
    chain = _Chain([])

    class _Sb:
        def table(self, name):
            return chain
    monkeypatch.setattr(einvoice_service, "_USE_MOCK", False)
    monkeypatch.setattr(einvoice_service, "_supabase", lambda: _Sb())
    einvoice_service.list_einvoices(FIRM, "cl-1")
    assert not any(c[0] == "eq" and c[1][0] == "sales_invoice_id" for c in chain.calls)
    assert not any(c[0] == "limit" for c in chain.calls)


def test_the_live_lookup_ignores_a_cancelled_record_in_the_database_read(monkeypatch):
    chain = _Chain([])

    class _Sb:
        def table(self, name):
            return chain
    monkeypatch.setattr(einvoice_service, "_USE_MOCK", False)
    monkeypatch.setattr(einvoice_service, "_supabase", lambda: _Sb())
    assert einvoice_service.live_einvoice_for_invoice(FIRM, "si-1") is None
    assert ("neq", ("status", "cancelled"), {}) in chain.calls
    assert ("eq", ("firm_id", FIRM), {}) in chain.calls


# ── the migration says it to the database ─────────────────────────────────────────────────────────────

def _migration() -> str:
    path = next(p for p in sorted((API / "migrations").glob("518_*.sql")) if "rollback" not in p.name)
    return path.read_text(encoding="utf-8")


def test_the_migration_declares_the_unique_index_on_live_records_only():
    sql = _migration()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_einvoice_records_one_live_per_invoice" in sql
    assert "sales_invoice_id IS NOT NULL AND status <> 'cancelled'" in sql


def test_the_migration_does_not_make_e_way_bills_unique():
    sql = _migration()
    assert "UNIQUE INDEX" in sql and sql.count("UNIQUE INDEX") == 1
    assert "eway_bill_records" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_eway_bill_records_invoice" in sql


def test_the_migration_is_idempotent():
    sql = _migration()
    statements = [ln for ln in sql.splitlines() if ln.startswith("CREATE ")]
    assert statements and all("IF NOT EXISTS" in ln for ln in statements)
