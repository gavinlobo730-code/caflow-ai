"""
Schedule III presentation grouping for the Balance Sheet and Statement of
Profit & Loss.

Companies Act 2013, Section 129 read with Schedule III (Division I) prescribes
the *form* in which a company's financial statements are presented — the
statutory line captions ("Trade Receivables", "Reserves & Surplus", "Finance
Costs", …) and their ordering. The monetary amounts themselves are the
authoritative, already-classified and sign-normalised line balances produced by
the reporting engine (builders.profit_loss / builders.balance_sheet). This
module only *groups* those amounts under the statutory captions and computes the
section subtotals.

Kept in the backend (not the React UI) so the statutory format is a single
source of truth and unit-tested — CLAUDE.md: zero business logic in the frontend.
All amounts are integer paise.
"""
from __future__ import annotations


# ── Balance Sheet grouping — Companies Act 2013, Schedule III, Part I ──────────
def bs_bucket(account_type: str, account_subtype: str | None) -> str | None:
    """Map an account's structured (type, subtype) to a Schedule III Balance
    Sheet caption. Returns None for accounts that do not belong on the Balance
    Sheet (e.g. Revenue/Expense)."""
    sub = (account_subtype or "").lower()
    typ = (account_type or "").lower()

    if typ == "equity":
        # "Share Capital" vs "Reserves & Surplus" (Schedule III, Part I, EQ&L)
        if "share capital" in sub or "capital" in sub:
            return "Share Capital"
        return "Reserves & Surplus"
    if typ == "liability":
        if "deferred tax" in sub:
            return "Deferred Tax Liability"
        # Bare "payable" included: the seeded vocabulary (coa_seed_service /
        # migration 197) tags Trade Payables with subtype "Payable" — without
        # it, Trade Payables showed ₹0 on the backend Schedule III while the
        # frontend statement (looser keywords) showed it correctly. Statutory-
        # dues subtypes ("GST Payable", "TDS Payable", …) are excluded so they
        # keep falling through to Other Current Liabilities; the seeded ones
        # carry "Current Liability" and never matched anyway.
        if "trade payable" in sub or "creditor" in sub:
            return "Trade Payables"
        if "payable" in sub and not any(
            k in sub for k in ("gst", "tds", "tax", "duty", "pf", "esi", "salary", "wage", "statutory")
        ):
            return "Trade Payables"
        # Short-term FIRST: the seeded subtype "Short Term Loan" contains
        # "term loan", so testing the long-term branch first presented every
        # working-capital loan as a non-current borrowing.
        if "short term" in sub or "overdraft" in sub or "cc limit" in sub:
            return "Short Term Borrowings"
        if "long term" in sub or "term loan" in sub or "debenture" in sub:
            return "Long Term Borrowings"
        return "Other Current Liabilities"
    if typ == "asset":
        # Intangibles FIRST — their subtype ("Intangible Asset") also
        # contains "asset"-family keywords the tangible test matches.
        if "intangible" in sub or "goodwill" in sub or "software" in sub:
            return "Intangible Fixed Assets"
        if any(k in sub for k in (
            "fixed asset", "tangible", "plant", "machinery", "furniture", "building", "vehicle",
        )):
            return "Tangible Fixed Assets"
        if "long term investment" in sub or "investment" in sub:
            return "Long Term Investments"
        if "inventor" in sub or "stock" in sub:
            return "Inventories"
        # Bare "receivable": the seeded subtype is "Receivable" (TDS
        # Receivable / Advance Tax carry "Tax", so they don't over-match).
        if "trade receivable" in sub or "debtor" in sub or "receivable" in sub:
            return "Trade Receivables"
        if "cash" in sub or "bank" in sub:
            return "Cash & Cash Equivalents"
        if "short term loan" in sub or "advance" in sub:
            return "Short Term Loans & Advances"
        return "Other Current Assets"
    return None


