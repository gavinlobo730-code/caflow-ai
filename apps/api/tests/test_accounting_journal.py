"""
Unit tests for double-entry accounting engine.
CGST Act Section 2(59): ITC. IT Act Section 44AB: Tax Audit.
All monetary values in paise (integer arithmetic).
"""
import pytest
from domain.accounting_service import AccountingService, MOCK_JOURNAL_ENTRIES, MOCK_ACCOUNTS


svc = AccountingService()


# ── Double-entry integrity ────────────────────────────────────────────────────

class TestDoubleEntryIntegrity:
    def test_all_posted_entries_are_balanced(self):
        """Every posted journal entry must have debit == credit."""
        for entry in MOCK_JOURNAL_ENTRIES:
            if entry["status"] != "posted":
                continue
            total_debit = sum(ln["debit_paise"] for ln in entry["lines"])
            total_credit = sum(ln["credit_paise"] for ln in entry["lines"])
            assert total_debit == total_credit, (
                f"Entry {entry['id']} unbalanced: debit={total_debit} credit={total_credit}"
            )

    def test_trial_balance_is_balanced(self):
        """Trial balance total debit must equal total credit (posted entries only)."""
        tb = svc.get_trial_balance()
        assert tb["is_balanced"], (
            f"Trial balance unbalanced: diff={tb['difference_paise']} paise"
        )
        assert tb["difference_paise"] == 0

    def test_trial_balance_grand_totals_are_integers(self):
        tb = svc.get_trial_balance()
        assert isinstance(tb["total_debit_paise"], int)
        assert isinstance(tb["total_credit_paise"], int)

    def test_create_journal_entry_rejects_unbalanced_when_posting(self):
        from core.exceptions import ValidationError
        with pytest.raises(ValidationError, match="nbalanced"):
            svc.create_journal_entry({
                "client_id": "c-001",
                "firm_id": "firm-001",
                "entry_date": "2025-06-01",
                "narration": "Bad entry",
                "status": "posted",
                "lines": [
                    {"account_id": "acc-002", "debit_paise": 100000, "credit_paise": 0},
                    {"account_id": "acc-013", "debit_paise": 0, "credit_paise": 50000},  # unbalanced
                ],
            })

    def test_create_journal_entry_requires_2_lines(self):
        from core.exceptions import ValidationError
        with pytest.raises(ValidationError):
            svc.create_journal_entry({
                "client_id": "c-001",
                "status": "draft",
                "lines": [
                    {"account_id": "acc-002", "debit_paise": 100000, "credit_paise": 0},
                ],
            })


# ── Trial Balance ──────────────────────────────────────────────────────────

class TestTrialBalance:
    def test_accounts_in_trial_balance(self):
        tb = svc.get_trial_balance()
        account_ids = {row["account_id"] for row in tb["lines"]}
        # These accounts appear in mock journal entries
        assert "acc-002" in account_ids   # Bank
        assert "acc-009" in account_ids   # GST Payable
        assert "acc-015" in account_ids   # Professional Fees

    def test_as_of_date_filter(self):
        tb_full = svc.get_trial_balance()
        tb_early = svc.get_trial_balance("2025-04-10")  # Only first few entries
        # Early balance should have fewer or equal total debit
        assert tb_early["total_debit_paise"] <= tb_full["total_debit_paise"]

    def test_all_paise_values_are_integers(self):
        tb = svc.get_trial_balance()
        for row in tb["lines"]:
            assert isinstance(row["total_debit_paise"], int)
            assert isinstance(row["total_credit_paise"], int)
            assert isinstance(row["net_paise"], int)


# ── Profit & Loss ──────────────────────────────────────────────────────────

class TestProfitAndLoss:
    FY_START = "2025-04-01"
    FY_END = "2026-03-31"

    def test_revenue_positive(self):
        pl = svc.get_profit_loss(start_date=self.FY_START, end_date=self.FY_END)
        assert pl["revenue"]["total_paise"] > 0

    def test_expenses_positive(self):
        pl = svc.get_profit_loss(start_date=self.FY_START, end_date=self.FY_END)
        assert pl["operating_expenses"]["total_paise"] > 0

    def test_net_profit_equals_revenue_minus_opex(self):
        pl = svc.get_profit_loss(start_date=self.FY_START, end_date=self.FY_END)
        expected = pl["revenue"]["total_paise"] - pl["operating_expenses"]["total_paise"]
        assert pl["net_profit_paise"] == expected

    def test_client_filter(self):
        pl_all = svc.get_profit_loss(start_date=self.FY_START, end_date=self.FY_END)
        pl_c001 = svc.get_profit_loss(start_date=self.FY_START, end_date=self.FY_END, client_id="c-001")
        # c-001 filtered P&L should have <= revenue of all-clients P&L
        assert pl_c001["revenue"]["total_paise"] <= pl_all["revenue"]["total_paise"]

    def test_all_paise_are_integers(self):
        pl = svc.get_profit_loss(start_date=self.FY_START, end_date=self.FY_END)
        assert isinstance(pl["revenue"]["total_paise"], int)
        assert isinstance(pl["operating_expenses"]["total_paise"], int)
        assert isinstance(pl["net_profit_paise"], int)


# ── Balance Sheet ──────────────────────────────────────────────────────────

class TestBalanceSheet:
    def test_assets_positive(self):
        bs = svc.get_balance_sheet()
        assert bs["total_assets_paise"] > 0

    def test_balance_sheet_is_balanced(self):
        bs = svc.get_balance_sheet()
        assert bs["is_balanced"], (
            f"Balance sheet unbalanced: assets={bs['total_assets_paise']} "
            f"liab+equity={bs['total_liabilities_equity_paise']}"
        )

    def test_all_paise_are_integers(self):
        bs = svc.get_balance_sheet()
        assert isinstance(bs["total_assets_paise"], int)
        assert isinstance(bs["total_liabilities_equity_paise"], int)


# ── Ledger ─────────────────────────────────────────────────────────────────

class TestLedger:
    def test_bank_ledger_has_entries(self):
        lines = svc.get_ledger("acc-002")
        assert len(lines) > 0

    def test_running_balance_is_integer(self):
        lines = svc.get_ledger("acc-002")
        for ln in lines:
            assert isinstance(ln["running_balance_paise"], int)

    def test_running_balance_cumulative(self):
        """Each line's running balance must equal previous + debit - credit."""
        lines = svc.get_ledger("acc-002")
        running = 0
        for ln in lines:
            running += ln["debit_paise"] - ln["credit_paise"]
            assert ln["running_balance_paise"] == running

    def test_ledger_sorted_by_date(self):
        lines = svc.get_ledger("acc-002")
        dates = [ln["date"] for ln in lines]
        assert dates == sorted(dates)

    def test_date_filter(self):
        all_lines = svc.get_ledger("acc-002")
        filtered = svc.get_ledger("acc-002", start_date="2025-05-01")
        assert len(filtered) <= len(all_lines)
