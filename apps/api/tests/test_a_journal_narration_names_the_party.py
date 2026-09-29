"""
A sales-invoice or purchase-bill journal's own narration names the customer
or vendor, not the word "customer"/"vendor".

WHAT WAS WRONG (apex-accounting-reports-09)
    phase2_journal_service.journal_for_sales_invoice hard-coded
    `f"Sales invoice {invoice_no} to customer — CGST Act §9"`, and
    journal_for_purchase_bill hard-coded `f"... from vendor{rcm_note} — ..."`.
    Neither ever looked the party up, so EVERY sales and purchase journal's
    entry-level narration said the literal word "customer"/"vendor" — which is
    what the Day Book, Recent Entries and the Cash Book actually show a CA,
    and it never once named who the money was to or from.

THE FIX
    Phase2JournalService._party_name(db, firm_id, client_id, table, party_id,
    fallback) is a single-row lookup by id — the same shape _find_account
    already uses for chart-of-accounts rows — and both narrations now
    interpolate its answer. It falls back to the neutral word rather than
    raising: a missing or deleted party must never block posting the journal
    itself (the same posture SALES-13 takes for a document's own party
    fallback), so the isolated tests below pin that falling back is silent,
    not an exception.

All monetary values are integer paise. No live database connection is used.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_API_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

import services.phase2_journal_service as _original_module  # noqa: E402
_ORIGINAL_SINGLETON = _original_module.phase2_journal_service


def tearDownModule():
    """Restore phase2_journal_service after _make_svc()'s forced-non-mock reload.

    _make_svc() reloads the module with SUPABASE_URL set so _USE_MOCK becomes
    False; patch.dict restores os.environ but NOT the reloaded module, so
    _USE_MOCK would leak False into later test modules (see
    test_phase2_journal_key_resolution.py, which established this pattern).
    Reloading here under the ambient (mock) environment restores _USE_MOCK to
    its true value.

    THAT RELOAD IS NOT ENOUGH ON ITS OWN, because reload() re-executes
    `phase2_journal_service = Phase2JournalService()` at module scope and so
    hands back a BRAND NEW singleton — different object identity from the one
    every other already-imported caller is holding. A caller that captured the
    module's own attribute at ITS import time (`from services.phase2_journal_service
    import phase2_journal_service`, module-level) still sees the ORIGINAL
    object either way, since reload mutates the SAME module namespace in
    place. But a caller that re-imports the singleton FRESH at CALL TIME —
    `routers/sales_invoices.issue_invoice` does exactly this, inside the
    function body, so a later test can `monkeypatch.setattr` the module-level
    name and have it take effect on the next request — picks up whichever
    instance is CURRENTLY on the module when it runs. Leaving the reload's new
    instance in place would silently swap out the very object
    test_batch3_1_hardening.py's own monkeypatch had already patched, so its
    patch stops reaching the router's next call — found because this file
    collects and runs BEFORE test_batch3_1_hardening.py alphabetically, where
    test_phase2_journal_key_resolution.py's identical reload has always run
    AFTER it and so never exposed this. Restoring the pre-test singleton
    object explicitly, not just re-deriving a fresh one, is what keeps a
    late-bound caller's next call seeing exactly what it would have seen had
    this file never run.
    """
    import importlib
    import services.phase2_journal_service as mod
    importlib.reload(mod)
    mod.phase2_journal_service = _ORIGINAL_SINGLETON


def _make_svc():
    """Return a Phase2JournalService instance forced into non-mock mode."""
    with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co"}):
        import importlib
        import services.phase2_journal_service as mod
        importlib.reload(mod)
        return mod.Phase2JournalService()


def _row_lookup_db(tables: dict) -> MagicMock:
    """A fake `db.table(name)` that answers a fixed row set per table name for
    the exact `.select().eq().eq().eq().limit().execute()` chain _party_name
    issues. `tables` maps a table name to the list of rows its lookup answers
    (empty list == not found)."""
    db = MagicMock()

    def _table(name):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=tables.get(name, []))
        t = MagicMock()
        t.select.return_value.eq.return_value.eq.return_value.eq.return_value \
            .limit.return_value = chain
        return t

    db.table.side_effect = _table
    return db


class TestPartyNameIsolated(unittest.TestCase):
    """_party_name in isolation, no posting pipeline involved."""

    def setUp(self):
        self.svc = _make_svc()

    def test_resolves_the_real_name_when_the_row_is_found(self):
        db = _row_lookup_db({"customers": [{"name": "Meridian Textiles"}]})
        self.assertEqual(
            self.svc._party_name(db, "firm-1", "client-1", "customers", "cust-1", "customer"),
            "Meridian Textiles",
        )

    def test_falls_back_when_no_party_id_is_given(self):
        db = _row_lookup_db({})
        # No party_id at all — never even queries the table.
        self.assertEqual(
            self.svc._party_name(db, "firm-1", "client-1", "vendors", None, "vendor"),
            "vendor",
        )
        db.table.assert_not_called()

    def test_falls_back_when_the_row_is_not_found(self):
        db = _row_lookup_db({"vendors": []})
        self.assertEqual(
            self.svc._party_name(db, "firm-1", "client-1", "vendors", "ven-404", "vendor"),
            "vendor",
        )

    def test_falls_back_and_does_not_raise_when_the_lookup_itself_throws(self):
        db = MagicMock()
        db.table.side_effect = RuntimeError("connection reset")
        # Must not propagate — a missing/unreadable party can never block
        # posting the journal.
        self.assertEqual(
            self.svc._party_name(db, "firm-1", "client-1", "customers", "cust-1", "customer"),
            "customer",
        )


class TestSalesInvoiceNarration(unittest.TestCase):
    """journal_for_sales_invoice's narration, against a forced-non-mock service
    with _create_journal itself patched — the same shape
    TestInterstateInvoicePosting uses in test_phase2_journal_key_resolution.py."""

    def test_names_the_real_customer(self):
        svc = _make_svc()
        db = _row_lookup_db({"customers": [{"name": "Meridian Textiles"}]})

        invoice = {
            "invoice_no": "INV/2026-27/0001",
            "customer_id": "cust-1",
            "total_paise": 118000,
            "taxable_amount_paise": 100000,
            "cgst_paise": 9000,
            "sgst_paise": 9000,
            "invoice_date": "2026-04-10",
        }

        with patch("core.supabase_client.get_supabase", return_value=db):
            with patch.object(svc, "_find_account", return_value="acct-001"):
                with patch.object(svc, "_create_journal", return_value="jnl-1") as mock_cj:
                    svc.journal_for_sales_invoice(invoice, "firm-1", "client-1")

        self.assertTrue(mock_cj.called, "_create_journal must be invoked")
        narration = mock_cj.call_args[1]["narration"]
        self.assertIn("Meridian Textiles", narration)
        self.assertNotIn("to customer —", narration)

    def test_falls_back_to_the_neutral_word_when_the_customer_cannot_be_read(self):
        svc = _make_svc()
        db = _row_lookup_db({"customers": []})

        invoice = {
            "invoice_no": "INV/2026-27/0002",
            "customer_id": "cust-missing",
            "total_paise": 118000,
            "taxable_amount_paise": 100000,
            "cgst_paise": 9000,
            "sgst_paise": 9000,
            "invoice_date": "2026-04-10",
        }

        with patch("core.supabase_client.get_supabase", return_value=db):
            with patch.object(svc, "_find_account", return_value="acct-001"):
                with patch.object(svc, "_create_journal", return_value="jnl-1") as mock_cj:
                    svc.journal_for_sales_invoice(invoice, "firm-1", "client-1")

        self.assertTrue(mock_cj.called)
        narration = mock_cj.call_args[1]["narration"]
        self.assertEqual(narration, "Sales invoice INV/2026-27/0002 to customer — CGST Act §9")


class TestPurchaseBillNarration(unittest.TestCase):
    def test_names_the_real_vendor(self):
        svc = _make_svc()

        # purchase_bill_lines: empty rows -> the fallback single-account debit
        # path, which is fine here since no line routing is asserted.
        vendor_db = _row_lookup_db({"vendors": [{"name": "Apex Steel Traders"}]})
        line_chain = MagicMock()
        line_chain.execute.return_value = MagicMock(data=[])

        def _table(name):
            if name == "purchase_bill_lines":
                t = MagicMock()
                t.select.return_value.eq.return_value = line_chain
                return t
            return vendor_db.table(name)

        db = MagicMock()
        db.table.side_effect = _table

        bill = {
            "id": "bill-1",
            "bill_no": "BILL-9001",
            "vendor_id": "ven-1",
            "taxable_amount_paise": 50000,
            "total_paise": 59000,
            "net_payable_paise": 59000,
            "cgst_paise": 4500,
            "sgst_paise": 4500,
            "bill_date": "2026-04-12",
        }

        with patch("core.supabase_client.get_supabase", return_value=db):
            with patch.object(svc, "_find_account", return_value="acct-001"):
                with patch.object(svc, "_create_journal", return_value="jnl-2") as mock_cj:
                    svc.journal_for_purchase_bill(bill, "firm-1", "client-1")

        self.assertTrue(mock_cj.called, "_create_journal must be invoked")
        narration = mock_cj.call_args[1]["narration"]
        self.assertIn("Apex Steel Traders", narration)
        self.assertNotIn("from vendor ", narration)
        self.assertNotIn("from vendor{", narration)


if __name__ == "__main__":
    unittest.main()
