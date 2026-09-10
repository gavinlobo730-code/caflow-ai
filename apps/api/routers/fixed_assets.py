"""
Fixed Assets router — Asset register, depreciation engine, disposal.

Depreciation methods:
- SL  (Straight Line Method): annual depreciation = (cost - salvage) / useful_life_years
- WDV (Written Down Value):   annual depreciation = WDV × wdv_rate_percent / 100

Companies Act 2013 Schedule II prescribes a useful LIFE per class of asset, not
a WDV percentage — see _SCHEDULE_II_PART_C below, which is the one table, and
the only source the create form's defaults come from.
"""
# ist_today, not datetime.now(timezone.utc): at 00:20 IST on 1 April a UTC
# "today" is still 31 March, so a defaulted depreciation period or disposal
# date lands in the PREVIOUS financial year — quite possibly one the CA has
# just locked.
from core.ist_clock import ist_today, month_end_date
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP
import calendar
import math
import re

from models.common import api_response
from models.accounting import (FixedAssetIn, FixedAssetUpdateIn, DepreciationIn,
                               DepreciationRunIn, DisposalIn)
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from services.timeline_service import timeline_service
from services.phase2_journal_service import Phase2JournalService
from services.period_validation_service import period_validation_service, get_fy_for_date
from services import period_lock_service
from services.audit_service import log_event
from services.numbering import next_sequence

router = APIRouter(prefix="/api/fixed-assets", tags=["fixed_assets"])


