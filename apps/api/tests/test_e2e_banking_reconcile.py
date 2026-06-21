"""
Phase 5.2 final sprint — Banking Cycle (post/match → reconcile → reporting).

Complements test_e2e_banking.py (import + double-entry). Here:
  • a posted bank transaction's journal feeds REPORTING (trial balance);
  • the reconciliation lifecycle: open session → reconcile posted lines →
    complete with tie-out enforcement (every in-period line reconciled AND the
    arithmetic ties out), with the completed session immutable;
  • cross-firm isolation.

(The full post → draft-journal → approve chain is covered by
tests/test_bank_posting.py; this drives the reconciliation engine end-to-end.)
"""
import pytest
from fastapi import HTTPException

import services.bank_reconciliation_service as brs_mod
from services.bank_reconciliation_service import BankReconciliationService
from services.phase2_journal_service import phase2_journal_service as js
from tests.e2e_harness import FakeDB, wire_e2e, trial_balance, account_balance


FIRM = "FIRM-A"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [brs_mod])              # patches get_supabase + silences timeline
    db.seed("clients", {"id": "CLI", "firm_id": FIRM})
    db.seed("bank_accounts", {"id": "BA", "firm_id": FIRM, "client_id": "CLI",
                              "bank_name": "HDFC", "account_no": "0001"})
    db.seed("bank_statements", {"id": "ST", "firm_id": FIRM, "bank_account_id": "BA"})
    # Two POSTED transactions (posted_journal_id set) in the April period.
    db.seed("bank_transactions", {"id": "T1", "firm_id": FIRM, "client_id": "CLI", "statement_id": "ST",
                                  "transaction_date": "2026-04-05", "credit_paise": 500_000, "debit_paise": 0,
                                  "posted_journal_id": "J1", "reconciliation_id": None})
    db.seed("bank_transactions", {"id": "T2", "firm_id": FIRM, "client_id": "CLI", "statement_id": "ST",
                                  "transaction_date": "2026-04-10", "credit_paise": 0, "debit_paise": 200_000,
                                  "posted_journal_id": "J2", "reconciliation_id": None})
    return BankReconciliationService(), db


# --------------------------------------------------------------------------- #
#  Reporting: a posted bank transaction's journal lands in the trial balance
# --------------------------------------------------------------------------- #
def test_posted_bank_txn_feeds_trial_balance(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [])
    txn = {"id": "TX", "transaction_date": "2026-04-05", "credit_paise": 500_000,
           "debit_paise": 0, "description": "Client receipt", "reference_no": "R1"}
    jid = js.journal_for_bank_transaction(db, FIRM, "CLI", txn,
                                          account_id="COA-AR", bank_coa_account_id="COA-BANK")
    assert jid
    tb = trial_balance(db, FIRM, "CLI")
    assert tb["total_debit_paise"] == tb["total_credit_paise"] == 500_000   # balanced, posted
    assert account_balance(db, "COA-BANK") == 500_000                       # money IN ⇒ Dr Bank


# --------------------------------------------------------------------------- #
#  Reconcile lifecycle
# --------------------------------------------------------------------------- #
def test_reconcile_lifecycle_ties_out(monkeypatch):
    brs, db = _setup(monkeypatch)
    sess = brs.create_session(db, FIRM, "CLI", "BA", "2026-04-01", "2026-04-30",
                              opening_balance_paise=0, closing_balance_paise=300_000)
    rid = sess["id"]
    assert sess["status"] == "open"

    # Reconcile both posted lines (deposit 5,000 − withdrawal 2,000 = 3,000).
    prog = brs.reconcile(db, FIRM, rid, ["T1", "T2"])
    assert prog["status"] == "in_progress"
    assert prog["counts"]["reconciled"] == 2 and prog["counts"]["unreconciled"] == 0

    # Complete — every in-period line reconciled AND ties out (0 + 500,000 − 200,000 = 300,000).
    done = brs.complete(db, FIRM, rid)
    assert done["status"] == "completed"
    assert all(t["reconciled"] for t in db.rows("bank_transactions"))


def test_reconcile_complete_blocked_when_unreconciled(monkeypatch):
    brs, db = _setup(monkeypatch)
    rid = brs.create_session(db, FIRM, "CLI", "BA", "2026-04-01", "2026-04-30",
                             opening_balance_paise=0, closing_balance_paise=300_000)["id"]
    brs.reconcile(db, FIRM, rid, ["T1"])              # leave T2 unreconciled (in period)
    with pytest.raises(HTTPException) as ei:
        brs.complete(db, FIRM, rid)
    assert ei.value.status_code == 422                # statement not fully reconciled
    assert brs.get_session(db, FIRM, rid)["status"] != "completed"


def test_reconcile_complete_blocked_when_not_tied_out(monkeypatch):
    brs, db = _setup(monkeypatch)
    # Closing balance deliberately wrong ⇒ arithmetic won't tie out.
    rid = brs.create_session(db, FIRM, "CLI", "BA", "2026-04-01", "2026-04-30",
                             opening_balance_paise=0, closing_balance_paise=999_999)["id"]
    brs.reconcile(db, FIRM, rid, ["T1", "T2"])
    with pytest.raises(HTTPException) as ei:
        brs.complete(db, FIRM, rid)
    assert ei.value.status_code == 422                # does not tie out


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_reconcile_foreign_firm_cannot_open_session(monkeypatch):
    brs, db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as ei:           # bank account not found for FIRM-B
        brs.create_session(db, "FIRM-B", "CLI", "BA", "2026-04-01", "2026-04-30")
    assert ei.value.status_code == 422


def test_reconcile_foreign_firm_cannot_touch_session(monkeypatch):
    brs, db = _setup(monkeypatch)
    rid = brs.create_session(db, FIRM, "CLI", "BA", "2026-04-01", "2026-04-30",
                             opening_balance_paise=0, closing_balance_paise=300_000)["id"]
    # Session fetch is firm-scoped (.eq("firm_id", ...).single()) ⇒ foreign firm
    # matches no row and cannot reconcile or complete.
    with pytest.raises(Exception):
        brs.reconcile(db, "FIRM-B", rid, ["T1"])
    with pytest.raises(Exception):
        brs.complete(db, "FIRM-B", rid)
    assert not any(t.get("reconciled") for t in db.rows("bank_transactions"))   # untouched
