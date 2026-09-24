"""
A customer's credit position — SALES-25 (b), migration 414.

The RULE is `domain/sales/credit_limit.py`. This fetches its three inputs and
nothing else: the limit recorded on the customer, whether the firm asked for a
block rather than a warning, and what the customer already has open.

WHAT IS ALREADY OPEN IS `outstanding_paise`, THE GENERATED COLUMN. Migration
278 made it `GENERATED ALWAYS ... STORED` precisely so the formula — which
carries the CGST s.34 note terms that `total - paid` omits — lives once, in the
schema. `GET /sales-invoices/outstanding` re-subtracts it in Python and gets
the same answer today; this does not, because two derivations of one figure is
how they come to disagree.

THE READ IS BOUNDED BY THE ANSWER. One customer's open documents, filtered in
the query rather than in Python, and only the one column summed — a screen
showing "Rs. 1,30,000 open" must not ship a customer's whole invoice history to
compute it.
"""
from __future__ import annotations

from typing import Optional

from domain.sales import credit_limit

#: A document in one of these statuses is not a receivable. `draft` was never
#: issued (no journal posted) and `cancelled` was withdrawn; `paid` has nothing
#: left open and would contribute zero anyway, and is excluded so the read is
#: as small as the answer. The same set `customer_statement_service` calls
#: _DEAD_INVOICE.
_NOT_A_RECEIVABLE = ("paid", "cancelled", "draft")


def outstanding_for_customer(db, firm_id: str, client_id: str,
                             customer_id: str) -> int:
    """What this customer currently has open, in integer paise."""
    rows = (db.table("client_sales_invoices")
            .select("outstanding_paise")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .eq("customer_id", customer_id)
            .not_.in_("status", list(_NOT_A_RECEIVABLE))
            .execute().data) or []
    return sum(int(r.get("outstanding_paise") or 0) for r in rows)


def firm_blocks(db, firm_id: str) -> bool:
    """Has the firm asked for a REFUSAL rather than a warning?

    Absent settings read as FALSE, which is the column's own default and the
    safe direction: a firm that has never opened the settings screen has not
    asked for anything to be refused.
    """
    rows = (db.table("invoice_settings")
            .select("credit_limit_blocks")
            .eq("firm_id", firm_id).limit(1).execute().data) or []
    return bool(rows[0].get("credit_limit_blocks")) if rows else False


def assess_invoice(db, firm_id: str, client_id: str, customer_id: str,
                   invoice_paise: int, *,
                   limit_paise: Optional[int] = None,
                   customer: Optional[dict] = None,
                   is_opening: bool = False) -> credit_limit.Assessment:
    """Where one invoice leaves the customer against their recorded limit.

    `customer` is the already-fetched row where the caller has one — the
    invoice create path resolves it for the state code anyway, and re-reading
    it here would be a second Singapore-to-Mumbai round trip per invoice on the
    bulk import path.
    """
    if limit_paise is None and customer is not None:
        limit_paise = customer.get("credit_limit_paise")
    if limit_paise is None:
        # Nobody recorded one. Answer without touching the ledger at all: the
        # outstanding figure changes nothing about a `not_set` answer, and a
        # query per invoice for a column no client has filled in yet is a read
        # the answer does not need.
        return credit_limit.assess(
            limit_paise=None, outstanding_paise=0, invoice_paise=invoice_paise)
    return credit_limit.assess(
        limit_paise=limit_paise,
        outstanding_paise=outstanding_for_customer(db, firm_id, client_id, customer_id),
        invoice_paise=invoice_paise,
        firm_blocks=firm_blocks(db, firm_id),
        is_opening=is_opening)
