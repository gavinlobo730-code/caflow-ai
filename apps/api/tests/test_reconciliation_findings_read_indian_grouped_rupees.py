"""Every check_* finding's human-readable SUMMARY reads Indian-grouped
rupees, not raw integer paise or a float division (apex-accounting-reports-19).

services/reconciliation_service.py built several sentences by interpolating
a raw integer paise value straight into an f-string (e.g. "net overstatement
of 15210091758 paise"), and two more used `f"₹{x/100:.2f}"` — float division,
never Indian-grouped, and exactly the pattern CLAUDE.md's money-formatting
section calls out. All six now go through domain/money_text.rupees_paise,
which is integer-safe, sign-safe and Indian-grouped.

`amount_paise` (the finding's own machine-readable field, used for a UI
badge) is deliberately UNTOUCHED here — only the sentence changed. Amounts
below are chosen large enough (crossing a lakh) that Indian grouping is
visibly different from a Western thousands-grouping, so a fix that merely
divided by 100 without grouping correctly would still be caught.

Fixture shapes for `FakeDB` are lifted verbatim from
tests/test_reconciliation_service.py so this file exercises the real
plumbing rather than a shape nothing else agrees with.
"""
from __future__ import annotations

from domain.reporting.model import JournalEntry, JournalLine
from tests.e2e_harness import FakeDB

import services.reconciliation_service as rs

FIRM = "FIRM-A"
CLIENT = "CLI-A"


def _entry(id_, *, reference_no=None, lines):
    return JournalEntry(
        id=id_, entry_date="2026-04-05", client_id=CLIENT, firm_id=FIRM,
        entry_type="Journal", lines=tuple(lines), reference_no=reference_no,
    )


def _line(account_id, debit=0, credit=0):
    return JournalLine(account_id=account_id, debit_paise=debit, credit_paise=credit)


def _no_raw_paise_or_float_division(summary: str) -> None:
    assert "paise" not in summary, f"the sentence still names the unit as paise: {summary!r}"
    assert "/100" not in summary and "/ 100" not in summary, summary


def test_trial_balance_imbalance_reads_indian_grouped_rupees():
    entries = {
        "e1": _entry("e1", lines=[_line("bank", debit=123_456_750 + 900), _line("sales", credit=900)]),
    }
    findings = rs.check_trial_balance(None, FIRM, CLIENT, entries)
    assert len(findings) == 1
    summary = findings[0]["summary"]
    assert "12,34,567.50" in summary, summary
    assert findings[0]["amount_paise"] == 123_456_750, "the machine-readable field stays raw paise"
    _no_raw_paise_or_float_division(summary)


def test_missing_cogs_journal_reads_indian_grouped_rupees_not_a_float_division():
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "sales_invoice",
        "source_id": "INV-1", "movement_type": "sale", "value_delta_paise": -123_456_750,
    })
    db.seed("client_sales_invoices", {"id": "INV-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-BULK-001"})
    findings = rs.check_missing_cogs_journals(db, FIRM, CLIENT, {})
    assert len(findings) == 1
    summary = findings[0]["summary"]
    assert "12,34,567.50" in summary, summary
    _no_raw_paise_or_float_division(summary)


