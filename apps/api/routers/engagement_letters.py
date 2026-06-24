"""
Engagement Letter Management System.

Covers the full engagement letter lifecycle for a CA firm:
  Draft → Generated → Sent → Viewed → Signed / Rejected / Expired

These engagement letters are DISTINCT from fee_engagements (the table used by
the existing engagements.py router for ongoing service engagement tracking).

All monetary values are stored in integer paise (₹1 = 100 paise) — never float.
CGST Act Section 31 requires written engagement documentation before service
commencement. These letters satisfy that requirement.

CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT any letter without explicit CA approval.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, date
import uuid

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

router = APIRouter(prefix="/api/engagement-letters", tags=["engagement-letters"])


# ─── In-memory mock stores ────────────────────────────────────────────────────

_MOCK_TEMPLATES:   list[dict] = []
_MOCK_ENGAGEMENTS: list[dict] = []
_MOCK_EVENTS:      list[dict] = []


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _advance_lead(lead_id, firm_id, target_stage, current_user) -> None:
    """
    Auto-advance the linked lead's pipeline stage after an engagement-letter
    transition (Objectives 1 & 2). No-op when there is no lead. The lazy import
    avoids a circular import with the lifecycle router, and any failure is
    swallowed — an engagement action must never fail because of a sync issue.
    """
    if not lead_id:
        return
    try:
        from routers.lifecycle import advance_lead_stage
        advance_lead_stage(
            lead_id, firm_id, target_stage,
            actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
        )
    except Exception:
        pass


# ─── Default templates ────────────────────────────────────────────────────────

_DEFAULT_TEMPLATES = [
    {
        "name": "GST Compliance Engagement",
        "service_type": "GST Compliance",
        "content": """<h2>Engagement Letter — GST Compliance Services</h2>
<p>Date: {{engagement_date}}</p>
<p>Dear {{client_name}},</p>
<p>We, <strong>{{firm_name}}</strong>, are pleased to confirm our engagement to provide
GST Compliance services to your organisation. This letter sets out the terms of our
engagement as agreed between us.</p>
<h3>Scope of Services</h3>
<ul>
  <li>Preparation and filing of GSTR-1 (outward supplies) by the 11th of each month
      — CGST Act Section 37</li>
  <li>Preparation and filing of GSTR-3B (summary return) by the 20th of each month
      — CGST Act Section 39</li>
  <li>Reconciliation of GSTR-2B with purchase register on a monthly basis</li>
  <li>Assistance with GST notices and departmental correspondence</li>
  <li>Annual GSTR-9 filing by 31st December — CGST Act Section 44</li>
</ul>
<h3>Fee</h3>
<p>Our professional fee for the above services is <strong>₹{{engagement_fee}} per month</strong>
(exclusive of applicable taxes), payable by the 10th of each month.</p>
<h3>Client Responsibilities</h3>
<p>You agree to provide all invoices, purchase documents, and bank statements by the
5th of each month to enable timely filing.</p>
<h3>Term</h3>
<p>This engagement commences on {{start_date}} and continues until terminated by either
party with 30 days' written notice.</p>
<p>Please sign and return a copy of this letter to confirm your acceptance.</p>
<br/>
<p>Yours sincerely,</p>
<p><strong>{{partner_name}}</strong><br/>Authorised Partner<br/>{{firm_name}}</p>
<p>Client Acceptance: _________________________ Date: _____________</p>""",
        "is_default": True,
    },
    {
        "name": "Income Tax Return Engagement",
        "service_type": "Income Tax Return",
        "content": """<h2>Engagement Letter — Income Tax Return Services</h2>
<p>Date: {{engagement_date}}</p>
<p>Dear {{client_name}},</p>
<p>We, <strong>{{firm_name}}</strong>, confirm our engagement to prepare and file your
Income Tax Return for the relevant Assessment Year.</p>
<h3>Scope of Services</h3>
<ul>
  <li>Computation of total income and tax liability — IT Act Section 139</li>
  <li>Preparation of ITR in the applicable form (ITR-1 / ITR-2 / ITR-3 / ITR-4 as
      applicable to your situation)</li>
  <li>Verification and e-filing on the Income Tax portal</li>
  <li>Assistance with assessment proceedings if any notices are received under
      IT Act Section 143(1) / 143(2)</li>
  <li>PAN verification and Form 26AS reconciliation</li>
