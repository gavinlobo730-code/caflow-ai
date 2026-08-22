"""
Cash Flow Statement (AS-3 / Companies Act 2013 Schedule III) — correctness tests
for the remediated entry-level method (post-audit of c78c7f1).

Proves, per scenario, that:
  • Investing/Financing follow ACTUAL cash legs (full disposal proceeds in
    investing; gain/loss NOT shown as operating).
  • Depreciation and year-end closing entries (no cash leg) are EXCLUDED, and
    depreciation is ADDED BACK in the operating reconciliation.
  • Reconciliation is meaningful: O+I+F == net change == independent(closing −
    opening), AND the indirect operating breakdown ties to operating cash.
All integer paise.
"""
from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)

FIRM, CLIENT = "firm-cf", "client-cf"
START, END = "2026-04-01", "2027-03-31"
PRE = "2026-03-02"   # before the window → affects opening cash only

ACCOUNTS = [
    Account("bank",   "1000", "Bank — HDFC",            "Asset",     "Bank",              system_key="bank"),
    Account("ar",     "1100", "Trade Receivables",      "Asset",     "Receivable",        system_key="ar"),
    Account("gstout", "2200", "GST Output Payable",     "Liability", "Tax",               system_key="gst_output"),
    Account("ap",     "2150", "Trade Payables",         "Liability", "Payable",           system_key="ap"),
    Account("rev",    "4000", "Professional Fees",      "Revenue",   "Professional Fees"),
    Account("exp",    "5000", "Office Rent",            "Expense",   "Operating Expense"),
    Account("fa",     "1500", "Office Equipment",       "Asset",     "Fixed Asset"),
    Account("accdep", "1599", "Accumulated Depreciation","Asset",    "Fixed Asset"),
    Account("depexp", "5900", "Depreciation Expense",   "Expense",   "Depreciation"),
    Account("gain",   "4900", "Profit on Asset Disposal","Revenue",  "Other Income"),
    Account("loss",   "5950", "Loss on Asset Disposal", "Expense",   "Other Expense"),
    Account("loan",   "2500", "Term Loan",              "Liability", "Loan"),
    Account("cap",    "3000", "Partner Capital Account","Equity",    "Capital"),
    Account("retd",   "3100", "Retained Earnings",      "Equity",    "Retained"),
    Account("inv",    "1200", "Inventory",              "Asset",     "Inventory"),
    Account("obe",    "3050", "Opening Balance Equity", "Equity",    "Capital"),
]


def je(jid, lines, date="2026-06-01"):
    return JournalEntry(id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM,
                        entry_type="x", lines=tuple(JournalLine(*l) for l in lines))


# ₹10,000 opening cash, introduced before the window (capital). Affects opening only.
OPENING = je("ob", [("bank", 1000000, 0), ("cap", 0, 1000000)], PRE)


def svc_for(entries):
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(entries)))


def cf(svc, basis="accrual"):
    return svc.cash_flow_statement(FIRM, CLIENT, START, END, basis=basis)


def total(s, sec):
    return s[sec]["total_paise"]


def line_for(s, sec, aid):
    return next((l for l in s[sec]["lines"] if l["account_id"] == aid), None)


def assert_reconciles(s):
    assert s["reconciles"] is True
    assert total(s, "operating") + total(s, "investing") + total(s, "financing") == s["net_change_paise"]
    assert s["closing_cash_paise"] - s["opening_cash_paise"] == s["net_change_paise"]
    assert s["operating_reconciliation"]["ties_out"] is True


# ── 1. Depreciation ───────────────────────────────────────────────────────────

def test_depreciation_excluded_and_added_back():
    s = cf(svc_for([OPENING, je("d", [("depexp", 10000, 0), ("accdep", 0, 10000)])]))
    assert total(s, "operating") == 0          # non-cash → no operating cash
    assert total(s, "investing") == 0          # NOT mis-posted to investing
    assert total(s, "financing") == 0
    assert s["net_change_paise"] == 0
    assert s["non_cash_excluded_count"] == 1
    r = s["operating_reconciliation"]
    assert r["net_profit_paise"] == -10000     # expense reduced profit
    assert r["depreciation_addback_paise"] == 10000   # …added back
    assert r["net_cash_operating_paise"] == 0
    assert s["opening_cash_paise"] == 1000000 and s["closing_cash_paise"] == 1000000
    assert_reconciles(s)


