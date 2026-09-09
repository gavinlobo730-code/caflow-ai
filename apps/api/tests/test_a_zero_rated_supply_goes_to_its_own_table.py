"""
Zero-rated is three tables, not one, and Table 6A is the wrong one for two of
them.

WHAT WAS WRONG
    domain/gst/classifier.py routed all of these to EXP_WP / EXP_WOP, which
    gstr1_builder files in Table 6A:

        SEZ_with_payment      -> EXP_WP
        SEZ_without_payment   -> EXP_WOP
        Deemed_export         -> EXP_WOP

    Table 6A HAS NO ctin FIELD. A supply to an SEZ unit or developer and a
    deemed export both go to a REGISTERED recipient, and the whole point of
    declaring them is that the recipient's own return matches them — an SEZ
    unit's refund under IGST Act s.16(3), a deemed-export recipient's under
    Notification 48/2017-Central Tax read with CGST s.147. Filing them in 6A
    dropped the recipient's GSTIN entirely, so there was nothing to match.

    They belong in Tables 6B and 6C, which the GSTN payload carries INSIDE the
    b2b section, distinguished by inv_typ.

    AND inv_typ WAS THIS APPLICATION'S OWN INTERNAL STRING. _build_b2b emitted
    `inv.invoice_type if != "Regular" else "R"`, so had one of these ever
    reached it, the payload would have carried "SEZ_with_payment" in a field
    the portal parses as an enum. It never fired only because the routing sent
    them somewhere else — one bug hiding another.

    SEPARATELY: a real export made ON PAYMENT of IGST was filed as WOPAY.
    TransactionForClassification carried no tax field at all and the classifier
    said so in a comment — "assume no IGST payment (LUT)". WOPAY claims a
    refund of accumulated input credit; WPAY claims a refund of the tax paid.
    Those are different refunds under different rules, and the exporter had
    already paid the tax.

WHAT COULD NOT BE VERIFIED HERE
    The four inv_typ codes themselves. Direct egress is refused by this
    environment's proxy, so the GSTN schema could not be re-read; they come
    from the 2026-09-07 audit's evidence. They are held in ONE map
    (gstr1_builder._INV_TYP) so a correction is a single edit — and the routing
    fix stands regardless of what the codes turn out to be spelled, because
    losing the recipient's GSTIN is wrong under every reading.
"""
from __future__ import annotations

import pytest

from domain.gst.classifier import (GSTInvoiceCategory, TransactionForClassification,
                                   classify_transaction)
from domain.gst.gstr1_builder import (InvoiceForGSTR1, InvoiceLine, build_gstr1)

GSTIN = "27AAAAA0000A1Z5"
BUYER = "27BBBBB1111B1Z5"
PERIOD = "052025"


def _txn(**over) -> TransactionForClassification:
    f = {"id": "T", "transaction_type": "sales_invoice", "party_gstin": BUYER,
         "is_interstate": False, "taxable_amount_paise": 100_000_00,
         "supply_type": "taxable", "invoice_type": "Regular",
         "place_of_supply": "27", "invoice_value_paise": 118_000_00,
         "transaction_date": "2025-05-10", "igst_paise": 0}
    f.update(over)
    return TransactionForClassification(**f)


def _invoice(ref: str, category: GSTInvoiceCategory, *, gstin: str | None = BUYER,
             igst: int = 0) -> InvoiceForGSTR1:
    line = InvoiceLine(hsn_sac_code="998314", description="svc", quantity=1.0,
                       unit="NOS", rate_paise=100_000_00, taxable_paise=100_000_00,
                       gst_rate=18.0, cgst_paise=0, sgst_paise=0,
                       igst_paise=igst, cess_paise=0)
    return InvoiceForGSTR1(
        id=ref, transaction_type="sales_invoice", reference_no=ref,
        transaction_date="2025-05-10", party_gstin=gstin, party_name="Acme",
        place_of_supply="27", is_interstate=True,
        taxable_amount_paise=100_000_00, cgst_paise=0, sgst_paise=0,
        igst_paise=igst, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="zero_rated",
        gst_invoice_category=category, original_invoice_ref=None,
        original_invoice_date=None, lines=[line])


def _payload(invoices):
    return build_gstr1(invoices, GSTIN, PERIOD)


def _inv_typs(payload) -> dict:
    return {inv["inum"]: inv["inv_typ"]
            for g in payload.get("b2b") or [] for inv in g["inv"]}


