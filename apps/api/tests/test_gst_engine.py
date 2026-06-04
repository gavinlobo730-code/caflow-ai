"""Unit tests for the GST filing engine.

Every monetary computation has a corresponding test.
All amounts in integer paise. Never float.
"""
import pytest
from domain.gst.classifier import (
    GSTInvoiceCategory,
    TransactionForClassification,
    classify_transaction,
    classify_transactions,
    B2CL_THRESHOLD_PAISE,
)
from domain.gst.gstr3b_computer import (
    SalesTransaction,
    PurchaseTransaction,
    GSTR2ARecord,
    compute_gstr3b,
    _apply_rule_36_4_cap,
)
from domain.gst.gstr1_builder import (
    InvoiceForGSTR1,
    InvoiceLine,
    build_gstr1,
    _paise_to_rupees,
    _format_date_gstn,
    _build_hsn_summary,
)
from domain.gst.validator import GSTValidator, InvoiceToValidate


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_sale(
    party_gstin=None,
    is_interstate=False,
    taxable_paise=100_000_00,   # ₹1,00,000
    gst_rate=18.0,
    supply_type="taxable",
    is_reverse_charge=False,
    transaction_type="sales_invoice",
) -> SalesTransaction:
    tax = int(taxable_paise * gst_rate / 100)
    if is_interstate:
        return SalesTransaction(
            transaction_type=transaction_type,
            taxable_amount_paise=taxable_paise,
            cgst_paise=0, sgst_paise=0, igst_paise=tax, cess_paise=0,
            supply_type=supply_type, is_reverse_charge=is_reverse_charge,
        )
    half = tax // 2
    return SalesTransaction(
        transaction_type=transaction_type,
        taxable_amount_paise=taxable_paise,
        cgst_paise=half, sgst_paise=half, igst_paise=0, cess_paise=0,
        supply_type=supply_type, is_reverse_charge=is_reverse_charge,
    )


def make_purchase(taxable_paise=50_000_00, gst_rate=18.0, is_interstate=False) -> PurchaseTransaction:
    tax = int(taxable_paise * gst_rate / 100)
    if is_interstate:
        return PurchaseTransaction(
            taxable_amount_paise=taxable_paise,
            cgst_paise=0, sgst_paise=0, igst_paise=tax, cess_paise=0,
            is_reverse_charge=False,
        )
    half = tax // 2
    return PurchaseTransaction(
        taxable_amount_paise=taxable_paise,
        cgst_paise=half, sgst_paise=half, igst_paise=0, cess_paise=0,
        is_reverse_charge=False,
    )


def make_txn_for_classify(
    transaction_type="sales_invoice",
    party_gstin=None,
    is_interstate=False,
    taxable_paise=100_000_00,
    supply_type="taxable",
    invoice_type="Regular",
    place_of_supply="27",
) -> TransactionForClassification:
    return TransactionForClassification(
        id="test-id",
        transaction_type=transaction_type,
        party_gstin=party_gstin,
        is_interstate=is_interstate,
        taxable_amount_paise=taxable_paise,
        supply_type=supply_type,
        invoice_type=invoice_type,
        place_of_supply=place_of_supply,
    )


def make_invoice_for_gstr1(
    id="inv-001",
    reference_no="INV/2025/001",
    transaction_date="2025-05-15",
    party_gstin="27AABCU9603R1ZX",
    party_name="Test Co",
    place_of_supply="27",
    is_interstate=False,
    taxable_paise=100_000_00,
    gst_rate=18.0,
    category=GSTInvoiceCategory.B2B,
    transaction_type="sales_invoice",
    lines=None,
) -> InvoiceForGSTR1:
    tax = int(taxable_paise * gst_rate / 100)
    half = tax // 2
    return InvoiceForGSTR1(
        id=id,
        transaction_type=transaction_type,
        reference_no=reference_no,
        transaction_date=transaction_date,
        party_gstin=party_gstin,
        party_name=party_name,
        place_of_supply=place_of_supply,
        is_interstate=is_interstate,
        taxable_amount_paise=taxable_paise,
        cgst_paise=half,
        sgst_paise=half,
        igst_paise=0,
        cess_paise=0,
        is_reverse_charge=False,
        invoice_type="Regular",
        supply_type="taxable",
        gst_invoice_category=category,
        original_invoice_ref=None,
        original_invoice_date=None,
        lines=lines or [],
    )


