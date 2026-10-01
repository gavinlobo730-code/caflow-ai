"""practice_management-17 — the firm calendar reads the obligation calendar, and the
obligation calendar can be asked for ONE MONTH without hiding what is late.

WHAT WAS WRONG
    `/calendar` generated its deadlines in the browser: the 11th and the 20th for
    every client, advance-tax dates, AOC-4 and MGT-7 a day off the compliance
    engine, no QRMP or state-group rule, every deadline attached to all clients,
    and a done tick kept in component state. The backend already served
    `GET /api/compliance/obligations/calendar` and nothing called it. Pointing a
    month grid at it raised one question the endpoint could not answer — it read
    EVERY obligation the firm had ever generated and returned them all, so a
    screen showing one month paid for every year.

WHAT IS ASSERTED
    * `date_from` / `date_to` bound upcoming and completed by due date, both
      inclusive, and a window that is half given, backwards or wider than the cap
      is REFUSED rather than answered with some other window;
    * THE OVERDUE BUCKET IS NEVER WINDOWED: an obligation that is late is late
      whichever month the screen is showing, so navigating to another month cannot
      make it vanish; a FILED row outside the window is not dragged in by that;
    * a row that is in the window AND overdue is returned once;
    * the dates are the engine's, untouched: a QRMP client's GSTR-3B comes back on
      the 22nd or 24th `compliance_engine` computes for their state, never the 20th;
    * the assignment scope still applies to every bucket;
    * with no window the answer is what it always was.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.compliance_ops as ops
from core.auth import get_current_user
from mock_data import MOCK_COMPLIANCE_RECORDS
from services import compliance_engine as ce
from services import compliance_obligation_service as ob

FIRM = "firm-cal-1"
MINE, THEIRS = "client-mine", "client-theirs"
PARTNER = {"id": "u-ptr", "firm_id": FIRM, "role": "Partner", "email": "p@f.in"}
TODAY = date(2026, 10, 10)


@pytest.fixture(autouse=True)
def records(monkeypatch):
    saved = list(MOCK_COMPLIANCE_RECORDS)
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setattr(ob, "ist_today", lambda: TODAY)
    yield MOCK_COMPLIANCE_RECORDS
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_COMPLIANCE_RECORDS.extend(saved)


def _row(rid, due, status="Not Started", client=MINE, otype="GSTR3B", label=None):
    row = {"id": rid, "firm_id": FIRM, "client_id": client, "obligation_type": otype,
           "compliance_type": "GST", "period_label": label or f"{otype} {due}",
           "period_start": due, "period_end": due, "due_date": due, "status": status,
           "created_at": "2026-04-01T00:00:00+00:00", "updated_at": "2026-04-01T00:00:00+00:00"}
    MOCK_COMPLIANCE_RECORDS.append(row)
    return row


def _client(user=PARTNER):
    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _ids(payload, bucket):
    return sorted(r["id"] for r in payload["data"][bucket])


def _get(**params):
    res = _client().get("/api/compliance/obligations/calendar", params=params)
    return res


# ── the window ───────────────────────────────────────────────────────────────

def test_a_window_bounds_upcoming_and_completed_by_due_date_inclusive():
    _row("before", "2026-10-31")
    _row("first", "2026-11-01")
    _row("mid", "2026-11-15")
    _row("last", "2026-11-30")
    _row("after", "2026-12-01")
    _row("done-in", "2026-11-10", status="Filed")
    _row("done-out", "2026-12-10", status="Filed")
    res = _get(date_from="2026-11-01", date_to="2026-11-30").json()
    assert _ids(res, "upcoming") == ["first", "last", "mid"], "both ends are inclusive, neighbours are not in"
    assert _ids(res, "completed") == ["done-in"], "a filed row outside the window is not in the answer"


def test_the_overdue_bucket_is_never_windowed():
    """Another month on screen must not make a late filing disappear."""
    _row("late-sep", "2026-09-20")
    _row("late-aug", "2026-08-20")
    _row("future", "2026-12-20")
    res = _get(date_from="2026-12-01", date_to="2026-12-31").json()
    assert _ids(res, "overdue") == ["late-aug", "late-sep"], "late is late whichever month is showing"
    assert _ids(res, "upcoming") == ["future"]


def test_a_filed_row_outside_the_window_is_not_dragged_in_as_late():
    _row("filed-long-ago", "2026-03-20", status="Filed")
    _row("completed-long-ago", "2026-03-11", status="Completed")
    res = _get(date_from="2026-11-01", date_to="2026-11-30").json()
    assert _ids(res, "overdue") == [] and _ids(res, "completed") == []


def test_a_row_that_is_in_the_window_and_overdue_is_returned_once():
    _row("both", "2026-10-05")
    res = _get(date_from="2026-10-01", date_to="2026-10-31").json()
    assert _ids(res, "overdue") == ["both"]
    assert _ids(res, "upcoming") == [] and _ids(res, "completed") == []


def test_due_today_is_upcoming_not_overdue():
    _row("today", TODAY.isoformat())
    res = _get(date_from="2026-10-01", date_to="2026-10-31").json()
    assert _ids(res, "upcoming") == ["today"] and _ids(res, "overdue") == []


# ── what is refused ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("params,why", [
    ({"date_from": "2026-11-01"}, "half a window"),
    ({"date_to": "2026-11-30"}, "half a window"),
    ({"date_from": "2026-11-30", "date_to": "2026-11-01"}, "backwards"),
    ({"date_from": "2025-01-01", "date_to": "2026-11-01"}, "wider than the cap"),
    ({"date_from": "not-a-date", "date_to": "2026-11-01"}, "not a date"),
])
def test_a_window_that_is_not_one_is_refused_not_answered_with_another(params, why):
    assert _get(**params).status_code == 422, why


def test_the_widest_window_allowed_is_the_cap():
    start = date(2026, 1, 1)
    ok = start + timedelta(days=ops.MAX_CALENDAR_WINDOW_DAYS)
    assert _get(date_from=start.isoformat(), date_to=ok.isoformat()).status_code == 200
    assert _get(date_from=start.isoformat(),
                date_to=(ok + timedelta(days=1)).isoformat()).status_code == 422


def test_with_no_window_the_answer_is_what_it_always_was():
    _row("a", "2026-03-11", status="Filed")
    _row("b", "2026-09-01")
    _row("c", "2027-01-11")
    res = _get().json()
    assert (_ids(res, "completed"), _ids(res, "overdue"), _ids(res, "upcoming")) == (["a"], ["b"], ["c"])


# ── the dates are the engine's ───────────────────────────────────────────────

@pytest.mark.parametrize("state,day", [("27", 22), ("07", 24)])
def test_a_qrmp_clients_gstr_3b_comes_back_on_the_22nd_or_24th_the_engine_computes(state, day):
    """Rule 61A: category X states 22nd, category Y 24th — never the monthly 20th
    the browser calendar showed every client. The screen holds no date of its own;
    this asserts the endpoint returns the engine's, untouched."""
    for spec in ob._gst_obligations("2026-27", ce.QUARTERLY, state):
        MOCK_COMPLIANCE_RECORDS.append({**spec, "id": f"{spec['obligation_type']}-{spec['period_start']}",
                                        "firm_id": FIRM, "client_id": MINE, "status": "Not Started",
                                        "created_at": "2026-04-01T00:00:00+00:00",
                                        "updated_at": "2026-04-01T00:00:00+00:00"})
    res = _get(date_from="2026-10-01", date_to="2026-12-31").json()["data"]
    rows = [r for r in res["upcoming"] if r["obligation_type"] == "GSTR3B"]
    assert [r["due_date"] for r in rows] == [f"2026-10-{day}"], "the quarter ending September, due after it"
    assert rows[0]["due_date"] == ce.gstr3b_due_date(2026, 7, ce.QUARTERLY, state).isoformat()
    assert rows[0]["period_label"].startswith("GSTR-3B"), "named by the engine's own label"
    assert not any(r["due_date"] == "2026-10-20" and r["obligation_type"] == "GSTR3B"
                   for r in res["upcoming"]), "no monthly 20th for a quarterly filer"


