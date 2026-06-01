"""
AI Copilot Router — Enhanced AI assistant with firm context.
Different from /api/assistant (simple Q&A). Serves /api/ai-copilot.
"""
import os
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from models.common import api_response

router = APIRouter(prefix="/api/ai-copilot", tags=["ai-copilot"])

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


def _build_firm_context() -> str:
    """Build context string from live service layer data."""
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
        clients = client_repo.find_all()
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


@router.post("/chat")
def copilot_chat(body: CopilotRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return api_response(False, None, "ANTHROPIC_API_KEY not configured")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        firm_context = _build_firm_context()
        system_prompt = COPILOT_SYSTEM_PROMPT.format(firm_context=firm_context)

        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in body.conversation_history
        ]
        messages.append({"role": "user", "content": body.message})

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )

        answer = response.content[0].text if response.content else ""

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