</ul>
<h3>Fee</h3>
<p>Our professional fee for the above services is <strong>₹{{engagement_fee}} per annum</strong>
(exclusive of applicable taxes).</p>
<h3>Client Responsibilities</h3>
<p>You shall provide Form 16 / Form 16A, bank statements, investment proofs, and all
relevant financial documents within 7 days of our request.</p>
<p>Please confirm your acceptance by signing below.</p>
<br/>
<p>Yours sincerely,</p>
<p><strong>{{partner_name}}</strong><br/>Authorised Partner<br/>{{firm_name}}</p>
<p>Client Acceptance: _________________________ Date: _____________</p>""",
        "is_default": True,
    },
    {
        "name": "Tax Audit Engagement",
        "service_type": "Tax Audit",
        "content": """<h2>Engagement Letter — Tax Audit Services</h2>
<p>Date: {{engagement_date}}</p>
<p>Dear {{client_name}},</p>
<p>We, <strong>{{firm_name}}</strong>, confirm our appointment as Tax Auditors for your
organisation under Section 44AB of the Income Tax Act, 1961.</p>
<h3>Scope of Services</h3>
<ul>
  <li>Audit of books of accounts under IT Act Section 44AB</li>
  <li>Preparation and certification of Form 3CA/3CB and Form 3CD</li>
  <li>Verification of tax computations, depreciation schedules, and deductions</li>
  <li>Reporting of specified domestic transactions if applicable (IT Act Section 92E)</li>
  <li>E-filing of Tax Audit Report on the Income Tax portal by 30th September</li>
</ul>
<h3>Fee</h3>
<p>Our professional fee for the Tax Audit is <strong>₹{{engagement_fee}}</strong>
(exclusive of applicable taxes), payable on completion of the audit.</p>
<h3>Independence</h3>
<p>We confirm that we are independent of your organisation as required by ICAI
Standards on Auditing and the Income Tax Act.</p>
<p>Please sign and return to confirm your acceptance.</p>
<br/>
<p>Yours sincerely,</p>
<p><strong>{{partner_name}}</strong><br/>Authorised Partner<br/>{{firm_name}}</p>
<p>Client Acceptance: _________________________ Date: _____________</p>""",
        "is_default": True,
    },
    {
        "name": "ROC Compliance Engagement",
        "service_type": "ROC Compliance",
        "content": """<h2>Engagement Letter — ROC Compliance Services</h2>
<p>Date: {{engagement_date}}</p>
<p>Dear {{client_name}},</p>
<p>We, <strong>{{firm_name}}</strong>, are pleased to confirm our engagement for
Registrar of Companies (ROC) compliance services under the Companies Act, 2013.</p>
<h3>Scope of Services</h3>
<ul>
  <li>Annual return filing — Form MGT-7 (Companies Act 2013, Section 92)</li>
  <li>Financial statements filing — Form AOC-4 (Companies Act 2013, Section 137)</li>
  <li>Director KYC (DIR-3 KYC) annually</li>
  <li>Event-based filings: change in directors, address, authorised capital</li>
  <li>Maintenance of statutory registers</li>
  <li>Board meeting minutes and secretarial record maintenance</li>
</ul>
<h3>Fee</h3>
<p>Our professional fee for the above services is <strong>₹{{engagement_fee}} per annum</strong>
(exclusive of applicable taxes).</p>
<p>Please sign below to confirm your acceptance.</p>
<br/>
<p>Yours sincerely,</p>
<p><strong>{{partner_name}}</strong><br/>Authorised Partner<br/>{{firm_name}}</p>
<p>Client Acceptance: _________________________ Date: _____________</p>""",
        "is_default": True,
    },
    {
        "name": "Bookkeeping Engagement",
        "service_type": "Bookkeeping",
        "content": """<h2>Engagement Letter — Bookkeeping Services</h2>
<p>Date: {{engagement_date}}</p>
<p>Dear {{client_name}},</p>
<p>We, <strong>{{firm_name}}</strong>, confirm our engagement to provide bookkeeping
and accounting services for your organisation.</p>
<h3>Scope of Services</h3>
<ul>
  <li>Recording of all accounting transactions on a monthly basis</li>
  <li>Bank reconciliation statements</li>
  <li>Preparation of monthly trial balance and P&amp;L statement</li>
  <li>Accounts receivable and payable management</li>
  <li>Preparation of financials per Schedule III of Companies Act 2013</li>
  <li>TDS computation and deduction tracking — IT Act Chapter XVII-B</li>
</ul>
<h3>Fee</h3>
<p>Our professional fee for the above services is <strong>₹{{engagement_fee}} per month</strong>
(exclusive of applicable taxes), payable by the 15th of each month.</p>
<h3>Client Responsibilities</h3>
<p>You shall provide all source documents (invoices, receipts, bank statements) by
the 5th of each month.</p>
<p>Please sign below to confirm your acceptance.</p>
<br/>
<p>Yours sincerely,</p>
<p><strong>{{partner_name}}</strong><br/>Authorised Partner<br/>{{firm_name}}</p>
<p>Client Acceptance: _________________________ Date: _____________</p>""",
        "is_default": True,
    },
    {
        "name": "Virtual CFO Engagement",
        "service_type": "Virtual CFO",
        "content": """<h2>Engagement Letter — Virtual CFO Services</h2>
