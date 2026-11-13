"""The dates on a quotation, a sales order, a purchase order and a goods receipt are judged before anything reads them (POST-A-380, the second slice).

WHAT WAS WRONG
    Twenty-one request-model fields on the documents that come BEFORE the tax invoice and the bill were a bare `str` or `Optional[str]` with no validator: a quotation's date and its
    validity, a sales order's date, the customer's order date and the expected delivery, a purchase order's date and expected date, and a goods receipt's date, its two objection dates
    and the supplier's challan date. They go straight into DATE columns (an empty or impossible date was a 500 from the database with no sentence, for a script, an import or a
    hand-made request), and the goods receipt's objection dates are compared as TEXT by the model's own check and by the service that finds the latest removal, so a date that was
    not in its canonical form compared wrongly.

WHAT IS HELD
    The same three types the first slice made (`models/iso_date`): `IsoDate` where the date must be there, `OptionalIsoDate` where a NEW document may leave it out (a blank is no date, as
    the screens already send it), `PatchIsoDate` where an EDIT may leave it out (absent keeps the stored one: both services drop a `None`, and a blank is REFUSED because it would
    reach a DATE column). Whether a day may be in the future or in a period is not judged here. The rule over the whole API is
    `test_a_date_field_on_a_request_model_is_a_real_date_or_is_on_the_frozen_list.py`.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BeforeValidator, ValidationError

import models.iso_date as iso
from core.auth import get_current_user

REQUIRED, OPTIONAL, PATCH = "required", "optional", "patch"
FUNC = {REQUIRED: iso._required_day, OPTIONAL: iso._optional_day, PATCH: iso._patch_day}

FIELDS = [
    ("models.sales_cycle", "QuotationIn", "document_date", REQUIRED),
    ("models.sales_cycle", "QuotationIn", "valid_until", OPTIONAL),
    ("models.sales_cycle", "QuotationUpdateIn", "document_date", PATCH),
    ("models.sales_cycle", "QuotationUpdateIn", "valid_until", PATCH),
    ("models.sales_cycle", "SalesOrderIn", "document_date", REQUIRED),
    ("models.sales_cycle", "SalesOrderIn", "customer_po_date", OPTIONAL),
    ("models.sales_cycle", "SalesOrderIn", "expected_delivery_date", OPTIONAL),
    ("models.sales_cycle", "SalesOrderUpdateIn", "document_date", PATCH),
    ("models.sales_cycle", "SalesOrderUpdateIn", "customer_po_date", PATCH),
    ("models.sales_cycle", "SalesOrderUpdateIn", "expected_delivery_date", PATCH),
    ("models.purchase_cycle", "PurchaseOrderIn", "document_date", REQUIRED),
    ("models.purchase_cycle", "PurchaseOrderIn", "expected_date", OPTIONAL),
    ("models.purchase_cycle", "PurchaseOrderUpdateIn", "document_date", PATCH),
    ("models.purchase_cycle", "PurchaseOrderUpdateIn", "expected_date", PATCH),
    ("models.purchase_cycle", "GoodsReceiptIn", "received_on", REQUIRED),
    ("models.purchase_cycle", "GoodsReceiptIn", "objection_raised_on", OPTIONAL),
    ("models.purchase_cycle", "GoodsReceiptIn", "objection_removed_on", OPTIONAL),
    ("models.purchase_cycle", "GoodsReceiptIn", "vendor_challan_date", OPTIONAL),
    ("models.purchase_cycle", "GoodsReceiptUpdateIn", "received_on", PATCH),
    ("models.purchase_cycle", "GoodsReceiptUpdateIn", "objection_raised_on", PATCH),
    ("models.purchase_cycle", "GoodsReceiptUpdateIn", "objection_removed_on", PATCH),
    ("models.purchase_cycle", "GoodsReceiptUpdateIn", "vendor_challan_date", PATCH),
]
IDS = [f"{c}.{f}" for _, c, f, _ in FIELDS]
BAD = ["30/09/2026", "2026-02-30", "2026-9-1x", "soon", "2026-07-01T10:00:00", "２０２６-07-01", "+2026-07-01"]


def _model(module: str, cls: str):
    return getattr(importlib.import_module(module), cls)


def _run(kind: str, value, field: str):
    return FUNC[kind](value, SimpleNamespace(field_name=field))


def test_the_table_is_every_field_and_each_kind_is_used():
    assert len(FIELDS) == 22 and len(set(FIELDS)) == 22
    assert {k for *_, k in FIELDS} == {REQUIRED, OPTIONAL, PATCH}


@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_the_field_carries_the_type_for_the_way_it_is_asked(module, cls, field, kind):
    found = [m for m in _model(module, cls).model_fields[field].metadata if isinstance(m, BeforeValidator)]
    assert [v.func for v in found] == [FUNC[kind]], f"{cls}.{field} is not judged as a {kind} date"


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_a_text_that_is_not_a_day_is_refused_naming_the_field(module, cls, field, kind, bad):
    with pytest.raises(ValueError, match=f"{field} must be a date written YYYY-MM-DD."):
        _run(kind, bad, field)


@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_a_number_is_refused_and_a_real_day_is_kept_in_its_canonical_form(module, cls, field, kind):
    with pytest.raises(ValueError, match=f"{field} must be a date written YYYY-MM-DD."):
        _run(kind, 20260701, field)
    assert _run(kind, " 2026-07-01 ", field) == "2026-07-01"


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_a_blank_means_what_its_kind_says(module, cls, field, kind, blank):
    if kind == OPTIONAL:
        assert _run(kind, blank, field) is None
    else:
        with pytest.raises(ValueError, match=f"{field} must be a date written YYYY-MM-DD."):
            _run(kind, blank, field)


# ── the real models, as the routes and screens build them ─────────────────────────────────────────────

LINE = [{"description": "Castings"}]          # every model needs a line; the description is the only required part of one


def test_a_new_order_or_receipt_that_leaves_its_optional_dates_blank_stores_none_as_the_screens_send():
    from models.purchase_cycle import GoodsReceiptIn, PurchaseOrderIn
    from models.sales_cycle import QuotationIn, SalesOrderIn
    quote = QuotationIn(client_id="c", customer_id="x", document_no="Q/1", document_date="2026-07-01", valid_until="", lines=LINE)
    assert quote.valid_until is None
    order = SalesOrderIn(client_id="c", customer_id="x", document_no="SO/1", document_date="2026-07-01", customer_po_date="", expected_delivery_date=None, lines=LINE)
    assert order.customer_po_date is None and order.expected_delivery_date is None
    po = PurchaseOrderIn(client_id="c", vendor_id="v", document_no="PO/1", document_date="2026-07-01", expected_date="", lines=LINE)
    assert po.expected_date is None
    receipt = GoodsReceiptIn(client_id="c", vendor_id="v", document_no="GRN/1", received_on="2026-07-01", objection_raised_on="", objection_removed_on="", vendor_challan_date="", lines=LINE)
    assert (receipt.objection_raised_on, receipt.objection_removed_on, receipt.vendor_challan_date) == (None, None, None)


def test_an_edit_that_leaves_a_date_out_keeps_it_and_one_that_sends_a_blank_is_refused():
    from models.purchase_cycle import GoodsReceiptUpdateIn
    from models.sales_cycle import QuotationUpdateIn
    for model, field in ((QuotationUpdateIn, "valid_until"), (GoodsReceiptUpdateIn, "objection_removed_on")):
        assert getattr(model(), field) is None
        assert field not in model().model_dump(exclude_unset=True)
        assert getattr(model(**{field: "2026-07-31"}), field) == "2026-07-31"
        with pytest.raises(ValidationError) as caught:
            model(**{field: ""})
        assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


def test_the_objection_dates_are_compared_as_days_because_they_are_stored_as_days():
    from models.purchase_cycle import GoodsReceiptIn
    with pytest.raises(ValidationError):
        GoodsReceiptIn(client_id="c", vendor_id="v", document_no="GRN/2", received_on="2026-07-01", objection_raised_on="20260710", objection_removed_on="2026-07-05", lines=LINE)
    ok = GoodsReceiptIn(client_id="c", vendor_id="v", document_no="GRN/3", received_on="2026-07-01", objection_raised_on="20260705", objection_removed_on="2026-07-10", lines=LINE)
    assert ok.objection_raised_on == "2026-07-05"          # the compact form is stored as the day, so the text comparison below it compares days


# ── over HTTP: a 422 with the sentence at the door, not a 500 from the database ──────────────────────────

@pytest.fixture
def client():
    from routers.purchase_cycle import router as purchase_cycle
    from routers.sales_cycle import router as sales_cycle
    app = FastAPI()
    for r in (sales_cycle, purchase_cycle):
        app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path,field", [("/api/sales-cycle/quotations", "document_date"), ("/api/sales-cycle/orders", "document_date"),
                                        ("/api/purchase-cycle/orders", "document_date"), ("/api/purchase-cycle/receipts", "received_on")])
@pytest.mark.parametrize("bad", ["", "2026-02-30", "soon", "2026-07-01T10:00:00", 20260701])
def test_the_creating_doors_answer_422_with_the_sentence_for_a_date_that_is_not_one(client, path, field, bad):
    r = client.post(path, json={field: bad})
    assert r.status_code == 422, r.text
    assert f"{field} must be a date written YYYY-MM-DD." in r.text


@pytest.mark.parametrize("path,field", [("/api/sales-cycle/quotations/q1", "valid_until"), ("/api/sales-cycle/orders/o1", "expected_delivery_date"),
                                        ("/api/purchase-cycle/orders/o1", "expected_date"), ("/api/purchase-cycle/receipts/r1", "objection_removed_on")])
@pytest.mark.parametrize("bad", ["", "2026-02-30", "soon"])
def test_the_editing_doors_answer_422_and_never_a_500_for_a_blank_or_a_bad_date(client, path, field, bad):
    r = client.patch(path, json={field: bad})
    assert r.status_code == 422, r.text
    assert f"{field} must be a date written YYYY-MM-DD." in r.text
