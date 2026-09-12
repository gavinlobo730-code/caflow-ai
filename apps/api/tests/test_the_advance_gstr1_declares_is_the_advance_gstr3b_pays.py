"""One advance, one liability — GSTR-1 Table 11 and GSTR-3B Table 3.1(a).

WHAT WAS WRONG (GST-15)
    CGST Act §13(2) puts the time of supply for SERVICES at the earlier of
    invoice or payment, so tax on an advance received for services falls due
    when it is received, before any invoice exists. `gst_advance_service.
    table_11_sections` computes the GSTR-1 Table 11A rows for exactly that and
    `gst_return_service.gstr1_from_books` merges them into the file the CA
    uploads.

    `compute_gstr3b` had no advances input at all. So a client with
    `gst_advance_tax_applicable` ticked filed a GSTR-1 declaring a liability
    and, days later, a GSTR-3B that discharged none of it — the return that
    actually pays the tax was short by the whole of Table 11A, every month,
    with both returns internally consistent and no figure anywhere pointing at
    the difference.

    It was latent while nothing could set the client flag. That stopped being
    true when the flag got a checkbox on the client form and the receipt form
    got the three Table 11A fields, so this is live product behaviour.

WHY 11B IS SUBTRACTED
    11B is an advance received in an EARLIER period — whose tax that period's
    3.1(a) already paid — settled against an invoice raised in THIS one. That
    invoice is in `sales` and contributes its whole value to 3.1(a) again, so
    without the subtraction the same rupee is taxed twice. Adding 11A alone
    would have replaced an under-declaration with a double charge.

WHY THE LEDGER COMPARISON EXCLUDES IT
    A receipt journal is Bank Dr / Trade Receivable Cr and carries no
    output-tax leg, so the §13(2) liability is declared on the return and
    exists nowhere in the general ledger. Comparing the declared figure against
    a ledger that structurally cannot carry it would mark every advance-bearing
    client permanently unreconciled. It is held out of the comparison and NAMED
    — `reconciliation.output_gst.advance_tax_excluded_paise` — while
    `tax_liability_paise`, which is the return's liability rather than the
    ledger's movement, still carries the whole of it.

WHY THIS DRIVES REAL DOCUMENTS
    The claim is that two independently built returns agree about one receipt.
    A test that hands both sides the same number cannot see that they did not.
    So this posts a real sales invoice through routers/sales_invoices.py and
    reads BOTH returns out of gst_return_service, comparing GSTR-1's own rupee
    rows against GSTR-3B's paise.
"""
from __future__ import annotations

import pytest

import services.gst_return_service as grs
import services.gst_advance_service as adv
from domain.gst.gstr3b_computer import AdvanceTaxOnReceipts, compute_gstr3b
import tests.test_gstr3b_itc_reversal_from_books as E

FIRM, CLIENT, GSTIN = E.FIRM, "CLI", E.GSTIN
JUNE, JULY = E.JUNE, E.JULY


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    d = E._setup(monkeypatch)
    E.wire_e2e(monkeypatch, d, [grs, adv])
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Acme", "gstin": "27BBBBB1111B1Z5",
                         "state_code": "27", "is_active": True})
    return d


def _advances_on(db, on=True):
    """The client flag, as the client form writes it (migration 286)."""
    rows = db.table("clients").select("id").eq("id", CLIENT).execute().data
    assert rows, "the harness seeds the client; this update has to hit it"
    db.table("clients").update(
        {"gst_advance_tax_applicable": on}).eq("id", CLIENT).execute()


def _receipt(db, no, date, amount, *, rate=1800, pos="27", interstate=False):
    """An advance, with the three columns `receipt_service` writes on it.

    Seeded rather than posted: what the receipt PATH writes into those columns
    is pinned by test_an_advance_carries_what_table_11a_declares_it_at.py and
    test_an_advance_is_split_by_the_server_not_the_browser.py. What is under
    test here is what the two RETURNS do with them.
    """
    return db.seed("receipts", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "receipt_no": no, "receipt_date": date, "amount_paise": amount,
        "allocated_paise": 0, "unallocated_paise": amount,
        "gst_rate_bps": rate, "place_of_supply": pos,
        "is_interstate": interstate})


