"""An emptied soft box on an edit clears the stored value, and the screen no longer says "saved" while the old one stays (POST-A-399, first slice).

WHAT WAS WRONG
    The edit routes read their body with `model_dump(exclude_none=True)`, so "the person did not touch this box" and "the person emptied it" both
    arrived as no value, and the edit screens sent `value.trim() || undefined`, which drops the key from the JSON altogether. A CA who emptied the note or
    the reference of an invoice and pressed Save was told it was saved, and the old value was there when the invoice was opened again.

WHAT THIS HOLDS (the invoice, the purchase bill and the four notes)
    * `models.clearable.patch_dict` is `model_dump(exclude_none=True)` plus each CLEARABLE field the request SENT as null (or, for text, blank), as
      None: a field that was not sent is absent, and a null for a field that is not CLEARABLE is absent too;
    * the sales invoice's reference and note, the purchase bill's own reference and note, and each note's `notes` are cleared by a null, on a draft
      and on an issued document, and the stored row reads back NULL;
    * the due date and the credit days are NOT clearable: every invoice and bill made here carries a due date (a create that names none resolves one),
      so a null for either is "not sent" and the SCREEN refuses to empty a due date that is on file;
    * the evidence of a document is NOT clearable: the bill number, the attached copy of the supplier's invoice, a sales invoice's customer, and the
      other locked particulars still read null as "not sent", and an issued document is not refused for a null it did not mean;
    * a note typed on a NEW sales credit note or sales debit note is stored (the create models had no such field and the box was dropped);
    * every name in a model's CLEARABLE is an optional field of that model and a column that accepts NULL in the production schema, and a model with
      a CLEARABLE set this file does not know the table of fails it.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import ClassVar, FrozenSet

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.sales_invoices as si
from models.clearable import clearable_fields, patch_dict
from models.invoices import (InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn, SalesInvoiceIn,
                             SalesInvoiceUpdateIn)
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
API = Path(__file__).resolve().parents[1]


# ── the reader, alone ──────────────────────────────────────────────────────────────────────────────────

class _Plain(BaseModel):
    a: str | None = None
    b: int | None = None


class _Soft(BaseModel):
    CLEARABLE: ClassVar[FrozenSet[str]] = frozenset({"note", "days"})
    note: str | None = None
    days: int | None = None
    kept: str | None = None


def test_a_model_without_a_clearable_set_reads_exactly_as_exclude_none_always_did():
    m = _Plain(a=None, b=3)
    assert patch_dict(m) == m.model_dump(exclude_none=True) == {"b": 3}
    assert clearable_fields(m) == frozenset()


def test_a_value_is_kept_and_a_field_not_sent_is_absent():
    assert patch_dict(_Soft(note="x")) == {"note": "x"}
    assert patch_dict(_Soft()) == {}


def test_a_clearable_field_sent_as_null_or_blank_is_a_clear_and_not_sent_is_not():
    assert patch_dict(_Soft(note=None)) == {"note": None}
    assert patch_dict(_Soft(note="   ")) == {"note": None}, "a blank is a clear, not an empty string to store"
    assert patch_dict(_Soft(note="")) == {"note": None}
    assert patch_dict(_Soft(days=None)) == {"days": None}
    assert patch_dict(_Soft(note=None, days=7, kept="k")) == {"note": None, "days": 7, "kept": "k"}


def test_a_field_that_is_not_clearable_still_reads_null_as_not_sent():
    assert patch_dict(_Soft(kept=None)) == {}, "a caller that sends nulls for what it does not mean to change must not be turned into one that erases"
    assert patch_dict(_Soft(kept="")) == {"kept": ""}, "an empty string for an ordinary field is the value it always was"


def test_it_reads_the_request_as_it_arrived_so_a_json_null_is_a_clear():
    body = json.loads('{"note": null, "kept": null}')
    assert patch_dict(_Soft(**body)) == {"note": None}
    assert patch_dict(_Soft.model_validate(json.loads("{}"))) == {}


def test_the_value_of_a_clearable_field_that_was_not_sent_is_absent_whatever_the_models_default_is():
    class _Defaulted(BaseModel):
        CLEARABLE: ClassVar[FrozenSet[str]] = frozenset({"note"})
        note: str | None = "a default that is not None"

    assert patch_dict(_Defaulted()) == {}, "a default is not something the caller sent"
    assert patch_dict(_Defaulted(note=None)) == {"note": None}


# ── the sales invoice ──────────────────────────────────────────────────────────────────────────────────────

def _invoice_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "state_code": "27", "gstin": "27XYZAB5678C1Z2",
                          "credit_days": 15, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    return db


def _new_invoice(db, **over):
    kw = dict(client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="CL-001", reference_no="PO-77", notes="Please pay by cheque",
              lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="X", hsn_sac="9982", quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0)])
    kw.update(over)
    return si.create_invoice(SalesInvoiceIn(**kw), CALLER)["data"]


def _stored(db, table, row_id):
    return next(r for r in db.rows(table) if r["id"] == row_id)


@pytest.mark.parametrize("status", ["draft", "issued"])
def test_a_note_and_a_reference_sent_as_null_are_cleared_on_an_invoice(monkeypatch, status):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice(db)
    assert _stored(db, "client_sales_invoices", inv["id"])["notes"] == "Please pay by cheque"
    _stored(db, "client_sales_invoices", inv["id"])["status"] = status
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes=None, reference_no=None), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "client_sales_invoices", inv["id"])
    assert row["notes"] is None and row["reference_no"] is None, "the screen said saved and the old value stayed"
    assert row["due_date"] == "2026-04-25", "what was not sent is left alone"


def test_a_blank_note_is_a_clear_too(monkeypatch):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice(db)
    _stored(db, "client_sales_invoices", inv["id"])["status"] = "issued"
    assert si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="   ", reference_no=""), CALLER)["success"] is True
    row = _stored(db, "client_sales_invoices", inv["id"])
    assert row["notes"] is None and row["reference_no"] is None, "a note of nothing is no note: it is not stored as blank text"


def test_a_field_that_is_not_in_the_request_is_left_alone(monkeypatch):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice(db)
    _stored(db, "client_sales_invoices", inv["id"])["status"] = "issued"
    assert si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="Revised"), CALLER)["success"] is True
    row = _stored(db, "client_sales_invoices", inv["id"])
    assert row["notes"] == "Revised" and row["reference_no"] == "PO-77"


def test_an_issued_invoice_is_not_refused_for_a_null_it_did_not_mean_and_a_locked_field_is_still_locked(monkeypatch):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice(db)
    row = _stored(db, "client_sales_invoices", inv["id"])
    row["status"] = "issued"
    before = dict(row)
    # nulls for locked fields are "not sent": nothing is refused and nothing changes (a caller that always sends them keeps working)
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(customer_id=None, invoice_no=None, supply_state_code=None, notes="n"), CALLER)
    assert out["success"] is True
    after = _stored(db, "client_sales_invoices", inv["id"])
    assert after["customer_id"] == before["customer_id"] and after["invoice_no"] == before["invoice_no"]
    # a real change to a locked field is still refused
    with pytest.raises(HTTPException) as caught:
        si.update_invoice(inv["id"], SalesInvoiceUpdateIn(invoice_no="CL-002"), CALLER)
    assert caught.value.status_code == 422


def test_a_due_date_and_credit_days_sent_as_null_are_not_a_clear(monkeypatch):
    """Every invoice carries a due date, so the SCREEN refuses to empty one; the route reads a null as it always did, "not sent"."""
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice(db)
    _stored(db, "client_sales_invoices", inv["id"])["status"] = "issued"
    assert _stored(db, "client_sales_invoices", inv["id"])["due_date"] == "2026-04-25"
    assert _stored(db, "client_sales_invoices", inv["id"])["credit_days"] == 15
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(due_date=None, credit_days=None, notes="n"), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "client_sales_invoices", inv["id"])
    assert row["due_date"] == "2026-04-25" and row["credit_days"] == 15, "a due date is corrected and not cleared"


def test_a_due_date_given_still_works_out_the_credit_days_as_it_always_did(monkeypatch):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice(db)
    _stored(db, "client_sales_invoices", inv["id"])["status"] = "issued"
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(due_date="2026-06-01", credit_days=None), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "client_sales_invoices", inv["id"])
    assert row["due_date"] == "2026-06-01" and row["credit_days"] == 52, "terms never contradict the real due date"


def test_the_mock_mode_branch_of_the_invoice_edit_clears_too(monkeypatch):
    """With no database the route edits an in-memory list and returns the merged row: the cleared fields must be None there as well."""
    monkeypatch.setattr(si, "_USE_MOCK", True)
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES", [{"id": "MI-1", "status": "issued", "client_id": "CLI", "invoice_date": "2026-04-10",
                                                      "due_date": "2026-04-25", "notes": "n", "reference_no": "r"}])
    out = si.update_invoice("MI-1", SalesInvoiceUpdateIn(notes=None, reference_no=None, due_date=None), CALLER)
    assert out["success"] is True, out
    row = out["data"]
    assert row["notes"] is None and row["reference_no"] is None
    assert row["due_date"] == "2026-04-25", "a null due date is not a clear in mock mode either"


# ── the purchase bill ────────────────────────────────────────────────────────────────────────────────────────

def _bill_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": False, "credit_days": 15})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    return db


def _new_bill(**over):
    kw = dict(client_id="CLI", vendor_id="VEND", bill_date="2026-04-10", bill_no="B-001", our_reference="OUR-1", notes="Received with the goods",
              document_url="path/to/scan.pdf",
              lines=[PurchaseBillLineIn(description="X", hsn_sac="9982", quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")])
    kw.update(over)
    return pb.create_purchase_bill(PurchaseBillIn(**kw), CALLER)["data"]


@pytest.mark.parametrize("status", ["draft", "received"])
def test_a_reference_and_a_note_sent_as_null_are_cleared_on_a_bill(monkeypatch, status):
    db = _bill_setup(monkeypatch)
    bill = _new_bill()
    _stored(db, "purchase_bills", bill["id"])["status"] = status
    out = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(our_reference=None, notes=None), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "purchase_bills", bill["id"])
    assert row["our_reference"] is None and row["notes"] is None
    assert row["due_date"] == "2026-04-25", "what was not sent is left alone"


def test_the_bill_number_and_the_attached_copy_of_the_suppliers_invoice_are_evidence_and_cannot_be_cleared(monkeypatch):
    db = _bill_setup(monkeypatch)
    bill = _new_bill()
    _stored(db, "purchase_bills", bill["id"])["status"] = "received"
    out = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(bill_no=None, document_url=None, notes="n"), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "purchase_bills", bill["id"])
    assert row["bill_no"] == "B-001" and row["document_url"] == "path/to/scan.pdf", "a null for evidence is 'not sent', never a clear"


def test_a_bills_due_date_and_credit_days_sent_as_null_are_not_a_clear(monkeypatch):
    db = _bill_setup(monkeypatch)
    bill = _new_bill()
    _stored(db, "purchase_bills", bill["id"])["status"] = "received"
    assert _stored(db, "purchase_bills", bill["id"])["due_date"] == "2026-04-25"
    out = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(due_date=None, credit_days=None, notes="n"), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "purchase_bills", bill["id"])
    assert row["due_date"] == "2026-04-25", "a due date is corrected and not cleared"


def test_the_mock_mode_branch_of_the_bill_edit_clears_too(monkeypatch):
    monkeypatch.setattr(pb, "_USE_MOCK", True)
    monkeypatch.setattr(pb, "MOCK_PURCHASE_BILLS", [{"id": "MB-1", "status": "received", "client_id": "CLI", "vendor_id": "VEND", "bill_date": "2026-04-10",
                                                      "due_date": "2026-04-25", "bill_no": "B-001", "our_reference": "OUR-1", "notes": "n"}])
    out = pb.update_purchase_bill("MB-1", PurchaseBillUpdateIn(our_reference=None, notes=None, bill_no=None, due_date=None), CALLER)
    assert out["success"] is True, out
    row = out["data"]
    assert row["our_reference"] is None and row["notes"] is None
    assert row["bill_no"] == "B-001" and row["due_date"] == "2026-04-25"


# ── the four notes ──────────────────────────────────────────────────────────────────────────────────────────────

_NOTES = [
    (cn, "credit_notes", "update_credit_note", "CreditNoteUpdateIn", {"customer_id": "CUST", "credit_note_date": "2026-04-12", "total_paise": 100}),
    (sdn, "sales_debit_notes", "update_sales_debit_note", "SalesDebitNoteUpdateIn", {"customer_id": "CUST", "debit_note_date": "2026-04-12", "total_paise": 100}),
    (dn, "debit_notes", "update_debit_note", "DebitNoteUpdateIn", {"vendor_id": "VEND", "debit_note_date": "2026-04-12", "total_paise": 100, "document_url": "scan.pdf"}),
    (pcn, "purchase_credit_notes", "update_purchase_credit_note", "PurchaseCreditNoteUpdateIn", {"vendor_id": "VEND", "credit_note_date": "2026-04-12", "total_paise": 100, "document_url": "scan.pdf"}),
]


@pytest.mark.parametrize("status", ["draft", "issued"])
@pytest.mark.parametrize("module,table,handler,model_name,extra", _NOTES, ids=[t for _, t, *_ in _NOTES])
def test_a_note_sent_as_null_is_cleared_on_a_note_of_each_kind(monkeypatch, module, table, handler, model_name, extra, status):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [module])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    row = db.seed(table, {"firm_id": FIRM, "client_id": "CLI", "status": status, "notes": "A note to clear", "deleted_at": None, **extra})
    model = getattr(module, model_name)
    out = getattr(module, handler)(row["id"], model(notes=None), CALLER)
    assert out["success"] is True, out
    assert _stored(db, table, row["id"])["notes"] is None, f"{table}: the screen said saved and the note stayed"
    if "document_url" in extra:
        # the attached copy of a purchase note is evidence: a null for it is not a clear, and an issued note is not refused for it
        out = getattr(module, handler)(row["id"], model(notes="again", document_url=None), CALLER)
        assert out["success"] is True, out
        assert _stored(db, table, row["id"])["document_url"] == "scan.pdf"
        assert _stored(db, table, row["id"])["notes"] == "again"


def test_an_issued_note_is_still_closed_to_a_real_change_of_anything_but_its_note(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cn])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    row = db.seed("credit_notes", {"firm_id": FIRM, "client_id": "CLI", "status": "issued", "notes": "n", "reason": "Return", "deleted_at": None})
    with pytest.raises(HTTPException) as caught:
        cn.update_credit_note(row["id"], cn.CreditNoteUpdateIn(reason="Changed"), CALLER)
    assert caught.value.status_code == 422
    out = cn.update_credit_note(row["id"], cn.CreditNoteUpdateIn(reason=None, notes="m"), CALLER)
    assert out["success"] is True and _stored(db, "credit_notes", row["id"])["reason"] == "Return", "a null for the reason is 'not sent'"


# ── a note typed on a NEW sales credit note or debit note is stored ──────────────────────────────────────────────

def _note_setup(monkeypatch, module):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [module])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2026-04-01"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "state_code": "27", "is_active": True, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Advice", "kind": "service"})
    return db


def _line():
    return InvoiceLineIn(description="line", quantity=1, rate_paise=20000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")


@pytest.mark.parametrize("typed,stored", [("  Agreed on the phone  ", "Agreed on the phone"), ("   ", None), (None, None)])
def test_a_note_typed_on_a_new_sales_credit_note_is_stored_trimmed(monkeypatch, typed, stored):
    db = _note_setup(monkeypatch, cn)
    out = cn.create_credit_note(cn.CreditNoteIn(client_id="CLI", customer_id="CUST", credit_note_date="2026-06-05", lines=[_line()], notes=typed), CALLER)
    assert out["success"] is True, out
    assert _stored(db, "credit_notes", out["data"]["id"])["notes"] == stored


@pytest.mark.parametrize("typed,stored", [("  Late fee agreed  ", "Late fee agreed"), ("   ", None), (None, None)])
def test_a_note_typed_on_a_new_sales_debit_note_is_stored_trimmed(monkeypatch, typed, stored):
    db = _note_setup(monkeypatch, sdn)
    out = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(client_id="CLI", customer_id="CUST", debit_note_date="2026-06-05", lines=[_line()], notes=typed), CALLER)
    assert out["success"] is True, out
    assert _stored(db, "sales_debit_notes", out["data"]["id"])["notes"] == stored


def _purchase_note_setup(monkeypatch, module):
    """The purchase side: a vendor in the client's State and a goods-free service line, so only the note and the attached copy are in question."""
    db = _note_setup(monkeypatch, module)
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier Co", "state_code": "27", "gstin": "27CCCCC2222C1Z5",
                        "tds_applicable": False, "is_active": True, "opening_balance_paise": 0})
    return db


