"""What a hub tile ASKS, in what unit, and which tiles nobody can answer.

Decision D1 fixes the hub at fifteen tiles and 2.2's DONE WHEN is the hard
part: *every tile shows a real figure or a real count; none is a stub.* This
module is the authority for what "a real figure" MEANS per tile. It holds no
database handle and runs no query — `services/hub_service.py` fetches, and the
screen renders. The split matters because the question a tile asks is a product
judgement that should be reviewable on its own, and because two screens (firm
level and client level) ask the same fifteen questions at different scopes.

── THE SIGNAL IS WHAT NEEDS DOING, NOT WHAT EXISTS ──────────────────────────

A tile reading "1,284 invoices" tells a CA nothing they will act on. Every
signal here is an OUTSTANDING count or amount: returns not yet filed, bank
lines not yet passed, bills past their limit, months not yet depreciated. A
hub whose tiles are all zero is a practice with nothing to do, which is the
only reading that makes the number worth putting on a tile at all.

That also fixes the DIRECTION: **lower is better, everywhere**, so one visual
rule serves all fifteen and a CA never has to remember which way a tile reads.

── TWO TILES HAVE NO SIGNAL AND SAY SO ──────────────────────────────────────

`insights` and `reports` are DESTINATIONS rather than queues: nothing is
outstanding on a report, and the Insights tile's own contents are Phase 3a.
They carry `signal=None` with a reason, and the screen renders that reason
instead of a number.

This is deliberately NOT a zero. `domain/gst/gstr3b_computer`'s rule about a
nil on a return applies here word for word: a nil meaning *there is nothing to
do* and a nil meaning *nobody can tell* are different facts, and a tile showing
"0" for the second is the stub 2.2 exists to forbid. A test asserts the two
states are distinguishable in the payload, so a frontend cannot collapse them.

── THE UNIT IS PART OF THE QUESTION ─────────────────────────────────────────

`COUNT` is a number of things; `PAISE` is money and the browser formats it the
Indian way (`lib/money/format.ts`). A tile may not switch unit by scope or by
value — "₹4.2L overdue" at firm level and "3 invoices" at client level would be
two different tiles wearing one name.

── SCOPE ────────────────────────────────────────────────────────────────────

Every tile answers at BOTH scopes, and `client_scoped=False` marks the three
that are facts about the FIRM rather than about a client (its own compliance
calendar, its documents, its insights). At client scope those render their
client-level equivalent where one exists and are omitted where one does not —
the service decides that, since it is the thing that knows what it fetched.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Unit(str, Enum):
    """What a tile's number IS. Never inferred from the value."""

    COUNT = "count"
    PAISE = "paise"


@dataclass(frozen=True)
class Tile:
    """One hub tile's identity and the question it asks.

    `question` is written for a CA, in the words they would use, because it is
    what the screen shows under the number — a tile that says "12" over
    "Returns not filed" is actionable and one that says "12" over "GST" is not.
    """

    id: str
    label: str
    #: The FIRM-level screen, or None where this module has none. Four of the
    #: five that had none now hold a WORKLIST — one row per client with this
    #: tile's own figure beside it; `domain/hub/worklist.py` is the authority
    #: for which, and why `inventory` is still None. See
    #: MODULES_WITH_NO_FIRM_SCREEN.
    firm_href: Optional[str]
    #: The first segment under `/clients/:id/`, or None for a firm-only tile.
    #: The client href is DERIVED from it rather than stored, the same rule
    #: `lib/workspace/clientPath.switchClientPath` applies: one segment, and
    #: every one of them has its own landing page.
    client_section: Optional[str]
    question: str
    unit: Unit
    #: None where the tile is a destination rather than a queue. The reason is
    #: rendered in place of a figure; see the module docstring.
    no_signal_because: Optional[str] = None
    #: Set where the tile HAS a figure for one client and none for the firm.
    #: `inventory` is the only one: what is at or below its reorder level is
    #: on-hand stock against a per-item level, and on-hand is a sum of
    #: `inventory_stock_ledger` deltas PER CLIENT — there is no firm-wide
    #: aggregate, and computing one would be a read per client per item, which
    #: is the reporting rule's own definition of a query proportional to the
    #: ledger rather than to the answer.
    no_firm_signal_because: Optional[str] = None
    #: False where the question is about the FIRM and has no per-client form.
    client_scoped: bool = True

    @property
    def answerable(self) -> bool:
        """At any scope. `answerable_at` is the per-scope question."""
        return self.no_signal_because is None

    def answerable_at(self, client_id: Optional[str]) -> bool:
        if not self.answerable:
            return False
        return not (client_id is None and self.no_firm_signal_because)

    def why_no_signal(self, client_id: Optional[str]) -> Optional[str]:
        if self.no_signal_because:
            return self.no_signal_because
        if client_id is None and self.no_firm_signal_because:
            return self.no_firm_signal_because
        return None

    def href_for(self, client_id: Optional[str]) -> Optional[str]:
        """Where this tile goes at this scope, or None if nowhere yet.

        A firm hub's tile for a client-only module answers None rather than
        linking to a `MovedToClientWorkspace` TOMBSTONE — a page whose whole
        content is "this moved". Sending a CA there from a tile showing a real
        number is worse than a dead link: the number says the tile works.
        `/accounting/fixed-assets` WAS one of those and is now the fixed-asset
        worklist; `inventory` is the one tile still answering None here, with
        `worklist.NO_WORKLIST_BECAUSE` giving the reason.
        """
        if client_id is None:
            return self.firm_href
        return f"/clients/{client_id}/{self.client_section}/" if self.client_section else None


