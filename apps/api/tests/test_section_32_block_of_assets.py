"""
IT-09 ≡ FA-06: §32 block-of-assets depreciation, which existed nowhere.

WHAT WAS MISSING

`domain/income_tax/book_to_tax_bridge.py` says in its own docstring that
depreciation is charged twice on two different systems, that the difference is
usually the largest single line in the bridge, and that "NOTHING IN THIS
CODEBASE IMPLEMENTS THE SECOND ONE". A grep for 'block of assets' returned that
docstring and nothing else. `build_bridge` therefore took the §32 figure as an
Optional input and marked itself INCOMPLETE whenever it was absent — which was
always, because no router imported it either.

This is the second system.

WHAT §32 IS, AS AGAINST SCHEDULE II

    Schedule II  per ASSET, over its useful LIFE. Each asset has its own
                 written-down value and its own remaining life.
    §32          per BLOCK, at the block's RATE, on the block's written-down
                 value. Assets lose their identity inside the block entirely.

They are not two rates for one calculation. An asset sold out of a §32 block
does not produce a gain or loss on that asset — it reduces the block by the
moneys payable, and only if that empties or overdraws the block does §50 make a
short-term capital gain of the difference.

WHAT THIS FILE PINS

The four things that are easy to get wrong and expensive to get wrong:

  * the SECOND PROVISO's 180 days, which turns on PUT TO USE and not on
    purchase, and whose boundary moves in a leap previous year;
  * §43(6)(c)'s order — the moneys payable reduce the full-rate part of the
    block before they reach the half-rate additions, because the other order
    allows the full rate on money the block no longer has;
  * §50's two limbs, which are different questions: an overdrawn block is a
    gain, an EMPTIED one is a loss, and a positive written-down value does not
    settle whether any asset remains;
  * every fact the engine refuses to invent — the rate, whether the block still
    exists, §32(1)(iia) eligibility, and an addition with no put-to-use date.
"""
from datetime import date

import pytest

from domain.income_tax.section_32 import (
    Addition, Block, Deletion, Section32Result, compute, compute_block,
    half_rate_cutoff,
)

FY_END = date(2026, 3, 31)          # FY 2025-26
L = 1_00_000_00                     # one lakh in paise


def _block(**kw) -> Block:
    base = {"key": "P&M 15%", "rate_percent": 15, "opening_wdv_paise": 10 * L}
    base.update(kw)
    return Block(**base)


# ══════════════════════════════════════════════════════════════════════════════
# The 180-day proviso
# ══════════════════════════════════════════════════════════════════════════════

def test_the_cutoff_is_3_october_in_an_ordinary_year():
    assert half_rate_cutoff(date(2026, 3, 31)) == date(2025, 10, 3)


def test_the_cutoff_moves_in_a_leap_previous_year():
    """1 April 2023 – 31 March 2024 contains 29 February. A hardcoded
    "3 October" would be a day wrong in one year out of four, and the wrong way:
    it would allow the full rate on an asset entitled to half."""
    assert half_rate_cutoff(date(2024, 3, 31)) == date(2023, 10, 4)


def test_an_asset_put_to_use_on_the_cutoff_gets_the_full_rate():
    got = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("Lathe", 10 * L, date(2025, 10, 3)),)), fy_end=FY_END)
    assert got.additions_full_rate_paise == 10 * L
    assert got.depreciation_paise == int(0.15 * 10 * L)


def test_an_asset_put_to_use_a_day_later_gets_half():
    got = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("Lathe", 10 * L, date(2025, 10, 4)),)), fy_end=FY_END)
    assert got.additions_half_rate_paise == 10 * L
    assert got.depreciation_paise == int(0.075 * 10 * L)


def test_it_is_PUT_TO_USE_that_counts_not_the_purchase():
    """The proviso reads "acquired ... AND is put to use ... for a period of
    less than one hundred and eighty days". An asset bought in February and put
    to use in June belongs to the NEXT previous year and gets nothing now — not
    half."""
    got = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("Press", 10 * L, date(2026, 6, 1)),)), fy_end=FY_END)
    assert got.additions_full_rate_paise == 0
    assert got.additions_half_rate_paise == 0
    assert got.additions_not_put_to_use_paise == 10 * L
    assert got.depreciation_paise == 0


def test_an_addition_with_no_put_to_use_date_is_refused_not_guessed():
    """Half would under-allow and full would over-allow, and both look like an
    answer."""
    got = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("Press", 10 * L),)), fy_end=FY_END)
    assert got.depreciation_paise == 0
    assert got.additions_not_put_to_use_paise == 10 * L
    assert any("no put-to-use date" in g for g in got.gaps)


# ══════════════════════════════════════════════════════════════════════════════
# §43(6)(c) — the block's written-down value
# ══════════════════════════════════════════════════════════════════════════════

