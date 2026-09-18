"""SALES-35 — four line models took a GST rate and none of them checked it.

`gst_rate_percent: float = 18.0` on `InvoiceLineIn`, `PurchaseBillLineIn`,
`PreInvoiceLineIn` and `PurchaseOrderLineIn`, with no validator on any of them.
Measured on a Rs 1,000 line before this:

    -5      accepted -> CGST -2,500 + SGST -2,500
    1800    accepted -> CGST  9,000 + SGST  9,000
    999999  accepted -> 4,99,99,500 each

The middle one is why this exists. `1800` is how this codebase spells 18%
everywhere it uses BASIS POINTS, so moving a figure between the two units
produces a plausible number that charges a hundredfold — and it reaches the
ledger, the customer's invoice, GSTR-1 and GSTR-3B with nothing objecting.
"""
from __future__ import annotations

import pydantic
import pytest

from domain.gst.rate_bounds import rate_percent_violation, MAX_GST_RATE_PERCENT
from domain.sales.line_tax import compute_line_gst
from models.invoices import InvoiceLineIn, PurchaseBillLineIn
from models.purchase_cycle import PurchaseOrderLineIn
from models.sales_cycle import PreInvoiceLineIn

#: Every model whose line carries a percentage GST rate. Listed rather than
#: discovered so that a fifth is a deliberate addition — the four were found by
#: grep and the point of this module is that the count was zero.
LINE_MODELS = (InvoiceLineIn, PurchaseBillLineIn,
               PreInvoiceLineIn, PurchaseOrderLineIn)


def _line(model, **kw):
    return model(service_catalogue_id="SVC-1", description="x", quantity=1,
                 rate_paise=100_000, **kw)


# ── the rule ─────────────────────────────────────────────────────────────────

def test_a_rate_is_bounded_and_not_enumerated():
    """CLAUDE.md is explicit that GST rate slabs are per-line on the document
    and deliberately NOT a central table here, so a list of allowed rates would
    be the very thing that file says not to build and would refuse a rate a
    Council notification adds. `AdvanceIn._rate_in_range` already records this
    argument for the basis-point twin."""
    for ok in (0, 0.1, 0.25, 1.5, 5, 12, 18, 28, MAX_GST_RATE_PERCENT):
        assert rate_percent_violation(ok) is None, ok
    for slab_not_notified in (7, 9, 11, 40):
        assert rate_percent_violation(slab_not_notified) is None, (
            "the bound catches a unit mix-up; it does not police the Council"
        )


def test_a_negative_rate_is_refused_and_the_reason_says_what_it_would_do():
    assert "negative output tax" in (rate_percent_violation(-5) or "")
    assert rate_percent_violation(-0.01) is not None


def test_the_basis_point_mix_up_is_refused_and_BOTH_units_are_named():
    """The reader who hits this is by construction confused about which unit
    they are in, so a message naming only one of them does not help."""
    why = rate_percent_violation(1800) or ""
    assert "PERCENTAGE" in why and "basis points" in why
    assert "18 is 18%" in why and "1800 is 18%" in why


def test_a_rate_that_is_not_a_number_is_refused():
    """NaN passes every comparison below it, so it needs its own branch."""
    assert rate_percent_violation(float("nan")) is not None
    assert rate_percent_violation("eighteen") is not None


def test_absent_is_not_a_violation():
    """None is a real third state — the field is optional on the doors that
    make it optional, and a missing rate is not a wrong one."""
    assert rate_percent_violation(None) is None


# ── every door ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", LINE_MODELS, ids=lambda m: m.__name__)
@pytest.mark.parametrize("bad", [-5.0, 1800.0, 999999.0])
def test_every_line_model_refuses_it(model, bad):
    """A validator on one door only is one PATCH away from being none, and
    PurchaseBillLineIn is the ITC side — a wrong rate there claims credit."""
    with pytest.raises(pydantic.ValidationError):
        _line(model, gst_rate_percent=bad)


@pytest.mark.parametrize("model", LINE_MODELS, ids=lambda m: m.__name__)
def test_every_line_model_still_takes_a_real_rate(model):
    for ok in (0.0, 5.0, 18.0, 28.0):
        assert _line(model, gst_rate_percent=ok).gst_rate_percent == ok


def test_the_four_models_delegate_rather_than_each_carrying_the_rule():
    """One level of indirection, the shape `_validate_quantity` already uses.
    Four copies of a bound is four places for them to drift apart."""
    import inspect
    from pathlib import Path
    api = Path(__file__).resolve().parents[1]
    for name in ("models/invoices.py", "models/purchase_cycle.py",
                 "models/sales_cycle.py"):
        src = (api / name).read_text()
        assert "rate_percent_violation" in src, (
            f"{name} must reach the one rule in domain/gst/rate_bounds"
        )
    assert "MAX_GST_RATE_PERCENT" not in (
        api / "models" / "invoices.py").read_text(), (
        "the bound itself belongs in the domain module, not restated at a door"
    )


# ── what it cost ─────────────────────────────────────────────────────────────

def test_the_money_it_was_letting_through():
    """The premise, so the size of it is on the record rather than in a
    commit message."""
    assert compute_line_gst(100_000, int(-5.0 * 100), False) == (-2500, -2500, 0)
    assert compute_line_gst(100_000, int(1800.0 * 100), False) == (900000, 900000, 0)
    assert compute_line_gst(100_000, int(18.0 * 100), False) == (9000, 9000, 0), (
        "and what it should be: Rs 90 + Rs 90 on a Rs 1,000 line at 18%"
    )