def _adjust(db, receipt, amount, when):
    """An allocation against an invoice — what turns 11A into 11B."""
    db.seed("receipt_allocations", {
        "receipt_id": receipt["id"], "allocated_paise": amount,
        "created_at": f"{when}T00:00:00+00:00"})


def _3b(db, period=JUNE):
    return grs.gstr3b_from_books(db, FIRM, CLIENT, period, GSTIN)


def _out(db, period=JUNE):
    return _3b(db, period)["working"]["outward"]


# ── the fixture has to actually produce a Table 11 ───────────────────────────

def test_the_fixture_really_declares_an_11a_row(db):
    """Guard. With no 11A row every assertion below compares two zeros and
    holds with the fix removed — which is how GST-15 survived a suite that
    already tested Table 11 thoroughly, one layer below GSTR-3B."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    t11 = adv.table_11_sections(db, FIRM, CLIENT, JUNE)
    assert t11["applicable"] is True
    assert t11["at"], "no Table 11A row — the rest of this file would be vacuous"
    assert t11["paise"]["at"] == {"taxable_paise": 1_00_000, "igst_paise": 0,
                                  "cgst_paise": 9_000, "sgst_paise": 9_000}


# ── 11A reaches 3.1(a) ───────────────────────────────────────────────────────

def test_an_advance_is_declared_in_table_31a(db):
    """Rs 1,180 received at 18% intra-state: Rs 1,000 taxable, Rs 90 each head.
    An advance is money the customer paid, so it is INCLUSIVE of the tax."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    o = _out(db)
    assert o["taxable_value_paise"] == 1_00_000
    assert o["taxable_cgst_paise"] == 9_000
    assert o["taxable_sgst_paise"] == 9_000
    assert o["taxable_igst_paise"] == 0


def test_an_inter_state_advance_goes_to_igst(db):
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000, pos="29", interstate=True)
    o = _out(db)
    assert o["taxable_igst_paise"] == 18_000
    assert o["taxable_cgst_paise"] == 0 and o["taxable_sgst_paise"] == 0


def test_a_goods_client_declares_no_advance(db):
    """Notification 66/2017-Central Tax removed the charge on an advance for
    GOODS — the liability arises at the invoice (§12(2) proviso). Most clients
    are this one, which is why the flag defaults off."""
    _advances_on(db, False)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    o = _out(db)
    assert o["taxable_value_paise"] == 0 and o["taxable_cgst_paise"] == 0


