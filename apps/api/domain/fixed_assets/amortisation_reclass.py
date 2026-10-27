"""Moving an intangible asset's accumulated amortisation out of the shared ledger into the ledger of its own (POST-A-345, stage 3).

The ARITHMETIC AND THE REFUSALS, with no database in it. `services/amortisation_reclass_service` reads the facts and posts; this module
says what an asset's move is made of and when a batch of moves must not be posted. Integer paise throughout.

WHY AN ASSET'S MOVE IS NOT ITS REGISTER FIGURE
    Schedule III (Companies Act 2013, Division I) presents tangible and intangible assets on separate lines, each net of its own
    accumulated depreciation or amortisation. The shared Accumulated Depreciation ledger sits on the tangible line, so an intangible
    asset's amortisation reduced the wrong line. The register holds ONE accumulated figure per asset, and it is not the same thing as
    what the ledger holds for that asset:

      * `posted_here` is what the asset's own depreciation journals put in the shared ledger (net of any reversal of them). It is
        evidence in the ledger, asset by asset, because a depreciation journal carries the asset's id.
      * `carried_over` is the rest of the register's figure: depreciation the asset already had when it was brought over from another
        system (the opening-register import posts no journal; the amount arrives through the opening balances or an imported trial
        balance and sits wherever that put it). The product CANNOT know which ledger that is, so the person posting names it, and it
        is never moved silently.
      * Where the ledger holds MORE than the register (a depreciation journal posted and the register update failed, an asset entered
        at a written-down value), the two disagree and the asset is not moved: the difference is named, not absorbed.

    Moving only `posted_here` and then pointing the asset at the new ledger would leave the carried-over part behind, and the asset's
    disposal would debit the new ledger for the whole register figure: the new ledger would go to a debit balance and the shared one
    would keep a credit with no asset behind it. That is the half-in-each-ledger defect this change exists to prevent, so such an asset
    waits until its carried-over part has a named home.

THE DATES, BECAUSE A BALANCE SHEET IS CUT AT A DATE AND A LEDGER IS JUDGED AT EACH OF THEM
    The person posting states the date the reclassification is AS AT (no default; the opening-register import's rule), and it must be
    a MONTH END: depreciation is posted at month ends, balances are kept by month, and a balance sheet is cut at a month end, so a
    mid-month date has no balance to be judged against. What the ledger holds up to that date goes in an entry dated that day.

    Months already posted AFTER that date are in the shared ledger too. Each moves in an entry dated at the END OF THE FINANCIAL YEAR
    IT FALLS IN, or today where that year has not ended, so that EVERY year-end balance sheet from the stated date on shows the
    corrected split and not only the ones after today. (An entry dated today would leave the year-end balance sheet of any year
    between the stated date and today with the tangible line short and the intangible line over, while the screen said it was fixed.)
    A balance sheet cut at some other date between the stated date and the next year end can show part of the amortisation still in
    the old ledger, and the screen says so.

    The shared ledger (and the ledger named for the carried-over part) must hold enough AS AT EVERY MONTH END from the first entry to
    today, not only on the days an entry is dated and not only today: an entry dated 31 March that debits a ledger which did not yet
    hold the credit makes the prior year's balance sheet show a debit balance on a contra account, and a debit posted to the same
    ledger a month after the entry (a disposal of a tangible asset whose depreciation sits there) does the same to every later one.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

MOVES = "moves"
POINTED_ONLY = "pointed_only"
EXCLUDED = "excluded"


def month_end_problem(iso: str) -> Optional[str]:
    """A sentence if `iso` (YYYY-MM-DD) is not the last day of its month, else None."""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return "Say the date the reclassification is as at, as YYYY-MM-DD."
    if d.day != calendar.monthrange(d.year, d.month)[1]:
        return ("The reclassification is as at a month end, for example 31 March or 30 September: depreciation is posted at month ends, "
                "balances are kept month by month and a balance sheet is cut at a month end.")
    return None


def later_entry_date(entry_date: str, today: str, *, fy_end_of: Callable[[str], str]) -> str:
    """The date the entry that moves a month posted after the stated date is dated: the end of the financial year the month falls in,
    or today where that year has not ended yet."""
    end = fy_end_of(entry_date)
    return end if end < today else today


@dataclass(frozen=True)
class AssetPosition:
    """What is known about one live, unpointed intangible asset. All paise."""
    asset_id: str
    asset_code: str
    asset_name: str
    #: the register's accumulated depreciation for the asset.
    register_paise: int
    #: net credit the asset's own depreciation journals put in the shared ledger, dated on or before `as_at`.
    posted_to_as_at_paise: int
    #: the same, dated after `as_at`, grouped by the date of the entry that will move them: ((YYYY-MM-DD, paise), ...) by date.
    posted_later: tuple = ()


@dataclass(frozen=True)
class AssetPlan:
    asset_id: str
    asset_code: str
    asset_name: str
    outcome: str
    register_paise: int
    #: leaves the shared ledger on `as_at`.
    from_shared_to_as_at_paise: int = 0
    #: leaves the ledger the person named for the carried-over part, on `as_at`.
    from_carried_paise: int = 0
    #: leaves the shared ledger later, one entry per date: ((YYYY-MM-DD, paise), ...) by date.
    later: tuple = ()
    reason: str = ""

    @property
    def from_shared_after_as_at_paise(self) -> int:
        return sum(amount for _d, amount in self.later)

    @property
    def credit_to_own_ledger_paise(self) -> int:
        return self.from_shared_to_as_at_paise + self.from_carried_paise + self.from_shared_after_as_at_paise


def plan_asset(pos: AssetPosition, *, says_rupees) -> AssetPlan:
    """What moving one asset is made of, or why it is not moved. `says_rupees` writes an amount in a sentence (`rupee_text`)."""
    later_total = sum(amount for _d, amount in pos.posted_later)
    if pos.register_paise < 0 or pos.posted_to_as_at_paise < 0 or any(amount < 0 for _d, amount in pos.posted_later):
        return AssetPlan(pos.asset_id, pos.asset_code, pos.asset_name, EXCLUDED, pos.register_paise, reason=(
            "The ledger shows more reversed than posted for this asset's depreciation, so what it holds cannot be told from what the "
            "register says. Look at its depreciation entries before moving it."))
    posted = pos.posted_to_as_at_paise + later_total
    if pos.register_paise == 0 and posted == 0:
        return AssetPlan(pos.asset_id, pos.asset_code, pos.asset_name, POINTED_ONLY, 0)
    carried = pos.register_paise - posted
    if carried < 0:
        return AssetPlan(pos.asset_id, pos.asset_code, pos.asset_name, EXCLUDED, pos.register_paise, reason=(
            f"The ledger holds {says_rupees(-carried)} more of this asset's depreciation than the register records "
            f"(register {says_rupees(pos.register_paise)}, depreciation journals {says_rupees(posted)}). That is a difference to "
            "explain, not to move: a depreciation journal posted and the register did not follow, or the asset was entered at a "
            "written-down value."))
    return AssetPlan(pos.asset_id, pos.asset_code, pos.asset_name, MOVES, pos.register_paise,
                     from_shared_to_as_at_paise=pos.posted_to_as_at_paise, from_carried_paise=carried,
                     later=tuple((d, a) for d, a in pos.posted_later if a))


def entry_dates(plans: list[AssetPlan], as_at: str) -> list[str]:
    """Every date an entry of this batch is dated, earliest first: the stated date (only if some asset has something to move AS AT it:
    otherwise no entry is dated there and a closed year then is no reason to refuse), then each later one."""
    dates: set[str] = set()
    for p in plans:
        if p.outcome == MOVES:
            if p.from_shared_to_as_at_paise or p.from_carried_paise:
                dates.add(as_at)
            dates |= {d for d, _a in p.later}
    return sorted(dates)


def check_dates(dates: list[str], today: str) -> list[str]:
    """Every date the shared ledger (and the ledger named for the carried-over part) is judged at: each entry's own date AND every month
    end from the first entry's month to the later of the last entry's month and today's. An entry takes credit out of the ledger from
    its date on, so the ledger must still be in credit on every balance sheet cut after it, not only on the days an entry is dated: a
    debit posted to the same ledger a month later (a disposal of a tangible asset whose depreciation sits there) would otherwise take
    the tangible line's contra into debit on every later balance sheet and pass the check."""
    if not dates:
        return []
    first = date.fromisoformat(dates[0])
    last = max(date.fromisoformat(dates[-1]), date.fromisoformat(today))
    points = set(dates)
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        points.add(date(year, month, calendar.monthrange(year, month)[1]).isoformat())
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return sorted(points)


