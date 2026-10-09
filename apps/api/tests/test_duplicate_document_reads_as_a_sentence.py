"""
A repeated document number reaches the CA as a sentence, not an index name.

These indexes already existed — two tabs recording the same invoice twice was
already impossible. What did not work was the SENTENCE. Postgres answers a
unique violation by naming the index, so the CA whose second tab lost the race
was told

    This record already exists. duplicate key value violates unique constraint
    "ux_sales_invoice_no_per_client"

which is complete, correct, and reads as a crash. The guard is only useful if
the refusal says what to do about it.
"""
from __future__ import annotations

import pytest

from core.exceptions import duplicate_document, unhandled_failure


class _PgError(Exception):
    """The shape supabase-py raises: one dict arg carrying code and message."""
    def __init__(self, code: str, message: str):
        super().__init__({"code": code, "message": message})


def _dup(index: str) -> _PgError:
    return _PgError("23505", f'duplicate key value violates unique constraint "{index}"')


@pytest.mark.parametrize("index, must_say", [
    ("client_sales_invoices_firm_client_invoice_no_live_key", "invoice"),
    ("uq_purchase_bills_vendor_invoice", "vendor"),
    ("receipts_firm_client_receipt_no_key", "receipt"),
    ("credit_notes_firm_client_credit_note_no_key", "credit note"),
    ("sales_debit_notes_firm_id_debit_note_no_key", "debit note"),
    ("purchase_payments_firm_payment_no_key", "payment"),
    ("debit_notes_firm_client_debit_note_no_key", "debit note"),
    ("uq_client_sales_invoices_recurring", "recurring"),
    ("bank_accounts_client_id_account_no_key", "bank account"),
    ("chart_of_accounts_firm_code_unique", "code"),
    ("chart_of_accounts_firm_id_client_id_account_code_key", "code"),
    ("chart_of_accounts_firm_name_unique", "name"),
])
def test_each_index_has_its_own_sentence(index, must_say):
    said = duplicate_document(_dup(index))
    assert said and must_say in said.lower()
    assert index not in said and "constraint" not in said, \
        "the index name must not reach the CA"


def test_the_invoice_message_says_what_to_do_about_it():
    """"Already exists" alone leaves a CA staring at the form. The index is partial on
    deleted_at, so delete-and-re-enter is the way out and the sentence says so."""
    said = duplicate_document(_dup("client_sales_invoices_firm_client_invoice_no_live_key"))
    assert "different number" in said and "delete" in said.lower()


def test_it_is_a_409_and_not_a_500():
    """A duplicate is the caller asking for something the database refuses, not
    a server fault, and 500 would invite a retry that cannot succeed."""
    status, text = unhandled_failure(_dup("receipts_firm_client_receipt_no_key"))
    assert status == 409
    assert "receipt" in text.lower()


def test_an_unrelated_unique_violation_keeps_the_generic_sentence():
    """Only the listed indexes have one unambiguous meaning. Anything else gets
    the generic wording rather than a guess."""
    assert duplicate_document(_dup("ux_something_else")) is None
    status, text = unhandled_failure(_dup("ux_something_else"))
    assert status == 409 and "already exists" in text.lower()


def test_a_failure_that_is_not_a_duplicate_says_nothing_here():
    assert duplicate_document(_PgError("23503", "violates foreign key")) is None
    assert duplicate_document(ValueError("nothing to do with the database")) is None


# ── a ledger refused by the chart of accounts (PRE-A-001) ────────────────────
#
# Creating a ledger from inside a voucher with a code another ledger held showed
# the CA "Could not create the account: duplicate key value violates unique
# constraint chart_of_accounts_firm_id_client_id_account_code_key", because no
# chart_of_accounts index was in the table. Production holds three unique
# indexes there and two of them are keyed on the FIRM, so the ledger that refused
# the code or the name may be a firm-level account or another client's.

import json
from pathlib import Path

from fastapi import HTTPException

from core.exceptions import document_failure_detail

