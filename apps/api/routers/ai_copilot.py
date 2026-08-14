"""
AI Copilot Router — Enhanced AI assistant with firm context.
Different from /api/assistant (simple Q&A). Serves /api/ai-copilot.
"""
import os
import logging
import httpx
from fastapi import HTTPException, APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from fastapi import Request
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, effective_client_ids, filter_by_client
from middleware.rate_limit import check_rate_limit

_logger = logging.getLogger("caflow.ai_copilot")

router = APIRouter(prefix="/api/ai-copilot", tags=["ai-copilot"])

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

COPILOT_SYSTEM_PROMPT = """You are PracticeSync AI Copilot — an intelligent assistant for Indian Chartered Accountants.

You have access to the following firm context:
{firm_context}

You can help with:
- Searching and summarizing client information
- Explaining compliance status and risks
- Recommending actions for overdue filings
- Interpreting document risks
- Summarizing client health scores
- Explaining GST/ITR/TDS rules with section references (CGST Act 2017, IT Act 1961)

Be specific about numbers and deadlines. The context deliberately contains NO
client names or identifiers — do not ask for them, invent them, or claim to know
which client a figure belongs to. Answer with counts and general guidance, and
tell the user to open the relevant screen for per-client detail.

"Be specific" is not a licence to guess. If you are uncertain of a rule, a rate
or a date, say so and recommend the CA verify it — a wrong figure stated
confidently is worse to a CA than no answer. Rates and thresholds change with
each Finance Act, so name the year any rate you quote applies to.

Never advise submitting anything to a government portal on the user's behalf.
End tax law answers with: Source: [Act name], Section [number]
"""


class ChatMessage(BaseModel):
    role: str
    content: str


class CopilotRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = []
    context: Optional[str] = "general"


def _build_firm_context(firm_id: str, current_user: dict) -> str:
    """Build context string from live service layer data scoped to firm.

    R2.8/F19 tenancy fix: every call below must be scoped to firm_id — these
    three previously defaulted to firm_id=None, which returns platform-wide
    counts (active_clients, overdue_tasks, compliance_overdue, high_risk
    counts across every firm) into the Groq system prompt instead of the
    caller's own firm's numbers.

    M2: the CLIENT NAMES below are the sharp part — they go verbatim into the
    Groq system prompt, so an unassigned Executive could simply ask the copilot
    to list them. They are narrowed to the caller's assigned book.
    get_firm_summary takes allowed_client_ids (the F2 convention). The task
    dashboard and risk tallies expose no per-client scoping parameter and are
    left firm-wide COUNTS — no client is named in them; that is the same line
    already drawn for /api/copilot/intelligence/*, recorded in the audit doc
    rather than silently narrowed here.
    """
    allowed = effective_client_ids(current_user)

    try:
        from domain.task_service import TaskDomainService
        task_svc = TaskDomainService()
        dashboard = task_svc.get_dashboard_summary(firm_id=firm_id)
    except Exception:
        dashboard = {}

    try:
        from domain.compliance_record_service import compliance_record_service
        firm_summary = compliance_record_service.get_firm_summary(
            firm_id=firm_id, allowed_client_ids=allowed)
    except Exception:
        firm_summary = {}

    try:
        from domain.risk_engine import get_risk_dashboard_stats
        risk_stats = get_risk_dashboard_stats(firm_id=firm_id)
    except Exception:
        risk_stats = {}

    try:
        from repositories.client_repository import client_repo
        # Pass firm_id to prevent cross-firm data leak
        clients = client_repo.find_all(firm_id=firm_id)
        # `clients` rows key their own id as "id", not "client_id".
        # CLIENT CONFIDENTIALITY: client names are deliberately NOT collected here.
        # Only the COUNT reaches the prompt. See the note above the return below.
        client_count = len(filter_by_client(current_user, clients, key="id"))
    except Exception:
        client_count = 0

    lines = [
        f"Active Clients: {dashboard.get('active_clients', 0)}",
        # Count only — never the names. Groq is a third-party processor and a
        # client list is exactly the sort of thing an Indian CA practice must not
        # hand to one (ICAI client-confidentiality obligations). Aggregates keep
        # "what is my workload?" answerable while identifying nobody.
        f"Clients: {client_count}",
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
    """Return structured firm-level context for the AI Copilot panel.

    M2: `clients` below is a NAMED list of every client in the firm — the same
    leak _build_firm_context has, in structured form. Narrowed identically;
    see that function for why the task/risk tallies are left firm-wide."""
    firm_id = current_user.get("firm_id")

    try:
        from domain.task_service import TaskDomainService
        # R2.8/F19 tenancy fix: must be scoped to firm_id — omitting it returns
        # platform-wide active_clients/overdue_tasks/due_today/due_this_week
        # counts instead of the caller's own firm's numbers.
        dashboard = TaskDomainService().get_dashboard_summary(firm_id=firm_id)
    except Exception:
        dashboard = {}

    try:
        from domain.compliance_record_service import compliance_record_service
        firm_summary = compliance_record_service.get_firm_summary(
            firm_id=firm_id, allowed_client_ids=effective_client_ids(current_user))
    except Exception:
        firm_summary = {}

    try:
        from domain.risk_engine import get_risk_dashboard_stats
        risk_stats = get_risk_dashboard_stats(firm_id=firm_id)
    except Exception:
        risk_stats = {}

    try:
        from repositories.client_repository import client_repo
        clients = filter_by_client(current_user, client_repo.find_all(firm_id=firm_id), key="id")
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
    """REMOVED — deliberately a stub that returns nothing.

    This used to assemble a single client's name, entity type, GSTIN, PAN,
    status, open task titles with due dates and compliance records into a Groq
    prompt. Its only caller (the client-level copilot) is now a 410, so the
    body is gone rather than left as dead code: an unreachable function that
    still knows how to serialise a PAN is one refactor away from being reachable
    again. Kept as a stub only because a test monkeypatches this name.
    """
    return ""

@router.post("/client/{client_id}/chat")
async def client_copilot_chat(
    body: CopilotRequest,
    current_user: dict = Depends(rbac("ai", "copilot")),
):
    """DISABLED — this endpoint sent a single client's identifying data to Groq.

    It built its prompt from client_name, entity_type, GSTIN, PAN, status,
    individual task titles with due dates, and compliance records, and posted
    that to a third-party AI provider. Unlike the firm-level copilot there was
    no reduced version worth keeping: the endpoint's entire purpose was to feed
    one client's data to the model.

    Kept as an explicit 410 rather than deleted so callers get a clear reason
    instead of a bare 404, and so the removal is visible to anyone reading the
    router. If this comes back it needs a provider that does not retain
    submitted data, or a locally-hosted model — not a smaller prompt.
    """
    raise HTTPException(
        status_code=410,
        detail="The client-level copilot has been withdrawn: it sent client "
               "identifiers (GSTIN, PAN) to a third-party AI provider. Use the "
               "firm-level copilot, which carries no client-identifying data.",
    )


@router.post("/chat")
async def copilot_chat(request: Request, body: CopilotRequest, current_user: dict = Depends(rbac("ai", "copilot"))):
    check_rate_limit(request, current_user["firm_id"])
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return api_response(False, None, "AI Copilot is not configured on the server")

    try:
        firm_context = _build_firm_context(current_user["firm_id"], current_user)
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
        _logger.error("AI Copilot (firm) error: %s", e)
        return api_response(False, None, "AI Copilot is temporarily unavailable. Please try again.")
