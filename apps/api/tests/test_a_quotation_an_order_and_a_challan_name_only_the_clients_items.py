"""A quotation, a sales order, a delivery challan, a purchase order and a goods receipt may only name a product or service of
their own client (POST-A-441).

THE GAP
    Every invoice, bill and note door asks `services/line_item_ownership.assert_items_are_the_clients` before it writes a line
    (POST-A-246), because a line naming a sibling client's item (or another firm's) looks the item up under the wrong client and
    moves nothing. The three documents before the tax invoice took `service_catalogue_id` on each line and wrote it as sent. The
    screen offers only the client's own items and an invoice raised from such an order is refused at its own door, so the reach was
    a hand-made request; since the order form gained its product picker (POST-A-104) an item on these lines is ordinary input.

WHAT IS HELD
    * the eight doors that write these lines ask the same function before anything is written: the quotation, sales order and
      challan creates, the quotation and sales order edits that replace their lines, and, found by the independent review of
      16-11-2026, the purchase order and goods receipt creates and the purchase order edit (a challan's edit corrects a draft
      line's words and HSN code only, and refuses an item);
    * an edit that also changes the number refuses a number already taken BEFORE it replaces the lines, so a refused edit leaves the
      document as it was and never a header whose totals are no longer its lines';
    * a sibling client's item and another firm's are refused with a 422 that names the line by its position, and NOTHING is written,
      neither the header nor a line;
    * the client's own item passes and is stored on the line, and a line that names no item asks nothing;
    * only the item is handed on: a stray `sales_order_line_id` on one of these lines does not reach the order-billing rule, which
      is about an INVOICE's lines.
"""
from __future__ import annotations

import copy

import pytest
from fastapi import HTTPException

from domain.gst import delivery_challan as dc
from services import purchase_cycle_service as pcs
from services import sales_cycle_service as svc
from tests.test_the_sales_cycle_before_the_tax_invoice import _order_db

MINE = "11111111-1111-4111-8111-111111111111"
SIBLINGS = "33333333-3333-4333-8333-333333333333"
STRANGERS = "44444444-4444-4444-8444-444444444444"
REFUSED = "names a product or service that is not in this client's catalogue"


def _db():
    db = _order_db()
    db.store["service_catalogue"] = [
        {"id": MINE, "firm_id": "F1", "client_id": "C1"},
        {"id": SIBLINGS, "firm_id": "F1", "client_id": "C2"},
        {"id": STRANGERS, "firm_id": "F2", "client_id": "C9"},
    ]
    db.store["sales_quotations"] = [{
        "id": "Q1", "firm_id": "F1", "client_id": "C1", "customer_id": "X1", "kind": "quotation",
        "document_no": "QT/1", "document_date": "2026-04-01", "status": "draft", "is_inter_state": False,
    }]
    db.store["sales_quotation_lines"] = [{
        "id": "QL1", "firm_id": "F1", "client_id": "C1", "quotation_id": "Q1", "line_order": 0,
        "description": "Widget", "quantity": "1.000", "rate_paise": 100000, "gst_rate_percent": 18,
    }]
    db.store["vendors"] = [{"id": "V1", "firm_id": "F1", "client_id": "C1"}]
    db.store["purchase_orders"] = [{
        "id": "PO1", "firm_id": "F1", "client_id": "C1", "vendor_id": "V1", "document_no": "PO/1",
        "document_date": "2026-04-01", "status": "open", "is_inter_state": False,
    }]
    db.store["purchase_order_lines"] = [{
        "id": "POL1", "firm_id": "F1", "client_id": "C1", "order_id": "PO1", "line_order": 0,
        "description": "Widget", "quantity": "1.000", "rate_paise": 100000, "gst_rate_percent": 18,
    }]
    return db


def _lines(*items):
    return [{"description": f"Line {n}", "quantity": 1, "rate_paise": 100000, "gst_rate_percent": 18,
             **({"service_catalogue_id": item} if item else {})}
            for n, item in enumerate(items, 1)]


def _quotation(items):
    return {"client_id": "C1", "customer_id": "X1", "kind": "quotation", "document_no": "QT/9",
            "document_date": "2026-04-05", "is_inter_state": False, "lines": _lines(*items)}


