"""
A customer's TAN — the field the 26AS reconciliation cannot work without.

WHY THIS EXISTS
    Migration 291 added `customers.tan`, but nothing could write it. The
    Pydantic models did not accept the field, so FastAPI dropped it silently;
    the customer form had no input; and the six select lists that load a
    customer for editing did not fetch it. The column could never hold a value,
    which made the identity-matching half of the 26AS reconciliation dead code.

WHAT A TAN IS, AND WHY IT HAS TO BE TYPED IN
    IT Act §203A. A TAN is the number a business quotes when it deducts tax at
    source on a payment. Form 26AS — the taxpayer's record of tax others
    withheld from it — identifies each deductor by TAN and nothing else.

    It is 4 letters + 5 digits + 1 letter, where a PAN is 5 + 4 + 1, and the two
    share no characters: a TAN CANNOT be derived from a PAN or from anything
    else already on the customer record. Somebody has to type it.

    Without it, domain/income_tax/form26as_matcher can only match a 26AS row to
    a book credit on the deductor's NAME, which it accepts but flags as needing
    a human to confirm.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.parties import CustomerIn, CustomerUpdateIn, VendorIn


def _customer(**kw):
    return CustomerIn(client_id="c1", name="Acme Pvt Ltd", **kw)


# ── The model accepts it at all (the whole defect) ────────────────────────────

def test_a_customer_can_carry_a_tan():
    assert _customer(tan="MUMA12345B").tan == "MUMA12345B"


def test_a_tan_is_optional():
    """Most customers never deduct TDS, so requiring one would be wrong."""
    assert _customer().tan is None


def test_the_update_model_carries_it_too():
    """Recording a TAN on an existing customer is the common case — the CA
    learns it from the first 26AS, long after the customer was created."""
    assert CustomerUpdateIn(tan="DELB98765C").tan == "DELB98765C"


# ── Format (IT Act §203A) ─────────────────────────────────────────────────────

def test_a_tan_is_normalised_to_uppercase_like_pan_and_gstin():
    assert _customer(tan="  muma12345b  ").tan == "MUMA12345B"


def test_a_malformed_tan_is_rejected():
    with pytest.raises(ValidationError):
        _customer(tan="NOTATAN")


def test_a_pan_is_not_accepted_as_a_tan():
    """The two formats are 5+4+1 and 4+5+1 — a PAN can never be a valid TAN,
    and accepting one would put an unmatchable value in the field."""
    pan = "ABCDE1234F"
    assert _customer(pan=pan).pan == pan
    with pytest.raises(ValidationError):
        _customer(tan=pan)


def test_the_update_model_rejects_a_malformed_tan_too():
    with pytest.raises(ValidationError):
        CustomerUpdateIn(tan="12345ABCDE")


# ── Vendors deliberately do NOT have one ──────────────────────────────────────

def test_a_vendor_has_no_tan_field():
    """Opposite direction of TDS. Here the CLIENT is the deductor, and its 26Q
    return reports the vendor's PAN — the vendor's TAN never appears."""
    assert "tan" not in VendorIn.model_fields


# ── It reaches the database row ───────────────────────────────────────────────

def test_the_tan_survives_into_the_row_the_router_writes():
    """The router builds its insert from model_dump(), so a field the model
    does not declare is dropped before it ever reaches the database — which is
    exactly how the column stayed permanently empty."""
    assert _customer(tan="MUMA12345B").model_dump()["tan"] == "MUMA12345B"
