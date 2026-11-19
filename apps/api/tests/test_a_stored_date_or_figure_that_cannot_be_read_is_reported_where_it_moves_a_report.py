"""POST-A-505, the reading: six narrow handlers that moved a report onto a fallback without a word now report.

WHAT WAS WRONG
    The rule `test_a_narrow_handler_that_substitutes_a_value_says_so.py` freezes 152 narrow handlers whose whole body is a constant.
    Reading the ones that substitute a NUMBER for a stored date or figure found six where the fallback changes what a report or a deduction
    says: three ageing sums (a customer's receivables, a vendor's payables and the unapplied advances) that aged a document they could
    not date as ZERO days old, which is the current bucket, so the overdue total came out short; a stored TDS rate that could not be
    read, which became 0%; a stored bonus percentage that could not be read, which became a bonus of nothing; and a joining date that
    could not be read, which kept the twelve-month projection of §192. The columns are typed, so reaching any of them means damage, and
    damage is what a report must not paper over without saying so.

WHAT THIS HOLDS
    * the shared helper `days_old` ages a missing date as 0 with no report, a readable date by the day, and an unreadable one as 0 WITH a
      report that names the operation and what did not parse;
    * the customer and vendor ageing and the advances report age through it, driven with a bill, an invoice and an advance whose stored
      date is garbage: the document is still counted (the fallback answers) and the report is made;
    * the three figure helpers keep their fallbacks and report.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import pytest

from domain.reporting.age_of_document import days_old

TODAY = date(2026, 6, 30)


@pytest.fixture
def reports(caplog):
    caplog.set_level(logging.ERROR, logger="caflow.observability")
    return lambda: " ".join(r.getMessage() for r in caplog.records)


# ── the shared helper ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_missing_date_is_zero_days_old_and_says_nothing(reports):
    assert days_old(None, TODAY, operation="x.y") == 0
    assert days_old("", TODAY, operation="x.y") == 0
    assert reports() == ""


def test_a_readable_date_is_aged_by_the_day_whatever_its_shape(reports):
    assert days_old("2026-06-20", TODAY, operation="x.y") == 10
    assert days_old("2026-06-20T18:40:00+00:00", TODAY, operation="x.y") == 10      # the first ten characters are the date
    assert days_old(date(2026, 6, 20), TODAY, operation="x.y") == 10
    assert days_old(datetime(2026, 6, 20, 23, 59), TODAY, operation="x.y") == 10
    assert days_old("2026-07-10", TODAY, operation="x.y") == -10                   # a future due date is negative, as the buckets expect
    assert reports() == ""


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-45", "31/03/2026", 12345, "yesterday"])
def test_a_date_that_cannot_be_read_is_zero_days_old_and_reported(bad, reports):
    assert days_old(bad, TODAY, operation="x.unreadable", document_id="D1") == 0
    text = reports()
    assert "x.unreadable" in text and "D1" in text


# ── the three ageing sums ────────────────────────────────────────────────────────────────────────────────────────

def test_the_vendor_ageing_counts_a_bill_it_cannot_date_and_says_so(monkeypatch, reports):
    from tests.test_ap_completeness import CALLER, FIRM, _bill, _received_bill, _setup
    from services.vendor_statement_service import vendor_statement_service

    db = _setup(monkeypatch)
    bid, net = _received_bill(db, rate=1_00000)
    _bill(db, bid)["due_date"] = "not-a-date"
    aging = vendor_statement_service.ap_aging(db, FIRM, "CLI", as_of="2025-06-15")
    assert aging["total_outstanding_paise"] == net, "the bill it could not date must still be counted"
    assert [row["bill_id"] for row in aging["bills"]] == [bid]
    assert "vendor_statement.ap_aging.unreadable_date" in reports() and bid in reports()
    assert CALLER  # (the import keeps the harness's caller visible to a reader)


def test_the_customer_ageing_counts_an_invoice_it_cannot_date_and_says_so(reports):
    from tests.e2e_harness import FakeDB
    from services.customer_statement_service import customer_statement_service

    db = FakeDB()
    db.seed("customers", {"id": "K1", "firm_id": "F", "client_id": "C", "name": "Mehta Traders"})
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": "F", "client_id": "C", "customer_id": "K1", "invoice_no": "SINV-1", "invoice_date": "garbled",
        "due_date": "also garbled", "total_paise": 118000, "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0,
        "outstanding_paise": 118000, "status": "issued", "deleted_at": None,
    })
    aging = customer_statement_service.ar_aging(db, "F", "C", as_of="2026-06-30")
    assert aging["total_outstanding_paise"] == 118000, "the invoice it could not date must still be counted"
    assert "customer_statement.ar_aging.unreadable_date" in reports() and "INV1" in reports()


def test_the_advances_report_ages_an_undated_advance_as_current_and_says_so(reports):
    from domain.reporting.party_advances import AdvanceInput, unapplied_advances

    rows = [AdvanceInput(document_id="PAY1", document_no="VPMT-1", party_id="V1", party_name="Supplier", document_date="not-a-date",
                         settlement_paise=50000, unallocated_paise=50000, allocated_paise=0)]
    out = unapplied_advances(rows, today=TODAY, document_label="payment")
    assert out.total_paise == 50000, "the advance must still be counted"
    assert "party_advances.unreadable_date" in reports() and "PAY1" in reports()


# ── the three figure helpers ─────────────────────────────────────────────────────────────────────────────────────

def test_a_stored_tds_rate_that_cannot_be_read_keeps_zero_and_is_reported(reports):
    from services.tds_return_service import _typed_rate_bps

    assert _typed_rate_bps("10") == 1000 and _typed_rate_bps("1.5") == 150 and _typed_rate_bps(None) == 0
    assert reports() == ""
    assert _typed_rate_bps("ten percent") == 0
    assert "tds_return.typed_rate_unreadable" in reports()


def test_a_stored_bonus_percentage_that_cannot_be_read_keeps_zero_and_is_reported(reports):
    from services.bonus_register_service import _percent_of

    assert _percent_of(2_400_000, 8.33) == 199_920 and _percent_of(100, None) == 0
    assert reports() == ""
    assert _percent_of(100_00, "eight") == 0
    assert "bonus_register.percent_of_unreadable" in reports()


def test_a_joining_date_that_cannot_be_read_keeps_twelve_months_and_is_reported(reports):
    from routers.payroll import _months_employed_in_fy

    assert _months_employed_in_fy(None, "2026-27") == 12 and _months_employed_in_fy("2026-10-01", "2026-27") == 6
    assert reports() == ""
    assert _months_employed_in_fy("someday in October", "2026-27") == 12
    assert "payroll.months_employed_unreadable" in reports()
