"""
IT Act 1961, §32 — depreciation on a BLOCK OF ASSETS.

WHY THIS EXISTS

Depreciation is charged twice in every Indian business's books, on two systems
that are not two rates for one calculation:

    Companies Act 2013, Schedule II — per ASSET, over its useful life. This is
    what routers/fixed_assets.py computes and what the accounts carry.

    IT Act 1961, §32 — per BLOCK, at a rate fixed for the block, on the block's
    written-down value. Assets lose their identity inside the block; there is
    no per-asset life at all, and no per-asset written-down value.

The difference between them is usually the largest single line in the
book-to-tax bridge, and `domain/income_tax/book_to_tax_bridge.py` has said in
its own docstring since it was written that "NOTHING IN THIS CODEBASE
IMPLEMENTS THE SECOND ONE". This is the second one.

WHAT §32 ACTUALLY SAYS, IN THE ORDER IT SAYS IT

  §2(11) defines a block as a group of assets of the SAME NATURE carrying the
  SAME RATE of depreciation. So "which block" and "what rate" are one fact, not
  two.

  §43(6)(c) gives the written-down value of a block at the end of the year:
  opening WDV, PLUS the actual cost of assets acquired and falling in that
  block during the year, MINUS the moneys payable in respect of any asset of
  that block sold, discarded, demolished or destroyed — the reduction being
  limited so the block cannot go below nil.

  The SECOND PROVISO to §32(1) halves the rate where an asset is acquired by
  the assessee during the previous year AND put to use for less than 180 days
  in that year. Note the conjunction: it is put-to-use that counts, and an
  asset bought in March and put to use the following June gets nothing at all
  this year, not half.

  §50 turns the block's collapse into a CAPITAL GAIN. Where the moneys payable
  exceed the block's WDV plus additions, the excess is a SHORT-TERM capital
  gain; and where the block ceases to exist because every asset in it has gone,
  whatever remains is a short-term capital loss (or the excess a gain), and no
  depreciation is allowed on it that year.

WHAT THIS MODULE REFUSES TO DECIDE, AND WHY EACH ONE IS A HUMAN STEP

  * THE RATE. Appendix I to the Income-tax Rules is a long statutory table with
    a dozen plant-and-machinery classes in it, and this repository's rule is
    that such data is entered by a human rather than written from memory
    (CLAUDE.md, "The other statutory data a human has to supply"). A block IS a
    rate under §2(11), so the CA who decides which block an asset falls in has
    already decided its rate. The block carries it; this module holds no table
    and cannot silently apply a wrong one.

  * WHETHER THE BLOCK STILL EXISTS. §50's second limb turns on whether any
    asset of the block remains, which is a fact about the register and not
    about the money: a block can have a positive WDV and no assets left. It is
    told, never inferred, and the caller that cannot say gets a named gap.

  * ADDITIONAL DEPRECIATION under §32(1)(iia). It is 20% of the actual cost of
    NEW plant and machinery, and it reaches only an assessee engaged in the
    manufacture or production of an article or thing (or in the generation,
    transmission or distribution of power), and not one who has opted into
    §115BAA or §115BAB. None of those three facts is held anywhere in this
    product. It is claimed only where the caller says so, per addition, and
    otherwise reported as not claimed rather than quietly forgone.

  * THE OPENING WDV. It comes off last year's return, and in the first year
    this software covers a client there is nothing here to derive it from.

Integer paise throughout — never float.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

#: The second proviso to §32(1): "acquired by the assessee during the previous
#: year and is put to use for the purposes of business or profession for a
#: period of less than one hundred and eighty days in that previous year".
#: Derived from the year's own end rather than stated as "3 October", because
#: the boundary moves in a leap previous year and a hardcoded date would be a
#: day wrong in one year out of four.
HALF_RATE_DAYS = 180


def half_rate_cutoff(fy_end: date) -> date:
    """The last put-to-use date that still earns the FULL rate.

    An asset put to use on day D is used for (fy_end − D + 1) days, so the full
    rate needs D ≤ fy_end − 179 days.
    """
    return fy_end - timedelta(days=HALF_RATE_DAYS - 1)


@dataclass(frozen=True)
class Addition:
    """One asset acquired during the year and falling into this block.

    `put_to_use_date` is NOT the purchase date, and the difference is the whole
    of the second proviso: an asset bought in February and put to use in May
    belongs to the NEXT previous year entirely. A caller that has only a
    purchase date should say so rather than passing it here as if it were the
    other thing — see `Block.gaps`.
    """
    label: str
    cost_paise: int
    put_to_use_date: Optional[date] = None
    #: §32(1)(iia). True only where the CA has determined that this is new
    #: plant or machinery AND the assessee qualifies. Never inferred.
    additional_depreciation_eligible: bool = False


@dataclass(frozen=True)
class Deletion:
    """An asset of this block sold, discarded, demolished or destroyed.

    §43(6)(c)(i)(B) reduces the block by "the moneys payable in respect of" it —
    the sale consideration, NOT the asset's book value and not its cost. An
    asset scrapped for nothing reduces the block by nothing, and still leaves
    the block.
    """
    label: str
    moneys_payable_paise: int


@dataclass(frozen=True)
class Block:
    """One block of assets: a nature and a rate, under §2(11)."""
    key: str
    #: Per cent, as Appendix I states it — 15 for plant and machinery, 40 for
    #: computers. Supplied, because a block IS its rate.
    rate_percent: int
    opening_wdv_paise: int
    additions: tuple[Addition, ...] = ()
    deletions: tuple[Deletion, ...] = ()
    #: §50's second limb. False means every asset of the block has gone, which
    #: makes the whole remaining balance a short-term capital loss and allows no
    #: depreciation. None means the caller could not say, and the result carries
    #: a gap rather than an assumption either way.
    assets_remain: Optional[bool] = True


@dataclass(frozen=True)
class BlockResult:
    key: str
    rate_percent: int
    opening_wdv_paise: int
    additions_full_rate_paise: int
    additions_half_rate_paise: int
    additions_not_put_to_use_paise: int
    deletions_paise: int
    wdv_before_depreciation_paise: int
    depreciation_paise: int
    additional_depreciation_paise: int
    closing_wdv_paise: int
    #: §50. Positive is a short-term capital GAIN, negative a short-term LOSS.
    short_term_capital_gain_paise: int
    gaps: tuple[str, ...] = ()

    @property
    def total_allowance_paise(self) -> int:
        return self.depreciation_paise + self.additional_depreciation_paise


def _pct(amount: int, rate_percent: int, *, half: bool = False) -> int:
    """rate% of an amount, in whole paise, rounded half up.

    Integer arithmetic throughout (CLAUDE.md). The halving is applied to the
    RATE, which is what the proviso says, rather than to the resulting
    depreciation — the two differ by a paise on odd figures and the statute is
    unambiguous about which it means.
    """
    numerator = amount * rate_percent
    denominator = 200 if half else 100
    if numerator < 0:
        return -((-numerator + denominator // 2) // denominator)
    return (numerator + denominator // 2) // denominator


def compute_block(block: Block, *, fy_end: date) -> BlockResult:
    """§32 depreciation for one block for one previous year."""
    gaps: list[str] = []
    cutoff = half_rate_cutoff(fy_end)
    fy_start = date(fy_end.year - 1, 4, 1)

    full, half, not_yet = 0, 0, 0
    additional = 0
    for a in block.additions:
        if a.put_to_use_date is None:
            # Not assumed either way. Half the rate would under-allow and the
            # full rate would over-allow, and both look like an answer.
            gaps.append(
                f"{a.label}: no put-to-use date, so the second proviso to §32(1) "
                f"could not be applied. The addition is excluded from the "
                f"depreciable base — supply the date it was put to use.")
            not_yet += a.cost_paise
            continue
        if a.put_to_use_date > fy_end:
            # Bought this year, put to use in the next. §32 allows nothing on it
            # this year — not half.
            not_yet += a.cost_paise
            continue
        if a.put_to_use_date < fy_start:
            gaps.append(
                f"{a.label}: put to use before this previous year began, so it "
                f"is not an addition of this year. Check the opening written-down "
                f"value instead.")
            not_yet += a.cost_paise
            continue
        if a.put_to_use_date <= cutoff:
            full += a.cost_paise
        else:
            half += a.cost_paise
        if a.additional_depreciation_eligible:
            # §32(1)(iia): 20 per cent of actual cost, halved where the asset was
            # put to use for less than 180 days — and the other half is allowed
            # in the FOLLOWING year under the third proviso, which this engine
            # does not carry forward for the caller.
            if a.put_to_use_date <= cutoff:
                additional += _pct(a.cost_paise, 20)
            else:
                additional += _pct(a.cost_paise, 20, half=True)
                gaps.append(
                    f"{a.label}: half of the §32(1)(iia) additional depreciation "
                    f"is allowed in the FOLLOWING previous year under the third "
                    f"proviso. It is not carried forward here.")

    deletions = sum(d.moneys_payable_paise for d in block.deletions)

    # §43(6)(c): opening + additions − moneys payable. The reduction bites the
    # full-rate part of the block first; only what it cannot absorb there
    # reaches the half-rate additions. Doing it the other way round would allow
    # depreciation at the full rate on money the block no longer has.
    base_full = block.opening_wdv_paise + full
    remaining_deduction = deletions
    take = min(base_full, remaining_deduction)
    base_full -= take
    remaining_deduction -= take
    base_half = max(0, half - remaining_deduction)
    remaining_deduction -= (half - base_half)

    wdv_before = block.opening_wdv_paise + full + half - deletions

    # §50. Two limbs, and they are different questions.
    stcg = 0
    depreciation = 0
    block_survives = True
    if wdv_before < 0:
        # The moneys payable exceeded the block. The excess is a short-term
        # capital gain and the block closes at nil; no depreciation is allowed.
        stcg = -wdv_before
        additional = 0
        block_survives = False
    elif block.assets_remain is False:
        # The block has ceased to exist. Whatever is left is a short-term
        # capital LOSS, and again nothing is depreciated.
        stcg = -wdv_before
        additional = 0
        block_survives = False
    else:
        if block.assets_remain is None:
            gaps.append(
                "Whether any asset of this block remains at the year end was not "
                "stated. §50 turns an emptied block into a short-term capital "
                "loss and allows no depreciation on it, and a positive written-"
                "down value does not settle the question. Depreciation below "
                "assumes the block still exists.")
        depreciation = _pct(base_full, block.rate_percent) + \
            _pct(base_half, block.rate_percent, half=True)
        # A block cannot be depreciated below nil.
        depreciation = min(depreciation, max(0, wdv_before))
        additional = min(additional, max(0, wdv_before - depreciation))

    # Where §50 has applied, the block is GONE — the whole balance has become a
    # short-term capital gain or loss and there is nothing left to carry into
    # next year's opening written-down value. Leaving the money in would let the
    # same amount be relieved twice: once as a capital loss, then again as
    # depreciation in every year that followed.
    closing = 0 if not block_survives else max(0, wdv_before - depreciation - additional)

    return BlockResult(
        key=block.key,
        rate_percent=block.rate_percent,
        opening_wdv_paise=block.opening_wdv_paise,
        additions_full_rate_paise=full,
        additions_half_rate_paise=half,
        additions_not_put_to_use_paise=not_yet,
        deletions_paise=deletions,
        wdv_before_depreciation_paise=wdv_before,
        depreciation_paise=depreciation,
        additional_depreciation_paise=additional,
        closing_wdv_paise=closing,
        short_term_capital_gain_paise=stcg,
        gaps=tuple(gaps),
    )


@dataclass(frozen=True)
class Section32Result:
    blocks: tuple[BlockResult, ...]
    depreciation_paise: int
    additional_depreciation_paise: int
    short_term_capital_gain_paise: int
    gaps: tuple[str, ...]

    @property
    def total_allowance_paise(self) -> int:
        """What the book-to-tax bridge deducts as depreciation under §32."""
        return self.depreciation_paise + self.additional_depreciation_paise


def compute(blocks: Sequence[Block], *, fy_end: date) -> Section32Result:
    """§32 for every block of one assessee for one previous year.

    The §50 figures are NOT netted into the allowance. A short-term capital gain
    on a block is a capital gain — it belongs in the capital gains schedule and
    is taxed there, and folding it into the depreciation line would hide it in a
    number nobody reads as a gain.
    """
    results = tuple(compute_block(b, fy_end=fy_end) for b in blocks)
    return Section32Result(
        blocks=results,
        depreciation_paise=sum(r.depreciation_paise for r in results),
        additional_depreciation_paise=sum(r.additional_depreciation_paise for r in results),
        short_term_capital_gain_paise=sum(r.short_term_capital_gain_paise for r in results),
        gaps=tuple(g for r in results for g in r.gaps),
    )
