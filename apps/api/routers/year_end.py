"""
Year End Engagements router — CRUD for year-end engagements with status transitions.
Status flow: draft → in_review → approved → locked
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, filter_by_client
from models.fy import FYLabel, OptionalFYLabel

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


def _check_engagement_locked(engagement: dict, *, new_status: Optional[str] = None) -> None:
    """Refuse every modification of a locked engagement — except reopening it.

    Without the exemption the reopen is unreachable no matter what the
    transition table says: this runs first and 403s on the status alone. That
    is how "locked" stayed terminal even though set_client_lock had supported
    lock=False since migration 289.
    """
    if engagement.get("status") != "locked":
        return
    if new_status is not None and _is_reopen("locked", new_status):
        return
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
    # ACC-05: "locked" used to be terminal, here and in the client_year_locks
    # row it writes. Reopening a closed year is ordinary practice — a revised
    # interest certificate, a §143(1) intimation, an audit adjustment found
    # while filing the ITR — and the posting kernel's own refusal tells the CA
    # to "Reopen the year before posting to it", which was an instruction to do
    # something the product could not do.
    "locked":    ["approved"],
}

# Roles allowed to transition to each target status
_TRANSITION_ROLE_GUARDS: dict[str, set[str]] = {
    "in_review": {"Partner", "Manager", "Executive"},
    "approved":  {"Partner", "Manager"},
    "locked":    {"Partner"},
    "draft":     {"Partner", "Manager"},
}

# The ONE transition whose guard cannot be read off its target status. Going to
# "approved" is a Manager's call in the ordinary review loop; going there FROM
# "locked" reverses a Partner's finalisation and reopens the client's financial
# year for posting, so it is Partner-only and must say why. Keyed on the PAIR
# because the target alone is what made the two look like the same move.
REOPEN_TRANSITION = ("locked", "approved")
_REOPEN_ROLES: set[str] = {"Partner"}
REOPEN_REASON_REQUIRED = (
    "Reopening a finalised year needs a reason — it reverses a Partner's "
    "final approval and lets postings back into a closed year. Send it as "
    "`comment`."
)


def _is_reopen(current_status: str, new_status: str) -> bool:
    return (current_status, new_status) == REOPEN_TRANSITION


# ── Request models ────────────────────────────────────────────────────────────

class EngagementCreateIn(BaseModel):
    client_id: str
    financial_year: FYLabel   # e.g. "2024-25"
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
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
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


class EngagementUdinIn(BaseModel):
    """The UDIN the signing member obtained from ICAI's portal.

    None clears a number recorded in error — a wrong UDIN on an issued
    document is worse than none, so removing one must be possible.
    """
    udin: Optional[str] = None


@router.patch("/engagements/{engagement_id}/udin")
def record_engagement_udin(
    engagement_id: str,
    data: EngagementUdinIn,
    current_user: dict = Depends(rbac("year_end", "write")),
):
    """Record the UDIN for this year-end set. RECORDED, NEVER GENERATED.

    A UDIN is issued by ICAI's UDIN portal to the member in practice who signs
    the document, against their own membership credentials. Nothing here may
    produce one: a number minted by this software would be a fabricated
    attestation reference on a document asserting that a CA signed it, which is
    exactly what the number exists to prevent.

    So this endpoint takes what the member obtained and checks only that its
    SHAPE could be a UDIN. It cannot and does not confirm the number was issued,
    is still live, or belongs to this document — only ICAI's portal can, and the
    pack says so where it prints the number.
    """
    from domain.udin import describe_udin_format, is_valid_udin, normalise_udin

    udin = normalise_udin(data.udin)
    if udin is not None and not is_valid_udin(udin):
        raise HTTPException(status_code=422, detail=describe_udin_format())

    eng = _assert_engagement_scope(current_user, engagement_id)
    # Deliberately NOT gated on _check_engagement_locked: the UDIN is obtained
    # AFTER the statements are signed, which is after the year is locked. A
    # lock that prevented recording it would make the field unreachable in the
    # only state it is ever used in.
    now = datetime.now(timezone.utc).isoformat()
    recorded_at = now if udin else None
    recorded_by = current_user.get("id") if udin else None
    patch = {
        "udin": udin,
        "udin_recorded_at": recorded_at,
        "udin_recorded_by": recorded_by,
    }

    if _USE_MOCK:
        eng.update(patch)
        eng["updated_at"] = now
        return api_response(True, eng)

    from core.supabase_client import get_supabase
    db = get_supabase()
    # The column names are written out rather than spread from `patch`, so
    # tests/test_backend_columns_exist_pg can read them and check them against
    # the real schema — the same reason the accounting-policies reads are
    # spelled out. A spread dict is invisible to that checker, and these three
    # columns are new in migration 290.
    updated = (db.table("year_end_engagements")
               .update({"udin": udin,
                        "udin_recorded_at": recorded_at,
                        "udin_recorded_by": recorded_by,
                        "updated_at": now})
               .eq("id", engagement_id).eq("firm_id", current_user["firm_id"])
               .execute().data or [])
    return api_response(True, updated[0] if updated else {**eng, **patch})


def _assert_transition_allowed(current_status: str, new_status: str,
                               role: str, comment: Optional[str]) -> None:
    """One place both the mock and the real branch ask the same three questions.

    They used to ask them twice, in two copies, and a rule added to one would
    silently not hold in the other — which is how the reopen's Partner-only
    guard and its mandatory reason could have gone in on the real path only.
    """
    if new_status not in _STATUS_TRANSITIONS.get(current_status, []):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot transition from '{current_status}' to '{new_status}'",
        )
    reopening = _is_reopen(current_status, new_status)
    allowed_roles = _REOPEN_ROLES if reopening else _TRANSITION_ROLE_GUARDS.get(new_status, set())
    if role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=(f"Role '{role}' cannot reopen a finalised year-end. "
                    "Only a Partner can." if reopening else
                    f"Role '{role}' cannot set status to '{new_status}'"),
        )
    if reopening and not (comment or "").strip():
        raise HTTPException(status_code=422, detail=REOPEN_REASON_REQUIRED)


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
        _check_engagement_locked(eng, new_status=new_status)
        _assert_transition_allowed(eng["status"], new_status, role, data.comment)
        eng["status"] = new_status
        eng["updated_at"] = datetime.now(timezone.utc).isoformat()
        return api_response(True, eng)

    row = _assert_engagement_scope(current_user, engagement_id)
    _check_engagement_locked(row, new_status=new_status)

    from core.supabase_client import get_supabase
    db = get_supabase()

    _assert_transition_allowed(row["status"], new_status, role, data.comment)

    now = datetime.now(timezone.utc).isoformat()
    # Two literal payloads rather than one built up in a variable: only a
    # literal dict has column names test_backend_columns_exist_pg.py can read
    # and check against the real schema.
    #
    # The reopen branch writes the same columns routers/year_end_reviews.py's
    # reopen writes. Two endpoints reaching one workflow must leave the same
    # record behind, or which one the CA used becomes a fact you have to know
    # to read the history — the two-screens-disagree shape this phase is
    # about. final_approved_by/at are deliberately NOT cleared: they record
    # that the approval happened.
    if _is_reopen(row["status"], new_status):
        updated = (
            db.table("year_end_engagements")
            .update({"status": new_status, "updated_at": now, "locked_at": None,
                     "reopened_at": now, "reopened_by": current_user.get("id"),
                     "reopen_reason": (data.comment or "").strip()})
            .eq("id", engagement_id)
            .execute()
            .data[0]
        )
    else:
        updated = (
            db.table("year_end_engagements")
            .update({"status": new_status, "updated_at": now})
            .eq("id", engagement_id)
            .execute()
            .data[0]
        )

    from services.year_end_workflow_service import (
        lock_year_if_completing, unlock_year_on_reopen)
    lock_year_if_completing(
        db, firm_id, row.get("financial_year"), new_status,
        # public.users.id — the INTERNAL id. client_year_locks.locked_by FKs it
        # (migration 289); auth_user_id was passed here and failed that FK,
        # leaving the engagement locked and the year open.
        actor_id=current_user.get("id"),
        actor_auth_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        # The engagement's own client — a year-end closes one entity's year,
        # never the whole practice's.
        client_id=row.get("client_id"),
    )
    if _is_reopen(row["status"], new_status):
        # After the status write, matching the lock's own ordering. If this
        # fails the engagement reads "approved" with the year still locked,
        # which is recoverable through the ordinary steps — final-approve is
        # idempotent on an already-locked year, and the reopen can then be
        # taken again.
        unlock_year_on_reopen(
            db, firm_id, row.get("financial_year"), (data.comment or "").strip(),
            actor_id=current_user.get("id"),
            actor_auth_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            client_id=row.get("client_id"),
        )

    return api_response(True, updated)
