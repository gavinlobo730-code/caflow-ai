"""
The practice's fee revenue for a window, read from both places it is billed (POST-B-193).

`domain/practice/fee_sources` is the rule and says why. This module fetches:

  * the earlier fee bills, by the one read every revenue figure already used (`invoice_repo.fee_revenue_rows`);
  * the fee bills in the practice's own books, as ONE answer per customer from `report_party_totals`
    (`report_transactions_service.party_totals`, the firm Reports page's own function), asked for the practice's own
    client. What crosses the wire is one line per customer, not a row per invoice, which is CLAUDE.md's reporting rule;
  * the links that say which customer is which client (`client_firm_customer_links`, one row per billed client, G3).

WHO IS ASKING is not this module's question. The three routes that call it are gated on the practice's fee economics
(`billing:read`, a Partner's) and narrow the rows to the caller's own clients before any figure is made; the practice's
books themselves stay the Partner's alone (G1), and nothing of them leaves here but a total per client. The privileged
client is used because `report_party_totals` is executable by the service role only, with the firm named in every read.
"""
from __future__ import annotations

from dataclasses import dataclass

from core import db_provider
from core.db_paging import fetch_all
from domain.practice import fee_sources
from repositories.invoice_repository import invoice_repo
from services import report_transactions_service
from services.internal_client_service import get_internal_client_id


@dataclass(frozen=True)
class FeeRevenue:
    #: Every revenue row of the window, both places, each carrying `source`.
    rows: list[dict]
    #: `fee_sources.BOOKS_READ` or `fee_sources.BOOKS_NOT_SET_UP`.
    books_state: str
    #: Billed in the practice's books to customers that are no client of the firm. In no row above.
    unlinked_paise: int
    unlinked_customers: int


def _links(db, firm_id: str) -> dict[str, str]:
    """`{customer in the practice's books: the client it is}` for the firm (G3: at most one per client)."""
    rows = fetch_all(
        lambda: (db.table("client_firm_customer_links").select("id, client_id, internal_customer_id")
                 .eq("firm_id", firm_id)),
        key="id", label="fee customer links",
    )
    return {str(r["internal_customer_id"]): str(r["client_id"])
            for r in rows if r.get("internal_customer_id") and r.get("client_id")}


def fee_revenue(firm_id: str, date_from: str, date_to: str) -> FeeRevenue:
    """Both places, for `date_from`..`date_to` inclusive. A failed read raises: half a revenue figure is not a figure."""
    earlier = fee_sources.tagged(invoice_repo.fee_revenue_rows(firm_id, date_from, date_to), fee_sources.SOURCE_EARLIER)

    db = db_provider.service_db_or_none()
    practice = get_internal_client_id(firm_id) if db is not None else None
    if db is None or not practice:
        return FeeRevenue(rows=earlier, books_state=fee_sources.BOOKS_NOT_SET_UP, unlinked_paise=0, unlinked_customers=0)

    totals = report_transactions_service.party_totals(
        db, firm_id, client_ids=[str(practice)], date_from=date_from, date_to=date_to)
    books, unlinked_paise, unlinked_customers = fee_sources.books_rows(
        totals.get("revenue") or [], _links(db, firm_id), date_to)
    return FeeRevenue(rows=[*earlier, *books], books_state=fee_sources.BOOKS_READ,
                      unlinked_paise=unlinked_paise, unlinked_customers=unlinked_customers)