def test_an_advance_that_cannot_be_declared_is_not_declared(db):
    """No rate means no row in GSTR-1 Table 11A, so no tax in 3.1(a) either.
    A guessed rate is a guessed liability, and 3.1(a) is where it would be
    PAID rather than merely declared."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000, rate=None)
    assert _out(db)["taxable_cgst_paise"] == 0
    assert adv.table_11_sections(db, FIRM, CLIENT, JUNE)["gaps"], (
        "it must still be NAMED — silently dropping it is the older bug")


# ── the two returns agree, which is the whole finding ────────────────────────

def test_gstr1_and_gstr3b_declare_the_same_tax_on_one_advance(db):
    """Rupees on one side, paise on the other, one receipt underneath.

    This is GST-15 stated directly: before the fix GSTR-1's `at` section
    carried Rs 90 + Rs 90 and GSTR-3B's 3.1(a) carried nothing at all.
    """
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)

    itms = grs.gstr1_from_books(db, FIRM, CLIENT, JUNE, GSTIN)["payload"]["at"][0]["itms"]
    g1_cgst = round(sum(i.get("camt", 0) for i in itms) * 100)
    g1_sgst = round(sum(i.get("samt", 0) for i in itms) * 100)
    g1_val = round(sum(i["ad_amt"] for i in itms) * 100)

    o = _out(db)
    assert (g1_val, g1_cgst, g1_sgst) == (
        o["taxable_value_paise"], o["taxable_cgst_paise"], o["taxable_sgst_paise"])


# ── 11B, and why omitting it would be worse ──────────────────────────────────

def test_an_advance_adjusted_this_period_is_taken_back_out(db):
    """June's 3.1(a) paid the tax on this advance. July's invoice carries the
    whole value again, so July's 3.1(a) must subtract 11B or the same rupee is
    taxed twice — a double charge, which is worse than the shortfall it
    replaces."""
    _advances_on(db)
    r = _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    assert _out(db, JUNE)["taxable_cgst_paise"] == 9_000

    _adjust(db, r, 1_18_000, "2025-07-04")
    o = _out(db, JULY)
    assert o["taxable_value_paise"] == -1_00_000
    assert o["taxable_cgst_paise"] == -9_000
    assert o["taxable_sgst_paise"] == -9_000


def test_an_advance_received_and_settled_in_one_period_touches_neither(db):
    """It was invoiced before any 11A could declare it, so the invoice's own
    tax is the whole liability and Table 11 is silent both ways."""
    _advances_on(db)
    r = _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    _adjust(db, r, 1_18_000, "2025-06-20")
    o = _out(db, JUNE)
    assert o["taxable_value_paise"] == 0 and o["taxable_cgst_paise"] == 0


# ── what the screen and the challan are given ────────────────────────────────

def test_the_advance_part_of_31a_is_broken_out_for_the_screen(db):
    """`working.advances_11` — a breakdown of 3.1(a), never an addition to it.
    A figure folded into a total with no account of itself is what made this
    invisible for as long as it was."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    w = _3b(db)["working"]
    a = w["advances_11"]
    assert a["taxable_value_paise"] == 1_00_000
    assert a["cgst_paise"] == 9_000 and a["sgst_paise"] == 9_000
    assert a["igst_paise"] == 0
    for k in ("taxable_value_paise", "cgst_paise", "sgst_paise", "igst_paise"):
        assert isinstance(a[k], int), (k, a[k])   # r(paise) divides by 100
    assert "13(2)" in a["rule"]
    # It is INSIDE 3.1(a), not beside it.
    assert w["outward"]["taxable_cgst_paise"] == a["cgst_paise"]


def test_the_block_is_served_even_when_there_is_no_advance(db):
    """The screen reads it unconditionally. A key that appears only sometimes
    is a NaN on the months it does not."""
    a = _3b(db)["working"]["advances_11"]
    assert a["taxable_value_paise"] == 0 and a["igst_paise"] == 0


def test_the_challan_carries_the_advance_tax(db):
    """3.1(a) is output tax under §2(82), so the set-off spends credit on it
    and what is left is cash. A liability declared and not payable would be
    the same bug in a different place."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    out = _3b(db)
    assert out["tax_liability_paise"] == 18_000
    assert out["cash_payable_paise"] == 18_000


# ── the ledger comparison ────────────────────────────────────────────────────

def test_the_ledger_comparison_holds_the_advance_out_and_names_it(db):
    """A receipt posts no output-tax leg, so the GL has nothing to compare.
    Including it would report every advance-bearing client as permanently
    unreconciled against a difference no entry in this product can close."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    rec = _3b(db)["reconciliation"]["output_gst"]
    assert rec["advance_tax_excluded_paise"] == 18_000
    assert rec["books_paise"] == 0
    assert rec["difference_paise"] == 0
    assert rec["matched"] is True


def test_a_month_with_no_advance_names_nothing(db):
    rec = _3b(db)["reconciliation"]["output_gst"]
    assert rec["advance_tax_excluded_paise"] == 0
    assert rec["matched"] is True


