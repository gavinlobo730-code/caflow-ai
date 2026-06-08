from fastapi import APIRouter, Depends, HTTPException, Path, Query
from models.client import ClientCreate, ClientUpdate
from models.common import api_response
from core.permissions import rbac
from repositories.client_repository import client_repo
from repositories.compliance_records_repository import compliance_records_repo
from mock_data import MOCK_COMPLIANCE_TASKS, MOCK_DOCUMENTS, MOCK_ACTIVITY_LOGS, MOCK_AI_INSIGHTS, MOCK_TASKS
from datetime import date

router = APIRouter(prefix="/api/clients", tags=["clients"])


def _assert_firm(client: dict, firm_id: str | None) -> None:
    """Raise 404 if client belongs to a different firm."""
    if client.get("firm_id") and client["firm_id"] != firm_id:
        raise HTTPException(status_code=404, detail="Client not found")


def _check_delete_blockers(client_id: str, firm_id: str) -> list[str]:
    """
    Return a list of human-readable blockers that prevent soft-deletion.
    Deletion is safe only when all compliance obligations are filed and
    no active compliance records exist.
    """
    blockers: list[str] = []

    # Open compliance tasks (mock path — real path goes via repo)
    open_tasks = [
        t for t in MOCK_COMPLIANCE_TASKS
        if t["client_id"] == client_id and t.get("status") not in ("filed", "not_applicable")
        and (t.get("firm_id") == firm_id or t.get("firm_id") is None)
    ]
    if open_tasks:
        blockers.append(
            f"{len(open_tasks)} open compliance task(s): "
            + ", ".join(t.get("compliance_type", "?") for t in open_tasks[:3])
            + (" and more" if len(open_tasks) > 3 else "")
        )

    # Active compliance records
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
    client = client_repo.find_by_id(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(client, current_user.get("firm_id"))

    tasks = [t for t in MOCK_COMPLIANCE_TASKS if t["client_id"] == client_id]
    docs = [d for d in MOCK_DOCUMENTS if d["client_id"] == client_id]
    activity = [a for a in MOCK_ACTIVITY_LOGS if a["client_id"] == client_id]
    insights = [i for i in MOCK_AI_INSIGHTS if i["client_id"] == client_id]
    client_tasks = [t for t in MOCK_TASKS if t["client_id"] == client_id and t["status"] != "completed"]
    completed_tasks = [t for t in MOCK_TASKS if t["client_id"] == client_id and t["status"] == "completed"]

    upcoming = sorted(
        [t for t in tasks if t["status"] in ("pending", "overdue")],
        key=lambda t: t["due_date"]
    )[:5]

    return api_response(True, {
        "profile": client,
        "compliance_tasks": tasks,
        "upcoming_deadlines": upcoming,
        "documents": docs,
        "recent_activity": sorted(activity, key=lambda a: a["created_at"], reverse=True)[:10],
        "ai_insights": [i for i in insights if i["status"] in ("open", "acknowledged")],
        "open_tasks": client_tasks,
        "completed_tasks": completed_tasks[:5],
        "task_summary": {
            "open": len(client_tasks),
            "completed": len(completed_tasks),
            "overdue": len([t for t in client_tasks if t.get("due_date") and t["due_date"] < date.today().isoformat()]),
            "review_required": len([t for t in client_tasks if t["status"] == "review_required"]),
        },
        "summary": {
            "total_tasks": len(tasks),
            "overdue_count": sum(1 for t in tasks if t["status"] == "overdue"),
            "pending_count": sum(1 for t in tasks if t["status"] == "pending"),
            "filed_count": sum(1 for t in tasks if t["status"] == "filed"),
            "document_count": len(docs),
            "open_insights": sum(1 for i in insights if i["status"] == "open"),
        }
    })


@router.post("")
def create_client(body: ClientCreate, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    data = {**body.model_dump(), "firm_id": firm_id}
    client = client_repo.create(data)
    return api_response(True, {"client": client})


@router.patch("/{client_id}")
def update_client(client_id: str, body: ClientUpdate, current_user: dict = Depends(rbac("client", "write"))):
    firm_id = current_user.get("firm_id")
    existing = client_repo.find_by_id(client_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_firm(existing, firm_id)
    # archived → active transition must use the restore endpoint
    if body.status and body.status.value == "archived":
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/clients/{id}/archive to archive a client"
        )
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = client_repo.update(client_id, updates)
    return api_response(True, {"client": updated})


@router.post("/{client_id}/archive")
def archive_client(client_id: str, current_user: dict = Depends(rbac("client", "write"))):
    """
    Archive a client. Archived clients are hidden from normal listings but
    all historical data is preserved. Can be reversed with /restore.
    """
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
    """
    Restore an archived client back to active status.
    """
    firm_id = current_user.get("firm_id")
    # find_by_id skips deleted rows — archived rows are visible
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
    Soft-delete a client (sets deleted_at). This is irreversible without DB admin access.
    Requires Partner role. Blocked when open compliance obligations or active records exist.
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
