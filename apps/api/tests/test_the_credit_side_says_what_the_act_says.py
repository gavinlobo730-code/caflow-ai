"""Phase 13b — two defects on the ITC side, both about credit that is not credit.

GST-19  Rule 36(4)'s cap was applied to a book figure that includes
        SELF-ASSESSED reverse-charge tax, against a portal figure that
        structurally cannot include it — so it trimmed credit on tax the client
        had already paid in cash.

PUR-04  A §17(5) blocked line's tax was still debited to GST Input, leaving a
        phantom asset on the balance sheet and a permanent, unexplainable
        difference between the ledger and the return.

Both were held latent by the same thing the September audit got wrong: GST-19
by "nothing writes gstr2a_records" (the 2B reconciliation does now), PUR-04 by
"PUR-05 keeps itc_eligible unsettable" (the purchase-bill editor sets it now).
"""
from __future__ import annotations

import pytest

from domain.gst.gstr3b_computer import (
    compute_gstr3b, PurchaseTransaction, GSTR2ARecord, SalesTransaction,
)

P = 1  # paise are the unit; the figures below are written in paise


def _rcm(igst=0, cgst=0, sgst=0, taxable=100000):
    return PurchaseTransaction(taxable, cgst, sgst, igst, 0, True)


def _b2b(igst=0, cgst=0, sgst=0, taxable=100000):
    return PurchaseTransaction(taxable, cgst, sgst, igst, 0, False)


# ── GST-19 ───────────────────────────────────────────────────────────────────
#
# CGST Rule 36(4): "Input tax credit to be availed by a registered person in
# respect of invoices or debit notes, the details of which are required to be
# furnished by the supplier under sub-section (1) of section 37 ...". On a
# §9(3)/(4) supply the supplier charges and furnishes nothing; the recipient
# issues a §31(3)(f) self-invoice and pays the tax in cash, and Rule 36(1)(b)
# makes that the document — "subject to the payment of tax". A document the
# recipient issued to itself has no supplier to have furnished it.

def test_reverse_charge_credit_survives_a_cap_that_bites_on_the_b2b_credit():
    """The measured case. One ₹1,00,000 bill with ₹18,000 IGST, matched in 2B,
    plus a reverse-charge supply carrying ₹50,000 of self-assessed IGST.

    Before this fix: book ₹68,000 capped to the 2B's ₹18,000 — ₹50,000 of
    credit withheld on tax the client had already remitted.
    """
    r = compute_gstr3b([], [_b2b(igst=18000), _rcm(igst=50000, taxable=277778)],
                       [GSTR2ARecord(0, 0, 18000)])
    assert r.itc_igst == 68000
    assert r.itc_capped_by_2a is False


def test_the_cap_still_bites_on_the_supplier_filed_half():
    """The carve-out must not become an amnesty. Same two purchases, but the
    b2b bill is NOT in the 2B: §16(2)(aa) withholds that ₹18,000 and the
    ₹50,000 of self-assessed credit stands."""
    r = compute_gstr3b([], [_b2b(igst=18000), _rcm(igst=50000, taxable=277778)],
                       [], have_2b=True)
    assert r.itc_igst == 50000
    assert r.itc_capped_by_2a is True


def test_the_reverse_charge_credit_is_not_lent_to_the_unmatched_b2b_credit():
    """Why this is cap-then-add rather than an inflated numerator. A month with
    ₹50,000 of RCM and an unfiled ₹18,000 b2b bill owes exactly ₹50,000 of
    credit — not ₹68,000, which is what capping the combined figure against a
    combined numerator would allow."""
    r = compute_gstr3b([], [_b2b(igst=18000), _rcm(igst=50000, taxable=277778)],
                       [], have_2b=True)
    assert r.itc_igst == 50000, "the RCM figure was lent to the unmatched b2b credit"


def test_an_all_reverse_charge_month_is_never_capped():
    """Nothing in it is a §37 document, so there is nothing for the sub-rule to
    reach. A 2B on file showing nil does not change that."""
    r = compute_gstr3b([], [_rcm(cgst=9000, sgst=9000)], [], have_2b=True)
    assert r.itc_cgst == 9000 and r.itc_sgst == 9000
    assert r.itc_capped_by_2a is False


