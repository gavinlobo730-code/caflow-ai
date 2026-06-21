"""
Payment provider abstraction (Phase 4.6).

Provider-agnostic interface for online payments. The rest of the system depends
ONLY on this package's interface + dataclasses — never on a specific gateway.
A provider NEVER performs accounting; it only creates links and reports
verified payment events. Accounting happens solely through the existing receipt
engine (services.receipt_service.create_receipt_core), driven by payment_service.
"""
from services.payments.base import (
    PaymentProvider,
    PaymentLinkRequest,
    PaymentLinkResult,
    VerifiedEvent,
    CREATED,
    AUTHORIZED,
    CAPTURED,
    FAILED,
    REFUNDED,
    PENDING_STATUSES,
)
from services.payments.factory import get_provider

__all__ = [
    "PaymentProvider",
    "PaymentLinkRequest",
    "PaymentLinkResult",
    "VerifiedEvent",
    "CREATED",
    "AUTHORIZED",
    "CAPTURED",
    "FAILED",
    "REFUNDED",
    "PENDING_STATUSES",
    "get_provider",
]
