"""
SALES-11 — a discount on the invoice, and CGST §15(3)(a) applied to it.

THE SECTION
    §15(3): "The value of the supply shall not include any discount which is
    given — (a) before or at the time of the supply if such discount has been
    DULY RECORDED IN THE INVOICE issued in respect of such supply".

    So the tax is charged on the NET, and the relief is conditional on the
    invoice showing the discount. Both halves are asserted here: the arithmetic,
    and that the figure survives onto the document.

THE SECTION THIS IS NOT
    §15(3)(b) — a discount given AFTER the supply — is excluded only where it
    was established in an agreement at or before the time of supply, is
    specifically linked to the invoices, AND the recipient has reversed the
    attributable ITC. That is the §34 credit-note path. A test below asserts
    that the note models cannot carry a discount field at all, because a
    post-supply discount quietly reducing the value of a supply already made is
    exactly what §15(3)(b) exists to prevent.

WHAT IS NOT TESTED HERE
    The browser's mirror of this arithmetic. That is pinned separately and much
    harder, by shared/gst-parity-vectors.json — twelve discount documents run
    through both implementations and asserted equal integer by integer.
"""
import pytest

from domain.gst.discount import allocate, apply_to_lines, discount_for


# ── The line ─────────────────────────────────────────────────────────────────

def test_a_percentage_comes_off_the_line():
    assert discount_for(1_000_00, percent_bps=500) == 50_00


def test_a_flat_amount_is_taken_as_given():
    assert discount_for(1_000_00, amount_paise=25_00) == 25_00


def test_no_discount_at_all_is_nothing():
    assert discount_for(1_000_00) == 0
    assert discount_for(0) == 0


def test_the_percentage_wins_when_both_arrive():
    """The percentage is what the CA typed; the amount beside it is what a
    screen derived. Letting a derived number override a typed one is how a
    form's preview becomes the document."""
    assert discount_for(1_000_00, percent_bps=500, amount_paise=99_99) == 50_00


def test_a_discount_floors_and_never_rounds_up():
    """A larger discount is a smaller taxable value and less tax, so flooring
    is the only direction that cannot under-declare. 33,333 x 333 / 10,000 is
    1,109.98 paise."""
    assert discount_for(333_33, percent_bps=333) == 1109


def test_a_hundred_percent_discount_is_a_free_of_charge_line():
    assert discount_for(1_000_00, percent_bps=10_000) == 1_000_00


def test_a_discount_larger_than_the_line_is_refused_not_capped():
    """A negative value of supply is not something the GL or GSTR-1 can
    represent, and silently capping it would charge tax on a figure nobody
    agreed."""
    with pytest.raises(ValueError, match="exceeds the line value"):
        discount_for(100_00, amount_paise=100_01)


def test_a_negative_discount_is_refused():
    with pytest.raises(ValueError):
        discount_for(100_00, amount_paise=-1)
    with pytest.raises(ValueError, match="between 0 and 10000"):
        discount_for(100_00, percent_bps=-1)
    with pytest.raises(ValueError, match="between 0 and 10000"):
        discount_for(100_00, percent_bps=10_001)


# ── The document-level allocation ────────────────────────────────────────────

def test_the_parts_sum_to_the_whole():
    """A pro-rata split that loses a paise makes the invoice total differ from
    the figure the customer was quoted."""
    for total in range(0, 40):
        parts = allocate(total, [100_00, 50_00, 33_33])
        assert sum(parts) == total, total


def test_the_residue_goes_to_the_largest_remainder_and_ties_break_by_position():
    # Ten paise over three equal lines: 3 each, one paise over, and with all
    # three remainders equal it goes to the first.
    assert allocate(10, [100, 100, 100]) == [4, 3, 3]


def test_the_same_invoice_always_allocates_the_same_way():
    a = allocate(7, [100, 100, 100, 100])
    b = allocate(7, [100, 100, 100, 100])
    assert a == b == [2, 2, 2, 1]


def test_a_line_with_no_value_left_takes_no_share():
    assert allocate(100, [1_000, 0]) == [100, 0]


def test_nothing_left_to_discount_allocates_nothing():
    """Every line already fully discounted — divide by zero, or allocate
    nothing. There is no value left to reduce."""
    assert allocate(0, [0, 0]) == [0, 0]
    assert allocate(50, [0, 0]) == [0, 0]


def test_a_document_discount_larger_than_the_bill_is_refused():
    with pytest.raises(ValueError, match="exceeds the invoice value"):
        allocate(100_01, [100_00])


# ── The two together ─────────────────────────────────────────────────────────

