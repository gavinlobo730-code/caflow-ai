"""
Schedule III presentation grouping moved to the backend (Companies Act 2013,
Section 129 read with Schedule III, Division I). Verifies the statutory
line-caption classification and the section subtotals / PBT / PAT so the format
is a single, tested source of truth (not React business logic).
"""
from domain.reporting.schedule_iii import bs_bucket, pl_bucket, build_schedule_iii


# ── Classification (Schedule III, Part I — Balance Sheet) ─────────────────────
def test_bs_bucket_equity_split():
    assert bs_bucket("Equity", "Share Capital") == "Share Capital"
    assert bs_bucket("Equity", "Equity Share Capital") == "Share Capital"
    assert bs_bucket("Equity", "Reserves & Surplus") == "Reserves & Surplus"
    assert bs_bucket("Equity", None) == "Reserves & Surplus"


def test_bs_bucket_liabilities():
    assert bs_bucket("Liability", "Long Term Borrowings") == "Long Term Borrowings"
    assert bs_bucket("Liability", "Term Loan from Bank") == "Long Term Borrowings"
    assert bs_bucket("Liability", "Deferred Tax Liability") == "Deferred Tax Liability"
    assert bs_bucket("Liability", "Trade Payables") == "Trade Payables"
    assert bs_bucket("Liability", "Sundry Creditors") == "Trade Payables"
    assert bs_bucket("Liability", "Bank Overdraft") == "Short Term Borrowings"
    assert bs_bucket("Liability", "GST Payable") == "Other Current Liabilities"


def test_bs_bucket_assets():
    assert bs_bucket("Asset", "Plant & Machinery") == "Tangible Fixed Assets"
    assert bs_bucket("Asset", "Goodwill") == "Intangible Fixed Assets"
    assert bs_bucket("Asset", "Long Term Investment") == "Long Term Investments"
    assert bs_bucket("Asset", "Inventory / Stock") == "Inventories"
    assert bs_bucket("Asset", "Trade Receivables") == "Trade Receivables"
    assert bs_bucket("Asset", "Sundry Debtors") == "Trade Receivables"
    assert bs_bucket("Asset", "Bank Account") == "Cash & Cash Equivalents"
    assert bs_bucket("Asset", "Advance to Suppliers") == "Short Term Loans & Advances"
    assert bs_bucket("Asset", "Prepaid Expenses") == "Other Current Assets"


def test_bs_bucket_non_bs_returns_none():
    assert bs_bucket("Revenue", "Sales") is None
    assert bs_bucket("Expense", "Rent") is None


# ── Classification (Schedule III, Part II — Statement of P&L) ─────────────────
def test_pl_bucket_revenue_and_expense():
    assert pl_bucket("Revenue", "Sales of Services") == "Revenue from Operations"
    assert pl_bucket("Revenue", "Interest Income") == "Other Income"
    assert pl_bucket("Expense", "Raw Material Purchase") == "Cost of Materials Consumed"
    assert pl_bucket("Expense", "Employee Salaries") == "Employee Benefit Expense"
    assert pl_bucket("Expense", "Bank Charges") == "Finance Costs"
    assert pl_bucket("Expense", "Depreciation") == "Depreciation & Amortisation"
    assert pl_bucket("Expense", "Income Tax") == "Tax Expense"
    assert pl_bucket("Expense", "Office Rent") == "Other Expenses"
    assert pl_bucket("Asset", "Cash") is None


