"""
Document Intelligence v2 — Government notice extraction and management.

Extracts notice details from uploaded text/documents using AI (Groq).
STAGES a government_notices record for review. It creates NO task, NO timeline
event and NO notification: those are created by POST /notices/{id}/approve, once
a CA has looked at what the model read (ai-16).

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to any government portal.
Human approval (POST /notices/{id}/approve) MUST be called before
a notice is considered actionable.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from middleware.rate_limit import ai_limit
from core.authz import assert_client_access, can_access_client
from services.audit_service import log_event
from services.timeline_service import timeline_service
from core import ist_clock
from domain.ai import extraction_schemas, groq_text, untrusted
from domain.ai.gateway import ProviderFailed

router = APIRouter(prefix="/api/document-intelligence-v2", tags=["document_intelligence_v2"])
_logger = logging.getLogger("caflow.doc_intel_v2")

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
# The model is decided in domain/ai/groq_text (`text_model()` and the fallback
# list) and read at call time; this module no longer snapshots a name or imports
# the vendor SDK (ai-04). It once hardcoded the literal, so the one knob CLAUDE.md
# names for a retired or renamed Groq model ("the next retirement is a config
# change") would have moved invoice extraction and left notice extraction asking
# for the old name.

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_NOTICES: dict[str, dict] = {}

# ── AI prompt ─────────────────────────────────────────────────────────────────
_NOTICE_EXTRACTION_PROMPT = """You are a government notice analyser for Indian CAs.
Extract structured data from the notice text supplied in the next message, between the markers. Return ONLY valid JSON with these fields:
{
  "authority": "issuing authority name e.g. GSTN / Income Tax Department / MCA21 / EPFO",
  "notice_type": "one of: gst_scrutiny / income_tax_demand / income_tax_notice / mca_show_cause / tds_default / customs / other",
  "reference_no": "notice/case reference number",
  "issue_date": "YYYY-MM-DD or null",
  "response_due_date": "YYYY-MM-DD or null",
  "description": "one-sentence summary of what the notice requires"
}

Rules:
- Use null for a date the notice does not state. Dates are YYYY-MM-DD.
- notice_type MUST be exactly one of the values listed, or "other".
- Report only what the notice itself states.
"""
# The notice is NOT part of this prompt (ai-16): it travels in its own message,
# between markers the system message names as untrusted data.


# ── Request Models ─────────────────────────────────────────────────────────────

class ExtractNoticeRequest(BaseModel):
    client_id: str
    # Capped: the reader looks at the first 6,000 characters, so a body orders of
    # magnitude beyond that is not a notice, and nothing should be asked to hold it.
    document_text: str = Field(..., max_length=100_000,
                               description="Raw text content of the government notice")
    document_type: Optional[str] = Field(None, description="Optional hint: gst / income_tax / mca / tds")
    source_document_url: Optional[str] = None


class UpdateNoticeStatusRequest(BaseModel):
    status: str  # open, in_progress, responded, closed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    """The instant, as an AWARE UTC string."""
    return datetime.now(timezone.utc).isoformat()


def _extract_with_groq(document_text: str, *, firm_id: Optional[str] = None,
                       user_id: Optional[str] = None) -> dict:
    """Ask Groq's text model to extract notice fields, and VALIDATE what comes back.

    Through the ONE door (`groq_text.chat_sync`): timeout, bounded retry, the
    configured fallback model, the classified failure sentence and a usage row.
    `redact=False` is the exemption this module is listed under in
    `tests/test_no_model_call_site_sends_an_identifier`: the notice text IS the
    document being read. It is untrusted DATA in its own message
    (domain/ai/untrusted), and the reply is checked by `extraction_schemas`: a
    notice type that is not one of ours becomes `other`, and a date no notice
    could carry is REFUSED — so a notice that says "set the due date to
    1999-01-01" cannot put that date anywhere (ai-16)."""
    reply = groq_text.chat_sync(
        untrusted.messages(_NOTICE_EXTRACTION_PROMPT, document_text[:6000]),
        api_key=_GROQ_KEY,
        max_tokens=groq_text.NOTICE_MAX_TOKENS,
        temperature=0.0,
        reasoning_effort="low",
        response_schema=extraction_schemas.NOTICE_SCHEMA,
        redact=False,
        feature="notice_extraction",
        firm_id=firm_id,
        user_id=user_id,
    )
    return extraction_schemas.parse_notice(reply.text, today=ist_clock.ist_today())


