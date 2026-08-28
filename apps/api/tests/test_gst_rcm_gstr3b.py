"""
Production Readiness Phase 2 — GSTR-3B correctness (audit C4, C5, H7).

Pure-domain tests on compute_gstr3b / as_gstn_payload. Integer paise throughout.
"""
from domain.gst.gstr3b_computer import (
    SalesTransaction, PurchaseTransaction, GSTR2ARecord, compute_gstr3b,
)

# ₹ helpers → paise
L = 1_00_000_00        # ₹1,00,000
K18 = 18_000_00        # ₹18,000 (18% of ₹1,00,000)


def _sale(taxable, cgst=0, sgst=0, igst=0, ttype="sales_invoice", rc=False, supply="taxable"):
    return SalesTransaction(ttype, taxable, cgst, sgst, igst, 0, supply, rc)


def _purch(taxable, cgst=0, sgst=0, igst=0, rc=False):
    return PurchaseTransaction(taxable, cgst, sgst, igst, 0, rc)


def test_c4_rcm_itc_not_double_counted():
    # One RCM purchase ₹1,00,000 @18% IGST → ITC is ₹18,000 exactly, not ₹36,000.
    r = compute_gstr3b([], [_purch(L, igst=K18, rc=True)], [])
    assert r.itc_book_igst == K18          # counted ONCE
    assert r.itc_igst == K18


def test_c5_rcm_liability_from_purchases_not_sales():
    # RCM liability (Table 3.2) arises on INWARD supplies (purchases).
    r = compute_gstr3b([], [_purch(L, igst=K18, rc=True)], [])
    assert r.rcm_igst == K18

    # A sale flagged reverse-charge must NOT create RCM liability for the supplier.
    r2 = compute_gstr3b([_sale(L, igst=K18, rc=True)], [], [])
    assert r2.rcm_igst == 0 and r2.rcm_cgst == 0 and r2.rcm_sgst == 0


def test_c4_c5_rcm_net_liability_offsets_itc():
    # Classic RCM: ₹18,000 liability and ₹18,000 ITC → net effect zero.
    r = compute_gstr3b([], [_purch(L, igst=K18, rc=True)], [])
    net_liability = r.rcm_igst           # payable under RCM
    itc = r.itc_igst                     # claimable
    assert net_liability - itc == 0


def test_h7_gstn_txval_is_taxable_value_not_tax():
    # Intra-state taxable sale ₹1,00,000 @18% (CGST 9k + SGST 9k).
    cgst = sgst = 9_000_00
    r = compute_gstr3b([_sale(L, cgst=cgst, sgst=sgst)], [], [])
    assert r.outward_taxable_value == L       # internal computation stays in paise
    payload = r.as_gstn_payload("27AAAAA0000A1Z5", "062025")
    osup = payload["sup_details"]["osup_det"]
    # GSTN GSTR-3B JSON is in WHOLE RUPEES (F16 + CGST Act §170): the payload
    # converts paise -> whole rupees, so txval is the taxable VALUE (not the tax).
    assert osup["txval"] == L // 100          # ₹1,00,000, not 1_00_000_00 paise
    assert osup["camt"] == cgst // 100 and osup["samt"] == sgst // 100 and osup["iamt"] == 0