# ── 2. Asset purchase ─────────────────────────────────────────────────────────

def test_asset_purchase_is_investing_outflow():
    s = cf(svc_for([OPENING, je("p", [("fa", 50000, 0), ("bank", 0, 50000)])]))
    assert total(s, "investing") == -50000
    assert line_for(s, "investing", "fa")["amount_paise"] == -50000
    assert total(s, "operating") == 0 and total(s, "financing") == 0
    assert s["net_change_paise"] == -50000
    assert s["closing_cash_paise"] == 950000
    assert_reconciles(s)


# ── 3. Asset disposal — gain ──────────────────────────────────────────────────

def test_asset_disposal_gain_full_proceeds_in_investing():
    pre = [OPENING,
           je("acq", [("fa", 100000, 0), ("bank", 0, 100000)], PRE),
           je("dep", [("depexp", 60000, 0), ("accdep", 0, 60000)], PRE)]
    # cost 100000, accum dep 60000, WDV 40000, proceeds 50000, gain 10000
    disp = je("disp", [("accdep", 60000, 0), ("bank", 50000, 0), ("fa", 0, 100000), ("gain", 0, 10000)])
    s = cf(svc_for(pre + [disp]))
    assert total(s, "investing") == 50000      # FULL proceeds, not WDV (40000)
    assert total(s, "operating") == 0          # gain NOT shown as operating cash
    assert total(s, "financing") == 0
    r = s["operating_reconciliation"]
    assert r["net_profit_paise"] == 10000          # gain sits in P&L…
    assert r["non_operating_adjust_paise"] == -10000   # …and is removed from operating
    assert r["net_cash_operating_paise"] == 0
    assert s["opening_cash_paise"] == 900000        # 1,000,000 − 100,000 acquisition
    assert s["closing_cash_paise"] == 950000
    assert_reconciles(s)


# ── 4. Asset disposal — loss ──────────────────────────────────────────────────

def test_asset_disposal_loss_full_proceeds_loss_added_back():
    pre = [OPENING,
           je("acq", [("fa", 100000, 0), ("bank", 0, 100000)], PRE),
           je("dep", [("depexp", 60000, 0), ("accdep", 0, 60000)], PRE)]
    # WDV 40000, proceeds 30000, loss 10000
    disp = je("disp", [("accdep", 60000, 0), ("bank", 30000, 0), ("loss", 10000, 0), ("fa", 0, 100000)])
    s = cf(svc_for(pre + [disp]))
    assert total(s, "investing") == 30000      # full proceeds
    assert total(s, "operating") == 0
    r = s["operating_reconciliation"]
    assert r["net_profit_paise"] == -10000         # loss in P&L…
    assert r["non_operating_adjust_paise"] == 10000    # …added back (removed from operating)
    assert r["net_cash_operating_paise"] == 0
    assert_reconciles(s)


# ── 5. Loan proceeds ──────────────────────────────────────────────────────────

def test_loan_proceeds_financing_inflow():
    s = cf(svc_for([je("l", [("bank", 100000, 0), ("loan", 0, 100000)])]))
    assert total(s, "financing") == 100000
    assert line_for(s, "financing", "loan")["amount_paise"] == 100000
    assert total(s, "operating") == 0 and total(s, "investing") == 0
    assert s["net_change_paise"] == 100000
    assert_reconciles(s)


# ── 6. Loan repayment ─────────────────────────────────────────────────────────

def test_loan_repayment_financing_outflow():
    s = cf(svc_for([OPENING, je("r", [("loan", 30000, 0), ("bank", 0, 30000)])]))
    assert total(s, "financing") == -30000
    assert line_for(s, "financing", "loan")["amount_paise"] == -30000
    assert s["net_change_paise"] == -30000
    assert s["closing_cash_paise"] == 970000
    assert_reconciles(s)


