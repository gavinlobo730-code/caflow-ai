"""A document line may only name a product or service of the document's own client (POST-A-246).

THE GAP
    `models/invoices.require_service_catalogue_id` only tests that the id is not blank, and the sales-invoice, purchase-bill
    and note routers copied a line's `service_catalogue_id` onto the stored row without asking whose item it was. A line
    naming a sibling client's item, or another firm's, was accepted: the invoice issued and posted revenue and GST, and the
    line moved no stock and posted no cost of goods, because the posting paths look the item up under the firm AND the client
    (the catalogue is the client's, POST-A-109) and an id that is not this client's resolves to nothing there. The only trace
    was a WARNING with a count. Nothing in production was wrong (read on 18-10-2026: 0 of 9,498 sales lines and 0 of 2,583
    purchase lines name an item of another client), so this closes a door before anyone walks through it.

WHAT THIS DOES
    One read of the items the document's lines name, under the firm and the client, BEFORE anything is written; any line whose
    item is not found there (another client's, another firm's, deleted, or not an id at all) is refused with a 422 that names
    the LINES by position. It is a read, not a write, and it asks nothing when no line names an item.

WHAT IT DOES NOT DO
    It does not filter on whether the item is still active: an archived item is still the client's, and a draft that names one
    must remain editable. It does not look at the document's other references (customer, vendor, original invoice), which each
    route already scopes. And it is the API's answer only: a writer that does not come through these routes (a SQL function, an
    import that builds rows itself) is not asked; the posting paths' own client-scoped lookup remains the second lock.
"""
from __future__ import annotations

from typing import Iterable, Mapping, NamedTuple, Optional

from fastapi import HTTPException


def _item_id(line) -> Optional[str]:
    value = line.get("service_catalogue_id") if isinstance(line, Mapping) else getattr(line, "service_catalogue_id", None)
    text = str(value).strip() if value is not None else ""
    return text or None


def assert_items_are_the_clients(db, firm_id: str, client_id: str, lines: Iterable,
                                 known: Optional[set] = None) -> None:
    """Refuse (422) a document whose lines name an item that is not this firm's and this client's.

    `lines` are the request's lines, as dicts or models. `db` is a client that can read `service_catalogue` (None in mock mode,
    which has no catalogue, and then nothing is asked). Names the offending lines by their 1-based position.

    `known` is a set the CALLER keeps across documents of one client (a bulk import): ids already found to be the client's
    are not asked again and each newly found one is added, so a batch costs one read per distinct item and not per invoice.
    Only ids that were FOUND are ever added, never a refused one."""
    if db is None:
        return
    named = [(n, _item_id(line)) for n, line in enumerate(lines, 1)]
    owned: set[str] = set(known) if known is not None else set()
    # Compared in lower case (a uuid column answers in lower case and a request may not), asked as typed.
    ids = sorted({text for _, text in named if text and text.lower() not in owned})
    if ids:
        rows = (db.table("service_catalogue").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id).in_("id", ids).execute().data) or []
        found = {str(r["id"]).lower() for r in rows}
        owned |= found
        if known is not None:
            known |= found
    refused = [n for n, text in named if text and text.lower() not in owned]
    if refused:
        many = len(refused) > 1
        raise HTTPException(
            status_code=422,
            detail=(f"{'Lines' if many else 'Line'} {', '.join(str(n) for n in refused)} "
                    f"{'name' if many else 'names'} a product or service that is not in this client's catalogue. "
                    "Pick one from this client's catalogue, or add it there first."))


class ItemOwner(NamedTuple):
    """Whose catalogue a builder's lines are checked against: a client to read it with, the firm, the client, and optionally
    the set a bulk import keeps. A line builder takes `owner=None` for "nothing to ask" (mock mode has no catalogue)."""
    db: object
    firm_id: str
    client_id: str
    known: Optional[set] = None

    @classmethod
    def live(cls, firm_id: str, client_id: str) -> "ItemOwner":
        """The owner read through the request's own database client."""
        from core.supabase_client import get_supabase
        return cls(get_supabase(), firm_id, client_id)


def check(owner: Optional[ItemOwner], lines: Iterable) -> None:
    """`assert_items_are_the_clients` for a builder that was handed an owner, and nothing for one that was not."""
    if owner is not None:
        assert_items_are_the_clients(owner.db, owner.firm_id, owner.client_id, lines, owner.known)
