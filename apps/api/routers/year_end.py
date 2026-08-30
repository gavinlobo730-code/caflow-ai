"""
Year End Engagements router — CRUD for year-end engagements with status transitions.
Status flow: draft → in_review → approved → locked
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, filter_by_client

_USE_MOCK = not os.environ.get("SUPABASE_URL")

router = APIRouter(prefix="/year-end", tags=["year-end"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_financial_year(financial_year: str) -> tuple[str, str]:
    """
    Parse financial year string like "2024-25" into fy_start and fy_end ISO dates.
    Indian FY: April 1 to March 31.
    """
    try:
        start_year = int(financial_year.split("-")[0])
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="financial_year must be in 'YYYY-YY' format e.g. '2024-25'")
    fy_start = f"{start_year}-04-01"
    fy_end = f"{start_year + 1}-03-31"
    return fy_start, fy_end


def _check_engagement_locked(engagement: dict) -> None:
    if engagement.get("status") == "locked":
        raise HTTPException(status_code=403, detail="Engagement is locked. No further modifications are allowed.")


def _assert_engagement_scope(current_user: dict, engagement_id: str) -> dict:
    """Resolve a year_end_engagements row and 404 unless it belongs to the
    caller's firm and the caller may access its client.

    # M2 audit finding: get_engagement and update_engagement_status resolved
    # the engagement by firm_id alone and never checked its client against
    # the caller's assignment — a Manager or Executive assigned to no client
    # in common with this engagement could still read and transition it.
    # can_access_client (not assert_client_access) so a hidden engagement and
    # a missing one raise byte-identical detail text, the same message-oracle
    # fix already applied across this sweep.
    """
    firm_id = current_user["firm_id"]
    if _USE_MOCK:
        eng = _MOCK_ENGAGEMENTS.get(engagement_id)
        if not eng or eng["firm_id"] != firm_id or not can_access_client(current_user, eng.get("client_id")):
            raise HTTPException(status_code=404, detail="Engagement not found")
        return eng

    from core.supabase_client import get_supabase
    db = get_supabase()
    try:
        row = (
            db.table("year_end_engagements")
            .select("*")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
            .data
        )
    except Exception:
        # Supabase's real .single() raises (PGRST116) rather than returning
        # None on zero rows — without this the intended 404 below crashes to
        # an unhandled 500 for a missing or wrong-firm engagement_id. Same
        # shape already fixed in year_end_adjustments.py's own resolver.
        row = None
    if not row or not can_access_client(current_user, row.get("client_id")):
        raise HTTPException(status_code=404, detail="Engagement not found")
    return row


# ── Mock store (in-memory, for dev/test) ─────────────────────────────────────

_MOCK_ENGAGEMENTS: dict[str, dict] = {}

_VALID_STATUSES = ["draft", "in_review", "approved", "locked"]

_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "draft":     ["in_review"],
    "in_review": ["approved", "draft"],
    "approved":  ["locked"],
    "locked":    [],
}

# Roles allowed to transition to each target status
_TRANSITION_ROLE_GUARDS: dict[str, set[str]] = {
    "in_review": {"Partner", "Manager", "Executive"},
    "approved":  {"Partner", "Manager"},
    "locked":    {"Partner"},
    "draft":     {"Partner", "Manager"},
}


# ── Request models ────────────────────────────────────────────────────────────

class EngagementCreateIn(BaseModel):
    client_id: str
    financial_year: str   # e.g. "2024-25"
    engagement_name: Optional[str] = None


class EngagementStatusIn(BaseModel):
    status: str
    comment: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/engagements")
def create_engagement(
    data: EngagementCreateIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, data.client_id)
    firm_id = current_user["firm_id"]
    fy_start, fy_end = _parse_financial_year(data.financial_year)
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        eid = str(uuid.uuid4())
        engagement = {
            "id": eid,
            "firm_id": firm_id,
            "client_id": data.client_id,
            "financial_year": data.financial_year,
            "fy_start": fy_start,
            "fy_end": fy_end,
            "engagement_name": data.engagement_name or f"Year End {data.financial_year}",
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "created_by": current_user.get("auth_user_id"),
        }
        _MOCK_ENGAGEMENTS[eid] = engagement
        return api_response(True, engagement)

    from core.supabase_client import get_supabase
    db = get_supabase()
    row = db.table("year_end_engagements").insert({
        "id": str(uuid.uuid4()),
        "firm_id": firm_id,
        "client_id": data.client_id,
        "financial_year": data.financial_year,
        "fy_start": fy_start,
        "fy_end": fy_end,
        "engagement_name": data.engagement_name or f"Year End {data.financial_year}",
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "created_by": current_user.get("auth_user_id"),
    }).execute().data[0]
    return api_response(True, row)


@router.get("/engagements")
def list_engagements(
    client_id: Optional[str] = Query(None),
    financial_year: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("year_end", "read")),
):
    # M2 audit finding: client_id, when supplied, was never checked; when
    # omitted, the list was firm-wide with no per-row narrowing at all — an
    # Executive assigned to one client could list every client's engagements.
    if client_id:
        assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]

    if _USE_MOCK:
        results = [
            e for e in _MOCK_ENGAGEMENTS.values()
            if e["firm_id"] == firm_id
            and (not client_id or e["client_id"] == client_id)
            and (not financial_year or e["financial_year"] == financial_year)
        ]
        results = filter_by_client(current_user, results)
        return api_response(True, results)

    from core.supabase_client import get_supabase
    db = get_supabase()
    q = db.table("year_end_engagements").select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if financial_year:
        q = q.eq("financial_year", financial_year)
    rows = q.order("created_at", desc=True).execute().data
    rows = filter_by_client(current_user, rows)
    return api_response(True, rows)


@router.get("/engagements/{engagement_id}")
def get_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("year_end", "read")),
):
    # M2 audit finding: row-addressed by engagement_id, resolved by firm_id
    # alone with no check that the caller is assigned to its client.
    row = _assert_engagement_scope(current_user, engagement_id)

    if _USE_MOCK:
        detail = {
            **row,
            "checklist_completion_pct": 0,
            "adjustment_count": 0,
        }
        return api_response(True, detail)

    from core.supabase_client import get_supabase
    db = get_supabase()

    # Checklist completion %
    checklist_rows = (
        db.table("year_end_checklist_items")
        .select("id, status")
        .eq("engagement_id", engagement_id)
        .execute()
        .data
    )
    total = len(checklist_rows)
    completed = sum(1 for r in checklist_rows if r.get("status") == "complete")
    completion_pct = int((completed / total) * 100) if total else 0

    # Adjustment count
    adj_count = (
        db.table("year_end_adjustments")
        .select("id", count="exact")
        .eq("engagement_id", engagement_id)
        .execute()
        .count
        or 0
    )

    return api_response(True, {
        **row,
        "checklist_completion_pct": completion_pct,
        "adjustment_count": adj_count,
    })


@router.patch("/engagements/{engagement_id}/status")
def update_engagement_status(
    engagement_id: str,
    data: EngagementStatusIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    firm_id = current_user["firm_id"]
    role = current_user.get("role", "")
    new_status = data.status

    if new_status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{new_status}'")

    # M2 audit finding: row-addressed by engagement_id, resolved by firm_id
    # alone with no check that the caller is assigned to its client — a
    # wrong-firm-assigned Manager or Executive could transition (write to)
    # another staff member's client's engagement.
    if _USE_MOCK:
        eng = _assert_engagement_scope(current_user, engagement_id)
        _check_engagement_locked(eng)

        allowed_transitions = _STATUS_TRANSITIONS.get(eng["status"], [])
        if new_status not in allowed_transitions:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot transition from '{eng['status']}' to '{new_status}'",
            )
        allowed_roles = _TRANSITION_ROLE_GUARDS.get(new_status, set())
        if role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' cannot set status to '{new_status}'",
            )
        eng["status"] = new_status
        eng["updated_at"] = datetime.now(timezone.utc).isoformat()
        return api_response(True, eng)

    row = _assert_engagement_scope(current_user, engagement_id)
    _check_engagement_locked(row)

    from core.supabase_client import get_supabase
    db = get_supabase()

    allowed_transitions = _STATUS_TRANSITIONS.get(row["status"], [])
    if new_status not in allowed_transitions:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from '{row['status']}' to '{new_status}'",
        )
    allowed_roles = _TRANSITION_ROLE_GUARDS.get(new_status, set())
    if role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' cannot set status to '{new_status}'",
        )

    updated = (
        db.table("year_end_engagements")
        .update({"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", engagement_id)
        .execute()
        .data[0]
    )

    from services.year_end_workflow_service import lock_year_if_completing
    lock_year_if_completing(
        db, firm_id, row.get("financial_year"), new_status,
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        # The engagement's own client — a year-end closes one entity's year,
        # never the whole practice's.
        client_id=row.get("client_id"),
    )

    return api_response(True, updated)
