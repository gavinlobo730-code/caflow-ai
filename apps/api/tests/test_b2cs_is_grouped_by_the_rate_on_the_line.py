"""
GSTR-1 Table 7 declares a rate-wise summary, and the rate is the LINE's.

WHAT WAS WRONG
    _build_b2cs keyed its grouping on _infer_rate(inv) — total tax divided by
    taxable value, for the whole invoice. An invoice to an unregistered buyer
    carrying a 5% line and an 18% line was declared as ONE row at 11.5%.

    Two things follow, and the second is why it survived so long:

      * 11.5% is not a rate. The tariff has 0, 0.25, 3, 5, 12, 18 and 28, and
        Table 7 is a rate-wise declaration under CGST Rule 59(2) — the portal
        has no bucket for a blend.
      * THE TAX TOTAL WAS RIGHT. camt + samt + iamt summed to the same figure
        either way, so the return balanced against the books, GSTR-3B agreed,
        and the only thing wrong was the breakup that the rate-wise table exists
        to state.

WHAT THE FIX IS
    The grouping _build_invoice_items has always done for B2B, applied across
    invoices instead of within one. Table 7 asks the same question Table 4A's
    itms does; it had a different answer.

THE HEADER FALLBACK IS KEPT AND IS NOT THE SAME THING
    An invoice with no stored lines has one rate by definition, so inferring it
    is a reading of the data rather than a blend of two rates. That is
    _build_invoice_items' own fallback and it stays consistent with it.
"""
from __future__ import annotations

from domain.gst.classifier import GSTInvoiceCategory
from domain.gst.gstr1_builder import (InvoiceForGSTR1, InvoiceLine, build_gstr1)

GSTIN = "27AAAAA0000A1Z2"
PERIOD = "052025"


def _line(rate: float, taxable_paise: int, *, interstate: bool) -> InvoiceLine:
    tax = int(taxable_paise * rate / 100)
    return InvoiceLine(
        hsn_sac_code="998314", description="svc", quantity=1.0, unit="NOS",
        rate_paise=taxable_paise, taxable_paise=taxable_paise, gst_rate=rate,
        cgst_paise=0 if interstate else tax // 2,
        sgst_paise=0 if interstate else tax - tax // 2,
        igst_paise=tax if interstate else 0,
        cess_paise=0)


def _invoice(ref: str, lines: list[InvoiceLine], *, interstate: bool = False,
             pos: str = "27") -> InvoiceForGSTR1:
    return InvoiceForGSTR1(
        id=ref, transaction_type="sales_invoice", reference_no=ref,
        transaction_date="2025-05-10", party_gstin=None, party_name="Consumer",
        place_of_supply=pos, is_interstate=interstate,
        taxable_amount_paise=sum(l.taxable_paise for l in lines),
        cgst_paise=sum(l.cgst_paise for l in lines),
        sgst_paise=sum(l.sgst_paise for l in lines),
        igst_paise=sum(l.igst_paise for l in lines),
        cess_paise=sum(l.cess_paise for l in lines),
        is_reverse_charge=False, invoice_type="Regular", supply_type="taxable",
        gst_invoice_category=GSTInvoiceCategory.B2CS,
        original_invoice_ref=None, original_invoice_date=None, lines=lines)


def _b2cs(invoices) -> list[dict]:
    return build_gstr1(invoices, GSTIN, PERIOD).payload["b2cs"]


# ── The defect itself ───────────────────────────────────────────────────────

def test_two_rates_on_one_invoice_are_two_rows():
    inv = _invoice("INV1", [_line(5.0, 1_000_00, interstate=False),
                            _line(18.0, 1_000_00, interstate=False)])
    rows = {r["rt"]: r for r in _b2cs([inv])}
    assert set(rows) == {5.0, 18.0}, (
        "an invoice with a 5% line and an 18% line used to produce ONE row at "
        f"11.5%; got {sorted(rows)}")
    assert rows[5.0]["txval"] == 1000.0
    assert rows[18.0]["txval"] == 1000.0


