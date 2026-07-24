"""
Task #239 — 4 GST computation gaps:

  1. CGST Act §17(5) blocked-credit ITC was never implemented — compute_gstr3b
     claimed 100% of book GST as ITC unconditionally, and GSTR-3B Table 4(D)(1)
     ("ineligible ITC") was hard-coded empty. Fixed via a new CA-set
     itc_eligible/blocked_credit_reason flag on purchase_bill_lines (migration
     240), aggregated onto the bill header and excluded from the ITC claim.
  2. gstr1_builder._build_hsn_summary's no-line-items fallback branch summed
     taxable/CGST/SGST/IGST but never cess into Table 12's "OTH" bucket.
  3. form26as_service._parse_amount and gst_workspace.upload_gstr2b both
     converted rupees to paise via float(x) * 100 instead of Decimal — never
     float, per project rule.
  4. domain.gst.portal_service.run_sync_job caught every per-snap_type portal
     fetch failure into a warning log and always reported "completed"
     regardless of how many (or all) fetches actually failed.
"""
from decimal import Decimal

import pytest

from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


# =============================================================================
# 1a. Pydantic model: blocked_credit_reason required when itc_eligible=False
# =============================================================================

def test_purchase_bill_line_requires_blocked_credit_reason_when_ineligible():
    with pytest.raises(Exception):
        PurchaseBillLineIn(description="Club membership", rate_paise=100000, quantity=1,
                           service_catalogue_id="SVC-1", itc_eligible=False)


def test_purchase_bill_line_defaults_to_eligible():
    ln = PurchaseBillLineIn(description="Office supplies", rate_paise=100000, quantity=1,
                             service_catalogue_id="SVC-1")
    assert ln.itc_eligible is True
    assert ln.blocked_credit_reason is None


def test_purchase_bill_line_accepts_ineligible_with_reason():
    ln = PurchaseBillLineIn(description="Club membership", rate_paise=100000, quantity=1,
                             service_catalogue_id="SVC-1", itc_eligible=False,
                             blocked_credit_reason="17_5_b_club_membership")
    assert ln.itc_eligible is False
    assert ln.blocked_credit_reason == "17_5_b_club_membership"


# =============================================================================
# 1b. domain/gst/gstr3b_computer.py: ineligible ITC excluded from the claim
# =============================================================================

def test_compute_gstr3b_excludes_ineligible_itc_from_claim():
    from domain.gst.gstr3b_computer import PurchaseTransaction, compute_gstr3b

    purchases = [
        # Eligible: ₹1,00,000 @18% = 9,000/9,000 CGST/SGST.
        PurchaseTransaction(taxable_amount_paise=100_00000, cgst_paise=9_00000, sgst_paise=9_00000,
                            igst_paise=0, cess_paise=0, is_reverse_charge=False),
        # Blocked under §17(5) (e.g. club membership): ₹50,000 @18% = 4,500/4,500 — must
        # NOT contribute to the ITC claim.
        PurchaseTransaction(taxable_amount_paise=50_00000, cgst_paise=4_50000, sgst_paise=4_50000,
                            igst_paise=0, cess_paise=0, is_reverse_charge=False,
                            ineligible_cgst_paise=4_50000, ineligible_sgst_paise=4_50000),
    ]
    result = compute_gstr3b([], purchases, [])
    assert result.itc_cgst == 9_00000
    assert result.itc_sgst == 9_00000
    assert result.itc_ineligible_cgst == 4_50000
    assert result.itc_ineligible_sgst == 4_50000


def test_compute_gstr3b_ineligible_excluded_before_rule_36_4_cap():
    """CGST Act §17(5) ineligibility is a hard bar — it must not be
    'restored' by the Rule 36(4) 2A/2B cap, which only compares eligible
    book ITC against eligible supplier-filed credit."""
    from domain.gst.gstr3b_computer import PurchaseTransaction, GSTR2ARecord, compute_gstr3b

    purchases = [
        PurchaseTransaction(taxable_amount_paise=100_00000, cgst_paise=10_00000, sgst_paise=10_00000,
                            igst_paise=0, cess_paise=0, is_reverse_charge=False,
                            ineligible_cgst_paise=10_00000, ineligible_sgst_paise=10_00000),
    ]
    # Even with abundant GSTR-2A credit available, ineligible ITC stays 0.
    gstr2a = [GSTR2ARecord(cgst_paise=10_00000, sgst_paise=10_00000, igst_paise=0)]
    result = compute_gstr3b([], purchases, gstr2a)
    assert result.itc_cgst == 0
    assert result.itc_sgst == 0
    assert result.itc_ineligible_cgst == 10_00000
    assert result.itc_ineligible_sgst == 10_00000


