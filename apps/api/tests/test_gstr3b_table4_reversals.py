"""GSTR-3B Table 4 in the shape the portal has used since 1 September 2022.

WHAT WAS WRONG
    compute_gstr3b filed:

        4(A) ITC available   NET of blocked credit
        4(B) ITC reversed    hard-coded []
        4(D) ineligible      the §17(5) amount, under type "RUL"

    That is the layout the form had BEFORE Notification 14/2022-Central Tax,
    read with Circular 170/02/2022-GST, which the GSTN put live on the portal
    on 01-09-2022 (so from the August 2022 period onward). Under the current
    form:

        4(A)    is GROSS — all ITC availed, including credit reversed later in
                the same return. It is auto-populated from GSTR-2B, so a 4(A)
                that has already deducted blocked credit cannot tie to 2B and
                the taxpayer is asked to explain a difference that is really
                just a different definition.
        4(B)(1) permanent reversals: Rules 38, 42, 43 and §17(5).
        4(B)(2) reclaimable reversals: Rule 37/37A, §16(2)(b) and (c) — the
                ones that come back through 4(A)(5) later, and which the
                electronic credit reversal and re-claimed statement tracks.
        4(C)    = 4(A) - 4(B).
        4(D)(2) §16(4) and place-of-supply ineligibility only. The circular is
                explicit that §17(5), once shown in 4(B), is NOT repeated here.

    The old layout arrived at the same tax payable — 4(C) came out the same
    either way — which is exactly why nothing caught it. What was wrong was the
    face of the return: 4(A) understated against 2B, and 4(B) declared that no
    credit had been reversed in a period when the books had reversed some.

WHAT THIS FILE PINS
    The arithmetic identity (4C = 4A - 4B), the classification (which reversal
    lands on which side), and the two things the old code got wrong that no
    total would ever reveal.
"""
import pytest

from domain.gst.gstr3b_computer import (
    GSTR2ARecord,
    ITCReversal,
    PurchaseTransaction,
    SalesTransaction,
    compute_gstr3b,
)

GSTIN = "27AABCU9603R1ZM"
PERIOD = "042026"


def _purchase(cgst, sgst, igst=0, *, blocked_cgst=0, blocked_sgst=0, blocked_igst=0):
    return PurchaseTransaction(
        taxable_amount_paise=(cgst + sgst + igst) * 100 // 18 if (cgst or sgst or igst) else 0,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst, cess_paise=0,
        is_reverse_charge=False,
        ineligible_cgst_paise=blocked_cgst,
        ineligible_sgst_paise=blocked_sgst,
        ineligible_igst_paise=blocked_igst,
    )


def _sale(cgst, sgst):
    return SalesTransaction(
        transaction_type="invoice",
        taxable_amount_paise=(cgst + sgst) * 100 // 18,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=0, cess_paise=0,
        supply_type="taxable", is_reverse_charge=False,
    )


# Four DISTINCT amounts, so no assertion below can be satisfied by the wrong
# bucket happening to hold the same number.
AVAILED_CGST = 1_00_000        # Rs 1,000.00 of ordinary credit
BLOCKED_CGST = 7_000           # Rs 70.00 blocked under §17(5)
PERM_CGST = 3_000              # Rs 30.00 permanently reversed (bill cancelled)
TEMP_CGST = 1_100              # Rs 11.00 reversed under Rule 37, reclaimable


def _table4(result):
    return result.as_gstn_payload(GSTIN, PERIOD)["itc_elg"]


def _avl(t4, ty="OTH"):
    """One row of Table 4(A). It is five objects — IMPG, IMPS, ISRC, ISD, OTH
    — one per row of the form (GSTN offline utility V5.8, sheet rows 31-35).
    Ordinary purchase credit lands in OTH, "All other ITC"."""
    return {x["ty"]: x for x in t4["itc_avl"]}[ty]


def _avl_total(t4, head):
    return sum(x[head] for x in t4["itc_avl"])


