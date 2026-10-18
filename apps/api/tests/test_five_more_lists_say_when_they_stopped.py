"""Five more lists answer a window, and a screen no longer guesses it was cut short from a row count (POST-A-262).

THE DEFECT
    The login history, the workflow approvals, the firm's HSN/SAC library and the memory screen's client profiles and open
    anomalies each decided "this list was cut short" by `rows.length === <the limit they asked for>`. That is wrong in both
    directions: a list of exactly that many rows is reported as cut short, and a window handed back short because the caller
    may see fewer rows says nothing while more exist. The fix is the one already built for time entries, notifications, the
    entity register and the pipeline (`core/list_window`): the route reads ONE ROW MORE than the window, answers
    `{<rows>, returned, has_more, limit, max_limit}` and the screen reads it through `readWindow`.

WHAT IS HELD
    * each route reads `probe(limit)` rows, never returns the probe row, and says `has_more` from the READ (a scoped caller is
      never told a window is complete because the narrowing ate the overflow);
    * a window that exactly fills is complete; `limit` and the route's own ceiling are served; the limit is bounded at that
      ceiling;
    * the old page-length counts (`total`, `count`) are gone: a count that is only the window's length reads like a total;
    * the HSN library's Archived tab is a window over RETIRED codes (`archived_only`), not a filter over a window of all.
"""
from __future__ import annotations

import typing

import pytest

import routers.firm_hsn_library as hsn
import routers.identity as ident
import routers.memory_intelligence as mem
import routers.workflow_builder as wb
from core import list_window

FIRM = "firm-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "role": "Partner"}


def _bounds(fn):
    hint = typing.get_type_hints(fn, include_extras=True)["limit"]
    meta = [m for m in hint.__metadata__ if hasattr(m, "metadata")]
    assert meta, "the limit parameter carries no Query bounds"
    found = {type(c).__name__: c for c in meta[0].metadata}
    return found["Ge"].ge, found["Le"].le


# ── login history ─────────────────────────────────────────────────────────────────────────────────────

class _Events:
    def __init__(self, n):
        self.rows = [{"id": f"e{i}"} for i in range(n)]
        self.asked = []

    def list_for_firm(self, firm_id, limit=100):
        self.asked.append(limit)
        return self.rows[:limit]


def _login(monkeypatch, n, limit):
    repo = _Events(n)
    monkeypatch.setattr(ident, "login_events_repo", repo)
    return repo, ident.firm_login_history(limit=limit, current_user=USER)["data"]


def test_login_history_reads_one_row_more_and_says_older_events_exist(monkeypatch):
    repo, out = _login(monkeypatch, 12, 5)
    assert repo.asked == [6]
    assert out["returned"] == len(out["events"]) == 5 and out["has_more"] is True
    assert out["limit"] == 5 and out["max_limit"] == ident.LOGIN_HISTORY_MAX == 1000
    assert [e["id"] for e in out["events"]] == ["e0", "e1", "e2", "e3", "e4"], "the probe row was returned"


def test_login_history_that_exactly_fills_the_window_is_complete(monkeypatch):
    _, out = _login(monkeypatch, 5, 5)
    assert out["returned"] == 5 and out["has_more"] is False


# ── workflow approvals ────────────────────────────────────────────────────────────────────────────────

class _WfRepo:
    def __init__(self, n, owners=None):
        self.rows = [{"id": f"a{i}", "instance_id": f"i{i}", "status": "pending"} for i in range(n)]
        self.asked = []
        self.owners = owners or {}

    def list_approvals(self, firm_id, status=None, limit=50):
        self.asked.append(limit)
        return self.rows[:limit]

    def get_instance(self, firm_id, instance_id):
        return {"template_id": "t1", "client_id": self.owners.get(instance_id, "c-mine")}

    def get_template(self, firm_id, template_id):
        return {"name": "Template"}

    def client_ids_for_instances(self, firm_id, ids):
        return {i: self.owners.get(i, "c-mine") for i in ids}


