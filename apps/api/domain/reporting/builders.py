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
