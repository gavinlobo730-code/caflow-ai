from fastapi import APIRouter, Depends, HTTPException, Path, Query
from models.client import ClientCreate, ClientUpdate
from models.common import api_response
from core.permissions import rbac
from repositories.client_repository import client_repo
from repositories.compliance_records_repository import compliance_records_repo
from repositories.document_repository import document_repo
from repositories.task_repository import task_repo
from repositories.ai_insights_repository import ai_insights_repo
from mock_data import MOCK_ACTIVITY_LOGS
from datetime import date
from services.audit_service import log_event
from services.internal_client_service import assert_can_view_client
from core.authz import effective_client_ids, can_access_client

router = APIRouter(prefix="/api/clients", tags=["clients"])


def _supabase_enabled() -> bool:
    """True when a real Supabase backend is configured (i.e. not mock mode).
    Mirrors the _db() guard used elsewhere so DB-only blocker checks are skipped
    in mock mode and never crash on a missing client."""
    import os
    return bool(os.environ.get("SUPABASE_URL"))


def _assert_firm(client: dict, current_user: dict) -> None:
    """Raise 404 if client belongs to a different firm, or is outside the
    caller's client-assignment scope (M2 — Executive/Reviewer/Manager only
    see clients assigned to them; only Partner is firm-wide, per
    core.authz._FIRMWIDE_ROLES). Both branches share the same message so a
    caller cannot distinguish "hidden" from "missing" (message-oracle)."""
    firm_id = current_user.get("firm_id")
    if client.get("firm_id") and client["firm_id"] != firm_id:
        raise HTTPException(status_code=404, detail="Client not found")
    if not can_access_client(current_user, client.get("id")):
        raise HTTPException(status_code=404, detail="Client not found")


def _check_delete_blockers(client_id: str, firm_id: str, client_pan: str | None = None) -> list[str]:
    """
    Return human-readable blockers that prevent permanent deletion.
    Historical records must be fully resolved before a client can be deleted.
    IT Act Section 139 / CGST Act Section 37 — obligations persist until filed.

    client_pan (optional) lets the DSC check match firm-scoped DSC records by PAN.
    All dependent-entity DB lookups are NON-FATAL: a missing table or DB error must
    never crash the delete path, so each is wrapped in try/except (mirroring how the
    existing checks tolerate empty/erroring repos).
    """
    blockers: list[str] = []

    active_records = [
        r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id)
        if r.get("status") not in ("Filed",)
    ]
    if active_records:
        blockers.append(
            f"{len(active_records)} active compliance record(s) not yet filed"
        )

    active_work = [
        t for t in task_repo.find_all(firm_id=firm_id, client_id=client_id)
        if t.get("status") != "completed"
    ]
    if active_work:
        blockers.append(f"{len(active_work)} active work item(s)")

    docs = document_repo.find_all(firm_id=firm_id, client_id=client_id)
    if docs:
        blockers.append(f"{len(docs)} document(s) attached")

    # ── Active fee engagements (fee_engagements table; DB-only, skip in mock) ──
    # Ongoing billing relationships must be closed before the client is removed.
    if _supabase_enabled():
        try:
            from core.supabase_client import get_supabase
            res = (
                get_supabase()
                .table("fee_engagements")
                .select("id", count="exact")
                .eq("firm_id", firm_id)
                .eq("client_id", client_id)
                .eq("status", "Active")
                .execute()
            )
            n = res.count if res.count is not None else len(res.data or [])
            if n > 0:
                blockers.append(f"{n} active fee engagement(s)")
        except Exception:
            pass

    # ── Active engagement letters (engagements table) ──────────────────────────
    # CGST Act Section 31 — a live engagement letter documents an active mandate.
    _TERMINAL_LETTER_STATUSES = ("Rejected", "Expired")
    active_letters = 0
    if _supabase_enabled():
        try:
            from core.supabase_client import get_supabase
            res = (
                get_supabase()
                .table("engagements")
                .select("id, status")
                .eq("firm_id", firm_id)
                .eq("client_id", client_id)
                .execute()
            )
            active_letters = len([
                e for e in (res.data or [])
                if e.get("status") not in _TERMINAL_LETTER_STATUSES
            ])
        except Exception:
            active_letters = 0
    else:
        try:
            from routers.engagement_letters import _MOCK_ENGAGEMENTS
            active_letters = len([
                e for e in _MOCK_ENGAGEMENTS
                if e.get("firm_id") == firm_id
                and e.get("client_id") == client_id
                and e.get("status") not in _TERMINAL_LETTER_STATUSES
            ])
        except Exception:
            active_letters = 0
    if active_letters > 0:
        blockers.append(f"{active_letters} active engagement letter(s)")

    # ── Fee invoices on record (financial history must not be orphaned) ────────
    # invoice_repo.find_all already excludes soft-deleted invoices.
    try:
        from repositories.invoice_repository import invoice_repo
        invoices = invoice_repo.find_all(firm_id=firm_id, client_id=client_id)
        if invoices:
            blockers.append(f"{len(invoices)} fee invoice(s) on record")
    except Exception:
        pass

    # ── DSC records registered to this client's PAN (firm-scoped, DB-only) ──────
    # dsc_records is firm-scoped (no client_id) but carries a pan column.
    if client_pan and _supabase_enabled():
        try:
            from core.supabase_client import get_supabase
            res = (
                get_supabase()
                .table("dsc_records")
                .select("id", count="exact")
                .eq("firm_id", firm_id)
                .eq("pan", client_pan)
                .execute()
            )
            n = res.count if res.count is not None else len(res.data or [])
            if n > 0:
                blockers.append(f"{n} DSC record(s) registered to this PAN")
        except Exception:
            pass

    return blockers