# ── 7. Capital introduction ───────────────────────────────────────────────────

def test_capital_introduction_financing_inflow():
    s = cf(svc_for([je("c", [("bank", 500000, 0), ("cap", 0, 500000)])]))
    assert total(s, "financing") == 500000
    assert line_for(s, "financing", "cap")["amount_paise"] == 500000
    assert s["net_change_paise"] == 500000
    assert_reconciles(s)


# ── 8. Drawings ───────────────────────────────────────────────────────────────

def test_drawings_financing_outflow():
    s = cf(svc_for([OPENING, je("dr", [("cap", 20000, 0), ("bank", 0, 20000)])]))
    assert total(s, "financing") == -20000
    assert line_for(s, "financing", "cap")["amount_paise"] == -20000
    assert total(s, "operating") == 0 and total(s, "investing") == 0
    assert s["net_change_paise"] == -20000
    assert_reconciles(s)


# ── 9. GST liability movements ────────────────────────────────────────────────

def test_gst_movements_are_operating():
    s = cf(svc_for([
        je("sale",  [("bank", 11800, 0), ("rev", 0, 10000), ("gstout", 0, 1800)]),
        je("remit", [("gstout", 1800, 0), ("bank", 0, 1800)], "2026-06-20"),
    ]))
    assert total(s, "operating") == 10000      # 11,800 collected − 1,800 GST remitted
    assert total(s, "investing") == 0 and total(s, "financing") == 0
    assert line_for(s, "investing", "gstout") is None
    assert line_for(s, "financing", "gstout") is None
    r = s["operating_reconciliation"]
    assert r["net_profit_paise"] == 10000
    assert r["net_cash_operating_paise"] == 10000
    assert s["net_change_paise"] == 10000
    assert_reconciles(s)


# ── 10. Year-end closing entries ──────────────────────────────────────────────

def test_year_end_close_excluded_no_distortion():
    s = cf(svc_for([
        je("earn",  [("ar", 10000, 0), ("rev", 0, 10000)]),               # credit sale (earned)
        je("close", [("rev", 10000, 0), ("retd", 0, 10000)], "2027-03-31"),  # year-end close
    ]))
    assert total(s, "operating") == 0
    assert total(s, "investing") == 0
    assert total(s, "financing") == 0          # retained-earnings close is NOT financing
    assert line_for(s, "financing", "retd") is None
    assert s["net_change_paise"] == 0
    assert s["non_cash_excluded_count"] == 2
    r = s["operating_reconciliation"]
    assert r["net_profit_paise"] == 10000          # earned profit, NOT zeroed by the close
    assert r["working_capital_change_paise"] == -10000  # offset by the A/R increase
    assert r["net_cash_operating_paise"] == 0
    assert_reconciles(s)


# ── Opening balances (the gap the year-end guard did not cover) ──────────────
# Opening balances are the SAME shape as the year-end close — a non-cash entry
# with an equity leg — but they carry no P&L leg, so a guard written as
# `has_equity and has_pl` let them through.
#
# What that cost: the equity leg is classified financing, so working_capital
# skips it; there is no bank leg, so financing_cash never sees it. The operating
# counterpart legs ARE counted. The indirect reconciliation ends up short by
# exactly the equity movement.
#
# Found on a live client: Q1 out by +₹40,54,000 and Q2 by −₹40,54,000, opening
# balances posted 1 April and corrected in July. The full year netted to zero
# and showed a green tick. Only splitting it into quarters made it visible —
# and for a client whose opening balances are never reversed, the ANNUAL
# statement is wrong too, with nothing to cancel it.

# The production shape, at legible scale: an opening-balance batch that brings
# in stock and payables against Opening Balance Equity, and the separate
# opening-stock entry that offsets part of it. Net equity movement ₹400 debit.
OB_BALANCE = je("ob-bal",   [("obe", 103000, 0), ("inv", 0, 99000), ("ap", 0, 4000)], "2026-04-01")
OB_STOCK   = je("ob-stock", [("inv", 99000, 0), ("obe", 0, 99000)], "2026-04-01")
CREDIT_SALE = je("sale", [("ar", 10000, 0), ("rev", 0, 10000)], "2026-06-01")


