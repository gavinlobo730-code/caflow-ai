"""Realization prices each hour from the rate it was recorded with, and is not shown where that is not known (POST-A-426),
and the three analytics endpoints open any financial year (POST-A-427).

WHAT WAS WRONG, measured on the code this replaced (each is a test below):

  * `get_effort_by_engagement` averaged the LEGACY `hourly_rate_paise` of the entries that carried one and the report
    multiplied that average by ALL the engagement's billable minutes. Since migration 451 an hour is priced when it is
    recorded and the answer is stored in `billable_rate_paise`, and `hourly_rate_paise` is NULL on every entry the timer
    started, so a firm that prices its time that way saw a dash against every engagement, and one that had a few legacy
    entries had the rest of its hours priced at theirs;
  * an engagement with time and no invoice was not a row although the firm's total counted its hours;
  * the server answered the firm's figure as `realization_rate` and the browser read `overall_realization_rate`, so the
    tile was a dash whatever the books held;
  * the window was this week, this month or this quarter to date and any other word was read as the month, so last
    financial year could not be opened.

THE RULES THESE TESTS HOLD:

  * an entry is priced from `billable_rate_paise`, then `hourly_rate_paise`, floored once per entry; a stated 0 is a rate;
  * an entry nobody priced is named (`unpriced_minutes`) and is not worth 0; a row with one has NO realization;
  * time with no invoice is a row whose realization is 0.0 when its time is priced;
  * the firm's figure is revenue over the whole worth, and it is None while any billable minute is unpriced;
  * a window is a financial year when it is asked for as one, an unknown window is a 422, and a financial year given with
    any other window is a 422 too.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from domain.billing import time_rate
from domain.practice import realization as rule

API = Path(__file__).resolve().parents[1]


def _entry(minutes, *, billable=None, hourly=None, engagement="e1", is_billable=True, client="A"):
    return {"duration_minutes": minutes, "is_billable": is_billable, "billable_rate_paise": billable,
            "hourly_rate_paise": hourly, "engagement_id": engagement, "client_id": client}


# ════════════════════════════════════════════════════════
# the rule
# ════════════════════════════════════════════════════════

def test_the_stored_billing_rate_comes_first_and_the_legacy_one_second():
    assert time_rate.entry_rate({"billable_rate_paise": 50_000, "hourly_rate_paise": 90_000}) == 50_000
    assert time_rate.entry_rate({"billable_rate_paise": None, "hourly_rate_paise": 90_000}) == 90_000
    assert time_rate.entry_rate({"hourly_rate_paise": 90_000}) == 90_000
    assert time_rate.entry_rate({}) is None


def test_a_stated_zero_is_a_rate_and_is_not_passed_over_for_the_second_column():
    assert time_rate.entry_rate({"billable_rate_paise": 0, "hourly_rate_paise": 90_000}) == 0


def test_the_unbilled_work_total_and_realization_price_an_hour_through_the_same_function():
    """One function says what an hour is worth, so the two screens cannot disagree about the same hour."""
    entry = {"is_billable": True, "duration_minutes": 90, "billable_rate_paise": 40_000, "hourly_rate_paise": 90_000,
             "client_id": "A", "task_id": "t"}
    assert time_rate.entry_group(entry)["value_paise"] == 60_000
    assert rule.fold_worth([{**entry, "engagement_id": "e1"}], "engagement_id")["e1"].value_paise == 60_000


def test_an_hour_priced_only_by_the_stored_rate_is_worth_it_and_realizes():
    """The defect itself: every timer entry has no legacy rate, so the old read found no rate and the screen drew a dash."""
    worth = rule.fold_worth([_entry(120, billable=50_000), _entry(60, billable=50_000)], "engagement_id")["e1"]
    assert (worth.billable_minutes, worth.unpriced_minutes, worth.value_paise) == (180, 0, 150_000)
    assert rule.realization_rate(120_000, worth) == 0.8


def test_one_entry_with_a_legacy_rate_does_not_price_the_nine_beside_it():
    """The old read averaged the one rate it found and applied it to all ten hours."""
    entries = [_entry(60, hourly=200_000)] + [_entry(60) for _ in range(9)]
    worth = rule.fold_worth(entries, "engagement_id")["e1"]
    assert (worth.billable_minutes, worth.unpriced_minutes, worth.priced_value_paise) == (600, 540, 200_000)
    assert worth.value_is_known is False
    assert rule.realization_rate(1_000_000, worth) is None, "a ratio against a fifth of the worth is five times too high"


def test_an_entry_nobody_priced_is_unknown_not_worth_nothing():
    worth = rule.fold_worth([_entry(60)], "engagement_id")["e1"]
    assert (worth.unpriced_minutes, worth.priced_value_paise, worth.value_is_known) == (60, None, False)
    assert rule.realization_rate(500_000, worth) is None


def test_non_billable_and_empty_entries_are_not_counted():
    worth = rule.fold_worth([_entry(60, billable=10_000, is_billable=False), _entry(0, billable=10_000),
                             _entry(None, billable=10_000), _entry(30, billable=10_000)], "engagement_id")
    assert worth["e1"].billable_minutes == 30 and worth["e1"].value_paise == 5_000


def test_time_with_no_engagement_is_the_group_none_and_is_in_no_row():
    groups = rule.fold_worth([_entry(60, billable=10_000, engagement=None)], "engagement_id")
    assert groups[None].billable_minutes == 60
    assert rule.rows({}, groups) == []
    assert rule.firm({}, groups).worth.billable_minutes == 0, "time that names no engagement is in no total"


def test_a_row_is_floored_once_per_entry_and_the_floors_are_what_it_adds_up():
    worth = rule.fold_worth([_entry(1, billable=50), _entry(1, billable=50)], "engagement_id")["e1"]
    assert worth.value_paise == 0, "a minute at 50 paise an hour is a floor of 0, twice: the floor of the sum would be 1"


def test_a_worth_of_nothing_has_no_realization_and_no_time_has_none_either():
    zero = rule.fold_worth([_entry(60, billable=0)], "engagement_id")["e1"]
    assert zero.value_is_known and rule.realization_rate(10_000, zero) is None, "a ratio against ₹0 is undefined"
    assert rule.realization_rate(10_000, rule.Worth()) is None


def test_time_billed_for_nothing_is_a_realization_of_zero_and_is_a_row():
    groups = rule.fold_worth([_entry(60, billable=60_000, engagement="never-billed")], "engagement_id")
    row = rule.rows({"billed": 100_000}, {**groups, "billed": rule.Worth(60, 0, 60_000)})
    by_key = {r.key: r for r in row}
    assert by_key["never-billed"].revenue_paise == 0 and by_key["never-billed"].realization_rate == 0.0
    assert by_key["never-billed"].revenue_per_hour_paise == 0
    assert by_key["billed"].realization_rate == 1.67


def test_revenue_with_no_billable_time_has_no_revenue_per_hour():
    assert rule.revenue_per_hour_paise(100_000, 0) is None
    assert rule.revenue_per_hour_paise(100_000, 120) == 50_000


def test_the_firm_figure_is_none_while_any_billable_minute_is_unpriced():
    worth = {"e1": rule.Worth(60, 0, 100_000), "e2": rule.Worth(60, 60, 0)}
    firm = rule.firm({"e1": 100_000, "e2": 100_000}, worth)
    assert firm.worth.unpriced_minutes == 60 and firm.realization_rate is None
    assert firm.worth.priced_value_paise == 100_000
    assert rule.firm({"e1": 100_000}, {"e1": worth["e1"]}).realization_rate == 1.0


def test_fees_on_an_engagement_nobody_timed_are_named_and_left_out_of_the_roll_ups_ratio():
    """THE DEFECT TWO REVIEWERS FOUND. A timed audit (₹1,000 against ₹1,000 of time) and a fixed-fee return with no time (₹9,000):
    the firm read 10.00× and ₹10,000 an hour above rows that said 1.00× and a dash."""
    revenue = {"audit": 100_000, "gst": 900_000}
    worth = {"audit": rule.Worth(60, 0, 100_000)}
    by_key = {r.key: r for r in rule.rows(revenue, worth)}
    assert by_key["audit"].realization_rate == 1.0 and by_key["audit"].revenue_without_time_paise == 0
    assert by_key["gst"].realization_rate is None and by_key["gst"].revenue_per_hour_paise is None
    assert by_key["gst"].revenue_without_time_paise == 900_000
    firm = rule.firm(revenue, worth)
    assert (firm.revenue_paise, firm.revenue_without_time_paise) == (1_000_000, 900_000)
    assert firm.realization_rate == 1.0 and firm.revenue_per_hour_paise == 100_000


def test_combine_adds_the_rows_and_each_part_keeps_its_own_comparison():
    parts = rule.rows({"a": 100_000, "b": 50_000, "c": 70_000},
                      {"a": rule.Worth(60, 0, 200_000), "b": rule.Worth(30, 0, 100_000)})
    total = rule.combine("client", parts)
    assert (total.revenue_paise, total.compared_paise, total.revenue_without_time_paise) == (220_000, 150_000, 70_000)
    assert (total.worth.billable_minutes, total.worth.value_paise) == (90, 300_000)
    assert total.realization_rate == 0.5


def test_invoices_and_time_that_name_no_engagement_are_counted_apart_by_client():
    invoices = [{"client_id": "A", "engagement_id": None, "status": "Issued", "amount_paise": 40_000},
                {"client_id": "A", "engagement_id": None, "status": "Draft", "amount_paise": 999_000},
                {"client_id": "A", "engagement_id": "e1", "status": "Issued", "amount_paise": 70_000},
                {"client_id": "B", "engagement_id": None, "status": "Paid", "amount_paise": 5_000},
                {"client_id": None, "engagement_id": None, "status": "Issued", "amount_paise": 1}]
    assert rule.revenue_outside_engagements(invoices) == {"A": 40_000, "B": 5_000}
    entries = [_entry(60, billable=1, engagement=None, client="A"), _entry(30, billable=1, engagement=None, client="A"),
               _entry(45, billable=1, engagement=None, client=None), _entry(60, billable=1, engagement="e1", client="A"),
               _entry(60, billable=1, engagement=None, client="A", is_billable=False), _entry(0, billable=1, engagement=None)]
    assert rule.minutes_outside_engagements(entries) == {"A": 90, None: 45}


def test_a_row_with_no_revenue_and_no_time_is_not_a_row():
    assert rule.rows({"x": 0}, {"y": rule.Worth()}) == []


def test_the_rows_are_in_the_order_of_the_fee_then_the_key():
    rows = rule.rows({"b": 5, "a": 5, "c": 9}, {})
    assert [r.key for r in rows] == ["c", "a", "b"]


# ════════════════════════════════════════════════════════
# the endpoint, over the real repositories and a database that has the row cap
# ════════════════════════════════════════════════════════

import routers.analytics as an  # noqa: E402
from tests._capped_postgrest import DB_MAX_ROWS, CappedDB  # noqa: E402

FIRM = "firm-real"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}
A, B, C = "client-a", "client-b", "client-c"
NAMES = {A: "A Ltd", B: "B Ltd", C: "C Ltd"}
ENGS = [{"id": "ea", "client_id": A, "service_type": "Audit"},
        {"id": "eb", "client_id": B, "service_type": "GST"},
        {"id": "ec", "client_id": C, "service_type": "Tax"}]


def _window() -> tuple[str, str]:
    date_from, date_to, _ = an._period_range("month")
    return date_from, date_to


def _fee(i, client, engagement, amount, status="Issued"):
    date_from, _ = _window()
    return {"id": f"inv{i:05d}", "firm_id": FIRM, "client_id": client, "engagement_id": engagement, "status": status,
            "invoice_date": date_from, "is_deleted": False, "amount_paise": amount,
            "gst_paise": amount * 18 // 100, "total_paise": amount + amount * 18 // 100}


def _time(i, client, engagement, minutes, **extra):
    date_from, _ = _window()
    return {"id": f"te{i:05d}", "firm_id": FIRM, "user_id": "u1", "client_id": client, "engagement_id": engagement,
            "duration_minutes": minutes, "is_billable": True, "started_at": f"{date_from}T10:00:00+05:30",
            "ended_at": f"{date_from}T11:00:00+05:30", "hourly_rate_paise": None, "billable_rate_paise": None, **extra}


@pytest.fixture
def book(monkeypatch):
    import core.authz as authz
    import core.db_provider as provider
    import repositories.client_repository as cr
    import repositories.engagement_repository as er
    import repositories.invoice_repository as ir
    import repositories.time_tracking_analytics_repository as tta

    def install(invoices=(), entries=(), scope=None):
        db = CappedDB({"fee_invoices": list(invoices), "time_entries": list(entries), "users": []})
        monkeypatch.setattr(ir, "_USE_MOCK", False)
        monkeypatch.setattr(ir, "_get_db", lambda: db)
        monkeypatch.setattr(tta, "_USE_MOCK", False)
        monkeypatch.setattr(tta, "_get_db", lambda: db)
        monkeypatch.setattr(provider, "service_db", lambda: db)
        monkeypatch.setattr(authz, "effective_client_ids", lambda user: scope)
        monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: [{"id": c, "client_name": n} for c, n in NAMES.items()])
        monkeypatch.setattr(er.engagement_repo, "find_all", lambda **kw: ENGS)
        monkeypatch.setattr(an, "_get_db", lambda: db)
        return db

    return install


def _real(**kw):
    return an.revenue_vs_effort(period="month", current_user=USER, **kw)["data"]


def test_a_firm_that_prices_its_time_with_the_stored_rates_gets_a_realization(book):
    book(invoices=[_fee(1, A, "ea", 80_000)], entries=[_time(1, A, "ea", 120, billable_rate_paise=50_000)])
    data = _real()
    row = next(e for e in data["by_engagement"] if e["engagement_id"] == "ea")
    assert row["billable_time_value_paise"] == 100_000 and row["realization_rate"] == 0.8
    assert (data["realization_rate"], data["unpriced_minutes"]) == (0.8, 0)
    client = next(c for c in data["by_client"] if c["client_id"] == A)
    assert client["realization_rate"] == 0.8 and client["revenue_per_hour_paise"] == 40_000


def test_a_row_with_an_unpriced_hour_shows_no_realization_and_names_the_minutes(book):
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, B, "eb", 100_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, B, "eb", 60),
                  _time(3, B, "eb", 60, hourly_rate_paise=100_000)])
    data = _real()
    rows = {e["engagement_id"]: e for e in data["by_engagement"]}
    assert rows["ea"]["realization_rate"] == 1.0 and rows["ea"]["unpriced_minutes"] == 0
    assert rows["eb"]["realization_rate"] is None and rows["eb"]["unpriced_minutes"] == 60
    assert rows["eb"]["billable_time_value_paise"] == 100_000, "the priced hour is still shown"
    assert data["realization_rate"] is None and data["unpriced_minutes"] == 60
    assert {c["client_id"]: c["realization_rate"] for c in data["by_client"]} == {A: 1.0, B: None}


def test_an_engagement_with_time_and_no_invoice_is_listed_with_a_realization_of_zero(book):
    book(invoices=[_fee(1, A, "ea", 100_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, C, "ec", 120, billable_rate_paise=50_000)])
    data = _real()
    row = next(e for e in data["by_engagement"] if e["engagement_id"] == "ec")
    assert (row["revenue_paise"], row["effort_minutes"], row["realization_rate"]) == (0, 120, 0.0)
    assert any(c["client_id"] == C for c in data["by_client"])
    assert data["total_billable_minutes"] == 180
    assert data["realization_rate"] == round(100_000 / 200_000, 2), "the firm's worth includes the time nobody invoiced"


def test_revenue_is_the_fee_before_gst_and_only_for_issued_invoices(book):
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, A, "ea", 900_000, status="Draft"),
                   _fee(3, A, "ea", 50_000, status="Overdue")],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000)])
    assert _real()["total_revenue_paise"] == 150_000


def test_time_with_no_engagement_is_counted_apart_and_is_in_no_total(book):
    book(invoices=[_fee(1, A, "ea", 100_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, A, None, 300, billable_rate_paise=100_000)])
    data = _real()
    assert data["minutes_without_engagement"] == 300 and data["total_billable_minutes"] == 60
    assert data["realization_rate"] == 1.0


def test_an_assigned_caller_gets_the_figure_of_their_own_book_and_their_own_loose_time(book):
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, B, "eb", 100_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, B, "eb", 600, billable_rate_paise=100_000),
                  _time(3, B, None, 900, billable_rate_paise=100_000), _time(4, A, None, 30, billable_rate_paise=100_000)],
         scope={A})
    data = _real()
    assert {c["client_id"] for c in data["by_client"]} == {A}
    assert data["total_revenue_paise"] == 100_000 and data["total_billable_minutes"] == 60
    assert data["minutes_without_engagement"] == 30, "another client's loose time is not the caller's to read"


def test_fifteen_hundred_time_entries_are_all_counted_not_the_first_thousand(book):
    entries = [_time(i, A, "ea", 60, billable_rate_paise=10_000) for i in range(1, 1501)]
    assert len(entries) > DB_MAX_ROWS
    db = book(invoices=[_fee(1, A, "ea", 5_000_000)], entries=entries)
    data = _real()
    assert data["total_billable_minutes"] == 1500 * 60 and data["billable_time_value_paise"] == 1500 * 10_000
    assert len(db.requests["time_entries"]) >= 2


def test_a_firm_wide_caller_keeps_the_time_on_an_engagement_the_list_no_longer_carries(book):
    """Revenue on an engagement the list lacks stays in the totals, so its time stays too: the two sides are the same engagements."""
    book(invoices=[_fee(1, A, "gone", 100_000)], entries=[_time(1, A, "gone", 60, billable_rate_paise=100_000)])
    data = _real()
    row = next(e for e in data["by_engagement"] if e["engagement_id"] == "gone")
    assert (row["service_type"], row["revenue_paise"], row["effort_minutes"], row["realization_rate"]) == ("Unknown", 100_000, 60, 1.0)
    assert data["realization_rate"] == 1.0


def test_a_fixed_fee_engagement_nobody_timed_does_not_inflate_the_firms_or_the_clients_figure(book):
    """The tile showed 10.00× and ₹10,000 an hour above rows reading 1.00× and a dash."""
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, B, "eb", 900_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000)])
    data = _real()
    assert (data["realization_rate"], data["avg_revenue_per_hour_paise"]) == (1.0, 100_000)
    assert (data["total_revenue_paise"], data["revenue_without_time_paise"]) == (1_000_000, 900_000)
    clients = {c["client_id"]: c for c in data["by_client"]}
    assert clients[A]["realization_rate"] == 1.0 and clients[A]["revenue_without_time_paise"] == 0
    assert clients[B]["realization_rate"] is None and clients[B]["revenue_without_time_paise"] == 900_000
    engagements = {e["engagement_id"]: e for e in data["by_engagement"]}
    assert engagements["eb"]["realization_rate"] is None and engagements["eb"]["revenue_without_time_paise"] == 900_000


def test_a_client_with_two_engagements_is_the_sum_of_both(book, monkeypatch):
    """Every other fixture has one engagement a client, so a roll-up that kept the last engagement instead of adding passed."""
    two = ENGS + [{"id": "ea2", "client_id": A, "service_type": "Tax"}]
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, A, "ea2", 50_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=200_000), _time(2, A, "ea2", 30, billable_rate_paise=200_000),
                  _time(3, A, "ea2", 30)])
    monkeypatch.setattr(an.engagement_repo, "find_all", lambda **kw: two)  # the fixture's list, with a second one for the client
    data = _real()
    client = next(c for c in data["by_client"] if c["client_id"] == A)
    assert client["revenue_paise"] == 150_000 and client["effort_minutes"] == 120
    assert client["unpriced_minutes"] == 30, "the client's unpriced hours are the sum of its engagements', and are what the row names"
    assert client["billable_time_value_paise"] == 300_000 and client["realization_rate"] is None


def test_a_row_whose_hours_are_all_unpriced_has_no_value_and_not_a_value_of_zero(book):
    """`billable_time_value_paise` is null for the engagement, the client and the firm when no hour behind it has a rate."""
    book(invoices=[_fee(1, A, "ea", 100_000)], entries=[_time(1, A, "ea", 60)])
    data = _real()
    assert data["billable_time_value_paise"] is None
    assert data["by_engagement"][0]["billable_time_value_paise"] is None
    assert data["by_client"][0]["billable_time_value_paise"] is None
    assert data["unpriced_minutes"] == 60 and data["by_client"][0]["unpriced_minutes"] == 60


def test_invoices_and_time_naming_no_engagement_are_named_by_client_and_for_the_firm(book):
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, A, None, 40_000), _fee(3, B, None, 5_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, A, None, 90, billable_rate_paise=100_000)])
    data = _real()
    assert data["revenue_without_engagement_paise"] == 45_000 and data["minutes_without_engagement"] == 90
    client = next(c for c in data["by_client"] if c["client_id"] == A)
    assert (client["revenue_without_engagement_paise"], client["minutes_without_engagement"]) == (40_000, 90)
    assert data["total_revenue_paise"] == 100_000 and data["total_billable_minutes"] == 60
    assert not any(c["client_id"] == B for c in data["by_client"]), "a client with only invoices naming no engagement has no row"


def test_an_assigned_callers_figures_name_only_their_own_clients_fees_and_hours(book):
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, B, "eb", 100_000), _fee(3, B, None, 7_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, B, "eb", 60, billable_rate_paise=100_000)],
         scope={A})
    data = _real()
    assert data["revenue_without_engagement_paise"] == 0, "another client's fee is not the caller's to read"
    assert {e["engagement_id"] for e in data["by_engagement"]} == {"ea"}
    assert data["total_billable_minutes"] == 60 and data["billable_time_value_paise"] == 100_000


def test_an_archived_client_keeps_its_name_beside_its_fees_as_profitability_gives_it(book, monkeypatch):
    """The realization read left archived clients out of the names, so a client archived mid-period read 'Unknown'."""
    import repositories.client_repository as cr
    book(invoices=[_fee(1, A, "ea", 100_000)], entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000)])
    seen = {}

    def find_all(**kw):
        seen.update(kw)
        return [{"id": A, "client_name": "A Ltd"}]
    monkeypatch.setattr(cr.client_repo, "find_all", find_all)
    assert _real()["by_client"][0]["client_name"] == "A Ltd" and seen.get("include_archived") is True


@pytest.mark.parametrize("endpoint", ["profitability_analytics", "fee_concentration", "revenue_vs_effort"])
def test_every_analytics_endpoint_reads_archived_clients_for_their_names(book, monkeypatch, endpoint):
    """A client archived during the period still has its fees and hours in it, and without its name the row reads 'Unknown'
    beside real money. The three endpoints are one screen, so they ask the same question of the client list."""
    import repositories.client_repository as cr
    book(invoices=[_fee(1, A, "ea", 100_000)], entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000)])
    seen = []
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: seen.append(kw) or [{"id": A, "client_name": "A Ltd"}])
    getattr(an, endpoint)(period="month", current_user=USER)
    assert seen and all(kw.get("include_archived") is True for kw in seen), f"{endpoint} left archived clients out: {seen}"


def test_the_figures_do_not_depend_on_the_engagement_or_client_lists_being_complete(book, monkeypatch):
    """The lists carry labels. A list cut short by the database's row cap costs a name, never a fee or an hour."""
    import repositories.client_repository as cr
    book(invoices=[_fee(1, A, "ea", 100_000)], entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000)])
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: [])
    monkeypatch.setattr(an.engagement_repo, "find_all", lambda **kw: [])
    data = _real()
    assert (data["total_revenue_paise"], data["total_billable_minutes"], data["realization_rate"]) == (100_000, 60, 1.0)
    assert data["by_client"][0]["client_name"] == "Unknown" and data["by_engagement"][0]["service_type"] == "Unknown"