def _base():
    """One purchase carrying both ordinary and blocked credit, plus one
    permanent and one reclaimable reversal."""
    purchases = [_purchase(AVAILED_CGST + BLOCKED_CGST, AVAILED_CGST + BLOCKED_CGST,
                           blocked_cgst=BLOCKED_CGST, blocked_sgst=BLOCKED_CGST)]
    reversals = [
        ITCReversal(cgst_paise=PERM_CGST, sgst_paise=PERM_CGST,
                    reclaimable=False, reason="purchase bill B-1 cancelled"),
        ITCReversal(cgst_paise=TEMP_CGST, sgst_paise=TEMP_CGST,
                    reclaimable=True, reason="Rule 37 — supplier unpaid 180 days"),
    ]
    return compute_gstr3b([_sale(5_00_000, 5_00_000)], purchases, [], reversals)


# ── the fixture has to exercise every bucket ─────────────────────────────────

def test_the_fixture_puts_a_distinct_amount_in_every_bucket():
    """Guard. If any of the four were zero or equal to another, the assertions
    below could pass with two buckets swapped, or with 4(B) still empty."""
    assert len({AVAILED_CGST, BLOCKED_CGST, PERM_CGST, TEMP_CGST}) == 4
    r = _base()
    assert r.itc_ineligible_cgst == BLOCKED_CGST
    assert r.itc_rev_perm_cgst == PERM_CGST
    assert r.itc_rev_temp_cgst == TEMP_CGST
    assert r.itc_cgst == AVAILED_CGST


# ── 4(A): gross, so it ties to GSTR-2B ───────────────────────────────────────

def test_4a_reports_all_credit_availed_including_blocked_credit():
    avl = _avl(_table4(_base()))
    assert avl["camt"] == (AVAILED_CGST + BLOCKED_CGST) // 100, (
        "4(A) is net of §17(5) — it cannot tie to the 2B-populated figure the "
        "portal shows, and the taxpayer is asked to explain the difference")
    assert avl["samt"] == (AVAILED_CGST + BLOCKED_CGST) // 100


def test_4a_is_not_reduced_by_a_reversal_declared_in_4b():
    """Reversing in 4(B) and also netting it out of 4(A) would deduct the same
    credit twice."""
    with_rev = _avl(_table4(_base()))["camt"]
    no_rev = _avl(_table4(compute_gstr3b(
        [_sale(5_00_000, 5_00_000)],
        [_purchase(AVAILED_CGST + BLOCKED_CGST, AVAILED_CGST + BLOCKED_CGST,
                   blocked_cgst=BLOCKED_CGST, blocked_sgst=BLOCKED_CGST)],
        [], [],
    )))["camt"]
    assert with_rev == no_rev


# ── 4(B): the split is the whole point ───────────────────────────────────────

def test_4b1_carries_the_permanent_reversals_and_section_17_5():
    rev = {r["ty"]: r for r in _table4(_base())["itc_rev"]}
    assert set(rev) == {"RUL", "OTH"}, rev
    assert rev["RUL"]["camt"] == (BLOCKED_CGST + PERM_CGST) // 100, (
        "4(B)(1) must carry both the §17(5) amount and the reversals that will "
        "never be reclaimed")


def test_4b2_carries_only_the_reclaimable_reversals():
    rev = {r["ty"]: r for r in _table4(_base())["itc_rev"]}
    assert rev["OTH"]["camt"] == TEMP_CGST // 100, (
        "4(B)(2) tells the portal a credit is coming back through 4(A)(5); the "
        "credit reversal and re-claimed statement reconciles against it, so a "
        "permanent reversal declared here is a balance that never clears")


def test_a_reversal_is_not_counted_on_both_sides():
    rev = {r["ty"]: r for r in _table4(_base())["itc_rev"]}
    assert rev["RUL"]["camt"] + rev["OTH"]["camt"] == (
        BLOCKED_CGST + PERM_CGST + TEMP_CGST) // 100


@pytest.mark.parametrize("reclaimable,expected_ty", [(False, "RUL"), (True, "OTH")])
def test_the_reclaimable_flag_alone_decides_the_side(reclaimable, expected_ty):
    r = compute_gstr3b([], [_purchase(50_000, 50_000)], [], [
        ITCReversal(cgst_paise=9_000, reclaimable=reclaimable, reason="x")])
    rev = {x["ty"]: x for x in _table4(r)["itc_rev"]}
    other = "OTH" if expected_ty == "RUL" else "RUL"
    assert rev[expected_ty]["camt"] == 90
    assert rev[other]["camt"] == 0


# ── 4(C) = 4(A) - 4(B) ───────────────────────────────────────────────────────

