"""A sales invoice line names the order line it bills, an order shows what has been invoiced, and billing more than was ordered is
refused (POST-A-104, migration 589).

WHAT WAS WRONG
    An order's position showed INVOICED as zero on every line, and said so, because an invoice line carried no link back to the order
    line it billed. Nothing could raise an invoice from an order, and nothing refused billing the same line twice.

WHAT THESE HOLD (mock mode; the database's own refusal is in the `_pg` file)
    * the position counts issued invoices that NAME the line: not a draft (unless the question is what hangs from the line), not a
      cancelled or deleted invoice, and not an unlinked invoice line that merely has the same description;
    * a save that would bill more than is left (drafts counted) is refused in words; billing exactly what is left is not; a draft
      re-saved is checked against everything else; another client's order line, a cancelled order, another customer's order and a
      line re-pointed at another item are refused; a line that names no order line is not asked about at all;
    * at ISSUE the draft is asked again, because its customer, its order and what other drafts bill can change without its lines
      being saved (the independent read's F2), and the issue asks it after the draft adds up and before the accounts;
    * the seed offers each line still unbilled at its unbilled quantity, names the order line, converts the rate to basis points, and
      names what it does not carry, each a fact about the records: a challan's undelivered goods only on an order that uses challans,
      a line with no catalogue item, and the discounts, with ONE sentence where the order has a document discount (F3);
    * an order whose lines any invoice names, whatever its state, keeps its lines and nothing is half deleted (F1);
    * both invoice doors check and carry the link, the model reads it as an id, a note's line has no such field, and the seed asks
      the permission an invoice's create asks.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest
from fastapi import HTTPException

from domain.gst import delivery_challan as dc
from services import sales_cycle_service as svc
from tests.test_the_sales_cycle_before_the_tax_invoice import _order_db

API = pathlib.Path(__file__).resolve().parents[1]


def _invoice(db, inv_id, status, lines, *, deleted=False, client="C1"):
    db.store.setdefault("client_sales_invoices", []).append(
        {"id": inv_id, "firm_id": "F1", "client_id": client, "status": status, "deleted_at": "2026-05-01" if deleted else None})
    for i, (order_line, qty) in enumerate(lines):
        db.store.setdefault("client_sales_invoice_lines", []).append(
            {"id": f"{inv_id}-l{i}", "sales_invoice_id": inv_id, "sales_order_line_id": order_line, "quantity": qty,
             "description": "Widget"})


def _line(position, lid):
    return next(ln for ln in position["lines"] if ln["order_line_id"] == lid)


def test_the_position_counts_the_issued_invoices_that_name_the_line_and_nothing_else():
    db = _order_db()
    _invoice(db, "I1", "issued", [("L1", "3.000")])
    _invoice(db, "I2", "paid", [("L1", "1.000"), ("L2", "5.000")])
    _invoice(db, "I3", "draft", [("L1", "2.000")])
    _invoice(db, "I4", "cancelled", [("L1", "4.000")])
    _invoice(db, "I5", "issued", [("L1", "4.000")], deleted=True)
    _invoice(db, "I6", "issued", [(None, "9.000")])                     # same description, no link: not this order's
    position = svc.order_open_position(db, "F1", "O1")
    assert _line(position, "L1")["invoiced_qty"] == "4.000" and _line(position, "L1")["unbilled_qty"] == "6.000"
    assert _line(position, "L2")["invoiced_qty"] == "5.000" and _line(position, "L2")["unbilled_qty"] == "0.000"
    assert position["gaps"] == [svc.INVOICED_QUANTITY_IS_NOT_LINKED]
    assert _line(svc.order_open_position(db, "F1", "O1", with_drafts=True), "L1")["invoiced_qty"] == "6.000"


def test_another_firms_invoice_naming_the_line_bills_nothing_here():
    db = _order_db()
    db.store.setdefault("client_sales_invoices", []).append({"id": "IX", "firm_id": "F2", "client_id": "C9", "status": "issued"})
    db.store.setdefault("client_sales_invoice_lines", []).append(
        {"id": "IX-l0", "sales_invoice_id": "IX", "sales_order_line_id": "L1", "quantity": "7.000"})
    assert _line(svc.order_open_position(db, "F1", "O1"), "L1")["invoiced_qty"] == "0.000"


def test_billing_more_than_is_left_is_refused_and_drafts_count():
    db = _order_db()
    _invoice(db, "I1", "issued", [("L1", "6.000")])
    _invoice(db, "I2", "draft", [("L1", "3.000")])
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [{"sales_order_line_id": "L1", "quantity": 2}])
    assert exc.value.status_code == 422
    assert "more than the 1.000 still unbilled" in exc.value.detail and "already invoiced or on a draft invoice" in exc.value.detail
    svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [{"sales_order_line_id": "L1", "quantity": 1}])   # exactly what is left


def test_two_lines_of_one_invoice_billing_one_order_line_are_added_together():
    db = _order_db()
    with pytest.raises(HTTPException):
        svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [
            {"sales_order_line_id": "L2", "quantity": 3}, {"sales_order_line_id": "L2", "quantity": 3}])


def test_a_draft_resaved_is_checked_against_everything_else():
    db = _order_db()
    _invoice(db, "I1", "draft", [("L1", "10.000")])
    with pytest.raises(HTTPException):
        svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [{"sales_order_line_id": "L1", "quantity": 10}])
    svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [{"sales_order_line_id": "L1", "quantity": 10}],
                                           exclude_invoice_id="I1")


def test_another_clients_order_line_a_cancelled_order_and_another_customers_order_are_refused():
    db = _order_db()
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_lines_against_orders(db, "F1", "C2", "X1", [{"sales_order_line_id": "L1", "quantity": 1}])
    assert "not one of this client's" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_lines_against_orders(db, "F1", "C1", "X9", [{"sales_order_line_id": "L1", "quantity": 1}])
    assert "another customer's" in exc.value.detail
    db.store["sales_orders"][0]["status"] = "cancelled"
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [{"sales_order_line_id": "L1", "quantity": 1}])
    assert "cancelled" in exc.value.detail


def test_a_line_that_names_no_order_line_is_not_asked_about():
    class _NoReads:
        def table(self, name):
            raise AssertionError(f"read {name} for an invoice that bills no order line")
    svc.check_invoice_lines_against_orders(_NoReads(), "F1", "C1", "X1", [{"description": "Fee", "quantity": 1}])


def test_the_seed_offers_what_is_unbilled_and_names_the_order_line_it_bills():
    db = _order_db()
    db.store["sales_order_lines"][0].update({"rate_paise": 5000, "gst_rate_percent": "18.00", "unit": "NOS", "is_service": False,
                                             "service_catalogue_id": "S-W"})
    db.store["sales_order_lines"][1].update({"rate_paise": 900, "gst_rate_percent": "5.00", "is_service": True})
    _invoice(db, "I1", "issued", [("L1", "4.000")])
    _invoice(db, "I2", "draft", [("L2", "5.000")])                     # the whole of L2 is on a draft: nothing left to offer
    answer = svc.invoice_seed_from_order(db, "F1", "O1")
    assert answer["order"] == {"id": "O1", "document_no": "SO/1"}
    [line] = answer["seed"]["lines"]
    assert line == {
        "description": "Widget", "hsn_sac": None, "quantity": "6", "unit": "NOS", "rate_paise": 5000, "gst_rate_bps": 1800,
        "is_service": False, "service_catalogue_id": "S-W", "discount_percent_bps": None, "cess_rate_bps": None,
        "cess_specific_paise_per_unit": None, "sales_order_line_id": "L1"}
    assert answer["seed"]["customer_id"] == "X1" and answer["seed"]["is_interstate"] is False
    assert answer["notes"] == []          # an item, no discount, and no challans on this order: nothing to say


def test_a_line_with_no_catalogue_item_is_named_because_an_invoice_line_needs_one():
    db = _order_db()
    notes = svc.invoice_seed_from_order(db, "F1", "O1")["notes"]
    assert sum("names no product or service" in n for n in notes) == 2
    assert any(n.startswith("Gadget: the order line names no product or service") for n in notes)


def _with_items(db):
    for ln, item in zip(db.store["sales_order_lines"], ("S-W", "S-G"), strict=True):
        ln["service_catalogue_id"] = item
    return db


def test_what_a_challan_has_not_carried_is_said_only_for_an_order_delivered_on_challans():
    db = _with_items(_order_db())
    assert not any("delivery challan" in n for n in svc.invoice_seed_from_order(db, "F1", "O1")["notes"]), (
        "goods that leave under the tax invoice itself have no challan, and a sentence on every line would be noise")
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/1", "document_date": "2026-04-05", "order_id": "O1", "reason": dc.REASON_INVOICE_TO_FOLLOW,
        "lines": [{"description": "Widget", "quantity": 4, "rate_paise": 100, "order_line_id": "L1"}]})
    db.store["delivery_challans"][0]["status"] = "issued"
    _invoice(db, "I1", "issued", [("L1", "4.000")])
    notes = svc.invoice_seed_from_order(db, "F1", "O1")["notes"]
    assert "Widget: 6 of the 6 offered is not yet on an issued delivery challan against this order." in notes
    assert "Gadget: 5 of the 5 offered is not yet on an issued delivery challan against this order." in notes
    assert not any("s.31" in n or "removal" in n for n in notes), "a sentence about the records, not a reading of the Act"


def test_a_document_discount_is_one_sentence_and_no_line_amount_is_offered_beside_it():
    """Each order line's stored discount includes its share of the document's (`compute_lines`), so naming a line's amount beside
    the document sentence would invite the same discount twice (the independent read's F3)."""
    db = _with_items(_order_db())
    priced, _ = svc.compute_lines(
        [{"description": "Widget", "quantity": 10, "rate_paise": 1000, "gst_rate_percent": 18},
         {"description": "Gadget", "quantity": 5, "rate_paise": 2000, "gst_rate_percent": 18, "discount_percent_bps": 500}],
        is_inter_state=False, document_percent_bps=1000)
    for row, p in zip(db.store["sales_order_lines"], priced, strict=True):
        row.update(discount_paise=p["discount_paise"], discount_percent_bps=p["discount_percent_bps"])
    assert db.store["sales_order_lines"][0]["discount_paise"] > 0      # the share of the document discount, on a line with none of its own
    db.store["sales_orders"][0]["discount_percent_bps"] = 1000
    answer = svc.invoice_seed_from_order(db, "F1", "O1")
    assert answer["notes"] == [svc.ORDER_DISCOUNT_NOT_CARRIED]
    assert [ln["discount_percent_bps"] for ln in answer["seed"]["lines"]] == [None, 500]     # a line's own percentage is carried


def test_a_line_amount_discount_with_no_document_discount_is_named():
    db = _with_items(_order_db())
    db.store["sales_order_lines"][0].update(discount_paise=500)
    notes = svc.invoice_seed_from_order(db, "F1", "O1")["notes"]
    assert notes == ["Widget: the order line's discount is an amount for the whole ordered quantity and is not carried; enter it on "
                     "the invoice if it applies to what is billed."]


def test_the_seed_refuses_an_order_with_nothing_left_and_a_cancelled_order():
    db = _order_db()
    _invoice(db, "I1", "issued", [("L1", "10.000"), ("L2", "5.000")])
    with pytest.raises(HTTPException) as exc:
        svc.invoice_seed_from_order(db, "F1", "O1")
    assert exc.value.status_code == 409 and "nothing left to bill" in exc.value.detail
    db = _order_db()
    db.store["sales_orders"][0]["status"] = "cancelled"
    with pytest.raises(HTTPException) as exc:
        svc.invoice_seed_from_order(db, "F1", "O1")
    assert exc.value.status_code == 409


@pytest.mark.parametrize("status,deleted", [("draft", False), ("issued", False), ("cancelled", False), ("draft", True)],
                         ids=["a draft", "an issued invoice", "a cancelled invoice", "a deleted draft"])
def test_an_order_whose_lines_an_invoice_names_keeps_its_lines_whatever_the_invoices_state(status, deleted):
    """A cancelled or deleted invoice's lines still point at the order's lines, and the database refuses their delete (ON DELETE
    RESTRICT): the guard asks what POINTS at the lines, not what is billed, so nothing is half replaced (the independent read's F1)."""
    db = _order_db()
    _invoice(db, "I1", status, [("L2", "1.000")], deleted=deleted)
    with pytest.raises(HTTPException) as exc:
        svc.update_order(db, "F1", "O1", {"lines": [{"description": "Widget", "quantity": 9, "rate_paise": 100, "gst_rate_percent": 18}]})
    assert exc.value.status_code == 409 and exc.value.detail == svc.ORDER_LINES_ARE_BILLED
    assert [ln["id"] for ln in db.store["sales_order_lines"]] == ["L1", "L2"]          # nothing was deleted, the first line included


def test_an_order_no_invoice_names_can_still_be_re_priced():
    db = _order_db()
    _invoice(db, "I1", "issued", [(None, "1.000")])
    svc.update_order(db, "F1", "O1", {"lines": [{"description": "Widget", "quantity": 9, "rate_paise": 100, "gst_rate_percent": 18}]})
    assert [ln["description"] for ln in db.store["sales_order_lines"]] == ["Widget"]


def test_an_invoice_line_naming_another_item_than_the_order_lines_is_refused():
    db = _with_items(_order_db())
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [
            {"sales_order_line_id": "L1", "quantity": 1, "service_catalogue_id": "S-OTHER"}])
    assert "names a different product or service" in exc.value.detail and '"Widget"' in exc.value.detail
    svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [{"sales_order_line_id": "L1", "quantity": 1, "service_catalogue_id": "S-W"}])
    db.store["sales_order_lines"][0]["service_catalogue_id"] = None          # an order line with no item: the item is not asked
    svc.check_invoice_lines_against_orders(db, "F1", "C1", "X1", [
        {"sales_order_line_id": "L1", "quantity": 1, "service_catalogue_id": "S-OTHER"}])


