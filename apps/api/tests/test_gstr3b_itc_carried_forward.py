"""Net tax of zero has to say WHICH zero it is.

WHAT WAS MISSING
    Apex Trading Solutions, April 2026, on the deployed screen:

        Tax Liability   Rs 17,77,664.34
        ITC Claimed     Rs 54,32,625.99
        Net Tax         Rs 0

    Every figure verified correct against the books to the paisa. And yet the
    screen is unreadable, because Rs 0 is equally consistent with

        liability and credit cancelled out exactly, nothing carries forward
        credit exceeded liability and Rs 36,54,961.65 carries into May

    and the difference between those two readings is a third of a crore of the
    client's money. The return had no field for it, so the screen could not
    show it however it was rendered.

WHAT IS ASSERTED
    That the residual is right in the ordinary case, that it is zero whenever
    tax is actually payable (a balance and a payment cannot both exist — the
    credit would have paid the tax), and above all that it RECONCILES: credit
    available, minus credit consumed, minus credit carried, must be zero for
    any input at all. That last one is the invariant that makes the figure
    trustworthy; the specific numbers below are just worked examples of it.

    The set-off is deliberately NOT changed here. Section 49(4) permits payment
    only out of credit available in the electronic credit ledger, net tax
    already floors at zero, and every net_* figure this suite asserts elsewhere
    is unmoved. What was added is the residual of that same arithmetic.
"""
from __future__ import annotations

import pytest

from _pytest.monkeypatch import MonkeyPatch

import tests.test_gstr3b_itc_reversal_from_books as E
from domain.gst.gstr3b_computer import (
    PurchaseTransaction,
    SalesTransaction,
    compute_gstr3b,
)


def sale(taxable, igst=0, cgst=0, sgst=0, cess=0):
    return SalesTransaction(
        transaction_type="sales_invoice", taxable_amount_paise=taxable,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst, cess_paise=cess,
        supply_type="taxable", is_reverse_charge=False,
    )


def purchase(taxable, igst=0, cgst=0, sgst=0, cess=0, **kw):
    return PurchaseTransaction(
        taxable_amount_paise=taxable, cgst_paise=cgst, sgst_paise=sgst,
        igst_paise=igst, cess_paise=cess, is_reverse_charge=False, **kw
    )


# ── The reported case ───────────────────────────────────────────────────────

def test_the_april_2026_figures_carry_forward_what_the_screen_did_not_show():
    """Apex's real April, head for head, straight from the production books:

        output   IGST 12,31,348.40  CGST 2,73,157.79  SGST 2,73,158.15
        credit   IGST 37,20,871.07  CGST 8,55,877.28  SGST 8,55,877.64
    """
    result = compute_gstr3b(
        [sale(1029804305, igst=123134840, cgst=27315779, sgst=27315815)],
        [purchase(3076249027, igst=372087107, cgst=85587728, sgst=85587764)],
        [],
    )
    # Unchanged: nothing to pay.
    assert result.net_igst == 0
    assert result.net_cgst == 0
    assert result.net_sgst == 0

    assert result.itc_available_paise == 543262599      # Rs 54,32,625.99
    assert result.itc_consumed_paise == 177766434       # Rs 17,77,664.34
    assert result.itc_carried_forward_paise == 365496165  # Rs 36,54,961.65


# ── The invariant ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("out_i,out_c,out_s,in_i,in_c,in_s", [
    (0, 0, 0, 0, 0, 0),                       # nothing at all
    (100000, 0, 0, 0, 0, 0),                  # liability, no credit
    (0, 0, 0, 100000, 0, 0),                  # credit, no liability
    (100000, 50000, 50000, 100000, 50000, 50000),   # exactly matched
    (100000, 50000, 50000, 900000, 10000, 10000),   # IGST credit spills over
    (900000, 10000, 10000, 100000, 50000, 50000),   # liability outruns credit
    (0, 500000, 500000, 900000, 0, 0),        # only IGST credit, only state tax
    (123134840, 27315779, 27315815, 372087107, 85587728, 85587764),  # April
])
def test_available_less_consumed_is_always_what_is_carried(
        out_i, out_c, out_s, in_i, in_c, in_s):
    """The figure is only worth showing if it reconciles for every input.

    A carried-forward balance that did not tie back to the net tax printed
    beside it would be a second, disagreeing set-off — the exact failure mode
    that keeping this a residual of net_* is meant to prevent.
    """
    result = compute_gstr3b(
        [sale(out_i + out_c + out_s, igst=out_i, cgst=out_c, sgst=out_s)],
        [purchase(in_i + in_c + in_s, igst=in_i, cgst=in_c, sgst=in_s)],
        [],
    )
    assert (result.itc_available_paise
            - result.itc_consumed_paise
            - result.itc_carried_forward_paise) == 0


def test_nothing_carries_forward_while_tax_is_still_payable():
    """Credit left over AND tax to pay cannot both be true: the credit would
    have paid the tax. If this ever fails, the set-off stopped short."""
    result = compute_gstr3b(
        [sale(5000000, igst=900000)],
        [purchase(1000000, igst=180000)],
        [],
    )
    assert result.net_igst > 0, "this fixture is meant to leave tax payable"
    assert result.itc_carried_forward_paise == 0


def test_credit_with_no_liability_carries_in_full():
    result = compute_gstr3b([], [purchase(1000000, igst=180000, cgst=9000, sgst=9000)], [])
    assert result.itc_carried_forward_paise == 198000
    assert result.itc_consumed_paise == 0


