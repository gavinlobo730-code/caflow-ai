"""
services/reconciliation_service.py — books-integrity checks (task #244).

Each check_* function is tested directly against hand-built JournalEntry
data (bypassing SupabaseLedgerSource's PostgREST embedded-select shape,
which the shared e2e_harness.FakeDB doesn't reproduce) plus the shared
e2e_harness.FakeDB for every other table these checks read. One end-to-end
orchestration test drives run_reconciliation() itself, monkeypatching
SupabaseLedgerSource._entries for the same reason.
"""
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


# ── check_trial_balance ──────────────────────────────────────────────────────

def test_trial_balance_clean_when_balanced():
    entries = {
        "e1": _entry("e1", lines=[_line("bank", debit=1000), _line("sales", credit=1000)]),
    }
    assert rs.check_trial_balance(None, FIRM, CLIENT, entries) == []


def test_trial_balance_flags_imbalance():
    entries = {
        "e1": _entry("e1", lines=[_line("bank", debit=1000), _line("sales", credit=900)]),
    }
    findings = rs.check_trial_balance(None, FIRM, CLIENT, entries)
    assert len(findings) == 1
    assert findings[0]["check_name"] == "trial_balance"
    assert findings[0]["severity"] == "critical"
    assert findings[0]["amount_paise"] == 100


# ── check_missing_cogs_journals ──────────────────────────────────────────────

def test_missing_cogs_journal_detected():
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "sales_invoice",
        "source_id": "INV-1", "movement_type": "sale", "value_delta_paise": -50000,
    })
    db.seed("client_sales_invoices", {"id": "INV-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-BULK-001"})
    entries = {}  # no journal at all posted anywhere
    findings = rs.check_missing_cogs_journals(db, FIRM, CLIENT, entries)
    assert len(findings) == 1
    assert findings[0]["check_name"] == "missing_cogs_journal"
    assert findings[0]["amount_paise"] == 50000
    assert findings[0]["details"]["invoice_no"] == "INV-BULK-001"


def test_cogs_journal_present_is_not_flagged():
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "sales_invoice",
        "source_id": "INV-1", "movement_type": "sale", "value_delta_paise": -50000,
    })
    db.seed("client_sales_invoices", {"id": "INV-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "INV-BULK-001"})
    entries = {"j1": _entry("j1", reference_no="INV-BULK-001-COGS", lines=[_line("cogs", 500), _line("inv", credit=500)])}
    assert rs.check_missing_cogs_journals(db, FIRM, CLIENT, entries) == []


def test_zero_value_sale_movements_not_flagged():
    # e.g. an oversold-at-Rs-0-cost movement — nothing to have journaled.
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "sales_invoice",
        "source_id": "INV-1", "movement_type": "sale", "value_delta_paise": 0,
    })
    assert rs.check_missing_cogs_journals(db, FIRM, CLIENT, {}) == []


# ── check_missing_inventory_receipt_journals ─────────────────────────────────

