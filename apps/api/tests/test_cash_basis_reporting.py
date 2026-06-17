"""
Unit tests for Cash Basis vs Accrual Basis reporting.

IT Act Section 145: method of accounting (cash vs accrual).
IT Act Section 44AA: record-keeping for professionals.
Companies Act Section 128: companies must use accrual (mercantile) system.

Cash basis is management reporting only — never affects GST returns.
All amounts in integer paise. No floats. No rounding drift.
"""
import pytest
from domain.accounting_service import (
    AccountingService,
    MOCK_JOURNAL_ENTRIES,
    ACCOUNT_INDEX,
)


@pytest.fixture(autouse=True)
def fresh_service():
    """Each test gets a fresh AccountingService instance."""
    return AccountingService()


# ─── Helper to build a service with injected journal entries ─────────────────

def _service_with_entries(entries: list[dict]) -> AccountingService:
    """
    Build an AccountingService and monkey-patch MOCK_JOURNAL_ENTRIES
    to contain exactly the provided entries for isolated testing.
    """
    import domain.accounting_service as svc_module
    original = svc_module.MOCK_JOURNAL_ENTRIES[:]
    svc_module.MOCK_JOURNAL_ENTRIES.clear()
    svc_module.MOCK_JOURNAL_ENTRIES.extend(entries)
    # Rebuild the index so _build_ar_debit_index() sees only our entries
    svc_module.JOURNAL_INDEX.clear()
    svc_module.JOURNAL_INDEX.update({e["id"]: e for e in entries})
    svc = AccountingService()
    yield svc
    # Restore
    svc_module.MOCK_JOURNAL_ENTRIES.clear()
    svc_module.MOCK_JOURNAL_ENTRIES.extend(original)
    svc_module.JOURNAL_INDEX.clear()
    svc_module.JOURNAL_INDEX.update({e["id"]: e for e in original})


# ─── Fixtures: canonical test entries ─────────────────────────────────────────

# Use explicit dates in current FY (2026-27) so get_profit_loss() default range includes them.
# Explicit start_date/end_date are passed in every P&L call below for date-independence.
_FY_START = "2026-04-01"
_FY_END = "2027-03-31"

# Invoice: Dr A/R 10000000 (₹1,00,000), Cr Revenue 10000000 — accrual invoice
INVOICE_ENTRY = {
    "id": "je-test-inv", "client_id": "c-test", "firm_id": "firm-001",
    "entry_date": "2026-04-10", "reference_no": "INV/TEST/001",
    "narration": "Test invoice", "entry_type": "Sales", "status": "posted",
    "lines": [
        {"id": "jl-ti-1", "account_id": "acc-003", "account_name": "Trade Receivables", "debit_paise": 10000000, "credit_paise": 0, "narration": ""},
        {"id": "jl-ti-2", "account_id": "acc-015", "account_name": "Professional Fees — GST Clients", "debit_paise": 0, "credit_paise": 10000000, "narration": ""},
    ],
}

# Full receipt: Dr Bank 10000000, Cr A/R 10000000
FULL_RECEIPT_ENTRY = {
    "id": "je-test-rec-full", "client_id": "c-test", "firm_id": "firm-001",
    "entry_date": "2026-04-20", "reference_no": "REC/TEST/001",
    "narration": "Full receipt", "entry_type": "Receipt", "status": "posted",
    "lines": [
        {"id": "jl-rf-1", "account_id": "acc-002", "account_name": "Bank — HDFC", "debit_paise": 10000000, "credit_paise": 0, "narration": ""},
        {"id": "jl-rf-2", "account_id": "acc-003", "account_name": "Trade Receivables", "debit_paise": 0, "credit_paise": 10000000, "narration": ""},
    ],
}

# Partial receipt: Dr Bank 4000000, Cr A/R 4000000  (40% of 10000000)
PARTIAL_RECEIPT_ENTRY = {
    "id": "je-test-rec-part", "client_id": "c-test", "firm_id": "firm-001",
    "entry_date": "2026-04-20", "reference_no": "REC/TEST/001P",
    "narration": "Partial receipt", "entry_type": "Receipt", "status": "posted",
    "lines": [
        {"id": "jl-rp-1", "account_id": "acc-002", "account_name": "Bank — HDFC", "debit_paise": 4000000, "credit_paise": 0, "narration": ""},
        {"id": "jl-rp-2", "account_id": "acc-003", "account_name": "Trade Receivables", "debit_paise": 0, "credit_paise": 4000000, "narration": ""},
    ],
}