# ── Classifier Tests ──────────────────────────────────────────────────────────

class TestInvoiceClassifier:
    def test_b2b_registered_buyer(self):
        txn = make_txn_for_classify(party_gstin="27AABCU9603R1ZX")
        assert classify_transaction(txn) == GSTInvoiceCategory.B2B

    def test_b2cs_unregistered_intrastate(self):
        txn = make_txn_for_classify(party_gstin=None, is_interstate=False)
        assert classify_transaction(txn) == GSTInvoiceCategory.B2CS

    def test_b2cs_unregistered_interstate_below_threshold(self):
        # Interstate but taxable ≤ ₹2.5L → B2CS
        txn = make_txn_for_classify(
            party_gstin=None, is_interstate=True,
            taxable_paise=B2CL_THRESHOLD_PAISE,  # exactly ₹2.5L = B2CS (not >)
        )
        assert classify_transaction(txn) == GSTInvoiceCategory.B2CS

    def test_b2cl_unregistered_interstate_above_threshold(self):
        # Interstate taxable > ₹2.5L → B2CL
        txn = make_txn_for_classify(
            party_gstin=None, is_interstate=True,
            taxable_paise=B2CL_THRESHOLD_PAISE + 1,
        )
        assert classify_transaction(txn) == GSTInvoiceCategory.B2CL

    def test_cdnr_credit_note_registered(self):
        txn = make_txn_for_classify(
            transaction_type="credit_note", party_gstin="27AABCU9603R1ZX"
        )
        assert classify_transaction(txn) == GSTInvoiceCategory.CDNR

    def test_cdna_credit_note_unregistered(self):
        txn = make_txn_for_classify(transaction_type="credit_note", party_gstin=None)
        assert classify_transaction(txn) == GSTInvoiceCategory.CDNA

    def test_debit_note_registered(self):
        txn = make_txn_for_classify(
            transaction_type="debit_note", party_gstin="27AABCU9603R1ZX"
        )
        assert classify_transaction(txn) == GSTInvoiceCategory.CDNR

    def test_nil_rated_supply(self):
        txn = make_txn_for_classify(supply_type="nil_rated", party_gstin="27AABCU9603R1ZX")
        assert classify_transaction(txn) == GSTInvoiceCategory.NIL_EXEMPT

    def test_exempt_supply(self):
        txn = make_txn_for_classify(supply_type="exempt")
        assert classify_transaction(txn) == GSTInvoiceCategory.NIL_EXEMPT

    def test_export_sez_with_payment(self):
        """SEZ_with_payment invoice_type → EXP_WP regardless of supply_type."""
        txn = make_txn_for_classify(invoice_type="SEZ_with_payment", is_interstate=True)
        assert classify_transaction(txn) == GSTInvoiceCategory.EXP_WP

    def test_export_sez_without_payment(self):
        """SEZ_without_payment takes precedence over zero_rated → EXP_WOP."""
        txn = make_txn_for_classify(
            supply_type="zero_rated", invoice_type="SEZ_without_payment", is_interstate=True
        )
        assert classify_transaction(txn) == GSTInvoiceCategory.EXP_WOP

    def test_export_zero_rated_regular_defaults_to_wopay(self):
        """Regular export (zero_rated, no explicit invoice_type) → EXP_WOP (conservative).

        Without an explicit payment indicator we cannot assume IGST was paid.
        Defaulting to EXP_WOP is safe — CA will correct if IGST was paid.
        """
        txn = make_txn_for_classify(supply_type="zero_rated", is_interstate=True, place_of_supply="96")
        assert classify_transaction(txn) == GSTInvoiceCategory.EXP_WOP

    def test_batch_classification(self):
        txns = [
            TransactionForClassification("t1", "sales_invoice", "27AABCU9603R1ZX", False, 100_000_00, "taxable", "Regular", "27"),
            TransactionForClassification("t2", "sales_invoice", None, False, 50_000_00, "taxable", "Regular", "27"),
            TransactionForClassification("t3", "credit_note", "27AABCU9603R1ZX", False, 10_000_00, "taxable", "Regular", "27"),
        ]
        results = classify_transactions(txns)
        assert results["t1"] == GSTInvoiceCategory.B2B
        assert results["t2"] == GSTInvoiceCategory.B2CS
        assert results["t3"] == GSTInvoiceCategory.CDNR