<p>Date: {{engagement_date}}</p>
<p>Dear {{client_name}},</p>
<p>We, <strong>{{firm_name}}</strong>, are pleased to confirm our engagement to provide
Virtual CFO (Chief Financial Officer) services to your organisation.</p>
<h3>Scope of Services</h3>
<ul>
  <li>Monthly MIS reports: P&amp;L, Balance Sheet, Cash Flow statement</li>
  <li>Budget preparation, variance analysis, and financial forecasting</li>
  <li>Working capital management and cash flow planning</li>
  <li>Statutory compliance oversight (GST, TDS, ROC, Income Tax)</li>
  <li>Liaison with banks, investors, and statutory authorities</li>
  <li>Internal audit and risk management advisory</li>
  <li>Due diligence support for fundraising or transactions</li>
</ul>
<h3>Fee</h3>
<p>Our professional retainer fee is <strong>₹{{engagement_fee}} per month</strong>
(exclusive of applicable taxes), payable in advance by the 1st of each month.</p>
<h3>Exclusions</h3>
<p>Out-of-pocket expenses (travel, regulatory fees) shall be billed at actuals with
prior approval.</p>
<p>Please sign below to confirm your acceptance.</p>
<br/>
<p>Yours sincerely,</p>
<p><strong>{{partner_name}}</strong><br/>Authorised Partner<br/>{{firm_name}}</p>
<p>Client Acceptance: _________________________ Date: _____________</p>""",
        "is_default": True,
    },
]


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class TemplateIn(BaseModel):
    name: str
    service_type: str
    content: str
    is_default: bool = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    service_type: Optional[str] = None
    content: Optional[str] = None
    is_default: Optional[bool] = None


class EngagementIn(BaseModel):
    title: str
    template_id: Optional[str] = None
    lead_id: Optional[str] = None
    client_id: Optional[str] = None
    fee_amount_paise: int = 0
    start_date: Optional[str] = None    # ISO date string
    expiry_date: Optional[str] = None   # ISO date string
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None
    notes: Optional[str] = None


class EngagementUpdate(BaseModel):
    title: Optional[str] = None
    fee_amount_paise: Optional[int] = None
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None


class SignIn(BaseModel):
    signed_pdf_url: Optional[str] = None   # URL to uploaded signed copy


class RejectIn(BaseModel):
    rejection_notes: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _render_merge_fields(content: str, fields: dict) -> str:
    """Replace {{key}} placeholders with their values. Unknown keys are left blank."""
    for key, value in fields.items():
        content = content.replace("{{" + key + "}}", str(value or ""))
    return content


def _next_engagement_no(db, firm_id: str) -> str:
    """Generate sequential engagement number like EL-2026-0001."""
    year = datetime.now(timezone.utc).year
    if not db:
        n = len(_MOCK_ENGAGEMENTS) + 1
        return f"EL-{year}-{n:04d}"
    res = (
        db.table("engagements")
        .select("engagement_number")
        .eq("firm_id", firm_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if rows:
        try:
            parts = rows[0]["engagement_number"].split("-")
            last_no = int(parts[-1])
            return f"EL-{year}-{last_no + 1:04d}"
        except Exception:
            pass
    return f"EL-{year}-0001"


def _format_fee(fee_amount_paise: int) -> str:
    """Format paise as ₹X — integer arithmetic only, never float."""
    # All monetary values in integer paise — CGST Act compliance
    rupees = fee_amount_paise // 100
    paise_remainder = fee_amount_paise % 100
    if paise_remainder:
        return f"₹{rupees}.{paise_remainder:02d}"
    return f"₹{rupees}"


def _seed_default_templates(db, firm_id: str, created_by: Optional[str]) -> list[dict]:
    """Seed the 6 default templates for a firm that has none."""
    now = datetime.now(timezone.utc).isoformat()
    seeded = []
    for tmpl in _DEFAULT_TEMPLATES:
        row = {
            "id":           str(uuid.uuid4()),
            "firm_id":      firm_id,
            "name":         tmpl["name"],
            "service_type": tmpl["service_type"],
            "content":      tmpl["content"],
            "version":      1,
            "is_default":   tmpl["is_default"],
            "is_deleted":   False,
            "created_by":   created_by,
            "created_at":   now,
            "updated_at":   now,
        }
        seeded.append(row)
    if not db:
        _MOCK_TEMPLATES.extend(seeded)
    else:
        try:
            db.table("engagement_templates").insert(seeded).execute()
        except Exception:
            pass
    return seeded


def _log_engagement_event(
    db, engagement_id: str, firm_id: str, event_type: str,
    user_id: Optional[str], metadata: Optional[dict] = None
) -> None:
    """Insert an engagement_events row. Non-fatal — never raises."""
    now = datetime.now(timezone.utc).isoformat()
    event_row = {
        "id":             str(uuid.uuid4()),
        "engagement_id":  engagement_id,
        "firm_id":        firm_id,
        "event_type":     event_type,
        "user_id":        user_id,
        "metadata":       metadata,
        "created_at":     now,
    }
    if not db:
        _MOCK_EVENTS.append(event_row)
    else:
        try:
            db.table("engagement_events").insert(event_row).execute()
        except Exception:
            pass


# ─── Template Endpoints ───────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    List all non-deleted engagement letter templates for the firm.
    If no templates exist, seeds 6 professional defaults.
    """
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        templates = [
            t for t in _MOCK_TEMPLATES
            if t.get("firm_id") == firm_id and not t.get("is_deleted")
        ]
        if not templates:
            templates = _seed_default_templates(db, firm_id, current_user.get("auth_user_id"))
        return api_response(True, {"templates": templates, "total": len(templates)})

    try:
        res = (
            db.table("engagement_templates")
            .select("*")
            .eq("firm_id", firm_id)
            .eq("is_deleted", False)
            .order("created_at")
            .execute()
        )
        templates = res.data or []
        if not templates:
            templates = _seed_default_templates(db, firm_id, current_user.get("auth_user_id"))
            # Re-fetch after seeding so we return DB rows with DB timestamps
            res2 = (
                db.table("engagement_templates")
                .select("*")
                .eq("firm_id", firm_id)
                .eq("is_deleted", False)
                .order("created_at")
                .execute()
            )
            templates = res2.data or templates
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return api_response(True, {"templates": templates, "total": len(templates)})


