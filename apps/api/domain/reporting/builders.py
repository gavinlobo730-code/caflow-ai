"""
Report builders — turn a stream of ProjectedLines into Trial Balance, P&L and
Balance Sheet payloads. Shared by both accrual and cash bases so the two are
computed by identical code over the same source (only the line stream differs).

Response shapes are byte-compatible with the legacy accounting_service so the
frontend and existing consumers need no change. Integer paise throughout.
"""
from __future__ import annotations

from datetime import date

from .model import Account, ProjectedLine


def _acc(accounts: dict[str, Account], aid: str) -> Account:
    return accounts.get(aid) or Account(id=aid, code="", name=aid, type="")


def trial_balance(lines: list[ProjectedLine], accounts: dict[str, Account],
                  as_of_date: str | None, basis: str) -> dict:
    totals: dict[str, dict] = {}
    for ln in lines:
        a = _acc(accounts, ln.account_id)
        row = totals.get(ln.account_id)
        if row is None:
            row = {
                "account_id": ln.account_id,
                "account_code": a.code,
                "account_name": a.name,
                "account_type": a.type,
                "total_debit_paise": 0,
                "total_credit_paise": 0,
                "net_paise": 0,
            }
            totals[ln.account_id] = row
        row["total_debit_paise"] += ln.debit_paise
        row["total_credit_paise"] += ln.credit_paise

    tb_lines, grand_dr, grand_cr = [], 0, 0
    for row in totals.values():
        row["net_paise"] = row["total_debit_paise"] - row["total_credit_paise"]
        # Drop net-zero accounts (e.g. A/R fully transformed away in cash basis).
        if row["total_debit_paise"] == 0 and row["total_credit_paise"] == 0:
            continue
        tb_lines.append(row)
        grand_dr += row["total_debit_paise"]
        grand_cr += row["total_credit_paise"]
    tb_lines.sort(key=lambda x: x["account_code"])
    diff = grand_dr - grand_cr
    out = {
        "as_of_date": as_of_date or date.today().isoformat(),
        "lines": tb_lines,
        "total_debit_paise": grand_dr,
        "total_credit_paise": grand_cr,
        "is_balanced": diff == 0,
        "difference_paise": diff,
    }
    if basis == "cash":
        out["basis"] = "cash"
    return out


def profit_loss(lines: list[ProjectedLine], accounts: dict[str, Account],
                start_date: str, end_date: str, basis: str) -> dict:
    income: dict[str, int] = {}
    expense: dict[str, int] = {}
    for ln in lines:
        a = _acc(accounts, ln.account_id)
        if a.is_income:
            income[ln.account_id] = income.get(ln.account_id, 0) + ln.credit_paise - ln.debit_paise
        elif a.is_expense:
            expense[ln.account_id] = expense.get(ln.account_id, 0) + ln.debit_paise - ln.credit_paise

    def section(label: str, totals: dict[str, int]) -> dict:
        rows = []
        for aid, amt in totals.items():
            if amt == 0:
                continue
            a = _acc(accounts, aid)
            # account_type/subtype/code are presentation hints (Schedule III grouping
            # is done in the UI); all monetary aggregation stays here in the backend.
            rows.append({
                "account_id": aid,
                "account_name": a.name,
                "account_code": a.code,
                "account_type": a.type,
                "account_subtype": a.subtype,
                "amount_paise": amt,
            })
        rows.sort(key=lambda x: x["account_name"])
        return {"label": label, "lines": rows, "total_paise": sum(v for v in totals.values())}

    revenue = section("Revenue", income)
    opex = section("Operating Expenses", expense)
    out = {
        "start_date": start_date,
        "end_date": end_date,
        "revenue": revenue,
        "cost_of_sales": {"label": "Cost of Sales", "lines": [], "total_paise": 0},
        "gross_profit_paise": revenue["total_paise"],
        "operating_expenses": opex,
        "net_profit_paise": revenue["total_paise"] - opex["total_paise"],
    }
    if basis == "cash":
        out["basis"] = "cash"
    return out


# ── Cash Flow Statement (AS-3 / Companies Act 2013 Schedule III) ──────────────
#
# Classification uses STRUCTURED chart fields only — account_type,
# account_subtype and system_account_key — never the free-text account name
# (mirrors the resolver's key-first architecture). Cash & cash-equivalent
# accounts are identified by the caller (AccountResolver.bank_ids) and excluded
# here. system_account_key is authoritative for control accounts; subtype
# disambiguates fixed assets / loans which carry no system key.

# Control-account keys that are always operating working-capital items.
_OPERATING_KEYS = frozenset({
    "ar", "ap", "gst_input", "gst_output", "gst_cgst", "gst_sgst", "gst_igst",
    "tds_payable", "tds_receivable", "advance_customer", "advance_vendor",
})


def _classify_activity(a: Account) -> str:
    """Map a non-cash account to an AS-3 activity: operating | investing | financing.

    Uses account_type + account_subtype + system_account_key (controlled fields),
    never the account name. Cash/bank accounts are handled by the caller.
    """
    if a.system_key in _OPERATING_KEYS:
        return "operating"
    sub = (a.subtype or "").strip().lower()
    if a.type == "Asset":
        # Non-current / capital assets → investing; current assets → operating.
        if any(t in sub for t in ("fixed", "investment", "non-current", "non current")):
            return "investing"
        return "operating"
    if a.type == "Equity":
        return "financing"
    if a.type == "Liability":
        # Borrowings / long-term liabilities → financing; current → operating.
        if any(t in sub for t in ("loan", "borrow", "long-term", "long term", "non-current", "non current")):
            return "financing"
        return "operating"
    # Revenue / Income / Expense → operating (the profit-derived cash).
    return "operating"


