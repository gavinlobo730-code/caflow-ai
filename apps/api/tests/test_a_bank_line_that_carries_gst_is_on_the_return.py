"""A bank charge the CA marked as carrying GST reaches GSTR-3B (BANK-24).

WHAT WAS WRONG
    The posting drawer lets a CA say "there is 18% GST inside this Rs 590", and
    `bank_posting_service` then posts Dr Bank Charges 500 / Dr GST Input 90 /
    Cr Bank 590. That 90 is input tax credit under CGST Act s.16 and it sits in
    the GST Input ledger from that moment.

    GSTR-3B was built only from DOCUMENTS — purchase bills, the two purchase
    note types, sales invoices, the s.34 notes — and a bank charge is none of
    those. So the credit the CA had explicitly declared never reached Table
    4(A), the client under-claimed it every month, and the SAME 90 came back on
    the other side of the books-vs-ledger reconciliation as an unexplained ITC
    difference, because `_gl_gst_movements` reads the GST Input account and the
    return did not.

    Money IN is the same defect and the worse one:
    `charge_gst.build_inclusive_lines(is_credit=True)` credits GST Output for
    an outward supply received straight into the bank, so the liability was in
    the ledger and no return declared it.

WHAT THIS FILE PROVES, AND WHY IT POSTS REAL JOURNALS
    The claim is that two independently derived figures now agree — the return
    (from `bank_transactions`) and the ledger (from `journal_lines`). A test
    that hands both sides the same number cannot see that they did not. So
    every case below posts through `bank_posting_service.post` and reads the
    answer out of `gst_return_service.gstr3b_from_books`.

    THE DOCUMENT IS THE TRANSACTION, NOT THE JOURNAL. Migration 382 records the
    posted rate on `bank_transactions`; nothing here reads the tax back out of
    `journal_lines`. Sourcing it there would make that slice of the
    reconciliation compare the ledger with itself and agree by construction —
    the same reason Table 4(B) is built from documents.
"""
from __future__ import annotations

import pytest

import services.bank_posting_service as bps
import services.bank_split_service as bss
import services.gst_return_service as grs
import services.phase2_journal_service as pjs
from domain.gst import bank_charge_gst
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM, CLIENT = "FIRM-A", "CLI"
GSTIN = "27AAAAA0000A1Z2"
JUNE = "062025"
ACTOR = "u-int"


# ── harness ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [bps, bss, grs, pjs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN,
                       "financial_year_start": "2025-04-01"})
    coa = seed_standard_coa(d, FIRM, CLIENT)
    d.coa = coa
    d.seed("chart_of_accounts", {
        "id": "ACC-CHARGES", "firm_id": FIRM, "client_id": CLIENT,
        "system_account_key": None, "account_name": "Bank Charges",
        "account_type": "Expense", "is_active": True})
    d.seed("chart_of_accounts", {
        "id": "ACC-FEES", "firm_id": FIRM, "client_id": CLIENT,
        "system_account_key": None, "account_name": "Consulting Income",
        "account_type": "Income", "is_active": True})
    return d


def _txn(db, *, out: int = 0, into: int = 0, date: str = "2025-06-14",
         category: str = "Expense", description: str = "MONTHLY CHARGES"):
    return db.seed("bank_transactions", {
        "firm_id": FIRM, "client_id": CLIENT, "transaction_date": date,
        "description": description, "debit_paise": out, "credit_paise": into,
        "category": category, "match_status": "unmatched",
    })


def _post(db, txn, *, rate=None, interstate=False, counter="ACC-CHARGES"):
    return bps.bank_posting_service.post(
        db, FIRM, txn["id"], bank_account_id=db.coa["bank"],
        account_id=counter, gst_rate_bps=rate, is_interstate=interstate,
        actor_id=ACTOR)


def _return(db):
    return grs.gstr3b_from_books(db, FIRM, CLIENT, JUNE, GSTIN)


def _gst_input_balance(db) -> int:
    """Net debit on the GST Input account, straight off the journal lines —
    the LEDGER side, read independently of anything the return does."""
    acc = db.coa["gst_input"]
    return sum(int(l.get("debit_paise") or 0) - int(l.get("credit_paise") or 0)
               for l in db.rows("journal_lines") if l.get("account_id") == acc)