# ── GSTR-3B Computation Tests ─────────────────────────────────────────────────

class TestGSTR3BComputer:
    def test_basic_intrastate_supply_18pct(self):
        """₹1,00,000 taxable at 18% → ₹9,000 CGST + ₹9,000 SGST output."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0)]
        result = compute_gstr3b(sales, [], [])
        assert result.outward_taxable_cgst == 9_000_00
        assert result.outward_taxable_sgst == 9_000_00
        assert result.outward_taxable_igst == 0

    def test_basic_interstate_supply_18pct(self):
        """₹1,00,000 inter-state at 18% → ₹18,000 IGST."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0, is_interstate=True)]
        result = compute_gstr3b(sales, [], [])
        assert result.outward_taxable_igst == 18_000_00
        assert result.outward_taxable_cgst == 0
        assert result.outward_taxable_sgst == 0

    def test_itc_from_purchases(self):
        """₹50,000 purchase at 18% gives ₹4,500 each CGST/SGST ITC."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0)]
        purchases = [make_purchase(taxable_paise=50_000_00, gst_rate=18.0)]
        result = compute_gstr3b(sales, purchases, [])
        assert result.itc_cgst == 4_500_00
        assert result.itc_sgst == 4_500_00

    def test_net_tax_payable_after_itc(self):
        """₹1L sales 18% → ₹9,000 CGST output. ₹50K purchase 18% → ₹4,500 ITC. Net = ₹4,500."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0)]
        purchases = [make_purchase(taxable_paise=50_000_00, gst_rate=18.0)]
        result = compute_gstr3b(sales, purchases, [])
        assert result.net_cgst == 4_500_00
        assert result.net_sgst == 4_500_00
        assert result.net_igst == 0

    def test_rule_36_4_cap_applied(self):
        """ITC capped at 105% of GSTR-2A when book ITC exceeds cap."""
        # Book ITC: ₹10,000 CGST. GSTR-2A: ₹8,000 CGST. Cap = 8,000 * 1.05 = 8,400
        book_cgst = 10_000_00
        gstr2a_cgst = 8_000_00
        cap = (gstr2a_cgst * 105) // 100  # = 8,400_00

        sales = [SalesTransaction("sales_invoice", 100_000_00, 9_000_00, 9_000_00, 0, 0, "taxable", False)]
        purchases = [PurchaseTransaction(55_555_55, book_cgst, book_cgst, 0, 0, False)]
        gstr2a = [GSTR2ARecord(cgst_paise=gstr2a_cgst, sgst_paise=0, igst_paise=0)]

        result = compute_gstr3b(sales, purchases, gstr2a)
        assert result.itc_cgst == cap
        assert result.itc_capped_by_2a is True

    def test_rule_36_4_no_cap_when_book_within_limit(self):
        """No cap applied when book ITC ≤ 105% of GSTR-2A."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0)]
        purchases = [make_purchase(taxable_paise=50_000_00, gst_rate=18.0)]
        gstr2a = [GSTR2ARecord(cgst_paise=5_000_00, sgst_paise=0, igst_paise=0)]  # 4500 book < 5000 * 1.05 = 5250
        result = compute_gstr3b(sales, purchases, gstr2a)
        assert result.itc_cgst == 4_500_00  # not capped
        assert result.itc_capped_by_2a is False

    def test_rule_36_4_no_cap_when_gstr2a_is_zero(self):
        """No cap applied when GSTR-2A records absent — CA should upload GSTR-2A."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0)]
        purchases = [make_purchase(taxable_paise=50_000_00, gst_rate=18.0)]
        result = compute_gstr3b(sales, purchases, [])  # no GSTR-2A
        assert result.itc_cgst == 4_500_00
        assert result.itc_capped_by_2a is False

    def test_zero_tax_when_no_sales(self):
        result = compute_gstr3b([], [], [])
        assert result.outward_taxable_cgst == 0
        assert result.net_cgst == 0

    def test_multiple_sales_aggregated(self):
        """Three ₹1L sales at 18% → ₹27,000 CGST output total."""
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0) for _ in range(3)]
        result = compute_gstr3b(sales, [], [])
        assert result.outward_taxable_cgst == 27_000_00
        assert result.outward_taxable_sgst == 27_000_00

    def test_nil_exempt_not_included_in_output_tax(self):
        """Nil-rated supply does not contribute to output tax."""
        sales = [
            make_sale(taxable_paise=100_000_00, gst_rate=18.0),
            make_sale(taxable_paise=50_000_00, gst_rate=0.0, supply_type="nil_rated"),
        ]
        result = compute_gstr3b(sales, [], [])
        assert result.outward_taxable_cgst == 9_000_00  # only from first sale
        assert result.outward_nil_exempt == 50_000_00

    def test_igst_excess_offset_against_cgst_sgst(self):
        """Excess IGST ITC is split equally against CGST and SGST (Section 49(5))."""
        # Output: ₹5,000 CGST + ₹5,000 SGST (intra-state)
        # ITC: ₹15,000 IGST (inter-state purchase) → excess ₹15,000 - ₹0 = ₹15,000
        # Excess split: ₹7,500 vs CGST, ₹7,500 vs SGST
        # Net CGST = max(0, 5000 - 4500 - 7500) = 0; Net SGST = 0
        sales = [make_sale(taxable_paise=100_000_00, gst_rate=18.0, is_interstate=False)]  # 9000 CGST + 9000 SGST
        purchases = [make_purchase(taxable_paise=150_000_00, gst_rate=18.0, is_interstate=True)]  # 27000 IGST ITC
        result = compute_gstr3b(sales, purchases, [])
        assert result.net_igst == 0
        # Excess 27000 IGST covers 9000 CGST + 9000 SGST → both 0
        assert result.net_cgst == 0
        assert result.net_sgst == 0

    def test_credit_note_reduces_output_tax(self):
        """GSTR-3B Table 3.1 is NET — credit notes must reduce output tax.

        GSTR-3B instructions (CBIC): report net taxable value after adjusting
        for credit notes. A credit note SUBTRACTS from outward_taxable_cgst/sgst.
        """
        invoice = make_sale(taxable_paise=100_000_00, gst_rate=18.0)  # 9000 CGST
        credit_note = SalesTransaction(
            transaction_type="credit_note",
            taxable_amount_paise=20_000_00,
            cgst_paise=1_800_00, sgst_paise=1_800_00, igst_paise=0, cess_paise=0,
            supply_type="taxable", is_reverse_charge=False,
        )
        result = compute_gstr3b([invoice, credit_note], [], [])
        assert result.outward_taxable_cgst == 7_200_00   # 9000 - 1800
        assert result.outward_taxable_sgst == 7_200_00

    def test_gstn_payload_structure(self):
        """Verify GSTN payload has required top-level keys."""
        result = compute_gstr3b(
            [make_sale()], [make_purchase()], []
        )
        payload = result.as_gstn_payload("27AABCU9603R1ZX", "052025")
        assert "gstin" in payload
        assert "ret_period" in payload
        assert "sup_details" in payload
        assert "itc_elg" in payload
        assert "intr_ltfee" in payload
        assert payload["gstin"] == "27AABCU9603R1ZX"
        assert payload["ret_period"] == "052025"

    def test_paise_to_rupees_precision(self):
        """Paise to rupees conversion must be exact to 2 decimal places."""
        assert _paise_to_rupees(100_000_00) == 100000.0
        assert _paise_to_rupees(9_000_00) == 9000.0
        assert _paise_to_rupees(4_500_50) == 4500.5
        assert _paise_to_rupees(1) == 0.01
        assert _paise_to_rupees(99) == 0.99


