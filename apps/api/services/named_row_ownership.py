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


def vendor_is_the_clients(db, firm_id: str, client_id: str, vendor_id) -> None:
    """404 "That vendor was not found." unless `vendor_id` is a vendor of this firm and this client. Nothing named, nothing asked."""
    named = _named(vendor_id)
    if db is None or named is None:
        return
    rows = (db.table("vendors").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise _not_found("vendor")


def customer_is_the_clients(db, firm_id: str, client_id: str, customer_id) -> None:
    """404 "That customer was not found." unless `customer_id` is a customer of this firm and this client."""
    named = _named(customer_id)
    if db is None or named is None:
        return
    rows = (db.table("customers").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise _not_found("customer")


def purchase_bill_is_the_clients(db, firm_id: str, client_id: str, bill_id) -> None:
    """404 "That bill was not found." (the words `purchase_cycle_service.bill_of_client` uses) unless the bill is this client's."""
    named = _named(bill_id)
    if db is None or named is None:
        return
    rows = (db.table("purchase_bills").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise _not_found("bill")


def bank_account_is_the_clients(db, firm_id: str, client_id: str, bank_account_id) -> None:
    """404 "That bank account was not found." unless the bank account is this client's."""
    named = _named(bank_account_id)
    if db is None or named is None:
        return
    # A bank table is read with the privileged client, after the caller's firm and client are asserted (POST-A-339); the filter below
    # is that assertion, so the account has to be this firm's and this client's whoever is asking.
    rows = (privileged_for(db).table("bank_accounts").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise _not_found("bank account")


def sales_invoice_is_the_clients(db, firm_id: str, client_id: str, invoice_id) -> None:
    """404 "That invoice was not found." unless the sales invoice is this client's."""
    named = _named(invoice_id)
    if db is None or named is None:
        return
    rows = (db.table("client_sales_invoices").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise _not_found("invoice")
