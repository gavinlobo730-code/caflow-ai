"""The firm-level /gst and /income-tax trackers read and add `compliance_calendar` rows through the API (POST-A-208).

WHAT WAS WRONG
    Both trackers read the calendar from the browser over PostgREST and the income-tax one inserted into it there too, so `rbac()` never ran,
    the caller's client assignment was whatever row security said and the insert wrote no audit event. Only their Mark Filed went through
    the server. The list they show did not change and is not changed here: the calendar, not the obligation store.

WHAT IS HELD (through the real routes over the shared in-memory database)
    * the GST family lists GSTR-1, GSTR-3B and GSTR-9 and nothing else, the income-tax family only the ITR, both with one client embed;
    * only this firm's rows, oldest due date first; a caller assigned to some clients reads only those (a Partner reads all);
    * adding a row creates it PENDING, with the form in the notes, for the caller's own client only (404 otherwise, nothing stored),
      writes an audit event naming the person by the auth id, and answers a second one for the same client, type and period in a sentence
      (409) and not in the database's words;
    * a return type the calendar has no value for, a day that is not one and a period that ends before it starts are 422s;
    * the reads and the add are asked of `compliance_record` read and write, and the add is made with the privileged client.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.compliance as comp
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "p@f.test", "role": "Partner"}
EXEC = {"id": "u2", "firm_id": FIRM, "auth_user_id": "a2", "email": "e@f.test", "role": "Executive"}


@pytest.fixture
def world(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [comp])
    monkeypatch.setattr(comp, "_USE_MOCK", False)
    events = []
    monkeypatch.setattr(comp, "log_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(comp, "assert_client_access", lambda user, cid, **k: None)
    d.events = events
    for cid in ("c1", "c2"):
        d.seed("clients", {"id": cid, "firm_id": FIRM, "client_name": f"Client {cid}", "gstin": "G", "pan": "P", "entity_type": "Company"})

    def row(i, ctype, due, client="c1", firm=FIRM):
        return d.seed("compliance_calendar", {"id": i, "firm_id": firm, "client_id": client, "compliance_type": ctype,
                      "period_start": "2026-04-01", "period_end": "2026-04-30", "due_date": due, "filing_status": "pending"})
    row("r3", "GSTR3B", "2026-05-20"); row("r1", "GSTR1", "2026-05-11"); row("r9", "GSTR9", "2026-12-31")
    row("t1", "TDS26Q", "2026-07-31"); row("i1", "ITR", "2026-07-31"); row("x1", "GSTR1", "2026-05-11", firm="firm-2")
    return d


def _ids(out):
    assert out["success"] is True, out
    return [r["id"] for r in out["data"]]


def test_the_gst_family_lists_the_three_gst_returns_and_nothing_else_oldest_due_first(world):
    assert _ids(comp.calendar_tracker_rows(family="gst", current_user=PARTNER)) == ["r1", "r3", "r9"]


def test_the_itr_family_lists_only_the_income_tax_return(world):
    assert _ids(comp.calendar_tracker_rows(family="itr", current_user=PARTNER)) == ["i1"]


def test_another_firms_rows_are_never_read(world):
    assert "x1" not in _ids(comp.calendar_tracker_rows(family="gst", current_user=PARTNER))


def test_a_caller_assigned_to_some_clients_reads_only_those(world, monkeypatch):
    world.seed("compliance_calendar", {"id": "r2c2", "firm_id": FIRM, "client_id": "c2", "compliance_type": "GSTR1",
                                       "period_start": "2026-05-01", "period_end": "2026-05-31", "due_date": "2026-06-11"})
    monkeypatch.setattr("core.authz.effective_client_ids", lambda u: {"c2"})
    assert _ids(comp.calendar_tracker_rows(family="gst", current_user=EXEC)) == ["r2c2"]
    monkeypatch.setattr("core.authz.effective_client_ids", lambda u: None)
    assert "r2c2" in _ids(comp.calendar_tracker_rows(family="gst", current_user=PARTNER))


def _add(user=PARTNER, **kw):
    body = {"client_id": "c1", "compliance_type": "ITR", "period_start": "2025-04-01", "period_end": "2026-03-31",
            "due_date": "2026-07-31", "notes": "ITR-3", **kw}
    return comp.add_calendar_entry(comp.CalendarEntryIn(**body), current_user=user)


def test_an_added_return_is_pending_carries_the_form_and_is_audited_by_the_auth_id(world):
    out = _add()
    assert out["success"] is True, out
    row = next(r for r in world.rows("compliance_calendar") if r["period_start"] == "2025-04-01")
    assert row["filing_status"] == "pending" and row["filed_date"] is None and row["notes"] == "ITR-3" and row["firm_id"] == FIRM
    [(args, kw)] = world.events
    assert args[:2] == (FIRM, "compliance_calendar") and args[3] == "create" and kw["actor_id"] == "a1"


def test_a_blank_note_is_stored_as_none(world):
    _add(compliance_type="GSTR1", notes="  ")
    row = next(r for r in world.rows("compliance_calendar") if r["period_start"] == "2025-04-01")
    assert row["notes"] is None


def test_a_client_the_caller_may_not_reach_is_a_404_and_nothing_is_stored(world, monkeypatch):
    def refuse(user, cid, **k):
        raise HTTPException(status_code=404, detail="Not found")
    monkeypatch.setattr(comp, "assert_client_access", refuse)
    before = len(world.rows("compliance_calendar"))
    with pytest.raises(HTTPException) as e:
        _add()
    assert e.value.status_code == 404 and len(world.rows("compliance_calendar")) == before and world.events == []


def test_a_duplicate_is_answered_in_a_sentence(world, monkeypatch):
    class Boom(Exception):
        pass
    real = world.table

    def table(name):
        t = real(name)
        if name == "compliance_calendar":
            orig = t.insert
            def insert(*a, **k):
                q = orig(*a, **k)
                q.execute = lambda: (_ for _ in ()).throw(Boom('{"code": "23505", "message": "duplicate key value"}'))
                return q
            t.insert = insert
        return t
    monkeypatch.setattr(world, "table", table)
    with pytest.raises(HTTPException) as e:
        _add()
    assert e.value.status_code == 409 and "already has a ITR on the calendar" in e.value.detail and "23505" not in e.value.detail
    assert world.events == []


@pytest.mark.parametrize("bad", [{"compliance_type": "TDS26Q"}, {"due_date": "31/07/2026"}, {"period_start": "2026-02-30"},
                                 {"period_start": "2026-04-01", "period_end": "2026-03-31"}])
def test_a_value_the_calendar_cannot_hold_is_refused(bad):
    with pytest.raises(ValidationError):
        comp.CalendarEntryIn(**{"client_id": "c1", "compliance_type": "ITR", "period_start": "2025-04-01",
                                "period_end": "2026-03-31", "due_date": "2026-07-31", **bad})


def test_the_routes_ask_the_right_permission_and_the_add_writes_with_the_privileged_client():
    src = Path(comp.__file__).read_text()
    tree = ast.parse(src)
    fns = {n.name: ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "rbac('compliance_record', 'read')" in fns["calendar_tracker_rows"]
    assert "rbac('compliance_record', 'write')" in fns["add_calendar_entry"]
    assert "privileged_for" in fns["add_calendar_entry"] and "assert_client_access" in fns["add_calendar_entry"]
    assert "filter_by_client" in fns["calendar_tracker_rows"] and "fetch_all_ordered" in fns["calendar_tracker_rows"]