# Bill: Dr Expense 5000000, Cr A/P 5000000 — accrual bill
BILL_ENTRY = {
    "id": "je-test-bill", "client_id": "c-test", "firm_id": "firm-001",
    "entry_date": "2026-04-11", "reference_no": "BILL/TEST/001",
    "narration": "Test bill", "entry_type": "Purchase", "status": "posted",
    "lines": [
        {"id": "jl-tb-1", "account_id": "acc-018", "account_name": "Salary Expense", "debit_paise": 5000000, "credit_paise": 0, "narration": ""},
        {"id": "jl-tb-2", "account_id": "acc-008", "account_name": "Trade Payables", "debit_paise": 0, "credit_paise": 5000000, "narration": ""},
    ],
}

# Full payment: Dr A/P 5000000, Cr Bank 5000000
FULL_PAYMENT_ENTRY = {
    "id": "je-test-pay-full", "client_id": "c-test", "firm_id": "firm-001",
    "entry_date": "2026-04-25", "reference_no": "PAY/TEST/001",
    "narration": "Full payment", "entry_type": "Payment", "status": "posted",
    "lines": [
        {"id": "jl-pf-1", "account_id": "acc-008", "account_name": "Trade Payables", "debit_paise": 5000000, "credit_paise": 0, "narration": ""},
        {"id": "jl-pf-2", "account_id": "acc-002", "account_name": "Bank — HDFC", "debit_paise": 0, "credit_paise": 5000000, "narration": ""},
    ],
}

# Partial payment: Dr A/P 2000000, Cr Bank 2000000 (40% of 5000000)
PARTIAL_PAYMENT_ENTRY = {
    "id": "je-test-pay-part", "client_id": "c-test", "firm_id": "firm-001",
    "entry_date": "2026-04-25", "reference_no": "PAY/TEST/001P",
    "narration": "Partial payment", "entry_type": "Payment", "status": "posted",
    "lines": [
        {"id": "jl-pp-1", "account_id": "acc-008", "account_name": "Trade Payables", "debit_paise": 2000000, "credit_paise": 0, "narration": ""},
        {"id": "jl-pp-2", "account_id": "acc-002", "account_name": "Bank — HDFC", "debit_paise": 0, "credit_paise": 2000000, "narration": ""},
    ],
}


# ─── Revenue tests ─────────────────────────────────────────────────────────────