# ── Rule 36(4) Unit Tests ─────────────────────────────────────────────────────

class TestRule364Cap:
    def test_cap_applied(self):
        capped, was_capped = _apply_rule_36_4_cap(book=10_000_00, gstr2a=8_000_00)
        assert capped == 8_400_00  # 8000 * 105 / 100
        assert was_capped is True

    def test_no_cap_within_limit(self):
        capped, was_capped = _apply_rule_36_4_cap(book=8_000_00, gstr2a=8_000_00)
        assert capped == 8_000_00  # 8000 ≤ 8000 * 1.05 = 8400
        assert was_capped is False

    def test_no_cap_when_gstr2a_zero(self):
        capped, was_capped = _apply_rule_36_4_cap(book=5_000_00, gstr2a=0)
        assert capped == 5_000_00
        assert was_capped is False

    def test_zero_book(self):
        capped, was_capped = _apply_rule_36_4_cap(book=0, gstr2a=10_000_00)
        assert capped == 0
        assert was_capped is False

    def test_integer_arithmetic_no_float(self):
        """105% cap must use integer division to avoid float rounding."""
        # 8001 * 105 / 100 = 8401.05 → integer = 8401 (floor)
        capped, was_capped = _apply_rule_36_4_cap(book=9_000_00, gstr2a=8_001_00)
        assert capped == (8_001_00 * 105) // 100  # strict integer arithmetic
        assert isinstance(capped, int)


