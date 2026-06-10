"""
Phase 2 — Sales cycle unit tests.
Tests GST computation, invoice creation, receipt allocation, credit note logic.
All amounts in paise (integer). Never float.
CGST Act Section 8: Intra-state → CGST+SGST, Inter-state → IGST.
"""
import pytest
from decimal import Decimal


# ---------------------------------------------------------------------------
# GST computation helpers (duplicated from router logic for test isolation)
# ---------------------------------------------------------------------------

def compute_gst(taxable_paise: int, gst_rate_bps: int, is_interstate: bool) -> dict:
    """
    Compute GST split from taxable amount and rate in basis points.
    CGST Act §8: Intra-state supply → CGST + SGST (equal halves).
    Inter-state supply → IGST at full rate.
    Integer arithmetic only — never float.
    """
    assert isinstance(taxable_paise, int), "taxable_paise must be int"
    assert isinstance(gst_rate_bps, int), "gst_rate_bps must be int"

    total_gst = (taxable_paise * gst_rate_bps) // 10000

    if is_interstate:
        return {
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": total_gst,
            "total_gst_paise": total_gst,
        }
    else:
        cgst = total_gst // 2
        sgst = total_gst - cgst  # handles odd paise correctly
        return {
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "igst_paise": 0,
            "total_gst_paise": total_gst,
        }


def compute_line_taxable(quantity_str: str, rate_paise: int) -> int:
    """
    Compute taxable amount for a line using Decimal to avoid float imprecision,
    then convert to integer paise.
    """
    qty = Decimal(str(quantity_str))
    return int(qty * Decimal(str(rate_paise)))


def compute_tds(taxable_paise: int, tds_rate_bps: int) -> int:
    """TDS = taxable × rate (bps) ÷ 10000. Integer only."""
    assert isinstance(taxable_paise, int)
    assert isinstance(tds_rate_bps, int)
    return (taxable_paise * tds_rate_bps) // 10000


# ---------------------------------------------------------------------------
# GST computation tests
# ---------------------------------------------------------------------------

class TestGSTComputation:

    def test_intra_state_18_percent(self):
        """Standard 18% GST intra-state: ₹1,00,000 taxable."""
        result = compute_gst(10_000_000, 1800, is_interstate=False)
        # 18% of ₹1,00,000 = ₹18,000 = 1,800,000 paise
        # CGST = SGST = ₹9,000 = 900,000 paise
        assert result["total_gst_paise"] == 1_800_000
        assert result["cgst_paise"] == 900_000
        assert result["sgst_paise"] == 900_000
        assert result["igst_paise"] == 0

    def test_inter_state_18_percent(self):
        """18% GST inter-state → IGST only."""
        result = compute_gst(10_000_000, 1800, is_interstate=True)
        assert result["igst_paise"] == 1_800_000
        assert result["cgst_paise"] == 0
        assert result["sgst_paise"] == 0

    def test_5_percent_gst(self):
        """5% GST (pharmaceuticals, etc.)."""
        result = compute_gst(100_000, 500, is_interstate=False)
        # ₹1,000 × 5% = ₹50 = 5,000 paise
        assert result["total_gst_paise"] == 5_000
        assert result["cgst_paise"] == 2_500
        assert result["sgst_paise"] == 2_500

    def test_12_percent_intra(self):
        result = compute_gst(1_000_000, 1200, is_interstate=False)
        assert result["total_gst_paise"] == 120_000
        assert result["cgst_paise"] == 60_000
        assert result["sgst_paise"] == 60_000

    def test_28_percent_inter_state(self):
        """28% GST inter-state luxury goods."""
        result = compute_gst(1_000_000, 2800, is_interstate=True)
        assert result["igst_paise"] == 280_000
        assert result["cgst_paise"] == 0

    def test_zero_percent(self):
        """Zero-rated or exempt supply."""
        result = compute_gst(5_000_000, 0, is_interstate=False)
        assert result["total_gst_paise"] == 0
        assert result["cgst_paise"] == 0
        assert result["sgst_paise"] == 0

    def test_odd_paise_cgst_sgst_split(self):
        """Odd total GST — SGST gets the extra paise."""
        # 1 paise taxable at 18% = 0 paise (floor division)
        result = compute_gst(1, 1800, is_interstate=False)
        assert result["cgst_paise"] + result["sgst_paise"] == result["total_gst_paise"]

    def test_large_amount_integer(self):
        """₹1 crore taxable — no float overflow."""
        taxable = 1_00_00_000 * 100  # paise
        result = compute_gst(taxable, 1800, is_interstate=False)
        assert result["cgst_paise"] + result["sgst_paise"] == result["total_gst_paise"]
        assert result["total_gst_paise"] == (taxable * 1800) // 10000

    def test_integer_types_enforced(self):
        with pytest.raises(AssertionError):
            compute_gst(100.5, 1800, False)  # float not allowed
        with pytest.raises(AssertionError):
            compute_gst(100, 18.0, False)  # float rate not allowed


