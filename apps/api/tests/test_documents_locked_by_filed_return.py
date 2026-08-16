"""
A filed return closes the period for invoices and bills too, not just journals.

WHAT WAS MISSING
    Sales invoices and purchase bills already refuse a lot: cancelled documents
    cannot be touched at all, an issued document is frozen to soft fields only
    (CGST §34 — corrections go through a credit or debit note), and the
    financial-year lock is checked at every write.

    None of that knows about filed returns. period_validation_service takes
    (firm_id, date) and a filed return is a fact about a CLIENT, so an invoice
    could be created, or its date moved, inside a period whose GSTR-1 had
    already gone to the portal. The return said one thing and the books said
    another, with nothing recording why.

WHY THE CHECK LIVES IN SQL
    period_lock_reason (migration 267) is the same function the journal edit
    path enforces with, inside the transaction that rewrites posted rows.
    Answering it a second time in Python would give us two definitions of
    "closed" that agree until the day one is changed.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.purchase_bills as pb
from services import period_lock_service
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [si, pb, period_lock_service])
    d.seed("firms", {"id": FIRM, "name": "F1", "locked_financial_years": []})
    return d


def _file_gstr1_for_june(db, filed_on="2026-07-11"):
    db.seed("filings", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_type": "GSTR-1",
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "filed_date": filed_on, "status": "filed", "deleted_at": None,
    })


# ── the lock itself ──────────────────────────────────────────────────────────

def test_an_open_period_reports_no_reason(db):
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15") is None


def test_a_filed_return_names_itself_and_the_date_it_was_filed(db):
    _file_gstr1_for_june(db)

    reason = period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15")

    assert reason is not None
    assert "GSTR-1" in reason, "the CA needs to know WHICH return closed the period"
    assert "11 Jul 2026" in reason, "and when it went"
    assert "amendment" in reason.lower(), "and what to do instead"


def test_the_lock_stops_at_the_period_boundary(db):
    _file_gstr1_for_june(db)

    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-05-31") is None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-01") is not None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-30") is not None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-07-01") is None


def test_an_unfiled_filing_row_does_not_close_anything(db):
    """A filing row with no filed_date is a task in the calendar, not a document
    at the portal. Blocking on it would freeze books nobody has submitted
    anything for."""
    db.seed("filings", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_type": "GSTR-1",
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "filed_date": None, "status": "draft", "deleted_at": None,
    })

    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15") is None


def test_another_clients_filing_does_not_close_this_ones_books(db):
    _file_gstr1_for_june(db)

    assert period_lock_service.lock_reason(db, FIRM, "client-2", "2026-06-15") is None


def test_a_locked_year_still_reports_as_before(db):
    """267 moved this function; it did not change what it decides."""
    db.rows("firms")[0]["locked_financial_years"] = ["2026-27"]

    reason = period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15")

    assert reason is not None and "2026-27 is locked" in reason


# ── failing closed ───────────────────────────────────────────────────────────

class _Broken:
    def rpc(self, *_a, **_k):
        raise RuntimeError("connection reset by peer")


def test_a_check_that_cannot_run_treats_the_period_as_closed():
    """A document wrongly allowed into a filed period is not recoverable from
    the UI — the return has already gone. Same posture as
    manual_journal_service._lock_reason and period_validation_service."""
    reason = period_lock_service.lock_reason(_Broken(), FIRM, CLIENT, "2026-06-15")

    assert reason == period_lock_service.UNVERIFIABLE
    assert "again" in reason.lower(), "say that retrying is the fix"


def test_the_unverifiable_message_is_not_dressed_up_as_a_real_lock():
    """The CA can act on 'the year is locked'. All they can do about a failed
    check is retry, so the two must not read the same."""
    assert "locked" not in period_lock_service.UNVERIFIABLE.lower()
    assert "filed" not in period_lock_service.UNVERIFIABLE.lower()


def test_nothing_to_check_is_not_a_lock(db):
    """Bulk paths and drafts legitimately arrive without a client or a date."""
    assert period_lock_service.lock_reason(db, FIRM, None, "2026-06-15") is None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, None) is None
    assert period_lock_service.lock_reason(db, "", CLIENT, "2026-06-15") is None


# ── wired into the documents ─────────────────────────────────────────────────

def test_editing_a_sales_invoice_inside_a_filed_period_is_refused(db):
    _file_gstr1_for_june(db)
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "invoice_date": "2026-06-15", "invoice_no": "INV-1",
    })

    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV1", si.SalesInvoiceUpdateIn(notes="edited"),
                          current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_moving_a_sales_invoice_into_a_filed_period_is_refused(db):
    """Moving a document INTO a closed period changes that period's numbers as
    surely as editing one already there — checking only its current date would
    miss it entirely."""
    _file_gstr1_for_june(db)
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "invoice_date": "2026-07-15", "invoice_no": "INV-1",
    })

    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV1", si.SalesInvoiceUpdateIn(invoice_date="2026-06-15"),
                          current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_an_invoice_in_an_open_period_is_still_editable(db):
    """The guard has to let the ordinary case through, or it is just an outage."""
    _file_gstr1_for_june(db)
    db.seed("client_sales_invoices", {
        "id": "INV2", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "invoice_date": "2026-07-15", "invoice_no": "INV-2",
    })

    resp = si.update_invoice("INV2", si.SalesInvoiceUpdateIn(notes="fine"),
                             current_user=USER)

    assert resp["success"] is True


def test_editing_a_purchase_bill_inside_a_filed_period_is_refused(db):
    """The purchase side matters for a different reason: a bill inside a filed
    period carries ITC already claimed in that GSTR-3B."""
    db.seed("filings", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_type": "GSTR-3B",
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "filed_date": "2026-07-20", "status": "filed", "deleted_at": None,
    })
    db.seed("purchase_bills", {
        "id": "BILL1", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "bill_date": "2026-06-15", "bill_no": "B-1",
    })

    with pytest.raises(HTTPException) as e:
        pb.update_purchase_bill("BILL1", pb.PurchaseBillUpdateIn(notes="edited"),
                       current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-3B" in e.value.detail
