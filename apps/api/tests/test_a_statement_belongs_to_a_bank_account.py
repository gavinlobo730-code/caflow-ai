"""
BANK-22 — an imported statement names its bank account, and a line whose
statement does not is refused rather than posted somewhere plausible.

WHAT WAS WRONG

    `bank_account_id` was optional on both import doors — `StatementImportIn`
    and the `/statements/upload` form — and `bank_posting_service._resolve_bank`
    fell through, when it could not resolve one, to `resolve_payment_account`'s
    generic master "Bank" ledger.

    That fallback is the dangerous half. The entry balances, the trial balance
    foots, and the money is in the wrong bank sub-ledger: the account it
    belongs to never reconciles, the bank register's running balance is wrong
    for that account, and nothing on the journal says why. A refusal costs a
    re-import; a plausible posting costs a reconciliation nobody can close and
    a search for a difference that is not in the books.

    Nor is posting the only thing an unlinked statement breaks.
    `bank_reconciliation_service` has no account to reconcile, the bank
    register has no column to run a balance down, transfer detection cannot
    tell which account a line belongs to (`bank_transfer_service.
    _account_by_statement`), and `bank_column_mapping_service.find_mapping`
    returns None without one, so the CA re-maps the same layout every month.

WHAT IS NOT DONE, AND IS NAMED

    `bank_transactions` still has no `bank_account_id` column of its own — it
    is reached through `statement_id`. Denormalising it is a migration, a
    backfill and four read paths, and nothing here needs it: every stored line
    has a statement (`banking_service._import_core` is the only writer of the
    column) and every new statement now has an account.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.banking import StatementImportIn, StatementImportRow
from services.bank_posting_service import bank_posting_service
from tests.test_bank_posting import (          # the posting suite's own double
    FIRM, CLIENT, _db_with_accounts, _seed_txn, _lines_for, _patch,   # noqa: F401
)


def _row():
    return StatementImportRow(transaction_date="2026-04-01", description="x",
                              debit_paise=0, credit_paise=100, balance_paise=100)


# ── the door ──────────────────────────────────────────────────────────────────

def test_an_import_must_name_the_bank_account_it_is_for():
    with pytest.raises(ValidationError) as e:
        StatementImportIn(client_id="CLI", bank_name="HDFC", rows=[_row()])
    assert "bank_account_id" in str(e.value)


def test_a_blank_bank_account_is_not_an_answer():
    """A required `str` still accepts "" — which would create exactly the
    unlinked statement the field is required to prevent."""
    with pytest.raises(ValidationError) as e:
        StatementImportIn(client_id="CLI", bank_name="HDFC",
                          bank_account_id="   ", rows=[_row()])
    assert "bank account" in str(e.value)


def test_a_named_account_is_kept_and_trimmed():
    body = StatementImportIn(client_id="CLI", bank_name="HDFC",
                             bank_account_id=" ba-1 ", rows=[_row()])
    assert body.bank_account_id == "ba-1"


def test_the_upload_form_requires_it_too():
    """The two doors have to agree: the JSON import and the multipart upload
    both create a `bank_statements` row, and a field required on one and
    optional on the other is the door that stays open."""
    import inspect

    import routers.banking as bk

    param = inspect.signature(bk.upload_statement).parameters["bank_account_id"]
    assert param.annotation is str, "Optional[str] would let the upload skip it"
    # FastAPI turns `Form(...)` into a FieldInfo whose default is
    # PydanticUndefined; `Form(None)` leaves a real None there.
    assert param.default.is_required(), "Form(None) is not required"


# ── the posting ───────────────────────────────────────────────────────────────

def test_a_line_whose_statement_has_no_bank_account_is_refused():
    db = _db_with_accounts()
    _seed_txn(db, credit=100_000, category="Customer Payment", statement_id="stmt-1")
    db.store.setdefault("bank_statements", []).append(
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": None})

    with pytest.raises(HTTPException) as e:
        bank_posting_service.post(db, FIRM, "t1", actor_id="u1")
    assert e.value.status_code == 422
    assert "not linked to a bank account" in str(e.value.detail)
    assert not db.store.get("journal_lines"), "nothing may be posted to a guessed ledger"


def test_a_bank_account_with_no_ledger_of_its_own_is_refused_too():
    """Half-linked is not linked. The account exists and has no GL account, so
    there is still nothing to debit or credit."""
    db = _db_with_accounts()
    _seed_txn(db, credit=100_000, category="Customer Payment", statement_id="stmt-1")
    db.store.setdefault("bank_statements", []).append(
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": "ba-1"})
    db.store.setdefault("bank_accounts", []).append(
        {"id": "ba-1", "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": None})

    with pytest.raises(HTTPException) as e:
        bank_posting_service.post(db, FIRM, "t1", actor_id="u1")
    assert e.value.status_code == 422
    assert not db.store.get("journal_lines")


def test_a_linked_statement_posts_to_its_own_bank_ledger():
    """The control. The refusal must not be the only outcome, and the ledger it
    resolves has to be the ACCOUNT'S, not the firm's master Bank."""
    db = _db_with_accounts()
    _seed_txn(db, credit=100_000, category="Customer Payment", statement_id="stmt-1")
    db.store.setdefault("bank_statements", []).append(
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": "ba-1"})
    db.store.setdefault("bank_accounts", []).append(
        {"id": "ba-1", "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": "acc-bank2"})

    res = bank_posting_service.post(db, FIRM, "t1", actor_id="u1")
    dr = next(l for l in _lines_for(db, res["posted_journal_id"]) if l["debit_paise"])
    assert dr["account_id"] == "acc-bank2"


def test_an_explicitly_named_bank_ledger_still_wins():
    """The Post drawer sends the ledger the CA chose, and that is not affected
    by whether the statement carries a link."""
    db = _db_with_accounts()
    _seed_txn(db, credit=100_000, category="Customer Payment", statement_id="stmt-1")
    db.store.setdefault("bank_statements", []).append(
        {"id": "stmt-1", "firm_id": FIRM, "client_id": CLIENT, "bank_account_id": None})

    res = bank_posting_service.post(db, FIRM, "t1", bank_account_id="acc-bank", actor_id="u1")
    dr = next(l for l in _lines_for(db, res["posted_journal_id"]) if l["debit_paise"])
    assert dr["account_id"] == "acc-bank"