def _order(items):
    return {"client_id": "C1", "customer_id": "X1", "document_no": "SO/9", "document_date": "2026-04-05",
            "is_inter_state": False, "lines": _lines(*items)}


def _challan(items):
    return {"client_id": "C1", "document_no": "DC/9", "document_date": "2026-04-05",
            "reason": dc.REASON_INVOICE_TO_FOLLOW, "is_inter_state": False, "lines": _lines(*items)}


def _purchase_order(items):
    return {"client_id": "C1", "vendor_id": "V1", "document_no": "PO/9", "document_date": "2026-04-05",
            "is_inter_state": False, "lines": _lines(*items)}


def _receipt(items):
    return {"client_id": "C1", "vendor_id": "V1", "document_no": "GRN/9", "received_on": "2026-04-05", "lines": _lines(*items)}


DOORS = {
    "create a quotation": lambda db, items: svc.create_quotation(db, "F1", _quotation(items)),
    "create an order": lambda db, items: svc.create_order(db, "F1", _order(items)),
    "create a challan": lambda db, items: svc.create_challan(db, "F1", _challan(items)),
    "replace a quotation's lines": lambda db, items: svc.update_quotation(db, "F1", "Q1", {"lines": _lines(*items)}),
    "replace an order's lines": lambda db, items: svc.update_order(db, "F1", "O1", {"lines": _lines(*items)}),
    "create a purchase order": lambda db, items: pcs.create_order(db, "F1", _purchase_order(items)),
    "create a goods receipt": lambda db, items: pcs.create_receipt(db, "F1", _receipt(items)),
    "replace a purchase order's lines": lambda db, items: pcs.update_order(db, "F1", "PO1", {"lines": _lines(*items)}),
}


@pytest.mark.parametrize("door", list(DOORS))
@pytest.mark.parametrize("foreign", [SIBLINGS, STRANGERS], ids=["a sibling client's item", "another firm's item"])
def test_a_line_naming_an_item_that_is_not_the_clients_is_refused_and_nothing_is_written(door, foreign):
    db = _db()
    before = copy.deepcopy(db.store)
    with pytest.raises(HTTPException) as e:
        DOORS[door](db, [MINE, foreign])
    assert e.value.status_code == 422
    assert e.value.detail.startswith("Line 2 ") and REFUSED in e.value.detail, e.value.detail
    assert db.store == before, f"{door} wrote something before refusing"


@pytest.mark.parametrize("door", list(DOORS))
def test_the_clients_own_item_passes_and_is_kept_on_the_line(door):
    db = _db()
    DOORS[door](db, [MINE, None])
    table = {"create a quotation": "sales_quotation_lines", "replace a quotation's lines": "sales_quotation_lines",
             "create an order": "sales_order_lines", "replace an order's lines": "sales_order_lines",
             "create a challan": "delivery_challan_lines", "create a purchase order": "purchase_order_lines",
             "replace a purchase order's lines": "purchase_order_lines", "create a goods receipt": "goods_receipt_lines"}[door]
    written = [ln for ln in db.store[table] if ln.get("description") in ("Line 1", "Line 2")]
    assert [ln.get("service_catalogue_id") for ln in written] == [MINE, None]


def test_every_refused_line_is_named_not_only_the_first():
    db = _db()
    with pytest.raises(HTTPException) as e:
        DOORS["create an order"](db, [SIBLINGS, MINE, STRANGERS])
    assert e.value.detail.startswith("Lines 1, 3 name ")


def test_a_stray_invoice_field_on_these_lines_does_not_reach_the_order_billing_rule(monkeypatch):
    """`assert_items_are_the_clients` also asks an INVOICE line's `sales_order_line_id` against the order it bills. A quotation's
    line bills nothing, so only its item is handed on, and a field that does not belong here cannot start that read."""
    called = []
    monkeypatch.setattr(svc, "check_invoice_lines_against_orders", lambda *a, **k: called.append(a))
    db = _db()
    payload = _quotation([MINE])
    payload["lines"][0]["sales_order_line_id"] = "L1"
    svc.create_quotation(db, "F1", payload)
    assert called == []


LINE_TABLES = ("sales_quotation_lines", "sales_order_lines", "delivery_challan_lines", "purchase_order_lines", "goods_receipt_lines")


