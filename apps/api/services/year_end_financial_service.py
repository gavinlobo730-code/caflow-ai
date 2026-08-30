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

    # Representative mock values (integer paise). These figures are chosen so
    # the sheet BALANCES, which it previously did not: share capital 1,00,000 +
    # reserves 50,000 + payables 25,000 + borrowings 30,000 + other 5,000 came
    # to 2,10,000 against assets of 2,10,000, and then a mock PAT of 62,000 was
    # added to reserves without any asset to match it — so mock mode served an
    # is_balanced=False balance sheet and, unlike the real path, never
    # validated, so nothing ever said so. Dev, demo and every test that runs
    # without SUPABASE_URL saw it.
    #
    # Now the assets carry the year's profit too: the 62,000 earned is held as
    # cash, so cash_and_bank is 50,000 + 62,000.
    balance_sheet["equity_and_liabilities"]["share_capital"]         = 100_000_00  # 1,00,000 rupees in paise
    balance_sheet["equity_and_liabilities"]["reserves_and_surplus"]  = 50_000_00
    balance_sheet["equity_and_liabilities"]["trade_payables"]        = 25_000_00
    balance_sheet["equity_and_liabilities"]["short_term_borrowings"] = 30_000_00
    balance_sheet["equity_and_liabilities"]["other_current_liabilities"] = 5_000_00

    balance_sheet["assets"]["tangible_assets"]         = 80_000_00
    balance_sheet["assets"]["trade_receivables"]       = 60_000_00
    balance_sheet["assets"]["cash_and_bank"]           = 50_000_00
    balance_sheet["assets"]["inventories"]             = 20_000_00

    # The surplus already on the books before this year — the mock's own
    # brought-forward figure, held in the 50,000 of reserves seeded above.
    surplus_brought_forward = 50_000_00

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

    # The year's profit lands in reserves AND in the asset that holds it. Only
    # the first half used to happen, which is what unbalanced the mock.
    balance_sheet["equity_and_liabilities"]["reserves_and_surplus"] += pat
    balance_sheet["assets"]["cash_and_bank"] += pat

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
            "surplus_brought_forward_paise": surplus_brought_forward,
            "profit_for_the_year_paise":     pat,
            "surplus_carried_forward_paise": surplus_brought_forward + pat,
        },
        "profit_loss":          profit_loss,
        # Mock mode returns the same SHAPE as the real path, key for key. It
        # used to omit "comparatives" entirely; both current readers reach for
        # it defensively (.get / ?? null) so nothing crashed, but a mock whose
        # shape differs from production is a mock that hides the bugs it exists
        # to surface. There is no preceding period to invent here, and
        # Schedule III para 5 excepts the first statements after
        # incorporation — so it is an explicit None, not a column of zeros.
        "comparatives":         None,
        # No ledger to inspect in mock mode, so nothing that looks like a
        # hand-posted close. Present so the shape matches the real path —
        # test_mock_mode_returns_the_same_shape_as_the_real_path.
        "closing_entry_dates":  [],
        "trial_balance_hash":   compute_trial_balance_hash(raw_balances),
        "fy_start":             fy_start,
        "fy_end":               fy_end,
        "client_id":            client_id,
        "firm_id":              firm_id,
    }


def _closing_entries_in(raw_lines: list, mapping_lookup: dict) -> list:
    """Posted entries in this window that look like a CLOSING or appropriation
    journal — every line lands on either a Profit & Loss account or an equity
    account, with at least one of each.

    Why this is reported and NOT excluded. A closing entry is dated at the year
    end, so it falls INSIDE that year's own P&L window and cancels the revenue
    and expenses it closes: a firm that closes its books by hand gets a nil
    Statement of Profit and Loss for that year, while the Balance Sheet stays
    correct and nothing raises. That is a silent wrong number, and it is why
    this is surfaced.

    It is not silently netted out instead, because the shape above is a
    heuristic and no field on journal_entries marks a close (entry_type is
    CHECK-constrained to Sales/Purchase/Payment/Receipt/Journal/Contra/Opening
    by migration 003, none of which means "closing"). A heuristic that misfires
    would delete a real transaction from the P&L and report a plausible figure
    instead of an obviously nil one — the worse failure of the two. Excluding
    them properly means marking them at the point they are posted, which is a
    schema change and a CA-facing affordance, not a guess made at read time.
    """
    by_entry: dict = {}
    for line in raw_lines:
        entry = line.get("journal_entries") or {}
        key = (entry.get("entry_date"), line.get("journal_entry_id"))
        by_entry.setdefault(key, []).append(line)

    found = []
    for (entry_date, _eid), entry_lines in by_entry.items():
        has_pl = has_equity = False
        for line in entry_lines:
            mapping = mapping_lookup.get(line["account_id"])
            schedule_line = mapping["schedule_line"] if mapping else "other_current_assets"
            if schedule_line in PL_INCOME_LINES or schedule_line in PL_EXPENSE_LINES \
                    or schedule_line in PL_TAX_LINES:
                has_pl = True
            elif schedule_line in ("reserves_and_surplus", "share_capital"):
                has_equity = True
            else:
                # Any asset or liability leg means this is an ordinary
                # transaction, not a close.
                has_pl = has_equity = False
                break
        if has_pl and has_equity:
            found.append(entry_date)
    return sorted(set(found))


