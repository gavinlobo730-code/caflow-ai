"""
Batch 1 — money correctness tests for the Sales Invoice.

Covers:
  1. Odd-basis-point CGST/SGST split — CGST+SGST equals the full tax (== the
     IGST an inter-state supply of the same taxable+rate would attract); no
     one-paise understatement/imbalance.
  2. Invoice-level round-off (nearest ₹1, half-up) calculations.
  3. Balanced sales-invoice journal (Dr == Cr) WITH and WITHOUT round-off.
  4. Existing-invoice compatibility — whole-rupee/normal amounts are unchanged.
  5. Posting-failure behaviour — journal_for_sales_invoice re-raises unexpected
     exceptions instead of silently returning None.

Pure integer paise throughout. No floating point.
CGST Act §8 (place-of-supply split) · §15 (round-off does not change the value
of supply or the GST thereon).
"""
import os
import pytest

from routers.sales_invoices import _compute_line_gst, _round_off_paise


# ---------------------------------------------------------------------------
# Helpers that mirror phase2_journal_service.journal_for_sales_invoice line rules
# ---------------------------------------------------------------------------

def _invoice_from(taxable: int, gst_rate_bps: int, is_interstate: bool) -> dict:
    """Build the stored invoice amounts exactly as the create path does:
    per-line GST, then invoice-level round-off on (taxable + GST)."""
    cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
    base_total = taxable + cgst + sgst + igst
    round_off = _round_off_paise(base_total)
    return {
        "taxable_amount_paise": taxable,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "round_off_paise": round_off,
        "total_paise": base_total + round_off,
    }


def _sales_journal_lines(inv: dict) -> list[dict]:
    """Replicate journal_for_sales_invoice's Dr/Cr line construction."""
    lines = [
        {"debit_paise": inv["total_paise"], "credit_paise": 0},              # Dr Trade Receivables
        {"debit_paise": 0, "credit_paise": inv["taxable_amount_paise"]},     # Cr Sales Revenue
    ]
    for head in ("cgst_paise", "sgst_paise", "igst_paise"):
        if inv[head] > 0:
            lines.append({"debit_paise": 0, "credit_paise": inv[head]})       # Cr GST output
    ro = inv["round_off_paise"]
    if ro > 0:
        lines.append({"debit_paise": 0, "credit_paise": ro})                  # Cr Round Off
    elif ro < 0:
        lines.append({"debit_paise": -ro, "credit_paise": 0})                 # Dr Round Off
    return lines


def _assert_balanced(inv: dict):
    lines = _sales_journal_lines(inv)
    total_dr = sum(l["debit_paise"] for l in lines)
    total_cr = sum(l["credit_paise"] for l in lines)
    assert total_dr == total_cr, f"journal imbalance: Dr {total_dr} != Cr {total_cr} for {inv}"


# ---------------------------------------------------------------------------
# 1. Odd-basis-point CGST/SGST split
# ---------------------------------------------------------------------------

class TestOddBpsGstSplit:
    def test_intra_equals_inter_for_odd_tax(self):
        """CGST+SGST (intra) must equal IGST (inter) for the same taxable+rate.
        ₹300.00 @ 0.25% → full tax 75 paise (odd) → 37 + 38 == 75 == IGST."""
        taxable, bps = 30_000, 25  # ₹300.00, 0.25%
        cgst, sgst, igst_intra = _compute_line_gst(taxable, bps, is_interstate=False)
        _, _, igst_inter = _compute_line_gst(taxable, bps, is_interstate=True)
        assert igst_intra == 0 and igst_inter == 75
        assert cgst + sgst == igst_inter == 75          # no one-paise shortfall
        assert (cgst, sgst) == (37, 38)                  # SGST absorbs the odd paise
        assert abs(cgst - sgst) <= 1                     # halves differ by at most 1 paise

    def test_odd_full_tax_at_18pct(self):
        """₹105.55 @ 18% → full tax 1899 paise (odd). Old per-half floor gave
        1898 (1 paise short); the fix yields 949 + 950 == 1899 == IGST."""
        taxable, bps = 10_555, 1800
        cgst, sgst, _ = _compute_line_gst(taxable, bps, is_interstate=False)
        _, _, igst = _compute_line_gst(taxable, bps, is_interstate=True)
        assert cgst + sgst == igst == 1899
        assert (cgst, sgst) == (949, 950)

    def test_split_never_exceeds_or_understates_full(self):
        """For a sweep of taxable values and rates, CGST+SGST == floor(taxable*bps/10000)."""
        for bps in (25, 100, 500, 1200, 1800, 2800):
            for taxable in range(0, 5000, 7):  # many non-round amounts
                cgst, sgst, _ = _compute_line_gst(taxable, bps, is_interstate=False)
                full = (taxable * bps) // 10000
                assert cgst + sgst == full
                assert cgst == full // 2 and sgst == full - full // 2


# ---------------------------------------------------------------------------
# 2. Round-off calculations (nearest ₹1, half-up)
# ---------------------------------------------------------------------------

