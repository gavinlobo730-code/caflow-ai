"""A straight-line asset posts the same charge every month of every year of its life and reaches its salvage value at the end of it.

WHAT WAS WRONG (found on 27-10-2026 by an independent review of the change that made the opening accumulated depreciation of a
straight-line asset's year stick; the figures below were reproduced by posting month after month through the route)

    `routers/fixed_assets._compute_annual_depreciation` caps the year's figure at what is left to depreciate
    (`min(annual, wdv_now - floor)`), and `wdv_now` was read from the asset's LIVE accumulated depreciation. For a
    written-down-value asset the year's figure was already worked out once, from the balance the year OPENED at
    (task #232); a straight-line asset skipped that and was handed the live row. In every year but the last the cap sits far above
    the figure (cost less salvage over the life) and nothing shows. In the last year each month posted lowers the cap, so the next
    month's charge is smaller than the one before: on a cost of 1,00,000.00 over five years the fifth year posted 12,960.05 of the
    20,000.00 left and 7,039.95 stayed undepreciated; on a cost of 1,20,000.00 bought on 1 April the fifth year posted 15,552.08
    of 24,000.00, and the tail ran on after the end of the life without ever reaching salvage. An asset brought over from another
    system carrying more than its straight-line share is capped the same way.

    Schedule II spreads the cost less the residual value over the useful life, so an asset that does not reach its residual value
    by the end of its life is a wrong depreciation charge for the year in which it ends. Nobody was affected in production:
    it holds no straight-line asset (read 27-10-2026).

WHAT IS HELD
    * the year's figure is resolved from the balance the year opened at, for either method, so every month of one year posts the
      same charge;
    * a straight-line asset bought on 1 April posts its whole cost less salvage by 31 March of its fifth year (to within the paise
      the monthly division discards, a fixed 8 paise a year on a cost that does not divide into twelve);
    * an asset brought over with more than its straight-line share already carried posts what is left, evenly, and not a
      shrinking figure;
    * an asset already at its salvage value posts nothing.
"""
import pytest

import routers.fixed_assets as fa_router
from routers.fixed_assets import _annual_depreciation_for_period
from tests.test_r232_fixed_asset_depreciation import FIRM, FakeDB, _dep, _seed_asset

SL = dict(depreciation_method="SL", wdv_rate_percent=None)
LAKH = 1_00_000_00


def _months(first_year: int, years: int):
    for y in range(first_year, first_year + years):
        for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3):
            yield f"{y if m >= 4 else y + 1}-{m:02d}"


@pytest.fixture
def posting(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fa_router, "_db", lambda: db)
    monkeypatch.setattr(fa_router._journal_svc, "journal_for_depreciation", lambda *a, **k: "je-1")
    return db


def _post(period):
    return fa_router.post_depreciation("asset-1", _dep(period=period), {"firm_id": FIRM, "id": "u1"})


def _charges_by_year(asset, first_year, years):
    """{financial year start: [the charge posted in each of its twelve months]}, posted through the route."""
    out: dict[int, list[int]] = {}
    for period in _months(first_year, years):
        before = asset["accumulated_depreciation_paise"]
        _post(period)
        y, m = int(period[:4]), int(period[5:])
        out.setdefault(y if m >= 4 else y - 1, []).append(asset["accumulated_depreciation_paise"] - before)
    return out


# ── the resolver, as a pure function ─────────────────────────────────────────────────────────────────────────────────────────
def _asset(**kw):
    base = {"purchase_cost_paise": LAKH, "salvage_value_paise": 0, "asset_category": "Other", "useful_life_years": 5, **SL}
    base.update(kw)
    return base


def test_the_last_years_figure_is_what_was_left_at_the_start_of_the_year_whatever_has_been_posted_since():
    # 80,000.00 carried in at the start of year five; two months of the year already posted since.
    asset = _asset(accumulated_depreciation_paise=80_000_00 + 2 * 1_666_66, depreciation_fy="2030-31",
                   depreciation_fy_start_accum_paise=80_000_00)
    annual, fy, opening = _annual_depreciation_for_period(asset, "2030-07")
    assert fy == "2030-31" and opening == 80_000_00
    assert annual == 20_000_00, "the year's figure must not shrink as the year's own months are posted"