#: D1's fifteen, in D1's order. The order is the reading order of a CA's day —
#: what is due, then what the practice knows, then the transaction modules,
#: then the statutory ones, then the registers, then the year end.
TILES: tuple[Tile, ...] = (
    Tile(
        id="compliance",
        label="Compliance Calendar",
        firm_href="/deadlines",
        client_section="tasks",
        question="Obligations due and not yet filed",
        unit=Unit.COUNT,
    ),
    Tile(
        id="insights",
        label="Insights",
        # ⚠️ WAS `/health`, WHICH IS ONE OF THE THREE THINGS THIS TILE NAMES.
        # `/health` is a client HEALTH monitor; the tile asks about health,
        # risk AND profitability, so two thirds of its own question had
        # nowhere to land. `/insights` (Phase 3a-5) renders the
        # recommendations, the compliance risk and the relationship health;
        # profitability is a question about the PRACTICE rather than a client
        # and sits with the rest of its commercial position at
        # `/practice/profitability`, which the Insights page links to rather
        # than duplicating.
        firm_href="/insights",
        client_section=None,
        question="Health, risk and profitability",
        unit=Unit.COUNT,
        no_signal_because=(
            "Insights is a destination, not a queue — there is nothing "
            "outstanding on an analysis."
        ),
        client_scoped=False,
    ),
    Tile(
        id="gst",
        label="GST",
        firm_href="/gst",
        client_section="compliance",
        question="Returns prepared and not yet filed",
        unit=Unit.COUNT,
    ),
    Tile(
        id="banking",
        label="Banking",
        firm_href="/accounting/banking",
        client_section="bank",
        question="Statement lines not yet passed",
        unit=Unit.COUNT,
    ),
    Tile(
        id="accounting",
        label="Accounting",
        firm_href="/accounting",
        client_section="accounting",
        question="Journals still in draft",
        unit=Unit.COUNT,
    ),
    Tile(
        id="sales",
        label="Sales",
        firm_href="/accounting/receivables",
        client_section="sales",
        question="Overdue from customers",
        unit=Unit.PAISE,
    ),
    Tile(
        id="purchases",
        label="Purchases",
        firm_href="/accounting/purchases",
        client_section="purchases",
        question="Overdue to suppliers",
        unit=Unit.PAISE,
    ),
    Tile(
        id="tds",
        label="TDS",
        firm_href="/tds",
        client_section="compliance",
        question="Deducted and not yet deposited",
        unit=Unit.PAISE,
    ),
    Tile(
        id="payroll",
        label="Payroll",
        firm_href="/payroll",
        client_section="payroll",
        question="Runs not yet released",
        unit=Unit.COUNT,
    ),
    Tile(
        id="income_tax",
        label="Income Tax",
        firm_href="/income-tax",
        client_section="tax",
        question="Returns not yet filed",
        unit=Unit.COUNT,
    ),
    Tile(
        id="fixed_assets",
        label="Fixed Assets",
        firm_href="/accounting/fixed-assets",
        client_section="fixed-assets",
        question="Assets with depreciation outstanding",
        unit=Unit.COUNT,
    ),
    Tile(
        id="inventory",
        label="Inventory",
        firm_href=None,
        client_section="inventory",
        question="Items at or below their reorder level",
        unit=Unit.COUNT,
        no_firm_signal_because=(
            "On-hand stock is a sum of one client's own ledger, so there is "
            "no firm-wide figure to show — open a client to see what needs "
            "reordering."
        ),
    ),
    Tile(
        id="year_end",
        label="Year-End",
        firm_href="/accounting/year-end",
        client_section="year-end",
        question="Engagements not yet finalised",
        unit=Unit.COUNT,
    ),
    Tile(
        id="reports",
        label="Reports",
        firm_href="/reports",
        client_section=None,
        question="Financial statements and registers",
        unit=Unit.COUNT,
        no_signal_because=(
            "A report is a destination, not a queue — nothing is "
            "outstanding on one, and a count of available reports is a fact "
            "about this product rather than about the practice."
        ),
        client_scoped=False,
    ),
    Tile(
        id="documents",
        label="Documents",
        firm_href="/documents",
        client_section="documents",
        question="Documents awaiting review",
        unit=Unit.COUNT,
    ),
)


