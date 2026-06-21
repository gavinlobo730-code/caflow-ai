"""
RazorpayProvider — real Razorpay adapter (env-gated, used when PAYMENT_PROVIDER=razorpay).

Razorpay amounts are already in paise, so amount_paise maps 1:1. Uses the REST API
via `requests` (imported lazily so this module never breaks import when the dep or
keys are absent). Webhook signature: HMAC-SHA256(webhook_secret, raw_body) compared
to the X-Razorpay-Signature header. Checkout redirect signature:
HMAC-SHA256(key_secret, "{order_id}|{payment_id}").

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this talks to an external payment
# gateway. No accounting is performed here; receipts are created only by
# payment_service via the existing receipt engine after a verified capture.
"""
import os
import hmac
import hashlib
import json
import logging
from typing import Optional

from services.payments.base import (
    PaymentProvider, PaymentLinkRequest, PaymentLinkResult, VerifiedEvent,
    CREATED, AUTHORIZED, CAPTURED, FAILED, REFUNDED,
)

_logger = logging.getLogger("caflow.payments.razorpay")
_API = "https://api.razorpay.com/v1"

_STATUS = {
    "created": CREATED, "authorized": AUTHORIZED, "captured": CAPTURED,
    "failed": FAILED, "refunded": REFUNDED,
}
_EVENT_STATUS = {
    "payment.authorized": AUTHORIZED,
    "payment.captured": CAPTURED,
    "payment.failed": FAILED,
    "payment_link.paid": CAPTURED,
    "refund.processed": REFUNDED,
}


class RazorpayProvider(PaymentProvider):
    name = "razorpay"

    def __init__(self):
        self._key_id = os.environ.get("RAZORPAY_KEY_ID", "")
        self._key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        self._webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").encode()

    def _auth(self):
        return (self._key_id, self._key_secret)

    def create_payment_link(self, req: PaymentLinkRequest) -> PaymentLinkResult:
        import requests  # lazy
        body = {
            "amount": req.amount_paise,            # already paise
            "currency": req.currency,
            "description": req.description[:255],
            "reference_id": req.reference_id,
            "notes": req.notes or {},
        }
        customer = {}
        if req.customer_name:
            customer["name"] = req.customer_name
        if req.customer_email:
            customer["email"] = req.customer_email
        if req.customer_phone:
            customer["contact"] = req.customer_phone
        if customer:
            body["customer"] = customer
            body["notify"] = {"email": bool(req.customer_email), "sms": bool(req.customer_phone)}
        if req.expires_at:
            body["expire_by"] = req.expires_at
        resp = requests.post(f"{_API}/payment_links", auth=self._auth(), json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return PaymentLinkResult(
            provider=self.name,
            provider_link_id=data.get("id", ""),
            provider_order_id=data.get("order_id"),
            short_url=data.get("short_url", ""),
            status=CREATED,
        )

    def get_payment_status(self, provider_payment_id: str) -> str:
        import requests  # lazy
        resp = requests.get(f"{_API}/payments/{provider_payment_id}", auth=self._auth(), timeout=20)
        resp.raise_for_status()
        return _STATUS.get(resp.json().get("status", ""), CREATED)

    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        expected = hmac.new(self._key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def process_webhook(self, headers: dict, raw_body: bytes) -> VerifiedEvent:
        sig = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature") or ""
        verified = False
        if self._webhook_secret:
            expected = hmac.new(self._webhook_secret, raw_body or b"", hashlib.sha256).hexdigest()
            verified = hmac.compare_digest(expected, sig)
        try:
            payload = json.loads((raw_body or b"").decode() or "{}")
        except Exception:
            payload = {}
        event_type = payload.get("event", "")
        container = (payload.get("payload") or {})
        entity = ((container.get("payment") or {}).get("entity")) or {}
        link_entity = ((container.get("payment_link") or {}).get("entity")) or {}
        return VerifiedEvent(
            provider=self.name,
            event_id=str(headers.get("x-razorpay-event-id") or payload.get("id") or entity.get("id") or ""),
            event_type=event_type,
            status=_EVENT_STATUS.get(event_type, CREATED),
            signature_verified=verified,
            provider_payment_id=entity.get("id"),
            provider_order_id=entity.get("order_id"),
            provider_link_id=entity.get("payment_link_id") or link_entity.get("id"),
            amount_paise=entity.get("amount"),
            raw=payload,
        )