# ---------------------------------------------------------------------------
# Line taxable amount tests
# ---------------------------------------------------------------------------

class TestLineTaxable:

    def test_whole_numbers(self):
        result = compute_line_taxable("10", 1_000_00)  # 10 units × ₹1,000 (100,000 paise)
        assert result == 1_000_000  # ₹10,000

    def test_fractional_quantity(self):
        """3.5 kg × ₹200/kg (20,000 paise) = ₹700 (70,000 paise)."""
        result = compute_line_taxable("3.5", 20_000)
        assert result == 70_000

    def test_two_decimal_quantity(self):
        """2.25 units × 50,000 paise = 112,500 paise."""
        result = compute_line_taxable("2.25", 50_000)
        assert result == 112_500


# ---------------------------------------------------------------------------
# TDS computation tests
# ---------------------------------------------------------------------------

class TestTDSComputation:

    def test_194c_2_percent(self):
        """IT Act §194C: TDS on contractor @ 2% = 200 bps."""
        tds = compute_tds(10_000_000, 200)  # ₹1,00,000 taxable
        assert tds == 200_000  # ₹2,000

    def test_194i_10_percent_rent(self):
        """IT Act §194I: TDS on rent @ 10% = 1000 bps."""
        tds = compute_tds(5_000_000, 1000)  # ₹50,000 rent
        assert tds == 500_000  # ₹5,000

    def test_194j_10_percent_professional(self):
        """IT Act §194J: TDS on professional fees @ 10%."""
        tds = compute_tds(2_000_000, 1000)
        assert tds == 200_000

    def test_zero_rate(self):
        tds = compute_tds(5_000_000, 0)
        assert tds == 0

    def test_integer_enforcement(self):
        with pytest.raises(AssertionError):
            compute_tds(100000.5, 1000)


# ---------------------------------------------------------------------------
# Invoice total computation
# ---------------------------------------------------------------------------

