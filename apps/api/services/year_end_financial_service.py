"""
Year End Financial Statements Service — Schedule III engine.
Generates Balance Sheet and Profit & Loss per Companies Act 2013, Schedule III.

All values in integer paise (BIGINT). Never float.
Balance Sheet must balance: total_assets == total_equity_and_liabilities.
Reference: Companies Act 2013, Schedule III, Part I (Balance Sheet) and Part II (P&L).
"""
import hashlib
import json
import os
from typing import Dict, Any

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Schedule III line codes ───────────────────────────────────────────────────
# Companies Act 2013, Schedule III, Part I — Balance Sheet

BS_EQUITY_LIABILITY_LINES = [
    "share_capital",
    "reserves_and_surplus",
    "long_term_borrowings",
    "deferred_tax_liabilities",
    "other_long_term_liabilities",
    "long_term_provisions",
    "short_term_borrowings",
    "trade_payables",
    "other_current_liabilities",
    "short_term_provisions",
]

BS_ASSET_LINES = [
    "tangible_assets",
    "intangible_assets",
    "capital_wip",
    "long_term_investments",
    "deferred_tax_assets",
    "long_term_loans_and_advances",
    "other_non_current_assets",
    "current_investments",
    "inventories",
    "trade_receivables",
    "cash_and_bank",
    "short_term_loans_and_advances",
    "other_current_assets",
]

# Companies Act 2013, Schedule III, Part II — Statement of Profit & Loss
PL_INCOME_LINES = [
    "revenue_from_operations",
    "other_income",
]

PL_EXPENSE_LINES = [
    "cost_of_materials_consumed",
    "purchases_of_stock_in_trade",
    "changes_in_inventories",
    "employee_benefit_expense",
    "finance_costs",
    "depreciation_and_amortisation",
    "other_expenses",
]

# Schedule III, Part II, item VII: "Tax expense: (1) Current tax
# (2) Deferred tax" is its own item, struck AFTER profit before tax — not one
# of the expenses that produce it. These lines are therefore deliberately NOT
# in PL_EXPENSE_LINES: including them would subtract the tax charge twice,
# once inside PBT and once from it.
PL_TAX_LINES = [
    "current_tax",
    "deferred_tax",
]

# Account types that behave as credit-normal (liabilities, income, equity)
# For assets/expenses: balance = SUM(debit_paise) - SUM(credit_paise)
# For liabilities/income/equity: balance = SUM(credit_paise) - SUM(debit_paise)
_CREDIT_NORMAL_LINES = set(BS_EQUITY_LIABILITY_LINES) | set(PL_INCOME_LINES)