def _draft(db, inv_id, lines, customer="X1"):
    _invoice(db, inv_id, "draft", lines)
    db.store["client_sales_invoices"][-1]["customer_id"] = customer
    return db.store["client_sales_invoices"][-1]


def test_at_issue_the_draft_is_asked_again_what_changed_since_its_lines_were_saved():
    """Three things change a draft's right to bill an order without its lines being saved again (the independent read's F2)."""
    db = _order_db()
    moved = _draft(db, "I1", [("L1", "2.000")], customer="X9")              # a header-only edit changed its customer
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_still_bills_its_orders(db, "F1", moved)
    assert "another customer's" in exc.value.detail

    db = _order_db()
    draft = _draft(db, "I1", [("L1", "2.000")])
    svc.check_invoice_still_bills_its_orders(db, "F1", draft)                 # fine as saved
    db.store["sales_orders"][0]["status"] = "cancelled"                       # the order was cancelled since
    with pytest.raises(HTTPException) as exc:
        svc.check_invoice_still_bills_its_orders(db, "F1", draft)
    assert "cancelled" in exc.value.detail

    db = _order_db()                                                          # two saves at one moment each found the other absent
    first, second = _draft(db, "I1", [("L1", "10.000")]), _draft(db, "I2", [("L1", "10.000")])
    for draft in (first, second):
        with pytest.raises(HTTPException) as exc:
            svc.check_invoice_still_bills_its_orders(db, "F1", draft)
        assert "still unbilled" in exc.value.detail


