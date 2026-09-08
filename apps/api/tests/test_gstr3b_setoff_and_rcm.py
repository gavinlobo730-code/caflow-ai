"""GSTR-3B: the §49 set-off, reverse charge, and zero-rated supplies.

Three defects, all of which produced a return that looked entirely reasonable
and understated or overstated real money:

  1. CGST and SGST credit never crossed to an IGST liability. §49(5)(b) and (c)
     each have a SECOND limb — CGST credit against IGST, SGST credit against
     IGST — and only the first limbs were implemented. An inter-state seller
     with local purchases was told to pay the whole IGST liability in cash
     while the credit sat in the ledger.

  2. The reverse-charge liability was accumulated into rcm_* and then never
     charged, while the matching credit WAS deducted. §49(4) with §2(82) puts
     reverse-charge tax outside the credit ledger's reach entirely: it is paid
     in cash. The return was understated by twice the reverse-charge tax.

  3. A zero-rated supply contributed its taxable value and dropped its IGST.
     An export made ON PAYMENT of integrated tax under IGST Act §16(3)(b) —
     the route taken precisely so the tax can be refunded under CGST Act §54 —
     declared the turnover and none of the tax.

All amounts are integer paise. Never float.
"""
from domain.gst.gstr3b_computer import (
    GSTR2ARecord,
    PurchaseTransaction,
    SalesTransaction,
    compute_gstr3b,
)

# ₹ helpers → paise
L10 = 10_00_000_00      # ₹10,00,000
L1 = 1_00_000_00        # ₹1,00,000
IGST18_ON_L10 = 1_80_000_00   # ₹1,80,000 — 18% of ₹10,00,000


def _sale(taxable, *, cgst=0, sgst=0, igst=0, cess=0,
          ttype="sales_invoice", supply="taxable", rc=False):
    return SalesTransaction(
        transaction_type=ttype,
        taxable_amount_paise=taxable,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst, cess_paise=cess,
        supply_type=supply, is_reverse_charge=rc,
    )


def _purchase(taxable, *, cgst=0, sgst=0, igst=0, cess=0, rc=False):
    return PurchaseTransaction(
        taxable_amount_paise=taxable,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst, cess_paise=cess,
        is_reverse_charge=rc,
    )


# ── 1. Cross-utilisation: §49(5)(b) and (c), both limbs ──────────────────────

