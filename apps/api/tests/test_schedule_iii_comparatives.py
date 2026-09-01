"""
Comparatives — Schedule III, Division I, General Instructions para 5.

    "Except in the case of the first Financial Statements laid before the
     Company (after its incorporation) the corresponding amounts (comparatives)
     for the immediately preceding reporting period for all items shown in the
     Financial Statements including notes shall also be given."

ALL ITEMS. A balance sheet with one column is not a Schedule III balance sheet
and a CA cannot sign it — which is what this engine produced until now, while
the Reports hub said in as many words that "the statements carry a previous-year
column".

The second column is produced by running build_schedule_iii's own body over the
preceding period and merging, so the comparative cannot be computed by a
different rule from the figure it sits beside, and a caption added to one column
is added to both or the merge refuses. These prove both halves of that.
"""
import pytest

from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)
from domain.reporting.schedule_iii import build_schedule_iii
from domain.reporting.service import _has_any_amount, _preceding_period

FIRM, CLIENT = "firm-comp", "client-comp"
THIS, PRIOR = ("2026-04-01", "2027-03-31"), ("2025-04-01", "2026-03-31")
L = 1_00_000_00

ACCOUNTS = [
    Account("bank", "1000", "Bank",              "Asset",     "Bank", system_key="bank"),
    Account("ar",   "1100", "Trade Receivables", "Asset",     "Receivable", system_key="ar"),
    Account("ap",   "2150", "Trade Payables",    "Liability", "Payable", system_key="ap"),
    Account("cap",  "3000", "Share Capital",     "Equity",    "Share Capital"),
    Account("rev",  "4000", "Sales",             "Revenue",   "Sales"),
    Account("exp",  "5000", "Office Rent",       "Expense",   "Operating Expense"),
]


def je(jid, lines, when):
    return JournalEntry(id=jid, entry_date=when, client_id=CLIENT, firm_id=FIRM,
                        entry_type="x", lines=tuple(JournalLine(*l) for l in lines))


TWO_YEARS = [
    # FY 2025-26 — the comparative year.
    je("p1", [("bank", 10 * L, 0), ("cap", 0, 10 * L)], "2025-04-01"),
    je("p2", [("ar", 20 * L, 0), ("rev", 0, 20 * L)], "2025-09-30"),
    je("p3", [("exp", 4 * L, 0), ("ap", 0, 4 * L)], "2025-10-31"),
    # FY 2026-27 — the reporting year.
    je("c1", [("ar", 35 * L, 0), ("rev", 0, 35 * L)], "2026-09-30"),
    je("c2", [("exp", 6 * L, 0), ("ap", 0, 6 * L)], "2026-10-31"),
]


def _svc(entries):
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(entries)))


def _line(doc, top, key, caption):
    for sec in doc[top][key]:
        for ln in sec["lines"]:
            if ln["label"] == caption:
                return ln
    raise AssertionError(f"{caption} is not on the statement")


# ── The preceding period ─────────────────────────────────────────────────────

def test_the_preceding_period_is_the_same_length_ending_the_day_before():
    assert _preceding_period("2026-04-01", "2027-03-31") == ("2025-04-01", "2026-03-31")


def test_a_stub_period_gets_a_stub_comparative():
    """A company incorporated in November has a first reporting period of five
    months, and its comparative is the five months before — not twelve. "The
    same dates a year earlier" happens to be right for a full financial year and
    is wrong here."""
    p_start, p_end = _preceding_period("2025-11-01", "2026-03-31")
    assert p_end == "2025-10-31"
    from datetime import date
    assert (date.fromisoformat("2026-03-31") - date.fromisoformat("2025-11-01")) == \
           (date.fromisoformat(p_end) - date.fromisoformat(p_start))


# ── Every item carries its corresponding amount ──────────────────────────────

def test_every_balance_sheet_line_carries_a_comparative():
    doc = _svc(TWO_YEARS).schedule_iii(FIRM, CLIENT, *THIS)
    assert doc["comparatives"]["present"] is True
    assert doc["comparatives"]["period"] == {"fy_start": PRIOR[0], "fy_end": PRIOR[1]}
    for key in ("equity_and_liabilities", "assets"):
        for sec in doc["balance_sheet"][key]:
            assert sec["prior_total_paise"] is not None, sec["heading"]
            for ln in sec["lines"]:
                assert ln["prior_paise"] is not None, ln["label"]


def test_every_pl_line_carries_a_comparative():
    doc = _svc(TWO_YEARS).schedule_iii(FIRM, CLIENT, *THIS)
    for key in ("revenue", "expenses"):
        for sec in doc["profit_and_loss"][key]:
            assert sec["prior_total_paise"] is not None, sec["heading"]
            for ln in sec["lines"]:
                assert ln["prior_paise"] is not None, ln["label"]