def test_4c_is_4a_minus_4b_on_every_head():
    t4 = _table4(_base())
    rev = t4["itc_rev"]
    for head in ("iamt", "camt", "samt", "csamt"):
        assert t4["itc_net"][head] == _avl_total(t4, head) - sum(r[head] for r in rev), head


def test_the_net_credit_is_what_the_old_layout_reported_as_available():
    """The move must not change how much credit is actually claimed — only where
    it is declared. Without the two reversals, 4(C) is the old 4(A)."""
    r = compute_gstr3b(
        [_sale(5_00_000, 5_00_000)],
        [_purchase(AVAILED_CGST + BLOCKED_CGST, AVAILED_CGST + BLOCKED_CGST,
                   blocked_cgst=BLOCKED_CGST, blocked_sgst=BLOCKED_CGST)],
        [], [],
    )
    assert _table4(r)["itc_net"]["camt"] == AVAILED_CGST // 100


def test_a_reversal_larger_than_the_credit_does_not_file_a_negative_4c():
    """A negative figure in 4(C) is not a value the form accepts. It can happen
    honestly — a bill cancelled in a month with almost no purchases."""
    r = compute_gstr3b([], [_purchase(1_000, 1_000)], [], [
        ITCReversal(cgst_paise=50_000, sgst_paise=50_000, reclaimable=False,
                    reason="large cancellation")])
    assert _table4(r)["itc_net"]["camt"] == 0
    assert r.itc_net_cgst == 0


# ── 4(D): what must NOT be here ──────────────────────────────────────────────

def test_section_17_5_is_not_repeated_in_4d():
    inelg = _table4(_base())["itc_inelg"]
    assert all(x["camt"] == 0 and x["samt"] == 0 and x["iamt"] == 0 for x in inelg), (
        "§17(5) is declared in 4(B)(1); Circular 170/02/2022-GST says it is not "
        "to be reported again in 4(D), and reporting it twice overstates the "
        "ineligible credit the portal shows against the taxpayer")


# ── whole rupees, CGST Act §170 ──────────────────────────────────────────────

def test_every_table_4_figure_is_a_whole_rupee_integer():
    t4 = _table4(compute_gstr3b([], [_purchase(1_00_067, 1_00_049)], [], [
        ITCReversal(cgst_paise=2_051, sgst_paise=2_049, reclaimable=True, reason="x")]))
    figures = ([x[h] for x in t4["itc_avl"] for h in ("iamt", "camt", "samt", "csamt")]
               + [x[h] for x in t4["itc_rev"] for h in ("iamt", "camt", "samt", "csamt")]
               + [t4["itc_net"][h] for h in ("iamt", "camt", "samt", "csamt")])
    assert all(isinstance(f, int) for f in figures), figures
    # §170: half a rupee or more rounds up. 2,051 paise -> Rs 21, 2,049 -> Rs 20.
    rev = {x["ty"]: x for x in t4["itc_rev"]}
    assert rev["OTH"]["camt"] == 21 and rev["OTH"]["samt"] == 20


# ── no reversals at all: the common case must be untouched ───────────────────

def test_a_period_with_no_reversals_still_declares_both_4b_rows_as_zero():
    """The portal expects the rows; omitting them is not the same as zero."""
    t4 = _table4(compute_gstr3b([_sale(1_000, 1_000)], [_purchase(500, 500)], [], []))
    rev = {x["ty"]: x for x in t4["itc_rev"]}
    assert set(rev) == {"RUL", "OTH"}
    assert all(rev[t][h] == 0 for t in rev for h in ("iamt", "camt", "samt", "csamt"))
    assert t4["itc_net"]["camt"] == 5


def test_the_2a_cap_still_applies_to_4a():
    """Rule 36(4) caps the credit at what suppliers filed. 4(A) reports credit
    AVAILED, so the cap has to bite before the gross-up, not after."""
    r = compute_gstr3b([], [_purchase(1_00_000, 1_00_000)], [
        GSTR2ARecord(cgst_paise=60_000, sgst_paise=60_000, igst_paise=0)], [])
    assert r.itc_capped_by_2a is True
    assert _avl(_table4(r))["camt"] == 600


# ── Table 6: what the reversal does to the tax actually payable ──────────────

