"""
Production Readiness Phase 1 — C2: sales-invoice cancellation.

Cancelling an ISSUED invoice must not mutate or delete the original posted
journal (immutability + append-only). Instead it posts an equal-and-opposite
REVERSAL through the single kernel, so:
  * GL Trade Receivables control nets back to 0
  * the invoice is excluded from outstanding
  * the trial balance stays balanced
  * the reversal entry carries reversal_of → the original issue journal

Cancellation is BLOCKED (accounting rules) where a settlement already exists —
a receipt (paid_paise) or a credit note (credited_paise) — because reversing the
invoice would strand those sub-ledger journals. Drafts are deleted, not
cancelled. Integer paise throughout.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.credit_notes as cn
import services.receipt_service as rsvc
from services.customer_statement_service import customer_statement_service
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, rsvc])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                          "is_active": True, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    return db


def _issue_invoice(db, inv_no="INV-1", taxable=100000, cgst=9000, sgst=9000, igst=0):
    total = taxable + cgst + sgst + igst
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "invoice_no": inv_no, "invoice_date": "2025-06-01", "status": "draft",
        "total_paise": total, "taxable_amount_paise": taxable,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
        "paid_paise": 0, "credited_paise": 0, "is_interstate": bool(igst),
    })
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"], total


def _ar(db):
    return account_balance(db, coa_id(db, FIRM, "ar"))


def _invoice(db, inv_id):
    return next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)


def test_cancel_issued_invoice_posts_reversal_and_nets_gl_to_zero(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)
    assert _ar(db) == total                                   # AR raised by the issue journal
    issue_jrnl = _invoice(db, inv_id)["journal_entry_id"]
    assert issue_jrnl

    res = si.cancel_invoice(inv_id, CALLER)
    assert res["success"] is True

    inv = _invoice(db, inv_id)
    assert inv["status"] == "cancelled"
    # The original issue journal is UNTOUCHED (immutable) ...
    orig = next(e for e in db.rows("journal_entries") if e["id"] == issue_jrnl)
    assert orig.get("is_posted", True) is True and not orig.get("reversal_of")
    # ... and exactly ONE reversal was posted, linked back to it, through the kernel.
    reversals = [e for e in db.rows("journal_entries") if e.get("reversal_of") == issue_jrnl]
    assert len(reversals) == 1 and reversals[0].get("is_posted", True) is True

    assert _ar(db) == 0                                       # GL AR control nets to zero
    assert si.get_outstanding("CLI", CALLER)["data"]["outstanding_paise"] == 0  # excluded
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]  # ledger still balanced


def test_cancel_is_not_duplicated_on_retry(monkeypatch):
    # Idempotency: if the status flip failed after the reversal posted, a retry must
    # NOT post a second reversal. Simulate by re-driving cancel after forcing status
    # back to issued (the reversal already exists).
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)
    issue_jrnl = _invoice(db, inv_id)["journal_entry_id"]
    assert si.cancel_invoice(inv_id, CALLER)["success"] is True
    _invoice(db, inv_id)["status"] = "issued"                 # pretend the flip was lost
    assert si.cancel_invoice(inv_id, CALLER)["success"] is True
    reversals = [e for e in db.rows("journal_entries") if e.get("reversal_of") == issue_jrnl]
    assert len(reversals) == 1                                # still exactly one
    assert _ar(db) == 0


def test_cannot_cancel_invoice_with_receipt_applied(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)
    # A genuine receipt settles part of the invoice (paid_paise > 0).
    rsvc.create_receipt_core(FIRM, {
        "client_id": "CLI", "customer_id": "CUST1", "receipt_date": "2025-06-10",
        "amount_paise": 50000, "allocations": [{"sales_invoice_id": inv_id, "allocated_paise": 50000}],
    }, CALLER, db)
    assert _invoice(db, inv_id)["paid_paise"] == 50000
    with pytest.raises(HTTPException) as ex:
        si.cancel_invoice(inv_id, CALLER)
    assert ex.value.status_code == 409
    # Nothing reversed, invoice not cancelled.
    assert _invoice(db, inv_id)["status"] != "cancelled"
    assert not [e for e in db.rows("journal_entries") if e.get("reversal_of")]


def test_cannot_cancel_invoice_with_credit_note_applied(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)
    cnrow = db.seed("credit_notes", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "sales_invoice_id": inv_id,
        "credit_note_no": "CN-1", "credit_note_date": "2025-06-05", "status": "draft",
        "taxable_amount_paise": 40000, "cgst_paise": 3600, "sgst_paise": 3600, "igst_paise": 0,
        "total_paise": 47200, "is_interstate": False,
    })
    assert cn.issue_credit_note(cnrow["id"], CALLER)["success"] is True
    assert _invoice(db, inv_id)["credited_paise"] == 47200
    with pytest.raises(HTTPException) as ex:
        si.cancel_invoice(inv_id, CALLER)
    assert ex.value.status_code == 409
    assert _invoice(db, inv_id)["status"] != "cancelled"


def test_cannot_cancel_draft_invoice(monkeypatch):
    db = _setup(monkeypatch)
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "invoice_no": "INV-DRAFT", "invoice_date": "2025-06-01", "status": "draft",
        "total_paise": 118000, "taxable_amount_paise": 100000,
        "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0,
        "paid_paise": 0, "credited_paise": 0,
    })
    with pytest.raises(HTTPException) as ex:
        si.cancel_invoice(inv["id"], CALLER)
    assert ex.value.status_code == 422


def test_cannot_cancel_already_cancelled_invoice(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    assert si.cancel_invoice(inv_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        si.cancel_invoice(inv_id, CALLER)
    assert ex.value.status_code == 422