#: Modules with NO firm-level screen. It was FIVE when it was measured on
#: 24-09-2026 while writing the href guard — Banking, Purchases, Fixed Assets,
#: Inventory and Year-End — with two of them landing on a
#: `MovedToClientWorkspace` TOMBSTONE, which is worse than absent: a tile
#: showing a real number and landing on "this moved" reads as a working
#: destination. That was question G3, and D22 answers it: four of the five got
#: a firm-level WORKLIST (one row per client, this tile's own figure beside
#: it), taking the recommendation's own shape — a roll-up rather than a
#: rebuilt register, which is what the tombstones' retirement decision allows.
#: A firm-level route is STATIC, so all four cost ZERO of D10's dynamic
#: redirect rules.
#:
#: `inventory` remains, and `domain/hub/worklist.NO_WORKLIST_BECAUSE` holds the
#: reason: there is no firm-wide figure to rank clients by.
MODULES_WITH_NO_FIRM_SCREEN: tuple[str, ...] = ("inventory",)

BY_ID: dict[str, Tile] = {t.id: t for t in TILES}

#: Rendered on every hub, firm level and client level alike. A CA looking at
#: fifteen numbers needs to know what they have in common before they can read
#: any of them.
LOWER_IS_BETTER = (
    "Every figure is what is still outstanding, so zero is the finished state "
    "on every tile."
)


def tiles_for_scope(client_id: Optional[str]) -> tuple[Tile, ...]:
    """The tiles a hub at this scope shows.

    A client hub drops the three firm-level questions rather than showing them
    with a firm-wide number beside one client's name, which would read as that
    client's figure. `insights` and `reports` are firm-level by construction
    (they carry no signal at all); `compliance` and `documents` exist at both
    scopes and stay.
    """
    if client_id is None:
        return TILES
    return tuple(t for t in TILES if t.client_scoped)


def describe(tile: Tile, signal: Optional[int], client_id: Optional[str] = None) -> dict:
    """One tile, ready to render — the shape the endpoint serves.

    `signal` is None for BOTH of the two reasons a tile can have no number,
    and the payload tells them apart with `answerable`: False means nobody can
    compute it and `no_signal_because` says why; True with a null signal means
    the fetch for that one tile FAILED, which is a third state and is the
    service's to report. A tile that genuinely has nothing outstanding carries
    0, not null.
    """
    ok = tile.answerable_at(client_id)
    return {
        "id": tile.id,
        "label": tile.label,
        "href": tile.href_for(client_id),
        "question": tile.question,
        "unit": tile.unit.value,
        "answerable": ok,
        "no_signal_because": tile.why_no_signal(client_id),
        "signal": signal if ok else None,
    }
