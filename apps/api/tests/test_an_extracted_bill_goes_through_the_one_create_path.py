"""A bill from a scanned document is a purchase bill, not a second kind.

WHAT WAS WRONG (PUR-17)

    `POST /api/purchase-bills/from-document` built the `purchase_bills` row
    and its lines by hand and inserted them itself. It is the only create path
    in this router that does not go through `_create_purchase_bill_core`, and
    it had drifted a long way:

      * A failed vendor match left `vendor_id = None` and inserted it. The
        column is NOT NULL (migration 050:233; the production schema fixture
        records `"nullable": "NO"`), so on the real database the insert raised
        and the CA got "Unable to complete purchase bill operation" with no
        reason. On FakeDB it succeeded, which is why the one test covering
        this endpoint passed while naming no supplier at all.
      * The LINES went in with `cgst_paise`, `sgst_paise` and `igst_paise`
        hard zero while the HEADER carried the extracted tax, so the bill did
        not foot to its own lines. Everything that reads lines — the GSTR-3B
        purchase feed, the ITC register, the line editor — saw a tax-free bill.
      * `is_interstate`, `total_gst_paise` and the §17(5) `ineligible_itc_*`
        columns were never written, so the bill classified wrongly in GSTR-3B
        and its blocked credit read as claimable.
      * `tds_paise` was a hard zero under a comment saying TDS "requires CA
        review before application". The ordinary create path resolves TDS from
        the vendor master through the one engine, and the bill is a DRAFT
        either way — a CA reviews it before /receive posts anything.
      * Neither `period_validation_service.validate_posting_date_cached` nor
        `period_lock_service.assert_open` ran, so an extraction could book a
        bill into a financial year the firm had locked or a month whose
        GSTR-3B was filed. The ordinary path has refused both since PUR/SALES-15.

    Zero frontend callers, which is how it drifted: `PurchaseBillEditor.tsx`
    does its own vendor match and posts to the ordinary create endpoint.

WHY ROUTED RATHER THAN DELETED

    Deleting it is the other honest fix, and the probe suggested it. It keeps
    the capability instead: `routers/document_intelligence_v1.py` advertises
    the endpoint in its own docstring, and an endpoint that is redundant and
    CORRECT is a much better starting point than one that was deleted and gets
    rebuilt by hand later — which is the mistake this file is about.

WHAT IS REFUSED RATHER THAN FILLED IN

    No vendor match and no line items are both 422s that say what to do. The
    extraction's own header amounts are NOT written over the computed ones:
    `_compute_bill_lines_and_totals` derives tax from rate x quantity x rate,
    and the model's reading survives in `ai_extraction_data` for the CA to
    compare against.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.invoices import BillFromDocumentIn
from models.parties import VendorIn
import tests.test_r237_ar_ap_hardening as H

CALLER = H.CALLER
FIRM = H.FIRM


@pytest.fixture
def env(monkeypatch):
    si, pb, cn, dn, cu, ve, pp, db = H._setup(monkeypatch)
    ve.create_vendor(VendorIn(client_id="CLI-A", name="Acme Traders",
                              state_code="27", gstin="27CCCCC2222C1Z8"), CALLER)
    return pb, ve, db


def _extract(**over):
    body = {
        "invoice_no": "AI-1", "invoice_date": "2026-06-01",
        "vendor_gstin": "27CCCCC2222C1Z8",
        "taxable_amount_paise": 1_00_000,
        "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0,
        "total_paise": 1_18_000,
        "line_items": [{"description": "Widget", "hsn_sac": "1234",
                        "rate_paise": 1_00_000, "quantity": 1,
                        "gst_rate_bps": 1800,
                        "taxable_amount_paise": 1_00_000}],
    }
    body.update(over)
    return body


def _make(pb, **over):
    return pb.create_bill_from_document(
        BillFromDocumentIn(client_id="CLI-A", extracted_data=_extract(**over)), CALLER)


# ── the fixture has to actually produce a bill ───────────────────────────────

def test_a_matched_extraction_still_creates_a_draft_bill(env):
    """Guard. If every case 422'd, the assertions below would be vacuous."""
    pb, _ve, _db = env
    out = _make(pb)
    assert out["success"] is True
    assert out["data"]["status"] == "draft"
    assert out["data"]["requires_review"] is True


# ── the vendor is resolved, and refused when it cannot be ────────────────────

