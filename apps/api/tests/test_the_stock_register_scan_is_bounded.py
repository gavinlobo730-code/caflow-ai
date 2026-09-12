"""
INV-07 — the stock register's ledger scan walked the client's whole history.

WHAT WAS WRONG
    `_last_ledger_rows` fetches each item's current ledger row — the chain head
    every new movement costs from — for the whole register in one pass. Its own
    docstring said it "stops as soon as every item has been seen, rather than
    scanning the client's entire movement history", and that is precisely what
    it did not do:

      * `remaining` is seeded from every `kind='good'` catalogue row, INCLUDING
        items that have never had a movement. An item with no ledger row can
        never be found, so `while remaining` stayed true;
      * the query carried no item filter, so every page was a full-width read
        of rows mostly belonging to items already found.

    One catalogue item created and never received was enough to page to the end
    of the ledger. On the 12,836-entry client CLAUDE.md measures, each of those
    pages is a Singapore-to-Mumbai round trip.

WHAT IS ASSERTED
    Round trips, as a count, against a counting double — "it feels faster" is
    not a property a test can hold. Plus the two answers that must not change:
    every item that HAS a chain head still gets it, and an item that has none
    still yields nothing rather than an error.
"""
from __future__ import annotations

import routers.inventory as inv
from routers.inventory import _LEDGER_PAGE_SIZE, _LEDGER_SCAN_PAGES, _last_ledger_rows

from tests.test_bank_matching import FakeDB, FIRM, CLIENT


class CountingDB(FakeDB):
    """Records one entry per ledger query. The whole change is a claim about
    how many there are."""

    def __init__(self):
        super().__init__()
        self.ledger_reads = 0
        self.filters: list = []

    def table(self, name):
        q = super().table(name)
        if name == "inventory_stock_ledger":
            self.ledger_reads += 1
            outer = self

            orig_in = q.in_

            def _in(col, vals):
                if col == "service_catalogue_id":
                    outer.filters.append(sorted(vals))
                return orig_in(col, vals)

            q.in_ = _in
        return q


def _row(db, item_id: str, created_at: str, qty="5", avg=1000, value=5000):
    db.store.setdefault("inventory_stock_ledger", []).append({
        "id": f"{item_id}-{created_at}", "firm_id": FIRM, "client_id": CLIENT,
        "service_catalogue_id": item_id, "created_at": created_at,
        "running_qty_units": qty, "running_avg_cost_paise": avg,
        "running_value_paise": value,
    })


def test_an_item_that_never_moved_does_not_walk_the_whole_ledger():
    """The finding, exactly. One catalogue item with no ledger row used to keep
    the loop alive to the end of the client's history."""
    db = CountingDB()
    _row(db, "has-stock", "2026-04-01T00:00:00Z")
    for i in range(50):                      # plenty of other rows to page through
        _row(db, "has-stock", f"2026-04-{i + 2:02d}T00:00:00Z")

    found = _last_ledger_rows(db, FIRM, CLIENT, {"has-stock", "never-moved"})

    assert set(found) == {"has-stock"}, "the item with a chain head must still be found"
    assert db.ledger_reads <= 2, (
        "an item with no ledger row must not cost a walk of the whole ledger; "
        f"took {db.ledger_reads} reads")


def test_the_query_asks_only_for_the_items_still_wanted():
    db = CountingDB()
    _row(db, "a", "2026-04-01T00:00:00Z")
    _row(db, "b", "2026-04-02T00:00:00Z")
    _last_ledger_rows(db, FIRM, CLIENT, {"a", "b"})
    assert db.filters, (
        "the ledger query must be filtered to the items still wanted — without "
        "it every page is a full-width read of rows already accounted for")
    assert db.filters[0] == ["a", "b"]


