"""Deleting a draft must not stop the client numbering documents (SALES-04),
and a firm's SECOND client must be able to raise one at all.

These go through the routers against the e2e harness, whose unique indexes are
now derived from services.numbering.NUMBER_SERIES — so a number the database
would reject is rejected here too, and reaches insert_with_number's retry
exactly as it does in production.

Against the previous code the three deletion tests fail — six identical
colliding attempts, then a 500. The two second-client tests PASS against it
here and are not the negative control for migration 350: the harness's unique
keys are derived from NUMBER_SERIES, so they already carry the widened scope.
What those two pin is that the router numbers per client, which is only half
the pair. The other half — that the DATABASE agrees — is
test_document_number_scope_matches_the_constraint_pg.py, and that one does
fail without the migration.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import routers.vendors as ve
from models.invoices import InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch, clients=("CLI",)):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, dn, pb, pcn, sdn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    for c in clients:
        db.seed("clients", {"id": c, "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2",
                            "financial_year_start": "2025-04-01"})
        db.seed("customers", {"id": f"CUST-{c}", "firm_id": FIRM, "client_id": c, "name": "Acme",
                              "is_active": True, "opening_balance_paise": 0})
        db.seed("vendors", {"id": f"VEND-{c}", "firm_id": FIRM, "client_id": c, "name": "Supplier",
                            "state_code": "27", "gstin": "27CCCCC2222C1Z5",
                            "tds_applicable": False, "opening_balance_paise": 0})
        seed_standard_coa(db, FIRM, c)
        db.seed("service_catalogue", {"id": f"SVC-{c}", "firm_id": FIRM, "client_id": c,
                                      "name": "Goods", "kind": "good"})
    return db


def _issued_invoice(db, client="CLI", no="INV-1"):
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": client, "customer_id": f"CUST-{client}",
        "invoice_no": no, "invoice_date": "2025-06-01", "status": "draft",
        "total_paise": 118000, "taxable_amount_paise": 100000,
        "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0,
        # A PLACE OF SUPPLY, because an invoice cannot be issued without one
        # (SALES-29, CGST Rule 46(n)). These rows are seeded straight into
        # the table rather than built by create_invoice, so they carry only
        # what is written here — a real invoice always has this column.
        "supply_state_code": "27",
        "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0, "is_interstate": False,
    })
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"]


def _received_bill(db, client="CLI", no="BILL-1"):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id=client, vendor_id=f"VEND-{client}", bill_date="2025-06-01", bill_no=no,
        lines=[PurchaseBillLineIn(description="mat", rate_paise=100000, quantity=1,
                                  gst_rate_percent=18.0, service_catalogue_id=f"SVC-{client}")],
    ), CALLER)
    assert res["success"] is True
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _new_credit_note(inv_id, client="CLI", rate=10000):
    res = cn.create_credit_note(cn.CreditNoteIn(
        client_id=client, customer_id=f"CUST-{client}", credit_note_date="2025-06-05",
        sales_invoice_id=inv_id, reason="Goods returned",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=rate,
                             gst_rate_percent=18.0, service_catalogue_id=f"SVC-{client}")],
    ), CALLER)
    assert res["success"] is True, res
    return res["data"]


# ───────────────────────── the wedge ─────────────────────────

def test_deleting_a_middle_draft_credit_note_leaves_the_series_usable(monkeypatch):
    db = _setup(monkeypatch)
    inv_id = _issued_invoice(db)

    first = _new_credit_note(inv_id)
    second = _new_credit_note(inv_id)
    third = _new_credit_note(inv_id)
    assert [n["credit_note_no"][-4:] for n in (first, second, third)] == ["0001", "0002", "0003"]

    assert cn.delete_credit_note(second["id"], CALLER)["success"] is True

    fourth = _new_credit_note(inv_id)
    assert fourth["credit_note_no"].endswith("0004")


def test_the_deleted_number_is_not_handed_out_again(monkeypatch):
    """0002's gap is permanent — the audit_log holds its create and delete, and
    two documents that were both CN-…-0002 is not a trail anybody can follow."""
    db = _setup(monkeypatch)
    inv_id = _issued_invoice(db)
    numbers = [_new_credit_note(inv_id)["credit_note_no"] for _ in range(3)]
    gone = numbers[1]

    target = next(r for r in db.rows("credit_notes") if r["credit_note_no"] == gone)
    assert cn.delete_credit_note(target["id"], CALLER)["success"] is True

    for _ in range(3):
        assert _new_credit_note(inv_id)["credit_note_no"] != gone


def test_deleting_a_middle_draft_debit_note_leaves_the_series_usable(monkeypatch):
    db = _setup(monkeypatch)
    bill_id = _received_bill(db)

    def make():
        res = dn.create_debit_note(dn.DebitNoteIn(
            client_id="CLI", vendor_id="VEND-CLI", debit_note_date="2025-06-05",
            purchase_bill_id=bill_id, reason="Short supply",
            lines=[InvoiceLineIn(description="short", quantity=1, rate_paise=5000,
                                 gst_rate_percent=18.0, service_catalogue_id="SVC-CLI")],
        ), CALLER)
        assert res["success"] is True, res
        return res["data"]

    made = [make() for _ in range(3)]
    assert dn.delete_debit_note(made[1]["id"], CALLER)["success"] is True
    assert make()["debit_note_no"].endswith("0004")


# ───────── the second client of a firm (migration 350) ─────────

def test_a_second_client_can_raise_a_sales_debit_note(monkeypatch):
    """sales_debit_notes was UNIQUE (firm_id, debit_note_no) from migration 210
    while its router numbered per client, so client B computed SDN-…-0001,
    the constraint rejected it, and all six retries recomputed the same 0001."""
    db = _setup(monkeypatch, clients=("CLI-A", "CLI-B"))

    def make(client):
        inv_id = _issued_invoice(db, client=client, no=f"INV-{client}")
        res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
            client_id=client, customer_id=f"CUST-{client}", debit_note_date="2025-06-05",
            sales_invoice_id=inv_id, reason="Undercharged",
            lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=5000,
                                 gst_rate_percent=18.0, service_catalogue_id=f"SVC-{client}")],
        ), CALLER)
        assert res["success"] is True, res
        return res["data"]["debit_note_no"]

    assert make("CLI-A").endswith("0001")
    assert make("CLI-B").endswith("0001")     # its own series, not the firm's


def test_a_second_client_can_raise_a_purchase_credit_note(monkeypatch):
    db = _setup(monkeypatch, clients=("CLI-A", "CLI-B"))

    def make(client):
        bill_id = _received_bill(db, client=client, no=f"BILL-{client}")
        res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
            client_id=client, vendor_id=f"VEND-{client}", credit_note_date="2025-06-05",
            purchase_bill_id=bill_id, reason="Vendor undercharged",
            lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=5000,
                                 gst_rate_percent=18.0, service_catalogue_id=f"SVC-{client}")],
        ), CALLER)
        assert res["success"] is True, res
        return res["data"]["credit_note_no"]

    assert make("CLI-A").endswith("0001")
    assert make("CLI-B").endswith("0001")