@dataclass
class BatchCheck:
    total_paise: int = 0
    from_shared_paise: int = 0
    from_carried_paise: int = 0
    refusals: list[str] = field(default_factory=list)


def _outflow_by_date(plans: list[AssetPlan], as_at: str, carried_source_is_shared: bool) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in plans:
        if p.outcome != MOVES:
            continue
        first = p.from_shared_to_as_at_paise + (p.from_carried_paise if carried_source_is_shared else 0)
        if first:
            out[as_at] = out.get(as_at, 0) + first
        for d, amount in p.later:
            out[d] = out.get(d, 0) + amount
    return out


def check_batch(plans: list[AssetPlan], *, as_at: str, shared_balance_at: dict, carried_source_is_shared: bool,
                carried_balance_at: Optional[int | dict], own_credit_paise: Optional[int], already_in_own_ledger_paise: int,
                says_rupees, says_date=str) -> BatchCheck:
    """Whether the batch may be posted. Balances are THIS CLIENT's credit balance of a ledger (a credit balance is positive);
    None means the balance could not be read, which refuses, because not being able to look is never the same as it being enough.

    * `shared_balance_at` maps each date in `check_dates` (every entry's date and every month end from the first entry to today) to the
      shared ledger's credit balance AS AT THAT DATE, and the shared ledger must cover what has left it by then (cumulatively), or the
      move would put the tangible line's contra into a debit balance on that day's balance sheet;
    * the ledger named for the carried-over part, if it is not the shared one, must hold at least the carried-over part on every one of
      those dates from `as_at` on (a dict of date -> balance; a bare number is the balance as at `as_at` alone);
    * the new ledger must hold exactly what the assets already pointed at it account for. A credit nothing explains (a trial balance
      mapped to it by name, an entry made by hand) would be doubled by a move, and no netting is offered because which of the two is
      the mistake is the person's answer.
    """
    moving = [p for p in plans if p.outcome == MOVES]
    out = BatchCheck(
        total_paise=sum(p.credit_to_own_ledger_paise for p in moving),
        from_shared_paise=sum(p.from_shared_to_as_at_paise + p.from_shared_after_as_at_paise for p in moving),
        from_carried_paise=sum(p.from_carried_paise for p in moving))
    if not moving:
        return out
    outflow = _outflow_by_date(moving, as_at, carried_source_is_shared)
    left = 0
    for d in sorted(set(shared_balance_at) | set(outflow)):
        left += outflow.get(d, 0)
        if not left:
            continue                       # nothing has left the ledger yet on this date
        held = shared_balance_at.get(d)
        if held is None:
            out.refusals.append(f"The balance of the shared Accumulated Depreciation ledger as at {says_date(d)} could not be read, so it "
                                "cannot be checked against what would leave it. Nothing was posted.")
            break
        if held < left:
            out.refusals.append(
                f"The shared Accumulated Depreciation ledger holds {says_rupees(held)} for this client as at {says_date(d)} and "
                f"{says_rupees(left)} would have left it by then. Moving that much would turn the tangible assets' contra into a debit "
                "balance on that date's balance sheet. Find where the rest of this depreciation sits (an imported trial balance often "
                "puts it in a ledger of its own) and name that ledger for the carried-over part, or state a later date, or leave "
                "these assets where they are.")
            break                          # the first date it fails on is the one to name
    if not carried_source_is_shared and out.from_carried_paise:
        points = carried_balance_at if isinstance(carried_balance_at, dict) else (
            None if carried_balance_at is None else {as_at: carried_balance_at})
        if points is None:
            out.refusals.append("The balance of the ledger named for the carried-over part could not be read. Nothing was posted.")
        else:
            for d in sorted(points):
                if d >= as_at and (points[d] is None or points[d] < out.from_carried_paise):
                    out.refusals.append(
                        f"The ledger named for the carried-over part holds {says_rupees(points[d] or 0)} as at {says_date(d)} and "
                        f"{says_rupees(out.from_carried_paise)} would leave it.")
                    break
    if own_credit_paise is None:
        out.refusals.append("The balance of the Accumulated Amortisation ledger could not be read. Nothing was posted.")
    elif own_credit_paise > already_in_own_ledger_paise:
        out.refusals.append(
            f"The Accumulated Amortisation ledger already carries {says_rupees(own_credit_paise)} for this client and the assets "
            f"already pointed at it account for {says_rupees(already_in_own_ledger_paise)}: {says_rupees(own_credit_paise - already_in_own_ledger_paise)} "
            "more than they explain (an imported trial balance mapped to it by name, or an entry made by hand). Moving more into it would "
            "double that. Which of the two is the mistake is for you to say; nothing is netted here.")
    elif own_credit_paise < already_in_own_ledger_paise:
        out.refusals.append(
            f"The Accumulated Amortisation ledger carries {says_rupees(own_credit_paise)} for this client and the assets already "
            f"pointed at it account for {says_rupees(already_in_own_ledger_paise)}: {says_rupees(already_in_own_ledger_paise - own_credit_paise)} "
            "less than they should (a reclassification entry reversed or edited by hand, or an asset disposed of twice). Nothing is "
            "moved until that is looked at; nothing is netted here.")
    return out