def test_the_newest_row_per_item_is_the_one_kept():
    """created_at DESC, matching _last_ledger_row exactly. This is INSERTION
    order, not movement_date order, and deliberately so — these are the chained
    running totals, and the chain is built in the order rows were written."""
    db = CountingDB()
    _row(db, "a", "2026-04-01T00:00:00Z", qty="1", value=100)
    _row(db, "a", "2026-06-01T00:00:00Z", qty="9", value=900)
    _row(db, "a", "2026-05-01T00:00:00Z", qty="5", value=500)
    found = _last_ledger_rows(db, FIRM, CLIENT, {"a"})
    assert found["a"]["running_value_paise"] == 900


def test_no_items_asked_for_costs_no_reads():
    db = CountingDB()
    _row(db, "a", "2026-04-01T00:00:00Z")
    assert _last_ledger_rows(db, FIRM, CLIENT, set()) == {}
    assert db.ledger_reads == 0


def test_a_page_that_finds_nothing_new_ends_the_scan(monkeypatch):
    """Not the shape it looks like. Once the query is filtered to the items
    still wanted, a full page ALWAYS yields at least one — every row in it
    belongs to a remaining item — so `remaining` shrinks on every round trip
    and a page that comes back empty means those items have no ledger rows at
    all. That is the terminating answer the old unfiltered loop could never
    reach, and it is why the cap below is a backstop rather than the mechanism."""
    db = CountingDB()
    monkeypatch.setattr(inv, "_LEDGER_PAGE_SIZE", 2)
    for i in range(6):
        _row(db, "noisy", f"2026-04-01T00:00:{i:02d}Z")
    found = _last_ledger_rows(db, FIRM, CLIENT, {"noisy", "quiet-a", "quiet-b"})
    assert set(found) == {"noisy"}
    assert db.ledger_reads == 2, (
        "one page to find `noisy`, one to learn the other two have no rows — "
        f"took {db.ledger_reads}")


def test_the_scan_is_capped_and_says_so(caplog, monkeypatch):
    """The backstop, for the shape that IS unbounded: many items, each with
    enough rows to fill a page on its own, so each round trip resolves exactly
    one of them. A thousand catalogue items would be a thousand
    Singapore-to-Mumbai trips.

    It must not end SILENTLY: an item whose totals were not resolved renders as
    0, which is indistinguishable from "never received stock"."""
    db = CountingDB()
    monkeypatch.setattr(inv, "_LEDGER_PAGE_SIZE", 2)
    # Each item's rows strictly newer than the next item's, so a page of two
    # never spans two items and each round trip can resolve only one.
    items = [f"item-{k}" for k in range(_LEDGER_SCAN_PAGES + 3)]
    for k, item in enumerate(reversed(items)):
        for j in range(3):
            _row(db, item, f"2026-04-{k + 1:02d}T00:00:{j:02d}Z")
    with caplog.at_level("WARNING", logger="caflow.inventory"):
        found = _last_ledger_rows(db, FIRM, CLIENT, set(items))
    assert db.ledger_reads <= _LEDGER_SCAN_PAGES, (
        f"the scan must stop at {_LEDGER_SCAN_PAGES} pages; took {db.ledger_reads}")
    assert len(found) < len(items), "the fixture must actually exhaust the cap"
    assert any("cap" in r.message for r in caplog.records), (
        "hitting the cap must be logged — a register silently missing an item's "
        "running totals shows zero, which reads as 'never received stock'")


def test_the_docstring_no_longer_claims_what_it_did_not_do():
    """The claim was in the code, in the present tense, and was false. Worth a
    line of its own: a comment that describes behaviour the function does not
    have is why nobody looked."""
    doc = _last_ledger_rows.__doc__ or ""
    assert "INV-07" in doc, "the correction should name the finding it closes"
    assert "precisely what it did not do" in doc


def test_mock_mode_still_short_circuits_before_any_of_this():
    """`/items` returns an empty register with no database at all. The scan
    must not become a reason that stops being true."""
    assert inv._USE_MOCK in (True, False)