def _mock_statements(client_id: str, firm_id: str, fy_start: str, fy_end: str) -> Dict[str, Any]:
    """
    Return representative mock Schedule III data for dev/test.
    All values in integer paise. Never float.
    """
    balance_sheet = {
        "equity_and_liabilities": {
            line: 0 for line in BS_EQUITY_LIABILITY_LINES
        },
        "assets": {
            line: 0 for line in BS_ASSET_LINES
        },
    }
    profit_loss = {
        "income": {line: 0 for line in PL_INCOME_LINES},
        "expenses": {line: 0 for line in PL_EXPENSE_LINES},
        "profit_before_tax_paise": 0,
        "tax_expense_paise": 0,
        "profit_after_tax_paise": 0,
    }

    # Inject representative mock values (integer paise)
    balance_sheet["equity_and_liabilities"]["share_capital"]         = 100_000_00  # 1,00,000 rupees in paise
    balance_sheet["equity_and_liabilities"]["reserves_and_surplus"]  = 50_000_00
    balance_sheet["equity_and_liabilities"]["trade_payables"]        = 25_000_00
    balance_sheet["equity_and_liabilities"]["short_term_borrowings"] = 30_000_00
    balance_sheet["equity_and_liabilities"]["other_current_liabilities"] = 5_000_00

    balance_sheet["assets"]["tangible_assets"]         = 80_000_00
    balance_sheet["assets"]["trade_receivables"]       = 60_000_00
    balance_sheet["assets"]["cash_and_bank"]           = 50_000_00
    balance_sheet["assets"]["inventories"]             = 20_000_00

    profit_loss["income"]["revenue_from_operations"] = 200_000_00
    profit_loss["income"]["other_income"]            = 5_000_00
    profit_loss["expenses"]["employee_benefit_expense"]      = 80_000_00
    profit_loss["expenses"]["other_expenses"]                = 50_000_00
    profit_loss["expenses"]["depreciation_and_amortisation"] = 10_000_00
    profit_loss["expenses"]["finance_costs"]                 = 3_000_00

    total_income   = sum(profit_loss["income"].values())
    total_expenses = sum(profit_loss["expenses"].values())
    pbt  = total_income - total_expenses
    # Mock mode mirrors the real path: the charge is whatever is provided for,
    # and nothing is provided for here. See the long note in
    # generate_financial_statements — a flat percentage of book profit is not
    # a tax computation under any Indian rate.
    tax  = 0
    pat  = pbt - tax

    profit_loss["profit_before_tax_paise"] = pbt
    profit_loss["tax_expense_paise"]       = tax
    profit_loss["profit_after_tax_paise"]  = pat

    # Add PAT to reserves to make BS balance
    balance_sheet["equity_and_liabilities"]["reserves_and_surplus"] += pat

    # Compute totals (all integer paise)
    total_equity_liabilities = sum(balance_sheet["equity_and_liabilities"].values())
    total_assets             = sum(balance_sheet["assets"].values())

    # Build trial balance for hashing
    raw_balances = {
        **{f"el_{k}": v for k, v in balance_sheet["equity_and_liabilities"].items()},
        **{f"a_{k}": v  for k, v in balance_sheet["assets"].items()},
    }

    return {
        "balance_sheet": {
            **balance_sheet,
            "total_equity_and_liabilities_paise": total_equity_liabilities,
            "total_assets_paise":                 total_assets,
            "is_balanced":                        total_equity_liabilities == total_assets,
        },
        "profit_loss":          profit_loss,
        "trial_balance_hash":   compute_trial_balance_hash(raw_balances),
        "fy_start":             fy_start,
        "fy_end":               fy_end,
        "client_id":            client_id,
        "firm_id":              firm_id,
    }