# ── GSTR-1 Builder Tests ──────────────────────────────────────────────────────

class TestGSTR1Builder:
    def test_b2b_invoice_structure(self):
        """B2B payload has correct structure."""
        inv = make_invoice_for_gstr1(category=GSTInvoiceCategory.B2B)
        payload = build_gstr1([inv], "27AABCU9603R1ZX", "052025")
        assert "b2b" in payload.payload
        b2b = payload.payload["b2b"]
        assert len(b2b) == 1
        assert b2b[0]["ctin"] == "27AABCU9603R1ZX"
        assert len(b2b[0]["inv"]) == 1
        inv_entry = b2b[0]["inv"][0]
        assert inv_entry["inum"] == "INV/2025/001"
        assert inv_entry["pos"] == "27"

    def test_b2cs_aggregated_by_rate_and_pos(self):
        """B2CS invoices are aggregated by rate + place of supply."""
        inv1 = make_invoice_for_gstr1(
            id="i1", reference_no="INV001", party_gstin=None,
            taxable_paise=50_000_00, gst_rate=18.0,
            category=GSTInvoiceCategory.B2CS, place_of_supply="27",
        )
        inv2 = make_invoice_for_gstr1(
            id="i2", reference_no="INV002", party_gstin=None,
            taxable_paise=50_000_00, gst_rate=18.0,
            category=GSTInvoiceCategory.B2CS, place_of_supply="27",
        )
        payload = build_gstr1([inv1, inv2], "27AABCU9603R1ZX", "052025")
        assert "b2cs" in payload.payload
        b2cs = payload.payload["b2cs"]
        assert len(b2cs) == 1  # aggregated into one row
        assert b2cs[0]["txval"] == 1_000_00.0  # ₹1,00,000 total

    def test_date_format_conversion(self):
        """GSTN requires DD-MM-YYYY; ISO dates must be converted."""
        assert _format_date_gstn("2025-05-15") == "15-05-2025"
        assert _format_date_gstn("2025-12-31") == "31-12-2025"

    def test_invoice_count_in_summary(self):
        invoices = [
            make_invoice_for_gstr1(id=f"inv{i}", reference_no=f"INV00{i}")
            for i in range(3)
        ]
        payload = build_gstr1(invoices, "27AABCU9603R1ZX", "052025")
        assert payload.invoice_count == 3

    def test_credit_note_goes_to_cdnr(self):
        inv = make_invoice_for_gstr1(
            transaction_type="credit_note",
            category=GSTInvoiceCategory.CDNR,
        )
        payload = build_gstr1([inv], "27AABCU9603R1ZX", "052025")
        assert "cdnr" in payload.payload
        cdnr = payload.payload["cdnr"]
        assert cdnr[0]["nt"][0]["ntty"] == "C"

    def test_gstin_and_period_in_payload(self):
        payload = build_gstr1([], "27AABCU9603R1ZX", "052025")
        assert payload.payload["gstin"] == "27AABCU9603R1ZX"
        assert payload.payload["fp"] == "052025"

    def test_taxable_total_computed_correctly(self):
        """Total taxable value must sum all sales invoices."""
        inv1 = make_invoice_for_gstr1(id="i1", reference_no="I1", taxable_paise=100_000_00)
        inv2 = make_invoice_for_gstr1(id="i2", reference_no="I2", taxable_paise=200_000_00)
        payload = build_gstr1([inv1, inv2], "27AABCU9603R1ZX", "052025")
        assert payload.taxable_total_paise == 300_000_00