def test_the_filters_narrow_the_lists_and_leave_the_totals_alone(book):
    book(invoices=[_fee(1, A, "ea", 100_000), _fee(2, B, "eb", 100_000)],
         entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000), _time(2, B, "eb", 60, billable_rate_paise=100_000)])
    data = _real(client_id=A)
    assert [c["client_id"] for c in data["by_client"]] == [A]
    assert data["total_revenue_paise"] == 200_000


WEB_API_TS = API.parent / "web" / "lib" / "api" / "index.ts"


def _ts_block(text: str, opening: str, closing: str) -> str:
    m = re.search(re.escape(opening) + r"(.*?)" + closing, text, re.S)
    assert m, f"{opening!r} is no longer declared in lib/api/index.ts"
    return m.group(1)


def _ts_keys(block: str, indent: int) -> set[str]:
    return set(re.findall(rf"^ {{{indent}}}(\w+)\??:", block, re.M))


def test_the_browsers_payload_names_the_keys_the_endpoint_answers(book):
    """The server answered `realization_rate` and the browser read `overall_realization_rate`: the firm's tile was a dash
    whatever the books held. A key either side renames now fails here, from the side that owns the payload."""
    ts = WEB_API_TS.read_text(encoding="utf-8")
    interface = _ts_block(ts, "export interface RealizationPayload {", r"\n\}\n")
    book(invoices=[_fee(1, A, "ea", 100_000)], entries=[_time(1, A, "ea", 60, billable_rate_paise=100_000)])
    data = _real()
    assert _ts_keys(interface, 2) == set(data)
    assert _ts_keys(_ts_block(interface, "by_client: {", r"\n  \}\[\];"), 4) == set(data["by_client"][0])
    assert _ts_keys(_ts_block(interface, "by_engagement: {", r"\n  \}\[\];"), 4) == set(data["by_engagement"][0])


