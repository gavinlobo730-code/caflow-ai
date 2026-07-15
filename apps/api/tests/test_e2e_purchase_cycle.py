"""
Phase 5.2 WS-1 — Purchase cycle E2E.

Drives the REAL endpoints through the full lifecycle against one shared DB:

  create_purchase_bill (draft, GST + TDS auto) → receive (posts journal) →
  create_purchase_payment (settles AP)

Reconciliation asserted:
  * TDS is deducted from the taxable value (IT Act §194J) ⇒ net_payable = total − TDS;
  * receiving posts a balanced journal (Dr Purchases + GST Input / Cr Trade
    Payables + TDS Payable) — trial balance ties out;
  * AP carries net_payable, then nets to zero after the vendor payment;
  * Bank is credited by the cash paid.

Negative tenant-isolation legs:
  * a foreign-firm user cannot receive or cancel another firm's bill (404, no journal).

Observation (documented in the coverage report, asserted here as current behaviour):
  PurchasePaymentIn carries no purchase_bill_id, so a payment is NOT linked to a
  bill and does NOT move the bill's status — AP is correct at the ledger level,
  but bill-level paid tracking is inert through the payments API (OOS-1 context).
"""
import pytest
from fastapi import HTTPException

from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch, tds_applicable=True):
    import routers.purchase_bills as pb
    import routers.purchase_payments as pp
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb, pp])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})  # state 27
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": tds_applicable,
                        "tds_section": "194J", "tds_rate_bps": 1000})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Audit Services", "kind": "service"})
    return pb, pp, db


def _bill_in(rate_paise=10_000_000, gst=18.0, bill_no="VINV-001"):
    return PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date="2026-04-05", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Audit services", hsn_sac="9982",
                                  quantity=1, rate_paise=rate_paise, gst_rate_percent=gst)],
    )


def test_purchase_cycle_full_lifecycle_reconciles(monkeypatch):
    pb, pp, db = _setup(monkeypatch)

    # 1) Create draft bill — ₹1,00,000 @ 18%, vendor TDS 194J @ 10%.
    resp = pb.create_purchase_bill(_bill_in(), CALLER)
    assert resp["success"] is True, resp
    bill = resp["data"]
    bill_id = bill["id"]
    assert bill["taxable_amount_paise"] == 10_000_000
    assert bill["cgst_paise"] == 900_000 and bill["sgst_paise"] == 900_000
    assert bill["total_paise"] == 11_800_000
    assert bill["tds_paise"] == 1_000_000                       # 10% of taxable
    assert bill["net_payable_paise"] == 10_800_000             # total − TDS
    assert bill["status"] == "draft"
    assert trial_balance(db, FIRM, "CLI") == {"total_debit_paise": 0, "total_credit_paise": 0}

    # 2) Receive — posts Dr Purchases + GST Input / Cr Trade Payables + TDS Payable.
    resp = pb.receive_purchase_bill(bill_id, CALLER)
    assert resp["success"] is True, resp
    assert resp["data"]["status"] == "received"

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 11_800_000  # balanced
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -10_800_000        # Cr Payables = net
    assert account_balance(db, coa_id(db, FIRM, "gst_input")) == 1_800_000   # Dr ITC = cgst+sgst
    assert account_balance(db, coa_id(db, FIRM, "tds_payable")) == -1_000_000  # Cr TDS payable

    # 3) Vendor payment of the net payable — Dr Trade Payables / Cr Bank.
    resp = pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id="VEND", payment_date="2026-04-25",
        amount_paise=10_800_000,
    ), CALLER)
    assert resp["success"] is True, resp

    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 22_600_000
    assert account_balance(db, coa_id(db, FIRM, "ap")) == 0                  # AP cleared
    assert account_balance(db, coa_id(db, FIRM, "bank")) == -10_800_000      # Cr Bank = cash paid

    # Documented gap: the payment did NOT move the bill status (no bill linkage).
    bill_now = db.table("purchase_bills").select("*").eq("id", bill_id).execute().data[0]
    assert bill_now["status"] == "received"


def test_purchase_cycle_no_tds_when_vendor_not_applicable(monkeypatch):
    pb, pp, db = _setup(monkeypatch, tds_applicable=False)
    bill = pb.create_purchase_bill(_bill_in(), CALLER)["data"]
    assert bill["tds_paise"] == 0
    assert bill["net_payable_paise"] == bill["total_paise"] == 11_800_000


def test_purchase_cycle_interstate_uses_igst(monkeypatch):
    pb, pp, db = _setup(monkeypatch)
    db.table("vendors").update({"state_code": "29"}).eq("id", "VEND").execute()  # vendor 29 vs client 27
    bill = pb.create_purchase_bill(_bill_in(), CALLER)["data"]
    assert bill["igst_paise"] == 1_800_000
    assert bill["cgst_paise"] == 0 and bill["sgst_paise"] == 0


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_purchase_cycle_foreign_firm_cannot_receive(monkeypatch):
    pb, pp, db = _setup(monkeypatch)
    bill_id = pb.create_purchase_bill(_bill_in(), CALLER)["data"]["id"]

    with pytest.raises(HTTPException) as ei:
        pb.receive_purchase_bill(bill_id, OTHER)
    assert ei.value.status_code == 404

    bill = db.table("purchase_bills").select("*").eq("id", bill_id).execute().data[0]
    assert bill["status"] == "draft"                                # untouched
    assert trial_balance(db, FIRM, "CLI")["total_debit_paise"] == 0  # no journal


def test_purchase_cycle_foreign_firm_cannot_cancel(monkeypatch):
    pb, pp, db = _setup(monkeypatch)
    bill_id = pb.create_purchase_bill(_bill_in(), CALLER)["data"]["id"]
    pb.receive_purchase_bill(bill_id, CALLER)

    with pytest.raises(HTTPException) as ei:
        pb.cancel_purchase_bill(bill_id, OTHER)
    assert ei.value.status_code == 404
    bill = db.table("purchase_bills").select("*").eq("id", bill_id).execute().data[0]
    assert bill["status"] == "received"                             # not cancelled