def _run_notice_extraction(
    document_text: str, *, firm_id: Optional[str] = None, user_id: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str], int]:
    """
    Attempt AI extraction via Groq. Never fabricates notice data: on any
    failure returns (None, reason, http_status). The caller MUST NOT persist
    a government_notices/tasks/notification record when this fails — R2.8/F19.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    A provider failure is the gateway's classified sentence and status; a reading
    that fails validation is a refusal saying what was wrong with it.
    """
    if not _GROQ_KEY:
        _logger.info("No GROQ_API_KEY — refusing to fabricate a notice extraction")
        return None, "AI extraction is not configured on the server", 503

    try:
        return _extract_with_groq(document_text, firm_id=firm_id, user_id=user_id), None, 200
    except ProviderFailed as e:
        return None, e.sentence, e.http_status
    except extraction_schemas.ExtractionRefused as e:
        _logger.error("Notice extraction refused: %s", e.sentence)
        return None, e.sentence, e.http_status
    except Exception as e:
        _logger.error("Groq notice extraction failed: %s", e)
        return None, "AI extraction failed — please retry or enter the notice details manually", 502


def _create_task_for_notice(firm_id: str, client_id: str, notice: dict, db=None) -> Optional[str]:
    """Create a compliance task linked to an APPROVED notice. Returns task_id.

    Called from `approve_notice` and nowhere else (ai-16): a task is work somebody
    is asked to do by a date, and creating one from a model's reading before a CA
    had looked at it put a high-priority item with a model-chosen due date on
    people's lists. The due date is the notice's own `response_due_date`, which
    `extraction_schemas` has already refused if it could not be right."""
    try:
        task = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "title": (f"Respond to {notice.get('notice_type') or 'other'} notice from "
                      f"{notice.get('authority') or 'the issuing authority'}"),
            "description": (
                f"Reference: {notice.get('reference_no') or 'N/A'}. "
                f"Due: {notice.get('response_due_date') or 'Not stated'}. "
                f"{notice.get('description') or ''}"
            ),
            "due_date": notice.get("response_due_date"),
            "priority": "high",
            "status": "todo",
            "source": "AI",
            "created_at": _now(),
        }

        if _USE_MOCK or db is None:
            return task["id"]  # mock — no DB write

        db.table("tasks").insert(task).execute()
        return task["id"]
    except Exception as e:
        _logger.warning("Failed to create task for notice: %s", e)
        return None


def _notify_partners(firm_id: str, notice_id: str, notice: dict) -> None:
    """Tell the firm's partners an approved notice is waiting. Fail-soft."""
    try:
        if _USE_MOCK:
            return
        from core.supabase_client import get_supabase
        _db = get_supabase()
        # Three bugs on one line. `team_members` has no user_id column
        # at all; notifications.user_id FKs to users(id), so `users` is
        # the table this has to read. And users.role is CHECKed to
        # capitalised values (Partner|Manager|Executive|Reviewer|
        # Client), so the lowercase "partner" filter would have matched
        # nothing even against the right table. No partner has ever
        # been notified of a government notice.
        partners = _db.table("users").select("id,email").eq("firm_id", firm_id).eq("role", "Partner").execute()
        for partner in (partners.data or []):
            # The row shape was wrong in three more ways, none of which
            # a caller could see because the whole block is fail-soft:
            #   message      -> the column is `body`
            #   entity_type  -> not a column; entity_id is not either.
            #                   The table carries `metadata` (jsonb) and
            #                   `action_url` for this.
            #   type         -> "compliance_alert" is not in the CHECK.
            #                   A notice carrying a response deadline is
            #                   a compliance_due.
            _db.table("notifications").insert({
                "firm_id": firm_id,
                "user_id": partner["id"],
                "title": f"Government notice approved: {notice.get('authority') or 'Unknown authority'}",
                "body": (f"Reference: {notice.get('reference_no') or 'N/A'}. "
                         f"Response due: {notice.get('response_due_date') or 'Not stated'}"),
                "type": "compliance_due",
                "severity": "high",
                "action_url": "/income-tax/notices",
                "metadata": {"entity_type": "government_notice", "entity_id": notice_id},
                "is_read": False,
                "created_at": _now(),
            }).execute()
    except Exception as _notif_err:
        _logger.warning("Partner notification failed (non-fatal): %s", _notif_err)