@router.get("")
def list_clients(
    include_archived: bool = Query(False, description="Include archived clients"),
    include_test: bool = Query(True, description="Include test clients"),
    current_user: dict = Depends(rbac("client", "read")),
):
    firm_id = current_user.get("firm_id")
    clients = client_repo.find_all(
        firm_id=firm_id,
        include_archived=include_archived,
        include_test=include_test,
    )
    # M2: assignment scope — Executive/Reviewer only see clients assigned to them
    # (Partner/Manager firm-wide ⇒ effective set is None ⇒ no filtering).
    eff = effective_client_ids(current_user)
    if eff is not None:
        clients = [c for c in clients if str(c.get("id")) in eff]
    return api_response(True, {"clients": clients, "total": len(clients)})


@router.get("/{client_id}")
def get_client_workspace(client_id: str = Path(...), current_user: dict = Depends(rbac("client", "read"))):
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id, firm_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, current_user)
    # Guardrail G1: the internal practice client is Partner-only (404 to non-partners).
    assert_can_view_client(client, current_user)

    # R3.13d: compliance_tasks (System B) is being retired — compliance_records
    # (System A) is the canonical obligation entity. Status vocabulary differs
    # (System A: Not Started/Awaiting Documents/In Progress/Ready For Review/
    # Ready To File/Filed/Completed/Overdue — capitalized, not System B's
    # lowercase pending/in_progress/filed/overdue/not_applicable).
    tasks = compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id)
    open_compliance = [t for t in tasks if t.get("status") not in ("Filed", "Completed")]
    docs = document_repo.find_all(firm_id=firm_id, client_id=client_id)
    insights = ai_insights_repo.find_all(firm_id=firm_id, client_id=client_id)
    client_tasks = task_repo.find_all(firm_id=firm_id, client_id=client_id)

    # activity_logs: no dedicated repo yet — filter mock by client_id as read-only fallback
    activity = [a for a in MOCK_ACTIVITY_LOGS if a.get("client_id") == client_id]

    open_tasks = [t for t in client_tasks if t.get("status") != "completed"]
    completed_tasks = [t for t in client_tasks if t.get("status") == "completed"]
    today_iso = date.today().isoformat()

    upcoming = sorted(open_compliance, key=lambda t: t.get("due_date", ""))[:5]

    return api_response(True, {
        "profile": client,
        "compliance_tasks": tasks,
        "upcoming_deadlines": upcoming,
        "documents": docs,
        "recent_activity": sorted(activity, key=lambda a: a.get("created_at", ""), reverse=True)[:10],
        "ai_insights": [i for i in insights if i.get("status") in ("open", "acknowledged")],
        "open_tasks": open_tasks,
        "completed_tasks": completed_tasks[:5],
        "task_summary": {
            "open": len(open_tasks),
            "completed": len(completed_tasks),
            "overdue": len([t for t in open_tasks if t.get("due_date") and t["due_date"] < today_iso]),
            "review_required": len([t for t in open_tasks if t.get("status") == "review_required"]),
        },
        "summary": {
            "total_tasks": len(tasks),
            "overdue_count": sum(1 for t in tasks if t.get("status") == "Overdue"),
            "pending_count": sum(1 for t in tasks if t.get("status") == "Not Started"),
            "filed_count": sum(1 for t in tasks if t.get("status") in ("Filed", "Completed")),
            "document_count": len(docs),
            "open_insights": sum(1 for i in insights if i.get("status") == "open"),
        }
    })