class TestCrossUtilisationAgainstIGST:
    """CGST Act §49(5)(b): credit of central tax "shall first be utilised
    towards payment of central tax and the amount remaining, if any, may be
    utilised towards the payment of integrated tax". §49(5)(c) says the same
    for State tax. Only the first half of each was implemented."""

    def test_local_credit_discharges_an_interstate_liability(self):
        """The reported case. An inter-state sale of ₹10,00,000 (IGST
        ₹1,80,000) against local purchases carrying ₹1,00,000 CGST and
        ₹1,00,000 SGST of credit is NIL payable, with ₹20,000 left over."""
        sales = [_sale(L10, igst=IGST18_ON_L10)]
        purchases = [_purchase(L10, cgst=L1, sgst=L1)]

        r = compute_gstr3b(sales, purchases, [])

        # §49(5)(b) sends the ₹1,00,000 CGST credit to IGST (there is no CGST
        # liability), §49(5)(c) sends ₹80,000 of the SGST credit after it.
        assert r.net_igst == 0
        assert r.net_cgst == 0
        assert r.net_sgst == 0
        assert r.cash_payable_paise == 0
        # ₹20,000 of State credit is untouched and carries into the next period.
        assert r.itc_consumed_paise == IGST18_ON_L10
        assert r.itc_carried_forward_paise == 20_000_00

    def test_cgst_credit_alone_can_discharge_an_igst_liability(self):
        """§49(5)(b) second limb on its own, with no State credit involved."""
        sales = [_sale(L10, igst=IGST18_ON_L10)]
        purchases = [_purchase(L10, cgst=2_00_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_igst == 0
        assert r.itc_carried_forward_paise == 20_000_00

    def test_sgst_credit_alone_can_discharge_an_igst_liability(self):
        """§49(5)(c) second limb on its own."""
        sales = [_sale(L10, igst=IGST18_ON_L10)]
        purchases = [_purchase(L10, sgst=2_00_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_igst == 0
        assert r.itc_carried_forward_paise == 20_000_00

    def test_credit_short_of_the_liability_leaves_the_difference_payable(self):
        """Cross-utilisation is a set-off, not a waiver: ₹1,00,000 of local
        credit against ₹1,80,000 of IGST leaves ₹80,000 payable in cash."""
        sales = [_sale(L10, igst=IGST18_ON_L10)]
        purchases = [_purchase(L10, cgst=50_000_00, sgst=50_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_igst == 80_000_00
        assert r.itc_carried_forward_paise == 0

    def test_igst_credit_is_still_spent_first(self):
        """§49A with Rule 88A: integrated-tax credit is exhausted before any
        central or State credit is touched. Unchanged behaviour, pinned here
        because the cross-utilisation above must not have displaced it."""
        sales = [_sale(L10, igst=IGST18_ON_L10)]
        purchases = [_purchase(L10, igst=1_00_000_00, cgst=50_000_00, sgst=50_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_igst == 0
        assert r.itc_carried_forward_paise == 20_000_00


class TestNoCrossUtilisationBetweenCGSTAndSGST:
    """§49(5)(e) and (f) — the two directions that stay closed. Central credit
    may not pay State tax and State credit may not pay central tax, and the
    new second limbs above must not have opened a path between them."""

    def test_cgst_credit_is_never_used_against_sgst_liability(self):
        """§49(5)(e). CGST credit of ₹30,000 against a ₹10,000 CGST and
        ₹10,000 SGST liability: the CGST half goes, the SGST half stays."""
        sales = [_sale(L1, cgst=10_000_00, sgst=10_000_00)]
        purchases = [_purchase(L1, cgst=30_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_cgst == 0
        assert r.net_sgst == 10_000_00, (
            "§49(5)(e) bars central-tax credit from paying State tax")

    def test_sgst_credit_is_never_used_against_cgst_liability(self):
        """§49(5)(f), the mirror image."""
        sales = [_sale(L1, cgst=10_000_00, sgst=10_000_00)]
        purchases = [_purchase(L1, sgst=30_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_sgst == 0
        assert r.net_cgst == 10_000_00, (
            "§49(5)(f) bars State-tax credit from paying central tax")

    def test_leftover_local_credit_with_no_igst_liability_just_carries_forward(self):
        """With nothing under the integrated head to cross to, the residue of
        each local credit stays where it is rather than crossing to the other."""
        sales = [_sale(L1, cgst=10_000_00, sgst=10_000_00)]
        purchases = [_purchase(L1, cgst=30_000_00, sgst=5_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_cgst == 0
        assert r.net_sgst == 5_000_00
        assert r.itc_carried_forward_paise == 20_000_00


class TestExcessIGSTCreditIsNotStranded:
    """Rule 88A lets the balance of integrated-tax credit go against central
    OR State tax "in any order and in any proportion". The engine halves it —
    the split the Table 6.1 walk-through is written against — but half of it
    landing on a head with a smaller liability must not leave the rest idle
    while the other head is still payable.

    CGST and SGST liabilities are equal on ordinary data (same base, same
    rate), so this is the guard rather than the common path.
    """

    def test_the_unused_half_falls_to_the_other_head(self):
        sales = [_sale(L1, cgst=20_000_00, sgst=0)]
        purchases = [_purchase(L1, igst=20_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_cgst == 0, (
            "half of ₹20,000 covers only ₹10,000 of the CGST liability; the "
            "other half has no SGST liability to meet and must fall back")
        assert r.net_sgst == 0
        assert r.itc_carried_forward_paise == 0


# ── 2. Reverse charge — §49(4) with §2(82): paid in CASH ─────────────────────

class TestReverseChargeIsPaidInCash:
    """CGST Act §49(4) lets the electronic credit ledger pay "output tax", and
    §2(82) defines output tax to EXCLUDE tax payable on reverse charge basis.
    So the §9(3)/(4) liability declared in Table 3.1(d) is discharged in cash,
    in full, and the matching credit is claimed separately on 4(A)(3)."""

    def test_reverse_charge_liability_is_charged_at_all(self):
        """One RCM purchase, nothing else. ₹18,000 is payable in cash."""
        r = compute_gstr3b([], [_purchase(L1, igst=18_000_00, rc=True)], [])

        assert r.rcm_igst == 18_000_00
        assert r.rcm_cash_paise == 18_000_00
        assert r.cash_payable_igst == 18_000_00
        assert r.cash_payable_paise == 18_000_00

    def test_the_credit_ledger_cannot_discharge_it(self):
        """A ledger full of unrelated credit changes nothing: §49(4) does not
        reach reverse-charge tax however much credit is available."""
        purchases = [
            _purchase(L1, igst=18_000_00, rc=True),
            _purchase(L10, cgst=1_00_000_00, sgst=1_00_000_00),
        ]
        r = compute_gstr3b([], purchases, [])

        assert r.rcm_cash_paise == 18_000_00
        assert r.cash_payable_paise == 18_000_00, (
            "reverse-charge tax is payable in cash even with ₹2,00,000 of "
            "credit available — §49(4) read with §2(82)")

    def test_it_is_not_netted_against_outward_tax(self):
        """The doubled understatement. An inter-state sale of ₹1,00,000 (IGST
        ₹18,000) and one RCM purchase of ₹1,00,000 (IGST ₹18,000): the RCM
        credit legitimately discharges the outward liability, and the RCM tax
        itself is still ₹18,000 in cash. The return used to come out at nil."""
        sales = [_sale(L1, igst=18_000_00)]
        purchases = [_purchase(L1, igst=18_000_00, rc=True)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_igst == 0          # outward tax met by the RCM credit
        assert r.rcm_cash_paise == 18_000_00
        assert r.cash_payable_paise == 18_000_00, (
            "the reverse-charge liability was omitted while its credit was "
            "deducted — the return was understated by twice the RCM tax")

    def test_net_tax_on_outward_supplies_stays_free_of_it(self):
        """net_* is Table 6 on OUTWARD supplies and must not absorb the
        reverse-charge tax: adding it there would let the §49 set-off pay it."""
        sales = [_sale(L10, igst=IGST18_ON_L10)]
        purchases = [_purchase(L1, cgst=9_000_00, sgst=9_000_00, rc=True)]

        r = compute_gstr3b(sales, purchases, [])

        # ₹18,000 of local RCM credit crosses to the IGST liability (§49(5)(b)
        # and (c) second limbs), leaving ₹1,62,000 of outward tax.
        assert r.net_igst == 1_62_000_00
        assert r.net_cgst == 0 and r.net_sgst == 0
        # ...and the ₹18,000 of reverse-charge tax is payable on top, in cash.
        assert r.cash_payable_cgst == 9_000_00
        assert r.cash_payable_sgst == 9_000_00
        assert r.cash_payable_paise == 1_62_000_00 + 18_000_00

    def test_it_is_still_declared_in_table_3_1_d(self):
        """The payload side was already right and must stay right."""
        r = compute_gstr3b([], [_purchase(L1, igst=18_000_00, rc=True)], [])
        isup_rev = r.as_gstn_payload("27AAAAA0000A1Z5", "062026")["sup_details"]["isup_rev"]

        assert isup_rev["iamt"] == 18_000     # whole rupees, CGST Act §170

    def test_the_credit_ledger_residual_ignores_it(self):
        """itc_carried_forward is credit left in the ledger. Reverse-charge tax
        never spends credit, so it cannot reduce the residual."""
        purchases = [
            _purchase(L1, igst=18_000_00, rc=True),
            _purchase(L10, cgst=1_00_000_00, sgst=1_00_000_00),
        ]
        r = compute_gstr3b([], purchases, [])

        # 4(C) = ₹18,000 RCM credit + ₹2,00,000 local credit, nothing spent.
        assert r.itc_consumed_paise == 0
        assert r.itc_carried_forward_paise == 2_18_000_00


# ── 3. Zero-rated supplies — IGST Act §16(3) ─────────────────────────────────

class TestZeroRatedSupplies:
    """IGST Act §16(3) gives two routes. Under (a) the supply goes out on a
    bond or LUT with no tax and the unutilised credit is refunded; under (b)
    it goes out ON PAYMENT of integrated tax and that tax is refunded (CGST
    Act §54). Table 3.1(b) of the return carries both the turnover and the
    tax, and the engine used to carry only the turnover."""

    def test_an_export_with_payment_declares_its_igst(self):
        sales = [_sale(L10, igst=IGST18_ON_L10, supply="zero_rated")]

        r = compute_gstr3b(sales, [], [])

        assert r.outward_zero_rated == L10
        assert r.outward_zero_rated_igst == IGST18_ON_L10

        osup_zero = r.as_gstn_payload("27AAAAA0000A1Z5", "062026")["sup_details"]["osup_zero"]
        assert osup_zero["txval"] == 10_00_000     # whole rupees (CGST Act §170)
        assert osup_zero["iamt"] == 1_80_000, (
            "a §16(3)(b) export declares the tax it paid; a nil here forfeits "
            "the §54 refund it was paid for")

    def test_an_export_under_lut_declares_no_tax(self):
        """§16(3)(a). Nothing is invented for a supply that bore no tax."""
        sales = [_sale(L10, supply="zero_rated")]

        r = compute_gstr3b(sales, [], [])

        assert r.outward_zero_rated == L10
        assert r.outward_zero_rated_igst == 0

        osup_zero = r.as_gstn_payload("27AAAAA0000A1Z5", "062026")["sup_details"]["osup_zero"]
        assert osup_zero["txval"] == 10_00_000
        assert osup_zero["iamt"] == 0

    def test_zero_rated_never_carries_central_or_state_tax(self):
        """IGST Act §7(5) makes a zero-rated supply inter-state, so 3.1(b) can
        only ever carry integrated tax."""
        sales = [_sale(L10, igst=IGST18_ON_L10, supply="zero_rated")]
        osup_zero = compute_gstr3b(sales, [], []).as_gstn_payload(
            "27AAAAA0000A1Z5", "062026")["sup_details"]["osup_zero"]

        assert osup_zero["camt"] == 0
        assert osup_zero["samt"] == 0
        assert osup_zero["csamt"] == 0

    def test_it_stays_out_of_table_3_1_a(self):
        """3.1(a) and 3.1(b) are different rows. Zero-rated turnover and tax
        must not leak into the taxable-supplies line."""
        sales = [_sale(L10, igst=IGST18_ON_L10, supply="zero_rated")]

        r = compute_gstr3b(sales, [], [])

        assert r.outward_taxable_value == 0
        assert r.outward_taxable_igst == 0

    def test_a_credit_note_reduces_the_declared_export_tax(self):
        """CGST Act §34 — Table 3.1 is reported net."""
        sales = [
            _sale(L10, igst=IGST18_ON_L10, supply="zero_rated"),
            _sale(L1, igst=18_000_00, supply="zero_rated", ttype="credit_note"),
        ]

        r = compute_gstr3b(sales, [], [])

        assert r.outward_zero_rated == L10 - L1
        assert r.outward_zero_rated_igst == IGST18_ON_L10 - 18_000_00

    def test_the_tax_paid_on_an_export_is_a_real_liability(self):
        """§16(3)(b) is worth taking only because the tax is actually paid, so
        it belongs in the Table 6 liability like any other integrated tax."""
        sales = [_sale(L10, igst=IGST18_ON_L10, supply="zero_rated")]

        r = compute_gstr3b(sales, [], [])

        assert r.liability_igst == IGST18_ON_L10
        assert r.net_igst == IGST18_ON_L10
        assert r.cash_payable_paise == IGST18_ON_L10

    def test_credit_discharges_it_like_any_other_igst(self):
        """The exporter's own input credit sets off the tax on the export, and
        the cross-utilisation of §49(5)(b)/(c) reaches it too."""
        sales = [_sale(L10, igst=IGST18_ON_L10, supply="zero_rated")]
        purchases = [_purchase(L10, cgst=1_00_000_00, sgst=1_00_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.net_igst == 0
        assert r.itc_carried_forward_paise == 20_000_00

    def test_an_lut_export_creates_no_liability(self):
        """The whole point of §16(3)(a): nothing to pay, credit accumulates."""
        sales = [_sale(L10, supply="zero_rated")]
        purchases = [_purchase(L10, cgst=1_00_000_00, sgst=1_00_000_00)]

        r = compute_gstr3b(sales, purchases, [])

        assert r.liability_igst == 0
        assert r.cash_payable_paise == 0
        assert r.itc_carried_forward_paise == 2_00_000_00


# ── All three at once ────────────────────────────────────────────────────────

def test_one_period_carrying_all_three():
    """An exporter's month: a ₹10,00,000 export on payment of IGST, local
    purchases of ₹10,00,000 (₹90,000 CGST + ₹90,000 SGST), and one
    reverse-charge freight bill of ₹1,00,000 (₹18,000 IGST).

    Liability   ₹1,80,000 IGST on the export (3.1(b))
                ₹18,000 reverse charge (3.1(d)) — cash only
    Credit      ₹90,000 CGST + ₹90,000 SGST + ₹18,000 IGST (the RCM credit)
    """
    sales = [_sale(L10, igst=IGST18_ON_L10, supply="zero_rated")]
    purchases = [
        _purchase(L10, cgst=90_000_00, sgst=90_000_00),
        _purchase(L1, igst=18_000_00, rc=True),
    ]

    r = compute_gstr3b(sales, purchases, [], (), ())

    assert r.liability_igst == IGST18_ON_L10
    # ₹18,000 IGST credit first (§49A), then ₹90,000 CGST and ₹72,000 SGST.
    assert r.net_igst == 0
    assert r.itc_carried_forward_paise == 18_000_00
    # Only the reverse charge is left, and it is cash.
    assert r.rcm_cash_paise == 18_000_00
    assert r.cash_payable_paise == 18_000_00

    p = r.as_gstn_payload("27AAAAA0000A1Z5", "062026")
    assert p["sup_details"]["osup_zero"] == {
        "txval": 10_00_000, "iamt": 1_80_000, "camt": 0, "samt": 0, "csamt": 0}
    assert p["sup_details"]["isup_rev"]["iamt"] == 18_000


def test_rule_36_4_cap_still_reaches_the_cross_utilised_credit():
    """The cap is applied to book ITC before the set-off, so credit trimmed by
    Rule 36(4) cannot cross to the IGST liability either."""
    sales = [_sale(L10, igst=IGST18_ON_L10)]
    purchases = [_purchase(L10, cgst=1_00_000_00, sgst=1_00_000_00)]
    # Suppliers have filed only ₹50,000 of each.
    gstr2a = [GSTR2ARecord(cgst_paise=50_000_00, sgst_paise=50_000_00, igst_paise=0)]

    r = compute_gstr3b(sales, purchases, gstr2a)

    assert r.itc_capped_by_2a is True
    assert r.net_igst == IGST18_ON_L10 - 1_00_000_00
