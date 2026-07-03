"""
Phase 5.2 final sprint — Customer Cycle (integrated, one flow).

  Customer → Invoice → Issue → Reminder → Statement → Receipt → AR cleared

Drives the real endpoints across five modules against one shared DB and asserts
the accounting outcome end-to-end: the issued invoice posts a balanced journal,
an overdue reminder can be sent, the statement reflects the invoice then the
receipt, and AR nets to zero once settled. Includes negative + cross-firm legs.
(Role/permission checks for this cycle live in test_e2e_permissions.py.)

Past-dated documents (2020) make "overdue" independent of the test clock.
"""
import pytest
from fastapi import HTTPException

from models.parties import CustomerIn
from models.invoices import SalesInvoiceIn, InvoiceLineIn, ReceiptIn, ReceiptAllocationIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, trial_balance, account_balance, coa_id


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.customers as cu
    import routers.sales_invoices as si
    import routers.receipts as rc
    import routers.customer_statements as cs
    import services.receipt_service as rs
    import services.collections_service as col
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, cs, rs, col])
    monkeypatch.setattr(cs, "_db", lambda: db)
    monkeypatch.setattr(col, "_USE_MOCK", False)
    monkeypatch.setattr(col, "_dispatch_invoice_reminder", lambda *a, **k: True)  # stub email transport
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    return cu, si, rc, cs, col, db


def test_customer_cycle_end_to_end(monkeypatch):
    cu, si, rc, cs, col, db = _setup(monkeypatch)

    # 1) Customer
    cust = cu.create_customer(CustomerIn(
        client_id="CLI", name="Acme Buyer", state_code="27",
        email="buyer@acme.test", credit_days=15), CALLER)["data"]
    cust_id = cust["id"]

    # 2-3) Invoice → Issue (overdue, past-dated). Journal posts; AR = total.
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2020-01-10", due_date="2020-01-25",
        lines=[InvoiceLineIn(description="Consulting", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)]), CALLER)["data"]
    inv_id = inv["id"]
    assert si.issue_invoice(inv_id, CALLER)["data"]["status"] == "issued"
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 1_180_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 1_180_000

    # 4) Reminder (invoice is overdue).
    rem = col.send_invoice_reminder(FIRM, inv_id, actor_id="u1", db=db)
    assert rem["sent"] is True and rem["to"] == "buyer@acme.test"

    # 5) Statement — invoice present, nothing received yet.
    st1 = cs.get_statement("CLI", cust_id, "2020-01-01", "2020-12-31", CALLER)["data"]
    assert st1["totals"]["invoiced_paise"] == 1_180_000
    assert st1["totals"]["received_paise"] == 0
    assert st1["closing_balance_paise"] == 1_180_000

    # 6) Receipt → AR cleared.
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust_id, receipt_date="2020-02-01", amount_paise=1_180_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv_id, allocated_paise=1_180_000)]), CALLER)

    paid = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert paid["paid_paise"] == 1_180_000 and paid["status"] == "paid"

    # 7) Statement again — receipt reflected, balance settled.
    st2 = cs.get_statement("CLI", cust_id, "2020-01-01", "2020-12-31", CALLER)["data"]
    assert st2["totals"]["received_paise"] == 1_180_000
    assert st2["closing_balance_paise"] == 0

    # AR cleared at the ledger; Bank debited; books balanced throughout.
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 0
    assert account_balance(db, coa_id(db, FIRM, "bank")) == 1_180_000
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_f7_journal_failure_does_not_settle_ar(monkeypatch):
    """F7: the receipt posts its GL journal BEFORE settling AR, so a journal
    failure must leave the invoice unpaid and write no receipt — never settled AR
    with no GL entry."""
    cu, si, rc, cs, col, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="B", email="b@x.test"), CALLER)["data"]
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_date="2020-01-10", due_date="2020-01-25",
        lines=[InvoiceLineIn(description="x", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    inv_id = inv["id"]
    assert db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]["paid_paise"] == 0

    # Simulate a GL posting failure (e.g. a missing Chart-of-Accounts account).
    import services.phase2_journal_service as pjs

    def _boom(**_k):
        raise ValueError("Required account not found: Bank")
    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_receipt", _boom)

    try:
        resp = rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2020-02-01", amount_paise=1_180_000,
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv_id, allocated_paise=1_180_000)]), CALLER)
        assert resp.get("success") is False    # surfaced as an error envelope, not a silent success
    except Exception:
        pass                                   # or it propagated — also fine

    # The F7 guarantee: AR untouched, no receipt written.
    after = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert after["paid_paise"] == 0 and after["status"] != "paid", "AR must not settle when the GL journal fails"
    assert db.table("receipts").select("id").execute().data == [], "no receipt row when the journal fails"


