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
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from services import payment_service

router = APIRouter(prefix="/api/payments", tags=["payments"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.payments")


def _db():
    """Real Supabase client, or None in mock mode (online payments require a DB)."""
    if _USE_MOCK:
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


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
    """Generate a payment link for an invoice's exact outstanding balance."""
    db = _require_db()
    link = payment_service.create_link(db, current_user.get("firm_id"), body.invoice_id, actor=current_user)
    return api_response(True, link)


@router.get("/links")
def list_payment_links(invoice_id: str = Query(...), current_user: dict = Depends(rbac("accounting", "read"))):
    db = _require_db()
    return api_response(True, payment_service.list_links(db, current_user.get("firm_id"), invoice_id))


@router.get("/links/{link_id}")
def get_payment_link(link_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    db = _require_db()
    link = payment_service.get_link(db, current_user.get("firm_id"), link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Payment link not found.")
    return api_response(True, link)


@router.post("/links/{link_id}/send")
def send_payment_link(link_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Email the payment link to the customer (reuses email + invoice_deliveries)."""
    db = _require_db()
    return api_response(True, payment_service.send_link_email(db, current_user.get("firm_id"), link_id, actor=current_user))


@router.get("")
def payment_history(invoice_id: str = Query(...), current_user: dict = Depends(rbac("accounting", "read"))):
    """Outstanding + links + payments for an invoice (payment history / timeline)."""
    db = _require_db()
    return api_response(True, payment_service.history(db, current_user.get("firm_id"), invoice_id))


# ── Public webhook (Deliverables E, I) ────────────────────────────────────────

@router.post("/webhook/{provider}")
async def payment_webhook(provider: str, request: Request):
    """Gateway webhook. Signature-verified, replay-protected and idempotent inside
    payment_service. A bad signature is recorded and rejected with 400; a verified
    capture settles via the existing receipt engine exactly once."""
    db = _require_db()
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    result = payment_service.process_webhook(db, provider, headers, raw)
    if not result.get("ok"):
        # Invalid signature (or unprocessable) — do not leak detail.
        raise HTTPException(status_code=400, detail="Webhook rejected.")
    return api_response(True, result)
