"""
Banking Tier 2.1 + 2.2 — carried-forward opening balance and the
beginning-balance mismatch check.

WHY THIS MATTERS
    The opening balance used to be typed in by hand for every reconciliation,
    with nothing to check it against. A typo produced a reconciliation that tied
    out PERFECTLY to the wrong number — the arithmetic is exact either way, so
    nothing downstream could notice, and the error was then frozen into the
    completion snapshot and carried into the next period.

    It was never a matter of opinion: the opening balance is the closing balance
    the last completed reconciliation tied out to, and that figure was already
    stored in that session's frozen snapshot the whole time.

Both figures here are financial calculations, so the arithmetic is unit-tested
directly (CLAUDE.md) as well as through the service.
"""
import pytest

from domain.banking import reconciliation as recon
import services.bank_reconciliation_service as brs
from services.bank_reconciliation_service import bank_reconciliation_service as svc

from tests.test_bank_reconciliation import FakeDB, FIRM, CLIENT, BA, START, END, _txn


# ══════════════════════════════════════════════════════════════════════════════
# Pure arithmetic
# ══════════════════════════════════════════════════════════════════════════════

def test_reconciled_book_balance_accumulates_across_sessions():
    assert recon.reconciled_book_balance(
        account_opening_paise=100000,
        completed_sessions=[
            {"deposits_paise": 500000, "withdrawals_paise": 200000, "adjustments_paise": 0},
            {"deposits_paise": 100000, "withdrawals_paise": 50000, "adjustments_paise": 0},
        ],
    ) == 450000


def test_reconciled_book_balance_includes_adjustments():
    """A documented adjustment (a bank charge, say) is part of the tie-out, so it
    must be part of the carry-forward too — otherwise every period after an
    adjusted one starts wrong."""
    assert recon.reconciled_book_balance(
        account_opening_paise=0,
        completed_sessions=[{"deposits_paise": 10000, "withdrawals_paise": 0,
                             "adjustments_paise": -1500}],
    ) == 8500


def test_reconciled_book_balance_with_no_sessions_is_the_account_opening():
    assert recon.reconciled_book_balance(
        account_opening_paise=250000, completed_sessions=[]) == 250000


def test_reconciled_book_balance_handles_missing_keys():
    assert recon.reconciled_book_balance(
        account_opening_paise=100, completed_sessions=[{}]) == 100


def test_opening_balance_check_matches():
    r = recon.opening_balance_check(
        suggested_opening_paise=450000, reconciled_book_balance_paise=450000)
    assert r["matches"] is True and r["mismatch_paise"] == 0


def test_opening_balance_check_reports_a_signed_mismatch():
    """Signed, not absolute: the direction tells the CA whether the statement
    side or the book side moved."""
    over = recon.opening_balance_check(
        suggested_opening_paise=450000, reconciled_book_balance_paise=440000)
    assert over["mismatch_paise"] == 10000 and over["matches"] is False
    under = recon.opening_balance_check(
        suggested_opening_paise=440000, reconciled_book_balance_paise=450000)
    assert under["mismatch_paise"] == -10000 and under["matches"] is False


def test_opening_balance_check_is_exact_to_the_paise():
    r = recon.opening_balance_check(
        suggested_opening_paise=450001, reconciled_book_balance_paise=450000)
    assert r["matches"] is False and r["mismatch_paise"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Service
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(brs.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None, raising=False)
    d = FakeDB()
    d.store["bank_accounts"] = [
        {"id": BA, "firm_id": FIRM, "client_id": CLIENT, "bank_name": "HDFC",
         "account_no": "0001", "coa_account_id": "coa-bank", "opening_balance_paise": 100000},
    ]
    d.store["bank_statements"] = [
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": BA,
         "statement_from": START, "statement_to": END},
    ]
    d.store["bank_transactions"] = [
        _txn("t1", credit=50000), _txn("t2", debit=20000), _txn("t3", credit=30000),
    ]
    d.store["bank_reconciliations"] = []
    return d


def _complete_a_period(db, *, opening, closing, txn_ids):
    """Open a session, reconcile the given transactions, complete it."""
    sid = svc.create_session(db, FIRM, CLIENT, BA, START, END,
                             opening_balance_paise=opening,
                             closing_balance_paise=closing, actor_id="u1")["id"]
    svc.reconcile(db, FIRM, sid, txn_ids, actor_id="u1")
    svc.complete(db, FIRM, sid, actor_id="u1")
    return sid


# ── 2.1 carry-forward ───────────────────────────────────────────────────────

def test_first_reconciliation_starts_from_the_account_opening(db):
    s = svc.opening_suggestion(db, FIRM, CLIENT, BA)
    assert s["source"] == "bank_account_opening"
    assert s["suggested_opening_paise"] == 100000
    assert s["completed_count"] == 0
    assert s["previous_reconciliation"] is None
    assert s["matches"] is True