def test_missing_inventory_receipt_journal_reads_indian_grouped_rupees(monkeypatch):
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "purchase_bill",
        "source_id": "BILL-1", "movement_type": "purchase", "value_delta_paise": 123_456_750,
    })
    db.seed("purchase_bills", {"id": "BILL-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "VEND-001"})
    monkeypatch.setattr(
        "services.phase2_journal_service.purchase_bill_journal_ref",
        lambda bill_id: f"PB-{bill_id}",
    )
    findings = rs.check_missing_inventory_receipt_journals(db, FIRM, CLIENT, {})
    assert len(findings) == 1
    summary = findings[0]["summary"]
    assert "12,34,567.50" in summary, summary
    _no_raw_paise_or_float_division(summary)


def test_inventory_cache_drift_reads_indian_grouped_rupees():
    db = FakeDB()
    db.seed("service_catalogue", {
        "id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT, "kind": "good",
        "name": "Widget", "stock_qty_units": 3000, "avg_cost_paise": 5000,
    })
    db.seed("inventory_stock_ledger", {
        "service_catalogue_id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT,
        "running_qty_units": 500, "running_avg_cost_paise": 5000, "created_at": "2026-07-18T00:00:00Z",
    })
    findings = rs.check_inventory_cache_drift(db, FIRM, CLIENT, {})
    assert len(findings) == 1
    summary = findings[0]["summary"]
    # drift = (3000 - 500) * 5000 paise = 1,25,00,000 paise = Rs 1,25,000.00
    assert "1,25,000.00" in summary, summary
    _no_raw_paise_or_float_division(summary)


def test_ar_subledger_vs_gl_reads_indian_grouped_rupees():
    db = FakeDB()
    db.seed("chart_of_accounts", {
        "id": "AR-1", "firm_id": FIRM, "client_id": None,
        "account_name": "Trade Receivables", "is_active": True,
    })
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "status": "issued",
        "total_paise": 100000, "paid_paise": 40000, "credited_paise": 0, "debit_note_paise": 0,
    })
    entries = {"j1": _entry("j1", lines=[_line("AR-1", debit=1_000_060000), _line("sales", credit=1_000_060000)])}
    findings = rs.check_ar_subledger_vs_gl(db, FIRM, CLIENT, entries)
    assert len(findings) == 1
    summary = findings[0]["summary"]
    assert "₹" in summary and "," in summary, summary
    _no_raw_paise_or_float_division(summary)


def test_ap_subledger_vs_gl_reads_indian_grouped_rupees():
    db = FakeDB()
    db.seed("chart_of_accounts", {
        "id": "AP-1", "firm_id": FIRM, "client_id": None,
        "account_name": "Trade Payables", "is_active": True,
    })
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "status": "received",
        "net_payable_paise": 80000, "paid_paise": 30000, "debited_paise": 0, "credit_note_paise": 0,
    })
    entries = {"j1": _entry("j1", lines=[_line("purch", debit=1_000_050000), _line("AP-1", credit=1_000_050000)])}
    findings = rs.check_ap_subledger_vs_gl(db, FIRM, CLIENT, entries)
    assert len(findings) == 1
    summary = findings[0]["summary"]
    assert "₹" in summary and "," in summary, summary
    _no_raw_paise_or_float_division(summary)


def test_orphan_money_journals_reads_indian_grouped_rupees():
    class Line:
        def __init__(self, debit=0, credit=0):
            self.debit_paise, self.credit_paise = debit, credit

    class Entry:
        def __init__(self, eid, entry_type, debit=0, ref="VPMT-0001", when="2026-03-27"):
            self.id, self.entry_type = eid, entry_type
            self.reference_no, self.entry_date = ref, when
            self.lines = [Line(debit=debit), Line(credit=debit)]

    class DB:
        """Answers the three lookups the check makes — lifted from
        tests/test_orphan_money_journals.py, which nothing here owns."""

        def __init__(self):
            self._t, self._f = None, {}

        def table(self, name):
            self._t, self._f = name, {}
            return self

        def select(self, *_a):
            return self

        def eq(self, col, val):
            self._f[col] = val
            return self

        def limit(self, _n):
            return self

        def execute(self):
            return type("R", (), {"data": []})()   # never owned, never reversed

    entries = {"je1": Entry("je1", "Payment", debit=123_456_750)}
    findings = rs.check_orphan_money_journals(DB(), FIRM, CLIENT, entries)
    assert len(findings) == 1
    summary = findings[0]["summary"]
    assert "12,34,567.50" in summary, summary
    _no_raw_paise_or_float_division(summary)
