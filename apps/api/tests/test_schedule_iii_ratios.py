"""
The eleven Schedule III ratios — Division I clause (Q).

MCA Notification G.S.R. 207(E) of 24-03-2021 inserted Additional Regulatory
Information into Schedule III Division I's General Instructions. Clause (Q)
prescribes eleven named ratios and then two obligations that are not
arithmetic: the items in numerator and denominator must be explained, and any
change of MORE than 25% from the preceding year needs its own explanation.

These are the statutory reading, not the plumbing. The plumbing —
that the note ties to the statements, and that the endpoints are wired — is in
tests/test_ratio_note_ties_to_the_statements.py.
"""
import pytest

from domain.reporting import ratios as R

L = 1_00_000_00          # one lakh rupees, in paise


def _co(**kw) -> R.Components:
    return R.Components(**kw)


def _by_key(doc, key):
    return next(r for r in doc["ratios"] if r["key"] == key)


# A profitable trading client, and the same client a year earlier.
CURRENT = _co(
    share_capital=10 * L, reserves=5 * L,
    long_term_borrowings=6 * L, short_term_borrowings=2 * L,
    trade_payables=3 * L, other_current_liabilities=1 * L,
    inventories=4 * L, trade_receivables=6 * L, cash=2 * L,
    long_term_investments=5 * L,
    revenue_from_operations=60 * L, other_income=1 * L,
    cost_of_materials=36 * L, employee_benefits=10 * L,
    finance_costs=1 * L, depreciation=2 * L, other_expenses=3 * L,
    tax_expense=2 * L,
)
PRIOR = _co(
    share_capital=10 * L, reserves=2 * L,
    long_term_borrowings=8 * L, short_term_borrowings=2 * L,
    trade_payables=2 * L, other_current_liabilities=1 * L,
    inventories=2 * L, trade_receivables=4 * L, cash=1 * L,
    long_term_investments=5 * L,
    revenue_from_operations=40 * L, other_income=0,
    cost_of_materials=25 * L, employee_benefits=8 * L,
    finance_costs=1 * L, depreciation=2 * L, other_expenses=2 * L,
    tax_expense=1 * L,
)


# ── The table itself ─────────────────────────────────────────────────────────

def test_all_eleven_ratios_are_present_in_the_statutory_order():
    doc = R.build(CURRENT, PRIOR)
    assert [r["clause"] for r in doc["ratios"]] == [
        "(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)", "(j)", "(k)"]
    assert [r["label"] for r in doc["ratios"]] == [
        "Current Ratio", "Debt-Equity Ratio", "Debt Service Coverage Ratio",
        "Return on Equity Ratio", "Inventory turnover ratio",
        "Trade Receivables turnover ratio", "Trade payables turnover ratio",
        "Net capital turnover ratio", "Net profit ratio",
        "Return on Capital employed", "Return on investment",
    ]


def test_every_ratio_discloses_its_numerator_and_denominator():
    """Clause (Q): "The company shall explain the items included in numerator
    and denominator". A bare number is not the disclosure — the words are part
    of what gets filed, so no ratio may ship without them."""
    doc = R.build(CURRENT, PRIOR, principal_repaid_paise=2 * L)
    for r in doc["ratios"]:
        if r["unavailable_reason"]:
            continue
        assert r["numerator"] and r["numerator"]["label"].strip(), r["key"]
        assert r["denominator"] and r["denominator"]["label"].strip(), r["key"]


# ── The arithmetic ───────────────────────────────────────────────────────────

def test_current_ratio():
    # (4 + 6 + 2) / (2 + 3 + 1) = 12/6 = 2.00
    r = _by_key(R.build(CURRENT), "current_ratio")
    assert r["value_bps"] == 2 * R.BPS
    assert r["numerator"]["paise"] == 12 * L
    assert r["denominator"]["paise"] == 6 * L


def test_debt_equity_uses_total_borrowings_over_shareholders_funds():
    # (6 + 2) / (10 + 5) = 0.5333…
    r = _by_key(R.build(CURRENT), "debt_equity")
    assert r["value_bps"] == (8 * L) * R.BPS // (15 * L)


def test_net_profit_ratio_is_pat_over_revenue_from_operations():
    # PBT = (60+1) - (36+10+1+2+3) = 9L; PAT = 7L; 7/60
    r = _by_key(R.build(CURRENT), "net_profit_ratio")
    assert r["numerator"]["paise"] == 7 * L
    assert r["denominator"]["paise"] == 60 * L
    assert r["unit"] == R.UNIT_PERCENT


