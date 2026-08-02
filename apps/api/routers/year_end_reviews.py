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
    """Record a review event in the audit history table.

    Writes to `year_end_review_events`, which is what production actually has.
    This used to target `year_end_reviews` from migration 067 — a table that was
    never created, because a divergent Studio migration created the
    `year_end_*` set instead and 067 never ran. Every insert here has therefore
    been failing silently since the feature shipped: the except below swallows
    it, so the review trail was quietly empty rather than loudly broken.
    See docs/audits/2026-08-02-migration-ledger-drift-audit.md.

    `reviewed_by` is not sent: year_end_review_events has no such column, and
    `actor_id` already carries who did it. The four event_type values this
    router emits match the table's CHECK constraint exactly.
    """
    import uuid
    try:
        db.table("year_end_review_events").insert({
            "id":            str(uuid.uuid4()),
            "engagement_id": engagement_id,
            "firm_id":       firm_id,
            "event_type":    event_type,
            "comment":       comment,
            "actor_id":      actor_id,
            # `reviewed_by` deliberately omitted — see the docstring above.
            "created_at":    datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass  # Non-critical audit trail — do not fail the main operation


# ── Request models ────────────────────────────────────────────────────────────

class ReviewActionIn(BaseModel):
    comment: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/engagements/{engagement_id}/reviews/submit-for-review")
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


@router.post("/engagements/{engagement_id}/reviews/approve")
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


@router.post("/engagements/{engagement_id}/reviews/request-revision")
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


@router.post("/engagements/{engagement_id}/reviews/final-approve")
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

    from services.year_end_workflow_service import lock_year_if_completing
    lock_year_if_completing(
        db, firm_id, eng.get("financial_year"), "locked",
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
    )

    return api_response(True, updated)


# ── Review state (steps + history) ──────────────────────────────────────────

_STEP_FIELDS = (
    ("prepared", "submitted_by", "submitted_at"),
    ("reviewed", "approved_by", "approved_at"),
    ("approved", "final_approved_by", "final_approved_at"),
)

# Each audit event's fixed (from_status, to_status) — the workflow only ever
# makes these four transitions, so this is a static lookup, not derived data.
_EVENT_TRANSITIONS = {
    "submitted_for_review":      ("draft", "in_review"),
    "approved":                  ("in_review", "approved"),
    "revision_requested":        ("in_review", "draft"),
    "final_approved_and_locked": ("approved", "locked"),
}


def _build_steps(eng: dict, users_by_auth_id: dict) -> list[dict]:
    steps = []
    for step_key, actor_field, at_field in _STEP_FIELDS:
        actor_id = eng.get(actor_field)
        user = users_by_auth_id.get(actor_id, {}) if actor_id else {}
        steps.append({
            "step": step_key,
            "user_name": user.get("full_name"),
            "user_role": user.get("role"),
            "completed_at": eng.get(at_field),
            "comment": None,
        })
    return steps


def _history_entry(row: dict, users_by_auth_id: dict) -> dict:
    actor_id = row.get("actor_id")
    user = users_by_auth_id.get(actor_id, {}) if actor_id else {}
    from_status, to_status = _EVENT_TRANSITIONS.get(row.get("event_type"), (None, None))
    return {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "action": row.get("event_type"),
        "performed_by": user.get("full_name") or actor_id or "—",
        "performed_at": row.get("created_at"),
        "comment": row.get("comment"),
        "from_status": from_status,
        "to_status": to_status,
    }


@router.get("/engagements/{engagement_id}/reviews")
def get_review_state(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    """The three-step timeline + full audit history the review page renders."""
    firm_id = current_user["firm_id"]

    if _USE_MOCK:
        eng = _get_mock_engagement(engagement_id, firm_id)
        # Mock mode has no audit table -- synthesize one entry reflecting the
        # engagement's current status so the frontend's history[0].to_status
        # (its sole source for "what state is this in") stays correct.
        history = []
        if eng["status"] != "draft":
            history = [{
                "id": engagement_id, "engagement_id": engagement_id,
                "action": "current_status", "performed_by": "—",
                "performed_at": eng.get("updated_at"), "comment": None,
                "from_status": None, "to_status": eng["status"],
            }]
        return api_response(True, {"steps": _build_steps(eng, {}), "history": history})

    from core.supabase_client import get_supabase
    db = get_supabase()
    eng = _get_db_engagement(db, engagement_id, firm_id)

    actor_ids = {eng.get(f) for _, f, _ in _STEP_FIELDS if eng.get(f)}
    history_rows = (
        db.table("year_end_review_events").select("*")
        .eq("engagement_id", engagement_id)
        .order("created_at", desc=True)
        .execute().data or []
    )
    actor_ids |= {r.get("actor_id") for r in history_rows if r.get("actor_id")}

    users_by_auth_id = {}
    if actor_ids:
        rows = (
            db.table("users").select("auth_user_id, full_name, role")
            .in_("auth_user_id", list(actor_ids)).execute().data or []
        )
        users_by_auth_id = {r["auth_user_id"]: r for r in rows}

    steps = _build_steps(eng, users_by_auth_id)
    history = [_history_entry(r, users_by_auth_id) for r in history_rows]
    return api_response(True, {"steps": steps, "history": history})
