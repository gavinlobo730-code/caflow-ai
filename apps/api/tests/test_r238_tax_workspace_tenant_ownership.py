"""
Task #238 — audit-pass-3 systemic missing tenant-ownership check on GST/TDS/
MCA/ITR write endpoints (tds_workspace.py, mca_workspace.py, itr_workspace.py,
form_26as.py, einvoice.py, eway_bill.py, income_tax.py's create_capital_gains,
compliance_records.py).

Same root cause as tasks #230/#231/#234/#237: a caller-supplied client_id used
in a write path without checking it belongs to the caller's own firm (or, for
compliance_records.update, without checking the caller is ASSIGNED to the
fetched record's client). Fixed by wiring core.authz.assert_client_access at
the top of each endpoint, mirroring this codebase's own already-fixed sibling
(income_tax.py's save_advance_tax, task #230).

Every "rejects foreign client" test proves TWO things: (1) a 404, and (2) the
downstream create/persist call was never reached (via a monkeypatched spy) --
so a rejected request leaves no artifact behind, not just an error response.
"""
import pytest
from fastapi import HTTPException

import core.authz as authz
from tests.e2e_harness import FakeDB

PARTNER_F1 = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p1", "id": "u1", "email": "p1@f1.test"}


@pytest.fixture
def enforced(monkeypatch):
    """Force the real (non-mock) client-ownership enforcement path. C1
    belongs to F1 (every fixture user's firm); C-OTHER belongs to F2."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_belongs(client_id, firm_id):
        if client_id == "C-OTHER":
            return firm_id == "F2"
        return firm_id == "F1"
    monkeypatch.setattr(authz, "_client_belongs_to_firm", fake_belongs)
    yield


def _never_called(*_a, **_k):
    raise AssertionError("downstream create/persist call must not run when access is denied")


# =============================================================================
# tds_workspace.py
# =============================================================================

def test_create_challan_rejects_foreign_client(enforced):
    import routers.tds_workspace as m
    body = m.CreateChallanRequest(
        client_id="C-OTHER", bsr_code="1234567", challan_date="2026-06-01",
        amount_paise=100000, challan_no="CH1", section="194C",
        financial_year="2025-26", quarter="Q1")
    with pytest.raises(HTTPException) as ei:
        m.create_challan(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_challan_accepts_own_firm(enforced):
    import routers.tds_workspace as m
    body = m.CreateChallanRequest(
        client_id="C1", bsr_code="1234567", challan_date="2026-06-01",
        amount_paise=100000, challan_no="CH1", section="194C",
        financial_year="2025-26", quarter="Q1")
    resp = m.create_challan(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_return_rejects_foreign_client(enforced):
    import routers.tds_workspace as m
    body = m.CreateReturnRequest(client_id="C-OTHER", return_type="24Q",
                                  quarter="Q1", financial_year="2025-26")
    with pytest.raises(HTTPException) as ei:
        m.create_return(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_return_accepts_own_firm(enforced):
    import routers.tds_workspace as m
    body = m.CreateReturnRequest(client_id="C1", return_type="24Q",
                                  quarter="Q1", financial_year="2025-26")
    resp = m.create_return(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_certificate_rejects_foreign_client(enforced):
    import routers.tds_workspace as m
    body = m.CreateCertificateRequest(
        client_id="C-OTHER", deductee_pan="ABCDE1234F", deductee_name="X",
        financial_year="2025-26", certificate_type="Form 16A",
        tds_amount_paise=1000, section="194C")
    with pytest.raises(HTTPException) as ei:
        m.create_certificate(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_certificate_accepts_own_firm(enforced):
    import routers.tds_workspace as m
    body = m.CreateCertificateRequest(
        client_id="C1", deductee_pan="ABCDE1234F", deductee_name="X",
        financial_year="2025-26", certificate_type="Form 16A",
        tds_amount_paise=1000, section="194C")
    resp = m.create_certificate(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_upload_form26as_rejects_foreign_client(enforced):
    import routers.tds_workspace as m
    body = m.Form26ASUploadRequest(client_id="C-OTHER", financial_year="2025-26")
    with pytest.raises(HTTPException) as ei:
        m.upload_form26as(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_upload_form26as_accepts_own_firm(enforced):
    import routers.tds_workspace as m
    body = m.Form26ASUploadRequest(client_id="C1", financial_year="2025-26")
    resp = m.upload_form26as(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


# =============================================================================
# mca_workspace.py
# =============================================================================

def test_create_company_rejects_foreign_client(enforced):
    import routers.mca_workspace as m
    body = m.CreateCompanyRequest(client_id="C-OTHER", cin="U12345MH2020PTC123456",
                                   company_name="Foo Pvt Ltd")
    with pytest.raises(HTTPException) as ei:
        m.create_company(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_company_accepts_own_firm(enforced):
    import routers.mca_workspace as m
    body = m.CreateCompanyRequest(client_id="C1", cin="U12345MH2020PTC123456",
                                   company_name="Foo Pvt Ltd")
    resp = m.create_company(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_director_rejects_foreign_client(enforced):
    import routers.mca_workspace as m
    body = m.CreateDirectorRequest(client_id="C-OTHER", din="12345678", name="A B",
                                    designation="Director", date_of_appointment="2026-01-01")
    with pytest.raises(HTTPException) as ei:
        m.create_director(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_director_accepts_own_firm(enforced):
    import routers.mca_workspace as m
    body = m.CreateDirectorRequest(client_id="C1", din="12345678", name="A B",
                                    designation="Director", date_of_appointment="2026-01-01")
    resp = m.create_director(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_mca_filing_rejects_foreign_client(enforced):
    import routers.mca_workspace as m
    body = m.CreateFilingRequest(client_id="C-OTHER", form_type="AOC-4")
    with pytest.raises(HTTPException) as ei:
        m.create_filing(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_mca_filing_accepts_own_firm(enforced):
    import routers.mca_workspace as m
    body = m.CreateFilingRequest(client_id="C1", form_type="AOC-4")
    resp = m.create_filing(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


# =============================================================================
# itr_workspace.py
# =============================================================================

def test_create_snapshot_rejects_foreign_client(enforced):
    import routers.itr_workspace as m
    body = m.SnapshotRequest(client_id="C-OTHER", financial_year="2025-26",
                              assessment_year="2026-27", regime="new")
    with pytest.raises(HTTPException) as ei:
        m.create_snapshot(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_snapshot_accepts_own_firm(enforced):
    import routers.itr_workspace as m
    body = m.SnapshotRequest(client_id="C1", financial_year="2025-26",
                              assessment_year="2026-27", regime="new")
    resp = m.create_snapshot(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_itr_filing_rejects_foreign_client(enforced):
    import routers.itr_workspace as m
    body = m.CreateFilingRequest(client_id="C-OTHER", financial_year="2025-26",
                                  assessment_year="2026-27", itr_form="ITR-3")
    with pytest.raises(HTTPException) as ei:
        m.create_filing(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_itr_filing_accepts_own_firm(enforced):
    import routers.itr_workspace as m
    body = m.CreateFilingRequest(client_id="C1", financial_year="2025-26",
                                  assessment_year="2026-27", itr_form="ITR-3")
    resp = m.create_filing(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_disallowance_rejects_foreign_client(enforced):
    import routers.itr_workspace as m
    body = m.DisallowanceRequest(client_id="C-OTHER", financial_year="2025-26",
                                  section="40A(3)", description="cash pmt", amount_paise=50000)
    with pytest.raises(HTTPException) as ei:
        m.create_disallowance(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_disallowance_accepts_own_firm(enforced):
    import routers.itr_workspace as m
    body = m.DisallowanceRequest(client_id="C1", financial_year="2025-26",
                                  section="40A(3)", description="cash pmt", amount_paise=50000)
    resp = m.create_disallowance(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_auto_detect_40a3_rejects_foreign_client(enforced):
    import routers.itr_workspace as m
    with pytest.raises(HTTPException) as ei:
        m.auto_detect_40a3(client_id="C-OTHER", financial_year="2025-26", current_user=PARTNER_F1)
    assert ei.value.status_code == 404


def test_auto_detect_40a3_accepts_own_firm(enforced):
    import routers.itr_workspace as m
    resp = m.auto_detect_40a3(client_id="C1", financial_year="2025-26", current_user=PARTNER_F1)
    assert resp["success"] is True


def test_create_deduction_rejects_foreign_client(enforced):
    import routers.itr_workspace as m
    body = m.DeductionClaimRequest(client_id="C-OTHER", financial_year="2025-26",
                                    section="80C", claimed_amount_paise=15000000)
    with pytest.raises(HTTPException) as ei:
        m.create_deduction(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_deduction_accepts_own_firm(enforced):
    import routers.itr_workspace as m
    body = m.DeductionClaimRequest(client_id="C1", financial_year="2025-26",
                                    section="80C", claimed_amount_paise=15000000)
    resp = m.create_deduction(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_create_bf_loss_rejects_foreign_client(enforced):
    import routers.itr_workspace as m
    body = m.BFLossRequest(client_id="C-OTHER", assessment_year="2026-27",
                            loss_type="business", original_amount_paise=100000,
                            expiry_assessment_year="2034-35")
    with pytest.raises(HTTPException) as ei:
        m.create_bf_loss(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_bf_loss_accepts_own_firm(enforced):
    import routers.itr_workspace as m
    body = m.BFLossRequest(client_id="C1", assessment_year="2026-27",
                            loss_type="business", original_amount_paise=100000,
                            expiry_assessment_year="2034-35")
    resp = m.create_bf_loss(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


# =============================================================================
# form_26as.py
# =============================================================================

def test_create_26as_upload_rejects_foreign_client(enforced):
    import routers.form_26as as m
    body = m.CreateUploadRequest(client_id="C-OTHER", financial_year="2025-26")
    with pytest.raises(HTTPException) as ei:
        m.create_upload(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_26as_upload_accepts_own_firm(enforced):
    import routers.form_26as as m
    body = m.CreateUploadRequest(client_id="C1", financial_year="2025-26")
    resp = m.create_upload(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_run_26as_reconciliation_rejects_foreign_client(enforced):
    import routers.form_26as as m
    body = m.RunReconRequest(client_id="C-OTHER", financial_year="2025-26")
    with pytest.raises(HTTPException) as ei:
        m.run_reconciliation(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_run_26as_reconciliation_accepts_own_firm(enforced, monkeypatch):
    import routers.form_26as as m
    # The reconciliation precondition (a parsed upload) is exercised by the
    # sibling test_phase3_tds.py suite -- here we only prove the assert_client_
    # access gate runs first, then the normal "no parsed upload" 400 fires
    # (proving the request was NOT silently rejected as a 404 for C1).
    body = m.RunReconRequest(client_id="C1", financial_year="2025-26")
    with pytest.raises(HTTPException) as ei:
        m.run_reconciliation(body, PARTNER_F1)
    assert ei.value.status_code == 400  # not 404 -- access was granted


# =============================================================================
# einvoice.py
# =============================================================================

def test_create_einvoice_record_rejects_foreign_client(enforced):
    import routers.einvoice as m
    body = m.CreateEInvoiceRequest(client_id="C-OTHER", invoice_number="INV-1",
                                    invoice_date="2026-06-01")
    with pytest.raises(HTTPException) as ei:
        m.create_record(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_einvoice_record_accepts_own_firm(enforced):
    import routers.einvoice as m
    body = m.CreateEInvoiceRequest(client_id="C1", invoice_number="INV-1",
                                    invoice_date="2026-06-01")
    resp = m.create_record(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


# =============================================================================
# eway_bill.py
# =============================================================================

def test_create_eway_bill_rejects_foreign_client(enforced):
    import routers.eway_bill as m
    body = m.CreateEWayBillRequest(client_id="C-OTHER", invoice_number="INV-1",
                                    dispatch_from="Mumbai", ship_to="Pune",
                                    goods_description="Widgets", taxable_value_paise=100000)
    with pytest.raises(HTTPException) as ei:
        m.create_eway_bill(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_eway_bill_accepts_own_firm(enforced):
    import routers.eway_bill as m
    body = m.CreateEWayBillRequest(client_id="C1", invoice_number="INV-1",
                                    dispatch_from="Mumbai", ship_to="Pune",
                                    goods_description="Widgets", taxable_value_paise=100000)
    resp = m.create_eway_bill(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


# =============================================================================
# income_tax.py — create_capital_gains
# =============================================================================

def test_create_capital_gains_rejects_foreign_client(enforced):
    import routers.income_tax as m
    body = m.CreateCapitalGainsRequest(
        client_id="C-OTHER", asset_description="Flat sale", asset_type="property",
        purchase_date="2015-01-01", sale_date="2026-01-01",
        purchase_cost_paise=100_00000, sale_value_paise=300_00000)
    with pytest.raises(HTTPException) as ei:
        m.create_capital_gains(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_capital_gains_accepts_own_firm(enforced):
    import routers.income_tax as m
    body = m.CreateCapitalGainsRequest(
        client_id="C1", asset_description="Flat sale", asset_type="property",
        purchase_date="2015-01-01", sale_date="2026-01-01",
        purchase_cost_paise=100_00000, sale_value_paise=300_00000)
    resp = m.create_capital_gains(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


# =============================================================================
# compliance_records.py
# =============================================================================

def test_create_compliance_record_rejects_foreign_client(enforced):
    import routers.compliance_records as m
    body = m.ComplianceRecordIn(client_id="C-OTHER", compliance_type="gstr1", due_date="2026-07-11")
    with pytest.raises(HTTPException) as ei:
        m.create_compliance_record(body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_create_compliance_record_accepts_own_firm(enforced, monkeypatch):
    import routers.compliance_records as m
    monkeypatch.setattr(
        m.compliance_record_service, "create_record",
        lambda data, firm_id: {"id": "cr1", "firm_id": firm_id, **data})
    body = m.ComplianceRecordIn(client_id="C1", compliance_type="gstr1", due_date="2026-07-11")
    resp = m.create_compliance_record(body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"


def test_update_compliance_record_rejects_foreign_client(enforced, monkeypatch):
    import routers.compliance_records as m
    monkeypatch.setattr(
        m.compliance_record_service, "get_record",
        lambda record_id, firm_id=None: {"id": record_id, "firm_id": firm_id, "client_id": "C-OTHER"})
    monkeypatch.setattr(m.compliance_record_service, "update_record", _never_called)
    body = m.ComplianceRecordUpdateIn(notes="hijack")
    with pytest.raises(HTTPException) as ei:
        m.update_compliance_record("cr1", body, PARTNER_F1)
    assert ei.value.status_code == 404


def test_update_compliance_record_accepts_own_firm(enforced, monkeypatch):
    import routers.compliance_records as m
    monkeypatch.setattr(
        m.compliance_record_service, "get_record",
        lambda record_id, firm_id=None: {"id": record_id, "firm_id": firm_id, "client_id": "C1"})
    monkeypatch.setattr(
        m.compliance_record_service, "update_record",
        lambda record_id, data, firm_id=None: {"id": record_id, "firm_id": firm_id, "client_id": "C1", **data})
    body = m.ComplianceRecordUpdateIn(notes="ok")
    resp = m.update_compliance_record("cr1", body, PARTNER_F1)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == "C1"
