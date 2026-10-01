"""A GSTR-3B is set off against what the credit ledger HOLDS, not only against what
this return availed (gst-06).

WHAT WAS WRONG
    `compute_gstr3b` spent Table 4(C) of THIS return and nothing else. The
    electronic credit ledger is a running balance — credit one return leaves
    unspent is still there when the next is filed, and CGST Act s.49(4) lets the
    whole of it pay output tax. So Apex's April 2026, which closed holding
    Rs 36,54,961.65 of IGST credit, opened May as though April had not happened:
    a May with Rs 1,00,000 of output tax showed Rs 1,00,000 payable IN CASH, and
    under Rule 88B(1) that cash figure is also what late interest is charged on.

WHAT IS ASSERTED
    * The reported case, to the paisa: opening Rs 36,54,961.65 and Rs 1,00,000 of
      output tax -> nothing payable, no interest, and the closing credit is the
      opening less what the month used.
    * The s.49(5) ORDER holds over the pool the opening joins: IGST credit first
      and across both local heads (Rule 88A), CGST credit towards CGST then IGST,
      SGST credit towards SGST then IGST, nothing across CGST<->SGST, cess only
      against cess.
    * It is an INPUT, not a rewrite of Table 4: 4(C) and the payload's `itc_net`
      are the same with and without an opening balance.
    * Nil opening is exactly what every caller computed before — a matrix.
    * The invariants: available - consumed == carried == the sum of the closings,
      for any opening at all, and credit is never spent twice.
    * Where the opening comes from (recorded > previous return > not recorded),
      what is said when it is not KNOWN, and that two saved returns CHAIN —
      month two opens with month one's closing, found by an exact date.
    * A balance that cannot be a balance is refused; a statement that is not
      whole is refused, so a missing head is never read as nil.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.gst_credit_ledger as router
import routers.purchase_bills as pb
import routers.sales_invoices as si
import services.gst_credit_ledger_service as svc
import services.gst_return_service as grs
from domain.gst import credit_ledger as cl
from domain.gst.credit_ledger import CreditBalance, CreditLedgerError
from domain.gst.gstr3b_computer import (
    PurchaseTransaction, SalesTransaction, compute_gstr3b,
)
from tests.test_gst_return_reconciliation import (
    CALLER, FIRM, GSTIN, _issue_invoice, _receive_bill, _setup,
)

CLI = "CLI"


def sale(igst=0, cgst=0, sgst=0, cess=0):
    return SalesTransaction(
        transaction_type="sales_invoice", taxable_amount_paise=igst + cgst + sgst + cess,
        cgst_paise=cgst, sgst_paise=sgst, igst_paise=igst, cess_paise=cess,
        supply_type="taxable", is_reverse_charge=False)


def purchase(igst=0, cgst=0, sgst=0, cess=0):
    return PurchaseTransaction(
        taxable_amount_paise=igst + cgst + sgst + cess, cgst_paise=cgst,
        sgst_paise=sgst, igst_paise=igst, cess_paise=cess, is_reverse_charge=False)


# ── The reported case ───────────────────────────────────────────────────────

APEX_OPENING = 365496165          # Rs 36,54,961.65 — April 2026's closing IGST credit


def test_a_36_lakh_opening_covers_a_one_lakh_liability_in_full():
    r = compute_gstr3b([sale(igst=100000)], [], [],
                       opening_credit=CreditBalance(igst_paise=APEX_OPENING))
    assert r.net_igst == 0
    assert r.cash_payable_paise == 0
    # What the month used is the liability, and what is left is the rest.
    assert r.itc_consumed_paise == 100000
    assert r.closing_igst == APEX_OPENING - 100000
    assert r.itc_carried_forward_paise == APEX_OPENING - 100000
    # Nothing was availed in the period: 4(C) is nil, the credit is all opening.
    assert r.itc_net_igst == 0
    assert r.itc_available_paise == APEX_OPENING


def test_without_the_opening_the_same_month_pays_cash():
    """The premise: this is the defect the opening balance removes."""
    r = compute_gstr3b([sale(igst=100000)], [], [])
    assert r.cash_payable_paise == 100000
    assert r.closing_igst == 0


def test_cash_interest_is_charged_only_on_what_the_credit_did_not_cover():
    """Rule 88B(1): interest runs only on tax paid by debiting the CASH ledger.
    A late return whose liability the opening credit discharged owes none."""
    late = date(2026, 6, 1)
    with_opening = compute_gstr3b(
        [sale(igst=100000)], [], [],
        opening_credit=CreditBalance(igst_paise=APEX_OPENING))
    without = compute_gstr3b([sale(igst=100000)], [], [])
    assert with_opening.as_gstn_payload(GSTIN, "042026", filed_on=late)[
        "intr_ltfee"]["intr_details"] == {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    assert without.as_gstn_payload(GSTIN, "042026", filed_on=late)[
        "intr_ltfee"]["intr_details"]["iamt"] > 0, (
        "premise: with no opening the same late return DOES carry interest")


def test_a_partial_opening_leaves_only_the_shortfall_for_cash_and_interest():
    late = date(2026, 6, 1)
    r = compute_gstr3b([sale(igst=100000)], [], [],
                       opening_credit=CreditBalance(igst_paise=60000))
    assert r.cash_payable_igst == 40000
    assert r.closing_igst == 0
    full = compute_gstr3b([sale(igst=100000)], [], [])
    part = r.as_gstn_payload(GSTIN, "042026", filed_on=late)["intr_ltfee"]["intr_details"]["iamt"]
    whole = full.as_gstn_payload(GSTIN, "042026", filed_on=late)["intr_ltfee"]["intr_details"]["iamt"]
    assert 0 < part < whole


# ── The s.49(5) order holds over the pool ───────────────────────────────────

def test_an_opening_igst_credit_pays_igst_then_both_local_heads_before_any_cgst_credit():
    """Rule 88A: IGST credit is exhausted first. With CGST credit availed this
    period too, the IGST opening is what pays the local liability and the CGST
    credit is the one left over."""
    r = compute_gstr3b(
        [sale(cgst=60000, sgst=60000)], [purchase(cgst=50000)], [],
        opening_credit=CreditBalance(igst_paise=120000))
    assert r.net_cgst == 0 and r.net_sgst == 0
    assert r.closing_igst == 0, "the IGST credit is spent first, whichever return it came from"
    assert r.closing_cgst == 50000, "the CGST credit availed this period is untouched"


def test_an_opening_cgst_credit_pays_cgst_then_igst_and_never_sgst():
    r = compute_gstr3b(
        [sale(igst=30000, cgst=50000, sgst=40000)], [], [],
        opening_credit=CreditBalance(cgst_paise=100000))
    # CGST credit: 50,000 to CGST (s.49(5)(b)), then the remaining 50,000 to IGST
    # (30,000). It is NEVER used for SGST (s.49(5)(f)).
    assert r.net_cgst == 0 and r.net_igst == 0
    assert r.net_sgst == 40000, "CGST credit cannot pay SGST"
    assert r.closing_cgst == 20000


def test_an_opening_sgst_credit_pays_sgst_then_igst_and_never_cgst():
    r = compute_gstr3b(
        [sale(igst=30000, cgst=40000, sgst=50000)], [], [],
        opening_credit=CreditBalance(sgst_paise=100000))
    assert r.net_sgst == 0 and r.net_igst == 0
    assert r.net_cgst == 40000, "SGST credit cannot pay CGST"
    assert r.closing_sgst == 20000


def test_an_opening_cess_credit_pays_cess_and_nothing_else():
    r = compute_gstr3b([sale(igst=100000, cess=5000)], [], [],
                       opening_credit=CreditBalance(cess_paise=8000))
    assert r.net_cess == 0 and r.closing_cess == 3000
    assert r.net_igst == 100000, "cess credit may not pay GST (GST Compensation Act s.11(2))"
    # And GST credit never pays cess.
    other = compute_gstr3b([sale(igst=100000, cess=5000)], [], [],
                           opening_credit=CreditBalance(igst_paise=900000))
    assert other.net_cess == 5000
    assert other.closing_igst == 900000 - 100000


def test_reverse_charge_tax_is_still_cash_whatever_the_opening_balance():
    """s.49(4) with s.2(82): the ledger pays OUTPUT tax only. An opening balance
    must not become a way of discharging tax the Act says is paid in cash."""
    rcm = PurchaseTransaction(
        taxable_amount_paise=100000, cgst_paise=9000, sgst_paise=9000,
        igst_paise=0, cess_paise=0, is_reverse_charge=True)
    r = compute_gstr3b([], [rcm], [], opening_credit=CreditBalance(
        igst_paise=10_00_000, cgst_paise=10_00_000, sgst_paise=10_00_000))
    assert r.rcm_cash_paise == 18000
    assert r.cash_payable_paise == 18000


# ── It is an input, not a rewrite of Table 4 ────────────────────────────────

def test_the_opening_balance_never_appears_in_table_4():
    a = compute_gstr3b([sale(igst=100000)], [purchase(igst=20000)], [])
    b = compute_gstr3b([sale(igst=100000)], [purchase(igst=20000)], [],
                       opening_credit=CreditBalance(igst_paise=APEX_OPENING))
    assert (a.itc_net_igst, a.itc_avail_igst) == (b.itc_net_igst, b.itc_avail_igst)
    pa, pb_ = a.as_gstn_payload(GSTIN, "042026"), b.as_gstn_payload(GSTIN, "042026")
    assert pa["itc_elg"] == pb_["itc_elg"], (
        "Table 4 declares what THIS return availed; last month's credit is not on this form")
    assert pa["sup_details"] == pb_["sup_details"]


# ── Nil opening is exactly what every caller computed before ────────────────

MATRIX = [
    ([], []),
    ([sale(igst=100000)], []),
    ([], [purchase(igst=180000, cgst=9000, sgst=9000)]),
    ([sale(igst=900000, cgst=10000, sgst=10000)], [purchase(igst=100000, cgst=50000, sgst=50000)]),
    ([sale(cgst=500000, sgst=500000, cess=7000)], [purchase(igst=900000, cess=3000)]),
    ([sale(igst=123134840, cgst=27315779, sgst=27315815)],
     [purchase(igst=372087107, cgst=85587728, sgst=85587764)]),
]


@pytest.mark.parametrize("sales,purchases", MATRIX)
def test_a_nil_or_absent_opening_is_what_every_caller_computed_before(sales, purchases):
    absent = compute_gstr3b(sales, purchases, [])
    none = compute_gstr3b(sales, purchases, [], opening_credit=None)
    nil = compute_gstr3b(sales, purchases, [], opening_credit=CreditBalance())
    for other in (none, nil):
        for f in ("net_igst", "net_cgst", "net_sgst", "net_cess", "closing_igst",
                  "closing_cgst", "closing_sgst", "closing_cess"):
            assert getattr(other, f) == getattr(absent, f), f
        assert other.cash_payable_paise == absent.cash_payable_paise
        assert other.itc_available_paise == absent.itc_available_paise
    assert absent.opening_credit_paise == 0


# ── The invariants ──────────────────────────────────────────────────────────

OPENINGS = [
    CreditBalance(),
    CreditBalance(igst_paise=APEX_OPENING),
    CreditBalance(cgst_paise=70000, sgst_paise=30000),
    CreditBalance(igst_paise=5, cgst_paise=3, sgst_paise=1, cess_paise=9),
    CreditBalance(igst_paise=10**9, cgst_paise=10**9, sgst_paise=10**9, cess_paise=10**9),
]


@pytest.mark.parametrize("opening", OPENINGS)
@pytest.mark.parametrize("sales,purchases", MATRIX)
def test_available_less_consumed_is_carried_and_carried_is_the_sum_of_the_closings(
        sales, purchases, opening):
    r = compute_gstr3b(sales, purchases, [], opening_credit=opening)
    assert r.itc_available_paise - r.itc_consumed_paise - r.itc_carried_forward_paise == 0
    assert r.itc_carried_forward_paise == r.closing_credit_paise, (
        "the carry-forward and the per-head closings are two views of one set-off")
    for head in ("igst", "cgst", "sgst", "cess"):
        assert getattr(r, f"closing_{head}") >= 0, "a ledger is never overdrawn"
    assert r.opening_credit_paise == opening.total_paise


@pytest.mark.parametrize("opening", OPENINGS)
@pytest.mark.parametrize("sales,purchases", MATRIX)
def test_credit_is_never_spent_twice(sales, purchases, opening):
    """Everything the ledger held is either still in it or paid a liability."""
    r = compute_gstr3b(sales, purchases, [], opening_credit=opening)
    held = r.itc_net_igst + r.itc_net_cgst + r.itc_net_sgst + r.itc_net_cess + opening.total_paise
    assert r.itc_consumed_paise + r.closing_credit_paise == held
    owed = (r.liability_igst + r.liability_cgst + r.liability_sgst + r.liability_cess)
    assert owed - r.itc_consumed_paise == r.net_igst + r.net_cgst + r.net_sgst + r.net_cess


# ── The balance as a value ──────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [-1, 1.5, "100", None, True])
def test_a_balance_that_cannot_be_a_balance_is_refused(bad):
    with pytest.raises(CreditLedgerError):
        CreditBalance(igst_paise=bad)


def test_a_negative_balance_is_refused_in_words_that_say_what_a_negative_would_be():
    with pytest.raises(CreditLedgerError, match="demand"):
        CreditBalance(cgst_paise=-100)


def test_columns_are_read_only_when_all_four_are_there():
    row = {"credit_closing_igst_paise": 5, "credit_closing_cgst_paise": 6,
           "credit_closing_sgst_paise": 7, "credit_closing_cess_paise": 8}
    assert CreditBalance.from_columns(row, "credit_closing") == CreditBalance(5, 6, 7, 8)
    assert CreditBalance.from_columns({**row, "credit_closing_cess_paise": None},
                                      "credit_closing") is None, (
        "a missing head is not a nil head")
    assert CreditBalance.from_columns({}, "credit_closing") is None


# ── Where the opening comes from ────────────────────────────────────────────

def _prev(total=APEX_OPENING, status="submitted", period="042026"):
    return cl.PreviousClosing(balance=CreditBalance(igst_paise=total), period=period,
                              status=status, as_of="2026-04-30")


def _rec(total=1000):
    return cl.RecordedOpening(balance=CreditBalance(igst_paise=total), note="portal 1 May")


def test_a_recorded_balance_beats_the_chain_and_the_difference_is_reported():
    o = cl.resolve_opening(window_start="2026-05-01", previous=_prev(), recorded=_rec(1000))
    assert o.source == cl.SOURCE_RECORDED and o.known
    assert o.balance.igst_paise == 1000
    assert o.recorded_minus_chain["igst_paise"] == 1000 - APEX_OPENING
    assert any("April 2026" in s and "recorded figure is used" in s for s in o.sentences)
    assert o.label == "Recorded from the portal"


def test_a_recorded_balance_that_agrees_with_the_chain_reports_no_difference():
    o = cl.resolve_opening(window_start="2026-05-01", previous=_prev(1000), recorded=_rec(1000))
    assert o.source == cl.SOURCE_RECORDED
    assert o.recorded_minus_chain is None and o.sentences == ()


def test_the_chain_is_used_when_nothing_is_recorded():
    o = cl.resolve_opening(window_start="2026-05-01", previous=_prev(), recorded=None)
    assert o.source == cl.SOURCE_PREVIOUS_RETURN and o.known
    assert o.balance.igst_paise == APEX_OPENING
    assert o.sentences == (), "a FILED previous return is a settled opening"
    assert o.label == "Carried from the April 2026 return"


def test_an_unfiled_previous_return_makes_the_chained_opening_provisional_in_words():
    o = cl.resolve_opening(window_start="2026-05-01", previous=_prev(status="draft"),
                           recorded=None)
    assert o.source == cl.SOURCE_PREVIOUS_RETURN
    assert len(o.sentences) == 1 and "not marked as filed" in o.sentences[0]


def test_no_opening_anywhere_is_NOT_KNOWN_and_says_so_rather_than_reading_as_nil():
    o = cl.resolve_opening(window_start="2026-05-01", previous=None, recorded=None)
    assert o.source == cl.SOURCE_NOT_RECORDED
    assert o.known is False
    assert o.balance.is_nil, "the arithmetic assumes nil"
    assert o.sentences == (cl.NOT_RECORDED_SENTENCE,)
    assert "NOTHING" in cl.NOT_RECORDED_SENTENCE and "cannot be lower" in cl.NOT_RECORDED_SENTENCE
    assert o.as_dict()["known"] is False


def test_unreadable_is_a_different_state_from_not_recorded():
    a = cl.resolve_opening(window_start="2026-05-01", previous=None, recorded=None)
    b = cl.unreadable("2026-05-01")
    assert b.source == cl.SOURCE_UNREADABLE and b.known is False
    assert a.sentences != b.sentences, "one sends a CA to key a balance, the other to compute again"


def test_a_keyed_nil_is_a_known_nil_not_an_unknown_one():
    o = cl.resolve_opening(window_start="2026-05-01", previous=None,
                           recorded=cl.RecordedOpening(balance=CreditBalance()))
    assert o.known is True and o.balance.is_nil


# ── The statement a saved return carries ────────────────────────────────────

def _block(opening=CreditBalance(igst_paise=500), closing=CreditBalance(igst_paise=300),
           source=cl.SOURCE_RECORDED, as_of="2026-04-30"):
    o = cl.OpeningCredit(balance=opening, source=source, window_start="2026-04-01")
    return cl.ledger_block(o, closing=closing, window_end=as_of)


def test_a_statement_becomes_ten_columns_and_round_trips_through_the_chain_reader():
    cols = cl.statement_columns(_block())
    assert set(cols) == {
        "credit_opening_igst_paise", "credit_opening_cgst_paise",
        "credit_opening_sgst_paise", "credit_opening_cess_paise",
        "credit_closing_igst_paise", "credit_closing_cgst_paise",
        "credit_closing_sgst_paise", "credit_closing_cess_paise",
        "credit_closing_as_of", "credit_opening_source"}
    assert CreditBalance.from_columns(cols, "credit_closing") == CreditBalance(igst_paise=300)
    assert CreditBalance.from_columns(cols, "credit_opening") == CreditBalance(igst_paise=500)
    assert cols["credit_closing_as_of"] == "2026-04-30"


@pytest.mark.parametrize("mutate", [
    lambda b: None,
    lambda b: {**b, "opening": None},
    lambda b: {**b, "closing": {"igst_paise": 1}},                       # three heads missing
    lambda b: {**b, "opening": {**b["opening"], "source": "invented"}},
    lambda b: {**b, "closing_as_of": "30/04/2026"},
    lambda b: {**b, "closing": {**b["closing"], "cess_paise": -1}},
])
def test_a_statement_that_is_not_whole_is_refused(mutate):
    """A missing head read as nil would record a closing nobody computed, and the
    next return would open with it."""
    with pytest.raises(CreditLedgerError):
        cl.statement_columns(mutate(_block()))


# ── Chained returns, through the real from-books build ──────────────────────

def _save(db, out, *, status="draft", gstin=GSTIN, period=None):
    """What a save stores: the credit columns from the block the compute served."""
    row = {"id": f"R-{out['period']}-{gstin}", "firm_id": FIRM, "client_id": CLI,
           "gstin": gstin, "period": period or out["period"], "status": status}
    row.update(cl.statement_columns(out["credit_ledger"]))
    db.seed("gstr3b_returns", row)
    return row


def test_month_two_opens_with_month_ones_closing(monkeypatch):
    db = _setup(monkeypatch)
    _receive_bill(db, "B-JUN", rate=5_00000, date="2025-06-12")        # credit 45,000 + 45,000

    june = grs.gstr3b_from_books(db, FIRM, CLI, "062025", GSTIN)
    assert june["credit_ledger"]["opening"]["source"] == "not_recorded"
    assert june["credit_ledger"]["closing"]["cgst_paise"] == 45000
    assert june["credit_ledger"]["closing"]["sgst_paise"] == 45000
    assert june["credit_ledger"]["closing_as_of"] == "2025-06-30"
    assert june["itc_carried_forward_paise"] == 90000
    _save(db, june, status="submitted")

    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000,
                   date="2025-07-10")                                  # liability 90,000 + 90,000
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    op = july["credit_ledger"]["opening"]
    assert op["source"] == "previous_return" and op["known"] is True
    assert op["balance"]["cgst_paise"] == 45000 and op["balance"]["sgst_paise"] == 45000
    assert op["label"] == "Carried from the June 2025 return"
    # June's credit pays half of July's tax; the rest is cash — and without the
    # chain the whole 1,80,000 would have been.
    assert july["cash_payable_paise"] == 90000
    assert july["credit_ledger"]["closing"]["total_paise"] == 0
    assert july["itc_carried_forward_paise"] == 0


def test_the_same_month_without_a_saved_predecessor_pays_the_whole_amount(monkeypatch):
    """The premise of the chain test above: with no saved June, July is cash."""
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    assert july["credit_ledger"]["opening"]["known"] is False
    assert july["cash_payable_paise"] == 180000


def test_a_balance_keyed_from_the_portal_beats_the_chain(monkeypatch):
    db = _setup(monkeypatch)
    _receive_bill(db, "B-JUN", rate=5_00000, date="2025-06-12")
    _save(db, grs.gstr3b_from_books(db, FIRM, CLI, "062025", GSTIN))
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")

    svc.record_opening(db, firm_id=FIRM, client_id=CLI, gstin=GSTIN, window_start="2025-07-01",
                       balance=CreditBalance(cgst_paise=90000, sgst_paise=90000),
                       note="Electronic Credit Ledger, 1 July 2025", recorded_by="u-int")
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    op = july["credit_ledger"]["opening"]
    assert op["source"] == "recorded"
    assert op["recorded_minus_chain"] == {"igst_paise": 0, "cgst_paise": 45000,
                                          "sgst_paise": 45000, "cess_paise": 0}
    assert july["cash_payable_paise"] == 0, "the portal's balance covers the whole month"


def test_the_first_period_a_client_has_here_can_be_opened_with_a_keyed_balance(monkeypatch):
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")
    svc.record_opening(db, firm_id=FIRM, client_id=CLI, gstin=GSTIN, window_start="2025-07-01",
                       balance=CreditBalance(igst_paise=APEX_OPENING), note=None, recorded_by=None)
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    assert july["credit_ledger"]["opening"]["source"] == "recorded"
    assert july["cash_payable_paise"] == 0
    assert july["credit_ledger"]["closing"]["igst_paise"] == APEX_OPENING - 180000


def test_a_gap_in_the_chain_is_not_chained_across(monkeypatch):
    """The lookup is the EXACT day before the window. A saved June does not open
    August: July's return is missing and nobody can say what it did to the ledger."""
    db = _setup(monkeypatch)
    _receive_bill(db, "B-JUN", rate=5_00000, date="2025-06-12")
    _save(db, grs.gstr3b_from_books(db, FIRM, CLI, "062025", GSTIN))
    _issue_invoice(db, "INV-AUG", taxable=10_00000, cgst=90000, sgst=90000, date="2025-08-10")
    aug = grs.gstr3b_from_books(db, FIRM, CLI, "082025", GSTIN)
    assert aug["credit_ledger"]["opening"]["source"] == "not_recorded"
    assert aug["cash_payable_paise"] == 180000


