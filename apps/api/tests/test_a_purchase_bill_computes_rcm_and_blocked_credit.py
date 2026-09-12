"""PUR-29: the two GST rules on the purchase-bill compute path had no test.

`_compute_bill_lines_and_totals` decides two things a CA is liable for and
nothing exercised either:

  * CGST Act s.9(3)/(4) REVERSE CHARGE — the vendor invoices WITHOUT tax and
    the recipient self-assesses it. The tax is still computed (it drives
    GSTR-3B Table 3.1(d), the ITC claim under s.16 and the RCM journal legs)
    but what the VENDOR is owed is the taxable value alone. Get it wrong the
    other way and Trade Payables is overstated by tax nobody charged — which
    is exactly what the code did before the docstring at :455 was written.

  * CGST Act s.17(5) BLOCKED CREDIT — tax on an `itc_eligible=false` line is
    still owed to the vendor and must NOT reach the ITC claim. The two move in
    opposite directions, so a single test that only checks the total cannot
    tell a correct answer from either mistake.

These are the rules; the arithmetic that supports them (_compute_line_gst,
the intra/inter split) is covered elsewhere. What is asserted here is the
part a reader would otherwise have to take on trust.
"""
import pytest

from routers.purchase_bills import _compute_bill_lines_and_totals


# The REAL identity converter an INR bill gets (_resolve_bill_currency returns
# exactly this whenever the currency is INR or the feature is off). A hand-made
# stub would be a second implementation of the thing under test, and the first
# draft of this file was one — it lacked to_txn and the whole suite errored.
from domain.currency.document_currency import identity_currency


VENDOR = {"id": "V1", "name": "Supplier", "state_code": "27",
          "tds_applicable": False, "gstin": "27AABCU9603R1ZX"}


def _line(rate_paise=1_000_00, pct=18.0, **kw):
    return {"description": "svc", "hsn_sac": "9982", "quantity": 1,
            "rate_paise": rate_paise, "gst_rate_percent": pct, **kw}


def _compute(lines, *, interstate=False, rcm=False):
    return _compute_bill_lines_and_totals(
        lines, interstate, VENDOR, "2026-06-01", "FIRM",
        identity_currency("2026-06-01"),
        db=None, is_reverse_charge=rcm)


# ── s.9(3)/(4): reverse charge ───────────────────────────────────────────────

def test_an_rcm_bill_still_computes_the_tax():
    """The self-assessed tax drives 3B Table 3.1(d), the s.16 claim and the
    journal. Not computing it is not the same as not owing it."""
    out = _compute([_line()], rcm=True)
    assert out["cgst_paise"] == 9_000, out          # 9% of Rs 1,000 is Rs 90
    assert out["sgst_paise"] == 9_000
    assert out["igst_paise"] == 0


def test_an_rcm_bill_owes_the_vendor_the_taxable_value_alone():
    """The vendor invoiced WITHOUT tax. Adding it overstates Trade Payables by
    tax nobody charged, and that is what this path used to do."""
    out = _compute([_line()], rcm=True)
    assert out["total_paise"] == 1_000_00
    assert out["computed_lines"][0]["line_total_paise"] == 1_000_00


def test_an_ordinary_bill_owes_the_vendor_the_tax_too():
    """The control. Without it, 'always return the taxable value' passes the
    two tests above."""
    out = _compute([_line()], rcm=False)
    assert out["total_paise"] == 1_180_00
    assert out["computed_lines"][0]["line_total_paise"] == 1_180_00


def test_reverse_charge_does_not_change_which_heads_the_tax_falls_under():
    inter = _compute([_line()], interstate=True, rcm=True)
    assert inter["igst_paise"] == 18_000
    assert inter["cgst_paise"] == 0 and inter["sgst_paise"] == 0


# ── s.17(5): blocked credit ──────────────────────────────────────────────────

def test_blocked_tax_is_reported_separately():
    out = _compute([_line(itc_eligible=False, blocked_credit_reason="motor_vehicle")])
    assert out["ineligible_itc_cgst_paise"] == 9_000
    assert out["ineligible_itc_sgst_paise"] == 9_000


def test_blocked_tax_is_still_owed_to_the_vendor():
    """s.17(5) bars the CREDIT, not the payment. A bill whose total shrinks
    because the credit is blocked short-pays the supplier."""
    out = _compute([_line(itc_eligible=False)])
    assert out["total_paise"] == 1_180_00


def test_eligible_tax_is_not_reported_as_blocked():
    out = _compute([_line()])
    assert out["ineligible_itc_cgst_paise"] == 0
    assert out["ineligible_itc_sgst_paise"] == 0
    assert out["ineligible_itc_igst_paise"] == 0


def test_a_line_says_nothing_and_the_credit_is_eligible():
    """The default matters: itc_eligible is absent on every bill created
    before migration 240, and treating absence as BLOCKED would silently
    withhold credit on the whole back catalogue."""
    line = _line()
    assert "itc_eligible" not in line
    out = _compute([line])
    assert out["computed_lines"][0]["itc_eligible"] is True
    assert out["ineligible_itc_cgst_paise"] == 0


def test_a_mixed_bill_splits_the_two_kinds_of_tax():
    """The case that catches a total-only implementation: one blocked line and
    one eligible line, where the bill total is the same either way."""
    out = _compute([
        _line(rate_paise=1_000_00),
        _line(rate_paise=2_000_00, itc_eligible=False),
    ])
    assert out["cgst_paise"] == 27_000        # Rs 90 + Rs 180
    assert out["ineligible_itc_cgst_paise"] == 18_000
    assert out["total_paise"] == 3_540_00            # 3,000 + 540


# ── the two rules together ───────────────────────────────────────────────────

def test_blocked_credit_on_a_reverse_charge_bill():
    """Both at once, which is a real case: s.9(3) freight where s.17(5) bars
    the credit. The vendor is owed the taxable value (they charged no tax) AND
    the self-assessed tax is blocked — so the recipient pays the tax in cash
    under s.49(4) and claims nothing back."""
    out = _compute([_line(itc_eligible=False)], rcm=True)
    assert out["total_paise"] == 1_000_00, "the vendor charged no tax"
    assert out["cgst_paise"] == 9_000, "the recipient still self-assesses"
    assert out["ineligible_itc_cgst_paise"] == 9_000, "and claims none of it"