def test_at_issue_an_invoice_that_bills_no_order_is_asked_nothing_more():
    class _OnlyItsLines:
        def table(self, name):
            assert name == "client_sales_invoice_lines", f"read {name} for an invoice that bills no order"
            return _order_db().table(name)
    svc.check_invoice_still_bills_its_orders(_OnlyItsLines(), "F1", {"id": "I1", "client_id": "C1", "customer_id": "X1"})


def test_the_issue_asks_the_order_rule_after_the_draft_adds_up_and_before_the_accounts():
    from domain.sales import issue_readiness as ir
    body = _function("services/issue_readiness_service.py", "blockers_for_sales_invoice")
    order = [body.index(k) for k in ("ir.DRAFT_DOES_NOT_ADD_UP", "check_invoice_still_bills_its_orders", "missing_accounts_for_sales_invoice")]
    assert order == sorted(order)
    assert ir.ORDER_LINES_NOT_BILLABLE in ir.CODES and ir.ACTION_FOR[ir.ORDER_LINES_NOT_BILLABLE] is None


def test_the_seed_asks_the_permission_the_invoice_it_raises_needs():
    seed = _function("routers/sales_cycle.py", "order_invoice_seed")
    create = _function("routers/sales_invoices.py", "create_invoice")
    assert "rbac('accounting', 'write')" in seed and "rbac('accounting', 'write')" in create


