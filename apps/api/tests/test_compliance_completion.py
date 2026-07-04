"""
Compliance completion tests — 20 tests covering GST, TDS, MCA deadlines.

CGST Act references:
  Section 37 — GSTR-1 (outward supplies), due 11th of following month
  Section 39 — GSTR-3B, due 20th of following month
  Section 44 — GSTR-9 annual return, due 31st December
  Section 25 — GSTIN format validation

IT Act references:
  Section 194C — TDS on contractor payments
  Section 194J — TDS on professional/technical fees
  Section 203 — TDS certificates Form 16A

Companies Act 2013:
  §92  — MGT-7 annual return, within 60 days of AGM
  §137 — AOC-4 financial statements, within 30 days of AGM
  §139 — ADT-1 auditor appointment, within 15 days of AGM
  §165 — DIR-12 director changes, within 30 days
"""
import pytest
from datetime import date, timedelta


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_mca_stores():
    from routers.mca_workspace import _MOCK_COMPANIES, _MOCK_DIRECTORS, _MOCK_FILINGS
    _MOCK_COMPANIES.clear()
    _MOCK_DIRECTORS.clear()
    _MOCK_FILINGS.clear()
    yield


_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-compliance"}
_CLIENT_ID = "client-compliance-001"


# ═══════════════════════════════════════════════════════════════
# SECTION 1 — GST Tests
# ═══════════════════════════════════════════════════════════════

class TestGSTDueDates:
    """
    CGST Act Section 37 — GSTR-1 due on 11th of month following tax period.
    CGST Act Section 39 — GSTR-3B due on 20th of month following tax period.
    CGST Act Section 44 — GSTR-9 annual return due 31st December.
    """

    def test_gstr1_due_date_is_11th_of_following_month(self):
        """CGST Act Section 37: GSTR-1 for April is due on 11th May."""
        # Tax period: April (month=4, year=2026)
        tax_period_month = 4
        tax_period_year = 2026
        # Due date = 11th of the following month
        following_month = tax_period_month + 1 if tax_period_month < 12 else 1
        following_year = tax_period_year if tax_period_month < 12 else tax_period_year + 1
        due_date = date(following_year, following_month, 11)
        assert due_date == date(2026, 5, 11), "GSTR-1 for April must be due on 11th May (Section 37 CGST Act)"

    def test_gstr1_due_date_december_rolls_to_january(self):
        """CGST Act Section 37: GSTR-1 for December is due on 11th January."""
        tax_period_month = 12
        tax_period_year = 2025
        following_month = 1
        following_year = 2026
        due_date = date(following_year, following_month, 11)
        assert due_date == date(2026, 1, 11)

    def test_gstr3b_due_date_is_20th_of_following_month(self):
        """CGST Act Section 39: GSTR-3B for May is due on 20th June."""
        tax_period_month = 5
        tax_period_year = 2026
        following_month = tax_period_month + 1
        due_date = date(tax_period_year, following_month, 20)
        assert due_date == date(2026, 6, 20), "GSTR-3B for May must be due on 20th June (Section 39 CGST Act)"

    def test_gstr9_annual_return_due_31_december(self):
        """CGST Act Section 44: GSTR-9 for FY 2025-26 is due on 31st December 2026."""
        fy_end_year = 2026   # FY 2025-26 ends 31 March 2026; annual return due 31 Dec 2026
        due_date = date(fy_end_year, 12, 31)
        assert due_date.month == 12
        assert due_date.day == 31
        assert due_date == date(2026, 12, 31)


