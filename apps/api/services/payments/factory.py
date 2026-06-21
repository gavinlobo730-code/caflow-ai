"""
Provider selection. Default is the dependency-free MockProvider; set
PAYMENT_PROVIDER=razorpay (plus RAZORPAY_* keys) to use the real gateway.

The webhook route passes its `{provider}` path segment as `name`; it MUST match
the configured PAYMENT_PROVIDER or we raise (the route then rejects). This pins
the webhook to exactly one provider so a request to e.g. /webhook/mock can never
instantiate the mock verifier in a Razorpay-configured deployment.
"""
import os
from typing import Optional

from services.payments.base import PaymentProvider
from services.payments.mock import MockProvider


def configured_provider() -> str:
    return os.environ.get("PAYMENT_PROVIDER", "mock").lower()


def get_provider(name: Optional[str] = None) -> PaymentProvider:
    configured = configured_provider()
    if name is not None and name.lower() != configured:
        raise ValueError(f"Payment provider '{name}' is not the configured provider.")
    if configured == "razorpay":
        from services.payments.razorpay import RazorpayProvider
        return RazorpayProvider()
    if configured == "mock":
        return MockProvider()
    raise ValueError(f"Unsupported PAYMENT_PROVIDER: {configured}")
