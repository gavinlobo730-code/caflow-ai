"""A receipt or a payment whose answer was lost on the way back is answered from what was stored (ledger POST-A-582).

WHAT WAS WRONG
    `settle_receipt_atomic` and `settle_payment_atomic` commit before they answer. If the connection drops, or the call times out,
    after the commit and before the answer reaches the API, the API saw an error for a document that WAS stored. The person read a
    failure and recorded it again: a pure advance (which no outstanding amount stops) was stored twice, and a receipt against an
    invoice was refused for the amount already settled, in words that said the invoice was paid and a failure that said it was not.
    The class is older than the two functions, which is what makes the fix cheap: the receipt's or payment's id is chosen BEFORE the
    call, so the API can read the one row by that id and answer with what is there.

WHAT THIS HOLDS (mock mode: the functions' doubles in `tests/e2e_harness.py`; the call that commits and then fails is made by wrapping
the double's `rpc`)
    * a rupee payment against one bill, a rupee payment across several bills, a foreign payment, a plain rupee receipt, an advance
      receipt and a foreign receipt each answer SUCCESS when the function committed and the answer was lost, with the stored row's id,
      its ledger entry and its allocation rows; one document, one entry and one settlement exist afterwards, and the person is not
      asked to record it again;
    * an error BEFORE the function ran (nothing stored) is answered as the failure it is, and nothing is invented;
    * the function's own refusal (here: more than is outstanding) is still a refusal, and the stored row is not consulted for it;
    * the reader (`ledger_door.stored_answer`) answers for the firm and client it was asked for and for no other, says None when
      the read itself fails (the first error stands), and rebuilds the function's own answer shape.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.invoices import (InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentAllocationIn, PurchasePaymentIn,
                             ReceiptAllocationIn, ReceiptIn, SalesInvoiceIn)
from models.parties import CustomerIn, VendorIn
from services import ledger_door
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-582"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-u1", "email": "ca@f.test", "role": "Partner"}
LOST = ConnectionError("the connection closed before the database's answer arrived")


@pytest.fixture
def book(monkeypatch):
    import routers.customers as cu
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    import routers.receipts as rc
    import routers.sales_invoices as si
    import routers.vendors as ve
    import services.purchase_payment_service as pps
    import services.receipt_service as rs

    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, pb, pp, rc, si, ve, pps, rs])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5", "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Services", "kind": "service"})
    return db, dict(cu=cu, pb=pb, pp=pp, rc=rc, si=si, ve=ve)


def _lose_the_answer(db, fn_name: str, *, commit: bool = True, error: Exception = LOST):
    """Make the named function's call fail: after it committed (the answer was lost) or before it ran (nothing stored)."""
    real = db.rpc

    def rpc(fn, params=None):
        builder = real(fn, params)
        if fn != fn_name:
            return builder

        class _Lost:
            def execute(self):
                if commit:
                    builder.execute()
                raise error
        return _Lost()

    db.rpc = rpc


def _rows(db, table):
    return db._tables.get(table, [])


def _vendor_bill(m, total, no, *, currency=None, rate=None):
    vendor = m["ve"].create_vendor(VendorIn(client_id="CLI", name=f"Supplier {no}", state_code="27"), CALLER)["data"]
    extra = {"currency": currency, "exchange_rate": rate} if currency else {}
    bill = m["pb"].create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor["id"], bill_date="2026-06-01", bill_no=no, **extra,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=total, quantity=1,
                                  gst_rate_percent=0.0)]), CALLER)["data"]
    assert m["pb"].receive_purchase_bill(bill["id"], CALLER)["success"] is True
    return vendor, bill


def _customer_invoice(m, total, no, *, currency=None, rate=None):
    customer = m["cu"].create_customer(CustomerIn(client_id="CLI", name=f"Customer {no}", state_code="27"), CALLER)["data"]
    extra = {"currency": currency, "exchange_rate": rate} if currency else {}
    inv = m["si"].create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=customer["id"], invoice_date="2026-06-01", invoice_no=no, **extra,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1, rate_paise=total,
                             gst_rate_percent=0.0)]), CALLER)["data"]
    assert m["si"].issue_invoice(inv["id"], CALLER)["success"] is True
    return customer, inv


def _pay(m, vendor, amount, **kw):
    return m["pp"].create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vendor["id"], payment_date="2026-06-10", amount_paise=amount, **kw), CALLER)


def _receive(m, customer, amount, allocations=(), **kw):
    return m["rc"].create_receipt(ReceiptIn(
        client_id="CLI", customer_id=customer["id"], receipt_date="2026-06-10", amount_paise=amount, **kw,
        allocations=[ReceiptAllocationIn(sales_invoice_id=i, allocated_paise=a) for i, a in allocations]), CALLER)


