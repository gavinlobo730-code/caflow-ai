"""A proposed amendment has to be able to reach the file the CA uploads.

WHAT WAS WRONG
    Three pieces existed and none of them were joined up:

      services/gst_amendment_service.outstanding_amendments()  worked out which
          corrections a period must carry, with the §37(3) window on each;
      domain/gst/amendments.merge_into_payload()               folded them into
          a GSTR-1 payload;
      services/gst_amendment_service.apply_amendments()        wrapped that,
          with a docstring explaining it was deliberately a separate call so
          the CA's review step could not be skipped.

    Nothing called apply_amendments. No route produced a merged payload. So
    GET /gstr1/amendments showed a CA exactly which corrections CGST Act §37
    required them to declare, and the only GSTR-1 they could download was the
    one without them. The amendment tables were computed for two features'
    worth of code and then filed nowhere.

    This adds the route. The review step stays: nothing is merged until the CA
    asks for the merged file, which is a separate call from reading the
    proposals.

WHAT MUST NOT REGRESS
    An amendment whose §37(3) window has closed cannot be declared at all.
    outstanding_amendments() already keeps those out of `sections` — it
    reports them under `expired` instead — so the merge cannot file one. The
    tests below pin that from the route's side, because it is the one failure
    here that would put an unlawful entry into a file a CA uploads.
"""
from datetime import date

import pytest

import routers.gst as gst_router
import routers.gst_workspace as gw
import services.gst_amendment_service as svc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM, CLIENT = "FIRM-A", "CLI"
GSTIN = "27AAAAA0000A1Z5"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs, gst_router])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Acme", "gstin": "27BBBBB1111B1Z5",
                         "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


def _invoice(db, invoice_no, invoice_date, taxable, cgst=0, sgst=0):
    return db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "invoice_no": invoice_no, "invoice_date": invoice_date, "status": "issued",
        "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
        "igst_paise": 0, "total_paise": taxable + cgst + sgst,
        "is_interstate": False, "supply_state_code": "27",
        "supply_type": "taxable", "invoice_type": "Regular",
        "is_reverse_charge": False, "deleted_at": None,
    })


def _file(db, period):
    payload = grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)["payload"]
    db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": period, "gstin": GSTIN,
        "status": "submitted", "payload_json": payload,
        "submitted_at": "2025-01-01T00:00:00Z", "arn": f"ARN{period}"})


def _drifted_june(db):
    """June 2025 filed, then its invoice edited. FY 2025-26, so the correction
    window closes 30 November 2026."""
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update(
        {"taxable_amount_paise": 150_000}).eq("id", row["id"]).execute()
    return row


def _merged(db, period="072025"):
    """What the new route returns: the July return with amendments folded in."""
    base = grs.gstr1_from_books(db, FIRM, CLIENT, period, GSTIN)
    out = svc.outstanding_amendments(db, FIRM, CLIENT, period)
    return svc.apply_amendments(base["payload"], out), out


# ── the route exists and is reachable ────────────────────────────────────────

def test_the_route_is_registered():
    """The whole defect was that no route produced a merged payload."""
    from main import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/gst/gstr1/with-amendments" in paths


def _via_route(period="072025"):
    """Through the endpoint function itself, not the service beneath it.

    Calling apply_amendments() directly proves the SERVICE merges. It says
    nothing about whether the route does — and "the route does not merge" was
    the entire defect. A negative control that removed the merge from the route
    passed against service-level tests, which is how this function came to
    exist.
    """
    from routers.gst import FromBooksRequest, gstr1_with_amendments_endpoint
    res = gstr1_with_amendments_endpoint(
        FromBooksRequest(client_id=CLIENT, period=period), CALLER)
    assert res["success"] is True, res
    return res["data"]


def test_the_route_itself_returns_a_merged_payload(db):
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)

    data = _via_route()

    assert "b2ba" in data["payload"], (
        "the endpoint returned the un-amended payload — the amendments are "
        "computed, reported, and still not in the file the CA downloads")
    assert data["amendments"]["counts"]["amendments"] == 1
    assert data["amendments"]["sections"] == ["b2ba"]
    assert data["ca_review_required"] is True


def test_the_route_reports_what_it_could_not_merge(db):
    """A CA needs the un-mergeable items in the same answer: an invoice never
    declared, and a cancelled document with no single right correction."""
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update(
        {"status": "cancelled"}).eq("id", row["id"]).execute()

    data = _via_route()
    assert data["amendments"]["needs_decision"], data["amendments"]
    assert "b2ba" not in data["payload"]


# ── the merge ────────────────────────────────────────────────────────────────

def test_an_outstanding_amendment_reaches_the_payload(db):
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)

    payload, out = _merged(db)

    assert out["counts"]["amendments"] == 1, "the fixture produced no amendment"
    assert "b2ba" in payload, (
        "the amendment was computed and left out of the file the CA uploads")
    assert payload["b2ba"], "b2ba present but empty"


def test_the_unamended_return_is_unchanged_by_the_merge(db):
    """The merge adds amendment tables; it must not touch the period's own."""
    _drifted_june(db)
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)

    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    merged, _ = _merged(db)
    for section in ("b2b", "b2cs", "b2cl", "cdnr", "hsn", "doc_issue"):
        assert merged.get(section) == base.get(section), section


def test_a_period_with_nothing_outstanding_produces_the_same_payload(db):
    _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    _invoice(db, "INV-2", "2025-07-05", 50_000, 4_500, 4_500)

    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    merged, out = _merged(db)
    assert out["counts"]["amendments"] == 0
    assert merged == base


# ── what must never be merged ────────────────────────────────────────────────

def test_an_out_of_time_amendment_is_never_folded_into_the_payload(db):
    """§37(3): after 30 November following the FY the correction cannot be
    declared at all. Filing one anyway is the worst outcome available here."""
    _drifted_june(db)
    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025",
                                     as_of=date(2027, 1, 1))
    assert out["counts"]["expired_periods"] == 1, "the fixture is not out of time"
    assert out["counts"]["amendments"] == 0

    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    merged = svc.apply_amendments(base, out)
    assert "b2ba" not in merged
    assert merged == base


def test_the_same_drift_in_time_does_get_merged(db):
    """Guard for the test above: it must fail because the window CLOSED, not
    because the fixture stopped producing drift."""
    _drifted_june(db)
    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025",
                                     as_of=date(2026, 1, 1))
    assert out["counts"]["amendments"] == 1
    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    assert "b2ba" in svc.apply_amendments(base, out)


def test_a_document_needing_a_decision_stays_out_of_the_payload(db):
    """A document cancelled after filing has no single right answer — amend to
    nil, or raise a credit note. It is surfaced, never chosen for the CA."""
    row = _invoice(db, "INV-1", "2025-06-10", 100_000, 9_000, 9_000)
    _file(db, "062025")
    db.table("client_sales_invoices").update(
        {"status": "cancelled"}).eq("id", row["id"]).execute()

    out = svc.outstanding_amendments(db, FIRM, CLIENT, "072025")
    assert out["counts"]["needs_decision"] >= 1, "the fixture produced no decision"
    base = grs.gstr1_from_books(db, FIRM, CLIENT, "072025", GSTIN)["payload"]
    merged = svc.apply_amendments(base, out)
    assert merged == base, "a document needing a CA decision was filed anyway"
