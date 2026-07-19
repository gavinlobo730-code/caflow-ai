"""
Sales Credit Note parity build — GET single / PATCH (dedicated edit page +
drawer, mirroring the same tests already proven for debit_notes.py,
purchase_credit_notes.py and sales_debit_notes.py).
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.credit_notes as cn
from models.invoices import InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                          "is_active": True, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Returned Goods", "kind": "good"})
    return db


def _issue_invoice(db, inv_no="INV-1", taxable=100000, cgst=9000, sgst=9000, igst=0):
    total = taxable + cgst + sgst + igst
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "invoice_no": inv_no, "invoice_date": "2025-06-01", "status": "draft",
        "total_paise": total, "taxable_amount_paise": taxable,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
        "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0, "is_interstate": bool(igst),
    })
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"], total


def _create_cn(db, inv_id, rate, no="CN-1"):
    res = cn.create_credit_note(cn.CreditNoteIn(
        client_id="CLI", customer_id="CUST1", credit_note_date="2025-06-05",
        sales_invoice_id=inv_id, reason="Goods returned",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=rate,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    return res["data"]["id"], res["data"]["total_paise"]


def test_get_single_credit_note_returns_lines(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    cn_id, total = _create_cn(db, inv_id, rate=20000)
    res = cn.get_credit_note(cn_id, CALLER)
    assert res["success"] is True
    assert res["data"]["id"] == cn_id
    assert res["data"]["total_paise"] == total
    assert len(res["data"]["lines"]) == 1
    assert res["data"]["lines"][0]["description"] == "return"


def test_patch_draft_credit_note_recomputes_totals_from_new_lines(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    cn_id, _ = _create_cn(db, inv_id, rate=20000)                    # 23600
    res = cn.update_credit_note(cn_id, cn.CreditNoteUpdateIn(
        lines=[InvoiceLineIn(description="corrected return", quantity=1, rate_paise=50000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["total_paise"] == 59000                       # 50000 + 18%
    assert len(res["data"]["lines"]) == 1
    assert res["data"]["lines"][0]["description"] == "corrected return"
    assert cn.get_credit_note(cn_id, CALLER)["data"]["total_paise"] == 59000


def test_patch_notes_allowed_on_issued_credit_note(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    cn_id, _ = _create_cn(db, inv_id, rate=20000)
    assert cn.issue_credit_note(cn_id, CALLER)["success"] is True
    res = cn.update_credit_note(cn_id, cn.CreditNoteUpdateIn(
        notes="internal note",
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["notes"] == "internal note"


def test_patch_lines_rejected_on_issued_credit_note(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    cn_id, _ = _create_cn(db, inv_id, rate=20000)
    assert cn.issue_credit_note(cn_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        cn.update_credit_note(cn_id, cn.CreditNoteUpdateIn(
            lines=[InvoiceLineIn(description="x", quantity=1, rate_paise=1000,
                                  gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
        ), CALLER)
    assert ex.value.status_code == 422


def test_line_unit_persists_on_create_and_edit(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    res = cn.create_credit_note(cn.CreditNoteIn(
        client_id="CLI", customer_id="CUST1", credit_note_date="2025-06-05",
        sales_invoice_id=inv_id, reason="Goods returned",
        lines=[InvoiceLineIn(description="return", quantity=2, unit="KGS", rate_paise=20000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    cn_id = res["data"]["id"]
    assert res["data"]["lines"][0]["unit"] == "KGS"
    assert cn.get_credit_note(cn_id, CALLER)["data"]["lines"][0]["unit"] == "KGS"

    upd = cn.update_credit_note(cn_id, cn.CreditNoteUpdateIn(
        lines=[InvoiceLineIn(description="return", quantity=2, unit="BOX", rate_paise=20000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert upd["success"] is True
    assert upd["data"]["lines"][0]["unit"] == "BOX"
    assert cn.get_credit_note(cn_id, CALLER)["data"]["lines"][0]["unit"] == "BOX"


def test_issue_credit_note_propagates_journal_http_exception(monkeypatch):
    """A deliberate business-rule rejection from the journal kernel (e.g. a
    locked-FY check firing at posting time) carries a real, actionable
    status+message the CA needs (task #97) — the rollback must still run, but
    the exception itself must propagate as-is, not get collapsed into the
    generic "Please try again" (retrying identical input would never succeed)."""
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    cn_id, _ = _create_cn(db, inv_id, rate=20000)

    import services.phase2_journal_service as pjs
    def _boom(*a, **k):
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked for posting.")
    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_credit_note", _boom)

    with pytest.raises(HTTPException) as e:
        cn.issue_credit_note(cn_id, CALLER)
    assert e.value.status_code == 422
    assert "locked" in e.value.detail.lower()
    # The sub-ledger rollback must still have run — invoice not left partially applied.
    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    assert inv["credited_paise"] == 0