def test_the_blended_rate_is_never_emitted():
    """11.5% is the exact figure the old code produced on this invoice. Named
    so a revert fails on the number, not just on the row count."""
    inv = _invoice("INV1", [_line(5.0, 1_000_00, interstate=False),
                            _line(18.0, 1_000_00, interstate=False)])
    assert 11.5 not in {r["rt"] for r in _b2cs([inv])}


def test_every_rate_emitted_is_one_the_tariff_has():
    inv = _invoice("INV1", [_line(5.0, 1_000_00, interstate=False),
                            _line(12.0, 700_00, interstate=False),
                            _line(18.0, 1_000_00, interstate=False),
                            _line(28.0, 300_00, interstate=False)])
    tariff = {0.0, 0.25, 3.0, 5.0, 12.0, 18.0, 28.0}
    assert {r["rt"] for r in _b2cs([inv])} <= tariff


# ── What the fix must NOT change ────────────────────────────────────────────

def test_the_tax_total_is_unchanged():
    """The reason this was invisible: the money always added up. It still must."""
    inv = _invoice("INV1", [_line(5.0, 1_000_00, interstate=False),
                            _line(18.0, 1_000_00, interstate=False)])
    rows = _b2cs([inv])
    assert sum(r["camt"] for r in rows) == round(inv.cgst_paise / 100, 2)
    assert sum(r["samt"] for r in rows) == round(inv.sgst_paise / 100, 2)
    assert sum(r["txval"] for r in rows) == round(inv.taxable_amount_paise / 100, 2)


def test_the_same_rate_across_invoices_still_aggregates_into_one_row():
    """Table 7 is a summary. Splitting per invoice would be the opposite bug."""
    a = _invoice("INV1", [_line(18.0, 1_000_00, interstate=False)])
    b = _invoice("INV2", [_line(18.0, 2_000_00, interstate=False)])
    rows = _b2cs([a, b])
    assert len(rows) == 1
    assert rows[0]["txval"] == 3000.0


def test_inter_and_intra_at_one_rate_stay_two_rows():
    """Rule 59(2) keys on supply type as well as rate and place of supply — the
    earlier fix this grouping already carried, re-asserted because the key
    changed shape."""
    intra = _invoice("INV1", [_line(18.0, 1_000_00, interstate=False)], interstate=False)
    inter = _invoice("INV2", [_line(18.0, 1_000_00, interstate=True)],
                     interstate=True, pos="29")
    rows = _b2cs([intra, inter])
    assert {r["sply_ty"] for r in rows} == {"INTRA", "INTER"}
    assert len(rows) == 2


def test_two_places_of_supply_at_one_rate_stay_two_rows():
    a = _invoice("INV1", [_line(18.0, 1_000_00, interstate=True)], interstate=True, pos="29")
    b = _invoice("INV2", [_line(18.0, 1_000_00, interstate=True)], interstate=True, pos="33")
    assert {r["pos"] for r in _b2cs([a, b])} == {"29", "33"}


# ── The header fallback ─────────────────────────────────────────────────────

def test_an_invoice_with_no_stored_lines_still_declares_its_rate():
    """One rate by definition, so inferring it is a reading rather than a blend
    — and dropping the invoice would be worse than either."""
    inv = _invoice("INV1", [_line(18.0, 1_000_00, interstate=False)])
    headerless = InvoiceForGSTR1(**{**inv.__dict__, "lines": []})
    rows = _b2cs([headerless])
    assert len(rows) == 1 and rows[0]["rt"] == 18.0
    assert rows[0]["txval"] == 1000.0


def test_a_lined_and_a_headerless_invoice_at_one_rate_merge():
    """The fallback must land in the SAME bucket as a real line at that rate,
    or a client part-way through a data migration files two rows at 18%."""
    lined = _invoice("INV1", [_line(18.0, 1_000_00, interstate=False)])
    headerless = InvoiceForGSTR1(
        **{**_invoice("INV2", [_line(18.0, 2_000_00, interstate=False)]).__dict__,
           "lines": []})
    rows = _b2cs([lined, headerless])
    assert len(rows) == 1
    assert rows[0]["txval"] == 3000.0