# ── a payment ─────────────────────────────────────────────────────────────

def test_a_rupee_payment_against_one_bill_whose_answer_was_lost_is_answered_from_what_was_stored(book):
    db, m = book
    vendor, bill = _vendor_bill(m, 500_000, "B-1")
    entries = len(_rows(db, "journal_entries"))
    _lose_the_answer(db, "settle_payment_atomic")
    made = _pay(m, vendor, 200_000, purchase_bill_id=bill["id"])
    assert made["success"] is True, made
    (payment,) = _rows(db, "purchase_payments")
    assert made["data"]["id"] == payment["id"] and made["data"]["journal_entry_id"] == payment["journal_entry_id"]
    assert len(_rows(db, "journal_entries")) - entries == 1
    bill_row = next(b for b in _rows(db, "purchase_bills") if b["id"] == bill["id"])
    assert (bill_row["paid_paise"], bill_row["status"]) == (200_000, "partially_paid")


def test_a_rupee_payment_across_several_bills_whose_answer_was_lost_names_its_allocations(book):
    db, m = book
    vendor, first = _vendor_bill(m, 300_000, "B-2")
    second = m["pb"].create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vendor["id"], bill_date="2026-06-02", bill_no="B-3",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=200_000, quantity=1, gst_rate_percent=0.0)]),
        CALLER)["data"]
    assert m["pb"].receive_purchase_bill(second["id"], CALLER)["success"] is True
    _lose_the_answer(db, "settle_payment_atomic")
    made = m["pp"].create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vendor["id"], payment_date="2026-06-10", amount_paise=500_000,
        allocations=[PurchasePaymentAllocationIn(purchase_bill_id=first["id"], allocated_paise=300_000),
                     PurchasePaymentAllocationIn(purchase_bill_id=second["id"], allocated_paise=200_000)]), CALLER)
    assert made["success"] is True, made
    assert len(_rows(db, "purchase_payments")) == 1 and len(_rows(db, "purchase_payment_allocations")) == 2
    assert sorted(a["allocated_paise"] for a in _rows(db, "purchase_payment_allocations")) == [200_000, 300_000]
    assert {b["id"]: b["status"] for b in _rows(db, "purchase_bills") if b["id"] in (first["id"], second["id"])} == \
        {first["id"]: "paid", second["id"]: "paid"}


def test_a_foreign_payment_whose_answer_was_lost_is_answered_from_what_was_stored(book):
    db, m = book
    vendor, bill = _vendor_bill(m, 100_000, "USD-1", currency="USD", rate="80.0")
    _lose_the_answer(db, "settle_payment_atomic")
    made = m["pp"].create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vendor["id"], payment_date="2026-06-10", amount_paise=100_000, purchase_bill_id=bill["id"],
        currency="USD", exchange_rate="83.0"), CALLER)
    assert made["success"] is True, made
    assert len(_rows(db, "purchase_payments")) == 1
    assert next(b for b in _rows(db, "purchase_bills") if b["id"] == bill["id"])["status"] == "paid"


def test_an_error_before_the_payment_function_ran_is_a_failure_and_nothing_is_stored(book):
    db, m = book
    vendor, bill = _vendor_bill(m, 500_000, "B-4")
    _lose_the_answer(db, "settle_payment_atomic", commit=False)
    # the route answers an unexpected error in its own envelope: a failure, and nothing recorded
    answer = _pay(m, vendor, 200_000, purchase_bill_id=bill["id"])
    assert answer["success"] is False and "connection closed" in str(answer["error"]), answer
    assert _rows(db, "purchase_payments") == [] and _rows(db, "purchase_payment_allocations") == []
    assert next(b for b in _rows(db, "purchase_bills") if b["id"] == bill["id"]).get("paid_paise", 0) == 0


# ── a receipt ─────────────────────────────────────────────────────────────

def test_a_rupee_receipt_whose_answer_was_lost_is_answered_from_what_was_stored(book):
    db, m = book
    customer, inv = _customer_invoice(m, 500_000, "INV-1")
    entries = len(_rows(db, "journal_entries"))
    _lose_the_answer(db, "settle_receipt_atomic")
    made = _receive(m, customer, 500_000, [(inv["id"], 500_000)])
    assert made["success"] is True, made
    (receipt,) = _rows(db, "receipts")
    assert made["data"]["id"] == receipt["id"] and made["data"]["journal_entry_id"] == receipt["journal_entry_id"]
    assert len(_rows(db, "journal_entries")) - entries == 1 and len(_rows(db, "receipt_allocations")) == 1
    assert next(i for i in _rows(db, "client_sales_invoices") if i["id"] == inv["id"])["status"] == "paid"


