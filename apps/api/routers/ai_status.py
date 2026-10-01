"""Is the AI answering? — the Partner's status and the one button that asks. (ai-06)

FOUR ROUTES, AND ONLY ONE OF THEM COSTS ANYTHING.
    `GET  /api/ai-status`          reads: what this process has seen each provider
                                   do and what this firm's own usage rows say.
                                   Free, unlimited, no model call.
    `POST /api/ai-status/probe`    makes ONE small real call to ONE provider
                                   through the gateway, so it uses the real key and
                                   the real model name and leaves the real usage row.
                                   Rate limited (bucket `probe`) AFTER the permission
                                   check, so a refusal spends nothing.
    `GET  /api/ai-status/usage`    what the firm's AI use came to in a month (tokens,
                                   pages, calls, failures, by feature and by day) and
                                   where it stands against its allowance (ai-17).
    `PUT  /api/ai-status/budget`   sets or clears the firm's monthly allowance. The
                                   one write; audited; both limits travel together.

ONE PROVIDER PER REQUEST. A failing provider can spend the gateway's whole forty
seconds, and `lib/api` abandons a request at forty-five and never retries, so two
providers in one request could not both answer in time. The screen asks twice.

PARTNER-ONLY, behind `mfa_guard` — the same footing as the security posture, for
the same reason: it reports what the deployment is configured with (model names,
which keys exist) and it spends the firm's quota.

A FAILURE IS A 200 WITH A SENTENCE. A person pressing "check" wants to be told
that the model was retired or the key was revoked, in words, and that is the
point of the screen — it is not an error of the request.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StrictInt

from core.auth import mfa_guard
from core.permissions import rbac
from core.ist_clock import ist_today
from domain.ai import budget as ai_budget
from domain.ai import probe as ai_probe
from middleware.rate_limit import ai_limit
from models.common import api_response
from services import ai_status_service, ai_usage_service
from services.audit_service import log_event

router = APIRouter(prefix="/api/ai-status", tags=["ai"])


def _db():
    """The privileged client, or None with no database. Every read carries the
    caller's `firm_id`; the table's own policy would only show a Partner their own
    firm, and this is the client the stored history is written with."""
    if not os.environ.get("SUPABASE_URL"):
        return None
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


@router.get("", dependencies=[Depends(mfa_guard)])
def ai_status(current_user: dict = Depends(rbac("firm", "admin"))) -> dict:
    return api_response(True, ai_status_service.status(_db(), current_user["firm_id"]))


@router.post("/probe", dependencies=[Depends(mfa_guard)])
def run_probe(
    provider: Literal["groq", "gemini"] = Query(...),
    current_user: dict = Depends(rbac("firm", "admin")),
    _limit: None = Depends(ai_limit("probe")),
) -> dict:
    firm_id = current_user["firm_id"]
    result = ai_probe.probe(provider, firm_id=firm_id, user_id=current_user.get("id"))
    # A probe spends the firm's quota and says whether its key works, so it is
    # something an auditor may ask about. No text of any kind is recorded.
    log_event(firm_id, "ai_probe", "", "create",
              actor_id=current_user.get("auth_user_id"),
              new_data={"provider": provider, "state": result.state, "kind": result.kind,
                        "model": result.model, "answered_by": result.answered_by})
    return api_response(True, {"result": result.as_dict(),
                               "status": ai_status_service.status(_db(), firm_id)})


@router.get("/usage", dependencies=[Depends(mfa_guard)])
def ai_usage(
    month: Optional[str] = Query(None, description="YYYY-MM; the current IST month when absent"),
    current_user: dict = Depends(rbac("firm", "admin")),
) -> dict:
    try:
        chosen = ai_budget.parse_month(month, ist_today())
    except ai_budget.BudgetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return api_response(True, ai_usage_service.usage(_db(), current_user["firm_id"], chosen))


class AllowanceIn(BaseModel):
    """BOTH keys are required and `null` means no limit, so the request says what the
    allowance IS afterwards: a screen that sends one limit cannot clear the other by leaving
    it out, and a client that sends neither changes nothing it meant to."""
    monthly_token_limit: Optional[StrictInt]
    monthly_page_limit: Optional[StrictInt]


@router.put("/budget", dependencies=[Depends(mfa_guard)])
def set_ai_budget(
    body: AllowanceIn,
    current_user: dict = Depends(rbac("firm", "admin")),
) -> dict:
    db = _db()
    if db is None:
        raise HTTPException(status_code=503, detail=ai_usage_service.NO_DATABASE)
    try:
        limits = ai_budget.Limits(
            monthly_tokens=ai_budget.validate_limit(
                body.monthly_token_limit, name="The token limit", maximum=ai_budget.MAX_TOKEN_LIMIT),
            monthly_pages=ai_budget.validate_limit(
                body.monthly_page_limit, name="The page limit", maximum=ai_budget.MAX_PAGE_LIMIT))
    except ai_budget.BudgetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    firm_id = current_user["firm_id"]
    previous = ai_usage_service.set_limits(db, firm_id, current_user.get("id"), limits)
    # A change to what the firm may spend is something an auditor may ask about.
    log_event(firm_id, "ai_firm_budget", firm_id, "update",
              actor_id=current_user.get("auth_user_id"),
              old_data=previous.as_dict(), new_data=limits.as_dict())
    return api_response(True, ai_usage_service.usage(db, firm_id, ai_budget.month_of(ist_today())))
