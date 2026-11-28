"""A receipt in rupees does not settle an invoice billed in a foreign currency (ledger POST-A-576; migration 782).

WHAT WAS WRONG
    Found on 28-11-2026 by the independent review of the foreign-receipt change (POST-A-095), in code that change did not alter. Neither
    the API's rupee receipt nor the rupee branch of the receipt function asked what currency an invoice is billed in. A receipt in
    rupees allocated to a USD invoice moved `paid_paise`, left `paid_txn` at nothing, and marked the invoice paid by its rupee total:
    the books said paid while the whole foreign amount stood outstanding and no realised exchange difference existed. Re-allocating a
    receipt had the same hole, and a second one: it moves rupees only, so a FOREIGN receipt's allocations were reversed and re-applied
    in rupees with the foreign amounts left where they were.

WHAT THIS HOLDS (mock mode; the real-Postgres half is test_782_..._pg.py)
    * recording a rupee receipt against an invoice billed in USD is refused with a sentence that says which invoice, which currency
      and what to do, before anything is written;
    * the receipt function refuses the same if the API's check is ever missed (the test double mirrors migration 782, and the function's
      last definition is read for the refusal);
    * re-allocating a rupee receipt onto such an invoice is refused with the same sentence, and re-allocating a receipt that is itself
      in a foreign currency is refused in words; nothing is changed by either;
    * a rupee receipt on a rupee invoice, and a foreign receipt on a foreign invoice, are recorded as before.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests import _receipt_function_source as src
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-576"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-u1", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def world(monkeypatch):
    import routers.customers as cu
    import routers.receipts as rc
    import routers.sales_invoices as si
    import services.receipt_service as rs
    from models.invoices import InvoiceLineIn, SalesInvoiceIn
    from models.parties import CustomerIn

    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, rs])
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5", "functional_currency": "INR", "multi_currency_enabled": True})
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Services", "kind": "service"})
    customer = cu.create_customer(CustomerIn(client_id="CLI", name="Overseas Co", state_code="27"), CALLER)["data"]

    def invoice(number: str, total: int, currency: str | None = None, rate: str | None = None) -> dict:
        extra = {"currency": currency, "exchange_rate": rate} if currency else {}
        made = si.create_invoice(SalesInvoiceIn(
            client_id="CLI", customer_id=customer["id"], invoice_date="2026-06-01", invoice_no=number, **extra,
            lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1, rate_paise=total,
                                 gst_rate_percent=0.0)]), CALLER)["data"]
        assert si.issue_invoice(made["id"], CALLER)["success"] is True
        return made

    return db, rc, rs, customer, invoice


def _row(db, table: str, row_id: str) -> dict:
    return next(r for r in db._tables[table] if r["id"] == row_id)


def _receipt(rc, customer, amount, allocations=(), **extra):
    from models.invoices import ReceiptAllocationIn, ReceiptIn
    return rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=customer["id"], receipt_date="2026-06-10", amount_paise=amount, **extra,
        allocations=[ReceiptAllocationIn(sales_invoice_id=i, allocated_paise=a) for i, a in allocations]), CALLER)


def test_a_rupee_receipt_against_an_invoice_billed_in_usd_is_refused_in_words_and_nothing_is_recorded(world):
    db, rc, rs, customer, invoice = world
    usd = invoice("USD-576-1", 100_000, "USD", "80.0")
    before = dict(_row(db, "client_sales_invoices", usd["id"]))
    with pytest.raises(HTTPException) as refused:
        _receipt(rc, customer, 8_000_000, [(usd["id"], 8_000_000)])
    assert refused.value.status_code == 422
    assert refused.value.detail == rs.rupee_receipt_against_a_foreign_invoice("USD-576-1", "USD")
    assert "USD-576-1" in refused.value.detail and "Record the receipt in USD" in refused.value.detail and "Nothing was recorded" in refused.value.detail
    assert db._tables.get("receipts", []) == [] and db._tables.get("receipt_allocations", []) == []
    assert _row(db, "client_sales_invoices", usd["id"]) == before


def test_the_receipt_function_refuses_it_too_if_the_api_check_is_ever_missed(world, monkeypatch):
    """The second lock. With the API's own check taken away, the function (its double here, migration 782 in the database) refuses
    the receipt and leaves nothing."""
    db, rc, rs, customer, invoice = world
    usd = invoice("USD-576-2", 100_000, "USD", "80.0")
    before = dict(_row(db, "client_sales_invoices", usd["id"]))
    monkeypatch.setattr(rs, "_assert_invoices_can_take_a_rupee_receipt", lambda *a, **k: None)
    entries = len(db._tables.get("journal_entries", []))
    try:
        answer = _receipt(rc, customer, 8_000_000, [(usd["id"], 8_000_000)])
        assert answer["success"] is False and "billed in USD" in str(answer["error"]), answer
    except Exception as refused:               # the route may hand the function's refusal on as it is
        assert "billed in USD" in str(getattr(refused, "detail", refused))
    assert db._tables.get("receipts", []) == [] and len(db._tables.get("journal_entries", [])) == entries
    assert _row(db, "client_sales_invoices", usd["id"]) == before


def test_the_functions_last_definition_holds_the_refusal():
    name, body = src.body_definitions(src.migration_files())[-1]
    assert "the receipt is in INR and invoice % is billed in %" in body, f"{name} no longer refuses a rupee receipt a foreign invoice"
    assert "IF NOT v_foreign AND v_invoice_ccy <> 'INR' THEN" in body


def test_re_allocating_a_rupee_receipt_onto_a_foreign_invoice_is_refused_with_the_same_sentence(world):
    from routers.receipts import ReceiptAllocationsUpdateIn
    db, rc, rs, customer, invoice = world
    usd = invoice("USD-576-3", 100_000, "USD", "80.0")
    made = _receipt(rc, customer, 8_000_000)
    assert made["success"] is True, made
    before = dict(_row(db, "client_sales_invoices", usd["id"]))
    with pytest.raises(HTTPException) as refused:
        rc.update_allocations(made["data"]["id"], ReceiptAllocationsUpdateIn(
            allocations=[{"sales_invoice_id": usd["id"], "allocated_paise": 8_000_000}]), CALLER)
    assert refused.value.status_code == 422
    assert refused.value.detail == rs.rupee_receipt_against_a_foreign_invoice("USD-576-3", "USD")
    assert _row(db, "client_sales_invoices", usd["id"]) == before and db._tables.get("receipt_allocations", []) == []


def test_re_allocating_a_receipt_that_is_itself_in_a_foreign_currency_is_refused_in_words(world):
    from routers.receipts import ReceiptAllocationsUpdateIn
    db, rc, _rs, customer, invoice = world
    usd = invoice("USD-576-4", 100_000, "USD", "80.0")
    made = _receipt(rc, customer, 100_000, [(usd["id"], 60_000)], currency="USD", exchange_rate="83.0")
    assert made["success"] is True, made
    before = dict(_row(db, "client_sales_invoices", usd["id"]))
    allocations = [dict(a) for a in db._tables["receipt_allocations"]]
    with pytest.raises(HTTPException) as refused:
        rc.update_allocations(made["data"]["id"], ReceiptAllocationsUpdateIn(
            allocations=[{"sales_invoice_id": usd["id"], "allocated_paise": 100_000}]), CALLER)
    assert refused.value.status_code == 422
    assert refused.value.detail == rc.FOREIGN_RECEIPT_IS_NOT_REALLOCATED.format(currency="USD")
    assert "Reverse the receipt and record it again" in refused.value.detail and "Nothing was changed" in refused.value.detail
    assert _row(db, "client_sales_invoices", usd["id"]) == before and db._tables["receipt_allocations"] == allocations


def test_a_rupee_receipt_on_a_rupee_invoice_and_a_foreign_one_on_a_foreign_invoice_are_recorded_as_before(world):
    db, rc, _rs, customer, invoice = world
    inr = invoice("INR-576-5", 500_000)
    usd = invoice("USD-576-5", 100_000, "USD", "80.0")
    assert _receipt(rc, customer, 500_000, [(inr["id"], 500_000)])["success"] is True
    assert _receipt(rc, customer, 100_000, [(usd["id"], 100_000)], currency="USD", exchange_rate="83.0")["success"] is True
    assert _row(db, "client_sales_invoices", inr["id"])["status"] == "paid"
    paid = _row(db, "client_sales_invoices", usd["id"])
    assert (paid["status"], int(paid["paid_txn"])) == ("paid", 100_000)