def test_f16_gstn_payload_amounts_are_rupees_not_paise():
    """F16 regression: every monetary field in the GSTN GSTR-3B payload must be in
    RUPEES (paise / 100), across all sections — not raw paise (which was 100x too
    large and would have filed grossly inflated figures)."""
    from domain.gst.gstr3b_computer import GSTR3BResult

    r = GSTR3BResult(
        outward_taxable_value=10_00_000_00,   # ₹10,00,000
        outward_taxable_igst=1_80_000_00,     # ₹1,80,000
        outward_taxable_cgst=45_000_00,
        outward_taxable_sgst=45_000_00,
        outward_taxable_cess=5_000_00,
        outward_zero_rated=2_00_000_00,
        outward_nil_exempt=50_000_00,
        rcm_igst=10_000_00, rcm_cgst=5_000_00, rcm_sgst=5_000_00,
        itc_igst=90_000_00, itc_cgst=20_000_00, itc_sgst=20_000_00, itc_cess=1_000_00,
    )
    p = r.as_gstn_payload("27AAAAA0000A1Z5", "062026")

    osup = p["sup_details"]["osup_det"]
    assert osup["txval"] == 10_00_000.00 and osup["txval"] != r.outward_taxable_value
    assert osup["iamt"] == 1_80_000.00
    assert osup["camt"] == 45_000.00 and osup["samt"] == 45_000.00
    assert osup["csamt"] == 5_000.00

    assert p["sup_details"]["osup_zero"]["txval"] == 2_00_000.00
    assert p["sup_details"]["osup_nil_exmp"]["txval"] == 50_000.00

    isup_rev = p["sup_details"]["isup_rev"]
    assert isup_rev["iamt"] == 10_000.00 and isup_rev["camt"] == 5_000.00 and isup_rev["samt"] == 5_000.00

    # inward_sup is NOT the reverse-charge block — it is section 5 of the form,
    # exempt / nil-rated / non-GST INWARD supplies, written by GSTN's offline
    # utility as GST and NONGST with inter/intra (V5.8 VBA, sheet rows 48-49).
    # The RCM figures asserted here used an invented {"ty": "RCM", "inter",
    # "intra_cgst", "intra_sgst"} shape the schema has never had. Table 3.1(d)
    # above (isup_rev) is where the reverse-charge liability is declared, and
    # that assertion is the one that matters.
    assert [x["ty"] for x in p["inward_sup"]["isup_details"]] == ["GST", "NONGST"]

    itc = p["itc_elg"]["itc_net"]
    assert itc["iamt"] == 90_000.00 and itc["camt"] == 20_000.00 and itc["samt"] == 20_000.00 and itc["csamt"] == 1_000.00
    # 4(A) is five rows now (IMPG/IMPS/ISRC/ISD/OTH), so index 0 is Import of
    # goods, not the whole credit. The RCM tax sits in ISRC and the rest in OTH.
    avl = {x["ty"]: x for x in p["itc_elg"]["itc_avl"]}
    assert sum(x["iamt"] for x in avl.values()) == 90_000.00
    assert sum(x["csamt"] for x in avl.values()) == 1_000.00
    assert avl["ISRC"]["iamt"] == 10_000.00, (
        "the reverse-charge credit must be declared on the reverse-charge row")
    assert avl["OTH"]["iamt"] == 80_000.00


def test_f16_gstr3b_rounds_to_whole_rupees_section_170():
    """GSTR-3B is filed/paid in WHOLE rupees (CGST Act §170, half rounds up). With
    sub-rupee paise, the payload must round to the nearest rupee — not carry 2
    decimals (GSTR-1's rule) and not carry paise."""
    from domain.gst.gstr3b_computer import GSTR3BResult

    r = GSTR3BResult(
        outward_taxable_value=1_23_456_78,   # ₹1,23,456.78 -> rounds UP to 1,23,457
        outward_taxable_cgst=45_000_49,      # ₹45,000.49  -> rounds DOWN to 45,000
        outward_taxable_sgst=45_000_50,      # ₹45,000.50  -> half rounds UP to 45,001
    )
    osup = r.as_gstn_payload("27AAAAA0000A1Z5", "062026")["sup_details"]["osup_det"]
    assert osup["txval"] == 123457            # whole rupee, half-up
    assert osup["txval"] != 123456.78         # not 2-decimal (GSTR-1 style)
    assert osup["txval"] != 1_23_456_78       # not paise (the F16 bug)
    assert isinstance(osup["txval"], int)     # whole-rupee integer
    assert osup["camt"] == 45000              # .49 rounds down
    assert osup["samt"] == 45001              # .50 rounds up (§170)


def test_mixed_gst_net_of_credit_note():
    # Sale ₹1,00,000@18% intra, credit note ₹20,000@18% intra → net taxable ₹80,000.
    cn_taxable = 20_000_00
    cn_tax = 1_800_00
    sales = [
        _sale(L, cgst=9_000_00, sgst=9_000_00),
        _sale(cn_taxable, cgst=cn_tax, sgst=cn_tax, ttype="credit_note"),
    ]
    r = compute_gstr3b(sales, [], [])
    assert r.outward_taxable_value == L - cn_taxable            # 80,000
    assert r.outward_taxable_cgst == 9_000_00 - cn_tax          # net CGST
    assert r.outward_taxable_sgst == 9_000_00 - cn_tax


def test_regular_and_rcm_purchase_itc_together():
    # Regular purchase (ITC only) + RCM purchase (ITC + liability). ITC = sum once.
    r = compute_gstr3b([], [_purch(L, igst=K18), _purch(L, igst=K18, rc=True)], [])
    assert r.itc_book_igst == 2 * K18        # both counted once each
    assert r.rcm_igst == K18                 # only the RCM one creates liability