def capitalised_cost_paise(cost_paise: int, igst_paise: int, cgst_paise: int,
                           sgst_paise: int, itc_eligible: Optional[bool]) -> int:
    """The asset's DEPRECIABLE cost, after CGST Act §17(5).

    Tax on an acquisition goes one of two ways and there is no third:

      * credit is available   -> it is an ASSET (input tax credit), claimed in
        the return, and no part of the machine's cost;
      * credit is BLOCKED     -> §17(5) bars it (a motor vehicle for personal
        carriage is the everyday case). The money was still paid and it bought
        the asset, so it is part of the cost — which means it DEPRECIATES.

    That second limb is why `itc_eligible` cannot be defaulted: leaving blocked
    tax out of the cost is not a presentational slip, it is depreciation the
    client never claims for the life of the asset.

    `None` — not stated — is treated as NOT capitalising, which matches every
    row created before migration 343 and keeps their cost unchanged.
    """
    tax = int(igst_paise or 0) + int(cgst_paise or 0) + int(sgst_paise or 0)
    return int(cost_paise) + (tax if (tax and itc_eligible is False) else 0)


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row via keyset paging on `key`.

    The same helper eleven services carry. An un-paged `.execute()` is silently
    capped at PostgREST's ~1000 rows, and a register-integrity report that
    stopped at 1000 assets would answer "clean" for the client most likely to
    have a problem. FA-12 records that the other fixed-asset reads have the same
    gap; this closes it only where the new report needs it, rather than widening
    the change.
    """
    first = make_query()
    if not (hasattr(first, "gt") and hasattr(first, "order") and hasattr(first, "limit")):
        return first.execute().data or []
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(page).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            break
        cursor = rows[-1][key]
    return out


_journal_svc = Phase2JournalService()

# ─── Companies Act 2013, Schedule II — the LIVES, and the rate derived ───────
#
# Schedule II prescribes a useful LIFE per class of asset (Part C). It does not
# prescribe a WDV percentage anywhere: the percentage is DERIVED from the life,
#
#     R = 1 − (residual value / original cost) ^ (1/n)
#
# which is the rate at which n years of reducing-balance charges take an asset
# from its cost down to its residual value. So the life is what is stored here
# and the rate is computed from it. That is what the statute actually says; it
# makes the SL path right for free (SL divides by the same n); and it removes
# the second number that can drift away from the first.
#
# WHAT WAS HERE BEFORE WAS NOT SCHEDULE II. It was a hand-written rate column
# in which only Building was close (5.00% against the 60-year figure of 4.87%),
# and the provenance of the rest was visible in the numbers themselves:
# Furniture 10.00% and Intangibles 25.00% are INCOME TAX ACT block rates, and
# 25.89% — the correct TEN-year figure — sat against Vehicles, which Schedule
# II gives eight years. Two statutes mixed under one statute's name, on a form
# that labelled the field "Companies Act 2013 Sch II rate". Every wrong entry
# was wrong in the same direction — Office Equipment charged 13.91% where the
# five-year life gives 45.07% — so each of them UNDER-depreciated, overstating
# both the carrying value and the profit.
#
# The category keys are the asset_category taxonomy used platform-wide — the
# create form's list (now served from here, see GET /categories) and the GL
# account mapping in services/phase2_journal_service.py's cat_map. task #232
# fixed an earlier mismatch in those keys; adding a key here without adding it
# there silently books the asset to Plant & Machinery.

# Schedule II, Part C, Note 5: "Ordinarily, the residual value of an asset is
# often insignificant but it should generally be not more than 5% of the
# original cost of the asset." Named rather than written inline because it is
# the one term in the derivation that is a statutory cap and not an input.
SCHEDULE_II_RESIDUAL_FRACTION = Decimal("0.05")

# Part C, by the Schedule's own headings. Where a heading prescribes more than
# one life the CA has a real choice, so ALL of them are offered and the first
# is only the default — a server is not a laptop and a lorry on hire is not a
# company car. A life of None means Schedule II prescribes none for that class,
# which is an ANSWER and not a missing number (see _no_statutory_basis).
_SCHEDULE_II_PART_C: dict[str, tuple[tuple[str, Optional[int]], ...]] = {
    "Building": (
        ("Buildings (other than factory buildings) — RCC frame structure", 60),
        ("Buildings (other than factory buildings) — other than RCC frame structure", 30),
        ("Factory buildings", 30),
    ),
    "Plant & Machinery": (
        ("General rate — plant and machinery other than continuous process plant", 15),
        ("Continuous process plant", 25),
    ),
    "Furniture & Fixtures": (
        ("General furniture and fittings", 10),
        ("Furniture and fittings used in hotels, restaurants, boarding houses and similar", 8),
    ),
    "Office Equipment": (
        ("Office equipment", 5),
    ),
    "Computer & IT Equipment": (
        ("End user devices — desktops, laptops, etc.", 3),
        ("Servers and networks", 6),
    ),
    "Vehicles": (
        ("Motor cars, buses and lorries other than those used in a business of running them on hire", 8),
        ("Motor buses, lorries, cars and taxies used in a business of running them on hire", 6),
        ("Motor cycles, scooters and other mopeds", 10),
    ),
    "Land": (
        ("Land — not a depreciable asset", None),
    ),
    "Intangibles": (
        ("Amortised under AS 26 / Ind AS 38 — Schedule II Part A prescribes no life", None),
    ),
    "Other": (
        ("No Schedule II class — the CA determines the life or rate", None),
    ),
}

# Land has no useful life to spread a cost over, so Schedule II never
# depreciates it. That is a different statement from "we do not have a rate for
# it": the rate is a definite 0.00, and the SL path must honour it too.
_NOT_DEPRECIABLE = frozenset({"Land"})


def _wdv_rate_for_life(years: Optional[int]) -> Optional[Decimal]:
    """The Schedule II WDV rate for a useful life, to the two decimals
    fixed_assets.wdv_rate_percent (NUMERIC(5,2)) can hold.

        R = 1 − (residual/cost) ^ (1/n),  residual/cost capped at 5%

    Decimal throughout, never float: this number multiplies the WDV in every
    charge the asset will ever produce, and a binary float here is a rounding
    difference in all of them.
    """
    if not years:
        return None
    ratio = SCHEDULE_II_RESIDUAL_FRACTION ** (Decimal(1) / Decimal(years))
    return ((Decimal(1) - ratio) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# category -> the Schedule II classes it offers, each with its derived rate.
SCHEDULE_II_CATEGORIES: dict[str, tuple[dict, ...]] = {
    category: tuple(
        {
            "label": label,
            "useful_life_years": years,
            "wdv_rate_percent": (
                Decimal("0.00") if category in _NOT_DEPRECIABLE else _wdv_rate_for_life(years)
            ),
        }
        for label, years in classes
    )
    for category, classes in _SCHEDULE_II_PART_C.items()
}


def _default_schedule_ii_class(category: Optional[str]) -> dict:
    """The class a new asset in this category gets unless the CA picks another.
    An unknown category falls through to "Other", which prescribes nothing —
    so it refuses rather than inventing a rate for a category nobody modelled."""
    classes = SCHEDULE_II_CATEGORIES.get(category or "Other") or SCHEDULE_II_CATEGORIES["Other"]
    return classes[0]


# The old name and the old shape (category -> rate), now derived from the lives
# so the two can no longer disagree. A None value means Schedule II prescribes
# no life for that category and therefore no rate — the CA supplies one.
_DEFAULT_WDV_RATES: dict[str, Optional[Decimal]] = {
    category: classes[0]["wdv_rate_percent"] for category, classes in SCHEDULE_II_CATEGORIES.items()
}


def _no_statutory_basis(category: str, method: str) -> str:
    needed = "a WDV rate" if method == "WDV" else "a useful life"
    return (
        f"Schedule II prescribes no useful life for '{category}', so there is no rate to "
        f"default to — record {needed} for this asset. Intangible assets are amortised "
        f"under AS 26 / Ind AS 38 (Schedule II Part A), which is a judgement the CA makes, "
        f"not a figure this table can supply."
    )


_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


#: The three tiers a correction to an asset falls into. They are three
#: different MECHANISMS, and conflating any two is how a register and a ledger
#: come apart:
#:
#:   A  no GL and no statutory consequence — write it and log it.
#:   B  the acquisition JOURNAL is wrong too, so the correction is a reversal
#:      and a re-post through the one kernel, never an in-place rewrite.
#:   C  a revision of an accounting ESTIMATE (Companies Act 2013 Schedule II
#:      Part C Note 7, AS 10 / Ind AS 16 §51): it applies to the remaining
#:      carrying amount over the remaining life, PROSPECTIVELY. Rewriting
#:      months already posted at the old basis would restate periods a return
#:      may already cover.
_TIER_A_FIELDS = frozenset({"asset_name", "location", "notes"})
_TIER_B_FIELDS = frozenset({
    "purchase_cost_paise", "asset_category", "purchase_date",
    "acquisition_mode", "vendor_id", "purchase_bill_id", "bank_account_id",
    "payment_mode", "igst_paise", "cgst_paise", "sgst_paise",
    "itc_eligible", "itc_blocked_reason",
})
_TIER_C_FIELDS = frozenset({
    "useful_life_years", "salvage_value_paise", "depreciation_method",
    "wdv_rate_percent",
})


def _live_asset(db, asset_id: str, firm_id: str) -> Optional[dict]:
    """The asset row, firm-scoped, excluding a soft-deleted one (migration 351).

    `.single()` raises where PostgREST returns no row, so the filter has to be
    part of the query rather than a check afterwards — a deleted asset must
    read as absent, not as a row with a deleted_at on it.
    """
    res = (db.table("fixed_assets").select("*")
           .eq("id", asset_id).eq("firm_id", firm_id)
           .is_("deleted_at", "null").limit(1).execute())
    rows = res.data if isinstance(res.data, list) else ([res.data] if res.data else [])
    return rows[0] if rows else None


def _compute_annual_depreciation(asset: dict) -> int:
    """
    Compute ONE YEAR's depreciation in paise from the asset's current state,
    using Decimal (never binary float — CLAUDE.md: every rupee calculation
    must use integer paise arithmetic).
    SL:  (cost - salvage) / useful_life_years
    WDV: current_wdv × rate / 100

    Callers must only pass an `asset` whose accumulated_depreciation_paise
    represents the OPENING balance of the year being computed — see
    _annual_depreciation_for_period, which is what routers/fixed_assets.py's
    posting/projection endpoints actually call; this pure function has no
    per-call memory of which year it's being asked about.

    Raises ValueError where neither the row nor Schedule II supplies a basis
    for the charge (an intangible with no amortisation rate recorded, say).
    Refusing is the point: falling back to a plausible number is how the
    Income-tax rates got into a table labelled Schedule II in the first place.
    """
    cost     = asset["purchase_cost_paise"]
    salvage  = asset.get("salvage_value_paise", 0)
    method   = asset.get("depreciation_method", "WDV")
    accum    = asset.get("accumulated_depreciation_paise", 0)
    category = asset.get("asset_category") or "Other"
    wdv_now  = cost - accum

    # Schedule II spreads a cost over a useful life. Land has none, so it is
    # never depreciated — whichever method the row happens to carry.
    if category in _NOT_DEPRECIABLE:
        return 0

    if wdv_now <= salvage:
        return 0  # fully depreciated

    if method == "SL":
        life = asset.get("useful_life_years") or _default_schedule_ii_class(category)["useful_life_years"]
        if not life:
            raise ValueError(_no_statutory_basis(category, "SL"))
        annual = math.floor(Decimal(cost - salvage) / Decimal(life))
    else:  # WDV
        rate_value = asset.get("wdv_rate_percent")
        if rate_value is None:
            rate_value = _DEFAULT_WDV_RATES.get(category, _DEFAULT_WDV_RATES["Other"])
        if rate_value is None:
            raise ValueError(_no_statutory_basis(category, "WDV"))
        rate = Decimal(str(rate_value))
        annual = math.floor(Decimal(wdv_now) * rate / Decimal(100))

    # Cannot depreciate below salvage value
    return min(annual, wdv_now - salvage)


def _annual_depreciation_for_period(asset: dict, period: str) -> tuple[int, str, int]:
    """Resolve the FIXED annual depreciation charge this asset's `period`
    posting (or projection) should divide by 12, plus which financial year
    it belongs to and the opening-of-year accumulated_depreciation_paise it
    was computed from — the router persists both back onto the asset row
    (fixed_assets.depreciation_fy / depreciation_fy_start_accum_paise,
    migration 239) so the NEXT month's posting in the same FY reuses them.

    task #232 audit finding: WDV depreciation was previously recomputed at
    EVERY monthly posting from accumulated_depreciation_paise as it stood
    THAT MONTH — already reduced by every earlier month's charge in the same
    year — instead of a fixed annual figure computed once from the year's
    OPENING WDV. Each month's charge then used a smaller and smaller base,
    systematically under-depreciating (~6.6% understated in year one,
    compounding in later years) versus Schedule II's fixed-rate-on-opening-
    balance method. SL is unaffected — cost/salvage/life never change, so
    recomputing it every time already yields the same figure regardless of
    when accumulated_depreciation_paise last changed.
    """
    fy = get_fy_for_date(f"{period}-01")
    live_accum = asset.get("accumulated_depreciation_paise", 0)

    if asset.get("depreciation_method", "WDV") != "WDV":
        return _compute_annual_depreciation(asset), fy, live_accum

    if asset.get("depreciation_fy") == fy and asset.get("depreciation_fy_start_accum_paise") is not None:
        fy_start_accum = int(asset["depreciation_fy_start_accum_paise"])
    else:
        # First posting (or projection) touching this FY for this asset —
        # the CURRENT accumulated depreciation correctly IS the opening
        # balance of this FY, since nothing has posted against it yet.
        fy_start_accum = live_accum

    snapshot = dict(asset, accumulated_depreciation_paise=fy_start_accum)
    annual = _compute_annual_depreciation(snapshot)
    return annual, fy, fy_start_accum


def _period_end_date(period: str) -> str:
    """Last calendar day of a 'YYYY-MM' period, as an ISO date string — the
    canonical posting date for a monthly depreciation entry (period-lock
    validation and the journal's entry_date both key off this).

    A thin wrapper over core.ist_clock.month_end_date, which is the one
    implementation. There were three of these; the payroll accrual would have
    been a fourth."""
    return month_end_date(period)


def _month_label(value) -> Optional[str]:
    """The 'YYYY-MM' month of a depreciation_posted_through value.

    The column is a DATE, so what comes back is '2026-04-30' (or a date
    object), never the 'YYYY-MM' the API speaks. Everything that compares a
    posted-through against a period goes through here rather than comparing
    the two strings and happening to be right about the prefix."""
    if not value:
        return None
    return str(value)[:7]


def _months_in_range(from_period: str, to_period: str) -> list[str]:
    """Every 'YYYY-MM' from one month to another, inclusive, in order.

    Order is the whole point: depreciation is charged month by month, each one
    reading the accumulated balance the previous left, and a month in a new
    financial year re-bases the annual charge. A set or a reversed list would
    produce different figures, not just a different sequence.
    """
    y, m = int(from_period[:4]), int(from_period[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= to_period:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _months_missing_before(posted_through_month: str, period: str) -> list[str]:
    """Every month strictly between the last posted month and `period`.

    Empty when the request is the very next month (the normal case), and
    empty when it is not later at all (the caller has already 409'd on that).
    """
    y, m = int(posted_through_month[:4]), int(posted_through_month[5:7])
    gap = []
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        label = f"{y:04d}-{m:02d}"
        if label >= period:
            return gap
        gap.append(label)


def _depreciation_months_outstanding(asset: dict, disposal_date: str) -> list[str]:
    """Whole months held that have NOT been depreciated, up to the month before
    disposal.

    FA-08. `dispose_asset` computes the gain or loss from
    `purchase_cost_paise - accumulated_depreciation_paise`, which is whatever
    has been POSTED. An asset bought in April, depreciated to June and sold in
    November therefore books a WDV four months too high, a gain four months too
    small (or a loss too large), and a year's depreciation expense short by the
    same amount — with nothing on the screen saying so. FA-01 made this worse
    in one sense that is really a correction: accumulated depreciation used to
    be frozen at 0 for every asset, so the stale figure is now a real number
    that looks trustworthy.

    WHY THIS REFUSES RATHER THAN POSTING THE GAP. `post_depreciation` already
    refuses a skipped month and says which ones are missing, in its own words:
    "each month is its own journal needing its own CA review ... quietly posting
    three entries behind one click is exactly the unprompted acting this
    codebase does not do." A disposal that silently posted four months of
    depreciation would be that, and it would do it inside a transaction the CA
    thinks is about a sale.

    THE MONTH OF DISPOSAL IS DELIBERATELY NOT REQUIRED. Depreciation to a
    disposal DATE is a part month, and the engine posts whole months only (the
    purchase month is the single pro-rated exception, Schedule II Note 3). Every
    whole month up to the one before disposal is charged; the part month is not,
    and `dispose_asset` reports it rather than pretending it charged it.
    """
    posted = _month_label(asset.get("depreciation_posted_through"))
    purchase_month = str(asset.get("purchase_date") or "")[:7]
    disposal_month = str(disposal_date)[:7]
    if not purchase_month or not disposal_month:
        return []
    # Depreciation is due for whole months from purchase up to the month BEFORE
    # disposal. `_months_missing_before(x, y)` gives the months strictly between
    # x and y, so passing the disposal month gives exactly that set.
    if posted is None:
        # Nothing posted at all: the purchase month itself is outstanding too.
        if purchase_month >= disposal_month:
            return []
        return [purchase_month] + _months_missing_before(purchase_month, disposal_month)
    if posted >= disposal_month:
        return []
    return _months_missing_before(posted, disposal_month)


def _prorate_purchase_month(monthly_paise: int, purchase_date: str) -> int:
    """Schedule II Note 3 / IT Act §32: an asset isn't held for the WHOLE of
    its purchase month — pro-rate that one month's charge by the fraction of
    days actually held (inclusive of the purchase day itself). Every OTHER
    month is already correctly pro-rated by omission: the CA only calls
    /depreciate for periods the asset was actually held, so months before
    purchase simply never get posted (see post_depreciation's purchase-date
    guard). Integer floor-division throughout — never float."""
    year, month, day = int(purchase_date[:4]), int(purchase_date[5:7]), int(purchase_date[8:10])
    days_in_month = calendar.monthrange(year, month)[1]
    days_held = days_in_month - day + 1
    return (monthly_paise * days_held) // days_in_month


# ─── Asset Register ───────────────────────────────────────────────────────────

@router.get("")
def list_assets(
    client_id: str = Query(...),
    include_disposed: bool = Query(False),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    # Mount-guard-covered (required client_id query param); explicit so the
    # scope check is visible at the read.
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])
    q = (db.table("fixed_assets").select("*").eq("firm_id", current_user["firm_id"])
         .eq("client_id", client_id).is_("deleted_at", "null"))
    if not include_disposed:
        q = q.eq("is_disposed", False)
    res = q.order("purchase_date", desc=True).execute()
    assets = res.data or []
    # Compute current WDV for display
    for a in assets:
        a["current_wdv_paise"] = a["purchase_cost_paise"] - a.get("accumulated_depreciation_paise", 0)
    return api_response(True, assets)


@router.post("")
def create_asset(
    data: FixedAssetIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """Add an asset and auto-post the acquisition journal."""
    # client_id rides in the JSON body, which the mount-level guard does
    # inspect on POST/PUT/PATCH; explicit so the check is visible before the
    # acquisition journal is posted.
    assert_client_access(current_user, data.client_id)

    # Resolve the Schedule II basis BEFORE anything is written. The CA may
    # send either figure explicitly (the form pre-fills the category's default
    # and lets it be overridden — Schedule II allows a different useful life,
    # which then has to be DISCLOSED in the accounts rather than being
    # forbidden); where they do not, the default
    # for the category is used, and where Schedule II prescribes nothing for
    # the category the request is REFUSED rather than given a plausible rate.
    # `is not None` and not `or`: an explicit 0.00 is a real answer.
    method       = data.depreciation_method.value
    default_cls  = _default_schedule_ii_class(data.asset_category)
    wdv_rate     = data.wdv_rate_percent if data.wdv_rate_percent is not None else default_cls["wdv_rate_percent"]
    useful_life  = data.useful_life_years or default_cls["useful_life_years"]
    if data.asset_category not in _NOT_DEPRECIABLE:
        if method == "WDV" and wdv_rate is None:
            raise HTTPException(status_code=422, detail=_no_statutory_basis(data.asset_category, "WDV"))
        if method == "SL" and not useful_life:
            raise HTTPException(status_code=422, detail=_no_statutory_basis(data.asset_category, "SL"))

    db = _db()
    if not db:
        return api_response(True, {"id": "mock-id", **data.model_dump()})

    # task #232 audit finding: this router never checked the FY lock at all —
    # an asset could be created (and its acquisition journal posted) inside a
    # financial year the firm has already closed. Every other posting router
    # (inventory, sales, purchases, GST...) already enforces this.
    period_validation_service.validate_posting_date(current_user["firm_id"], data.purchase_date)

    client_id = data.client_id

    # ── FA-07: the facts that decide the credit leg ─────────────────────────
    # A bill may be capitalised ONCE. Migration 343's partial unique index is
    # the real guarantee; this check exists so the CA gets a sentence rather
    # than a constraint-violation message, and so the reason is stated where
    # somebody reading the router can see it.
    if data.purchase_bill_id:
        clash = (db.table("fixed_assets").select("id, asset_code")
                 .eq("firm_id", current_user["firm_id"])
                 .eq("purchase_bill_id", data.purchase_bill_id)
                 .is_("deleted_at", "null")
                 .limit(1).execute().data) or []
        if clash:
            raise HTTPException(
                status_code=409,
                detail=(f"That purchase bill is already capitalised as "
                        f"{clash[0].get('asset_code') or 'an existing asset'}. "
                        f"Capitalising it twice would put the cost in Fixed "
                        f"Assets twice and leave the payable unchanged."))

    # BLOCKED TAX IS PART OF THE COST, not an expense and not a credit.
    # CGST Act §17(5) bars input credit on, among others, a motor vehicle for
    # personal carriage. The tax is still paid, so it is capitalised — which
    # means it DEPRECIATES, and which is why itc_eligible has to be answered
    # rather than defaulted. This is the only place the cost is adjusted; the
    # journal reads purchase_cost_paise as already-capitalised.
    capitalised_cost = capitalised_cost_paise(
        data.purchase_cost_paise, data.igst_paise, data.cgst_paise,
        data.sgst_paise, data.itc_eligible)

    # The asset code, one past the HIGHEST in the client's series. It was a
    # COUNT of the client's assets — the SALES-04 shape — and here the
    # consequence is worse than a wedge: FA-ACQ-{code} is the acquisition
    # journal's reference and the posting kernel dedupes on (client_id,
    # reference_no, entry_date), so a reused code makes a new asset's
    # acquisition land on the OLD asset's entry and its cost never reach the
    # balance sheet. Soft-deleted rows keep their codes and are deliberately
    # still counted here (no deleted_at filter).
    asset_code = "FA-{:04d}".format(next_sequence(
        db, "fixed_assets", "FA-",
        firm_id=current_user["firm_id"], client_id=client_id))

    row = db.table("fixed_assets").insert({
        "firm_id":                     current_user["firm_id"],
        "client_id":                   client_id,
        "asset_code":                  asset_code,
        "asset_name":                  data.asset_name,
        "asset_category":              data.asset_category,
        "purchase_date":               data.purchase_date,
        "purchase_cost_paise":         capitalised_cost,
        "salvage_value_paise":         data.salvage_value_paise,
        "acquisition_mode":            data.acquisition_mode,
        "vendor_id":                   data.vendor_id,
        "purchase_bill_id":            data.purchase_bill_id,
        "bank_account_id":             data.bank_account_id,
        "payment_mode":                data.payment_mode,
        "igst_paise":                  data.igst_paise,
        "cgst_paise":                  data.cgst_paise,
        "sgst_paise":                  data.sgst_paise,
        "itc_eligible":                data.itc_eligible,
        "itc_blocked_reason":          data.itc_blocked_reason,
        # The LIFE is stored too, not just the rate — it is what Schedule II
        # actually prescribes, it is what a SL asset depreciates by, and it is
        # what a reviewer needs to see to check the rate beside it.
        "useful_life_years":           useful_life,
        "depreciation_method":         method,
        # NUMERIC(5,2) — float() only at the wire, the arithmetic above is Decimal.
        "wdv_rate_percent":            float(wdv_rate) if wdv_rate is not None else None,
        "accumulated_depreciation_paise": 0,
        "location":                    data.location,
        "notes":                       data.notes,
    }).execute()

    asset = (row.data or [{}])[0]

    # Auto-post acquisition journal — CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    journal_id = _journal_svc.journal_for_asset_acquisition(asset, current_user["firm_id"], client_id)
    if journal_id:
        db.table("fixed_assets").update({"journal_entry_id": journal_id}).eq("id", asset["id"]).execute()
        asset["journal_entry_id"] = journal_id

    timeline_service.log(client_id, "accounting", "Asset Created",
        f"{asset_code}: {data.asset_name} added — ₹{capitalised_cost//100:,}", "info")

    return api_response(True, asset)


def _post_one_month(db, asset: dict, period: str, firm_id: str) -> dict:
    """Post ONE month's depreciation for one asset, or refuse and say why.

    Extracted from `post_depreciation` so the range runner below charges months
    through exactly the same rules rather than a second copy of them. CLAUDE.md's
    reason for the SQL/Python parity tests is the same reason here: two
    implementations of one rule drift, and this one writes to the ledger.

    Raises HTTPException for every refusal — a locked period, a gap, a period
    before the asset existed, no statutory basis. The single-asset endpoint lets
    those reach the caller; the range runner catches them per asset and reports
    them, because one asset with no rate must not stop the other ninety-nine.

    Returns the same body the endpoint returns, PLUS the asset fields that
    changed, so a caller looping over months can carry the row forward without a
    round trip per month — apps/api runs in Singapore and Postgres is in Mumbai.
    """
    if asset["is_disposed"]:
        raise HTTPException(status_code=422, detail="Cannot depreciate a disposed asset")

    posted_month = _month_label(asset.get("depreciation_posted_through"))
    if posted_month and posted_month >= period:
        raise HTTPException(status_code=409, detail=f"Depreciation already posted through {posted_month}")

    # A month may not be SKIPPED. Posting Apr–Aug and then Oct used to charge
    # one month for October and move posted-through with it; September was then
    # permanently unreachable, because the check above only ever compares
    # against the furthest month reached. The year was short one month's
    # depreciation and nothing said so.
    #
    # REFUSE rather than post the gap: each month is its own journal needing
    # its own CA review (and the purchase month is pro-rated, and a month in a
    # new FY re-bases the annual charge), so quietly posting three entries
    # behind one click is exactly the unprompted acting this codebase does not
    # do. Naming the months makes the fix one click each, in order.
    #
    # The range runner does not get round this. It walks months IN ORDER from
    # the earliest unposted one, so it never presents this function with a gap —
    # the CA asked for a RANGE, by name, and every month in it is posted and
    # reported. That is a different act from silently filling a hole behind a
    # click that asked for one month.
    if posted_month:
        missing = _months_missing_before(posted_month, period)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Depreciation for {', '.join(missing)} has not been posted — post "
                    f"{missing[0]} first. Skipping a month would leave it unpostable: "
                    f"this asset is posted through {posted_month} and that only moves forward."
                ),
            )

    # task #232 audit finding: nothing stopped a CA from posting depreciation
    # for a period before the asset was even purchased.
    purchase_month = asset["purchase_date"][:7]
    if period < purchase_month:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot post depreciation for {period} — asset was purchased in {purchase_month}.",
        )

    # task #232 audit finding: fixed_assets.py never checked the FY lock.
    entry_date = _period_end_date(period)
    period_validation_service.validate_posting_date(firm_id, entry_date)
    # And the CLIENT's own lock — a filed GSTR-3B or a finalised year covers
    # exactly the period-end date a depreciation entry carries. This was on the
    # acknowledged debt list; the range runner below is what makes it worth
    # paying now, because it posts twelve months in one call rather than one
    # behind a click a CA has just looked at. The refusal names the action that
    # would work, and the runner reports it per asset rather than swallowing it.
    period_lock_service.assert_open(db, firm_id, asset.get("client_id"), entry_date)

    # Fixed annual figure for THIS financial year (see
    # _annual_depreciation_for_period's docstring for why it must be fixed
    # per-FY, not recomputed every month) — monthly = annual / 12.
    try:
        annual, fy, fy_start_accum = _annual_depreciation_for_period(asset, period)
    except ValueError as e:
        # No Schedule II basis and none recorded on the row — refuse with the
        # reason rather than charging a made-up rate to the ledger.
        raise HTTPException(status_code=422, detail=str(e))
    if annual <= 0:
        return {"message": "Asset fully depreciated", "depreciation_paise": 0,
                "asset_id": asset["id"], "period": period, "posted": False}

    monthly = math.floor(Decimal(annual) / Decimal(12))

    # Schedule II Note 3 / IT Act §32 180-day rule: pro-rate the asset's
    # purchase month by days actually held.
    if period == purchase_month:
        monthly = _prorate_purchase_month(monthly, asset["purchase_date"])

    if monthly <= 0:
        return {"message": "No depreciation to post for this period.",
                "depreciation_paise": 0, "asset_id": asset["id"], "period": period,
                "posted": False}

    # Post journal — CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    journal_id = _journal_svc.journal_for_depreciation(
        asset, monthly, period, firm_id, asset["client_id"]
    )

    # Update accumulated depreciation
    new_accum = asset.get("accumulated_depreciation_paise", 0) + monthly
    changed = {
        "accumulated_depreciation_paise": new_accum,
        "current_wdv_paise":             asset["purchase_cost_paise"] - new_accum,
        # fixed_assets.depreciation_posted_through is a DATE (migration 054),
        # not a month label. Writing the 'YYYY-MM' period into it is what
        # Postgres rejects as 22007 invalid_input_syntax — and it rejected the
        # WHOLE update, so the journal above landed on the ledger and the
        # register never moved: accumulated depreciation stayed at 0 and the
        # WDV stayed at cost for ever, while the posting kernel's dedupe on
        # (client_id, reference_no, entry_date) made every retry look like a
        # duplicate. The month END is the right date, and the same one the
        # entry itself carries: "posted through 30-04-2026" is exactly what
        # the column claims, and _month_label reads the month back out of it.
        "depreciation_posted_through":   entry_date,
        "depreciation_fy":               fy,
        "depreciation_fy_start_accum_paise": fy_start_accum,
    }
    db.table("fixed_assets").update(changed).eq("id", asset["id"]).eq("firm_id", firm_id).execute()
    # The caller's copy moves with the row, so a month-by-month loop reads the
    # opening accumulated depreciation each iteration without re-fetching.
    asset.update(changed)

    timeline_service.log(asset["client_id"], "accounting", "Depreciation Posted",
        f"{asset.get('asset_code')}: ₹{monthly//100:,} depreciation for {period}", "info")

    return {
        "asset_id":           asset["id"],
        "period":             period,
        "depreciation_paise": monthly,
        "journal_entry_id":   journal_id,
        "new_accumulated":    new_accum,
        "new_wdv":            asset["purchase_cost_paise"] - new_accum,
        "posted":             True,
    }


@router.post("/{asset_id}/depreciate")
def post_depreciation(
    asset_id: str,
    data: DepreciationIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """
    Post depreciation for a given period (month YYYY-MM; defaults to the
    current month). Computes depreciation and creates journal entry.
    Idempotent: checks depreciation_posted_through before posting.
    """
    period = data.period or ist_today().strftime("%Y-%m")
    if not _PERIOD_RE.match(period):
        raise HTTPException(status_code=422, detail="period must be in YYYY-MM format.")

    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "period": period, "depreciation_paise": 0})

    asset = _live_asset(db, asset_id, current_user["firm_id"])
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Row-addressed by asset_id with no client_id in the request, so the
    # mount-level guard never fires. Same IDOR family as the task #241 fix on
    # depreciation_schedule below, but a WRITE: this posts a depreciation
    # journal, so an unassigned caller could move another book's ledger.
    # Checked before every mutation, and reuses the 404 above so the response
    # is not an existence oracle.
    if not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail="Asset not found")

    out = _post_one_month(db, asset, period, current_user["firm_id"])
    out.pop("posted", None)
    return api_response(True, out)


#: How many months this endpoint will post in one call. A year of twelve months
#: across a 500-asset register is 6,000 journals, and `lib/api` aborts a request
#: at 45 seconds and deliberately never retries it. So the run is CHUNKED and
#: resumable: it stops at the cap, says how many months are left, and the screen
#: calls again — the same shape as the bank module's REDRAFT_CHUNK.
DEPRECIATION_RUN_CHUNK = 200


@router.post("/run-depreciation")
def run_depreciation(
    data: DepreciationRunIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """Post every unposted month in a range, for every live asset of a client.

    WHY THIS EXISTS (FA-04)

        `POST /{asset_id}/depreciate` charges exactly ONE month for ONE asset,
        and the only bulk path was a loop in the browser: one HTTP request per
        asset per month, with every error swallowed. A CA closing a year on a
        200-asset register made 2,400 requests and could not tell which of them
        had failed. There was no annual mode, no range, and no job.

    WHY IT IS NOT THE THING THE SINGLE ENDPOINT REFUSES

        That endpoint refuses to fill a GAP — post April to August, then ask for
        October, and September would be silently skipped and then unpostable.
        The refusal is right, and this does not get round it: the run walks
        months IN ORDER from each asset's earliest unposted one, so it never
        creates a gap, and it reports every month it posted. A CA who names a
        range is asking for those months; a CA who clicks "October" is not
        asking for September.

    WHAT IT REPORTS

        Per asset: the months posted, and — if it stopped — the month it stopped
        at and the reason in the words the single endpoint would have used. One
        asset with no statutory rate, or one locked period, must not stop the
        other ninety-nine, and must not vanish either. `remaining_months` is what
        a "Run again" control needs.
    """
    for label, value in (("from_period", data.from_period), ("to_period", data.to_period)):
        if not _PERIOD_RE.match(value):
            raise HTTPException(status_code=422, detail=f"{label} must be in YYYY-MM format.")
    if data.to_period < data.from_period:
        raise HTTPException(status_code=422,
                            detail="to_period must not be before from_period.")

    assert_client_access(current_user, data.client_id)
    db = _db()
    if not db:
        return api_response(True, {"client_id": data.client_id, "assets": [],
                                   "months_posted": 0, "depreciation_paise": 0,
                                   "remaining_months": 0})

    assets = (db.table("fixed_assets").select("*")
              .eq("firm_id", current_user["firm_id"]).eq("client_id", data.client_id)
              .eq("is_disposed", False).is_("deleted_at", "null")
              .order("asset_code").execute().data or [])

    results, months_posted, total_paise, remaining = [], 0, 0, 0
    for asset in assets:
        posted_here, stopped_at, reason = [], None, None
        for period in _months_in_range(data.from_period, data.to_period):
            if months_posted >= DEPRECIATION_RUN_CHUNK:
                remaining += 1
                continue
            posted_month = _month_label(asset.get("depreciation_posted_through"))
            if posted_month and posted_month >= period:
                continue                      # already charged; not a failure
            if period < asset["purchase_date"][:7]:
                continue                      # before the asset existed
            try:
                out = _post_one_month(db, asset, period, current_user["firm_id"])
            except HTTPException as e:
                # Stop THIS asset at the first refusal and keep its reason. Going
                # on would either skip a month (which the next call then refuses
                # for ever) or repeat the same refusal eleven times.
                stopped_at, reason = period, str(e.detail)
                break
            if out.get("posted"):
                posted_here.append({"period": period,
                                    "depreciation_paise": out["depreciation_paise"],
                                    "journal_entry_id": out.get("journal_entry_id")})
                months_posted += 1
                total_paise += out["depreciation_paise"]
            elif out.get("message"):
                # Fully depreciated, or a pro-rated purchase month that rounds to
                # nothing. Not an error, and not silence either.
                stopped_at, reason = period, out["message"]
                break
        results.append({
            "asset_id": asset["id"], "asset_code": asset.get("asset_code"),
            "asset_name": asset.get("asset_name"),
            "months_posted": len(posted_here), "months": posted_here,
            "depreciation_paise": sum(m["depreciation_paise"] for m in posted_here),
            "stopped_at": stopped_at, "reason": reason,
        })

    return api_response(True, {
        "client_id": data.client_id,
        "from_period": data.from_period, "to_period": data.to_period,
        "assets": results,
        "assets_considered": len(assets),
        "months_posted": months_posted,
        "depreciation_paise": total_paise,
        # Non-zero only when the chunk cap was hit. The run is resumable: call
        # again with the same range and it picks up where it stopped, because
        # every asset's own posted-through says where that is.
        "remaining_months": remaining,
        "chunk_limit": DEPRECIATION_RUN_CHUNK,
    })


@router.patch("/{asset_id}/dispose")
def dispose_asset(
    asset_id: str,
    data: DisposalIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """
    Dispose of an asset (sale, scrapped, written off).
    Creates disposal journal with gain/loss on disposal.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    Atomicity (C1 fix): the asset is claimed FIRST via a conditional update
    (WHERE is_disposed = false) before any journal is posted. A second/retry
    request that loses the race — or arrives after a prior successful
    disposal — affects zero rows and 409s before ever touching the ledger,
    so a duplicate disposal journal can never be created. As of task #103,
    `journal_for_asset_disposal` re-raises unexpected errors instead of
    swallowing them into a None return (a None return can now only mean
    `_USE_MOCK`); either a raised exception or a None journal_id rolls the
    claim back so the asset is never left "disposed" with no corresponding
    journal.
    """
    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "disposed": True})

    asset = _live_asset(db, asset_id, current_user["firm_id"])
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Same row-addressed gap as post_depreciation, and likewise a WRITE: this
    # posts a disposal journal with gain/loss. Checked before the conditional
    # claim described above, so an unassigned caller never reaches the ledger.
    if not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail="Asset not found")

    disposal_type   = data.disposal_type
    sale_proceeds   = data.sale_proceeds_paise
    disposal_date   = data.disposal_date or ist_today().isoformat()
    disposal_notes  = data.notes if data.notes is not None else asset.get("notes")

    # task #232 audit finding: fixed_assets.py never checked the FY lock —
    # checked before any mutation, same as the purchase/depreciation paths.
    period_validation_service.validate_posting_date(current_user["firm_id"], disposal_date)

    # FA-08: the gain or loss is computed from what has been POSTED, so every
    # unposted month is a WDV that is too high and a gain that is too small.
    # Refused, and named, exactly as post_depreciation refuses a skipped month —
    # posting them here would be four journals behind one click, in a
    # transaction the CA thinks is about a sale.
    outstanding = _depreciation_months_outstanding(asset, disposal_date)
    if outstanding:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Depreciation for {', '.join(outstanding)} has not been posted. "
                f"The gain or loss on disposal is computed from the written-down "
                f"value, so posting it now would book a WDV {len(outstanding)} "
                f"month{'s' if len(outstanding) > 1 else ''} too high. Post "
                f"{outstanding[0]} first."
            ),
        )

    # Capture pre-disposal values for rollback before any mutation.
    prior_disposal_date  = asset.get("disposal_date")
    prior_disposal_value = asset.get("disposal_value_paise")
    prior_notes           = asset.get("notes")

    def _rollback_claim():
        db.table("fixed_assets").update({
            "is_disposed":          False,
            "disposal_date":        prior_disposal_date,
            "disposal_value_paise": prior_disposal_value,
            "notes":                prior_notes,
        }).eq("id", asset_id).eq("firm_id", current_user["firm_id"]).execute()

    # Claim the disposal atomically: only succeeds if still not disposed.
    claim = db.table("fixed_assets").update({
        "is_disposed":          True,
        "disposal_date":        disposal_date,
        "disposal_value_paise": sale_proceeds,
        "notes":                disposal_notes,
    }).eq("id", asset_id).eq("firm_id", current_user["firm_id"]).eq("is_disposed", False).execute()
    if not claim.data:
        raise HTTPException(status_code=409, detail="Asset already disposed")

    asset["disposal_date"] = disposal_date

    try:
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        journal_id = _journal_svc.journal_for_asset_disposal(asset, sale_proceeds, current_user["firm_id"], asset["client_id"])
    except Exception:
        # Compensate: the claim above must never be left standing without a
        # journal behind it — undo it so a retry can cleanly start over.
        _rollback_claim()
        raise
    if journal_id is None:
        _rollback_claim()
        raise HTTPException(status_code=502, detail="Failed to post the disposal journal. The asset has not been disposed — please retry.")

    wdv = asset["purchase_cost_paise"] - asset.get("accumulated_depreciation_paise", 0)
    gain_loss = sale_proceeds - wdv

    # The days between the last whole month charged and the disposal date are
    # NOT charged — the engine posts whole months only, the purchase month
    # being the single pro-rated exception (Schedule II Note 3). Reported
    # rather than silently absorbed into the gain, because a figure nobody is
    # told about is how FA-08 survived this long: the WDV looked right.
    #
    # Nothing is left uncharged only when the disposal falls on the last day of
    # a month that has itself been depreciated. The refusal above guarantees
    # every EARLIER whole month is charged, so this is the whole of the gap.
    _posted_month = _month_label(asset.get("depreciation_posted_through")) or ""
    _dy, _dm = int(str(disposal_date)[:4]), int(str(disposal_date)[5:7])
    _last_day_of_disposal_month = calendar.monthrange(_dy, _dm)[1]
    part_month_uncharged = not (
        _posted_month >= str(disposal_date)[:7]
        and int(str(disposal_date)[8:10]) == _last_day_of_disposal_month
    )

    timeline_service.log(asset["client_id"], "accounting", "Asset Disposed",
        f"{asset.get('asset_code')}: {disposal_type} — ₹{sale_proceeds//100:,} proceeds, "
        f"{'gain' if gain_loss >= 0 else 'loss'} ₹{abs(gain_loss)//100:,}", "warning")

    return api_response(True, {
        "asset_id":        asset_id,
        "disposal_type":   disposal_type,
        "sale_proceeds":   sale_proceeds,
        "wdv_at_disposal": wdv,
        "gain_loss_paise": gain_loss,
        "journal_entry_id": journal_id,
        # Whole months are charged; the days between the last month end and the
        # disposal date are not. Stated so the CA can see the figure is a whole
        # month short rather than discovering it in the accounts.
        "part_month_depreciation_not_charged": part_month_uncharged,
    })


# ─────────────────────── FA-10: correcting the register ──────────────────────
#
# Until this, an asset was final the moment it was saved. A CA who typed
# ₹15,00,000 for ₹1,50,000 had three options and all three were wrong: dispose
# at nil proceeds (which books a fabricated loss, and first demands every
# unposted month be depreciated); reverse the journal through the generic
# accounting endpoint (which leaves the register claiming a cost the ledger no
# longer carries, and register-integrity does not notice because
# journal_entry_id is still populated); or a database console.
#
# The shape here is the one migrations 266/275/276 established for journals:
# append-only on the ledger, a correction while the period is OPEN, and the
# audit log — not the row — is what is immutable.


def _reverse_tolerating_already_reversed(db, firm_id: str, entry_id: str,
                                         reversal_date: str, narration: str,
                                         actor_id: Optional[str]) -> Optional[str]:
    """Reverse, treating "already reversed" as work that is done.

    A correction that failed partway is completed by RETRYING it, and on the
    retry the reversal is already on the ledger. Surfacing reverse_entry's 409
    there would report a failure for the one step that had succeeded.
    """
    try:
        return _journal_svc.reverse_entry(
            db, firm_id, entry_id, reversal_date,
            narration=narration, created_by=actor_id)
    except HTTPException as exc:
        if exc.status_code == 409 and "already been reversed" in str(exc.detail):
            return None
        raise


def _next_unposted_month(asset: dict) -> Optional[str]:
    """The month a further posting would charge, or None if none is posted yet."""
    posted = _month_label(asset.get("depreciation_posted_through"))
    if not posted:
        return None
    y, m = int(posted[:4]), int(posted[5:7])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def _previous_month(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


@router.patch("/{asset_id}")
def correct_asset(
    asset_id: str,
    data: FixedAssetUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """Correct an asset already in the register.

    exclude_unset, NOT exclude_none: clearing `location` to null is a real
    edit, and exclude_none would drop it silently — PAY-12's mechanism.
    """
    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "corrected": []})

    asset = _live_asset(db, asset_id, current_user["firm_id"])
    # Row-addressed by asset_id with no client_id in the request, so the
    # mount-level guard never fires — the same IDOR family as post_depreciation
    # and dispose_asset, and likewise a WRITE. One message for both branches so
    # the response is not an oracle for which asset ids exist.
    if not asset or not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail="Asset not found")
    firm_id, client_id = current_user["firm_id"], asset["client_id"]

    changes = data.model_dump(exclude_unset=True)
    reason = (changes.pop("reason", None) or "").strip()
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to correct — no field was sent.")

    tier_a = set(changes) & _TIER_A_FIELDS
    tier_b = set(changes) & _TIER_B_FIELDS
    tier_c = set(changes) & _TIER_C_FIELDS

    # The period the asset SITS in has to be open before anything moves, and
    # where the date itself moves, so does the period it moves INTO. Both, the
    # way edit_posted_journal checks both (migration 266). This is
    # period_lock_service and not period_validation_service on purpose: the
    # latter is firm-FY only and takes no client_id, so it would happily
    # correct an asset inside a period whose GSTR-3B has been filed.
    if tier_b or tier_c:
        period_lock_service.assert_open(db, firm_id, client_id, asset.get("purchase_date"))
        if changes.get("purchase_date"):
            period_lock_service.assert_open(db, firm_id, client_id, changes["purchase_date"])

    if asset.get("is_disposed") and (tier_b or tier_c):
        raise HTTPException(
            status_code=422,
            detail=("This asset has been disposed, so its cost and depreciation "
                    "basis are settled — the gain or loss was computed from them. "
                    "Its name, location and notes can still be corrected."))

    posted_month = _month_label(asset.get("depreciation_posted_through"))

    # TIER B on a depreciated asset. Every posted month was computed from the
    # cost being corrected, so correcting it silently would leave the ledger
    # carrying charges no basis in the register supports. Named rather than
    # refused blankly, in the shape post_depreciation uses for a skipped month.
    if tier_b and posted_month:
        raise HTTPException(
            status_code=422,
            detail=(f"Depreciation is posted through {posted_month} on the current "
                    f"cost. Reverse it a month at a time (most recent first) before "
                    f"correcting {', '.join(sorted(tier_b))} — each posted month was "
                    f"computed from the figure being changed."))

    # TIER C on a financial year that already carries postings. Schedule II
    # charges ONE annual figure divided by twelve (see
    # _annual_depreciation_for_period), so a revised life or rate part-way
    # through a year would give the remaining months a different monthly charge
    # from the ones already posted — the fixed-annual-charge rule broken with
    # nothing on the screen saying so. AS 10 makes the revision prospective;
    # the clean boundary this engine has is the financial year.
    if tier_c and posted_month:
        next_month = _next_unposted_month(asset)
        if asset.get("depreciation_fy") == get_fy_for_date(f"{next_month}-01"):
            raise HTTPException(
                status_code=422,
                detail=(f"{asset.get('depreciation_fy')} already carries depreciation "
                        f"posted through {posted_month} on the current basis. A revised "
                        f"life, rate, method or salvage value applies prospectively "
                        f"(Schedule II Part C Note 7), and this engine holds one annual "
                        f"charge per financial year — so change it from the start of the "
                        f"next year, or reverse {posted_month} back to the start of "
                        f"{asset.get('depreciation_fy')} first."))

    update: dict = {k: v for k, v in changes.items() if k in _TIER_A_FIELDS | _TIER_C_FIELDS}
    if "depreciation_method" in update and update["depreciation_method"] is not None:
        update["depreciation_method"] = getattr(
            update["depreciation_method"], "value", update["depreciation_method"])

    journal_id = asset.get("journal_entry_id")
    if tier_b:
        # The stored purchase_cost_paise is the CAPITALISED figure —
        # capitalised_cost_paise() already folded §17(5)-blocked tax into it and
        # the raw cost is stored nowhere. Re-capitalising the stored value would
        # add that tax a second time and over-depreciate for the asset's life,
        # so a change to the tax facts must arrive WITH the cost they apply to.
        tax_fields = {"igst_paise", "cgst_paise", "sgst_paise", "itc_eligible"}
        if (set(changes) & tax_fields) and "purchase_cost_paise" not in changes:
            raise HTTPException(
                status_code=422,
                detail=("Send purchase_cost_paise with any change to the tax on the "
                        "acquisition. The register holds the cost AFTER blocked tax "
                        "was capitalised into it (CGST Act §17(5)) and does not keep "
                        "the figure as typed, so the two have to be given together."))

        merged = dict(asset)
        merged.update({k: v for k, v in changes.items() if k in _TIER_B_FIELDS})
        merged.update(update)
        if "purchase_cost_paise" in changes:
            merged["purchase_cost_paise"] = capitalised_cost_paise(
                int(changes["purchase_cost_paise"]),
                int(merged.get("igst_paise") or 0), int(merged.get("cgst_paise") or 0),
                int(merged.get("sgst_paise") or 0), merged.get("itc_eligible"))

        revision = int(asset.get("corrections_count") or 0) + 1

        # Reverse first, then post the correction, then move the row. If the
        # post fails the acquisition is reversed and the register is unchanged
        # — recoverable by sending the same correction again, which is what the
        # 502 below says, because the reversal is then already done.
        if journal_id:
            _reverse_tolerating_already_reversed(
                db, firm_id, journal_id, asset["purchase_date"],
                f"Correction of asset {asset.get('asset_code')}" + (f": {reason}" if reason else ""),
                current_user.get("id"))

        try:
            new_journal = _journal_svc.journal_for_asset_acquisition(
                merged, firm_id, client_id, reference_suffix=f"-R{revision}")
        except Exception:
            raise
        if journal_id and new_journal is None:
            raise HTTPException(
                status_code=502,
                detail=("The acquisition journal was reversed but the corrected one "
                        "could not be posted. The asset is unchanged — send the same "
                        "correction again to complete it."))

        update.update({k: v for k, v in changes.items() if k in _TIER_B_FIELDS})
        update["purchase_cost_paise"] = merged["purchase_cost_paise"]
        update["current_wdv_paise"] = (
            merged["purchase_cost_paise"] - int(asset.get("accumulated_depreciation_paise") or 0))
        update["corrections_count"] = revision
        if new_journal:
            update["journal_entry_id"] = new_journal

    # Written BEFORE the mutation and unswallowed by design (audit_capture's
    # triggers skip service-role writes — migration 111).
    log_event(
        firm_id, "fixed_asset", asset_id, "update",
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        old_data={k: asset.get(k) for k in sorted(set(update) | {"asset_code"})},
        new_data=update,
        metadata={"reason": reason or None,
                  "tiers": sorted({t for t, present in
                                   (("A", tier_a), ("B", tier_b), ("C", tier_c)) if present})},
    )

    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.table("fixed_assets").update(update).eq("id", asset_id).eq("firm_id", firm_id).execute()

    timeline_service.log(client_id, "accounting", "Asset Corrected",
        f"{asset.get('asset_code')}: {', '.join(sorted(changes))}"
        + (f" — {reason}" if reason else ""), "info")

    return api_response(True, {
        "asset_id": asset_id,
        "corrected": sorted(changes),
        "journal_entry_id": update.get("journal_entry_id", journal_id),
        "acquisition_reposted": bool(tier_b),
    })


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """Remove an asset that should never have been created.

    SOFT, and narrow: only where nothing has been posted against it beyond the
    acquisition. Anything with a depreciation month or a disposal behind it is
    a history, not a mistake, and is corrected by reversing those first.

    The row stays, and so does its asset_code, because FA-ACQ-{code} is the
    acquisition journal's reference and the kernel dedupes on (client_id,
    reference_no, entry_date) — hand the code to the next asset and its
    acquisition lands on this one's entry.
    """
    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "deleted": True})

    asset = _live_asset(db, asset_id, current_user["firm_id"])
    # Row-addressed by asset_id with no client_id in the request, so the
    # mount-level guard never fires — the same IDOR family as post_depreciation
    # and dispose_asset, and likewise a WRITE. One message for both branches so
    # the response is not an oracle for which asset ids exist.
    if not asset or not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail="Asset not found")
    firm_id, client_id = current_user["firm_id"], asset["client_id"]

    posted_month = _month_label(asset.get("depreciation_posted_through"))
    if posted_month:
        raise HTTPException(
            status_code=422,
            detail=(f"Depreciation is posted through {posted_month} on this asset. "
                    f"Reverse it a month at a time (most recent first) before deleting "
                    f"— a deleted asset would leave those charges in the P&L with "
                    f"nothing in the register behind them."))
    if asset.get("is_disposed"):
        raise HTTPException(
            status_code=422,
            detail="This asset has been disposed. A disposal is a transaction, not a "
                   "mistake to remove — reverse the disposal journal instead.")

    period_lock_service.assert_open(db, firm_id, client_id, asset.get("purchase_date"))

    if asset.get("journal_entry_id"):
        _reverse_tolerating_already_reversed(
            db, firm_id, asset["journal_entry_id"], asset["purchase_date"],
            f"Asset {asset.get('asset_code')} deleted — acquisition reversed",
            current_user.get("id"))

    # The WHOLE row, in the same request and unswallowed — migration 276's rule
    # for a journal deletion, and for the same reason: the log is what is
    # immutable, not the row.
    log_event(
        firm_id, "fixed_asset", asset_id, "delete",
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        old_data=dict(asset),
    )

    db.table("fixed_assets").update({
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "deleted_by": current_user.get("id"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", asset_id).eq("firm_id", firm_id).execute()

    timeline_service.log(client_id, "accounting", "Asset Deleted",
        f"{asset.get('asset_code')}: {asset.get('asset_name')} — acquisition reversed",
        "warning")

    return api_response(True, {"asset_id": asset_id, "deleted": True,
                               "acquisition_reversed": bool(asset.get("journal_entry_id"))})


@router.post("/{asset_id}/depreciation/{period}/reverse")
def reverse_depreciation(
    asset_id: str,
    period: str,
    current_user: dict = Depends(rbac("accounting", "write"))
):
    """Undo the LAST posted month of depreciation.

    Last only, so the register can only unwind in the order it was built and
    can never be left with a hole: post_depreciation refuses any month at or
    below depreciation_posted_through, and that column otherwise only moves
    forward, so a hole in the middle would be permanently uncharged.

    The reversal is dated the SAME day as what it reverses. Reversing April in
    November would credit November's P&L and leave April overstated — right
    when April is closed, wrong when it is open, and this endpoint refuses
    unless it is open.
    """
    if not _PERIOD_RE.match(period or ""):
        raise HTTPException(status_code=422, detail="period must be in YYYY-MM format.")

    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "period": period, "reversed": True})

    asset = _live_asset(db, asset_id, current_user["firm_id"])
    # Row-addressed by asset_id with no client_id in the request, so the
    # mount-level guard never fires — the same IDOR family as post_depreciation
    # and dispose_asset, and likewise a WRITE. One message for both branches so
    # the response is not an oracle for which asset ids exist.
    if not asset or not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail="Asset not found")
    firm_id, client_id = current_user["firm_id"], asset["client_id"]

    posted_month = _month_label(asset.get("depreciation_posted_through"))
    if not posted_month:
        raise HTTPException(status_code=422, detail="No depreciation has been posted on this asset.")
    if period != posted_month:
        raise HTTPException(
            status_code=422,
            detail=(f"{posted_month} is the last month posted — reverse that first. "
                    f"Months come off in the order they went on, because a month "
                    f"below the posted-through mark can never be posted again."))
    if asset.get("is_disposed"):
        raise HTTPException(
            status_code=422,
            detail="This asset has been disposed and the gain or loss was computed "
                   "from its written-down value. Reverse the disposal first.")

    entry_date = _period_end_date(period)
    period_lock_service.assert_open(db, firm_id, client_id, entry_date)

    reference = f"FA-DEPN-{asset.get('asset_code') or asset['id'][:8]}-{period}"
    entry = ((db.table("journal_entries").select("id, entry_date")
              .eq("firm_id", firm_id).eq("client_id", client_id)
              .eq("reference_no", reference).eq("is_reversed", False)
              .limit(1).execute().data) or [None])[0]
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=(f"No live depreciation journal found for {period} ({reference}). "
                    f"It may already have been reversed."))

    lines = (db.table("journal_lines").select("debit_paise")
             .eq("journal_entry_id", entry["id"]).execute().data) or []
    charge = max([int(l.get("debit_paise") or 0) for l in lines] or [0])
    if charge <= 0:
        raise HTTPException(status_code=422,
                            detail=f"The {period} depreciation journal carries no charge to reverse.")

    _reverse_tolerating_already_reversed(
        db, firm_id, entry["id"], entry.get("entry_date") or entry_date,
        f"Reversal of depreciation on {asset.get('asset_code')} for {period}",
        current_user.get("id"))

    # Roll the register back to where it stood before that month. The previous
    # month is only the new mark if it was actually POSTED — the first posting
    # may legitimately start at any month, so a purchase in April first charged
    # in August must go back to nothing, not to July.
    previous = _previous_month(period)
    prev_ref = f"FA-DEPN-{asset.get('asset_code') or asset['id'][:8]}-{previous}"
    prev_entry = ((db.table("journal_entries").select("id")
                   .eq("firm_id", firm_id).eq("client_id", client_id)
                   .eq("reference_no", prev_ref).eq("is_reversed", False)
                   .limit(1).execute().data) or [None])[0]
    new_posted_through = _period_end_date(previous) if prev_entry else None

    new_accum = max(0, int(asset.get("accumulated_depreciation_paise") or 0) - charge)
    update = {
        "accumulated_depreciation_paise": new_accum,
        "current_wdv_paise": int(asset["purchase_cost_paise"]) - new_accum,
        "depreciation_posted_through": new_posted_through,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # The FY's fixed annual charge is cached on the row. Once the year holds no
    # posted month, the cache is a claim about a year that has none — clear it
    # so the next posting re-bases from the year's real opening WDV.
    if new_posted_through is None or get_fy_for_date(new_posted_through) != asset.get("depreciation_fy"):
        update["depreciation_fy"] = None
        update["depreciation_fy_start_accum_paise"] = None

    log_event(
        firm_id, "fixed_asset", asset_id, "update",
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        old_data={"period": period, "reference_no": reference,
                  "accumulated_depreciation_paise": asset.get("accumulated_depreciation_paise"),
                  "depreciation_posted_through": asset.get("depreciation_posted_through"),
                  "depreciation_fy": asset.get("depreciation_fy")},
        new_data=update,
        metadata={"action": "depreciation_reversed", "charge_paise": charge},
    )

    db.table("fixed_assets").update(update).eq("id", asset_id).eq("firm_id", firm_id).execute()

    timeline_service.log(client_id, "accounting", "Depreciation Reversed",
        f"{asset.get('asset_code')}: ₹{charge//100:,} for {period} reversed", "warning")

    return api_response(True, {
        "asset_id": asset_id,
        "period": period,
        "reversed_paise": charge,
        "accumulated_depreciation_paise": new_accum,
        "depreciation_posted_through": new_posted_through,
    })


@router.get("/depreciation-schedule")
def depreciation_schedule(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    """Return projected depreciation schedule for all active assets."""
    # task #241 closed the cross-FIRM half of this IDOR (below); this closes
    # the within-firm half — firm_id alone still let an unassigned member read
    # another staff member's client register.
    assert_client_access(current_user, client_id)
    db = _db()
    if not db:
        return api_response(True, [])

    # task #241 fix: this used to filter only by client_id, with no firm_id
    # check at all -- any authenticated user in ANY firm could read another
    # firm's fixed-asset register by supplying its client_id (IDOR). Every
    # other endpoint in this file already scopes by firm_id (list_assets,
    # create_asset, post_depreciation, dispose_asset) -- this was the one
    # gap.
    assets = (
        db.table("fixed_assets").select("*")
        .eq("firm_id", current_user["firm_id"])
        .eq("client_id", client_id)
        .eq("is_disposed", False)
        .is_("deleted_at", "null")
        .execute().data or []
    )
    # Projected as of the CURRENT financial year — reuses each asset's own
    # cached depreciation_fy/depreciation_fy_start_accum_paise (task #232) so
    # the figure shown here matches what the next actual posting will charge,
    # instead of recomputing from the live (already-reduced) WDV every call.
    today_period = ist_today().strftime("%Y-%m")
    schedule = []
    for a in assets:
        # An asset with no statutory basis for its charge reports itself as a
        # named gap instead of taking the whole schedule down with it — the
        # same shape payroll uses for an unmodelled state's professional tax.
        # A zero with a reason beside it is not the same number as a zero.
        statutory_gap = None
        try:
            annual, _fy, _fy_start = _annual_depreciation_for_period(a, today_period)
        except ValueError as e:
            annual, statutory_gap = 0, str(e)
        wdv    = a["purchase_cost_paise"] - a.get("accumulated_depreciation_paise", 0)
        schedule.append({
            "asset_id":               a["id"],
            "asset_code":             a.get("asset_code"),
            "asset_name":             a["asset_name"],
            "asset_category":         a["asset_category"],
            "purchase_cost_paise":    a["purchase_cost_paise"],
            "accumulated_paise":      a.get("accumulated_depreciation_paise", 0),
            "current_wdv_paise":      wdv,
            "annual_depreciation_paise": annual,
            "monthly_depreciation_paise": math.floor(Decimal(annual) / Decimal(12)),
            "depreciation_method":    a["depreciation_method"],
            "salvage_value_paise":    a.get("salvage_value_paise", 0),
            # Both bases travel with the row so the screen can SHOW what it is
            # charging on without recomputing anything (CLAUDE.md: zero
            # business logic in the frontend).
            "wdv_rate_percent":       a.get("wdv_rate_percent"),
            "useful_life_years":      a.get("useful_life_years"),
            "depreciation_posted_through": _month_label(a.get("depreciation_posted_through")),
            "statutory_gap":          statutory_gap,
        })
    return api_response(True, schedule)


@router.get("/categories")
def asset_categories(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read"))
):
    """Companies Act 2013 Schedule II Part C, as the create form needs it.

    The form used to carry its own copy of this table, which is how the two
    drifted: the frontend's literal and the backend's were identical wrong
    numbers, and neither said where they came from. There is one table now
    (_SCHEDULE_II_PART_C) and this is how it reaches the browser.

    The Schedule itself is statutory and identical for every client — the
    client_id is here because this list is only ever asked for from inside a
    client's fixed-asset workspace, and every endpoint in this router consults
    the caller's client scope rather than firm_id alone.
    """
    assert_client_access(current_user, client_id)
    return api_response(True, [
        {
            "category":       category,
            "depreciable":    category not in _NOT_DEPRECIABLE,
            "residual_value_cap_percent": float(SCHEDULE_II_RESIDUAL_FRACTION * 100),
            "classes": [
                {
                    "label":             c["label"],
                    "useful_life_years": c["useful_life_years"],
                    # NUMERIC(5,2) on the way back in; float only at the wire.
                    "wdv_rate_percent":  None if c["wdv_rate_percent"] is None else float(c["wdv_rate_percent"]),
                }
                for c in classes
            ],
        }
        for category, classes in SCHEDULE_II_CATEGORIES.items()
    ])


@router.get("/register-integrity")
def register_integrity(
    client_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Where the fixed-asset register and the general ledger disagree (FA-07).

    THE THREE WAYS THEY COME APART, and each is silent today:

      * AN ASSET WITH NO ACQUISITION JOURNAL. The register says the client owns
        a machine and no entry ever put it on the balance sheet. It arises when
        journal posting failed after the row was inserted — the router updates
        `journal_entry_id` in a SECOND statement, so a failure between them
        leaves exactly this.
      * A BILL CAPITALISED TWICE. Migration 343's unique index stops it now, but
        rows created before it are unprotected, and the same bill's cost then
        sits in Fixed Assets twice while its payable is recorded once.
      * AN ASSET FROM A BILL WITH NO BILL. `acquisition_mode = 'from_bill'`
        means the entry only RECLASSIFIED cost out of purchases; if the bill has
        since been deleted, nothing supports the asset.

    This REPORTS. It repairs nothing and posts nothing: every remedy is a
    judgement — repost, delete a duplicate, re-link a bill — and which one is
    right depends on facts the ledger does not hold.
    """
    db = _db()
    if not db:
        return api_response(True, {"checked": 0, "findings": []})
    firm_id = current_user["firm_id"]
    assert_client_access(current_user, client_id)

    rows = _paginate_all(lambda: db.table("fixed_assets")
                         .select("id, asset_code, asset_name, purchase_cost_paise, "
                                 "journal_entry_id, acquisition_mode, purchase_bill_id, "
                                 "is_disposed")
                         .eq("firm_id", firm_id).eq("client_id", client_id)
                         .is_("deleted_at", "null"))

    findings: list[dict] = []
    by_bill: dict[str, list[dict]] = {}
    for a in rows:
        if not a.get("journal_entry_id"):
            findings.append({
                "kind": "no_acquisition_journal",
                "asset_code": a.get("asset_code"),
                "asset_name": a.get("asset_name"),
                "amount_paise": int(a.get("purchase_cost_paise") or 0),
                "what_it_means": (
                    "This asset is in the register and no journal entry ever put "
                    "it on the balance sheet."),
            })
        if a.get("purchase_bill_id"):
            by_bill.setdefault(a["purchase_bill_id"], []).append(a)

    for bill_id, assets in by_bill.items():
        if len(assets) > 1:
            findings.append({
                "kind": "bill_capitalised_more_than_once",
                "purchase_bill_id": bill_id,
                "asset_codes": [a.get("asset_code") for a in assets],
                "amount_paise": sum(int(a.get("purchase_cost_paise") or 0) for a in assets),
                "what_it_means": (
                    "One purchase bill is capitalised as several assets, so its "
                    "cost is in Fixed Assets more than once."),
            })

    bill_ids = sorted(by_bill)
    live: set[str] = set()
    for i in range(0, len(bill_ids), 200):
        got = (db.table("purchase_bills").select("id")
               .eq("firm_id", firm_id).in_("id", bill_ids[i:i + 200])
               .execute().data) or []
        live.update(str(b["id"]) for b in got)
    for bill_id, assets in by_bill.items():
        if bill_id not in live:
            findings.append({
                "kind": "capitalised_from_a_bill_that_is_gone",
                "purchase_bill_id": bill_id,
                "asset_codes": [a.get("asset_code") for a in assets],
                "what_it_means": (
                    "The entry only moved cost out of purchases; with the bill "
                    "deleted, nothing supports the asset."),
            })

    return api_response(True, {
        "checked": len(rows),
        "findings": findings,
        # An empty list is an ANSWER, and the count is what makes it one — "no
        # findings" over nothing checked is not the same statement.
        "clean": not findings,
    })