@router.post("/templates")
def create_template(
    body: TemplateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Create a new engagement letter template. Manager+."""
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id":           str(uuid.uuid4()),
        "firm_id":      firm_id,
        "name":         body.name,
        "service_type": body.service_type,
        "content":      body.content,
        "version":      1,
        "is_default":   body.is_default,
        "is_deleted":   False,
        "created_by":   current_user.get("auth_user_id"),
        "created_at":   now,
        "updated_at":   now,
    }
    if not db:
        _MOCK_TEMPLATES.append(row)
        return api_response(True, {"template": row})

    try:
        res = db.table("engagement_templates").insert(row).execute()
        created = (res.data or [row])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        log_event(firm_id, "engagement_template", created["id"], "create",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data={"name": body.name, "service_type": body.service_type})
    except Exception:
        pass
    return api_response(True, {"template": created})


@router.get("/templates/{template_id}")
def get_template(
    template_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Get a single engagement letter template."""
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        tmpl = next(
            (t for t in _MOCK_TEMPLATES
             if t["id"] == template_id and t.get("firm_id") == firm_id
             and not t.get("is_deleted")),
            None,
        )
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        return api_response(True, {"template": tmpl})

    try:
        res = (
            db.table("engagement_templates")
            .select("*")
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .eq("is_deleted", False)
            .single()
            .execute()
        )
        tmpl = res.data
    except Exception:
        tmpl = None
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return api_response(True, {"template": tmpl})


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    body: TemplateUpdate,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Update an engagement letter template. Increments version. Manager+."""
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    updates["updated_at"] = now

    if not db:
        tmpl = next(
            (t for t in _MOCK_TEMPLATES
             if t["id"] == template_id and t.get("firm_id") == firm_id
             and not t.get("is_deleted")),
            None,
        )
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        old_version = tmpl.get("version", 1)
        tmpl.update(updates)
        tmpl["version"] = old_version + 1
        return api_response(True, {"template": tmpl})

    # Fetch existing for version bump
    try:
        existing_res = (
            db.table("engagement_templates")
            .select("version")
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .eq("is_deleted", False)
            .single()
            .execute()
        )
        existing = existing_res.data
    except Exception:
        existing = None
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    updates["version"] = existing["version"] + 1
    try:
        res = (
            db.table("engagement_templates")
            .update(updates)
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        updated = (res.data or [{}])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        log_event(firm_id, "engagement_template", template_id, "update",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data=updates)
    except Exception:
        pass
    return api_response(True, {"template": updated})


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Soft-delete an engagement letter template (sets is_deleted=true). Manager+."""
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        tmpl = next(
            (t for t in _MOCK_TEMPLATES
             if t["id"] == template_id and t.get("firm_id") == firm_id
             and not t.get("is_deleted")),
            None,
        )
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl["is_deleted"] = True
        tmpl["updated_at"] = now
        return api_response(True, {"message": "Template deleted", "template_id": template_id})

    try:
        existing_res = (
            db.table("engagement_templates")
            .select("id")
            .eq("id", template_id)
            .eq("firm_id", firm_id)
            .eq("is_deleted", False)
            .single()
            .execute()
        )
        existing = existing_res.data
    except Exception:
        existing = None
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        db.table("engagement_templates").update({
            "is_deleted": True,
            "updated_at": now,
        }).eq("id", template_id).eq("firm_id", firm_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        log_event(firm_id, "engagement_template", template_id, "delete",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data={"is_deleted": True})
    except Exception:
        pass
    return api_response(True, {"message": "Template deleted", "template_id": template_id})


# ─── Engagement Letter Endpoints ──────────────────────────────────────────────

@router.get("")
def list_engagements(
    status: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("client", "read")),
):
    """List engagement letters with optional filters by status, lead_id, or client_id."""
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        result = [e for e in _MOCK_ENGAGEMENTS if e.get("firm_id") == firm_id]
        if status:
            result = [e for e in result if e.get("status") == status]
        if lead_id:
            result = [e for e in result if e.get("lead_id") == lead_id]
        if client_id:
            result = [e for e in result if e.get("client_id") == client_id]
        return api_response(True, {"engagements": result, "total": len(result)})

    try:
        q = (
            db.table("engagements")
            .select("*")
            .eq("firm_id", firm_id)
        )
        if status:
            q = q.eq("status", status)
        if lead_id:
            q = q.eq("lead_id", lead_id)
        if client_id:
            q = q.eq("client_id", client_id)
        res = q.order("created_at", desc=True).execute()
        engagements = res.data or []
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return api_response(True, {"engagements": engagements, "total": len(engagements)})


@router.post("")
def create_engagement(
    body: EngagementIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Create a new engagement letter in Draft status. Manager+.
    Auto-generates engagement_number (EL-YYYY-NNNN).
    If template_id is provided, copies template content into engagement.content.
    All fees stored in integer paise — CGST Act Section 31.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()
    engagement_id = str(uuid.uuid4())
    engagement_number = _next_engagement_no(db, firm_id)

    # Resolve template content if template_id provided
    content = ""
    if body.template_id:
        if not db:
            tmpl = next(
                (t for t in _MOCK_TEMPLATES
                 if t["id"] == body.template_id and t.get("firm_id") == firm_id
                 and not t.get("is_deleted")),
                None,
            )
        else:
            try:
                tmpl_res = (
                    db.table("engagement_templates")
                    .select("content")
                    .eq("id", body.template_id)
                    .eq("firm_id", firm_id)
                    .eq("is_deleted", False)
                    .single()
                    .execute()
                )
                tmpl = tmpl_res.data
            except Exception:
                tmpl = None
        if tmpl:
            content = tmpl.get("content", "")

    # fee_amount_paise must be a non-negative integer — CGST Act compliance
    fee_paise = int(body.fee_amount_paise)
    if fee_paise < 0:
        raise HTTPException(status_code=422, detail="fee_amount_paise must be non-negative")

    row = {
        "id":                engagement_id,
        "firm_id":           firm_id,
        "lead_id":           body.lead_id,
        "client_id":         body.client_id,
        "template_id":       body.template_id,
        "engagement_number": engagement_number,
        "title":             body.title,
        "status":            "Draft",
        "content":           content,
        "fee_amount_paise":  fee_paise,
        "start_date":        body.start_date,
        "expiry_date":       body.expiry_date,
        "recipient_name":    body.recipient_name,
        "recipient_email":   body.recipient_email,
        "generated_pdf_url": None,
        "signed_pdf_url":    None,
        "sent_at":           None,
        "viewed_at":         None,
        "signed_at":         None,
        "rejected_at":       None,
        "rejection_notes":   None,
        "created_by":        current_user.get("auth_user_id"),
        "created_at":        now,
        "updated_at":        now,
    }

    if not db:
        _MOCK_ENGAGEMENTS.append(row)
        _log_engagement_event(db, engagement_id, firm_id, "created",
                              current_user.get("auth_user_id"))
        # Objective 1: creating a letter advances the linked lead to "Engagement Drafted".
        _advance_lead(row.get("lead_id"), firm_id, "Engagement Drafted", current_user)
        return api_response(True, {"engagement": row})

    try:
        res = db.table("engagements").insert(row).execute()
        created = (res.data or [row])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log_engagement_event(db, engagement_id, firm_id, "created",
                          current_user.get("auth_user_id"),
                          {"title": body.title, "engagement_number": engagement_number})
    try:
        log_event(firm_id, "engagement", engagement_id, "create",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data={"title": body.title, "engagement_number": engagement_number,
                             "fee_amount_paise": fee_paise})
    except Exception:
        pass
    # Objective 1: creating a letter advances the linked lead to "Engagement Drafted".
    _advance_lead(created.get("lead_id") or body.lead_id, firm_id, "Engagement Drafted", current_user)
    return api_response(True, {"engagement": created})


@router.get("/{engagement_id}")
def get_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Get a single engagement letter with its audit event history."""
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        eng = next(
            (e for e in _MOCK_ENGAGEMENTS
             if e["id"] == engagement_id and e.get("firm_id") == firm_id),
            None,
        )
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        events = [ev for ev in _MOCK_EVENTS if ev.get("engagement_id") == engagement_id]
        return api_response(True, {"engagement": eng, "events": events})

    try:
        eng_res = (
            db.table("engagements")
            .select("*")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
        )
        eng = eng_res.data
    except Exception:
        eng = None
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")

    try:
        ev_res = (
            db.table("engagement_events")
            .select("*")
            .eq("engagement_id", engagement_id)
            .order("created_at")
            .execute()
        )
        events = ev_res.data or []
    except Exception:
        events = []

    return api_response(True, {"engagement": eng, "events": events})


@router.patch("/{engagement_id}")
def update_engagement(
    engagement_id: str,
    body: EngagementUpdate,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Update an engagement letter. Only allowed when status is Draft. Manager+."""
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    # Validate paise if provided
    if "fee_amount_paise" in updates:
        updates["fee_amount_paise"] = int(updates["fee_amount_paise"])
        if updates["fee_amount_paise"] < 0:
            raise HTTPException(status_code=422, detail="fee_amount_paise must be non-negative")

    updates["updated_at"] = now

    if not db:
        eng = next(
            (e for e in _MOCK_ENGAGEMENTS
             if e["id"] == engagement_id and e.get("firm_id") == firm_id),
            None,
        )
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        if eng["status"] != "Draft":
            raise HTTPException(status_code=409,
                                detail=f"Cannot update engagement in '{eng['status']}' status. Only Draft engagements can be updated.")
        old_data = {k: eng.get(k) for k in updates}
        eng.update(updates)
        _log_engagement_event(db, engagement_id, firm_id, "updated",
                              current_user.get("auth_user_id"))
        return api_response(True, {"engagement": eng})

    try:
        existing_res = (
            db.table("engagements")
            .select("status")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
        )
        existing = existing_res.data
    except Exception:
        existing = None
    if not existing:
        raise HTTPException(status_code=404, detail="Engagement not found")

    if existing["status"] != "Draft":
        raise HTTPException(status_code=409,
                            detail=f"Cannot update engagement in '{existing['status']}' status. Only Draft engagements can be updated.")

    try:
        res = (
            db.table("engagements")
            .update(updates)
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        updated = (res.data or [{}])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log_engagement_event(db, engagement_id, firm_id, "updated",
                          current_user.get("auth_user_id"), updates)
    try:
        log_event(firm_id, "engagement", engagement_id, "update",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data=updates)
    except Exception:
        pass
    return api_response(True, {"engagement": updated})


@router.post("/{engagement_id}/generate")
def generate_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Transition Draft → Generated.
    Renders all {{merge_fields}} in the content using lead/client data.
    Returns the rendered content. Manager+.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()

    if not db:
        eng = next(
            (e for e in _MOCK_ENGAGEMENTS
             if e["id"] == engagement_id and e.get("firm_id") == firm_id),
            None,
        )
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        if eng["status"] != "Draft":
            raise HTTPException(status_code=409,
                                detail=f"Cannot generate: engagement is '{eng['status']}', expected 'Draft'.")
        fields = {
            "client_name":      eng.get("recipient_name") or "Client",
            "client_pan":       "",
            "client_gstin":     "",
            "firm_name":        "Your CA Firm",
            "partner_name":     current_user.get("name") or current_user.get("email") or "Partner",
            "engagement_fee":   _format_fee(int(eng.get("fee_amount_paise") or 0)),
            "engagement_date":  today,
            "start_date":       eng.get("start_date") or today,
        }
        rendered = _render_merge_fields(eng.get("content", ""), fields)
        eng["content"] = rendered
        eng["status"] = "Generated"
        eng["updated_at"] = now
        _log_engagement_event(db, engagement_id, firm_id, "generated",
                              current_user.get("auth_user_id"))
        return api_response(True, {"engagement": eng, "rendered_content": rendered})

    try:
        eng_res = (
            db.table("engagements")
            .select("*")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
        )
        eng = eng_res.data
    except Exception:
        eng = None
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if eng["status"] != "Draft":
        raise HTTPException(status_code=409,
                            detail=f"Cannot generate: engagement is '{eng['status']}', expected 'Draft'.")

    # Resolve lead/client data for merge fields
    client_name = eng.get("recipient_name") or ""
    client_pan = ""
    client_gstin = ""

    if eng.get("lead_id"):
        try:
            lead_res = (
                db.table("leads")
                .select("company_name, contact_name")
                .eq("id", eng["lead_id"])
                .single()
                .execute()
            )
            if lead_res.data:
                client_name = client_name or lead_res.data.get("company_name") or lead_res.data.get("contact_name") or ""
        except Exception:
            pass

    if eng.get("client_id"):
        try:
            client_res = (
                db.table("clients")
                .select("client_name, pan, gstin")
                .eq("id", eng["client_id"])
                .single()
                .execute()
            )
            if client_res.data:
                client_name = client_name or client_res.data.get("client_name") or ""
                client_pan = client_res.data.get("pan") or ""
                client_gstin = client_res.data.get("gstin") or ""
        except Exception:
            pass

    fields = {
        "client_name":      client_name or "Client",
        "client_pan":       client_pan,
        "client_gstin":     client_gstin,
        "firm_name":        "Your CA Firm",
        "partner_name":     current_user.get("name") or current_user.get("email") or "Partner",
        "engagement_fee":   _format_fee(int(eng.get("fee_amount_paise") or 0)),
        "engagement_date":  today,
        "start_date":       eng.get("start_date") or today,
    }
    rendered = _render_merge_fields(eng.get("content", ""), fields)

    try:
        res = (
            db.table("engagements")
            .update({"status": "Generated", "content": rendered, "updated_at": now})
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        updated = (res.data or [eng])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log_engagement_event(db, engagement_id, firm_id, "generated",
                          current_user.get("auth_user_id"),
                          {"merge_fields_resolved": list(fields.keys())})
    try:
        log_event(firm_id, "engagement", engagement_id, "status_change",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  old_data={"status": "Draft"},
                  new_data={"status": "Generated"})
    except Exception:
        pass
    return api_response(True, {"engagement": updated, "rendered_content": rendered})


@router.post("/{engagement_id}/send")
def send_engagement(
    engagement_id: str,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Transition Generated/Draft → Sent. Records sent_at timestamp. Manager+.
    CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT without explicit CA confirmation.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    _VALID_SEND_STATUSES = {"Draft", "Generated"}

    if not db:
        eng = next(
            (e for e in _MOCK_ENGAGEMENTS
             if e["id"] == engagement_id and e.get("firm_id") == firm_id),
            None,
        )
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        if eng["status"] not in _VALID_SEND_STATUSES:
            raise HTTPException(status_code=409,
                                detail=f"Cannot send: engagement is '{eng['status']}'. Expected one of: {sorted(_VALID_SEND_STATUSES)}.")
        eng["status"] = "Sent"
        eng["sent_at"] = now
        eng["updated_at"] = now
        _log_engagement_event(db, engagement_id, firm_id, "sent",
                              current_user.get("auth_user_id"))
        # Objective 1: sending a letter advances the linked lead to "Engagement Sent".
        _advance_lead(eng.get("lead_id"), firm_id, "Engagement Sent", current_user)
        return api_response(True, {"engagement": eng})

    try:
        eng_res = (
            db.table("engagements")
            .select("status, lead_id")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
        )
        eng = eng_res.data
    except Exception:
        eng = None
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if eng["status"] not in _VALID_SEND_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"Cannot send: engagement is '{eng['status']}'. Expected one of: {sorted(_VALID_SEND_STATUSES)}.")

    try:
        res = (
            db.table("engagements")
            .update({"status": "Sent", "sent_at": now, "updated_at": now})
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        updated = (res.data or [{}])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log_engagement_event(db, engagement_id, firm_id, "sent",
                          current_user.get("auth_user_id"))
    try:
        log_event(firm_id, "engagement", engagement_id, "status_change",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  old_data={"status": eng["status"]},
                  new_data={"status": "Sent", "sent_at": now})
    except Exception:
        pass
    # Objective 1: sending a letter advances the linked lead to "Engagement Sent".
    _advance_lead(eng.get("lead_id"), firm_id, "Engagement Sent", current_user)
    return api_response(True, {"engagement": updated})


@router.post("/{engagement_id}/sign")
def sign_engagement(
    engagement_id: str,
    body: SignIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Transition Sent/Viewed → Signed. Records signed_at and optional signed_pdf_url.
    Manager+. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    _VALID_SIGN_STATUSES = {"Sent", "Viewed"}

    if not db:
        eng = next(
            (e for e in _MOCK_ENGAGEMENTS
             if e["id"] == engagement_id and e.get("firm_id") == firm_id),
            None,
        )
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        if eng["status"] not in _VALID_SIGN_STATUSES:
            raise HTTPException(status_code=409,
                                detail=f"Cannot sign: engagement is '{eng['status']}'. Expected one of: {sorted(_VALID_SIGN_STATUSES)}.")
        eng["status"] = "Signed"
        eng["signed_at"] = now
        eng["updated_at"] = now
        if body.signed_pdf_url:
            eng["signed_pdf_url"] = body.signed_pdf_url
        _log_engagement_event(db, engagement_id, firm_id, "signed",
                              current_user.get("auth_user_id"),
                              {"signed_pdf_url": body.signed_pdf_url})
        # Objective 1: signing a letter advances the linked lead to "Engagement Signed".
        _advance_lead(eng.get("lead_id"), firm_id, "Engagement Signed", current_user)
        return api_response(True, {"engagement": eng})

    try:
        eng_res = (
            db.table("engagements")
            .select("status, lead_id")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
        )
        eng = eng_res.data
    except Exception:
        eng = None
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if eng["status"] not in _VALID_SIGN_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"Cannot sign: engagement is '{eng['status']}'. Expected one of: {sorted(_VALID_SIGN_STATUSES)}.")

    update: dict = {"status": "Signed", "signed_at": now, "updated_at": now}
    if body.signed_pdf_url:
        update["signed_pdf_url"] = body.signed_pdf_url

    try:
        res = (
            db.table("engagements")
            .update(update)
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        updated = (res.data or [{}])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log_engagement_event(db, engagement_id, firm_id, "signed",
                          current_user.get("auth_user_id"),
                          {"signed_pdf_url": body.signed_pdf_url})
    try:
        log_event(firm_id, "engagement", engagement_id, "status_change",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  old_data={"status": eng["status"]},
                  new_data={"status": "Signed", "signed_at": now})
    except Exception:
        pass
    # Objective 1: signing a letter advances the linked lead to "Engagement Signed".
    _advance_lead(eng.get("lead_id"), firm_id, "Engagement Signed", current_user)
    return api_response(True, {"engagement": updated})


@router.post("/{engagement_id}/reject")
def reject_engagement(
    engagement_id: str,
    body: RejectIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """
    Transition Sent/Viewed → Rejected. Records rejected_at and optional rejection_notes.
    Manager+.
    """
    db = _db()
    firm_id = current_user["firm_id"]
    now = datetime.now(timezone.utc).isoformat()

    _VALID_REJECT_STATUSES = {"Sent", "Viewed"}

    if not db:
        eng = next(
            (e for e in _MOCK_ENGAGEMENTS
             if e["id"] == engagement_id and e.get("firm_id") == firm_id),
            None,
        )
        if not eng:
            raise HTTPException(status_code=404, detail="Engagement not found")
        if eng["status"] not in _VALID_REJECT_STATUSES:
            raise HTTPException(status_code=409,
                                detail=f"Cannot reject: engagement is '{eng['status']}'. Expected one of: {sorted(_VALID_REJECT_STATUSES)}.")
        eng["status"] = "Rejected"
        eng["rejected_at"] = now
        eng["updated_at"] = now
        if body.rejection_notes:
            eng["rejection_notes"] = body.rejection_notes
        _log_engagement_event(db, engagement_id, firm_id, "rejected",
                              current_user.get("auth_user_id"),
                              {"rejection_notes": body.rejection_notes})
        return api_response(True, {"engagement": eng})

    try:
        eng_res = (
            db.table("engagements")
            .select("status")
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .single()
            .execute()
        )
        eng = eng_res.data
    except Exception:
        eng = None
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if eng["status"] not in _VALID_REJECT_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"Cannot reject: engagement is '{eng['status']}'. Expected one of: {sorted(_VALID_REJECT_STATUSES)}.")

    update: dict = {"status": "Rejected", "rejected_at": now, "updated_at": now}
    if body.rejection_notes:
        update["rejection_notes"] = body.rejection_notes

    try:
        res = (
            db.table("engagements")
            .update(update)
            .eq("id", engagement_id)
            .eq("firm_id", firm_id)
            .execute()
        )
        updated = (res.data or [{}])[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _log_engagement_event(db, engagement_id, firm_id, "rejected",
                          current_user.get("auth_user_id"),
                          {"rejection_notes": body.rejection_notes})
    try:
        log_event(firm_id, "engagement", engagement_id, "status_change",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  old_data={"status": eng["status"]},
                  new_data={"status": "Rejected", "rejected_at": now,
                             "rejection_notes": body.rejection_notes})
    except Exception:
        pass
    return api_response(True, {"engagement": updated})
