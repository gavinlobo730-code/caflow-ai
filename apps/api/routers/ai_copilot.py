"""
AI Copilot Router — Enhanced AI assistant with firm context.
Different from /api/assistant (simple Q&A). Serves /api/ai-copilot.
"""
import os
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from fastapi import Request
from models.common import api_response
from core.permissions import rbac
from middleware.rate_limit import check_rate_limit

router = APIRouter(prefix="/api/ai-copilot", tags=["ai-copilot"])

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

COPILOT_SYSTEM_PROMPT = """You are CAflow AI Copilot — an intelligent assistant for Indian Chartered Accountants.

You have access to the following firm context:
{firm_context}

You can help with:
- Searching and summarizing client information
- Explaining compliance status and risks
- Recommending actions for overdue filings
- Interpreting document risks
- Summarizing client health scores
- Explaining GST/ITR/TDS rules with section references (CGST Act 2017, IT Act 1961)

Always be specific. Reference actual client names and data from the context when relevant.
End tax law answers with: Source: [Act name], Section [number]
"""


class ChatMessage(BaseModel):
    role: str
    content: str


class CopilotRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = []
    context: Optional[str] = "general"


def _build_firm_context(firm_id: str) -> str:
    """Build context string from live service layer data scoped to firm."""
    try:
        from domain.task_service import TaskDomainService
        task_svc = TaskDomainService()
        dashboard = task_svc.get_dashboard_summary()
    except Exception:
        dashboard = {}

    try:
        from domain.compliance_record_service import compliance_record_service
        firm_summary = compliance_record_service.get_firm_summary()
    except Exception:
        firm_summary = {}

    try:
        from domain.risk_engine import get_risk_dashboard_stats
        risk_stats = get_risk_dashboard_stats()
    except Exception:
        risk_stats = {}

    try:
        from repositories.client_repository import client_repo
        # Pass firm_id to prevent cross-firm data leak
        clients = client_repo.find_all(firm_id=firm_id)
        client_names = [c["client_name"] for c in clients]
    except Exception:
        client_names = []

    lines = [
        f"Active Clients: {dashboard.get('active_clients', 0)}",
        f"Clients: {', '.join(client_names) if client_names else 'N/A'}",
        f"Overdue Tasks: {dashboard.get('overdue_tasks', 0)}",
        f"Tasks Due Today: {dashboard.get('tasks_due_today', 0)}",
        f"Compliance Overdue: {dashboard.get('compliance_overdue', 0)}",
        f"High-Risk Clients: {dashboard.get('high_risk_clients', 0)}",
        f"Compliance Due This Week: {dashboard.get('compliance_due_week', 0)}",
        f"Overdue Compliance Records: {firm_summary.get('overdue', 0)}",
        f"Ready to File: {firm_summary.get('ready_to_file', 0)}",
        f"Open Risks — Critical: {risk_stats.get('critical', 0)}, High: {risk_stats.get('high', 0)}, Medium: {risk_stats.get('medium', 0)}",
        f"Total Open Risks: {risk_stats.get('total_open', 0)}",
    ]
    return "\n".join(lines)


@router.get("/firm-context")
def get_firm_context(current_user: dict = Depends(rbac("ai", "copilot"))):
    """Return structured firm-level context for the AI Copilot panel."""
    firm_id = current_user.get("firm_id")

    try:
        from domain.task_service import TaskDomainService
        dashboard = TaskDomainService().get_dashboard_summary()
    except Exception:
        dashboard = {}

    try:
        from domain.compliance_record_service import compliance_record_service
        firm_summary = compliance_record_service.get_firm_summary(firm_id=firm_id)
    except Exception:
        firm_summary = {}

    try:
        from domain.risk_engine import get_risk_dashboard_stats
        risk_stats = get_risk_dashboard_stats(firm_id=firm_id)
    except Exception:
        risk_stats = {}

    try:
        from repositories.client_repository import client_repo
        clients = client_repo.find_all(firm_id=firm_id)
        client_list = [{"id": c["id"], "name": c["client_name"], "status": c.get("status")} for c in clients]
    except Exception:
        client_list = []

    return api_response(True, {
        "active_clients": dashboard.get("active_clients", len(client_list)),
        "clients": client_list,
        "tasks": {
            "overdue": dashboard.get("overdue_tasks", 0),
            "due_today": dashboard.get("tasks_due_today", 0),
            "due_this_week": dashboard.get("tasks_due_week", 0),
        },
        "compliance": {
            "overdue": firm_summary.get("overdue", 0),
            "due_this_week": dashboard.get("compliance_due_week", 0),
            "ready_to_file": firm_summary.get("ready_to_file", 0),
            "filed": firm_summary.get("filed", 0),
        },
        "risks": {
            "critical": risk_stats.get("critical", 0),
            "high": risk_stats.get("high", 0),
            "medium": risk_stats.get("medium", 0),
            "total_open": risk_stats.get("total_open", 0),
        },
    })


