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
import math

from models.common import api_response
from models.accounting import FixedAssetIn, DepreciationIn, DisposalIn
from core.permissions import rbac
from services.timeline_service import timeline_service
from services.phase2_journal_service import Phase2JournalService

router = APIRouter(prefix="/api/fixed-assets", tags=["fixed_assets"])

_journal_svc = Phase2JournalService()

# Companies Act 2013 Schedule II — default WDV rates
_DEFAULT_WDV_RATES = {
    "Plant & Machinery": 13.91,
    "Furniture":         18.10,
    "Computer":          31.67,
    "Vehicle":           25.89,
    "Building":           5.00,
    "Intangible":        25.00,
    "Other":             13.91,
}


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _compute_annual_depreciation(asset: dict) -> int:
    """
    Compute annual depreciation in paise using integer arithmetic.
    SL:  (cost - salvage) / useful_life_years
    WDV: current_wdv × rate / 100
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
        annual = math.floor((cost - salvage) / life)
    else:  # WDV
        rate = float(asset.get("wdv_rate_percent") or _DEFAULT_WDV_RATES.get(asset.get("asset_category", "Other"), 13.91))
        annual = math.floor(wdv_now * rate / 100)

    # Cannot depreciate below salvage value
    return min(annual, wdv_now - salvage)


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
    q = db.table("fixed_assets").select("*").eq("client_id", client_id)
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

    # Generate asset code
    client_id = data.client_id
    count_res = db.table("fixed_assets").select("id", count="exact").eq("client_id", client_id).execute()
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
        "wdv_rate_percent":            data.wdv_rate_percent or _DEFAULT_WDV_RATES.get(cat, 13.91),
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
    Post depreciation for a given period (month YYYY-MM or year YYYY).
    Computes depreciation and creates journal entry.
    Idempotent: checks depreciation_posted_through before posting.
    """
    db = _db()
    period = data.period or datetime.now(timezone.utc).strftime("%Y-%m")

    if not db:
        return api_response(True, {"asset_id": asset_id, "period": period, "depreciation_paise": 0})

    asset = db.table("fixed_assets").select("*").eq("id", asset_id).single().execute().data
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset["is_disposed"]:
        raise HTTPException(status_code=422, detail="Cannot depreciate a disposed asset")

    # Check already posted
    if asset.get("depreciation_posted_through") and asset["depreciation_posted_through"] >= period:
        raise HTTPException(status_code=409, detail=f"Depreciation already posted through {asset['depreciation_posted_through']}")

    # Compute monthly depreciation = annual / 12
    annual = _compute_annual_depreciation(asset)
    monthly = math.floor(annual / 12)

    if monthly <= 0:
        return api_response(True, {"message": "Asset fully depreciated", "depreciation_paise": 0})

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
    }).eq("id", asset_id).execute()

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
    """
    db = _db()
    if not db:
        return api_response(True, {"asset_id": asset_id, "disposed": True})

    asset = db.table("fixed_assets").select("*").eq("id", asset_id).single().execute().data
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset["is_disposed"]:
        raise HTTPException(status_code=409, detail="Asset already disposed")

    disposal_type   = data.disposal_type
    sale_proceeds   = data.sale_proceeds_paise
    disposal_date   = data.disposal_date or str(datetime.now(timezone.utc).date())

    asset["disposal_date"] = disposal_date

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    journal_id = _journal_svc.journal_for_asset_disposal(asset, sale_proceeds, current_user["firm_id"], asset["client_id"])

    db.table("fixed_assets").update({
        "is_disposed":        True,
        "disposal_date":      disposal_date,
        "disposal_value_paise": sale_proceeds,
        "notes":              data.get("notes", asset.get("notes")),
    }).eq("id", asset_id).execute()

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

    assets = db.table("fixed_assets").select("*").eq("client_id", client_id).eq("is_disposed", False).execute().data or []
    schedule = []
    for a in assets:
        annual = _compute_annual_depreciation(a)
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
            "monthly_depreciation_paise": math.floor(annual / 12),
            "depreciation_method":    a["depreciation_method"],
            "salvage_value_paise":    a.get("salvage_value_paise", 0),
        })
    return api_response(True, schedule)
