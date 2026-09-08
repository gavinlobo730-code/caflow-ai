"""
Fixed Assets router — Asset register, depreciation engine, disposal.

Depreciation methods:
- SL  (Straight Line Method): annual depreciation = (cost - salvage) / useful_life_years
- WDV (Written Down Value):   annual depreciation = WDV × wdv_rate_percent / 100

Companies Act 2013 Schedule II prescribes a useful LIFE per class of asset, not
a WDV percentage — see _SCHEDULE_II_PART_C below, which is the one table, and
the only source the create form's defaults come from.
"""
from core.ist_clock import month_end_date
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP
import calendar
import math
import re

from models.common import api_response
from models.accounting import FixedAssetIn, DepreciationIn, DisposalIn
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from services.timeline_service import timeline_service
from services.phase2_journal_service import Phase2JournalService
from services.period_validation_service import period_validation_service, get_fy_for_date

router = APIRouter(prefix="/api/fixed-assets", tags=["fixed_assets"])

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
    q = db.table("fixed_assets").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
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

    # Generate asset code
    client_id = data.client_id
    count_res = db.table("fixed_assets").select("id", count="exact").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).execute()
    count = (count_res.count or 0) + 1
    asset_code = f"FA-{count:04d}"

    row = db.table("fixed_assets").insert({
        "firm_id":                     current_user["firm_id"],
        "client_id":                   client_id,
        "asset_code":                  asset_code,
        "asset_name":                  data.asset_name,
        "asset_category":              data.asset_category,
        "purchase_date":               data.purchase_date,
        "purchase_cost_paise":         data.purchase_cost_paise,
        "salvage_value_paise":         data.salvage_value_paise,
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
        f"{asset_code}: {data.asset_name} added — ₹{data.purchase_cost_paise//100:,}", "info")

    return api_response(True, asset)


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
    period = data.period or datetime.now(timezone.utc).strftime("%Y-%m")
    if not _PERIOD_RE.match(period):
        raise HTTPException(status_code=422, detail="period must be in YYYY-MM format.")

    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "period": period, "depreciation_paise": 0})

    asset = db.table("fixed_assets").select("*").eq("id", asset_id).eq("firm_id", current_user["firm_id"]).single().execute().data
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
    if asset["is_disposed"]:
        raise HTTPException(status_code=422, detail="Cannot depreciate a disposed asset")

    # Check already posted
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
    period_validation_service.validate_posting_date(current_user["firm_id"], entry_date)

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
        return api_response(True, {"message": "Asset fully depreciated", "depreciation_paise": 0})

    monthly = math.floor(Decimal(annual) / Decimal(12))

    # Schedule II Note 3 / IT Act §32 180-day rule: pro-rate the asset's
    # purchase month by days actually held.
    if period == purchase_month:
        monthly = _prorate_purchase_month(monthly, asset["purchase_date"])

    if monthly <= 0:
        return api_response(True, {"message": "No depreciation to post for this period.", "depreciation_paise": 0})

    # Post journal — CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    journal_id = _journal_svc.journal_for_depreciation(
        asset, monthly, period, current_user["firm_id"], asset["client_id"]
    )

    # Update accumulated depreciation
    new_accum = asset.get("accumulated_depreciation_paise", 0) + monthly
    db.table("fixed_assets").update({
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
    }).eq("id", asset_id).eq("firm_id", current_user["firm_id"]).execute()

    timeline_service.log(asset["client_id"], "accounting", "Depreciation Posted",
        f"{asset.get('asset_code')}: ₹{monthly//100:,} depreciation for {period}", "info")

    return api_response(True, {
        "asset_id":           asset_id,
        "period":             period,
        "depreciation_paise": monthly,
        "journal_entry_id":   journal_id,
        "new_accumulated":    new_accum,
        "new_wdv":            asset["purchase_cost_paise"] - new_accum,
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

    asset = db.table("fixed_assets").select("*").eq("id", asset_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Same row-addressed gap as post_depreciation, and likewise a WRITE: this
    # posts a disposal journal with gain/loss. Checked before the conditional
    # claim described above, so an unassigned caller never reaches the ledger.
    if not can_access_client(current_user, asset.get("client_id")):
        raise HTTPException(status_code=404, detail="Asset not found")

    disposal_type   = data.disposal_type
    sale_proceeds   = data.sale_proceeds_paise
    disposal_date   = data.disposal_date or str(datetime.now(timezone.utc).date())
    disposal_notes  = data.notes if data.notes is not None else asset.get("notes")

    # task #232 audit finding: fixed_assets.py never checked the FY lock —
    # checked before any mutation, same as the purchase/depreciation paths.
    period_validation_service.validate_posting_date(current_user["firm_id"], disposal_date)

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
        .execute().data or []
    )
    # Projected as of the CURRENT financial year — reuses each asset's own
    # cached depreciation_fy/depreciation_fy_start_accum_paise (task #232) so
    # the figure shown here matches what the next actual posting will charge,
    # instead of recomputing from the live (already-reduced) WDV every call.
    today_period = datetime.now(timezone.utc).strftime("%Y-%m")
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
