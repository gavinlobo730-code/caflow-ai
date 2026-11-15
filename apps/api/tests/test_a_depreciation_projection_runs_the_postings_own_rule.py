"""The Depreciation tab shows what the postings will charge over each asset's remaining life, year by year (POST-A-115).

WHAT WAS WRONG
    `GET /api/fixed-assets/depreciation-schedule` and the Depreciation tab showed one year: the charge of the financial year that
    contains today. Nothing showed when an asset would be fully depreciated or what each later year would charge (FA-18's second
    half).

WHAT IS HELD
    * the projection is the postings' own arithmetic: months posted through the real route, one at a time, add up to the
      projection taken before them, year by year, and a projection taken after them carries on exactly where they stopped;
    * asking a month's charge once per year (it is fixed for a financial year) gives exactly what asking it every month gives;
    * it starts at the month after the last one posted; with nothing posted, at the purchase month for an asset acquired here (no
      depreciation carried) and in the current month for one brought over part-depreciated, which says the months before it are
      then foreclosed; months still behind the current month are named;
    * it ends where a posting would: the year's figure is nil, a month's charge rounds to nil once something is posted (before
      that a nil month is passed, as a first posting may start in any month), or after PROJECTION_YEARS years; every ending says
      what stays on the register; a nil rate is not "fully depreciated"; land is not depreciated and an asset with no statutory
      basis says why;
    * the schedule row's year figure is the projection's for the current year, so a register with months behind is not shown a
      year's figure no posting can charge; the full projection is served per asset, when its row is opened;
    * each month takes its share of the year's figure, so a straight-line asset is charged its whole cost by the end of its life
      and nothing is left for a year after it (POST-A-436: twelve floored twelfths had left 40 paise on 1,00,000.00 over five
      years, posted in a sixth year, and the first version of the projection showed exactly that);
"""
from __future__ import annotations

import routers.fixed_assets as fa
from models.accounting import DepreciationIn
from tests.test_an_intangible_assets_amortisation_moves_to_its_own_ledger import CALLER, CLIENT, _create, _firm

LAKH = 1_00_000_00


def _sl(**kw):
    row = dict(id="a", asset_name="Press", asset_category="Plant and Machinery", purchase_cost_paise=LAKH, salvage_value_paise=0,
               accumulated_depreciation_paise=0, purchase_date="2026-04-01", is_disposed=False, depreciation_method="SL",
               useful_life_years=5)
    row.update(kw)
    return row


def _wdv(**kw):
    return _sl(**{"asset_category": "Computers", "depreciation_method": "WDV", "useful_life_years": 3, "wdv_rate_percent": 63.16,
                  **kw})


# ── the arithmetic ───────────────────────────────────────────────────────────

def test_a_straight_line_asset_runs_its_life_and_says_where_it_ends():
    got = fa.project_remaining_life(_sl(), "2026-04")
    assert got["starts_at"] == "2026-04" and got["start_note"] is None, "bought this month: nothing before it is foreclosed"
    years = [(y["financial_year"], y["months"], y["charge_paise"]) for y in got["years"]]
    # Each month takes its share of the year's 20,000.00, so five years charge the whole 1,00,000.00 and the sixth has nothing.
    assert years == [("2026-27", 12, 20_000_00), ("2027-28", 12, 20_000_00), ("2028-29", 12, 20_000_00),
                     ("2029-30", 12, 20_000_00), ("2030-31", 12, 20_000_00)]
    assert (got["ends"], got["total_paise"], got["years"][-1]["closing_wdv_paise"]) == ("fully_depreciated", LAKH, 0)
    assert got["end_note"] == ("The last charge is in Mar 2031; the asset then stands at ₹0.00 on the register and every later "
                               "year's figure is nil.")