def test_the_line_discount_comes_off_first_then_the_document_one():
    """"5% off this line, and 2% off the bill" — the bill is what is LEFT after
    the line discounts. Taking both off the gross would compound two reliefs the
    customer was quoted as one."""
    out = apply_to_lines(
        [{"gross_paise": 1_000_00, "discount_percent_bps": 500},
         {"gross_paise": 500_00}],
        document_percent_bps=200)

    # Line 1: 1,000 less 5% = 950. Line 2: 500. Bill 1,450, less 2% = 29.
    assert out[0]["discount_paise"] == 50_00 + 19_00
    assert out[1]["discount_paise"] == 10_00
    assert out[0]["taxable_paise"] == 931_00
    assert out[1]["taxable_paise"] == 490_00
    # 1,450 x 0.98
    assert sum(r["taxable_paise"] for r in out) == 1_421_00


def test_the_percentage_typed_is_carried_through_for_the_customers_copy():
    """§15(3)(a) makes the relief conditional on the invoice RECORDING the
    discount, so how it was arrived at has to survive."""
    out = apply_to_lines([{"gross_paise": 1_000_00, "discount_percent_bps": 750}])
    assert out[0]["discount_percent_bps"] == 750


def test_a_flat_amount_leaves_no_percentage_to_print():
    out = apply_to_lines([{"gross_paise": 1_000_00, "discount_paise": 100_00}])
    assert out[0]["discount_percent_bps"] is None


def test_no_discount_anywhere_leaves_the_taxable_value_alone():
    out = apply_to_lines([{"gross_paise": 1_000_00}, {"gross_paise": 500_00}])
    assert [r["discount_paise"] for r in out] == [0, 0]
    assert [r["taxable_paise"] for r in out] == [1_000_00, 500_00]


def test_gross_less_discount_is_always_the_taxable_value():
    """The invariant migration 364 rests on when it does not store the gross."""
    out = apply_to_lines(
        [{"gross_paise": 333_33, "discount_percent_bps": 777},
         {"gross_paise": 100_01},
         {"gross_paise": 7, "discount_paise": 3}],
        document_amount_paise=1_111)
    for r, gross in zip(out, (333_33, 100_01, 7)):
        assert r["taxable_paise"] + r["discount_paise"] == gross


# ── §15(3)(b) is a different remedy, and the models say so ───────────────────

def test_a_credit_note_line_cannot_carry_a_discount():
    """The shared InvoiceLineIn has no discount field, so the credit and debit
    note routes — which are typed to it — cannot accept one. A post-supply
    discount needs a pre-supply agreement and the recipient's ITC reversal
    (§15(3)(b)); it is the §34 note itself, not a field on one."""
    from models.invoices import InvoiceLineIn, SalesInvoiceLineIn
    assert not any("discount" in f for f in InvoiceLineIn.model_fields)
    assert "discount_percent_bps" in SalesInvoiceLineIn.model_fields
    assert "discount_paise" in SalesInvoiceLineIn.model_fields


def test_a_plain_line_is_still_accepted_on_a_sales_invoice():
    """The recurring-invoice builder, the billing service and a hundred tests
    construct the shared line. Accepting one is the truth about a line with no
    discount — the guarantee that matters is the one above."""
    from models.invoices import InvoiceLineIn, SalesInvoiceIn
    plain = InvoiceLineIn(description="Consulting", rate_paise=1_000_00,
                          service_catalogue_id="svc-1")
    inv = SalesInvoiceIn(client_id="c", customer_id="cu", invoice_no="INV-1",
                         invoice_date="2026-04-01", lines=[plain])
    assert inv.lines[0].discount_percent_bps is None
    assert inv.lines[0].discount_paise is None


def test_the_model_refuses_an_impossible_percentage():
    from pydantic import ValidationError
    from models.invoices import SalesInvoiceLineIn
    with pytest.raises(ValidationError):
        SalesInvoiceLineIn(description="x", rate_paise=1, discount_percent_bps=10_001)
    with pytest.raises(ValidationError):
        SalesInvoiceLineIn(description="x", rate_paise=1, discount_paise=-1)


# ── The customer's copy ──────────────────────────────────────────────────────

def _summary(invoice: dict, lines=None):
    """The invoice's summary block as (label, value) pairs — what the customer's
    copy actually shows. See services/invoice_pdf_service.summary_lines for why
    it is a function rather than inline in the renderer."""
    from services.invoice_pdf_service import summary_lines
    lines = lines or []
    return summary_lines(
        invoice, lines,
        invoice["taxable_amount_paise"],
        invoice["cgst_paise"] + invoice["sgst_paise"] + invoice["igst_paise"],
        invoice["cgst_paise"], invoice["sgst_paise"], invoice["igst_paise"],
        invoice["total_paise"])


