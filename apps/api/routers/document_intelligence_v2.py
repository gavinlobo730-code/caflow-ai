"""
Document Intelligence v2 — Government notice extraction and management.

Extracts notice details from uploaded text/documents using AI (Groq).
Creates government_notices record + compliance task.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to any government portal.
Human approval (POST /notices/{id}/approve) MUST be called before
a notice is considered actionable.
"""
from __future__ import annotations

import json
import os
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from services.audit_service import log_event
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/document-intelligence-v2", tags=["document_intelligence_v2"])
_logger = logging.getLogger("caflow.doc_intel_v2")

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_NOTICES: dict[str, dict] = {}

# ── AI prompt ─────────────────────────────────────────────────────────────────
_NOTICE_EXTRACTION_PROMPT = """You are a government notice analyser for Indian CAs.
Extract structured data from the notice text below. Return ONLY valid JSON with these fields:
{
  "authority": "issuing authority name e.g. GSTN / Income Tax Department / MCA21 / EPFO",
  "notice_type": "one of: gst_scrutiny / income_tax_demand / income_tax_notice / mca_show_cause / tds_default / customs / other",
  "reference_no": "notice/case reference number",
  "issue_date": "YYYY-MM-DD or null",
  "response_due_date": "YYYY-MM-DD or null",
  "description": "one-sentence summary of what the notice requires"
}

Notice text:
"""


# ── Request Models ─────────────────────────────────────────────────────────────

class ExtractNoticeRequest(BaseModel):
    client_id: str
    document_text: str = Field(..., description="Raw text content of the government notice")
    document_type: Optional[str] = Field(None, description="Optional hint: gst / income_tax / mca / tds")
    source_document_url: Optional[str] = None


class UpdateNoticeStatusRequest(BaseModel):
    status: str  # open, in_progress, responded, closed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_with_groq(document_text: str) -> dict:
    """Call Groq llama-3.3-70b-versatile to extract notice fields."""
    from groq import Groq

    client = Groq(api_key=_GROQ_KEY)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": _NOTICE_EXTRACTION_PROMPT + document_text[:6000]}],
        temperature=0.0,
        max_tokens=512,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _run_notice_extraction(document_text: str) -> tuple[Optional[dict], Optional[str], int]:
    """
    Attempt AI extraction via Groq. Never fabricates notice data: on any
    failure returns (None, reason, http_status). The caller MUST NOT persist
    a government_notices/tasks/notification record when this fails — R2.8/F19.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    if not _GROQ_KEY:
        _logger.info("No GROQ_API_KEY — refusing to fabricate a notice extraction")
        return None, "AI extraction is not configured on the server", 503

    try:
        return _extract_with_groq(document_text), None, 200
    except Exception as e:
        _logger.error("Groq notice extraction failed: %s", e)
        return None, "AI extraction failed — please retry or enter the notice details manually", 502


def _create_task_for_notice(firm_id: str, client_id: str, notice: dict, db=None) -> Optional[str]:
    """Create a compliance task linked to the notice. Returns task_id."""
    try:
        task = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": client_id,
            "title": f"Respond to {notice['notice_type']} notice from {notice['authority']}",
            "description": (
                f"Reference: {notice.get('reference_no', 'N/A')}. "
                f"Due: {notice.get('response_due_date', 'Unknown')}. "
                f"{notice.get('description', '')}"
            ),
            "due_date": notice.get("response_due_date"),
            "priority": "high",
            "status": "todo",
            "source": "AI",
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK or db is None:
            return task["id"]  # mock — no DB write

        db.table("tasks").insert(task).execute()
        return task["id"]
    except Exception as e:
        _logger.warning("Failed to create task for notice: %s", e)
        return None


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
):
    """
    Extract government notice details from text using AI.
    Creates government_notices record + compliance task.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    Call POST /notices/{id}/approve after CA reviews extracted data.
    """
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]

    # R2.8/F19: AI extraction happens BEFORE any persistence. A failed or
    # unavailable extraction returns an honest error here and now — no
    # government_notices row, no task, no partner notification is ever
    # created for fabricated/mock data.
    extracted, error, status_code = _run_notice_extraction(body.document_text)
    if error:
        return JSONResponse(status_code=status_code, content=api_response(False, None, error))

    try:
        db = None
        if not _USE_MOCK:
            from core.supabase_client import get_supabase
            db = get_supabase()

        task_id = _create_task_for_notice(firm_id, body.client_id, extracted, db)

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
            "task_id": task_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_NOTICES[record["id"]] = record
        else:
            db.table("government_notices").insert(record).execute()

        log_event(firm_id, "government_notice", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        timeline_service.log_timeline_event(
            client_id=body.client_id, firm_id=firm_id,
            financial_year="", category="compliance",
            event_type="government_notice_received",
            title=f"Government notice extracted: {extracted.get('notice_type')} from {extracted.get('authority')}",
            severity="warning",
        )

        # Notify partners about new government notice — reuse existing notification infrastructure
        notice_id = record["id"]
        try:
            if not _USE_MOCK:
                from core.supabase_client import get_supabase
                _db = get_supabase()
                # Get all partners for this firm
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
                        "title": f"New Government Notice: {extracted.get('authority', 'Unknown')}",
                        "body": f"Reference: {extracted.get('reference_no', 'N/A')}. Response due: {extracted.get('response_due_date', 'Unknown')}",
                        "type": "compliance_due",
                        "severity": "high",
                        "action_url": "/income-tax/notices",
                        "metadata": {"entity_type": "government_notice", "entity_id": notice_id},
                        "is_read": False,
                        "created_at": datetime.utcnow().isoformat(),
                    }).execute()
        except Exception as _notif_err:
            _logger.warning("Partner notification failed (non-fatal): %s", _notif_err)

        return api_response(True, {
            **record,
            "ca_review_required": True,
            "message": "Notice extracted. CA must review and approve via POST /notices/{id}/approve before taking action.",
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
                  actor_id=current_user.get("id"), new_data=updates)
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
    This is the required human-in-the-loop step.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    Only after CA approval is the notice considered verified and actionable.
    """
    try:
        if _assert_notice_scope(current_user, notice_id) is None:
            return api_response(False, None, "Notice not found")

        firm_id = current_user["firm_id"]
        updates = {
            "ca_approved": True,
            "ca_approved_by": current_user.get("id"),
            "ca_approved_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            if notice_id not in _MOCK_NOTICES:
                return api_response(False, None, "Notice not found")
            _MOCK_NOTICES[notice_id].update(updates)
            rec = _MOCK_NOTICES[notice_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("government_notices").update(updates).eq("id", notice_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "government_notice", notice_id, "ca_approved",
                  actor_id=current_user.get("id"), new_data=updates)
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
        return api_response(True, {**rec, "message": "Notice approved by CA. Now actionable."})
    except Exception as e:
        return api_response(False, None, "Unable to complete document processing. Please try again.")