def test_the_vendor_is_matched_by_gstin(env):
    pb, ve, db = env
    bill = _make(pb)["data"]
    vend = next(v for v in db.rows("vendors") if v.get("gstin") == "27CCCCC2222C1Z8")
    assert bill["vendor_id"] == vend["id"]


def test_the_vendor_is_matched_by_name_when_there_is_no_gstin(env):
    """An unregistered supplier has no GSTIN, and a scan rarely reproduces a
    legal name exactly — so the name match is a contains, not an equality."""
    pb, _ve, db = env
    bill = _make(pb, vendor_gstin=None, gstin=None, vendor_name="Acme")["data"]
    vend = next(v for v in db.rows("vendors") if v.get("name") == "Acme Traders")
    assert bill["vendor_id"] == vend["id"]


def test_no_vendor_match_is_refused_and_says_why(env):
    """It used to carry the None into the insert, against a NOT NULL column,
    and the CA read 'Unable to complete purchase bill operation'."""
    pb, _ve, _db = env
    with pytest.raises(HTTPException) as ei:
        _make(pb, vendor_gstin="27ZZZZZ9999Z1Z8", gstin=None, vendor_name="Nobody Ltd")
    assert ei.value.status_code == 422
    assert "vendor" in ei.value.detail.lower()
    assert "add the supplier" in ei.value.detail.lower()


def test_a_vendor_of_another_client_does_not_match(env):
    """`_match_extracted_vendor` is firm- AND client-scoped: another client's
    vendor carries the wrong TDS section, PAN and state code."""
    pb, ve, _db = env
    ve.create_vendor(VendorIn(client_id="CLI-B", name="Beta Supplies",
                              state_code="29"), CALLER)
    with pytest.raises(HTTPException) as ei:
        _make(pb, vendor_gstin=None, gstin=None, vendor_name="Beta Supplies")
    assert ei.value.status_code == 422


# ── the bill is computed, not transcribed ────────────────────────────────────

def test_the_lines_carry_their_own_gst(env):
    """The header used to carry the extracted tax while every line went in with
    all three heads zero, so the bill did not foot to its own lines and every
    reader of `purchase_bill_lines` saw a tax-free bill."""
    pb, _ve, db = env
    bill = _make(pb)["data"]
    lines = [l for l in db.rows("purchase_bill_lines") if l["bill_id"] == bill["id"]]
    assert len(lines) == 1
    assert lines[0]["cgst_paise"] == 9_000
    assert lines[0]["sgst_paise"] == 9_000
    assert lines[0]["igst_paise"] == 0
    assert (lines[0]["cgst_paise"] + lines[0]["sgst_paise"] + lines[0]["igst_paise"]
            == bill["cgst_paise"] + bill["sgst_paise"] + bill["igst_paise"])


def test_the_header_columns_the_hand_built_insert_never_set(env):
    """`is_interstate` decides CGST+SGST against IGST in GSTR-3B;
    `total_gst_paise` and the §17(5) `ineligible_itc_*` columns are read by the
    ITC side. None of the four was written by the old path."""
    pb, _ve, _db = env
    bill = _make(pb)["data"]
    assert bill["is_interstate"] is False          # 27 -> 27
    assert bill["total_gst_paise"] == 18_000
    for k in ("ineligible_itc_cgst_paise", "ineligible_itc_sgst_paise",
              "ineligible_itc_igst_paise"):
        assert bill[k] == 0
    assert bill["total_paise"] == 1_18_000


def test_an_inter_state_extraction_lands_on_igst(env):
    """The old path took the extracted heads verbatim, so a model that read a
    local bill's tax as IGST wrote IGST. The split is now the engine's, from
    the vendor's state against the client's."""
    pb, ve, _db = env
    ve.create_vendor(VendorIn(client_id="CLI-A", name="Karnataka Co",
                              state_code="29", gstin="29DDDDD3333D1ZP"), CALLER)
    bill = _make(pb, vendor_gstin="29DDDDD3333D1ZP")["data"]
    assert bill["is_interstate"] is True
    assert bill["igst_paise"] == 18_000
    assert bill["cgst_paise"] == 0 and bill["sgst_paise"] == 0


