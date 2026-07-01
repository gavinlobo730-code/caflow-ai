"""
Report builders — turn a stream of ProjectedLines into Trial Balance, P&L and
Balance Sheet payloads. Shared by both accrual and cash bases so the two are
computed by identical code over the same source (only the line stream differs).

Response shapes are byte-compatible with the legacy accounting_service so the
frontend and existing consumers need no change. Integer paise throughout.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .model import Account, JournalEntry, ProjectedLine


def _acc(accounts: dict[str, Account], aid: str) -> Account:
    return accounts.get(aid) or Account(id=aid, code="", name=aid, type="")


def ledger(entries_by_id: dict[str, JournalEntry], accounts: dict[str, Account],
           account_id: str, start: Optional[str], end: Optional[str]) -> dict:
    """Per-account general ledger with opening / running / closing balances.

    Accrual, posted-only (the source already filters is_posted + deleted_at). The
    opening balance is the cumulative debit−credit for the account STRICTLY before
    `start`, so the running balance carries forward across periods (the previous
    browser implementation wrongly restarted at zero each year). `entries_by_id`
    is the full posted history for the tenant. Balances are signed integer paise
    (debit-positive); is_debit reflects the side. Order: entry_date, then
    created_at, then id — deterministic for same-day and backdated entries.
    """
    acct = accounts.get(account_id)
    hits = [(e, ln) for e in entries_by_id.values()
            for ln in e.lines if ln.account_id == account_id]
    hits.sort(key=lambda el: (el[0].entry_date, el[0].created_at or "", el[0].id))

    opening = 0
    in_range: list[tuple[JournalEntry, object]] = []
    for e, ln in hits:
        if start and e.entry_date < start:
            opening += ln.debit_paise - ln.credit_paise
        elif end and e.entry_date > end:
            continue                          # after the window — excluded from this view
        else:
            in_range.append((e, ln))

    running = opening
    total_debit = total_credit = 0
    rows = []
    has_foreign = False
    for e, ln in in_range:
        running += ln.debit_paise - ln.credit_paise
        total_debit += ln.debit_paise
        total_credit += ln.credit_paise
        row = {
            "entry_id": e.id,
            "entry_date": e.entry_date,
            "reference_no": e.reference_no,
            "narration": e.narration,
            "debit_paise": ln.debit_paise,
            "credit_paise": ln.credit_paise,
            "running_balance_paise": running,
            "is_debit": running >= 0,
        }
        # Multi-Currency Phase 5 — optional transaction-currency visibility. Emitted
        # ONLY for genuinely foreign lines, so an INR-only ledger is byte-for-byte
        # unchanged. The base paise above stay authoritative (they drive the running
        # balance and every aggregate report); these are display memo only.
        if getattr(ln, "is_foreign", False):
            has_foreign = True
            row["txn_currency"] = (ln.txn_currency or "").upper()
            row["txn_debit_minor"] = int(ln.txn_debit or 0)
            row["txn_credit_minor"] = int(ln.txn_credit or 0)
            if ln.exchange_rate is not None:
                row["exchange_rate"] = str(ln.exchange_rate)
        rows.append(row)

    out = {
        "account_id": account_id,
        "account_code": acct.code if acct else "",
        "account_name": acct.name if acct else "",
        "account_type": acct.type if acct else "",
        "start_date": start,
        "end_date": end,
        "opening_balance_paise": opening,
        "opening_is_debit": opening >= 0,
        "closing_balance_paise": running,
        "closing_is_debit": running >= 0,
        "total_debit_paise": total_debit,
        "total_credit_paise": total_credit,
        "lines": rows,
    }
    # A single presence flag lets the frontend show a currency column only when it
    # matters; absent (falsy) for INR-only accounts, so nothing changes for them.
    if has_foreign:
        out["has_foreign_lines"] = True
    return out


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


def _activity_of_entry(lines, accounts, bank_ids) -> str:
    """Classify a CASH-touching journal entry by its non-cash legs.
    Investing wins over financing wins over operating (an entry touching a fixed
    asset is an investing transaction regardless of any P&L leg, so disposal
    proceeds land in investing and the gain/loss is not shown as operating cash)."""
    acts = {
        _classify_activity(_acc(accounts, l.account_id))
        for l in lines if l.account_id not in bank_ids
    }
    if "investing" in acts:
        return "investing"
    if "financing" in acts:
        return "financing"
    return "operating"


def _attribute(acc_totals: dict, nonbank, accounts: dict, activity: str, cash: int) -> None:
    """Attribute an entry's cash to the most material counterpart account of its
    activity (e.g. disposal proceeds shown against the fixed-asset account)."""
    candidates = [l for l in nonbank
                  if _classify_activity(_acc(accounts, l.account_id)) == activity] or list(nonbank)
    if not candidates:
        return
    key = max(candidates, key=lambda l: l.debit_paise + l.credit_paise).account_id
    acc_totals[key] = acc_totals.get(key, 0) + cash


def _non_operating_pl(nonbank, accounts: dict) -> int:
    """Net P&L recognised in a non-operating (investing/financing) entry — i.e.
    gain (+) / loss (−) on disposal. credit−debit so a gain is positive."""
    total = 0
    for l in nonbank:
        a = _acc(accounts, l.account_id)
        if a.is_income or a.is_expense:
            total += l.credit_paise - l.debit_paise
    return total


def cash_flow(entries: list, accounts: dict[str, Account],
              bank_ids: frozenset[str], start_date: str, end_date: str,
              opening_cash_paise: int, closing_cash_paise: int, basis: str) -> dict:
    """
    AS-3 Cash Flow Statement (Companies Act 2013 Schedule III).

    Method (correct AS-3, not naive movement classification):
      • Investing & Financing — the ACTUAL cash legs of entries that touch a
        fixed-asset / loan / equity account (so a disposal shows full proceeds in
        investing, never the gain in operating).
      • Operating — the residual cash, presented as the INDIRECT reconciliation:
        net profit + depreciation add-back − non-operating gains ± working capital.
      • Non-cash entries (depreciation, year-end closing, accruals — no bank leg)
        are EXCLUDED from every section.

    Reconciliation is meaningful, not tautological:
      O + I + F == net cash change == (independent) closing − opening cash, AND
      the operating indirect breakdown ties to operating cash.
    Integer paise throughout — never float.
    """
    inv_acc: dict[str, int] = {}
    fin_acc: dict[str, int] = {}
    operating_cash = 0
    investing_cash = 0
    financing_cash = 0
    non_operating_pl = 0          # gain(+)/loss(−) on disposal etc.
    net_profit = 0               # accrual P&L for the period (excl. closing entries)
    depreciation = 0             # non-cash add-back
    working_capital = 0          # Δ operating current assets/liabilities
    non_cash_excluded = 0
    total_cash = 0

    for e in entries:
        elines = e.lines
        cash = sum(l.debit_paise - l.credit_paise for l in elines if l.account_id in bank_ids)
        total_cash += cash
        nonbank = [l for l in elines if l.account_id not in bank_ids]

        # ── Cash sections (actual cash legs) ──────────────────────────────────
        if cash != 0:
            activity = _activity_of_entry(elines, accounts, bank_ids)
            if activity == "investing":
                investing_cash += cash       # MEDIUM-3: full proceeds / cost to investing
                _attribute(inv_acc, nonbank, accounts, "investing", cash)
                non_operating_pl += _non_operating_pl(nonbank, accounts)
            elif activity == "financing":
                financing_cash += cash
                _attribute(fin_acc, nonbank, accounts, "financing", cash)
                non_operating_pl += _non_operating_pl(nonbank, accounts)
            else:
                operating_cash += cash
        else:
            non_cash_excluded += 1           # MEDIUM-4/5: non-cash entry excluded from cash flow

        # ── Operating-reconciliation inputs (HIGH-1) ─────────────────────────
        # Exclude year-end closing / equity reclassifications: a non-cash entry
        # that moves P&L into equity (Dr Revenue / Cr Retained Earnings) is not
        # period profit and must not pollute the indirect reconciliation (MEDIUM-5).
        has_equity = any(_acc(accounts, l.account_id).type == "Equity" for l in nonbank)
        has_pl = any(_acc(accounts, l.account_id).is_income or _acc(accounts, l.account_id).is_expense
                     for l in nonbank)
        if cash == 0 and has_equity and has_pl:
            continue
        for l in nonbank:
            a = _acc(accounts, l.account_id)
            if a.is_income or a.is_expense:
                net_profit += l.credit_paise - l.debit_paise         # P&L: credit-positive
                if a.is_expense and (a.subtype or "").strip().lower() == "depreciation":
                    depreciation += l.debit_paise - l.credit_paise   # non-cash add-back
            elif _classify_activity(a) == "operating":
                working_capital += l.credit_paise - l.debit_paise    # Δ operating WC

    operating_profit = net_profit - non_operating_pl                 # strip disposal gain/loss
    # Meaningful cross-check (HIGH-2): the indirect operating reconciliation must
    # tie to the residual operating cash — catches any mis-classification.
    operating_reconciles = (operating_profit + depreciation + working_capital) == operating_cash

    def acct_section(label: str, totals: dict[str, int]) -> dict:
        rows = []
        for aid, amt in totals.items():
            if amt == 0:
                continue
            a = _acc(accounts, aid)
            rows.append({
                "account_id": aid, "account_code": a.code, "account_name": a.name,
                "account_type": a.type, "account_subtype": a.subtype, "amount_paise": amt,
            })
        rows.sort(key=lambda x: x["account_code"])
        return {"label": label, "lines": rows, "total_paise": sum(totals.values())}

    # Operating section presented as the indirect reconciliation.
    op_lines = [{
        "account_id": "__net_profit__", "account_code": "", "account_name": "Net profit for the period",
        "account_type": "", "account_subtype": None, "amount_paise": net_profit,
    }]
    adjust = depreciation - non_operating_pl
    if adjust:
        op_lines.append({
            "account_id": "__noncash__", "account_code": "",
            "account_name": "Add back: depreciation & non-operating items",
            "account_type": "", "account_subtype": None, "amount_paise": adjust,
        })
    if working_capital:
        op_lines.append({
            "account_id": "__wc__", "account_code": "",
            "account_name": "Changes in working capital",
            "account_type": "", "account_subtype": None, "amount_paise": working_capital,
        })
    operating = {"label": "Cash from Operating Activities", "lines": op_lines, "total_paise": operating_cash}
    investing = acct_section("Cash from Investing Activities", inv_acc)
    financing = acct_section("Cash from Financing Activities", fin_acc)

    net_change = operating_cash + investing_cash + financing_cash
    reconciles = (
        net_change == total_cash                                   # every cash entry classified
        and (closing_cash_paise - opening_cash_paise) == net_change  # ties to ledger cash balances
        and operating_reconciles                                   # indirect == residual (not tautological)
    )
    out = {
        "start_date": start_date,
        "end_date": end_date,
        "operating": operating,
        "investing": investing,
        "financing": financing,
        "net_change_paise": net_change,
        "opening_cash_paise": opening_cash_paise,
        "closing_cash_paise": closing_cash_paise,
        "reconciles": reconciles,
        "non_cash_excluded_count": non_cash_excluded,
        "operating_reconciliation": {
            "net_profit_paise": net_profit,
            "non_operating_adjust_paise": -non_operating_pl,   # remove gains / add back losses
            "depreciation_addback_paise": depreciation,
            "working_capital_change_paise": working_capital,
            "net_cash_operating_paise": operating_cash,
            "ties_out": operating_reconciles,
        },
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
