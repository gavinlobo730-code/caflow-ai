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