class TestCashBasisRevenue:

    def test_unpaid_invoice_accrual_shows_full_revenue(self, fresh_service):
        """Accrual: invoice alone shows full revenue."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(INVOICE_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-inv"] = INVOICE_ENTRY

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="accrual")
            total_rev = pl["revenue"]["total_paise"]
            assert total_rev == 10000000, f"Expected 10000000, got {total_rev}"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_unpaid_invoice_cash_shows_zero_revenue(self, fresh_service):
        """Cash: unpaid invoice → cash revenue = 0 (no cash received)."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(INVOICE_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-inv"] = INVOICE_ENTRY

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="cash")
            total_rev = pl["revenue"]["total_paise"]
            assert total_rev == 0, f"Unpaid invoice: cash revenue must be 0, got {total_rev}"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_fully_paid_invoice_cash_shows_full_revenue(self, fresh_service):
        """Cash: invoice + full receipt → cash revenue = invoice amount (paise)."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            entries = [INVOICE_ENTRY, FULL_RECEIPT_ENTRY]
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(entries)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update({e["id"]: e for e in entries})

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="cash")
            total_rev = pl["revenue"]["total_paise"]
            assert total_rev == 10000000, f"Full receipt: cash revenue must be 10000000, got {total_rev}"
            # Integer paise — not a float
            assert isinstance(total_rev, int), "Revenue must be integer paise"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_partially_paid_invoice_cash_shows_collected_amount(self, fresh_service):
        """Cash: invoice ₹1,00,000 + receipt ₹40,000 → cash revenue = 4000000 paise."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            entries = [INVOICE_ENTRY, PARTIAL_RECEIPT_ENTRY]
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(entries)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update({e["id"]: e for e in entries})

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="cash")
            total_rev = pl["revenue"]["total_paise"]
            # 4000000/10000000 = 40% of 10000000 revenue = 4000000 paise
            assert total_rev == 4000000, f"Partial receipt: cash revenue must be 4000000, got {total_rev}"
            assert isinstance(total_rev, int), "Revenue must be integer paise"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_accrual_always_shows_full_revenue_regardless_of_payment(self, fresh_service):
        """Accrual: invoice + partial receipt → accrual revenue is still full amount."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            entries = [INVOICE_ENTRY, PARTIAL_RECEIPT_ENTRY]
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(entries)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update({e["id"]: e for e in entries})

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="accrual")
            total_rev = pl["revenue"]["total_paise"]
            assert total_rev == 10000000, f"Accrual revenue with partial receipt must be 10000000, got {total_rev}"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)


# ─── Expense tests ─────────────────────────────────────────────────────────────

class TestCashBasisExpense:

    def test_unpaid_bill_accrual_shows_full_expense(self, fresh_service):
        """Accrual: bill alone shows full expense."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(BILL_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-bill"] = BILL_ENTRY

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="accrual")
            total_exp = pl["operating_expenses"]["total_paise"]
            assert total_exp == 5000000, f"Expected 5000000, got {total_exp}"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_unpaid_bill_cash_shows_zero_expense(self, fresh_service):
        """Cash: unpaid bill → cash expense = 0 (no cash paid)."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(BILL_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-bill"] = BILL_ENTRY

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="cash")
            total_exp = pl["operating_expenses"]["total_paise"]
            assert total_exp == 0, f"Unpaid bill: cash expense must be 0, got {total_exp}"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_fully_paid_bill_cash_shows_full_expense(self, fresh_service):
        """Cash: bill + full payment → cash expense = bill amount."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            entries = [BILL_ENTRY, FULL_PAYMENT_ENTRY]
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(entries)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update({e["id"]: e for e in entries})

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="cash")
            total_exp = pl["operating_expenses"]["total_paise"]
            assert total_exp == 5000000, f"Full payment: cash expense must be 5000000, got {total_exp}"
            assert isinstance(total_exp, int), "Expense must be integer paise"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_partially_paid_bill_cash_shows_paid_amount(self, fresh_service):
        """Cash: bill ₹50,000 + payment ₹20,000 → cash expense = 2000000 paise."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            entries = [BILL_ENTRY, PARTIAL_PAYMENT_ENTRY]
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(entries)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update({e["id"]: e for e in entries})

            svc = AccountingService()
            pl = svc.get_profit_loss(start_date=_FY_START, end_date=_FY_END, basis="cash")
            total_exp = pl["operating_expenses"]["total_paise"]
            # 2000000/5000000 = 40% of 5000000 = 2000000 paise
            assert total_exp == 2000000, f"Partial payment: cash expense must be 2000000, got {total_exp}"
            assert isinstance(total_exp, int), "Expense must be integer paise"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)


# ─── Balance Sheet tests ───────────────────────────────────────────────────────

class TestCashBasisBalanceSheet:

    def test_accrual_bs_includes_ar(self, fresh_service):
        """Accrual: unpaid invoice creates A/R on balance sheet."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(INVOICE_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-inv"] = INVOICE_ENTRY

            svc = AccountingService()
            bs = svc.get_balance_sheet(basis="accrual")
            asset_lines = bs["assets"][0]["lines"]
            ar_line = next((l for l in asset_lines if "Receivable" in l["account_name"]), None)
            assert ar_line is not None, "Accrual BS must include Trade Receivables"
            assert ar_line["balance_paise"] == 10000000
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_cash_bs_excludes_unpaid_ar(self, fresh_service):
        """Cash BS: unpaid invoice → Trade Receivables not on balance sheet."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(INVOICE_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-inv"] = INVOICE_ENTRY

            svc = AccountingService()
            bs = svc.get_balance_sheet(basis="cash")
            asset_lines = bs["assets"][0]["lines"]
            ar_line = next((l for l in asset_lines if "Receivable" in l["account_name"]), None)
            assert ar_line is None, "Cash BS must NOT include Trade Receivables for unpaid invoice"
            assert bs["is_balanced"], "Cash BS must balance even with no AR"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_accrual_bs_includes_ap(self, fresh_service):
        """Accrual: unpaid bill creates A/P on balance sheet."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(BILL_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-bill"] = BILL_ENTRY

            svc = AccountingService()
            bs = svc.get_balance_sheet(basis="accrual")
            liab_lines = bs["liabilities"][0]["lines"]
            ap_line = next((l for l in liab_lines if "Payable" in l["account_name"]), None)
            assert ap_line is not None, "Accrual BS must include Trade Payables"
            assert ap_line["balance_paise"] == 5000000
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_cash_bs_excludes_unpaid_ap(self, fresh_service):
        """Cash BS: unpaid bill → Trade Payables not on balance sheet."""
        import domain.accounting_service as m
        orig = m.MOCK_JOURNAL_ENTRIES[:]
        orig_idx = dict(m.JOURNAL_INDEX)
        try:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.append(BILL_ENTRY)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX["je-test-bill"] = BILL_ENTRY

            svc = AccountingService()
            bs = svc.get_balance_sheet(basis="cash")
            liab_lines = bs["liabilities"][0]["lines"]
            ap_line = next((l for l in liab_lines if "Payable" in l["account_name"]), None)
            assert ap_line is None, "Cash BS must NOT include Trade Payables for unpaid bill"
            assert bs["is_balanced"], "Cash BS must balance even with no AP"
        finally:
            m.MOCK_JOURNAL_ENTRIES.clear()
            m.MOCK_JOURNAL_ENTRIES.extend(orig)
            m.JOURNAL_INDEX.clear()
            m.JOURNAL_INDEX.update(orig_idx)

    def test_cash_bs_is_balanced(self, fresh_service):
        """Cash basis balance sheet always balances (Assets = Liabilities + Equity)."""
        svc = AccountingService()
        bs = svc.get_balance_sheet(basis="cash")
        assert bs["is_balanced"], (
            f"Cash BS must balance. Assets={bs['total_assets_paise']}, "
            f"Liab+Equity={bs['total_liabilities_equity_paise']}"
        )

    def test_cash_bs_totals_are_integers(self, fresh_service):
        """All cash BS totals must be integer paise — no floats."""
        svc = AccountingService()
        bs = svc.get_balance_sheet(basis="cash")
        assert isinstance(bs["total_assets_paise"], int)
        assert isinstance(bs["total_liabilities_equity_paise"], int)


