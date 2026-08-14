"""
services/ledger_span_service.py — what "All Time" resolves to.

The span feeds a UI decision (how many columns a report is split into), so the
failure modes that matter are the quiet ones: a draft entry stretching the
window past where the numbers start, a half-answer becoming "today", or an
empty client scope silently widening to the whole firm.
"""
import pytest

from services.ledger_span_service import ledger_span


class _Query:
    """Records the filters applied, returns whatever rows the fake was seeded
    with for the requested sort direction."""

    def __init__(self, table, rows_asc, log):
        self._table, self._rows_asc, self._log = table, rows_asc, log
        self._desc = False

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._log.setdefault("eq", []).append((col, val))
        return self

    def is_(self, col, val):
        self._log.setdefault("is", []).append((col, val))
        return self

    def in_(self, col, vals):
        self._log.setdefault("in", []).append((col, list(vals)))
        return self

    def order(self, col, desc=False):
        self._log.setdefault("order", []).append((col, desc))
        self._desc = desc
        return self

    def limit(self, n):
        self._log.setdefault("limit", []).append(n)
        return self

    def execute(self):
        rows = list(reversed(self._rows_asc)) if self._desc else list(self._rows_asc)
        return type("R", (), {"data": rows[:1]})()


class _DB:
    def __init__(self, rows_asc):
        self.rows_asc, self.log = rows_asc, {}
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return _Query(name, self.rows_asc, self.log)


def test_returns_the_first_and_last_posted_dates():
    db = _DB([{"entry_date": "2024-04-01"}, {"entry_date": "2026-03-31"}])

    assert ledger_span(db, "f1") == {
        "first_entry_date": "2024-04-01", "last_entry_date": "2026-03-31"}


def test_only_posted_undeleted_entries_are_considered():
    """A draft entry must not stretch the window: the first reporting column
    would cover a period with nothing in it, and the user would read that as
    missing data rather than as a draft."""
    db = _DB([{"entry_date": "2024-04-01"}])
    ledger_span(db, "f1")

    assert ("is_posted", True) in db.log["eq"]
    assert ("deleted_at", "null") in db.log["is"]
    assert ("firm_id", "f1") in db.log["eq"]


def test_it_reads_one_row_from_each_end_rather_than_scanning():
    """The whole point of the endpoint is that it is cheap enough to call on
    every report load. Two ordered single-row reads, not an aggregate."""
    db = _DB([{"entry_date": "2024-04-01"}])
    ledger_span(db, "f1")

    assert db.log["order"] == [("entry_date", False), ("entry_date", True)]
    assert db.log["limit"] == [1, 1]


def test_an_empty_ledger_yields_no_span():
    db = _DB([])

    assert ledger_span(db, "f1") == {
        "first_entry_date": None, "last_entry_date": None}


def test_a_named_client_filters_by_that_client():
    db = _DB([{"entry_date": "2025-01-01"}])
    ledger_span(db, "f1", ["c1"])

    assert ("client_id", ["c1"]) in db.log["in"]


def test_scoping_to_no_clients_returns_nothing_without_querying():
    """An empty list means the caller is assigned to no clients. It must NOT
    reach `.in_("client_id", [])`, whose result would be the whole firm on some
    drivers — the opposite of what an empty scope means."""
    db = _DB([{"entry_date": "2025-01-01"}])

    assert ledger_span(db, "f1", []) == {
        "first_entry_date": None, "last_entry_date": None}
    assert db.tables == [], "queried the database for an empty scope"


def test_a_firmwide_scope_applies_no_client_filter():
    db = _DB([{"entry_date": "2025-01-01"}])
    ledger_span(db, "f1", None)

    assert "in" not in db.log


def test_a_timestamp_is_truncated_to_a_date():
    """entry_date may come back as a full timestamp depending on the column
    type. The frontend compares these as ISO dates, so a trailing time
    component would make "2024-04-01T00:00:00" sort after "2024-04-01"."""
    db = _DB([{"entry_date": "2024-04-01T00:00:00+00:00"},
              {"entry_date": "2026-03-31T18:30:00+00:00"}])

    assert ledger_span(db, "f1") == {
        "first_entry_date": "2024-04-01", "last_entry_date": "2026-03-31"}


@pytest.mark.parametrize("rows", [[{"entry_date": None}], [{}]])
def test_a_missing_date_is_treated_as_no_span_not_a_half_range(rows):
    """A one-sided span is not a range. Letting half an answer through would
    give the UI a start with no end, which downstream becomes "today" and
    silently truncates the report."""
    db = _DB(rows)

    assert ledger_span(db, "f1") == {
        "first_entry_date": None, "last_entry_date": None}
