"""
Backend half of the frontend/backend GST parity guard.

shared/gst-parity-vectors.json is generated from the real backend functions
(see generate_gst_parity_vectors.py) and is ALSO asserted by the frontend in
apps/web/lib/money/gstLine.parity.test.ts. This test re-derives every vector
here, so the fixture cannot silently fall out of step with the server: change
_compute_line_gst or the taxable formula and this fails, telling you to
regenerate the fixture — at which point the frontend test fails too unless the
preview is updated to match.

That coupling is the whole point. Previously the preview computed GST with
Math.round against the server's floor, and float-multiplied the taxable base
against the server's exact-decimal truncation, so a CA could see ₹60.18 in the
summary and get ₹60.00 saved.
"""
import json
import os
from decimal import Decimal

import pytest

from routers.sales_invoices import _compute_line_gst, _round_off_paise
from domain.gst import discount as gst_discount

_FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "shared", "gst-parity-vectors.json",
)

with open(_FIXTURE) as _fh:
    _DATA = json.load(_fh)

VECTORS = _DATA["vectors"]
DOCUMENTS = _DATA["documents"]
DISCOUNTS = _DATA["discounts"]


def _ids(items):
    return [i["label"] for i in items]


@pytest.mark.parametrize("v", VECTORS, ids=_ids(VECTORS))
def test_backend_matches_parity_vector(v):
    """Every fixture line still reproduces from the live backend functions."""
    quantity = v["payload"]["quantity"]
    rate_paise = v["payload"]["rate_paise"]
    bps = v["payload"]["gst_rate_bps"]

    # The API's own derivation of bps from the percentage on the wire.
    assert int(round(float(v["gst_rate_percent"]) * 100)) == bps

    taxable = int(Decimal(str(quantity)) * rate_paise)
    cgst, sgst, igst = _compute_line_gst(taxable, bps, v["is_interstate"])

    exp = v["expected"]
    assert taxable == exp["taxable_paise"]
    assert cgst == exp["cgst_paise"]
    assert sgst == exp["sgst_paise"]
    assert igst == exp["igst_paise"]
    assert taxable + cgst + sgst + igst == exp["line_total_paise"]


@pytest.mark.parametrize("d", DOCUMENTS, ids=_ids(DOCUMENTS))
def test_backend_matches_parity_document(d):
    """Multi-line totals, including opt-in invoice round-off, still reproduce."""
    t = c = s = i = 0
    for ln in d["lines"]:
        quantity = float(ln["qty"])
        # Mirrors the frontend's rate_paise (JS Math.round is half-away-from-zero).
        rate_paise = int((float(ln["rate"]) * 100) + 0.5)
        bps = int(round(float(ln["gst_rate_percent"]) * 100))
        taxable = int(Decimal(str(quantity)) * rate_paise)
        lc, ls, li = _compute_line_gst(taxable, bps, d["is_interstate"])
        t += taxable
        c += lc
        s += ls
        i += li

    base_total = t + c + s + i
    ro = _round_off_paise(base_total) if d["round_off_enabled"] else 0

    exp = d["expected"]
    assert t == exp["taxable_paise"]
    assert c == exp["cgst_paise"]
    assert s == exp["sgst_paise"]
    assert i == exp["igst_paise"]
    assert c + s + i == exp["gst_paise"]
    assert ro == exp["round_off_paise"]
    assert base_total + ro == exp["grand_total_paise"]