def test_the_first_posting_of_a_year_caps_the_figure_at_what_is_left_at_that_moment():
    asset = _asset(accumulated_depreciation_paise=90_000_00, depreciation_fy="2029-30", depreciation_fy_start_accum_paise=70_000_00)
    annual, fy, opening = _annual_depreciation_for_period(asset, "2030-04")        # a NEW year: nothing posted against it yet
    assert fy == "2030-31" and opening == 90_000_00 and annual == 10_000_00


def test_an_asset_at_its_salvage_value_has_no_figure():
    asset = _asset(salvage_value_paise=10_000_00, accumulated_depreciation_paise=90_000_00)
    assert _annual_depreciation_for_period(asset, "2030-04")[0] == 0


# ── through the posting route, month after month ─────────────────────────────────────────────────────────────────────────────
def test_every_month_of_every_year_of_the_life_posts_the_same_charge_and_the_cost_is_written_off(posting):
    cost = 1_20_000_00                                   # 24,000.00 a year: divides into twelve, so nothing is discarded
    asset = _seed_asset(posting, purchase_date="2026-04-01", purchase_cost_paise=cost, salvage_value_paise=0,
                        useful_life_years=5, accumulated_depreciation_paise=0, **SL)
    by_year = _charges_by_year(asset, 2026, 5)
    for year, charges in by_year.items():
        assert charges == [2_000_00] * 12, f"FY {year}-{year + 1 - 2000}: a month's charge moved within the year: {charges}"
    assert asset["accumulated_depreciation_paise"] == cost
    assert asset["current_wdv_paise"] == 0


def test_a_cost_that_does_not_divide_into_twelve_loses_only_the_paise_the_division_discards_and_the_same_every_year(posting):
    asset = _seed_asset(posting, purchase_date="2026-04-01", purchase_cost_paise=LAKH, salvage_value_paise=0,
                        useful_life_years=5, accumulated_depreciation_paise=0, **SL)
    by_year = _charges_by_year(asset, 2026, 5)
    totals = [sum(c) for c in by_year.values()]
    assert len(set(totals)) == 1 and totals[0] == 12 * 1_666_66, totals          # five equal years, none shrinking
    assert 0 <= LAKH - asset["accumulated_depreciation_paise"] <= 5 * 12, "only the discarded paise may be left"


def test_the_final_years_months_are_not_a_shrinking_series(posting):
    asset = _seed_asset(posting, purchase_date="2026-04-01", purchase_cost_paise=LAKH, salvage_value_paise=0,
                        useful_life_years=5, accumulated_depreciation_paise=0, **SL)
    last = _charges_by_year(asset, 2026, 5)[2030]
    assert last == [1_666_66] * 12, last


def test_an_asset_brought_over_with_most_of_its_cost_written_off_posts_what_is_left_evenly(posting):
    """90,000.00 already carried against a 1,00,000.00 cost: 10,000.00 is left, which is less than a year's 20,000.00."""
    asset = _seed_asset(posting, purchase_date="2022-04-01", purchase_cost_paise=LAKH, salvage_value_paise=0,
                        useful_life_years=5, accumulated_depreciation_paise=90_000_00, **SL)
    charges = _charges_by_year(asset, 2026, 1)[2026]
    assert charges == [833_33] * 12, charges                                      # 10,000.00 / 12, not a shrinking tail
    assert LAKH - asset["accumulated_depreciation_paise"] <= 12


def test_the_charge_never_takes_the_asset_below_its_salvage_value(posting):
    """Cost 1,00,000.00 less a salvage of 10,000.00 is 18,000.00 a year for five years, and the sixth year has nothing to post."""
    asset = _seed_asset(posting, purchase_date="2026-04-01", purchase_cost_paise=LAKH, salvage_value_paise=10_000_00,
                        useful_life_years=5, accumulated_depreciation_paise=0, **SL)
    by_year = _charges_by_year(asset, 2026, 5)
    assert all(c == [1_500_00] * 12 for c in by_year.values()), by_year
    assert asset["accumulated_depreciation_paise"] == LAKH - 10_000_00
    sixth = _post("2031-04")
    assert sixth["data"]["depreciation_paise"] == 0 and asset["accumulated_depreciation_paise"] == LAKH - 10_000_00