# ── scope ────────────────────────────────────────────────────────────────────

def test_the_assignment_scope_still_applies_to_every_bucket(monkeypatch):
    _row("mine-up", "2026-11-12")
    _row("theirs-up", "2026-11-12", client=THEIRS)
    _row("mine-late", "2026-09-12")
    _row("theirs-late", "2026-09-12", client=THEIRS)
    _row("mine-done", "2026-11-02", status="Filed")
    _row("theirs-done", "2026-11-02", status="Filed", client=THEIRS)
    monkeypatch.setattr(ops, "filter_by_client",
                        lambda user, rows, key="client_id": [r for r in rows if r.get(key) == MINE])
    res = _get(date_from="2026-11-01", date_to="2026-11-30").json()
    assert _ids(res, "upcoming") == ["mine-up"]
    assert _ids(res, "overdue") == ["mine-late"]
    assert _ids(res, "completed") == ["mine-done"]


# ── the database branch pushes the window into the query ─────────────────────

def test_the_database_read_is_bounded_by_the_window_and_the_overdue_read_is_not(monkeypatch):
    """The mock suite above never reaches the PostgREST branch of the repository,
    which is where the bound has to be in the QUERY. Run against the in-memory
    database double, counting what the paged reads actually deliver: a month's grid
    over three years of obligations fetches the month's rows plus the late ones —
    not every row the firm has ever generated."""
    from tests.e2e_harness import FakeDB
    import repositories.compliance_records_repository as repo_mod
    import domain.compliance_record_service as svc_mod

    db = FakeDB()
    seeded = 0
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            for c in range(5):
                due = date(year, month, 20)
                db.seed("compliance_records", {
                    "firm_id": FIRM, "client_id": f"c{c}", "obligation_type": "GSTR3B",
                    "compliance_type": "GST", "period_label": f"GSTR-3B {year}-{month}",
                    "period_start": due.isoformat(), "period_end": due.isoformat(),
                    "due_date": due.isoformat(), "deleted_at": None,
                    "status": "Filed" if due < date(2026, 9, 1) else "Not Started",
                    "created_at": "2026-04-01T00:00:00+00:00", "updated_at": "2026-04-01T00:00:00+00:00"})
                seeded += 1
    delivered: list[int] = []
    real = repo_mod.fetch_all

    def counting(make_query, key="id", **kw):
        rows = real(make_query, key, **kw)
        delivered.append(len(rows))
        return rows

    monkeypatch.setattr(repo_mod, "_USE_MOCK", False)
    monkeypatch.setattr(repo_mod, "_get_db", lambda: db)
    monkeypatch.setattr(repo_mod, "fetch_all", counting)

    cal = ob.calendar(FIRM, today=TODAY, date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    assert sorted({r["due_date"] for r in cal["upcoming"]}) == ["2026-11-20"] and len(cal["upcoming"]) == 5
    # Late: the five September-2026 rows (due 20 Sep, not filed) — unfiled and before today.
    assert sorted({r["due_date"] for r in cal["overdue"]}) == ["2026-09-20"]
    assert sum(delivered) == 5 + 5, (
        f"the reads delivered {delivered} rows out of {seeded} on file: the window must be in the QUERY")
    assert seeded == 180


def test_the_unbounded_database_read_is_unchanged_for_every_other_caller(monkeypatch):
    from tests.e2e_harness import FakeDB
    import repositories.compliance_records_repository as repo_mod
    db = FakeDB()
    for i in range(7):
        db.seed("compliance_records", {"firm_id": FIRM, "client_id": MINE, "due_date": f"2026-0{i + 1}-20",
                                       "status": "Not Started", "deleted_at": None})
    monkeypatch.setattr(repo_mod, "_USE_MOCK", False)
    monkeypatch.setattr(repo_mod, "_get_db", lambda: db)
    assert len(repo_mod.compliance_records_repo.find_all(firm_id=FIRM)) == 7