# ── the charge reaches Table 4(A), and the two sides agree ───────────────────

def test_a_bank_charge_with_gst_is_claimed_in_table_4a(db):
    """Rs 590 at 18% is Rs 500 of expense and Rs 90 of credit — s.16 gives the
    credit on an input service received in the course of business."""
    _post(db, _txn(db, out=59_000), rate=1800)
    r = _return(db)
    w = r["working"]["itc"]
    assert w["cgst_paise"] == 4_500
    assert w["sgst_paise"] == 4_500
    assert r["reconciliation"]["bank_lines"]["itc_paise"] == 9_000
    assert r["reconciliation"]["bank_lines"]["inward_line_count"] == 1


def test_the_books_now_agree_with_the_ledger(db):
    """THE POINT OF THE WHOLE CHANGE. The GST Input debit was always in the
    ledger; the return did not know about it, so `itc.matched` was false every
    month a client had a bank charge. Both sides are asserted from their own
    source — the ledger figure is summed off journal_lines here, not read out
    of the return."""
    _post(db, _txn(db, out=59_000), rate=1800)
    r = _return(db)
    assert _gst_input_balance(db) == 9_000
    itc = r["reconciliation"]["itc"]
    assert itc["ledger_paise"] == 9_000
    assert itc["books_paise"] == 9_000
    assert itc["difference_paise"] == 0
    assert itc["matched"] is True


def test_an_interstate_charge_lands_on_igst(db):
    """IGST Act s.12(12) puts the place of supply for banking services at the
    recipient's location on the supplier's records, so a bank registered in
    another state supplies inter-state. The CA states it; nothing infers it."""
    _post(db, _txn(db, out=59_000), rate=1800, interstate=True)
    w = _return(db)["working"]["itc"]
    assert w["igst_paise"] == 9_000
    assert w["cgst_paise"] == 0 and w["sgst_paise"] == 0


def test_the_credit_is_all_other_itc_and_not_reverse_charge(db):
    """Table 4(A)(5) "All other ITC", not 4(A)(3) ISRC. The bank charges the
    tax and pays it over — there is no s.9(3)/(4) liability on the client, and
    putting it on the reverse-charge row would ALSO create a 3.1(d) liability
    that does not exist, so the client would pay the tax twice.

    Asserted on the GSTN payload's own rows, which is the file that would be
    uploaded, and in whole rupees because CGST Act s.170 rounds a GSTR-3B
    figure to the nearest rupee."""
    _post(db, _txn(db, out=59_000), rate=1800)
    r = _return(db)
    assert r["rcm_cash_paise"] == 0
    rows = {row["ty"]: row for row in r["payload"]["itc_elg"]["itc_avl"]}
    assert rows["OTH"]["camt"] == 45 and rows["OTH"]["samt"] == 45
    assert rows["ISRC"] == {"ty": "ISRC", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}
    assert rows["IMPS"]["iamt"] == 0
    # …and it is INSIDE the Rule 36(4) population, not beside it. The cap sits
    # outside only self-assessed tax, which is raised on the recipient's own
    # s.31(3)(f) invoice; a bank charges the tax and files it, so the invoice
    # is furnished even though nothing here can say which 2B row it is.
    r36 = r["working"]["rule_36_4"]
    assert r36["self_assessed_cgst_paise"] == 0
    assert r36["self_assessed_sgst_paise"] == 0


# ── money IN: an outward supply the return had never declared ────────────────

def test_a_receipt_marked_with_gst_is_declared_in_3_1_a(db):
    """CGST Act s.9 levies on the outward supply, and the posting already
    credited GST Output — so the liability was in the ledger and the return
    paid none of it."""
    _post(db, _txn(db, into=1_18_000_00, category="Other",
                   description="CONSULTING FEE RECEIVED"),
          rate=1800, counter="ACC-FEES")
    r = _return(db)
    out = r["working"]["outward"]
    assert out["taxable_value_paise"] == 1_00_000_00
    assert out["taxable_cgst_paise"] == 9_000_00
    assert out["taxable_sgst_paise"] == 9_000_00
    assert r["reconciliation"]["bank_lines"]["output_tax_paise"] == 18_000_00
    assert r["reconciliation"]["output_gst"]["matched"] is True


