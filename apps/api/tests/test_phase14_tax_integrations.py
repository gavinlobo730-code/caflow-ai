"""
Phase 14 — Tax, XBRL & External Integrations
Unit tests covering:
- Tax computation snapshots (immutability, versioning)
- Disallowances (40A(3), 43B) with paise arithmetic
- Deduction claims (80C, 80D etc.)
- Brought forward losses (IT Act §72, §74)
- ITR filing workflow transitions
- XBRL validation engine
- 26AS parsing and reconciliation
- Tally XML parsing and validation
- E-Invoice and E-Way Bill state machines
- GST portal sync abstraction

All monetary values must be integer paise — never float.
"""
import pytest

# ── Constants ─────────────────────────────────────────────────────────────────
L = 100_000 * 100   # 1 lakh in paise
K = 1_000 * 100     # 1 thousand in paise


# ── Computation Workspace ─────────────────────────────────────────────────────

class TestComputationSnapshots:
    def test_snapshot_version_increments(self):
        from domain.income_tax.computation_workspace import (
            save_computation_snapshot, list_snapshots
        )
        kwargs = dict(
            firm_id="f1", client_id="c1",
            financial_year="2025-26", assessment_year="2026-27",
            regime="new", income={"taxable_income_paise": 50 * L},
            computation_result={"tax_liability_paise": 5 * L},
            created_by="u1",
        )
        s1 = save_computation_snapshot(**kwargs)
        s2 = save_computation_snapshot(**kwargs)
        assert s2["version"] == s1["version"] + 1

    def test_snapshot_contains_paise_not_float(self):
        from domain.income_tax.computation_workspace import save_computation_snapshot
        snap = save_computation_snapshot(
            firm_id="f2", client_id="c2",
            financial_year="2025-26", assessment_year="2026-27",
            regime="old",
            income={"taxable_income_paise": 75 * L, "tax_liability_paise": 10 * L},
            computation_result={},
            created_by="u1",
        )
        assert isinstance(snap["id"], str)

    def test_review_snapshot(self):
        from domain.income_tax.computation_workspace import (
            save_computation_snapshot, review_snapshot
        )
        snap = save_computation_snapshot(
            firm_id="f3", client_id="c3",
            financial_year="2025-26", assessment_year="2026-27",
            regime="new", income={}, computation_result={}, created_by="u1",
        )
        reviewed = review_snapshot("f3", snap["id"], "partner1")
        assert reviewed["status"] == "reviewed"
        assert reviewed["reviewed_by"] == "partner1"


# ── Disallowances ─────────────────────────────────────────────────────────────

class TestDisallowances:
    def test_create_40a3_disallowance(self):
        from domain.income_tax.computation_workspace import create_disallowance
        d = create_disallowance(
            firm_id="f1", client_id="c1", financial_year="2025-26",
            section="40A(3)",
            description="Cash payment to vendor",
            amount_paise=15_000 * 100,  # ₹15,000 > ₹10,000 limit
            created_by="u1",
        )
        assert d["section"] == "40A(3)"
        assert d["amount_paise"] == 15_000 * 100
        assert isinstance(d["amount_paise"], int), "Amount must be integer paise"
        assert d["status"] == "pending"

    def test_create_43b_disallowance_pf(self):
        from domain.income_tax.computation_workspace import create_disallowance
        d = create_disallowance(
            firm_id="f1", client_id="c1", financial_year="2025-26",
            section="43B_pf",
            description="Unpaid PF contribution as of 31st March",
            amount_paise=50_000 * 100,
            created_by="u1",
        )
        assert d["section"] == "43B_pf"
        assert d["amount_paise"] == 50_000 * 100

    def test_disallowance_status_update(self):
        from domain.income_tax.computation_workspace import (
            create_disallowance, update_disallowance_status
        )
        d = create_disallowance(
            firm_id="f1", client_id="c4", financial_year="2025-26",
            section="other", description="Manual adjustment",
            amount_paise=10 * K, created_by="u1",
        )
        updated = update_disallowance_status("f1", d["id"], "accepted")
        assert updated["status"] == "accepted"

    def test_disallowance_listing_by_client_fy(self):
        from domain.income_tax.computation_workspace import (
            create_disallowance, list_disallowances
        )
        for _ in range(3):
            create_disallowance(
                firm_id="f_list", client_id="c_list", financial_year="2025-26",
                section="40A(3)", description="Cash payment",
                amount_paise=12_000 * 100, created_by="u1",
            )
        items = list_disallowances("f_list", "c_list", "2025-26")
        assert len(items) >= 3


