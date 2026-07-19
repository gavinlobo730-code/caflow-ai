"""
Sales debit notes — the §34(3) increase-side mirror of credit notes (undercharge
correction on an issued invoice; the customer now owes more).

A sales debit note increases the linked invoice's receivable in the AR SUB-LEDGER
(debit_note_paise + sales_debit_note_allocations) and posts a kernel journal (Dr
Trade Receivables / Cr Sales / Cr GST Output), so the sub-ledger, the GL AR control
and the customer statement reconcile:
  invoice net outstanding = (total_paise + debit_note_paise) - paid_paise - credited_paise.

Also covers the direct interaction with the existing (reduction-side) credit note:
issuing a credit note against an invoice that already carries a debit note must use
the EFFECTIVE total (total + debit_note_paise), not the original total, as its
ceiling — the exact ripple fix applied to routers/credit_notes.py alongside this
feature.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.credit_notes as cn
import routers.sales_debit_notes as sdn
import routers.receipts as receipts
from models.invoices import InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance, trial_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, sdn, receipts])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme",
                          "is_active": True, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
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


def _create_dn(db, inv_id, rate, no="SDN-1"):
    res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
        client_id="CLI", customer_id="CUST1", debit_note_date="2025-06-05",
        sales_invoice_id=inv_id, reason="Rate correction — undercharged",
        lines=[InvoiceLineIn(description="additional charge", quantity=1, rate_paise=rate,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    return res["data"]["id"], res["data"]["total_paise"]


def _inv(db, inv_id):
    return next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)


def _ar(db):
    return account_balance(db, coa_id(db, FIRM, "ar"))


def test_sales_debit_note_increases_receivable_and_reconciles(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                        # AR = 118000
    assert _ar(db) == total
    dn_id, dn_total = _create_dn(db, inv_id, rate=20000)       # 20000 @18% = 23600
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True

    inv = _inv(db, inv_id)
    assert inv["debit_note_paise"] == dn_total                # sub-ledger
    net_out = inv["total_paise"] + inv["debit_note_paise"] - inv["paid_paise"] - inv["credited_paise"]
    assert net_out == total + dn_total                         # 141600
    assert _ar(db) == total + dn_total                         # GL AR control moved UP, not down
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
    assert any(a["debit_note_id"] == dn_id and a["allocated_paise"] == dn_total
               for a in db.rows("sales_debit_note_allocations"))
    assert inv["status"] == "issued"                           # nothing paid yet — status unchanged


def test_sales_debit_note_has_no_ceiling(monkeypatch):
    """Unlike a credit note, a debit note may exceed the invoice's original total —
    there is nothing to exceed when you're increasing what's owed."""
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db, taxable=10000, cgst=900, sgst=900)   # total 11800
    dn_id, dn_total = _create_dn(db, inv_id, rate=1_000000)    # far larger than the original invoice
    assert dn_total > total
    res = sdn.issue_sales_debit_note(dn_id, CALLER)
    assert res["success"] is True
    assert _inv(db, inv_id)["debit_note_paise"] == dn_total


def test_sales_debit_note_marks_invoice_paid_once_settled(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                         # 118000
    dn_id, dn_total = _create_dn(db, inv_id, rate=20000)        # 23600
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True
    # Fully settle the ORIGINAL total only — the debit note's addition is still owed.
    db.rows("client_sales_invoices")[0]["paid_paise"] = total
    inv = _inv(db, inv_id)
    assert inv["status"] != "paid"                             # 118000 paid < 141600 effective total


def test_cannot_debit_note_a_draft_invoice(monkeypatch):
    db = _setup(monkeypatch)
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1",
        "invoice_no": "INV-DRAFT", "invoice_date": "2025-06-01", "status": "draft",
        "total_paise": 11800, "taxable_amount_paise": 10000,
        "cgst_paise": 900, "sgst_paise": 900, "igst_paise": 0,
        "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0, "is_interstate": False,
    })
    dn_id, _ = _create_dn(db, inv["id"], rate=1000)
    with pytest.raises(HTTPException) as ex:
        sdn.issue_sales_debit_note(dn_id, CALLER)
    assert ex.value.status_code == 422


def test_create_sales_debit_note_computes_gst_from_percent(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
        client_id="CLI", customer_id="CUST1", debit_note_date="2025-06-05",
        sales_invoice_id=inv_id, reason="undercharged",
        lines=[InvoiceLineIn(description="extra", quantity=1, rate_paise=100000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    data = res["data"]
    assert data["taxable_amount_paise"] == 100000
    assert (data["cgst_paise"] + data["sgst_paise"] + data["igst_paise"]) == 18000
    assert data["total_paise"] == 118000


def test_draft_sales_debit_note_can_be_deleted(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, _ = _create_dn(db, inv_id, rate=1000)
    res = sdn.delete_sales_debit_note(dn_id, CALLER)
    assert res["success"] is True
    with pytest.raises(HTTPException) as ex:
        sdn.get_sales_debit_note(dn_id, CALLER)
    assert ex.value.status_code == 404


def test_issued_sales_debit_note_cannot_be_deleted(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, _ = _create_dn(db, inv_id, rate=1000)
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        sdn.delete_sales_debit_note(dn_id, CALLER)
    assert ex.value.status_code == 422


# ── Interaction with the existing (reduction-side) credit note ──────────────

def test_credit_note_after_debit_note_uses_effective_total(monkeypatch):
    """A debit note raises what the invoice can still absorb — a credit note
    issued afterwards must be checked against (total + debit_note_paise), not
    the stale original total, or a legitimate correction gets rejected."""
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                         # 118000
    dn_id, dn_total = _create_dn(db, inv_id, rate=20000)        # 23600
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True
    assert _inv(db, inv_id)["debit_note_paise"] == dn_total

    # A credit note for MORE than the original total (118000) but within the
    # new effective total (141600) must be accepted, not rejected as
    # "exceeds outstanding" against the stale pre-debit-note total.
    cn_res = cn.create_credit_note(cn.CreditNoteIn(
        client_id="CLI", customer_id="CUST1", credit_note_date="2025-06-06",
        sales_invoice_id=inv_id, reason="Partial waiver",
        lines=[InvoiceLineIn(description="waiver", quantity=1, rate_paise=130000,
                              gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert cn_res["success"] is True
    cn_id, cn_total = cn_res["data"]["id"], cn_res["data"]["total_paise"]
    assert total < cn_total < total + dn_total                 # exceeds ORIGINAL total, not effective

    issue_res = cn.issue_credit_note(cn_id, CALLER)
    assert issue_res["success"] is True

    inv = _inv(db, inv_id)
    net_out = inv["total_paise"] + inv["debit_note_paise"] - inv["paid_paise"] - inv["credited_paise"]
    assert net_out == (total + dn_total) - cn_total
    assert _ar(db) == (total + dn_total) - cn_total
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_receipt_can_collect_the_debit_noted_amount(monkeypatch):
    """The Record Payment flow (services.receipt_service via routers.receipts)
    must accept a receipt for the invoice's TRUE outstanding, including a
    debit note's addition — not just the original total. Exercises FakeDB's
    settle_receipt_atomic mirror (tests/e2e_harness.py), which was patched
    alongside the real Postgres RPC (migration 211)."""
    db = _setup(monkeypatch)
    inv_id, total = _issue_invoice(db)                          # 118000
    dn_id, dn_total = _create_dn(db, inv_id, rate=20000)         # 23600
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True
    effective_total = total + dn_total                          # 141600

    res = receipts.create_receipt(receipts.ReceiptIn(
        client_id="CLI", customer_id="CUST1", receipt_date="2025-06-10",
        amount_paise=effective_total, payment_mode="bank",
        allocations=[{"sales_invoice_id": inv_id, "allocated_paise": effective_total}],
    ), CALLER)
    assert res["success"] is True

    inv = _inv(db, inv_id)
    assert inv["paid_paise"] == effective_total
    assert inv["status"] == "paid"
    assert _ar(db) == 0


# ── GET single / PATCH (feature-parity build: dedicated edit page + drawer) ──

def test_get_single_sales_debit_note_returns_lines(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, total = _create_dn(db, inv_id, rate=20000)
    res = sdn.get_sales_debit_note(dn_id, CALLER)
    assert res["success"] is True
    assert res["data"]["id"] == dn_id
    assert res["data"]["total_paise"] == total
    assert len(res["data"]["lines"]) == 1
    assert res["data"]["lines"][0]["description"] == "additional charge"


def test_patch_draft_sales_debit_note_recomputes_totals_from_new_lines(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, _ = _create_dn(db, inv_id, rate=20000)                  # 23600
    res = sdn.update_sales_debit_note(dn_id, sdn.SalesDebitNoteUpdateIn(
        lines=[InvoiceLineIn(description="corrected charge", quantity=1, rate_paise=50000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["total_paise"] == 59000                     # 50000 + 18%
    assert len(res["data"]["lines"]) == 1
    assert res["data"]["lines"][0]["description"] == "corrected charge"
    assert sdn.get_sales_debit_note(dn_id, CALLER)["data"]["total_paise"] == 59000


def test_patch_notes_allowed_on_issued_sales_debit_note(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, _ = _create_dn(db, inv_id, rate=20000)
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True
    res = sdn.update_sales_debit_note(dn_id, sdn.SalesDebitNoteUpdateIn(
        notes="internal note",
    ), CALLER)
    assert res["success"] is True
    assert res["data"]["notes"] == "internal note"


def test_patch_lines_rejected_on_issued_sales_debit_note(monkeypatch):
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, _ = _create_dn(db, inv_id, rate=20000)
    assert sdn.issue_sales_debit_note(dn_id, CALLER)["success"] is True
    with pytest.raises(HTTPException) as ex:
        sdn.update_sales_debit_note(dn_id, sdn.SalesDebitNoteUpdateIn(
            lines=[InvoiceLineIn(description="x", quantity=1, rate_paise=1000,
                                  gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
        ), CALLER)
    assert ex.value.status_code == 422


def test_line_unit_persists_on_create_and_edit(monkeypatch):
    # _compute_lines previously never read ln.get("unit") at all, so every
    # line's unit silently landed NULL regardless of what the editor sent —
    # unlike sales_invoices.py/purchase_bills.py, which always did.
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
        client_id="CLI", customer_id="CUST1", debit_note_date="2025-06-05",
        sales_invoice_id=inv_id, reason="Rate correction — undercharged",
        lines=[InvoiceLineIn(description="additional charge", quantity=2, unit="KGS", rate_paise=20000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    dn_id = res["data"]["id"]
    assert res["data"]["lines"][0]["unit"] == "KGS"
    assert sdn.get_sales_debit_note(dn_id, CALLER)["data"]["lines"][0]["unit"] == "KGS"

    upd = sdn.update_sales_debit_note(dn_id, sdn.SalesDebitNoteUpdateIn(
        lines=[InvoiceLineIn(description="additional charge", quantity=2, unit="BOX", rate_paise=20000,
                              gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert upd["success"] is True
    assert upd["data"]["lines"][0]["unit"] == "BOX"
    assert sdn.get_sales_debit_note(dn_id, CALLER)["data"]["lines"][0]["unit"] == "BOX"


def test_issue_sales_debit_note_propagates_journal_http_exception(monkeypatch):
    """A deliberate business-rule rejection from the journal kernel (e.g. a
    locked-FY check firing at posting time) carries a real, actionable
    status+message the CA needs (task #97) — the rollback must still run, but
    the exception itself must propagate as-is, not get collapsed into the
    generic "Please try again" (retrying identical input would never succeed)."""
    db = _setup(monkeypatch)
    inv_id, _ = _issue_invoice(db)
    dn_id, _ = _create_dn(db, inv_id, rate=20000)

    import services.phase2_journal_service as pjs
    def _boom(*a, **k):
        raise HTTPException(status_code=422, detail="Financial year 2025-26 is locked for posting.")
    monkeypatch.setattr(pjs.phase2_journal_service, "journal_for_sales_debit_note", _boom)

    with pytest.raises(HTTPException) as e:
        sdn.issue_sales_debit_note(dn_id, CALLER)
    assert e.value.status_code == 422
    assert "locked" in e.value.detail.lower()
    inv = next(i for i in db.rows("client_sales_invoices") if i["id"] == inv_id)
    assert inv["debit_note_paise"] == 0   # rollback ran — invoice not left partially applied


def test_list_invoice_reminders_propagates_http_exception(monkeypatch):
    """sales_invoices.py's list_invoice_reminders was missing the
    except-HTTPException-then-raise guard its sibling remind_invoice already
    has (task #97) — a permission/not-found rejection from collections_service
    must propagate with its real status+detail, not the generic "Unable to
    fetch reminder history. Please try again."."""
    monkeypatch.setattr(si, "_USE_MOCK", False)

    from services import collections_service
    def _boom(*a, **k):
        raise HTTPException(status_code=404, detail="Invoice not found.")
    monkeypatch.setattr(collections_service, "invoice_reminder_history", _boom)

    with pytest.raises(HTTPException) as e:
        si.list_invoice_reminders("missing-invoice", CALLER)
    assert e.value.status_code == 404
    assert "not found" in e.value.detail.lower()