def test_the_worked_example():
    """Opening ₹10,00,000; a ₹2,00,000 addition in June and ₹1,00,000 in
    December; ₹50,000 of moneys payable on a sale.

        full-rate base  10,00,000 + 2,00,000 − 50,000 = 11,50,000 @ 15%  1,72,500
        half-rate base                        1,00,000 @ 7.5%               7,500
                                                                        ─────────
                                                                        1,80,000
    """
    got = compute_block(_block(
        additions=(Addition("Lathe", 2 * L, date(2025, 6, 1)),
                   Addition("Press", 1 * L, date(2025, 12, 1))),
        deletions=(Deletion("Old drill", 50_000_00),)), fy_end=FY_END)
    assert got.wdv_before_depreciation_paise == 1_250_000_00
    assert got.depreciation_paise == 1_80_000_00
    assert got.closing_wdv_paise == 10_70_000_00
    assert got.short_term_capital_gain_paise == 0


def test_the_moneys_payable_bite_the_FULL_rate_part_first():
    """The order §43(6)(c) implies, and the one that matters. Reducing the
    half-rate additions first would leave the full rate applying to money the
    block no longer has — a larger allowance than the section gives."""
    got = compute_block(_block(
        opening_wdv_paise=1 * L,
        additions=(Addition("New press", 10 * L, date(2025, 12, 1)),),
        deletions=(Deletion("Sold", 1 * L),)), fy_end=FY_END)
    # Full-rate base 1,00,000 absorbed entirely; half-rate base untouched.
    assert got.depreciation_paise == int(0.075 * 10 * L)


def test_a_sale_reduces_the_block_by_the_MONEYS_PAYABLE_not_by_cost():
    """§43(6)(c)(i)(B). An asset scrapped for nothing reduces the block by
    nothing — and still leaves it."""
    got = compute_block(_block(deletions=(Deletion("Scrapped", 0),)), fy_end=FY_END)
    assert got.deletions_paise == 0
    assert got.wdv_before_depreciation_paise == 10 * L


def test_an_asset_is_never_depreciated_individually():
    """The property that separates §32 from Schedule II: two blocks with the
    same total money in them, split differently between assets, depreciate
    identically, because the block is the unit."""
    one = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("A", 10 * L, date(2025, 5, 1)),)), fy_end=FY_END)
    many = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("A", 3 * L, date(2025, 5, 1)),
        Addition("B", 3 * L, date(2025, 6, 1)),
        Addition("C", 4 * L, date(2025, 7, 1)))), fy_end=FY_END)
    assert one.depreciation_paise == many.depreciation_paise


# ══════════════════════════════════════════════════════════════════════════════
# §50 — the block's collapse
# ══════════════════════════════════════════════════════════════════════════════

def test_moneys_payable_over_the_block_is_a_SHORT_TERM_GAIN():
    got = compute_block(_block(
        opening_wdv_paise=5 * L,
        deletions=(Deletion("Sold high", 8 * L),)), fy_end=FY_END)
    assert got.short_term_capital_gain_paise == 3 * L
    assert got.depreciation_paise == 0, "an overdrawn block is not depreciated"
    assert got.closing_wdv_paise == 0


def test_an_EMPTIED_block_is_a_short_term_LOSS_even_with_money_left():
    """§50's second limb, and a different question from the first. A block can
    have a positive written-down value and no assets left — every one sold at a
    loss — and then the balance is a capital loss, not a depreciable base."""
    got = compute_block(_block(
        opening_wdv_paise=5 * L,
        deletions=(Deletion("Sold cheap", 1 * L),),
        assets_remain=False), fy_end=FY_END)
    assert got.wdv_before_depreciation_paise == 4 * L
    assert got.short_term_capital_gain_paise == -4 * L
    assert got.depreciation_paise == 0
    assert got.closing_wdv_paise == 0


def test_not_knowing_whether_assets_remain_is_a_named_gap():
    """Money does not answer it, so the engine says so rather than assuming
    either way — and states which assumption the figure below rests on."""
    got = compute_block(_block(assets_remain=None), fy_end=FY_END)
    assert got.depreciation_paise > 0
    assert any("§50" in g and "not stated" in g for g in got.gaps)


def test_a_block_is_never_depreciated_below_nil():
    got = compute_block(_block(
        opening_wdv_paise=100, rate_percent=40), fy_end=FY_END)
    assert got.depreciation_paise == 40
    assert got.closing_wdv_paise == 60
    empty = compute_block(_block(opening_wdv_paise=0), fy_end=FY_END)
    assert empty.depreciation_paise == 0 and empty.closing_wdv_paise == 0


# ══════════════════════════════════════════════════════════════════════════════
# §32(1)(iia) additional depreciation
# ══════════════════════════════════════════════════════════════════════════════

