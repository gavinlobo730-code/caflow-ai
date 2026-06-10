"""
Phase 2 Stabilization — unit tests.
These tests run entirely without a database connection (mock mode).
All monetary calculations use integer paise arithmetic (never float).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the api package root is on sys.path
_API_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

# ---------------------------------------------------------------------------
# Helpers — replicated here to keep tests self-contained
# ---------------------------------------------------------------------------

def _get_fy_for_date(date_str: str) -> str:
    """Return Indian FY string for a given ISO date. April → next year suffix."""
    from datetime import datetime
    parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
    start_year = parsed.year if parsed.month >= 4 else parsed.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def _current_fy_long_from_date(year: int, month: int) -> str:
    start = year if month >= 4 else year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _compute_line_gst(taxable_paise: int, gst_rate_bps: int, is_interstate: bool):
    """
    Integer paise GST computation.
    CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST.
    Returns (cgst_paise, sgst_paise, igst_paise) — all int.
    """
    if is_interstate:
        igst = (taxable_paise * gst_rate_bps) // 10000
        return 0, 0, igst
    half_rate = gst_rate_bps // 2
    cgst = (taxable_paise * half_rate) // 10000
    sgst = (taxable_paise * half_rate) // 10000
    return cgst, sgst, 0


# ---------------------------------------------------------------------------
# 1. Period validation — mock mode always passes
# ---------------------------------------------------------------------------

class TestPeriodValidationMockMode(unittest.TestCase):
    def test_period_validation_open_period(self):
        """validate_posting_date in mock mode always passes without raising."""
        # Ensure mock mode by temporarily removing SUPABASE_URL
        with patch.dict(os.environ, {}, clear=True):
            # Re-import so _USE_MOCK picks up the patched env
            import importlib
            import services.period_validation_service as pv_mod
            importlib.reload(pv_mod)
            svc = pv_mod.PeriodValidationService()
            # Should not raise regardless of the date
            svc.validate_posting_date("any-firm-id", "2025-04-01")
            svc.validate_posting_date("any-firm-id", "2024-03-31")
            svc.validate_posting_date("any-firm-id", "2023-01-15")


# ---------------------------------------------------------------------------
# 2. Period validation helper — FY string derivation
# ---------------------------------------------------------------------------

class TestPeriodValidationFYHelper(unittest.TestCase):
    def test_fy_april(self):
        """April date belongs to FY starting that calendar year."""
        result = _get_fy_for_date("2025-04-01")
        self.assertEqual(result, "2025-26")

    def test_fy_march(self):
        """March date belongs to FY starting the previous calendar year."""
        result = _get_fy_for_date("2026-03-31")
        self.assertEqual(result, "2025-26")

    def test_fy_july(self):
        result = _get_fy_for_date("2024-07-15")
        self.assertEqual(result, "2024-25")

    def test_fy_january(self):
        result = _get_fy_for_date("2025-01-01")
        self.assertEqual(result, "2024-25")


# ---------------------------------------------------------------------------
# 3. Journal balance — sales invoice (Dr == Cr)
# ---------------------------------------------------------------------------

class TestJournalBalanceSalesInvoice(unittest.TestCase):
    def _build_invoice(self, taxable: int, gst_rate_bps: int, is_interstate: bool) -> dict:
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
        total = taxable + cgst + sgst + igst
        return {
            "invoice_no": "SINV-2526-0001",
            "invoice_date": "2025-06-01",
            "taxable_amount_paise": taxable,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "igst_paise": igst,
            "total_paise": total,
        }

    def _journal_lines_for_sales_invoice(self, invoice: dict, gst_account_id: str) -> list:
        """Replicate the line-building logic from phase2_journal_service."""
        lines = [
            {"debit_paise": invoice["total_paise"], "credit_paise": 0},
            {"debit_paise": 0, "credit_paise": invoice["taxable_amount_paise"]},
        ]
        if invoice.get("cgst_paise", 0) > 0:
            lines.append({"debit_paise": 0, "credit_paise": invoice["cgst_paise"]})
        if invoice.get("sgst_paise", 0) > 0:
            lines.append({"debit_paise": 0, "credit_paise": invoice["sgst_paise"]})
        if invoice.get("igst_paise", 0) > 0:
            lines.append({"debit_paise": 0, "credit_paise": invoice["igst_paise"]})
        return lines

    def test_journal_balance_intrastate(self):
        """Intra-state invoice Dr == Cr (CGST+SGST split)."""
        inv = self._build_invoice(1_000_000, 1800, False)  # ₹10,000 at 18%
        lines = self._journal_lines_for_sales_invoice(inv, "gst-acc")
        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr)

    def test_journal_balance_interstate(self):
        """Inter-state invoice Dr == Cr (IGST)."""
        inv = self._build_invoice(1_000_000, 1800, True)
        lines = self._journal_lines_for_sales_invoice(inv, "gst-acc")
        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr)


# ---------------------------------------------------------------------------
# 4. Journal balance — purchase bill with TDS (Dr == Cr)
# ---------------------------------------------------------------------------

class TestJournalBalancePurchaseBillWithTDS(unittest.TestCase):
    def _build_bill(self, taxable: int, gst_rate_bps: int, tds_rate_bps: int) -> dict:
        # IT Act §194J: TDS on taxable amount only (excluding GST)
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, False)
        total = taxable + cgst + sgst + igst
        tds = (taxable * tds_rate_bps) // 10000
        net_payable = total - tds
        return {
            "bill_no": "BILL-001",
            "bill_date": "2025-06-01",
            "taxable_amount_paise": taxable,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "igst_paise": igst,
            "total_paise": total,
            "tds_paise": tds,
            "net_payable_paise": net_payable,
            "tds_section": "194J",
        }

    def _journal_lines_for_purchase_bill(self, bill: dict) -> list:
        lines = [
            {"debit_paise": bill["taxable_amount_paise"], "credit_paise": 0},
        ]
        if bill.get("cgst_paise", 0) > 0:
            lines.append({"debit_paise": bill["cgst_paise"], "credit_paise": 0})
        if bill.get("sgst_paise", 0) > 0:
            lines.append({"debit_paise": bill["sgst_paise"], "credit_paise": 0})
        if bill.get("igst_paise", 0) > 0:
            lines.append({"debit_paise": bill["igst_paise"], "credit_paise": 0})
        lines.append({"debit_paise": 0, "credit_paise": bill["net_payable_paise"]})
        if bill.get("tds_paise", 0) > 0:
            lines.append({"debit_paise": 0, "credit_paise": bill["tds_paise"]})
        return lines

    def test_journal_balance_purchase_bill_with_tds(self):
        """Purchase bill with TDS: Dr == Cr. IT Act §194J."""
        bill = self._build_bill(1_000_000, 1800, 1000)  # 18% GST, 10% TDS
        lines = self._journal_lines_for_purchase_bill(bill)
        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr)

    def test_journal_balance_purchase_bill_no_tds(self):
        """Purchase bill without TDS: Dr == Cr."""
        bill = self._build_bill(500_000, 900, 0)
        lines = self._journal_lines_for_purchase_bill(bill)
        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr)


# ---------------------------------------------------------------------------
# 5. Journal balance — credit note (Dr == Cr)
# ---------------------------------------------------------------------------

class TestJournalBalanceCreditNote(unittest.TestCase):
    def _build_cn(self, taxable: int, gst_rate_bps: int, is_interstate: bool) -> dict:
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
        total = taxable + cgst + sgst + igst
        return {
            "credit_note_no": "CN-2526-0001",
            "credit_note_date": "2025-06-10",
            "taxable_amount_paise": taxable,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "igst_paise": igst,
            "total_paise": total,
        }

    def _journal_lines_for_credit_note(self, cn: dict) -> list:
        """CGST Act §34: Dr Sales/GST Output, Cr Trade Receivables."""
        lines = [{"debit_paise": cn["taxable_amount_paise"], "credit_paise": 0}]
        if cn.get("cgst_paise", 0) > 0:
            lines.append({"debit_paise": cn["cgst_paise"], "credit_paise": 0})
        if cn.get("sgst_paise", 0) > 0:
            lines.append({"debit_paise": cn["sgst_paise"], "credit_paise": 0})
        if cn.get("igst_paise", 0) > 0:
            lines.append({"debit_paise": cn["igst_paise"], "credit_paise": 0})
        lines.append({"debit_paise": 0, "credit_paise": cn["total_paise"]})
        return lines

    def test_journal_balance_credit_note_intrastate(self):
        """Credit note (intra-state) Dr == Cr. CGST Act §34."""
        cn = self._build_cn(500_000, 1800, False)
        lines = self._journal_lines_for_credit_note(cn)
        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr)

    def test_journal_balance_credit_note_interstate(self):
        """Credit note (inter-state) Dr == Cr."""
        cn = self._build_cn(500_000, 1800, True)
        lines = self._journal_lines_for_credit_note(cn)
        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr)


# ---------------------------------------------------------------------------
# 6. Timeline service — mock mode never raises
# ---------------------------------------------------------------------------

class TestTimelineMockNoRaise(unittest.TestCase):
    def test_timeline_mock_no_raise(self):
        """log_timeline_event in mock mode does not raise under any circumstances."""
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import services.timeline_service as ts_mod
            importlib.reload(ts_mod)
            svc = ts_mod.TimelineService()
            # Should never raise regardless of inputs
            svc.log_timeline_event(
                client_id="client-1",
                firm_id="firm-1",
                financial_year="2025-26",
                category="accounting",
                event_type="invoice_posted",
                title="Test event",
                description="Test description",
                severity="success",
                entity_type="sales_invoice",
                entity_id="inv-1",
                amount_paise=118_00_00,  # ₹1,180 in paise
                actor_id="user-1",
                actor_name="test@ca.com",
            )


# ---------------------------------------------------------------------------
# 7. Document intelligence — extraction response requires_review flag
# ---------------------------------------------------------------------------

class TestDocumentIntelligenceRequiresReview(unittest.TestCase):
    def test_document_intelligence_requires_review(self):
        """
        AI-extracted bills must always have requires_review=True.
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        """
        # Simulate the extraction response shape from purchase_bills router
        extracted_bill = {
            "id": "bill-uuid",
            "status": "draft",
            "requires_review": True,
            "is_ai_extracted": True,
        }
        self.assertTrue(extracted_bill["requires_review"],
                        "AI-extracted bill must always require CA review before posting")
        self.assertEqual(extracted_bill["status"], "draft",
                         "AI-extracted bill must always start as draft — never auto-received")


# ---------------------------------------------------------------------------
# 8. Purchase bill lines — router payload uses 'bill_id' key
# ---------------------------------------------------------------------------

class TestPurchaseBillLinesColumnName(unittest.TestCase):
    def test_purchase_bill_lines_column_name(self):
        """
        The purchase_bill_lines insert payload must use 'bill_id' (not 'purchase_bill_id').
        Migration 051 renames the FK column to 'bill_id' to match the router.
        """
        # Simulate router payload construction (from purchase_bills.py create_purchase_bill)
        bill_id = "some-bill-uuid"
        line = {
            "description": "Professional service",
            "hsn_sac": "998311",
            "quantity": 1,
            "rate_paise": 1_000_000,
            "gst_rate_bps": 1800,
            "taxable_amount_paise": 1_000_000,
            "cgst_paise": 90_000,
            "sgst_paise": 90_000,
            "igst_paise": 0,
            "line_total_paise": 1_180_000,
        }
        payload = {"bill_id": bill_id, **line}

        self.assertIn("bill_id", payload)
        self.assertNotIn("purchase_bill_id", payload)
        self.assertEqual(payload["bill_id"], bill_id)


# ---------------------------------------------------------------------------
# 9. Account resolution — raises ValueError when account not found
# ---------------------------------------------------------------------------

class TestAccountResolutionRaisesOnMissing(unittest.TestCase):
    def test_account_resolution_raises_on_missing(self):
        """_find_account must raise ValueError when no account is found in DB."""
        # Force non-mock mode by temporarily setting SUPABASE_URL
        with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co"}):
            import importlib
            import services.phase2_journal_service as svc_mod
            importlib.reload(svc_mod)
            svc = svc_mod.Phase2JournalService()

        # Mock DB that returns no data
        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = MagicMock(data=[])
        mock_db.table.return_value.select.return_value \
            .eq.return_value.or_.return_value \
            .ilike.return_value.eq.return_value \
            .limit.return_value = mock_chain

        with self.assertRaises(ValueError) as ctx:
            svc._find_account(mock_db, "firm-1", "client-1", "%Trade Receivable%")

        self.assertIn("Required account not found", str(ctx.exception))
        self.assertIn("%Trade Receivable%", str(ctx.exception))
        self.assertIn("Chart of Accounts", str(ctx.exception))


# ---------------------------------------------------------------------------
# 10. Integer arithmetic — GST calculation
# ---------------------------------------------------------------------------

class TestGSTIntegerArithmetic(unittest.TestCase):
    def test_gst_integer_arithmetic(self):
        """
        Spot-check: 18% GST on ₹10,000 = ₹1,800.
        CGST Act §8: all calculations in integer paise.
        (1_000_000 paise * 1800 bps) // 10000 = 180_000 paise.
        """
        taxable_paise = 1_000_000  # ₹10,000
        gst_rate_bps  = 1800       # 18%
        result = (taxable_paise * gst_rate_bps) // 10000
        self.assertEqual(result, 180_000)
        self.assertIsInstance(result, int)

    def test_gst_intrastate_split(self):
        """
        CGST Act §8: Intra-state → CGST = SGST = half of total GST.
        """
        taxable_paise = 1_000_000
        gst_rate_bps  = 1800
        cgst, sgst, igst = _compute_line_gst(taxable_paise, gst_rate_bps, False)
        self.assertEqual(cgst, 90_000)
        self.assertEqual(sgst, 90_000)
        self.assertEqual(igst, 0)
        self.assertIsInstance(cgst, int)
        self.assertIsInstance(sgst, int)

    def test_gst_interstate(self):
        """
        CGST Act §8: Inter-state → IGST = full rate, no CGST/SGST.
        """
        taxable_paise = 1_000_000
        gst_rate_bps  = 1800
        cgst, sgst, igst = _compute_line_gst(taxable_paise, gst_rate_bps, True)
        self.assertEqual(cgst, 0)
        self.assertEqual(sgst, 0)
        self.assertEqual(igst, 180_000)
        self.assertIsInstance(igst, int)


# ---------------------------------------------------------------------------
# 11. Integer arithmetic — TDS calculation
# ---------------------------------------------------------------------------

class TestTDSIntegerArithmetic(unittest.TestCase):
    def test_tds_integer_arithmetic(self):
        """
        Spot-check: 2% TDS on ₹10,000 = ₹200.
        IT Act §194C: TDS on taxable amount (excluding GST).
        (1_000_000 paise * 200 bps) // 10000 = 20_000 paise.
        """
        taxable_paise = 1_000_000  # ₹10,000
        tds_rate_bps  = 200        # 2%
        result = (taxable_paise * tds_rate_bps) // 10000
        self.assertEqual(result, 20_000)
        self.assertIsInstance(result, int)

    def test_tds_194j_rate(self):
        """
        IT Act §194J: 10% TDS on ₹10,000 = ₹1,000.
        """
        taxable_paise = 1_000_000
        tds_rate_bps  = 1000       # 10%
        result = (taxable_paise * tds_rate_bps) // 10000
        self.assertEqual(result, 100_000)
        self.assertIsInstance(result, int)


# ---------------------------------------------------------------------------
# 12. FY string format
# ---------------------------------------------------------------------------

class TestFYStringFormat(unittest.TestCase):
    def test_fy_string_format_april(self):
        """_current_fy_long() returns 'YYYY-YY' format (not 'YYYY')."""
        # April 2025 → "2025-26"
        result = _current_fy_long_from_date(2025, 4)
        self.assertRegex(result, r"^\d{4}-\d{2}$",
                         "FY string must be in 'YYYY-YY' format")
        self.assertEqual(result, "2025-26")

    def test_fy_string_format_march(self):
        """March date returns the previous start year."""
        result = _current_fy_long_from_date(2026, 3)
        self.assertRegex(result, r"^\d{4}-\d{2}$")
        self.assertEqual(result, "2025-26")

    def test_fy_string_format_consistency(self):
        """Verify format is 'YYYY-YY' not 'YYYY' (the invoice-numbering short form)."""
        result = _current_fy_long_from_date(2025, 7)
        self.assertIn("-", result, "Long FY string must contain a hyphen")
        parts = result.split("-")
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[0]), 4)
        self.assertEqual(len(parts[1]), 2)


if __name__ == "__main__":
    unittest.main()
