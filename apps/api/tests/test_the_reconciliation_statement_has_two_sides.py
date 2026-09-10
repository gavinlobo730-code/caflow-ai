"""
BANK-04: the document titled "Bank Reconciliation Statement" was not one.

WHAT WAS WRONG

Every row the reconciliation knew about was a STATEMENT line.
`domain/banking/reconciliation.tie_out` proves one identity — opening +
reconciled deposits − reconciled withdrawals ± adjustments == the statement's
closing balance — and the service buckets statement lines into reconciled,
unreconciled and exceptions. Nothing in the module read `journal_entries` or
`journal_lines` at all.

So a cheque issued and entered in the books but not yet presented at the bank
had no row anywhere in it, and neither did a deposit banked but not yet
credited. Those two ARE the substance of a BRS. The CA opened Reconcile
expecting the document they have prepared every month of their career and got a
tick-list plus a difference; at year end the auditor's working paper could not be
produced from this product at all. Tally, Zoho, Busy and Marg all produce the
two-sided statement.

WHAT IT IS NOW

    Balance as per Cash Book (books)
      Add:  cheques issued but not yet presented
      Less: cheques/deposits banked but not yet credited
      Add:  amounts credited by the bank, not yet in the books
      Less: amounts debited by the bank, not yet in the books
      = Balance as per Pass Book (bank)

computed by `public.bank_reconciling_items` (migration 356) where there is a
database and by `domain/banking/brs.py` in mock mode, held identical by
tests/test_brs_sql_parity_pg.py. The tie-out stays exactly as it was, as the
internal check. This file covers the twin, the service around it, and the two
things only the service can decide: what happens when a bank account has no
ledger account, and what happens to the document when a period is certified.
"""
import pytest
from fastapi import HTTPException

import routers.banking as banking
import services.bank_reconciliation_service as brs_service
from domain.banking.brs import LIST_CAP, reconciling_items
from services.bank_reconciliation_service import bank_reconciliation_service as svc
from tests.test_bank_reconciliation import FakeDB

FIRM, CLIENT, BA, GL = "firm-brs", "client-brs", "ba-brs", "coa-bank-brs"
START, END = "2026-03-01", "2026-03-31"


# ══════════════════════════════════════════════════════════════════════════════
# The twin, on its own
# ══════════════════════════════════════════════════════════════════════════════

def _book(line_id, entry_id, date, *, debit=0, credit=0, ref=None, narration=""):
    return {"line_id": line_id, "entry_id": entry_id, "entry_date": date,
            "narration": narration, "reference_no": ref,
            "debit_paise": debit, "credit_paise": credit}


def _bank(tid, date, *, debit=0, credit=0, ref=None, desc="", entry=None):
    return {"id": tid, "transaction_date": date, "description": desc,
            "reference_no": ref, "debit_paise": debit, "credit_paise": credit,
            "posted_journal_id": entry}


def test_the_worked_example_from_every_textbook():
    """Books 15,000. A ₹10,000 cheque issued and not presented; a ₹5,000 deposit
    banked and not credited; ₹118 of bank charges not in the books. The bank's
    own balance is 19,882 — and the statement gets there from 15,000."""
    book = [_book("l1", "e1", "2026-03-28", credit=10_000_00, ref="CHQ 4411"),
            _book("l2", "e2", "2026-03-30", debit=5_000_00),
            _book("l3", "e3", "2026-03-10", debit=20_000_00)]
    bank = [_bank("t1", "2026-03-10", credit=20_000_00, entry="e3"),
            _bank("t2", "2026-03-31", debit=118_00, desc="SERVICE CHARGES")]
    got = reconciling_items(book, bank, as_of="2026-03-31",
                            statement_balance_paise=19_882_00)
    assert got["book_balance_paise"] == 15_000_00
    assert got["unpresented_cheques"]["total_paise"] == 10_000_00
    assert got["deposits_in_transit"]["total_paise"] == 5_000_00
    assert got["bank_debits_not_in_books"]["total_paise"] == 118_00
    assert got["bank_credits_not_in_books"]["total_paise"] == 0
    assert got["computed_bank_balance_paise"] == 19_882_00
    assert got["agrees"] is True and got["difference_paise"] == 0