@pytest.mark.parametrize("d", DISCOUNTS, ids=_ids(DISCOUNTS))
def test_backend_matches_parity_discount(d):
    """§15(3)(a) — the discount comes off before the tax, and the browser
    mirror (gstLine.applyDiscountsToLines) must land on the same integers.

    This pins the TAXABLE VALUE, not just the discount arithmetic. A document
    discount allocated even a paise differently previews a different tax from
    the one the server saves, which is the exact class of drift this whole
    fixture exists to prevent.
    """
    gross = []
    for ln in d["lines"]:
        quantity = float(ln["qty"])
        # Mirrors the frontend's rate_paise (JS Math.round is half-away-from-zero).
        rate_paise = int((float(ln["rate"]) * 100) + 0.5)
        gross.append(int(Decimal(str(quantity)) * rate_paise))

    resolved = gst_discount.apply_to_lines(
        [{"gross_paise": g,
          "discount_percent_bps": ln["discount_percent_bps"],
          "discount_paise": ln["discount_paise"]}
         for g, ln in zip(gross, d["lines"])],
        document_percent_bps=d["document_discount_percent_bps"],
        document_amount_paise=d["document_discount_paise"],
    )

    t = c = s_ = i = 0
    for g, ln, r, want in zip(gross, d["lines"], resolved, d["expected"]["lines"]):
        assert g == want["gross_paise"]
        assert int(r["discount_paise"]) == want["discount_paise"]
        assert int(r["taxable_paise"]) == want["taxable_paise"]
        bps = int(round(float(ln["gst_rate_percent"]) * 100))
        lc, ls, li = _compute_line_gst(int(r["taxable_paise"]), bps, d["is_interstate"])
        assert (lc, ls, li) == (want["cgst_paise"], want["sgst_paise"], want["igst_paise"])
        t += int(r["taxable_paise"]); c += lc; s_ += ls; i += li

    exp = d["expected"]
    assert t == exp["taxable_paise"]
    assert c + s_ + i == exp["gst_paise"]
    # The allocated parts sum to the whole: a pro-rata split that loses a paise
    # makes the invoice total differ from the figure the customer was quoted.
    assert sum(int(r["discount_paise"]) for r in resolved) == exp["total_discount_paise"]
    assert sum(gross) - exp["total_discount_paise"] == exp["taxable_paise"]


def test_the_discount_cases_cover_both_levels_and_the_residue():
    """A fixture that only ever tested one line and one discount would pass
    while the pro-rata allocation was wrong, which is the half that cannot be
    checked by inspection."""
    assert len(DISCOUNTS) >= 10
    assert any(len(d["lines"]) >= 3 for d in DISCOUNTS), "no multi-line case"
    assert any(d["document_discount_percent_bps"] for d in DISCOUNTS), "no document %"
    assert any(d["document_discount_paise"] for d in DISCOUNTS), "no document amount"
    assert any(ln["discount_percent_bps"] for d in DISCOUNTS for ln in d["lines"]), \
        "no line %"
    assert any(ln["discount_paise"] for d in DISCOUNTS for ln in d["lines"]), \
        "no line amount"
    # At least one where the parts could not divide evenly, so the residue rule
    # is exercised rather than assumed.
    assert any(
        d["document_discount_paise"] and len(d["lines"]) > 1
        and d["document_discount_paise"] % len(d["lines"]) != 0
        for d in DISCOUNTS), "no case with a residue to allocate"


def test_fixture_covers_the_known_divergences():
    """Guard the guard: the two bugs this fixture exists for must stay covered,
    so nobody trims the vector list back down to only 'nice' numbers."""
    by_label = {v["label"]: v for v in VECTORS}

    # floor-vs-round: full tax is 1899.9 paise. Rounding gives 1900 (what the
    # old preview showed); the server floors to 1899.
    v = by_label["floor-vs-round GST: full tax 1899.9 paise"]
    assert v["expected"]["cgst_paise"] + v["expected"]["sgst_paise"] == 1899

    # truncate-vs-round: 0.335 x 100 paise is exactly 33.5 -> truncates to 33.
    # The old preview's Math.round gave 34.
    v = by_label["truncate-vs-round taxable: 0.335 x Rs.1"]
    assert v["expected"]["taxable_paise"] == 33


def test_every_ui_gst_slab_is_covered():
    """A rate the UI can offer but the fixture never exercises is a blind spot."""
    ui_slabs = {0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28}
    covered = {v["gst_rate_percent"] for v in VECTORS}
    assert ui_slabs <= covered, f"uncovered slabs: {sorted(ui_slabs - covered)}"
