"""The date on an invoice, a bill, a receipt, a vendor payment and the four notes is judged before anything reads it (POST-A-380, the documents' slice).

WHAT WAS WRONG
    Twenty request-model fields that carry the date of a document the books are made from were a bare `str` or `Optional[str]` with no validator: the
    date of a sales invoice, a purchase bill, a receipt, a vendor payment, a credit note, a debit note, a purchase credit note, a sales debit note, a
    reversal and an e-invoice, with the due dates and the edit models beside them. Each of those dates reaches the period check, `fy_code` (which numbers the
    document in a financial year) and a DATE column. A caller that is not the screen (a script, an import, a hand-made request) that sent "" or
    "2026-02-30" got a 500 with no sentence (the vendor payment's blank date raised in the period check before the route's own `try`), and a text with
    something after the day was numbered by its first ten characters. The screens already ask for the date in words; this is the same refusal for every other caller.

WHAT IS HELD
    One type per way a date is asked (`models/iso_date`: `IsoDate` must be there, `OptionalIsoDate` a new document may leave out, `PatchIsoDate` an edit may
    leave out), the field is annotated with the right one, and the behaviour of each is what its comment says: a real day is kept in its canonical form,
    anything else is a 422 naming the field, a number is not a date, and an edit that SENDS a blank is refused because the route would drop a blank as "nothing to change".
    The rule over the whole API (a new bare date field fails) is `test_a_date_field_on_a_request_model_is_a_real_date_or_is_on_the_frozen_list.py`.
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

# (module, class, field, kind): all twenty, so a field dropped from the type or given the wrong one fails here by name.
FIELDS = [
    ("models.invoices", "SalesInvoiceIn", "invoice_date", REQUIRED),
    ("models.invoices", "SalesInvoiceIn", "due_date", OPTIONAL),
    ("models.invoices", "SalesInvoiceUpdateIn", "invoice_date", PATCH),
    ("models.invoices", "SalesInvoiceUpdateIn", "due_date", PATCH),
    ("models.invoices", "PurchaseBillIn", "bill_date", REQUIRED),
    ("models.invoices", "PurchaseBillIn", "due_date", OPTIONAL),
    ("models.invoices", "PurchaseBillUpdateIn", "bill_date", PATCH),
    ("models.invoices", "PurchaseBillUpdateIn", "due_date", PATCH),
    ("models.invoices", "ReceiptIn", "receipt_date", REQUIRED),
    ("models.invoices", "PurchasePaymentIn", "payment_date", REQUIRED),
    ("routers.credit_notes", "CreditNoteIn", "credit_note_date", REQUIRED),
    ("routers.credit_notes", "CreditNoteUpdateIn", "credit_note_date", PATCH),
    ("routers.debit_notes", "DebitNoteIn", "debit_note_date", REQUIRED),
    ("routers.debit_notes", "DebitNoteUpdateIn", "debit_note_date", PATCH),
    ("routers.purchase_credit_notes", "PurchaseCreditNoteIn", "credit_note_date", REQUIRED),
    ("routers.purchase_credit_notes", "PurchaseCreditNoteUpdateIn", "credit_note_date", PATCH),
    ("routers.sales_debit_notes", "SalesDebitNoteIn", "debit_note_date", REQUIRED),
    ("routers.sales_debit_notes", "SalesDebitNoteUpdateIn", "debit_note_date", PATCH),
    ("models.accounting", "JournalReversalIn", "reversal_date", REQUIRED),
    ("routers.einvoice", "CreateEInvoiceRequest", "invoice_date", REQUIRED),
]
IDS = [f"{c}.{f}" for _, c, f, _ in FIELDS]
BAD = ["30/09/2026", "2026-02-30", "2026-9-1x", "soon", "2026-07-01T10:00:00", "2026-07-01 10:00", "２０２６-07-01", "+2026-07-01"]


def _model(module: str, cls: str):
    return getattr(importlib.import_module(module), cls)


def _validators(model, field):
    return [m for m in model.model_fields[field].metadata if isinstance(m, BeforeValidator)]


def _run(kind: str, value, field: str):
    return FUNC[kind](value, SimpleNamespace(field_name=field))


def test_the_table_is_all_twenty_and_each_kind_is_used():
    assert len(FIELDS) == 20 and len(set(FIELDS)) == 20
    assert {k for *_, k in FIELDS} == {REQUIRED, OPTIONAL, PATCH}


@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_the_field_carries_the_type_for_the_way_it_is_asked(module, cls, field, kind):
    found = _validators(_model(module, cls), field)
    assert [v.func for v in found] == [FUNC[kind]], f"{cls}.{field} is not judged as a {kind} date"


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_a_text_that_is_not_a_day_is_refused_naming_the_field(module, cls, field, kind, bad):
    with pytest.raises(ValueError, match=f"{field} must be a date written YYYY-MM-DD."):
        _run(kind, bad, field)


@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_a_number_is_not_a_date_and_a_real_day_is_kept_in_its_canonical_form(module, cls, field, kind):
    with pytest.raises(ValueError, match=f"{field} must be a date written YYYY-MM-DD."):
        _run(kind, 20260701, field)
    assert _run(kind, " 2026-07-01 ", field) == "2026-07-01"
    assert _run(kind, "2026-07-01\n", field) == "2026-07-01"        # surrounding whitespace is trimmed, as a padded box is
    assert _run(kind, "20260701", field) == "2026-07-01"          # the compact form `date.fromisoformat` reads is stored as the day, not as that text


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("module,cls,field,kind", FIELDS, ids=IDS)
def test_a_blank_means_what_its_kind_says(module, cls, field, kind, blank):
    if kind == OPTIONAL:
        assert _run(kind, blank, field) is None           # a new document may leave the date out; the credit terms or the probe fill it
    else:
        with pytest.raises(ValueError, match=f"{field} must be a date written YYYY-MM-DD."):
            _run(kind, blank, field)
    if kind == PATCH:
        with pytest.raises(ValueError, match="leave it out to keep it as it is"):
            _run(kind, blank, field)


@pytest.mark.parametrize("kind", [OPTIONAL, PATCH])
def test_not_sent_is_none_for_a_date_that_may_be_left_out(kind):
    assert _run(kind, None, "due_date") is None


def test_a_required_date_that_is_none_is_refused():
    with pytest.raises(ValueError, match="invoice_date must be a date written YYYY-MM-DD."):
        _run(REQUIRED, None, "invoice_date")


# ── the real models, built the way the routes build them ───────────────────────────────────────────

def test_a_receipt_and_a_vendor_payment_refuse_a_date_that_is_not_one_and_keep_one_that_is():
    from models.invoices import PurchasePaymentIn, ReceiptIn
    for model, field, extra in ((ReceiptIn, "receipt_date", dict(customer_id="c1", amount_paise=100)),
                                (PurchasePaymentIn, "payment_date", dict(vendor_id="v1", amount_paise=100))):
        for bad in ["", "2026-02-30", "soon"]:
            with pytest.raises(ValidationError) as caught:
                model(client_id="cl1", **{field: bad}, **extra)
            assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)
        assert getattr(model(client_id="cl1", **{field: " 2026-07-01 "}, **extra), field) == "2026-07-01"


def test_an_edit_that_leaves_a_date_out_leaves_it_alone_and_one_that_sends_a_blank_is_refused():
    from models.invoices import PurchaseBillUpdateIn, SalesInvoiceUpdateIn
    for model, field in ((SalesInvoiceUpdateIn, "due_date"), (PurchaseBillUpdateIn, "due_date")):
        assert getattr(model(), field) is None
        assert field not in model(notes="x").model_dump(exclude_unset=True)
        assert getattr(model(**{field: "2026-07-31"}), field) == "2026-07-31"
        for bad in ["", "   ", "2026-02-30"]:
            with pytest.raises(ValidationError) as caught:
                model(**{field: bad})
            assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_new_document_that_leaves_the_due_date_blank_has_none_so_the_credit_terms_fill_it():
    from models.invoices import PurchaseBillIn, SalesInvoiceIn
    for model, field in ((SalesInvoiceIn, "due_date"), (PurchaseBillIn, "due_date")):
        assert getattr(model.model_construct(), field, None) is None
        assert model.model_fields[field].default is None


def test_the_near_duplicate_probe_stays_tolerant_because_it_is_advisory_and_never_refuses():
    from routers.purchase_bills import NearDuplicateProbeIn
    # A read-only probe: an unreadable date still gives advice by number and amount (domain/purchases/near_duplicate._as_date reads it as none).
    for bad in ["", "soon", "2026-02-30", "2026-07-01T10:00:00"]:
        assert NearDuplicateProbeIn(client_id="c", vendor_id="v", bill_date=bad).bill_date == bad


# ── over HTTP: a 422 with the sentence at the door, not a 500 from the period check or the database ──────

@pytest.fixture
def client():
    from routers.credit_notes import router as credit_notes
    from routers.purchase_payments import router as purchase_payments
    from routers.receipts import router as receipts
    app = FastAPI()
    for r in (purchase_payments, receipts, credit_notes):
        app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path,field", [("/api/purchase-payments", "payment_date"), ("/api/receipts/", "receipt_date"), ("/api/credit-notes/", "credit_note_date")])
@pytest.mark.parametrize("bad", ["", "2026-02-30", "soon", "2026-07-01T10:00:00", 20260701])
def test_the_posting_doors_answer_422_with_the_sentence_for_a_date_that_is_not_one(client, path, field, bad):
    r = client.post(path, json={field: bad})
    assert r.status_code == 422, r.text
    assert f"{field} must be a date written YYYY-MM-DD." in r.text


# ── a date inside a body the model does not type: a document reading (POST-A-380) ─────────────────────

@pytest.fixture
def bills_client():
    from routers.purchase_bills import router as purchase_bills
    app = FastAPI()
    app.include_router(purchase_bills)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("bad", ["soon", "2026-02-30", "2026-07-01T10:00:00", 20260701])
def test_a_reading_with_a_date_that_is_not_a_day_is_a_422_and_not_a_bill_dated_that(bills_client, bad):
    r = bills_client.post("/api/purchase-bills/from-document", json={"client_id": "c1", "extracted_data": {"invoice_no": "A/1", "invoice_date": bad}})
    assert r.status_code == 422, r.text
    assert "invoice_date must be a date written YYYY-MM-DD." in r.text


def test_a_reading_with_a_real_date_gets_past_the_date_and_stops_at_the_next_thing_it_lacks(bills_client):
    r = bills_client.post("/api/purchase-bills/from-document", json={"client_id": "c1", "extracted_data": {"invoice_no": "A/1", "invoice_date": " 2026-07-01 "}})
    assert "invoice_date must be a date" not in r.text          # whatever it stops at (a vendor, the lines), it is not the date


# ── a bulk import's row error is a sentence, without the library's label ─────────────────────────────

def test_the_first_refusal_of_a_model_is_a_sentence_without_pydantics_label():
    from core.exceptions import validation_sentence
    from models.invoices import ReceiptIn
    with pytest.raises(ValidationError) as caught:
        ReceiptIn(client_id="c", customer_id="x", amount_paise=1, receipt_date="2026-02-30")
    assert validation_sentence(caught.value, "Invalid.") == "receipt_date must be a date written YYYY-MM-DD."
    assert validation_sentence(ValueError("not a validation error"), "Invalid.") == "Invalid."