def test_gstr3b_payload_populates_itc_inelg():
    from domain.gst.gstr3b_computer import PurchaseTransaction, compute_gstr3b

    purchases = [
        PurchaseTransaction(taxable_amount_paise=50_00000, cgst_paise=4_50000, sgst_paise=4_50000,
                            igst_paise=0, cess_paise=0, is_reverse_charge=False,
                            ineligible_cgst_paise=4_50000, ineligible_sgst_paise=4_50000),
    ]
    result = compute_gstr3b([], purchases, [])
    payload = result.as_gstn_payload("27AAAAA0000A1Z5", "062026")
    inelg = payload["itc_elg"]["itc_inelg"][0]
    assert inelg["camt"] == 4500.0
    assert inelg["samt"] == 4500.0


def test_compute_gstr3b_all_eligible_unaffected_by_ineligible_fields():
    """Sanity: purchases with no §17(5) lines (the default, pre-existing
    behavior) still claim 100% ITC — this fix must not regress the common
    case."""
    from domain.gst.gstr3b_computer import PurchaseTransaction, compute_gstr3b

    purchases = [
        PurchaseTransaction(taxable_amount_paise=100_00000, cgst_paise=9_00000, sgst_paise=9_00000,
                            igst_paise=0, cess_paise=0, is_reverse_charge=False),
    ]
    result = compute_gstr3b([], purchases, [])
    assert result.itc_cgst == 9_00000
    assert result.itc_sgst == 9_00000
    assert result.itc_ineligible_cgst == 0
    assert result.itc_ineligible_sgst == 0


# =============================================================================
# 1c. routers/purchase_bills.py: ineligible totals computed + persisted
# =============================================================================

def _pb_setup(monkeypatch):
    import routers.purchase_bills as pb
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "is_active": True, "tds_applicable": False})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Office Supplies", "kind": "good"})
    db.seed("service_catalogue", {"id": "SVC-2", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Club Membership", "kind": "service"})
    return pb, db


def test_create_purchase_bill_computes_ineligible_itc_totals(monkeypatch):
    pb, db = _pb_setup(monkeypatch)
    result = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date="2026-06-01", bill_no="B-1",
        lines=[
            PurchaseBillLineIn(description="Stationery", rate_paise=100_00000, quantity=1,
                               gst_rate_percent=18.0, service_catalogue_id="SVC-1"),
            PurchaseBillLineIn(description="Club membership", rate_paise=50_00000, quantity=1,
                               gst_rate_percent=18.0, service_catalogue_id="SVC-2",
                               itc_eligible=False, blocked_credit_reason="17_5_b_club_membership"),
        ],
    ), CALLER)
    assert result["success"] is True
    bill = result["data"]
    # 50,000 @18% intra-state = 4,500 CGST + 4,500 SGST on the blocked line.
    assert bill["ineligible_itc_cgst_paise"] == 4_50000
    assert bill["ineligible_itc_sgst_paise"] == 4_50000
    # The bill total/net_payable are unaffected -- ITC eligibility never
    # changes what the vendor is owed, only what can be claimed as ITC.
    assert bill["cgst_paise"] == 13_50000  # (100,000 + 50,000) * 9%
    assert bill["sgst_paise"] == 13_50000

    lines = [r for r in db.rows("purchase_bill_lines") if r["bill_id"] == bill["id"]]
    eligible_line = next(l for l in lines if l["description"] == "Stationery")
    blocked_line = next(l for l in lines if l["description"] == "Club membership")
    assert eligible_line["itc_eligible"] is True
    assert blocked_line["itc_eligible"] is False
    assert blocked_line["blocked_credit_reason"] == "17_5_b_club_membership"


