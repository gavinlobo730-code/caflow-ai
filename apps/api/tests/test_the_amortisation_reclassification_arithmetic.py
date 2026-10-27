"""What moving an intangible asset's accumulated amortisation out of the shared ledger is made of, and when a batch must not be posted
(POST-A-345, stage 3). The arithmetic and the refusals only: `domain/fixed_assets/amortisation_reclass` has no database in it.

WHAT IS HELD
    * an asset's move is its register figure, split into what its own depreciation entries put in the shared ledger (on or before the
      stated date, and after it, grouped by the date of the entry that moves them) and the carried-over remainder that only the person
      posting can place;
    * where the ledger holds MORE than the register the asset is not moved, and the sentence says by how much;
    * the date is a month end; a month posted after it moves in an entry dated the end of ITS financial year, or today where that year
      has not ended, so every year-end balance sheet from the stated date on is exact;
    * the batch is refused when the shared ledger holds less than has left it AS AT THE DATE OF ANY ENTRY, when a named carried-over ledger
      holds less than the carried-over part, when the new ledger carries a credit nothing explains or less than the assets pointed at it
      account for (each worded by direction), and whenever a balance could not be read;
    * a batch that moves nothing is never refused, whatever could or could not be read.
"""
from __future__ import annotations

import pytest

from domain.fixed_assets import amortisation_reclass as arc
from domain.money_sentence import rupee_text

R = rupee_text
AS_AT = "2025-09-30"
FY_END = "2026-03-31"
TODAY = "2026-10-27"


def _fy_end_of(iso: str) -> str:
    year = int(iso[:4]) + (1 if int(iso[5:7]) >= 4 else 0)
    return f"{year}-03-31"


def _pos(register, to_as_at=0, later=(), code="FA-1"):
    return arc.AssetPosition(asset_id=f"id-{code}", asset_code=code, asset_name=f"Asset {code}", register_paise=register,
                             posted_to_as_at_paise=to_as_at, posted_later=tuple(later))


def _plan(register, to_as_at=0, later=(), code="FA-1"):
    return arc.plan_asset(_pos(register, to_as_at, later, code), says_rupees=R)


# ── the date ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("iso", ["2025-09-30", "2026-03-31", "2024-02-29", "2025-02-28", "2025-12-31"])
def test_a_month_end_is_accepted(iso):
    assert arc.month_end_problem(iso) is None


@pytest.mark.parametrize("iso", ["2025-09-29", "2025-09-01", "2024-02-28", "2025-02-27", "2025-12-30"])
def test_a_date_that_is_not_a_month_end_is_refused_in_words(iso):
    assert "month end" in arc.month_end_problem(iso)


def test_a_date_that_is_not_a_date_is_refused():
    assert arc.month_end_problem("2025-02-30") is not None and arc.month_end_problem("nonsense") is not None


@pytest.mark.parametrize("month,expected", [
    ("2025-10-31", "2026-03-31"), ("2026-03-31", "2026-03-31"), ("2026-04-30", TODAY), ("2026-06-30", TODAY)])
def test_a_later_month_moves_on_its_years_end_or_today_when_that_year_has_not_ended(month, expected):
    assert arc.later_entry_date(month, TODAY, fy_end_of=_fy_end_of) == expected


# ── one asset ───────────────────────────────────────────────────────────────

def test_an_asset_whose_register_figure_is_all_its_own_depreciation_moves_all_of_it_from_the_shared_ledger():
    p = _plan(register=60_000_00, to_as_at=40_000_00, later=[(FY_END, 12_000_00), (TODAY, 8_000_00)])
    assert p.outcome == arc.MOVES
    assert (p.from_shared_to_as_at_paise, p.from_carried_paise, p.from_shared_after_as_at_paise) == (40_000_00, 0, 20_000_00)
    assert p.later == ((FY_END, 12_000_00), (TODAY, 8_000_00))
    assert p.credit_to_own_ledger_paise == 60_000_00


def test_what_the_register_has_beyond_the_asset_s_own_journals_is_carried_over_and_named_apart():
    p = _plan(register=70_000_00, to_as_at=40_000_00, later=[(TODAY, 20_000_00)])
    assert p.outcome == arc.MOVES and p.from_carried_paise == 10_000_00
    assert p.credit_to_own_ledger_paise == 70_000_00, "the whole register figure is credited to the new ledger, so the asset is whole"