# ── Validator Tests ───────────────────────────────────────────────────────────

class TestGSTValidator:
    def setup_method(self):
        self.v = GSTValidator()

    def test_valid_gstin(self):
        assert self.v.validate_gstin("27AABCU9603R1ZX") == []

    def test_invalid_gstin_length(self):
        errors = self.v.validate_gstin("27AABCU9603R1Z")
        assert len(errors) == 1
        assert errors[0].field == "gstin"

    def test_invalid_gstin_format(self):
        errors = self.v.validate_gstin("ABC123")
        assert len(errors) == 1

    def test_empty_gstin(self):
        errors = self.v.validate_gstin("")
        assert len(errors) == 1

    def test_valid_period(self):
        assert self.v.validate_period("052025") == []
        assert self.v.validate_period("122025") == []

    def test_invalid_period_month(self):
        errors = self.v.validate_period("132025")
        assert len(errors) == 1

    def test_invalid_period_format(self):
        errors = self.v.validate_period("2025-05")
        assert len(errors) == 1

    def test_valid_invoice(self):
        inv = InvoiceToValidate(
            reference_no="INV001",
            transaction_date="2025-05-10",
            party_gstin="27AABCU9603R1ZX",
            place_of_supply="27",
            taxable_amount_paise=100_000_00,
            cgst_paise=9_000_00,
            sgst_paise=9_000_00,
            igst_paise=0,
            is_interstate=False,
            gst_rate=18.0,
        )
        errors = self.v.validate_invoice(inv, "052025")
        assert not any(e.severity == "error" for e in errors)

    def test_cgst_not_equal_sgst_intrastate(self):
        inv = InvoiceToValidate(
            reference_no="INV001", transaction_date="2025-05-10",
            party_gstin=None, place_of_supply="27",
            taxable_amount_paise=100_000_00,
            cgst_paise=9_000_00, sgst_paise=8_000_00, igst_paise=0,
            is_interstate=False, gst_rate=None,
        )
        errors = self.v.validate_invoice(inv, "052025")
        assert any(e.field == "cgst_sgst" for e in errors)

    def test_igst_on_intrastate_flagged(self):
        inv = InvoiceToValidate(
            reference_no="INV001", transaction_date="2025-05-10",
            party_gstin=None, place_of_supply="27",
            taxable_amount_paise=100_000_00,
            cgst_paise=0, sgst_paise=0, igst_paise=18_000_00,
            is_interstate=False, gst_rate=None,
        )
        errors = self.v.validate_invoice(inv, "052025")
        assert any(e.field == "igst" for e in errors)

    def test_invalid_place_of_supply(self):
        inv = InvoiceToValidate(
            reference_no="INV001", transaction_date="2025-05-10",
            party_gstin=None, place_of_supply="99",
            taxable_amount_paise=100_000_00,
            cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0,
            is_interstate=False, gst_rate=None,
        )
        errors = self.v.validate_invoice(inv, "052025")
        assert any(e.field == "place_of_supply" for e in errors)

    def test_duplicate_invoice_numbers(self):
        invs = [
            InvoiceToValidate("INV001", "2025-05-01", None, "27", 100_00, 9_00, 9_00, 0, False, None),
            InvoiceToValidate("INV001", "2025-05-02", None, "27", 200_00, 18_00, 18_00, 0, False, None),
        ]
        errors = self.v.validate_no_duplicates(invs)
        assert len(errors) == 1
        assert errors[0].field == "reference_no"

    def test_tax_arithmetic_mismatch_warning(self):
        """Tax amount not matching rate × taxable gives a warning, not error."""
        inv = InvoiceToValidate(
            reference_no="INV001", transaction_date="2025-05-10",
            party_gstin=None, place_of_supply="27",
            taxable_amount_paise=100_000_00,
            cgst_paise=10_000_00,  # wrong — should be 9,000 for 18%
            sgst_paise=10_000_00,
            igst_paise=0,
            is_interstate=False,
            gst_rate=18.0,
        )
        errors = self.v.validate_invoice(inv, "052025")
        warnings = [e for e in errors if e.severity == "warning" and e.field == "tax_amount"]
        assert len(warnings) == 1

    def test_invoice_date_outside_period_is_warning(self):
        """Invoice from 3 months ago should be a warning, not error."""
        inv = InvoiceToValidate(
            reference_no="INV001", transaction_date="2025-02-10",  # Feb
            party_gstin=None, place_of_supply="27",
            taxable_amount_paise=100_000_00,
            cgst_paise=9_000_00, sgst_paise=9_000_00, igst_paise=0,
            is_interstate=False, gst_rate=None,
        )
        errors = self.v.validate_invoice(inv, "052025")  # May 2025 return
        date_warnings = [e for e in errors if e.field == "invoice_date"]
        assert len(date_warnings) == 1
        assert date_warnings[0].severity == "warning"


