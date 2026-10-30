"""POST-A-097: the statements count the balances that sit on an "Other" line because nobody decided.

WHAT WAS MISSING
    `classify` says which of three things decided an account's Schedule III caption: the CA's mapping, a keyword in the subtype, or
    nothing (the account landed on a caption in `RESIDUAL_CAPTIONS`). The builders put that on every statement line as
    `schedule_iii_basis` and nothing counted it. So the mapping screen's "37 of 53 accounts mapped" measured the chart, not the
    books: an account with no balance counted the same as the one holding the year's deposits, and a CA could not see "N balances,
    Rs X, sit on an Other line because no one decided".

WHAT IS HELD
    * only a line whose basis is `residual` is counted: a mapped account and a subtype match are not, whatever the caption;
    * the money is the sum of ABSOLUTE balances, so a debit and a credit balance on the same line do not cancel;
    * the count is over the lines the statements present, so an account with no balance in the period is not in it;
    * a P&L expense with no matching subtype is counted on Other Expenses as an asset or liability is on Other Current Assets or
      Liabilities, and `by_caption` says which;
    * a line that carries no basis at all (a statement built elsewhere) is not counted and not guessed at: `unjudged_lines` says how
      many, so a nil is never a claim about lines this could not read;
    * `build_schedule_iii` carries the count for the reporting period.
"""
from domain.reporting.builders import balance_sheet, profit_loss
from domain.reporting.model import Account, ProjectedLine
from domain.reporting.schedule_iii import build_schedule_iii, residual_balances

FY = ("2026-04-01", "2027-03-31")


def _accounts(mapping=None):
    return {
        # A subtype that matches no keyword: lands on Other Current Assets unless somebody says otherwise.
        "deposit": Account(id="deposit", code="1900", name="Security Deposit - Landlord", type="Asset",
                           subtype="Widget Deposits", schedule_iii_mapping=mapping),
        # A subtype that matches: Cash & Cash Equivalents, decided by the subtype.
        "bank": Account(id="bank", code="1100", name="HDFC Bank", type="Asset", subtype="Bank"),
        # Credit-balance residual liability.
        "owed": Account(id="owed", code="2900", name="Sundry Widget Creditors", type="Liability", subtype="Widget Dues"),
        # A P&L expense nothing matches.
        "misc": Account(id="misc", code="5900", name="Widget Costs", type="Expense", subtype="Widget Costs"),
        # An account with no balance in the period.
        "idle": Account(id="idle", code="1901", name="Idle Widget Deposit", type="Asset", subtype="Widget Deposits"),
        "sales": Account(id="sales", code="4000", name="Sales", type="Revenue", subtype="Sales"),
    }


LINES = [
    ProjectedLine("deposit", 5_00_000, 0),
    ProjectedLine("bank", 2_00_000, 0),
    ProjectedLine("owed", 0, 3_00_000),
    ProjectedLine("misc", 40_000, 0),
    ProjectedLine("sales", 0, 40_000),
]


def _statements(mapping=None, lines=LINES):
    accts = _accounts(mapping)
    bs = balance_sheet(lines, accts, FY[1], "accrual")
    pl = profit_loss(lines, accts, FY[0], FY[1], "accrual")
    return pl, bs


def test_the_builders_still_put_the_basis_on_every_line_this_counts_from():
    pl, bs = _statements()
    bases = {ln["account_name"]: ln["schedule_iii_basis"]
             for sec in bs["assets"] + bs["liabilities"] for ln in sec["lines"]}
    assert bases["Security Deposit - Landlord"] == "residual"
    assert bases["HDFC Bank"] == "subtype"


def test_only_a_line_nobody_decided_is_counted_and_the_money_is_what_sits_there():
    pl, bs = _statements()
    got = residual_balances(pl, bs)
    assert got["accounts"] == 3                                   # the deposit, the creditors, the widget costs
    assert got["absolute_paise"] == 5_00_000 + 3_00_000 + 40_000
    assert got["by_caption"] == {
        "Other Current Assets": {"accounts": 1, "absolute_paise": 5_00_000},
        "Other Current Liabilities": {"accounts": 1, "absolute_paise": 3_00_000},
        "Other Expenses": {"accounts": 1, "absolute_paise": 40_000},
    }
    assert got["unjudged_lines"] == 0


def test_mapping_the_account_takes_it_out_of_the_count():
    pl, bs = _statements(mapping="Long-term Investments")
    got = residual_balances(pl, bs)
    assert got["accounts"] == 2
    assert "Other Current Assets" not in got["by_caption"]


def test_a_debit_and_a_credit_balance_on_the_same_line_do_not_cancel():
    accts = {
        "d": Account(id="d", code="1", name="A", type="Asset", subtype="Widget Deposits"),
        "c": Account(id="c", code="2", name="B", type="Asset", subtype="Widget Deposits"),
    }
    bs = balance_sheet([ProjectedLine("d", 1_000, 0), ProjectedLine("c", 0, 1_000)], accts, FY[1], "accrual")
    pl = profit_loss([], accts, FY[0], FY[1], "accrual")
    got = residual_balances(pl, bs)
    assert got["accounts"] == 2 and got["absolute_paise"] == 2_000


def test_an_account_with_no_balance_is_not_a_line_and_is_not_counted():
    pl, bs = _statements()
    names = {ln["account_name"] for sec in bs["assets"] for ln in sec["lines"]}
    assert "Idle Widget Deposit" not in names
    assert residual_balances(pl, bs)["accounts"] == 3


def test_a_line_with_no_basis_is_counted_as_unjudged_and_never_as_residual_or_decided():
    pl = {"revenue": {"lines": []}, "operating_expenses": {"lines": [{"account_name": "x", "amount_paise": 9_00}]}}
    bs = {"assets": [{"lines": [{"balance_paise": 1_000, "schedule_iii_caption": "Other Current Assets"}]}],
          "liabilities": [], "equity": []}
    got = residual_balances(pl, bs)
    assert got == {"accounts": 0, "absolute_paise": 0, "by_caption": {}, "unjudged_lines": 2}


def test_an_account_that_classify_could_place_on_no_caption_is_unjudged_and_not_an_other_line():
    pl = {"revenue": {"lines": [{"schedule_iii_basis": "residual", "schedule_iii_caption": None, "amount_paise": 700}]}}
    assert residual_balances(pl, {"assets": [], "liabilities": [], "equity": []}) == {
        "accounts": 0, "absolute_paise": 0, "by_caption": {}, "unjudged_lines": 1}


def test_nothing_on_the_books_is_a_count_of_nothing():
    pl, bs = _statements(lines=[])
    assert residual_balances(pl, bs) == {"accounts": 0, "absolute_paise": 0, "by_caption": {}, "unjudged_lines": 0}


def test_the_schedule_iii_statement_carries_the_count_for_the_reporting_period_only():
    pl, bs = _statements()
    prior_pl, prior_bs = _statements(lines=[ProjectedLine("deposit", 9_99_999, 0)])
    doc = build_schedule_iii(pl, bs, FY[0], FY[1], prior_pl, prior_bs, "2025-04-01", "2026-03-31")
    assert doc["residual_balances"]["accounts"] == 3
    assert doc["residual_balances"]["absolute_paise"] == 8_40_000
    without = build_schedule_iii(pl, bs, FY[0], FY[1])
    assert without["residual_balances"] == doc["residual_balances"]