def test_each_year_opens_where_the_last_closed():
    got = fa.project_remaining_life(_wdv(), "2026-04")["years"]
    assert got[0]["opening_wdv_paise"] == LAKH
    assert all(a["closing_wdv_paise"] == b["opening_wdv_paise"] for a, b in zip(got, got[1:], strict=False))
    assert all(y["opening_wdv_paise"] - y["charge_paise"] == y["closing_wdv_paise"] for y in got)


def test_asking_a_month_once_a_year_is_asking_it_every_month():
    assets = [_sl(), _wdv(), _wdv(useful_life_years=None, wdv_rate_percent=15),
              _sl(purchase_date="2026-06-17"),                                   # a pro-rated purchase month
              _sl(purchase_date="2025-10-15", accumulated_depreciation_paise=5_00_000, depreciation_posted_through="2026-06-30",
                  depreciation_fy="2026-27", depreciation_fy_start_accum_paise=0),
              _wdv(salvage_value_paise=10_000_00, depreciation_posted_through="2027-01-31", accumulated_depreciation_paise=40_00_000,
                   depreciation_fy="2026-27", depreciation_fy_start_accum_paise=0)]
    for a in assets:
        for today in ("2026-04", "2026-11"):
            assert fa.project_remaining_life(a, today) == fa.project_remaining_life(a, today, _every_month=True), a


def test_a_purchase_month_is_pro_rated_as_a_posting_pro_rates_it():
    got = fa.project_remaining_life(_sl(purchase_date="2026-06-17"), "2026-04")
    first = got["years"][0]
    assert (first["first_month"], first["months"]) == ("2026-06", 10)
    # June is the third month of the year: its share is 1,666.67, held 14 of its 30 days; July to March take the rest of the year.
    june = 20_000_00 * 3 // 12 - 20_000_00 * 2 // 12
    assert first["charge_paise"] == june * 14 // 30 + (20_000_00 - 20_000_00 * 3 // 12)


# ── where it starts and where it ends ────────────────────────────────────────

def test_an_asset_acquired_here_and_never_posted_starts_at_its_purchase_month_and_names_the_months_behind():
    got = fa.project_remaining_life(_sl(purchase_date="2026-06-10"), "2026-11")
    assert (got["starts_at"], got["years"][0]["first_month"], got["years"][0]["months"]) == ("2026-06", "2026-06", 10)
    assert got["start_note"] == ("Jun 2026 to Oct 2026 are not posted yet: this assumes they are posted, in order, as they must be "
                                 "before a later month can be.")
    assert fa.project_remaining_life(_sl(purchase_date="2027-01-01"), "2026-11")["starts_at"] == "2027-01"


def test_an_asset_brought_over_part_depreciated_starts_now_and_says_the_months_before_are_foreclosed():
    got = fa.project_remaining_life(_sl(purchase_date="2024-04-01", accumulated_depreciation_paise=40_000_00), "2026-11")
    assert got["starts_at"] == "2026-11" and "can then no longer be posted" in got["start_note"]


def test_something_posted_starts_at_the_next_month_and_names_the_months_behind():
    row = _sl(depreciation_posted_through="2026-06-30", accumulated_depreciation_paise=4_99_998, depreciation_fy="2026-27",
              depreciation_fy_start_accum_paise=0)
    got = fa.project_remaining_life(row, "2026-11")
    assert (got["starts_at"], got["years"][0]["months"]) == ("2026-07", 9) and got["start_note"].startswith("Jul 2026 to Oct 2026")
    assert fa.project_remaining_life(row, "2026-07")["start_note"] is None, "the next month due is the current one: nothing behind"


def test_a_purchase_month_that_charges_nothing_does_not_end_a_projection_with_nothing_posted():
    """30.00 over ten years is 3.00 a year, 25 paise a month; bought on 31 December, December charges 25 x 1 // 31 = nil. A posting
    of December moves nothing, so January is still a first posting and charges 25 paise."""
    got = fa.project_remaining_life(_sl(purchase_cost_paise=30_00, useful_life_years=10, purchase_date="2026-12-31"), "2026-12")
    assert got["years"][0]["first_month"] == "2027-01" and got["years"][0]["charge_paise"] == 25 * 3
    assert got["ends"] != "rounds_to_nil" or got["years"][-1]["financial_year"] > "2030-31"