def test_an_ordinary_month_with_no_reverse_charge_caps_exactly_as_before():
    """The control. Nothing about the b2b path changes."""
    r = compute_gstr3b([], [_b2b(cgst=9000, sgst=9000)],
                       [GSTR2ARecord(1000, 1000, 0)])
    assert r.itc_cgst == 1000 and r.itc_sgst == 1000
    assert r.itc_capped_by_2a is True


def test_each_head_carves_out_independently():
    """An inter-state reverse charge lands on IGST and an intra-state one on
    CGST/SGST. A carve-out applied to only some heads would pass a
    single-direction test."""
    r = compute_gstr3b(
        [], [_rcm(igst=50000, taxable=277778), _rcm(cgst=9000, sgst=9000),
             _b2b(igst=18000), _b2b(cgst=9000, sgst=9000)],
        [], have_2b=True)
    assert (r.itc_igst, r.itc_cgst, r.itc_sgst) == (50000, 9000, 9000)


def test_a_blocked_reverse_charge_line_is_still_blocked():
    """§17(5) and Rule 36(4) are different bars and the carve-out only lifts
    the second. Blocked tax is netted out of the book figure before any of this
    (gstr3b_computer nets `ineligible_*` into `book_*`), so a blocked RCM line
    gets no credit at all."""
    blocked = PurchaseTransaction(277778, 0, 0, 50000, 0, True,
                                  ineligible_igst_paise=50000)
    r = compute_gstr3b([], [blocked], [], have_2b=True)
    assert r.itc_igst == 0
    assert r.itc_self_assessed_igst == 0


def test_the_self_assessed_figure_is_reported_so_a_reader_can_see_why():
    """A CA who sees book ₹68,000 against a 2A of ₹18,000 and NO cap applied
    must be able to see the reason without re-deriving it."""
    r = compute_gstr3b([], [_b2b(igst=18000), _rcm(igst=50000, taxable=277778)],
                       [GSTR2ARecord(0, 0, 18000)])
    assert r.itc_book_igst == 68000
    assert r.itc_2a_igst == 18000
    assert r.itc_self_assessed_igst == 50000
    assert r.itc_book_igst - r.itc_self_assessed_igst == r.itc_2a_igst


def test_an_import_stays_inside_the_cap():
    """Deliberately NOT carved out with reverse charge. IGST on a bill of entry
    IS communicated — GSTR-2B carries it in impg/impgsez — so it is matched
    credit like any other. It is booked as an ordinary IGST purchase, not as
    reverse charge, so it caps."""
    r = compute_gstr3b([], [_b2b(igst=18000)], [], have_2b=True)
    assert r.itc_igst == 0 and r.itc_capped_by_2a is True


def test_table_4a_still_sums_after_the_carve_out():
    """4(C) = 4(A) − 4(B) is an identity on the face of the return. ISRC is
    capped at what is available so the five rows sum; with the carve-out the
    RCM figure is always available, so ISRC is never trimmed."""
    r = compute_gstr3b([SalesTransaction("invoice", 1000000, 0, 90000, 90000, 0, "taxable", False)],
                       [_b2b(cgst=45000, sgst=45000), _rcm(cgst=9000, sgst=9000)],
                       [GSTR2ARecord(1000, 1000, 0)])
    t4 = r.as_gstn_payload("27AAAAA0000A1Z2", "062026")["itc_elg"]
    for head in ("iamt", "camt", "samt", "csamt"):
        assert (sum(x[head] for x in t4["itc_avl"])
                - sum(x[head] for x in t4["itc_rev"])) == t4["itc_net"][head], head


# ── PUR-04 ───────────────────────────────────────────────────────────────────
#
# CGST Act §17(5) bars the credit outright, so the tax on a blocked line will
# never be set off and is never recoverable — it is part of what the supply
# cost. ICAI's Guidance Note on Accounting for GST says so in terms: tax not
# eligible for input credit is added to the cost of the related goods or
# services.

