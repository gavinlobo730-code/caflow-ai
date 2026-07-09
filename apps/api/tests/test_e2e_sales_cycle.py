"""
Phase 5.2 WS-1 — Sales cycle E2E.

Drives the REAL endpoints through the full lifecycle against one shared in-memory
DB and asserts the ACCOUNTING outcome at each step, not just HTTP success:

  create_invoice (draft) → issue_invoice (posts journal) → create_receipt (settles AR)

Reconciliation asserted:
  * issued invoice posts a balanced journal (Dr AR / Cr Sales + GST) — trial
    balance ties out;
  * AR account carries the invoice total, then nets to zero after full receipt;
  * Bank account is debited by the cash received.

Negative tenant-isolation legs:
  * a foreign-firm user cannot issue another firm's invoice (404, no journal);
  * a receipt cannot allocate to a foreign-firm invoice (422, no AR mutation).
"""
import pytest
from fastapi import HTTPException

from models.invoices import SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    import routers.receipts as rc
    import services.receipt_service as rs
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, rc, rs])
    # Client in state 27 (GSTIN prefix), customer also 27 ⇒ intra-state ⇒ CGST+SGST.
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27",
                          "gstin": "27XYZAB5678C1Z2", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    return si, rc, rs, db


def _invoice_in(qty=1, rate_paise=1_000_000, gst=18.0, invoice_no="SC-001"):
    return SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        due_date="2026-05-10", invoice_no=invoice_no,
        lines=[InvoiceLineIn(description="Consulting", hsn_sac="9982",
                             quantity=qty, rate_paise=rate_paise, gst_rate_percent=gst)],
    )


def test_sales_cycle_full_lifecycle_reconciles(monkeypatch):
    si, rc, rs, db = _setup(monkeypatch)

    # 1) Create draft invoice — GST auto-computed (₹10,000 @ 18% intra-state).
    resp = si.create_invoice(_invoice_in(), CALLER)
    assert resp["success"] is True, resp
    inv = resp["data"]
    inv_id = inv["id"]
    assert inv["taxable_amount_paise"] == 1_000_000
    assert inv["cgst_paise"] == 90_000 and inv["sgst_paise"] == 90_000
    assert inv["igst_paise"] == 0
    assert inv["total_paise"] == 1_180_000
    assert inv["status"] == "draft" and inv["paid_paise"] == 0

    # No journal yet (draft is off-books).
    assert trial_balance(db, FIRM, "CLI") == {"total_debit_paise": 0, "total_credit_paise": 0}

    # 2) Issue — posts the balanced journal Dr AR / Cr Sales + CGST + SGST.
    resp = si.issue_invoice(inv_id, CALLER)
    assert resp["success"] is True, resp
    assert resp["data"]["status"] == "issued"
    assert resp["data"].get("journal_entry_id")

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 1_180_000  # balanced
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 1_180_000          # Dr AR = total
    assert account_balance(db, coa_id(db, FIRM, "revenue")) == -1_000_000    # Cr Sales = taxable
    assert account_balance(db, coa_id(db, FIRM, "gst_cgst")) == -90_000
    assert account_balance(db, coa_id(db, FIRM, "gst_sgst")) == -90_000

    # 3) Receipt for the full amount, allocated to the invoice — settles AR.
    resp = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id="CUST", receipt_date="2026-04-20",
        amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv_id, allocated_paise=1_180_000)],
    ), CALLER)
    assert resp["success"] is True, resp

    paid_inv = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert paid_inv["paid_paise"] == 1_180_000
    assert paid_inv["status"] == "paid"

    # Ledger after receipt: still balanced; AR nets to zero; Bank debited by cash.
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 2_360_000
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0                  # AR cleared
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 1_180_000        # Dr Bank = cash


def test_sales_cycle_partial_receipt_leaves_partially_paid(monkeypatch):
    si, rc, rs, db = _setup(monkeypatch)
    inv_id = si.create_invoice(_invoice_in(), CALLER)["data"]["id"]
    si.issue_invoice(inv_id, CALLER)

    resp = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id="CUST", receipt_date="2026-04-21",
        amount_paise=600_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv_id, allocated_paise=600_000)],
    ), CALLER)
    assert resp["success"] is True, resp

    inv = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert inv["paid_paise"] == 600_000 and inv["status"] == "partially_paid"
    # AR remaining = 1,180,000 - 600,000.
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 580_000


def test_sales_cycle_interstate_uses_igst(monkeypatch):
    si, rc, rs, db = _setup(monkeypatch)
    # Customer in a different state (29) than client (27) ⇒ inter-state ⇒ IGST.
    db.table("customers").update({"state_code": "29"}).eq("id", "CUST").execute()
    inv = si.create_invoice(_invoice_in(), CALLER)["data"]
    assert inv["igst_paise"] == 180_000
    assert inv["cgst_paise"] == 0 and inv["sgst_paise"] == 0
    assert inv["total_paise"] == 1_180_000


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_sales_cycle_foreign_firm_cannot_issue(monkeypatch):
    si, rc, rs, db = _setup(monkeypatch)
    inv_id = si.create_invoice(_invoice_in(), CALLER)["data"]["id"]

    with pytest.raises(HTTPException) as ei:
        si.issue_invoice(inv_id, OTHER)            # Firm B tries to issue Firm A's invoice
    assert ei.value.status_code == 404

    inv = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert inv["status"] == "draft"                # untouched
    assert trial_balance(db, FIRM, "CLI")["total_debit_paise"] == 0  # no journal posted


def test_sales_cycle_receipt_cannot_allocate_foreign_invoice(monkeypatch):
    si, rc, rs, db = _setup(monkeypatch)
    inv_id = si.create_invoice(_invoice_in(), CALLER)["data"]["id"]
    si.issue_invoice(inv_id, CALLER)

    # Firm B records a receipt for ITS client but allocates Firm A's invoice id.
    with pytest.raises(HTTPException) as ei:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id="CUST", receipt_date="2026-04-22",
            amount_paise=1_180_000,
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv_id, allocated_paise=1_180_000)],
        ), OTHER)
    assert ei.value.status_code == 422            # F1: foreign invoice rejected

    inv = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert inv["paid_paise"] == 0                 # AR not mutated
