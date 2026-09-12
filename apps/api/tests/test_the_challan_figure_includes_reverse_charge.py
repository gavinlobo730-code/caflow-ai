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


# ═════════════════════════════════════════════════════════════════════════════
# GST-01's REMAINING HALF — the RECORD, not the money
# ═════════════════════════════════════════════════════════════════════════════
#
# The money was right everywhere after 46bd46c and the record was not.
# `gstr3b_returns` holds net_igst/cgst/sgst_paise and net_tax_paise, every one
# of them the credit-settled figure, and `filings.tax_payable_paise` is written
# from net_tax_paise — so a return with any reverse charge on it recorded a tax
# payable SMALLER than the challan the CA actually paid, on the row that is
# supposed to BE the evidence of what was filed.
#
# Migration 339 adds rcm_cash_paise and cash_payable_paise. Both default to 0,
# and 0 means "not stated" rather than "nothing to pay" — a row saved before the
# migration has never carried a cash figure, so the readers fall back to
# net_tax_paise, which is what WAS recorded. A backfill is deliberately not
# attempted: recomputing the set-off would run it against books that may have
# moved since the return was filed.

def test_the_save_request_accepts_the_cash_figure():
    from routers.gst_workspace import SaveGSTR3BRequest

    fields = SaveGSTR3BRequest.model_fields
    assert "cash_payable_paise" in fields, (
        "SaveGSTR3BRequest had no cash column, so the challan could not be "
        "stored however right the computation was")
    assert "rcm_cash_paise" in fields, (
        "and the two must be separable: a challan equal to the residual because "
        "there is no reverse charge, and one equal to it because the credit ran "
        "out, are different facts")
    # Defaulted rather than required — a caller that has not been updated must
    # not start failing.
    body = SaveGSTR3BRequest(client_id="c", period="042026", gstin="27AAAAA0000A1Z2",
                             net_tax_paise=1_79_500)
    assert body.cash_payable_paise == 0
    assert body.rcm_cash_paise == 0


def test_a_stored_row_without_a_cash_figure_falls_back_to_the_residual():
    """0 is "not stated". Reading it as "nothing to pay" would report a zero
    challan for every return saved before migration 339."""
    from routers.gst_workspace import _cash_payable

    assert _cash_payable(0, 1_79_500) == 1_79_500
    assert _cash_payable(None, 1_79_500) == 1_79_500
    # And a real figure wins over the residual, which is the whole point.
    assert _cash_payable(1_80_000, 1_79_500) == 1_80_000
    # A genuinely nil return stays nil.
    assert _cash_payable(0, 0) == 0


def test_the_filings_row_records_what_was_paid_not_what_was_set_off():
    """`filings.tax_payable_paise` is the evidence of the filing. §49(4) with
    §2(82) makes reverse-charge tax cash on top of the set-off, so the residual
    is the wrong figure for it whenever 3.1(d) is non-zero."""
    import inspect

    from routers import gst_workspace

    src = inspect.getsource(gst_workspace.update_gstr3b_status)
    i = src.index("record_filing(")
    call = src[i:src.index(")\n", i)]
    assert "_cash_payable(" in call, (
        "record_filing must be given the challan, not net_tax_paise alone")
    assert 'rec.get("cash_payable_paise")' in call


def test_the_detail_report_can_list_the_documents_behind_31d():
    """A figure with no documents behind it is the one line of the return
    nobody can check — and it is the line whose tax cannot be paid from credit,
    so getting it wrong costs cash rather than credit."""
    from services.gst_return_service import GSTR3B_DETAIL_LINES

    assert "3.1d" in GSTR3B_DETAIL_LINES


def test_31d_lists_only_the_reverse_charge_documents():
    """The control: 4(A) lists every bill, 3.1(d) only the ones carrying the
    charge. If they came back the same the filter is not running."""
    from services import gst_return_service as G

    mp = MonkeyPatch()
    try:
        db = E._setup(mp)
        E._receive_bill(db, "PLAIN-1", 2_00000, "2025-07-04")
        four_a = G.gstr3b_detail(db, E.FIRM, "CLI", E.JULY, "4A")
        three_one_d = G.gstr3b_detail(db, E.FIRM, "CLI", E.JULY, "3.1d")
        assert four_a["rows"], "the harness must post at least one bill"
        assert not three_one_d["rows"], (
            "an ordinary bill is in 4(A) and must not be in 3.1(d)")
        assert three_one_d["count"] == 0

        # And a bill that DOES carry the charge appears.
        for b in db.rows("purchase_bills"):
            b["is_reverse_charge"] = True
        with_rcm = G.gstr3b_detail(db, E.FIRM, "CLI", E.JULY, "3.1d")
        assert len(with_rcm["rows"]) == len(four_a["rows"]), (
            "with every bill marked reverse charge the two lines must agree — "
            "otherwise the filter is not the only difference between them")
    finally:
        mp.undo()
