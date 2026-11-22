"""Only a DRAFT may take away the document it is raised against, its reason, or its place of supply (POST-A-399, the sixth slice).

WHAT WAS WRONG
    The four note editors sent the "Against invoice" (or "Against bill") box as `id || undefined` and the reason as `text || undefined`, and the
    invoice editor sent its place of supply the same way; the edit routes read a missing key as "not sent". So an emptied box on a draft changed
    nothing and the screen said it saved. The one that mattered most: changing the customer of a draft credit note empties its "Against invoice"
    box, and the note went on pointing at the OLD customer's invoice.

WHAT THIS HOLDS
    * `models.clearable.draft_only_clears` answers each field of the model's `CLEARABLE_ON_A_DRAFT` that the request SENT as null or blank, as
      None, and nothing for a field that was not sent or carries a value;
    * on a DRAFT note of each of the four kinds, a null for the linked document and a null (or a blank) for the reason are written as NULL, and a
      field that was not sent is left alone;
    * on an ISSUED note the same request changes neither and is NOT refused (a null there has always read "not sent"), a blank is treated as the
      null is, and a real change of either is still refused in the route's own words;
    * a draft invoice's place of supply is cleared by a null, and an issued invoice's is kept and the request is not refused;
    * every name in a `CLEARABLE_ON_A_DRAFT` is an optional field of its model and a column that accepts NULL in the production schema snapshot,
      is never also in the model's `CLEARABLE` (which clears at any status), and no model names such a set that this file does not know.

WHAT IT DOES NOT HOLD. The routes are driven against the in-memory database, not a real one. Whether the document a note is raised against
belongs to the note's own customer or supplier was not asked by these routes at all; that was its own finding (POST-A-553),
closed in the same change and held by `tests/test_a_note_is_raised_against_a_document_of_its_own_party.py`.
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
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.sales_invoices as si
from models.clearable import draft_only_clears, patch_dict, put_back_on_a_draft, without
from models.invoices import InvoiceLineIn, SalesInvoiceIn, SalesInvoiceUpdateIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
API = Path(__file__).resolve().parents[1]


# ── the reader, alone ─────────────────────────────────────────────────────────────

class _Note(BaseModel):
    CLEARABLE: ClassVar[FrozenSet[str]] = frozenset({"notes"})
    CLEARABLE_ON_A_DRAFT: ClassVar[FrozenSet[str]] = frozenset({"link", "reason"})
    link: str | None = None
    reason: str | None = None
    notes: str | None = None
    party: str | None = None


def test_a_draft_only_field_sent_as_null_or_blank_is_answered_and_one_not_sent_or_given_is_not():
    assert draft_only_clears(_Note()) == {}
    assert draft_only_clears(_Note(link=None)) == {"link": None}
    assert draft_only_clears(_Note(link="", reason="   ")) == {"link": None, "reason": None}
    assert draft_only_clears(_Note(link="INV-1", reason="Return")) == {}
    assert draft_only_clears(_Note.model_validate({"reason": None, "party": None})) == {"reason": None}, "only the names the model lists"
    assert draft_only_clears(_Note(notes=None)) == {}, "what clears at any status is patch_dict's, not this function's"


def test_a_model_with_no_such_set_answers_nothing():
    class _Plain(BaseModel):
        link: str | None = None
    assert draft_only_clears(_Plain(link=None)) == {}


def test_a_blank_does_not_travel_on_as_an_empty_string():
    """`patch_dict` keeps a blank for a field it does not clear (exclude_none drops only None). The route takes the draft-only names out before
    it writes, so "" never reaches a uuid column."""
    model = _Note(link="", reason="Return")
    assert patch_dict(model) == {"link": "", "reason": "Return"}
    assert without(patch_dict(model), draft_only_clears(model)) == {"reason": "Return"}


# ── the four notes ────────────────────────────────────────────────────────────────

_NOTES = [
    (cn, "credit_notes", "update_credit_note", "CreditNoteUpdateIn", "sales_invoice_id", {"customer_id": "CUST", "credit_note_date": "2026-04-12"}),
    (sdn, "sales_debit_notes", "update_sales_debit_note", "SalesDebitNoteUpdateIn", "sales_invoice_id", {"customer_id": "CUST", "debit_note_date": "2026-04-12"}),
    (dn, "debit_notes", "update_debit_note", "DebitNoteUpdateIn", "purchase_bill_id", {"vendor_id": "VEND", "debit_note_date": "2026-04-12"}),
    (pcn, "purchase_credit_notes", "update_purchase_credit_note", "PurchaseCreditNoteUpdateIn", "purchase_bill_id", {"vendor_id": "VEND", "credit_note_date": "2026-04-12"}),
]
_IDS = [t for _, t, *_ in _NOTES]


def _a_note(monkeypatch, module, table, link, extra, status):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [module])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    row = db.seed(table, {"firm_id": FIRM, "client_id": "CLI", "status": status, "notes": "n", "reason": "Rate correction",
                          link: "DOC-OLD", "total_paise": 100, "deleted_at": None, **extra})
    return db, row


def _stored(db, table, row_id):
    return next(r for r in db.rows(table) if r["id"] == row_id)


@pytest.mark.parametrize("module,table,handler,model_name,link,extra", _NOTES, ids=_IDS)
def test_a_draft_note_drops_the_document_it_was_raised_against_and_its_reason(monkeypatch, module, table, handler, model_name, link, extra):
    db, row = _a_note(monkeypatch, module, table, link, extra, "draft")
    model = getattr(module, model_name)
    out = getattr(module, handler)(row["id"], model(**{link: None}), CALLER)
    assert out["success"] is True, out
    stored = _stored(db, table, row["id"])
    assert stored[link] is None, f"{table}: the box was emptied, the screen said saved and the note still points at the old document"
    assert stored["reason"] == "Rate correction", "a field that was not sent is left alone"

    out = getattr(module, handler)(row["id"], model(reason="  "), CALLER)
    assert out["success"] is True, out
    assert _stored(db, table, row["id"])["reason"] is None, f"{table}: an emptied reason stayed"
    assert out["data"][link] is None and out["data"]["reason"] is None, "the answer is the row as it now stands"


@pytest.mark.parametrize("module,table,handler,model_name,link,extra", _NOTES, ids=_IDS)
def test_a_draft_note_whose_boxes_were_not_touched_keeps_both(monkeypatch, module, table, handler, model_name, link, extra):
    db, row = _a_note(monkeypatch, module, table, link, extra, "draft")
    model = getattr(module, model_name)
    out = getattr(module, handler)(row["id"], model(notes="changed"), CALLER)
    assert out["success"] is True, out
    stored = _stored(db, table, row["id"])
    assert stored[link] == "DOC-OLD" and stored["reason"] == "Rate correction" and stored["notes"] == "changed"


@pytest.mark.parametrize("empty", [None, ""])
@pytest.mark.parametrize("module,table,handler,model_name,link,extra", _NOTES, ids=_IDS)
def test_an_issued_note_keeps_both_and_is_not_refused_for_an_empty_it_did_not_mean(monkeypatch, module, table, handler, model_name, link, extra, empty):
    db, row = _a_note(monkeypatch, module, table, link, extra, "issued")
    model = getattr(module, model_name)
    out = getattr(module, handler)(row["id"], model(**{link: empty, "reason": empty, "notes": "m"}), CALLER)
    assert out["success"] is True, out
    stored = _stored(db, table, row["id"])
    assert stored[link] == "DOC-OLD" and stored["reason"] == "Rate correction", f"{table}: an issued note lost a frozen particular"
    assert stored["notes"] == "m"


@pytest.mark.parametrize("module,table,handler,model_name,link,extra", _NOTES, ids=_IDS)
def test_an_issued_note_still_refuses_a_real_change_of_its_reason(monkeypatch, module, table, handler, model_name, link, extra):
    db, row = _a_note(monkeypatch, module, table, link, extra, "issued")
    with pytest.raises(HTTPException) as caught:
        getattr(module, handler)(row["id"], getattr(module, model_name)(reason="Changed"), CALLER)
    assert caught.value.status_code == 422
    assert _stored(db, table, row["id"])["reason"] == "Rate correction"


@pytest.mark.parametrize("module,table,handler,model_name,link,extra", _NOTES, ids=_IDS)
def test_the_mock_mode_branch_of_each_note_route_does_the_same(monkeypatch, module, table, handler, model_name, link, extra):
    """Local development and the demo run with no database: the route's other branch holds the notes in a list, and it clears on a draft and
    keeps on an issued note exactly as the database branch does."""
    monkeypatch.setattr(module, "_USE_MOCK", True)
    scope = next((n for n in dir(module) if n.startswith("_assert_") and n.endswith("_scope")), None)
    assert scope, f"{module.__name__} has no scope check to stand in for"
    monkeypatch.setattr(module, scope, lambda *a, **k: None)
    store_name = next(n for n in dir(module) if n.startswith("MOCK_") and not n.endswith("_LINES") and isinstance(getattr(module, n), list))
    for status, expect_link, expect_reason in (("draft", None, None), ("issued", "DOC-OLD", "Rate correction")):
        note = {"id": f"N-{status}", "firm_id": FIRM, "client_id": "CLI", "status": status, "notes": "n", "reason": "Rate correction", link: "DOC-OLD"}
        monkeypatch.setattr(module, store_name, [note])
        out = getattr(module, handler)(note["id"], getattr(module, model_name)(**{link: None, "reason": None, "notes": "m"}), CALLER)
        assert out["success"] is True, out
        held = getattr(module, store_name)[0]
        assert held[link] == expect_link and held["reason"] == expect_reason, f"{module.__name__} mock branch, {status}"
        assert held["notes"] == "m"


# ── the sales invoice's place of supply ───────────────────────────────────────────

def _invoice_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "state_code": "27", "gstin": "27XYZAB5678C1Z2",
                          "credit_days": 15, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    return db


def _new_invoice():
    return si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="CL-001", supply_state_code="29",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="X", hsn_sac="9982", quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0)]), CALLER)["data"]


def test_a_draft_invoice_drops_its_place_of_supply_and_an_untouched_one_is_kept(monkeypatch):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice()
    assert _stored(db, "client_sales_invoices", inv["id"])["supply_state_code"] == "29"
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(notes="a note"), CALLER)
    assert out["success"] is True and _stored(db, "client_sales_invoices", inv["id"])["supply_state_code"] == "29"
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(supply_state_code=None), CALLER)
    assert out["success"] is True, out
    assert _stored(db, "client_sales_invoices", inv["id"])["supply_state_code"] is None, "the state was emptied, the screen said saved and the old one stayed"


@pytest.mark.parametrize("empty", [None, ""])
def test_an_issued_invoice_keeps_its_place_of_supply_and_is_not_refused(monkeypatch, empty):
    db = _invoice_setup(monkeypatch)
    inv = _new_invoice()
    next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"])["status"] = "issued"
    out = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(supply_state_code=empty, notes="m"), CALLER)
    assert out["success"] is True, out
    stored = _stored(db, "client_sales_invoices", inv["id"])
    assert stored["supply_state_code"] == "29" and stored["notes"] == "m"


# ── what may be taken away from a draft is a NULL-able column, and nothing names a set this file does not know ─────

DRAFT_MODELS = [
    (cn.CreditNoteUpdateIn, "credit_notes", {"sales_invoice_id", "reason"}),
    (sdn.SalesDebitNoteUpdateIn, "sales_debit_notes", {"sales_invoice_id", "reason"}),
    (dn.DebitNoteUpdateIn, "debit_notes", {"purchase_bill_id", "reason"}),
    (pcn.PurchaseCreditNoteUpdateIn, "purchase_credit_notes", {"purchase_bill_id", "reason"}),
    (SalesInvoiceUpdateIn, "client_sales_invoices", {"supply_state_code"}),
]


def _columns(table):
    t = json.loads((API / "tests" / "fixtures" / "production_schema_2026-09-03.json").read_text(encoding="utf-8"))[table]
    cols = t.get("columns", t)
    return cols if isinstance(cols, dict) else {c.get("name") or c.get("column_name"): c for c in cols}


@pytest.mark.parametrize("model,table,names", DRAFT_MODELS, ids=[t for _, t, _ in DRAFT_MODELS])
def test_every_draft_only_name_is_an_optional_field_a_nullable_column_and_not_also_clearable_at_any_status(model, table, names):
    draft_only = set(getattr(model, "CLEARABLE_ON_A_DRAFT", frozenset()))
    assert draft_only == names, f"{model.__name__}: the set changed; decide each name here, with its reason, before a route clears it"
    assert not (draft_only & set(getattr(model, "CLEARABLE", frozenset()))), "a field is cleared at any status or only on a draft, not both"
    cols = _columns(table)
    for name in sorted(draft_only):
        assert name in model.model_fields and not model.model_fields[name].is_required(), f"{name} is not an optional field of {model.__name__}"
        assert name in cols, f"{table} has no column {name} in the production schema"
        assert str(cols[name].get("nullable", cols[name].get("is_nullable"))).upper() in ("YES", "TRUE"), f"{table}.{name} is NOT NULL: a clear would be a 500"


def test_no_model_names_a_draft_only_set_that_this_file_does_not_know():
    named = set()
    for folder in ("models", "routers"):
        for path in sorted((API / folder).glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    target = stmt.target if isinstance(stmt, ast.AnnAssign) else (stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None)
                    if isinstance(target, ast.Name) and target.id == "CLEARABLE_ON_A_DRAFT":
                        named.add(node.name)
    known = {m.__name__ for m, _, _ in DRAFT_MODELS}
    assert named == known, f"unknown: {sorted(named - known)}; gone: {sorted(known - named)}"


def test_the_names_held_aside_are_put_back_for_a_draft_and_for_no_other_status():
    for status, expected in (("draft", {"notes": "n", "link": None}), ("issued", {"notes": "n"}), ("paid", {"notes": "n"}),
                             ("cancelled", {"notes": "n"}), (None, {"notes": "n"}), ("", {"notes": "n"}), ("Draft", {"notes": "n"})):
        data = {"notes": "n"}
        put_back_on_a_draft(data, {"link": None}, status)
        assert data == expected, status


def _source_of(module, name):
    text = Path(module.__file__).read_text(encoding="utf-8")
    return ast.get_source_segment(text, next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name))


def test_every_route_whose_model_names_a_draft_only_set_reads_it_and_applies_it_only_to_a_draft():
    """The set on a model does nothing by itself. Each of the five routes takes the names out of what it writes, and puts them back through
    the one function that asks whether the stored document is a draft, in both of its branches, and never writes them any other way."""
    for module, handler, reader in [(cn, "update_credit_note", None), (sdn, "update_sales_debit_note", None), (dn, "update_debit_note", None),
                                    (pcn, "update_purchase_credit_note", None), (si, "update_invoice", "_what_the_edit_sent")]:
        src = _source_of(module, handler)
        read = _source_of(module, reader) if reader else src
        assert "draft_clears = draft_only_clears(" in read, f"{module.__name__}.{handler} does not read the draft-only set"
        assert "without(patch_dict(" in read and ", draft_clears)" in read, f"{module.__name__}.{handler} writes the draft-only names before it knows the status"
        if reader:
            assert f"data, draft_clears, line_units = {reader}(data)" in src, f"{module.__name__}.{handler} does not read its edit through {reader}"
        assert src.count("put_back_on_a_draft(data, draft_clears, ") == 2, f"{module.__name__}.{handler}: both branches (no database, database) must put them back"
        assert "data.update(draft_clears)" not in src, f"{module.__name__}.{handler} writes the names held aside without asking whether the document is a draft"
