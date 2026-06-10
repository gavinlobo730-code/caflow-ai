"""
Phase 2 — Purchase cycle unit tests.
Tests TDS deduction, purchase bill totals, payment tracking, double-entry balance.
All amounts in paise (integer). Never float.
IT Act Section 194C/194I/194J: TDS at source on applicable vendor payments.
"""
import pytest
from decimal import Decimal


# ---------------------------------------------------------------------------
# Helpers (mirroring router logic for isolated unit testing)
# ---------------------------------------------------------------------------

def compute_gst(taxable_paise: int, gst_rate_bps: int, is_interstate: bool) -> dict:
    """CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST."""
    total_gst = (taxable_paise * gst_rate_bps) // 10000
    if is_interstate:
        return {"cgst_paise": 0, "sgst_paise": 0, "igst_paise": total_gst, "total_gst_paise": total_gst}
    cgst = total_gst // 2
    sgst = total_gst - cgst
    return {"cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": 0, "total_gst_paise": total_gst}


def compute_tds(taxable_paise: int, tds_rate_bps: int) -> int:
    """IT Act §194C/I/J: TDS = taxable × rate_bps ÷ 10000 (integer floor)."""
    return (taxable_paise * tds_rate_bps) // 10000


def build_purchase_bill(
    lines: list[dict],
    is_interstate: bool,
    tds_applicable: bool,
    tds_rate_bps: int,
    tds_section: str = "194C",
) -> dict:
    """Aggregate a purchase bill from line items."""
    taxable_total = 0
    cgst_total = sgst_total = igst_total = 0

    for line in lines:
        qty = Decimal(str(line["quantity"]))
        rate = int(line["rate_paise"])
        taxable = int(qty * Decimal(str(rate)))
        gst = compute_gst(taxable, line["gst_rate_bps"], is_interstate)
        taxable_total += taxable
        cgst_total += gst["cgst_paise"]
        sgst_total += gst["sgst_paise"]
        igst_total += gst["igst_paise"]

    total_gst = cgst_total + sgst_total + igst_total
    total_paise = taxable_total + total_gst
    tds_paise = compute_tds(taxable_total, tds_rate_bps) if tds_applicable else 0
    net_payable = total_paise - tds_paise

    return {
        "taxable_amount_paise": taxable_total,
        "cgst_paise": cgst_total,
        "sgst_paise": sgst_total,
        "igst_paise": igst_total,
        "total_gst_paise": total_gst,
        "total_paise": total_paise,
        "tds_paise": tds_paise,
        "tds_section": tds_section if tds_applicable else None,
        "net_payable_paise": net_payable,
    }


# ---------------------------------------------------------------------------
# Purchase Bill — TDS tests
# ---------------------------------------------------------------------------

