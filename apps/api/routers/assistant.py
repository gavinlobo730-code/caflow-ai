import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

SYSTEM_PROMPT = (
    "You are a GST and Income Tax expert assistant for Indian Chartered Accountants. "
    "Answer questions accurately citing the relevant section of the CGST Act 2017, "
    "IGST Act, or Income Tax Act 1961. Always end your answer with: "
    "Source: [Act name], Section [number]. "
    "If unsure, say so — never guess on tax matters."
)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


class Message(BaseModel):
    role: str
    content: str


class AssistantRequest(BaseModel):
    question: str
    conversation_history: Optional[List[Message]] = []
    client_id: Optional[str] = None


@router.post("")
async def assistant(request: AssistantRequest, current_user: dict = Depends(rbac("ai", "read"))):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="AI assistant is not configured on the server")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m.role, "content": m.content} for m in (request.conversation_history or [])]
    messages.append({"role": "user", "content": request.question})

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 1024},
            timeout=30,
        )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="AI service error. Please try again.")

    full_answer: str = response.json()["choices"][0]["message"]["content"]

    source = ""
    if "Source:" in full_answer:
        parts = full_answer.rsplit("Source:", 1)
        answer = parts[0].strip()
        source = "Source:" + parts[1].strip()
    else:
        answer = full_answer

    return api_response(True, {"answer": answer, "source": source})