def test_return_on_capital_employed_adds_finance_costs_back():
    """EBIT, not PAT: capital employed includes the debt that produced the
    finance cost, so charging that cost against the return double-counts it."""
    r = _by_key(R.build(CURRENT), "return_on_capital_employed")
    assert r["numerator"]["paise"] == 10 * L          # PBT 9L + finance 1L
    assert r["denominator"]["paise"] == 23 * L        # equity 15L + debt 8L + DTL 0


def test_turnover_ratios_use_the_average_of_opening_and_closing():
    """A turnover ratio divides a full year's flow by a balance, so the balance
    has to be the year's average or the ratio moves with the year-end position
    rather than with the business."""
    r = _by_key(R.build(CURRENT, PRIOR), "inventory_turnover")
    assert r["denominator"]["paise"] == (4 * L + 2 * L) // 2
    assert "average" in r["denominator"]["label"]


def test_with_no_preceding_year_the_closing_balance_is_used_and_says_so():
    r = _by_key(R.build(CURRENT), "inventory_turnover")
    assert r["denominator"]["paise"] == 4 * L
    assert "no preceding year" in r["denominator"]["label"]


# ── ratio_bps, the one piece of arithmetic everything rests on ───────────────

@pytest.mark.parametrize("num,den,expected", [
    (100, 50, 2 * R.BPS),
    (50, 100, R.BPS // 2),
    (0, 100, 0),
    (-100, 50, -2 * R.BPS),
    (100, -50, -2 * R.BPS),
    (-100, -50, 2 * R.BPS),
])
def test_ratio_bps(num, den, expected):
    assert R.ratio_bps(num, den) == expected


def test_a_zero_denominator_is_undefined_not_zero():
    """A client with no current liabilities has no current ratio — reporting
    0.00 would read as "cannot pay", which is the opposite of the truth."""
    assert R.ratio_bps(100, 0) is None
    r = _by_key(R.build(_co(inventories=5 * L)), "current_ratio")
    assert r["value_bps"] is None
    assert r["numerator"]["paise"] == 5 * L, "the components are still disclosed"


def test_truncation_does_not_exaggerate_a_negative_ratio():
    """Floor division on a negative would report -0.67 as -0.67 rounded AWAY
    from zero. Both signs truncate toward zero here."""
    assert R.ratio_bps(-2, 3) == -(2 * R.BPS // 3)


# ── The 25% test ─────────────────────────────────────────────────────────────

def test_a_move_over_25_percent_needs_an_explanation():
    change, needs = R.variance(15_000, 10_000)          # 1.50 from 1.00 = +50%
    assert change == 50 * 100
    assert needs is True


def test_exactly_25_percent_does_not():
    """Clause (Q) says "more than 25%"."""
    change, needs = R.variance(12_500, 10_000)
    assert change == 25 * 100
    assert needs is False


def test_a_negative_ratio_keeps_the_DIRECTION_of_its_change():
    """The base is the MAGNITUDE of the preceding year, so the sign of the
    change still means what it says.

    A loss-making client's return on equity going from -0.20 to -0.30 has gone
    DOWN by 50%, and that is what is reported. Dividing by the SIGNED prior year
    would give +50% — a fall in the ratio presented as a rise, which a reviewer
    skimming a variance column would read as an improvement."""
    assert R.variance(-3_000, -2_000) == (-50 * 100, True)
    # and back the other way: -0.30 to -0.20 is a rise, and reads as one.
    assert R.variance(-2_000, -3_000) == (33 * 100 + 33, True)


def test_a_prior_year_of_zero_is_flagged_with_no_percentage():
    """Any move off zero is infinite as a percentage and material by
    definition, so it is flagged without a number rather than divided by
    zero."""
    change, needs = R.variance(5_000, 0)
    assert change is None and needs is True
    assert R.variance(0, 0) == (0, False)


def test_the_note_counts_what_still_needs_an_explanation():
    doc = R.build(CURRENT, PRIOR)
    flagged = [r["key"] for r in doc["ratios"] if r["needs_explanation"]]
    assert flagged, "the fixture was meant to move some ratios by more than 25%"
    assert doc["needs_explanation_count"] == len(flagged)

    answered = R.build(CURRENT, PRIOR, explanations={flagged[0]: "Stock built for the new line."})
    assert answered["needs_explanation_count"] == len(flagged) - 1
    assert _by_key(answered, flagged[0])["explanation"] == "Stock built for the new line."


def test_both_years_are_computed_by_the_same_function():
    """The preceding year's figure must be this year's calculation run over last
    year's numbers. Two implementations of one ratio is how a variance appears
    that is really a difference in method."""
    doc = R.build(CURRENT, PRIOR)
    prior_only = R.build(PRIOR)
    for r in doc["ratios"]:
        if r["prior_value_bps"] is None:
            continue
        assert r["prior_value_bps"] == _by_key(prior_only, r["key"])["value_bps"], r["key"]


# ── What is refused rather than guessed ──────────────────────────────────────

def test_debt_service_coverage_refuses_without_the_principal_repaid():
    """The movement in the borrowing balance is drawdowns LESS repayments. A
    client who repaid 40 lakh and drew 35 lakh shows a movement of 5 lakh, and
    a DSCR built on that overstates cover eightfold. Lenders read this ratio."""
    doc = R.build(CURRENT, PRIOR)
    r = _by_key(doc, "dscr")
    assert r["value_bps"] is None
    assert r["denominator"] is None
    assert "PRINCIPAL" in r["unavailable_reason"]
    assert "debt_service_principal_unknown" in [g["code"] for g in doc["gaps"]]


def test_debt_service_coverage_computes_once_the_principal_is_supplied():
    doc = R.build(CURRENT, PRIOR, principal_repaid_paise=2 * L)
    r = _by_key(doc, "dscr")
    # earnings = PAT 7L + depreciation 2L + finance 1L = 10L
    # service  = finance 1L + principal 2L = 3L
    assert r["numerator"]["paise"] == 10 * L
    assert r["denominator"]["paise"] == 3 * L
    assert r["value_bps"] == (10 * L) * R.BPS // (3 * L)
    assert "debt_service_principal_unknown" not in [g["code"] for g in doc["gaps"]]


def test_zero_principal_repaid_is_an_answer_not_an_absence():
    """A client that paid no principal this year has debt service equal to its
    finance costs. That is a real, high, correct ratio — not a missing one."""
    doc = R.build(CURRENT, PRIOR, principal_repaid_paise=0)
    r = _by_key(doc, "dscr")
    assert r["value_bps"] is not None
    assert r["denominator"]["paise"] == 1 * L


def test_return_on_investment_refuses_when_no_income_is_tagged():
    """Nothing in the chart says which income came from investments, and a zero
    would claim the investments earned nothing."""
    doc = R.build(CURRENT)                      # investment_income defaults to None
    r = _by_key(doc, "return_on_investment")
    assert r["value_bps"] is None
    assert r["numerator"] is None
    assert "investment_income_not_tagged" in [g["code"] for g in doc["gaps"]]


def test_return_on_investment_computes_once_the_chart_tags_it():
    c = R.Components(**{**CURRENT.__dict__, "investment_income": 1 * L})
    r = _by_key(R.build(c), "return_on_investment")
    assert r["numerator"]["paise"] == 1 * L
    assert r["denominator"]["paise"] == 5 * L
    assert r["value_bps"] == 20 * 100              # 20%


def test_investment_income_is_read_off_account_subtypes_not_the_pl_caption():
    """pl_bucket folds dividend and interest income into "Other Income", which
    is right for the face of the P&L and useless here."""
    pl = {"revenue": {"lines": [
        {"account_type": "Revenue", "account_subtype": "Professional Fees", "amount_paise": 10 * L},
        {"account_type": "Revenue", "account_subtype": "Dividend Income", "amount_paise": 1 * L},
        {"account_type": "Revenue", "account_subtype": "Interest Income", "amount_paise": 50_00},
    ]}}
    assert R._investment_income(pl) == 1 * L + 50_00
    assert R._investment_income({"revenue": {"lines": [
        {"account_type": "Revenue", "account_subtype": "Sales", "amount_paise": 10 * L}]}}) is None


def test_a_missing_preceding_year_is_reported_as_a_gap():
    doc = R.build(CURRENT)
    assert doc["has_prior_year"] is False
    assert "no_preceding_year" in [g["code"] for g in doc["gaps"]]
    assert all(r["prior_value_bps"] is None for r in doc["ratios"])
    assert all(not r["needs_explanation"] for r in doc["ratios"]), (
        "with no preceding year there is nothing to have moved by 25%")


def test_the_statute_is_cited_on_the_note():
    doc = R.build(CURRENT)
    assert "G.S.R. 207(E)" in doc["statute"]
    assert doc["variance_threshold_bps"] == 25 * 100
