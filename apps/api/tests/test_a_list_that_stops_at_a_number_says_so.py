"""POST-A-132: a list that stops at a number says it stopped.

Time entries, notifications and a client's tasks asked for "the latest 100" and
showed 100 rows as though they were all of them. The server now reads ONE ROW
MORE than the window and answers `has_more`; the screens print it. This file
holds the server half: the window arithmetic, the two routes, the windowed time
read, and the complete read the export needs (the single read it replaced was
cut at PostgREST's ~1000 rows without a word).
"""
import typing

import pytest

import repositories.time_tracking_repository as tt_repo_module
import routers.notifications as nt
import routers.time_tracking as tt
from core import list_window
from tests.e2e_harness import FakeDB

FIRM = "firm-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


# ── the window arithmetic ────────────────────────────────────────────────────

def test_a_probe_asks_for_one_row_more_than_the_window():
    assert list_window.probe(100) == 101


def test_the_extra_row_is_the_signal_and_is_never_returned():
    window, more = list_window.split(list(range(101)), 100)
    assert (len(window), more) == (100, True)
    assert window[-1] == 99


def test_a_window_that_is_exactly_full_is_not_reported_as_cut_short():
    window, more = list_window.split(list(range(100)), 100)
    assert (len(window), more) == (100, False)


def test_a_short_read_is_complete():
    assert list_window.split([], 100) == ([], False)
    assert list_window.split([1, 2, 3], 100) == ([1, 2, 3], False)


# ── notifications ────────────────────────────────────────────────────────────

class _Repo:
    def __init__(self, n):
        self.rows = [{"id": f"N{i}", "client_id": None} for i in range(n)]
        self.asked = []

    def find_all(self, **kw):
        self.asked.append(kw["limit"])
        return self.rows[: kw["limit"]]

    def count_unread(self, **kw):
        return 7


@pytest.fixture
def notifications(monkeypatch):
    def make(n):
        repo = _Repo(n)
        monkeypatch.setattr(nt, "notifications_repo", repo)
        monkeypatch.setattr(nt, "filter_by_client", lambda user, items, key="client_id": list(items))
        return repo
    return make


def test_notifications_say_when_older_ones_exist_and_never_return_the_probe_row(notifications):
    repo = notifications(120)
    out = nt.list_notifications(current_user=USER, limit=100)["data"]
    assert repo.asked == [101]
    assert out["has_more"] is True
    assert out["returned"] == len(out["notifications"]) == 100
    assert out["limit"] == 100 and out["max_limit"] == list_window.MAX_LIST_LIMIT


def test_notifications_that_fit_the_window_are_reported_complete(notifications):
    notifications(100)
    out = nt.list_notifications(current_user=USER, limit=100)["data"]
    assert out["has_more"] is False and out["returned"] == 100


def test_a_scoped_person_is_not_told_the_window_is_complete_because_the_filter_ate_the_overflow(notifications, monkeypatch):
    notifications(120)
    monkeypatch.setattr(nt, "filter_by_client", lambda user, items, key="client_id": [])
    out = nt.list_notifications(current_user=USER, limit=100)["data"]
    assert out["notifications"] == [] and out["returned"] == 0
    assert out["has_more"] is True


def test_the_notification_list_no_longer_serves_a_count_that_is_only_the_page_length(notifications):
    notifications(3)
    assert "total" not in nt.list_notifications(current_user=USER, limit=100)["data"]


def _limit_bounds(fn):
    hints = typing.get_type_hints(fn, include_extras=True)["limit"]
    meta = [m for m in hints.__metadata__ if hasattr(m, "metadata")]
    assert meta, "the limit parameter carries no Query bounds"
    bounds = {type(c).__name__: c for c in meta[0].metadata}
    return bounds["Ge"].ge, bounds["Le"].le


@pytest.mark.parametrize("fn", [nt.list_notifications, tt.list_entries])
def test_a_list_limit_is_bounded_at_the_servers_ceiling(fn):
    low, high = _limit_bounds(fn)
    assert (low, high) == (1, list_window.MAX_LIST_LIMIT)


# ── time entries ─────────────────────────────────────────────────────────────

def _seed_entries(db, n):
    for i in range(n):
        db.seed("time_entries", {
            "id": f"e{i:05d}", "firm_id": FIRM, "client_id": None, "user_id": "u1",
            "started_at": f"2026-01-{(i % 28) + 1:02d}T09:{i % 60:02d}:00Z",
            "duration_minutes": 10, "is_billable": i % 2 == 0,
        })


def test_the_time_entry_window_returns_the_latest_and_says_older_exist(monkeypatch):
    db = FakeDB()
    _seed_entries(db, 12)
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: db)
    rows, more = tt_repo_module.time_tracking_repo.find_page(firm_id=FIRM, limit=5)
    assert len(rows) == 5 and more is True
    starts = [r["started_at"] for r in rows]
    assert starts == sorted(starts, reverse=True)
    # …and the five are the NEWEST five of the twelve, not the first five stored.
    everything = sorted((r["started_at"] for r in db.rows("time_entries")), reverse=True)
    assert starts == everything[:5]


def test_a_time_entry_window_that_holds_every_row_is_complete(monkeypatch):
    db = FakeDB()
    _seed_entries(db, 5)
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: db)
    rows, more = tt_repo_module.time_tracking_repo.find_page(firm_id=FIRM, limit=5)
    assert (len(rows), more) == (5, False)


def test_the_time_entry_route_serves_the_window_signal_and_sums_over_what_it_returned(monkeypatch):
    class Repo:
        def find_page(self, **kw):
            assert kw["limit"] == 3
            return ([
                {"id": "a", "duration_minutes": 60, "is_billable": True, "client_id": None},
                {"id": "b", "duration_minutes": 30, "is_billable": False, "client_id": None},
            ], True)

    monkeypatch.setattr(tt, "time_tracking_repo", Repo())
    monkeypatch.setattr(tt, "filter_by_client", lambda user, items, key="client_id": list(items))
    out = tt.list_entries(current_user=USER, limit=3)["data"]
    assert out["has_more"] is True and out["returned"] == 2 and out["limit"] == 3
    assert out["max_limit"] == list_window.MAX_LIST_LIMIT
    assert (out["total_minutes"], out["billable_minutes"]) == (90, 60)
    assert "total" not in out


# ── the complete read (the export) ───────────────────────────────────────────

class _Capped:
    """PostgREST's db-max-rows: a response is cut at 1000 rows and says nothing."""

    def __init__(self, q):
        self._q = q

    def __getattr__(self, name):
        attr = getattr(self._q, name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            out = attr(*a, **k)
            if name == "execute":
                out.data = list(out.data or [])[:1000]
                return out
            return self if out is self._q else out
        return call


class _CappedDB(FakeDB):
    def table(self, name):
        return _Capped(super().table(name))


def test_the_complete_read_is_not_cut_at_the_servers_row_cap(monkeypatch):
    db = _CappedDB()
    _seed_entries(db, 2350)
    monkeypatch.setattr(tt_repo_module, "_get_db", lambda: db)
    rows = tt_repo_module.time_tracking_repo.find_all(firm_id=FIRM)
    assert len(rows) == 2350
    assert len({r["id"] for r in rows}) == 2350
    starts = [r["started_at"] for r in rows]
    assert starts == sorted(starts, reverse=True)


def test_the_capped_double_really_does_truncate_a_single_read():
    """Negative control for the one above: without paging, 2,350 rows come back as 1,000."""
    db = _CappedDB()
    _seed_entries(db, 2350)
    assert len(db.table("time_entries").select("*").eq("firm_id", FIRM).execute().data) == 1000