def test_opening_balances_do_not_break_the_reconciliation():
    """The regression. Without the fix the indirect breakdown is short by the
    ₹400 equity movement and ties_out is false — which is what the CA sees as
    'Cash flow does not reconcile to the change in cash balances'."""
    s = cf(svc_for([OB_BALANCE, OB_STOCK, CREDIT_SALE]))
    assert_reconciles(s)


def test_opening_balances_are_excluded_whole_not_half():
    """The precise defect: the equity leg was dropped while its INVENTORY and
    PAYABLES counterparts were counted as working capital. Excluding one leg of
    a balanced entry is what created the residual, so the assertion is that
    working capital reflects the trading only."""
    s = cf(svc_for([OB_BALANCE, OB_STOCK, CREDIT_SALE]))
    r = s["operating_reconciliation"]
    assert r["net_profit_paise"] == 10000
    assert r["working_capital_change_paise"] == -10000, (
        "opening stock/payables leaked into working capital — they are an "
        "opening position, not a movement of the period"
    )
    assert r["net_cash_operating_paise"] == 0


def test_opening_balance_equity_is_not_reported_as_financing():
    """It has no cash leg, so it is not a financing FLOW either. It must simply
    be absent — not moved from one wrong place to another."""
    s = cf(svc_for([OB_BALANCE, OB_STOCK, CREDIT_SALE]))
    assert line_for(s, "financing", "obe") is None
    assert total(s, "financing") == 0


def test_a_sub_annual_window_reconciles_too():
    """The live symptom. The annual view hid this because the client's opening
    balances were later corrected and the two cancelled; a quarter does not get
    that luck, and neither does an ordinary client's full year."""
    svc = svc_for([OB_BALANCE, OB_STOCK, CREDIT_SALE])
    q1 = svc.cash_flow_statement(FIRM, CLIENT, "2026-04-01", "2026-06-30")
    assert_reconciles(q1)
    assert q1["operating_reconciliation"]["net_profit_paise"] == 10000


def test_every_quarter_of_the_year_reconciles_independently():
    """Each window judged on its own, which is what the quarterly columns do."""
    svc = svc_for([OB_BALANCE, OB_STOCK, CREDIT_SALE])
    for start, end in (("2026-04-01", "2026-06-30"), ("2026-07-01", "2026-09-30"),
                       ("2026-10-01", "2026-12-31"), ("2027-01-01", "2027-03-31")):
        s = svc.cash_flow_statement(FIRM, CLIENT, start, end)
        assert s["operating_reconciliation"]["ties_out"] is True, f"{start}..{end} does not tie out"


def test_the_quarters_sum_to_the_year():
    """Flows are period-additive. If a quarter double-counted or dropped an
    entry at a boundary, the year would stop agreeing with its parts."""
    svc = svc_for([OB_BALANCE, OB_STOCK, CREDIT_SALE])
    quarters = [svc.cash_flow_statement(FIRM, CLIENT, a, b) for a, b in (
        ("2026-04-01", "2026-06-30"), ("2026-07-01", "2026-09-30"),
        ("2026-10-01", "2026-12-31"), ("2027-01-01", "2027-03-31"))]
    year = cf(svc)
    for key in ("net_profit_paise", "working_capital_change_paise", "net_cash_operating_paise"):
        assert sum(q["operating_reconciliation"][key] for q in quarters) == \
               year["operating_reconciliation"][key], key


def test_depreciation_survives_the_wider_exclusion():
    """The scoping decision, pinned. Excluding every non-cash entry that touches
    a NON-OPERATING account — the broader rule — would take depreciation with
    it, since Dr Depreciation / Cr Accumulated Depreciation is non-cash and its
    credit leg is a fixed asset. The guard is scoped to EQUITY for this reason,
    and this asserts the two coexist."""
    s = cf(svc_for([
        OB_BALANCE, OB_STOCK, CREDIT_SALE,
        je("dep", [("depexp", 3000, 0), ("accdep", 0, 3000)], "2026-09-30"),
    ]))
    r = s["operating_reconciliation"]
    assert r["depreciation_addback_paise"] == 3000, "the add-back was lost"
    assert r["net_profit_paise"] == 10000 - 3000
    assert_reconciles(s)