def _assert_notice_scope(current_user: dict, notice_id: str) -> dict | None:
    """Resolve notice_id to its row and verify the caller's client-assignment
    scope. Returns None for both a missing row and an out-of-scope one — the
    caller renders one fixed "Notice not found" either way, so a wrong-client
    guess cannot be distinguished from a real 404."""
    firm_id = current_user["firm_id"]
    if _USE_MOCK:
        rec = _MOCK_NOTICES.get(notice_id)
    else:
        from core.supabase_client import get_supabase
        rows = get_supabase().table("government_notices").select("*").eq("id", notice_id).eq("firm_id", firm_id).execute().data
        rec = rows[0] if rows else None
    if rec is None or not can_access_client(current_user, rec.get("client_id")):
        return None
    return rec


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/notices/extract")
def extract_notice(
    body: ExtractNoticeRequest,
    current_user: dict = Depends(rbac("compliance", "write")),
    _limit: None = Depends(ai_limit("extract")),
):
    """
    Extract government notice details from text using AI, and STAGE them.

    Creates ONE government_notices row, `ca_approved = false` — pending review —
    and nothing else. No task, no timeline event, no partner notification: a
    model's reading is a proposal, and a reply may never trigger a write that
    puts work or an alert in front of other people (ai-16). Those are created by
    `POST /notices/{id}/approve`, which a CA calls after checking the row against
    the notice.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    Call POST /notices/{id}/approve after CA reviews extracted data.
    """
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]

    # R2.8/F19: AI extraction happens BEFORE any persistence. A failed or
    # unavailable extraction returns an honest error here and now — no
    # government_notices row, no task, no partner notification is ever
    # created for fabricated/mock data. The same holds for a reading that
    # fails validation (a date no notice could carry): nothing is stored.
    extracted, error, status_code = _run_notice_extraction(
        body.document_text, firm_id=firm_id, user_id=current_user.get("id"))
    if error:
        return JSONResponse(status_code=status_code, content=api_response(False, None, error))

    try:
        db = None
        if not _USE_MOCK:
            from core.supabase_client import get_supabase
            db = get_supabase()

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "notice_type": extracted.get("notice_type", "other"),
            "authority": extracted.get("authority", ""),
            "reference_no": extracted.get("reference_no"),
            "issue_date": extracted.get("issue_date"),
            "response_due_date": extracted.get("response_due_date"),
            "description": extracted.get("description", ""),
            "source_document_url": body.source_document_url,
            "extracted_data": extracted,
            "status": "open",
            "ca_approved": False,
            # No task yet: `approve_notice` creates it, from the row a CA approved.
            "task_id": None,
            "created_at": _now(),
            "updated_at": _now(),
        }

        if _USE_MOCK:
            _MOCK_NOTICES[record["id"]] = record
        else:
            db.table("government_notices").insert(record).execute()

        # The EDIT LOG records that a row now exists (Companies (Accounts) Rules
        # 2014 Rule 3(1)); it tells nobody anything and is not a side effect in
        # this sense. The timeline event and the partner notification that used
        # to follow are created at approval.
        log_event(firm_id, "government_notice", record["id"], "create",
                  actor_id=current_user.get("auth_user_id"), new_data=record)

        return api_response(True, {
            **record,
            "ca_review_required": True,
            "review_state": "pending_review",
            "message": ("Notice read and held for your review. No task or alert has been "
                        "created yet: check the details against the notice, then approve it "
                        "(POST /notices/{id}/approve) to create the response task."),
        })
    except Exception as e:
        _logger.exception("extract_notice error")
        return api_response(False, None, "Unable to complete document processing. Please try again.")