def test_tds_comes_from_the_vendor_master_like_any_other_bill(env):
    """It was a hard zero under a comment saying TDS 'requires CA review'. The
    rate is the engine's (CLAUDE.md: one TDS engine), and the bill is a draft
    either way — nothing is posted until a human calls /receive."""
    pb, ve, _db = env
    ve.create_vendor(VendorIn(
        client_id="CLI-A", name="Contractor Ltd", state_code="27",
        gstin="27EEEEE4444E1ZE", pan="AAAPL1234C",
        tds_applicable=True, tds_section="194C"), CALLER)
    bill = _make(pb, vendor_gstin="27EEEEE4444E1ZE",
                 taxable_amount_paise=2_00_00_000,
                 total_paise=2_36_00_000,
                 line_items=[{"description": "Works contract", "rate_paise": 2_00_00_000,
                              "quantity": 1, "gst_rate_bps": 1800}])["data"]
    assert bill["tds_section"] == "194C"
    assert bill["tds_paise"] > 0
    assert bill["net_payable_paise"] == bill["total_paise"] - bill["tds_paise"]


def test_the_extraction_is_kept_beside_the_computed_figures(env):
    """The Purchases page badges the bill from `is_ai_extracted`, and the blob
    is what a CA compares the computed figures against. Both survive the move
    onto the core, which is why the core takes them as passthrough."""
    pb, _ve, db = env
    bill = _make(pb)["data"]
    row = next(b for b in db.rows("purchase_bills") if b["id"] == bill["id"])
    assert row["is_ai_extracted"] is True
    assert row["ai_extraction_data"]["invoice_no"] == "AI-1"


def test_an_ordinary_bill_is_not_marked_ai_extracted(env):
    """The passthrough must default off, or every hand-typed bill gets the
    badge."""
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn
    pb, _ve, db = env
    vend = next(v for v in db.rows("vendors") if v.get("gstin") == "27CCCCC2222C1Z8")
    out = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI-A", vendor_id=vend["id"], bill_date="2026-06-01",
        bill_no="TYPED-1",
        lines=[PurchaseBillLineIn(description="x", rate_paise=1_00_000,
                                  quantity=1, gst_rate_percent=18.0,
                                  service_catalogue_id="SVC-1")]), CALLER)
    row = next(b for b in db.rows("purchase_bills") if b["id"] == out["data"]["id"])
    assert row["is_ai_extracted"] is False
    assert row["ai_extraction_data"] is None


# ── what cannot be built is named ────────────────────────────────────────────

def test_an_extraction_with_no_lines_is_refused(env):
    """It used to insert a header with no lines at all. GST is charged per line
    at the line's own rate, so a bill with none has no computable tax — and
    /receive would post a journal from a document that does not foot."""
    pb, _ve, _db = env
    with pytest.raises(HTTPException) as ei:
        _make(pb, line_items=[])
    assert ei.value.status_code == 422
    # The CORE also refuses a bill with no lines, so asserting "line" alone
    # passes with this endpoint's own check deleted. What has to survive is
    # THIS message: the core's "At least one line item is required" is right
    # for a typed bill and useless for a scan, where the answer is to enter it
    # by hand or upload a better image.
    assert "clearer scan" in ei.value.detail.lower()


def test_a_filed_return_refuses_an_extracted_bill(env):
    """Neither lock ran on this path. A bill is a CLAIM: booking June's after
    June's GSTR-3B is filed carries ITC that return never claimed, and §16(4)
    puts that credit in the CURRENT return rather than the closed one. The
    ordinary create path has refused it since SALES-15; this one did not."""
    pb, _ve, db = env
    db.seed("filings", {"firm_id": FIRM, "client_id": "CLI-A",
                        "filing_type": "GSTR-3B", "filed_date": "2026-07-20",
                        "period_start": "2026-06-01", "period_end": "2026-06-30"})
    with pytest.raises(HTTPException) as ei:
        _make(pb)
    assert ei.value.status_code in (409, 422)
    assert "gstr-3b" in str(ei.value.detail).lower()


# ── it is still a draft, and still not posted ────────────────────────────────

def test_nothing_is_posted_to_the_ledger(env):
    """The whole endpoint is behind CA REVIEW REQUIRED. Routing it through the
    core must not have made it post — the core creates a draft; /receive is
    what posts."""
    pb, _ve, db = env
    before = len(db.rows("journal_entries"))
    _make(pb)
    assert len(db.rows("journal_entries")) == before


def test_the_duplicate_guard_still_fires(env):
    """One supplier invoice, one bill — an upload retried after a timeout is
    exactly how the same document arrives twice. The old path had its own copy
    of this check; the core's is the one that now runs."""
    pb, _ve, _db = env
    assert _make(pb)["success"] is True
    with pytest.raises(HTTPException) as ei:
        _make(pb)
    assert ei.value.status_code == 409