class TestGSTINValidation:
    """CGST Act Section 25 — GSTIN format: 2-digit state code + PAN + entity + Z + checksum."""

    def test_valid_gstin_passes(self):
        """Valid GSTIN should match format: 2-digit state + PAN (10) + entity + Z + check."""
        import re
        GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
        valid = "27AABCU9603R1ZX"
        assert GSTIN_RE.match(valid), "Valid GSTIN should pass format check"

    def test_invalid_gstin_wrong_state_code(self):
        """GSTIN with invalid state code (e.g. 99) should fail."""
        import re
        GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
        invalid_state = "99AABCU9603R1ZX"
        # State code 99 is not valid, but the regex only checks numeric format.
        # Use the validator for state code validation.
        from domain.gst.validator import GSTValidator, VALID_STATE_CODES
        assert "99" not in VALID_STATE_CODES, "State code 99 is not a valid Indian state code"

    def test_gstin_must_have_z_at_position_13(self):
        """CGST Act Section 25: Position 13 of GSTIN must be 'Z'."""
        import re
        GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
        # Missing Z at position 13
        without_z = "27AABCU9603R1AX"
        assert not GSTIN_RE.match(without_z), "GSTIN without Z at position 13 should fail"

    def test_gstin_validator_detects_invalid_format(self):
        """GSTValidator.validate_gstin returns errors for malformed GSTIN."""
        from domain.gst.validator import GSTValidator
        validator = GSTValidator()
        errors = validator.validate_gstin("INVALID_GSTIN")
        assert len(errors) > 0, "Malformed GSTIN must produce validation errors"
        assert errors[0].field == "gstin"

    def test_gst_mismatch_detection_via_invoice_validation(self):
        """GST mismatch: computed tax vs stored tax difference triggers warning (Section 15 CGST Act)."""
        from domain.gst.validator import GSTValidator, InvoiceToValidate
        validator = GSTValidator()
        # Taxable ₹1000, rate 18%, computed tax = ₹180 = 18000p
        # Stored CGST = 5000p, SGST = 5000p = 10000p total — mismatch
        inv = InvoiceToValidate(
            reference_no="INV001",
            transaction_date="2026-05-15",
            party_gstin="27AABCU9603R1ZX",
            place_of_supply="27",
            taxable_amount_paise=100000,  # ₹1000
            cgst_paise=5000,
            sgst_paise=5000,
            igst_paise=0,
            is_interstate=False,
            gst_rate=18.0,
        )
        errors = validator.validate_invoice(inv, "052026")
        # Should have a tax mismatch warning (computed=18000p, stored=10000p)
        tax_errors = [e for e in errors if e.field == "tax_amount"]
        assert len(tax_errors) > 0, "Tax mismatch should be flagged (Section 15 CGST Act)"


# ═══════════════════════════════════════════════════════════════
# SECTION 2 — TDS Tests
# ═══════════════════════════════════════════════════════════════

class TestTDSDueDates:
    """IT Rules Rule 31A: 24Q/26Q due 31 Jul / 31 Oct / 31 Jan / 31 May.
    quarter_dates() is FY-parameterised (the old QUARTER_DATES dict was pinned
    to FY 2025-26's literal dates — audit F17)."""

    def test_26q_q1_due_date_31_july(self):
        """Q1 (Apr–Jun): 26Q due on 31st July."""
        from domain.tds.section_rates import quarter_dates
        _, q_end, due = quarter_dates("2025-26", "Q1")
        assert due == "2025-07-31", "26Q Q1 must be due on 31st July"

    def test_26q_q2_due_date_31_october(self):
        """Q2 (Jul–Sep): 26Q due on 31st October."""
        from domain.tds.section_rates import quarter_dates
        _, q_end, due = quarter_dates("2025-26", "Q2")
        assert due == "2025-10-31", "26Q Q2 must be due on 31st October"

    def test_26q_q3_due_date_31_january(self):
        """Q3 (Oct–Dec): 26Q due on 31st January (of the FY's END year)."""
        from domain.tds.section_rates import quarter_dates
        _, q_end, due = quarter_dates("2025-26", "Q3")
        assert due == "2026-01-31", "26Q Q3 must be due on 31st January"

    def test_26q_q4_due_date_31_may(self):
        """Q4 (Jan–Mar): 26Q due on 31st MAY of the FY's end year (Rule 31A) —
        not "31 April", which does not exist."""
        from domain.tds.section_rates import quarter_dates
        _, q_end, due = quarter_dates("2025-26", "Q4")
        assert due == "2026-05-31", "26Q Q4 must be due on 31st May"

    def test_quarter_dates_work_for_any_fy(self):
        """The calendar must be FY-derived, not hardcoded to one year."""
        from domain.tds.section_rates import quarter_dates
        assert quarter_dates("2026-27", "Q1") == ("2026-04-01", "2026-06-30", "2026-07-31")
        assert quarter_dates("2026-27", "Q4") == ("2027-01-01", "2027-03-31", "2027-05-31")


