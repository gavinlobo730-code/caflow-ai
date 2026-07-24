"""
Task #237 — AR/AP money-movement gaps round 3:

  1. Cross-client customer/vendor resolution — sales_invoices.py and
     purchase_bills.py resolved a customer/vendor_id by (firm_id, id) alone,
     not also client_id, so a batch/CSV row (or a crafted single-document
     request) naming a customer/vendor that belongs to a DIFFERENT client of
     the SAME firm silently invoiced/billed using that other client's
     party — wrong GSTIN/PAN/state_code/credit_days on the document, and a
     cross-client data leak within the firm.
  2. Line quantity had no positivity validator (InvoiceLineIn/PurchaseBillLineIn).
  3. sales_invoices.py / purchase_bills.py / credit_notes.py CREATE paths didn't
     reject a non-positive computed total (debit_notes.py's own CREATE path,
     and credit_notes.py's own UPDATE path, already did).
  4. debit_notes.py's purchase-debit-note issuance used 2-way status logic
     ("paid" / unchanged) instead of the 3-way logic ("paid" / "partially_paid"
     / unchanged) its 3 sibling note types use.
  5. credit_notes.py's create_credit_note read the linked sales_invoice's
     is_interstate with no firm_id filter — a cross-firm data leak.
  6. FXRevaluationService._open_receivables/_open_payables didn't fold
     debit_note_paise/credit_note_paise into open FX exposure, understating
     the revaluation base for any invoice/bill with a note applied.
  7. purchase_bills.create_bill_from_document's AI-extracted line_total_paise
     used rate_paise alone, ignoring quantity.
  8. purchase_payments.py never cross-checked the supplied vendor_id against
     the linked purchase_bill's own vendor (domestic + foreign paths).
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.invoices import (
    InvoiceLineIn, PurchaseBillLineIn, SalesInvoiceIn, PurchaseBillIn,
    PurchasePaymentIn, BillFromDocumentIn,
)
from models.parties import CustomerIn, VendorIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
OTHER_FIRM = "FIRM-B"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


# =============================================================================
# 2. quantity must be positive (pure Pydantic model tests — no DB)
# =============================================================================

def test_invoice_line_rejects_zero_quantity():
    with pytest.raises(ValidationError):
        InvoiceLineIn(description="x", rate_paise=100, quantity=0, service_catalogue_id="SVC-1")


def test_invoice_line_rejects_negative_quantity():
    with pytest.raises(ValidationError):
        InvoiceLineIn(description="x", rate_paise=100, quantity=-1, service_catalogue_id="SVC-1")


def test_purchase_bill_line_rejects_zero_quantity():
    with pytest.raises(ValidationError):
        PurchaseBillLineIn(description="x", rate_paise=100, quantity=0, service_catalogue_id="SVC-1")


def test_purchase_bill_line_accepts_positive_quantity():
    ln = InvoiceLineIn(description="x", rate_paise=100, quantity=0.5, service_catalogue_id="SVC-1")
    assert ln.quantity == 0.5


# =============================================================================
# Shared harness
# =============================================================================

def _setup(monkeypatch):
    import routers.sales_invoices as si
    import routers.purchase_bills as pb
    import routers.credit_notes as cn
    import routers.debit_notes as dn
    import routers.customers as cu
    import routers.vendors as ve
    import routers.purchase_payments as pp
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb, cn, dn, cu, ve, pp])
    db.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    db.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    db.seed("clients", {"id": "CLI-A", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    db.seed("clients", {"id": "CLI-B", "firm_id": FIRM, "gstin": "29BBBBB0000B1Z5"})
    seed_standard_coa(db, FIRM, "CLI-A")
    seed_standard_coa(db, FIRM, "CLI-B")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI-A",
                                  "name": "Consulting", "kind": "service"})
    db.seed("service_catalogue", {"id": "SVC-2", "firm_id": FIRM, "client_id": "CLI-B",
                                  "name": "Consulting", "kind": "service"})
    return si, pb, cn, dn, cu, ve, pp, db


def _line(svc="SVC-1", rate=1_000_000, gst=18.0):
    return InvoiceLineIn(service_catalogue_id=svc, description="Consulting", hsn_sac="9982",
                         quantity=1, rate_paise=rate, gst_rate_percent=gst).model_dump()


# =============================================================================
# 1a. Cross-client customer resolution — sales_invoices.py
# =============================================================================

def test_create_invoice_rejects_customer_from_different_client(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    cust_b = cu.create_customer(CustomerIn(client_id="CLI-B", name="B Buyer", state_code="29"), CALLER)["data"]

    with pytest.raises(HTTPException) as ei:
        si.create_invoice(SalesInvoiceIn(
            client_id="CLI-A", customer_id=cust_b["id"], invoice_date="2026-06-01",
            invoice_no="INV-1", lines=[_line()],
        ), CALLER)
    assert ei.value.status_code == 422
    assert "not found" in ei.value.detail.lower()


def test_bulk_create_invoices_rejects_customer_from_different_client(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    cust_a = cu.create_customer(CustomerIn(client_id="CLI-A", name="A Buyer", state_code="27"), CALLER)["data"]
    cust_b = cu.create_customer(CustomerIn(client_id="CLI-B", name="B Buyer", state_code="29"), CALLER)["data"]

    class _Payload:
        def __init__(self, invoices): self.invoices = invoices

    good = {"client_id": "CLI-A", "customer_id": cust_a["id"], "invoice_date": "2026-06-01",
            "invoice_no": "OK-1", "lines": [_line()]}
    # Cross-client: bill CLI-A's invoice using CLI-B's own customer id.
    bad = {"client_id": "CLI-A", "customer_id": cust_b["id"], "invoice_date": "2026-06-01",
           "invoice_no": "BAD-1", "lines": [_line()]}

    resp = si.bulk_create_invoices(_Payload([good, bad]), CALLER)
    assert resp["success"] is True
    created_nos = {inv["invoice_no"] for inv in resp["data"]["created"]}
    assert created_nos == {"OK-1"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["invoice_no"] == "BAD-1"


# =============================================================================
# 1b. Cross-client vendor resolution — purchase_bills.py
# =============================================================================

def test_create_purchase_bill_rejects_vendor_from_different_client(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    vend_b = ve.create_vendor(VendorIn(client_id="CLI-B", name="B Supplier", state_code="29"), CALLER)["data"]

    with pytest.raises(HTTPException) as ei:
        pb.create_purchase_bill(PurchaseBillIn(
            client_id="CLI-A", vendor_id=vend_b["id"], bill_date="2026-06-01", bill_no="BILL-1",
            lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000,
                                      quantity=1, gst_rate_percent=18.0)],
        ), CALLER)
    assert ei.value.status_code == 404


def test_bulk_create_purchase_bills_rejects_vendor_from_different_client(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    vend_a = ve.create_vendor(VendorIn(client_id="CLI-A", name="A Supplier", state_code="27"), CALLER)["data"]
    vend_b = ve.create_vendor(VendorIn(client_id="CLI-B", name="B Supplier", state_code="29"), CALLER)["data"]

    class _Payload:
        def __init__(self, bills): self.bills = bills

    def _bill_dict(vendor_id, bill_no):
        return {"client_id": "CLI-A", "vendor_id": vendor_id, "bill_date": "2026-06-01", "bill_no": bill_no,
                "lines": [PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000,
                                             quantity=1, gst_rate_percent=18.0).model_dump()]}

    good = _bill_dict(vend_a["id"], "OK-1")
    bad = _bill_dict(vend_b["id"], "BAD-1")  # CLI-B's own vendor used against CLI-A's bill

    resp = pb.bulk_create_purchase_bills(_Payload([good, bad]), CALLER)
    assert resp["success"] is True
    created_nos = {b["bill_no"] for b in resp["data"]["created"]}
    assert created_nos == {"OK-1"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["bill_no"] == "BAD-1"


# =============================================================================
# 3. non-positive computed total rejected on CREATE
# =============================================================================

def test_create_invoice_rejects_zero_total(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI-A", name="Buyer", state_code="27"), CALLER)["data"]
    with pytest.raises(HTTPException) as ei:
        si.create_invoice(SalesInvoiceIn(
            client_id="CLI-A", customer_id=cust["id"], invoice_date="2026-06-01", invoice_no="ZERO-1",
            lines=[_line(rate=0, gst=0.0)],
        ), CALLER)
    assert ei.value.status_code == 422
    assert "positive" in ei.value.detail.lower()


def test_create_purchase_bill_rejects_zero_total(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI-A", name="Supplier", state_code="27"), CALLER)["data"]
    with pytest.raises(HTTPException) as ei:
        pb.create_purchase_bill(PurchaseBillIn(
            client_id="CLI-A", vendor_id=vend["id"], bill_date="2026-06-01", bill_no="ZERO-1",
            lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=0,
                                      quantity=1, gst_rate_percent=0.0)],
        ), CALLER)
    assert ei.value.status_code == 422
    assert "positive" in ei.value.detail.lower()


def test_create_credit_note_rejects_zero_total(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI-A", name="Buyer", state_code="27"), CALLER)["data"]
    with pytest.raises(HTTPException) as ei:
        cn.create_credit_note(cn.CreditNoteIn(
            client_id="CLI-A", customer_id=cust["id"], credit_note_date="2026-06-01",
            lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=0,
                                 quantity=1, gst_rate_percent=0.0)],
        ), CALLER)
    assert ei.value.status_code == 422
    assert "positive" in ei.value.detail.lower()


# =============================================================================
# 4. debit_notes.py: 3-way status logic on issuance (parity with siblings)
# =============================================================================

def test_issue_debit_note_sets_partially_paid_when_not_fully_relieved(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI-A", name="Supplier", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI-A", vendor_id=vend["id"], bill_date="2026-06-01", bill_no="B-1",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100_00000,
                                  quantity=1, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)

    # Debit-note only a THIRD of the bill's taxable value — the bill must be
    # "partially_paid" afterward, not silently left at its pre-issue status
    # (the 2-way-logic bug: "paid" if fully relieved, else UNCHANGED).
    note = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI-A", vendor_id=vend["id"], debit_note_date="2026-06-05",
        purchase_bill_id=bill["id"],
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="return", rate_paise=30_00000,
                             quantity=1, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    result = dn.issue_debit_note(note["id"], CALLER)
    assert result["success"] is True

    bill_row = next(r for r in db.rows("purchase_bills") if r["id"] == bill["id"])
    assert bill_row["status"] == "partially_paid"


def test_issue_debit_note_still_sets_paid_when_fully_relieved(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI-A", name="Supplier", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI-A", vendor_id=vend["id"], bill_date="2026-06-01", bill_no="B-2",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100_00000,
                                  quantity=1, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)

    note = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI-A", vendor_id=vend["id"], debit_note_date="2026-06-05",
        purchase_bill_id=bill["id"],
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="return", rate_paise=100_00000,
                             quantity=1, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    result = dn.issue_debit_note(note["id"], CALLER)
    assert result["success"] is True

    bill_row = next(r for r in db.rows("purchase_bills") if r["id"] == bill["id"])
    assert bill_row["status"] == "paid"


# =============================================================================
# 5. credit_notes.py create: no cross-firm is_interstate leak
# =============================================================================

def test_create_credit_note_does_not_leak_interstate_from_other_firms_invoice(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI-A", name="Buyer", state_code="27"), CALLER)["data"]
    # An invoice belonging to a DIFFERENT firm, interstate=True.
    db.seed("client_sales_invoices", {
        "id": "FOREIGN-INV", "firm_id": OTHER_FIRM, "client_id": "OTHER-CLI",
        "is_interstate": True, "status": "issued", "deleted_at": None,
    })

    result = cn.create_credit_note(cn.CreditNoteIn(
        client_id="CLI-A", customer_id=cust["id"], credit_note_date="2026-06-01",
        sales_invoice_id="FOREIGN-INV",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000,
                             quantity=1, gst_rate_percent=18.0)],
    ), CALLER)
    assert result["success"] is True
    # Must NOT have picked up the foreign firm's invoice's is_interstate=True —
    # the lookup couldn't see it (firm-scoped), so it stays at the default.
    assert result["data"]["is_interstate"] is False
    assert result["data"]["cgst_paise"] > 0 and result["data"]["igst_paise"] == 0


# =============================================================================
# 6. FX revaluation folds debit_note_paise / credit_note_paise
# =============================================================================

def test_open_receivables_folds_debit_note_paise():
    from domain.currency.fx_revaluation_service import FXRevaluationService
    db = FakeDB()
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": "F1", "client_id": "C1",
        "txn_currency": "USD", "exchange_rate": "83", "total_paise": 830000,
        "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 100000,
        "txn_total": 10000, "paid_txn": 0, "status": "issued", "invoice_date": "2026-06-01",
    })
    out = FXRevaluationService()._open_receivables(db, "F1", "C1", "2026-06-30")
    assert len(out) == 1
    _ccy, _foreign_out, base_out = out[0]
    assert base_out == 830000 + 100000  # total + debit notes − paid − credited


def test_open_payables_folds_credit_note_paise():
    from domain.currency.fx_revaluation_service import FXRevaluationService
    db = FakeDB()
    db.seed("purchase_bills", {
        "id": "BILL1", "firm_id": "F1", "client_id": "C1",
        "txn_currency": "USD", "exchange_rate": "83", "net_payable_paise": 830000,
        "paid_paise": 0, "debited_paise": 0, "credit_note_paise": 50000,
        "txn_net_payable": 10000, "paid_txn": 0, "status": "received", "bill_date": "2026-06-01",
    })
    out = FXRevaluationService()._open_payables(db, "F1", "C1", "2026-06-30")
    assert len(out) == 1
    _ccy, _foreign_out, base_out = out[0]
    assert base_out == 830000 + 50000  # net_payable + credit notes − paid − debited


# =============================================================================
# 7. AI-extracted line_total_paise must be quantity-aware
# =============================================================================

def test_create_bill_from_document_line_total_uses_taxable_amount_not_rate(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    result = pb.create_bill_from_document(BillFromDocumentIn(
        client_id="CLI-A",
        extracted_data={
            "invoice_no": "AI-1", "invoice_date": "2026-06-01",
            "taxable_amount_paise": 300000, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
            "total_paise": 300000,
            "line_items": [
                {"description": "Widget", "hsn_sac": "1234", "rate_paise": 100000,
                 "quantity": 3, "taxable_amount_paise": 300000},
            ],
        },
    ), CALLER)
    assert result["success"] is True
    lines = [r for r in db.rows("purchase_bill_lines") if r["bill_id"] == result["data"]["id"]]
    assert len(lines) == 1
    # 3 x rate_paise(100000) = 300000 taxable -- NOT rate_paise (100000) alone.
    assert lines[0]["line_total_paise"] == 300000


# =============================================================================
# 8. purchase_payments.py: payment's vendor_id must match the bill's own vendor
# =============================================================================

def test_create_purchase_payment_rejects_bill_belonging_to_different_vendor(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    vend1 = ve.create_vendor(VendorIn(client_id="CLI-A", name="Vendor 1", state_code="27"), CALLER)["data"]
    vend2 = ve.create_vendor(VendorIn(client_id="CLI-A", name="Vendor 2", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI-A", vendor_id=vend1["id"], bill_date="2026-06-01", bill_no="B-1",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000,
                                  quantity=1, gst_rate_percent=18.0)],
    ), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)

    with pytest.raises(HTTPException) as ei:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI-A", vendor_id=vend2["id"], payment_date="2026-06-10",
            amount_paise=50000, purchase_bill_id=bill["id"],
        ), CALLER)
    assert ei.value.status_code == 422
    assert "vendor" in ei.value.detail.lower()

    bill_row = next(r for r in db.rows("purchase_bills") if r["id"] == bill["id"])
    assert bill_row.get("paid_paise") in (0, None)  # untouched


def test_create_foreign_purchase_payment_rejects_bill_belonging_to_different_vendor(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = _setup(monkeypatch)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    db.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    db.table("clients").update({"functional_currency": "INR", "multi_currency_enabled": True}) \
        .eq("id", "CLI-A").execute()
    vend1 = ve.create_vendor(VendorIn(client_id="CLI-A", name="Vendor 1", state_code="27"), CALLER)["data"]
    vend2 = ve.create_vendor(VendorIn(client_id="CLI-A", name="Vendor 2", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI-A", vendor_id=vend1["id"], bill_date="2026-06-01", bill_no="USD-B-1",
        currency="USD", exchange_rate="83.0",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="x", rate_paise=100000,
                                  quantity=1, gst_rate_percent=0.0)],
    ), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)

    with pytest.raises(HTTPException) as ei:
        pp.create_purchase_payment(PurchasePaymentIn(
            client_id="CLI-A", vendor_id=vend2["id"], payment_date="2026-06-10",
            amount_paise=50000, purchase_bill_id=bill["id"], currency="USD", exchange_rate="84.0",
        ), CALLER)
    assert ei.value.status_code == 422
    assert "vendor" in ei.value.detail.lower()