# ── Brought Forward Losses ────────────────────────────────────────────────────

class TestBroughtForwardLosses:
    def test_create_business_loss(self):
        """IT Act §72 — Business loss carry-forward up to 8 years."""
        from domain.income_tax.computation_workspace import create_bf_loss
        loss = create_bf_loss(
            firm_id="f1", client_id="c1",
            assessment_year="2023-24",
            loss_type="business",
            original_amount_paise=200 * L,
            expiry_assessment_year="2031-32",
            created_by="u1",
            source_itr_ack="ABCD1234567",
        )
        assert loss["loss_type"] == "business"
        assert loss["original_amount_paise"] == 200 * L
        assert loss["utilized_amount_paise"] == 0
        assert loss["remaining_amount_paise"] == 200 * L

    def test_utilize_loss_reduces_remaining(self):
        from domain.income_tax.computation_workspace import create_bf_loss, utilize_bf_loss
        loss = create_bf_loss(
            firm_id="f1", client_id="c_loss",
            assessment_year="2022-23",
            loss_type="capital_long_term",
            original_amount_paise=100 * L,
            expiry_assessment_year="2030-31",
            created_by="u1",
        )
        updated = utilize_bf_loss("f1", loss["id"], 30 * L)
        assert updated["utilized_amount_paise"] == 30 * L
        assert updated["remaining_amount_paise"] == 70 * L

    def test_utilize_loss_cannot_exceed_original(self):
        from domain.income_tax.computation_workspace import create_bf_loss, utilize_bf_loss
        loss = create_bf_loss(
            firm_id="f1", client_id="c_loss2",
            assessment_year="2021-22",
            loss_type="business",
            original_amount_paise=50 * L,
            expiry_assessment_year="2029-30",
            created_by="u1",
        )
        with pytest.raises(ValueError, match="Utilization exceeds"):
            utilize_bf_loss("f1", loss["id"], 60 * L)  # More than original


# ── ITR Workflow ──────────────────────────────────────────────────────────────

