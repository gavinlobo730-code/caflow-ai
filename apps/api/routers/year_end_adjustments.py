"""
Year End Adjustments router — Phase 6.
Manages year-end adjustment entries with approval workflow.
Adjustment types: accrual, prepayment, provision, reclassification,
                  depreciation_adj, manual.
Status flow: draft → pending_review → approved → posted
             draft → pending_review → rejected

All monetary values: integer paise (BIGINT). Never float.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from core.authz import can_access_client
from services.audit_service import log_event
from services.period_validation_service import period_validation_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.year_end_adjustments")

router = APIRouter(prefix="/year-end", tags=["year-end-adjustments"])

_VALID_ADJUSTMENT_TYPES = {
    "accrual", "prepayment", "provision",
    "reclassification", "depreciation_adj", "manual",
}
_VALID_STATUSES = {"draft", "pending_review", "approved", "posted", "rejected"}

# journal_entries.source_type for an adjustment posted from this router. Snake
# case, matching the values the other posting paths use ("bank_transaction",
# "purchase_payment", "receipt"). Deliberately NOT 'manual': migrations 275/276
# let a MANUAL entry be edited or discarded while its period is open, and a
# year-end adjustment carries its own draft → submitted → approved → posted
# trail, so it is a source document rather than a hand-written entry.
_JOURNAL_SOURCE_TYPE = "year_end_adjustment"

# journal_entries.entry_type is CHECK-constrained (migration 003) to
# Sales / Purchase / Payment / Receipt / Journal / Contra / Opening. An
# adjustment is a Journal; the fact that it came from the year-end workflow is
# carried by _JOURNAL_SOURCE_TYPE, not by inventing an eighth entry type.
_JOURNAL_ENTRY_TYPE = "Journal"


def _journal_reference(adjustment_id: str) -> str:
    """The posting kernel's idempotency key is (firm, client, reference_no,
    entry_date), so the reference has to be derived from something unique to
    this adjustment — the same reasoning as
    phase2_journal_service.purchase_bill_journal_ref. The adjustment's own id
    is unique; reference_no on the adjustment row is free text a CA types and
    two adjustments dated the same day may share it."""
    return f"YEA-{str(adjustment_id)[:8].upper()}"

# ── Mock store ────────────────────────────────────────────────────────────────
# engagement_id → list of adjustment dicts
_MOCK_ADJUSTMENTS: dict[str, list[dict]] = {}


def _get_mock_engagement(engagement_id: str) -> dict:
    """Return the mock engagement row, or {} if not found. Mock mode has no
    engagement store worth enforcing tenancy against — real enforcement runs
    against the live DB (core/authz.py's ENFORCEMENT NOTE)."""
    # Import here to avoid circular imports; mock only
    try:
        from routers.year_end import _MOCK_ENGAGEMENTS
        return _MOCK_ENGAGEMENTS.get(engagement_id, {})
    except Exception:
        return {}


def _assert_engagement_client_mock(current_user: dict, engagement_id: str) -> None:
    """M2 audit finding: every endpoint on this router resolved the
    engagement (for the locked-status check below) but never checked its
    client against the caller's assignment. Permissive when the mock
    engagement is missing, matching this codebase's established mock-mode
    convention (nothing to scope against)."""
    eng = _get_mock_engagement(engagement_id)
    if eng.get("client_id") and not can_access_client(current_user, eng["client_id"]):
        raise HTTPException(status_code=404, detail="Engagement not found")


def _guard_locked_mock(current_user: dict, engagement_id: str) -> None:
    _assert_engagement_client_mock(current_user, engagement_id)
    if _get_mock_engagement(engagement_id).get("status") == "locked":
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


def _assert_engagement_scope(db, engagement_id: str, current_user: dict,
                             *, require_unlocked: bool = False) -> dict:
    """Resolve a year_end_engagements row and 404 unless it belongs to the
    caller's firm and the caller may access its client. With
    require_unlocked (every WRITE endpoint below), also 403s if the
    engagement is locked — reads (list_adjustments) may still see a locked
    engagement's adjustments; only writes are blocked.

    Pre-existing bug found while testing this fix, not itself an M2 issue:
    Supabase's real .single() raises (PGRST116) rather than returning None
    when zero rows match, so a missing or wrong-firm engagement_id was
    crashing this into a 500 instead of the 404 below — the same
    .single()-without-a-try/except shape also appears in health.py,
    relationships.py, lifecycle.py, engagement_letters.py, fixed_assets.py
    and form_26as.py (unaudited, out of scope for this phase)."""
    try:
        row = (
            db.table("year_end_engagements")
            .select("id, status, firm_id, client_id")
            .eq("id", engagement_id)
            .eq("firm_id", current_user["firm_id"])
            .single()
            .execute()
            .data
        )
    except Exception:
        row = None
    if not row or not can_access_client(current_user, row["client_id"]):
        # can_access_client (boolean), not assert_client_access, so a
        # hidden engagement and a missing one raise byte-identical detail
        # text — assert_client_access's generic "Not found" would otherwise
        # distinguish the two even at matching status codes. Checked before
        # the locked-status check so an unassigned caller learns nothing
        # about the engagement's state, not even that it exists.
        raise HTTPException(status_code=404, detail="Engagement not found")
    if require_unlocked and row["status"] == "locked":
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
        _guard_locked_mock(current_user, engagement_id)
        record["client_id"] = "client-001"
        _MOCK_ADJUSTMENTS.setdefault(engagement_id, []).append(record)
        return api_response(True, record)

    from core.supabase_client import get_supabase
    db = get_supabase()
    # F9 fix: client_id is NOT NULL on year_end_adjustments; derive it from the
    # (firm-validated) engagement rather than trusting client input.
    eng = _assert_engagement_scope(db, engagement_id, current_user, require_unlocked=True)
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
    # M2 audit finding: unlike every write endpoint below (which resolves
    # the engagement via _assert_engagement_scope), this read never checked
    # the engagement at all — not even that it belonged to the caller's
    # firm, let alone their assignment.
    if _USE_MOCK:
        _assert_engagement_client_mock(current_user, engagement_id)
        return api_response(True, _MOCK_ADJUSTMENTS.get(engagement_id, []))

    from core.supabase_client import get_supabase
    db = get_supabase()
    _assert_engagement_scope(db, engagement_id, current_user)
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
        _guard_locked_mock(current_user, engagement_id)
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
    _assert_engagement_scope(db, engagement_id, current_user, require_unlocked=True)

    try:
        existing = (
            db.table("year_end_adjustments")
            .select("*")
            .eq("id", adjustment_id)
            .eq("engagement_id", engagement_id)
            .single()
            .execute()
            .data
        )
    except Exception:
        # Same pre-existing .single()-raises-on-zero-rows shape as
        # _assert_engagement_scope above — a missing adjustment_id crashed
        # this into a 500 instead of the 404 below.
        existing = None
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
        _guard_locked_mock(current_user, engagement_id)
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
    _assert_engagement_scope(db, engagement_id, current_user, require_unlocked=True)

    try:
        existing = (
            db.table("year_end_adjustments")
            .select("*")
            .eq("id", adjustment_id)
            .eq("engagement_id", engagement_id)
            .single()
            .execute()
            .data
        )
    except Exception:
        # Same pre-existing .single()-raises-on-zero-rows shape as
        # _assert_engagement_scope above — a missing adjustment_id crashed
        # this into a 500 instead of the 404 below.
        existing = None
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
        _guard_locked_mock(current_user, engagement_id)
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
    _assert_engagement_scope(db, engagement_id, current_user, require_unlocked=True)

    try:
        existing = (
            db.table("year_end_adjustments")
            .select("*")
            .eq("id", adjustment_id)
            .eq("engagement_id", engagement_id)
            .single()
            .execute()
            .data
        )
    except Exception:
        # Same pre-existing .single()-raises-on-zero-rows shape as
        # _assert_engagement_scope above — a missing adjustment_id crashed
        # this into a 500 instead of the 404 below.
        existing = None
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
    Post an approved adjustment — creates a journal entry through the single
    posting kernel (phase2_journal_service._create_journal).
    source_type='year_end_adjustment' tags the journal entry for traceability.
    """
    now = datetime.now(timezone.utc).isoformat()

    if _USE_MOCK:
        _guard_locked_mock(current_user, engagement_id)
        items = _MOCK_ADJUSTMENTS.get(engagement_id, [])
        adj = next((a for a in items if a["id"] == adjustment_id), None)
        if not adj:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        if adj["status"] != "approved":
            raise HTTPException(status_code=422, detail="Only approved adjustments can be posted")
        # task #240 fix: posting was the only GL-affecting action on this
        # router with no locked-financial-year check — every other posting
        # endpoint (fixed_assets.py, purchase_bills.py, ...) blocks postings
        # dated into an already-locked FY; this let a year-end adjustment
        # slip a journal entry into a locked period.
        period_validation_service.validate_posting_date(current_user["firm_id"], adj["adjustment_date"])
        mock_journal_id = str(uuid.uuid4())
        adj["status"] = "posted"
        adj["posted_by"] = current_user.get("auth_user_id")
        adj["posted_at"] = now
        adj["journal_entry_id"] = mock_journal_id
        adj["updated_at"] = now
        return api_response(True, adj)

    from core.supabase_client import get_supabase
    from services.phase2_journal_service import phase2_journal_service
    db = get_supabase()
    eng = _assert_engagement_scope(db, engagement_id, current_user, require_unlocked=True)

    try:
        existing = (
            db.table("year_end_adjustments")
            .select("*")
            .eq("id", adjustment_id)
            .eq("engagement_id", engagement_id)
            .single()
            .execute()
            .data
        )
    except Exception:
        # Same pre-existing .single()-raises-on-zero-rows shape as
        # _assert_engagement_scope above — a missing adjustment_id crashed
        # this into a 500 instead of the 404 below.
        existing = None
    if not existing:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if existing["status"] != "approved":
        raise HTTPException(status_code=422, detail="Only approved adjustments can be posted")

    # task #240 fix: block posting into an already-locked financial year —
    # see the identical check in the mock branch above for context.
    period_validation_service.validate_posting_date(current_user["firm_id"], existing["adjustment_date"])

    # ── The journal goes through the ONE posting kernel ───────────────────────
    # This used to assemble a journal_entries dict here, insert it, then insert
    # the two journal_lines in a separate statement. Two things were wrong with
    # that, and the second is the one that matters.
    #
    # (a) The columns were not the live ones. It sent `source` and
    #     `source_ref_id`; journal_entries has `source_type` and `source_id`
    #     (migration 104). It omitted `client_id` and `entry_type`, both NOT
    #     NULL with no default (migration 003). So in production the insert
    #     failed on EVERY approved adjustment: the CA worked the whole
    #     workflow — draft, submitted, approved — clicked Post and got a 500,
    #     nothing reached the ledger, and the Balance Sheet and P&L they went
    #     on to sign were the UNADJUSTED ones.
    #
    # (b) It was a second write path into the general ledger, which CLAUDE.md
    #     forbids outright. _create_journal asserts double-entry balance,
    #     refuses a zero-value entry, checks the CLIENT's own year lock
    #     (migration 289 — the firm-level lock above is a different lock),
    #     dedupes on (firm, client, reference_no, entry_date), and writes the
    #     header and every line in ONE transaction via post_journal_atomic
    #     (migration 152). The hand-rolled path had none of that — and a line
    #     insert failing after the header committed stranded an orphan header
    #     that the immutability trigger makes unrepairable.
    #
    # Routing through the kernel fixes (a) as a side effect: the kernel is the
    # thing that knows what the columns are called.
    #
    # client_id comes from the (firm-validated) engagement for the same reason
    # create_adjustment derives it from there rather than from the request.
    client_id = eng.get("client_id") or existing.get("client_id")
    amount_paise = existing["amount_paise"]          # integer paise — BIGINT
    lines = [
        {
            "account_id":   existing["debit_account_id"],
            "debit_paise":  amount_paise,
            "credit_paise": 0,
            "narration":    existing["description"],
        },
        {
            "account_id":   existing["credit_account_id"],
            "debit_paise":  0,
            "credit_paise": amount_paise,
            "narration":    existing["description"],
        },
    ]

    # Claim the posting FIRST, conditionally on the row still being `approved`
    # — the same discipline as fixed_assets.dispose_asset and
    # purchase_bills.receive_purchase_bill. A second click, or a retry that
    # raced the first, matches zero rows and 409s before touching the ledger.
    claim = (
        db.table("year_end_adjustments")
        .update({
            "status":     "posted",
            "posted_by":  current_user.get("auth_user_id"),
            "posted_at":  now,
            "updated_at": now,
        })
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .eq("status", "approved")
        .execute()
        .data
    )
    if not claim:
        raise HTTPException(status_code=409, detail="This adjustment has already been posted")

    def _rollback_claim() -> None:
        """Nothing reached the ledger, so the adjustment must not be left
        `posted` with no journal behind it — put it back where a retry can
        pick it up."""
        db.table("year_end_adjustments").update({
            "status":     "approved",
            "posted_by":  None,
            "posted_at":  None,
            "updated_at": now,
        }).eq("id", adjustment_id).eq("engagement_id", engagement_id).execute()

    try:
        journal_id = phase2_journal_service._create_journal(
            db=db,
            firm_id=current_user["firm_id"],
            client_id=client_id,
            entry_date=existing["adjustment_date"],
            reference_no=_journal_reference(adjustment_id),
            narration=existing["description"],
            entry_type=_JOURNAL_ENTRY_TYPE,
            lines=lines,
            is_posted=True,
            source_type=_JOURNAL_SOURCE_TYPE,
            source_id=adjustment_id,
            # journal_entries.created_by FKs public.users.id (the internal user
            # id), NOT the Supabase auth id — see CLAUDE.md. year_end_adjustments
            # .posted_by above has no FK and has always carried auth_user_id;
            # the two columns genuinely hold different identifiers.
            created_by=current_user.get("id"),
        )
        if not journal_id:
            raise RuntimeError("year-end adjustment journal posting returned no id")
    except Exception as jerr:
        _rollback_claim()
        if isinstance(jerr, HTTPException):
            # A deliberate refusal (a closed client year, say) carries a
            # sentence the CA can act on; collapsing it into a generic message
            # would tell them to retry something that can never succeed.
            raise
        if isinstance(jerr, ValueError):
            # The kernel's own rejections — imbalance, a zero-value entry, a
            # client financial year already finalised.
            raise HTTPException(status_code=422, detail=str(jerr))
        _logger.error(
            "post_adjustment: journal posting failed for adjustment %s; the "
            "adjustment was rolled back to approved: %s", adjustment_id, jerr,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Could not post this year-end adjustment — nothing was written "
                   "to the ledger. The failure has been logged for the team.",
        )

    # Link the journal only after it exists, so journal_entry_id never names an
    # entry that was not written.
    linked = (
        db.table("year_end_adjustments")
        .update({"journal_entry_id": journal_id, "updated_at": now})
        .eq("id", adjustment_id)
        .eq("engagement_id", engagement_id)
        .execute()
        .data
    )
    updated = linked[0] if linked else {**claim[0], "journal_entry_id": journal_id}
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
        _guard_locked_mock(current_user, engagement_id)
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
    _assert_engagement_scope(db, engagement_id, current_user, require_unlocked=True)

    try:
        existing = (
            db.table("year_end_adjustments")
            .select("*")
            .eq("id", adjustment_id)
            .eq("engagement_id", engagement_id)
            .single()
            .execute()
            .data
        )
    except Exception:
        # Same pre-existing .single()-raises-on-zero-rows shape as
        # _assert_engagement_scope above — a missing adjustment_id crashed
        # this into a 500 instead of the 404 below.
        existing = None
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
