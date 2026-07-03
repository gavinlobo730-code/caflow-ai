"""
Year End Reviews router — Phase 6.
Manages the review and approval workflow for year-end engagements.

Status flow:
  draft → in_review (Staff/Manager submits)
  in_review → approved (Manager approves)
  in_review → draft (Manager requests revision)
  approved → locked (Partner final approval)

Reference: CA firm review workflow standards.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end-reviews"])

_ROLE_HIERARCHY = ["Client", "Reviewer", "Executive", "Manager", "Partner"]


def _role_gte(role: str, minimum: str) -> bool:
    try:
        return _ROLE_HIERARCHY.index(role) >= _ROLE_HIERARCHY.index(minimum)
    except ValueError:
        return False


# ── Mock helper ───────────────────────────────────────────────────────────────

def _get_mock_engagement(engagement_id: str, firm_id: str) -> dict:
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        eng = _MOCK_ENGAGEMENTS.get(engagement_id)
        if not eng or eng["firm_id"] != firm_id:
            raise HTTPException(status_code=404, detail="Engagement not found")
        return eng
    except ImportError:
        raise HTTPException(status_code=404, detail="Engagement not found")


def _update_mock_engagement(engagement_id: str, updates: dict) -> dict:
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        if engagement_id not in _MOCK_ENGAGEMENTS:
            raise HTTPException(status_code=404, detail="Engagement not found")
        _MOCK_ENGAGEMENTS[engagement_id].update(updates)
        return _MOCK_ENGAGEMENTS[engagement_id]
    except ImportError:
        raise HTTPException(status_code=404, detail="Engagement not found")


def _get_db_engagement(db, engagement_id: str, firm_id: str) -> dict:
    row = (
        db.table("year_end_engagements")
        .select("*")
        .eq("id", engagement_id)
        .eq("firm_id", firm_id)
        .single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return row


def _record_review_event(db, engagement_id: str, firm_id: str, event_type: str,
                          actor_id: str, comment: Optional[str]) -> None:
    """Record review event in audit history table (year_end_reviews, migration
    067 — event_type/actor_id are additive columns, migration 155, since 067's
    own review_type/action vocabulary doesn't cover this router's event names)."""
    import uuid
    try:
        db.table("year_end_reviews").insert({
            "id":            str(uuid.uuid4()),
            "engagement_id": engagement_id,
            "firm_id":       firm_id,
            "event_type":    event_type,
            "comment":       comment,
            "actor_id":      actor_id,
            "reviewed_by":   actor_id,
            "created_at":    datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass  # Non-critical audit trail — do not fail the main operation


# ── Request models ────────────────────────────────────────────────────────────

class ReviewActionIn(BaseModel):
    comment: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{engagement_id}/reviews/submit-for-review")
def submit_for_review(
    engagement_id: str,
    data: ReviewActionIn = ReviewActionIn(),
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """
    Staff/Manager/Executive submits engagement for review.
    Transitions: draft → in_review.
    """
    role    = current_user.get("role", "Executive")
    firm_id = current_user["firm_id"]
    now     = datetime.now(timezone.utc).isoformat()

    if not _role_gte(role, "Executive"):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' cannot submit for review. Requires Executive or above.",
        )

    if _USE_MOCK:
        eng = _get_mock_engagement(engagement_id, firm_id)
        if eng["status"] != "draft":
            raise HTTPException(
                status_code=422,
                detail=f"Can only submit a draft engagement. Current status: {eng['status']}",
            )
        return api_response(True, _update_mock_engagement(engagement_id, {
            "status":       "in_review",
            "submitted_by": current_user.get("auth_user_id"),
            "submitted_at": now,
            "updated_at":   now,
        }))

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_db_engagement(db, engagement_id, firm_id)
    if eng["status"] != "draft":
        raise HTTPException(
            status_code=422,
            detail=f"Can only submit a draft engagement. Current status: {eng['status']}",
        )

    updates = {
        "status":       "in_review",
        "submitted_by": current_user.get("auth_user_id"),
        "submitted_at": now,
        "updated_at":   now,
    }
    updated = (
        db.table("year_end_engagements")
        .update(updates)
        .eq("id", engagement_id)
        .execute()
        .data[0]
    )
    _record_review_event(db, engagement_id, firm_id, "submitted_for_review",
                         current_user.get("auth_user_id"), data.comment)
    log_event(firm_id, "year_end_engagement", engagement_id, "submit_for_review",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"status": "in_review"})
    return api_response(True, updated)


@router.post("/{engagement_id}/reviews/approve")
def approve_review(
    engagement_id: str,
    data: ReviewActionIn = ReviewActionIn(),
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """
    Manager approves the engagement.
    Transitions: in_review → approved.
    Requires Manager or Partner.
    """
    role    = current_user.get("role", "")
    firm_id = current_user["firm_id"]
    now     = datetime.now(timezone.utc).isoformat()

    if not _role_gte(role, "Manager"):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' cannot approve. Requires Manager or above.",
        )

    if _USE_MOCK:
        eng = _get_mock_engagement(engagement_id, firm_id)
        if eng["status"] != "in_review":
            raise HTTPException(
                status_code=422,
                detail=f"Can only approve an in_review engagement. Current status: {eng['status']}",
            )
        return api_response(True, _update_mock_engagement(engagement_id, {
            "status":      "approved",
            "approved_by": current_user.get("auth_user_id"),
            "approved_at": now,
            "updated_at":  now,
        }))

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_db_engagement(db, engagement_id, firm_id)
    if eng["status"] != "in_review":
        raise HTTPException(
            status_code=422,
            detail=f"Can only approve an in_review engagement. Current status: {eng['status']}",
        )

    updates = {
        "status":      "approved",
        "approved_by": current_user.get("auth_user_id"),
        "approved_at": now,
        "updated_at":  now,
    }
    updated = (
        db.table("year_end_engagements")
        .update(updates)
        .eq("id", engagement_id)
        .execute()
        .data[0]
    )
    _record_review_event(db, engagement_id, firm_id, "approved",
                         current_user.get("auth_user_id"), data.comment)
    log_event(firm_id, "year_end_engagement", engagement_id, "approve",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"status": "approved"})
    return api_response(True, updated)


@router.post("/{engagement_id}/reviews/request-revision")
def request_revision(
    engagement_id: str,
    data: ReviewActionIn = ReviewActionIn(),
    current_user: dict = Depends(rbac("year_end", "approve")),
):
    """
    Manager requests changes — sends engagement back to draft.
    Transitions: in_review → draft.
    Requires Manager or Partner.
    """
    role    = current_user.get("role", "")
    firm_id = current_user["firm_id"]
    now     = datetime.now(timezone.utc).isoformat()

    if not _role_gte(role, "Manager"):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' cannot request revision. Requires Manager or above.",
        )

    if _USE_MOCK:
        eng = _get_mock_engagement(engagement_id, firm_id)
        if eng["status"] != "in_review":
            raise HTTPException(
                status_code=422,
                detail=f"Can only request revision for an in_review engagement. Current: {eng['status']}",
            )
        return api_response(True, _update_mock_engagement(engagement_id, {
            "status":              "draft",
            "revision_requested_by": current_user.get("auth_user_id"),
            "revision_comment":    data.comment,
            "updated_at":          now,
        }))

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_db_engagement(db, engagement_id, firm_id)
    if eng["status"] != "in_review":
        raise HTTPException(
            status_code=422,
            detail=f"Can only request revision for an in_review engagement. Current: {eng['status']}",
        )

    updates = {
        "status":                "draft",
        "revision_requested_by": current_user.get("auth_user_id"),
        "revision_comment":      data.comment,
        "updated_at":            now,
    }
    updated = (
        db.table("year_end_engagements")
        .update(updates)
        .eq("id", engagement_id)
        .execute()
        .data[0]
    )
    _record_review_event(db, engagement_id, firm_id, "revision_requested",
                         current_user.get("auth_user_id"), data.comment)
    log_event(firm_id, "year_end_engagement", engagement_id, "request_revision",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"status": "draft", "comment": data.comment})
    return api_response(True, updated)


@router.post("/{engagement_id}/reviews/final-approve")
def final_approve(
    engagement_id: str,
    data: ReviewActionIn = ReviewActionIn(),
    current_user: dict = Depends(rbac("year_end", "final_approve")),
):
    """
    Partner gives final approval and locks the engagement.
    Transitions: approved → locked.
    Only Partner can perform this action.
    Once locked, no further modifications are permitted on the engagement or its data.
    """
    role    = current_user.get("role", "")
    firm_id = current_user["firm_id"]
    now     = datetime.now(timezone.utc).isoformat()

    if role != "Partner":
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' cannot give final approval. Only Partner can lock an engagement.",
        )

    if _USE_MOCK:
        eng = _get_mock_engagement(engagement_id, firm_id)
        if eng["status"] != "approved":
            raise HTTPException(
                status_code=422,
                detail=f"Can only final-approve an approved engagement. Current: {eng['status']}",
            )
        return api_response(True, _update_mock_engagement(engagement_id, {
            "status":           "locked",
            "final_approved_by":current_user.get("auth_user_id"),
            "final_approved_at":now,
            "locked_at":        now,
            "updated_at":       now,
        }))

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_db_engagement(db, engagement_id, firm_id)
    if eng["status"] != "approved":
        raise HTTPException(
            status_code=422,
            detail=f"Can only final-approve an approved engagement. Current: {eng['status']}",
        )

    updates = {
        "status":            "locked",
        "final_approved_by": current_user.get("auth_user_id"),
        "final_approved_at": now,
        "locked_at":         now,
        "updated_at":        now,
    }
    updated = (
        db.table("year_end_engagements")
        .update(updates)
        .eq("id", engagement_id)
        .execute()
        .data[0]
    )
    _record_review_event(db, engagement_id, firm_id, "final_approved_and_locked",
                         current_user.get("auth_user_id"), data.comment)
    log_event(firm_id, "year_end_engagement", engagement_id, "final_approve",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"status": "locked"})
    return api_response(True, updated)
