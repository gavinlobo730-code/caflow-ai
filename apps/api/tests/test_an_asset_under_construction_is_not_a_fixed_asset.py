"""Capital work-in-progress (FA-11a, migration 397).

WHAT WAS WRONG
    There was no CWIP anywhere in this product. `fixed_assets` is the only
    place an asset can live and everything in it is depreciated, so a client
    building a factory either left it out of the register — a balance sheet
    short by the whole of what had been spent — or put it in and had
    depreciation charged on an asset that was not ready for use. AS-10
    paragraph 20 starts depreciation when the asset is AVAILABLE FOR USE.

AND IT IS A DISCLOSURE
    MCA G.S.R. 207(E) of 24-03-2021 — the same amendment behind the two ageing
    schedules `domain/reporting/ageing.py` already builds — gives CWIP its own
    balance-sheet line, an ageing schedule split between projects in progress
    and projects temporarily suspended, and a completion schedule for anything
    overdue or over its approved cost.

    `capital_wip` HAS BEEN A DECLARED YEAR-END LINE SINCE THAT MODULE WAS
    WRITTEN and no caption resolved to it, so the line was structurally nil for
    every client. That is the half of this nobody could have seen.

What these tests hold:
  1. The ageing ages MONEY, per tranche, into the four prescribed bands.
  2. Suspension moves the ROW, never removes the balance.
  3. As at a DATE — a project capitalised in June is CWIP in a March note.
  4. The completion schedule reaches only overdue or over-cost projects, and
     REFUSES rather than guesses where the original approval is not recorded.
  5. Capitalisation creates the asset with the right date, and is one-way.
  6. The Schedule III caption reaches the line that was always declared.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.fixed_assets import cwip
from domain.reporting.schedule_iii import bs_bucket
from domain.reporting.year_end_lines import CAPTION_TO_SCHEDULE_LINE
from services import cwip_service as svc
from tests.e2e_harness import FakeDB

FIRM = "firm-cwip"
CLIENT = "client-cwip"
AS_OF = date(2026, 3, 31)


def _project(**over):
    base = dict(cwip_id="p1", name="New factory", status=cwip.IN_PROGRESS,
                started_on=date(2023, 4, 1))
    base.update(over)
    return cwip.Project(**base)


def _add(on, amount, cwip_id="p1"):
    return cwip.Addition(cwip_id=cwip_id, incurred_on=on, amount_paise=amount)


# ── 1. the ageing ages money ────────────────────────────────────────────────

def test_one_project_has_amounts_in_several_bands_at_once():
    """The point of ageing the TRANCHE rather than the project.

    A build begun three years ago whose last contractor bill arrived last month
    has money of three different ages in it. A project-level date would put all
    of it in the oldest band and overstate how long the company's capital has
    been tied up.
    """
    out = cwip.ageing(
        [_project()],
        [_add(date(2022, 6, 1), 10_00_000),      # > 3 years
         _add(date(2024, 6, 1), 20_00_000),      # 1-2 years
         _add(date(2026, 1, 1), 30_00_000)],     # < 1 year
        as_of=AS_OF)
    row = out.rows[cwip.IN_PROGRESS]
    assert row["more_than_3_years"] == 10_00_000
    assert row["1_2_years"] == 20_00_000
    assert row["less_than_1_year"] == 30_00_000
    assert out.total_paise == 60_00_000


@pytest.mark.parametrize("incurred,expected", [
    (date(2026, 3, 31), "less_than_1_year"),     # today
    (date(2025, 4, 1), "less_than_1_year"),      # 11 months and a bit
    (date(2025, 3, 31), "1_2_years"),            # exactly one year
    (date(2024, 3, 31), "2_3_years"),
    (date(2023, 3, 31), "more_than_3_years"),
    (date(2023, 4, 1), "2_3_years"),             # a day short of three years
])
def test_the_band_boundaries(incurred, expected):
    """Exactly one year is in the SECOND band: "less than 1 year" means less
    than, and an amount outstanding for precisely a year is not."""
    assert cwip.bucket_for(incurred, AS_OF) == expected


def test_the_four_bands_are_the_prescribed_ones_in_order():
    assert [b[0] for b in cwip.BUCKETS] == [
        "less_than_1_year", "1_2_years", "2_3_years", "more_than_3_years"]
    assert list(cwip.ROW_LABELS.values()) == [
        "Projects in progress", "Projects temporarily suspended"]


# ── 2. suspension is presentational ─────────────────────────────────────────

def test_a_suspended_project_moves_row_and_keeps_its_balance():
    """Schedule III splits the TOTAL between two rows; it does not take a
    suspended project's cost off the balance sheet. Reading suspension as a
    removal would be a write-off nobody decided."""
    live = cwip.ageing([_project()], [_add(date(2026, 1, 1), 5_00_000)], as_of=AS_OF)
    held = cwip.ageing([_project(status=cwip.SUSPENDED)],
                       [_add(date(2026, 1, 1), 5_00_000)], as_of=AS_OF)
    assert live.total_paise == held.total_paise == 5_00_000
    assert live.rows[cwip.IN_PROGRESS]["less_than_1_year"] == 5_00_000
    assert held.rows[cwip.SUSPENDED]["less_than_1_year"] == 5_00_000
    assert held.rows[cwip.IN_PROGRESS]["less_than_1_year"] == 0


# ── 3. as at a date ─────────────────────────────────────────────────────────

def test_a_project_capitalised_later_is_still_CWIP_in_an_earlier_note():
    """The same discipline `stock_position_as_at` applies to the stock ledger,
    and the reason `capitalised_on` is recorded rather than the row deleted."""
    p = _project(capitalised_on=date(2026, 6, 30))
    march = cwip.ageing([p], [_add(date(2026, 1, 1), 7_00_000)], as_of=date(2026, 3, 31))
    september = cwip.ageing([p], [_add(date(2026, 1, 1), 7_00_000)], as_of=date(2026, 9, 30))
    assert march.total_paise == 7_00_000, "it was work-in-progress in March"
    assert september.total_paise == 0, "by September it is a fixed asset"


def test_a_cost_incurred_after_the_reporting_date_is_not_in_the_note():
    out = cwip.ageing([_project()], [_add(date(2026, 4, 15), 9_00_000)], as_of=AS_OF)
    assert out.total_paise == 0


def test_a_live_project_with_no_spend_yet_is_still_listed():
    """"No projects" and "no spend" are different facts on a note whose whole
    purpose is showing how long money has been sitting."""
    out = cwip.ageing([_project()], [], as_of=AS_OF)
    assert [r["project_name"] for r in out.by_project] == ["New factory"]
    assert out.total_paise == 0


def test_an_abandoned_project_is_not_capital_work_in_progress():
    out = cwip.ageing([_project(status="abandoned")],
                      [_add(date(2026, 1, 1), 3_00_000)], as_of=AS_OF)
    assert out.total_paise == 0


# ── 4. the completion schedule ──────────────────────────────────────────────

def test_only_an_overdue_or_over_cost_project_is_reported():
    on_track = _project(cwip_id="ok", name="On track",
                        approved_completion_date=date(2027, 3, 31),
                        approved_cost_paise=100_00_000,
                        expected_completion_date=date(2027, 3, 31))
    late = _project(cwip_id="late", name="Late",
                    approved_completion_date=date(2025, 3, 31),
                    approved_cost_paise=100_00_000,
                    expected_completion_date=date(2026, 9, 30))
    out = cwip.completion_schedule(
        [on_track, late],
        [_add(date(2025, 1, 1), 10_00_000, "ok"),
         _add(date(2025, 1, 1), 10_00_000, "late")],
        as_of=AS_OF)
    assert [r["project_name"] for r in out.rows] == ["Late"]
    assert "overdue" in out.rows[0]["reason"]


def test_over_the_approved_cost_is_enough_on_its_own():
    over = _project(approved_completion_date=date(2027, 3, 31),
                    approved_cost_paise=5_00_000,
                    expected_completion_date=date(2026, 12, 31))
    out = cwip.completion_schedule(
        [over], [_add(date(2025, 1, 1), 9_00_000)], as_of=AS_OF)
    assert len(out.rows) == 1
    assert "exceeded" in out.rows[0]["reason"]
    assert "overdue" not in out.rows[0]["reason"]


def test_a_project_with_no_recorded_approval_is_NAMED_never_assumed_compliant():
    """Both directions of the guess are wrong: defaulting the date to the start
    reports every project overdue on day two, and defaulting the cost to what
    has been spent reports none over budget ever."""
    out = cwip.completion_schedule(
        [_project()], [_add(date(2024, 1, 1), 4_00_000)], as_of=AS_OF)
    assert out.rows == []
    assert len(out.gaps) == 1
    assert "originally approved" in out.gaps[0].lower() or "ORIGINAL" in out.gaps[0]


def test_a_reportable_project_with_no_expected_date_is_NAMED_not_bucketed():
    """A row with no band states nothing; a row put in "more than 3 years"
    because nobody said otherwise states something false."""
    out = cwip.completion_schedule(
        [_project(approved_completion_date=date(2025, 3, 31))],
        [_add(date(2024, 1, 1), 4_00_000)], as_of=AS_OF)
    assert len(out.rows) == 1
    assert out.rows[0]["bucket"] is None
    assert out.gaps and "expected" in out.gaps[0].lower()
    assert sum(out.buckets.values()) == 0


# ── 5. the ledger, the asset and the one-way door ───────────────────────────

def _seed_project(db, **over):
    row = {"id": "p1", "firm_id": FIRM, "client_id": CLIENT,
           "project_name": "New factory", "asset_category": "Building",
           "started_on": "2024-04-01", "status": "in_progress"}
    row.update(over)
    return db.seed("capital_work_in_progress", row)


def _seed_cost(db, amount, *, on="2025-06-01", **over):
    row = {"firm_id": FIRM, "client_id": CLIENT, "cwip_id": "p1",
           "incurred_on": on, "description": "Contractor bill",
           "amount_paise": amount, "igst_paise": 0, "cgst_paise": 0,
           "sgst_paise": 0, "itc_eligible": True}
    row.update(over)
    return db.seed("cwip_additions", row)


def test_blocked_tax_is_part_of_what_the_asset_cost_and_eligible_tax_is_not():
    """AS-10 paragraph 9 — non-refundable purchase taxes are in the cost of the
    asset; credit barred by CGST s.17(5) is refundable from nobody. The same
    sentence AS-2 paragraph 6 applies to stock."""
    eligible = {"amount_paise": 10_00_000, "igst_paise": 1_80_000,
                "cgst_paise": 0, "sgst_paise": 0, "itc_eligible": True}
    blocked = {**eligible, "itc_eligible": False}
    assert svc.capitalised_cost_of(eligible) == 10_00_000
    assert svc.capitalised_cost_of(blocked) == 10_00_000 + 1_80_000


def test_capitalisation_creates_the_asset_at_the_accumulated_cost():
    db = FakeDB()
    _seed_project(db)
    _seed_cost(db, 40_00_000, on="2024-06-01")
    _seed_cost(db, 60_00_000, on="2025-09-01")
    out = svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                         put_to_use_date="2026-01-15")
    assert out["ok"] is True
    assert out["cost_paise"] == 100_00_000
    asset = db.rows("fixed_assets")[0]
    assert asset["purchase_cost_paise"] == 100_00_000
    assert asset["current_wdv_paise"] == 100_00_000
    assert asset["accumulated_depreciation_paise"] == 0


def test_the_asset_is_dated_WHEN_IT_BECAME_READY_not_when_the_build_began():
    """AS-10 paragraph 20. Dating the asset at the project's start would charge
    every year of construction as depreciation the moment it is capitalised —
    on an asset nobody could use in any of them."""
    db = FakeDB()
    _seed_project(db, started_on="2023-04-01")
    _seed_cost(db, 50_00_000, on="2023-06-01")
    svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                   put_to_use_date="2026-01-15")
    asset = db.rows("fixed_assets")[0]
    assert asset["put_to_use_date"] == "2026-01-15"
    assert asset["purchase_date"] == "2026-01-15"


def test_capitalising_twice_is_refused():
    db = FakeDB()
    _seed_project(db)
    _seed_cost(db, 10_00_000)
    svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                   put_to_use_date="2026-01-15")
    again = svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                           put_to_use_date="2026-02-15")
    assert again["ok"] is False and "already" in again["refusal"]


def test_a_project_with_nothing_spent_cannot_be_capitalised():
    db = FakeDB()
    _seed_project(db)
    out = svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                         put_to_use_date="2026-01-15")
    assert out["ok"] is False and "no cost" in out["refusal"]


def test_a_cost_cannot_be_added_after_capitalisation():
    db = FakeDB()
    _seed_project(db, status="capitalised", capitalised_on="2026-01-15")
    out = svc.add_cost(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                       incurred_on="2026-02-01", description="More work",
                       amount_paise=1_00_000)
    assert out["ok"] is False


def test_suspending_a_capitalised_project_is_refused():
    db = FakeDB()
    _seed_project(db, status="capitalised", capitalised_on="2026-01-15")
    out = svc.set_status(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                         status="suspended", on_date="2026-02-01")
    assert out["ok"] is False


def test_capitalising_is_not_reachable_through_the_status_door():
    """It creates an asset and posts a journal, so it is its own action."""
    db = FakeDB()
    _seed_project(db)
    out = svc.set_status(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                         status="capitalised", on_date="2026-01-15")
    assert out["ok"] is False
    assert db.rows("fixed_assets") == []


def test_a_project_in_another_firm_is_not_reachable():
    db = FakeDB()
    _seed_project(db, firm_id="other-firm")
    assert svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                          put_to_use_date="2026-01-15")["ok"] is False
    assert svc.add_cost(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                        incurred_on="2026-02-01", description="x",
                        amount_paise=100)["ok"] is False


def test_the_schedules_read_the_capitalised_cost_so_the_note_can_tie():
    """The balance sheet carries the blocked tax, so the note must age the same
    rupees the ledger holds or the two cannot reconcile."""
    db = FakeDB()
    _seed_project(db)
    _seed_cost(db, 10_00_000, on="2026-01-01", igst_paise=1_80_000,
               itc_eligible=False)
    out = svc.schedules(db, firm_id=FIRM, client_id=CLIENT, as_of=AS_OF)
    assert out["ageing"]["total_paise"] == 11_80_000


def test_a_cost_that_did_not_post_SAYS_SO(app_journal_that_fails=None):
    """The state that breaks the whole feature, reported rather than swallowed.

    The ageing schedule has to tie to the capital work-in-progress figure on
    the balance sheet. A tranche recorded and not posted is exactly the
    difference, and `_find_account` raises for any firm that had no chart of
    accounts when migration 397 ran — so this is reachable, not theoretical.
    """
    class _Fails:
        def journal_for_cwip_addition(self, **_kw):
            return None

    db = FakeDB()
    _seed_project(db)
    out = svc.add_cost(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                       incurred_on="2026-01-01", description="Contractor bill",
                       amount_paise=5_00_000, journal=_Fails())
    assert out["ok"] is True, "the cost is a fact and is still recorded"
    assert out["gaps"], "a cost that did not reach the ledger has to say so"
    assert "balance sheet" in out["gaps"][0]


def test_the_asset_is_created_even_if_the_transfer_entry_fails():
    """Refusing would strand the cost in work-in-progress with a finished asset
    nobody can depreciate. The gap says what is still owed."""
    class _Fails:
        def journal_for_cwip_capitalisation(self, **_kw):
            return None

    db = FakeDB()
    _seed_project(db)
    _seed_cost(db, 10_00_000)
    out = svc.capitalise(db, firm_id=FIRM, client_id=CLIENT, cwip_id="p1",
                         put_to_use_date="2026-01-15", journal=_Fails())
    assert out["ok"] is True
    assert db.rows("fixed_assets"), "the asset exists"
    assert out["gaps"]


# ── 6. the Schedule III line that was always declared ───────────────────────

def test_the_caption_reaches_the_year_end_line_that_was_always_declared():
    """`capital_wip` has been in BS_ASSET_LINES since that module was written
    and nothing could reach it: no caption resolved there, so the year-end
    balance sheet carried a structurally nil CWIP line for every client."""
    assert CAPTION_TO_SCHEDULE_LINE["Capital Work-in-Progress"] == "capital_wip"


@pytest.mark.parametrize("subtype", [
    "Capital Work-in-Progress", "CWIP", "Capital Work in Progress",
    "Under Construction",
])
def test_the_subtype_lands_on_its_own_caption(subtype):
    assert bs_bucket("Asset", subtype) == "Capital Work-in-Progress"


def test_a_cwip_subtype_naming_plant_does_NOT_become_a_tangible_fixed_asset():
    """The order of the two tests is the whole of it: "Capital Work in Progress
    - Plant" contains "plant", and the tangible branch would claim it — showing
    an asset under construction as one in use, which is FA-11a."""
    assert bs_bucket("Asset", "Capital Work in Progress - Plant") == \
        "Capital Work-in-Progress"


def test_the_caveat_says_why_it_is_not_depreciated():
    assert "available for use" in cwip.CWIP_DOES_NOT_DEPRECIATE
    assert "AS-10" in cwip.CWIP_DOES_NOT_DEPRECIATE