def test_the_exclusion_does_not_hide_a_real_mismatch(db):
    """Guard on the guard. Holding the advance out must not turn the
    comparator off: a genuine books-vs-ledger difference still has to show."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000)
    assert _3b(db)["reconciliation"]["output_gst"]["matched"] is True

    # An output-tax credit in the ledger that no document produced — posted to
    # the real gst_cgst control account the harness seeds, because that is what
    # _gl_gst_movements reads.
    cgst = next(c["id"] for c in db.rows("chart_of_accounts")
                if c.get("system_account_key") == "gst_cgst")
    je = db.seed("journal_entries", {
        "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2025-06-15",
        "is_posted": True})
    db.seed("journal_lines", {"journal_entry_id": je["id"], "account_id": cgst,
                              "debit_paise": 0, "credit_paise": 5_000})

    rec = _3b(db)["reconciliation"]["output_gst"]
    assert rec["ledger_paise"] == 5_000
    assert rec["advance_tax_excluded_paise"] == 18_000
    assert rec["difference_paise"] == -5_000
    assert rec["matched"] is False, (
        "a real difference must survive the advance exclusion")


# ── the unit underneath ──────────────────────────────────────────────────────

def test_the_default_is_no_advances_and_changes_nothing():
    """Most clients have no Table 11 at all. `advances=None` has to leave
    3.1(a) exactly as it was, or the fix is a regression for everyone else."""
    assert compute_gstr3b([], [], []).outward_taxable_cgst == 0
    r = compute_gstr3b([], [], [], advances=None)
    assert (r.advance_taxable_value, r.advance_cgst, r.advance_sgst,
            r.advance_igst) == (0, 0, 0, 0)


def test_an_empty_table_11_is_not_applied():
    a = AdvanceTaxOnReceipts(received={}, adjusted={})
    assert a.is_empty is True
    assert compute_gstr3b([], [], [], advances=a).outward_taxable_value == 0


def test_11a_and_11b_that_cancel_are_still_empty():
    """Nothing to add, and the flag must say so rather than the arithmetic
    reaching the result and adding zero to every head."""
    same = {"taxable_paise": 1_00_000, "cgst_paise": 9_000, "sgst_paise": 9_000}
    assert AdvanceTaxOnReceipts(received=same, adjusted=same).is_empty is True


def test_the_net_is_not_clamped():
    """An adjustment larger than the period's own advances is a real fact about
    the books. A silent floor at zero would hide it behind an ordinary 3.1(a)
    and re-open the double charge from the other side."""
    a = AdvanceTaxOnReceipts(received={}, adjusted={"cgst_paise": 9_000})
    assert a.net("cgst_paise") == -9_000
    assert a.is_empty is False
    assert compute_gstr3b([], [], [], advances=a).outward_taxable_cgst == -9_000


def test_a_missing_head_reads_as_zero_not_as_an_error():
    """`table_11_sections` always sends all four, but a stored or partial
    bucket must not raise inside a return build."""
    a = AdvanceTaxOnReceipts(received={"cgst_paise": 9_000}, adjusted={})
    assert a.net("igst_paise") == 0 and a.net("cgst_paise") == 9_000


# ── the advances are not asserted into Table 3.2 ─────────────────────────────

def test_an_advance_is_not_put_in_table_32(db):
    """3.2 is "of the supplies shown in 3.1(a)" made inter-state to
    unregistered persons, composition dealers and UIN holders. A receipt
    records no recipient class, so a 3.2 bucket would assert a fact the books
    do not hold — and the portal cross-checks 3.2 against GSTR-1's B2CL/B2CS,
    which carry no advance either."""
    _advances_on(db)
    _receipt(db, "RCT-1", "2025-06-10", 1_18_000, pos="29", interstate=True)
    t32 = _3b(db)["working"]["inter_state_3_2"]
    assert t32["unregistered"] == {} and t32["composition"] == {}
    assert t32["uin"] == {}
