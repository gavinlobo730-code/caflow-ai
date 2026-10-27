"""A straight-line asset keeps the opening accumulated depreciation of its financial year, so the fixed-assets note shows the whole
year's charge and not the last month's.

WHAT WAS WRONG (found on 27-10-2026, by posting twelve months of depreciation on a real database and reading the note)

    `routers/fixed_assets._annual_depreciation_for_period` returns three things, the last being "the opening-of-year accumulated
    depreciation this charge was computed from", and the router stores it on the asset after EVERY posting
    (`fixed_assets.depreciation_fy_start_accum_paise`, migration 239). For a written-down-value asset it was resolved properly, reusing
    the stored figure inside the year. For every other method the function returned early with the LIVE accumulated depreciation, so a
    straight-line asset's "opening of the year" was overwritten with the balance before the latest posting, month after month.

    Nothing computed from the CHARGE noticed (cost, salvage and life never move), which is why the docstring said straight line was
    unaffected and the existing straight-line test ignored the third value. What reads the stored figure is the fixed-assets note
    (`domain/reporting/fixed_asset_movement`): it takes the year's charge as accumulated less opening, so twelve months of ₹1,333.33
    showed as one month, and for an asset bought during the year the closing accumulated depreciation and net block were wrong by the
    other eleven. The ledger was right throughout, so the register and the books disagreed and the note SAID they disagreed.
    Production holds no straight-line asset (read 27-10-2026), so no stored row needs repair.
"""
import pytest

import routers.fixed_assets as fa_router
from domain.reporting import fixed_asset_movement as fam
from routers.fixed_assets import _annual_depreciation_for_period
from tests.test_r232_fixed_asset_depreciation import FIRM, FakeDB, _dep, _patch_side_effects, _seed_asset  # noqa: F401

SL = dict(depreciation_method="SL", useful_life_years=5, salvage_value_paise=0, wdv_rate_percent=None)


def _sl_asset(**kw):
    base = {"purchase_cost_paise": 100_000_00, "accumulated_depreciation_paise": 0, "asset_category": "Other", **SL}
    base.update(kw)
    return base


# ── the resolver, as a pure function ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_first_straight_line_posting_of_a_year_opens_the_year_at_the_live_balance():
    asset = _sl_asset(accumulated_depreciation_paise=30_000_00, depreciation_fy="2025-26", depreciation_fy_start_accum_paise=10_000_00)
    annual, fy, opening = _annual_depreciation_for_period(asset, "2026-04")                   # a NEW year: nothing posted against it yet
    assert fy == "2026-27" and opening == 30_000_00 and annual == 20_000_00


def test_a_later_straight_line_posting_in_the_same_year_reuses_the_stored_opening():
    asset = _sl_asset(accumulated_depreciation_paise=30_000_00 + 5_000_00, depreciation_fy="2026-27",
                      depreciation_fy_start_accum_paise=30_000_00)
    annual, fy, opening = _annual_depreciation_for_period(asset, "2026-07")
    assert fy == "2026-27" and annual == 20_000_00
    assert opening == 30_000_00, "the opening of the year is not the balance before this month's posting"


def test_an_asset_with_no_stored_opening_for_the_year_opens_it_at_the_live_balance():
    asset = _sl_asset(accumulated_depreciation_paise=4_000_00, depreciation_fy="2026-27", depreciation_fy_start_accum_paise=None)
    assert _annual_depreciation_for_period(asset, "2026-08")[2] == 4_000_00


def test_the_written_down_value_opening_is_resolved_exactly_as_before():
    asset = {"purchase_cost_paise": 100_000_00, "salvage_value_paise": 0, "depreciation_method": "WDV", "wdv_rate_percent": 24.0,
             "asset_category": "Other", "accumulated_depreciation_paise": 6_000_00, "depreciation_fy": "2026-27",
             "depreciation_fy_start_accum_paise": 0}
    annual, _fy, opening = _annual_depreciation_for_period(asset, "2026-07")
    assert opening == 0 and annual == 24_000_00


# ── through the posting route, month after month ─────────────────────────────────────────────────────────────────────────────────
def _post(db, period):
    return fa_router.post_depreciation("asset-1", _dep(period=period), {"firm_id": FIRM, "id": "u1"})


@pytest.fixture
def posting(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fa_router, "_db", lambda: db)
    monkeypatch.setattr(fa_router._journal_svc, "journal_for_depreciation", lambda *a, **k: "je-1")
    return db


def test_the_stored_opening_does_not_move_while_a_year_of_straight_line_depreciation_is_posted(posting):
    asset = _seed_asset(posting, purchase_date="2026-04-01", **SL, accumulated_depreciation_paise=0)
    for n, period in enumerate(("2026-04", "2026-05", "2026-06", "2026-07"), start=1):
        _post(posting, period)
        assert asset["depreciation_fy_start_accum_paise"] == 0, f"after posting {n} months the year's opening had moved"
        assert asset["depreciation_fy"] == "2026-27"
    assert asset["accumulated_depreciation_paise"] == 4 * 1_666_66


def test_the_fixed_assets_note_shows_the_whole_years_charge_for_an_asset_bought_in_the_year(posting):
    asset = _seed_asset(posting, purchase_date="2026-04-01", **SL, accumulated_depreciation_paise=0)
    for period in ("2026-04", "2026-05", "2026-06", "2026-07"):
        _post(posting, period)
    movement = fam.movement_from_rows([asset], "2027-03-31")
    row = movement.classes[0]
    assert row["charge_paise"] == 4 * 1_666_66 and row["opening_accum_paise"] == 0
    assert row["closing_accum_paise"] == asset["accumulated_depreciation_paise"], "the note's closing balance is the register's"
    assert row["closing_net_paise"] == 100_000_00 - 4 * 1_666_66
    assert movement.split_known is True


def test_the_note_splits_an_asset_held_at_the_start_of_the_year_between_opening_and_charge(posting):
    """Bought in an earlier year with 20,000 already depreciated: the year opens at 20,000 and three months add to it."""
    asset = _seed_asset(posting, purchase_date="2025-04-01", **SL, accumulated_depreciation_paise=20_000_00,
                        depreciation_fy="2025-26", depreciation_fy_start_accum_paise=0)
    for period in ("2026-04", "2026-05", "2026-06"):
        _post(posting, period)
    assert asset["depreciation_fy"] == "2026-27" and asset["depreciation_fy_start_accum_paise"] == 20_000_00
    row = fam.movement_from_rows([asset], "2027-03-31").classes[0]
    assert row["opening_accum_paise"] == 20_000_00, "the year opened at the balance carried in, not at the balance before the last month"
    assert row["charge_paise"] == 3 * 1_666_66
    assert row["closing_accum_paise"] == asset["accumulated_depreciation_paise"]


def test_the_next_year_opens_at_the_balance_the_last_one_ended_on(posting):
    asset = _seed_asset(posting, purchase_date="2026-04-01", **SL, accumulated_depreciation_paise=0)
    _post(posting, "2026-04")
    _post(posting, "2026-05")
    ended = asset["accumulated_depreciation_paise"]
    # Foreclosing the months in between is the router's own, separately tested business; the opening is what is asserted here.
    asset["depreciation_posted_through"] = "2027-03-31"
    _post(posting, "2027-04")
    assert asset["depreciation_fy"] == "2027-28" and asset["depreciation_fy_start_accum_paise"] == ended
