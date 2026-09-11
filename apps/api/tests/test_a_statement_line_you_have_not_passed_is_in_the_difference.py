"""
BANK-23 — the reconciliation showed only POSTED lines, so the one thing causing
the difference was the one thing not on screen.

WHAT WAS WRONG
    `_posted_account_txns` ended with

        return [t for t in rows if t.get("posted_journal_id")]

    and every bucket was built from what it returned. So a statement line the CA
    had not passed yet — on the bank statement because the bank moved the money,
    not in the books because nobody wrote the journal — reached NO bucket.

    The arithmetic then said the wrong thing twice over. `_summary` builds the
    reconciled book balance from RECONCILED lines, so it is short by exactly the
    unpassed line's amount and the tie-out fails. And the completion gate counts
    `unreconciled`, which is posted-only, so it reported "0 transactions still
    unreconciled" over a difference it could not explain. The CA is then told to
    go and find a missing or duplicated transaction; there isn't one.

WHAT IS ASSERTED
    1. The bucket exists, holds exactly the in-period unpassed lines, and its
       total IS the difference — the finding as a number.
    2. Completion is refused, naming the count and where to go, and refused
       BEFORE the tie-out, since this is the cause of that difference.
    3. Two lines that legitimately have no journal are NOT in it, and this is
       the half a bare `posted_journal_id IS NULL` test gets wrong:
         * a line the CA SET ASIDE — a decision, and it will never have one;
         * the RECEIVING side of a transfer pair, which bank_posting_service
           refuses to post by name because the paying side already wrote the
           whole double entry.
       Either one in the bucket would make the period uncompletable for ever.
    4. The other three buckets keep their meaning exactly — `_classify` now gets
       the unfiltered list, so a regression here would quietly change what
       "unreconciled" means on a screen CAs certify from.
    5. A report from before this existed still prints. A completed session serves
       a frozen snapshot (F2) with no `not_passed` key, and a certified document
       must not start raising KeyError.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from domain.banking import entry as E
import services.bank_reconciliation_service as brs_mod
from services.bank_reconciliation_service import bank_reconciliation_service as svc
from tests.test_bank_reconciliation import (db, FIRM, CLIENT, BA, START, END,   # noqa: F401
                                            _txn, _open, _set_aside)


def _rid(db, opening=100000, closing=160000):
    return _open(db, opening, closing)


# ── 1. the bucket, and the number ────────────────────────────────────────────

def test_the_bucket_holds_exactly_the_unpassed_in_period_lines(db):        # noqa: F811
    rid = _rid(db)
    out = svc.get_session(db, FIRM, rid)
    assert out["counts"]["not_passed"] == 1, "t4 in the fixture is exactly this line"
    rep = svc.report(db, FIRM, rid)
    assert [t["id"] for t in rep["not_passed"]] == ["t4"]
    assert rep["counts"]["not_passed"] == 1


def test_the_bucket_is_the_difference(db):                                 # noqa: F811
    """The finding as a number. The bank's closing balance includes t4's ₹999.99;
    the reconciled book balance cannot, because t4 is not in the books."""
    # Closing balance as the BANK would state it: 100000 + 50000 - 20000 + 30000
    # + 99999 (t4), i.e. every line on the statement.
    rid = _rid(db, opening=100000, closing=259999)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    rep = svc.report(db, FIRM, rid)
    net = sum(t["credit_paise"] - t["debit_paise"] for t in rep["not_passed"])
    assert net == 99999
    # The difference IS the bucket: the bank's closing balance carries t4 and
    # the reconciled book balance cannot, so they part company by its net to
    # the paise. Not `abs(...)` — the sign says the bank is AHEAD of the books,
    # which is the direction an unpassed receipt makes it.
    assert rep["summary"]["difference_paise"] == net == 99999, rep["summary"]
    assert not rep["ties_out"]


def test_an_out_of_period_unpassed_line_is_not_in_it(db):                  # noqa: F811
    db.store["bank_transactions"].append(
        _txn("t9", credit=5000, date="2025-05-15", posted=False))
    rid = _rid(db)
    rep = svc.report(db, FIRM, rid)
    assert [t["id"] for t in rep["not_passed"]] == ["t4"], (
        "a line outside the period is not this period's problem")


# ── 2. completion ────────────────────────────────────────────────────────────

def test_completion_is_refused_and_says_where_to_go(db):                   # noqa: F811
    rid = _rid(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    with pytest.raises(HTTPException) as e:
        svc.complete(db, FIRM, rid)
    assert e.value.status_code == 422
    detail = str(e.value.detail)
    assert "1 statement line(s)" in detail
    assert "Bank" in detail and "Entries" in detail, (
        "the refusal must name where the work is — nothing on this screen can "
        "fix a line with no journal")


def test_the_unpassed_check_comes_before_the_tie_out(db):                  # noqa: F811
    """Order matters. These lines are the CAUSE of the difference, so telling the
    CA "the statement does not tie out, chase ₹999.99" first sends them hunting
    a phantom."""
    rid = _rid(db, 100000, 259999)        # ties out ONLY once t4 is in the books
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    with pytest.raises(HTTPException) as e:
        svc.complete(db, FIRM, rid)
    assert "not been passed" in str(e.value.detail)
    assert "does not tie out" not in str(e.value.detail)


def test_dealing_with_the_line_lets_the_period_complete(db):               # noqa: F811
    rid = _rid(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    _set_aside(db, "t4")
    assert svc.complete(db, FIRM, rid)["status"] == "completed"


# ── 3. the two lines that legitimately have no journal ───────────────────────

def test_a_set_aside_line_is_not_in_the_bucket(db):                        # noqa: F811
    """Setting aside is a DECISION — "not ours", "a duplicate", "no entry
    needed". It will never have a journal, so a bucket that kept it would make
    the period uncompletable for ever."""
    _set_aside(db, "t4")
    rid = _rid(db)
    assert svc.report(db, FIRM, rid)["counts"]["not_passed"] == 0
    assert E.entry_state(
        next(t for t in db.store["bank_transactions"] if t["id"] == "t4")) == E.SET_ASIDE


def test_the_receiving_side_of_a_transfer_is_not_in_the_bucket(db):        # noqa: F811
    """It CANNOT post a journal. bank_posting_service refuses it by name: the
    paying side already wrote the complete double entry, and posting both would
    count the same money twice. So a NULL posted_journal_id here is correct and
    permanent."""
    covered = _txn("t6", debit=7000, posted=False)
    covered.update({"transfer_pair_id": "pair-1", "transfer_is_primary": False})
    db.store["bank_transactions"].append(covered)
    rid = _rid(db)
    assert E.entry_state(covered) == E.COVERED
    assert [t["id"] for t in svc.report(db, FIRM, rid)["not_passed"]] == ["t4"]


def test_a_line_with_a_journal_is_never_in_the_bucket_whatever_its_status(db):  # noqa: F811
    """The other half of the predicate, and the one an end-to-end fixture found.

    `E.entry_state`'s `passed` branch keys on `match_status = 'posted'`, NOT on
    the journal. A row carrying a journal whose status had not caught up — which
    is every row in tests/test_e2e_banking_reconcile.py's fixture — would be
    called unpassed by a state-only test, and completion would be refused over a
    line that is demonstrably in the ledger. "No journal" is what "not in the
    books" means, so it is asked first and the state only carves out."""
    posted_but_unstamped = _txn("t8", credit=4000, posted=True)
    posted_but_unstamped["match_status"] = None
    db.store["bank_transactions"].append(posted_but_unstamped)
    assert E.entry_state(posted_but_unstamped) in E.OPEN_STATES, (
        "the state alone says 'still to do' — which is the trap")

    rid = _rid(db)
    assert [t["id"] for t in svc.report(db, FIRM, rid)["not_passed"]] == ["t4"]


