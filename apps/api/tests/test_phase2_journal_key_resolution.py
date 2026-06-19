"""
Regression tests for Phase 2 journal service account key resolution.

Covers:
  - system_account_key-first lookup succeeds → name query skipped
  - Key lookup empty → falls back to name-pattern match
  - Both key and name fail → ValueError
  - Interstate invoice posting: Dr AR / Cr Revenue / Cr IGST (CGST Act §8)
  - Intrastate invoice posting: Dr AR / Cr Revenue / Cr CGST / Cr SGST (CGST Act §8)
  - Standard CoA fallback: single combined GST account (gst_cgst/sgst key absent → %GST Output%)

All tests run without a live database connection.
All monetary values are integer paise (never float).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

_API_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)


def _make_svc():
    """Return a Phase2JournalService instance forced into non-mock mode."""
    with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co"}):
        import importlib
        import services.phase2_journal_service as mod
        importlib.reload(mod)
        return mod.Phase2JournalService()


def _key_chain(mock_db, account_id: str):
    """Wire the key-lookup chain to return a single account row."""
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[{"id": account_id}])
    mock_db.table.return_value.select.return_value \
        .eq.return_value.eq.return_value \
        .eq.return_value.limit.return_value = chain
    return chain


def _name_chain(mock_db, account_id: str):
    """Wire the name-fallback chain to return a single account row."""
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[{"id": account_id}])
    mock_db.table.return_value.select.return_value \
        .eq.return_value.or_.return_value \
        .ilike.return_value.eq.return_value \
        .limit.return_value = chain
    return chain


def _empty_chain(mock_db):
    """Wire all query chains to return no data."""
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=[])
    tbl = mock_db.table.return_value.select.return_value
    tbl.eq.return_value.eq.return_value.eq.return_value.limit.return_value = chain
    tbl.eq.return_value.or_.return_value.ilike.return_value.eq.return_value.limit.return_value = chain
    return chain


# ---------------------------------------------------------------------------
# 1. Key resolution — key hit → returns immediately
# ---------------------------------------------------------------------------

class TestKeyResolutionHit(unittest.TestCase):
    def test_key_found_returns_id(self):
        """When system_account_key lookup returns a row, name pattern is never queried."""
        svc = _make_svc()
        mock_db = MagicMock()
        _key_chain(mock_db, "acct-ar-001")

        result = svc._find_account(mock_db, "firm-1", "client-1", "%Trade Receivable%", system_key="ar")

        self.assertEqual(result, "acct-ar-001")
        # ilike should never have been called on this path
        called_methods = [str(c) for c in mock_db.mock_calls]
        self.assertFalse(any("ilike" in m for m in called_methods))


# ---------------------------------------------------------------------------
# 2. Key resolution — key miss → name fallback
# ---------------------------------------------------------------------------

class TestKeyResolutionFallback(unittest.TestCase):
    def test_key_miss_falls_back_to_name(self):
        """When key lookup returns empty, name-pattern fallback is used."""
        svc = _make_svc()
        mock_db = MagicMock()

        # Key lookup returns empty; name lookup returns a row
        key_chain = MagicMock()
        key_chain.execute.return_value = MagicMock(data=[])
        mock_db.table.return_value.select.return_value \
            .eq.return_value.eq.return_value \
            .eq.return_value.limit.return_value = key_chain

        name_chain = MagicMock()
        name_chain.execute.return_value = MagicMock(data=[{"id": "acct-sales-001"}])
        mock_db.table.return_value.select.return_value \
            .eq.return_value.or_.return_value \
            .ilike.return_value.eq.return_value \
            .limit.return_value = name_chain

        result = svc._find_account(mock_db, "firm-1", "client-1", "%Sales%", system_key="revenue")

        self.assertEqual(result, "acct-sales-001")


# ---------------------------------------------------------------------------
# 3. Both key and name fail → ValueError
# ---------------------------------------------------------------------------

class TestKeyResolutionBothFail(unittest.TestCase):
    def test_both_lookups_fail_raises_value_error(self):
        """ValueError raised when neither key nor name finds an account."""
        svc = _make_svc()
        mock_db = MagicMock()
        _empty_chain(mock_db)

        with self.assertRaises(ValueError) as ctx:
            svc._find_account(mock_db, "firm-1", "client-1", "%Missing Account%", system_key="revenue")

        self.assertIn("Required account not found", str(ctx.exception))
        self.assertIn("Chart of Accounts", str(ctx.exception))

    def test_no_key_name_fails_raises_value_error(self):
        """ValueError raised when no system_key given and name lookup finds nothing."""
        svc = _make_svc()
        mock_db = MagicMock()
        _empty_chain(mock_db)

        with self.assertRaises(ValueError) as ctx:
            svc._find_account(mock_db, "firm-1", "client-1", "%Trade Receivable%")

        self.assertIn("Required account not found", str(ctx.exception))
        self.assertIn("%Trade Receivable%", str(ctx.exception))


# ---------------------------------------------------------------------------
# 4. Interstate invoice posting — Dr AR / Cr Revenue / Cr IGST
# ---------------------------------------------------------------------------

class TestInterstateInvoicePosting(unittest.TestCase):
    """
    CGST Act §8: Inter-state supply → IGST only (no CGST/SGST).
    Journal: Dr AR 6018 / Cr Revenue 5100 / Cr IGST 918.
    All values in integer paise.
    """

    def _make_db_for_invoice(self, ar_id, rev_id, igst_id, journal_id="jnl-001"):
        """Return a mock_db that resolves exactly three accounts and inserts a journal."""
        mock_db = MagicMock()

        # Route _find_account calls by system_key argument.
        # The service calls .eq("system_account_key", key) on the chain.
        # We capture calls by inspecting the mock state after execution.
        # Simpler: use side_effect on the table chain to return different values
        # based on call count.
        call_count = {"n": 0}
        accounts = [ar_id, rev_id, igst_id]

        def select_side(*args, **kwargs):
            inner = MagicMock()
            idx = call_count["n"]
            call_count["n"] += 1

            result_chain = MagicMock()
            result_chain.execute.return_value = MagicMock(
                data=[{"id": accounts[idx % len(accounts)]}]
            )
            # Wire the entire chain to the result
            inner.eq.return_value.eq.return_value.eq.return_value.limit.return_value = result_chain
            inner.eq.return_value.or_.return_value.ilike.return_value.eq.return_value.limit.return_value = result_chain
            return inner

        mock_db.table.return_value.select.side_effect = select_side

        # journal_entries insert
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": journal_id}]
        )
        # duplicate check returns empty
        mock_db.table.return_value.select.side_effect = select_side

        return mock_db

    def test_interstate_journal_balance(self):
        """
        Dr AR 6018 = Cr Revenue 5100 + Cr IGST 918.
        CGST Act §8: Inter-state → IGST only.
        All values are integer paise.
        """
        svc = _make_svc()

        invoice = {
            "invoice_no": "SINV-TEST-0001",
            "invoice_date": "2026-06-19",
            "total_paise": 6018,
            "taxable_amount_paise": 5100,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 918,
        }

        mock_db = MagicMock()
        call_count = {"n": 0}
        account_ids = ["ar-001", "rev-001", "igst-001"]

        def select_se(*args, **kwargs):
            inner = MagicMock()
            idx = call_count["n"]
            call_count["n"] += 1
            rc = MagicMock()
            rc.execute.return_value = MagicMock(data=[{"id": account_ids[idx % 3]}])
            inner.eq.return_value.eq.return_value.eq.return_value.limit.return_value = rc
            inner.eq.return_value.or_.return_value.ilike.return_value.eq.return_value.limit.return_value = rc
            return inner

        mock_db.table.return_value.select.side_effect = select_se

        # Patch _create_journal so the duplicate-check select doesn't interfere with
        # the account-resolution select mock; verify lines via call_args instead.
        with patch("core.supabase_client.get_supabase", return_value=mock_db):
            with patch.object(svc, "_create_journal", return_value="jnl-001") as mock_cj:
                result = svc.journal_for_sales_invoice(invoice, "firm-1", "client-1")

        self.assertEqual(result, "jnl-001")
        self.assertTrue(mock_cj.called, "_create_journal must be invoked")

        lines = mock_cj.call_args[1]["lines"]

        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr, "Journal must balance: Dr == Cr")
        self.assertEqual(total_dr, 6018)

        # AR debit
        ar_line = next(l for l in lines if l["debit_paise"] == 6018)
        self.assertEqual(ar_line["account_id"], "ar-001")
        # Revenue credit
        rev_line = next(l for l in lines if l["credit_paise"] == 5100)
        self.assertEqual(rev_line["account_id"], "rev-001")
        # IGST credit
        igst_line = next(l for l in lines if l["credit_paise"] == 918)
        self.assertEqual(igst_line["account_id"], "igst-001")

    def test_interstate_paise_are_integers(self):
        """All paise values in the invoice dict must be int, never float."""
        invoice = {
            "invoice_no": "SINV-INT-001",
            "invoice_date": "2026-06-19",
            "total_paise": 6018,
            "taxable_amount_paise": 5100,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "igst_paise": 918,
        }
        self.assertIsInstance(invoice["total_paise"], int)
        self.assertIsInstance(invoice["taxable_amount_paise"], int)
        self.assertIsInstance(invoice["igst_paise"], int)
        self.assertEqual(
            invoice["taxable_amount_paise"] + invoice["igst_paise"],
            invoice["total_paise"],
        )


# ---------------------------------------------------------------------------
# 5. Intrastate invoice posting — Dr AR / Cr Revenue / Cr CGST / Cr SGST
# ---------------------------------------------------------------------------

class TestIntrastateInvoicePosting(unittest.TestCase):
    """
    CGST Act §8: Intra-state supply → CGST + SGST (equal halves).
    Journal: Dr AR 11800 / Cr Revenue 10000 / Cr CGST 900 / Cr SGST 900.
    All values in integer paise.
    """

    def test_intrastate_journal_balance(self):
        """
        Dr AR 11800 = Cr Revenue 10000 + Cr CGST 900 + Cr SGST 900.
        CGST Act §8: Intra-state → CGST+SGST.
        """
        svc = _make_svc()

        invoice = {
            "invoice_no": "SINV-INTRA-001",
            "invoice_date": "2026-06-19",
            "total_paise": 11800,
            "taxable_amount_paise": 10000,
            "cgst_paise": 900,
            "sgst_paise": 900,
            "igst_paise": 0,
        }

        mock_db = MagicMock()
        call_count = {"n": 0}
        # ar, revenue, cgst, sgst — 4 account lookups for intrastate
        account_ids = ["ar-001", "rev-001", "cgst-001", "sgst-001"]

        def select_se(*args, **kwargs):
            inner = MagicMock()
            idx = call_count["n"]
            call_count["n"] += 1
            rc = MagicMock()
            rc.execute.return_value = MagicMock(data=[{"id": account_ids[idx % 4]}])
            inner.eq.return_value.eq.return_value.eq.return_value.limit.return_value = rc
            inner.eq.return_value.or_.return_value.ilike.return_value.eq.return_value.limit.return_value = rc
            return inner

        mock_db.table.return_value.select.side_effect = select_se

        # Patch _create_journal so the duplicate-check select doesn't consume
        # account-resolution mock slots; verify lines via call_args.
        with patch("core.supabase_client.get_supabase", return_value=mock_db):
            with patch.object(svc, "_create_journal", return_value="jnl-002") as mock_cj:
                result = svc.journal_for_sales_invoice(invoice, "firm-1", "client-1")

        self.assertEqual(result, "jnl-002")
        self.assertTrue(mock_cj.called, "_create_journal must be invoked")

        lines = mock_cj.call_args[1]["lines"]

        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr, "Journal must balance")
        self.assertEqual(total_dr, 11800)

        # Confirm 4 lines: AR dr, Revenue cr, CGST cr, SGST cr
        self.assertEqual(len(lines), 4)
        credits = sorted([l["credit_paise"] for l in lines if l["credit_paise"] > 0])
        self.assertEqual(credits, [900, 900, 10000])

    def test_intrastate_cgst_equals_sgst(self):
        """
        CGST Act §8: CGST and SGST are always equal for intra-state supplies.
        """
        taxable = 10000  # paise
        rate_bps = 1800  # 18%
        half_rate = rate_bps // 2
        cgst = (taxable * half_rate) // 10000
        sgst = (taxable * half_rate) // 10000
        self.assertEqual(cgst, sgst)
        self.assertIsInstance(cgst, int)
        self.assertIsInstance(sgst, int)


# ---------------------------------------------------------------------------
# 6. Standard CoA fallback — single combined GST account
# ---------------------------------------------------------------------------

class TestStandardCoAGSTFallback(unittest.TestCase):
    """
    Standard CoA has one combined account (e.g. 'GST Output Tax Payable').
    When gst_cgst/gst_sgst keys are absent, name fallback %GST Output% finds
    the combined account and CGST+SGST both post there. Journal still balances.
    """

    def test_combined_gst_account_fallback_balances(self):
        """
        When key lookup for gst_cgst/gst_sgst returns empty, name fallback
        returns the combined GST account. Both CGST and SGST credit it.
        Journal remains balanced.
        """
        svc = _make_svc()

        invoice = {
            "invoice_no": "SINV-STD-001",
            "invoice_date": "2026-06-19",
            "total_paise": 11800,
            "taxable_amount_paise": 10000,
            "cgst_paise": 900,
            "sgst_paise": 900,
            "igst_paise": 0,
        }

        mock_db = MagicMock()
        call_count = {"n": 0}
        # ar key hits, revenue key hits, gst_cgst key misses → name returns combined,
        # gst_sgst key misses → name returns combined
        key_results = {0: "ar-001", 1: "rev-001"}
        COMBINED_GST = "gst-combined-001"

        def select_se(*args, **kwargs):
            inner = MagicMock()
            idx = call_count["n"]
            call_count["n"] += 1

            key_chain = MagicMock()
            # First two calls succeed via key; subsequent key lookups return empty
            if idx in key_results:
                key_chain.execute.return_value = MagicMock(data=[{"id": key_results[idx]}])
            else:
                key_chain.execute.return_value = MagicMock(data=[])

            name_chain = MagicMock()
            name_chain.execute.return_value = MagicMock(data=[{"id": COMBINED_GST}])

            inner.eq.return_value.eq.return_value.eq.return_value.limit.return_value = key_chain
            inner.eq.return_value.or_.return_value.ilike.return_value.eq.return_value.limit.return_value = name_chain
            return inner

        mock_db.table.return_value.select.side_effect = select_se

        with patch("core.supabase_client.get_supabase", return_value=mock_db):
            with patch.object(svc, "_create_journal", return_value="jnl-003") as mock_cj:
                result = svc.journal_for_sales_invoice(invoice, "firm-1", "client-1")

        self.assertEqual(result, "jnl-003")
        self.assertTrue(mock_cj.called, "_create_journal must be invoked")

        lines = mock_cj.call_args[1]["lines"]

        total_dr = sum(l["debit_paise"] for l in lines)
        total_cr = sum(l["credit_paise"] for l in lines)
        self.assertEqual(total_dr, total_cr, "Journal must balance even with combined GST account")
        self.assertEqual(total_dr, 11800)

        # Both CGST and SGST credits go to the combined account
        gst_lines = [l for l in lines if l["account_id"] == COMBINED_GST]
        gst_total = sum(l["credit_paise"] for l in gst_lines)
        self.assertEqual(gst_total, 1800)


if __name__ == "__main__":
    unittest.main()