# ── End-to-end grouping over authoritative engine output ──────────────────────
def _pl():
    # amount_paise: income credit-positive, expense debit-positive (engine convention)
    return {
        "revenue": {"lines": [
            {"account_name": "Sales", "account_type": "Revenue", "account_subtype": "Operating Revenue", "amount_paise": 10_00_000_00},
            {"account_name": "Interest", "account_type": "Revenue", "account_subtype": "Interest Income", "amount_paise": 50_000_00},
        ], "total_paise": 10_50_000_00},
        "operating_expenses": {"lines": [
            {"account_name": "Purchases", "account_type": "Expense", "account_subtype": "Raw Material", "amount_paise": 4_00_000_00},
            {"account_name": "Salaries", "account_type": "Expense", "account_subtype": "Employee Cost", "amount_paise": 2_00_000_00},
            {"account_name": "Income Tax", "account_type": "Expense", "account_subtype": "Income Tax", "amount_paise": 1_00_000_00},
        ], "total_paise": 7_00_000_00},
        "net_profit_paise": 3_50_000_00,
    }


def _bs():
    return {
        "assets": [{"label": "Assets", "lines": [
            {"account_name": "Machinery", "account_type": "Asset", "account_subtype": "Plant & Machinery", "balance_paise": 5_00_000_00},
            {"account_name": "Debtors", "account_type": "Asset", "account_subtype": "Trade Receivables", "balance_paise": 3_00_000_00},
            {"account_name": "Bank", "account_type": "Asset", "account_subtype": "Bank", "balance_paise": 2_00_000_00},
        ], "total_paise": 10_00_000_00}],
        "liabilities": [{"label": "Liabilities", "lines": [
            {"account_name": "Creditors", "account_type": "Liability", "account_subtype": "Trade Payables", "balance_paise": 2_50_000_00},
        ], "total_paise": 2_50_000_00}],
        "equity": [{"label": "Equity", "lines": [
            {"account_name": "Capital", "account_type": "Equity", "account_subtype": "Share Capital", "balance_paise": 4_00_000_00},
            {"account_name": "Retained Earnings / Net Profit", "account_type": "Equity", "account_subtype": "Reserves & Surplus", "balance_paise": 3_50_000_00},
        ], "total_paise": 7_50_000_00}],
    }


def test_build_schedule_iii_groups_and_subtotals():
    out = build_schedule_iii(_pl(), _bs(), "2025-04-01", "2026-03-31")

    pl = out["profit_and_loss"]
    assert pl["total_revenue_paise"] == 10_50_000_00
    # Total Expenses (II) excludes tax; tax shown below the line
    assert pl["total_expenses_paise"] == 6_00_000_00
    assert pl["tax_expense_paise"] == 1_00_000_00
    assert pl["profit_before_tax_paise"] == 4_50_000_00      # 10.5L - 6L
    assert pl["profit_after_tax_paise"] == 3_50_000_00       # PBT - tax == engine net profit

    bs = out["balance_sheet"]
    assert bs["total_assets_paise"] == 10_00_000_00
    assert bs["total_equity_liabilities_paise"] == 10_00_000_00
    assert bs["is_balanced"] is True


def test_build_schedule_iii_caption_amounts():
    out = build_schedule_iii(_pl(), _bs(), "2025-04-01", "2026-03-31")

    # Balance Sheet captions carry the right grouped amounts
    caps = {}
    for sec in out["balance_sheet"]["assets"] + out["balance_sheet"]["equity_and_liabilities"]:
        for ln in sec["lines"]:
            caps[ln["label"]] = ln["paise"]
    assert caps["Fixed Assets — Tangible"] == 5_00_000_00
    assert caps["Trade Receivables"] == 3_00_000_00
    assert caps["Cash & Cash Equivalents"] == 2_00_000_00
    assert caps["Trade Payables"] == 2_50_000_00
    assert caps["Share Capital"] == 4_00_000_00
    assert caps["Reserves & Surplus"] == 3_50_000_00

    # P&L captions
    pcaps = {}
    for sec in out["profit_and_loss"]["revenue"] + out["profit_and_loss"]["expenses"]:
        for ln in sec["lines"]:
            pcaps[ln["label"]] = ln["paise"]
    assert pcaps["Revenue from Operations"] == 10_00_000_00
    assert pcaps["Other Income"] == 50_000_00
    assert pcaps["Cost of Materials Consumed"] == 4_00_000_00
    assert pcaps["Employee Benefit Expense"] == 2_00_000_00


