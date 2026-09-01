"""
The Schedule III ratio note must tie to the statements it is a note to.

WHY THIS FILE EXISTS
    Clause (Q) ratios are a NOTE to the balance sheet. If the "Trade
    Receivables" a ratio divides by differs from the "Trade Receivables" printed
    on the face of the statement, the CA signs two numbers that contradict each
    other — and nothing on either page says which is wrong.

    domain/reporting/ratios.components_from calls schedule_iii.bucket_amounts,
    the same function build_schedule_iii calls, so the two CANNOT differ. This
    proves it over a real ledger rather than trusting the call graph: every
    component is compared against the corresponding line of the built statement.

    tests/test_schedule_iii_ratios.py has the statutory reading; this has the
    wiring, end to end through the reporting engine and the router.
"""
import pytest
from fastapi import HTTPException

from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)
from domain.reporting import ratios as R
from domain.reporting.schedule_iii import build_schedule_iii

FIRM, CLIENT = "firm-ratio", "client-ratio"
FY, START, END = "2026-27", "2026-04-01", "2027-03-31"
L = 1_00_000_00

ACCOUNTS = [
    Account("bank",   "1000", "Bank — HDFC",            "Asset",     "Bank", system_key="bank"),
    Account("ar",     "1100", "Trade Receivables",      "Asset",     "Receivable", system_key="ar"),
    Account("inv",    "1200", "Inventory",              "Asset",     "Inventory"),
    Account("fa",     "1500", "Plant & Machinery",      "Asset",     "Fixed Asset"),
    Account("lti",    "1600", "Long Term Investments",  "Asset",     "Long Term Investment"),
    Account("ap",     "2150", "Trade Payables",         "Liability", "Payable", system_key="ap"),
    Account("stl",    "2400", "Bank Overdraft",         "Liability", "Short Term Loan"),
    Account("ltl",    "2500", "Term Loan",              "Liability", "Long Term Loan"),
    Account("cap",    "3000", "Share Capital",          "Equity",    "Share Capital"),
    Account("retd",   "3100", "Retained Earnings",      "Equity",    "Retained"),
    Account("rev",    "4000", "Sales",                  "Revenue",   "Sales"),
    Account("divi",   "4800", "Dividend Income",        "Revenue",   "Dividend Income"),
    Account("cogs",   "5000", "Cost of Materials",      "Expense",   "Raw Material"),
    Account("sal",    "5100", "Salaries",               "Expense",   "Employee Benefit"),
    Account("int",    "5200", "Interest on Term Loan",  "Expense",   "Finance Cost"),
    Account("dep",    "5900", "Depreciation",           "Expense",   "Depreciation"),
    Account("misc",   "5950", "Office Expenses",        "Expense",   "Operating Expense"),
]


def je(jid, lines, when="2026-06-01"):
    return JournalEntry(id=jid, entry_date=when, client_id=CLIENT, firm_id=FIRM,
                        entry_type="x", lines=tuple(JournalLine(*l) for l in lines))


ENTRIES = [
    # Opening position, posted on the first day of the year. Dated 2026-03-31
    # it would fall in FY 2025-26 and give that year a balance sheet, which is
    # correct behaviour and not what the "no preceding year" case below is for.
    je("open", [("bank", 3 * L, 0), ("inv", 2 * L, 0), ("fa", 10 * L, 0),
                ("lti", 5 * L, 0), ("cap", 0, 10 * L), ("ltl", 0, 8 * L),
                ("stl", 0, 2 * L)], "2026-04-01"),
    # The year.
    je("sale", [("ar", 60 * L, 0), ("rev", 0, 60 * L)], "2026-09-30"),
    je("recv", [("bank", 54 * L, 0), ("ar", 0, 54 * L)], "2026-12-31"),
    je("buy",  [("cogs", 36 * L, 0), ("ap", 0, 36 * L)], "2026-09-30"),
    je("pay",  [("ap", 33 * L, 0), ("bank", 0, 33 * L)], "2026-12-31"),
    je("wage", [("sal", 10 * L, 0), ("bank", 0, 10 * L)], "2027-01-31"),
    je("fin",  [("int", 1 * L, 0), ("bank", 0, 1 * L)], "2027-02-28"),
    je("dep",  [("dep", 2 * L, 0), ("fa", 0, 2 * L)], "2027-03-31"),
    je("othr", [("misc", 3 * L, 0), ("bank", 0, 3 * L)], "2027-03-15"),
    je("divd", [("bank", 1 * L, 0), ("divi", 0, 1 * L)], "2027-03-20"),
    je("stock", [("inv", 2 * L, 0), ("bank", 0, 2 * L)], "2027-03-25"),
]