def test_the_cheque_number_travels_because_that_is_what_makes_it_findable():
    book = [_book("l1", "e1", "2026-03-28", credit=10_000_00, ref="CHQ 4411",
                  narration="Rent — March")]
    got = reconciling_items(book, [], as_of="2026-03-31")
    item = got["unpresented_cheques"]["items"][0]
    assert item["reference_no"] == "CHQ 4411"
    assert item["particulars"] == "Rent — March"
    assert item["date"] == "2026-03-28" and item["source"] == "book"


def test_a_cheque_presented_next_month_is_unpresented_this_month():
    """The rule that lets a BRS be produced for a PAST date. The link exists
    permanently once April is imported; at 31 March the bank had not paid it, so
    it must still be an unpresented cheque. Without this, every historical BRS
    would change the moment the next month was imported."""
    book = [_book("l1", "e1", "2026-03-28", credit=10_000_00, ref="CHQ 4411")]
    april = _bank("t1", "2026-04-05", debit=10_000_00, entry="e1")

    march = reconciling_items(book, [], as_of="2026-03-31")
    assert march["unpresented_cheques"]["count"] == 1

    after = reconciling_items(book, [april], as_of="2026-04-30")
    assert after["unpresented_cheques"]["count"] == 0


def test_with_no_stated_balance_it_names_the_gap_rather_than_assuming_zero():
    got = reconciling_items([], [], as_of="2026-03-31")
    assert got["statement_balance_paise"] is None
    assert got["agrees"] is None and got["difference_paise"] is None
    assert "nothing has confirmed" in got["gap"]


def test_a_disagreement_is_reported_and_not_absorbed():
    """Nothing is reconciling here — the one receipt is on both sides — so the
    computed bank balance is the book balance, and the statement's own figure
    disagreeing with it is a real difference to chase."""
    book = [_book("l1", "e1", "2026-03-10", debit=20_000_00)]
    bank = [_bank("t1", "2026-03-10", credit=20_000_00, entry="e1")]
    got = reconciling_items(book, bank, as_of="2026-03-31",
                            statement_balance_paise=19_000_00)
    assert got["computed_bank_balance_paise"] == 20_000_00
    assert got["agrees"] is False
    assert got["difference_paise"] == -1_000_00


def test_the_lists_are_capped_and_the_totals_are_not():
    """On an account nobody has ever reconciled, EVERY book entry is an
    unpresented item — proportional to transaction volume, which is what
    CLAUDE.md's reporting rule forbids putting on the wire. The totals stay
    exact and the cut is stated, because a truncated list that claimed to be
    complete would be worse than a slow one."""
    book = [_book(f"l{i:03d}", f"e{i:03d}", "2026-03-10", credit=100)
            for i in range(10)]
    got = reconciling_items(book, [], as_of="2026-03-31", list_cap=3)
    bucket = got["unpresented_cheques"]
    assert bucket["count"] == 10 and bucket["listed"] == 3
    assert len(bucket["items"]) == 3
    assert bucket["total_paise"] == 1000, "the total covers every row"
    assert LIST_CAP == 500


def test_two_lines_of_one_entry_are_two_rows():
    book = [_book("l2", "e1", "2026-03-10", credit=400, narration="Second leg"),
            _book("l1", "e1", "2026-03-10", credit=300, narration="First leg")]
    items = reconciling_items(book, [], as_of="2026-03-31")["unpresented_cheques"]["items"]
    assert [i["particulars"] for i in items] == ["First leg", "Second leg"], (
        "ordered by LINE id — two rows sharing a sort key make the order unstable")


# ══════════════════════════════════════════════════════════════════════════════
# The service around it
# ══════════════════════════════════════════════════════════════════════════════