def test_build_schedule_iii_loss_is_negative():
    pl = {
        "revenue": {"lines": [
            {"account_name": "Sales", "account_type": "Revenue", "account_subtype": "Sales", "amount_paise": 1_00_000_00},
        ], "total_paise": 1_00_000_00},
        "operating_expenses": {"lines": [
            {"account_name": "Rent", "account_type": "Expense", "account_subtype": "Rent", "amount_paise": 1_50_000_00},
        ], "total_paise": 1_50_000_00},
        "net_profit_paise": -50_000_00,
    }
    out = build_schedule_iii(pl, {"assets": [], "liabilities": [], "equity": []}, "2025-04-01", "2026-03-31")
    assert out["profit_and_loss"]["profit_before_tax_paise"] == -50_000_00
    assert out["profit_and_loss"]["profit_after_tax_paise"] == -50_000_00
    assert out["balance_sheet"]["total_assets_paise"] == 0


def test_build_schedule_iii_includes_cost_of_sales():
    # Regression pin: builders.profit_loss() (domain/reporting/builders.py) keeps
    # Cost of Goods Sold in its OWN "cost_of_sales" section, separate from
    # "operating_expenses" (so gross profit can be computed there) — every
    # _pl() fixture above instead put COGS-like lines directly inside
    # "operating_expenses", which is NOT the real engine's shape and let
    # build_schedule_iii() silently never read "cost_of_sales" at all. That
    # dropped COGS from both "Cost of Materials Consumed" and the Total
    # Expenses / Profit figures on every real Schedule III P&L — caught by
    # comparing the reported P&L against real ledger data (task, 2026-07-24).
    pl = {
        "revenue": {"lines": [
            {"account_name": "Sales", "account_type": "Revenue", "account_subtype": "Operating Revenue", "amount_paise": 10_00_000_00},
        ], "total_paise": 10_00_000_00},
        "cost_of_sales": {"lines": [
            {"account_name": "Cost of Goods Sold", "account_type": "Expense", "account_subtype": "Cost of Goods Sold", "amount_paise": 6_00_000_00},
        ], "total_paise": 6_00_000_00},
        "operating_expenses": {"lines": [
            {"account_name": "Purchases", "account_type": "Expense", "account_subtype": "Purchases", "amount_paise": 1_00},  # near-zero: capitalised into Inventory
            {"account_name": "Salaries", "account_type": "Expense", "account_subtype": "Employee Cost", "amount_paise": 1_00_000_00},
        ], "total_paise": 1_00_100},
        "gross_profit_paise": 4_00_000_00,
        "net_profit_paise": 2_99_999_00,
    }
    out = build_schedule_iii(pl, {"assets": [], "liabilities": [], "equity": []}, "2025-04-01", "2026-03-31")
    pl_out = out["profit_and_loss"]

    caps = {ln["label"]: ln["paise"] for sec in pl_out["expenses"] for ln in sec["lines"]}
    # Cost of Goods Sold and the near-zero Purchases balance both bucket into
    # the same statutory caption — Schedule III has one "Cost of Materials
    # Consumed" line, not a separate one per underlying GL account.
    assert caps["Cost of Materials Consumed"] == 6_00_000_00 + 1_00

    # Total Expenses (II) and Profit must reconcile against Total Revenue (I)
    # exactly as displayed — this is the actual bug symptom: a CA reading the
    # statement could add up Revenue minus the shown Expenses lines and get a
    # different number than "Profit for the Period".
    assert pl_out["total_expenses_paise"] == caps["Cost of Materials Consumed"] + 1_00_000_00
    assert pl_out["total_revenue_paise"] - pl_out["total_expenses_paise"] == pl_out["profit_before_tax_paise"]
    assert pl_out["profit_before_tax_paise"] == 2_99_999_00