# ── The classifier sends each one where it belongs ──────────────────────────

@pytest.mark.parametrize("invoice_type,expected", [
    ("SEZ_with_payment", GSTInvoiceCategory.SEZ_WP),
    ("SEZ_without_payment", GSTInvoiceCategory.SEZ_WOP),
    ("Deemed_export", GSTInvoiceCategory.DEEMED_EXPORT),
])
def test_an_sez_or_deemed_export_is_not_a_table_6a_export(invoice_type, expected):
    assert classify_transaction(_txn(invoice_type=invoice_type)) is expected


def test_the_invoice_type_wins_over_a_zero_rated_supply_type(): 
    """Both are true of an SEZ supply — it IS zero-rated — and the one that
    says WHICH zero-rated it is has to decide."""
    assert classify_transaction(
        _txn(invoice_type="SEZ_without_payment", supply_type="zero_rated")
    ) is GSTInvoiceCategory.SEZ_WOP


def test_the_invoice_type_wins_over_place_of_supply_96():
    assert classify_transaction(
        _txn(invoice_type="SEZ_with_payment", place_of_supply="96")
    ) is GSTInvoiceCategory.SEZ_WP


def test_a_real_export_is_still_table_6a():
    assert classify_transaction(
        _txn(supply_type="zero_rated", place_of_supply="96", party_gstin=None)
    ) is GSTInvoiceCategory.EXP_WOP


# ── s.16(3): which limb, read off the invoice ───────────────────────────────

def test_an_export_carrying_igst_is_declared_with_payment():
    assert classify_transaction(
        _txn(supply_type="zero_rated", place_of_supply="96", party_gstin=None,
             igst_paise=18_000_00)
    ) is GSTInvoiceCategory.EXP_WP


def test_an_export_carrying_no_igst_is_under_the_lut():
    assert classify_transaction(
        _txn(supply_type="zero_rated", place_of_supply="96", party_gstin=None,
             igst_paise=0)
    ) is GSTInvoiceCategory.EXP_WOP


def test_a_deemed_export_has_no_lut_limb_to_detect():
    """Notification 48/2017-Central Tax works by charging the tax and refunding
    it afterwards, to the supplier or the recipient. There is no without-payment
    route, so carrying no IGST must not push it into one."""
    assert classify_transaction(
        _txn(invoice_type="Deemed_export", igst_paise=0)
    ) is GSTInvoiceCategory.DEEMED_EXPORT


# ── The payload ─────────────────────────────────────────────────────────────

def test_the_recipients_gstin_survives_into_the_payload():
    """THE defect, stated as the property that was lost."""
    p = _payload([_invoice("INV-SEZ", GSTInvoiceCategory.SEZ_WOP)]).payload
    assert "exp" not in p
    assert [g["ctin"] for g in p["b2b"]] == [BUYER]


@pytest.mark.parametrize("category,code", [
    (GSTInvoiceCategory.B2B, "R"),
    (GSTInvoiceCategory.SEZ_WP, "SEWP"),
    (GSTInvoiceCategory.SEZ_WOP, "SEWOP"),
    (GSTInvoiceCategory.DEEMED_EXPORT, "DE"),
])
def test_each_table_declares_its_own_inv_typ(category, code):
    p = _payload([_invoice("INV-1", category)]).payload
    assert _inv_typs(p) == {"INV-1": code}


def test_no_internal_string_can_reach_inv_typ():
    """The field is filled from the CATEGORY that routed the invoice, so the
    section it lands in and the code it declares cannot disagree — and this
    application's own vocabulary ("SEZ_with_payment") has no way in."""
    p = _payload([_invoice(f"INV-{i}", c) for i, c in enumerate((
        GSTInvoiceCategory.B2B, GSTInvoiceCategory.SEZ_WP,
        GSTInvoiceCategory.SEZ_WOP, GSTInvoiceCategory.DEEMED_EXPORT))]).payload
    assert set(_inv_typs(p).values()) <= {"R", "SEWP", "SEWOP", "DE"}


def test_a_real_export_still_goes_to_table_6a_with_its_exp_typ():
    p = _payload([_invoice("INV-EXP", GSTInvoiceCategory.EXP_WP,
                           gstin=None, igst=18_000_00)]).payload
    assert "b2b" not in p
    assert p["exp"][0]["exp_typ"] == "WPAY"


