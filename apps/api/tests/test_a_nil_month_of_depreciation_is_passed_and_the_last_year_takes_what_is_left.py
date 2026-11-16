"""A month whose share of a positive year's depreciation figure is nil is PASSED, and a straight-line asset's last year takes what
is left (POST-A-437).

WHAT WAS WRONG
    * A year's figure under twelve paise has months whose share is nil (5 paise a year: 0,0,1,0,1,0,0,1,0,1,0,1). Such a month
      posted nothing and left `depreciation_posted_through` where it was, so the next month was refused ("post that month first")
      for ever: an asset of 25 paise posted June and stopped at July. The range runner stopped at the first nil month too.
    * A straight-line year's figure is floor((cost - salvage) / life), so (cost - salvage) mod life paise were left after the life
      and fell in a later year on their own, whose months' shares were nil: 1,00,000.04 over five years ended 4 paise above nil.

WHAT IS HELD
    * the last year of a straight-line life takes what is left, and every earlier year is the floored figure;
    * through the single-month route and the range runner, every month of a year whose figure is 5 paise is reached: the nil months
      are passed (posted-through moves, no journal), the others post, and the year closes at its figure;
    * a reversal of the month after a passed month goes back to the passed month, a passed month can itself be reversed, and the
      months then post again to the same figure;
    * the projection passes a nil month as a posting does and ends fully depreciated.
"""
from __future__ import annotations

import routers.fixed_assets as fa
from models.accounting import DepreciationIn, DepreciationRunIn
from tests.test_an_intangible_assets_amortisation_moves_to_its_own_ledger import CALLER, CLIENT, _create, _firm

YEAR = [f"2026-{m:02d}" for m in range(4, 13)] + [f"2027-{m:02d}" for m in range(1, 4)]


def _sl(**kw):
    row = dict(purchase_cost_paise=1_00_000_04, salvage_value_paise=0, accumulated_depreciation_paise=0,
               depreciation_method="SL", useful_life_years=5, asset_category="Intangibles")
    row.update(kw)
    return row


def _journals(db, row):
    code = row.get("asset_code") or row["id"][:8]
    return sorted(e["reference_no"][-7:] for e in db.rows("journal_entries")
                  if str(e.get("reference_no", "")).startswith(f"FA-DEPN-{code}-") and not e.get("is_reversed"))


# ── the last year of a straight-line life ──────────────────────────────────

def test_the_last_year_of_a_straight_line_life_takes_what_is_left():
    figure = 1_00_000_04 // 5                                       # 20,000.00; 4 paise left over by the floor
    assert fa._compute_annual_depreciation(_sl()) == figure
    assert fa._compute_annual_depreciation(_sl(accumulated_depreciation_paise=3 * figure)) == figure, "not before the last year"
    assert fa._compute_annual_depreciation(_sl(accumulated_depreciation_paise=4 * figure)) == figure + 4
    assert fa._compute_annual_depreciation(_sl(accumulated_depreciation_paise=1_00_000_04)) == 0


def test_a_cost_that_divides_by_its_life_is_unchanged_and_a_salvage_is_kept():
    assert fa._compute_annual_depreciation(_sl(purchase_cost_paise=1_00_000_00, accumulated_depreciation_paise=80_000_00)) == 20_000_00
    got = fa._compute_annual_depreciation(_sl(purchase_cost_paise=1_00_000_04, salvage_value_paise=5_000_00,
                                             accumulated_depreciation_paise=4 * (95_000_04 // 5)))
    assert got == 95_000_04 - 4 * (95_000_04 // 5), "the last year stops at the salvage value"


def test_through_the_route_an_asset_whose_cost_does_not_divide_reaches_nil_at_the_end_of_its_life(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles", cost=1_00_000_04, life=5, method="SL", date="2021-04-01")
    for year in range(2021, 2026):
        months = [f"{year}-{m:02d}" for m in range(4, 13)] + [f"{year + 1}-{m:02d}" for m in range(1, 4)]
        for m in months:
            assert fa.post_depreciation(row["id"], DepreciationIn(period=m), CALLER)["success"]
    assert int(row["accumulated_depreciation_paise"]) == 1_00_000_04


# ── a nil month is passed ──────────────────────────────────────────────────

def test_every_month_of_a_five_paise_year_is_reached_and_the_year_closes_at_its_figure(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Pin", category="Intangibles", cost=25, life=5, method="SL", date="2026-04-01")
    shares = [fa._month_share(5, p, None) for p in YEAR]
    assert shares == [0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1]
    for period, share in zip(YEAR, shares, strict=True):
        out = fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["data"]
        assert out["depreciation_paise"] == share
        assert out.get("passed", False) is (share == 0), (period, out)
        assert fa._month_label(row["depreciation_posted_through"]) == period, "posted-through moves past a nil month"
    assert int(row["accumulated_depreciation_paise"]) == 5
    assert _journals(db, row) == [p for p, s in zip(YEAR, shares, strict=True) if s], "a passed month makes no journal"


def test_the_range_runner_does_not_stop_at_a_nil_month(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Pin", category="Intangibles", cost=25, life=5, method="SL", date="2026-04-01")
    out = fa.run_depreciation(DepreciationRunIn(client_id=CLIENT, from_period="2026-04", to_period="2027-03"), CALLER)["data"]
    got = next(a for a in out["assets"] if a["asset_id"] == row["id"])
    assert got["stopped_at"] is None, got
    assert got["months_posted"] == 5 and got["depreciation_paise"] == 5
    assert got["months_passed"] == ["2026-04", "2026-05", "2026-07", "2026-09", "2026-10", "2026-12", "2027-02"]
    assert fa._month_label(row["depreciation_posted_through"]) == "2027-03"


def test_a_reversal_goes_back_to_a_passed_month_and_a_passed_month_can_be_reversed(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Pin", category="Intangibles", cost=25, life=5, method="SL", date="2026-04-01")
    for period in YEAR[:5]:                                          # Apr nil, May nil, Jun 1, Jul nil, Aug 1
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    out = fa.reverse_depreciation(row["id"], "2026-08", CALLER)["data"]
    assert out["reversed_paise"] == 1 and out["depreciation_posted_through"] == "2026-07-31", "back to July, which was passed"
    out = fa.reverse_depreciation(row["id"], "2026-07", CALLER)["data"]
    assert out["reversed_paise"] == 0 and out["passed"] is True and out["depreciation_posted_through"] == "2026-06-30"
    assert int(row["accumulated_depreciation_paise"]) == 1
    for period in ("2026-06", "2026-05", "2026-04"):
        assert fa.reverse_depreciation(row["id"], period, CALLER)["success"]
    assert row["depreciation_posted_through"] is None and int(row["accumulated_depreciation_paise"]) == 0
    for period in YEAR:
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    assert int(row["accumulated_depreciation_paise"]) == 5, "posted again, the year closes at its figure"


def test_the_projection_passes_a_nil_month_and_ends_fully_depreciated():
    asset = dict(_sl(purchase_cost_paise=25), id="a", asset_name="Pin", purchase_date="2026-04-01", is_disposed=False)
    got = fa.project_remaining_life(asset, "2026-04")
    assert got["ends"] == "fully_depreciated" and got["total_paise"] == 25
    assert [y["charge_paise"] for y in got["years"]] == [5, 5, 5, 5, 5]
    every = fa.project_remaining_life(asset, "2026-04", _every_month=True)
    assert every["years"] == got["years"]
