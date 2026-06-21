"""
MockProvider — a deterministic, dependency-free payment provider for tests/dev.

It performs REAL HMAC-SHA256 signature verification (so webhook signature /
replay tests are meaningful) but never makes a network call. Webhook payloads
use the same shape as Razorpay so the parsing path is shared.
"""
import os
import json
import hmac
import hashlib
from typing import Optional

from services.payments.base import (
    PaymentProvider, PaymentLinkRequest, PaymentLinkResult, VerifiedEvent,
    CREATED, AUTHORIZED, CAPTURED, FAILED, REFUNDED,
)

_EVENT_STATUS = {
    "payment.created": CREATED,
    "payment.authorized": AUTHORIZED,
    "payment.captured": CAPTURED,
    "payment.failed": FAILED,
    "refund.processed": REFUNDED,
}


class MockProvider(PaymentProvider):
    name = "mock"

    def __init__(self, webhook_secret: Optional[str] = None):
        # No hardcoded default — without an explicit MOCK_WEBHOOK_SECRET the
        # provider FAILS CLOSED (verifies nothing). With the webhook now pinned
        # to the configured provider, mock is only ever reached when explicitly
        # selected; this removes any guessable-secret footgun.
        self._secret = (webhook_secret or os.environ.get("MOCK_WEBHOOK_SECRET", "")).encode()

    def create_payment_link(self, req: PaymentLinkRequest) -> PaymentLinkResult:
        return PaymentLinkResult(
            provider=self.name,
            provider_link_id=f"mock_link_{req.reference_id}",
            provider_order_id=f"mock_order_{req.reference_id}",
            short_url=f"https://mock-pay.local/pay/{req.reference_id}",
            status=CREATED,
        )

    def get_payment_status(self, provider_payment_id: str) -> str:
        return CAPTURED

    def _sign(self, raw_body: bytes) -> str:
        if not self._secret:
            return ""
        return hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()

    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        if not self._secret:
            return False
        expected = hmac.new(self._secret, f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def process_webhook(self, headers: dict, raw_body: bytes) -> VerifiedEvent:
        sig = headers.get("x-webhook-signature") or headers.get("X-Webhook-Signature") or ""
        verified = bool(self._secret) and hmac.compare_digest(self._sign(raw_body), sig)
        try:
            payload = json.loads((raw_body or b"").decode() or "{}")
        except Exception:
            payload = {}
        event_type = payload.get("event", "")
        entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
        return VerifiedEvent(
            provider=self.name,
            event_id=str(payload.get("id", "")),
            event_type=event_type,
            status=_EVENT_STATUS.get(event_type, CREATED),
            signature_verified=verified,
            provider_payment_id=entity.get("id"),
            provider_order_id=entity.get("order_id"),
            provider_link_id=entity.get("payment_link_id"),
            amount_paise=entity.get("amount"),
            raw=payload,
        )

    # Test helper: build a correctly-signed webhook (headers, body).
    def sign_webhook(self, payload: dict) -> tuple[dict, bytes]:
        body = json.dumps(payload).encode()
        return {"x-webhook-signature": self._sign(body)}, body