def cash_flow(lines: list[ProjectedLine], accounts: dict[str, Account],
              bank_ids: frozenset[str], start_date: str, end_date: str,
              opening_cash_paise: int, basis: str) -> dict:
    """
    Build an AS-3 (indirect-method) Cash Flow Statement from the period's
    ProjectedLines. Derived from ledger movement, so by double-entry:

        Operating + Investing + Financing
            = net movement of cash/bank accounts
            = Closing Cash − Opening Cash

    Every cash inflow is the credit side of a non-cash account's movement, so a
    non-cash account's contribution is (credit − debit) of its period movement
    (inflow positive). Integer paise throughout — never float.
    """
    by_activity: dict[str, dict[str, int]] = {"operating": {}, "investing": {}, "financing": {}}
    cash_movement = 0
    for ln in lines:
        if ln.account_id in bank_ids:
            cash_movement += ln.debit_paise - ln.credit_paise   # debit-positive = cash in
            continue
        a = _acc(accounts, ln.account_id)
        bucket = by_activity[_classify_activity(a)]
        bucket[ln.account_id] = bucket.get(ln.account_id, 0) + (ln.credit_paise - ln.debit_paise)

    def section(label: str, totals: dict[str, int]) -> dict:
        rows = []
        for aid, amt in totals.items():
            if amt == 0:
                continue
            a = _acc(accounts, aid)
            rows.append({
                "account_id": aid,
                "account_code": a.code,
                "account_name": a.name,
                "account_type": a.type,
                "account_subtype": a.subtype,
                "amount_paise": amt,
            })
        rows.sort(key=lambda x: x["account_code"])
        return {"label": label, "lines": rows, "total_paise": sum(totals.values())}

    operating = section("Cash from Operating Activities", by_activity["operating"])
    investing = section("Cash from Investing Activities", by_activity["investing"])
    financing = section("Cash from Financing Activities", by_activity["financing"])

    net_change = operating["total_paise"] + investing["total_paise"] + financing["total_paise"]
    closing_cash = opening_cash_paise + cash_movement
    out = {
        "start_date": start_date,
        "end_date": end_date,
        "operating": operating,
        "investing": investing,
        "financing": financing,
        "net_change_paise": net_change,
        "opening_cash_paise": opening_cash_paise,
        "closing_cash_paise": closing_cash,
        # Guaranteed equal by double-entry; surfaced for the UI and asserted in tests.
        "reconciles": net_change == cash_movement == (closing_cash - opening_cash_paise),
    }
    if basis == "cash":
        out["basis"] = "cash"
    return out


def balance_sheet(lines: list[ProjectedLine], accounts: dict[str, Account],
                  as_of_date: str | None, basis: str) -> dict:
    balances: dict[str, int] = {}
    for ln in lines:
        balances[ln.account_id] = balances.get(ln.account_id, 0) + ln.debit_paise - ln.credit_paise

    def lines_for(atype_pred) -> list[dict]:
        result = []
        for aid, net in balances.items():
            a = _acc(accounts, aid)
            if not atype_pred(a):
                continue
            bal = net if a.type == "Asset" else -net  # assets debit-positive; L/E credit-positive
            if bal != 0:
                result.append({
                    "account_id": aid,
                    "account_name": a.name,
                    "account_code": a.code,
                    "account_type": a.type,
                    "account_subtype": a.subtype,
                    "balance_paise": bal,
                })
        result.sort(key=lambda x: x["account_name"])
        return result

    def sect(label: str, rows: list[dict]) -> dict:
        return {"label": label, "lines": rows, "total_paise": sum(r["balance_paise"] for r in rows)}

    assets = [sect("Assets", lines_for(lambda a: a.type == "Asset"))]
    total_assets = sum(s["total_paise"] for s in assets)

    liabilities = [sect("Liabilities", lines_for(lambda a: a.type == "Liability"))]
    total_liab = sum(s["total_paise"] for s in liabilities)

    equity_rows = lines_for(lambda a: a.type == "Equity")
    income_net = sum(-net for aid, net in balances.items() if _acc(accounts, aid).is_income)
    expense_net = sum(net for aid, net in balances.items() if _acc(accounts, aid).is_expense)
    net_profit = income_net - expense_net
    if net_profit != 0:
        equity_rows.append({
            "account_id": "__retained__",
            "account_name": "Retained Earnings / Net Profit",
            "account_code": "",
            "account_type": "Equity",
            "account_subtype": "Reserves & Surplus",
            "balance_paise": net_profit,
        })
    equity = [sect("Equity", equity_rows)]
    total_equity = sum(s["total_paise"] for s in equity)

    total_le = total_liab + total_equity
    out = {
        "as_of_date": as_of_date or date.today().isoformat(),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "total_assets_paise": total_assets,
        "total_liabilities_equity_paise": total_le,
        "is_balanced": (total_assets - total_le) == 0,
    }
    if basis == "cash":
        out["basis"] = "cash"
    return out