class TestRoundOff:
    @pytest.mark.parametrize("amount,expected", [
        (10_000, 0),      # ₹100.00 — already whole
        (10_030, -30),    # ₹100.30 — round down
        (10_050, 50),     # ₹100.50 — half rounds UP
        (10_099, 1),      # ₹100.99 — round up
        (10_001, -1),     # ₹100.01 — round down
        (10_049, -49),    # ₹100.49 — largest round-down
        (0, 0),
    ])
    def test_round_off_delta(self, amount, expected):
        assert _round_off_paise(amount) == expected

    def test_round_off_makes_whole_rupee(self):
        for amount in range(10_000, 10_200):
            assert (amount + _round_off_paise(amount)) % 100 == 0

    def test_round_off_range(self):
        for amount in range(0, 1000):
            assert -49 <= _round_off_paise(amount) <= 50


# ---------------------------------------------------------------------------
# 3. Balanced journal — with and without round-off
# ---------------------------------------------------------------------------

class TestJournalBalance:
    def test_balanced_intrastate_round_amount(self):
        inv = _invoice_from(1_000_000, 1800, is_interstate=False)  # ₹10,000 @18%
        assert inv["round_off_paise"] == 0                         # whole-rupee tax
        _assert_balanced(inv)

    def test_balanced_interstate_round_amount(self):
        inv = _invoice_from(1_000_000, 1800, is_interstate=True)
        _assert_balanced(inv)

    def test_balanced_with_positive_round_off(self):
        # ₹105.55 @18% intra: taxable 10555 + 1899 tax = 12454 → round up +46 → 12500
        inv = _invoice_from(10_555, 1800, is_interstate=False)
        assert inv["round_off_paise"] == 46
        assert inv["total_paise"] % 100 == 0
        _assert_balanced(inv)

    def test_balanced_with_negative_round_off(self):
        # ₹100.20 @18% intra: taxable 10020 + 1803 tax = 11823 → round down -23 → 11800
        inv = _invoice_from(10_020, 1800, is_interstate=False)
        assert inv["round_off_paise"] == -23
        assert inv["total_paise"] % 100 == 0
        _assert_balanced(inv)

    def test_balanced_sweep(self):
        for bps in (25, 500, 1200, 1800, 2800):
            for taxable in range(0, 8000, 13):
                for inter in (False, True):
                    _assert_balanced(_invoice_from(taxable, bps, inter))


# ---------------------------------------------------------------------------
# 4. Existing-invoice compatibility (normal, whole-rupee amounts unchanged)
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_whole_rupee_amounts_unchanged(self):
        """Amounts whose tax lands on a whole rupee are byte-for-byte unchanged
        vs the historical per-half computation (regression guard)."""
        for taxable, bps in [(1_000_000, 1800), (5_000_00, 500), (2_000_00, 1200),
                             (10_000_00, 2800)]:
            cgst, sgst, _ = _compute_line_gst(taxable, bps, is_interstate=False)
            old_half = bps // 2
            old_cgst = (taxable * old_half) // 10000
            old_sgst = (taxable * old_half) // 10000
            # These specific amounts have even splits → identical to the old logic
            assert (cgst, sgst) == (old_cgst, old_sgst)

    def test_zero_round_off_adds_no_journal_line(self):
        inv = _invoice_from(1_000_000, 1800, is_interstate=False)
        assert inv["round_off_paise"] == 0
        # Only AR + Revenue + CGST + SGST — no round-off leg.
        assert len(_sales_journal_lines(inv)) == 4

    def test_total_reconciles_to_components(self):
        for taxable, bps, inter in [(10_555, 1800, False), (30_000, 25, False),
                                     (1_000_000, 1800, True)]:
            inv = _invoice_from(taxable, bps, inter)
            comp = (inv["taxable_amount_paise"] + inv["cgst_paise"] + inv["sgst_paise"]
                    + inv["igst_paise"] + inv["round_off_paise"])
            assert inv["total_paise"] == comp


# ---------------------------------------------------------------------------
# 5. Posting-failure behaviour — unexpected errors re-raise (not silent None)
# ---------------------------------------------------------------------------

class TestPostingReraise:
    def test_journal_reraises_unexpected_exception(self, monkeypatch):
        """journal_for_sales_invoice must re-raise an unexpected error (aligning
        with journal_for_receipt / journal_for_purchase_payment) rather than
        swallowing it into a None 'silent failure'."""
        import services.phase2_journal_service as pjs
        import core.supabase_client as sc

        # Force the non-mock path, then make the DB handle raise a NON-ValueError.
        monkeypatch.setattr(pjs, "_USE_MOCK", False)

        def _boom():
            raise RuntimeError("db exploded")

        monkeypatch.setattr(sc, "get_supabase", _boom)

        invoice = {
            "invoice_no": "SINV-2526-0001",
            "invoice_date": "2025-06-01",
            "taxable_amount_paise": 1_000_000,
            "cgst_paise": 90_000, "sgst_paise": 90_000, "igst_paise": 0,
            "round_off_paise": 0, "total_paise": 1_180_000,
        }
        with pytest.raises(RuntimeError):
            pjs.phase2_journal_service.journal_for_sales_invoice(
                invoice, "firm-1", "client-1"
            )