def _approvals(monkeypatch, repo, limit, scope=None):
    monkeypatch.setattr(wb, "_repo", lambda: repo)
    monkeypatch.setattr(wb, "filter_by_client",
                        lambda user, rows, key="client_id": rows if scope is None
                        else [r for r in rows if r.get(key) in scope])
    return wb.list_approvals(status="pending", limit=limit, current_user=USER)["data"]


def test_approvals_read_one_row_more_and_are_enriched_without_the_probe_row(monkeypatch):
    repo = _WfRepo(8)
    out = _approvals(monkeypatch, repo, 5)
    assert repo.asked == [6]
    assert out["returned"] == len(out["approvals"]) == 5 and out["has_more"] is True
    assert all(a["template_name"] == "Template" for a in out["approvals"])
    assert out["limit"] == 5 and out["max_limit"] == wb.APPROVALS_LIST_MAX == 200
    assert "total" not in out, "a count that is only the window's length reads like a total"


def test_a_scoped_caller_is_not_told_the_approvals_are_complete_because_the_narrowing_ate_the_overflow(monkeypatch):
    repo = _WfRepo(8, owners={f"i{i}": "c-theirs" for i in range(8)})
    out = _approvals(monkeypatch, repo, 5, scope={"c-mine"})
    assert out["approvals"] == [] and out["returned"] == 0
    assert out["has_more"] is True


def test_approvals_that_exactly_fill_the_window_are_complete(monkeypatch):
    out = _approvals(monkeypatch, _WfRepo(5), 5)
    assert out["returned"] == 5 and out["has_more"] is False


# ── memory: profiles and anomalies ────────────────────────────────────────────────────────────────────

class _MemRepo:
    def __init__(self, n):
        self.rows = [{"id": f"p{i}", "client_id": "c-mine" if i % 2 == 0 else "c-theirs"} for i in range(n)]
        self.asked = {}

    def list_profiles(self, firm_id, limit=50):
        self.asked["profiles"] = limit
        return self.rows[:limit]

    def list_anomalies(self, firm_id, client_id=None, status="open", limit=50):
        self.asked["anomalies"] = limit
        return self.rows[:limit]


def _memory(monkeypatch, n, limit, which, scope=None):
    repo = _MemRepo(n)
    monkeypatch.setattr(mem, "_get_repo", lambda: repo)
    monkeypatch.setattr(mem, "filter_by_client",
                        lambda user, rows, key="client_id": rows if scope is None
                        else [r for r in rows if r.get(key) in scope])
    if which == "profiles":
        return repo, mem.list_profiles(limit=limit, current_user=USER)["data"]
    return repo, mem.list_anomalies(client_id=None, status="open", limit=limit, current_user=USER)["data"]


@pytest.mark.parametrize("which", ["profiles", "anomalies"])
def test_memory_lists_read_one_row_more_and_say_more_exist(monkeypatch, which):
    repo, out = _memory(monkeypatch, 12, 5, which)
    assert repo.asked[which] == 6
    assert out["returned"] == len(out[which]) == 5 and out["has_more"] is True
    assert out["limit"] == 5 and out["max_limit"] == mem.MEMORY_LIST_MAX == 100
    assert "count" not in out


@pytest.mark.parametrize("which", ["profiles", "anomalies"])
def test_a_scoped_caller_still_sees_that_more_exist(monkeypatch, which):
    _, out = _memory(monkeypatch, 12, 5, which, scope={"c-mine"})
    assert out["returned"] < 5 and out["has_more"] is True


@pytest.mark.parametrize("which", ["profiles", "anomalies"])
def test_a_memory_window_that_exactly_fills_is_complete(monkeypatch, which):
    _, out = _memory(monkeypatch, 5, 5, which)
    assert out["has_more"] is False