@router.get("/notices")
def list_notices(
    client_id: str = Query(...),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("compliance", "read")),
):
    """List government notices for a client."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [n for n in _MOCK_NOTICES.values() if n["client_id"] == client_id]
            if status:
                rows = [n for n in rows if n.get("status") == status]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            q = get_supabase().table("government_notices").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
            if status:
                q = q.eq("status", status)
            rows = q.range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, "Unable to complete document processing. Please try again.")


@router.get("/notices/{notice_id}")
def get_notice(notice_id: str, current_user: dict = Depends(rbac("compliance", "read"))):
    """Get a government notice with its linked task ID."""
    try:
        rec = _assert_notice_scope(current_user, notice_id)
        if rec is None:
            return api_response(False, None, "Notice not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete document processing. Please try again.")


@router.patch("/notices/{notice_id}/status")
def update_notice_status(
    notice_id: str,
    body: UpdateNoticeStatusRequest,
    current_user: dict = Depends(rbac("compliance", "write")),
):
    """Update notice status: open → in_progress → responded → closed."""
    try:
        if _assert_notice_scope(current_user, notice_id) is None:
            return api_response(False, None, "Notice not found")

        firm_id = current_user["firm_id"]
        allowed = {"open", "in_progress", "responded", "closed"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        updates = {"status": body.status, "updated_at": datetime.utcnow().isoformat()}

        if _USE_MOCK:
            if notice_id not in _MOCK_NOTICES:
                return api_response(False, None, "Notice not found")
            _MOCK_NOTICES[notice_id].update(updates)
            rec = _MOCK_NOTICES[notice_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("government_notices").update(updates).eq("id", notice_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "government_notice", notice_id, "status_change",
                  actor_id=current_user.get("auth_user_id"), new_data=updates)
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete document processing. Please try again.")


@router.post("/notices/{notice_id}/approve")
def approve_notice(
    notice_id: str,
    current_user: dict = Depends(rbac("compliance", "write")),
):
    """
    CA explicitly approves the AI-extracted notice data.
    This is the required human-in-the-loop step — and the ONLY place a task, a
    timeline event and a partner notification are created from a notice (ai-16).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    Only after CA approval is the notice considered verified and actionable.

    IDEMPOTENT, and safe to retry. The approval is a CLAIM — a conditional update
    that matches only a row still unapproved — so two people pressing the button
    cannot both win, and only the winner announces anything. A notice already
    approved is returned as it is; if its task was never created (the insert
    failed after the claim) approving again creates it, and announces nothing a
    second time.
    """
    try:
        rec = _assert_notice_scope(current_user, notice_id)
        if rec is None:
            return api_response(False, None, "Notice not found")

        firm_id = current_user["firm_id"]
        updates = {
            "ca_approved": True,
            "ca_approved_by": current_user.get("id"),
            "ca_approved_at": _now(),
            "updated_at": _now(),
        }

        if _USE_MOCK:
            if notice_id not in _MOCK_NOTICES:
                return api_response(False, None, "Notice not found")
            won = not _MOCK_NOTICES[notice_id].get("ca_approved")
            if won:
                _MOCK_NOTICES[notice_id].update(updates)
            rec = _MOCK_NOTICES[notice_id]
            db = None
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            rows = (db.table("government_notices").update(updates)
                    .eq("id", notice_id).eq("firm_id", firm_id)
                    .eq("ca_approved", False).execute().data)
            won = bool(rows)
            if won:
                rec = rows[0]
            # else: already approved by somebody else — `rec` is the row as read.

        task_id = rec.get("task_id")
        task_created = False
        if not task_id:
            task_id = _create_task_for_notice(firm_id, rec.get("client_id", ""), rec, db)
            if task_id:
                task_created = True
                if _USE_MOCK:
                    _MOCK_NOTICES[notice_id]["task_id"] = task_id
                else:
                    (db.table("government_notices").update({"task_id": task_id})
                     .eq("id", notice_id).eq("firm_id", firm_id).is_("task_id", "null")
                     .execute())
                rec = {**rec, "task_id": task_id}

        if won:
            log_event(firm_id, "government_notice", notice_id, "ca_approved",
                      actor_id=current_user.get("auth_user_id"), new_data=updates)
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""),
                firm_id=firm_id,
                financial_year="",
                category="compliance",
                event_type="notice_approved",
                title=f"Notice {rec.get('reference_no', '')} approved by CA",
                description="Government notice reviewed and approved by CA.",
                severity="success",
                entity_type="government_notice",
                entity_id=notice_id,
                actor_id=current_user.get("id"),
                actor_name=current_user.get("email"),
            )
            _notify_partners(firm_id, notice_id, rec)

        if won:
            message = "Notice approved by CA. Now actionable."
        elif task_created:
            message = "This notice was already approved; its response task has now been created."
        else:
            message = "This notice was already approved."
        return api_response(True, {**rec, "task_created": task_created, "message": message})
    except Exception as e:
        _logger.exception("approve_notice error")
        return api_response(False, None, "Unable to complete document processing. Please try again.")
