"""
Payment provider interface + normalized data shapes.

Normalized status vocabulary (provider-specific statuses are mapped onto these):
  created    — link/order made, no money moved          → no accounting
  authorized — funds held, not captured                  → no accounting
  captured   — money actually received                   → create receipt (ONCE)
  failed     — payment failed                            → no accounting
  refunded   — captured then refunded                    → no accounting here

Only `captured` ever drives a receipt. Integer paise throughout.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

CREATED = "created"
AUTHORIZED = "authorized"
CAPTURED = "captured"
FAILED = "failed"
REFUNDED = "refunded"

# Statuses that must NOT touch accounting (everything except a real capture).
PENDING_STATUSES = (CREATED, AUTHORIZED)


@dataclass
class PaymentLinkRequest:
    """Request to create a hosted payment link for one invoice's outstanding amount."""
    amount_paise: int
    reference_id: str                 # our customer_payment_links.id (idempotency anchor)
    description: str
    currency: str = "INR"
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    expires_at: Optional[int] = None  # unix epoch seconds
    notes: dict = field(default_factory=dict)


@dataclass
class PaymentLinkResult:
    provider: str
    provider_link_id: str
    short_url: str
    provider_order_id: Optional[str] = None
    status: str = CREATED


@dataclass
class VerifiedEvent:
    """Outcome of verifying + parsing a webhook (or a verify_payment redirect).

    `signature_verified` is the gate: payment_service refuses to act on an event
    whose signature did not verify. `event_id` is the provider's unique event id
    used for replay/idempotency.
    """
    provider: str
    event_id: str
    event_type: str
    status: str                       # one of the normalized statuses above
    signature_verified: bool
    provider_payment_id: Optional[str] = None
    provider_order_id: Optional[str] = None
    provider_link_id: Optional[str] = None
    amount_paise: Optional[int] = None
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """A payment gateway adapter. Implementations must be side-effect-free with
    respect to accounting — they talk to the gateway and normalize results only."""

    name: str = "base"

    @abstractmethod
    def create_payment_link(self, req: PaymentLinkRequest) -> PaymentLinkResult:
        """Create a hosted payment link/order for `req.amount_paise`."""

    @abstractmethod
    def get_payment_status(self, provider_payment_id: str) -> str:
        """Return the normalized status of a payment by its provider id."""

    @abstractmethod
    def verify_payment(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        """Verify a client-side success callback signature (redirect flow)."""

    @abstractmethod
    def process_webhook(self, headers: dict, raw_body: bytes) -> VerifiedEvent:
        """Verify a webhook signature against the raw body and normalize it.
        MUST set signature_verified=False (never raise) when verification fails."""