_COPY = f"{FIRM}/CLI/debit_note/6f1e_scan.pdf"


@pytest.mark.parametrize("typed,stored", [("  Agreed by phone  ", "Agreed by phone"), ("   ", None), (None, None)])
@pytest.mark.parametrize("copy,kept", [(f" {_COPY} ", _COPY), ("  ", None), (None, None)])
def test_a_note_and_an_attached_copy_given_on_a_new_purchase_debit_note_are_stored(monkeypatch, typed, stored, copy, kept):
    """The screen uploads the supplier's scan first and sends its path with the note; the create model had neither field, so the row came back with both NULL and the screen said 'saved as draft'."""
    db = _purchase_note_setup(monkeypatch, dn)
    out = dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id="VEND", debit_note_date="2026-06-05", lines=[_line()], notes=typed, document_url=copy), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "debit_notes", out["data"]["id"])
    assert row["notes"] == stored and row["document_url"] == kept


@pytest.mark.parametrize("typed,stored", [("  Rate corrected  ", "Rate corrected"), ("   ", None), (None, None)])
@pytest.mark.parametrize("copy,kept", [(f" {_COPY} ", _COPY), ("  ", None), (None, None)])
def test_a_note_and_an_attached_copy_given_on_a_new_purchase_credit_note_are_stored(monkeypatch, typed, stored, copy, kept):
    db = _purchase_note_setup(monkeypatch, pcn)
    out = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(client_id="CLI", vendor_id="VEND", credit_note_date="2026-06-05", lines=[_line()], notes=typed, document_url=copy), CALLER)
    assert out["success"] is True, out
    row = _stored(db, "purchase_credit_notes", out["data"]["id"])
    assert row["notes"] == stored and row["document_url"] == kept


