"""
A filed return closes the period for invoices and bills too, not just journals.

WHAT WAS MISSING
    Sales invoices and purchase bills already refuse a lot: cancelled documents
    cannot be touched at all, an issued document is frozen to soft fields only
    (CGST §34 — corrections go through a credit or debit note), and the
    financial-year lock is checked at every write.

    None of that knows about filed returns. period_validation_service takes
    (firm_id, date) and a filed return is a fact about a CLIENT, so an invoice
    could be created, or its date moved, inside a period whose GSTR-1 had
    already gone to the portal. The return said one thing and the books said
    another, with nothing recording why.

WHY THE CHECK LIVES IN SQL
    period_lock_reason (migration 267) is the same function the journal edit
    path enforces with, inside the transaction that rewrites posted rows.
    Answering it a second time in Python would give us two definitions of
    "closed" that agree until the day one is changed.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.purchase_bills as pb
import routers.credit_notes as cn
import routers.sales_debit_notes as sdn
from models.invoices import InvoiceLineIn
from services import period_lock_service
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1",
        "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [si, pb, cn, sdn, period_lock_service])
    d.seed("firms", {"id": FIRM, "name": "F1", "locked_financial_years": []})
    return d


def _file_gstr1_for_june(db, filed_on="2026-07-11"):
    db.seed("filings", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_type": "GSTR-1",
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "filed_date": filed_on, "status": "filed", "deleted_at": None,
    })


# ── the lock itself ──────────────────────────────────────────────────────────

def test_an_open_period_reports_no_reason(db):
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15") is None


def test_a_filed_return_names_itself_and_the_date_it_was_filed(db):
    _file_gstr1_for_june(db)

    reason = period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15")

    assert reason is not None
    assert "GSTR-1" in reason, "the CA needs to know WHICH return closed the period"
    assert "11 Jul 2026" in reason, "and when it went"
    assert "amendment" in reason.lower(), "and what to do instead"


def test_the_lock_stops_at_the_period_boundary(db):
    _file_gstr1_for_june(db)

    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-05-31") is None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-01") is not None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-30") is not None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-07-01") is None


def test_an_unfiled_filing_row_does_not_close_anything(db):
    """A filing row with no filed_date is a task in the calendar, not a document
    at the portal. Blocking on it would freeze books nobody has submitted
    anything for."""
    db.seed("filings", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_type": "GSTR-1",
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "filed_date": None, "status": "draft", "deleted_at": None,
    })

    assert period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15") is None


def test_another_clients_filing_does_not_close_this_ones_books(db):
    _file_gstr1_for_june(db)

    assert period_lock_service.lock_reason(db, FIRM, "client-2", "2026-06-15") is None


def test_a_locked_year_still_reports_as_before(db):
    """267 moved this function; it did not change what it decides."""
    db.rows("firms")[0]["locked_financial_years"] = ["2026-27"]

    reason = period_lock_service.lock_reason(db, FIRM, CLIENT, "2026-06-15")

    assert reason is not None and "2026-27 is locked" in reason


# ── failing closed ───────────────────────────────────────────────────────────

class _Broken:
    def rpc(self, *_a, **_k):
        raise RuntimeError("connection reset by peer")


def test_a_check_that_cannot_run_treats_the_period_as_closed():
    """A document wrongly allowed into a filed period is not recoverable from
    the UI — the return has already gone. Same posture as
    manual_journal_service._lock_reason and period_validation_service."""
    reason = period_lock_service.lock_reason(_Broken(), FIRM, CLIENT, "2026-06-15")

    assert reason == period_lock_service.UNVERIFIABLE
    assert "again" in reason.lower(), "say that retrying is the fix"


def test_the_unverifiable_message_is_not_dressed_up_as_a_real_lock():
    """The CA can act on 'the year is locked'. All they can do about a failed
    check is retry, so the two must not read the same."""
    assert "locked" not in period_lock_service.UNVERIFIABLE.lower()
    assert "filed" not in period_lock_service.UNVERIFIABLE.lower()


def test_nothing_to_check_is_not_a_lock(db):
    """Bulk paths and drafts legitimately arrive without a client or a date."""
    assert period_lock_service.lock_reason(db, FIRM, None, "2026-06-15") is None
    assert period_lock_service.lock_reason(db, FIRM, CLIENT, None) is None
    assert period_lock_service.lock_reason(db, "", CLIENT, "2026-06-15") is None


# ── wired into the documents ─────────────────────────────────────────────────

def test_editing_a_sales_invoice_inside_a_filed_period_is_refused(db):
    _file_gstr1_for_june(db)
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "invoice_date": "2026-06-15", "invoice_no": "INV-1",
    })

    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV1", si.SalesInvoiceUpdateIn(notes="edited"),
                          current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_moving_a_sales_invoice_into_a_filed_period_is_refused(db):
    """Moving a document INTO a closed period changes that period's numbers as
    surely as editing one already there — checking only its current date would
    miss it entirely."""
    _file_gstr1_for_june(db)
    db.seed("client_sales_invoices", {
        "id": "INV1", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "invoice_date": "2026-07-15", "invoice_no": "INV-1",
    })

    with pytest.raises(HTTPException) as e:
        si.update_invoice("INV1", si.SalesInvoiceUpdateIn(invoice_date="2026-06-15"),
                          current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_an_invoice_in_an_open_period_is_still_editable(db):
    """The guard has to let the ordinary case through, or it is just an outage."""
    _file_gstr1_for_june(db)
    db.seed("client_sales_invoices", {
        "id": "INV2", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "invoice_date": "2026-07-15", "invoice_no": "INV-2",
    })

    resp = si.update_invoice("INV2", si.SalesInvoiceUpdateIn(notes="fine"),
                             current_user=USER)

    assert resp["success"] is True


def test_editing_a_purchase_bill_inside_a_filed_period_is_refused(db):
    """The purchase side matters for a different reason: a bill inside a filed
    period carries ITC already claimed in that GSTR-3B."""
    db.seed("filings", {
        "firm_id": FIRM, "client_id": CLIENT, "filing_type": "GSTR-3B",
        "period_start": "2026-06-01", "period_end": "2026-06-30",
        "filed_date": "2026-07-20", "status": "filed", "deleted_at": None,
    })
    db.seed("purchase_bills", {
        "id": "BILL1", "firm_id": FIRM, "client_id": CLIENT,
        "status": "draft", "bill_date": "2026-06-15", "bill_no": "B-1",
    })

    with pytest.raises(HTTPException) as e:
        pb.update_purchase_bill("BILL1", pb.PurchaseBillUpdateIn(notes="edited"),
                       current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-3B" in e.value.detail


# ── every document that lands in the return, not only the invoice ────────────
#
# SALES-15. Until migration 267's lock reached them, only sales invoices and
# purchase bills consulted it: credit notes, sales debit notes and the ISSUE
# transitions checked the financial-year lock alone. That was theoretical while
# nothing wrote public.filings, and stopped being theoretical the moment
# lib/data/gst.ts started PATCHing the status through the API — the lock fires
# for invoices and bills and, until now, silently did not for the rest.

def _line():
    return InvoiceLineIn(description="x", quantity=1, rate_paise=1_000_00,
                         gst_rate_percent=18.0, service_catalogue_id="SVC-1")


def _seed_party_and_catalogue(db):
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": CLIENT,
                          "name": "Acme", "state_code": "27", "is_active": True})
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT,
                                  "name": "Materials", "kind": "good"})


def test_a_credit_note_dated_inside_a_filed_period_is_refused(db):
    """§34(2) lets a credit note be declared only up to 30 November following
    the FY or the date GSTR-9 was furnished — and once GSTR-1 for the note's own
    period is filed, THAT return can no longer take it. The reduction goes in a
    later period's amendment tables."""
    _seed_party_and_catalogue(db)
    _file_gstr1_for_june(db)

    with pytest.raises(HTTPException) as e:
        cn.create_credit_note(cn.CreditNoteIn(
            client_id=CLIENT, customer_id="CUST1", credit_note_date="2026-06-15",
            reason="rate correction", lines=[_line()]), current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail
    assert "amendment" in e.value.detail.lower(), "refusing must say what to do instead"


def test_a_credit_note_in_an_open_period_is_still_allowed(db):
    """The control. A guard that refuses everything is an outage, not a rule."""
    _seed_party_and_catalogue(db)
    _file_gstr1_for_june(db)

    resp = cn.create_credit_note(cn.CreditNoteIn(
        client_id=CLIENT, customer_id="CUST1", credit_note_date="2026-07-15",
        reason="rate correction", lines=[_line()]), current_user=USER)

    assert resp["success"] is True, resp.get("error")


def test_moving_a_credit_note_into_a_filed_period_is_refused(db):
    _file_gstr1_for_june(db)
    db.seed("credit_notes", {
        "id": "CN1", "firm_id": FIRM, "client_id": CLIENT, "status": "draft",
        "credit_note_date": "2026-07-15", "credit_note_no": "CN-1", "deleted_at": None,
    })

    with pytest.raises(HTTPException) as e:
        cn.update_credit_note("CN1", cn.CreditNoteUpdateIn(credit_note_date="2026-06-15"),
                              current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_issuing_a_credit_note_into_a_filed_period_is_refused(db):
    """THE DEFERRED-POSTING GAP. A draft raised in June and issued in September
    posts with its JUNE date, so checking only at create is checking at the
    moment nothing was posted."""
    db.seed("credit_notes", {
        "id": "CN2", "firm_id": FIRM, "client_id": CLIENT, "status": "draft",
        "credit_note_date": "2026-06-15", "credit_note_no": "CN-2",
        "total_paise": 1_18_000, "deleted_at": None,
    })
    _file_gstr1_for_june(db, filed_on="2026-09-11")

    with pytest.raises(HTTPException) as e:
        cn.issue_credit_note("CN2", current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_a_sales_debit_note_dated_inside_a_filed_period_is_refused(db):
    """§34(3) makes a debit note a declaration in the return for the month it is
    issued in, and CGST §37 stops a filed return taking one."""
    _seed_party_and_catalogue(db)
    _file_gstr1_for_june(db)

    with pytest.raises(HTTPException) as e:
        sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
            client_id=CLIENT, customer_id="CUST1", debit_note_date="2026-06-15",
            reason="undercharged", lines=[_line()]), current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_issuing_a_sales_debit_note_into_a_filed_period_is_refused(db):
    db.seed("sales_debit_notes", {
        "id": "SDN1", "firm_id": FIRM, "client_id": CLIENT, "status": "draft",
        "debit_note_date": "2026-06-15", "debit_note_no": "SDN-1",
        "total_paise": 1_18_000, "deleted_at": None,
    })
    _file_gstr1_for_june(db, filed_on="2026-09-11")

    with pytest.raises(HTTPException) as e:
        sdn.issue_sales_debit_note("SDN1", current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_issuing_a_sales_invoice_into_a_filed_period_is_refused(db):
    """The same gap on the invoice itself: create checked the lock, issue did
    not, so a June draft could still be posted into a filed June."""
    db.seed("client_sales_invoices", {
        "id": "INV9", "firm_id": FIRM, "client_id": CLIENT, "status": "draft",
        "invoice_date": "2026-06-15", "invoice_no": "INV-9",
        "taxable_amount_paise": 1_00_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
        "igst_paise": 0, "total_paise": 1_18_000,
    })
    _file_gstr1_for_june(db, filed_on="2026-09-11")

    with pytest.raises(HTTPException) as e:
        si.issue_invoice("INV9", current_user=USER)

    assert e.value.status_code == 422
    assert "GSTR-1" in e.value.detail


def test_a_receipt_is_deliberately_NOT_locked_by_a_filed_return():
    """The one path SALES-15 asked for that is withheld, and the reason is in
    services/receipt_service.py beside the decision.

    A receipt moves Bank and Debtors and touches no output tax, and the only
    filing types written to public.filings are GSTR-1 and GSTR-3B — returns of
    SUPPLIES, not of collections. So a receipt back-dated into a filed period
    makes neither return disagree with anything, while refusing it would block
    an ordinary thing: recording a payment received on 20 June, entered on
    15 July, after GSTR-1 for June was filed on the 11th.

    Pinned as a DECISION so that adding the guard later is deliberate, and so
    that the reason travels with it.
    """
    import inspect

    from services import receipt_service
    from services import gst_filing_record_service as gfr

    src = inspect.getsource(receipt_service)
    assert "period_lock_service.assert_open" not in src.replace(
        "# DELIBERATELY NOT period_lock_service.assert_open", "")
    assert "DELIBERATELY NOT" in src, "the omission must be argued, not silent"

    # The premise the decision rests on. If a filing type appears that depends
    # on collections or on the balance sheet, the decision has to be retaken.
    types = {v for k, v in vars(gfr).items()
             if k.startswith("FILING_TYPE_") and isinstance(v, str)}
    assert types == {"GSTR-1", "GSTR-3B"}, (
        f"public.filings now records {sorted(types)} — re-read the argument in "
        "receipt_service before leaving receipts unguarded")
