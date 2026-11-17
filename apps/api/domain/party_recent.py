"""Which customers or suppliers a client has used most recently (POST-A-155).

THE PICKER PUTS THE PARTIES THIS CLIENT USED LAST AT THE TOP, AND THE ORDER IS READ FROM THE CLIENT'S OWN DOCUMENTS.
The combobox audit asked for recent-first customer and supplier pickers on the invoice and the bill; the HSN and
service-catalogue pickers had them and these did not, so a client with two hundred customers opened its invoice
picker in alphabetical order every time. The answer is derived, never stored: the newest documents of the client,
read in a bounded window (the answer is a handful of ids, so the read is sized to that and not to the ledger), each
party once, in the order of its most recent document. A carried-over opening document is not a use of the party in
this product (it was issued elsewhere), and a deleted one is not a use at all. Nothing is pre-selected: the list is
reordered and the person still chooses, because a party chosen for them is how an invoice goes to the wrong customer.
"""
from __future__ import annotations

from typing import Iterable

#: How many of the client's newest documents are read to find the recent parties.
WINDOW = 200
#: How many parties are offered at the top.
DEFAULT_LIMIT = 8


def recent_party_ids(rows: Iterable[dict], key: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Distinct `key` values in the order the rows come (newest first), skipping carried-over and deleted rows."""
    from domain.accounting.opening_documents import carried_over

    out: list[str] = []
    seen: set[str] = set()
    for r in rows or []:
        if carried_over(r) or r.get("deleted_at"):
            continue
        pid = r.get(key)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(str(pid))
        if len(out) >= limit:
            break
    return out


def read_recent(db, kind: str, firm_id: str, client_id: str, limit: int = DEFAULT_LIMIT) -> dict:
    """The recent party ids for one client: `kind` "customers" reads the sales invoices, "vendors" the purchase bills.

    Each table is named where the query is written, firm and client scoped, newest first, within WINDOW documents.
    """
    if kind == "customers":
        key = "customer_id"
        q = db.table("client_sales_invoices").select("id,customer_id,is_opening,deleted_at,created_at")
    elif kind == "vendors":
        key = "vendor_id"
        q = db.table("purchase_bills").select("id,vendor_id,is_opening,deleted_at,created_at")
    else:
        raise ValueError(f"no recent parties for {kind!r}")
    resp = (
        q.eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(WINDOW)
        .execute()
    )
    rows = resp.data or []
    return {"ids": recent_party_ids(rows, key, limit), "documents_read": len(rows), "window": WINDOW}