def test_next_reconciliation_carries_forward_the_completed_closing(db):
    # 100000 + 50000 + 30000 - 20000 = 160000
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    s = svc.opening_suggestion(db, FIRM, CLIENT, BA)
    assert s["source"] == "previous_reconciliation"
    assert s["suggested_opening_paise"] == 160000
    assert s["completed_count"] == 1
    assert s["previous_reconciliation"]["period_end"] == END
    assert s["matches"] is True, "the books must agree immediately after completion"


def test_create_session_defaults_the_opening_to_the_carry_forward(db):
    """The whole point of 2.1: omit it and get the right number, not zero."""
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    nxt = svc.create_session(db, FIRM, CLIENT, BA, "2025-05-01", "2025-05-31",
                             closing_balance_paise=0, actor_id="u1")
    assert nxt["opening_balance_paise"] == 160000


def test_an_explicit_opening_is_still_honoured(db):
    """A default, not a lock — including an explicit zero."""
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    nxt = svc.create_session(db, FIRM, CLIENT, BA, "2025-05-01", "2025-05-31",
                             opening_balance_paise=0, closing_balance_paise=0, actor_id="u1")
    assert nxt["opening_balance_paise"] == 0
    assert nxt["opening_balance_check"]["used_suggestion"] is False


def test_create_session_reports_the_check(db):
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    nxt = svc.create_session(db, FIRM, CLIENT, BA, "2025-05-01", "2025-05-31", actor_id="u1")
    chk = nxt["opening_balance_check"]
    assert chk["used_suggestion"] is True
    assert chk["typed_opening_paise"] == 160000
    assert chk["matches"] is True


def test_the_suggestion_comes_from_the_frozen_snapshot(db):
    """Not from the mutable row. The snapshot is what the session actually tied
    out to and cannot drift if the row is later touched."""
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    # Corrupt the row's closing balance; the snapshot still holds the truth.
    db.store["bank_reconciliations"][0]["closing_balance_paise"] = 999999
    assert svc.opening_suggestion(db, FIRM, CLIENT, BA)["suggested_opening_paise"] == 160000


# ── 2.2 mismatch detection ──────────────────────────────────────────────────

def test_unreconciling_after_completion_is_detected(db):
    """The condition worth warning about: a completed period's closing balance
    no longer agrees with the books' record of what is reconciled."""
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    # Something detaches a reconciled transaction after the fact.
    for t in db.store["bank_transactions"]:
        if t["id"] == "t3":
            t["reconciliation_id"] = None

    s = svc.opening_suggestion(db, FIRM, CLIENT, BA)
    assert s["matches"] is False
    # The statement side still says 160000; the books now total 130000.
    assert s["suggested_opening_paise"] == 160000
    assert s["reconciled_book_balance_paise"] == 130000
    assert s["mismatch_paise"] == 30000


def test_an_altered_adjustment_after_completion_is_detected(db):
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    db.store["bank_reconciliations"][0]["adjustments_paise"] = -2500
    s = svc.opening_suggestion(db, FIRM, CLIENT, BA)
    assert s["matches"] is False and s["mismatch_paise"] == 2500


def test_a_mismatch_never_blocks_opening_a_period(db):
    """A warning, not a gate. Refusing to open would leave the CA no way to
    investigate the difference."""
    _complete_a_period(db, opening=100000, closing=160000, txn_ids=["t1", "t2", "t3"])
    for t in db.store["bank_transactions"]:
        if t["id"] == "t3":
            t["reconciliation_id"] = None

    nxt = svc.create_session(db, FIRM, CLIENT, BA, "2025-05-01", "2025-05-31", actor_id="u1")
    assert nxt["status"] == "open"
    assert nxt["opening_balance_check"]["matches"] is False


def test_open_sessions_do_not_count_towards_the_carry_forward(db):
    """Only COMPLETED periods are settled history. An in-progress session's
    ticked lines must not move the next period's starting point."""
    sid = svc.create_session(db, FIRM, CLIENT, BA, START, END,
                             opening_balance_paise=100000,
                             closing_balance_paise=160000, actor_id="u1")["id"]
    svc.reconcile(db, FIRM, sid, ["t1"], actor_id="u1")
    s = svc.opening_suggestion(db, FIRM, CLIENT, BA)
    assert s["completed_count"] == 0
    assert s["source"] == "bank_account_opening"
    assert s["suggested_opening_paise"] == 100000
    assert s["matches"] is True


def test_suggestion_rejects_another_firms_bank_account(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        svc.opening_suggestion(db, "other-firm", CLIENT, BA)
    assert ei.value.status_code == 422
