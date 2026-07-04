"""
Year End Adjustments router — Phase 6.
Manages year-end adjustment entries with approval workflow.
Adjustment types: accrual, prepayment, provision, reclassification,
                  depreciation_adj, manual.
Status flow: draft → pending_review → approved → posted
             draft → pending_review → rejected

All monetary values: integer paise (BIGINT). Never float.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-adjustments"])

_VALID_ADJUSTMENT_TYPES = {
    "accrual", "prepayment", "provision",
    "reclassification", "depreciation_adj", "manual",
}
_VALID_STATUSES = {"draft", "pending_review", "approved", "posted", "rejected"}

# ── Mock store ────────────────────────────────────────────────────────────────
# engagement_id → list of adjustment dicts
_MOCK_ADJUSTMENTS: dict[str, list[dict]] = {}


def _get_mock_engagement_status(engagement_id: str) -> str:
    """Return mock engagement status — always 'draft' unless overridden."""
    # Import here to avoid circular imports; mock only
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        eng = _MOCK_ENGAGEMENTS.get(engagement_id, {})
        return eng.get("status", "draft")
    except Exception:
        return "draft"


def _guard_locked_mock(engagement_id: str) -> None:
    if _get_mock_engagement_status(engagement_id) == "locked":
        raise HTTPException(
            status_code=403,
            detail="Engagement is locked — no write operations permitted",
        )


# ── Request models ────────────────────────────────────────────────────────────

class AdjustmentCreateIn(BaseModel):
    adjustment_type: str          # accrual / prepayment / provision / reclassification / depreciation_adj / manual
    description: str
    amount_paise: int             # Must be positive integer paise — BIGINT, never float
    debit_account_id: str
    credit_account_id: str
    adjustment_date: str          # ISO date string YYYY-MM-DD
    reference_no: Optional[str] = None


class AdjustmentUpdateIn(BaseModel):
    description: Optional[str] = None
    amount_paise: Optional[int] = None
    debit_account_id: Optional[str] = None
    credit_account_id: Optional[str] = None
    adjustment_date: Optional[str] = None
    reference_no: Optional[str] = None


class AdjustmentRejectIn(BaseModel):
    reason: str


class AdjustmentCommentIn(BaseModel):
    comment: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_positive_paise(amount_paise: int) -> None:
    """All monetary amounts must be positive integers in paise. Never float."""
    if not isinstance(amount_paise, int) or isinstance(amount_paise, bool):
        raise HTTPException(status_code=422, detail="amount_paise must be an integer")
    if amount_paise <= 0:
        raise HTTPException(status_code=422, detail="amount_paise must be a positive integer (in paise)")


def _fetch_engagement_db(db, engagement_id: str, firm_id: str) -> dict:
    row = (
        db.table("year_end_engagements")
        .select("id, status, firm_id, client_id")
        .eq("id", engagement_id)
        .eq("firm_id", firm_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if row["status"] == "locked":
        raise HTTPException(
            status_code=403,
            detail="Engagement is locked — no write operations permitted",
        )
    return row


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{engagement_id}/adjustments")
def create_adjustment(
    engagement_id: str,
    data: AdjustmentCreateIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    if data.adjustment_type not in _VALID_ADJUSTMENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid adjustment_type '{data.adjustment_type}'. "
                   f"Must be one of: {sorted(_VALID_ADJUSTMENT_TYPES)}",
        )
    _require_positive_paise(data.amount_paise)

    now = datetime.now(timezone.utc).isoformat()
    adj_id = str(uuid.uuid4())

    record = {
        "id":               adj_id,
        "engagement_id":    engagement_id,
        "firm_id":          current_user["firm_id"],
        "adjustment_type":  data.adjustment_type,
        "description":      data.description,
        "amount_paise":     data.amount_paise,    # integer paise — BIGINT
        "debit_account_id": data.debit_account_id,
        "credit_account_id":data.credit_account_id,
        "adjustment_date":  data.adjustment_date,
        "reference_no":     data.reference_no,
        "status":           "draft",
        "created_by":       current_user.get("auth_user_id"),
        "created_at":       now,
        "updated_at":       now,
    }

    if _USE_MOCK:
        _guard_locked_mock(engagement_id)
        record["client_id"] = "client-001"
        _MOCK_ADJUSTMENTS.setdefault(engagement_id, []).append(record)
        return api_response(True, record)

    from core.supabase_client import get_supabase
    db = get_supabase()
    # F9 fix: client_id is NOT NULL on year_end_adjustments; derive it from the
    # (firm-validated) engagement rather than trusting client input.
    eng = _fetch_engagement_db(db, engagement_id, current_user["firm_id"])
    record["client_id"] = eng["client_id"]

    result = db.table("year_end_adjustments").insert(record).execute()
    created = result.data[0]
    log_event(
        current_user["firm_id"], "year_end_adjustment", adj_id, "create",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data=created,
    )
    return api_response(True, created)


@router.get("/{engagement_id}/adjustments")
def list_adjustments(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    if _USE_MOCK:
        return api_response(True, _MOCK_ADJUSTMENTS.get(engagement_id, []))

    from core.supabase_client import get_supabase
    db = get_supabase()
    rows = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("engagement_id", engagement_id)
        .eq("firm_id", current_user["firm_id"])
        .order("created_at", desc=False)
        .execute()
        .data
    )
    return api_response(True, rows)


@router.patch("/{engagement_id}/adjustments/{adjustment_id}")
def update_adjustment(
    engagement_id: str,
    adjustment_id: str,
    data: AdjustmentUpdateIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    if data.amount_paise is not None:
        _require_positive_paise(data.amount_paise)

    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        _guard_locked_mock(engagement_id)
        items = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        adj = next((a for a in items if a["id"] == adjustment_id), None)
        if not adj:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        if adj["status"] != "draft":
            raise HTTPException(status_code=422, detail="Only draft adjustments can be updated")
        updates = data.model_dump(exclude_none=True)
        adj.update(updates)
        adj["updated_at"] = now
        return api_response(True, adj)

    from core.supabase_client import get_supabase
    db = get_supabase()
    _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if existing["status"] != "draft":
        raise HTTPException(status_code=422, detail="Only draft adjustments can be updated")

    updates = data.model_dump(exclude_none=True)
    updates["updated_at"] = now

    updated = (
        db.table("year_end_adjustments")
        .update(updates)
        .eq("id", adjustment_id)
        .execute()
        .data[0]
    )
    return api_response(True, updated)


@router.post("/{engagement_id}/adjustments/{adjustment_id}/submit")
def submit_adjustment(
    engagement_id: str,
    adjustment_id: str,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        _guard_locked_mock(engagement_id)
        items = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        adj = next((a for a in items if a["id"] == adjustment_id), None)
        if not adj:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        if adj["status"] != "draft":
            raise HTTPException(status_code=422, detail="Only draft adjustments can be submitted")
        adj["status"] = "pending_review"
        adj["submitted_by"] = current_user.get("auth_user_id")
        adj["submitted_at"] = now
        adj["updated_at"] = now
        return api_response(True, adj)

    from core.supabase_client import get_supabase
    db = get_supabase()
    _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if existing["status"] != "draft":
        raise HTTPException(status_code=422, detail="Only draft adjustments can be submitted")

    updated = (
        db.table("year_end_adjustments")
        .update({
            "status":       "pending_review",
            "submitted_by": current_user.get("auth_user_id"),
            "submitted_at": now,
            "updated_at":   now,
        })
        .eq("id", adjustment_id)
        .execute()
        .data[0]
    )
    return api_response(True, updated)


@router.post("/{engagement_id}/adjustments/{adjustment_id}/approve")
def approve_adjustment(
    engagement_id: str,
    adjustment_id: str,
    data: AdjustmentCommentIn = AdjustmentCommentIn(),
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """Approve a pending_review adjustment. Requires Manager or Partner."""
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        _guard_locked_mock(engagement_id)
        items = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        adj = next((a for a in items if a["id"] == adjustment_id), None)
        if not adj:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        if adj["status"] != "pending_review":
            raise HTTPException(status_code=422, detail="Only pending_review adjustments can be approved")
        adj["status"] = "approved"
        adj["approved_by"] = current_user.get("auth_user_id")
        adj["approved_at"] = now
        adj["updated_at"] = now
        if data.comment:
            adj["review_comment"] = data.comment
        return api_response(True, adj)

    from core.supabase_client import get_supabase
    db = get_supabase()
    _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if existing["status"] != "pending_review":
        raise HTTPException(status_code=422, detail="Only pending_review adjustments can be approved")

    updates = {
        "status":         "approved",
        "approved_by":    current_user.get("auth_user_id"),
        "approved_at":    now,
        "updated_at":     now,
    }
    if data.comment:
        updates["review_comment"] = data.comment

    updated = (
        db.table("year_end_adjustments")
        .update(updates)
        .eq("id", adjustment_id)
        .execute()
        .data[0]
    )
    log_event(
        current_user["firm_id"], "year_end_adjustment", adjustment_id, "approve",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"status": "approved"},
    )
    return api_response(True, updated)


@router.post("/{engagement_id}/adjustments/{adjustment_id}/post")
def post_adjustment(
    engagement_id: str,
    adjustment_id: str,
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """
    Post an approved adjustment — creates a journal entry via accounting service.
    source='YEAR_END_ADJUSTMENT' tags the journal entry for traceability.
    """
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        _guard_locked_mock(engagement_id)
        items = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        adj = next((a for a in items if a["id"] == adjustment_id), None)
        if not adj:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        if adj["status"] != "approved":
            raise HTTPException(status_code=422, detail="Only approved adjustments can be posted")
        mock_journal_id = str(uuid.uuid4())
        adj["status"] = "posted"
        adj["posted_by"] = current_user.get("auth_user_id")
        adj["posted_at"] = now
        adj["journal_entry_id"] = mock_journal_id
        adj["updated_at"] = now
        return api_response(True, adj)

    from core.supabase_client import get_supabase
    db = get_supabase()
    _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if existing["status"] != "approved":
        raise HTTPException(status_code=422, detail="Only approved adjustments can be posted")

    # Create journal entry via accounting domain service with source tag
    journal_id = str(uuid.uuid4())
    journal_entry = {
        "id":           journal_id,
        "firm_id":      current_user["firm_id"],
        "entry_date":   existing["adjustment_date"],
        "reference_no": f"YEA-{adjustment_id[:8].upper()}",
        "narration":    existing["description"],
        "source":       "YEAR_END_ADJUSTMENT",
        "source_ref_id":adjustment_id,
        "is_posted":    True,
        "created_at":   now,
    }
    journal_lines = [
        {
            "journal_entry_id": journal_id,
            "account_id":       existing["debit_account_id"],
            "debit_paise":      existing["amount_paise"],   # integer paise
            "credit_paise":     0,
            "narration":        existing["description"],
        },
        {
            "journal_entry_id": journal_id,
            "account_id":       existing["credit_account_id"],
            "debit_paise":      0,
            "credit_paise":     existing["amount_paise"],   # integer paise
            "narration":        existing["description"],
        },
    ]
    db.table("journal_entries").insert(journal_entry).execute()
    db.table("journal_lines").insert(journal_lines).execute()

    # Update adjustment status
    updated = (
        db.table("year_end_adjustments")
        .update({
            "status":           "posted",
            "posted_by":        current_user.get("auth_user_id"),
            "posted_at":        now,
            "journal_entry_id": journal_id,
            "updated_at":       now,
        })
        .eq("id", adjustment_id)
        .execute()
        .data[0]
    )
    log_event(
        current_user["firm_id"], "year_end_adjustment", adjustment_id, "post",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"status": "posted", "journal_entry_id": journal_id},
    )
    return api_response(True, updated)


@router.post("/{engagement_id}/adjustments/{adjustment_id}/reject")
def reject_adjustment(
    engagement_id: str,
    adjustment_id: str,
    data: AdjustmentRejectIn,
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """Reject a pending_review adjustment. Reason is required."""
    if not data.reason or not data.reason.strip():
        raise HTTPException(status_code=422, detail="A reason is required to reject an adjustment")

    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        _guard_locked_mock(engagement_id)
        items = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        adj = next((a for a in items if a["id"] == adjustment_id), None)
        if not adj:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        if adj["status"] != "pending_review":
            raise HTTPException(status_code=422, detail="Only pending_review adjustments can be rejected")
        adj["status"] = "rejected"
        adj["rejected_by"] = current_user.get("auth_user_id")
        adj["rejected_at"] = now
        adj["rejection_reason"] = data.reason
        adj["updated_at"] = now
        return api_response(True, adj)

    from core.supabase_client import get_supabase
    db = get_supabase()
    _fetch_engagement_db(db, engagement_id, current_user["firm_id"])

    existing = (
        db.table("year_end_adjustments")
        .select("*")
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if existing["status"] != "pending_review":
        raise HTTPException(status_code=422, detail="Only pending_review adjustments can be rejected")

    updated = (
        db.table("year_end_adjustments")
        .update({
            "status":           "rejected",
            "rejected_by":      current_user.get("auth_user_id"),
            "rejected_at":      now,
            "rejection_reason": data.reason,
            "updated_at":       now,
        })
        .eq("id", adjustment_id)
        .execute()
        .data[0]
    )
    log_event(
        current_user["firm_id"], "year_end_adjustment", adjustment_id, "reject",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data={"status": "rejected", "reason": data.reason},
    )
    return api_response(True, updated)