# ════════════════════════════════════════════════════════
# the window (POST-A-427)
# ════════════════════════════════════════════════════════

def _today(monkeypatch, d):
    monkeypatch.setattr("routers.analytics.ist_today", lambda: d)


def test_a_past_financial_year_is_the_whole_year(monkeypatch):
    _today(monkeypatch, date(2026, 11, 12))
    assert an._period_range("fy", "2025-26") == ("2025-04-01", "2026-03-31", "FY 2025-26")


def test_the_year_that_is_running_ends_today_and_says_so(monkeypatch):
    _today(monkeypatch, date(2026, 11, 12))
    assert an._period_range("fy", "2026-27") == ("2026-04-01", "2026-11-12", "FY 2026-27 (to date)")


def test_a_financial_year_asked_for_without_a_year_is_the_one_that_is_running(monkeypatch):
    _today(monkeypatch, date(2027, 2, 3))
    assert an._period_range("fy") == ("2026-04-01", "2027-02-03", "FY 2026-27 (to date)")
    _today(monkeypatch, date(2026, 3, 31))
    assert an._period_range("fy") == ("2025-04-01", "2026-03-31", "FY 2025-26"), "the last day of a year is the whole year"


def test_a_financial_year_that_has_not_started_is_refused_in_words(monkeypatch):
    _today(monkeypatch, date(2026, 11, 12))
    with pytest.raises(HTTPException) as refused:
        an._period_range("fy", "2027-28")
    assert refused.value.status_code == 422 and "has not started" in refused.value.detail


