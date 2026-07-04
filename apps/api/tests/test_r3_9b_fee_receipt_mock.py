"""
R3.9b — mock-mode tests for services.fee_billing_service.record_receipt().

apps/web/app/billing/page.tsx's "Record Receipt" flow used to insert directly
into fee_receipts and force-set fee_invoices.status to "Paid" regardless of
the amount entered. These tests cover the corrected logic against the
mock-mode repo (real-Postgres RLS/RPC atomicity is proven separately in
test_r3_9b_fee_receipt_atomic_pg.py).
"""
import pytest
from fastapi import HTTPException

import services.fee_billing_service as fee_billing
from repositories.invoice_repository import invoice_repo
from mock_data import MOCK_INVOICES, INVOICE_INDEX

FIRM = "firm-r39b"


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    fee_billing.MOCK_FEE_RECEIPTS.clear()
    yield
    fee_billing.MOCK_FEE_RECEIPTS.clear()
    # Undo any invoice created during a test.
    MOCK_INVOICES[:] = [i for i in MOCK_INVOICES if i.get("firm_id") != FIRM]
    for key in [k for k, v in INVOICE_INDEX.items() if v.get("firm_id") == FIRM]:
        del INVOICE_INDEX[key]


def _make_invoice(total_paise: int, paid_paise: int = 0, status: str = "Sent") -> dict:
    record = invoice_repo.create({
        "firm_id": FIRM,
        "client_id": "client-r39b",
        "invoice_no": "INV-R39B",
        "amount_paise": total_paise,
        "gst_paise": 0,
        "total_paise": total_paise,
        "paid_paise": paid_paise,
        "status": status,
    })
    return record


def test_partial_receipt_leaves_status_unchanged():
    inv = _make_invoice(total_paise=590000)
    receipt = fee_billing.record_receipt(FIRM, inv["id"], {
        "amount_paise": 50000, "payment_mode": "NEFT",
    })
    assert receipt["amount_paise"] == 50000
    updated = invoice_repo.find_by_id(inv["id"])
    assert updated["paid_paise"] == 50000
    assert updated["status"] == "Sent"


def test_receipt_covering_total_marks_paid():
    inv = _make_invoice(total_paise=590000)
    fee_billing.record_receipt(FIRM, inv["id"], {"amount_paise": 90000, "payment_mode": "Cash"})
    fee_billing.record_receipt(FIRM, inv["id"], {"amount_paise": 500000, "payment_mode": "NEFT"})
    updated = invoice_repo.find_by_id(inv["id"])
    assert updated["paid_paise"] == 590000
    assert updated["status"] == "Paid"
    assert len([r for r in fee_billing.MOCK_FEE_RECEIPTS if r["invoice_id"] == inv["id"]]) == 2


def test_non_positive_amount_rejected():
    inv = _make_invoice(total_paise=590000)
    with pytest.raises(HTTPException) as exc:
        fee_billing.record_receipt(FIRM, inv["id"], {"amount_paise": 0})
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        fee_billing.record_receipt(FIRM, inv["id"], {"amount_paise": -100})


def test_invoice_not_found_rejected():
    with pytest.raises(HTTPException) as exc:
        fee_billing.record_receipt(FIRM, "does-not-exist", {"amount_paise": 100})
    assert exc.value.status_code == 404


def test_cross_firm_invoice_is_rejected():
    inv = _make_invoice(total_paise=590000)
    with pytest.raises(HTTPException) as exc:
        fee_billing.record_receipt("some-other-firm", inv["id"], {"amount_paise": 100})
    assert exc.value.status_code == 404