def test_land_is_not_depreciated_and_an_asset_with_no_basis_says_why():
    land = fa.project_remaining_life(_sl(asset_category="Land"), "2026-11")
    assert (land["ends"], land["years"], land["start_note"]) == ("not_depreciable", [], None)
    gap = fa.project_remaining_life(_wdv(asset_category="Intangibles", wdv_rate_percent=None, useful_life_years=None), "2026-11")
    assert gap["ends"] == "no_basis" and gap["years"] == [] and gap["end_note"]


def test_a_nil_rate_is_not_called_fully_depreciated():
    got = fa.project_remaining_life(_wdv(wdv_rate_percent=0), "2026-04")
    assert (got["ends"], got["years"]) == ("nil_charge", [])
    assert "nothing is charged; it stands at ₹1,00,000.00 on the register" in got["end_note"]


def test_a_reducing_balance_with_no_floor_stops_at_the_limit_and_says_so():
    got = fa.project_remaining_life(_wdv(purchase_cost_paise=10_000_000_00, useful_life_years=None, wdv_rate_percent=0.5), "2026-04")
    assert got["ends"] == "limit" and len(got["years"]) == fa.PROJECTION_YEARS
    assert f"stops after {fa.PROJECTION_YEARS} years" in got["end_note"] and "never reaches it" in got["end_note"]


def test_an_asset_already_fully_depreciated_projects_nothing():
    got = fa.project_remaining_life(_sl(accumulated_depreciation_paise=LAKH, depreciation_posted_through="2031-03-31"), "2031-04")
    assert (got["ends"], got["years"], got["total_paise"]) == ("fully_depreciated", [], 0)
    assert got["end_note"] == "Nothing is left to charge: the asset stands at ₹0.00 on the register, its salvage value."


# ── it is the postings' own arithmetic ───────────────────────────────────────

def _post_through_and_compare(row, today, months):
    """Post `months` through the real route, one at a time, and check them against the projection taken before, year by year;
    then check the projection taken after carries on where they stopped."""
    before = fa.project_remaining_life(dict(row), today)
    by_year: dict[str, int] = {}
    for period in months:
        was = int(row.get("accumulated_depreciation_paise") or 0)
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
        fy = f"{period[:4]}-{int(period[2:4]) + 1:02d}" if period[5:] >= "04" else f"{int(period[:4]) - 1}-{period[2:4]}"
        by_year[fy] = by_year.get(fy, 0) + int(row["accumulated_depreciation_paise"]) - was
    planned = {y["financial_year"]: y for y in before["years"]}
    done = sorted(by_year)
    for fy in done[:-1]:
        assert by_year[fy] == planned[fy]["charge_paise"], fy
    last = done[-1]
    after = fa.project_remaining_life(dict(row), _next(months[-1]))
    assert after["starts_at"] == _next(months[-1])
    rest_of_last = next((y["charge_paise"] for y in after["years"] if y["financial_year"] == last), 0)
    assert by_year[last] + rest_of_last == planned[last]["charge_paise"]
    assert [y for y in after["years"] if y["financial_year"] > last] == [y for y in before["years"] if y["financial_year"] > last]
    return before


def _next(period):
    return fa._next_month(period)


def _months(first, last):
    out, p = [], first
    while p <= last:
        out.append(p)
        p = _next(p)
    return out


def test_the_months_posted_through_the_route_are_the_projection(monkeypatch):
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV", date="2025-04-05")
    before = _post_through_and_compare(row, "2025-04", _months("2025-04", "2026-10"))
    assert before["years"][0]["charge_paise"] > 0


