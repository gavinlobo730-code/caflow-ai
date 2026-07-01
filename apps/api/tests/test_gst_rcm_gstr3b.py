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
    assert r.outward_taxable_value == L
    payload = r.as_gstn_payload("27AAAAA0000A1Z5", "062025")
    osup = payload["sup_details"]["osup_det"]
    assert osup["txval"] == L                 # taxable VALUE, not the tax
    assert osup["camt"] == cgst and osup["samt"] == sgst and osup["iamt"] == 0


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