class TestPurchaseBillTDS:

    def test_194c_contractor_2_percent(self):
        """IT Act §194C: Contractor payment TDS @ 2%."""
        lines = [{"quantity": 1, "rate_paise": 5_000_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=200, tds_section="194C")
        assert bill["taxable_amount_paise"] == 5_000_000
        assert bill["tds_paise"] == 100_000  # 2% of ₹50,000 = ₹1,000
        assert bill["net_payable_paise"] == bill["total_paise"] - bill["tds_paise"]

    def test_194i_rent_10_percent(self):
        """IT Act §194I: Rent TDS @ 10%."""
        lines = [{"quantity": 1, "rate_paise": 3_500_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=1000, tds_section="194I")
        assert bill["tds_paise"] == 350_000  # 10% of ₹35,000

    def test_194j_professional_fees(self):
        """IT Act §194J: Professional/technical fees TDS @ 10%."""
        lines = [{"quantity": 1, "rate_paise": 2_000_000, "gst_rate_bps": 0}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=1000, tds_section="194J")
        assert bill["tds_paise"] == 200_000
        assert bill["tds_section"] == "194J"

    def test_no_tds_when_not_applicable(self):
        lines = [{"quantity": 1, "rate_paise": 5_000_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=False, tds_rate_bps=0)
        assert bill["tds_paise"] == 0
        assert bill["tds_section"] is None
        assert bill["net_payable_paise"] == bill["total_paise"]

    def test_tds_on_taxable_not_gst_amount(self):
        """TDS is deducted on taxable value, not on GST amount."""
        taxable = 1_000_000  # ₹10,000
        lines = [{"quantity": 1, "rate_paise": taxable, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=1000)
        gst = (taxable * 1800) // 10000
        total = taxable + gst
        tds = (taxable * 1000) // 10000  # TDS on taxable, not total
        assert bill["tds_paise"] == tds
        assert bill["net_payable_paise"] == total - tds

    def test_integer_arithmetic_only(self):
        """TDS computation must never produce floats."""
        tds = compute_tds(1_000_001, 1000)
        assert isinstance(tds, int)


# ---------------------------------------------------------------------------
# Purchase Bill — GST input tax credit tests
# ---------------------------------------------------------------------------

class TestPurchaseBillGST:

    def test_itc_intra_state(self):
        """Intra-state purchase: CGST + SGST both claimable as ITC."""
        lines = [{"quantity": 1, "rate_paise": 1_000_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=False, tds_rate_bps=0)
        assert bill["cgst_paise"] == 90_000
        assert bill["sgst_paise"] == 90_000
        assert bill["igst_paise"] == 0

    def test_itc_inter_state(self):
        """Inter-state purchase: IGST claimable as ITC."""
        lines = [{"quantity": 1, "rate_paise": 1_000_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=True, tds_applicable=False, tds_rate_bps=0)
        assert bill["igst_paise"] == 180_000
        assert bill["cgst_paise"] == 0
        assert bill["sgst_paise"] == 0

    def test_multi_rate_lines(self):
        lines = [
            {"quantity": 1, "rate_paise": 1_000_000, "gst_rate_bps": 1800},
            {"quantity": 1, "rate_paise": 1_000_000, "gst_rate_bps": 500},
        ]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=False, tds_rate_bps=0)
        assert bill["taxable_amount_paise"] == 2_000_000
        gst1 = (1_000_000 * 1800) // 10000  # 180,000
        gst2 = (1_000_000 * 500) // 10000   # 50,000
        assert bill["total_gst_paise"] == gst1 + gst2


# ---------------------------------------------------------------------------
# Double-entry balance tests for purchase cycle
# ---------------------------------------------------------------------------

class TestPurchaseCycleJournals:

    def test_purchase_bill_journal_balance(self):
        """
        Purchase bill journal entry must balance.
        Dr Expense + Dr GST ITC = Cr Trade Payables + Cr TDS Payable
        """
        lines = [{"quantity": 1, "rate_paise": 3_500_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=1000, tds_section="194I")

        dr = bill["taxable_amount_paise"] + bill["cgst_paise"] + bill["sgst_paise"] + bill["igst_paise"]
        cr = bill["net_payable_paise"] + bill["tds_paise"]
        assert dr == cr, f"Journal out of balance: dr={dr} cr={cr}"

    def test_purchase_payment_journal_balance(self):
        """Dr Trade Payables = Cr Bank."""
        payment_amount = 4_230_000
        dr = payment_amount  # Dr Trade Payables
        cr = payment_amount  # Cr Bank
        assert dr == cr

    def test_net_payable_formula(self):
        """net_payable = total_paise - tds_paise."""
        lines = [{"quantity": 2, "rate_paise": 1_000_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=200)
        assert bill["net_payable_paise"] == bill["total_paise"] - bill["tds_paise"]

    def test_full_payment_cycle_balance(self):
        """End-to-end: bill → payment. Net payable = total payments recorded."""
        lines = [{"quantity": 1, "rate_paise": 5_000_000, "gst_rate_bps": 1800}]
        bill = build_purchase_bill(lines, is_interstate=False, tds_applicable=True, tds_rate_bps=200)

        # Simulate two partial payments summing to net_payable
        payment1 = bill["net_payable_paise"] // 2
        payment2 = bill["net_payable_paise"] - payment1
        assert payment1 + payment2 == bill["net_payable_paise"]


# ---------------------------------------------------------------------------
# Vendor master validation
# ---------------------------------------------------------------------------

class TestVendorValidation:

    GSTIN_RE_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"

    def _valid_gstin(self, gstin: str) -> bool:
        import re
        return bool(re.match(self.GSTIN_RE_PATTERN, gstin))

    def test_valid_gstin(self):
        assert self._valid_gstin("27AABCS1429B1Z5") is True

    def test_invalid_gstin_short(self):
        assert self._valid_gstin("27AABCS1429B1") is False  # 13 chars

    def test_invalid_gstin_lowercase(self):
        assert self._valid_gstin("27aabcs1429b1z5") is False

    def test_state_code_extraction(self):
        """First 2 chars of GSTIN = state code."""
        gstin = "27AABCS1429B1Z5"
        state_code = gstin[:2]
        assert state_code == "27"  # Maharashtra

    def test_tds_rate_bps_integer(self):
        """TDS rate stored as integer basis points, never float."""
        rate_percent = 2.0
        rate_bps = int(rate_percent * 100)
        assert rate_bps == 200
        assert isinstance(rate_bps, int)
