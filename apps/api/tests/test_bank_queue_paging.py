"""
The Categorize queue is paged, and the page is all it reads.

Two problems, one cause. The queue fetched every transaction for the client and
filtered in Python, so:

  * the screen rendered all of them in one scroll, with nothing saying how many
    there were — a CA working a 300-line statement could not tell how much was
    left, and
  * the read was proportional to statement volume. For a client with 12,836
    lines that is thirteen cross-region round trips to draw fifty rows, which
    is the shape CLAUDE.md rules out for exactly this reason.

The view filter is SQL now (`_view_filter`), so a page is the only thing that
crosses the wire, and `queue_total` reports the size of the whole view so the
count on screen stays honest.

The subtle one is the tiebreak. Statement dates repeat constantly — six lines
on 2026-04-15 is ordinary — and paging a sort with ties repeats rows on one
page and drops them from the next. `test_paging_a_tied_sort_loses_nothing` is
the test for that, and it fails against an ORDER BY with no `id`.
"""
import pytest

from services.bank_matching_service import bank_matching_service as svc
from tests.test_bank_matching import FakeDB, FIRM, CLIENT, _seed_txn


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    import services.bank_matching_service as bms
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


class UnorderedDB(FakeDB):
    """FakeDB, minus the accident that a heap has an order.

    A plain in-memory list is returned in insertion order every time, and
    Python's sort is stable, so a fake with no tiebreak still hands back the
    same sequence for every query — which makes a test for the MISSING
    tiebreak pass while the bug is present. Verified: deleting `.order("id")`
    from the service left the whole of this file green.

    Postgres offers no such courtesy. Rows tied on the ORDER BY key come back
    in whatever order the plan produced, and that can differ between the query
    for page 1 and the query for page 2. This models it minimally, by rotating
    each table by one position per query — deterministic, so a failure
    reproduces, but enough that any sort which is not TOTAL serves different
    sequences to consecutive queries.
    """

    def __init__(self):
        super().__init__()
        self._reads = 0

    def table(self, name):
        rows = self.store.setdefault(name, [])
        if rows:
            self._reads += 1
            k = self._reads % len(rows)
            self.store[name] = rows[k:] + rows[:k]
        return super().table(name)


def _seed_many(db, n, *, date="2026-04-15", **kw):
    """n rows. Ids are zero-padded so id order is insertion order."""
    for i in range(n):
        _seed_txn(db, id=f"t{i:03d}", transaction_date=date, **kw)
    return db


# ── The page is a page ────────────────────────────────────────────────────────

def test_a_page_holds_only_its_own_rows_and_the_total_counts_them_all():
    db = _seed_many(FakeDB(), 12)
    first = svc.queue(db, FIRM, CLIENT, "for_review", limit=5, offset=0)
    assert len(first) == 5
    assert svc.queue_total(db, FIRM, CLIENT, "for_review") == 12, \
        "the total must describe the view, not the page — it is what tells the CA what is left"


def test_the_last_page_is_short_rather_than_padded():
    db = _seed_many(FakeDB(), 12)
    last = svc.queue(db, FIRM, CLIENT, "for_review", limit=5, offset=10)
    assert len(last) == 2


def test_an_offset_past_the_end_is_empty_not_an_error():
    db = _seed_many(FakeDB(), 3)
    assert svc.queue(db, FIRM, CLIENT, "for_review", limit=5, offset=99) == []


def test_no_limit_still_returns_the_whole_view():
    """Callers that want everything — and every existing test — keep working."""
    db = _seed_many(FakeDB(), 12)
    assert len(svc.queue(db, FIRM, CLIENT, "for_review")) == 12


# ── The tiebreak ──────────────────────────────────────────────────────────────