@pytest.fixture()
def svc():
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(ENTRIES)))


def _statements(svc):
    pl = svc.profit_loss(FIRM, CLIENT, START, END, basis="accrual")
    bs = svc.balance_sheet(FIRM, CLIENT, END, basis="accrual")
    return pl, bs


def _line(doc_section, caption):
    for sec in doc_section:
        for ln in sec["lines"]:
            if ln["label"] == caption:
                return ln["paise"]
    raise AssertionError(f"{caption} is not on the statement")


# ── The tie ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("attr,caption", [
    ("share_capital",            "Share Capital"),
    ("reserves",                 "Reserves & Surplus"),
    ("long_term_borrowings",     "Long Term Borrowings"),
    ("short_term_borrowings",    "Short Term Borrowings"),
    ("trade_payables",           "Trade Payables"),
    ("other_current_liabilities", "Other Current Liabilities"),
    ("inventories",              "Inventories"),
    ("trade_receivables",        "Trade Receivables"),
    ("cash",                     "Cash & Cash Equivalents"),
    ("long_term_investments",    "Long Term Investments"),
])
def test_every_balance_sheet_component_equals_the_statement_line(svc, attr, caption):
    pl, bs = _statements(svc)
    doc = build_schedule_iii(pl, bs, START, END)
    c = R.components_from(pl, bs)
    sections = (doc["balance_sheet"]["equity_and_liabilities"]
                + doc["balance_sheet"]["assets"])
    assert getattr(c, attr) == _line(sections, caption), caption


@pytest.mark.parametrize("attr,caption", [
    ("revenue_from_operations", "Revenue from Operations"),
    ("other_income",            "Other Income"),
    ("cost_of_materials",       "Cost of Materials Consumed"),
    ("employee_benefits",       "Employee Benefit Expense"),
    ("finance_costs",           "Finance Costs"),
    ("depreciation",            "Depreciation & Amortisation Expense"),
    ("other_expenses",          "Other Expenses"),
])
def test_every_pl_component_equals_the_statement_line(svc, attr, caption):
    pl, bs = _statements(svc)
    doc = build_schedule_iii(pl, bs, START, END)
    c = R.components_from(pl, bs)
    sections = doc["profit_and_loss"]["revenue"] + doc["profit_and_loss"]["expenses"]
    assert getattr(c, attr) == _line(sections, caption), caption


def test_profit_after_tax_equals_the_statements(svc):
    pl, bs = _statements(svc)
    doc = build_schedule_iii(pl, bs, START, END)
    c = R.components_from(pl, bs)
    assert c.profit_after_tax == doc["profit_and_loss"]["profit_after_tax_paise"]
    assert c.total_revenue == doc["profit_and_loss"]["total_revenue_paise"]


def test_dividend_income_is_picked_up_as_investment_income(svc):
    """It is inside "Other Income" on the face of the P&L, and Return on
    Investment needs it separately."""
    pl, _bs = _statements(svc)
    c = R.components_from(pl, _statements(svc)[1])
    assert c.investment_income == 1 * L
    assert c.other_income == 1 * L, "and it stays in Other Income on the statement"


def test_the_note_computes_over_a_real_ledger(svc):
    pl, bs = _statements(svc)
    doc = R.build(R.components_from(pl, bs))
    current = next(r for r in doc["ratios"] if r["key"] == "current_ratio")
    assert current["value_bps"] is not None
    roi = next(r for r in doc["ratios"] if r["key"] == "return_on_investment")
    assert roi["value_bps"] == (1 * L) * R.BPS // (5 * L), "20% on 5 lakh of investments"


# ── The service ──────────────────────────────────────────────────────────────

def test_fy_bounds_and_preceding_year():
    from services import ratio_analysis_service as svc_mod
    assert svc_mod.fy_bounds("2026-27") == ("2026-04-01", "2027-03-31")
    assert svc_mod.preceding_fy("2026-27") == "2025-26"
    assert svc_mod.preceding_fy("2000-01") == "1999-00"


