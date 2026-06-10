from fastapi import APIRouter, Depends, HTTPException, Path, Query
from models.client import ClientCreate, ClientUpdate
from models.common import api_response
from core.permissions import rbac
from repositories.client_repository import client_repo
from repositories.compliance_repository import compliance_repo
from repositories.compliance_records_repository import compliance_records_repo
from repositories.document_repository import document_repo
from repositories.task_repository import task_repo
from repositories.ai_insights_repository import ai_insights_repo
from mock_data import MOCK_ACTIVITY_LOGS
from datetime import date
from services.audit_service import log_event

router = APIRouter(prefix="/api/clients", tags=["clients"])


def _assert_firm(client: dict, firm_id: str | None) -> None:
    """Raise 404 if client belongs to a different firm."""
    if client.get("firm_id") and client["firm_id"] != firm_id:
        raise HTTPException(status_code=404, detail="Client not found")


def _check_delete_blockers(client_id: str, firm_id: str) -> list[str]:
    """
    Return human-readable blockers that prevent soft-deletion.
    Deletion is safe only when all compliance obligations are filed.
    IT Act Section 139 / CGST Act Section 37 — obligations persist until filed.
    """
    blockers: list[str] = []

    open_tasks = [
        t for t in compliance_repo.find_all(firm_id=firm_id, client_id=client_id)
        if t.get("status") not in ("filed", "not_applicable")
    ]
    if open_tasks:
        blockers.append(
            f"{len(open_tasks)} open compliance task(s): "
            + ", ".join(t.get("compliance_type", "?") for t in open_tasks[:3])
            + (" and more" if len(open_tasks) > 3 else "")
        )

    active_records = [
        r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id)
        if r.get("status") not in ("Filed",)
    ]
    if active_records:
        blockers.append(
            f"{len(active_records)} active compliance record(s) not yet filed"
        )

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
    return api_response(True, {"clients": clients, "total": len(clients)})


@router.get("/{client_id}")
def get_client_workspace(client_id: str = Path(...), current_user: dict = Depends(rbac("client", "read"))):
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, firm_id)

    tasks = compliance_repo.find_all(firm_id=firm_id, client_id=client_id)
    docs = document_repo.find_all(firm_id=firm_id, client_id=client_id)
    insights = ai_insights_repo.find_all(firm_id=firm_id, client_id=client_id)
    client_tasks = task_repo.find_all(firm_id=firm_id, client_id=client_id)

    # activity_logs: no dedicated repo yet — filter mock by client_id as read-only fallback
    activity = [a for a in MOCK_ACTIVITY_LOGS if a.get("client_id") == client_id]

    open_tasks = [t for t in client_tasks if t.get("status") != "completed"]
    completed_tasks = [t for t in client_tasks if t.get("status") == "completed"]
    today_iso = date.today().isoformat()

    upcoming = sorted(
        [t for t in tasks if t.get("status") in ("pending", "overdue")],
        key=lambda t: t.get("due_date", "")
    )[:5]

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
            "overdue_count": sum(1 for t in tasks if t.get("status") == "overdue"),
            "pending_count": sum(1 for t in tasks if t.get("status") == "pending"),
            "filed_count": sum(1 for t in tasks if t.get("status") == "filed"),
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
    existing = client_repo.find_by_id(client_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(existing, firm_id)
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
    client = client_repo.find_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, firm_id)
    if client.get("status") == "archived":
        raise HTTPException(status_code=409, detail="Client is already archived")
    updated = client_repo.archive(client_id)
    return api_response(True, {"client": updated})


@router.post("/{client_id}/restore")
def restore_client(client_id: str, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, firm_id)
    if client.get("status") != "archived":
        raise HTTPException(status_code=409, detail="Client is not archived")
    updated = client_repo.restore(client_id)
    return api_response(True, {"client": updated})


@router.delete("/{client_id}")
def delete_client(client_id: str, current_user: dict = Depends(rbac("client", "delete"))):
    """
    Soft-delete a client (sets deleted_at). Blocked when open compliance
    obligations or active records exist.
    Historical data is never removed — only the client row is hidden.
    """
    firm_id = current_user.get("firm_id")
    client = client_repo.find_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, firm_id)

    blockers = _check_delete_blockers(client_id, firm_id)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Client cannot be deleted — resolve the following obligations first",
                "blockers": blockers,
            },
        )

    success = client_repo.soft_delete(client_id)
    if not success:
        raise HTTPException(status_code=500, detail="Delete failed")
    return api_response(True, {"message": "Client deleted", "client_id": client_id})