# ── the HSN library ───────────────────────────────────────────────────────────────────────────────────

CALLER = {"firm_id": "F1", "role": "Partner", "id": "u1"}


@pytest.fixture
def library(monkeypatch):
    def seed(n_active, n_retired=0):
        rows = ([{"firm_id": "F1", "hsn_code": f"{1000 + i}", "description": "Wheat", "hsn_type": "goods",
                  "is_active": True} for i in range(n_active)]
                + [{"firm_id": "F1", "hsn_code": f"{9000 + i}", "description": "Old", "hsn_type": "goods",
                    "is_active": False} for i in range(n_retired)])
        monkeypatch.setattr(hsn, "_USE_MOCK", True)
        monkeypatch.setattr(hsn, "MOCK_LIBRARY", rows)
    return seed


def _lib(**kw):
    args = dict(q="", hsn_type=None, include_archived=False, archived_only=False, limit=50, current_user=CALLER)
    args.update(kw)
    return hsn.list_library(**args)["data"]


def test_the_library_says_more_exist_beyond_the_window(library):
    library(12)
    out = _lib(limit=5)
    assert out["returned"] == len(out["codes"]) == 5 and out["has_more"] is True
    assert out["limit"] == 5 and out["max_limit"] == hsn.LIBRARY_LIST_MAX == 200
    assert [c["hsn_code"] for c in out["codes"]] == ["1000", "1001", "1002", "1003", "1004"]


def test_a_library_that_exactly_fills_the_window_is_complete(library):
    library(5)
    assert _lib(limit=5)["has_more"] is False


def test_the_archived_tab_lists_only_retired_codes_in_its_own_window(library):
    library(150, n_retired=7)
    out = _lib(archived_only=True, limit=5)
    assert {c["is_active"] for c in out["codes"]} == {False}
    assert out["returned"] == 5 and out["has_more"] is True, "the retired codes were hidden behind 150 active ones"


def test_include_archived_still_lists_both(library):
    library(2, n_retired=2)
    assert _lib(include_archived=True)["returned"] == 4
    assert _lib()["returned"] == 2


class _Chain:
    def __init__(self, rows):
        self.calls, self._rows = [], rows

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append((name, a))
            return self
        return call

    def execute(self):
        class R:
            data = self._rows
        return R()


def test_the_real_read_asks_for_twice_the_window_plus_the_probe_row_and_filters_retired_in_the_query(monkeypatch):
    chain = _Chain([{"hsn_code": str(i), "description": "x", "is_active": False} for i in range(11)])

    class _Sb:
        def table(self, name):
            assert name == "firm_hsn_library"
            return chain
    monkeypatch.setattr(hsn, "_USE_MOCK", False)
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: _Sb())
    out = _lib(archived_only=True, limit=5)
    assert ("limit", (11,)) in chain.calls, "twice the window plus one"
    assert ("eq", ("is_active", False)) in chain.calls, "the Archived tab must be filtered by the database"
    assert out["returned"] == 5 and out["has_more"] is True


# ── bounds ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn, ceiling", [
    (ident.firm_login_history, ident.LOGIN_HISTORY_MAX),
    (wb.list_approvals, wb.APPROVALS_LIST_MAX),
    (mem.list_profiles, mem.MEMORY_LIST_MAX),
    (mem.list_anomalies, mem.MEMORY_LIST_MAX),
    (hsn.list_library, hsn.LIBRARY_LIST_MAX),
])
def test_each_limit_is_bounded_at_its_routes_own_ceiling(fn, ceiling):
    assert _bounds(fn) == (1, ceiling)


def test_the_probe_row_cannot_push_a_route_past_its_ceiling():
    """The ceiling is on what a caller may ASK for; the extra row the route reads is one more than that and is never served."""
    assert list_window.probe(wb.APPROVALS_LIST_MAX) == wb.APPROVALS_LIST_MAX + 1
