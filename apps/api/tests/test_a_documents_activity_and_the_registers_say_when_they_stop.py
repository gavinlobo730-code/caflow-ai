"""POST-A-259: a document's activity is the document's, and a register list says when it stopped short.

THE TIMELINE (six drawers: a sales invoice, a purchase bill and the four notes)
    Each drawer asked `GET /api/timeline` for the CLIENT's latest hundred events of every kind and kept the ones that named
    its document in the browser. A document older than the client's hundredth event therefore read "No activity recorded
    yet": an empty state that was only an artefact of where the window stopped. The route filters on `entity_type` and
    `entity_id` now and answers `has_more` (one row more than the window is read and never returned).

THE REGISTERS (the entity register and the pipeline's leads)
    The relationship explorer asked for 100 entities, the ownership map took the default 50, the role form's picker 200, the
    register page guessed "capped" from `rows == 2000`, and the pipeline board guessed the same for leads. Each list endpoint
    answers a window now: `{<rows>, returned, has_more, limit, max_limit}`.
"""
from __future__ import annotations

import typing
from uuid import UUID

import pytest

import routers.lifecycle as lc
import routers.relationships as rel
import routers.timeline as tl
from core import list_window
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "F1", "F2"
CLIENT = "C1"
DOC = "11111111-1111-4111-8111-111111111111"
OTHER_DOC = "22222222-2222-4222-8222-222222222222"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}


def _ts(n: int) -> str:
    """A strictly increasing instant, so 'newest first' has one answer."""
    return f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00"