def test_every_headline_total_carries_a_comparative():
    doc = _svc(TWO_YEARS).schedule_iii(FIRM, CLIENT, *THIS)
    for k in ("total_equity_liabilities_prior_paise", "total_assets_prior_paise"):
        assert doc["balance_sheet"][k] is not None, k
    for k in ("total_revenue_prior_paise", "total_expenses_prior_paise",
              "profit_before_tax_prior_paise", "tax_expense_prior_paise",
              "profit_after_tax_prior_paise"):
        assert doc["profit_and_loss"][k] is not None, k


def test_the_comparative_figures_are_the_preceding_years_own(): 
    """Not a copy, not a scaled guess: the number in the second column must be
    what the preceding year's statement says."""
    svc = _svc(TWO_YEARS)
    doc = svc.schedule_iii(FIRM, CLIENT, *THIS)
    last_year = svc.schedule_iii(FIRM, CLIENT, *PRIOR)

    rev = _line(doc, "profit_and_loss", "revenue", "Revenue from Operations")
    assert rev["paise"] == 35 * L
    assert rev["prior_paise"] == 20 * L
    assert rev["prior_paise"] == _line(
        last_year, "profit_and_loss", "revenue", "Revenue from Operations")["paise"]

    # The balance sheet is cumulative, so the comparative is last year's CLOSING
    # position rather than last year's movement.
    ar = _line(doc, "balance_sheet", "assets", "Trade Receivables")
    assert ar["paise"] == 55 * L
    assert ar["prior_paise"] == 20 * L


def test_the_comparative_column_balances_too():
    doc = _svc(TWO_YEARS).schedule_iii(FIRM, CLIENT, *THIS)
    bs = doc["balance_sheet"]
    assert bs["total_assets_prior_paise"] == bs["total_equity_liabilities_prior_paise"]


# ── The statute's own exception ──────────────────────────────────────────────

def test_a_first_period_gets_no_comparative_and_says_why():
    """Para 5 excepts the first financial statements laid before a company after
    its incorporation. A client's first year on the platform is the same case,
    and a column of zeros is NOT that disclosure — it asserts the business had
    nil against every caption last year."""
    first_year_only = [e for e in TWO_YEARS if e.id.startswith("c")]
    doc = _svc(first_year_only).schedule_iii(FIRM, CLIENT, *THIS)
    assert doc["comparatives"]["present"] is False
    assert doc["comparatives"]["period"] is None
    assert "first financial statements" in doc["comparatives"]["reason"]
    for sec in doc["balance_sheet"]["assets"]:
        for ln in sec["lines"]:
            assert ln["prior_paise"] is None, (
                f"{ln['label']} was given a comparative there is no period for")


def test_an_empty_preceding_period_is_no_preceding_period():
    assert _has_any_amount({}, {}) is False
    assert _has_any_amount(
        {"revenue": {"lines": [{"amount_paise": 0}]}},
        {"assets": [{"lines": [{"balance_paise": 0}]}]}) is False
    assert _has_any_amount({"revenue": {"lines": [{"amount_paise": 1}]}}, {}) is True
    assert _has_any_amount({}, {"equity": [{"lines": [{"balance_paise": -1}]}]}) is True


# ── The merge refuses rather than mis-pairs ──────────────────────────────────

def test_a_caption_present_in_one_column_only_is_refused():
    """Both columns come from the same builder with the same fixed captions, so
    a mismatch is not a data condition — it means the two were not produced by
    the same code, and presenting them side by side is the exact defect
    comparatives exist to avoid. It has to fail loudly, not silently offset the
    column by one row."""
    from domain.reporting.schedule_iii import _attach_comparatives
    doc = build_schedule_iii({}, {}, *THIS)
    prior = build_schedule_iii({}, {}, *PRIOR)
    prior["balance_sheet"]["assets"][0]["lines"][0]["label"] = "Something Else"
    with pytest.raises(ValueError, match="comparative mismatch"):
        _attach_comparatives(doc, prior)


def test_a_missing_section_is_refused():
    from domain.reporting.schedule_iii import _attach_comparatives
    doc = build_schedule_iii({}, {}, *THIS)
    prior = build_schedule_iii({}, {}, *PRIOR)
    prior["profit_and_loss"]["expenses"] = []
    with pytest.raises(ValueError, match="comparative mismatch"):
        _attach_comparatives(doc, prior)


def test_a_shorter_line_list_is_refused():
    from domain.reporting.schedule_iii import _attach_comparatives
    doc = build_schedule_iii({}, {}, *THIS)
    prior = build_schedule_iii({}, {}, *PRIOR)
    prior["balance_sheet"]["assets"][0]["lines"].pop()
    with pytest.raises(ValueError, match="comparative line-count mismatch"):
        _attach_comparatives(doc, prior)


def test_the_shape_is_stable_whether_or_not_a_comparative_exists():
    """A renderer must not have to branch on which document it got."""
    with_prior = build_schedule_iii({}, {}, *THIS, {}, {}, *PRIOR)
    without = build_schedule_iii({}, {}, *THIS)
    def shape(d):
        return {(sec["heading"], tuple(sorted(ln.keys())))
                for k in ("equity_and_liabilities", "assets")
                for sec in d["balance_sheet"][k] for ln in sec["lines"]}
    assert shape(with_prior) == shape(without)