@pytest.mark.parametrize("bad", ["26-27", "twenty", "", None, "9999999-00"])
def test_a_malformed_financial_year_is_422(bad):
    from services import ratio_analysis_service as svc_mod
    with pytest.raises(HTTPException) as e:
        svc_mod.fy_bounds(bad)
    assert e.value.status_code == 422


def test_an_empty_preceding_year_is_treated_as_no_preceding_year(svc):
    """A client's first year on the platform has a preceding year of all zeros.
    Comparing against it makes every ratio an infinite move needing an
    explanation the CA cannot write, because nothing happened."""
    from services import ratio_analysis_service as svc_mod
    out = svc_mod.ratio_note(svc, None, FIRM, CLIENT, FY)
    assert out["has_prior_year"] is False
    assert out["preceding_fy"] is None
    assert "no_preceding_year" in [g["code"] for g in out["gaps"]]
    assert out["needs_explanation_count"] == 0


def test_the_note_is_dated_and_scoped(svc):
    from services import ratio_analysis_service as svc_mod
    out = svc_mod.ratio_note(svc, None, FIRM, CLIENT, FY)
    assert out["fy"] == FY
    assert out["period"] == {"start": START, "end": END}
    assert len(out["ratios"]) == 11


def test_the_note_refuses_a_firm_wide_request(svc):
    from services import ratio_analysis_service as svc_mod
    with pytest.raises(HTTPException) as e:
        svc_mod.ratio_note(svc, None, FIRM, "", FY)
    assert e.value.status_code == 422


# ── The endpoints ────────────────────────────────────────────────────────────

USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "p@f.in", "role": "Partner"}


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    import routers.accounting as ac
    monkeypatch.setattr(ac, "_prod_db", lambda: None)
    monkeypatch.setattr(ac, "assert_client_access", lambda *a, **k: None)


def test_the_ratio_endpoint_is_callable():
    import routers.accounting as ac
    out = ac.get_schedule_iii_ratios(client_id=CLIENT, fy=FY, current_user=USER)
    assert out["success"]
    assert len(out["data"]["ratios"]) == 11


def test_the_ratio_endpoint_rejects_a_malformed_year():
    import routers.accounting as ac
    with pytest.raises(HTTPException) as e:
        ac.get_schedule_iii_ratios(client_id=CLIENT, fy="26-27", current_user=USER)
    assert e.value.status_code == 422


def test_an_explanation_for_an_unknown_ratio_is_refused():
    import routers.accounting as ac
    from routers.accounting import RatioExplanationIn
    body = RatioExplanationIn(client_id=CLIENT, fy=FY, ratio_key="quick_ratio",
                              explanation="x")
    with pytest.raises(HTTPException) as e:
        ac.put_schedule_iii_ratio_explanation(body, USER)
    assert e.value.status_code == 422
    assert "unknown ratio" in str(e.value.detail)


def test_a_blank_explanation_is_refused_rather_than_stored():
    """An empty string would satisfy clause (Q) on paper and say nothing.
    Clearing is a delete, and has its own path."""
    import routers.accounting as ac
    from routers.accounting import RatioExplanationIn
    body = RatioExplanationIn(client_id=CLIENT, fy=FY, ratio_key="current_ratio",
                              explanation="   ")
    with pytest.raises(HTTPException) as e:
        ac.put_schedule_iii_ratio_explanation(body, USER)
    assert e.value.status_code == 422
    assert "cannot be blank" in str(e.value.detail)


def test_a_negative_principal_repaid_is_refused():
    import routers.accounting as ac
    from routers.accounting import RatioInputsIn
    body = RatioInputsIn(client_id=CLIENT, fy=FY, principal_repaid_paise=-1)
    with pytest.raises(HTTPException) as e:
        ac.put_schedule_iii_ratio_inputs(body, USER)
    assert e.value.status_code == 422
    assert "cannot be negative" in str(e.value.detail)


def test_clearing_the_principal_repaid_reaches_the_database_layer():
    """null must be distinguishable from "not sent" — a CA who entered a wrong
    figure has to be able to put the ratio back into its gap."""
    import routers.accounting as ac
    from routers.accounting import RatioInputsIn
    body = RatioInputsIn(client_id=CLIENT, fy=FY, principal_repaid_paise=None)
    with pytest.raises(HTTPException) as e:
        ac.put_schedule_iii_ratio_inputs(body, USER)
    assert e.value.status_code == 503, e.value.detail       # no DB in mock mode, NOT 422
