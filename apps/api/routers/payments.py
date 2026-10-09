"""
Payments router (Phase 4.6) — online payment links + the gateway webhook.

Staff endpoints (/api/payments/*) are rbac-gated (accounting) and firm-scoped.
The webhook (/api/payments/webhook/{provider}) is PUBLIC by design (gateways
cannot authenticate as a staff user) — it is protected instead by provider
signature verification, replay protection and idempotency inside payment_service.

A gateway never performs accounting; receipts are created solely by the existing
receipt engine on a verified capture. All amounts are integer paise.
"""
import os
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from models.common import api_response
from core.client_ip import client_ip
from core.permissions import rbac
from domain.payments import availability as payable
from services import payment_service
from services.payments import availability as online_payment
from core import db_provider

router = APIRouter(prefix="/api/payments", tags=["payments"])

#: A gateway's webhook is a few kilobytes of JSON. This route is public and its
#: body is parsed BEFORE the signature is checked (the providers read the event
#: type and id out of it), so an unbounded body is an unauthenticated way to make
#: the process parse and hold whatever it is sent. Well above any real delivery.
MAX_WEBHOOK_BODY_BYTES = 256 * 1024

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.payments")


def _db():
    # Real Supabase client, or None in mock mode (online payments require a DB).
    return None if _USE_MOCK else db_provider.request_db()


def _require_db():
    db = _db()
    if db is None:
        raise HTTPException(status_code=501, detail="Online payments require a configured database.")
    return db


class CreateLinkBody(BaseModel):
    invoice_id: str


# ── Staff: payment links + history (Deliverables D, G) ────────────────────────

@router.post("/links")
def create_payment_link(body: CreateLinkBody, current_user: dict = Depends(rbac("accounting", "write"))):
    """Generate a payment link for an invoice's exact outstanding balance.

    Refused with a 409 and the server's own sentence ("Online payment is coming soon. ...") unless a real gateway
    is set up: with the test double the link is an address that does not exist. Asked HERE and not inside
    `payment_service.create_link`, which the tests drive directly with the double (PRE-B-002 part 2).
    """
    online_payment.require_online_payment("staff")
    db = _require_db()
    link = payment_service.create_link(db, current_user.get("firm_id"), body.invoice_id, actor=current_user)
    return api_response(True, link)


@router.get("/links")
def list_payment_links(invoice_id: str = Query(...), current_user: dict = Depends(rbac("accounting", "read"))):
    db = _require_db()
    return api_response(True, payment_service.list_links(db, current_user.get("firm_id"), invoice_id, current_user))


@router.get("/links/{link_id}")
def get_payment_link(link_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    db = _require_db()
    link = payment_service.get_link(db, current_user.get("firm_id"), link_id, current_user)
    if not link:
        raise HTTPException(status_code=404, detail="Payment link not found.")
    # `get_link` is the sender's own resolver and returns the stored row; what a SCREEN is shown has an address
    # that goes nowhere taken off it.
    return api_response(True, payable.mask_link(link))


@router.post("/links/{link_id}/send")
def send_payment_link(link_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Email the payment link to the customer (reuses email + invoice_deliveries).

    One click by a member of the practice, never a schedule (D27). Refused with a 409 while no gateway is set up,
    and again inside the service for a link that cannot be paid (made by the test double, expired, paid, ...).
    """
    online_payment.require_online_payment("staff")
    db = _require_db()
    return api_response(True, payment_service.send_link_email(db, current_user.get("firm_id"), link_id, actor=current_user))


@router.get("")
def payment_history(invoice_id: str = Query(...), current_user: dict = Depends(rbac("accounting", "read"))):
    """Outstanding + links + payments for an invoice (payment history / timeline)."""
    db = _require_db()
    return api_response(True, payment_service.history(db, current_user.get("firm_id"), invoice_id, current_user))


# ── Public webhook (Deliverables E, I) ────────────────────────────────────────

@router.post("/webhook/{provider}")
async def payment_webhook(provider: str, request: Request):
    """Gateway webhook. Signature-verified, replay-protected and idempotent inside
    payment_service. A bad signature is rejected with 400 and leaves a log line, a
    counter and (at most a capped sample of) an event row — never an audit_log
    row; past 100 of them a minute from one address it is 429. A verified capture
    settles via the existing receipt engine exactly once.

    THE ONE ROUTE THAT MUST STAY `async def`. A sync route cannot reach the raw
    request body, and the signature is computed over the exact bytes the gateway
    sent — re-serialising a parsed payload changes them and every signature
    fails. So the body is awaited here and the BLOCKING half is handed to the
    threadpool instead: process_webhook verifies, reads and writes, all
    synchronously, and running it on the event loop stalls every other request
    on this worker while a gateway is being talked to.
    """
    db = _require_db()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Webhook body too large.")
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BODY_BYTES:          # chunked: no Content-Length to go on
        raise HTTPException(status_code=413, detail="Webhook body too large.")
    headers = {k.lower(): v for k, v in request.headers.items()}
    result = await run_in_threadpool(
        payment_service.process_webhook, db, provider, headers, raw, client_ip(request))
    if not result.get("ok"):
        if result.get("reason") == "rate_limited":
            # Unsigned requests from one address beyond the window. The gateway
            # never sees this: a signed delivery is not counted (see
            # payment_service._refuse_unsigned).
            raise HTTPException(status_code=429, detail="Too many requests.",
                                headers={"Retry-After": str(payment_service.UNSIGNED_WINDOW_SECONDS)})
        # Invalid signature (or unprocessable) — do not leak detail.
        raise HTTPException(status_code=400, detail="Webhook rejected.")
    return api_response(True, result)
