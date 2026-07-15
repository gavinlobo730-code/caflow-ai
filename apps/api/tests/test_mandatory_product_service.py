"""
Product/Service must be linked on every line item — no exceptions (explicit CA
directive: "without adding the product and service we cant save it"). Backend
enforcement lives at the Pydantic layer so it fires identically no matter which
document type or generator builds the line:

  * InvoiceLineIn   -> Sales Invoices, Credit Notes, Debit Notes
  * PurchaseBillLineIn -> Purchase Bills
  * RecurringLineIn -> Recurring Invoice Templates (routers/recurring_invoices.py)
  * BillingScheduleIn.service_id -> firm retainer/fee billing (routers/billing.py)

Both auto-generation paths (recurring templates, billing schedules) reuse
InvoiceLineIn under the hood, so the same guarantee covers CA-initiated AND
system-generated documents alike (migration 206 backs this with NOT NULL + FK
at the DB layer too).
"""
import pydantic
import pytest

from models.invoices import InvoiceLineIn, PurchaseBillLineIn
from routers.recurring_invoices import RecurringLineIn
from routers.billing import BillingScheduleIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa


def _line_kwargs():
    return dict(description="Consulting", hsn_sac="9982", quantity=1,
                rate_paise=100000, gst_rate_percent=18.0)


# ── InvoiceLineIn (Sales Invoices, Credit Notes, Debit Notes) ────────────────

def test_invoice_line_without_service_catalogue_id_rejected():
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        InvoiceLineIn(**_line_kwargs())


def test_invoice_line_with_blank_service_catalogue_id_rejected():
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        InvoiceLineIn(service_catalogue_id="   ", **_line_kwargs())


def test_invoice_line_with_service_catalogue_id_accepted():
    line = InvoiceLineIn(service_catalogue_id="SVC-1", **_line_kwargs())
    assert line.service_catalogue_id == "SVC-1"


# ── PurchaseBillLineIn (Purchase Bills) ───────────────────────────────────────

def test_purchase_bill_line_without_service_catalogue_id_rejected():
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        PurchaseBillLineIn(**_line_kwargs())


def test_purchase_bill_line_with_blank_service_catalogue_id_rejected():
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        PurchaseBillLineIn(service_catalogue_id="", **_line_kwargs())


def test_purchase_bill_line_with_service_catalogue_id_accepted():
    line = PurchaseBillLineIn(service_catalogue_id="SVC-1", **_line_kwargs())
    assert line.service_catalogue_id == "SVC-1"


# ── RecurringLineIn (Recurring Invoice Templates) ─────────────────────────────

def test_recurring_line_without_service_catalogue_id_rejected():
    # service_catalogue_id has no default, so an omitted field trips Pydantic's
    # own "Field required" check before the custom validator ever runs — the
    # blank-string case below is what exercises the custom message.
    with pytest.raises(pydantic.ValidationError, match="Field required"):
        RecurringLineIn(description="Retainer", rate_paise=100000)


def test_recurring_line_with_blank_service_catalogue_id_rejected():
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        RecurringLineIn(service_catalogue_id="", description="Retainer", rate_paise=100000)


def test_recurring_line_with_service_catalogue_id_accepted():
    line = RecurringLineIn(service_catalogue_id="SVC-1", description="Retainer", rate_paise=100000)
    assert line.service_catalogue_id == "SVC-1"


# ── BillingScheduleIn (firm retainer/fee billing) ─────────────────────────────

def test_billing_schedule_without_service_id_rejected():
    # service_id has no default, so an omitted field trips Pydantic's own
    # "Field required" check before the custom validator ever runs — the
    # blank-string case below is what exercises the custom message.
    with pytest.raises(pydantic.ValidationError, match="Field required"):
        BillingScheduleIn(client_id="CLI", arrangement="retainer", cadence="monthly", amount_paise=100000)


def test_billing_schedule_with_blank_service_id_rejected():
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        BillingScheduleIn(client_id="CLI", arrangement="retainer", cadence="monthly",
                          amount_paise=100000, service_id="  ")


def test_billing_schedule_with_service_id_accepted():
    sched = BillingScheduleIn(client_id="CLI", arrangement="retainer", cadence="monthly",
                              amount_paise=100000, service_id="SVC-1")
    assert sched.service_id == "SVC-1"


# ── CSV bulk-import: an unresolved Product/Service is a per-row error, not an
# aborted batch (Task #93 — the resolver step is a courtesy, not a hard gate;
# this is the actual backstop for a row the CA leaves unresolved). ──────────

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _bulk_setup(monkeypatch):
    import routers.sales_invoices as si
    import routers.purchase_bills as pb
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27", "is_active": True})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier",
                        "state_code": "27", "tds_applicable": False, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    return si, pb, db


class _BulkPayload:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_csv_bulk_import_unresolved_product_service_is_per_row_error_sales(monkeypatch):
    si, pb, db = _bulk_setup(monkeypatch)
    good = dict(client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="BULK-OK",
               lines=[{"service_catalogue_id": "SVC-1", "description": "Consulting",
                       "quantity": 1, "rate_paise": 100000, "gst_rate_percent": 18.0}])
    unresolved = dict(client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="BULK-UNRESOLVED",
                      lines=[{"description": "Consulting",  # no service_catalogue_id — CA left it unresolved
                              "quantity": 1, "rate_paise": 100000, "gst_rate_percent": 18.0}])
    resp = si.bulk_create_invoices(_BulkPayload(invoices=[good, unresolved]), CALLER)
    assert resp["success"] is True
    assert [i["invoice_no"] for i in resp["data"]["created"]] == ["BULK-OK"]   # good row unaffected
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["invoice_no"] == "BULK-UNRESOLVED"
    assert "Product/Service is required" in resp["data"]["errors"][0]["error"]


def test_csv_bulk_import_unresolved_product_service_is_per_row_error_purchase(monkeypatch):
    si, pb, db = _bulk_setup(monkeypatch)
    good = dict(client_id="CLI", vendor_id="VEND1", bill_date="2026-04-10", bill_no="BULK-OK",
               lines=[{"service_catalogue_id": "SVC-1", "description": "Materials",
                       "quantity": 1, "rate_paise": 100000, "gst_rate_percent": 18.0}])
    unresolved = dict(client_id="CLI", vendor_id="VEND1", bill_date="2026-04-10", bill_no="BULK-UNRESOLVED",
                      lines=[{"description": "Materials",  # no service_catalogue_id
                              "quantity": 1, "rate_paise": 100000, "gst_rate_percent": 18.0}])
    resp = pb.bulk_create_purchase_bills(_BulkPayload(bills=[good, unresolved]), CALLER)
    assert resp["success"] is True
    assert [b["bill_no"] for b in resp["data"]["created"]] == ["BULK-OK"]
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["bill_no"] == "BULK-UNRESOLVED"
    assert "Product/Service is required" in resp["data"]["errors"][0]["error"]