CHART_INDEXES = (
    "chart_of_accounts_firm_code_unique",
    "chart_of_accounts_firm_id_client_id_account_code_key",
    "chart_of_accounts_firm_name_unique",
)


def test_the_chart_indexes_named_here_are_the_ones_production_holds():
    """The names are read off the production snapshot, not remembered: a sentence
    keyed on an index nothing creates is a sentence that is never said."""
    guards = json.loads(
        (Path(__file__).parent / "fixtures" / "production_guards_2026-09-03.json").read_text())
    unique = {k.split(".", 1)[1] for k, v in guards["constraint"].items()
              if k.startswith("chart_of_accounts.") and v.get("detail") == "u"}
    assert set(CHART_INDEXES) == unique, (
        "production's unique constraints on chart_of_accounts changed; "
        "core.exceptions._DUPLICATE_DOCUMENT must say what each now means")


def test_every_unique_index_on_the_chart_has_a_sentence():
    for index in CHART_INDEXES:
        assert duplicate_document(_dup(index)), index


def test_a_taken_code_and_a_taken_name_are_told_apart():
    code = duplicate_document(_dup("chart_of_accounts_firm_code_unique"))
    name = duplicate_document(_dup("chart_of_accounts_firm_name_unique"))
    assert code != name
    assert code.startswith("An account with this code")
    assert name.startswith("An account with this name")
    # both code indexes mean the same thing to the CA
    assert duplicate_document(_dup("chart_of_accounts_firm_id_client_id_account_code_key")) == code


def test_the_sentence_says_the_firm_and_not_only_this_clients_chart():
    """Two of the three indexes are keyed on the firm, so the ledger that refused
    a code may be a firm-level account every client shares or another client's;
    "unique within this client" would send the CA to look in the wrong chart."""
    for index in CHART_INDEXES:
        said = duplicate_document(_dup(index))
        assert "whole firm" in said and "another client" in said, said
        assert "select the existing account" in said.lower(), said
        assert "this client's chart" not in said


def test_the_account_door_shows_the_sentence_and_not_the_index():
    for index in CHART_INDEXES:
        said = document_failure_detail(_dup(index), action="create the account")
        assert said == duplicate_document(_dup(index))
        assert "Could not create the account" not in said
        assert index not in said and "duplicate key" not in said


def test_creating_an_account_over_a_taken_code_answers_422_with_the_sentence(monkeypatch):
    """The route, not just the table: POST /api/accounting/accounts."""
    from models.accounting import AccountIn
    from routers import accounting

    class _Query:
        def insert(self, *_a, **_k):
            return self

        def execute(self):
            raise _dup("chart_of_accounts_firm_id_client_id_account_code_key")

    class _Db:
        def table(self, name):
            assert name == "chart_of_accounts"
            return _Query()

    monkeypatch.setattr(accounting, "_prod_db", lambda: _Db())
    monkeypatch.setattr(accounting, "assert_client_access", lambda *_a, **_k: None)
    with pytest.raises(HTTPException) as caught:
        accounting.create_account(
            AccountIn(name="Office Rent", code="5100", account_type="Expense"),
            client_id="c-1", current_user={"firm_id": "f-1", "role": "Partner"})
    assert caught.value.status_code == 422
    assert caught.value.detail == duplicate_document(_dup("chart_of_accounts_firm_code_unique"))
    assert "duplicate key" not in caught.value.detail


def test_the_ledger_dialog_promises_the_scope_the_database_holds():
    """The hint under the Code box used to read "Unique within this client's chart",
    which is false for a firm-keyed index. It is held from THIS side because the
    scope is the database's fact, and a guard written in apps/web would assert the
    dialog against a copy of itself."""
    import re
    source = (Path(__file__).resolve().parents[2] / "web" / "components" / "journal"
              / "QuickAddLedger.tsx").read_text()
    hint = re.search(r'label="Code"[^>]*\bhint="([^"]+)"', source)
    assert hint, "the Code field no longer carries a hint"
    text = hint.group(1).lower()
    assert "firm" in text and "within this client" not in text, hint.group(1)
