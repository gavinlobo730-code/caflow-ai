"""Every banking route also asks `banking:read`, first, and the dashboard's unmatched-lines figure is the server's (migration 524, found by the independent review of it).

THE GAP
    Migration 524 makes the database answer ZERO ROWS to a person whose Banking read a Partner has blocked (and a Reviewer, who is
    below the floor). The Team screen's drawer has one toggle per action, so a Partner can untick Read and leave Write or Approve at the
    role default, and `rbac("banking", "write")` then passed. Every banking service reads under the caller's own sign-in, so that person
    met a 404 for a line they could not see, a batch route that reported "0 changed" as a success, or, on an insert (which asks for the
    new row back, so it meets the read policy as well), a database refusal worded as a fault of the server. A route that cannot work for
    a caller should refuse at the door, in the words every other refusal uses; the payroll finalise tier already does (POST-A-219).

WHAT IS HELD
    * the banking router carries `banking:read` as a ROUTER-LEVEL dependency, so every route (all of them, and any added later) asks it,
      and asks it before the route's own guard; a floor on the number of routes keeps the scan from going vacuous;
    * driven for real: with read refused and write, approve or the Partner-only reopen allowed, a sample of each kind answers 403
      naming `read` on `banking`; with read allowed the same request is not refused at the door (the negative control);
    * the unmatched-lines count the dashboard shows: it counts the client's `unmatched` lines only (not posted or ignored ones, not
      another client's or another firm's), it is refused to a Reviewer and to anyone whose Banking read is blocked, and a blocked
      person is told so rather than shown a 0.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import core.permissions as permissions
import routers.banking as rb
from main import app
from routers.banking import router as banking_router
from tests.test_bank_entry_service import _db, _line
from tests.test_bank_matching import CLIENT, FIRM

client = TestClient(app, raise_server_exceptions=False)

#: One of each kind of route the router has: a write, a delete, a batch write, the banking approval, and the Partner-only reopen
#: (which asks `accounting:approve`, not banking, and is behind the read gate too).
SAMPLE = [
    ("POST", "/api/banking/accounts", {}, ("banking", "write")),
    ("POST", "/api/banking/statements/import", {}, ("banking", "write")),
    ("DELETE", "/api/banking/rules/r1", None, ("banking", "write")),
    ("POST", "/api/banking/transactions/batch-exclude", {}, ("banking", "write")),
    ("PUT", "/api/banking/reconciliations/rec1/adjustment", {}, ("banking", "approve")),
    ("POST", "/api/banking/reconciliations/rec1/reopen", {}, ("accounting", "approve")),
]


def _names(route) -> list[str]:
    return [d.call.__name__ for d in route.dependant.dependencies]


def test_every_banking_route_asks_banking_read_and_asks_it_first():
    seen = 0
    for route in banking_router.routes:
        rbac_names = [n for n in _names(route) if n.startswith("rbac_")]
        seen += 1
        assert rbac_names, f"{route.path} asks no permission at all"
        assert rbac_names[0] == "rbac_banking_read", (
            f"{route.path} asks {rbac_names[0]} before banking:read, so a person blocked from reading meets the wrong refusal")
    assert seen >= 60, f"expected the whole banking router (about 68 routes), found {seen}: the scan has gone vacuous"


def test_the_read_gate_is_declared_on_the_router_so_a_new_route_cannot_forget_it():
    names = [d.dependency.__name__ for d in banking_router.dependencies]
    assert names == ["rbac_banking_read"], names


def _as(monkeypatch, allowed, role="Partner"):
    """The caller holds exactly the `allowed` pairs, whatever the role table says."""
    monkeypatch.setattr(permissions, "can_user", lambda user, resource, action: (resource, action) in allowed)
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"{role}-1"}


@pytest.mark.usefixtures("dev_header_auth")
@pytest.mark.parametrize("method, path, body, held", SAMPLE, ids=[f"{m} {p.split('/api/banking/')[1]}" for m, p, _, _ in SAMPLE])
def test_a_person_blocked_from_reading_banking_is_told_so_at_the_door(monkeypatch, method, path, body, held):
    headers = _as(monkeypatch, allowed={held})
    r = client.request(method, path, json=body, headers=headers) if body is not None else client.request(method, path, headers=headers)
    assert r.status_code == 403, r.text
    assert "'read' on 'banking'" in r.json()["detail"], r.json()


@pytest.mark.usefixtures("dev_header_auth")
@pytest.mark.parametrize("method, path, body, held", SAMPLE, ids=[f"{m} {p.split('/api/banking/')[1]}" for m, p, _, _ in SAMPLE])
def test_negative_control_with_read_allowed_the_request_is_not_refused_at_the_door(monkeypatch, method, path, body, held):
    headers = _as(monkeypatch, allowed={held, ("banking", "read")})
    r = client.request(method, path, json=body, headers=headers) if body is not None else client.request(method, path, headers=headers)
    detail = r.json().get("detail", "") if r.headers.get("content-type", "").startswith("application/json") else ""
    assert "'read' on 'banking'" not in str(detail), r.text


# ── the unmatched-lines figure on the accounting dashboard ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    fake = _db()
    monkeypatch.setattr(rb, "_db", lambda: fake)
    return fake


def _h(role: str) -> dict:
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"{role}-1"}


@pytest.mark.usefixtures("dev_header_auth")
def test_the_count_is_the_clients_unmatched_lines_and_only_those(db):
    _line(db, "t1", "A", match_status="unmatched")
    _line(db, "t2", "B", match_status="unmatched")
    _line(db, "t3", "C", match_status="unmatched")
    _line(db, "t4", "D", match_status="posted")
    _line(db, "t5", "E", match_status="ignored")
    other_client = _line(db, "t6", "F", match_status="unmatched")
    other_client["client_id"] = "some-other-client"
    other_firm = _line(db, "t7", "G", match_status="unmatched")
    other_firm["firm_id"] = "some-other-firm"
    r = client.get("/api/banking/unmatched-count", params={"client_id": CLIENT}, headers=_h("Executive"))
    assert r.status_code == 200, r.text
    assert r.json() == {"success": True, "data": {"unmatched": 3}, "error": None}


@pytest.mark.usefixtures("dev_header_auth")
def test_a_client_with_no_unmatched_lines_has_a_real_zero(db):
    _line(db, "t1", "A", match_status="posted")
    r = client.get("/api/banking/unmatched-count", params={"client_id": CLIENT}, headers=_h("Executive"))
    assert r.status_code == 200 and r.json()["data"] == {"unmatched": 0}


@pytest.mark.usefixtures("dev_header_auth")
def test_a_reviewer_is_refused_and_is_not_handed_a_zero(db):
    _line(db, "t1", "A", match_status="unmatched")
    r = client.get("/api/banking/unmatched-count", params={"client_id": CLIENT}, headers=_h("Reviewer"))
    assert r.status_code == 403, r.text
    assert "unmatched" not in r.text, "a refusal must not carry a figure"


@pytest.mark.usefixtures("dev_header_auth")
def test_a_manager_whose_banking_read_is_blocked_is_refused(db, monkeypatch):
    _line(db, "t1", "A", match_status="unmatched")
    headers = _as(monkeypatch, allowed={("banking", "write")}, role="Manager")
    r = client.get("/api/banking/unmatched-count", params={"client_id": CLIENT}, headers=headers)
    assert r.status_code == 403, r.text
    assert "'read' on 'banking'" in r.json()["detail"]


@pytest.mark.usefixtures("dev_header_auth")
def test_the_route_needs_a_client(db):
    r = client.get("/api/banking/unmatched-count", headers=_h("Executive"))
    assert r.status_code == 422


@pytest.mark.usefixtures("dev_header_auth")
def test_the_count_asks_whether_the_caller_may_see_this_client(db, monkeypatch):
    """Read with the caller's own sign-in the database would also hide a client the caller is not assigned to, but the route does not
    lean on that: it asks the same question every other client-scoped read asks, first."""
    from fastapi import HTTPException

    _line(db, "t1", "A", match_status="unmatched")
    asked: list[str] = []

    def refuse(current_user, client_id):
        asked.append(client_id)
        raise HTTPException(status_code=403, detail="not your client")

    monkeypatch.setattr(rb, "assert_client_access", refuse)
    r = client.get("/api/banking/unmatched-count", params={"client_id": CLIENT}, headers=_h("Executive"))
    assert r.status_code == 403 and asked == [CLIENT], (r.status_code, asked)
    assert "unmatched" not in r.text


@pytest.mark.usefixtures("dev_header_auth")
def test_a_person_who_may_read_banking_and_not_write_it_gets_the_count(db, monkeypatch):
    """The count is a READ: it asks `banking:read` and nothing more. A route that also asked write would turn a person who may only
    look (a Manager a Partner has narrowed to read) into a dash on the dashboard."""
    _line(db, "t1", "A", match_status="unmatched")
    _line(db, "t2", "B", match_status="unmatched")
    headers = _as(monkeypatch, allowed={("banking", "read")}, role="Manager")
    r = client.get("/api/banking/unmatched-count", params={"client_id": CLIENT}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == {"unmatched": 2}


def test_the_web_client_asks_for_a_path_the_router_serves():
    """The dashboard's call is a string in `apps/web/lib/api/index.ts`; a misspelt path would 404 for everyone and the tile would show
    a dash forever, which no screen test of the tile can see."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "api" / "index.ts").read_text()
    m = re.search(r"unmatchedCount:[^`]*`(/api/banking/[a-z-]+)\?", src)
    assert m, "api.banking.unmatchedCount is not defined in apps/web/lib/api/index.ts"
    served = {(r.path, method) for r in banking_router.routes for method in r.methods}
    assert (m.group(1), "GET") in served, f"the web client asks GET {m.group(1)}, which the banking router does not serve"
