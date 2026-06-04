"""
TDS Engine unit tests.
IT Act Section 192 (salary TDS), Section 194 (non-salary TDS).
Section 206AA (PAN not available — 20% default rate).
Section 206AB (non-filers — doubled rate or 5%).
All monetary values in integer paise — IT Act Section 145A.
"""
import pytest
from domain.tds.tds_computer import TDSComputer, TDSDeducteeRecord, SECTION_THRESHOLDS
from domain.tds.tds_validator import TDSValidator


def make_deductee(
    name="ACME Corp",
    pan="ABCDE1234F",
    section="194J",
    payment_paise=100_000_00,
    tds_rate=10.0,
    tds_paise=10_000_00,
    deposited_paise=10_000_00,
    challan_no="CH001",
    bsr_code="0001234",
    challan_date="2025-05-31",
    payment_date="2025-05-15",
    nature="Professional fees",
):
    return TDSDeducteeRecord(
        deductee_name=name,
        deductee_pan=pan,
        section=section,
        nature_of_payment=nature,
        payment_date=payment_date,
        payment_amount_paise=payment_paise,
        tds_rate_pct=tds_rate,
        tds_deducted_paise=tds_paise,
        tds_deposited_paise=deposited_paise,
        challan_no=challan_no,
        bsr_code=bsr_code,
        challan_date=challan_date,
    )


# ── TDS Amount Computation ─────────────────────────────────────────────────────

class TestTDSAmountComputation:
    """IT Act Section 194 — threshold and rate tests."""

    def setup_method(self):
        self.c = TDSComputer()

    def test_194j_above_threshold(self):
        # Professional fees > 30,000 → 10% TDS
        amt = self.c.compute_tds_amount("194J", 50_000_00)
        assert amt == 5_000_00

    def test_194j_below_threshold_no_tds(self):
        # < 30,000 threshold → no TDS
        amt = self.c.compute_tds_amount("194J", 20_000_00)
        assert amt == 0

    def test_194c_individual_rate(self):
        # Contractor, individual → 1%
        amt = self.c.compute_tds_amount("194C", 50_000_00, is_company=False)
        assert amt == 500_00  # 1% of 50,000

    def test_194c_company_rate(self):
        # Contractor, company → 2%
        amt = self.c.compute_tds_amount("194C", 50_000_00, is_company=True)
        assert amt == 1_000_00  # 2% of 50,000

    def test_194a_below_threshold(self):
        # Interest < 4,000 → no TDS
        amt = self.c.compute_tds_amount("194A", 3_999_00)
        assert amt == 0

    def test_194a_above_threshold(self):
        # Interest = 10,000 → 10%
        amt = self.c.compute_tds_amount("194A", 10_000_00)
        assert amt == 1_000_00

    def test_194i_rent_above_threshold(self):
        # Rent 3,00,000 > 2,40,000 threshold → 10%
        amt = self.c.compute_tds_amount("194I", 300_000_00)
        assert amt == 30_000_00

    def test_integer_arithmetic_no_float(self):
        # 33,333 × 10% = 3,333.30 → floor = 333330 paise (IT Act Section 145A: integer paise)
        amt = self.c.compute_tds_amount("194J", 33_333_00)
        assert isinstance(amt, int)
        assert amt == 333_330  # floor(3333300 * 10 / 100) = 333330 paise

    def test_unknown_section_returns_zero(self):
        amt = self.c.compute_tds_amount("999X", 100_000_00)
        assert amt == 0


# ── 26Q Computation ────────────────────────────────────────────────────────────

class TestCompute26Q:
    """Form 26Q — non-salary TDS return."""

    def setup_method(self):
        self.c = TDSComputer()
        self.deductees = [
            make_deductee("Vendor A", "ABCDE1234F", "194J", 100_000_00, 10.0, 10_000_00, 10_000_00),
            make_deductee("Vendor B", "FGHIJ5678K", "194C", 50_000_00, 2.0, 1_000_00, 1_000_00),
        ]
        self.challans = [
            {"challan_no": "CH001", "bsr_code": "0001234", "payment_date": "2025-05-31",
             "tds_paise": 11_000_00, "total_paise": 11_000_00}
        ]

    def _compute(self):
        return self.c.compute_26q(
            tan="MUMA01234A",
            deductor_name="Test Firm",
            deductor_pan="AAAAA0000A",
            deductor_address="Mumbai",
            financial_year="2025-26",
            quarter="Q1",
            deductees=self.deductees,
            challans=self.challans,
        )

    def test_total_payment_aggregation(self):
        p = self._compute()
        assert p.total_payment_paise == 150_000_00  # 1L + 50K

    def test_total_tds_deducted(self):
        p = self._compute()
        assert p.total_tds_deducted_paise == 11_000_00  # 10K + 1K

    def test_deductee_count(self):
        p = self._compute()
        assert len(p.deductees) == 2

    def test_salary_deductee_excluded_from_26q(self):
        # 192 (salary) deductees should NOT appear in 26Q
        salary = make_deductee(section="192")
        p = self.c.compute_26q(
            tan="MUMA01234A", deductor_name="Firm", deductor_pan="AAAAA0000A",
            deductor_address="Mumbai", financial_year="2025-26", quarter="Q1",
            deductees=self.deductees + [salary], challans=[],
        )
        sections = [d.section for d in p.deductees]
        assert "192" not in sections

    def test_no_validation_errors_when_correct(self):
        p = self._compute()
        assert p.validation_errors == []

    def test_validation_error_on_short_tan(self):
        p = self.c.compute_26q(
            tan="SHORT",  # invalid
            deductor_name="Firm", deductor_pan="AAAAA0000A",
            deductor_address="Mumbai", financial_year="2025-26", quarter="Q1",
            deductees=self.deductees, challans=[],
        )
        assert any("TAN" in e for e in p.validation_errors)

    def test_section_206aa_pan_not_available(self):
        # PAN not available → rate must be ≥ 20%
        d = make_deductee(pan="PANNOTAVBL", tds_rate=10.0)
        p = self.c.compute_26q(
            tan="MUMA01234A", deductor_name="Firm", deductor_pan="AAAAA0000A",
            deductor_address="Mumbai", financial_year="2025-26", quarter="Q1",
            deductees=[d], challans=[],
        )
        assert any("206AA" in e for e in p.validation_errors)

    def test_tds_deposit_gap_error(self):
        # More deducted than deposited → error
        d = make_deductee(tds_paise=10_000_00, deposited_paise=5_000_00)
        p = self.c.compute_26q(
            tan="MUMA01234A", deductor_name="Firm", deductor_pan="AAAAA0000A",
            deductor_address="Mumbai", financial_year="2025-26", quarter="Q1",
            deductees=[d], challans=[],
        )
        assert any("deducted" in e.lower() for e in p.validation_errors)


