"""
Customer Credit Days = a per-invoice DEFAULT, snapshotted onto the invoice.

Verifies (CAFLOW customer-module task):
  * customer.credit_days populates a new invoice's due_date by default
  * an explicit credit_days or due_date on the request overrides it
  * the resolved terms (due_date + credit_days) are STORED on the invoice
  * changing the customer's Credit Days later does NOT touch existing invoices
All dates are plain calendar arithmetic; all money is integer paise elsewhere.
"""
import routers.sales_invoices as si
from routers.sales_invoices import _resolve_credit_terms, _apply_credit_days_due_date, _apply_due_date_credit_days
from models.invoices import SalesInvoiceIn, InvoiceLineIn, SalesInvoiceUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch, credit_days=15):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme", "state_code": "27", "gstin": "27XYZAB5678C1Z2",
                          "credit_days": credit_days, "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return db


def _inv(**over):
    kw = dict(client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", invoice_no="CD-001",
              lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="X", hsn_sac="9982", quantity=1,
                                   rate_paise=1_000_000, gst_rate_percent=18.0)])
    kw.update(over)
    return SalesInvoiceIn(**kw)


# ── pure resolver ───────────────────────────────────────────────────────────

def test_resolve_uses_customer_default():
    assert _resolve_credit_terms("2026-04-10", None, None, 15) == ("2026-04-25", 15)


def test_resolve_credit_days_override_beats_customer():
    assert _resolve_credit_terms("2026-04-10", None, 45, 15) == ("2026-05-25", 45)


def test_resolve_explicit_due_date_wins_and_derives_credit_days():
    # Apr 10 → Jun 01 is 52 days; due_date kept verbatim.
    assert _resolve_credit_terms("2026-04-10", "2026-06-01", None, 15) == ("2026-06-01", 52)


def test_resolve_falls_back_to_30_when_nothing_specified():
    assert _resolve_credit_terms("2026-04-10", None, None, None) == ("2026-05-10", 30)


def test_resolve_zero_credit_days_due_on_invoice_date():
    assert _resolve_credit_terms("2026-04-10", None, 0, 15) == ("2026-04-10", 0)


def test_apply_recompute_on_edit():
    d = {"credit_days": 20}
    _apply_credit_days_due_date(d, "2026-04-10")
    assert d["due_date"] == "2026-04-30"


def test_apply_noop_when_due_date_already_present():
    d = {"credit_days": 20, "due_date": "2026-09-09"}
    _apply_credit_days_due_date(d, "2026-04-10")
    assert d["due_date"] == "2026-09-09"


def test_apply_noop_when_no_credit_days():
    d = {}
    _apply_credit_days_due_date(d, "2026-04-10")
    assert "due_date" not in d


# ── reverse resolver: due_date edited directly -> re-derive credit_days ──────
# Mirror of _apply_credit_days_due_date, so the "Terms" label (a pure function
# of the stored credit_days) never goes stale after a due-date-only edit —
# e.g. the post-issue Edit Details modal, which only ever sends due_date.

def test_apply_reverse_recompute_on_edit():
    d = {"due_date": "2026-04-30"}
    _apply_due_date_credit_days(d, "2026-04-10")
    assert d["credit_days"] == 20


def test_apply_reverse_noop_when_credit_days_already_present():
    d = {"due_date": "2026-04-30", "credit_days": 99}
    _apply_due_date_credit_days(d, "2026-04-10")
    assert d["credit_days"] == 99


def test_apply_reverse_noop_when_no_due_date():
    d = {}
    _apply_due_date_credit_days(d, "2026-04-10")
    assert "credit_days" not in d


# ── create flow (real DB path via FakeDB) ────────────────────────────────────

def test_new_invoice_defaults_due_date_from_customer(monkeypatch):
    _setup(monkeypatch, credit_days=15)
    inv = si.create_invoice(_inv(), CALLER)["data"]
    assert inv["credit_days"] == 15
    assert inv["due_date"] == "2026-04-25"   # invoice_date + 15


def test_new_invoice_credit_days_override(monkeypatch):
    _setup(monkeypatch, credit_days=15)
    inv = si.create_invoice(_inv(credit_days=45), CALLER)["data"]
    assert inv["credit_days"] == 45
    assert inv["due_date"] == "2026-05-25"   # invoice_date + 45


def test_new_invoice_explicit_due_date_override(monkeypatch):
    _setup(monkeypatch, credit_days=15)
    inv = si.create_invoice(_inv(due_date="2026-06-01"), CALLER)["data"]
    assert inv["due_date"] == "2026-06-01"


def test_existing_invoice_unaffected_by_customer_credit_days_change(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    first = si.create_invoice(_inv(), CALLER)["data"]
    assert first["due_date"] == "2026-04-25" and first["credit_days"] == 15

    # CA later raises the customer's Credit Days to 60.
    for c in db.rows("customers"):
        if c["id"] == "CUST":
            c["credit_days"] = 60

    # The already-saved invoice keeps its snapshot — no rewrite.
    stored = next(r for r in db.rows("client_sales_invoices") if r["id"] == first["id"])
    assert stored["due_date"] == "2026-04-25"
    assert stored["credit_days"] == 15

    # A NEW invoice picks up the new default (Apr 10 + 60 = Jun 9).
    second = si.create_invoice(_inv(invoice_no="CD-002"), CALLER)["data"]
    assert second["credit_days"] == 60
    assert second["due_date"] == "2026-06-09"


# ── post-issue edit: due_date changes directly must resync credit_days ──────
# Regression test for the "Terms doesn't change when I edit the due date"
# report: the Edit Details modal only ever sends due_date, never credit_days.

def test_edit_due_date_on_issued_invoice_resyncs_credit_days(monkeypatch):
    db = _setup(monkeypatch, credit_days=15)
    inv = si.create_invoice(_inv(), CALLER)["data"]
    assert inv["due_date"] == "2026-04-25" and inv["credit_days"] == 15

    for row in db.rows("client_sales_invoices"):
        if row["id"] == inv["id"]:
            row["status"] = "issued"

    resp = si.update_invoice(inv["id"], SalesInvoiceUpdateIn(due_date="2026-06-01"), CALLER)
    assert resp["success"] is True

    stored = next(r for r in db.rows("client_sales_invoices") if r["id"] == inv["id"])
    assert stored["due_date"] == "2026-06-01"
    assert stored["credit_days"] == 52  # Apr 10 -> Jun 01