def test_an_asset_with_nothing_depreciated_is_pointed_and_nothing_moves():
    p = _plan(register=0)
    assert p.outcome == arc.POINTED_ONLY and p.credit_to_own_ledger_paise == 0


def test_a_ledger_that_holds_more_than_the_register_is_not_moved_and_the_sentence_gives_the_difference():
    p = _plan(register=50_000_00, to_as_at=40_000_00, later=[(TODAY, 15_000_00)])
    assert p.outcome == arc.EXCLUDED and p.credit_to_own_ledger_paise == 0
    assert "₹5,000.00 more" in p.reason and "₹50,000.00" in p.reason and "₹55,000.00" in p.reason


@pytest.mark.parametrize("register,a,later", [(-1, 0, ()), (0, -1, ()), (0, 0, [(TODAY, -1)]), (10_00, -5_00, [(TODAY, 5_00)])])
def test_a_negative_figure_means_more_reversed_than_posted_and_the_asset_is_not_moved(register, a, later):
    p = _plan(register, a, later)
    assert p.outcome == arc.EXCLUDED and "more reversed than posted" in p.reason


def test_nothing_is_ever_created_or_lost_in_a_plan():
    """Whatever the inputs, a moved asset is credited exactly its register figure (so the new ledger and the register agree)."""
    for register in (0, 1, 99, 1_00_00, 12_345_67):
        for a in (0, 1, 50, 1_00_00):
            for later in ((), ((FY_END, 3_00),), ((FY_END, 3_00), (TODAY, 7_00))):
                p = _plan(register, a, later)
                if p.outcome == arc.MOVES:
                    assert p.credit_to_own_ledger_paise == register
                    assert min(p.from_shared_to_as_at_paise, p.from_carried_paise, p.from_shared_after_as_at_paise) >= 0
                else:
                    assert p.credit_to_own_ledger_paise == 0


# ── which dates carry an entry ──────────────────────────────────────────────

def test_the_dates_are_the_stated_date_then_each_later_one_and_the_stated_date_only_if_something_moves_then():
    both = _plan(70_000_00, 40_000_00, [(FY_END, 12_000_00), (TODAY, 18_000_00)])
    assert arc.entry_dates([both], AS_AT) == [AS_AT, FY_END, TODAY]
    only_later = _plan(20_000_00, 0, [(TODAY, 20_000_00)])
    assert arc.entry_dates([only_later], AS_AT) == [TODAY], "no entry is dated at the stated date, so it is not asked of the closure lock"
    assert arc.entry_dates([_plan(0)], AS_AT) == [] and arc.entry_dates([_plan(5, 9)], AS_AT) == []


# ── the batch ───────────────────────────────────────────────────────────────

def _batch(plans, *, shared=10**9, carried_is_shared=True, carried=None, own=0, in_own=0, shared_at=None):
    dates = arc.entry_dates(plans, AS_AT)
    return arc.check_batch(plans, as_at=AS_AT, shared_balance_at=shared_at if shared_at is not None else {d: shared for d in dates},
                           carried_source_is_shared=carried_is_shared, carried_balance_at=carried, own_credit_paise=own,
                           already_in_own_ledger_paise=in_own, says_rupees=R)


def test_a_batch_that_the_shared_ledger_can_cover_has_no_refusal_and_reports_its_totals():
    out = _batch([_plan(70_000_00, 40_000_00, [(TODAY, 20_000_00)]), _plan(5_000_00, 5_000_00, code="FA-2")], shared=75_000_00)
    assert out.refusals == []
    assert (out.total_paise, out.from_shared_paise, out.from_carried_paise) == (75_000_00, 65_000_00, 10_000_00)


def test_the_shared_ledger_holding_less_than_would_leave_it_refuses_with_both_figures_the_date_and_the_way_forward():
    out = _batch([_plan(60_000_00, 60_000_00)], shared=59_999_99)
    assert len(out.refusals) == 1
    text = out.refusals[0]
    assert "₹59,999.99" in text and "₹60,000.00" in text and "debit balance" in text and "name that ledger" in text and "30 Sep" not in text
    assert str(AS_AT) in text, "it names the date it is judged at"