def test_the_customers_copy_shows_the_gross_the_discount_and_the_net():
    """§15(3)(a) excludes a discount from the value of supply only "if such
    discount has been duly recorded in the invoice" — so these lines being on
    the document is part of the statutory test, not decoration."""
    rows = _summary({
        "taxable_amount_paise": 95_000, "discount_paise": 5_000,
        "discount_percent_bps": 500,
        "cgst_paise": 8_550, "sgst_paise": 8_550, "igst_paise": 0,
        "total_paise": 1_12_100,
    })
    assert rows[0] == ("Gross Value", "1,000.00")
    assert rows[1] == ("Less: Discount @ 5%", "-50.00")
    assert rows[2] == ("Taxable Value", "950.00")
    # Gross less discount is the taxable value, on the face of the document.
    assert 1_00_000 - 5_000 == 95_000


def test_a_flat_discount_prints_without_inventing_a_percentage():
    rows = _summary({
        "taxable_amount_paise": 97_500, "discount_paise": 2_500,
        "discount_percent_bps": None,
        "cgst_paise": 8_775, "sgst_paise": 8_775, "igst_paise": 0,
        "total_paise": 1_15_050,
    })
    assert rows[1] == ("Less: Discount", "-25.00")


def test_a_fractional_percentage_prints_as_typed():
    """discount_percent_bps is BASIS POINTS and _pct_label takes MILLI-percent.
    Without the x10 a 2.5% discount printed as 0.25%."""
    rows = _summary({
        "taxable_amount_paise": 97_500, "discount_paise": 2_500,
        "discount_percent_bps": 250,
        "cgst_paise": 8_775, "sgst_paise": 8_775, "igst_paise": 0,
        "total_paise": 1_15_050,
    })
    assert rows[1][0] == "Less: Discount @ 2.5%"


def test_an_invoice_with_no_discount_keeps_the_block_it_always_had():
    rows = _summary({
        "taxable_amount_paise": 1_00_000, "discount_paise": 0,
        "cgst_paise": 9_000, "sgst_paise": 9_000, "igst_paise": 0,
        "total_paise": 1_18_000,
    })
    # The rate suffix is Rule 46(l)'s and is derived from the amounts — see
    # _document_rate. What matters here is that nothing was ADDED.
    assert [r[0].split(" @ ")[0] for r in rows] == [
        "Taxable Value", "CGST", "SGST", "Total"]
    assert not any("Discount" in r[0] for r in rows)


def test_a_document_that_never_heard_of_a_discount_still_renders():
    """Every invoice written before migration 364 has no such key at all."""
    rows = _summary({
        "taxable_amount_paise": 1_00_000,
        "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 18_000,
        "total_paise": 1_18_000,
    })
    assert [r[0].split(" @ ")[0] for r in rows] == ["Taxable Value", "IGST", "Total"]


def test_the_round_off_line_still_comes_after_the_tax_and_before_the_total():
    rows = _summary({
        "taxable_amount_paise": 95_000, "discount_paise": 5_000,
        "discount_percent_bps": 500, "round_off_paise": -30,
        "cgst_paise": 8_550, "sgst_paise": 8_550, "igst_paise": 0,
        "total_paise": 1_12_070,
    })
    labels = [r[0] for r in rows]
    assert labels.index("Round Off") == len(labels) - 2
    assert labels[-1] == "Total"
    assert rows[labels.index("Round Off")][1] == "-0.30"


def test_the_pdf_still_builds_with_a_discount_on_it():
    from services.invoice_pdf_service import build_sales_invoice_pdf
    pdf = build_sales_invoice_pdf({
        "invoice_no": "INV-1", "invoice_date": "2026-04-01",
        "taxable_amount_paise": 95_000, "discount_paise": 5_000,
        "discount_percent_bps": 500,
        "cgst_paise": 8_550, "sgst_paise": 8_550, "igst_paise": 0,
        "total_paise": 1_12_100,
        "lines": [{"description": "Widget", "hsn_sac": "8471", "quantity": 1,
                   "rate_paise": 1_00_000, "gst_rate_bps": 1800,
                   "taxable_amount_paise": 95_000, "cgst_paise": 8_550,
                   "sgst_paise": 8_550, "igst_paise": 0}],
    }, client={"client_name": "Seller", "gstin": "27AAACT2727Q1ZW"},
       customer={"name": "Buyer"})
    assert isinstance(pdf, (bytes, bytearray)) and len(pdf) > 1000
