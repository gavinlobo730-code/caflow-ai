"""
The Schedule III ratios — Division I, General Instructions, clause (Q).

WHAT THIS IS
    MCA Notification G.S.R. 207(E) of 24 March 2021, with effect from 1 April
    2021, added "Additional Regulatory Information" to the General Instructions
    for preparation of the Balance Sheet. One of those items is a table of
    ELEVEN named ratios:

        (a) Current Ratio                    (g) Trade payables turnover ratio
        (b) Debt-Equity Ratio                (h) Net capital turnover ratio
        (c) Debt Service Coverage Ratio      (i) Net profit ratio
        (d) Return on Equity Ratio           (j) Return on Capital employed
        (e) Inventory turnover ratio         (k) Return on investment
        (f) Trade Receivables turnover ratio

    and two obligations that are the whole reason this module has the shape it
    does:

        "The company shall explain the items included in numerator and
         denominator for computing the above ratios. Further explanation shall
         be provided for any change in the ratio by more than 25% as compared
         to the preceding year."

    So a bare number is not the disclosure. Every ratio here carries the two
    amounts it was computed from, in paise, and the words describing what went
    into each — because those words ARE part of what has to be filed. And every
    ratio is computed for the preceding year too, so the 25% test is a fact
    rather than something a CA re-derives by hand.

WHY THE COMPONENTS COME FROM bucket_amounts
    schedule_iii.bucket_amounts is the same function build_schedule_iii uses.
    A ratio note is a note TO the balance sheet: if "Trade Receivables" in the
    ratio differs from "Trade Receivables" on the face of the statement, the CA
    signs two numbers that contradict each other. Reusing the bucketing makes
    that impossible rather than unlikely, and a test asserts the components
    equal the statement lines.

ARITHMETIC
    Amounts stay integer paise. A ratio is not a rupee amount, so it is carried
    as `value_bps` — numerator/denominator x 10,000, floor-divided — which
    keeps every step integral. 10,000 bps is 1.00, so a current ratio of 1.75
    is 17,500 bps and a net profit ratio of 8.5% is 850 bps. `unit` says which
    way to read it; nothing here formats.

WHAT IS REFUSED RATHER THAN GUESSED
    Two of the eleven need a number the ledger does not hold, and both are
    reported as gaps with the ratio absent:

      * Debt Service Coverage needs PRINCIPAL REPAID on long-term borrowings
        during the year. The movement in the borrowing balance is a NET figure
        — new drawdowns less repayments — and using it would overstate cover
        for any client that borrowed again in the same year. That is a ratio
        lenders read.
      * Return on Investment needs income FROM INVESTMENTS. Where the chart of
        accounts tags an income account as dividend or interest income this is
        computed; where nothing is tagged, the answer is a gap, not zero —
        "no investment income" and "investments not separately tracked" are
        different claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .schedule_iii import bucket_amounts

# 10,000 bps = 1.00. A ratio expressed "x times" and one expressed as a
# percentage differ only in how they are READ, so both are carried the same way
# and `unit` decides the reading.
BPS = 10_000

UNIT_TIMES = "times"
UNIT_PERCENT = "percent"

# Schedule III clause (Q) requires an explanation for a change of more than 25%
# from the preceding year. More than, not at least: exactly 25% needs none.
VARIANCE_THRESHOLD_BPS = 25 * 100


# ── Which income accounts are investment income ──────────────────────────────
# pl_bucket folds dividend and interest income into "Other Income", which is
# right for the face of the P&L and useless for Return on Investment. These read
# the account's own subtype instead, so a client whose chart distinguishes them
# gets the ratio and one whose chart does not gets a gap.
_INVESTMENT_INCOME_SUBTYPES = ("dividend", "interest income", "investment income")


@dataclass(frozen=True)
class Component:
    """One side of a ratio, and the words that have to be disclosed with it."""
    label: str
    paise: int


@dataclass(frozen=True)
class Ratio:
    key: str
    clause: str                      # (a) … (k), as Schedule III lists them
    label: str
    unit: str
    numerator: Optional[Component]
    denominator: Optional[Component]
    value_bps: Optional[int]
    prior_value_bps: Optional[int] = None
    variance_bps: Optional[int] = None       # signed change vs prior, in bps
    needs_explanation: bool = False
    unavailable_reason: Optional[str] = None
    explanation: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "key": self.key, "clause": self.clause, "label": self.label,
            "unit": self.unit,
            "numerator": ({"label": self.numerator.label, "paise": self.numerator.paise}
                          if self.numerator else None),
            "denominator": ({"label": self.denominator.label, "paise": self.denominator.paise}
                            if self.denominator else None),
            "value_bps": self.value_bps,
            "prior_value_bps": self.prior_value_bps,
            "variance_bps": self.variance_bps,
            "needs_explanation": self.needs_explanation,
            "unavailable_reason": self.unavailable_reason,
            "explanation": self.explanation,
        }


def ratio_bps(numerator_paise: int, denominator_paise: int) -> Optional[int]:
    """numerator/denominator in basis points, or None where it does not exist.

    A zero denominator is not zero and not infinity — it is undefined, and the
    disclosure for it is a blank with the components shown, not a number a
    reader would take at face value. Truncation is toward zero on both signs so
    a negative ratio is not reported as more negative than it is.
    """
    if denominator_paise == 0:
        return None
    q = abs(numerator_paise) * BPS // abs(denominator_paise)
    negative = (numerator_paise < 0) != (denominator_paise < 0)
    return -q if negative else q


def variance(current_bps: Optional[int], prior_bps: Optional[int]) -> tuple[Optional[int], bool]:
    """(signed change vs the preceding year in bps, whether clause (Q) needs an
    explanation for it).

    Measured against the MAGNITUDE of the prior year, so a ratio that goes from
    -0.2 to -0.3 is a 50% worsening rather than a -50% one. Where the prior year
    is zero and this year is not, the change is undefined as a percentage and
    every such move is material by definition — so it is flagged with no number
    rather than divided by zero.
    """
    if current_bps is None or prior_bps is None:
        return None, False
    if prior_bps == 0:
        return (None, True) if current_bps != 0 else (0, False)
    change = (current_bps - prior_bps) * BPS // abs(prior_bps)
    return change, abs(change) > VARIANCE_THRESHOLD_BPS


@dataclass
class Components:
    """The Schedule III amounts every ratio is built from, for ONE year.

    Averages need both years, so this holds one year's closing position and the
    caller pairs two of them.
    """
    # Balance sheet
    share_capital: int = 0
    reserves: int = 0
    long_term_borrowings: int = 0
    short_term_borrowings: int = 0
    deferred_tax_liability: int = 0
    trade_payables: int = 0
    other_current_liabilities: int = 0
    inventories: int = 0
    trade_receivables: int = 0
    cash: int = 0
    short_term_loans_advances: int = 0
    other_current_assets: int = 0
    tangible: int = 0
    intangible: int = 0
    long_term_investments: int = 0
    # P&L
    revenue_from_operations: int = 0
    other_income: int = 0
    cost_of_materials: int = 0
    employee_benefits: int = 0
    finance_costs: int = 0
    depreciation: int = 0
    other_expenses: int = 0
    tax_expense: int = 0
    # Read off account subtypes rather than the P&L caption — see the module
    # docstring. None means the chart tags nothing as investment income, which
    # is not the same as zero.
    investment_income: Optional[int] = None

    @property
    def shareholders_funds(self) -> int:
        return self.share_capital + self.reserves

    @property
    def total_debt(self) -> int:
        return self.long_term_borrowings + self.short_term_borrowings

    @property
    def current_assets(self) -> int:
        return (self.inventories + self.trade_receivables + self.cash
                + self.short_term_loans_advances + self.other_current_assets)

    @property
    def current_liabilities(self) -> int:
        return (self.short_term_borrowings + self.trade_payables
                + self.other_current_liabilities)

    @property
    def working_capital(self) -> int:
        return self.current_assets - self.current_liabilities

    @property
    def total_revenue(self) -> int:
        return self.revenue_from_operations + self.other_income

    @property
    def total_expenses(self) -> int:
        return (self.cost_of_materials + self.employee_benefits + self.finance_costs
                + self.depreciation + self.other_expenses)

    @property
    def profit_before_tax(self) -> int:
        return self.total_revenue - self.total_expenses

    @property
    def profit_after_tax(self) -> int:
        return self.profit_before_tax - self.tax_expense

    @property
    def ebit(self) -> int:
        """Profit before interest and tax. Finance costs are added back because
        capital employed includes the debt that produced them."""
        return self.profit_before_tax + self.finance_costs

    @property
    def capital_employed(self) -> int:
        """Shareholders' funds + total debt + deferred tax liability — the
        funding side, which is what "employed" means here."""
        return self.shareholders_funds + self.total_debt + self.deferred_tax_liability


def _investment_income(pl: dict) -> Optional[int]:
    """Income the chart tags as coming from investments, or None if it tags
    none. Reads subtypes, not the Schedule III caption — see the module
    docstring."""
    total, tagged = 0, False
    for ln in pl.get("revenue", {}).get("lines", []):
        sub = (ln.get("account_subtype") or "").lower()
        if any(k in sub for k in _INVESTMENT_INCOME_SUBTYPES):
            total += int(ln.get("amount_paise") or 0)
            tagged = True
    return total if tagged else None


def components_from(pl: dict, bs: dict) -> Components:
    """One year's amounts, bucketed by the SAME function that builds the
    statements (schedule_iii.bucket_amounts), so the ratio note and the balance
    sheet it annotates cannot disagree."""
    b, p = bucket_amounts(pl, bs)
    return Components(
        share_capital=b.get("Share Capital", 0),
        reserves=b.get("Reserves & Surplus", 0),
        long_term_borrowings=b.get("Long Term Borrowings", 0),
        short_term_borrowings=b.get("Short Term Borrowings", 0),
        deferred_tax_liability=b.get("Deferred Tax Liability", 0),
        trade_payables=b.get("Trade Payables", 0),
        other_current_liabilities=b.get("Other Current Liabilities", 0),
        inventories=b.get("Inventories", 0),
        trade_receivables=b.get("Trade Receivables", 0),
        cash=b.get("Cash & Cash Equivalents", 0),
        short_term_loans_advances=b.get("Short Term Loans & Advances", 0),
        other_current_assets=b.get("Other Current Assets", 0),
        tangible=b.get("Tangible Fixed Assets", 0),
        intangible=b.get("Intangible Fixed Assets", 0),
        long_term_investments=b.get("Long Term Investments", 0),
        revenue_from_operations=p.get("Revenue from Operations", 0),
        other_income=p.get("Other Income", 0),
        cost_of_materials=p.get("Cost of Materials Consumed", 0),
        employee_benefits=p.get("Employee Benefit Expense", 0),
        finance_costs=p.get("Finance Costs", 0),
        depreciation=p.get("Depreciation & Amortisation", 0),
        other_expenses=p.get("Other Expenses", 0),
        tax_expense=p.get("Tax Expense", 0),
        investment_income=_investment_income(pl),
    )


def _avg(current: int, prior: Optional[int]) -> tuple[int, str]:
    """(average of opening and closing, how to describe it).

    With no preceding year there is no opening balance to average, and the
    closing figure is the honest substitute — but the disclosure has to SAY so,
    because a turnover ratio on a closing balance is not the same measure.
    """
    if prior is None:
        return current, "closing balance (no preceding year on record)"
    return (current + prior) // 2, "average of opening and closing balances"


# ── The eleven ─────────────────────────────────────────────────────────────
# Order and clause letters as Schedule III lists them. The numerator and
# denominator labels are the disclosure clause (Q) demands, not commentary.

GAP_DSCR = (
    "debt_service_principal_unknown",
    "Debt Service Coverage Ratio needs the PRINCIPAL repaid on long-term "
    "borrowings during the year. The books hold the movement in the borrowing "
    "balance, which is drawdowns less repayments — using it would overstate "
    "cover for any client that borrowed again in the same year, and this is a "
    "ratio lenders read. Record the principal repaid to compute it.",
)

GAP_ROI = (
    "investment_income_not_tagged",
    "Return on Investment needs income FROM INVESTMENTS. No income account in "
    "this client's chart is tagged as dividend, interest or investment income, "
    "so there is nothing to compute from. A zero would claim the investments "
    "earned nothing.",
)

GAP_NO_PRIOR = (
    "no_preceding_year",
    "No preceding year is on record, so the 25% variance test in clause (Q) "
    "cannot run and the turnover ratios use closing balances rather than "
    "averages. Both are noted on the ratios themselves.",
)


def build(current: Components, prior: Optional[Components] = None,
          principal_repaid_paise: Optional[int] = None,
          explanations: Optional[dict[str, str]] = None) -> dict:
    """The clause (Q) ratio table for one year, against its preceding year.

    `principal_repaid_paise` is the one figure a human supplies — see GAP_DSCR.
    `explanations` maps a ratio key to the CA's words for a >25% movement.
    """
    expl = explanations or {}

    def prior_of(fn):
        """The same ratio a year earlier, or None where there is no prior year.
        Computed by running the identical function over the prior Components, so
        the two years cannot be computed differently."""
        if prior is None:
            return None
        return fn(prior, None)

    rows: list[Ratio] = []

    def add(key: str, clause: str, label: str, unit: str,
            num: Optional[Component], den: Optional[Component],
            prior_bps: Optional[int] = None,
            unavailable_reason: Optional[str] = None) -> None:
        value = None if unavailable_reason else ratio_bps(num.paise, den.paise) if num and den else None
        change, needs = variance(value, prior_bps)
        rows.append(Ratio(
            key=key, clause=clause, label=label, unit=unit,
            numerator=num, denominator=den, value_bps=value,
            prior_value_bps=prior_bps, variance_bps=change,
            needs_explanation=needs, unavailable_reason=unavailable_reason,
            explanation=expl.get(key),
        ))

    # (a) Current Ratio = Current Assets / Current Liabilities
    add("current_ratio", "(a)", "Current Ratio", UNIT_TIMES,
        Component("Current Assets", current.current_assets),
        Component("Current Liabilities", current.current_liabilities),
        prior_of(lambda c, _: ratio_bps(c.current_assets, c.current_liabilities)))

    # (b) Debt-Equity Ratio = Total Debt / Shareholders' Equity
    add("debt_equity", "(b)", "Debt-Equity Ratio", UNIT_TIMES,
        Component("Total Debt (long term + short term borrowings)", current.total_debt),
        Component("Shareholders' Equity (share capital + reserves & surplus)",
                  current.shareholders_funds),
        prior_of(lambda c, _: ratio_bps(c.total_debt, c.shareholders_funds)))

    # (c) Debt Service Coverage Ratio
    #     = Earnings available for debt service / Debt service
    #     Earnings available = PAT + depreciation + finance costs (the non-cash
    #     and financing charges already deducted). Debt service = finance costs
    #     + principal repaid, and the principal is what the books do not hold.
    if principal_repaid_paise is None:
        add("dscr", "(c)", "Debt Service Coverage Ratio", UNIT_TIMES,
            Component("Earnings available for debt service "
                      "(profit after tax + depreciation + finance costs)",
                      current.profit_after_tax + current.depreciation + current.finance_costs),
            None, None, unavailable_reason=GAP_DSCR[1])
    else:
        earnings = current.profit_after_tax + current.depreciation + current.finance_costs
        service = current.finance_costs + principal_repaid_paise
        add("dscr", "(c)", "Debt Service Coverage Ratio", UNIT_TIMES,
            Component("Earnings available for debt service "
                      "(profit after tax + depreciation + finance costs)", earnings),
            Component("Debt service (finance costs + principal repaid)", service))

    # (d) Return on Equity = Profit after tax / Average shareholders' equity
    eq_avg, eq_basis = _avg(current.shareholders_funds,
                            prior.shareholders_funds if prior else None)
    add("return_on_equity", "(d)", "Return on Equity Ratio", UNIT_PERCENT,
        Component("Profit after tax", current.profit_after_tax),
        Component(f"Shareholders' Equity — {eq_basis}", eq_avg),
        prior_of(lambda c, _: ratio_bps(c.profit_after_tax, c.shareholders_funds)))

    # (e) Inventory turnover = Cost of materials consumed / Average inventory
    inv_avg, inv_basis = _avg(current.inventories, prior.inventories if prior else None)
    add("inventory_turnover", "(e)", "Inventory turnover ratio", UNIT_TIMES,
        Component("Cost of Materials Consumed", current.cost_of_materials),
        Component(f"Inventory — {inv_basis}", inv_avg),
        prior_of(lambda c, _: ratio_bps(c.cost_of_materials, c.inventories)))

    # (f) Trade Receivables turnover = Revenue from operations / Average
    #     trade receivables. The statute's measure is net CREDIT sales; nothing
    #     here separates cash from credit sales, so revenue from operations is
    #     used and the numerator label says exactly that — which is the
    #     disclosure clause (Q) asks for.
    tr_avg, tr_basis = _avg(current.trade_receivables,
                            prior.trade_receivables if prior else None)
    add("receivables_turnover", "(f)", "Trade Receivables turnover ratio", UNIT_TIMES,
        Component("Revenue from Operations (cash and credit sales are not "
                  "separately recorded)", current.revenue_from_operations),
        Component(f"Trade Receivables — {tr_basis}", tr_avg),
        prior_of(lambda c, _: ratio_bps(c.revenue_from_operations, c.trade_receivables)))

    # (g) Trade Payables turnover = Net credit purchases / Average trade
    #     payables. Same disclosure point as (f).
    tp_avg, tp_basis = _avg(current.trade_payables, prior.trade_payables if prior else None)
    add("payables_turnover", "(g)", "Trade payables turnover ratio", UNIT_TIMES,
        Component("Cost of Materials Consumed (cash and credit purchases are "
                  "not separately recorded)", current.cost_of_materials),
        Component(f"Trade Payables — {tp_basis}", tp_avg),
        prior_of(lambda c, _: ratio_bps(c.cost_of_materials, c.trade_payables)))

    # (h) Net capital turnover = Revenue from operations / Working capital
    add("net_capital_turnover", "(h)", "Net capital turnover ratio", UNIT_TIMES,
        Component("Revenue from Operations", current.revenue_from_operations),
        Component("Working Capital (current assets less current liabilities)",
                  current.working_capital),
        prior_of(lambda c, _: ratio_bps(c.revenue_from_operations, c.working_capital)))

    # (i) Net profit ratio = Profit after tax / Revenue from operations
    add("net_profit_ratio", "(i)", "Net profit ratio", UNIT_PERCENT,
        Component("Profit after tax", current.profit_after_tax),
        Component("Revenue from Operations", current.revenue_from_operations),
        prior_of(lambda c, _: ratio_bps(c.profit_after_tax, c.revenue_from_operations)))

    # (j) Return on Capital employed = EBIT / Capital employed
    add("return_on_capital_employed", "(j)", "Return on Capital employed", UNIT_PERCENT,
        Component("Earnings before interest and tax (profit before tax + finance costs)",
                  current.ebit),
        Component("Capital Employed (shareholders' equity + total debt + "
                  "deferred tax liability)", current.capital_employed),
        prior_of(lambda c, _: ratio_bps(c.ebit, c.capital_employed)))

    # (k) Return on investment = Income from investments / Average investments
    if current.investment_income is None:
        add("return_on_investment", "(k)", "Return on investment", UNIT_PERCENT,
            None, Component("Investments", current.long_term_investments),
            None, unavailable_reason=GAP_ROI[1])
    else:
        li_avg, li_basis = _avg(current.long_term_investments,
                                prior.long_term_investments if prior else None)
        add("return_on_investment", "(k)", "Return on investment", UNIT_PERCENT,
            Component("Income from investments (accounts tagged dividend, "
                      "interest or investment income)", current.investment_income),
            Component(f"Investments — {li_basis}", li_avg),
            prior_of(lambda c, _: ratio_bps(c.investment_income or 0,
                                            c.long_term_investments)))

    gaps: list[tuple[str, str]] = []
    if principal_repaid_paise is None:
        gaps.append(GAP_DSCR)
    if current.investment_income is None:
        gaps.append(GAP_ROI)
    if prior is None:
        gaps.append(GAP_NO_PRIOR)

    return {
        "statute": ("Schedule III to the Companies Act 2013, Division I, General "
                    "Instructions — Additional Regulatory Information, clause (Q), "
                    "as inserted by MCA Notification G.S.R. 207(E) dated "
                    "24 March 2021"),
        "variance_threshold_bps": VARIANCE_THRESHOLD_BPS,
        "has_prior_year": prior is not None,
        "ratios": [r.as_dict() for r in rows],
        "needs_explanation_count": sum(
            1 for r in rows if r.needs_explanation and not r.explanation),
        "gaps": [{"code": c, "message": m} for c, m in gaps],
    }