def _build_client_context(firm_id: str, client_id: str) -> str:
    """Build context for a single client: profile, tasks, compliance, intelligence scores."""
    lines = []
    try:
        from repositories.client_repository import client_repo
        client = client_repo.find_by_id(client_id)
        if not client or client.get("firm_id") != firm_id:
            return ""
        lines.append(f"Client: {client.get('client_name')}")
        lines.append(f"Entity Type: {client.get('entity_type', 'N/A')}")
        lines.append(f"GSTIN: {client.get('gstin', 'N/A')}, PAN: {client.get('pan', 'N/A')}")
        lines.append(f"Status: {client.get('status', 'N/A')}")
    except Exception:
        return ""

    try:
        from repositories.task_repository import task_repo
        tasks = [t for t in task_repo.find_all(firm_id=firm_id) if t.get("client_id") == client_id]
        open_tasks = [t for t in tasks if t.get("status") != "completed"]
        lines.append(f"Open Tasks: {len(open_tasks)}")
        for t in open_tasks[:10]:
            lines.append(f"  - {t.get('title')} (due {t.get('due_date', 'n/a')}, {t.get('status')})")
    except Exception:
        pass

    try:
        from repositories.compliance_records_repository import compliance_records_repo
        records = [r for r in compliance_records_repo.find_all(firm_id=firm_id)
                   if r.get("client_id") == client_id]
        lines.append(f"Compliance Records: {len(records)}")
        for r in records[:10]:
            lines.append(
                f"  - {r.get('compliance_type') or r.get('type')} "
                f"(due {r.get('due_date', 'n/a')}, {r.get('status')})"
            )
    except Exception:
        pass

    try:
        from services.intelligence_service import compute_compliance_risk, compute_relationship_health
        risk = next((c for c in compute_compliance_risk(firm_id)["clients"]
                     if c["client_id"] == client_id), None)
        if risk:
            lines.append(f"Compliance Risk Score: {risk['risk_score']}/100 ({risk['risk_level']})")
        health = next((c for c in compute_relationship_health(firm_id)["clients"]
                       if c["client_id"] == client_id), None)
        if health:
            lines.append(f"Relationship Health: {health['health_score']}/100 ({health['health_level']})")
            lines.append(f"Outstanding Receivables: ₹{health['outstanding_paise'] // 100:,}")
    except Exception:
        pass

    return "\n".join(lines)


@router.post("/client/{client_id}/chat")
async def client_copilot_chat(
    client_id: str,
    body: CopilotRequest,
    current_user: dict = Depends(rbac("ai", "copilot")),
):
    """Client-level copilot: same model, context scoped to a single client."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return api_response(False, None, "GROQ_API_KEY not configured")

    client_context = _build_client_context(current_user["firm_id"], client_id)
    if not client_context:
        return api_response(False, None, "Client not found")

    try:
        system_prompt = COPILOT_SYSTEM_PROMPT.format(firm_context=client_context)
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": msg.role, "content": msg.content} for msg in body.conversation_history]
        messages.append({"role": "user", "content": body.message})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 1024},
                timeout=30,
            )

        if response.status_code != 200:
            return api_response(False, None, f"AI service error: {response.status_code}")

        answer: str = response.json()["choices"][0]["message"]["content"]
        return api_response(True, {"answer": answer, "client_id": client_id})
    except Exception as e:
        return api_response(False, None, f"AI Copilot error: {str(e)}")


@router.post("/chat")
async def copilot_chat(request: Request, body: CopilotRequest, current_user: dict = Depends(rbac("ai", "copilot"))):
    check_rate_limit(request, current_user["firm_id"])
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return api_response(False, None, "GROQ_API_KEY not configured")

    try:
        firm_context = _build_firm_context(current_user["firm_id"])
        system_prompt = COPILOT_SYSTEM_PROMPT.format(firm_context=firm_context)

        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": msg.role, "content": msg.content} for msg in body.conversation_history]
        messages.append({"role": "user", "content": body.message})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 1024},
                timeout=30,
            )

        if response.status_code != 200:
            return api_response(False, None, f"AI service error: {response.status_code}")

        answer: str = response.json()["choices"][0]["message"]["content"]

        # Extract suggested actions from response
        suggested_actions: list[str] = []
        lower = answer.lower()
        if "overdue" in lower:
            suggested_actions.append("View overdue compliance")
        if "risk" in lower:
            suggested_actions.append("Open Risk Dashboard")
        if "document" in lower:
            suggested_actions.append("Review Documents")
        if "task" in lower:
            suggested_actions.append("View Tasks")
        if "client" in lower:
            suggested_actions.append("View Clients")

        return api_response(True, {
            "answer": answer,
            "suggested_actions": suggested_actions[:3],
            "context_used": body.context,
        })

    except Exception as e:
        return api_response(False, None, f"AI Copilot error: {str(e)}")