def generate_financial_statements(
    supabase,
    client_id: str,
    firm_id: str,
    fy_start: str,
    fy_end: str,
) -> Dict[str, Any]:
    """
    Generate Schedule III financial statements from the General Ledger.
    Companies Act 2013, Schedule III, Parts I and II.

    All values returned in integer paise. Never float.
    Reconciles with Trial Balance — raises ValueError if BS does not balance
    (within 1 paise tolerance for rounding guards).

    Steps:
    1. Fetch posted journal_lines for this client+firm in FY date range.
    2. Aggregate balance per account_id (integer paise).
    3. Apply account_group_mappings (firm_id + account_id → schedule_line).
    4. Aggregate by schedule_line.
    5. Validate: total_assets == total_equity_and_liabilities (1 paise tolerance).
    """
    if _USE_MOCK:
        return _mock_statements(client_id, firm_id, fy_start, fy_end)

    # ── 1. Fetch posted journal lines ─────────────────────────────────────────
    # F10 fix: Balance Sheet accounts (assets/liabilities/equity) carry a
    # CUMULATIVE balance that must include every prior year's postings, not
    # just the current FY's movement -- unlike P&L accounts (income/expense),
    # which correctly reset each FY. The previous version applied the FY
    # window uniformly to every account, silently dropping all prior-year
    # carry-forward for any client with more than one year of ledger history.
    # Fetch both windows; §4 below picks the correct one per account by its
    # schedule_line classification.
    # KEYSET-paginated: an un-paged .execute() is silently capped at PostgREST's
    # ~1000-row limit, so for any client with >1000 posted journal lines the
    # year-end statements were computed from a fraction of the ledger (wrong
    # figures, no error). Page by journal_lines.id until a short page. Also filter
    # deleted_at IS NULL — soft-deleted entries must be excluded, exactly as the
    # authoritative reporting engine (domain/reporting) does.
    _LINE_PAGE = 1000

    def _fetch_lines(gte_date: str | None) -> list:
        out: list = []
        cursor: str | None = None
        while True:
            q = (
                supabase
                .table("journal_lines")
                .select(
                    "id, account_id, debit_paise, credit_paise, "
                    "journal_entries!inner(client_id, firm_id, entry_date, is_posted, deleted_at)"
                )
                .eq("journal_entries.client_id", client_id)
                .eq("journal_entries.firm_id", firm_id)
                .eq("journal_entries.is_posted", True)
                .is_("journal_entries.deleted_at", "null")
                .lte("journal_entries.entry_date", fy_end)
                .order("id")
                .limit(_LINE_PAGE)
            )
            if gte_date:
                q = q.gte("journal_entries.entry_date", gte_date)
            if cursor is not None:
                q = q.gt("id", cursor)
            page = q.execute().data or []
            out.extend(page)
            if len(page) < _LINE_PAGE:
                break
            cursor = page[-1]["id"]
        return out

    fy_window_lines = _fetch_lines(fy_start)     # P&L: this year's movement only
    cumulative_lines = _fetch_lines(None)        # Balance Sheet: all-time to fy_end

    def _totals(raw_lines: list) -> tuple[Dict[str, int], Dict[str, int]]:
        debit_totals: Dict[str, int] = {}
        credit_totals: Dict[str, int] = {}
        for line in raw_lines:
            acct = line["account_id"]
            debit_totals[acct] = debit_totals.get(acct, 0) + int(line["debit_paise"])
            credit_totals[acct] = credit_totals.get(acct, 0) + int(line["credit_paise"])
        return debit_totals, credit_totals

    # ── 2. Aggregate integer paise balance per account_id, per window ───────
    # All arithmetic in integer paise — never float.
    fy_debit_totals, fy_credit_totals = _totals(fy_window_lines)
    cum_debit_totals, cum_credit_totals = _totals(cumulative_lines)

    all_account_ids = (
        set(fy_debit_totals) | set(fy_credit_totals)
        | set(cum_debit_totals) | set(cum_credit_totals)
    )

    # ── 3. Load account_group_mappings for this firm ─────────────────────────
    mappings_res = (
        supabase
        .table("account_group_mappings")
        .select("account_id, schedule_line, normal_balance")
        .eq("firm_id", firm_id)
        .execute()
    )
    mapping_lookup: Dict[str, dict] = {
        m["account_id"]: m for m in (mappings_res.data or [])
    }

    # ── 4. Aggregate by schedule_line (integer paise) ────────────────────────
    schedule_balances: Dict[str, int] = {}
    raw_balances: Dict[str, int] = {}

    for acct_id in all_account_ids:
        mapping = mapping_lookup.get(acct_id)
        if not mapping:
            # Unmapped accounts go to other_current_assets (a Balance Sheet line)
            schedule_line  = "other_current_assets"
            normal_balance = "debit"
        else:
            schedule_line  = mapping["schedule_line"]
            normal_balance = mapping.get("normal_balance", "debit")

        is_balance_sheet_line = (
            schedule_line in BS_EQUITY_LIABILITY_LINES or schedule_line in BS_ASSET_LINES
        )
        if is_balance_sheet_line:
            dr = cum_debit_totals.get(acct_id, 0)
            cr = cum_credit_totals.get(acct_id, 0)
        else:
            dr = fy_debit_totals.get(acct_id, 0)
            cr = fy_credit_totals.get(acct_id, 0)

        # Compute balance using normal balance convention (integer paise)
        if normal_balance == "credit" or schedule_line in _CREDIT_NORMAL_LINES:
            # Liabilities / income / equity: balance = credit - debit
            balance = cr - dr
        else:
            # Assets / expenses: balance = debit - credit
            balance = dr - cr

        schedule_balances[schedule_line] = schedule_balances.get(schedule_line, 0) + balance
        raw_balances[acct_id] = balance

    # ── 5. Build structured Schedule III output ──────────────────────────────
    bs_eq_lib = {line: schedule_balances.get(line, 0) for line in BS_EQUITY_LIABILITY_LINES}
    bs_assets  = {line: schedule_balances.get(line, 0) for line in BS_ASSET_LINES}
    pl_income  = {line: schedule_balances.get(line, 0) for line in PL_INCOME_LINES}
    pl_expense = {line: schedule_balances.get(line, 0) for line in PL_EXPENSE_LINES}

    total_eq_lib  = sum(bs_eq_lib.values())   # integer paise
    total_assets  = sum(bs_assets.values())   # integer paise
    total_income  = sum(pl_income.values())   # integer paise
    total_expense = sum(pl_expense.values())  # integer paise

    pbt = total_income  - total_expense       # integer paise

    # THE TAX CHARGE IS READ, NEVER INVENTED.
    #
    # This used to be `tax = max(0, pbt * 25 // 100)` — a flat 25% with no
    # basis in any statute. No Indian rate is 25% of book profit: a company
    # pays 30%, or 22% under §115BAA, or 15% under §115BAB, each plus
    # surcharge and 4% cess, with MAT under §115JB where applicable; a
    # proprietorship's profit is taxed in the PROPRIETOR's hands at individual
    # slabs and is not a charge on the business at all. And because the figure
    # was struck from BOOK profit it carried none of the disallowances,
    # depreciation differences or regime choices that produce a real one.
    #
    # It corrupted more than its own line. PAT flows into reserves below, so
    # the balance sheet's equity inherited the invention — and any real tax
    # provision already sitting in the GL was mapped to other_expenses, so it
    # reduced PBT as an operating cost and was then taxed again at 25%.
    #
    # Schedule III Part II item VII wants "Tax expense: (1) Current tax
    # (2) Deferred tax". For a company that has provided for tax, that is a
    # posted GL figure, so it is read from the ledger like every other line.
    # Where nothing is mapped the charge is nil and the note below says so —
    # a stated nil a CA can act on, rather than a plausible number they cannot
    # tell from a real one.
    pl_tax = {line: schedule_balances.get(line, 0) for line in PL_TAX_LINES}
    tax = sum(pl_tax.values())                # integer paise
    pat = pbt - tax                           # integer paise

    # Add PAT to reserves_and_surplus to close the P&L into BS
    bs_eq_lib["reserves_and_surplus"] = bs_eq_lib.get("reserves_and_surplus", 0) + pat
    total_eq_lib += pat

    # ── Validate BS balance (within 1 paise tolerance) ────────────────────────
    diff = abs(total_assets - total_eq_lib)
    if diff > 1:
        raise ValueError(
            f"Balance Sheet does not balance: "
            f"Assets={total_assets} paise, "
            f"Equity+Liabilities={total_eq_lib} paise, "
            f"Difference={diff} paise. "
            f"Check account_group_mappings for firm {firm_id}."
        )

    return {
        "balance_sheet": {
            "equity_and_liabilities": bs_eq_lib,
            "assets":                 bs_assets,
            "total_equity_and_liabilities_paise": total_eq_lib,
            "total_assets_paise":                 total_assets,
            "is_balanced":                        diff == 0,
        },
        "profit_loss": {
            "income":                  pl_income,
            "expenses":                pl_expense,
            "total_income_paise":      total_income,
            "total_expense_paise":     total_expense,
            "profit_before_tax_paise": pbt,
            "current_tax_paise":       pl_tax.get("current_tax", 0),
            "deferred_tax_paise":      pl_tax.get("deferred_tax", 0),
            "tax_expense_paise":       tax,
            "tax_expense_is_provided": tax != 0,
            "profit_after_tax_paise":  pat,
        },
        "trial_balance_hash": compute_trial_balance_hash(raw_balances),
        "fy_start":           fy_start,
        "fy_end":             fy_end,
        "client_id":          client_id,
        "firm_id":            firm_id,
    }


def compute_trial_balance_hash(balances: dict) -> str:
    """
    SHA-256 of sorted trial balance dict.
    Detects GL changes after snapshot — used for integrity verification.
    All values must be integer paise before calling this function.
    """
    serialized = json.dumps(sorted(balances.items()), separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()
