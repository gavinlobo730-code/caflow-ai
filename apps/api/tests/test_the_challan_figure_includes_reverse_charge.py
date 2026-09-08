"""What a CA carries to the payment screen is not the set-off result.

WHAT WAS WRONG
    domain/gst/gstr3b_computer gained rcm_cash_paise and cash_payable_paise
    when the §49(5) cross-utilisation was rebuilt, and the callers were left on
    the old fields. So every surface that reports "net tax payable" reported
    `net_igst + net_cgst + net_sgst` — the part discharged through the credit
    ledger — and omitted the reverse-charge tax entirely.

    That is not a rounding difference. CGST §49(4) allows the electronic credit
    ledger to be used only for "output tax", and §2(82) defines output tax as
    EXCLUDING "tax payable by him on reverse charge basis". So RCM is always
    cash, always on top, and a client with any §9(3)/(4) inward supply was
    shown a challan figure short by the whole of Table 3.1(d). Underpaying
    GSTR-3B carries interest under §50(1) at 18% and the return does not count
    as filed.

    The second half is the same shape: a zero-rated supply made ON PAYMENT OF
    TAX (§16(3)(b)) carries real IGST — refunded later under §54, but a
    liability in this return — and the books-side reconciliation comparator
    omitted it, so an exporter who does not use an LUT showed a permanent false
    mismatch against their own general ledger.

WHAT THIS TEST DOES
    Drives real posted documents through the e2e harness and asserts the
    SERVICE response, not the computer — the computer was already right. A
    field the screen needs and the service does not return is the failure this
    catches.
"""
from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

import tests.test_gstr3b_itc_reversal_from_books as E


@pytest.fixture()
def july():
    mp = MonkeyPatch()
    try:
        db = E._setup(mp)
        E._receive_bill(db, "B-1", 2_00000, "2025-07-04")
        yield E._3b(db, E.JULY)
    finally:
        mp.undo()


def test_the_service_reports_a_cash_figure_separate_from_the_set_off(july):
    """Both numbers, named differently, so neither can be read as the other."""
    assert "net_tax_paise" in july, "the credit-settled figure must stay"
    assert "cash_payable_paise" in july, (
        "the service must report what is actually paid in cash — §49(4) with "
        "§2(82) keeps reverse-charge tax out of the credit ledger"
    )
    assert "rcm_cash_paise" in july, (
        "and it must say how much of the cash is reverse charge, or the CA "
        "cannot reconcile the challan to the return"
    )


def test_table_six_carries_the_challan_total(july):
    """The screen renders `working.net_payable`. Its `total_paise` is the
    set-off result; `challan_total_paise` is what the CA pays."""
    np = july["working"]["net_payable"]
    assert "challan_total_paise" in np
    assert "rcm_cash_paise" in np
    assert np["challan_total_paise"] == np["total_paise"] + np["rcm_cash_paise"]


def test_a_period_with_no_reverse_charge_pays_exactly_the_set_off(july):
    """The no-RCM case must be unchanged — the fix adds a component, it does
    not shift the existing one."""
    np = july["working"]["net_payable"]
    if np["rcm_cash_paise"] == 0:
        assert np["challan_total_paise"] == np["total_paise"]
    assert july["cash_payable_paise"] == july["net_tax_paise"] + july["rcm_cash_paise"]


def test_the_outward_block_reports_the_tax_on_a_zero_rated_supply(july):
    """`zero_rated_paise` is turnover. A §16(3)(b) export on payment of tax
    also carries IGST, and Table 6.1 of the portal's own form includes it."""
    out = july["working"]["outward"]
    assert "zero_rated_paise" in out
    assert "zero_rated_igst_paise" in out


def test_the_ledger_comparator_counts_zero_rated_igst_as_output_tax(july):
    """IGST charged on an export made on payment of tax is posted to the output
    account like any other output tax, so the books-side comparator has to
    carry it or the reconciliation reports a difference that is not one."""
    import inspect
    from services import gst_return_service

    src = inspect.getsource(gst_return_service)
    i = src.index("books_output = (")
    stmt = src[i:src.index("\n\n", i)]
    assert "outward_zero_rated_igst" in stmt, (
        "books_output must include the IGST on zero-rated supplies made on "
        "payment of tax, or every such exporter shows a false GL mismatch"
    )