def test_the_shared_ledger_is_judged_at_the_date_of_each_entry_and_not_only_today():
    """Enough today, not enough on the stated date: an entry dated 30 Sep that debits a ledger which did not yet hold the credit would
    leave that day's balance sheet with a debit on a contra account."""
    plans = [_plan(60_000_00, 40_000_00, [(TODAY, 20_000_00)])]
    ok = _batch(plans, shared_at={AS_AT: 40_000_00, TODAY: 60_000_00})
    assert ok.refusals == []
    early = _batch(plans, shared_at={AS_AT: 39_999_99, TODAY: 60_000_00})
    assert len(early.refusals) == 1 and AS_AT in early.refusals[0] and "₹39,999.99" in early.refusals[0]


def test_what_has_already_left_counts_against_a_later_entry_of_the_same_batch():
    plans = [_plan(60_000_00, 40_000_00, [(TODAY, 20_000_00)])]
    out = _batch(plans, shared_at={AS_AT: 40_000_00, TODAY: 50_000_00})        # 50,000 held today, 60,000 will have left
    assert len(out.refusals) == 1 and TODAY in out.refusals[0] and "₹60,000.00" in out.refusals[0]


def test_the_carried_over_part_counts_against_the_shared_ledger_only_when_that_is_where_it_comes_from():
    plans = [_plan(70_000_00, 40_000_00, [(TODAY, 20_000_00)])]          # 10,000 carried over
    assert _batch(plans, shared=70_000_00, carried_is_shared=True).refusals == []
    assert _batch(plans, shared=69_999_99, carried_is_shared=True).refusals
    # named elsewhere: the shared ledger need only cover the 60,000 its own journals put there
    assert _batch(plans, shared=60_000_00, carried_is_shared=False, carried=10_000_00).refusals == []
    assert _batch(plans, shared=59_999_99, carried_is_shared=False, carried=10_000_00).refusals


def test_a_named_carried_over_ledger_that_holds_less_than_the_carried_over_part_refuses():
    out = _batch([_plan(70_000_00, 40_000_00, [(TODAY, 20_000_00)])], carried_is_shared=False, carried=9_999_99)
    assert len(out.refusals) == 1 and "named for the carried-over part holds ₹9,999.99" in out.refusals[0]


def test_a_named_carried_over_ledger_is_not_asked_when_nothing_is_carried_over():
    out = _batch([_plan(60_000_00, 40_000_00, [(TODAY, 20_000_00)])], carried_is_shared=False, carried=None)
    assert out.refusals == []


def test_a_credit_in_the_new_ledger_that_the_pointed_assets_do_not_explain_refuses_and_says_which_way():
    plans = [_plan(10_00, 10_00)]
    more = _batch(plans, own=50_00, in_own=0)
    assert len(more.refusals) == 1 and "₹50.00 more than they explain" in more.refusals[0] and "nothing is netted" in more.refusals[0]
    less = _batch(plans, own=0, in_own=50_00)
    assert len(less.refusals) == 1 and "₹50.00 less than they should" in less.refusals[0]
    assert "double" not in less.refusals[0], "a shortfall is not a doubling, and the old sentence blamed a trial balance for it"
    assert _batch(plans, own=50_00, in_own=50_00).refusals == []


@pytest.mark.parametrize("kwargs,fragment", [
    ({"shared_at": {AS_AT: None}}, "shared Accumulated Depreciation ledger as at"),
    ({"own": None}, "Accumulated Amortisation ledger could not be read"),
    ({"carried_is_shared": False, "carried": None}, "named for the carried-over part could not be read"),
])
def test_a_balance_that_could_not_be_read_refuses_because_not_being_able_to_look_is_not_enough(kwargs, fragment):
    out = _batch([_plan(70_000_00, 60_000_00)], **kwargs)          # 60,000 from its own journals and 10,000 carried over
    assert any(fragment in r for r in out.refusals), out.refusals


