"""
Phase 5.2 WS-1 — Banking E2E.

Covers the cross-module slice the existing bank_posting / bank_reconciliation
suites don't: the account + statement-import lifecycle and tenant isolation,
plus the pure double-entry rule that underpins every bank posting.

  create_bank_account → import_statement → (dedup re-import) → set GL account

(The full post → draft-journal → approve → reconcile chain has Phase-3.5 draft
semantics and is covered by tests/test_bank_posting.py and
tests/test_bank_reconciliation.py; here we assert the import lifecycle,
isolation, and that bank_txn_lines builds a balanced entry with the correct
debit/credit direction.)
"""
import pytest
from fastapi import HTTPException

from models.banking import BankAccountIn, StatementImportIn, StatementImportRow, TransactionAccountIn
from services.phase2_journal_service import phase2_journal_service as js
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.banking as bk
    import services.banking_service as bsvc
    db = FakeDB()
    wire_e2e(monkeypatch, db, [bk, bsvc])
    monkeypatch.setattr(bk, "_db", lambda: db)           # router uses _db(), not _USE_MOCK
    db.seed("clients", {"id": "CLI", "firm_id": FIRM})
    return bk, db


def _import_two(bk):
    return bk.import_statement(StatementImportIn(
        client_id="CLI", bank_name="HDFC", account_number="0001",
        rows=[
            StatementImportRow(transaction_date="2026-04-02", description="Client receipt",
                               credit_paise=500_000, balance_paise=500_000, reference_no="R1"),
            StatementImportRow(transaction_date="2026-04-03", description="Rent paid",
                               debit_paise=200_000, balance_paise=300_000, reference_no="P1"),
        ],
    ), CALLER)["data"]


def test_banking_account_and_import_lifecycle(monkeypatch):
    bk, db = _setup(monkeypatch)

    acct = bk.create_bank_account(BankAccountIn(
        client_id="CLI", bank_name="HDFC", account_no="0001"), CALLER)["data"]
    assert acct["firm_id"] == FIRM

    res = _import_two(bk)
    assert res["imported"] == 2 and res["duplicates_skipped"] == 0
    txns = db.rows("bank_transactions")
    assert len(txns) == 2
    assert all(t["firm_id"] == FIRM and t["match_status"] == "unmatched" for t in txns)

    # Idempotent re-import of the same rows ⇒ all skipped, no new rows.
    again = _import_two(bk)
    assert again["imported"] == 0 and again["duplicates_skipped"] == 2
    assert len(db.rows("bank_transactions")) == 2


def test_banking_set_account_marks_matched(monkeypatch):
    bk, db = _setup(monkeypatch)
    _import_two(bk)
    txn_id = db.rows("bank_transactions")[0]["id"]
    resp = bk.set_transaction_account(txn_id, TransactionAccountIn(account_id="COA-RENT"), CALLER)
    assert resp["data"]["match_status"] == "matched"
    assert db.rows("bank_transactions")[0]["account_id"] == "COA-RENT"


def test_banking_empty_import_rejected(monkeypatch):
    bk, db = _setup(monkeypatch)
    # The model forbids empty rows (validated before the service).
    with pytest.raises(Exception):
        StatementImportIn(client_id="CLI", bank_name="HDFC", rows=[])


# --------------------------------------------------------------------------- #
#  Double-entry correctness (the rule under every bank posting)
# --------------------------------------------------------------------------- #
def test_bank_txn_lines_inflow_debits_bank():
    amount, entry_type, lines = js.bank_txn_lines(
        debit_paise=0, credit_paise=500_000, account_id="COA-AR", bank_coa_account_id="COA-BANK")
    assert entry_type == "Receipt" and amount == 500_000
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 500_000
    bank_line = next(l for l in lines if l["account_id"] == "COA-BANK")
    assert bank_line["debit_paise"] == 500_000          # money IN ⇒ Dr Bank


def test_bank_txn_lines_outflow_credits_bank():
    amount, entry_type, lines = js.bank_txn_lines(
        debit_paise=200_000, credit_paise=0, account_id="COA-RENT", bank_coa_account_id="COA-BANK")
    assert entry_type == "Payment" and amount == 200_000
    assert sum(l["debit_paise"] for l in lines) == sum(l["credit_paise"] for l in lines) == 200_000
    bank_line = next(l for l in lines if l["account_id"] == "COA-BANK")
    assert bank_line["credit_paise"] == 200_000         # money OUT ⇒ Cr Bank


def test_bank_txn_lines_zero_amount_rejected():
    with pytest.raises(ValueError):
        js.bank_txn_lines(debit_paise=0, credit_paise=0, account_id="A", bank_coa_account_id="B")


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_banking_foreign_firm_sees_no_accounts(monkeypatch):
    bk, db = _setup(monkeypatch)
    bk.create_bank_account(BankAccountIn(client_id="CLI", bank_name="HDFC", account_no="0001"), CALLER)
    assert bk.list_bank_accounts(client_id="CLI", current_user=OTHER)["data"] == []


def test_banking_foreign_firm_cannot_set_account(monkeypatch):
    bk, db = _setup(monkeypatch)
    _import_two(bk)
    txn_id = db.rows("bank_transactions")[0]["id"]
    # Isolation invariant: a foreign-firm caller cannot mutate the txn.
    #
    # This used to surface as a 500-class error rather than a 404: the guard read
    # in _get_txn assumed .single() returns empty on no-row, but PostgREST
    # .single() RAISES on 0 rows. The client-scope guard (_assert_txn_scope) now
    # runs first and does its own firm-scoped .limit(1) lookup, so the intended
    # 404 is what actually comes back. Isolation was never the problem; the error
    # contract was.
    with pytest.raises(HTTPException) as e:
        bk.set_transaction_account(txn_id, TransactionAccountIn(account_id="X"), OTHER)
    assert e.value.status_code == 404
    assert db.rows("bank_transactions")[0].get("account_id") is None   # untouched