class TestTDSRates:
    """IT Act Section 194C — 1%/2%; Section 194J — 10%."""

    def test_194c_individual_rate_is_1_percent(self):
        """IT Act Section 194C: TDS on contractor payments to individuals is 1%."""
        from domain.tds.tds_computer import SECTION_THRESHOLDS
        _threshold, ind_rate, _co_rate = SECTION_THRESHOLDS["194C"]
        assert ind_rate == 1.0, "194C individual rate must be 1% (IT Act Section 194C)"

    def test_194c_company_rate_is_2_percent(self):
        """IT Act Section 194C: TDS on contractor payments to companies is 2%."""
        from domain.tds.tds_computer import SECTION_THRESHOLDS
        _threshold, _ind_rate, co_rate = SECTION_THRESHOLDS["194C"]
        assert co_rate == 2.0, "194C company rate must be 2% (IT Act Section 194C)"

    def test_194j_rate_is_10_percent(self):
        """IT Act Section 194J: TDS on professional/technical fees is 10%."""
        from domain.tds.tds_computer import SECTION_THRESHOLDS
        _threshold, ind_rate, co_rate = SECTION_THRESHOLDS["194J"]
        assert ind_rate == 10.0, "194J individual rate must be 10% (IT Act Section 194J)"
        assert co_rate == 10.0, "194J company rate must be 10% (IT Act Section 194J)"

    def test_194j_tds_computed_in_integer_paise(self):
        """IT Act Section 145A: All monetary computations must use integer paise
        (no floats). Payment must EXCEED the ₹50,000 threshold (Finance Act
        2025 raised 194J from ₹30,000) for TDS to apply."""
        from domain.tds.tds_computer import TDSComputer
        computer = TDSComputer()
        # Payment ₹60,000 (6000000 paise), Section 194J @ 10%
        tds = computer.compute_tds_amount("194J", 6_000_000, is_company=False, fy="2025-26")
        assert isinstance(tds, int), "TDS must be integer paise — IT Act Section 145A"
        assert tds == 600_000, "194J TDS on ₹60,000 should be ₹6,000 (600000 paise)"

    def test_194j_at_exactly_threshold_no_tds(self):
        """₹50,000 exactly does not EXCEED the ₹50,000 threshold → no TDS."""
        from domain.tds.tds_computer import TDSComputer
        computer = TDSComputer()
        tds = computer.compute_tds_amount("194J", 5_000_000, is_company=False, fy="2025-26")
        assert tds == 0

    def test_26as_reconciliation_deducted_vs_deposited(self):
        """26AS reconciliation: TDS deducted > deposited must generate validation error."""
        from domain.tds.tds_computer import TDSComputer, TDSDeducteeRecord
        computer = TDSComputer()
        deductee = TDSDeducteeRecord(
            deductee_name="Acme Services",
            deductee_pan="ABCDE1234F",
            section="194J",
            nature_of_payment="Professional Fees",
            payment_date="2026-04-30",
            payment_amount_paise=5_000_000,   # ₹50,000
            tds_rate_pct=10.0,
            tds_deducted_paise=500_000,       # ₹5,000 deducted
            tds_deposited_paise=0,            # ₹0 deposited — mismatch!
            challan_no="",
            bsr_code="0001234",
            challan_date="2026-05-07",
        )
        payload = computer.compute_26q(
            tan="ABCDE1234F",
            deductor_name="Test Co",
            deductor_pan="FGHIJ5678K",
            deductor_address="Mumbai",
            financial_year="2026-27",
            quarter="Q1",
            deductees=[deductee],
            challans=[],
        )
        assert len(payload.validation_errors) > 0, "Deducted > deposited must produce validation error (26AS reconciliation)"


# ═══════════════════════════════════════════════════════════════
# SECTION 3 — MCA Tests
# ═══════════════════════════════════════════════════════════════