def _calls(fn, name_test) -> list:
    """The call nodes in `fn` whose callee's name passes `name_test` (a plain name or the last part of an attribute)."""
    import ast
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name_test(name, n):
                out.append(n)
    return out


def _writes_lines(call) -> bool:
    """`db.table("<a line table>").insert(...)`, the challan's database functions, or the quotation's own line writer."""
    import ast
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr == "insert" and isinstance(f.value, ast.Call):
        inner = f.value
        if isinstance(inner.func, ast.Attribute) and inner.func.attr == "table" and inner.args and \
                isinstance(inner.args[0], ast.Constant) and inner.args[0].value in LINE_TABLES:
            return True
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "challan_writes" and \
            f.attr in ("create", "correct_draft"):
        return True
    return isinstance(f, ast.Name) and f.id == "_write_quotation_lines"


def test_every_function_that_writes_these_lines_asks_first_or_is_named_here():
    """The rule, read off both services with the parser: a function that writes these lines (directly, through the challan's
    database functions, or through the quotation's own line writer) is a door that asks `items_are_the_clients` BEFORE its
    first write, or it is one of the two named here for their reason. A new writer (a "duplicate" or "revise" of a document,
    say) fails until it asks."""
    import ast
    import inspect
    named = {
        "_write_quotation_lines": "the quotation's line writer: its two callers ask before calling it",
        "_write_an_amendment": "the challan's draft-line correction, which takes the words and HSN code only (held below)",
    }
    unasked = []
    for module in (svc, pcs):
        for fn in [n for n in ast.walk(ast.parse(inspect.getsource(module))) if isinstance(n, ast.FunctionDef)]:
            writes = _calls(fn, lambda name, call: _writes_lines(call))
            if not writes or fn.name in named:
                continue
            asks = _calls(fn, lambda name, call: name == "items_are_the_clients")
            first_write = min(c.lineno for c in writes)
            if not any(a.lineno < first_write for a in asks):
                unasked.append(f"{module.__name__}.{fn.name}")
    assert unasked == [], "these write document lines without asking that each line's item is the client's first"


def test_a_challans_edit_cannot_name_an_item_at_all():
    """The sixth writer, the correction of a draft challan's lines, takes the words and the HSN code only, so an item never reaches
    it: a correction that names one is refused in the challan rule's own sentence."""
    assert "service_catalogue_id" not in dc.DRAFT_LINE_FIELDS
    problem = dc.draft_line_corrections_problem("DC/1", dc.STATUS_DRAFT, [{"id": "CL1", "service_catalogue_id": SIBLINGS}], ["CL1"])
    assert problem and "service_catalogue_id" in problem


@pytest.mark.parametrize("door, table, number", [
    ("quotation", "sales_quotation_lines", "QT/TAKEN"),
    ("order", "sales_order_lines", "SO/TAKEN"),
    ("purchase order", "purchase_order_lines", "PO/TAKEN"),
])
def test_an_edit_that_takes_a_used_number_is_refused_before_its_lines_are_replaced(door, table, number):
    db = _db()
    db.store["sales_quotations"].append({"id": "Q2", "firm_id": "F1", "client_id": "C1", "kind": "quotation",
                                         "document_no": "QT/TAKEN", "status": "draft"})
    db.store["sales_orders"].append({"id": "O2", "firm_id": "F1", "client_id": "C1", "document_no": "SO/TAKEN",
                                     "status": "confirmed"})
    db.store["purchase_orders"].append({"id": "PO2", "firm_id": "F1", "client_id": "C1", "document_no": "PO/TAKEN",
                                        "status": "open"})
    before = copy.deepcopy(db.store[table])
    patch = {"document_no": number, "lines": _lines(MINE)}
    edit = {"quotation": lambda: svc.update_quotation(db, "F1", "Q1", patch),
            "order": lambda: svc.update_order(db, "F1", "O1", patch),
            "purchase order": lambda: pcs.update_order(db, "F1", "PO1", patch)}[door]
    with pytest.raises(HTTPException) as e:
        edit()
    assert e.value.status_code == 409
    assert db.store[table] == before, f"the {door}'s lines were replaced by an edit that was then refused"
