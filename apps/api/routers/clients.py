from fastapi import APIRouter, Depends, HTTPException, Path
from models.client import ClientCreate, ClientUpdate
from models.common import api_response
from core.permissions import rbac
from mock_data import (
    MOCK_CLIENTS, MOCK_COMPLIANCE_TASKS, MOCK_DOCUMENTS,
    MOCK_ACTIVITY_LOGS, MOCK_AI_INSIGHTS, CLIENT_INDEX, MOCK_TASKS,
)
from datetime import date

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("")
def list_clients(current_user: dict = Depends(rbac("client", "read"))):
    return api_response(True, {"clients": MOCK_CLIENTS, "total": len(MOCK_CLIENTS)})


@router.get("/{client_id}")
def get_client_workspace(client_id: str = Path(...), current_user: dict = Depends(rbac("client", "read"))):
    client = CLIENT_INDEX.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

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
    import uuid
    new_client = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "created_at": date.today().isoformat(),
        "updated_at": date.today().isoformat(),
    }
    return api_response(True, {"client": new_client})


@router.patch("/{client_id}")
def update_client(client_id: str, body: ClientUpdate, current_user: dict = Depends(rbac("client", "write"))):
    client = CLIENT_INDEX.get(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = {**client, **updates, "updated_at": date.today().isoformat()}
    return api_response(True, {"client": updated})