def test_an_outward_bank_line_is_not_in_table_3_2(db):
    """3.2 is "of the supplies shown in 3.1(a)" broken down by place of supply
    and recipient class. A bank line records neither, so a bucket here would
    assert a fact the books do not hold — the same refusal the advance receipt
    makes."""
    _post(db, _txn(db, into=1_18_000_00, category="Other"),
          rate=1800, interstate=True, counter="ACC-FEES")
    r = _return(db)
    # `inter_state_3_2` is the key, and getting it wrong is how this test
    # passes on nothing: a `.get()` of a name the working does not use returns
    # None, and "no rows" and "no such table" then look identical.
    rows = r["working"]["inter_state_3_2"]
    assert set(rows) == {"unregistered", "composition", "uin"}
    assert not any(rows.values()), rows
    # …while the supply itself IS in 3.1(a), inter-state.
    assert r["working"]["outward"]["taxable_igst_paise"] == 18_000_00


# ── what is NOT declared, and why ────────────────────────────────────────────

def test_a_line_posted_without_a_rate_declares_nothing(db):
    """The ordinary two-leg post. No GST leg in the ledger, nothing on the
    return, and the reconciliation still matches at zero."""
    _post(db, _txn(db, out=59_000))
    r = _return(db)
    assert r["reconciliation"]["bank_lines"]["itc_paise"] == 0
    assert r["reconciliation"]["itc"]["matched"] is True
    assert r["bank_line_caveats"] == []


def test_a_rate_of_zero_is_an_answer_and_still_declares_nothing(db):
    """A charge the CA marked as carrying no GST — interest, a government levy.
    It posts identically to an unmarked line, so nothing in the ledger tells
    the two apart, and neither may be classified into 3.1(c): the books do not
    say whether it is nil-rated, exempt or outside the levy.

    THE LINE COUNT IS THE ASSERTION, not the tax. A zero-rate row split at 0%
    yields tax of nil and a taxable value equal to the whole amount, so a
    version that let it through would still show nil tax — and quietly put the
    VALUE on the return."""
    _post(db, _txn(db, out=59_000), rate=0)
    r = _return(db)
    assert r["reconciliation"]["bank_lines"]["itc_paise"] == 0
    assert r["reconciliation"]["bank_lines"]["inward_line_count"] == 0
    assert r["working"]["outward"]["nil_exempt_paise"] == 0
    assert r["working"]["outward"]["non_gst_paise"] == 0


def test_a_receipt_marked_zero_rate_is_not_declared_as_a_supply(db):
    """The same rule on the direction where it costs something. A receipt could
    be a loan drawdown, a capital contribution or an interest credit; declaring
    its whole value in 3.1(a) because the CA said "no GST in this" would assert
    a supply the books never recorded."""
    _post(db, _txn(db, into=1_18_000_00, category="Other"), rate=0,
          counter="ACC-FEES")
    r = _return(db)
    assert r["working"]["outward"]["taxable_value_paise"] == 0
    assert r["reconciliation"]["bank_lines"]["outward_line_count"] == 0


def test_a_line_outside_the_period_is_not_on_this_return(db):
    _post(db, _txn(db, out=59_000, date="2025-07-03"), rate=1800)
    assert _return(db)["reconciliation"]["bank_lines"]["itc_paise"] == 0


def test_undoing_the_posting_takes_the_declaration_with_it(db):
    """The declared split describes a posting. Leaving it behind would keep the
    line in the return's document set while its journal is reversed out of the
    ledger — the very books-vs-ledger difference this change closes, arriving
    from the other end."""
    txn = _txn(db, out=59_000)
    _post(db, txn, rate=1800)
    assert _return(db)["reconciliation"]["bank_lines"]["itc_paise"] == 9_000
    bps.bank_posting_service.undo(db, FIRM, txn["id"], actor_id=ACTOR)
    r = _return(db)
    assert r["reconciliation"]["bank_lines"]["itc_paise"] == 0
    # And the ledger agrees: the reversal cancels the GST Input debit.
    assert _gst_input_balance(db) == 0
    assert r["reconciliation"]["itc"]["matched"] is True