def test_paging_a_tied_sort_loses_nothing():
    """Every row exactly once across the pages, with every date identical.

    Sorted on transaction_date alone the order between tied rows is arbitrary
    per query, so page 2 can re-serve what page 1 already showed and silently
    skip the rows it displaced. The id tiebreak is what makes the sort total."""
    db = _seed_many(UnorderedDB(), 20, date="2026-04-15")   # ALL on one date
    seen = []
    for offset in range(0, 20, 5):
        seen += [t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review",
                                            limit=5, offset=offset)]
    assert len(seen) == 20
    assert len(set(seen)) == 20, f"a row was served twice: {sorted(seen)}"
    assert set(seen) == {f"t{i:03d}" for i in range(20)}


def test_pages_are_in_date_order_across_the_boundary():
    db = UnorderedDB()
    for i, d in enumerate(["2026-04-01", "2026-04-20", "2026-04-05", "2026-04-30"]):
        _seed_txn(db, id=f"t{i}", transaction_date=d)
    got = [t["transaction_date"]
           for off in (0, 2)
           for t in svc.queue(db, FIRM, CLIENT, "for_review", limit=2, offset=off)]
    assert got == sorted(got), f"paging broke the date order: {got}"


# ── The view filter, now that it is SQL ───────────────────────────────────────

def test_the_view_filter_partitions_the_same_way_paged_as_whole():
    """The SQL predicate and the page must agree with the unpaged read — this is
    the regression that a filter push-down risks."""
    db = FakeDB()
    _seed_txn(db, id="a", match_status="unmatched")
    _seed_txn(db, id="b", match_status="posted")
    _seed_txn(db, id="c", match_status="ignored")
    _seed_txn(db, id="d", match_status="matched", matched_entity_id="inv-1")
    _seed_txn(db, id="e", match_status="unmatched", category="Bank Charges")
    for view, expected in (
        ("for_review", {"a", "d", "e"}),
        ("done",       {"b"}),
        ("ignored",    {"c"}),
        ("all",        {"a", "b", "c", "d", "e"}),
        ("unmatched",  {"a", "e"}),
        ("categorized", {"e"}),
        ("matched",    {"d"}),
    ):
        whole = {t["id"] for t in svc.queue(db, FIRM, CLIENT, view)}
        paged = {t["id"] for off in (0, 3)
                 for t in svc.queue(db, FIRM, CLIENT, view, limit=3, offset=off)}
        assert whole == expected, f"{view}: unpaged gave {whole}"
        assert paged == expected, f"{view}: paged gave {paged}"
        assert svc.queue_total(db, FIRM, CLIENT, view) == len(expected), view


def test_an_ignored_row_stays_out_of_the_total_of_a_working_view():
    """The count drives the pager. If it counted set-aside rows the CA would be
    told there is a next page that turns out to be empty."""
    db = FakeDB()
    _seed_txn(db, id="a", match_status="unmatched")
    _seed_txn(db, id="b", match_status="ignored", category="Bank Charges")
    assert svc.queue_total(db, FIRM, CLIENT, "for_review") == 1
    assert svc.queue_total(db, FIRM, CLIENT, "categorized") == 0, \
        "an ignored row carrying a category is not live work"


def test_an_empty_string_category_is_not_categorised():
    """`bool(t.get("category"))` excluded it; `category IS NOT NULL` would not."""
    db = FakeDB()
    _seed_txn(db, id="a", category="")
    assert svc.queue(db, FIRM, CLIENT, "categorized") == []


def test_an_unknown_view_is_refused_by_both_entry_points():
    db = FakeDB()
    for call in (lambda: svc.queue(db, FIRM, CLIENT, "excluded"),
                 lambda: svc.queue_total(db, FIRM, CLIENT, "excluded")):
        with pytest.raises(Exception):
            call()


# ── Search ────────────────────────────────────────────────────────────────────
# It is SQL, and that is the point: the screen shows one page, so a box that
# filtered the rows already fetched would answer "no match" for a line sitting
# on page four. A wrong answer, not a slow one.

