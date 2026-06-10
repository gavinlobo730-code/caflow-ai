"""
Audit log query endpoint — Partner only.
GET /api/audit?entity_type=&entity_id=&limit=
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def get_audit_log(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Returns audit log entries — restricted to Partners."""
    from core.supabase_client import get_supabase
    firm_id = current_user["firm_id"]

    try:
        q = (
            get_supabase().table("audit_log")
            .select("*")
            .eq("firm_id", firm_id)
        )
        if entity_type:
            q = q.eq("entity_type", entity_type)
        if entity_id:
            q = q.eq("entity_id", entity_id)
        if actor_id:
            q = q.eq("actor_id", actor_id)
        result = q.order("created_at", desc=True).limit(limit).execute()
        entries = result.data or []
    except Exception as e:
        return api_response(False, None, str(e))

    return api_response(True, {"entries": entries, "total": len(entries)})