def test_the_quantity_text_has_no_exponent_and_no_trailing_zeros():
    assert svc._quantity_text(Decimal("10.000")) == "10"
    assert svc._quantity_text(Decimal("2.500")) == "2.5"
    assert svc._quantity_text(Decimal("1E+1")) == "10"


def _function(rel: str, name: str) -> str:
    tree = ast.parse((API / rel).read_text())
    return ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name))


def test_both_invoice_doors_check_the_lines_and_carry_the_link():
    """Both doors ask the one line check, which asks the order cycle's rule when a line names an order line."""
    create = _function("routers/sales_invoices.py", "_create_invoice_core")
    assert "customer_id=data.get('customer_id')" in create and "assert_items_are_the_clients(" in create
    assert create.count("'sales_order_line_id'") >= 2, "the create door builds the line and its payload with the link"
    edit = _function("routers/sales_invoices.py", "update_invoice")
    assert "assert_items_are_the_clients(" in edit and "exclude_invoice_id=invoice_id" in edit
    assert "'sales_order_line_id': ln.get('sales_order_line_id')" in edit
    shared = _function("services/line_item_ownership.py", "assert_items_are_the_clients")
    assert "sales_cycle_service.check_invoice_lines_against_orders(" in shared


def test_the_shared_line_check_asks_the_order_rule_only_when_a_line_names_an_order_line():
    from services.line_item_ownership import assert_items_are_the_clients
    db = _order_db()
    _invoice(db, "I1", "issued", [("L1", "10.000")])
    assert_items_are_the_clients(db, "F1", "C1", [{"description": "Fee", "quantity": 99}], customer_id="X1")
    with pytest.raises(HTTPException) as exc:
        assert_items_are_the_clients(db, "F1", "C1", [{"description": "W", "quantity": 1, "sales_order_line_id": "L1"}],
                                     customer_id="X1")
    assert "still unbilled" in exc.value.detail


def test_the_model_reads_the_link_as_an_id_and_a_notes_line_has_none():
    from models.invoices import InvoiceLineIn, SalesInvoiceLineIn
    base = {"description": "W", "quantity": 1, "rate_paise": 100, "service_catalogue_id": "s1"}
    assert SalesInvoiceLineIn(**base, sales_order_line_id=" 0f0e0d0c-0b0a-0908-0706-050403020100 ").sales_order_line_id == \
        "0f0e0d0c-0b0a-0908-0706-050403020100"
    assert SalesInvoiceLineIn(**base, sales_order_line_id="").sales_order_line_id is None
    with pytest.raises(ValueError):
        SalesInvoiceLineIn(**base, sales_order_line_id="L1")
    assert "sales_order_line_id" not in InvoiceLineIn.model_fields       # a credit or debit note bills no order line