def test_the_set_off_uses_4c_not_4a():
    """CGST Act §49(4) lets tax be paid only from credit AVAILABLE in the
    electronic credit ledger. Credit reversed in this very return is not
    available — setting off the gross 4(A) figure spends the same rupee twice
    and the taxpayer underpays by the whole reversed amount."""
    sale = _sale(90000, 90000)
    purchase = _purchase(45000, 45000)
    without = compute_gstr3b([sale], [purchase], [], [])
    with_rev = compute_gstr3b([sale], [purchase], [], [
        ITCReversal(cgst_paise=45000, sgst_paise=45000, reclaimable=False,
                    reason="bill cancelled")])

    # Guard: the reversal really does empty 4(C), or the assertion below could
    # hold with the set-off unchanged.
    assert without.itc_net_cgst == 45000 and with_rev.itc_net_cgst == 0

    assert without.net_cgst == 90000 - 45000
    assert with_rev.net_cgst == 90000, (
        "the reversed credit was still set off against output tax — the return "
        "asks for less money than the law does")
    assert with_rev.net_sgst == 90000


def test_a_reclaimable_reversal_also_reduces_the_credit_set_off():
    """Rule 37 credit is coming back later, but it is not available NOW."""
    r = compute_gstr3b([_sale(90000, 90000)], [_purchase(45000, 45000)], [], [
        ITCReversal(cgst_paise=45000, sgst_paise=45000, reclaimable=True,
                    reason="Rule 37")])
    assert r.net_cgst == 90000 and r.net_sgst == 90000


def test_blocked_credit_was_already_out_of_the_set_off_and_stays_out():
    """§17(5) never reached the set-off before this change either — it is
    excluded from itc_* at source. Moving it into 4(B) must not double-count it
    by subtracting it a second time."""
    r = compute_gstr3b([_sale(90000, 90000)],
                       [_purchase(45000, 45000, blocked_cgst=5000, blocked_sgst=5000)],
                       [], [])
    # Credit available = 45000 - 5000 blocked = 40000. Tax = 90000 - 40000.
    assert r.itc_net_cgst == 40000
    assert r.net_cgst == 50000


def test_a_period_with_no_reversals_pays_exactly_what_it_paid_before():
    """The guard against fixing the reversal case by breaking every other one."""
    r = compute_gstr3b([_sale(90000, 90000)], [_purchase(45000, 45000)], [], [])
    assert r.net_cgst == 45000 and r.net_sgst == 45000
    assert r.itc_net_cgst == r.itc_cgst == 45000


def test_excess_igst_credit_is_still_cross_utilised_after_a_reversal():
    """§49(5): surplus IGST credit spills to CGST then SGST. The spill must be
    computed from the credit that survives 4(B), not from 4(A)."""
    sale = SalesTransaction("invoice", 5_00000, 45000, 45000, 0, 0, "taxable", False)
    purchase = PurchaseTransaction(10_00000, 0, 0, 1_00000, 0, False)
    r = compute_gstr3b([sale], [purchase], [], [
        ITCReversal(igst_paise=40000, reclaimable=False, reason="bill cancelled")])
    # IGST credit surviving 4(B) = 60000, no IGST output, so 60000 spills:
    # 30000 to CGST and 30000 to SGST.
    assert r.itc_net_igst == 60000
    assert r.net_igst == 0
    assert r.net_cgst == 45000 - 30000
    assert r.net_sgst == 45000 - 30000


def test_a_cess_reversal_reduces_the_cess_payable():
    """Cess has its own set-off line and its own reversal column. A cancelled
    bill on a cess-bearing supply (tobacco, coal, motor vehicles) carries cess
    like any other head, so the same rule applies to it."""
    sale = SalesTransaction("invoice", 5_00000, 45000, 45000, 0, 20000,
                            "taxable", False)
    purchase = PurchaseTransaction(2_00000, 18000, 18000, 0, 12000, False)
    without = compute_gstr3b([sale], [purchase], [], [])
    with_rev = compute_gstr3b([sale], [purchase], [], [
        ITCReversal(cess_paise=12000, reclaimable=False, reason="bill cancelled")])
    assert without.net_cess == 20000 - 12000
    assert with_rev.net_cess == 20000, (
        "the reversed cess credit was still set off — cess is a separate levy "
        "under the GST (Compensation to States) Act and underpaying it is the "
        "same defect as underpaying CGST")
    assert _table4(with_rev)["itc_net"]["csamt"] == 0