# ── Statement of P&L grouping — Companies Act 2013, Schedule III, Part II ──────
def pl_bucket(account_type: str, account_subtype: str | None) -> str | None:
    """Map an account's structured (type, subtype) to a Schedule III P&L caption.
    Returns None for non-P&L accounts."""
    sub = (account_subtype or "").lower()
    typ = (account_type or "").lower()

    if typ == "revenue":
        if "other income" in sub or "interest income" in sub or "dividend" in sub:
            return "Other Income"
        return "Revenue from Operations"
    if typ == "expense":
        if "material" in sub or "cost of goods" in sub or "purchase" in sub or "raw material" in sub:
            return "Cost of Materials"
        if "employee" in sub or "salary" in sub or "wages" in sub or "staff" in sub:
            return "Employee Benefit Expense"
        if "finance" in sub or "interest expense" in sub or "bank charge" in sub:
            return "Finance Costs"
        if "depreciation" in sub or "amortisation" in sub or "amortization" in sub:
            return "Depreciation & Amortisation"
        if "tax" in sub or "income tax" in sub or "deferred tax" in sub:
            return "Tax Expense"
        return "Other Expenses"
    return None


def _line(label: str, paise: int, indent: bool = True) -> dict:
    return {"label": label, "paise": paise, "indent": indent}


def _section(heading: str, lines: list[dict], total_paise: int, total_label: str) -> dict:
    return {"heading": heading, "lines": lines, "total_paise": total_paise, "total_label": total_label}


