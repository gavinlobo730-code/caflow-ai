"""
Where the practice's fee revenue is read from, and the sentence that says so (POST-B-193, the readers' first repoint).

WHAT WAS WRONG. The firm bills its clients in two places. The earlier one is the fee tables (`fee_invoices`, the screen now
called "Earlier fee bills"), which post nothing to any ledger. The surviving one, decided on 20 November 2026, is the
practice's own books: a billing schedule prepares a sales invoice on the practice's own client, it is issued, and it reaches
the general ledger and the firm's own GSTR-1. Profitability, fee concentration and realization read the EARLIER tables only,
so a fee billed the surviving way was revenue in the firm's books and nothing on the screen that judges which client pays.

WHAT THIS MODULE DECIDES, and it decides nothing about a database.

  * A FEE IN THE PRACTICE'S BOOKS IS THE TAXABLE VALUE OF ITS DOCUMENTS, NET OF CREDIT AND DEBIT NOTES. The figure per
    customer is `public.report_party_totals` (migrations 745 and 766) asked for the practice's own client and the window:
    the same rule, and the same function, as the firm Reports page's P&L Statement, so the two cannot disagree. It is
    before GST by construction, which is the definition `domain/practice/profitability` already holds for the earlier bills.
  * A CUSTOMER IS A CLIENT ONLY THROUGH ITS LINK. Guardrail G3 gives each client the firm bills exactly one customer in
    the practice's books (`client_firm_customer_links`). A customer with a link is that client's fee. A customer with NO
    link is not a client of the firm (the practice may sell an old laptop), so its total is in no client's revenue and is
    NAMED beside the figures, never dropped silently and never guessed onto a client.
  * A CLIENT'S NET CAN BE NEGATIVE in a window that holds a credit note and not its invoice. It is carried as it is: the
    profitability rule already treats revenue at or below nil as "no margin", and concentration leaves it out of shares.
  * ONE ROW PER CLIENT, IN THE SHAPE THE EARLIER ROWS HAVE, so the three rules downstream read both without a second
    code path. A books row names no engagement (a billing schedule is not a fee engagement), so realization, which is
    judged per engagement, names these fees beside its ratio and leaves them out of it, as it always has for an invoice
    that names no engagement.

THE SENTENCES are computed from the rows AFTER the caller's own narrowing, so a member assigned to some clients is told the
split of their own book and not the firm's. The unlinked figure belongs to no client and is told to a firm-wide caller only.

All arithmetic is whole paise. No statutory figure is held here.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from domain.money_sentence import rupee_text

#: Which of the two places a revenue row was read from. Carried on every row.
SOURCE_EARLIER = "earlier_fee_bills"
SOURCE_BOOKS = "practice_books"

#: The practice's own books were read (they may hold nothing in the window), or the firm has no practice client yet.
BOOKS_READ = "read"
BOOKS_NOT_SET_UP = "not_set_up"

#: The status word a books row carries. The documents behind it are already the counted ones (issued, part-paid or paid,
#: and issued or applied notes): `report_party_totals` chose them, and this is the earlier tables' word for "counts".
COUNTED_STATUS = "Issued"


def tagged(rows: Iterable[Mapping], source: str) -> list[dict]:
    return [{**r, "source": source} for r in rows]


def books_rows(revenue_lines: Iterable[Mapping], client_of_customer: Mapping[str, str],
               period_end: str) -> tuple[list[dict], int, int]:
    """`(rows, unlinked_paise, unlinked_customers)` from the practice's own revenue lines.

    `revenue_lines` is the `revenue` list of `party_totals` (one line per customer: `party_id`, `total_paise`,
    `documents`). `client_of_customer` maps a customer in the practice's books to the client it is (G3). A line with no
    party at all (a document that names no customer) is unlinked like any other customer nobody linked."""
    by_client: dict[str, list[int]] = {}
    unlinked_paise = 0
    unlinked_customers = 0
    for line in revenue_lines:
        total = int(line.get("total_paise") or 0)
        party = line.get("party_id")
        client_id = client_of_customer.get(str(party)) if party else None
        if not client_id:
            unlinked_paise += total
            unlinked_customers += 1
            continue
        slot = by_client.setdefault(str(client_id), [0, 0])
        slot[0] += total
        slot[1] += int(line.get("documents") or 0)
    rows = [
        {
            "id": f"practice-books:{client_id}",
            "client_id": client_id,
            "engagement_id": None,
            "status": COUNTED_STATUS,
            # The window's last day: the figure is the window's net, not one document's, and every reader has already
            # chosen the window. Nothing downstream buckets by this date.
            "invoice_date": period_end,
            "amount_paise": total,
            "documents": documents,
            "source": SOURCE_BOOKS,
        }
        for client_id, (total, documents) in sorted(by_client.items())
    ]
    return rows, unlinked_paise, unlinked_customers


def split(rows: Iterable[Mapping]) -> dict[str, int]:
    """What each place contributed to the rows given: `{earlier_fee_bills_paise, practice_books_paise}`. A row with no
    source is an earlier bill (the shape before this module)."""
    earlier = books = 0
    for r in rows:
        amount = int(r.get("amount_paise") or 0)
        if r.get("source") == SOURCE_BOOKS:
            books += amount
        else:
            earlier += amount
    return {"earlier_fee_bills_paise": earlier, "practice_books_paise": books}


def _rs(paise: int) -> str:
    """A rupee figure for a sentence, by the one function that writes one: the sign goes before the unit, so a net below
    nil reads "minus ₹200.00" and never "₹-200.00"."""
    return rupee_text(paise, "₹")


#: Which answer a sentence is for. The three are drawn on one screen, so each says only what is true of ITS figures and
#: the split in rupees is said once, beside the profitability figures.
FOR_PROFITABILITY = "profitability"
FOR_CONCENTRATION = "concentration"
FOR_REALIZATION = "realization"


def sentences(rows: Iterable[Mapping], books_state: str, *, view: str, unlinked_paise: Optional[int] = None,
              unlinked_customers: int = 0) -> list[str]:
    """What the revenue behind these figures was read from, in words a Partner reads beside them.

    `rows` are the rows the figures were made from (after the caller's narrowing). `unlinked_paise` is None for a caller
    who is not firm-wide: a fee that belongs to no client is not theirs to be told."""
    if view not in (FOR_PROFITABILITY, FOR_CONCENTRATION, FOR_REALIZATION):
        raise ValueError(f"no such answer: {view!r}")
    not_set_up = books_state == BOOKS_NOT_SET_UP
    if view == FOR_CONCENTRATION:
        return ["The fees counted are the earlier fee bills alone: the firm's own books are not set up."] if not_set_up else [
            "The fees counted are the fee bills in the firm's own books, before GST and after credit and debit notes, "
            "together with the earlier fee bills."]
    if view == FOR_REALIZATION:
        return [] if not_set_up else [
            "A fee bill in the firm's own books names no engagement, so realization, which is judged per engagement, "
            "names those fees beside its ratio and leaves them out of it."]
    parts = split(rows)
    earlier, books = parts["earlier_fee_bills_paise"], parts["practice_books_paise"]
    out: list[str] = []
    if not_set_up:
        out.append(
            "The firm's own books are not set up, so revenue here is the earlier fee bills alone. Fees billed from "
            "My practice will be counted once its books exist.")
    else:
        out.append(
            f"Revenue is read from two places: {_rs(books)} from the fee bills in the firm's own books (My practice), "
            f"taken before GST and after credit and debit notes, and {_rs(earlier)} from the earlier fee bills. A fee "
            "entered in both places would be counted twice.")
    if unlinked_paise is not None and unlinked_customers > 0:
        out.append(
            f"{_rs(unlinked_paise)} billed in the firm's own books to {unlinked_customers} "
            f"{'customer that is' if unlinked_customers == 1 else 'customers that are'} not one of the firm's clients "
            "is in no client's revenue and is left out of every figure here.")
    return out


def summary(rows: Iterable[Mapping], books_state: str, *, unlinked_paise: Optional[int] = None,
            unlinked_customers: int = 0) -> dict:
    """The same facts as `sentences`, as figures, for a screen that wants to draw them."""
    return {
        **split(rows),
        "practice_books": books_state,
        # None, not 0, for a caller who is not told (see `sentences`).
        "unlinked_paise": unlinked_paise,
        "unlinked_customers": unlinked_customers if unlinked_paise is not None else None,
    }