def test_a_bare_null_journal_test_would_have_caught_both(db):              # noqa: F811
    """The negative control for the two above, stated as the rule rather than as
    a mutation: the naive predicate puts three lines in the bucket where the
    entry state puts one."""
    _set_aside(db, "t4")
    covered = _txn("t6", debit=7000, posted=False)
    covered.update({"transfer_pair_id": "pair-1", "transfer_is_primary": False})
    db.store["bank_transactions"].append(covered)
    unpassed = _txn("t7", credit=1000, posted=False)
    db.store["bank_transactions"].append(unpassed)

    rows = db.store["bank_transactions"]
    naive = [t for t in rows if not t.get("posted_journal_id")]
    assert len(naive) == 3

    rid = _rid(db)
    assert [t["id"] for t in svc.report(db, FIRM, rid)["not_passed"]] == ["t7"]


# ── 4. the other three buckets are untouched ─────────────────────────────────

def test_the_other_buckets_keep_their_meaning(db):                         # noqa: F811
    """`_classify` now receives the UNFILTERED list, so the posted filter moved
    inside it. If that move leaked, `unreconciled` would start including lines
    with no journal — on a screen CAs certify from."""
    rid = _rid(db)
    rep = svc.report(db, FIRM, rid)
    assert [t["id"] for t in rep["unreconciled"]] == ["t1", "t2", "t3"]
    assert all(t["posted_journal_id"] for t in rep["unreconciled"])
    assert rep["reconciled"] == [] and rep["exceptions"] == []

    svc.reconcile(db, FIRM, rid, ["t1"])
    rep = svc.report(db, FIRM, rid)
    assert [t["id"] for t in rep["reconciled"]] == ["t1"]
    assert [t["id"] for t in rep["unreconciled"]] == ["t2", "t3"]
    assert [t["id"] for t in rep["not_passed"]] == ["t4"]


def test_one_fetch_serves_all_four_buckets(db):                            # noqa: F811
    """apps/api is in Singapore and Postgres in Mumbai, so a second query for
    the unpassed half would be a second crossing. `_posted_account_txns` is now
    derived from `_account_txns` rather than fetching again."""
    calls = []
    original = brs_mod.BankReconciliationService._account_txns

    def counted(self, db_, firm_id, bank_account_id):
        calls.append(bank_account_id)
        return original(self, db_, firm_id, bank_account_id)

    brs_mod.BankReconciliationService._account_txns = counted
    try:
        rid = _rid(db)
        calls.clear()
        svc.report(db, FIRM, rid)
        assert len(calls) == 1, f"the report fetched the account {len(calls)} times"
    finally:
        brs_mod.BankReconciliationService._account_txns = original


# ── 5. a report from before this existed still prints ────────────────────────

def test_a_frozen_snapshot_without_the_key_still_renders_a_csv(db):        # noqa: F811
    """F2 freezes the report at completion and never recomputes it, so a session
    completed before BANK-23 has no `not_passed`. `report_csv` must keep
    printing — a certified document that starts raising is worse than one
    missing a section that was empty anyway."""
    rid = _rid(db, 100000, 160000)
    svc.reconcile(db, FIRM, rid, ["t1", "t2", "t3"])
    _set_aside(db, "t4")
    svc.complete(db, FIRM, rid)

    session = next(s for s in db.store["bank_reconciliations"] if s["id"] == rid)
    session["snapshot"].pop("not_passed", None)
    session["snapshot"]["counts"].pop("not_passed", None)

    text = svc.report_csv(db, FIRM, rid)
    assert "Bank Reconciliation Report" in text
