"""A receipt from one customer does not settle an invoice issued to another customer of the same client (ledger POST-A-580, the
receipt half; migration 785).

WHAT WAS WRONG
    Found on 28-11-2026 while building the supplier payment's function, which refuses a bill raised by another supplier. No receipt
    path asked whose the invoice was. The API checked that an invoice a receipt settles is the client's, issued and billed in the
    receipt's currency; the receipt function asked the same; and re-allocating a receipt asked no more. A receipt from customer A
    naming customer B's invoice marked B's invoice paid and left A with no advance: two wrong statements. The screens offer only the
    customer's own invoices, and the bank match queue derives the customer from the documents and refuses a mix, so it took a
    hand-made request.

WHAT THIS HOLDS (mock mode; the real-Postgres half is test_785_..._pg.py)
    * recording a rupee receipt, or a foreign one, against another customer's invoice is refused with a sentence that names the
      invoice and says what a receipt settles, before anything is written;
    * the receipt function refuses the same if the API's check is ever missed (the test double mirrors migration 785, and the
      function's last definition is read for the refusal);
    * re-allocating a receipt onto another customer's invoice is refused, and says nothing was CHANGED;
    * a receipt against its own customer's invoices is recorded as before, and so is a receipt across two of them.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests import _receipt_function_source as src
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-580"
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
    payer = cu.create_customer(CustomerIn(client_id="CLI", name="The One Who Pays", state_code="27"), CALLER)["data"]
    other = cu.create_customer(CustomerIn(client_id="CLI", name="Somebody Else", state_code="27"), CALLER)["data"]

    def invoice(customer: dict, number: str, total: int, currency: str | None = None, rate: str | None = None) -> dict:
        extra = {"currency": currency, "exchange_rate": rate} if currency else {}
        made = si.create_invoice(SalesInvoiceIn(
            client_id="CLI", customer_id=customer["id"], invoice_date="2026-06-01", invoice_no=number, **extra,
            lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1, rate_paise=total,
                                 gst_rate_percent=0.0)]), CALLER)["data"]
        assert si.issue_invoice(made["id"], CALLER)["success"] is True
        return made

    return db, rc, rs, payer, other, invoice


def _row(db, table: str, row_id: str) -> dict:
    return next(r for r in db._tables[table] if r["id"] == row_id)


def _receipt(rc, customer, amount, allocations=(), **extra):
    from models.invoices import ReceiptAllocationIn, ReceiptIn
    return rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=customer["id"], receipt_date="2026-06-10", amount_paise=amount, **extra,
        allocations=[ReceiptAllocationIn(sales_invoice_id=i, allocated_paise=a) for i, a in allocations]), CALLER)


def _nothing_was_written(db) -> bool:
    return db._tables.get("receipts", []) == [] and db._tables.get("receipt_allocations", []) == []


def test_a_rupee_receipt_against_another_customers_invoice_is_refused_in_words_and_nothing_is_recorded(world):
    db, rc, rs, payer, other, invoice = world
    mine, theirs = invoice(payer, "INV-580-1", 500_000), invoice(other, "INV-580-2", 500_000)
    before = (dict(_row(db, "client_sales_invoices", mine["id"])), dict(_row(db, "client_sales_invoices", theirs["id"])))
    entries = len(db._tables.get("journal_entries", []))
    with pytest.raises(HTTPException) as refused:
        _receipt(rc, payer, 700_000, [(mine["id"], 500_000), (theirs["id"], 200_000)])
    assert refused.value.status_code == 422
    assert refused.value.detail == rs.invoice_of_another_customer("INV-580-2")
    assert "INV-580-2" in refused.value.detail and "issued to another customer" in refused.value.detail and "Nothing was recorded" in refused.value.detail
    assert _nothing_was_written(db) and len(db._tables.get("journal_entries", [])) == entries
    assert (_row(db, "client_sales_invoices", mine["id"]), _row(db, "client_sales_invoices", theirs["id"])) == before, \
        "the payer's own invoice was settled before the other customer's was refused"


def test_a_foreign_receipt_against_another_customers_invoice_is_refused_the_same_way(world):
    db, rc, rs, payer, other, invoice = world
    theirs = invoice(other, "USD-580-3", 100_000, "USD", "80.0")
    before = dict(_row(db, "client_sales_invoices", theirs["id"]))
    with pytest.raises(HTTPException) as refused:
        _receipt(rc, payer, 100_000, [(theirs["id"], 100_000)], currency="USD", exchange_rate="83.0")
    assert refused.value.status_code == 422 and refused.value.detail == rs.invoice_of_another_customer("USD-580-3")
    assert _nothing_was_written(db) and db._tables.get("fx_adjustments", []) == []
    assert _row(db, "client_sales_invoices", theirs["id"]) == before


def test_the_receipt_function_refuses_it_too_if_the_api_check_is_ever_missed(world, monkeypatch):
    """The second lock. With the API's own check taken away, the function (its double here, migration 785 in the database) refuses
    the receipt and leaves nothing."""
    db, rc, rs, payer, other, invoice = world
    theirs = invoice(other, "INV-580-4", 500_000)
    before = dict(_row(db, "client_sales_invoices", theirs["id"]))
    monkeypatch.setattr(rs, "_assert_invoices_can_take_a_rupee_receipt", lambda *a, **k: None)
    entries = len(db._tables.get("journal_entries", []))
    try:
        answer = _receipt(rc, payer, 500_000, [(theirs["id"], 500_000)])
        assert answer["success"] is False and "issued to another customer" in str(answer["error"]), answer
    except Exception as refused:               # the route may hand the function's refusal on as it is
        assert "issued to another customer" in str(getattr(refused, "detail", refused))
    assert _nothing_was_written(db) and len(db._tables.get("journal_entries", [])) == entries
    assert _row(db, "client_sales_invoices", theirs["id"]) == before


def test_the_functions_last_definition_holds_the_refusal():
    name, body = src.body_definitions(src.migration_files())[-1]
    assert "invoice % was issued to another customer" in body, f"{name} no longer refuses a receipt another customer's invoice"
    assert "IF v_invoice_customer IS DISTINCT FROM NULLIF(p_receipt->>'customer_id', '')::uuid THEN" in body
    # and it kept what migration 782 added (a replacement carries every earlier change forward, or silently reverts it)
    assert "IF NOT v_foreign AND v_invoice_ccy <> 'INR' THEN" in body and "RC001" in body
    # POST-A-581: the invoices of one receipt are locked in one order
    assert "GROUP BY (x->>'sales_invoice_id')::uuid" in body and "ORDER BY 1\n  LOOP" in body


def test_re_allocating_a_receipt_onto_another_customers_invoice_is_refused_and_says_nothing_was_changed(world):
    from routers.receipts import ReceiptAllocationsUpdateIn
    db, rc, rs, payer, other, invoice = world
    mine, theirs = invoice(payer, "INV-580-5", 500_000), invoice(other, "INV-580-6", 500_000)
    made = _receipt(rc, payer, 500_000, [(mine["id"], 200_000)])
    assert made["success"] is True, made
    settled = lambda inv: (int(_row(db, "client_sales_invoices", inv["id"]).get("paid_paise") or 0),          # noqa: E731
                           _row(db, "client_sales_invoices", inv["id"])["status"])
    before = (settled(mine), settled(theirs))
    assert before == ((200_000, "partially_paid"), (0, "issued"))
    allocations = [dict(a) for a in db._tables["receipt_allocations"]]
    with pytest.raises(HTTPException) as refused:
        rc.update_allocations(made["data"]["id"], ReceiptAllocationsUpdateIn(
            allocations=[{"sales_invoice_id": mine["id"], "allocated_paise": 200_000},
                         {"sales_invoice_id": theirs["id"], "allocated_paise": 300_000}]), CALLER)
    assert refused.value.status_code == 422
    assert refused.value.detail == rs.invoice_of_another_customer("INV-580-6", "changed")
    assert "Nothing was changed" in refused.value.detail
    assert (settled(mine), settled(theirs)) == before
    assert db._tables["receipt_allocations"] == allocations


def test_a_receipt_against_its_own_customers_invoices_is_recorded_as_before(world):
    from routers.receipts import ReceiptAllocationsUpdateIn
    db, rc, _rs, payer, _other, invoice = world
    first, second = invoice(payer, "INV-580-7", 500_000), invoice(payer, "INV-580-8", 300_000)
    usd = invoice(payer, "USD-580-9", 100_000, "USD", "80.0")
    made = _receipt(rc, payer, 800_000, [(first["id"], 500_000), (second["id"], 100_000)])
    assert made["success"] is True, made
    assert (_row(db, "client_sales_invoices", first["id"])["status"], _row(db, "client_sales_invoices", second["id"])["status"]) == \
        ("paid", "partially_paid")
    assert _receipt(rc, payer, 100_000, [(usd["id"], 100_000)], currency="USD", exchange_rate="83.0")["success"] is True
    assert _row(db, "client_sales_invoices", usd["id"])["status"] == "paid"
    # and its allocations can still be moved between its own customer's invoices
    moved = rc.update_allocations(made["data"]["id"], ReceiptAllocationsUpdateIn(
        allocations=[{"sales_invoice_id": first["id"], "allocated_paise": 500_000},
                     {"sales_invoice_id": second["id"], "allocated_paise": 300_000}]), CALLER)
    assert moved["success"] is True, moved
    assert _row(db, "client_sales_invoices", second["id"])["status"] == "paid"
