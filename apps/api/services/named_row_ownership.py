"""A document may only name a row of its own client (POST-A-338).

THE GAP
    Several documents carry the id of another row in their body: a Bill of Entry names a vendor and a purchase bill, a fixed asset
    names the bill it was bought on, a delivery challan names an order, a customer, a vendor and an invoice, a purchase order or
    a sales order names the party. The API reads and writes through the privileged client by firm and id, and the foreign key on
    each of those columns is not client-aware, so an id that belongs to a SIBLING client of the same firm was accepted and stored.
    The worst case was a Bill of Entry of client A naming client B's purchase bill: the carry-over then attached A's customs duty
    to B's bill, and so to B's stock cost.

WHAT THIS DOES
    One read per named row, under the firm AND the client, BEFORE anything is written. A row that is not there (another client's,
    another firm's, deleted or invented) is a 404 in the same words a missing row gets, so the answer does not say which it was.
    It asks nothing when no id is named or when there is no database (mock mode).

A MEMBER OF THE FIRM IS THE SAME QUESTION ONE LEVEL UP (POST-A-361, part 2)
    A request that names a person (an assignee, a reviewer, a capacity row's person) names a row of `users`, which belongs to the FIRM
    and not to a client. Where the column has a foreign key to `users` and a `firm_id` on its own table the database refuses a stranger
    since migration 566, in a failure the person cannot read; where the column is a bare uuid (`task_recurring_configs.assignee_id`,
    `fee_engagements.assigned_to`) nothing refused it at all. `member_is_the_firms` asks before anything is written and answers a
    stranger, a deleted member and an invented id in the same words. **ONE COLUMN IS KEYED TO THE OTHER ID.** Every person column above holds a
    `users.id`, except `leads.assigned_to`, whose foreign key is to `auth.users(id)` (migration 059; the production snapshot of 13-09-2026
    agrees): the value it can hold is a member's AUTH id, and a `users.id` there is refused by the database as a 500. A lead's assignee is asked
    with `member_auth_id_is_the_firms`, which reads `users.auth_user_id`; asking the first function there made every value unusable (an auth
    id answered 404, a `users.id` passed the check and failed the key).

WHAT IT DOES NOT DO
    It is the API's answer only. A writer that does not come through these routes (an import that builds rows itself, a SQL
    function) is not asked. Each table is spelled out in its own function and not read through a variable, because the column
    check in `tests/test_backend_columns_exist_pg.py` resolves no name and a read it cannot see is a read it cannot check.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from core.db_provider import privileged_for


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"That {what} was not found.")


def _named(row_id) -> Optional[str]:
    text = str(row_id).strip() if row_id is not None else ""
    return text or None


def _find(query) -> list:
    """The rows of one ownership lookup. A string that is not an id of the column's type (a UUID) makes PostgREST answer with a type error
    (SQLSTATE 22P02), which the route used to turn into a 500; a row that could never exist is a row that is not there, so it answers
    the way a missing row does. The check is made on the database's own answer and not in the helper's first line because the test
    suites use readable ids that are not UUIDs, and the production column's type is the only authority on what an id is."""
    try:
        return query.execute().data or []
    except Exception as exc:
        if _is_a_malformed_id(exc):
            return []
        raise


def _is_a_malformed_id(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or (exc.args[0].get("code") if exc.args and isinstance(exc.args[0], dict) else None)
    return str(code) == "22P02" or "invalid input syntax for type uuid" in str(exc)


def member_is_the_firms(db, firm_id: str, member_id) -> None:
    """404 "That team member was not found." unless `member_id` is a `users.id` of this firm that has not been deleted. Nothing named, nothing asked.

    Membership, not activity: a suspended member can still be named, as the task door has always allowed, because whether somebody may be
    assigned work is a staffing decision and not a tenancy one. A DELETED member (`users.deleted_at`) is not named: the task door's own
    lookup (`user_repo.find_by_id`) leaves them out, and a person who has been removed is not somebody to hand work to. The read is made with
    the privileged client and filtered by the id AND the firm, the same reasoning as the bank account below: the filter is the assertion."""
    named = _named(member_id)
    if db is None or named is None:
        return
    rows = _find(privileged_for(db).table("users").select("id").eq("id", named).eq("firm_id", firm_id)
                 .is_("deleted_at", None).limit(1))
    if not rows:
        raise _not_found("team member")


def member_auth_id_is_the_firms(db, firm_id: str, auth_user_id) -> None:
    """The same question for a column keyed to `auth.users(id)` (a lead's assignee): 404 unless `auth_user_id` is the auth id of a member of this
    firm who has not been deleted. Nothing named, nothing asked. A `users.id` is NOT an answer here: it is not an auth id, and the database
    would refuse it."""
    named = _named(auth_user_id)
    if db is None or named is None:
        return
    rows = _find(privileged_for(db).table("users").select("id").eq("auth_user_id", named).eq("firm_id", firm_id)
                 .is_("deleted_at", None).limit(1))
    if not rows:
        raise _not_found("team member")


def vendor_is_the_clients(db, firm_id: str, client_id: str, vendor_id) -> None:
    """404 "That vendor was not found." unless `vendor_id` is a vendor of this firm and this client. Nothing named, nothing asked."""
    named = _named(vendor_id)
    if db is None or named is None:
        return
    rows = _find(db.table("vendors").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("vendor")


def customer_is_the_clients(db, firm_id: str, client_id: str, customer_id) -> None:
    """404 "That customer was not found." unless `customer_id` is a customer of this firm and this client."""
    named = _named(customer_id)
    if db is None or named is None:
        return
    rows = _find(db.table("customers").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("customer")


def purchase_bill_is_the_clients(db, firm_id: str, client_id: str, bill_id) -> None:
    """404 "That bill was not found." (the words `purchase_cycle_service.bill_of_client` uses) unless the bill is this client's."""
    named = _named(bill_id)
    if db is None or named is None:
        return
    rows = _find(db.table("purchase_bills").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("bill")


def bank_account_is_the_clients(db, firm_id: str, client_id: str, bank_account_id) -> None:
    """404 "That bank account was not found." unless the bank account is this client's."""
    named = _named(bank_account_id)
    if db is None or named is None:
        return
    # A bank table is read with the privileged client, after the caller's firm and client are asserted (POST-A-339); the filter below
    # is that assertion, so the account has to be this firm's and this client's whoever is asking.
    rows = _find(privileged_for(db).table("bank_accounts").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("bank account")


def sales_invoice_is_the_clients(db, firm_id: str, client_id: str, invoice_id) -> None:
    """404 "That invoice was not found." unless the sales invoice is this client's."""
    named = _named(invoice_id)
    if db is None or named is None:
        return
    rows = _find(db.table("client_sales_invoices").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("invoice")


def client_document_is_the_clients(db, firm_id: str, client_id: str, document_id) -> None:
    """404 "That document was not found." unless the stored file (`client_documents`) is this client's."""
    named = _named(document_id)
    if db is None or named is None:
        return
    # The document tables are read with the privileged client, after the caller's firm and client are asserted (POST-A-339, the same
    # reasoning as the bank account above): the filter is the assertion.
    rows = _find(privileged_for(db).table("client_documents").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("document")


def journal_entry_is_the_clients(db, firm_id: str, client_id: str, journal_entry_id) -> None:
    """404 "That journal entry was not found." unless the ledger entry is this client's."""
    named = _named(journal_entry_id)
    if db is None or named is None:
        return
    rows = _find(db.table("journal_entries").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("journal entry")
