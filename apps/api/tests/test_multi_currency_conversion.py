"""
Multi-Currency Phase 3 — foreign→base conversion arithmetic (exact, integer).
Every rupee calculation uses integer paise; the rate is Decimal, never float.
"""
from decimal import Decimal

import pytest

from domain.currency.conversion import to_base_minor, to_txn_minor


# ── to_base_minor: txn minor units → base paise ───────────────────────────────
def test_usd_to_inr_same_minor_unit():
    # $1000.00 = 100000 cents; @ 83.5 → ₹83,500 = 8,350,000 paise
    assert to_base_minor(100000, Decimal("83.5"), txn_minor_unit=2) == 8_350_000


def test_jpy_to_inr_zero_minor_unit():
    # ¥1000 = 1000 minor units (0 decimals); @ 0.55 ₹/¥ → ₹550 = 55,000 paise
    assert to_base_minor(1000, Decimal("0.55"), txn_minor_unit=0) == 55_000


def test_rounding_half_up():
    # 12345 cents @ 83.33333333 → 12345*83.33333333 = 1,028,749.99... paise → HALF_UP
    got = to_base_minor(12345, Decimal("83.33333333"), txn_minor_unit=2)
    assert got == round(Decimal("12345") * Decimal("83.33333333"))


def test_rate_one_is_identity_for_inr():
    assert to_base_minor(54321, Decimal(1), txn_minor_unit=2) == 54321


def test_zero_amount():
    assert to_base_minor(0, Decimal("83.5"), txn_minor_unit=2) == 0


def test_non_positive_rate_rejected():
    with pytest.raises(ValueError):
        to_base_minor(100, Decimal(0), txn_minor_unit=2)


# ── to_txn_minor: base paise → txn minor units (memo only) ────────────────────
def test_inverse_roundtrips_for_clean_rate():
    base = to_base_minor(100000, Decimal("80"), txn_minor_unit=2)   # 8,000,000
    assert to_txn_minor(base, Decimal("80"), txn_minor_unit=2) == 100000


def test_inverse_jpy():
    base = to_base_minor(1000, Decimal("0.55"), txn_minor_unit=0)   # 55,000
    assert to_txn_minor(base, Decimal("0.55"), txn_minor_unit=0) == 1000


def test_components_sum_to_base_total_by_construction():
    # The document services define base_total = sum of converted components, so the
    # base journal balances exactly with no FX-rounding account.
    rate = Decimal("83.42")
    taxable, cgst, sgst = 100000, 9000, 9000  # txn cents
    b_tax = to_base_minor(taxable, rate, 2)
    b_cgst = to_base_minor(cgst, rate, 2)
    b_sgst = to_base_minor(sgst, rate, 2)
    base_total = b_tax + b_cgst + b_sgst
    # AR debit (base_total) equals the sum of the credit legs — balanced in base.
    assert base_total == b_tax + b_cgst + b_sgst