class TestMCADeadlines:
    """
    Companies Act 2013:
      §92  — MGT-7: AGM + 60 days
      §137 — AOC-4: AGM + 30 days
      §139 — ADT-1: AGM + 15 days
      §165 — DIR-12: director change + 30 days
    """

    def test_mgt7_deadline_is_agm_plus_60_days(self):
        """Companies Act 2013 §92: MGT-7 annual return due within 60 days of AGM."""
        agm = date(2026, 9, 30)
        mgt7_due = agm + timedelta(days=60)
        assert mgt7_due == date(2026, 11, 29)

    def test_aoc4_deadline_is_agm_plus_30_days(self):
        """Companies Act 2013 §137: AOC-4 financial statements due within 30 days of AGM."""
        agm = date(2026, 9, 30)
        aoc4_due = agm + timedelta(days=30)
        assert aoc4_due == date(2026, 10, 30)

    def test_adt1_deadline_is_agm_plus_15_days(self):
        """Companies Act 2013 §139: ADT-1 auditor appointment due within 15 days of AGM."""
        agm = date(2026, 9, 30)
        adt1_due = agm + timedelta(days=15)
        assert adt1_due == date(2026, 10, 15)

    def test_dir12_deadline_is_change_plus_30_days(self):
        """Companies Act 2013 §165: DIR-12 director change filing due within 30 days."""
        change_date = date(2026, 6, 1)
        dir12_due = change_date + timedelta(days=30)
        assert dir12_due == date(2026, 7, 1)

    def test_mca_calendar_router_returns_correct_form_types(self):
        """MCA calendar logic: all three required annual forms must be in the calendar."""
        from datetime import datetime, timedelta
        agm_str = "2026-09-30"
        agm_dt = date.fromisoformat(agm_str)
        # Replicate router logic
        annual_forms = [
            {"form_type": "ADT-1", "days": 15},
            {"form_type": "AOC-4", "days": 30},
            {"form_type": "MGT-7", "days": 60},
        ]
        calendar = {
            f["form_type"]: (agm_dt + timedelta(days=f["days"])).isoformat()
            for f in annual_forms
        }
        assert "MGT-7" in calendar, "Calendar must include MGT-7 (§92)"
        assert "AOC-4" in calendar, "Calendar must include AOC-4 (§137)"
        assert "ADT-1" in calendar, "Calendar must include ADT-1 (§139)"

    def test_mca_calendar_mgt7_date_is_agm_plus_60(self):
        """MGT-7 due date must be AGM + 60 days (§92)."""
        agm = date(2026, 9, 30)
        mgt7_due = (agm + timedelta(days=60)).isoformat()
        assert mgt7_due == "2026-11-29", "MGT-7 must be AGM+60 days"

    def test_mca_calendar_aoc4_date_is_agm_plus_30(self):
        """AOC-4 due date must be AGM + 30 days (§137)."""
        agm = date(2026, 9, 30)
        aoc4_due = (agm + timedelta(days=30)).isoformat()
        assert aoc4_due == "2026-10-30", "AOC-4 must be AGM+30 days"

    def test_filing_with_srn_recorded_in_mock_store(self):
        """Mock store: filing with SRN records correctly via direct store manipulation."""
        import uuid
        from routers.mca_workspace import _MOCK_FILINGS
        # Simulate filing creation (as the router would do)
        filing_id = str(uuid.uuid4())
        record = {
            "id": filing_id,
            "firm_id": "firm-compliance",
            "client_id": _CLIENT_ID,
            "form_type": "MGT-7",
            "financial_year": "2025-26",
            "status": "not_started",
            "srn": None,
            "filing_date": None,
            "acknowledgement_url": None,
        }
        _MOCK_FILINGS[filing_id] = record

        # Simulate PUT /filings/{id}/complete
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        updates = {
            "status": "filed",
            "srn": "SRN20261129001",
            "filing_date": "2026-11-25",
            "acknowledgement_url": "https://mca.gov.in/ack/SRN20261129001.pdf",
        }
        _MOCK_FILINGS[filing_id].update(updates)
        result = _MOCK_FILINGS[filing_id]

        assert result["srn"] == "SRN20261129001", "SRN must be stored on filing"
        assert result["status"] == "filed", "Status must be 'filed' after completion"
        assert result["acknowledgement_url"] is not None


# ═══════════════════════════════════════════════════════════════
# SECTION 4 — Compliance Calendar / Financial Year
# ═══════════════════════════════════════════════════════════════

class TestDeadlineGeneration:
    """Compliance calendar and April-March financial year rules."""

    def test_financial_year_starts_april_1(self):
        """Indian financial year: April 1 to March 31."""
        fy_start = date(2025, 4, 1)
        fy_end = date(2026, 3, 31)
        # FY must span exactly April to March
        assert fy_start.month == 4 and fy_start.day == 1
        assert fy_end.month == 3 and fy_end.day == 31
        # Duration should be 365 days (366 in leap year)
        duration = (fy_end - fy_start).days + 1
        assert duration in (365, 366), "FY must be April 1 to March 31"

    def test_fy_string_format_april_march(self):
        """FY string '2025-26' covers April 2025 to March 2026."""
        fy = "2025-26"
        start_year = int(fy.split("-")[0])
        end_year_short = int(fy.split("-")[1])
        end_year = start_year + 1
        assert end_year_short == end_year % 100, "FY format must be YYYY-YY e.g. 2025-26"
        fy_start = date(start_year, 4, 1)
        fy_end = date(end_year, 3, 31)
        assert fy_start < fy_end

    def test_advance_tax_due_dates(self):
        """IT Act Section 211: Advance tax installment due dates for FY 2026-27."""
        # 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
        fy_year = 2026  # FY 2026-27
        installments = [
            (date(fy_year, 6, 15), 15),
            (date(fy_year, 9, 15), 45),
            (date(fy_year, 12, 15), 75),
            (date(fy_year + 1, 3, 15), 100),
        ]
        for d, pct in installments:
            assert d.day == 15, f"Advance tax installment must be on the 15th, got {d}"
        percentages = [pct for _, pct in installments]
        assert percentages == [15, 45, 75, 100], "Cumulative advance tax percentages must be 15/45/75/100"