# ─── Trial Balance tests ───────────────────────────────────────────────────────

class TestCashBasisTrialBalance:

    def test_cash_tb_is_balanced(self, fresh_service):
        """Cash basis TB must balance (total debit = total credit)."""
        svc = AccountingService()
        tb = svc.get_trial_balance(basis="cash")
        assert tb["is_balanced"], (
            f"Cash TB must balance. Dr={tb['total_debit_paise']}, "
            f"Cr={tb['total_credit_paise']}, diff={tb['difference_paise']}"
        )

    def test_cash_tb_excludes_ar_account(self, fresh_service):
        """Cash TB has no net balance in Trade Receivables (A/R is transformed away)."""
        svc = AccountingService()
        tb = svc.get_trial_balance(basis="cash")
        for line in tb["lines"]:
            if line["account_id"] == "acc-003":
                net = line["total_debit_paise"] - line["total_credit_paise"]
                assert net == 0, f"Cash TB: A/R net balance must be 0, got {net}"

    def test_cash_tb_totals_are_integers(self, fresh_service):
        """All cash TB totals are integer paise."""
        svc = AccountingService()
        tb = svc.get_trial_balance(basis="cash")
        assert isinstance(tb["total_debit_paise"], int)
        assert isinstance(tb["total_credit_paise"], int)
        for line in tb["lines"]:
            assert isinstance(line["total_debit_paise"], int)
            assert isinstance(line["total_credit_paise"], int)


# ─── Regression: accrual output unchanged ─────────────────────────────────────

