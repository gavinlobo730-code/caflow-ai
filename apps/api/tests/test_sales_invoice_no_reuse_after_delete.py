"""
A soft-deleted sales invoice's number must be reusable (migration 209).

Bug report: a CA created a draft invoice numbered "00002", deleted it, and
every later attempt to reuse "00002" for a real invoice failed with "Invoice
number '00002' already exists for this client" — even though the deleted
draft is invisible everywhere in the UI. Root cause:
_assert_invoice_no_available (and the bulk-import existing-numbers prefetch)
queried client_sales_invoices without filtering deleted_at, and the DB-level
UNIQUE(firm_id, client_id, invoice_no) constraint (migration 151) had the
same gap. Fixed by filtering deleted_at IS NULL at the app level and
narrowing the DB constraint to a partial unique index with the same WHERE
clause (migration 209).

Uses tests.e2e_harness.FakeDB — a faithful-enough PostgREST double whose
.is_() actually filters (unlike the simpler recording fakes elsewhere in this
test suite), so this proves the query itself excludes deleted rows, not just
that _assert_invoice_no_available was called.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as sales_invoices
from routers.sales_invoices import _assert_invoice_no_available
from tests.e2e_harness import FakeDB

FIRM = "firm-1"
CLIENT = "client-1"


@pytest.fixture(autouse=True)
def _force_real_db_path(monkeypatch):
    # _assert_invoice_no_available branches on the module-level _USE_MOCK flag
    # FIRST and, if true, checks the unrelated MOCK_SALES_INVOICES global
    # instead of the `db` argument — without this, every test below would
    # silently exercise the mock branch (always empty, always "available")
    # and pass regardless of whether the real query filters deleted_at.
    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)


def test_deleted_invoice_number_is_free_to_reuse():
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "00002",
        "status": "draft", "deleted_at": "2026-07-14T05:20:00+00:00",
    })
    # Must NOT raise — the only row with this number is soft-deleted.
    _assert_invoice_no_available(db, FIRM, CLIENT, "00002")


def test_live_invoice_number_is_still_rejected():
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "00001",
        "status": "issued", "deleted_at": None,
    })
    with pytest.raises(HTTPException) as ei:
        _assert_invoice_no_available(db, FIRM, CLIENT, "00001")
    assert ei.value.status_code == 409
    assert "already exists" in ei.value.detail


def test_deleted_and_live_rows_with_same_number_still_rejects_on_the_live_one():
    """A number can legitimately have both a deleted AND a live row (the CA
    deleted a draft, then successfully created a real invoice reusing the
    number) — a second attempt to reuse it again must still be rejected."""
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "00002",
        "status": "draft", "deleted_at": "2026-07-14T05:20:00+00:00",
    })
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "00002",
        "status": "issued", "deleted_at": None,
    })
    with pytest.raises(HTTPException) as ei:
        _assert_invoice_no_available(db, FIRM, CLIENT, "00002")
    assert ei.value.status_code == 409


def test_exclude_id_still_allows_editing_the_same_live_invoice():
    db = FakeDB()
    live_id = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "00003",
        "status": "draft", "deleted_at": None,
    })["id"]
    # Editing invoice 00003 to keep its own number must not self-collide.
    _assert_invoice_no_available(db, FIRM, CLIENT, "00003", exclude_id=live_id)


def test_different_client_can_use_the_same_number():
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "00001",
        "status": "issued", "deleted_at": None,
    })
    _assert_invoice_no_available(db, FIRM, "client-2", "00001")