def test_create_purchase_bill_all_eligible_has_zero_ineligible_totals(monkeypatch):
    pb, db = _pb_setup(monkeypatch)
    result = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date="2026-06-01", bill_no="B-2",
        lines=[PurchaseBillLineIn(description="Stationery", rate_paise=100_00000, quantity=1,
                                  gst_rate_percent=18.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    bill = result["data"]
    assert bill["ineligible_itc_cgst_paise"] == 0
    assert bill["ineligible_itc_sgst_paise"] == 0
    assert bill["ineligible_itc_igst_paise"] == 0


# =============================================================================
# 1d. services/gst_return_service.py: reads the bill-header ineligible columns
# =============================================================================

def test_gstr3b_from_books_excludes_ineligible_itc(monkeypatch):
    import services.gst_return_service as svc
    db = FakeDB()
    db.seed("purchase_bills", {
        "id": "BILL1", "firm_id": FIRM, "client_id": "CLI", "status": "received",
        "bill_date": "2026-06-05", "taxable_amount_paise": 150_00000,
        "cgst_paise": 13_50000, "sgst_paise": 13_50000, "igst_paise": 0, "cess_paise": 0,
        "is_reverse_charge": False,
        "ineligible_itc_cgst_paise": 4_50000, "ineligible_itc_sgst_paise": 4_50000,
        "ineligible_itc_igst_paise": 0,
    })
    monkeypatch.setattr(svc, "_gl_gst_movements", lambda *a, **k: {"output_paise": 0, "itc_paise": 0, "by_head": {}})
    result = svc.gstr3b_from_books(db, FIRM, "CLI", "062026", "27AAAAA0000A1Z5")
    payload = result["payload"]
    assert payload["itc_elg"]["itc_avl"][0]["camt"] == 9000.0   # 13,50,000 - 4,50,000 = 9,00,000 paise = 9000 rupees
    assert payload["itc_elg"]["itc_inelg"][0]["camt"] == 4500.0


# =============================================================================
# 2. gstr1_builder._build_hsn_summary: no-lines fallback includes cess
# =============================================================================

def test_hsn_summary_fallback_includes_cess():
    from domain.gst.gstr1_builder import InvoiceForGSTR1, _build_hsn_summary
    from domain.gst.classifier import GSTInvoiceCategory

    inv = InvoiceForGSTR1(
        id="i1", transaction_type="sales_invoice", reference_no="INV-1",
        transaction_date="2026-06-10", party_gstin="27BBBBB1111B1Z5", party_name="Acme",
        place_of_supply="27", is_interstate=False,
        taxable_amount_paise=1_00_000_00, cgst_paise=9_000_00, sgst_paise=9_000_00,
        igst_paise=0, cess_paise=5_000_00, is_reverse_charge=False, invoice_type="Regular",
        supply_type="taxable", gst_invoice_category=GSTInvoiceCategory.B2B,
        original_invoice_ref=None, original_invoice_date=None, lines=[],  # no line items -> fallback
    )
    out = _build_hsn_summary([inv], turnover_paise=0)
    assert len(out) == 1
    assert out[0]["hsn_sc"] == "OTH"
    assert out[0]["csamt"] == 5000.0


def test_hsn_summary_fallback_zero_cess_unchanged():
    from domain.gst.gstr1_builder import InvoiceForGSTR1, _build_hsn_summary
    from domain.gst.classifier import GSTInvoiceCategory

    inv = InvoiceForGSTR1(
        id="i1", transaction_type="sales_invoice", reference_no="INV-1",
        transaction_date="2026-06-10", party_gstin="27BBBBB1111B1Z5", party_name="Acme",
        place_of_supply="27", is_interstate=False,
        taxable_amount_paise=1_00_000_00, cgst_paise=9_000_00, sgst_paise=9_000_00,
        igst_paise=0, cess_paise=0, is_reverse_charge=False, invoice_type="Regular",
        supply_type="taxable", gst_invoice_category=GSTInvoiceCategory.B2B,
        original_invoice_ref=None, original_invoice_date=None, lines=[],
    )
    out = _build_hsn_summary([inv], turnover_paise=0)
    assert out[0]["csamt"] == 0.0


# =============================================================================
# 3a. form26as_service._parse_amount: Decimal-based, never float
# =============================================================================

def test_parse_amount_decimal_precision():
    from domain.income_tax.form26as_service import _parse_amount
    # A value float(x)*100 would NOT reliably round-trip through IEEE-754.
    assert _parse_amount("19,999.99") == 1_999_999
    assert _parse_amount("100.05") == 10_005
    assert _parse_amount("1,00,000") == 10_000_000


def test_parse_amount_preserves_negative_sign():
    from domain.income_tax.form26as_service import _parse_amount
    # A correction/reversal row in 26AS -- must stay negative, not be
    # silently stripped to a positive credit.
    assert _parse_amount("-500.00") == -50000


def test_parse_amount_empty_and_malformed():
    from domain.income_tax.form26as_service import _parse_amount
    assert _parse_amount("") == 0
    with pytest.raises(ValueError):
        _parse_amount("12.34.56")


# =============================================================================
# 3b. gst_workspace.upload_gstr2b: Decimal-based txval -> paise
# =============================================================================

def test_txval_to_paise_decimal_precision():
    from routers.gst_workspace import _txval_to_paise
    assert _txval_to_paise(19999.99) == 1_999_999
    assert _txval_to_paise("19999.99") == 1_999_999
    assert _txval_to_paise(0) == 0
    assert _txval_to_paise(None) == 0


def test_upload_gstr2b_matches_using_decimal_conversion(monkeypatch):
    import routers.gst_workspace as m
    import core.authz as authz
    monkeypatch.setattr(authz, "_USE_MOCK", True)  # permissive assert_client_access
    body = m.GSTR2BUploadRequest(client_id="C1", period="042026", raw_data={
        "invoices": [{"inum": "INV-1", "sgstin": "27PQRST9012K1Z8", "txval": 19999.99}],
        "book_invoices": [{"invoice_no": "INV-1", "gstin": "27PQRST9012K1Z8", "taxable_paise": 1_999_999}],
    })
    resp = m.upload_gstr2b(body, CALLER)
    assert resp["success"] is True
    summary = resp["data"]["reconciliation_result"]["summary"]
    assert summary["matched_count"] == 1
    assert summary["mismatch_count"] == 0


# =============================================================================
# 4. domain/gst/portal_service.run_sync_job: partial/total failure surfaced
# =============================================================================

class _FakeProvider:
    def __init__(self, fail_types):
        self.fail_types = set(fail_types)

    def _maybe_fail(self, snap_type, value):
        if snap_type in self.fail_types:
            raise RuntimeError(f"portal unreachable for {snap_type}")
        return value

    def fetch_profile(self, gstin):
        return self._maybe_fail("profile", {"gstin": gstin})

    def fetch_filing_status(self, gstin, fy):
        return self._maybe_fail("filing_status", {})

    def fetch_return_history(self, gstin, fy):
        return self._maybe_fail("return_history", [])

    def fetch_liability_summary(self, gstin, period):
        return self._maybe_fail("liability_summary", {})

    def fetch_gstr1_status(self, gstin, period):
        return self._maybe_fail("gstr1_status", {})

    def fetch_gstr3b_status(self, gstin, period):
        return self._maybe_fail("gstr3b_status", {})


def _portal_setup(monkeypatch, fail_types, scope):
    import domain.gst.portal_service as ps
    db = FakeDB()
    monkeypatch.setattr(ps, "_USE_MOCK", False)
    monkeypatch.setattr(ps, "_supabase", lambda: db)
    monkeypatch.setattr(ps, "get_provider", lambda name="manual": _FakeProvider(fail_types))
    job = db.seed("gst_sync_jobs", {
        "firm_id": FIRM, "client_id": "CLI", "gstin": "27AAAAA0000A1Z5",
        "sync_type": "manual", "scope": scope, "status": "pending", "snapshots_created": 0,
    })
    return ps, db, job


def test_run_sync_job_all_succeed_is_completed(monkeypatch):
    ps, db, job = _portal_setup(monkeypatch, fail_types=[], scope=["profile", "filing_status"])
    result = ps.run_sync_job(FIRM, job["id"])
    assert result["status"] == "completed"
    assert result["snapshots_created"] == 2
    assert result["failed"] == []
    row = next(r for r in db.rows("gst_sync_jobs") if r["id"] == job["id"])
    assert row["status"] == "completed"


def test_run_sync_job_partial_failure_not_reported_as_completed(monkeypatch):
    ps, db, job = _portal_setup(monkeypatch, fail_types=["filing_status"],
                                 scope=["profile", "filing_status"])
    result = ps.run_sync_job(FIRM, job["id"])
    assert result["status"] == "partial_failure"
    assert result["snapshots_created"] == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["snap_type"] == "filing_status"
    row = next(r for r in db.rows("gst_sync_jobs") if r["id"] == job["id"])
    assert row["status"] == "partial_failure"
    assert "filing_status" in row["error_message"]


def test_run_sync_job_total_failure_is_error_not_completed(monkeypatch):
    ps, db, job = _portal_setup(monkeypatch, fail_types=["profile", "filing_status"],
                                 scope=["profile", "filing_status"])
    result = ps.run_sync_job(FIRM, job["id"])
    assert result["status"] == "error"
    assert result["snapshots_created"] == 0
    assert len(result["failed"]) == 2
    row = next(r for r in db.rows("gst_sync_jobs") if r["id"] == job["id"])
    assert row["status"] == "error"