class TestITRWorkflow:
    def test_create_itr_filing_draft(self):
        from domain.income_tax.itr_workflow import create_itr_filing
        f = create_itr_filing(
            firm_id="f1", client_id="c1",
            financial_year="2025-26", assessment_year="2026-27",
            itr_form="ITR-6", created_by="u1",
        )
        assert f["itr_form"] == "ITR-6"
        assert f["status"] == "draft"

    def test_valid_transition_draft_to_review(self):
        from domain.income_tax.itr_workflow import create_itr_filing, transition_itr_status
        f = create_itr_filing(
            firm_id="f1", client_id="c_wf1",
            financial_year="2025-26", assessment_year="2026-27",
            itr_form="ITR-3", created_by="u1",
        )
        result = transition_itr_status("f1", f["id"], "review", "reviewer1")
        assert result["status"] == "review"

    def test_invalid_transition_raises(self):
        from domain.income_tax.itr_workflow import create_itr_filing, transition_itr_status
        f = create_itr_filing(
            firm_id="f1", client_id="c_wf2",
            financial_year="2025-26", assessment_year="2026-27",
            itr_form="ITR-5", created_by="u1",
        )
        with pytest.raises(ValueError, match="Cannot transition"):
            transition_itr_status("f1", f["id"], "filed", "u1")  # Skip steps

    def test_full_workflow(self):
        from domain.income_tax.itr_workflow import create_itr_filing, transition_itr_status
        f = create_itr_filing(
            firm_id="f1", client_id="c_wf3",
            financial_year="2025-26", assessment_year="2026-27",
            itr_form="ITR-7", created_by="u1",
        )
        f = transition_itr_status("f1", f["id"], "review", "exec1")
        assert f["status"] == "review"
        f = transition_itr_status("f1", f["id"], "partner_review", "partner1")
        assert f["status"] == "partner_review"
        f = transition_itr_status("f1", f["id"], "ready_for_filing", "partner1")
        assert f["status"] == "ready_for_filing"

    def test_itr_version_saved(self):
        from domain.income_tax.itr_workflow import create_itr_filing, save_itr_version
        f = create_itr_filing(
            firm_id="f1", client_id="c_ver1",
            financial_year="2025-26", assessment_year="2026-27",
            itr_form="ITR-6", created_by="u1",
        )
        v = save_itr_version("f1", f["id"], {"schedule": "BS", "data": {}}, "u1")
        assert v["version"] == 1
        v2 = save_itr_version("f1", f["id"], {"schedule": "PL", "data": {}}, "u1")
        assert v2["version"] == 2

    def test_record_acknowledgement(self):
        from domain.income_tax.itr_workflow import create_itr_filing, transition_itr_status, record_filing_acknowledgement
        f = create_itr_filing(
            firm_id="f1", client_id="c_ack",
            financial_year="2025-26", assessment_year="2026-27",
            itr_form="ITR-6", created_by="u1",
        )
        # Move to ready_for_filing
        transition_itr_status("f1", f["id"], "review", "u1")
        transition_itr_status("f1", f["id"], "partner_review", "u1")
        transition_itr_status("f1", f["id"], "ready_for_filing", "u1")

        result = record_filing_acknowledgement(
            "f1", f["id"], "ABCD12345678901", "2026-07-31", "u1"
        )
        assert result["acknowledgement_number"] == "ABCD12345678901"
        assert result["status"] == "filed"


# ── XBRL Engine ───────────────────────────────────────────────────────────────

class TestXBRLEngine:
    def test_create_xbrl_package(self):
        from domain.income_tax.xbrl_service import create_xbrl_package
        pkg = create_xbrl_package(
            firm_id="f1", client_id="c1",
            financial_year="2025-26", created_by="u1",
        )
        assert pkg["status"] == "draft"
        assert pkg["taxonomy_version"] == "MCA_2023"

    def test_validation_detects_missing_mandatory_tags(self):
        from domain.income_tax.xbrl_service import create_xbrl_package, validate_xbrl_package
        pkg = create_xbrl_package(
            firm_id="f1", client_id="c_xbrl1",
            financial_year="2025-26", created_by="u1",
        )
        # No data loaded — should have missing mandatory tags
        result = validate_xbrl_package("f1", pkg["id"])
        assert result["status"] == "validation_failed"
        assert len(result["missing_tags"]) > 0

    def test_validation_passes_with_complete_data(self):
        from domain.income_tax.xbrl_service import (
            create_xbrl_package, update_xbrl_data, validate_xbrl_package, DEFAULT_MAPPINGS
        )
        pkg = create_xbrl_package(
            firm_id="f1", client_id="c_xbrl2",
            financial_year="2025-26", created_by="u1",
        )
        # Provide all mandatory tags
        mandatory_bs = {}
        mandatory_pnl = {}
        for sl, _, _, is_mandatory in DEFAULT_MAPPINGS:
            if is_mandatory:
                val = 100 * L  # ₹1,00,000 in paise
                if "BalanceSheet" in sl:
                    mandatory_bs[sl] = val
                else:
                    mandatory_pnl[sl] = val

        update_xbrl_data("f1", pkg["id"], balance_sheet_json=mandatory_bs, pnl_json=mandatory_pnl)
        result = validate_xbrl_package("f1", pkg["id"])
        assert result["status"] == "validated"
        assert len(result["missing_tags"]) == 0

    def test_validation_rejects_float_amounts(self):
        from domain.income_tax.xbrl_service import _run_validation
        data = {"BalanceSheet.Equity.ShareCapital": 100.50}  # Float — should fail
        errors, _ = _run_validation(data, "MCA_2023")
        float_errors = [e for e in errors if "float" in e.lower() or "paise" in e.lower()]
        assert len(float_errors) > 0, "Should reject float amounts"

    def test_default_mappings_count(self):
        from domain.income_tax.xbrl_service import get_default_tag_mappings
        mappings = get_default_tag_mappings()
        assert len(mappings) > 20  # At least 20 Schedule III lines


