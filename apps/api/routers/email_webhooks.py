"""The email provider's webhook: a bounce or a complaint marks the address (ops-21).

PUBLIC BY DESIGN, like the payment gateway's webhook: the caller is the provider, which cannot log
in. It is protected instead by the provider's signature (`domain/email_events.verify`) - a request
that does not carry a valid one writes nothing (SECURITY-PRIVACY-23) and is counted and, past 100 a
minute from one address, throttled. The body is capped at 256 KB before it is read and again
after, because it is parsed only once it has been verified and an unauthenticated route must not
buffer whatever it is sent.

NOT CONFIGURED IS A 503 AND NEVER AN OPEN DOOR: `RESEND_WEBHOOK_SECRET` unset (or not a signing
secret) answers 503 to every caller. The provider retries a 5xx, so a delivery sent before the
secret was set is not lost for good.

THE ONE ROUTE THAT MUST STAY `async def`, for the reason the payment webhook's docstring gives: the
signature is computed over the exact bytes sent, which only the raw body has. The blocking half
(database writes) is handed to the threadpool.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core import db_provider
from core.client_ip import client_ip
from domain import email_events
from models.common import api_response
from services import email_events_service

router = APIRouter(prefix="/api/email", tags=["email"])

_logger = logging.getLogger("caflow.email_webhooks")

#: A delivery event is a few hundred bytes of JSON.
MAX_WEBHOOK_BODY_BYTES = 256 * 1024


# The service-role client, or None in mock mode (there are no delivery tables to update).
_db = db_provider.service_db_or_none


@router.post("/webhook/resend")
async def resend_webhook(request: Request):
    """Resend's delivery events. Signature-verified; a permanent bounce or a complaint suppresses
    the address and marks the message; everything else is acknowledged and ignored."""
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "").strip()
    if not secret or email_events.decode_secret(secret) is None:
        raise HTTPException(status_code=503, detail="The email webhook is not configured.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Webhook body too large.")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BODY_BYTES:          # chunked: no Content-Length to go on
        raise HTTPException(status_code=413, detail="Webhook body too large.")
    headers = {k.lower(): v for k, v in request.headers.items()}
    result = await run_in_threadpool(
        email_events_service.process, secret, headers, raw, client_ip(request), db=_db())
    if not result.get("ok"):
        if result.get("reason") == "rate_limited":
            raise HTTPException(status_code=429, detail="Too many requests.",
                                headers={"Retry-After": str(email_events_service.UNSIGNED_WINDOW_SECONDS)})
        # Unsigned, badly signed or unreadable: say nothing about which.
        raise HTTPException(status_code=400, detail="Webhook rejected.")
    return api_response(True, result)