def _txn(tid, *, debit=0, credit=0, date="2026-03-10", entry=None, desc=""):
    return {"id": tid, "firm_id": FIRM, "client_id": CLIENT, "statement_id": "stmt-1",
            "transaction_date": date, "description": desc or f"txn {tid}",
            "reference_no": None, "debit_paise": debit, "credit_paise": credit,
            "match_status": "posted" if entry else "matched",
            "posted_journal_id": entry, "reconciled": False, "reconciliation_id": None}


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(brs_service.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None,
                        raising=False)
    d = FakeDB()
    d.store["bank_accounts"] = [
        {"id": BA, "firm_id": FIRM, "client_id": CLIENT, "bank_name": "HDFC",
         "account_no": "0001", "coa_account_id": GL}]
    d.store["bank_statements"] = [
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": BA,
         "statement_from": "2026-03-01", "statement_to": "2026-04-30"}]
    d.store["bank_transactions"] = [
        _txn("t1", credit=20_000_00, entry="e3"),
        _txn("t2", debit=118_00, date="2026-03-31", desc="SERVICE CHARGES"),
        # April's line, paying March's cheque.
        _txn("t3", debit=10_000_00, date="2026-04-05", entry="e1"),
    ]
    d.store["journal_entries"] = [
        {"id": "e1", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-03-28",
         "reference_no": "CHQ 4411", "narration": "Rent — March", "is_posted": True,
         "deleted_at": None},
        {"id": "e2", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-03-30",
         "reference_no": None, "narration": "Cash deposit", "is_posted": True,
         "deleted_at": None},
        {"id": "e3", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-03-10",
         "reference_no": None, "narration": "Receipt", "is_posted": True,
         "deleted_at": None},
        {"id": "e4", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-03-11",
         "reference_no": None, "narration": "Never posted", "is_posted": False,
         "deleted_at": None},
        {"id": "e5", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-03-12",
         "reference_no": None, "narration": "Deleted", "is_posted": True,
         "deleted_at": "2026-03-13T00:00:00Z"},
    ]
    d.store["journal_lines"] = [
        {"id": "l1", "journal_entry_id": "e1", "account_id": GL,
         "debit_paise": 0, "credit_paise": 10_000_00, "narration": None},
        {"id": "l2", "journal_entry_id": "e2", "account_id": GL,
         "debit_paise": 5_000_00, "credit_paise": 0, "narration": None},
        {"id": "l3", "journal_entry_id": "e3", "account_id": GL,
         "debit_paise": 20_000_00, "credit_paise": 0, "narration": None},
        {"id": "l4", "journal_entry_id": "e4", "account_id": GL,
         "debit_paise": 0, "credit_paise": 99_999_00, "narration": None},
        {"id": "l5", "journal_entry_id": "e5", "account_id": GL,
         "debit_paise": 0, "credit_paise": 88_888_00, "narration": None},
        # The other leg of the rent entry, on the expense account.
        {"id": "l6", "journal_entry_id": "e1", "account_id": "coa-rent",
         "debit_paise": 10_000_00, "credit_paise": 0, "narration": None},
    ]
    d.store["bank_reconciliations"] = []
    return d


def _post_the_charges(db) -> None:
    """Put the bank charges into the books, which is what a CA does before
    completing: the completion gate refuses while any in-period statement line
    is unreconciled, and an unposted line cannot be reconciled. After this the
    only reconciling items are on the BOOK side — which is the case the old
    document could not show at all."""
    next(t for t in db.store["bank_transactions"] if t["id"] == "t2").update(
        {"posted_journal_id": "e6", "match_status": "posted"})
    db.store["journal_entries"].append(
        {"id": "e6", "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-03-31",
         "reference_no": None, "narration": "Bank charges", "is_posted": True,
         "deleted_at": None})
    db.store["journal_lines"].append(
        {"id": "l7", "journal_entry_id": "e6", "account_id": GL,
         "debit_paise": 0, "credit_paise": 118_00, "narration": None})


def _open(db, closing=19_882_00):
    return svc.create_session(db, FIRM, CLIENT, BA, START, END,
                              opening_balance_paise=0,
                              closing_balance_paise=closing, actor_id="auth-1")["id"]


def test_the_service_produces_the_statement_from_the_books(db):
    got = svc.brs(db, FIRM, _open(db))
    assert got["book_balance_paise"] == 15_000_00
    assert got["unpresented_cheques"]["items"][0]["reference_no"] == "CHQ 4411"
    assert got["deposits_in_transit"]["total_paise"] == 5_000_00
    assert got["bank_debits_not_in_books"]["total_paise"] == 118_00
    assert got["computed_bank_balance_paise"] == 19_882_00
    assert got["agrees"] is True
    assert got["frozen"] is False
    assert got["reconciliation"]["statement_end_date"] == END


