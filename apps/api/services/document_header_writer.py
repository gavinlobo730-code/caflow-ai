"""The one door through which the API writes a document header's settlement and status columns (ledger POST-A-331).

WHY THERE IS A DOOR
    The headers of an invoice, a bill and the four notes (`client_sales_invoices`, `purchase_bills`, `credit_notes`,
    `debit_notes`, `purchase_credit_notes`, `sales_debit_notes`) carry the columns that say what has been settled against a
    document (`paid_paise`, `credited_paise`, `debited_paise`, `debit_note_paise`, `credit_note_paise`), what state it is in
    (`status`) and which journal entry it posted (`journal_entry_id`). About a dozen API paths write them, and until now every
    one wrote as the CALLER: through the request's own client, so that a database rule asking "who is writing" could not tell
    the API's own settlement from a member's direct PostgREST call. A member who holds the accounting tier could therefore mark
    an invoice paid, cancel it or re-issue a cancelled one over PostgREST, and nothing at the database could refuse it without
    refusing the API too.

    The way out, in the order migrations 535 and 536 used, is to move the writers to the privileged client FIRST and to take the
    signed-in role's write away in a LATER change (the old API against a refusing database fails soft and wrong). This module
    is the first half for every writer that moves: a writer calls `update_header` and not `.table(...).update(...)`, and the
    guard `tests/test_the_document_header_writers_...` holds which modules have moved and which have not, so the list only
    shrinks.

WHAT THE DOOR DOES FOR A WRITER
    * It runs the statement on the privileged client where there is one, and on the caller's own where there is none (mock mode
      and a test double, as `domain.inventory_service.ledger_writer` does), so a test that patches the caller's client keeps
      seeing the statement.
    * The privileged client carries no row security, so the statement names the document's id, its firm AND its client itself
      (a document that is not this client's matches nothing, exactly as a document the caller could not see did), and a writer
      that hands it no firm or no client is refused with a ValueError before anything is sent. A compare-and-set guard rides
      along as `expect`.
    * It writes the audit row the database does not. Migration 111's capture trigger records a write only when `auth.uid()` is
      present, and a write by the privileged client has none, so the row-level record of the change that the trigger used to
      make for the signed-in writer (who changed the document's settled amounts or its status, from what) would otherwise
      vanish with the move. `audit_service.log_event` is non-fatal by design, so a failed audit write never undoes a settlement
      that has already happened; it is made only when the statement changed a row, so a compare-and-set that lost its race
      writes nothing.

WHAT IT DOES NOT DO
    It judges nothing. Whether a document may be credited, paid or cancelled is the route's rule and has already been asked by
    the time a writer calls this; the door only changes WHO the database sees writing and records that it happened.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from services import audit_service

#: The six header tables and the audit entity each one is recorded under (the name the documents' own routes already use).
ENTITY_OF = {
    "client_sales_invoices": "sales_invoice",
    "purchase_bills": "purchase_bill",
    "credit_notes": "credit_note",
    "debit_notes": "debit_note",
    "purchase_credit_notes": "purchase_credit_note",
    "sales_debit_notes": "sales_debit_note",
}
HEADER_TABLES = frozenset(ENTITY_OF)

#: The statement, one literal chain per table: the privileged client carries no row security, so the filters that confine an
#: UPDATE to this document, this firm and this client are the ONLY confinement it has, and the firm-scope reader
#: (`tests/test_every_query_on_a_firm_table_carries_its_firm_scope.py`) reads a chain only when the table is a literal. One
#: `.table(variable)` here would have been a blind spot over the very statement that most needs reading.
_START = {
    "client_sales_invoices": lambda w, values, doc, firm, client: (
        w.table("client_sales_invoices").update(values).eq("id", doc).eq("firm_id", firm).eq("client_id", client)),
    "purchase_bills": lambda w, values, doc, firm, client: (
        w.table("purchase_bills").update(values).eq("id", doc).eq("firm_id", firm).eq("client_id", client)),
    "credit_notes": lambda w, values, doc, firm, client: (
        w.table("credit_notes").update(values).eq("id", doc).eq("firm_id", firm).eq("client_id", client)),
    "debit_notes": lambda w, values, doc, firm, client: (
        w.table("debit_notes").update(values).eq("id", doc).eq("firm_id", firm).eq("client_id", client)),
    "purchase_credit_notes": lambda w, values, doc, firm, client: (
        w.table("purchase_credit_notes").update(values).eq("id", doc).eq("firm_id", firm).eq("client_id", client)),
    "sales_debit_notes": lambda w, values, doc, firm, client: (
        w.table("sales_debit_notes").update(values).eq("id", doc).eq("firm_id", firm).eq("client_id", client)),
}


def header_writer(request_db):
    """The client a header is WRITTEN with: the privileged one where there is one, the caller's own where there is no other
    (mock mode, a test double), and None staying None."""
    if not request_db:
        return request_db
    from core import db_provider
    return db_provider.service_db_or_none() or request_db


def update_header(
    request_db,
    table: str,
    doc_id: str,
    values: Mapping[str, Any],
    *,
    firm_id: str,
    client_id: str,
    actor: Optional[Mapping[str, Any]],
    expect: Optional[Mapping[str, Any]] = None,
    before: Optional[Mapping[str, Any]] = None,
    reason: Optional[str] = None,
):
    """UPDATE one document header, as the API and not as the caller, and record it.

    `expect` is a compare-and-set guard (every pair becomes an `.eq`). `before` is what the statement replaces, named by the
    writer that read it, and is stored as the audit row's old data; `reason` says why when the write is not the forward move
    (a rollback of a posting that failed). `actor` is the signed-in person's row (`auth_user_id` and `email` are read from it)
    or None for a system caller such as the scheduler or a webhook. Returns the response of the statement, whose `.data` is
    the updated rows (empty when the guard did not match)."""
    if table not in HEADER_TABLES:
        raise ValueError(f"{table} is not a document header this door writes")
    if not (doc_id and firm_id and client_id):
        raise ValueError(f"an update of {table} must name the document, its firm and its client")
    query = _START[table](header_writer(request_db), dict(values), doc_id, firm_id, client_id)
    for column, value in (expect or {}).items():
        query = query.eq(column, value)
    response = query.execute()
    if response.data:
        audit_service.log_event(
            firm_id, ENTITY_OF[table], str(doc_id), "update",
            actor_id=(actor or {}).get("auth_user_id"),
            actor_email=(actor or {}).get("email"),
            old_data=dict(before) if before is not None else None,
            new_data=dict(values),
            metadata={"source": "api", "table": table, **({"reason": reason} if reason else {})},
        )
    return response