def test_the_summary_counts_6b_and_6c_separately_from_4a():
    """All three ride in one section, so a CA reading the summary would
    otherwise see only a B2B count and no sign a zero-rated supply was
    declared."""
    s = _payload([
        _invoice("A", GSTInvoiceCategory.B2B),
        _invoice("B", GSTInvoiceCategory.SEZ_WP),
        _invoice("C", GSTInvoiceCategory.SEZ_WOP),
        _invoice("D", GSTInvoiceCategory.DEEMED_EXPORT),
    ]).summary["counts"]
    assert s["b2b"] == 4        # the section really does carry all four
    assert s["sez"] == 2
    assert s["deemed_exports"] == 1


# ── What cannot be filed is NAMED, not dropped ──────────────────────────────

def test_an_sez_supply_with_no_recipient_gstin_is_reported_not_filed():
    """ctin is what the recipient's refund claim matches on. A group keyed on
    "" is a rejection at upload, and one such document would take the whole
    return with it — so it is held out and named."""
    out = _payload([_invoice("INV-NOGST", GSTInvoiceCategory.SEZ_WOP, gstin=None)])
    assert "b2b" not in out.payload
    assert [g["reference_no"] for g in out.gaps] == ["INV-NOGST"]
    assert out.gaps[0]["kind"] == "SEZ_WOP"
    assert "GSTIN" in out.gaps[0]["reason"]


def test_one_unfilable_document_does_not_cost_the_others():
    out = _payload([_invoice("INV-OK", GSTInvoiceCategory.SEZ_WOP),
                    _invoice("INV-NOGST", GSTInvoiceCategory.SEZ_WOP, gstin=None)])
    assert set(_inv_typs(out.payload)) == {"INV-OK"}
    assert [g["reference_no"] for g in out.gaps] == ["INV-NOGST"]


def test_a_complete_return_reports_no_gaps():
    out = _payload([_invoice("INV-1", GSTInvoiceCategory.B2B)])
    assert out.gaps == []


def test_a_b2b_invoice_with_no_gstin_is_not_reported_here():
    """It cannot happen — no GSTIN is what makes a supply B2C — and reporting
    it would be noise on a case the classifier has already handled."""
    out = _payload([_invoice("INV-1", GSTInvoiceCategory.B2B, gstin=None)])
    assert out.gaps == []


# ── The other silence the same mechanism closed ─────────────────────────────

def test_a_note_table_9b_has_no_row_for_is_reported_too():
    """_cdnur_unreportable's own docstring said it "reports how many were
    dropped, so a silent omission becomes a visible number". It was called by
    NOTHING. An intra-state credit note to an unregistered person has no row in
    Table 9B — its effect belongs in the Table 7 summary — and it simply
    vanished from the payload with no count anywhere.
    """
    note = InvoiceForGSTR1(
        id="CN-1", transaction_type="credit_note", reference_no="CN-1",
        transaction_date="2025-05-12", party_gstin=None, party_name="Walk-in",
        place_of_supply="27", is_interstate=False,
        taxable_amount_paise=10_000_00, cgst_paise=900_00, sgst_paise=900_00,
        igst_paise=0, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="taxable",
        gst_invoice_category=GSTInvoiceCategory.CDNA,
        original_invoice_ref="INV-1", original_invoice_date="2025-04-02", lines=[])

    out = _payload([note])
    assert "cdnur" not in out.payload
    assert [g["kind"] for g in out.gaps] == ["CDNUR"]
    assert out.gaps[0]["reference_no"] == "CN-1"
    assert "Table 7" in out.gaps[0]["reason"], (
        "a gap has to say what to do about it, or it is just a count")


def test_an_inter_state_note_to_an_unregistered_person_is_filable():
    """Table 9B does have a row for that one, so it must not be reported."""
    note = InvoiceForGSTR1(
        id="CN-2", transaction_type="credit_note", reference_no="CN-2",
        transaction_date="2025-05-12", party_gstin=None, party_name="Walk-in",
        place_of_supply="29", is_interstate=True,
        taxable_amount_paise=10_000_00, cgst_paise=0, sgst_paise=0,
        igst_paise=1_800_00, cess_paise=0, is_reverse_charge=False,
        invoice_type="Regular", supply_type="taxable",
        gst_invoice_category=GSTInvoiceCategory.CDNA,
        original_invoice_ref="INV-1", original_invoice_date="2025-04-02", lines=[])

    out = _payload([note])
    assert out.payload["cdnur"]
    assert out.gaps == []