def test_an_advance_whose_answer_was_lost_is_not_recorded_twice(book):
    """A pure advance has no invoice for an outstanding amount to stop a second one, so the lost answer is the whole defence."""
    db, m = book
    customer, _inv = _customer_invoice(m, 100_000, "INV-2")
    _lose_the_answer(db, "settle_receipt_atomic")
    made = _receive(m, customer, 250_000)
    assert made["success"] is True, made
    assert len(_rows(db, "receipts")) == 1 and made["data"]["id"] == _rows(db, "receipts")[0]["id"]


def test_a_foreign_receipt_whose_answer_was_lost_is_answered_from_what_was_stored(book):
    db, m = book
    customer, inv = _customer_invoice(m, 100_000, "USD-2", currency="USD", rate="80.0")
    _lose_the_answer(db, "settle_receipt_atomic")
    made = _receive(m, customer, 100_000, [(inv["id"], 100_000)], currency="USD", exchange_rate="83.0")
    assert made["success"] is True, made
    assert len(_rows(db, "receipts")) == 1 and len(_rows(db, "receipt_allocations")) == 1
    assert next(i for i in _rows(db, "client_sales_invoices") if i["id"] == inv["id"])["status"] == "paid"


def test_an_error_before_the_receipt_function_ran_is_a_failure_and_nothing_is_stored(book):
    db, m = book
    customer, inv = _customer_invoice(m, 500_000, "INV-3")
    _lose_the_answer(db, "settle_receipt_atomic", commit=False)
    answer = _receive(m, customer, 500_000, [(inv["id"], 500_000)])
    assert answer["success"] is False and "connection closed" in str(answer["error"]), answer
    assert _rows(db, "receipts") == [] and _rows(db, "receipt_allocations") == []
    assert next(i for i in _rows(db, "client_sales_invoices") if i["id"] == inv["id"]).get("paid_paise", 0) == 0


def test_the_functions_own_refusal_is_still_a_refusal(book):
    """More than is outstanding is refused by the API before the function is asked, and by the function if it is ever asked: the
    stored row is not consulted for either, and the person reads the refusal."""
    db, m = book
    customer, inv = _customer_invoice(m, 100_000, "INV-4")
    with pytest.raises(HTTPException) as refused:
        _receive(m, customer, 900_000, [(inv["id"], 900_000)])
    assert 400 <= refused.value.status_code < 500
    assert _rows(db, "receipts") == []


# ── the reader ────────────────────────────────────────────────────────────

def _stored_receipt(db):
    db.seed("receipts", {"id": "R-1", "firm_id": FIRM, "client_id": "CLI", "journal_entry_id": "J-1"})
    db.seed("journal_entries", {"id": "J-1", "firm_id": FIRM, "client_id": "CLI", "source_type": "receipt", "source_id": "R-1"})
    db.seed("receipt_allocations", {"id": "A-1", "receipt_id": "R-1", "sales_invoice_id": "S-1", "allocated_paise": 5})


def test_the_reader_rebuilds_the_functions_answer_shape(book):
    db, _m = book
    _stored_receipt(db)
    out = ledger_door.stored_answer(db, kind="receipt", row_id="R-1", firm_id=FIRM, client_id="CLI")
    assert set(out) == {"receipt_id", "journal_entry_id", "receipt", "allocations"}
    assert (out["receipt_id"], out["journal_entry_id"]) == ("R-1", "J-1") and out["receipt"]["id"] == "R-1"
    assert [a["id"] for a in out["allocations"]] == ["A-1"]


def test_the_reader_answers_for_the_firm_and_client_it_was_asked_for_and_for_no_other(book):
    db, _m = book
    _stored_receipt(db)
    assert ledger_door.stored_answer(db, kind="receipt", row_id="R-1", firm_id="OTHER-FIRM", client_id="CLI") is None
    assert ledger_door.stored_answer(db, kind="receipt", row_id="R-1", firm_id=FIRM, client_id="OTHER-CLIENT") is None
    assert ledger_door.stored_answer(db, kind="receipt", row_id="NOT-THERE", firm_id=FIRM, client_id="CLI") is None
    assert ledger_door.stored_answer(db, kind="payment", row_id="R-1", firm_id=FIRM, client_id="CLI") is None
    assert ledger_door.stored_answer(db, kind="receipt", row_id="", firm_id=FIRM, client_id="CLI") is None


def test_a_read_that_fails_answers_none_so_the_first_error_stands(book, monkeypatch):
    db, _m = book
    _stored_receipt(db)

    def broken(*a, **k):
        raise ConnectionError("the second connection failed too")
    monkeypatch.setattr(ledger_door, "ledger_client", broken)
    assert ledger_door.stored_answer(db, kind="receipt", row_id="R-1", firm_id=FIRM, client_id="CLI") is None