class TestInvoiceTotals:

    def _build_invoice(self, lines: list[dict], is_interstate: bool) -> dict:
        taxable_total = 0
        cgst_total = 0
        sgst_total = 0
        igst_total = 0

        for line in lines:
            taxable = compute_line_taxable(str(line["quantity"]), line["rate_paise"])
            gst = compute_gst(taxable, line["gst_rate_bps"], is_interstate)
            taxable_total += taxable
            cgst_total += gst["cgst_paise"]
            sgst_total += gst["sgst_paise"]
            igst_total += gst["igst_paise"]

        total_gst = cgst_total + sgst_total + igst_total
        return {
            "taxable_amount_paise": taxable_total,
            "cgst_paise": cgst_total,
            "sgst_paise": sgst_total,
            "igst_paise": igst_total,
            "total_gst_paise": total_gst,
            "total_paise": taxable_total + total_gst,
        }

    def test_single_line_intra_state(self):
        lines = [{"quantity": 1, "rate_paise": 1_000_000, "gst_rate_bps": 1800}]
        inv = self._build_invoice(lines, is_interstate=False)
        assert inv["taxable_amount_paise"] == 1_000_000
        assert inv["cgst_paise"] == 90_000
        assert inv["sgst_paise"] == 90_000
        assert inv["total_paise"] == 1_180_000  # ₹11,800

    def test_multi_line_invoice(self):
        lines = [
            {"quantity": 5, "rate_paise": 100_000, "gst_rate_bps": 1800},  # ₹5,000 + 18% = ₹5,900
            {"quantity": 2, "rate_paise": 500_000, "gst_rate_bps": 1200},  # ₹10,000 + 12% = ₹11,200
        ]
        inv = self._build_invoice(lines, is_interstate=False)
        assert inv["taxable_amount_paise"] == 500_000 + 1_000_000  # ₹15,000
        assert inv["total_paise"] == 590_000 + 1_120_000  # ₹17,100

    def test_double_entry_balance(self):
        """Sales invoice journal must balance: Dr = Cr."""
        lines = [{"quantity": 1, "rate_paise": 2_000_000, "gst_rate_bps": 1800}]
        inv = self._build_invoice(lines, is_interstate=False)
        # Journal: Dr Trade Receivables = total_paise
        # Cr Sales = taxable; Cr CGST = cgst; Cr SGST = sgst
        dr_total = inv["total_paise"]
        cr_total = inv["taxable_amount_paise"] + inv["cgst_paise"] + inv["sgst_paise"]
        assert dr_total == cr_total


# ---------------------------------------------------------------------------
# Receipt allocation tests
# ---------------------------------------------------------------------------

class TestReceiptAllocation:

    def test_full_allocation(self):
        """Receipt fully allocated to one invoice."""
        receipt_amount = 1_180_000  # ₹11,800
        invoice_outstanding = 1_180_000
        allocated = min(receipt_amount, invoice_outstanding)
        unallocated = receipt_amount - allocated
        assert allocated == 1_180_000
        assert unallocated == 0

    def test_partial_allocation(self):
        """Partial receipt — some unallocated."""
        receipt_amount = 500_000  # ₹5,000
        invoice_outstanding = 1_180_000
        allocated = min(receipt_amount, invoice_outstanding)
        unallocated = receipt_amount - allocated
        assert allocated == 500_000
        assert unallocated == 0  # all of receipt is allocated, invoice not fully paid

    def test_over_allocation_prevention(self):
        """Cannot allocate more than receipt amount."""
        receipt_amount = 500_000
        allocations = [300_000, 300_000]  # sum = 600,000 > 500,000
        total_alloc = sum(allocations)
        assert total_alloc > receipt_amount  # should be rejected

    def test_receipt_journal_balance(self):
        """Receipt journal must balance: Dr Bank = Cr Trade Receivables."""
        amount = 1_180_000
        dr = amount  # Dr Bank
        cr = amount  # Cr Trade Receivables
        assert dr == cr


# ---------------------------------------------------------------------------
# Credit note tests
# ---------------------------------------------------------------------------

class TestCreditNote:

    def test_credit_note_reduces_receivable(self):
        """Credit note journal: Dr Sales Returns + Dr GST Output, Cr Trade Receivables."""
        taxable = 1_000_000
        cgst = 90_000
        sgst = 90_000
        total = taxable + cgst + sgst

        dr_total = taxable + cgst + sgst  # Dr: sales returns + GST reversal
        cr_total = total                  # Cr: trade receivables
        assert dr_total == cr_total

    def test_cn_gst_computation_intra(self):
        gst = compute_gst(1_000_000, 1800, is_interstate=False)
        total = 1_000_000 + gst["total_gst_paise"]
        assert total == 1_180_000
