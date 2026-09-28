"""Which hub tile has a firm-level WORKLIST, and what one row of it means.

── WHAT WAS WRONG (question G3) ─────────────────────────────────────────────

`domain/hub/tiles.py` fixes D1's fifteen and five of them carried
`firm_href=None`: Banking, Purchases, Fixed Assets, Inventory and Year-End had
no firm-level destination at all. Two of the five were WORSE than absent —
`/accounting/fixed-assets` and `/accounting/invoices` are
`MovedToClientWorkspace` tombstones, pages whose whole content is "this moved",
so a tile showing a real number and landing on one reads as a working screen.
`Tile.href_for` answers None rather than linking to either, which is honest and
still leaves a CA looking at "7 assets with depreciation outstanding" with
nowhere to click.

── AND THE TOMBSTONES ARE NOT AN OVERSIGHT, WHICH DECIDES THE SHAPE ─────────

`components/accounting/MovedToClientWorkspace.tsx` records a deliberate earlier
decision: *"firm-level accounting screens have been retired ... Accounting now
flows exclusively through the client workspace."* So the answer to G3 is NOT to
rebuild a firm-level Fixed Assets REGISTER — that is the duplicate those
tombstones exist to prevent. It is the other thing a bureau actually asks on
the 3rd of the month: **which of my clients needs work in this module.**

A worklist is a QUEUE, not a register. It answers with one row per client and
the tile's own figure beside it, and every row opens that client's own section
— which is the model the retirement decision set, reached in one click instead
of through a client list somebody has to remember to filter.

── THE SIGNAL IS THE TILE'S OWN, NEVER A SECOND DEFINITION ──────────────────

Each entry below names the `Tile` it breaks down, and the SQL function
`public.hub_client_worklist` transcribes that tile's predicate. Two definitions
of "a bank line still needing a person" is how a tile and the screen it opens
come to disagree about the number in between them, and a CA who clicks 7 and
counts 5 stops trusting both. `tests/test_the_firm_hub_tiles_land_somewhere.py`
holds the transcription against `services/hub_service`'s own vocabulary.

── AND A SIXTH THAT HAD A DESTINATION, WHICH WAS THE WRONG ONE ──────────────

`sales` was left out on the belief that `/accounting/receivables` already
answered it. It did not (accounting-hub-2-05): that screen reads
`fee_invoices` — what the clients owe the PRACTICE — while the tile sums
`client_sales_invoices`, what the clients' CUSTOMERS owe THEM. A client whose
customers owed it ₹19.9 crore showed ₹0 on the screen the tile's number sent
the CA to. So Sales gets the same queue Purchases has, at
`/accounting/invoices`, replacing the last `MovedToClientWorkspace` tombstone
the way the fixed-asset worklist replaced the other; `/accounting/receivables`
keeps its behaviour and now says whose receivables it holds (migration 432).

── FOUR OF THE FIVE, AND THE FIFTH IS REFUSED WITH ITS REASON ───────────────

`inventory` gets no worklist. Its tile already carries
`no_firm_signal_because`: what is at or below a reorder level is on-hand stock
against a per-item level, on-hand is a sum of ONE client's ledger, and there is
no firm-wide figure — so a worklist for it would be a list of client names with
a dash beside each, which is `/clients` with extra steps. A screen that cannot
carry the figure it exists to rank by is not a worklist.

The eight tiles that already HAVE a real firm screen get no worklist either,
and that is a scope decision rather than a judgement that one would be
useless: `/gst`, `/tds`, `/deadlines` and the rest are real destinations, and
giving each a second one is a navigation change nobody asked for. G3 is about
the five with none, and Sales is here because its one was the wrong screen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.hub.tiles import BY_ID, Tile, Unit


@dataclass(frozen=True)
class Worklist:
    """One module's firm-level queue.

    `tile_id` is the authority for the QUESTION and the UNIT — both are read
    off `domain/hub/tiles.TILES` rather than restated, so a tile whose question
    is reworded cannot leave its worklist describing the old one.
    """

    tile_id: str
    #: The static firm-level route. Under `/accounting/` deliberately: that is
    #: where the firm-level accounting screens have always lived, and a static
    #: route costs NONE of D10's dynamic redirect budget, which is the fact that
    #: made G3 cheap.
    href: str
    #: The column heading over the figure. Short, because the tile's own
    #: `question` is the subtitle and repeating it in the column is noise. It
    #: names what the figure IS — see the note on the Sales entry.
    column: str
    #: Which section of the client workspace a row opens — the tile's
    #: `client_section`, restated here only so this module can be read on its
    #: own; a test asserts the two agree.
    opens_section: str

    @property
    def tile(self) -> Tile:
        return BY_ID[self.tile_id]

    @property
    def label(self) -> str:
        return self.tile.label

    @property
    def question(self) -> str:
        return self.tile.question

    @property
    def unit(self) -> Unit:
        return self.tile.unit


WORKLISTS: tuple[Worklist, ...] = (
    Worklist(
        tile_id="banking",
        href="/accounting/banking",
        column="Lines to pass",
        opens_section="bank",
    ),
    Worklist(
        tile_id="sales",
        # REPLACES the `MovedToClientWorkspace` tombstone at this path, the
        # Sales half of the pair `fixed-assets` was the other half of — see the
        # module docstring for why the tile no longer opens
        # `/accounting/receivables`, which is the PRACTICE's fee receivables.
        href="/accounting/invoices",
        # ⚠️ "Outstanding", NOT "Overdue", although the tile's question says
        # overdue: the figure is every live invoice with a balance, due or not,
        # and a column heads a number. Purchases carries the same figure under
        # "Overdue"; which of the two words the tiles should use — or whether
        # they should filter on `due_date` — is an open owner decision.
        column="Outstanding",
        opens_section="sales",
    ),
    Worklist(
        tile_id="purchases",
        href="/accounting/purchases",
        column="Overdue",
        opens_section="purchases",
    ),
    Worklist(
        tile_id="fixed_assets",
        # REPLACES the `MovedToClientWorkspace` tombstone at this exact path,
        # which is the point rather than a coincidence: the tombstone's own
        # message was "choose a client", and this is that sentence with the
        # clients that need choosing already listed.
        href="/accounting/fixed-assets",
        column="Assets to depreciate",
        opens_section="fixed-assets",
    ),
    Worklist(
        tile_id="year_end",
        href="/accounting/year-end",
        column="Engagements open",
        opens_section="year-end",
    ),
)

BY_TILE: dict[str, Worklist] = {w.tile_id: w for w in WORKLISTS}
BY_HREF: dict[str, Worklist] = {w.href: w for w in WORKLISTS}

#: Named rather than left as an absence. See the module docstring: a worklist
#: needs a figure to rank by, and this tile has none at firm scope.
NO_WORKLIST_BECAUSE: dict[str, str] = {
    "inventory": (
        "What is at or below its reorder level is a sum of one client's own "
        "stock ledger, so there is no firm-wide figure to rank clients by — "
        "a worklist here would be a list of names with a dash beside each. "
        "Open a client to see what needs reordering."
    ),
}


def worklist_for(tile_id: str) -> Optional[Worklist]:
    """The worklist for this tile, or None where there is deliberately none."""
    return BY_TILE.get(tile_id)


def firm_href_for(tile_id: str) -> Optional[str]:
    """Where this tile's FIRM hub sends a CA, worklist or otherwise.

    Asked by nothing today — `Tile.firm_href` is still the one field the hub
    reads, and the five worklists are written into it directly so the payload
    has one source. This exists so a caller wanting the worklist's own route
    does not reach for `BY_TILE[...]` and get a KeyError on the ten tiles
    that have none.
    """
    w = BY_TILE.get(tile_id)
    return w.href if w else BY_ID[tile_id].firm_href
