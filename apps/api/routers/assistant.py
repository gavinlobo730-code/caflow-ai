import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from models.common import api_response
from core.permissions import rbac

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# Ported from the frontend's dead /app/api/ai-assistant route (removed in #220),
# which carried a far richer domain brief than this endpoint had. Two things had
# to survive the move and are load-bearing:
#
#   1. THE "Source:" TRAILER IS A PARSER CONTRACT, not a stylistic preference.
#      The endpoint below splits the reply on the last "Source:" to populate the
#      `source` field. The frontend prompt never asked for it, so porting it
#      verbatim would have silently blanked that field on every answer. It is
#      stated first and last here for that reason, and pinned by a test.
#
#   2. RATES ARE DATED, DEADLINES ARE NOT. The statutory due dates below are
#      stable and match CLAUDE.md. The slab and surcharge figures came from a
#      specific Finance Act and were labelled with a forward financial year, as
#      if unchanged rates were a fact rather than an assumption. A CA asking
#      "what are the slabs" and receiving confidently wrong numbers is the worst
#      failure this endpoint has available to it, so the rates are attributed to
#      their source Act and the model is told to say when it cannot confirm the
#      year — rather than restating them as settled for a year nobody verified.
SYSTEM_PROMPT = """You are an expert AI assistant for Indian Chartered Accountants \
using PracticeSync. You answer on Indian taxation, GST and statutory compliance.

OUTPUT CONTRACT — follow exactly:
Always end your answer with a final line of the form:
Source: [Act name], Section [number]
This line is parsed by the application. Never omit it, never place anything after \
it, and never use the word "Source:" anywhere earlier in the answer.

INCOME TAX RATES (Finance Act 2025, for FY 2025-26 / AY 2026-27):
- New Tax Regime (default): 0-4L Nil, 4-8L 5%, 8-12L 10%, 12-16L 15%, 16-20L 20%, \
20-24L 25%, above 24L 30%
- Rebate u/s 87A: no tax payable if total income <= Rs 12 lakh under the new regime
- Standard deduction for salaried: Rs 75,000 under the new regime
- Old Tax Regime slabs: 0-2.5L Nil, 2.5-5L 5%, 5-10L 20%, above 10L 30%
- Surcharge: 10% (50L-1Cr), 15% (1Cr-2Cr), 25% (2Cr-5Cr), 37% (above 5Cr) — old \
regime only; capped at 25% under the new regime
- Health & Education Cess: 4% on tax plus surcharge

These rates are as enacted by the Finance Act 2025. If the user asks about a LATER \
financial year, say plainly that a subsequent Finance Act may have amended them and \
that the figures must be confirmed against the Act for that year. Do not restate \
them as current for a year you cannot verify.

GST COMPLIANCE (CGST Act) — statutory due dates:
- GSTR-1: 11th of the following month (Section 37); QRMP filers 13th
- GSTR-3B: 20th of the following month (Section 39); 22nd/24th for small taxpayers
- GSTR-9 annual return: 31st December (Section 44)
- GSTR-2B auto-populated by the 14th of the following month
- E-invoicing mandatory above Rs 5 crore turnover
- Registration thresholds: Rs 40L goods, Rs 20L services, Rs 10L special category states

TDS (rates per Finance Act 2025; thresholds and due dates statutory):
- Section 194C contractors: 1% individual/HUF, 2% others; threshold Rs 30,000 single / Rs 1L annual
- Section 194J professional fees: 10%; threshold Rs 30,000
- Section 192 salary: applicable slab rates
- Section 194A interest (non-bank): 10%; threshold Rs 5,000
- Section 194I rent: 2% plant/machinery, 10% land/building; threshold Rs 2.4L annual
- Section 194Q purchase of goods: 0.1%; threshold Rs 50L
- 24Q/26Q returns: 31 July (Q1), 31 October (Q2), 31 January (Q3), 31 May (Q4). \
Q4 is 31 May, NOT 30 April — it is the one quarter that does not follow the \
"end of the month after quarter end" pattern.

ADVANCE TAX (IT Act Sections 208 and 211), cumulative:
- 15 June 15%, 15 September 45%, 15 December 75%, 15 March 100%

MCA / COMPANIES ACT 2013:
- AOC-4 financial statements: within 30 days of the AGM
- MGT-7 / 7A annual return: within 60 days of the AGM
- DIR-3 KYC: 30 September annually
- ADT-1 auditor appointment: within 15 days of the AGM

RULES:
- Cite the specific provision, e.g. "Section 44 of the CGST Act", "Section 139 of \
the IT Act". A general answer with no section is not useful to a CA.
- The Indian financial year runs 1 April to 31 March.
- For anything to be filed or submitted, add: "Please have your CA review before filing."
- Never advise on tax evasion or aggressive avoidance.
- If you are unsure, say so. Never guess on a tax matter — a wrong figure stated \
confidently is worse than no answer.
- End with the Source: line described in the output contract above."""

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def split_source(full_answer: str) -> tuple[str, str]:
    """Split a reply into (answer, citation) on the trailing "Source:" marker.

    Module-level and public so the tests exercise THIS code rather than a copy
    of it. The first version of the test reimplemented the split inline, and the
    copy immediately drifted from the original — which is the same class of
    mistake as the prompt and the parser disagreeing, only in the test.

    rsplit, not split: the marker is defined as the LAST thing in the reply, so
    a stray earlier mention must not carve the answer in half. Returns an empty
    citation when the model omitted the marker — a degraded answer, not an
    error, which is exactly why the prompt's demand for it is asserted in tests.
    """
    if "Source:" not in full_answer:
        return full_answer, ""
    body, citation = full_answer.rsplit("Source:", 1)
    # Rebuilt with the space: .strip() removes the one the model wrote after the
    # colon, and rebuilding without it rendered every citation as
    # "Source:CGST Act, Section 37".
    return body.strip(), "Source: " + citation.strip()


class Message(BaseModel):
    role: str
    content: str


class AssistantRequest(BaseModel):
    question: str
    conversation_history: Optional[List[Message]] = []
    # NOTE: a client_id field used to sit here and was read by nothing — this
    # endpoint is a pure Groq passthrough over a static SYSTEM_PROMPT and loads
    # no client data. Removed because this router carries NO mount-level client
    # guard (main.py includes it with no dependencies), so a dead client_id is
    # a trap: the moment someone wires it up to real client context, there is
    # nothing enforcing assignment scope. If the assistant ever becomes
    # client-aware, add _CLIENT_GUARD to its include_router FIRST. Pydantic
    # ignores unknown fields by default, so callers still sending it are fine.


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

    answer, source = split_source(full_answer)

    return api_response(True, {"answer": answer, "source": source})