def test_missing_inventory_receipt_journal_detected(monkeypatch):
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "purchase_bill",
        "source_id": "BILL-1", "movement_type": "purchase", "value_delta_paise": 70000,
    })
    db.seed("purchase_bills", {"id": "BILL-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "VEND-001"})
    monkeypatch.setattr(
        "services.phase2_journal_service.purchase_bill_journal_ref",
        lambda bill_id: f"PB-{bill_id}",
    )
    findings = rs.check_missing_inventory_receipt_journals(db, FIRM, CLIENT, {})
    assert len(findings) == 1
    assert findings[0]["check_name"] == "missing_inventory_receipt_journal"
    assert findings[0]["amount_paise"] == 70000


def test_inventory_receipt_journal_present_under_either_reference_style(monkeypatch):
    db = FakeDB()
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": CLIENT, "source_type": "purchase_bill",
        "source_id": "BILL-1", "movement_type": "purchase", "value_delta_paise": 70000,
    })
    db.seed("purchase_bills", {"id": "BILL-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "VEND-001"})
    monkeypatch.setattr(
        "services.phase2_journal_service.purchase_bill_journal_ref",
        lambda bill_id: f"PB-{bill_id}",
    )
    # Old-style ref (vendor bill_no), the pre-fix convention.
    entries = {"j1": _entry("j1", reference_no="VEND-001-INV", lines=[_line("inv", 700), _line("purch", credit=700)])}
    assert rs.check_missing_inventory_receipt_journals(db, FIRM, CLIENT, entries) == []


# ── check_inventory_cache_drift ──────────────────────────────────────────────

def test_inventory_cache_drift_detected():
    db = FakeDB()
    db.seed("service_catalogue", {
        "id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT, "kind": "good",
        "name": "Widget", "stock_qty_units": 522, "avg_cost_paise": 5000,
    })
    db.seed("inventory_stock_ledger", {
        "service_catalogue_id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT,
        "running_qty_units": 297, "running_avg_cost_paise": 5000, "created_at": "2026-07-18T00:00:00Z",
    })
    findings = rs.check_inventory_cache_drift(db, FIRM, CLIENT, {})
    assert len(findings) == 1
    assert findings[0]["check_name"] == "inventory_cache_drift"
    assert findings[0]["details"]["item_count"] == 1
    assert findings[0]["details"]["items"][0]["drift_paise"] == (522 * 5000) - (297 * 5000)


def test_inventory_cache_matches_ledger_is_not_flagged():
    db = FakeDB()
    db.seed("service_catalogue", {
        "id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT, "kind": "good",
        "name": "Widget", "stock_qty_units": 297, "avg_cost_paise": 5000,
    })
    db.seed("inventory_stock_ledger", {
        "service_catalogue_id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT,
        "running_qty_units": 297, "running_avg_cost_paise": 5000, "created_at": "2026-07-18T00:00:00Z",
    })
    assert rs.check_inventory_cache_drift(db, FIRM, CLIENT, {}) == []


def test_inventory_item_with_no_ledger_history_is_not_flagged_as_drift():
    # A separate, pre-existing setup gap (never seeded) — not this check's concern.
    db = FakeDB()
    db.seed("service_catalogue", {
        "id": "SVC-1", "firm_id": FIRM, "client_id": CLIENT, "kind": "good",
        "name": "Widget", "stock_qty_units": 10, "avg_cost_paise": 100,
    })
    assert rs.check_inventory_cache_drift(db, FIRM, CLIENT, {}) == []


# ── check_ar_subledger_vs_gl / check_ap_subledger_vs_gl ──────────────────────

def test_ar_subledger_matches_gl_is_not_flagged():
    db = FakeDB()
    db.seed("chart_of_accounts", {
        "id": "AR-1", "firm_id": FIRM, "client_id": None,
        "account_name": "Trade Receivables", "is_active": True,
    })
    db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "status": "issued",
        "total_paise": 100000, "paid_paise": 40000, "credited_paise": 0, "debit_note_paise": 0,
    })
    entries = {"j1": _entry("j1", lines=[_line("AR-1", debit=60000), _line("sales", credit=60000)])}
    assert rs.check_ar_subledger_vs_gl(db, FIRM, CLIENT, entries) == []


def test_ar_subledger_mismatch_detected():
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
    assert findings[0]["check_name"] == "ar_subledger_vs_gl"
    assert findings[0]["severity"] == "critical"  # off by >= 1000 rupees


def test_ap_subledger_matches_gl_is_not_flagged():
    db = FakeDB()
    db.seed("chart_of_accounts", {
        "id": "AP-1", "firm_id": FIRM, "client_id": None,
        "account_name": "Trade Payables", "is_active": True,
    })
    db.seed("purchase_bills", {
        "firm_id": FIRM, "client_id": CLIENT, "status": "received",
        "net_payable_paise": 80000, "paid_paise": 30000, "debited_paise": 0, "credit_note_paise": 0,
    })
    entries = {"j1": _entry("j1", lines=[_line("purch", debit=50000), _line("AP-1", credit=50000)])}
    assert rs.check_ap_subledger_vs_gl(db, FIRM, CLIENT, entries) == []


def test_no_ar_account_configured_skips_silently():
    db = FakeDB()
    assert rs.check_ar_subledger_vs_gl(db, FIRM, CLIENT, {}) == []


# ── run_reconciliation orchestration ──────────────────────────────────────────

