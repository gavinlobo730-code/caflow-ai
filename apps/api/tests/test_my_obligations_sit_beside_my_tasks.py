"""My Work lists the open obligations a person is named on, beside their tasks (POST-A-206, first slice).

WHAT WAS WRONG
    The obligation generator writes `compliance_records` only, and My Work and the Tasks screen read tasks only, so a preparer's GST and TDS
    returns were nowhere on their own list: they were on Deadlines, among everybody's.

WHAT IS HELD
    * `my_obligations` lists the open obligations the person is preparer, reviewer or approver on, with the parts they hold, and nobody else's;
    * a settled obligation (Filed, Not Required) is not work and is left out; an overdue one says so by the one rule;
    * a caller who is not firm-wide sees only their own clients' obligations; another firm's are never read;
    * an obligation nobody is named on is counted apart, so an empty list in a practice that names no preparers is not "nothing to do";
    * the route is `GET /api/compliance/obligations/mine`, behind `compliance` read, and My Work asks it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_obligation_service as svc

FIRM = "F-206"
ME, OTHER = "user-me", "user-other"
TODAY = date(2026, 11, 17)
WEB = Path(__file__).resolve().parents[2] / "web"


def _rec(**over):
    row = {"firm_id": FIRM, "client_id": "C-1", "compliance_type": "GST", "obligation_type": "GSTR3B",
           "period_label": "October 2026", "due_date": "2026-11-20", "status": "Not Started"}
    row.update(over)
    return compliance_records_repo.create(row)


def test_it_lists_what_i_am_named_on_with_my_parts_and_nothing_else():
    a = _rec(preparer_id=ME, assigned_to=ME)
    b = _rec(reviewer_id=ME, preparer_id=OTHER, client_id="C-2", due_date="2026-11-11")
    _rec(preparer_id=OTHER)
    out = svc.my_obligations(FIRM, ME, today=TODAY)
    ids = [o["id"] for o in out["obligations"]]
    assert set(ids) >= {a["id"], b["id"]}
    mine = {o["id"]: o for o in out["obligations"]}
    assert mine[a["id"]]["my_roles"] == ["preparer"]
    assert mine[b["id"]]["my_roles"] == ["reviewer"]
    assert all(OTHER not in o["my_roles"] for o in out["obligations"])
    assert mine[b["id"]]["overdue"] is True and mine[a["id"]]["overdue"] is False
    assert ids.index(b["id"]) < ids.index(a["id"]), "soonest due first"


def test_a_settled_obligation_is_not_work():
    filed = _rec(preparer_id=ME, status="Filed", filed_date="2026-11-10")
    nr = _rec(preparer_id=ME, status="Not Required")
    ids = {o["id"] for o in svc.my_obligations(FIRM, ME, today=TODAY)["obligations"]}
    assert filed["id"] not in ids and nr["id"] not in ids


def test_a_scoped_caller_sees_only_their_clients_and_another_firm_is_never_read():
    here = _rec(preparer_id=ME, client_id="C-9")
    theirs = _rec(preparer_id=ME, client_id="C-8")
    elsewhere = _rec(preparer_id=ME, firm_id="F-OTHER")
    ids = {o["id"] for o in svc.my_obligations(FIRM, ME, today=TODAY, allowed_client_ids={"C-9"})["obligations"]}
    assert here["id"] in ids and theirs["id"] not in ids and elsewhere["id"] not in ids


def test_an_obligation_nobody_is_named_on_is_counted_apart():
    before = svc.my_obligations("F-206-B", ME, today=TODAY)["unassigned_in_scope"]
    _rec(firm_id="F-206-B")
    out = svc.my_obligations("F-206-B", ME, today=TODAY)
    assert out["unassigned_in_scope"] == before + 1 and out["total"] == 0


def test_the_route_is_served_behind_compliance_read():
    from main import app
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/compliance/obligations/mine")
    assert "GET" in route.methods
    src = Path(__file__).resolve().parents[1].joinpath("routers/compliance_ops.py").read_text()
    seg = src[src.index('@router.get("/obligations/mine")'):]
    assert 'rbac("compliance", "read")' in seg[:400]


def test_my_work_asks_for_my_obligations():
    page = (WEB / "app/work/page.tsx").read_text()
    data = (WEB / "lib/data/compliance.ts").read_text()
    assert "getMyObligations" in page and "/api/compliance/obligations/mine" in data


def test_the_obligation_list_names_who_prepares_and_who_reviews(monkeypatch):
    monkeypatch.setattr(svc, "_dashboard_names", lambda firm, c, u: ({}, {"u-p": "Priya", "u-r": "Ravi"}))
    rows = svc.with_people_named(FIRM, [
        {"id": "1", "preparer_id": "u-p", "reviewer_id": "u-r"},
        {"id": "2", "assigned_to": "u-p"},
        {"id": "3"},
        {"id": "4", "preparer_id": "u-gone"},
    ])
    by = {r["id"]: r for r in rows}
    assert (by["1"]["preparer_name"], by["1"]["reviewer_name"]) == ("Priya", "Ravi")
    assert by["2"]["preparer_name"] == "Priya", "assigned_to is the preparer where only it is set"
    assert by["3"]["preparer_name"] is None and by["3"]["reviewer_name"] is None
    assert by["4"]["preparer_name"] is None and "preparer_name" in by["4"]


def test_deadlines_shows_the_preparer_and_reviewer_and_filters_on_the_assignee():
    page = (WEB / "app/deadlines/page.tsx").read_text()
    assert 'key: "preparer", header: "Preparer"' in page and 'key: "reviewer", header: "Reviewer"' in page
    assert 'label: "Assignee (preparer)"' in page and '"Not assigned"' in page
    data = (WEB / "lib/data/compliance.ts").read_text()
    assert "preparer_name: raw.preparer_name" in data and "raw.preparer_id ?? raw.assigned_to" in data