def test_a_financial_year_with_any_other_window_is_refused_and_not_ignored(monkeypatch):
    _today(monkeypatch, date(2026, 11, 12))
    for period in ("week", "month", "quarter"):
        with pytest.raises(HTTPException) as refused:
            an._period_range(period, "2025-26")
        assert refused.value.status_code == 422


def test_an_unknown_window_is_a_422_at_the_door_and_never_the_month():
    adapter = TypeAdapter(an.PeriodWord)
    for word in ("week", "month", "quarter", "fy"):
        assert adapter.validate_python(word) == word
    for word in ("decade", "year", "", "MONTH"):
        with pytest.raises(ValidationError):
            adapter.validate_python(word)


def test_every_analytics_endpoint_that_takes_a_window_takes_the_one_set_of_words():
    import inspect
    from typing import get_type_hints
    seen = 0
    for name in ("profitability_analytics", "fee_concentration", "revenue_vs_effort"):
        fn = getattr(an, name)
        hints = get_type_hints(fn, include_extras=True)
        assert hints["period"] is an.PeriodWord, f"{name} reads a window as a bare string again"
        assert "financial_year" in inspect.signature(fn).parameters, f"{name} cannot be asked for a financial year"
        seen += 1
    assert seen == 3


def test_the_three_endpoints_read_the_same_window_for_the_same_year(book, monkeypatch):
    """Revenue on one screen and revenue on another must be the same figure: they share the resolver."""
    _today(monkeypatch, date(2026, 11, 12))
    date_from = "2025-06-01"
    fee = {**_fee(1, A, "ea", 100_000), "invoice_date": date_from}
    entry = {**_time(1, A, "ea", 60, billable_rate_paise=100_000), "started_at": f"{date_from}T10:00:00+05:30"}
    book(invoices=[fee], entries=[entry])
    profit = an.profitability_analytics(period="fy", financial_year="2025-26", current_user=USER)["data"]
    real = an.revenue_vs_effort(period="fy", financial_year="2025-26", current_user=USER)["data"]
    conc = an.fee_concentration(period="fy", financial_year="2025-26", current_user=USER)["data"]
    assert profit["period"] == real["period"] == conc["period"] == "FY 2025-26"
    assert profit["firm_metrics"]["total_revenue_paise"] == real["total_revenue_paise"] == conc["total_revenue_paise"] == 100_000
    month = an.revenue_vs_effort(period="month", current_user=USER)["data"]
    assert month["total_revenue_paise"] == 0, "the same book, asked for this month, has nothing in it"