def test_an_exactly_matched_period_carries_nothing():
    """The other reading of a zero net tax, and the one that must NOT report a
    balance."""
    result = compute_gstr3b(
        [sale(1000000, igst=180000)],
        [purchase(1000000, igst=180000)],
        [],
    )
    assert result.net_igst == 0
    assert result.itc_carried_forward_paise == 0, (
        "liability and credit cancelled out — there is nothing to carry, and "
        "saying otherwise would invent a balance"
    )


# ── It is 4(C) that carries, not 4(A) ───────────────────────────────────────

def test_blocked_credit_never_reaches_the_carry_forward():
    """Section 17(5) credit is reversed in 4(B) and never enters 4(C), so it
    cannot sit in the ledger waiting to be used next month. Reporting gross
    4(A) here would tell a CA they hold credit the law says they do not."""
    result = compute_gstr3b(
        [],
        [purchase(1000000, igst=180000, ineligible_igst_paise=80000)],
        [],
    )
    assert result.itc_avail_igst == 180000        # 4(A) is gross
    assert result.itc_net_igst == 100000          # 4(C) after the 4(B) reversal
    assert result.itc_carried_forward_paise == 100000


@pytest.mark.parametrize("out_i,out_c,out_s,in_i,in_c,in_s", [
    (0, 0, 0, 0, 0, 0),
    (18000000, 0, 0, 18000, 0, 0),            # liability dwarfs credit
    (0, 100000, 0, 1000000, 0, 0),            # credit dwarfs liability
    (100000, 50000, 50000, 100000, 50000, 50000),
    (0, 500000, 500000, 900000, 0, 0),        # IGST credit spilling to both
    (123134840, 27315779, 27315815, 372087107, 85587728, 85587764),
])
def test_the_set_off_never_spends_credit_it_does_not_have(
        out_i, out_c, out_s, in_i, in_c, in_s):
    """Consumed <= available is what keeps the carry-forward non-negative, and
    it is the property worth asserting rather than the floor itself.

    itc_carried_forward_paise clamps at zero, and that clamp is DEFENSIVE: no
    input reachable through compute_gstr3b drives consumption past the credit
    available, because net_* is itself derived by subtracting that credit. An
    earlier version of this file asserted `>= 0` directly and passed with the
    clamp deleted — a test that could not fail, which is worse than none.

    So this asserts the thing the clamp exists to guarantee. If the set-off is
    ever changed to discharge liability it has no credit for, this fails and
    the clamp stops silently absorbing it.
    """
    result = compute_gstr3b(
        [sale(out_i + out_c + out_s, igst=out_i, cgst=out_c, sgst=out_s)],
        [purchase(in_i + in_c + in_s, igst=in_i, cgst=in_c, sgst=in_s)],
        [],
    )
    assert result.itc_consumed_paise <= result.itc_available_paise, (
        "Table 6 discharged more liability than there was credit to discharge "
        "it with — the carry-forward would go negative and read as a refund"
    )
    assert result.itc_carried_forward_paise >= 0


# ── It has to reach the two screens that show a net tax ─────────────────────

@pytest.fixture()
def from_books():
    """A real from-books response, through the same harness the screen hits."""
    mp = MonkeyPatch()
    try:
        db = E._setup(mp)
        E._receive_bill(db, "B-1", 5_00000, "2025-07-04")
        yield E._3b(db, E.JULY)
    finally:
        mp.undo()


def test_the_endpoint_returns_the_carry_forward_at_the_top_level(from_books):
    """/clients/[id]/compliance/gst reads computeResult.itc_carried_forward_paise
    beside Tax Liability, ITC Claimed and Net Tax — a flat field, not one inside
    `working`. test_gstr3b_screen_contract covers the firm-level screen's
    working.* bindings; this covers the client workspace's flat one, which that
    scanner never looks at."""
    assert "itc_carried_forward_paise" in from_books
    assert isinstance(from_books["itc_carried_forward_paise"], int)


def test_the_working_block_carries_the_utilisation_the_firm_screen_renders(from_books):
    u = from_books["working"]["itc_utilisation"]
    assert set(u) == {"available_paise", "consumed_paise", "carried_forward_paise"}
    assert all(isinstance(v, int) for v in u.values())


def test_the_two_places_it_is_reported_can_never_disagree(from_books):
    """One is a flat field, the other sits inside `working`. Two copies of a
    number in one response is how a screen ends up contradicting itself."""
    assert (from_books["itc_carried_forward_paise"]
            == from_books["working"]["itc_utilisation"]["carried_forward_paise"])


def test_the_response_reconciles_end_to_end(from_books):
    """The whole point, against a real response rather than a hand-built one.

    The three headline figures the screen prints side by side have to close:
    what was owed, less what credit paid, is what is still payable — and what
    credit was NOT spent is what carries.
    """
    u = from_books["working"]["itc_utilisation"]
    assert u["available_paise"] - u["consumed_paise"] == u["carried_forward_paise"]
    assert (from_books["tax_liability_paise"] - u["consumed_paise"]
            == from_books["net_tax_paise"]), (
        "liability minus the credit set off against it is not the net tax on "
        "screen — the two numbers beside each other do not describe one return"
    )


def test_the_claimed_figure_is_what_can_be_spent(from_books):
    """`itc_claimed_paise` is Table 4(C) across IGST/CGST/SGST and is what the
    screen labels ITC Claimed; `available_paise` is the same plus cess. The
    carry-forward is measured against the second, so a cess-free period must
    show them equal — if they ever diverge without cess, one of the two is
    counting something the other is not."""
    u = from_books["working"]["itc_utilisation"]
    assert u["available_paise"] >= from_books["itc_claimed_paise"]
    assert u["available_paise"] - from_books["itc_claimed_paise"] == 0, (
        "this fixture posts no cess, so 4(C) and the spendable credit should "
        "be the same figure"
    )