def test_reposting_without_a_rate_declares_nothing(db):
    """FOUND BY A NEGATIVE CONTROL, and this is the case that makes the undo
    path's clearing load-bearing rather than tidy.

    Undo alone hides the declaration, because it also clears
    `posted_journal_id` and nothing unposted is read. But the CA then corrects
    the line and posts it again with NO rate — the drawer's ordinary two-leg
    post. `post()` sends no GST keys, so a stale `gst_rate_bps` left on the row
    would survive, `posted_journal_id` would be set once more, and the return
    would claim credit for a journal that has no GST leg at all: books above
    ledger, which is the mismatch in the direction that over-claims."""
    txn = _txn(db, out=59_000)
    _post(db, txn, rate=1800)
    bps.bank_posting_service.undo(db, FIRM, txn["id"], actor_id=ACTOR)
    live = [t for t in db.rows("bank_transactions") if t["id"] == txn["id"]][0]
    assert live.get("gst_rate_bps") is None
    _post(db, txn, rate=None)
    r = _return(db)
    assert r["reconciliation"]["bank_lines"]["itc_paise"] == 0
    assert r["reconciliation"]["itc"]["matched"] is True


def test_the_fetch_itself_leaves_unposted_lines_on_the_wire(db):
    """The engine skips an unposted line and the QUERY filters it out too, and
    the second one is not redundant: without it every bank transaction in the
    period crosses the Singapore-to-Mumbai wire to be discarded in Python,
    which is the reporting rule this codebase states as "what crosses the wire
    must be proportional to the size of the ANSWER".

    Asserted on the fetcher rather than on the query's source text, so it is
    the behaviour that is pinned and not one spelling of the filter."""
    _post(db, _txn(db, out=59_000, description="POSTED"), rate=1800)
    unposted = _txn(db, out=59_000, description="NOT POSTED")
    db.table("bank_transactions").update({"gst_rate_bps": 1800}).eq(
        "id", unposted["id"]).execute()
    rows = grs._bank_lines_declaring_gst(db, FIRM, CLIENT, "2025-06-01", "2025-06-30")
    assert [r["description"] for r in rows] == ["POSTED"]


# ── the caveats: the half that cannot be computed ────────────────────────────

def test_the_credit_says_it_has_no_2b_document_behind_it(db):
    """s.16(2)(aa) allows the credit only where the supplier has furnished the
    invoice and it has been communicated in GSTR-2B. A bank line carries no
    supplier GSTIN and no invoice number, and inventing one so the 2B match
    would pass is worse than the gap — it would claim a document exists."""
    _post(db, _txn(db, out=59_000), rate=1800)
    notes = " ".join(_return(db)["bank_line_caveats"])
    assert "16(2)(aa)" in notes
    assert "2B" in notes
    assert "90.00" in notes


def test_an_outward_bank_line_says_gstr1_will_not_carry_it(db):
    """GSTR-1 is built from invoices. An outward supply declared here has none,
    so the portal's own GSTR-1 vs GSTR-3B comparison will differ by exactly
    this amount until the invoice is raised (CGST Rule 46). Naming it is what
    puts it in front of the CA."""
    _post(db, _txn(db, into=1_18_000_00, category="Other"),
          rate=1800, counter="ACC-FEES")
    notes = " ".join(_return(db)["bank_line_caveats"])
    assert "Rule 46" in notes
    assert "GSTR-1" in notes


# ── the drill-down adds up to the summary ────────────────────────────────────

