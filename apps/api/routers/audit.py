"""
Audit log query endpoint — Partner only.

The edit log the proviso to Rule 3(1) of the Companies (Accounts) Rules 2014
requires, made readable. Every filter is applied IN THE DATABASE and the log is
paged with a cursor; what this replaced returned the most recent 200 rows
firm-wide with no date range and no paging, and its one caller then filtered
those 200 in the browser. See services/audit_service for why an IST date is not
a UTC date and why the cursor has to break ties on the id.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.permissions import rbac
from models.common import api_response
from services import audit_query_service as audit_query

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def get_audit_log(
    entity_type: Optional[str] = Query(
        None, description="One type, or a comma list — 'journal_entry,journal_line' "
                          "is one question, because migration 266 keys a line's "
                          "audit row to its PARENT entry id"),
    entity_id: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="IST date, inclusive (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="IST date, inclusive (YYYY-MM-DD)"),
    cursor: Optional[str] = Query(None, description="next_cursor from the previous page"),
    limit: int = Query(audit_query.DEFAULT_PAGE, ge=1, le=audit_query.MAX_PAGE),
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """One page of the firm's audit log, newest first — Partners only.

    `next_cursor` is null on the last page. There is deliberately no total: a
    count over the whole log to render one page is the cost this endpoint
    exists to remove, and `has_more` is what a "Load more" control needs.
    """
    from core.supabase_client import get_supabase
    try:
        return api_response(True, audit_query.query(
            get_supabase(), current_user["firm_id"],
            entity_type=entity_type, entity_id=entity_id, actor_id=actor_id,
            action=action, date_from=date_from, date_to=date_to,
            cursor=cursor, limit=limit))
    except audit_query.AuditQueryRefused as e:
        # A refusal names what to do next, so it is shown as written.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:                                       # noqa: BLE001
        return api_response(False, None, str(e))


@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_history(
    entity_type: str,
    entity_id: str,
    cursor: Optional[str] = Query(None),
    limit: int = Query(audit_query.DEFAULT_PAGE, ge=1, le=audit_query.MAX_PAGE),
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Everything that ever happened to ONE row, oldest change last.

    The question an auditor actually asks, and the one the old endpoint could
    not answer from any screen even though it already accepted entity_id: for a
    journal entry, `entity_type` is sent as 'journal_entry,journal_line',
    because a line's audit row is keyed to the parent entry (migration 266) and
    an entry's history that omits its lines omits the amounts.
    """
    from core.supabase_client import get_supabase
    try:
        return api_response(True, audit_query.query(
            get_supabase(), current_user["firm_id"],
            entity_type=entity_type, entity_id=entity_id,
            cursor=cursor, limit=limit))
    except audit_query.AuditQueryRefused as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:                                       # noqa: BLE001
        return api_response(False, None, str(e))
