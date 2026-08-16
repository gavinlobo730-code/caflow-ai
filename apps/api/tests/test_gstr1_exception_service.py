"""
The exception report against a real filed return.

The diff arithmetic is tested in test_gstr1_exception_report.py against the
rule. This is about what gets compared: which return counts as filed, what
happens when there is nothing to compare against, and whether an invoice edited
after filing actually surfaces — end to end, from a seeded invoice through
gstr1_from_books rather than from a payload written by the test.

That last part matters. A test that hands compare_payloads two dicts it built
itself proves the diff works and proves nothing about whether the service ever
reaches the books — the failure mode this whole run of tasks keeps hitting.
"""
from __future__ import annotations

import pytest

import routers.gst_workspace as gw
import services.gst_exception_service as svc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CLIENT = "CLI"
GSTIN = "27AAAAA0000A1Z5"
PERIOD = "062025"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                         "gstin": "27BBBBB1111B1Z5", "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _invoice(db, invoice_no, taxable, cgst=0, sgst=0, igst=0, **extra):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "invoice_no": invoice_no, "invoice_date": "2025-06-10", "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": igst, "total_paise": taxable + cgst + sgst + igst,
        "is_interstate": bool(igst), "supply_state_code": "27",
        "supply_type": "taxable", "invoice_type": "Regular", "is_reverse_charge": False,
        "deleted_at": None, **extra,
    })


def _books_payload(db) -> dict:
    """What we would file for this period right now."""
    return grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)["payload"]


def _file_return(db, payload, status="submitted"):
    return db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": PERIOD, "gstin": GSTIN,
        "status": status, "payload_json": payload,
        "submitted_at": "2025-07-11T10:00:00Z", "arn": "AA270625000001X",
    })


def _report(db):
    return svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD)


# ── which return counts as filed ─────────────────────────────────────────────

def test_a_period_with_no_return_at_all_is_not_filed(db):
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)

    assert _report(db)["status"] == "not_filed"


@pytest.mark.parametrize("status", ["draft", "validated", "ca_approved"])
def test_a_return_not_yet_submitted_has_nothing_to_drift_from(db, status):
    """A draft is re-derived from the books every time it is opened, so
    comparing against it would report the CA's own working back at them."""
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db), status=status)

    assert _report(db)["status"] == "not_filed"


def test_a_submitted_return_with_no_stored_payload_says_so(db):
    """Returns submitted before task #148 have status 'submitted' and
    payload_json NULL. Treating that as an empty payload would report every
    invoice in the period as missing from the return — a page of alarming
    findings describing nothing but our own past gap."""
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, None)

    out = _report(db)

    assert out["status"] == "payload_missing"
    assert "cannot be detected automatically" in out["message"]
    assert "documents" not in out, "a missing payload must not be reported as drift"


def test_the_filing_reference_is_carried_through(db):
    """The CA identifies the filing by its ARN, not by our row id."""
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db))

    out = _report(db)

    assert out["arn"] == "AA270625000001X"
    assert out["filed_at"] == "2025-07-11T10:00:00Z"


# ── nothing has moved ────────────────────────────────────────────────────────

def test_books_untouched_since_filing_report_clean(db):
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db))

    out = _report(db)

    assert out["status"] == "ok"
    assert out["clean"] is True
    assert out["finding_count"] == 0


# ── the real thing: an invoice changed after filing ──────────────────────────

def test_an_invoice_edited_after_filing_is_found(db):
    """THE test for this feature, and the one it would be easiest to write
    uselessly. It seeds a real invoice, freezes the real from-books payload as
    the filed return, then edits the invoice — so the drift has to travel all
    the way through gstr1_from_books to be seen."""
    row = _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db))

    db.table("client_sales_invoices").update({
        "taxable_amount_paise": 150_000, "cgst_paise": 13_500, "sgst_paise": 13_500,
    }).eq("id", row["id"]).execute()

    out = _report(db)

    assert out["clean"] is False
    changed = out["documents"]["amount_changed"]
    assert [c["doc_no"] for c in changed] == ["INV-1"]
    assert changed[0]["delta"]["taxable_paise"] == 50_000
    assert changed[0]["declare_in"] == "9A"


def test_an_invoice_raised_after_filing_is_found(db):
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db))

    _invoice(db, "INV-LATE", 40_000, 3_600, 3_600)

    out = _report(db)

    missing = out["documents"]["missing_from_return"]
    assert [d["doc_no"] for d in missing] == ["INV-LATE"]
    assert missing[0]["declare_in"] == "current period"


def test_an_invoice_cancelled_after_filing_is_found(db):
    """Cancellation, not deletion, is how a declared invoice leaves the books.

    The first version of this test soft-deleted an issued invoice, which the
    product refuses (routers/sales_invoices.py: only drafts may be deleted, and
    a draft is already outside the posted statuses the return reads). It was
    asserting on a state that cannot exist — and it failed, correctly.
    """
    row = _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db))

    db.table("client_sales_invoices").update(
        {"status": "cancelled"}).eq("id", row["id"]).execute()

    out = _report(db)

    gone = out["documents"]["missing_from_books"]
    assert [d["doc_no"] for d in gone] == ["INV-1"]
    assert gone[0]["declare_in"] == "9A"


def test_an_invoice_reclassified_after_filing_is_found(db):
    """The case task #156 made reachable: an SEZ supply filed as ordinary B2B,
    corrected on the invoice afterwards. Amending the value alone would leave
    it in the wrong GSTR-1 table."""
    row = _invoice(db, "INV-1", 100_000)
    _file_return(db, _books_payload(db))

    db.table("client_sales_invoices").update({
        "supply_type": "zero_rated", "invoice_type": "SEZ_without_payment",
    }).eq("id", row["id"]).execute()

    out = _report(db)

    rec = out["documents"]["reclassified"]
    assert [r["doc_no"] for r in rec] == ["INV-1"]
    assert rec[0]["filed_section"] == "b2b"
    assert rec[0]["books_section"] == "exp"


# ── scoping ──────────────────────────────────────────────────────────────────

def test_another_clients_filed_return_is_not_read(db):
    db.seed("clients", {"id": "CLI-2", "firm_id": FIRM, "gstin": "27CCCCC2222C1Z5",
                        "financial_year_start": "2025-04-01", "state_code": "27"})
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": "CLI-2", "period": PERIOD, "gstin": "27CCCCC2222C1Z5",
        "status": "submitted", "payload_json": {"gstin": "27CCCCC2222C1Z5", "fp": PERIOD},
    })

    assert _report(db)["status"] == "not_filed"


def test_another_periods_filed_return_is_not_read(db):
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": "052025", "gstin": GSTIN,
        "status": "submitted", "payload_json": {"gstin": GSTIN, "fp": "052025"},
    })

    assert _report(db)["status"] == "not_filed"


# ── the endpoint ─────────────────────────────────────────────────────────────

def test_the_endpoint_returns_the_report(db):
    _invoice(db, "INV-1", 100_000, 9_000, 9_000)
    _file_return(db, _books_payload(db))

    resp = gw.gstr1_exception_report(
        client_id=CLIENT, period=PERIOD,
        current_user={"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
                      "email": "ca@f.test", "role": "Partner"},
    )

    assert resp["success"] is True
    assert resp["data"]["status"] == "ok"
    assert resp["data"]["ca_review_required"] is True
