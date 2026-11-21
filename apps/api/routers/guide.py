"""
"Where is…?": which screen answers a person's question (POST-A-538).

POST /api/guide/where    {question, offered: [screen ids]}  ->  {screens: [at most three of those ids, best first]}

The route reaches a model, so it is rate limited per firm and per person like every route that does, and the firm's own
monthly allowance is asked by the chat door before anything is sent. `domain/guide/where.py` has the whole account of what
the model is given (the question and the product's own list of screens; nothing of the firm's) and what it may say (ids).

It is `ai:read`, the permission every staff role holds: a Reviewer on their first day is who most needs to ask.

WHAT A CALLER DOES WITH A REFUSAL. A model that is not configured (503), over the firm's allowance or rate limited (429),
or that did not answer (502, 504) is answered with the sentence the chat door wrote. The screen then falls back to a plain
search of the same list and says that it did, so a person is never left with nothing.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.permissions import rbac
from domain.ai import groq_text
from domain.guide import where
from middleware.rate_limit import ai_limit
from models.common import api_response

router = APIRouter(prefix="/api/guide", tags=["guide"])
_logger = logging.getLogger("caflow.guide")


class WhereIn(BaseModel):
    question: str
    #: The ids of the screens this person is offered (the menus' rule, said by the browser). Each must be a screen of the
    #: product: the text the model reads about a screen is the server's own.
    offered: list[str]


@router.post("/where")
async def where_is(body: WhereIn, current_user: dict = Depends(rbac("ai", "read")),
                   _limit: None = Depends(ai_limit("chat"))):
    problem = where.question_problem(body.question)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    try:
        screens = where.offered(body.offered)
    except where.NotAScreen as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        # 503 and the variable's name, as the assistant answers: a missing key is a deployment setting.
        raise HTTPException(status_code=503, detail=(
            "PracticeSync AI is not configured on this server: GROQ_API_KEY is not set."))

    try:
        reply = await groq_text.chat_detailed(
            where.build_messages(body.question, screens), api_key=api_key, max_tokens=where.MAX_TOKENS,
            temperature=0, feature="guide", firm_id=current_user.get("firm_id"), user_id=current_user.get("id"),
            reasoning_effort="low", response_schema=where.SCHEMA)
    except groq_text.ProviderFailed as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.sentence) from exc

    return api_response(True, {"screens": where.picks(reply.text, screens)})