# ── B2CS Regression Tests (Bug #1 fix) ───────────────────────────────────────

def make_b2cs_invoice(
    id: str,
    reference_no: str,
    is_interstate: bool,
    place_of_supply: str,
    taxable_paise: int = 100_000_00,
    gst_rate: float = 18.0,
) -> InvoiceForGSTR1:
    tax = int(taxable_paise * gst_rate / 100)
    if is_interstate:
        cgst, sgst, igst = 0, 0, tax
    else:
        cgst = sgst = tax // 2
        igst = 0
    return InvoiceForGSTR1(
        id=id,
        transaction_type="sales_invoice",
        reference_no=reference_no,
        transaction_date="2025-05-10",
        party_gstin=None,
        party_name="Consumer",
        place_of_supply=place_of_supply,
        is_interstate=is_interstate,
        taxable_amount_paise=taxable_paise,
        cgst_paise=cgst,
        sgst_paise=sgst,
        igst_paise=igst,
        cess_paise=0,
        is_reverse_charge=False,
        invoice_type="Regular",
        supply_type="taxable",
        gst_invoice_category=GSTInvoiceCategory.B2CS,
        original_invoice_ref=None,
        original_invoice_date=None,
        lines=[],
    )


class TestB2CSRegressionBug1:
    """Regression tests for Bug #1: B2CS grouping must separate INTER and INTRA.

    CGST Rule 59(2): B2CS aggregated by rate + POS + supply type.
    INTER and INTRA at the same rate and same POS are distinct supply types.
    """

    def test_inter_and_intra_same_pos_same_rate_produce_two_b2cs_rows(self):
        """INTER and INTRA invoices at same POS and same rate must NOT be merged."""
        inter = make_b2cs_invoice("i1", "INV001", is_interstate=True,  place_of_supply="27")
        intra = make_b2cs_invoice("i2", "INV002", is_interstate=False, place_of_supply="27")
        payload = build_gstr1([inter, intra], "27AABCU9603R1ZX", "052025")
        b2cs = payload.payload.get("b2cs", [])
        supply_types = {row["sply_tp"] for row in b2cs}
        assert "INTER" in supply_types, "INTER row missing from B2CS"
        assert "INTRA" in supply_types, "INTRA row missing from B2CS"
        assert len(b2cs) == 2, f"Expected 2 B2CS rows, got {len(b2cs)}"

    def test_inter_b2cs_taxable_value_correct(self):
        """INTER row must only include interstate invoice amounts."""
        inter = make_b2cs_invoice("i1", "INV001", is_interstate=True,  place_of_supply="29", taxable_paise=200_000_00)
        intra = make_b2cs_invoice("i2", "INV002", is_interstate=False, place_of_supply="29", taxable_paise=300_000_00)
        payload = build_gstr1([inter, intra], "27AABCU9603R1ZX", "052025")
        b2cs = payload.payload.get("b2cs", [])
        inter_row = next((r for r in b2cs if r["sply_tp"] == "INTER"), None)
        intra_row = next((r for r in b2cs if r["sply_tp"] == "INTRA"), None)
        assert inter_row is not None
        assert intra_row is not None
        assert inter_row["txval"] == pytest.approx(200_000_00 / 100, rel=1e-6)
        assert intra_row["txval"] == pytest.approx(300_000_00 / 100, rel=1e-6)

    def test_multiple_inter_same_pos_rate_are_aggregated(self):
        """Multiple INTER invoices at same POS+rate must aggregate into one row."""
        inv1 = make_b2cs_invoice("i1", "INV001", is_interstate=True, place_of_supply="27", taxable_paise=50_000_00)
        inv2 = make_b2cs_invoice("i2", "INV002", is_interstate=True, place_of_supply="27", taxable_paise=80_000_00)
        payload = build_gstr1([inv1, inv2], "27AABCU9603R1ZX", "052025")
        b2cs = payload.payload.get("b2cs", [])
        inter_rows = [r for r in b2cs if r["sply_tp"] == "INTER"]
        assert len(inter_rows) == 1
        assert inter_rows[0]["txval"] == pytest.approx(130_000_00 / 100, rel=1e-6)

    def test_mixed_pos_produces_separate_rows_per_pos(self):
        """Different POS values must remain separate even with same rate and supply type."""
        inv_27 = make_b2cs_invoice("i1", "INV001", is_interstate=True, place_of_supply="27")
        inv_29 = make_b2cs_invoice("i2", "INV002", is_interstate=True, place_of_supply="29")
        payload = build_gstr1([inv_27, inv_29], "27AABCU9603R1ZX", "052025")
        b2cs = payload.payload.get("b2cs", [])
        pos_values = {row["pos"] for row in b2cs}
        assert "27" in pos_values
        assert "29" in pos_values
        assert len(b2cs) == 2


# ── HSN/SAC Seed Uniqueness Validation ───────────────────────────────────────

import re as _re


class TestHSNSeedUniqueness:
    """Validates migration seed data has no duplicate HSN/SAC codes.

    Prevents regression of Bug #2 (duplicate 998313 entries in 036_gst_engine.sql).
    """

    def _extract_hsn_codes_from_migration(self, sql_path: str) -> list[str]:
        with open(sql_path) as f:
            content = f.read()
        # Match INSERT rows: ('CODE', ...
        return _re.findall(r"\('(\d+)'", content)

    def test_no_duplicate_hsn_codes_in_migration_036(self):
        import os
        sql_path = os.path.join(
            os.path.dirname(__file__),
            "..", "migrations", "036_gst_engine.sql"
        )
        codes = self._extract_hsn_codes_from_migration(sql_path)
        seen: set[str] = set()
        duplicates: list[str] = []
        for code in codes:
            if code in seen:
                duplicates.append(code)
            seen.add(code)
        assert duplicates == [], f"Duplicate HSN/SAC codes in migration 036: {duplicates}"
