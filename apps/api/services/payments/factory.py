"""
Provider selection. Default is the dependency-free MockProvider; set
PAYMENT_PROVIDER=razorpay (plus RAZORPAY_* keys) to use the real gateway.
The webhook route may pass an explicit provider name from its path.
"""
import os
from typing import Optional

from services.payments.base import PaymentProvider
from services.payments.mock import MockProvider


def get_provider(name: Optional[str] = None) -> PaymentProvider:
    name = (name or os.environ.get("PAYMENT_PROVIDER", "mock")).lower()
    if name == "razorpay":
        from services.payments.razorpay import RazorpayProvider
        return RazorpayProvider()
    return MockProvider()
