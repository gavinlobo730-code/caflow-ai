"""A year's depreciation is posted in full: each month takes its share of the year's figure, and the twelve add up to it (POST-A-436).

WHAT WAS WRONG
    `routers/fixed_assets._month_charge` charged `floor(annual / 12)` every month of a financial year, so a year whose figure is
    20,000.00 posted 19,999.92 while the Depreciation tab showed 20,000.00 as the year's charge, and the shortfall carried: a
    straight-line asset of 1,00,000.00 over five years was 40 paise short at the end of its life, posted 36 of them at three paise a
    month in a sixth year, and the last four never posted. The remaining-life projection (POST-A-115) showed exactly that.

WHAT IS HELD
    * month k of the year (April is 1) charges `annual x k // 12 - annual x (k - 1) // 12`: the twelve add up to the year's figure
      exactly, any run of months from k to March to `annual - annual x (k - 1) // 12`, and no two months differ by more than a paisa;
    * through the route, a reducing-balance asset posts its whole year's figure in each full year, and a straight-line asset reaches
      nil at the end of its life with nothing left for a year after it;
    * through the route, a year begun in October posts each month at its financial-year share (October is the seventh month, not
      the tenth: a figure that leaves nine paise over twelve tells the two apart);
    * the schedule's monthly figure is the share today's month takes, and a reversal takes back what that month's journal carries
      (it reads the journal, never this rule): months reversed and posted again post the same shares and the year still closes at
      its figure.
"""
from __future__ import annotations

import pytest

import routers.fixed_assets as fa
from models.accounting import DepreciationIn
from tests.test_an_intangible_assets_amortisation_moves_to_its_own_ledger import CALLER, CLIENT, _create, _firm

LAKH = 1_00_000_00
MONTHS = [f"2026-{m:02d}" for m in range(4, 13)] + [f"2027-{m:02d}" for m in range(1, 4)]


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("annual", [0, 1, 5, 11, 12, 13, 23, 1_000, 19_99_999, 20_00_000, 20_00_001, 4_653_840, 9_99_99_99_999])
def test_the_twelve_shares_add_up_to_the_year_and_differ_by_a_paisa_at_most(annual):
    shares = [fa._month_share(annual, p, None) for p in MONTHS]
    assert sum(shares) == annual
    assert max(shares) - min(shares) <= 1
    for k in range(1, 13):                                          # a year begun in month k (a migrated or new asset)
        assert sum(shares[k - 1:]) == annual - annual * (k - 1) // 12


def test_april_is_the_first_month_and_march_the_twelfth():
    assert [fa._month_of_the_year(p) for p in MONTHS] == list(range(1, 13))


def test_the_purchase_month_is_its_share_pro_rated_by_the_days_held():
    # June is the third month; bought on 17 June, it is held 14 of 30 days.
    assert fa._month_share(20_000_00, "2026-06", "2026-06-17") == (20_000_00 * 3 // 12 - 20_000_00 * 2 // 12) * 14 // 30
    assert fa._month_share(20_000_00, "2026-07", "2026-06-17") == 20_000_00 * 4 // 12 - 20_000_00 * 3 // 12


# ── through the route ────────────────────────────────────────────────────────

def _post_year(row, first_year):
    for m in [f"{first_year}-{x:02d}" for x in range(4, 13)] + [f"{first_year + 1}-{x:02d}" for x in range(1, 4)]:
        assert fa.post_depreciation(row["id"], DepreciationIn(period=m), CALLER)["success"]


def test_a_reducing_balance_asset_posts_its_whole_years_figure(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", cost=1_00_000_07, life=15, method="WDV", date="2025-04-01")
    figures = []
    for year in (2025, 2026):
        opening = int(row.get("accumulated_depreciation_paise") or 0)
        annual, fy, _ = fa._annual_depreciation_for_period(dict(row, depreciation_fy=None), f"{year}-04")
        _post_year(row, year)
        assert int(row["accumulated_depreciation_paise"]) - opening == annual > 0, (fy, annual)
        figures.append(annual)
    assert any(f % 12 for f in figures), "a figure that does not divide into twelve, which is the case that used to fall short"


def test_a_straight_line_asset_reaches_nil_at_the_end_of_its_life(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles", cost=LAKH, life=5, method="SL", date="2021-04-01")
    for year in range(2021, 2026):
        _post_year(row, year)
    assert int(row["accumulated_depreciation_paise"]) == LAKH
    after = fa.post_depreciation(row["id"], DepreciationIn(period="2026-04"), CALLER)["data"]
    assert after["depreciation_paise"] == 0 and int(row["accumulated_depreciation_paise"]) == LAKH


def test_the_schedule_shows_the_share_the_month_being_posted_takes(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles", cost=LAKH, life=5, method="SL", date="2025-04-01")
    monkeypatch.setattr(fa, "ist_today", lambda: __import__("datetime").date(2026, 5, 10))
    got = next(r for r in fa.depreciation_schedule(client_id=CLIENT, current_user=CALLER)["data"] if r["asset_id"] == row["id"])
    assert got["annual_depreciation_paise"] == 20_000_00
    assert got["monthly_depreciation_paise"] == fa._month_share(20_000_00, "2026-05", row["purchase_date"]) == 1_666_67


def test_a_year_begun_in_october_posts_each_month_at_its_financial_year_share(monkeypatch):
    """1,00,000.65 over five years is 20,000.13 a year, nine paise over twelve twelfths, so the month index matters: October is the
    seventh month of the financial year and its share differs from the tenth's in at least one month of the half year."""
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles", cost=1_00_000_65, life=5, method="SL", date="2026-10-01")
    annual = 20_000_13
    posted = []
    for period in ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]:
        was = int(row.get("accumulated_depreciation_paise") or 0)
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
        posted.append(int(row["accumulated_depreciation_paise"]) - was)
    assert posted == [annual * k // 12 - annual * (k - 1) // 12 for k in range(7, 13)]
    assert posted != [annual * k // 12 - annual * (k - 1) // 12 for k in (10, 11, 12, 1, 2, 3)], "the indexes must differ here"
    assert sum(posted) == annual - annual * 6 // 12


def test_a_month_reversed_and_posted_again_posts_the_same_share(monkeypatch):
    """A reversal takes back what the month's journal carries; posting the month again takes its share again, so the year still
    closes at its figure."""
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles", cost=LAKH, life=5, method="SL", date="2026-04-01")
    first = []
    for period in ["2026-04", "2026-05", "2026-06", "2026-07"]:
        was = int(row.get("accumulated_depreciation_paise") or 0)
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
        first.append(int(row["accumulated_depreciation_paise"]) - was)
    for period in ("2026-07", "2026-06"):
        assert fa.reverse_depreciation(row["id"], period, CALLER)["success"]
    assert int(row["accumulated_depreciation_paise"]) == sum(first[:2])
    again = []
    for period in ["2026-06", "2026-07"]:
        was = int(row["accumulated_depreciation_paise"])
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
        again.append(int(row["accumulated_depreciation_paise"]) - was)
    assert again == first[2:] == [20_000_00 * 3 // 12 - 20_000_00 * 2 // 12, 20_000_00 * 4 // 12 - 20_000_00 * 3 // 12]
    _post_year_from(row, "2026-08")
    assert int(row["accumulated_depreciation_paise"]) == 20_000_00, "the year closes at its figure"


def _post_year_from(row, first):
    months = [f"2026-{m:02d}" for m in range(4, 13)] + [f"2027-{m:02d}" for m in range(1, 4)]
    for m in months[months.index(first):]:
        assert fa.post_depreciation(row["id"], DepreciationIn(period=m), CALLER)["success"]