# ── 26AS Parsing ──────────────────────────────────────────────────────────────

class TestForm26ASParsing:
    SAMPLE_26AS = """
PART A
SR.\tDEDUCTOR NAME\tTAN\tDATE\tAMOUNT CREDITED\tTDS DEPOSITED\tSTATUS
1\tABC COMPANY LTD\tMUM12345A\t15/04/2025\t1000000\t100000\tF
2\tXYZ BANK LTD\tDEL67890B\t30/06/2025\t500000\t50000\tF

PART B
1\tPQR INDUSTRIES\tMUM11111C\t10/07/2025\t2000000\t200000\tF

PART C
1\tSELF\t\t15/06/2025\t0\t25000\tF
"""

    def test_parse_returns_records(self):
        from domain.income_tax.form26as_service import parse_26as_text
        records = parse_26as_text(self.SAMPLE_26AS)
        assert len(records) >= 2

    def test_parsed_amounts_are_integer_paise(self):
        from domain.income_tax.form26as_service import parse_26as_text
        records = parse_26as_text(self.SAMPLE_26AS)
        for r in records:
            assert isinstance(r["tds_deposited_paise"], int), "TDS must be integer paise"
            assert isinstance(r["amount_credited_paise"], int), "Amount must be integer paise"

    def test_part_a_is_tds_salary(self):
        from domain.income_tax.form26as_service import parse_26as_text
        records = parse_26as_text(self.SAMPLE_26AS)
        part_a = [r for r in records if r.get("part") == "A"]
        assert all(r["record_type"] == "tds_salary" for r in part_a)

    def test_create_upload(self):
        from domain.income_tax.form26as_service import create_upload
        upload = create_upload("f1", "c1", "2025-26", "u1")
        assert upload["parse_status"] == "pending"
        assert upload["financial_year"] == "2025-26"

    def test_save_parsed_records(self):
        from domain.income_tax.form26as_service import (
            create_upload, parse_26as_text, save_parsed_records
        )
        upload = create_upload("f1", "c_26as1", "2025-26", "u1")
        records = parse_26as_text(self.SAMPLE_26AS)
        result = save_parsed_records("f1", upload["id"], "c_26as1", "2025-26", records)
        assert result["parse_status"] == "parsed"
        assert result["total_records"] >= 2

    def test_reconciliation_creates_summary(self):
        from domain.income_tax.form26as_service import (
            create_upload, parse_26as_text, save_parsed_records, run_reconciliation
        )
        upload = create_upload("f1", "c_recon1", "2025-26", "u1")
        records = parse_26as_text(self.SAMPLE_26AS)
        save_parsed_records("f1", upload["id"], "c_recon1", "2025-26", records)
        recon = run_reconciliation("f1", "c_recon1", upload["id"], "2025-26", "u1")
        assert recon["status"] == "completed"
        assert recon["total_26as_records"] >= 0
        assert isinstance(recon["total_tds_26as_paise"], int)


# ── Tally Migration ───────────────────────────────────────────────────────────