class TestCashBasisRegression:
    """
    When basis=accrual, output must be identical to the original default behavior.
    This verifies no regression was introduced by the basis parameter.
    """

    def test_trial_balance_accrual_regression(self, fresh_service):
        """basis=accrual TB matches default TB (no basis param)."""
        svc = AccountingService()
        tb_default = svc.get_trial_balance()
        tb_accrual = svc.get_trial_balance(basis="accrual")
        assert tb_default["total_debit_paise"] == tb_accrual["total_debit_paise"]
        assert tb_default["total_credit_paise"] == tb_accrual["total_credit_paise"]
        assert tb_default["is_balanced"] == tb_accrual["is_balanced"]
        assert len(tb_default["lines"]) == len(tb_accrual["lines"])

    def test_profit_loss_accrual_regression(self, fresh_service):
        """basis=accrual P&L matches default P&L (no basis param)."""
        svc = AccountingService()
        pl_default = svc.get_profit_loss()
        pl_accrual = svc.get_profit_loss(basis="accrual")
        assert pl_default["revenue"]["total_paise"] == pl_accrual["revenue"]["total_paise"]
        assert pl_default["operating_expenses"]["total_paise"] == pl_accrual["operating_expenses"]["total_paise"]
        assert pl_default["net_profit_paise"] == pl_accrual["net_profit_paise"]

    def test_balance_sheet_accrual_regression(self, fresh_service):
        """basis=accrual BS matches default BS (no basis param)."""
        svc = AccountingService()
        bs_default = svc.get_balance_sheet()
        bs_accrual = svc.get_balance_sheet(basis="accrual")
        assert bs_default["total_assets_paise"] == bs_accrual["total_assets_paise"]
        assert bs_default["total_liabilities_equity_paise"] == bs_accrual["total_liabilities_equity_paise"]
        assert bs_default["is_balanced"] == bs_accrual["is_balanced"]

    def test_accrual_tb_is_balanced(self, fresh_service):
        """Accrual TB must remain balanced after adding cash-basis code."""
        svc = AccountingService()
        tb = svc.get_trial_balance(basis="accrual")
        assert tb["is_balanced"], f"Accrual TB must balance. diff={tb['difference_paise']}"

    def test_cash_pl_less_than_or_equal_accrual_revenue(self, fresh_service):
        """Cash revenue ≤ accrual revenue (collected ≤ earned)."""
        svc = AccountingService()
        pl_accrual = svc.get_profit_loss(basis="accrual")
        pl_cash = svc.get_profit_loss(basis="cash")
        assert pl_cash["revenue"]["total_paise"] <= pl_accrual["revenue"]["total_paise"], (
            f"Cash revenue ({pl_cash['revenue']['total_paise']}) must not exceed "
            f"accrual revenue ({pl_accrual['revenue']['total_paise']})"
        )

    def test_cash_pl_expenses_less_than_or_equal_accrual(self, fresh_service):
        """Cash expenses ≤ accrual expenses (paid ≤ incurred)."""
        svc = AccountingService()
        pl_accrual = svc.get_profit_loss(basis="accrual")
        pl_cash = svc.get_profit_loss(basis="cash")
        assert pl_cash["operating_expenses"]["total_paise"] <= pl_accrual["operating_expenses"]["total_paise"], (
            f"Cash expenses ({pl_cash['operating_expenses']['total_paise']}) must not exceed "
            f"accrual expenses ({pl_accrual['operating_expenses']['total_paise']})"
        )

    def test_cash_basis_marker_in_response(self, fresh_service):
        """Cash basis responses include basis='cash' marker."""
        svc = AccountingService()
        tb = svc.get_trial_balance(basis="cash")
        pl = svc.get_profit_loss(basis="cash")
        bs = svc.get_balance_sheet(basis="cash")
        assert tb.get("basis") == "cash"
        assert pl.get("basis") == "cash"
        assert bs.get("basis") == "cash"

    def test_accrual_basis_has_no_cash_marker(self, fresh_service):
        """Accrual responses do not have basis='cash' (avoiding confusion)."""
        svc = AccountingService()
        tb = svc.get_trial_balance(basis="accrual")
        assert tb.get("basis") != "cash"