def financial_years_fixed(as_at: str, today: str, later_dates: list[str]) -> list[dict]:
    """Which balance sheets the move changes, in words. The entry dated `as_at` and one entry at each later date mean that a balance
    sheet cut at `as_at`, at each of the dates in `later_dates` (financial year ends, and today) and at every date after the last
    one shows the corrected split. One cut at any other date after `as_at` can show the months not yet moved in the old ledger,
    and one cut before `as_at` keeps the split it had. Stated rather than implied."""
    fixed = [as_at, *later_dates]
    out = [{"label": "fixed", "fixed": True,
            "note": "Balance sheets cut at " + ", ".join(fixed[:-1]) + (" and " if len(fixed) > 1 else "") + fixed[-1]
                    + " and at any date after the last of these show the corrected split."
                    if len(fixed) > 1 else
                    f"The balance sheet as at {as_at} and every later one show the corrected split."}]
    if later_dates:
        out.append({"label": "between", "fixed": False,
                    "note": "A balance sheet cut at another date between these may still show the part posted after the earlier one in the "
                            "old ledger. Financial year ends are all exact."})
    out.append({"label": f"before {as_at}", "fixed": False,
                "note": "A balance sheet cut at an earlier date keeps the split it had. To correct one, state an earlier month end, "
                        "if that year is still open."})
    return out
