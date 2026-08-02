"""
Year End Checklist router — 12 standard checklist items per engagement.
Auto-initializes items if none exist when GET is called.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-checklist"])

# ── Standard 12 checklist items ───────────────────────────────────────────────

_STANDARD_ITEMS = [
    {"category": "banking",  "item_code": "BANK_REC",              "item_label": "Bank Reconciliation Complete",   "sequence_no": 1},
    {"category": "tax",      "item_code": "GST_FILED",             "item_label": "GST Returns Filed",              "sequence_no": 2},
    {"category": "tax",      "item_code": "TDS_FILED",             "item_label": "TDS Returns Filed",              "sequence_no": 3},
    {"category": "payroll",  "item_code": "PAYROLL_CLOSED",        "item_label": "Payroll Closed for Year",        "sequence_no": 4},
    {"category": "assets",   "item_code": "DEPRECIATION_POSTED",   "item_label": "Depreciation Posted",            "sequence_no": 5},
    {"category": "review",   "item_code": "RECEIVABLES_REVIEWED",  "item_label": "Receivables Reviewed",           "sequence_no": 6},
    {"category": "review",   "item_code": "PAYABLES_REVIEWED",     "item_label": "Payables Reviewed",              "sequence_no": 7},
    {"category": "review",   "item_code": "LOANS_REVIEWED",        "item_label": "Loans Reviewed",                 "sequence_no": 8},
    {"category": "review",   "item_code": "ADVANCES_REVIEWED",     "item_label": "Advances Reviewed",              "sequence_no": 9},
    {"category": "review",   "item_code": "RELATED_PARTIES_REVIEWED", "item_label": "Related Parties Reviewed",   "sequence_no": 10},
    {"category": "general",  "item_code": "PROVISIONS_REVIEWED",   "item_label": "Provisions Reviewed",            "sequence_no": 11},
    {"category": "general",  "item_code": "ACCRUALS_REVIEWED",     "item_label": "Accruals Reviewed",              "sequence_no": 12},
]

_VALID_ITEM_STATUSES = ["pending", "in_progress", "complete", "not_applicable"]

# ── Mock store ────────────────────────────────────────────────────────────────

# engagement_id → list of checklist item dicts
_MOCK_CHECKLIST: dict[str, list[dict]] = {}


def _fetch_engagement_db(db, engagement_id: str, firm_id: str) -> dict:
    """F1/F4-class fix: validate the engagement belongs to the caller's firm
    before touching its checklist -- neither endpoint checked this at all."""
    row = (
        db.table("year_end_engagements")
        .select("id, firm_id")
        .eq("id", engagement_id)
        .eq("firm_id", firm_id)
        .maybe_single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return row


def _init_checklist_items(engagement_id: str) -> list[dict]:
    """Create 12 standard items for an engagement."""
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for tmpl in _STANDARD_ITEMS:
        items.append({
            "id": str(uuid.uuid4()),
            "engagement_id": engagement_id,
            "category": tmpl["category"],
            "item_code": tmpl["item_code"],
            "item_label": tmpl["item_label"],
            "sequence_no": tmpl["sequence_no"],
            "status": "pending",
            "notes": None,
            "completed_by": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        })
    return items


# ── Request models ────────────────────────────────────────────────────────────

class ChecklistItemUpdateIn(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{engagement_id}/checklist")
def list_checklist(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        if engagement_id not in _MOCK_CHECKLIST:
            _MOCK_CHECKLIST[engagement_id] = _init_checklist_items(engagement_id)
        return api_response(True, _MOCK_CHECKLIST[engagement_id])

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_checklist_items")
        .select("*")
        .eq("engagement_id", engagement_id)
        .order("sequence_no")
        .execute()
        .data
    )

    if not existing:
        # Auto-initialize 12 standard items
        now = datetime.now(timezone.utc).isoformat()
        rows_to_insert = []
        for tmpl in _STANDARD_ITEMS:
            rows_to_insert.append({
                "id": str(uuid.uuid4()),
                "engagement_id": engagement_id,
                "firm_id": eng["firm_id"],
                "category": tmpl["category"],
                "item_code": tmpl["item_code"],
                "item_label": tmpl["item_label"],
                "sequence_no": tmpl["sequence_no"],
                "status": "pending",
                "notes": None,
                "completed_by": None,
                "completed_at": None,
                "created_at": now,
                "updated_at": now,
            })
        existing = db.table("year_end_checklist_items").insert(rows_to_insert).execute().data

    return api_response(True, existing)


@router.patch("/{engagement_id}/checklist/{item_id}")
def update_checklist_item(
    engagement_id: str,
    item_id: str,
    data: ChecklistItemUpdateIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    if data.status and data.status not in _VALID_ITEM_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{data.status}'")

    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        items = _MOCK_CHECKLIST.get(engagement_id, [])
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Checklist item not found")
        if data.status is not None:
            item["status"] = data.status
            if data.status == "complete":
                item["completed_by"] = current_user.get("auth_user_id")
                item["completed_at"] = now
        if data.notes is not None:
            item["notes"] = data.notes
        item["updated_at"] = now
        return api_response(True, item)

    from core.supabase_client import get_supabase
    db = get_supabase()
    _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_checklist_items")
        .select("*")
        .eq("id", item_id)
        .eq("engagement_id", engagement_id)
        .maybe_single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    updates: dict = {"updated_at": now}
    if data.status is not None:
        updates["status"] = data.status
        if data.status == "complete":
            updates["completed_by"] = current_user.get("auth_user_id")
            updates["completed_at"] = now
    if data.notes is not None:
        updates["notes"] = data.notes

    updated = (
        db.table("year_end_checklist_items")
        .update(updates)
        .eq("id", item_id)
        .execute()
        .data[0]
    )
    return api_response(True, updated)
