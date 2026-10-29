"""The pre-flight asks for exactly the accounts the sales journal looks up (POST-A-125).

`GET /api/sales-invoices/{id}/issue-preflight` answers "ready" or lists a missing chart of accounts. Both are claims about what
`phase2_journal_service.journal_for_sales_invoice` will go looking for, and a list of accounts written beside the posting is a second
place to say it. The pre-flight asks `domain/sales/issue_readiness.required_accounts`; the posting still resolves its own accounts
inline. This records every `_find_account` the posting makes, for every shape of invoice, and holds the two lists identical, so the
pre-flight cannot say "ready" for an invoice the posting then refuses, or name an account the posting never needs.
"""
from __future__ import annotations

import pytest

import core.supabase_client as sc
import services.phase2_journal_service as pjs
from domain.sales.issue_readiness import required_accounts

SHAPES = {
    "plain": {},
    "intra_state": {"cgst_paise": 9_000, "sgst_paise": 9_000},
    "inter_state": {"igst_paise": 18_000},
    "cess": {"igst_paise": 18_000, "cess_paise": 1_200},
    "rounded_up": {"cgst_paise": 9_000, "sgst_paise": 9_000, "round_off_paise": 40},
    "rounded_down": {"igst_paise": 18_000, "round_off_paise": -40},
    "everything": {"cgst_paise": 1, "sgst_paise": 1, "igst_paise": 1, "cess_paise": 1, "round_off_paise": 1},
}


def _record_the_postings_lookups(monkeypatch, invoice: dict) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    service = pjs.Phase2JournalService()

    def find(self, db, firm_id, client_id, name_pattern, system_key=None):
        seen.append((name_pattern, system_key))
        return f"acct-{len(seen)}"

    monkeypatch.setattr(pjs, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: object())
    monkeypatch.setattr(pjs.Phase2JournalService, "_find_account", find)
    monkeypatch.setattr(pjs.Phase2JournalService, "_currency_kwargs", lambda self, *a, **k: {})
    monkeypatch.setattr(pjs.Phase2JournalService, "_party_name", lambda self, *a, **k: "Acme")
    monkeypatch.setattr(pjs.Phase2JournalService, "_create_journal", lambda self, **k: "J-1")
    assert service.journal_for_sales_invoice(invoice, "FIRM", "CLI") == "J-1"
    return seen


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_postings_lookups_are_the_preflights_required_accounts(monkeypatch, shape):
    invoice = {"id": "I", "invoice_no": "INV-1", "invoice_date": "2025-06-01", "customer_id": "C", "total_paise": 118_000,
               "taxable_amount_paise": 100_000, **SHAPES[shape]}
    looked_up = _record_the_postings_lookups(monkeypatch, invoice)
    asked = [(a.pattern, a.system_key) for a in required_accounts(invoice)]
    assert asked == looked_up, f"{shape}: the pre-flight asks {asked} but the posting looks up {looked_up}"


def test_the_missing_accounts_method_asks_each_required_account_through_the_postings_own_lookup(monkeypatch):
    """It resolves through `_find_account` itself, not through a copy of that search, and reports the labels of the ones not found."""
    invoice = {"cgst_paise": 9, "sgst_paise": 9, "cess_paise": 1}
    asked: list[tuple[str, str]] = []

    def find(self, db, firm_id, client_id, name_pattern, system_key=None):
        asked.append((name_pattern, system_key))
        if system_key in ("revenue", "gst_sgst"):
            raise ValueError("Required account not found")
        return "acct"

    monkeypatch.setattr(pjs, "_USE_MOCK", False)
    monkeypatch.setattr(pjs.Phase2JournalService, "_find_account", find)
    missing = pjs.Phase2JournalService().missing_accounts_for_sales_invoice(object(), "FIRM", "CLI", invoice)
    assert missing == ["Sales", "GST Output (SGST)"]
    assert asked == [(a.pattern, a.system_key) for a in required_accounts(invoice)]


def test_the_in_memory_mode_has_no_chart_to_ask(monkeypatch):
    monkeypatch.setattr(pjs, "_USE_MOCK", True)
    assert pjs.Phase2JournalService().missing_accounts_for_sales_invoice(None, "FIRM", "CLI", {"cgst_paise": 9}) == []
