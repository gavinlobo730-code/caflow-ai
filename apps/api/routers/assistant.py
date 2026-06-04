from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from models.common import api_response
from core.permissions import rbac
import anthropic
import os

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

SYSTEM_PROMPT = (
    "You are a GST and Income Tax expert assistant for Indian Chartered Accountants. "
    "Answer questions accurately citing the relevant section of the CGST Act 2017, "
    "IGST Act, or Income Tax Act 1961. Always end your answer with: "
    "Source: [Act name], Section [number]. "
    "If unsure, say so — never guess on tax matters."
)


class Message(BaseModel):
    role: str
    content: str


class AssistantRequest(BaseModel):
    question: str
    conversation_history: Optional[List[Message]] = []
    client_id: Optional[str] = None


@router.post("")
async def assistant(request: AssistantRequest, current_user: dict = Depends(rbac("ai", "read"))):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": m.role, "content": m.content} for m in (request.conversation_history or [])]
    messages.append({"role": "user", "content": request.question})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    full_answer = response.content[0].text
    source = ""
    if "Source:" in full_answer:
        parts = full_answer.rsplit("Source:", 1)
        answer = parts[0].strip()
        source = "Source:" + parts[1].strip()
    else:
        answer = full_answer

    return api_response(True, {"answer": answer, "source": source})