def _post_bill(bill: dict, line_rows: list[dict]) -> list[dict]:
    """Run the purchase-bill posting and return the journal lines it built.

    The kernel's `_create_journal` is intercepted rather than run, because what
    is under test is which account each amount lands on — not the kernel, which
    has its own tests and its own balance assertion.
    """
    import unittest.mock as m
    import services.phase2_journal_service as mod

    svc = mod.phase2_journal_service
    captured: dict = {}

    class _DB:
        def table(self, name):
            assert name == "purchase_bill_lines", name
            return _Q()

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": line_rows})()

    orig_find, orig_create, orig_mock = (
        svc._find_account, svc._create_journal, mod._USE_MOCK)
    mod._USE_MOCK = False
    svc._find_account = lambda db, f, c, pattern, system_key=None: {
        "%GST Input%": "gst-input", "%Trade Payable%": "ap",
        "%TDS Payable%": "tds", "%Purchase%": "purchases",
        "%Expense%": "purchases",
    }[pattern]
    svc._create_journal = lambda **kw: (captured.update(kw), "J1")[1]
    try:
        with m.patch("core.supabase_client.get_supabase", return_value=_DB()):
            svc.journal_for_purchase_bill(bill, "f1", "c1")
    finally:
        svc._find_account, svc._create_journal = orig_find, orig_create
        mod._USE_MOCK = orig_mock
    return captured["lines"]


def _debits(lines: list[dict]) -> dict:
    out: dict = {}
    for ln in lines:
        if ln.get("debit_paise"):
            out[ln["account_id"]] = out.get(ln["account_id"], 0) + ln["debit_paise"]
    return out


def _bill(**over) -> dict:
    b = {"id": "b1", "bill_no": "PB-1", "bill_date": "2026-06-10",
         "taxable_amount_paise": 100000, "cgst_paise": 9000, "sgst_paise": 9000,
         "igst_paise": 0, "total_paise": 118000, "net_payable_paise": 118000,
         "ineligible_itc_cgst_paise": 0, "ineligible_itc_sgst_paise": 0,
         "ineligible_itc_igst_paise": 0}
    b.update(over)
    return b


def test_an_ordinary_bill_still_debits_the_whole_tax_to_gst_input():
    """The control. Nothing changes for a bill with no blocked line."""
    debits = _debits(_post_bill(
        _bill(), [{"expense_account_id": "office", "taxable_amount_paise": 100000,
                   "itc_eligible": True, "cgst_paise": 9000, "sgst_paise": 9000,
                   "igst_paise": 0}]))
    assert debits == {"office": 100000, "gst-input": 18000}


def test_a_blocked_line_puts_its_tax_on_the_expense_not_on_gst_input():
    """THE DEFECT. A club membership is §17(5)(b): the ₹18,000 will never be
    set off, so carrying it as Input GST is a phantom asset and a permanent
    difference between the ledger and the return — `gstr3b_computer` nets it
    out of book ITC while the GL called it recoverable for ever."""
    debits = _debits(_post_bill(
        _bill(ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000),
        [{"expense_account_id": "club", "taxable_amount_paise": 100000,
          "itc_eligible": False, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0}]))
    assert debits == {"club": 118000}
    assert "gst-input" not in debits


def test_the_blocked_tax_lands_on_the_blocked_line_s_own_account():
    """Allocated PER LINE, not pro-rata over the bill. A club membership's
    blocked tax belongs on the club membership, not spread across the office
    supplies on the same bill."""
    debits = _debits(_post_bill(
        _bill(taxable_amount_paise=200000, cgst_paise=18000, sgst_paise=18000,
              total_paise=236000, net_payable_paise=236000,
              ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000),
        [{"expense_account_id": "office", "taxable_amount_paise": 100000,
          "itc_eligible": True, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0},
         {"expense_account_id": "club", "taxable_amount_paise": 100000,
          "itc_eligible": False, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0}]))
    assert debits == {"office": 100000, "club": 118000, "gst-input": 18000}