def test_a_batch_that_moves_nothing_is_never_refused_whatever_could_not_be_read():
    pointed_only, excluded = _plan(0), _plan(1, 0, [(TODAY, 5)], code="FA-2")
    assert (pointed_only.outcome, excluded.outcome) == (arc.POINTED_ONLY, arc.EXCLUDED)
    nothing = _batch([pointed_only, excluded], shared_at={}, own=None, carried_is_shared=False, carried=None)
    assert nothing.refusals == [] and nothing.total_paise == 0


# ── which balance sheets it changes ─────────────────────────────────────────

def test_with_no_later_month_the_stated_date_and_every_later_one_are_fixed_and_earlier_ones_keep_their_split():
    rows = arc.financial_years_fixed("30 Sep 2025", "27 Oct 2026", [])
    assert [r["fixed"] for r in rows] == [True, False]
    assert "30 Sep 2025 and every later one" in rows[0]["note"] and "keeps the split it had" in rows[1]["note"]


def test_with_later_months_every_year_end_is_named_as_fixed_and_the_dates_in_between_are_said_to_be_partial():
    rows = arc.financial_years_fixed("30 Sep 2025", "27 Oct 2026", ["31 Mar 2026", "27 Oct 2026"])
    assert [r["fixed"] for r in rows] == [True, False, False]
    assert "30 Sep 2025, 31 Mar 2026 and 27 Oct 2026" in rows[0]["note"]
    assert "another date between these may still show" in rows[1]["note"] and "Financial year ends are all exact" in rows[1]["note"]
    assert "before 30 Sep 2025" in rows[2]["label"]


# ── judged at every month end, not only on the days an entry is dated ───────────────────────────

def test_the_dates_a_ledger_is_judged_at_are_every_entry_and_every_month_end_from_the_first_to_today():
    points = arc.check_dates([AS_AT, FY_END], TODAY)
    assert points[0] == AS_AT and AS_AT in points and FY_END in points
    month_ends = [d for d in points if d not in (AS_AT, FY_END, TODAY)]
    assert "2025-10-31" in month_ends and "2026-10-31" in month_ends, "to the month of today, which is whole in the monthly balances"
    assert points == sorted(points) and len(set(points)) == len(points)
    assert arc.check_dates([], TODAY) == []
    assert arc.check_dates(["2026-10-31"], TODAY) == ["2026-10-31"], "a single entry dated in today's own month"


def test_a_debit_after_the_entry_that_takes_the_ledger_below_what_left_it_refuses_on_that_month_end():
    """Sufficient on the entry's own day, short two months later: a later debit to the same ledger (a tangible asset's disposal)."""
    plans = [_plan(5_000_00, 5_000_00)]
    held = {AS_AT: 5_000_00, "2025-10-31": 5_000_00, "2025-11-30": 2_000_00, "2025-12-31": 2_000_00}
    out = _batch(plans, shared_at=held)
    assert len(out.refusals) == 1 and "2025-11-30" in out.refusals[0] and "₹2,000.00" in out.refusals[0]
    assert _batch(plans, shared_at={**held, "2025-11-30": 5_000_00, "2025-12-31": 5_000_00}).refusals == []


def test_a_month_before_anything_has_left_is_not_judged_so_a_pre_existing_debit_does_not_block_a_later_move():
    plans = [_plan(5_000_00, 5_000_00)]
    out = _batch(plans, shared_at={"2025-06-30": -1_00, AS_AT: 5_000_00})
    assert out.refusals == []


def test_a_named_carried_over_ledger_is_judged_on_every_date_from_the_stated_one():
    plans = [_plan(70_000_00, 40_000_00, [(TODAY, 20_000_00)])]
    held = {AS_AT: 30_000_00, "2025-10-31": 30_000_00, "2025-11-30": 9_999_99}
    out = _batch(plans, carried_is_shared=False, carried=held, shared_at={AS_AT: 40_000_00, TODAY: 60_000_00})
    assert len(out.refusals) == 1 and "₹9,999.99" in out.refusals[0] and "2025-11-30" in out.refusals[0]
    assert _batch(plans, carried_is_shared=False, carried={**held, "2025-11-30": 30_000_00}, shared_at={AS_AT: 40_000_00, TODAY: 60_000_00}).refusals == []
