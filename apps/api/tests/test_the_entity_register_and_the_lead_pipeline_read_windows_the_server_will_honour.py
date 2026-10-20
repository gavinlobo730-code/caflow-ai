"""The entity register and the lead pipeline read their windows in requests the database will honour (POST-A-295).

WHAT WAS WRONG
    `list_entities` (`ENTITY_LIST_MAX`, 2,000) and `list_leads` (`LEAD_LIST_MAX`, 2,000) read `.range(offset, offset + limit)`
    once, and PostgREST cuts any response at 1,000 rows without saying so (`core/db_paging.PAGE`). A firm with 1,500 entities
    asking for the ceiling got 1,000 rows and `has_more` false, because the read returned fewer than the window: a register
    cut short that said it was whole, which is the fault the window convention exists to prevent (POST-A-259). The TDS lists
    were found with the same fault and read through `core.db_paging.fetch_window`; so are these now.

HOW IT IS PROVEN
    A database double that, like PostgREST, answers at most 1,000 rows to one request and says nothing when it cuts one short
    (the double the TDS lists' own test uses), a firm with 1,500 rows, and the real route functions. Against the code before
    this change the 2,000-row window comes back 1,000 long with `has_more` false.
"""
import ast
from pathlib import Path

import pytest

import routers.lifecycle as lifecycle
import routers.relationships as relationships
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
USER = {"firm_id": FIRM, "id": "u-1", "role": "Partner"}
API = Path(__file__).resolve().parents[1]


