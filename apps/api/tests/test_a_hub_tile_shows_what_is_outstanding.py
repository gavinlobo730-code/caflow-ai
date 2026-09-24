"""D1's fifteen tiles, and the rule that keeps a tile from being a stub.

Phase 2.2's DONE WHEN is *every tile shows a real figure or a real count; none
is a stub.* `domain/hub/tiles.py` is where that is decided, and this is where
it is held — including the two tiles that honestly have no figure, because the
difference between "nothing is outstanding" and "nobody can tell" is the whole
reason this product writes `table_4a_gaps` and `movement_gaps` and
`statutory_gaps`.

The href test is the one worth reading twice: a hub tile pointing at a route
that does not exist is worse than a missing tile, because it reads as a
working destination. It is asserted from the PYTHON side against the real
`apps/web/app` tree, the same way
`test_the_browser_can_open_the_document_the_ledger_names.py` does — a guard in
`apps/web` would assert the route list against a copy of itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.hub.tiles import (
    BY_ID, LOWER_IS_BETTER, MODULES_WITH_NO_FIRM_SCREEN, TILES, Tile, Unit,
    describe, tiles_for_scope,
)

WEB_APP = Path(__file__).resolve().parents[3] / "apps" / "web" / "app"

#: D1, verbatim, in D1's order. Written out rather than derived, because the
#: decision is the authority and this is the only place the code is checked
#: against it — deriving it from TILES would assert the module against itself.
D1_ORDER = [
    "Compliance Calendar", "Insights", "GST", "Banking", "Accounting",
    "Sales", "Purchases", "TDS", "Payroll", "Income Tax",
    "Fixed Assets", "Inventory", "Year-End", "Reports", "Documents",
]


def test_the_hub_is_d1s_fifteen_in_d1s_order():
    assert [t.label for t in TILES] == D1_ORDER, (
        "the hub's tiles no longer match decision D1. D1 is locked — if the set "
        "or the order should change, that is an owner decision recorded in "
        "THE-PLAN.md, not an edit here."
    )
    assert len({t.id for t in TILES}) == len(TILES), "two tiles share an id"


def test_every_tile_with_a_figure_asks_what_is_OUTSTANDING():
    """The rule that makes fifteen numbers readable at a glance.

    Lower is better on every tile, so a CA never has to remember which way one
    reads. A tile asking for a total ("all invoices", "documents stored") would
    invert that silently — the number goes UP as the practice does well, next
    to fourteen that go down.
    """
    totals = re.compile(r"\b(total|all|every|stored|available|number of)\b", re.I)
    outstanding = re.compile(
        r"\b(not yet|outstanding|overdue|awaiting|still|at or below|not)\b", re.I)
    for t in TILES:
        if not t.answerable:
            continue
        assert not totals.search(t.question), (
            f"{t.id}'s question reads as a total: {t.question!r}. Every tile "
            f"counts what is still to be done — see LOWER_IS_BETTER.")
        assert outstanding.search(t.question), (
            f"{t.id}'s question does not name something outstanding: "
            f"{t.question!r}")
    assert "zero is the finished state" in LOWER_IS_BETTER


def test_a_tile_with_no_signal_says_why_and_cannot_be_given_a_number():
    """`insights` and `reports` are destinations, not queues.

    The second half is the load-bearing one: `describe` FORCES the signal to
    None for an unanswerable tile, so a service that computed something for one
    by mistake cannot put a figure on it. A number under "Reports" would be the
    exact stub 2.2 forbids, and it would be indistinguishable from a real one.
    """
    unanswerable = [t for t in TILES if not t.answerable]
    assert {t.id for t in unanswerable} == {"insights", "reports"}, (
        f"the set of signal-less tiles changed: {[t.id for t in unanswerable]}. "
        f"Adding one is a claim that nobody can compute it — it belongs in a "
        f"review, not in a passing test.")
    for t in unanswerable:
        assert t.no_signal_because and len(t.no_signal_because) > 40, (
            f"{t.id} has no signal and no real reason")
        assert describe(t, 99)["signal"] is None, (
            f"{t.id} accepted a figure it is not supposed to have")


def test_the_payload_tells_the_three_states_apart():
    """Nothing outstanding / nobody can tell / this one failed.

    A frontend must be able to render these differently, so they cannot share
    a spelling. Zero is a real answer and must not be null; an unanswerable
    tile is null AND flagged; a failed fetch is null and NOT flagged, which is
    the service's to report.
    """
    gst = BY_ID["gst"]
    nothing_outstanding = describe(gst, 0)
    assert nothing_outstanding["signal"] == 0 and nothing_outstanding["answerable"] is True

    cannot_tell = describe(BY_ID["reports"], None)
    assert cannot_tell["signal"] is None and cannot_tell["answerable"] is False
    assert cannot_tell["no_signal_because"]

    fetch_failed = describe(gst, None)
    assert fetch_failed["signal"] is None and fetch_failed["answerable"] is True
    assert fetch_failed["no_signal_because"] is None

    # And the three are genuinely distinct as dicts — the property a screen
    # needs and the one a refactor would quietly break.
    assert len({tuple(sorted(d.items(), key=lambda kv: kv[0]))
                for d in (nothing_outstanding, cannot_tell, fetch_failed)}) == 3


def test_a_client_hub_drops_only_the_firm_level_questions():
    firm = tiles_for_scope(None)
    client = tiles_for_scope("11111111-2222-3333-4444-555555555555")
    assert firm == TILES
    dropped = {t.id for t in firm} - {t.id for t in client}
    assert dropped == {"insights", "reports"}, (
        f"a client hub dropped {sorted(dropped)}. A tile is dropped at client "
        f"scope only where its question is about the FIRM — showing a "
        f"firm-wide number beside one client's name reads as that client's.")
    # Compliance and documents exist at both scopes and must survive.
    assert {"compliance", "documents"} <= {t.id for t in client}


@pytest.mark.parametrize("tile", TILES, ids=lambda t: t.id)
def test_every_firm_href_is_a_real_screen_and_not_a_tombstone(tile: Tile):
    """A tile linking nowhere useful is worse than no tile — it reads as working.

    Two failure modes, and the second is the one that needed measuring.
    A MISSING route 404s, which is at least obvious. A
    `MovedToClientWorkspace` page exists, renders, and says "this moved" —
    so a tile showing a real number and landing there looks like a working
    destination right up until the CA reads the page. `/accounting/
    fixed-assets` and `/accounting/invoices` are exactly that.

    This guard is what found the five in MODULES_WITH_NO_FIRM_SCREEN; before
    it, four of the hrefs in this module were plausible strings nobody had
    opened.
    """
    if not WEB_APP.exists():
        pytest.skip("apps/web is not present in this checkout")
    if tile.firm_href is None:
        assert tile.id in MODULES_WITH_NO_FIRM_SCREEN or not tile.client_scoped, (
            f"{tile.id} has no firm-level destination and is not recorded in "
            f"MODULES_WITH_NO_FIRM_SCREEN — an absence has to be a decision")
        return
    page = WEB_APP.joinpath(*[s for s in tile.firm_href.split("/") if s]) / "page.tsx"
    assert page.exists(), (
        f"{tile.id} links to {tile.firm_href}, which has no page.tsx")
    assert "MovedToClientWorkspace" not in page.read_text(encoding="utf-8"), (
        f"{tile.id} links to {tile.firm_href}, which is a tombstone — the whole "
        f"page says the feature moved to the client workspace")


@pytest.mark.parametrize("tile", [t for t in TILES if t.client_section], ids=lambda t: t.id)
def test_every_client_section_is_a_real_section(tile: Tile):
    """The client href is DERIVED from one segment, the same rule
    `switchClientPath` applies — so the segment has to be a real landing page,
    which is the premise
    `apps/web/scripts/a-client-switch-lands-on-the-same-section.test.ts` holds
    from the browser side."""
    if not WEB_APP.exists():
        pytest.skip("apps/web is not present in this checkout")
    page = WEB_APP / "clients" / "[id]" / tile.client_section / "page.tsx"
    assert page.exists(), (
        f"{tile.id} points at the client section {tile.client_section!r}, which "
        f"has no page under apps/web/app/clients/[id]/")


def test_the_firm_level_gap_is_recorded_and_honest():
    """Five of D1's fifteen have no firm-level screen. That is a real state of
    the product, not a defect in this module — and it is put to the owner as
    G3 rather than papered over with a link to the client list."""
    assert len(MODULES_WITH_NO_FIRM_SCREEN) == 5
    for tile_id in MODULES_WITH_NO_FIRM_SCREEN:
        assert tile_id in BY_ID, f"{tile_id} is not a tile"
        assert BY_ID[tile_id].firm_href is None, (
            f"{tile_id} is listed as having no firm screen and carries "
            f"{BY_ID[tile_id].firm_href!r}")
        assert BY_ID[tile_id].client_section, (
            f"{tile_id} has neither a firm screen nor a client section — it "
            f"would be reachable from no hub at all")


def test_a_unit_is_declared_and_not_guessed():
    """Money and counts are formatted differently and must not be told apart
    by looking at the value — `lib/money/format.ts` groups paise the Indian way
    and a count must not go through it."""
    assert {t.unit for t in TILES} == {Unit.COUNT, Unit.PAISE}
    paise = {t.id for t in TILES if t.unit is Unit.PAISE}
    assert paise == {"sales", "purchases", "tds"}, (
        f"the money tiles changed: {sorted(paise)}. A tile's unit is part of "
        f"its question — the same tile cannot be money at one scope and a "
        f"count at another.")
    for t in TILES:
        assert describe(t, 1)["unit"] in ("count", "paise")


def test_these_guards_are_not_vacuous():
    assert len(TILES) == 15
    assert len(D1_ORDER) == 15
    assert sum(1 for t in TILES if t.answerable) == 13
    assert BY_ID["gst"].question == "Returns prepared and not yet filed"