def test_a_straight_line_asset_across_its_capped_last_year_is_the_projection(monkeypatch):
    """1,00,000.00 over two years, bought in October: half a year, a whole one, and a third year whose figure is capped at what the
    first two left, so this posts across the cap."""
    db = _firm(monkeypatch)
    row = _create(db, name="Licence", category="Intangibles", cost=LAKH, life=2, method="SL", date="2024-10-01")
    before = _post_through_and_compare(row, "2024-10", _months("2024-10", "2026-10"))
    assert [y["financial_year"] for y in before["years"]][:3] == ["2024-25", "2025-26", "2026-27"]
    assert before["years"][2]["year_figure_paise"] < before["years"][1]["year_figure_paise"], "the third year is the capped one"
    assert before["total_paise"] == LAKH, "and the life charges the whole cost"


def test_an_asset_brought_over_mid_year_is_the_projection(monkeypatch):
    """The opening register's shape: depreciation carried, posted through a month in the middle of a year, no year recorded."""
    db = _firm(monkeypatch)
    row = _create(db, name="Press", category="Plant & Machinery", life=15, method="WDV", date="2022-04-01")
    row.update(accumulated_depreciation_paise=30_000_00, depreciation_posted_through="2025-09-30", depreciation_fy=None,
               depreciation_fy_start_accum_paise=None)
    _post_through_and_compare(row, "2025-10", _months("2025-10", "2026-10"))


def test_the_projection_is_served_per_asset_and_another_clients_asset_is_not_found(monkeypatch):
    from fastapi import HTTPException
    db = _firm(monkeypatch)
    lathe = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV")
    got = fa.remaining_life(lathe["id"], CALLER)["data"]
    assert got == fa.project_remaining_life(lathe, fa.ist_today().strftime("%Y-%m")) and got["years"]
    other_firm = _create(db, name="Press", category="Plant & Machinery", life=15, method="WDV")
    other_firm["firm_id"] = "FIRM-ELSE"

    def refused(asset_id, caller=CALLER):
        try:
            fa.remaining_life(asset_id, caller)
        except HTTPException as e:
            return (e.status_code, e.detail)
        return None

    assert refused("no-such-asset") == refused(other_firm["id"]) == (404, "Asset not found")
    monkeypatch.setattr(fa, "can_access_client", lambda user, client_id: False)   # a member not assigned to the client
    assert refused(lathe["id"]) == (404, "Asset not found"), "one sentence for a missing asset and one the caller cannot reach"


def test_the_schedule_rows_year_figure_is_the_one_the_postings_will_reach(monkeypatch):
    """A WDV asset posted through December 2025, looked at in November 2026: January to March 2026 must be posted first, and the
    year 2026-27 opens on what they leave. The row's figure is that year's, not one worked out from the register as it stands."""
    import datetime
    db = _firm(monkeypatch)
    row = _create(db, name="Lathe", category="Plant & Machinery", life=15, method="WDV", date="2025-04-01")
    for period in _months("2025-04", "2025-12"):
        assert fa.post_depreciation(row["id"], DepreciationIn(period=period), CALLER)["success"]
    monkeypatch.setattr(fa, "ist_today", lambda: datetime.date(2026, 11, 10))
    got = next(r for r in fa.depreciation_schedule(client_id=CLIENT, current_user=CALLER)["data"] if r["asset_id"] == row["id"])
    projected = fa.project_remaining_life(dict(row), "2026-11", through_fy="2026-27")["years"]
    assert got["annual_depreciation_paise"] == next(y for y in projected if y["financial_year"] == "2026-27")["year_figure_paise"]
    assert got["annual_depreciation_paise"] != fa._annual_depreciation_for_period(dict(row), "2026-11")[0], \
        "the register as it stands gives a different figure, which no posting can charge"
    assert "remaining_life" not in got, "the full projection is asked for one asset when its row is opened"
