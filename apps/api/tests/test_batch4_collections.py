"""
Batch 4 (Amendment v1.1) — Collections & AR, application-layer tests (mock mode).
Covers due-date aging buckets, derived overdue flags (no status mutation),
dashboard KPIs incl. TDS receivable, reminder idempotency, ReceiptIn TDS
settlement validation, and partner-only access. DB-level guarantees (migration
077, balanced TDS journal, invoice settlement) are in test_batch4_migration.py.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from core.permissions import can
from models.invoices import ReceiptIn, ReceiptAllocationIn
import services.internal_client_service as ics
import services.collections_service as coll
from routers.sales_invoices import MOCK_SALES_INVOICES
from routers.receipts import MOCK_RECEIPTS

FIRM = "F1"
INT = "INT"
TODAY = date(2026, 6, 30)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: INT)
    MOCK_SALES_INVOICES.clear()
    MOCK_RECEIPTS.clear()
    MOCK_SALES_INVOICES.extend([
        _inv("A", "issued", 118000, 0, "2026-06-20"),          # 10d overdue -> 0-30
        _inv("B", "issued", 100000, 0, "2026-04-15"),          # 76d -> 61-90
        _inv("C", "issued", 50000, 0, "2026-07-10"),           # future -> not_due
        _inv("D", "partially_paid", 100000, 40000, "2026-01-01"),  # >90, outstanding 60000
        _inv("E", "paid", 100000, 100000, "2026-01-01"),       # settled -> excluded
        _inv("F", "draft", 100000, 0, "2026-01-01"),           # draft -> excluded
    ])
    MOCK_RECEIPTS.append({"firm_id": FIRM, "client_id": INT, "amount_paise": 90000,
                          "tds_paise": 10000, "receipt_date": "2026-06-10"})
    yield
    MOCK_SALES_INVOICES.clear()
    MOCK_RECEIPTS.clear()


def _inv(iid, status, total, paid, due):
    return {"id": iid, "firm_id": FIRM, "client_id": INT, "invoice_no": f"SINV-{iid}",
            "invoice_date": "2026-03-01", "due_date": due, "total_paise": total,
            "paid_paise": paid, "status": status}


def test_aging_buckets_due_date_based():
    aging = coll.ar_aging(FIRM, today=TODAY)
    b = aging["buckets"]
    assert b["not_due"] == {"paise": 50000, "count": 1}      # C
    assert b["0-30"] == {"paise": 118000, "count": 1}        # A
    assert b["31-60"] == {"paise": 0, "count": 0}
    assert b["61-90"] == {"paise": 100000, "count": 1}       # B
    assert b["90+"] == {"paise": 60000, "count": 1}          # D outstanding
    assert aging["total_outstanding_paise"] == 328000
    assert aging["overdue_paise"] == 278000 and aging["overdue_count"] == 3


def test_overdue_is_derived_not_status_mutation():
    coll.sweep_overdue(FIRM, today=TODAY)
    by_id = {i["id"]: i for i in MOCK_SALES_INVOICES}
    # flags set; payment status preserved (no 'overdue' status)
    assert by_id["A"]["is_overdue"] is True and by_id["A"]["status"] == "issued"
    assert by_id["D"]["is_overdue"] is True and by_id["D"]["status"] == "partially_paid"
    assert by_id["D"]["aging_bucket"] == "90+" and by_id["D"]["days_overdue"] > 90
    assert by_id["C"]["is_overdue"] is False and by_id["C"]["aging_bucket"] == "not_due"
    # paid/draft never swept into overdue
    assert by_id["E"].get("is_overdue", False) is False
    assert "overdue" not in {i["status"] for i in MOCK_SALES_INVOICES}


def test_dashboard_kpis_include_tds_and_cash():
    dash = coll.dashboard(FIRM, date_from="2026-06-01", date_to="2026-06-30", today=TODAY)
    assert dash["total_receivable_paise"] == 328000
    assert dash["overdue_count"] == 3
    assert dash["tds_receivable_paise"] == 10000     # from receipts.tds_paise
    assert dash["collected_cash_paise"] == 90000


def test_reminders_idempotent_cadence():
    first = coll.send_overdue_reminders(FIRM, today=TODAY)
    assert first["reminders_sent"] == 3              # A, B, D
    # immediate re-run within cadence window -> none
    second = coll.send_overdue_reminders(FIRM, today=TODAY)
    assert second["reminders_sent"] == 0
    by_id = {i["id"]: i for i in MOCK_SALES_INVOICES}
    assert by_id["A"]["reminder_count"] == 1


def test_receipt_tds_settlement_validation():
    # settlement = amount + tds = 100000; allocating exactly 100000 is valid
    ReceiptIn(client_id="c", customer_id="cu", receipt_date="2026-06-10",
              amount_paise=90000, tds_paise=10000,
              allocations=[ReceiptAllocationIn(sales_invoice_id="A", allocated_paise=100000)])
    # allocating beyond settlement is rejected
    with pytest.raises(ValidationError):
        ReceiptIn(client_id="c", customer_id="cu", receipt_date="2026-06-10",
                  amount_paise=90000, tds_paise=10000,
                  allocations=[ReceiptAllocationIn(sales_invoice_id="A", allocated_paise=100001)])


def test_aging_bucket_boundaries():
    assert coll.aging_bucket(0) == "not_due"
    assert coll.aging_bucket(1) == "0-30"
    assert coll.aging_bucket(30) == "0-30"
    assert coll.aging_bucket(31) == "31-60"
    assert coll.aging_bucket(90) == "61-90"
    assert coll.aging_bucket(91) == "90+"


def test_due_date_fallback_uses_credit_days():
    inv = {"invoice_date": "2026-06-01"}  # no due_date
    assert coll.reference_due_date(inv, credit_days=30) == date(2026, 7, 1)


def test_partner_only_collections():
    assert can("Partner", "billing", "read") is True
    assert can("Manager", "billing", "read") is False
    assert can("Executive", "billing", "write") is False