def test_the_4a_listing_adds_up_to_the_4a_figure(db):
    """`gstr3b_detail`'s whole contract: a listing that disagrees with the
    figure above it turns one trusted number into two untrusted ones. A bank
    charge is now IN 4(A), so it has to be in the listing under it."""
    _post(db, _txn(db, out=59_000), rate=1800)
    d = grs.gstr3b_detail(db, FIRM, CLIENT, JUNE, "4A")
    r = _return(db)
    assert d["total_tax_paise"] == (r["working"]["itc"]["cgst_paise"]
                                    + r["working"]["itc"]["sgst_paise"]
                                    + r["working"]["itc"]["igst_paise"])
    row = [x for x in d["rows"] if x["kind"] == "Bank charge"][0]
    assert row["tax_paise"] == 9_000
    # No supplier invoice number, and that IS the finding: writing the
    # transaction's own id here would read as a reference the bank issued.
    assert row["document_no"] == ""
    assert row["party"] == "MONTHLY CHARGES"


def test_the_3_1a_listing_adds_up_too(db):
    _post(db, _txn(db, into=1_18_000_00, category="Other",
                   description="CONSULTING FEE RECEIVED"),
          rate=1800, counter="ACC-FEES")
    d = grs.gstr3b_detail(db, FIRM, CLIENT, JUNE, "3.1a")
    assert d["total_tax_paise"] == 18_000_00
    assert [x["kind"] for x in d["rows"]] == ["Bank receipt"]


def test_a_bank_charge_is_not_listed_under_reverse_charge(db):
    """3.1(d) is §9(3)/(4) tax the CLIENT self-assesses. The bank charged the
    tax and pays it over, so nothing here belongs on that line."""
    _post(db, _txn(db, out=59_000), rate=1800)
    assert grs.gstr3b_detail(db, FIRM, CLIENT, JUNE, "3.1d")["rows"] == []


# ── the engine on its own ────────────────────────────────────────────────────

def _row(**kw):
    base = {"id": "b", "posted_journal_id": "j", "gst_rate_bps": 1800,
            "debit_paise": 0, "credit_paise": 0, "transaction_date": "2025-06-01"}
    base.update(kw)
    return base


def test_the_split_is_exact():
    """taxable + tax == the gross the bank actually took, so the journal
    balances with no rounding plug. Rs 1,000 at 18% does not divide evenly."""
    d = bank_charge_gst.declared_gst([_row(debit_paise=1_000_00)])
    s = d.inward[0].split
    assert s.taxable_paise + s.tax_paise == 1_000_00
    assert s.taxable_paise == 84_745        # 100000 * 10000 // 11800
    assert s.tax_paise == 15_255


def test_direction_alone_decides_which_side_a_line_is_on():
    d = bank_charge_gst.declared_gst([
        _row(id="a", debit_paise=59_000),
        _row(id="b", credit_paise=59_000),
    ])
    assert [x.transaction_id for x in d.inward] == ["a"]
    assert [x.transaction_id for x in d.outward] == ["b"]


def test_an_unposted_line_is_skipped():
    assert bank_charge_gst.declared_gst(
        [_row(posted_journal_id=None, debit_paise=59_000)]).is_empty


def test_a_line_with_no_recorded_rate_is_skipped():
    assert bank_charge_gst.declared_gst(
        [_row(gst_rate_bps=None, debit_paise=59_000)]).is_empty


def test_a_zero_amount_line_does_not_raise():
    """`split_inclusive_charge` refuses a non-positive amount, and rightly —
    but a whole return must not fail on one stray row."""
    assert bank_charge_gst.declared_gst([_row()]).is_empty


def test_the_caveats_are_empty_when_nothing_was_declared():
    assert bank_charge_gst.declared_gst([]).caveats == ()


def test_the_fetch_selects_every_column_the_engine_reads(db):
    """A column the engine reads and the fetch does not select reads as absent,
    which for `gst_rate_bps` means "no GST declared" — a silently smaller
    return. Driven through the real fetch rather than compared against a
    constant, because a projection constant is what stops
    test_backend_columns_exist_pg checking the names against the real schema."""
    _post(db, _txn(db, out=59_000, description="MONTHLY CHARGES"), rate=1800)
    row = grs._bank_lines_declaring_gst(
        db, FIRM, CLIENT, "2025-06-01", "2025-06-30")[0]
    for col in bank_charge_gst._READS:
        assert col in row, f"the fetch does not select {col}"