def test_unposted_deleted_and_other_account_lines_are_not_in_it(db):
    got = svc.brs(db, FIRM, _open(db))
    amounts = [i["amount_paise"] for b in ("unpresented_cheques", "deposits_in_transit")
               for i in got[b]["items"]]
    assert 99_999_00 not in amounts and 88_888_00 not in amounts
    assert 15_000_00 == got["book_balance_paise"], (
        "the rent's expense leg must not be in the bank account's balance")


def test_a_bank_account_with_no_ledger_account_is_refused_not_guessed(db):
    """Without the GL account there is no book side, and a "BRS" with only the
    bank side is the document this replaces."""
    db.store["bank_accounts"][0]["coa_account_id"] = None
    with pytest.raises(HTTPException) as e:
        svc.brs(db, FIRM, _open(db))
    assert e.value.status_code == 422
    assert "not linked to a ledger account" in str(e.value.detail)


def test_completing_freezes_the_statement_with_the_tie_out(db):
    """A certified reconciliation that recomputed live would be a different
    document from the one that was signed off — and THIS half moves the moment
    the next month's statement is imported."""
    _post_the_charges(db)
    rid = _open(db, closing=19_882_00)
    svc.reconcile(db, FIRM, rid, ["t1", "t2"])
    svc.complete(db, FIRM, rid)

    frozen = svc.brs(db, FIRM, rid)
    assert frozen["frozen"] is True
    assert frozen["unpresented_cheques"]["total_paise"] == 10_000_00

    # April's statement arrives and clears the cheque. The certified document
    # must not move.
    db.store["bank_transactions"].append(
        _txn("t9", debit=10_000_00, date="2026-04-06", entry="e1"))
    assert svc.brs(db, FIRM, rid)["unpresented_cheques"]["total_paise"] == 10_000_00
    assert svc.report(db, FIRM, rid)["brs"]["unpresented_cheques"]["total_paise"] == 10_000_00


def test_a_period_certified_before_this_existed_gets_a_live_one_and_says_so(db):
    """Its snapshot has no statement. Computing one is the best available answer
    and must not be presented as the thing that was signed."""
    _post_the_charges(db)
    rid = _open(db)
    svc.reconcile(db, FIRM, rid, ["t1", "t2"])
    svc.complete(db, FIRM, rid)
    row = db.store["bank_reconciliations"][0]
    row["snapshot"] = {k: v for k, v in row["snapshot"].items() if k != "brs"}

    got = svc.brs(db, FIRM, rid)
    assert got["frozen"] is False
    assert got["unpresented_cheques"]["total_paise"] == 10_000_00


def test_a_failure_to_build_it_does_not_fail_the_completion(db, monkeypatch):
    """The completion gate is the tie-out and the reviewed lines. Losing the
    document because one of its queries failed would refuse a period that
    reconciles."""
    monkeypatch.setattr(svc, "brs",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _post_the_charges(db)
    rid = _open(db)
    svc.reconcile(db, FIRM, rid, ["t1", "t2"])
    assert svc.complete(db, FIRM, rid)["status"] == "completed"
    assert "brs" not in db.store["bank_reconciliations"][0]["snapshot"]


def test_the_pdf_carries_the_two_sided_statement(db):
    from services.bank_reconciliation_pdf_service import build_reconciliation_pdf
    rid = _open(db)
    report = {**svc.report(db, FIRM, rid), "brs": svc.brs(db, FIRM, rid)}
    pdf = build_reconciliation_pdf(report, {"name": "Test & Co"})
    assert pdf[:4] == b"%PDF"
    # The PDF is compressed, so assert on what the table was built from rather
    # than on rendered glyphs — the rows are the thing under test.
    assert report["brs"]["unpresented_cheques"]["items"][0]["reference_no"] == "CHQ 4411"
    assert report["brs"]["computed_bank_balance_paise"] == 19_882_00


def test_the_endpoint_is_readable_by_anyone_who_can_see_banking():
    """A BRS is a read. Producing one changes nothing, and gating it above
    `read` would put the auditor's working paper behind a tier the person
    preparing it may not have."""
    route = next(r for r in banking.router.routes
                 if getattr(r, "path", None) == "/api/banking/reconciliations/{recon_id}/brs")
    assert route.dependant.dependencies[0].call.__name__ == "rbac_banking_read"
    assert "GET" in route.methods