def build_schedule_iii(pl: dict, bs: dict, fy_start: str, fy_end: str) -> dict:
    """Group the authoritative P&L and Balance Sheet line amounts into the
    Companies Act 2013 Schedule III format with section subtotals.

    `pl` is a builders.profit_loss() dict (revenue/operating_expenses sections
    with `amount_paise` lines); `bs` is a builders.balance_sheet() dict
    (assets/liabilities/equity sections with `balance_paise` lines). Both carry
    `account_type`/`account_subtype` presentation hints on each line.
    """
    # ── Bucket the authoritative amounts under statutory captions ─────────────
    bs_buckets: dict[str, int] = {}
    for section in (*bs.get("assets", []), *bs.get("liabilities", []), *bs.get("equity", [])):
        for ln in section.get("lines", []):
            cap = bs_bucket(ln.get("account_type", ""), ln.get("account_subtype"))
            if cap:
                bs_buckets[cap] = bs_buckets.get(cap, 0) + ln.get("balance_paise", 0)

    pl_buckets: dict[str, int] = {}
    # builders.profit_loss() keeps Cost of Goods Sold in its OWN "cost_of_sales"
    # section (separate from "operating_expenses", so gross profit can be
    # computed) — omitting it here silently dropped COGS from every Schedule III
    # P&L entirely: "Cost of Materials Consumed" showed only the (near-zero, once
    # goods purchases are reclassified into Inventory) "Purchases" balance, and
    # "Total Expenses (II)" / "Profit for the Period" no longer reconciled
    # against the displayed Revenue and Expense lines.
    for group in ("revenue", "operating_expenses", "cost_of_sales"):
        for ln in pl.get(group, {}).get("lines", []):
            cap = pl_bucket(ln.get("account_type", ""), ln.get("account_subtype"))
            if cap:
                pl_buckets[cap] = pl_buckets.get(cap, 0) + ln.get("amount_paise", 0)

    def gb(k: str) -> int:
        return bs_buckets.get(k, 0)

    def gp(k: str) -> int:
        return pl_buckets.get(k, 0)

    # ── Balance Sheet: Equity & Liabilities ──────────────────────────────────
    share_cap, reserves = gb("Share Capital"), gb("Reserves & Surplus")
    shareholders_funds = share_cap + reserves
    ltb, dtl = gb("Long Term Borrowings"), gb("Deferred Tax Liability")
    non_current_liab = ltb + dtl
    stb, tp, ocl = gb("Short Term Borrowings"), gb("Trade Payables"), gb("Other Current Liabilities")
    current_liab = stb + tp + ocl
    total_equity_liab = shareholders_funds + non_current_liab + current_liab

    equity_and_liabilities = [
        _section("I. Shareholders' Funds", [
            _line("Share Capital", share_cap),
            _line("Reserves & Surplus", reserves),
        ], shareholders_funds, "Total Shareholders' Funds"),
        _section("II. Non-Current Liabilities", [
            _line("Long Term Borrowings", ltb),
            _line("Deferred Tax Liability", dtl),
        ], non_current_liab, "Total Non-Current Liabilities"),
        _section("III. Current Liabilities", [
            _line("Short Term Borrowings", stb),
            _line("Trade Payables", tp),
            _line("Other Current Liabilities", ocl),
        ], current_liab, "Total Current Liabilities"),
    ]

    # ── Balance Sheet: Assets ────────────────────────────────────────────────
    tangible, intangible, lt_inv = gb("Tangible Fixed Assets"), gb("Intangible Fixed Assets"), gb("Long Term Investments")
    non_current_assets = tangible + intangible + lt_inv
    inv, tr, cash = gb("Inventories"), gb("Trade Receivables"), gb("Cash & Cash Equivalents")
    stla, oca = gb("Short Term Loans & Advances"), gb("Other Current Assets")
    current_assets = inv + tr + cash + stla + oca
    total_assets = non_current_assets + current_assets

    assets = [
        _section("I. Non-Current Assets", [
            _line("Fixed Assets — Tangible", tangible),
            _line("Fixed Assets — Intangible", intangible),
            _line("Long Term Investments", lt_inv),
        ], non_current_assets, "Total Non-Current Assets"),
        _section("II. Current Assets", [
            _line("Inventories", inv),
            _line("Trade Receivables", tr),
            _line("Cash & Cash Equivalents", cash),
            _line("Short Term Loans & Advances", stla),
            _line("Other Current Assets", oca),
        ], current_assets, "Total Current Assets"),
    ]

    # ── Statement of Profit & Loss ───────────────────────────────────────────
    rev_ops, other_income = gp("Revenue from Operations"), gp("Other Income")
    total_revenue = rev_ops + other_income

    materials = gp("Cost of Materials")
    emp = gp("Employee Benefit Expense")
    finance = gp("Finance Costs")
    depr = gp("Depreciation & Amortisation")
    other_exp = gp("Other Expenses")
    tax_exp = gp("Tax Expense")  # shown below the line, not in "Total Expenses (II)"
    operating_expenses = materials + emp + finance + depr + other_exp
    profit_before_tax = total_revenue - operating_expenses
    profit_after_tax = profit_before_tax - tax_exp

    revenue = [
        _section("I. Revenue", [
            _line("Revenue from Operations", rev_ops),
            _line("Other Income", other_income),
        ], total_revenue, "Total Revenue (I)"),
    ]
    expenses = [
        _section("II. Expenses", [
            _line("Cost of Materials Consumed", materials),
            _line("Employee Benefit Expense", emp),
            _line("Finance Costs", finance),
            _line("Depreciation & Amortisation Expense", depr),
            _line("Other Expenses", other_exp),
        ], operating_expenses, "Total Expenses (II)"),
    ]

    return {
        "period": {"fy_start": fy_start, "fy_end": fy_end},
        "balance_sheet": {
            "equity_and_liabilities": equity_and_liabilities,
            "assets": assets,
            "total_equity_liabilities_paise": total_equity_liab,
            "total_assets_paise": total_assets,
            "is_balanced": total_assets == total_equity_liab,
        },
        "profit_and_loss": {
            "revenue": revenue,
            "expenses": expenses,
            "total_revenue_paise": total_revenue,
            "total_expenses_paise": operating_expenses,
            "profit_before_tax_paise": profit_before_tax,
            "tax_expense_paise": tax_exp,
            "profit_after_tax_paise": profit_after_tax,
        },
    }