class _Capped:
    """A query that answers at most `cap` rows to one request and says nothing when it cuts one short."""

    def __init__(self, query, cap):
        self._query, self._cap = query, cap

    def __getattr__(self, name):
        attr = getattr(self._query, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            out = attr(*args, **kwargs)
            if name == "execute":
                out.data = list(out.data or [])[: self._cap]
                return out
            return _Capped(out, self._cap) if hasattr(out, "execute") else out
        return call


class _CappedDB:
    def __init__(self, db, cap=1000):
        self._db, self._cap = db, cap

    def table(self, name):
        return _Capped(self._db.table(name), self._cap)


def _entities(n):
    db = FakeDB()
    for i in range(n):
        db.seed("entities", {"id": f"e-{i:05d}", "firm_id": FIRM, "full_name": f"Entity {i:05d}", "entity_type": "Individual"})
    db.seed("entities", {"id": "e-other", "firm_id": "FIRM-B", "full_name": "Another firm's", "entity_type": "Individual"})
    return _CappedDB(db)


def _leads(n):
    db = FakeDB()
    for i in range(n):
        db.seed("leads", {"id": f"l-{i:05d}", "firm_id": FIRM, "stage": "new", "is_converted": None,
                          "created_at": f"2026-10-{1 + i % 20:02d}T10:00:00+00:00", "name": f"Lead {i}"})
    db.seed("leads", {"id": "l-gone", "firm_id": FIRM, "stage": "_deleted", "is_converted": None,
                      "created_at": "2026-10-30T10:00:00+00:00"})
    db.seed("leads", {"id": "l-won", "firm_id": FIRM, "stage": "won", "is_converted": True,
                      "created_at": "2026-10-30T11:00:00+00:00"})
    return _CappedDB(db)


def _entity_window(monkeypatch, db, **kw):
    monkeypatch.setattr(relationships, "_db", lambda: db)
    args = {"entity_type": None, "search": None, "limit": 50, "offset": 0, "current_user": USER, **kw}
    return relationships.list_entities(**args)["data"]


def _lead_window(monkeypatch, db, **kw):
    monkeypatch.setattr(lifecycle, "_db", lambda: db)
    args = {"stage": None, "assigned_to": None, "limit": 50, "offset": 0, "current_user": USER, **kw}
    return lifecycle.list_leads(**args)["data"]


# ── the entity register ──────────────────────────────────────────────────────

def test_the_whole_register_comes_back_when_it_is_longer_than_one_request_the_database_will_honour(monkeypatch):
    out = _entity_window(monkeypatch, _entities(1500), limit=relationships.ENTITY_LIST_MAX)
    assert out["returned"] == 1500 and len(out["entities"]) == 1500, "the register was cut at the database's own ceiling"
    assert out["has_more"] is False
    assert len({e["id"] for e in out["entities"]}) == 1500, "a row came back twice"
    assert all(e["firm_id"] == FIRM for e in out["entities"]), "another firm's entity reached this firm's register"


def test_a_window_shorter_than_the_register_says_more_exist(monkeypatch):
    out = _entity_window(monkeypatch, _entities(1500), limit=1200)
    assert out["returned"] == 1200 and out["has_more"] is True, "the window was cut short and said it was whole"


def test_the_next_window_starts_where_the_last_ended_and_is_in_name_order(monkeypatch):
    db = _entities(1500)
    first = _entity_window(monkeypatch, db, limit=1200)
    rest = _entity_window(monkeypatch, db, limit=1200, offset=1200)
    assert rest["returned"] == 300 and rest["has_more"] is False
    names = [e["full_name"] for e in first["entities"] + rest["entities"]]
    assert names == sorted(names) and len(set(names)) == 1500


# ── the lead pipeline ────────────────────────────────────────────────────────

def test_the_whole_pipeline_comes_back_when_it_is_longer_than_one_request_the_database_will_honour(monkeypatch):
    out = _lead_window(monkeypatch, _leads(1500), limit=lifecycle.LEAD_LIST_MAX)
    assert out["returned"] == 1500 and out["has_more"] is False, "the pipeline was cut at the database's own ceiling"
    ids = [l["id"] for l in out["leads"]]
    assert len(set(ids)) == 1500 and "l-gone" not in ids and "l-won" not in ids, "a deleted or converted lead is in the pipeline"


def test_the_pipeline_is_newest_first_with_the_newest_id_first_within_an_instant(monkeypatch):
    out = _lead_window(monkeypatch, _leads(1500), limit=lifecycle.LEAD_LIST_MAX)
    keys = [(l["created_at"], l["id"]) for l in out["leads"]]
    assert keys == sorted(keys, reverse=True), "the order the board has always had changed"


def test_a_pipeline_window_shorter_than_the_pipeline_says_more_exist_and_the_next_starts_after_it(monkeypatch):
    db = _leads(1500)
    first = _lead_window(monkeypatch, db, limit=1100)
    rest = _lead_window(monkeypatch, db, limit=1100, offset=1100)
    assert first["returned"] == 1100 and first["has_more"] is True
    assert rest["returned"] == 400 and rest["has_more"] is False
    ids = [l["id"] for l in first["leads"] + rest["leads"]]
    assert len(set(ids)) == 1500


# ── the rule, not the two spellings ──────────────────────────────────────────

@pytest.mark.parametrize("module,function", [("routers/relationships.py", "list_entities"), ("routers/lifecycle.py", "list_leads")])
def test_a_window_route_does_not_page_by_hand(module, function):
    """A `.range(` in these handlers is the fault returning: one request asks for up to 2,000 rows and the database answers
    at most 1,000. They read through `core.db_paging.fetch_window` (`test_no_module_carries_its_own_pager` holds the rest)."""
    tree = ast.parse((API / module).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
    calls = [n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "range" not in calls, f"{function} asks for its window in one .range()"
    names = [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "fetch_window" in names, f"{function} no longer reads through fetch_window"


# ── the tie-break direction fetch_window learned ─────────────────────────────

class _Recorder:
    def __init__(self, log):
        self.log, self.orders, self.start, self.stop = log, [], 0, 0

    def order(self, *args, **kwargs):
        self.orders.append((args, kwargs))
        return self

    def range(self, start, stop):
        self.start, self.stop = start, stop
        return self

    def execute(self):
        from types import SimpleNamespace
        self.log.append(list(self.orders))
        return SimpleNamespace(data=[{"id": i} for i in range(self.start, self.stop + 1)])


def test_fetch_window_breaks_a_tie_on_the_id_the_way_it_is_told():
    from core import db_paging
    log: list = []
    db_paging.fetch_window(lambda: _Recorder(log), "created_at", count=10, desc=True, id_desc=True)
    assert log[0] == [(("created_at",), {"desc": True}), (("id",), {"desc": True})], "newest id first, as the pipeline always had"
    log.clear()
    db_paging.fetch_window(lambda: _Recorder(log), "full_name", count=10, desc=False)
    assert log[0] == [(("full_name",), {"desc": False}), (("id",), {})], "the default tie-break is the id ascending"