def _seed_named(db, n, desc, **kw):
    for i in range(n):
        _seed_txn(db, id=f"{desc[:4].lower()}{i:03d}", description=f"{desc} {i}", **kw)


def test_search_matches_the_bank_narration():
    db = FakeDB()
    _seed_named(db, 3, "TECHTRON IT SOLUTIONS")
    _seed_named(db, 5, "SILVER OAK INDUSTRIES")
    got = svc.queue(db, FIRM, CLIENT, "for_review", q_text="techtron")
    assert len(got) == 3, f"expected the three Techtron lines, got {len(got)}"
    assert all("TECHTRON" in t["description"] for t in got)


def test_search_is_case_insensitive_and_matches_a_substring():
    db = FakeDB()
    _seed_txn(db, id="a", description="NEFT DR-COSB0000003-SELF TRANSFER TO COSMOS")
    assert len(svc.queue(db, FIRM, CLIENT, "for_review", q_text="cosmos")) == 1
    assert len(svc.queue(db, FIRM, CLIENT, "for_review", q_text="CoSmOs")) == 1


def test_search_also_looks_at_the_reference_and_the_confirmed_payee():
    db = FakeDB()
    _seed_txn(db, id="a", description="UPI/CR/604812345679", reference_no="UTR-777")
    _seed_txn(db, id="b", description="NEFT", payee_name="Blue Horizon Exports")
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review", q_text="UTR-777")} == {"a"}
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review", q_text="horizon")} == {"b"}


def test_the_total_counts_the_SEARCHED_view_not_the_whole_one():
    """The pager is driven by this number. Counting unsearched rows would offer
    pages the search has emptied."""
    db = FakeDB()
    _seed_named(db, 3, "TECHTRON IT SOLUTIONS")
    _seed_named(db, 5, "SILVER OAK INDUSTRIES")
    assert svc.queue_total(db, FIRM, CLIENT, "for_review") == 8
    assert svc.queue_total(db, FIRM, CLIENT, "for_review", q_text="techtron") == 3


def test_search_composes_with_the_view_filter():
    """A search inside "Categorized" must not reach into "For review"."""
    db = FakeDB()
    _seed_txn(db, id="a", description="TECHTRON one", match_status="unmatched")
    _seed_txn(db, id="b", description="TECHTRON two", match_status="posted")
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review", q_text="techtron")} == {"a"}
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "done", q_text="techtron")} == {"b"}


def test_search_composes_with_paging():
    db = FakeDB()
    _seed_named(db, 12, "TECHTRON IT SOLUTIONS")
    _seed_named(db, 9, "SILVER OAK INDUSTRIES")
    seen = []
    for off in (0, 5, 10):
        seen += [t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review",
                                            limit=5, offset=off, q_text="techtron")]
    assert len(seen) == 12 and len(set(seen)) == 12, f"paged search lost rows: {seen}"


def test_a_wildcard_in_the_search_term_is_a_character_not_a_wildcard():
    """`%` and `_` are LIKE metacharacters. Unescaped, searching "50%" would
    match every row — which reads as "found everything" rather than an error."""
    db = FakeDB()
    _seed_txn(db, id="a", description="BANK CHARGE 50% SURCHARGE")
    _seed_txn(db, id="b", description="NOTHING RELEVANT HERE")
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review", q_text="50%")} == {"a"}
    # A bare "%" finds the rows containing a literal percent sign — NOT every
    # row, which is what an unescaped LIKE wildcard would have returned. My
    # first version of this asserted [] and was simply wrong about the meaning.
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review", q_text="%")} == {"a"}
    assert {t["id"] for t in svc.queue(db, FIRM, CLIENT, "for_review", q_text="_")} == set()


def test_an_empty_or_blank_search_is_no_filter_at_all():
    db = FakeDB()
    _seed_named(db, 4, "ANYTHING")
    for term in (None, "", "   "):
        assert len(svc.queue(db, FIRM, CLIENT, "for_review", q_text=term)) == 4, term