def test_the_entry_still_balances():
    """Total debit is unchanged — only its distribution moves. The kernel
    asserts this too, and it is intercepted here, so it is asserted here."""
    lines = _post_bill(
        _bill(ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000),
        [{"expense_account_id": "club", "taxable_amount_paise": 100000,
          "itc_eligible": False, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0}])
    assert (sum(ln.get("debit_paise", 0) for ln in lines)
            == sum(ln.get("credit_paise", 0) for ln in lines) == 118000)


def test_lines_that_do_not_foot_fall_back_to_one_expense_account():
    """Where the per-line split cannot be trusted — header-only, or lines that
    disagree with the header — the blocked tax goes to the one resolved expense
    account. The total is right either way, and the alternative (leaving it on
    GST Input) is the defect."""
    debits = _debits(_post_bill(
        _bill(ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000), []))
    assert debits == {"purchases": 118000}


def test_the_header_is_the_authority_when_the_lines_disagree():
    """Migration 240 keeps the header as the lines' sum precisely so
    `gstr3b_from_books` needs no join, and the header is what the RETURN reads.
    So a disagreement means the lines cannot carry the split, not that the
    header is wrong — the total must still tie to the header."""
    debits = _debits(_post_bill(
        _bill(ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000),
        [{"expense_account_id": "office", "taxable_amount_paise": 100000,
          "itc_eligible": False, "cgst_paise": 1, "sgst_paise": 1,
          "igst_paise": 0}]))
    assert sum(debits.values()) == 118000
    assert "gst-input" not in debits


def test_the_ledger_and_the_return_now_agree_on_one_bill():
    """THE PROPERTY THE FIX IS FOR, asserted across both implementations.

    `gst_return_service` compares `books_itc` (the return's Table 4 book figure,
    which has always netted §17(5) out) against `gl["itc_paise"]` (the net debit
    on the GST Input account). Before this change a blocked line made those two
    differ by exactly the blocked tax, every period, for ever — a mismatch a CA
    could not reconcile because neither side was wrong on its own terms.

    One bill, ₹1,00,000 taxable with ₹18,000 of tax, entirely blocked: the
    ledger's GST Input movement is nil and so is the return's book ITC.
    """
    lines = _post_bill(
        _bill(ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000),
        [{"expense_account_id": "club", "taxable_amount_paise": 100000,
          "itc_eligible": False, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0}])
    gl_itc = sum(ln.get("debit_paise", 0) - ln.get("credit_paise", 0)
                 for ln in lines if ln["account_id"] == "gst-input")

    books = compute_gstr3b([], [PurchaseTransaction(
        100000, 9000, 9000, 0, 0, False,
        ineligible_cgst_paise=9000, ineligible_sgst_paise=9000)], [])
    books_itc = books.itc_book_cgst + books.itc_book_sgst + books.itc_book_igst

    assert gl_itc == books_itc == 0


def test_they_agree_on_a_bill_that_is_only_half_blocked_too():
    """The harder half: the eligible ₹18,000 must still reach GST Input and
    still be claimed, while the blocked ₹18,000 reaches neither."""
    lines = _post_bill(
        _bill(taxable_amount_paise=200000, cgst_paise=18000, sgst_paise=18000,
              total_paise=236000, net_payable_paise=236000,
              ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000),
        [{"expense_account_id": "office", "taxable_amount_paise": 100000,
          "itc_eligible": True, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0},
         {"expense_account_id": "club", "taxable_amount_paise": 100000,
          "itc_eligible": False, "cgst_paise": 9000, "sgst_paise": 9000,
          "igst_paise": 0}])
    gl_itc = sum(ln.get("debit_paise", 0) - ln.get("credit_paise", 0)
                 for ln in lines if ln["account_id"] == "gst-input")

    books = compute_gstr3b([], [PurchaseTransaction(
        200000, 18000, 18000, 0, 0, False,
        ineligible_cgst_paise=9000, ineligible_sgst_paise=9000)], [])
    books_itc = books.itc_book_cgst + books.itc_book_sgst + books.itc_book_igst

    assert gl_itc == books_itc == 18000