# ── what may be cleared is a column that accepts NULL, and nothing names a set this file does not know ───────────────────

CLEARABLE_MODELS = [
    (SalesInvoiceUpdateIn, "client_sales_invoices"),
    (PurchaseBillUpdateIn, "purchase_bills"),
    (cn.CreditNoteUpdateIn, "credit_notes"),
    (sdn.SalesDebitNoteUpdateIn, "sales_debit_notes"),
    (dn.DebitNoteUpdateIn, "debit_notes"),
    (pcn.PurchaseCreditNoteUpdateIn, "purchase_credit_notes"),
]

#: A model's field and its column are not always one name; none of the six differ today.
_COLUMN_OF: dict[tuple[str, str], str] = {}


def _schema():
    return json.loads((API / "tests" / "fixtures" / "production_schema_2026-09-03.json").read_text(encoding="utf-8"))


def _columns(table):
    t = _schema()[table]
    cols = t.get("columns", t)
    if isinstance(cols, dict):
        return [dict(name=k, **v) for k, v in cols.items()]
    return cols


@pytest.mark.parametrize("model,table", CLEARABLE_MODELS, ids=[t for _, t in CLEARABLE_MODELS])
def test_every_clearable_name_is_an_optional_field_of_its_model_and_a_nullable_column(model, table):
    clearable = getattr(model, "CLEARABLE", frozenset())
    assert clearable, f"{model.__name__} names nothing it may clear"
    fields = model.model_fields
    cols = {c["name"] if isinstance(c, dict) and "name" in c else c.get("column_name"): c for c in _columns(table)}
    for name in sorted(clearable):
        assert name in fields, f"{model.__name__}.CLEARABLE names {name}, which is not a field of the model"
        assert not fields[name].is_required(), f"{name} is required on {model.__name__}: a clear cannot be a null for it"
        column = _COLUMN_OF.get((table, name), name)
        assert column in cols, f"{table} has no column {column} in the production schema"
        assert str(cols[column].get("nullable", cols[column].get("is_nullable"))).upper() in ("YES", "TRUE"), \
            f"{table}.{column} is NOT NULL: a clear would be a 500"