def _prior_period(fy_start: str, fy_end: str) -> tuple[str, str]:
    """The immediately preceding reporting period, as ISO dates.

    Derived by shifting both ends back one year rather than assuming an
    April-to-March window, so a client on a non-standard first period still
    gets the period that actually precedes it.
    """
    from datetime import date as _date

    def _shift(iso: str) -> str:
        d = _date.fromisoformat(str(iso)[:10])
        try:
            return d.replace(year=d.year - 1).isoformat()
        except ValueError:
            # 29 February: the preceding year has no such day.
            return d.replace(year=d.year - 1, day=28).isoformat()

    return _shift(fy_start), _shift(fy_end)


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
                    "id, journal_entry_id, account_id, debit_paise, credit_paise, "
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

    # ONE fetch serves BOTH reporting periods.
    #
    # Schedule III General Instructions para 5 requires the corresponding
    # amounts for the immediately preceding period, so this computes two
    # years — without reading the ledger twice to do it. _fetch_lines(None)
    # already returns every posted line up to fy_end, a superset of what
    # either year needs, so the periods are separated by DATE below rather
    # than by more round trips. That also retires the second fetch this
    # function used to make: it now costs ONE ledger read where it previously
    # cost two, while producing a whole extra year.
    cumulative_lines = _fetch_lines(None)        # every posted line <= fy_end

    prior_fy_start, prior_fy_end = _prior_period(fy_start, fy_end)

    def _entry_date(line: dict) -> str:
        return (line.get("journal_entries") or {}).get("entry_date") or ""

    # Four windows, two per period. A Balance Sheet is CUMULATIVE to its
    # period end; a P&L is WINDOWED to its own year. Pairing those wrongly is
    # the F10 bug noted above, and the preceding period obeys the same rule.
    fy_window_lines = [ln for ln in cumulative_lines if _entry_date(ln) >= fy_start]
    prior_window_lines = [ln for ln in cumulative_lines
                          if prior_fy_start <= _entry_date(ln) <= prior_fy_end]
    prior_cumulative_lines = [ln for ln in cumulative_lines
                              if _entry_date(ln) <= prior_fy_end]

    # Schedule III excepts "the first Financial Statements laid before the
    # Company after incorporation". With no posted line on or before the
    # preceding period's end there IS no such period, and a column of zeros
    # would assert one that was nil — a different and false claim. The
    # comparatives are omitted instead.
    has_prior_period = bool(prior_cumulative_lines)

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
    pr_fy_debit, pr_fy_credit = _totals(prior_window_lines)
    pr_cum_debit, pr_cum_credit = _totals(prior_cumulative_lines)

    all_account_ids = (
        set(fy_debit_totals) | set(fy_credit_totals)
        | set(cum_debit_totals) | set(cum_credit_totals)
        | set(pr_fy_debit) | set(pr_fy_credit)
        | set(pr_cum_debit) | set(pr_cum_credit)
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
    # One period's aggregation, so the PRECEDING period is computed by the
    # same code rather than a second implementation of the same rules. Two
    # implementations of a statutory format drift, and a comparative column
    # is only readable beside the current one if both are struck identically.
    def _aggregate(bs_dr, bs_cr, pl_dr, pl_cr):
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
                dr = bs_dr.get(acct_id, 0)
                cr = bs_cr.get(acct_id, 0)
            else:
                dr = pl_dr.get(acct_id, 0)
                cr = pl_cr.get(acct_id, 0)

            # Compute balance using normal balance convention (integer paise)
            if normal_balance == "credit" or schedule_line in _CREDIT_NORMAL_LINES:
                # Liabilities / income / equity: balance = credit - debit
                balance = cr - dr
            else:
                # Assets / expenses: balance = debit - credit
                balance = dr - cr

            schedule_balances[schedule_line] = schedule_balances.get(schedule_line, 0) + balance
            raw_balances[acct_id] = balance

        return schedule_balances, raw_balances

    schedule_balances, raw_balances = _aggregate(
        cum_debit_totals, cum_credit_totals, fy_debit_totals, fy_credit_totals)

    # The same aggregation with the CUMULATIVE window on BOTH sides, so the P&L
    # lines come back accumulated to fy_end instead of windowed to this year.
    # That is what the surplus carried into equity is struck from — see
    # _statement below. It reuses the totals already computed above, so it
    # costs no extra ledger read; test_one_ledger_read_serves_both_periods
    # still passes.
    cumulative_balances, _cum_raw = _aggregate(
        cum_debit_totals, cum_credit_totals, cum_debit_totals, cum_credit_totals)

    # ── 5. Build structured Schedule III output ──────────────────────────────
    # One period's statement, so the comparative column is produced by this
    # same function on the same rules.
    def _statement(sb, sb_cumulative):
        bs_eq_lib = {line: sb.get(line, 0) for line in BS_EQUITY_LIABILITY_LINES}
        bs_assets  = {line: sb.get(line, 0) for line in BS_ASSET_LINES}
        pl_income  = {line: sb.get(line, 0) for line in PL_INCOME_LINES}
        pl_expense = {line: sb.get(line, 0) for line in PL_EXPENSE_LINES}

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
        pl_tax = {line: sb.get(line, 0) for line in PL_TAX_LINES}
        tax = sum(pl_tax.values())                # integer paise
        pat = pbt - tax                           # integer paise

        # ── The surplus carried into equity is CUMULATIVE, not this year's ───
        #
        # This used to add `pat` — the CURRENT year's profit alone. Every
        # balance-sheet line is struck cumulatively (§2 above picks the
        # cumulative window for them), so assets and liabilities carried every
        # prior year's postings while equity carried only the latest year's
        # profit. Every entry that reaches the GL is balanced, so over every
        # line up to fy_end:
        #
        #     A = L + [ I - E - X ]  =  L + PAT(<= fy_end)
        #
        # while the statement reported L + PAT(this year). The sheet was
        # therefore out by PAT(< fy_start) — the sum of EVERY prior period's
        # profit after tax, accumulating year on year — and the ValueError
        # below fired. A client's second year of trading could not produce
        # financial statements at all: HTTP 422 from the statements endpoint,
        # the snapshot, the PDF and the audit pack alike.
        #
        # Schedule III, Division I, Part I wants exactly the cumulative figure.
        # "Reserves and Surplus" carries the sub-head "Surplus, i.e., balance
        # in Statement of Profit and Loss", and a balance is what has
        # accumulated, not what one year added. So the old line was wrong on
        # the statute's own terms before it was wrong arithmetically.
        #
        # DERIVING this rather than posting a closing journal into the GL is
        # deliberate, and it is what the other reporting engine already does
        # (domain/reporting/builders.balance_sheet computes net profit from the
        # same cumulative line set it uses for assets and injects a synthetic
        # equity row, which is why that engine never had this bug). Deriving is
        # also SELF-CORRECTING for a firm that posts its own closing entries by
        # hand: such an entry debits income by I_c, credits expenses by E_c and
        # credits an equity account by P = I_c - E_c, so cumulative PAT falls by
        # exactly P at the moment posted equity rises by exactly P. The total is
        # invariant, which is why there is no double count — the objection that
        # kept this unfixed. test_a_manually_posted_closing_entry_is_not_double_counted
        # pins it.
        cum_income = sum(sb_cumulative.get(line, 0) for line in PL_INCOME_LINES)
        cum_expense = sum(sb_cumulative.get(line, 0) for line in PL_EXPENSE_LINES)
        cum_tax = sum(sb_cumulative.get(line, 0) for line in PL_TAX_LINES)
        cumulative_pat = cum_income - cum_expense - cum_tax   # integer paise

        bs_eq_lib["reserves_and_surplus"] = (
            bs_eq_lib.get("reserves_and_surplus", 0) + cumulative_pat)
        total_eq_lib += cumulative_pat

        return {
            "bs_eq_lib": bs_eq_lib, "bs_assets": bs_assets,
            "pl_income": pl_income, "pl_expense": pl_expense, "pl_tax": pl_tax,
            "total_eq_lib": total_eq_lib, "total_assets": total_assets,
            "total_income": total_income, "total_expense": total_expense,
            "pbt": pbt, "tax": tax, "pat": pat,
            # The movement, so the equity figure is auditable rather than a
            # single number a CA has to take on trust. Schedule III's Reserves
            # and Surplus note is written in exactly this shape: opening
            # balance, add profit for the period, closing balance.
            "surplus_brought_forward": cumulative_pat - pat,
            "surplus_carried_forward": cumulative_pat,
        }

    # Entries inside this year's window that look like a hand-posted close.
    # Reported, never netted out — see _closing_entries_in.
    closing_dates = _closing_entries_in(fy_window_lines, mapping_lookup)

    cur = _statement(schedule_balances, cumulative_balances)
    bs_eq_lib, bs_assets = cur["bs_eq_lib"], cur["bs_assets"]
    pl_income, pl_expense, pl_tax = cur["pl_income"], cur["pl_expense"], cur["pl_tax"]
    total_eq_lib, total_assets = cur["total_eq_lib"], cur["total_assets"]
    total_income, total_expense = cur["total_income"], cur["total_expense"]
    pbt, tax, pat = cur["pbt"], cur["tax"], cur["pat"]

    # The comparative period, struck by the same _aggregate/_statement pair on
    # the same mappings — only the date windows differ.
    prior = None
    if has_prior_period:
        prior_balances, _prior_raw = _aggregate(
            pr_cum_debit, pr_cum_credit, pr_fy_debit, pr_fy_credit)
        prior_cumulative, _prior_cum_raw = _aggregate(
            pr_cum_debit, pr_cum_credit, pr_cum_debit, pr_cum_credit)
        prior = _statement(prior_balances, prior_cumulative)

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
            # Schedule III's Reserves and Surplus note is opening balance, add
            # profit for the period, closing balance. Carrying the movement
            # makes the equity figure checkable instead of a number the CA has
            # to take on trust — reserves_and_surplus above is the CLOSING
            # balance, and these say how it got there.
            "surplus_brought_forward_paise": cur["surplus_brought_forward"],
            "profit_for_the_year_paise":     pat,
            "surplus_carried_forward_paise": cur["surplus_carried_forward"],
        },
        # Dates in this period carrying an entry that closes Profit & Loss
        # accounts into equity. Such an entry is dated at the year end, so it
        # sits INSIDE this year's P&L window and cancels the revenue and
        # expenses it closes — the Statement of Profit and Loss below then
        # reads nil while the Balance Sheet stays correct and nothing raises.
        # Empty for the overwhelming majority of clients, who do not close
        # their own books. Non-empty means the P&L figures need a CA's eye
        # before they are relied on. See _closing_entries_in for why this is
        # reported rather than netted out.
        "closing_entry_dates": closing_dates,
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
        # Schedule III, Division I, General Instructions para 5: the
        # corresponding amounts for the immediately preceding reporting period
        # must be given for every item, including notes. Without them the
        # output is not a Schedule III financial statement and cannot be laid
        # before members, attached to AOC-4, or handed to an auditor.
        #
        # Carried alongside rather than folded into each line so every existing
        # reader of balance_sheet/profit_loss keeps working unchanged. None
        # means there is genuinely no preceding period (the first statements
        # after incorporation), which para 5 excepts — not that it was nil.
        "comparatives": None if prior is None else {
            "fy_start": prior_fy_start,
            "fy_end":   prior_fy_end,
            "balance_sheet": {
                "equity_and_liabilities": prior["bs_eq_lib"],
                "assets":                 prior["bs_assets"],
                "total_equity_and_liabilities_paise": prior["total_eq_lib"],
                "total_assets_paise":                 prior["total_assets"],
                "surplus_brought_forward_paise": prior["surplus_brought_forward"],
                "profit_for_the_year_paise":     prior["pat"],
                "surplus_carried_forward_paise": prior["surplus_carried_forward"],
                # Reported, never raised on: a preceding period that does not
                # balance is a fact about history the CA needs to see, and
                # refusing to render the CURRENT year over it would withhold
                # the statements they came for.
                "is_balanced": abs(prior["total_assets"] - prior["total_eq_lib"]) <= 1,
            },
            "profit_loss": {
                "income":                  prior["pl_income"],
                "expenses":                prior["pl_expense"],
                "total_income_paise":      prior["total_income"],
                "total_expense_paise":     prior["total_expense"],
                "profit_before_tax_paise": prior["pbt"],
                "current_tax_paise":       prior["pl_tax"].get("current_tax", 0),
                "deferred_tax_paise":      prior["pl_tax"].get("deferred_tax", 0),
                "tax_expense_paise":       prior["tax"],
                "tax_expense_is_provided": prior["tax"] != 0,
                "profit_after_tax_paise":  prior["pat"],
            },
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