@pytest.fixture
def timeline(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr("core.authz.assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(tl, "_USE_MOCK", False)
    return db


def _seed(db, n, *, entity_id, entity_type="sales_invoice", firm=FIRM, start=0, tag="e"):
    for i in range(n):
        db.seed("client_timeline_events", {
            "id": f"{tag}-{entity_id[:4]}-{start + i:04d}", "client_id": CLIENT, "firm_id": firm,
            "entity_type": entity_type, "entity_id": entity_id, "title": f"{tag} {start + i}",
            "created_at": _ts(start + i), "deleted_at": None,
        })


def _call(**kw):
    args = dict(client_id=CLIENT, category=None, severity=None, financial_year=None,
                entity_type=None, entity_id=None, limit=100, offset=0, current_user=USER)
    args.update(kw)
    return tl.list_timeline_events(**args)["data"]


# ── a document's events are not crowded out by the client's newer events of other kinds ──────────────────────────────

def test_a_document_older_than_the_clients_hundredth_event_still_has_its_history(timeline):
    _seed(timeline, 2, entity_id=DOC, start=0, tag="doc")                    # the document's two events, the oldest
    _seed(timeline, 150, entity_id=OTHER_DOC, entity_type="purchase_bill", start=10, tag="noise")

    # The old read: the client's latest hundred of any kind. The document is not in it.
    window = _call(limit=100)
    assert DOC not in {e["entity_id"] for e in window["events"]}

    # The new read: the document's own events.
    mine = _call(entity_type="sales_invoice", entity_id=DOC)
    assert [e["title"] for e in mine["events"]] == ["doc 1", "doc 0"]
    assert mine["has_more"] is False and mine["returned"] == 2


def test_the_filter_names_the_record_and_both_halves_are_asked(timeline):
    _seed(timeline, 2, entity_id=DOC, entity_type="sales_invoice", start=0, tag="inv")
    _seed(timeline, 2, entity_id=DOC, entity_type="credit_note", start=5, tag="cn")      # same id, other kind of record
    assert {e["title"] for e in _call(entity_type="sales_invoice", entity_id=DOC)["events"]} == {"inv 0", "inv 1"}
    assert {e["title"] for e in _call(entity_id=DOC)["events"]} == {"inv 0", "inv 1", "cn 5", "cn 6"}
    assert {e["title"] for e in _call(entity_type="credit_note")["events"]} == {"cn 5", "cn 6"}


def test_another_firms_event_for_the_same_record_is_never_returned(timeline):
    _seed(timeline, 2, entity_id=DOC, start=0, tag="mine")
    _seed(timeline, 3, entity_id=DOC, firm=OTHER_FIRM, start=5, tag="theirs")
    got = _call(entity_type="sales_invoice", entity_id=DOC)["events"]
    assert {e["firm_id"] for e in got} == {FIRM} and len(got) == 2


# ── the window says when it stopped, and the probe row is never returned ───────────────────────────────────────────────

def test_a_window_cut_short_says_so_and_returns_the_newest(timeline):
    _seed(timeline, 120, entity_id=DOC)
    out = _call(entity_type="sales_invoice", entity_id=DOC, limit=100)
    assert out["has_more"] is True and out["returned"] == len(out["events"]) == 100
    assert out["limit"] == 100 and out["max_limit"] == list_window.MAX_LIST_LIMIT
    assert out["events"][0]["title"] == "e 119" and out["events"][-1]["title"] == "e 20"


def test_a_window_that_is_exactly_full_is_not_reported_as_cut_short(timeline):
    _seed(timeline, 100, entity_id=DOC)
    out = _call(entity_type="sales_invoice", entity_id=DOC, limit=100)
    assert out["has_more"] is False and out["returned"] == 100


def test_the_next_window_starts_where_the_last_stopped(timeline):
    _seed(timeline, 7, entity_id=DOC)
    first = _call(entity_type="sales_invoice", entity_id=DOC, limit=3)
    second = _call(entity_type="sales_invoice", entity_id=DOC, limit=3, offset=3)
    assert [e["title"] for e in first["events"]] == ["e 6", "e 5", "e 4"] and first["has_more"] is True
    assert [e["title"] for e in second["events"]] == ["e 3", "e 2", "e 1"] and second["has_more"] is True


def test_the_in_memory_path_filters_and_windows_the_same_way(monkeypatch):
    import services.timeline_service as ts
    events = []
    for i in range(5):
        events.append({"id": f"a{i}", "client_id": CLIENT, "firm_id": FIRM, "entity_type": "sales_invoice",
                       "entity_id": DOC, "created_at": _ts(i), "title": f"a{i}"})
    events.append({"id": "b", "client_id": CLIENT, "firm_id": FIRM, "entity_type": "sales_invoice",
                   "entity_id": OTHER_DOC, "created_at": _ts(9), "title": "b"})
    monkeypatch.setattr(ts, "MOCK_TIMELINE_EVENTS", events, raising=False)
    monkeypatch.setattr(tl, "_USE_MOCK", True)
    monkeypatch.setattr("core.authz.assert_client_access", lambda *a, **k: None)
    out = _call(entity_type="sales_invoice", entity_id=UUID(DOC), limit=3)
    assert [e["id"] for e in out["events"]] == ["a4", "a3", "a2"] and out["has_more"] is True


def _bounds(fn, name="limit"):
    hint = typing.get_type_hints(fn, include_extras=True)[name]
    meta = [m for m in hint.__metadata__ if hasattr(m, "metadata")]
    assert meta, f"{fn.__name__}.{name} carries no Query bounds"
    bounds = {type(c).__name__: c for c in meta[0].metadata}
    return bounds["Ge"].ge, bounds["Le"].le


def test_the_timeline_limit_is_bounded_and_the_record_id_must_be_a_uuid():
    assert _bounds(tl.list_timeline_events) == (1, list_window.MAX_LIST_LIMIT)
    hint = typing.get_type_hints(tl.list_timeline_events)["entity_id"]
    assert UUID in typing.get_args(hint), "a record id that is not a uuid would reach the database as a 22P02 and answer 500"


# ── the entity register ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def entities(monkeypatch):
    monkeypatch.setattr(rel, "_db", lambda: None)
    rel._MOCK_ENTITIES.clear()
    yield rel._MOCK_ENTITIES
    rel._MOCK_ENTITIES.clear()


def _entity(i, firm=FIRM):
    return {"id": f"e-{i:04d}", "firm_id": firm, "full_name": f"Name {i:04d}", "entity_type": "Individual",
            "pan": None, "email": None}


def test_the_register_says_when_more_entities_exist_than_the_window(entities):
    entities.extend(_entity(i) for i in range(30))
    entities.append(_entity(99, firm=OTHER_FIRM))
    out = rel.list_entities(entity_type=None, search=None, limit=25, offset=0, current_user=USER)["data"]
    assert out["has_more"] is True and out["returned"] == len(out["entities"]) == 25
    assert out["max_limit"] == rel.ENTITY_LIST_MAX and out["limit"] == 25
    assert out["entities"][0]["full_name"] == "Name 0000"           # by name
    assert all(e["firm_id"] == FIRM for e in out["entities"])


def test_a_register_that_fits_the_window_is_complete(entities):
    entities.extend(_entity(i) for i in range(25))
    out = rel.list_entities(entity_type=None, search=None, limit=25, offset=0, current_user=USER)["data"]
    assert out["has_more"] is False and out["returned"] == 25


def test_the_register_ceiling_is_its_own_and_served(entities):
    assert _bounds(rel.list_entities) == (1, rel.ENTITY_LIST_MAX)
    assert rel.ENTITY_LIST_MAX >= list_window.MAX_LIST_LIMIT


# ── the pipeline's leads ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_pipeline_says_when_more_leads_exist_than_the_window(monkeypatch):
    monkeypatch.setattr(lc, "_db", lambda: None)
    leads = [{"id": f"L{i:03d}", "firm_id": FIRM, "stage": "Lead", "is_converted": False} for i in range(12)]
    monkeypatch.setattr(lc, "_MOCK_LEADS", leads)
    out = lc.list_leads(stage=None, assigned_to=None, limit=10, offset=0, current_user=USER)["data"]
    assert out["has_more"] is True and out["returned"] == len(out["leads"]) == 10
    assert out["max_limit"] == lc.LEAD_LIST_MAX
    full = lc.list_leads(stage=None, assigned_to=None, limit=12, offset=0, current_user=USER)["data"]
    assert full["has_more"] is False and full["returned"] == 12


def test_the_lead_limit_is_bounded_at_the_pipelines_ceiling():
    assert _bounds(lc.list_leads) == (1, lc.LEAD_LIST_MAX)


def test_nothing_in_the_three_routes_still_answers_a_bare_list():
    import inspect
    for fn in (tl.list_timeline_events, rel.list_entities, lc.list_leads):
        src = inspect.getsource(fn)
        assert "api_response(True, res.data or [])" not in src, f"{fn.__name__} still answers a bare list"
        assert "has_more" in src or "_window(" in src, f"{fn.__name__} does not build a window"
