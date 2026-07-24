"""
Fixed Assets router — Asset register, depreciation engine, disposal.

Depreciation methods:
- SL  (Straight Line Method): annual depreciation = (cost - salvage) / useful_life_years
- WDV (Written Down Value):   annual depreciation = WDV × wdv_rate_percent / 100

Companies Act 2013 Schedule II specifies WDV rates for various asset categories.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone, date
from decimal import Decimal
import calendar
import math
import re

from models.common import api_response
from models.accounting import FixedAssetIn, DepreciationIn, DisposalIn
from core.permissions import rbac
from services.timeline_service import timeline_service
from services.phase2_journal_service import Phase2JournalService
from services.period_validation_service import period_validation_service, get_fy_for_date

router = APIRouter(prefix="/api/fixed-assets", tags=["fixed_assets"])

_journal_svc = Phase2JournalService()

# Companies Act 2013 Schedule II — default WDV rates. task #232 audit finding:
# these keys used to be abbreviated ("Furniture", "Computer", "Vehicle",
# "Intangible", no "Office Equipment"/"Land" entry at all) and never matched
# the asset_category taxonomy actually used platform-wide — the create/edit
# form's CATEGORIES list (apps/web/.../fixed-assets/page.tsx) and the GL
# account mapping in services/phase2_journal_service.py's cat_map (already
# fixed for the same mismatch — see test_fixed_asset_gl_mapping.py). Whenever
# an asset was created without an explicit wdv_rate_percent, 4+ real
# categories silently fell through to the generic "Other" rate instead of
# their own. Values mirror the frontend's own WDV_RATES table exactly.
_DEFAULT_WDV_RATES = {
    "Plant & Machinery":       15.33,
    "Furniture & Fixtures":    10.00,
    "Computer & IT Equipment": 31.67,
    "Office Equipment":        13.91,
    "Vehicles":                25.89,
    "Building":                 5.00,
    "Land":                     0.00,
    "Intangibles":             25.00,
    "Other":                   15.33,
}

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
    """
    cost    = asset["purchase_cost_paise"]
    salvage = asset.get("salvage_value_paise", 0)
    method  = asset.get("depreciation_method", "WDV")
    accum   = asset.get("accumulated_depreciation_paise", 0)
    wdv_now = cost - accum

    if wdv_now <= salvage:
        return 0  # fully depreciated

    if method == "SL":
        life = asset.get("useful_life_years") or 5
        annual = math.floor(Decimal(cost - salvage) / Decimal(life))
    else:  # WDV
        rate_value = asset.get("wdv_rate_percent") or _DEFAULT_WDV_RATES.get(asset.get("asset_category", "Other"), _DEFAULT_WDV_RATES["Other"])
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
    validation and the journal's entry_date both key off this)."""
    year, month = int(period[:4]), int(period[5:7])
    last_day = calendar.monthrange(year, month)[1]
    return f"{period}-{last_day:02d}"


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

    cat = data.asset_category
    row = db.table("fixed_assets").insert({
        "firm_id":                     current_user["firm_id"],
        "client_id":                   client_id,
        "asset_code":                  asset_code,
        "asset_name":                  data.asset_name,
        "asset_category":              cat,
        "purchase_date":               data.purchase_date,
        "purchase_cost_paise":         data.purchase_cost_paise,
        "salvage_value_paise":         data.salvage_value_paise,
        "useful_life_years":           data.useful_life_years,
        "depreciation_method":         data.depreciation_method.value,
        "wdv_rate_percent":            data.wdv_rate_percent or _DEFAULT_WDV_RATES.get(cat, _DEFAULT_WDV_RATES["Other"]),
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
    if asset["is_disposed"]:
        raise HTTPException(status_code=422, detail="Cannot depreciate a disposed asset")

    # Check already posted
    if asset.get("depreciation_posted_through") and asset["depreciation_posted_through"] >= period:
        raise HTTPException(status_code=409, detail=f"Depreciation already posted through {asset['depreciation_posted_through']}")

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
    annual, fy, fy_start_accum = _annual_depreciation_for_period(asset, period)
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
        "depreciation_posted_through":   period,
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
        annual, _fy, _fy_start = _annual_depreciation_for_period(a, today_period)
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
        })
    return api_response(True, schedule)