@router.post("")
def create_client(body: ClientCreate, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    data = {**body.model_dump(), "firm_id": firm_id}
    client = client_repo.create(data)
    log_event(firm_id, "client", client.get("id",""), "create",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data=client)
    return api_response(True, {"client": client})


@router.patch("/{client_id}")
def update_client(client_id: str, body: ClientUpdate, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    existing = client_repo.find_by_id(client_id, firm_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(existing, current_user)
    if body.status and body.status.value == "archived":
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/clients/{id}/archive to archive a client"
        )
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = client_repo.update(client_id, updates)
    log_event(firm_id, "client", client_id, "update",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              old_data={k: existing.get(k) for k in updates}, new_data=updates)
    return api_response(True, {"client": updated})


@router.post("/{client_id}/archive")
def archive_client(client_id: str, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id, firm_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, current_user)
    if client.get("status") == "archived":
        raise HTTPException(status_code=409, detail="Client is already archived")
    actor_id = current_user.get("auth_user_id")
    updated = client_repo.archive(client_id, actor_id=actor_id)
    log_event(firm_id, "client", client_id, "archive",
              actor_id=actor_id, actor_email=current_user.get("email"),
              old_data={"status": client.get("status")},
              new_data={"status": "archived"})
    return api_response(True, {"client": updated})


@router.post("/{client_id}/restore")
def restore_client(client_id: str, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id, firm_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, current_user)
    if client.get("status") != "archived":
        raise HTTPException(status_code=409, detail="Client is not archived")
    actor_id = current_user.get("auth_user_id")
    updated = client_repo.restore(client_id, actor_id=actor_id)
    log_event(firm_id, "client", client_id, "restore",
              actor_id=actor_id, actor_email=current_user.get("email"),
              old_data={"status": "archived"},
              new_data={"status": "active"})
    return api_response(True, {"client": updated})


@router.delete("/{client_id}")
def delete_client(client_id: str, current_user: dict = Depends(rbac("client", "delete"))):
    """
    Soft-delete a client (Partner only). Blocked when any historical records exist.
    Historical data is never hard-deleted — only the client row is hidden.
    Callers should archive the client instead when records are present.
    """
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id, firm_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, current_user)

    blockers = _check_delete_blockers(client_id, firm_id, client_pan=client.get("pan"))
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Client cannot be permanently deleted because historical records exist. Archive the client instead.",
                "blockers": blockers,
            },
        )

    actor_id = current_user.get("auth_user_id")
    success = client_repo.soft_delete(client_id, actor_id=actor_id)
    if not success:
        raise HTTPException(status_code=500, detail="Delete failed")
    log_event(firm_id, "client", client_id, "delete",
              actor_id=actor_id, actor_email=current_user.get("email"),
              old_data={"client_name": client.get("client_name"), "status": client.get("status")},
              new_data={"deleted": True})
    return api_response(True, {"message": "Client deleted", "client_id": client_id})
