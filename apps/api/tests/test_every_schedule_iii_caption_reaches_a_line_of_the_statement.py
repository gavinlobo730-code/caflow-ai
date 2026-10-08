"""A caption Schedule III declares is a LINE of the statement it belongs to, never a balance the statement drops.

WHAT WAS WRONG
    `BALANCE_SHEET_CAPTIONS` lists "Capital Work-in-Progress" and says in a comment that Division I presents it on its
    own line under Non-current assets, never merged into Tangible. `classify` and `bs_bucket` return it. But
    `_build_one_year` read fourteen of the fifteen balance-sheet captions into a line and never read that one, so a
    client with a capital work-in-progress balance got a Schedule III balance sheet whose assets were short by exactly
    that balance and whose own `is_balanced` said False. It was found by giving the seeded demo client for
    construction a project (₹1,54,348 of cost): the asset side summed to -6,76,884,238 paise, the other side to
    -6,61,449,438, and the gap was the project to the paisa. The year-end statements carry `capital_wip` and the
    client Balance Sheet carries its own line, so only this statement lost it -- the `capital_wip` shape again: a
    name declared in a list that nothing reads.

THE RULE, STATED WITHOUT A LIST OF TODAY'S CAPTIONS
    For every caption the module declares, a line carrying that caption and an amount must leave the amount on the
    statement: summed over the presented lines (and, for the one caption Division I presents below the line, the tax
    expense), it is the amount, once. Side-agnostic on purpose: `bucket_amounts` buckets by caption wherever the line
    sat, so the test does not need to know which side a caption belongs to, and a caption added to either tuple later
    is covered the day it is added.
"""
from __future__ import annotations

import pytest

from domain.reporting import schedule_iii as s3
from domain.reporting.schedule_iii import build_schedule_iii

AMOUNT = 1_23_456_00  # ₹1,23,456 -- not a round number, so a double count or a half count cannot pass by luck


def _empty_pl() -> dict:
    return {"revenue": {"lines": []}, "operating_expenses": {"lines": []}, "cost_of_sales": {"lines": []}}


def _empty_bs() -> dict:
    return {"assets": [], "liabilities": [], "equity": []}


def _presented_balance_sheet(bs_out: dict) -> int:
    """Every paisa the statement shows on a line, both sides together."""
    total = 0
    for side in ("assets", "equity_and_liabilities"):
        for section in bs_out[side]:
            total += sum(line["paise"] for line in section["lines"])
    return total


def _presented_profit_and_loss(pl_out: dict) -> int:
    total = pl_out["tax_expense_paise"]
    for side in ("revenue", "expenses"):
        for section in pl_out[side]:
            total += sum(line["paise"] for line in section["lines"])
    return total


@pytest.mark.parametrize("caption", s3.BALANCE_SHEET_CAPTIONS)
def test_every_balance_sheet_caption_leaves_its_amount_on_a_line(caption):
    bs = _empty_bs()
    bs["assets"] = [{"label": "Assets", "lines": [{
        "account_name": "An account", "account_type": "Asset", "account_subtype": None,
        "schedule_iii_caption": caption, "balance_paise": AMOUNT}], "total_paise": AMOUNT}]

    out = build_schedule_iii(_empty_pl(), bs, "2025-04-01", "2026-03-31")["balance_sheet"]

    assert _presented_balance_sheet(out) == AMOUNT, (
        f"{caption!r} is a declared Balance Sheet caption but a balance carrying it does not reach a line of the "
        f"statement (presented {_presented_balance_sheet(out)} paise of {AMOUNT})")
    assert out["total_assets_paise"] + out["total_equity_liabilities_paise"] == AMOUNT


@pytest.mark.parametrize("caption", s3.PROFIT_LOSS_CAPTIONS)
def test_every_profit_and_loss_caption_leaves_its_amount_on_the_statement(caption):
    pl = _empty_pl()
    pl["operating_expenses"] = {"lines": [{
        "account_name": "An account", "account_type": "Expense", "account_subtype": None,
        "schedule_iii_caption": caption, "amount_paise": AMOUNT}], "total_paise": AMOUNT}

    out = build_schedule_iii(pl, _empty_bs(), "2025-04-01", "2026-03-31")["profit_and_loss"]

    assert _presented_profit_and_loss(out) == AMOUNT, (
        f"{caption!r} is a declared Profit and Loss caption but an amount carrying it does not reach the statement")


def test_a_balance_sheet_with_capital_work_in_progress_balances():
    """The case that was found: the same ledger, one project, and the statement's own verdict."""
    cwip = 1_54_348_00
    bs = {
        "assets": [{"label": "Assets", "lines": [
            {"account_name": "Plant", "account_type": "Asset", "account_subtype": "Fixed Asset",
             "schedule_iii_caption": "Tangible Fixed Assets", "balance_paise": 8_00_000_00},
            {"account_name": "Capital Work-in-Progress", "account_type": "Asset",
             "account_subtype": "Capital Work-in-Progress", "schedule_iii_caption": "Capital Work-in-Progress",
             "balance_paise": cwip},
        ], "total_paise": 8_00_000_00 + cwip}],
        "liabilities": [],
        "equity": [{"label": "Equity", "lines": [
            {"account_name": "Capital", "account_type": "Equity", "account_subtype": "Share Capital",
             "schedule_iii_caption": "Share Capital", "balance_paise": 8_00_000_00 + cwip},
        ], "total_paise": 8_00_000_00 + cwip}],
    }

    out = build_schedule_iii(_empty_pl(), bs, "2025-04-01", "2026-03-31")["balance_sheet"]

    assert out["is_balanced"] is True
    assert out["total_assets_paise"] == 8_00_000_00 + cwip
    lines = {ln["label"]: ln["paise"] for sec in out["assets"] for ln in sec["lines"]}
    assert lines["Capital Work-in-Progress"] == cwip
    # Never merged into the tangible line (Division I presents it on its own line).
    assert lines["Fixed Assets — Tangible"] == 8_00_000_00


def test_capital_work_in_progress_is_a_non_current_asset_line_after_the_fixed_assets():
    out = build_schedule_iii(_empty_pl(), _empty_bs(), "2025-04-01", "2026-03-31")["balance_sheet"]
    non_current = out["assets"][0]
    labels = [ln["label"] for ln in non_current["lines"]]
    assert labels.index("Capital Work-in-Progress") > labels.index("Fixed Assets — Intangible")
    assert labels.index("Capital Work-in-Progress") < labels.index("Long-term Investments")