def test_run_reconciliation_persists_run_and_findings(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {
            "e1": _entry("e1", lines=[_line("bank", debit=1000), _line("sales", credit=900)]),
        },
    )
    result = rs.run_reconciliation(db, FIRM, CLIENT, trigger="manual", triggered_by="user-1")

    assert result["status"] == "completed"
    assert result["checks_run"] == len(rs._CHECKS)
    assert result["findings_count"] >= 1  # the imbalance from the stubbed entries

    runs = db.rows("reconciliation_runs")
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["trigger"] == "manual"
    assert runs[0]["triggered_by"] == "user-1"
    assert runs[0]["completed_at"] is not None

    findings = db.rows("reconciliation_findings")
    assert len(findings) == result["findings_count"]
    assert all(f["run_id"] == runs[0]["id"] for f in findings)
    assert any(f["check_name"] == "trial_balance" for f in findings)


def test_run_reconciliation_clean_books_produce_zero_findings(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {
            "e1": _entry("e1", lines=[_line("bank", debit=1000), _line("sales", credit=1000)]),
        },
    )
    result = rs.run_reconciliation(db, FIRM, CLIENT, trigger="scheduled")
    assert result["status"] == "completed"
    assert result["findings_count"] == 0
    assert db.rows("reconciliation_findings") == []
    assert db.rows("reconciliation_runs")[0]["findings_count"] == 0


def test_run_reconciliation_survives_one_check_erroring(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {},
    )

    def _boom(db, firm_id, client_id, entries):
        raise RuntimeError("simulated check bug")

    monkeypatch.setattr(rs, "_CHECKS", [rs.check_trial_balance, _boom])
    result = rs.run_reconciliation(db, FIRM, CLIENT, trigger="manual")

    assert result["status"] == "completed"  # one bad check must not fail the whole run
    assert result["checks_run"] == 2
    error_findings = [f for f in result["findings"] if f["check_name"].endswith(".execution_error")]
    assert len(error_findings) == 1
    assert error_findings[0]["severity"] == "critical"


def test_run_reconciliation_records_failure_if_ledger_fetch_itself_errors(monkeypatch):
    db = FakeDB()

    def _boom(self, firm_id, client_id):
        raise ConnectionError("db unreachable")

    monkeypatch.setattr("domain.reporting.sources.SupabaseLedgerSource._entries", _boom)
    result = rs.run_reconciliation(db, FIRM, CLIENT, trigger="scheduled")

    assert result["status"] == "failed"
    assert "db unreachable" in result["error"]
    assert db.rows("reconciliation_runs")[0]["status"] == "failed"


# ── run_reconciliation_for_firm ───────────────────────────────────────────────

def test_run_reconciliation_for_firm_runs_every_client(monkeypatch):
    db = FakeDB()
    db.seed("clients", {"id": "C1", "firm_id": FIRM})
    db.seed("clients", {"id": "C2", "firm_id": FIRM})
    monkeypatch.setattr(
        "domain.reporting.sources.SupabaseLedgerSource._entries",
        lambda self, firm_id, client_id: {},
    )
    result = rs.run_reconciliation_for_firm(db, FIRM)
    assert result["clients_checked"] == 2
    assert result["findings_total"] == 0
    assert {c["client_id"] for c in result["clients"]} == {"C1", "C2"}
    assert len(db.rows("reconciliation_runs")) == 2


def test_run_reconciliation_for_firm_survives_one_client_erroring(monkeypatch):
    db = FakeDB()
    db.seed("clients", {"id": "C1", "firm_id": FIRM})
    db.seed("clients", {"id": "C2", "firm_id": FIRM})

    def _entries(self, firm_id, client_id):
        if client_id == "C1":
            raise ConnectionError("boom")
        return {}

    def _fake_run(db, firm_id, client_id, *, trigger, triggered_by=None):
        if client_id == "C1":
            raise RuntimeError("boom")
        return {"run_id": "r2", "status": "completed", "checks_run": 6, "findings_count": 0, "findings": []}

    monkeypatch.setattr(rs, "run_reconciliation", _fake_run)
    result = rs.run_reconciliation_for_firm(db, FIRM)
    assert result["clients_checked"] == 1
    by_client = {c["client_id"]: c for c in result["clients"]}
    assert "error" in by_client["C1"]
    assert by_client["C2"]["status"] == "completed"