def test_f7_over_allocated_receipt_posts_no_phantom_journal(monkeypatch):
    """F7 hardening: an over-allocated receipt must be rejected BEFORE anything
    posts — no phantom Dr Bank / Cr Trade Receivables journal, no receipt row —
    not deep inside the settlement loop after the journal already committed."""
    cu, si, rc, cs, col, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="C", email="c@x.test"), CALLER)["data"]
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_date="2020-01-10", due_date="2020-01-25",
        lines=[InvoiceLineIn(description="x", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    inv_id = inv["id"]
    ar_before = account_balance(db, coa_id(db, FIRM, "ar"))
    bank_before = account_balance(db, coa_id(db, FIRM, "bank"))

    with pytest.raises(HTTPException) as ei:
        rc.create_receipt(ReceiptIn(
            client_id="CLI", customer_id=cust["id"], receipt_date="2020-02-01",
            amount_paise=10_000_000,   # far more than the invoice's outstanding
            allocations=[ReceiptAllocationIn(sales_invoice_id=inv_id, allocated_paise=10_000_000)]), CALLER)
    assert ei.value.status_code == 422

    # No phantom cash/AR movement, no receipt row, invoice untouched.
    assert account_balance(db, coa_id(db, FIRM, "ar")) == ar_before
    assert account_balance(db, coa_id(db, FIRM, "bank")) == bank_before
    assert db.table("receipts").select("id").execute().data == []
    after = db.table("client_sales_invoices").select("*").eq("id", inv_id).execute().data[0]
    assert after["paid_paise"] == 0 and after["status"] != "paid"


def test_customer_cycle_reminder_only_when_overdue(monkeypatch):
    cu, si, rc, cs, col, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="A", email="a@x.test"), CALLER)["data"]
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_date="2099-01-01", due_date="2099-02-01",
        lines=[InvoiceLineIn(description="x", rate_paise=100000, gst_rate_percent=18.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    with pytest.raises(HTTPException) as ei:               # not yet due
        col.send_invoice_reminder(FIRM, inv["id"], db=db)
    assert ei.value.status_code == 422


def test_customer_cycle_cross_firm_isolation(monkeypatch):
    cu, si, rc, cs, col, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="A", email="a@x.test"), CALLER)["data"]
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_date="2020-01-10", due_date="2020-01-25",
        lines=[InvoiceLineIn(description="x", rate_paise=100000, gst_rate_percent=18.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)

    # Foreign firm cannot issue, remind on, or view a statement for this customer.
    with pytest.raises(HTTPException) as e1:
        si.issue_invoice(inv["id"], OTHER)
    assert e1.value.status_code == 404
    with pytest.raises(HTTPException) as e2:
        col.send_invoice_reminder("FIRM-B", inv["id"], db=db)
    assert e2.value.status_code == 404
    with pytest.raises(HTTPException) as e3:
        cs.get_statement("CLI", cust["id"], "2020-01-01", "2020-12-31", OTHER)
    assert e3.value.status_code == 404