# ── 24Q Computation ────────────────────────────────────────────────────────────

class TestCompute24Q:
    """Form 24Q — salary TDS return."""

    def setup_method(self):
        self.c = TDSComputer()
        self.salary_deductees = [
            make_deductee("Employee A", "EMPA01234F", "192", 600_000_00, 15.0, 90_000_00, 90_000_00, nature="Salary"),
            make_deductee("Employee B", "EMPB05678G", "192", 400_000_00, 10.0, 40_000_00, 40_000_00, nature="Salary"),
        ]

    def _compute(self):
        return self.c.compute_24q(
            tan="MUMA01234A",
            deductor_name="Employer Firm",
            deductor_pan="AAAAA0000A",
            deductor_address="Mumbai",
            financial_year="2025-26",
            quarter="Q1",
            deductees=self.salary_deductees,
            challans=[],
        )

    def test_total_salary(self):
        p = self._compute()
        assert p.total_salary_paise == 1_000_000_00  # 6L + 4L

    def test_total_tds_deducted(self):
        p = self._compute()
        assert p.total_tds_deducted_paise == 130_000_00  # 90K + 40K

    def test_non_salary_excluded_from_24q(self):
        # 194J deductee should NOT appear in 24Q
        professional = make_deductee(section="194J")
        p = self.c.compute_24q(
            tan="MUMA01234A", deductor_name="Firm", deductor_pan="AAAAA0000A",
            deductor_address="Mumbai", financial_year="2025-26", quarter="Q1",
            deductees=self.salary_deductees + [professional], challans=[],
        )
        sections = [d.section for d in p.deductees]
        assert "194J" not in sections
        assert all(s == "192" for s in sections)

    def test_empty_quarter_warning(self):
        p = self.c.compute_24q(
            tan="MUMA01234A", deductor_name="Firm", deductor_pan="AAAAA0000A",
            deductor_address="Mumbai", financial_year="2025-26", quarter="Q1",
            deductees=[], challans=[],
        )
        assert any("No salary" in w for w in p.warnings)


# ── TDS Validator ─────────────────────────────────────────────────────────────

class TestTDSValidator:
    def test_valid_pan(self):
        assert TDSValidator.validate_pan("ABCDE1234F") is True

    def test_invalid_pan(self):
        assert TDSValidator.validate_pan("INVALID") is False

    def test_pannotavbl_accepted(self):
        assert TDSValidator.validate_pan("PANNOTAVBL") is True

    def test_valid_tan(self):
        assert TDSValidator.validate_tan("MUMB01234A") is True

    def test_invalid_tan(self):
        assert TDSValidator.validate_tan("INVALID") is False

    def test_206aa_pan_not_available_rate(self):
        # IT Act Section 206AA: no PAN → max(base_rate, 20%)
        rate = TDSValidator.applicable_rate("194J", has_pan=False, base_rate=10.0)
        assert rate == 20.0

    def test_206aa_pan_available_base_rate(self):
        rate = TDSValidator.applicable_rate("194J", has_pan=True, base_rate=10.0)
        assert rate == 10.0

    def test_206ab_non_filer_doubled(self):
        # IT Act Section 206AB: non-filer → max(base*2, 5%)
        rate = TDSValidator.is_higher_rate_applicable("ABCDE1234F", is_non_filer=True, base_rate=10.0)
        assert rate == 20.0

    def test_206ab_non_filer_minimum_5pct(self):
        rate = TDSValidator.is_higher_rate_applicable("ABCDE1234F", is_non_filer=True, base_rate=1.0)
        assert rate == 5.0

    def test_206ab_filer_no_change(self):
        rate = TDSValidator.is_higher_rate_applicable("ABCDE1234F", is_non_filer=False, base_rate=10.0)
        assert rate == 10.0


# ── Threshold Table Integrity ─────────────────────────────────────────────────

class TestThresholdTable:
    def test_all_thresholds_non_negative(self):
        for sec, (thresh, ind, co) in SECTION_THRESHOLDS.items():
            assert thresh >= 0, f"Section {sec}: negative threshold"
            assert ind >= 0, f"Section {sec}: negative individual rate"
            assert co >= 0, f"Section {sec}: negative company rate"

    def test_integer_thresholds(self):
        for sec, (thresh, _, _) in SECTION_THRESHOLDS.items():
            assert isinstance(thresh, int), f"Section {sec}: threshold must be int paise"

    def test_common_sections_present(self):
        for sec in ["192", "194A", "194C", "194J", "194I", "194H"]:
            assert sec in SECTION_THRESHOLDS, f"Section {sec} missing from threshold table"