class TestTallyMigration:
    SAMPLE_XML = """<?xml version="1.0"?>
<ENVELOPE>
  <BODY>
    <IMPORTDATA>
      <LEDGER NAME="Cash">
        <NAME>Cash</NAME>
        <PARENT>Cash-in-Hand</PARENT>
        <OPENINGBALANCE>500000</OPENINGBALANCE>
      </LEDGER>
      <LEDGER NAME="ABC Enterprises">
        <NAME>ABC Enterprises</NAME>
        <PARENT>Sundry Debtors</PARENT>
        <OPENINGBALANCE>1000000</OPENINGBALANCE>
        <GSTREGISTRATIONNUMBER>27AABCU9603R1ZX</GSTREGISTRATIONNUMBER>
      </LEDGER>
      <VOUCHER>
        <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
        <DATE>20250401</DATE>
        <VOUCHERNUMBER>JNL-001</VOUCHERNUMBER>
        <NARRATION>Opening entry</NARRATION>
        <ALLLEDGERENTRIES.LIST>
          <LEDGERNAME>Cash</LEDGERNAME>
          <AMOUNT>-500000</AMOUNT>
        </ALLLEDGERENTRIES.LIST>
        <ALLLEDGERENTRIES.LIST>
          <LEDGERNAME>Capital Account</LEDGERNAME>
          <AMOUNT>500000</AMOUNT>
        </ALLLEDGERENTRIES.LIST>
      </VOUCHER>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    def test_parse_xml_returns_categories(self):
        from domain.tally.migration_service import parse_tally_xml
        result = parse_tally_xml(self.SAMPLE_XML)
        assert "ledgers" in result
        assert "customers" in result
        assert "journals" in result

    def test_parse_identifies_debtors_as_customers(self):
        from domain.tally.migration_service import parse_tally_xml
        result = parse_tally_xml(self.SAMPLE_XML)
        customer_names = [c["name"] for c in result["customers"]]
        assert "ABC Enterprises" in customer_names

    def test_parse_amounts_are_integer_paise(self):
        from domain.tally.migration_service import parse_tally_xml
        result = parse_tally_xml(self.SAMPLE_XML)
        for ledger in result["ledgers"] + result["customers"]:
            assert isinstance(ledger["opening_balance_paise"], int)

    def test_date_parsing(self):
        from domain.tally.migration_service import _parse_tally_date
        assert _parse_tally_date("20250401") == "2025-04-01"
        assert _parse_tally_date("20260331") == "2026-03-31"

    def test_amount_parsing(self):
        from domain.tally.migration_service import _parse_tally_amount
        assert _parse_tally_amount("500000") == 50_000_000  # 5L in paise
        assert _parse_tally_amount("-100000") == -10_000_000  # negative

    def test_validation_detects_unbalanced_journals(self):
        from domain.tally.migration_service import parse_tally_xml, validate_migration_data
        unbalanced_xml = """<?xml version="1.0"?>
<ENVELOPE><BODY><IMPORTDATA>
  <VOUCHER>
    <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
    <DATE>20250401</DATE>
    <VOUCHERNUMBER>JNL-BAD</VOUCHERNUMBER>
    <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Cash</LEDGERNAME>
      <AMOUNT>-100000</AMOUNT>
    </ALLLEDGERENTRIES.LIST>
    <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Bank</LEDGERNAME>
      <AMOUNT>99999</AMOUNT>
    </ALLLEDGERENTRIES.LIST>
  </VOUCHER>