def test_additional_depreciation_is_claimed_only_when_it_is_asserted():
    """20% of actual cost, and it reaches only an assessee engaged in
    manufacture or production (or the generation of power) who has not opted
    into §115BAA/§115BAB. None of those facts is held anywhere in this product,
    so it is never inferred from an asset being new plant."""
    silent = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("New press", 10 * L, date(2025, 5, 1)),)), fy_end=FY_END)
    assert silent.additional_depreciation_paise == 0

    claimed = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("New press", 10 * L, date(2025, 5, 1),
                 additional_depreciation_eligible=True),)), fy_end=FY_END)
    assert claimed.additional_depreciation_paise == 2 * L
    assert claimed.total_allowance_paise == int(0.15 * 10 * L) + 2 * L


def test_half_of_it_falls_into_the_following_year_and_the_engine_says_so():
    """The third proviso. Ten per cent now, ten per cent next year — and this
    engine does not carry the balance forward for the caller."""
    got = compute_block(_block(opening_wdv_paise=0, additions=(
        Addition("New press", 10 * L, date(2025, 12, 1),
                 additional_depreciation_eligible=True),)), fy_end=FY_END)
    assert got.additional_depreciation_paise == 1 * L
    assert any("FOLLOWING previous year" in g for g in got.gaps)


def test_no_additional_depreciation_on_a_collapsed_block():
    got = compute_block(_block(
        opening_wdv_paise=0,
        additions=(Addition("New press", 1 * L, date(2025, 5, 1),
                            additional_depreciation_eligible=True),),
        deletions=(Deletion("Sold", 5 * L),)), fy_end=FY_END)
    assert got.short_term_capital_gain_paise == 4 * L
    assert got.additional_depreciation_paise == 0


# ══════════════════════════════════════════════════════════════════════════════
# Across blocks
# ══════════════════════════════════════════════════════════════════════════════

def test_blocks_do_not_mix():
    """A gain on one block is not relieved by written-down value in another.
    Each block is its own computation under §2(11)."""
    got = compute([
        _block(key="P&M 15%", rate_percent=15, opening_wdv_paise=10 * L),
        _block(key="Computers 40%", rate_percent=40, opening_wdv_paise=2 * L,
               deletions=(Deletion("Sold", 5 * L),)),
    ], fy_end=FY_END)
    assert got.depreciation_paise == int(0.15 * 10 * L)
    assert got.short_term_capital_gain_paise == 3 * L
    assert [b.key for b in got.blocks] == ["P&M 15%", "Computers 40%"]


def test_the_capital_gain_is_NOT_netted_into_the_allowance():
    """It is a capital gain and belongs in the capital-gains schedule. Folding
    it into the depreciation line would hide it in a number nobody reads as a
    gain — and §74 does not let a capital loss relieve business income anyway."""
    got = compute([_block(opening_wdv_paise=1 * L,
                          deletions=(Deletion("Sold", 4 * L),))], fy_end=FY_END)
    assert got.total_allowance_paise == 0
    assert got.short_term_capital_gain_paise == 3 * L


def test_the_result_carries_every_blocks_gaps():
    got = compute([
        _block(key="A", additions=(Addition("No date", 1 * L),)),
        _block(key="B", assets_remain=None),
    ], fy_end=FY_END)
    assert len(got.gaps) == 2
    assert isinstance(got, Section32Result)


# ══════════════════════════════════════════════════════════════════════════════
# The rate is supplied, never held
# ══════════════════════════════════════════════════════════════════════════════

def test_the_engine_holds_no_rate_table():
    """Appendix I is a long statutory table and this repository's rule is that
    such data is entered by a human rather than written from memory (CLAUDE.md).
    A block IS a rate under §2(11), so the CA who decides the block has decided
    the rate — and there is nothing here to be silently wrong."""
    import domain.income_tax.section_32 as s32
    numeric = {n: v for n, v in vars(s32).items()
               if n.isupper() and isinstance(v, (dict, list, tuple))}
    assert numeric == {}, f"a rate table crept in: {numeric}"
    assert s32.HALF_RATE_DAYS == 180, "the one statutory number, and it is a period"


def test_every_rate_is_the_block_s_own():
    for rate in (5, 10, 15, 25, 30, 40, 45):
        got = compute_block(_block(rate_percent=rate, opening_wdv_paise=100 * L),
                            fy_end=FY_END)
        assert got.depreciation_paise == rate * L
        assert got.rate_percent == rate


def test_a_collapsed_block_carries_NOTHING_into_next_year():
    """The bug this file caught. Leaving the balance in the block would let the
    same money be relieved twice — once as a §50 capital loss, then again as
    depreciation in every year that followed."""
    emptied = compute_block(_block(
        opening_wdv_paise=5 * L, deletions=(Deletion("Sold cheap", 1 * L),),
        assets_remain=False), fy_end=FY_END)
    overdrawn = compute_block(_block(
        opening_wdv_paise=1 * L, deletions=(Deletion("Sold high", 4 * L),)),
        fy_end=FY_END)
    assert emptied.closing_wdv_paise == 0
    assert overdrawn.closing_wdv_paise == 0