def test_capital_introduced_in_cash_is_still_financing():
    """The guard is for NON-cash equity entries only. Money actually put into
    the business is a financing inflow and must not be swept up."""
    s = cf(svc_for([OB_BALANCE, OB_STOCK,
                    je("intro", [("bank", 50000, 0), ("cap", 0, 50000)], "2026-05-01")]))
    assert total(s, "financing") == 50000
    assert s["net_change_paise"] == 50000
    assert_reconciles(s)


# ── Cross-scenario invariants ─────────────────────────────────────────────────

def test_combined_ledger_reconciles_and_classifies():
    s = cf(svc_for([
        OPENING,
        je("sale",  [("bank", 59000, 0), ("rev", 0, 50000), ("gstout", 0, 9000)], "2026-04-10"),
        je("rent",  [("exp", 20000, 0), ("bank", 0, 20000)], "2026-04-15"),
        je("buy",   [("fa", 30000, 0), ("bank", 0, 30000)], "2026-05-01"),
        je("loan",  [("bank", 80000, 0), ("loan", 0, 80000)], "2026-05-10"),
        je("dep",   [("depexp", 5000, 0), ("accdep", 0, 5000)], "2026-06-30"),
        je("draw",  [("cap", 15000, 0), ("bank", 0, 15000)], "2026-07-01"),
    ]))
    assert total(s, "operating") == 39000      # 59,000 in − 20,000 rent
    assert total(s, "investing") == -30000     # asset purchase
    assert total(s, "financing") == 80000 - 15000  # loan in − drawings
    assert s["net_change_paise"] == 39000 - 30000 + 65000
    assert s["opening_cash_paise"] == 1000000
    assert s["closing_cash_paise"] == 1000000 + s["net_change_paise"]
    assert s["operating_reconciliation"]["depreciation_addback_paise"] == 5000
    assert_reconciles(s)


def test_basis_param_is_accepted_and_cash_totals_invariant():
    entries = [je("sale", [("bank", 11800, 0), ("rev", 0, 10000), ("gstout", 0, 1800)])]
    accrual = cf(svc_for(entries), "accrual")
    cash = cf(svc_for(entries), "cash")
    assert cash.get("basis") == "cash"
    # A cash flow statement is intrinsically actual-cash → identical totals.
    for sec in ("operating", "investing", "financing"):
        assert total(accrual, sec) == total(cash, sec)
    assert accrual["net_change_paise"] == cash["net_change_paise"] == 11800


def test_integer_paise_only():
    s = cf(svc_for([OPENING, je("x", [("bank", 333, 0), ("rev", 0, 333)])]))
    for k in ("net_change_paise", "opening_cash_paise", "closing_cash_paise"):
        assert isinstance(s[k], int)
    for sec in ("operating", "investing", "financing"):
        assert isinstance(total(s, sec), int)
        assert all(isinstance(l["amount_paise"], int) for l in s[sec]["lines"])
    assert_reconciles(s)


# ── 11. reconciles=False on unbalanced journal ────────────────────────────────

def test_reconciles_false_on_unbalanced_journal():
    # Bank receives ₹100 (10 000p) but only ₹80 (8 000p) is credited to revenue.
    # operating_cash = 10 000; indirect check = net_profit 8 000 ≠ 10 000 → False.
    # Proves the reconciliation is not tautological.
    s = cf(svc_for([je("unbal", [("bank", 10000, 0), ("rev", 0, 8000)])]))
    assert s["reconciles"] is False
    assert s["operating_reconciliation"]["ties_out"] is False
    assert s["net_change_paise"] == 10000          # actual bank cash is reported correctly
    assert total(s, "operating") == 10000
    assert s["operating_reconciliation"]["net_profit_paise"] == 8000