def test_no_clearable_set_is_named_that_this_file_does_not_know_the_table_of():
    """Found by source, not by import: every class in `models/` and `routers/` that assigns a CLEARABLE must be one of the models above, so a new one cannot skip the NULL check."""
    named = set()
    for folder in ("models", "routers"):
        for path in sorted((API / folder).glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    target = stmt.target if isinstance(stmt, ast.AnnAssign) else (stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
                    if isinstance(target, ast.Name) and target.id == "CLEARABLE":
                        named.add(node.name)
    known = {m.__name__ for m, _ in CLEARABLE_MODELS}
    assert named, "the scan found no CLEARABLE set at all"
    assert named == known, f"models with a CLEARABLE set this file does not know the table of: {sorted(named - known)}; known models that no longer have one: {sorted(known - named)}"


def test_the_clearable_names_are_free_text_and_never_a_date_an_amount_or_evidence():
    """The rule for what a person may clear is short (models/clearable.py): a soft, optional, free-text particular they typed. A date, a figure and the evidence of a document are not."""
    forbidden = {"due_date", "credit_days", "bill_no", "invoice_no", "document_url", "form_15ca_ack_no", "form_15ca_filed_on", "form_15cb_udin",
                 "shipping_bill_no", "shipping_bill_date", "port_code", "customer_id", "vendor_id", "total_paise", "supply_state_code"}
    for model, _ in CLEARABLE_MODELS:
        names = clearable_fields(model())
        assert not (names & forbidden), f"{model.__name__}.CLEARABLE names {sorted(names & forbidden)}: a date, a figure and the evidence of a document are corrected and not cleared"
        assert not any(n.endswith(("_date", "_paise", "_bps", "_on", "_at")) for n in names), f"{model.__name__}.CLEARABLE names a date or a figure: {sorted(names)}"