def test_another_registrations_return_is_not_chained(monkeypatch):
    """The ledger is per GSTIN (CGST s.49(1))."""
    db = _setup(monkeypatch)
    _receive_bill(db, "B-JUN", rate=5_00000, date="2025-06-12")
    june = grs.gstr3b_from_books(db, FIRM, CLI, "062025", GSTIN)
    _save(db, june, gstin="29AAAAA0000A1Z0")             # somebody else's registration
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    assert july["credit_ledger"]["opening"]["source"] == "not_recorded"


def test_a_return_saved_before_closings_were_recorded_is_not_chained(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("gstr3b_returns", {"id": "OLD", "firm_id": FIRM, "client_id": CLI, "gstin": GSTIN,
                               "period": "062025", "status": "submitted",
                               "credit_closing_as_of": None})
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    assert july["credit_ledger"]["opening"]["source"] == "not_recorded", (
        "NULL is 'nobody recorded this', never a nil closing")


def test_a_draft_predecessor_chains_but_says_it_is_provisional(monkeypatch):
    db = _setup(monkeypatch)
    _receive_bill(db, "B-JUN", rate=5_00000, date="2025-06-12")
    _save(db, grs.gstr3b_from_books(db, FIRM, CLI, "062025", GSTIN), status="draft")
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    op = july["credit_ledger"]["opening"]
    assert op["source"] == "previous_return"
    assert op["chain"]["is_filed"] is False
    assert any("not marked as filed" in s for s in op["sentences"])


def test_a_failed_read_is_unreadable_not_a_clean_nil(monkeypatch):
    db = _setup(monkeypatch)
    _issue_invoice(db, "INV-JUL", taxable=10_00000, cgst=90000, sgst=90000, date="2025-07-10")

    def boom(*a, **k):
        raise RuntimeError("PostgREST is down")
    monkeypatch.setattr(svc, "previous_closing", boom)
    july = grs.gstr3b_from_books(db, FIRM, CLI, "072025", GSTIN)
    op = july["credit_ledger"]["opening"]
    assert op["source"] == "unreadable" and op["known"] is False
    assert cl.UNREADABLE_SENTENCE in op["sentences"]
    assert july["cash_payable_paise"] == 180000, "assumed nil: the safe direction"


def test_a_quarterly_registration_chains_by_window_end_not_by_month(monkeypatch):
    """A QRMP quarter's return ends on the quarter's last day, and the next
    quarter opens with it — found by that exact date."""
    db = _setup(monkeypatch)
    db.seed("gstr3b_returns", {
        "id": "Q1", "firm_id": FIRM, "client_id": CLI, "gstin": GSTIN, "period": "042025",
        "status": "submitted", "credit_closing_igst_paise": 70000,
        "credit_closing_cgst_paise": 0, "credit_closing_sgst_paise": 0,
        "credit_closing_cess_paise": 0, "credit_closing_as_of": "2025-06-30"})
    prior = svc.previous_closing(db, FIRM, CLI, GSTIN, "2025-07-01")
    assert prior is not None and prior.balance.igst_paise == 70000 and prior.period == "042025"
    assert svc.previous_closing(db, FIRM, CLI, GSTIN, "2025-08-01") is None


# ── Keying a balance, through the route ─────────────────────────────────────

@pytest.fixture()
def routed(monkeypatch):
    db = _setup(monkeypatch)
    monkeypatch.setattr(router, "_db", lambda: db)
    monkeypatch.setattr(router, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(router, "log_event", lambda *a, **k: None)
    return db


def _body(**kw):
    base = dict(client_id=CLI, period="072025", igst_paise=APEX_OPENING, cgst_paise=0,
                sgst_paise=0, cess_paise=0, note="  portal, 1 July  ")
    base.update(kw)
    return router.OpeningIn(**base)


def test_putting_a_balance_stores_it_and_serves_where_it_will_apply(routed):
    res = router.put_opening(_body(), CALLER)
    assert res["success"] is True
    data = res["data"]
    assert data["opening"]["source"] == "recorded"
    assert data["opening"]["balance"]["igst_paise"] == APEX_OPENING
    assert data["opening"]["recorded"]["note"] == "portal, 1 July"
    assert data["window"]["start"] == "2025-07-01" and data["gstin"] == GSTIN
    rows = routed.rows("gst_credit_ledger_openings")
    assert len(rows) == 1 and rows[0]["window_start"] == "2025-07-01"


def test_putting_again_replaces_it_rather_than_adding_a_second(routed):
    router.put_opening(_body(), CALLER)
    router.put_opening(_body(igst_paise=111), CALLER)
    rows = routed.rows("gst_credit_ledger_openings")
    assert len(rows) == 1 and rows[0]["igst_paise"] == 111


def test_any_month_of_a_quarter_keys_the_quarters_first_day(routed):
    routed.seed("client_gst_registrations", {
        "id": "REG2", "firm_id": FIRM, "client_id": CLI, "gstin": "27AAAAA0000A1Z5",
        "state_code": "27", "registration_type": "regular", "filing_frequency": "quarterly",
        "is_active": True})
    res = router.put_opening(_body(period="052025", gstin="27AAAAA0000A1Z5"), CALLER)
    assert res["data"]["window"]["start"] == "2025-04-01"
    assert res["data"]["window"]["frequency"] == "quarterly"


def test_a_gstin_the_client_does_not_hold_is_refused_not_defaulted(routed):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        router.put_opening(_body(gstin="29BBBBB1111B1ZN"), CALLER)
    assert e.value.status_code == 422
    assert not routed.rows("gst_credit_ledger_openings")


def test_a_filed_window_refuses_to_have_its_opening_changed(routed):
    from fastapi import HTTPException
    routed.seed("gstr3b_returns", {"id": "F", "firm_id": FIRM, "client_id": CLI, "gstin": GSTIN,
                                   "period": "072025", "status": "submitted"})
    with pytest.raises(HTTPException) as e:
        router.put_opening(_body(), CALLER)
    assert e.value.status_code == 409 and "NEXT" in e.value.detail
    with pytest.raises(HTTPException) as e2:
        router.delete_opening(client_id=CLI, period="072025", gstin=None, current_user=CALLER)
    assert e2.value.status_code == 409


def test_a_negative_or_fractional_figure_is_refused_at_the_model():
    from pydantic import ValidationError
    for bad in (-1, 1.5, "100"):
        with pytest.raises(ValidationError):
            _body(igst_paise=bad)


def test_deleting_hands_the_window_back_to_the_chain_not_to_nil(routed):
    router.put_opening(_body(), CALLER)
    res = router.delete_opening(client_id=CLI, period="072025", gstin=None, current_user=CALLER)
    assert res["data"]["removed"] is True
    assert res["data"]["opening"]["source"] == "not_recorded", (
        "removing a keyed balance is not the same statement as 'the ledger was nil'")
    again = router.delete_opening(client_id=CLI, period="072025", gstin=None, current_user=CALLER)
    assert again["data"]["removed"] is False


def test_the_read_says_whether_the_return_is_already_filed(routed):
    assert router.get_opening(client_id=CLI, period="072025", gstin=None,
                              current_user=CALLER)["data"]["return_is_filed"] is False
    routed.seed("gstr3b_returns", {"id": "F", "firm_id": FIRM, "client_id": CLI, "gstin": GSTIN,
                                   "period": "072025", "status": "submitted"})
    assert router.get_opening(client_id=CLI, period="072025", gstin=None,
                              current_user=CALLER)["data"]["return_is_filed"] is True


def test_the_write_routes_need_gst_compute_and_the_read_needs_gst_read():
    import inspect
    src = inspect.getsource(router)
    assert src.count('rbac("gst", "compute")') == 2      # PUT and DELETE
    assert src.count('rbac("gst", "read")') == 1
    assert src.count("assert_client_access(") == 3
