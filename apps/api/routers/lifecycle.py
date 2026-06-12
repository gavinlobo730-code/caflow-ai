"""
Lifecycle router — Lead pipeline, proposals, onboarding workflows, and renewals.

Covers the full client acquisition and retention lifecycle for a CA firm:
  Lead → Proposal → Onboarding → Active Client → Renewal

All monetary values stored in integer paise (₹1 = 100 paise) — never float.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime, timezone
import uuid

from models.common import api_response
from core.permissions import rbac
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


# ─── In-memory mock stores ────────────────────────────────────────────────────

_MOCK_LEADS:     list[dict] = []
_MOCK_PROPOSALS: list[dict] = []
_MOCK_ONBOARDING_WORKFLOWS: list[dict] = []
_MOCK_ONBOARDING_TASKS:     list[dict] = []
_MOCK_RENEWALS:  list[dict] = []


def _db():
    import os
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _next_lead_no(db, firm_id: str) -> str:
    """Generate sequential lead number like LEAD-0001."""
    if not db:
        n = len(_MOCK_LEADS) + 1
        return f"LEAD-{n:04d}"
    res = db.table("leads").select("lead_no").eq("firm_id", firm_id).order("created_at", desc=True).limit(1).execute()
    rows = res.data or []
    if rows:
        try:
            last_no = int(rows[0]["lead_no"].split("-")[1])
            return f"LEAD-{last_no + 1:04d}"
        except Exception:
            pass
    return "LEAD-0001"


def _next_proposal_no(db, firm_id: str) -> str:
    """Generate sequential proposal number like PROP-2026-0001."""
    year = datetime.now(timezone.utc).year
    if not db:
        n = len(_MOCK_PROPOSALS) + 1
        return f"PROP-{year}-{n:04d}"
    res = db.table("proposals").select("proposal_no").eq("firm_id", firm_id).order("created_at", desc=True).limit(1).execute()
    rows = res.data or []
    if rows:
        try:
            parts = rows[0]["proposal_no"].split("-")
            last_no = int(parts[-1])
            return f"PROP-{year}-{last_no + 1:04d}"
        except Exception:
            pass
    return f"PROP-{year}-0001"


_DEFAULT_ONBOARDING_TASKS = [
    "Obtain PAN copy",
    "Obtain GST certificate",
    "Collect bank statements",
    "KYC documents",
    "Previous year financials",
    "Director/Partner documents",
    "Engagement letter signing",
    "Add to accounting software",
    "Create login credentials",
    "Welcome call scheduled",
]


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class LeadIn(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    stage: str = "Lead"
    estimated_value_paise: int = 0
    assigned_to: Optional[str] = None
    expected_close_date: Optional[str] = None
    notes: Optional[str] = None


class LeadUpdateIn(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    stage: Optional[str] = None
    estimated_value_paise: Optional[int] = None
    assigned_to: Optional[str] = None
    expected_close_date: Optional[str] = None
    notes: Optional[str] = None


class LeadConvertIn(BaseModel):
    client_id: Optional[str] = None


class ProposalIn(BaseModel):
    lead_id: Optional[str] = None
    client_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    total_value_paise: int = 0
    valid_until: Optional[str] = None
    status: str = "Draft"


class ProposalStatusIn(BaseModel):
    status: str  # Sent | Accepted | Rejected
    notes: Optional[str] = None


class OnboardingIn(BaseModel):
    client_id: str
    notes: Optional[str] = None


class TaskStatusIn(BaseModel):
    status: str  # Pending | In Progress | Done | Skipped
    notes: Optional[str] = None


class RenewalIn(BaseModel):
    client_id: str
    financial_year: str
    service_type: str
    renewal_date: Optional[str] = None
    value_paise: int = 0
    status: str = "Pending"
    assigned_to: Optional[str] = None
    notes: Optional[str] = None


class RenewalStatusIn(BaseModel):
    status: str
    notes: Optional[str] = None


# ─── Leads ────────────────────────────────────────────────────────────────────

@router.get("/leads")
def list_leads(
    stage: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        result = list(_MOCK_LEADS)
        if stage:
            result = [l for l in result if l.get("stage") == stage]
        if assigned_to:
            result = [l for l in result if l.get("assigned_to") == assigned_to]
        return api_response(True, result[offset: offset + limit])

    q = db.table("leads").select("*").eq("firm_id", current_user["firm_id"])
    if stage:
        q = q.eq("stage", stage)
    if assigned_to:
        q = q.eq("assigned_to", assigned_to)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return api_response(True, res.data or [])


@router.post("/leads")
def create_lead(
    data: LeadIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    lead_no = _next_lead_no(db, current_user["firm_id"])
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":                    str(uuid.uuid4()),
        "firm_id":               current_user["firm_id"],
        "lead_no":               lead_no,
        "company_name":          data.company_name,
        "contact_name":          data.contact_name,
        "email":                 data.email,
        "phone":                 data.phone,
        "source":                data.source,
        "stage":                 data.stage,
        "estimated_value_paise": int(data.estimated_value_paise),
        "assigned_to":           data.assigned_to,
        "expected_close_date":   data.expected_close_date,
        "notes":                 data.notes,
        "is_converted":          False,
        "created_at":            now,
        "updated_at":            now,
    }

    if not db:
        _MOCK_LEADS.append(row)
        timeline_service.log(
            row["id"], "lifecycle", "Lead Created",
            f"New lead {lead_no}: {data.company_name}", "info",
            firm_id=current_user["firm_id"],
        )
        return api_response(True, row)

    db.table("leads").insert(row).execute()
    # Log lifecycle event in the generic timeline
    timeline_service.log(
        row["id"], "lifecycle", "Lead Created",
        f"New lead {lead_no}: {data.company_name}", "info",
        firm_id=current_user["firm_id"],
        entity_type="lead", entity_id=row["id"],
        actor_id=current_user.get("auth_user_id"),
    )
    # Also insert into client_lifecycle_events for CRM tracking
    try:
        db.table("client_lifecycle_events").insert({
            "id":          str(uuid.uuid4()),
            "firm_id":     current_user["firm_id"],
            "entity_id":   row["id"],
            "entity_type": "lead",
            "event_type":  "lead_created",
            "description": f"Lead {lead_no} created for {data.company_name}",
            "created_at":  now,
        }).execute()
    except Exception:
        pass
    return api_response(True, row)


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: str,
    data: LeadUpdateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not db:
        for lead in _MOCK_LEADS:
            if lead["id"] == lead_id:
                old_stage = lead.get("stage")
                lead.update(update)
                if data.stage and data.stage != old_stage:
                    timeline_service.log(
                        lead_id, "lifecycle", "Lead Stage Changed",
                        f"Stage changed from {old_stage} to {data.stage}", "info",
                        firm_id=current_user["firm_id"],
                    )
                return api_response(True, lead)
        raise HTTPException(status_code=404, detail="Lead not found")

    # Fetch current stage before update
    existing = db.table("leads").select("stage").eq("id", lead_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Lead not found")

    old_stage = existing.get("stage")
    res = db.table("leads").update(update).eq("id", lead_id).eq("firm_id", current_user["firm_id"]).execute()
    result = (res.data or [{}])[0]

    if data.stage and data.stage != old_stage:
        now = datetime.now(timezone.utc).isoformat()
        timeline_service.log(
            lead_id, "lifecycle", "Lead Stage Changed",
            f"Stage changed from {old_stage} to {data.stage}", "info",
            firm_id=current_user["firm_id"],
            entity_type="lead", entity_id=lead_id,
            actor_id=current_user.get("auth_user_id"),
        )
        try:
            db.table("client_lifecycle_events").insert({
                "id":          str(uuid.uuid4()),
                "firm_id":     current_user["firm_id"],
                "entity_id":   lead_id,
                "entity_type": "lead",
                "event_type":  "lead_stage_changed",
                "description": f"Stage changed from '{old_stage}' to '{data.stage}'",
                "metadata":    {"from_stage": old_stage, "to_stage": data.stage},
                "created_at":  now,
            }).execute()
        except Exception:
            pass

    return api_response(True, result)


@router.post("/leads/{lead_id}/convert")
def convert_lead(
    lead_id: str,
    data: LeadConvertIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        for lead in _MOCK_LEADS:
            if lead["id"] == lead_id:
                lead["is_converted"] = True
                lead["stage"] = "Active"
                lead["converted_at"] = now
                lead["converted_client_id"] = data.client_id
                lead["updated_at"] = now
                timeline_service.log(
                    lead_id, "lifecycle", "Lead Converted",
                    f"Lead converted to active client", "success",
                    firm_id=current_user["firm_id"],
                )
                return api_response(True, lead)
        raise HTTPException(status_code=404, detail="Lead not found")

    existing = db.table("leads").select("*").eq("id", lead_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Lead not found")

    res = db.table("leads").update({
        "is_converted":         True,
        "stage":                "Active",
        "converted_at":         now,
        "converted_client_id":  data.client_id,
        "updated_at":           now,
    }).eq("id", lead_id).eq("firm_id", current_user["firm_id"]).execute()

    timeline_service.log(
        lead_id, "lifecycle", "Lead Converted",
        f"Lead {existing.get('lead_no', '')} converted to active client", "success",
        firm_id=current_user["firm_id"],
        entity_type="lead", entity_id=lead_id,
        actor_id=current_user.get("auth_user_id"),
    )
    try:
        db.table("client_lifecycle_events").insert({
            "id":          str(uuid.uuid4()),
            "firm_id":     current_user["firm_id"],
            "entity_id":   lead_id,
            "entity_type": "lead",
            "event_type":  "lead_converted",
            "description": f"Converted to client {data.client_id or '(new)'}",
            "created_at":  now,
        }).execute()
    except Exception:
        pass

    return api_response(True, (res.data or [{}])[0])


# ─── Proposals ────────────────────────────────────────────────────────────────

@router.get("/proposals")
def list_proposals(
    lead_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        result = list(_MOCK_PROPOSALS)
        if lead_id:
            result = [p for p in result if p.get("lead_id") == lead_id]
        if client_id:
            result = [p for p in result if p.get("client_id") == client_id]
        if status:
            result = [p for p in result if p.get("status") == status]
        return api_response(True, result[offset: offset + limit])

    q = db.table("proposals").select("*").eq("firm_id", current_user["firm_id"])
    if lead_id:
        q = q.eq("lead_id", lead_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if status:
        q = q.eq("status", status)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return api_response(True, res.data or [])


@router.post("/proposals")
def create_proposal(
    data: ProposalIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    proposal_no = _next_proposal_no(db, current_user["firm_id"])
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "id":                 str(uuid.uuid4()),
        "firm_id":            current_user["firm_id"],
        "proposal_no":        proposal_no,
        "lead_id":            data.lead_id,
        "client_id":          data.client_id,
        "title":              data.title,
        "description":        data.description,
        "total_value_paise":  int(data.total_value_paise),
        "valid_until":        data.valid_until,
        "status":             data.status,
        "created_at":         now,
        "updated_at":         now,
    }

    if not db:
        _MOCK_PROPOSALS.append(row)
        timeline_service.log(
            data.lead_id or data.client_id or row["id"],
            "lifecycle", "Proposal Created",
            f"Proposal {proposal_no}: {data.title}", "info",
            firm_id=current_user["firm_id"],
        )
        return api_response(True, row)

    db.table("proposals").insert(row).execute()
    timeline_service.log(
        data.lead_id or data.client_id or row["id"],
        "lifecycle", "Proposal Created",
        f"Proposal {proposal_no} created: {data.title}", "info",
        firm_id=current_user["firm_id"],
        entity_type="proposal", entity_id=row["id"],
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, row)


@router.patch("/proposals/{proposal_id}/status")
def update_proposal_status(
    proposal_id: str,
    data: ProposalStatusIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    update = {"status": data.status, "updated_at": now}
    if data.notes:
        update["notes"] = data.notes

    severity_map = {"Accepted": "success", "Rejected": "warning", "Sent": "info"}
    severity = severity_map.get(data.status, "info")

    if not db:
        for p in _MOCK_PROPOSALS:
            if p["id"] == proposal_id:
                p.update(update)
                timeline_service.log(
                    p.get("lead_id") or p.get("client_id") or proposal_id,
                    "lifecycle", f"Proposal {data.status}",
                    f"Proposal status changed to {data.status}", severity,
                    firm_id=current_user["firm_id"],
                )
                return api_response(True, p)
        raise HTTPException(status_code=404, detail="Proposal not found")

    existing = db.table("proposals").select("*").eq("id", proposal_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Proposal not found")

    res = db.table("proposals").update(update).eq("id", proposal_id).eq("firm_id", current_user["firm_id"]).execute()
    timeline_service.log(
        existing.get("lead_id") or existing.get("client_id") or proposal_id,
        "lifecycle", f"Proposal {data.status}",
        f"Proposal {existing.get('proposal_no', '')} status changed to {data.status}", severity,
        firm_id=current_user["firm_id"],
        entity_type="proposal", entity_id=proposal_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, (res.data or [{}])[0])


# ─── Onboarding ───────────────────────────────────────────────────────────────

@router.get("/onboarding")
def list_onboarding(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        workflows = [w for w in _MOCK_ONBOARDING_WORKFLOWS if w.get("client_id") == client_id]
        for wf in workflows:
            wf["tasks"] = [t for t in _MOCK_ONBOARDING_TASKS if t.get("workflow_id") == wf["id"]]
        return api_response(True, workflows)

    res = db.table("onboarding_workflows").select("*, onboarding_tasks(*)").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).order("created_at", desc=True).execute()
    return api_response(True, res.data or [])


@router.post("/onboarding")
def create_onboarding(
    data: OnboardingIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    workflow_id = str(uuid.uuid4())

    workflow = {
        "id":         workflow_id,
        "firm_id":    current_user["firm_id"],
        "client_id":  data.client_id,
        "status":     "In Progress",
        "notes":      data.notes,
        "created_at": now,
        "updated_at": now,
    }

    tasks = []
    for i, task_name in enumerate(_DEFAULT_ONBOARDING_TASKS):
        tasks.append({
            "id":          str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "firm_id":     current_user["firm_id"],
            "client_id":   data.client_id,
            "title":       task_name,
            "status":      "Pending",
            "sort_order":  i + 1,
            "created_at":  now,
            "updated_at":  now,
        })

    if not db:
        _MOCK_ONBOARDING_WORKFLOWS.append(workflow)
        _MOCK_ONBOARDING_TASKS.extend(tasks)
        workflow["tasks"] = tasks
        timeline_service.log(
            data.client_id, "lifecycle", "Onboarding Started",
            f"Onboarding workflow created with {len(tasks)} tasks", "info",
            firm_id=current_user["firm_id"],
        )
        return api_response(True, workflow)

    db.table("onboarding_workflows").insert(workflow).execute()
    if tasks:
        db.table("onboarding_tasks").insert(tasks).execute()

    timeline_service.log(
        data.client_id, "lifecycle", "Onboarding Started",
        f"Onboarding workflow started with {len(tasks)} tasks", "info",
        firm_id=current_user["firm_id"],
        entity_type="onboarding_workflow", entity_id=workflow_id,
        actor_id=current_user.get("auth_user_id"),
    )
    workflow["tasks"] = tasks
    return api_response(True, workflow)


@router.patch("/onboarding/{workflow_id}/tasks/{task_id}")
def update_onboarding_task(
    workflow_id: str,
    task_id: str,
    data: TaskStatusIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()

    if not db:
        task_found = None
        for t in _MOCK_ONBOARDING_TASKS:
            if t["id"] == task_id and t["workflow_id"] == workflow_id:
                t["status"] = data.status
                if data.notes:
                    t["notes"] = data.notes
                t["updated_at"] = now
                task_found = t
                break

        if not task_found:
            raise HTTPException(status_code=404, detail="Task not found")

        # Check if all tasks for this workflow are done
        wf_tasks = [t for t in _MOCK_ONBOARDING_TASKS if t.get("workflow_id") == workflow_id]
        all_done = all(t["status"] in ("Done", "Skipped") for t in wf_tasks)
        if all_done:
            for wf in _MOCK_ONBOARDING_WORKFLOWS:
                if wf["id"] == workflow_id:
                    wf["status"] = "Completed"
                    wf["completed_at"] = now
                    timeline_service.log(
                        wf["client_id"], "lifecycle", "Onboarding Completed",
                        "All onboarding tasks completed", "success",
                        firm_id=current_user["firm_id"],
                    )
                    break
        return api_response(True, task_found)

    # Real DB path
    task = db.table("onboarding_tasks").select("*").eq("id", task_id).eq("workflow_id", workflow_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update = {"status": data.status, "updated_at": now}
    if data.notes:
        update["notes"] = data.notes
    db.table("onboarding_tasks").update(update).eq("id", task_id).execute()

    # Check completion
    all_tasks = db.table("onboarding_tasks").select("status").eq("workflow_id", workflow_id).execute().data or []
    all_done = all(t["status"] in ("Done", "Skipped") for t in all_tasks)
    if all_done:
        wf = db.table("onboarding_workflows").select("client_id").eq("id", workflow_id).single().execute().data
        db.table("onboarding_workflows").update({"status": "Completed", "completed_at": now, "updated_at": now}).eq("id", workflow_id).execute()
        if wf:
            timeline_service.log(
                wf["client_id"], "lifecycle", "Onboarding Completed",
                "All onboarding tasks completed", "success",
                firm_id=current_user["firm_id"],
                entity_type="onboarding_workflow", entity_id=workflow_id,
                actor_id=current_user.get("auth_user_id"),
            )

    update["id"] = task_id
    return api_response(True, {**task, **update})


# ─── Renewals ─────────────────────────────────────────────────────────────────

@router.get("/renewals")
def list_renewals(
    status: Optional[str] = Query(None),
    financial_year: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    if not db:
        result = list(_MOCK_RENEWALS)
        if status:
            result = [r for r in result if r.get("status") == status]
        if financial_year:
            result = [r for r in result if r.get("financial_year") == financial_year]
        return api_response(True, result[offset: offset + limit])

    q = db.table("renewals").select("*").eq("firm_id", current_user["firm_id"])
    if status:
        q = q.eq("status", status)
    if financial_year:
        q = q.eq("financial_year", financial_year)
    res = q.order("renewal_date").range(offset, offset + limit - 1).execute()
    return api_response(True, res.data or [])


@router.post("/renewals")
def create_renewal(
    data: RenewalIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id":             str(uuid.uuid4()),
        "firm_id":        current_user["firm_id"],
        "client_id":      data.client_id,
        "financial_year": data.financial_year,
        "service_type":   data.service_type,
        "renewal_date":   data.renewal_date,
        "value_paise":    int(data.value_paise),
        "status":         data.status,
        "assigned_to":    data.assigned_to,
        "notes":          data.notes,
        "created_at":     now,
        "updated_at":     now,
    }

    if not db:
        _MOCK_RENEWALS.append(row)
        timeline_service.log(
            data.client_id, "lifecycle", "Renewal Created",
            f"Renewal created for {data.service_type} FY {data.financial_year}", "info",
            firm_id=current_user["firm_id"],
        )
        return api_response(True, row)

    db.table("renewals").insert(row).execute()
    timeline_service.log(
        data.client_id, "lifecycle", "Renewal Created",
        f"Renewal created for {data.service_type} FY {data.financial_year}", "info",
        firm_id=current_user["firm_id"],
        entity_type="renewal", entity_id=row["id"],
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, row)


@router.patch("/renewals/{renewal_id}/status")
def update_renewal_status(
    renewal_id: str,
    data: RenewalStatusIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    update = {"status": data.status, "updated_at": now}
    if data.notes:
        update["notes"] = data.notes

    severity_map = {"Completed": "success", "Cancelled": "warning", "Overdue": "critical"}
    severity = severity_map.get(data.status, "info")

    if not db:
        for r in _MOCK_RENEWALS:
            if r["id"] == renewal_id:
                r.update(update)
                timeline_service.log(
                    r["client_id"], "lifecycle", f"Renewal {data.status}",
                    f"Renewal status changed to {data.status}", severity,
                    firm_id=current_user["firm_id"],
                )
                return api_response(True, r)
        raise HTTPException(status_code=404, detail="Renewal not found")

    existing = db.table("renewals").select("*").eq("id", renewal_id).eq("firm_id", current_user["firm_id"]).single().execute().data
    if not existing:
        raise HTTPException(status_code=404, detail="Renewal not found")

    res = db.table("renewals").update(update).eq("id", renewal_id).eq("firm_id", current_user["firm_id"]).execute()
    timeline_service.log(
        existing["client_id"], "lifecycle", f"Renewal {data.status}",
        f"Renewal status changed to {data.status}", severity,
        firm_id=current_user["firm_id"],
        entity_type="renewal", entity_id=renewal_id,
        actor_id=current_user.get("auth_user_id"),
    )
    return api_response(True, (res.data or [{}])[0])


# ─── Lifecycle Dashboard ──────────────────────────────────────────────────────

@router.get("/dashboard")
def lifecycle_dashboard(
    current_user: dict = Depends(rbac("client", "read")),
):
    db = _db()
    firm_id = current_user["firm_id"]

    if not db:
        stage_counts: dict[str, dict] = {}
        for lead in _MOCK_LEADS:
            s = lead.get("stage", "Unknown")
            if s not in stage_counts:
                stage_counts[s] = {"stage": s, "count": 0, "total_value_paise": 0}
            stage_counts[s]["count"] += 1
            stage_counts[s]["total_value_paise"] += lead.get("estimated_value_paise", 0)

        today = datetime.now(timezone.utc).date().isoformat()
        overdue_renewals = sum(
            1 for r in _MOCK_RENEWALS
            if r.get("status") == "Pending" and r.get("renewal_date") and r["renewal_date"] < today
        )
        return api_response(True, {
            "stages":             list(stage_counts.values()),
            "total_leads":        len(_MOCK_LEADS),
            "total_proposals":    len(_MOCK_PROPOSALS),
            "overdue_renewals":   overdue_renewals,
        })

    today = datetime.now(timezone.utc).date().isoformat()

    leads = db.table("leads").select("stage, estimated_value_paise").eq("firm_id", firm_id).execute().data or []
    proposals = db.table("proposals").select("id").eq("firm_id", firm_id).execute().data or []
    overdue_renewals_res = db.table("renewals").select("id", count="exact").eq("firm_id", firm_id).eq("status", "Pending").lt("renewal_date", today).execute()

    stage_counts: dict[str, dict] = {}
    for lead in leads:
        s = lead.get("stage", "Unknown")
        if s not in stage_counts:
            stage_counts[s] = {"stage": s, "count": 0, "total_value_paise": 0}
        stage_counts[s]["count"] += 1
        stage_counts[s]["total_value_paise"] += int(lead.get("estimated_value_paise") or 0)

    return api_response(True, {
        "stages":           list(stage_counts.values()),
        "total_leads":      len(leads),
        "total_proposals":  len(proposals),
        "overdue_renewals": overdue_renewals_res.count or 0,
    })