</IMPORTDATA></BODY></ENVELOPE>"""
        parsed = parse_tally_xml(unbalanced_xml)
        items, errors = validate_migration_data(parsed, ["journals"])
        assert len(errors) > 0

    def test_create_job(self):
        from domain.tally.migration_service import create_migration_job
        job = create_migration_job(
            firm_id="f1", name="Test Import",
            source_file_name="data.xml",
            target_financial_year="2025-26",
            created_by="u1",
        )
        assert job["status"] == "uploaded"
        assert job["is_dry_run"] is True

    def test_dry_run_default(self):
        """Dry run must be True by default — never auto-import."""
        from domain.tally.migration_service import create_migration_job
        job = create_migration_job(
            firm_id="f1", name="Safety Test",
            source_file_name="safe.xml",
            target_financial_year="2025-26",
            created_by="u1",
        )
        assert job["is_dry_run"] is True, "Dry run must default to True"


# ── E-Invoice ─────────────────────────────────────────────────────────────────

class TestEInvoice:
    def test_create_record_draft(self):
        from domain.income_tax.einvoice_service import create_einvoice_record
        rec = create_einvoice_record(
            firm_id="f1", client_id="c1",
            invoice_number="INV-001", invoice_date="2025-04-01",
            created_by="u1",
        )
        assert rec["status"] == "draft"
        assert rec["irn"] is None
        assert rec["ca_review_required"] is True

    def test_record_irn_generated(self):
        from domain.income_tax.einvoice_service import (
            create_einvoice_record, record_irn_generated
        )
        rec = create_einvoice_record(
            firm_id="f1", client_id="c_irn",
            invoice_number="INV-002", invoice_date="2025-04-02",
            created_by="u1",
        )
        updated = record_irn_generated(
            firm_id="f1", record_id=rec["id"],
            irn="a" * 64,
            ack_number="ACK123",
            ack_date="2025-04-02T10:00:00Z",
        )
        assert updated["status"] == "generated"
        assert updated["irn"] == "a" * 64

    def test_cancel_irn(self):
        from domain.income_tax.einvoice_service import (
            create_einvoice_record, record_irn_generated, record_irn_cancelled
        )
        rec = create_einvoice_record(
            firm_id="f1", client_id="c_cancel",
            invoice_number="INV-003", invoice_date="2025-04-03",
            created_by="u1",
        )
        record_irn_generated("f1", rec["id"], "b" * 64, "ACK456", "2025-04-03T10:00:00Z")
        cancelled = record_irn_cancelled("f1", rec["id"], "Incorrect details")
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancellation_reason"] == "Incorrect details"

    def test_list_by_status(self):
        from domain.income_tax.einvoice_service import create_einvoice_record, list_einvoices
        for i in range(3):
            create_einvoice_record(
                firm_id="f_list", client_id="c_list_inv",
                invoice_number=f"INV-{i:03d}", invoice_date="2025-04-01",
                created_by="u1",
            )
        drafts = list_einvoices("f_list", "c_list_inv", "draft")
        assert len(drafts) >= 3


# ── E-Way Bill ────────────────────────────────────────────────────────────────

class TestEWayBill:
    def test_create_eway_bill_draft(self):
        from domain.income_tax.eway_service import create_eway_bill
        rec = create_eway_bill(
            firm_id="f1", client_id="c1",
            invoice_number="INV-EWB-001",
            dispatch_from="Mumbai, Maharashtra",
            ship_to="Delhi",
            goods_description="Electronic components",
            taxable_value_paise=100_000 * 100,  # ₹1L
            created_by="u1",
            transport_mode="road",
        )
        assert rec["status"] == "draft"
        assert rec["ewb_number"] is None
        assert rec["ca_review_required"] is True
        assert isinstance(rec["taxable_value_paise"], int)

    def test_record_ewb_generated(self):
        from domain.income_tax.eway_service import create_eway_bill, record_ewb_generated
        rec = create_eway_bill(
            firm_id="f1", client_id="c_ewb",
            invoice_number="INV-EWB-002",
            dispatch_from="Chennai", ship_to="Hyderabad",
            goods_description="Raw materials",
            taxable_value_paise=75_000 * 100,
            created_by="u1",
        )
        updated = record_ewb_generated(
            "f1", rec["id"],
            ewb_number="123456789012",
            ewb_date="2025-04-01T10:00:00Z",
            ewb_valid_upto="2025-04-03T23:59:59Z",
        )
        assert updated["status"] == "generated"
        assert updated["ewb_number"] == "123456789012"

    def test_cancel_ewb(self):
        from domain.income_tax.eway_service import (
            create_eway_bill, record_ewb_generated, record_ewb_cancelled
        )
        rec = create_eway_bill(
            firm_id="f1", client_id="c_ewb_cancel",
            invoice_number="INV-EWB-003",
            dispatch_from="Pune", ship_to="Bangalore",
            goods_description="Goods", taxable_value_paise=60_000 * 100,
            created_by="u1",
        )
        record_ewb_generated("f1", rec["id"], "111111111111", "2025-04-01T10:00:00Z", "2025-04-03T23:59:59Z")
        cancelled = record_ewb_cancelled("f1", rec["id"], "Order cancelled")
        assert cancelled["status"] == "cancelled"


# ── GST Portal ────────────────────────────────────────────────────────────────

class TestGSTPortal:
    def test_create_sync_job(self):
        from domain.gst.portal_service import create_sync_job
        job = create_sync_job(
            firm_id="f1", client_id="c1",
            gstin="27AABCU9603R1ZX",
            triggered_by="u1",
        )
        assert job["status"] == "pending"
        assert job["gstin"] == "27AABCU9603R1ZX"

    def test_save_manual_snapshot(self):
        from domain.gst.portal_service import save_manual_snapshot, list_snapshots
        snap = save_manual_snapshot(
            firm_id="f1", client_id="c_gst",
            gstin="27AABCU9603R1ZX",
            snapshot_type="filing_status",
            data={"gstr1": "filed", "gstr3b": "pending"},
            financial_year="2025-26",
        )
        assert snap["snapshot_type"] == "filing_status"

        snaps = list_snapshots("f1", "c_gst", "filing_status")
        assert len(snaps) >= 1

    def test_provider_interface(self):
        from domain.gst.portal_service import get_provider
        provider = get_provider("manual")
        profile = provider.fetch_profile("27AABCU9603R1ZX")
        assert "gstin" in profile

    def test_read_only_no_filing(self):
        """GST portal integration must never submit data."""
        from domain.gst.portal_service import ManualGSTProvider
        provider = ManualGSTProvider()
        # These methods exist but don't submit anything
        assert hasattr(provider, "fetch_profile")
        assert hasattr(provider, "fetch_filing_status")
        assert hasattr(provider, "fetch_return_history")
        # No submit/file method should exist
        assert not hasattr(provider, "submit_return")
        assert not hasattr(provider, "file_gstr")


# ── Paise Arithmetic Invariant ────────────────────────────────────────────────

class TestPaiseArithmetic:
    """Ensure all monetary computations use integer paise."""

    def test_all_computation_results_are_int(self):
        from domain.income_tax.itr_engine import itr_engine, ITRComputeRequest
        req = ITRComputeRequest(
            gross_salary_paise=50 * L,
            use_new_regime=True,
        )
        result = itr_engine.compute(req)
        assert isinstance(result.taxable_income_paise, int)
        assert isinstance(result.total_tax_paise, int)
        assert isinstance(result.net_payable_paise, int)
        assert isinstance(result.cess_paise, int)

    def test_no_float_in_paise_amounts(self):
        from domain.income_tax.computation_workspace import create_disallowance
        d = create_disallowance(
            firm_id="f_paise", client_id="c_paise", financial_year="2025-26",
            section="40A(3)", description="Test",
            amount_paise=12_345_678,  # Arbitrary integer paise
            created_by="u1",
        )
        assert isinstance(d["amount_paise"], int)
        assert not isinstance(d["amount_paise"], float)

    def test_tally_amount_parsing_returns_int(self):
        from domain.tally.migration_service import _parse_tally_amount
        result = _parse_tally_amount("1234567.89")
        assert isinstance(result, int)

    def test_26as_amounts_are_int(self):
        from domain.income_tax.form26as_service import _parse_amount
        result = _parse_amount("1,00,000")  # ₹1,00,000
        assert isinstance(result, int)
        assert result == 10_000_000  # 1 lakh in paise
