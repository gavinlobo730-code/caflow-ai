"""POST-A-543, Request access: a member of staff asks for a permission, a Partner who is not the asker decides it, and an
approval writes that one permission through the function the Team screen calls.

WHAT IS HELD
    * who may ask: every member of staff, a Reviewer included, through a door of its own; not a Partner (who changes
      access on the Team screen), and nobody outside the staff;
    * what may be asked for: any permission the server knows, EXCEPT My practice's (the practice and its fee billing) and
      the ones that change what other people may do; a person who already holds it is told so; one request per person per
      permission waits at a time, and a decided one does not block the next;
    * who may decide: a Partner by ROLE (the approve permission can be ticked for somebody else) and never the asker;
    * what an approval does: calls `user_permission_service.set_permissions` with exactly that pair set to allowed and the
      approving Partner as the person who granted it, writes the audit entry the Team screen's save writes, and tells the
      asker; a person who left or was suspended since is not changed and the request stays pending;
    * a rejection tells the asker, with the reason; the Partners are told when a request is made; a notification that
      cannot be written undoes nothing;
    * the asker reads their own requests and nobody else's.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import main
import repositories.approval_repository as arepo
import services.access_request_service as access
import services.approval_service as svc
from core.auth import get_current_user
from core.permissions import PERMISSIONS, PRIVILEGE_CHANGING
from routers.approvals import router as approvals_router

FIRM = "F1"


def _member(uid, role, **kw):
    return {"id": uid, "firm_id": kw.pop("firm_id", FIRM), "role": role, "full_name": kw.pop("full_name", uid.upper()),
            "email": f"{uid}@f.in", "auth_user_id": kw.pop("auth_user_id", f"auth-{uid}"), "is_active": True, **kw}


class _Users:
    def __init__(self, rows):
        self.rows = {r["id"]: r for r in rows}

    def find_by_id(self, id, *, firm_id):
        row = self.rows.get(id)
        return row if row and row["firm_id"] == firm_id else None

    def find_all(self, firm_id=None, **_):
        return [r for r in self.rows.values() if r["firm_id"] == firm_id]


class _Notes:
    def __init__(self):
        self.rows, self.fail = [], False

    def create(self, data):
        if self.fail:
            raise RuntimeError("the notifications table is away")
        self.rows.append(data)
        return data


@pytest.fixture
def world(monkeypatch):
    arepo._MOCK_REQUESTS.clear()
    audit, saved, notes = [], [], _Notes()
    for mod in (svc, access):
        monkeypatch.setattr(mod, "log_event", lambda *a, **k: audit.append({"a": a, "k": k}))
    users = _Users([
        _member("p1", "Partner"), _member("p2", "Partner"), _member("m1", "Manager"), _member("e1", "Executive"),
        _member("r1", "Reviewer"), _member("far", "Executive", firm_id="F2"),
    ])
    monkeypatch.setattr(access, "user_repo", users)
    import repositories.notifications_repository as nrepo
    monkeypatch.setattr(nrepo, "notifications_repo", notes)

    import services.user_permission_service as ups

    def set_permissions(db, firm_id, member, changes, actor_id):
        saved.append({"firm_id": firm_id, "member": member["id"], "changes": dict(changes), "granted_by": actor_id})
        return {}
    monkeypatch.setattr(ups, "set_permissions", set_permissions)
    import core.supabase_client as sb
    monkeypatch.setattr(sb, "get_service_supabase", lambda: object())
    yield {"users": users, "audit": audit, "saved": saved, "notes": notes}
    arepo._MOCK_REQUESTS.clear()


def _who(world, uid, **over):
    row = world["users"].rows[uid]
    return {k: row[k] for k in ("id", "role", "email", "auth_user_id", "full_name")} | {"firm_id": FIRM, **over}


def _ask(world, uid, resource="payroll", action="read", **extra):
    return svc.create_request(FIRM, access.REQUEST_TYPE, {"resource": resource, "action": action, **extra}, _who(world, uid))


# ── asking ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("uid", ["m1", "e1", "r1"])
def test_every_member_of_staff_who_is_not_a_partner_can_ask(world, uid):
    # Something each of them lacks by role: a Manager the approval of a migration, a Reviewer the books, an Executive payroll.
    resource, action = {"m1": ("tally_migration", "approve"), "r1": ("accounting", "read"), "e1": ("payroll", "read")}[uid]
    row = _ask(world, uid, resource, action)
    assert row["status"] == "pending" and row["request_type"] == "access_request"
    assert row["payload"]["user_id"] == uid and row["payload"]["resource"] == resource
    assert row["requested_by"] == uid


def test_the_stored_request_is_the_servers_facts_and_the_askers_words_are_kept_as_one_bounded_line(world):
    row = _ask(world, "e1", asked_from="  Payroll\n\n people  ", note="x" * 900, user_id="p1", user_name="Somebody Else")
    p = row["payload"]
    assert (p["user_id"], p["user_name"], p["user_email"], p["user_role"]) == ("e1", "E1", "e1@f.in", "Executive")
    assert p["asked_from"] == "Payroll people" and len(p["note"]) == access.NOTE_MAX
    assert "E1 (e1@f.in) asks for access: payroll read (asked from Payroll people)" == row["summary"]


def test_a_partner_is_told_to_use_the_team_screen_and_raises_nothing(world):
    with pytest.raises(HTTPException) as exc:
        _ask(world, "p1", "payroll", "read")
    assert exc.value.status_code == 409 and "Team, under Permissions" in exc.value.detail
    assert arepo._MOCK_REQUESTS == []


@pytest.mark.parametrize("resource,action", [("practice", "read"), ("practice", "write"), ("billing", "read"), ("billing", "write")])
def test_my_practice_cannot_be_asked_for(world, resource, action):
    with pytest.raises(HTTPException) as exc:
        _ask(world, "m1", resource, action)
    assert exc.value.status_code == 403 and "Partners only" in exc.value.detail
    assert arepo._MOCK_REQUESTS == []


def test_a_permission_that_changes_what_others_may_do_is_not_given_through_a_request(world):
    assert PRIVILEGE_CHANGING, "the list of privilege-changing permissions is empty: this test would hold nothing"
    for resource, action in sorted(PRIVILEGE_CHANGING):
        with pytest.raises(HTTPException) as exc:
            _ask(world, "e1", resource, action)
        assert exc.value.status_code == 403, f"{resource}:{action} was accepted"
        assert access.requestable(resource, action) is False
    assert arepo._MOCK_REQUESTS == []


def test_every_other_permission_the_server_knows_may_be_asked_for_and_an_unknown_one_may_not(world):
    asked = 0
    for resource, actions in PERMISSIONS.items():
        for action in actions:
            expected = resource not in ("practice", "billing") and (resource, action) not in PRIVILEGE_CHANGING
            assert access.requestable(resource, action) is expected, f"{resource}:{action}"
            asked += expected
    assert asked > 100
    for bad in [("payroll", "fly"), ("nothing", "read"), (None, "read"), ("payroll", None)]:
        with pytest.raises(HTTPException) as exc:
            svc.create_request(FIRM, access.REQUEST_TYPE, {"resource": bad[0], "action": bad[1]}, _who(world, "e1"))
        assert exc.value.status_code == 422


def test_somebody_who_already_holds_it_is_told_so(world):
    with pytest.raises(HTTPException) as exc:
        _ask(world, "e1", "client", "read")          # an Executive's own by role
    assert exc.value.status_code == 409 and "already have this access" in exc.value.detail
    # And by a tick a Partner already gave: the person's own overrides ride on the signed-in user.
    ticked = _who(world, "e1", permission_overrides={"payroll:read": True})
    with pytest.raises(HTTPException) as exc:
        svc.create_request(FIRM, access.REQUEST_TYPE, {"resource": "payroll", "action": "read"}, ticked)
    assert exc.value.status_code == 409


def test_one_request_per_person_per_permission_waits_at_a_time(world):
    first = _ask(world, "e1")
    with pytest.raises(HTTPException) as exc:
        _ask(world, "e1")
    assert exc.value.status_code == 409 and "already asked" in exc.value.detail
    _ask(world, "e1", "risk", "read")                 # another permission is another request
    _ask(world, "r1")                                 # and another person's is theirs
    svc.reject(FIRM, first["id"], _who(world, "p1"), "not this month")
    assert _ask(world, "e1")["status"] == "pending"   # a decided request does not block the next


def test_somebody_who_is_not_a_member_of_the_firms_staff_cannot_ask(world):
    outsider = {"id": "far", "role": "Executive", "email": "far@f.in", "auth_user_id": "auth-far", "firm_id": FIRM}
    with pytest.raises(HTTPException) as exc:
        svc.create_request(FIRM, access.REQUEST_TYPE, {"resource": "payroll", "action": "read"}, outsider)
    assert exc.value.status_code == 403
    client = _who(world, "e1", role="Client")
    with pytest.raises(HTTPException) as exc:
        svc.create_request(FIRM, access.REQUEST_TYPE, {"resource": "payroll", "action": "read"}, client)
    assert exc.value.status_code == 403


def test_the_partners_are_told_and_a_notice_that_cannot_be_written_does_not_lose_the_request(world):
    row = _ask(world, "e1")
    told = {n["user_id"] for n in world["notes"].rows}
    assert told == {"p1", "p2"}, "the firm's Partners were not all told, or somebody else was"
    assert all(n["metadata"]["approval_request_id"] == row["id"] for n in world["notes"].rows)
    world["notes"].fail = True
    assert _ask(world, "r1")["status"] == "pending"


# ── deciding ─────────────────────────────────────────────────────────────────

def test_an_approval_writes_exactly_that_permission_as_the_approving_partner(world):
    row = _ask(world, "e1", note="covering payroll for March")
    world["notes"].rows.clear()
    out = svc.approve(FIRM, row["id"], _who(world, "p2"))
    assert out["status"] == "approved" and out["result"] == {"user_id": "e1", "granted": "payroll:read"}
    assert world["saved"] == [{"firm_id": FIRM, "member": "e1", "changes": {"payroll:read": True}, "granted_by": "p2"}]
    # The audit entry the Team screen's save writes, with the Partner's AUTH id as the actor, and the request's own.
    perms = [e for e in world["audit"] if e["a"][1] == "user_permissions"]
    assert len(perms) == 1 and perms[0]["a"][2:4] == ("e1", "update")
    assert perms[0]["k"]["actor_id"] == "auth-p2"
    assert perms[0]["k"]["new_data"] == {"changes": {"payroll:read": True}, "by_access_request": row["id"]}
    assert any(e["a"][1] == "approval_request" and e["a"][3] == "approved" for e in world["audit"])
    # And the asker is told.
    assert [(n["user_id"], n["title"]) for n in world["notes"].rows] == [("e1", "Your request for access was approved")]


def test_only_a_partner_decides_and_never_the_asker(world):
    row = _ask(world, "m1", "tally_migration", "approve")
    # The approve permission can be ticked for a Manager; the role is what is asked.
    for not_a_partner in ("m1", "e1"):
        with pytest.raises(HTTPException) as exc:
            svc.approve(FIRM, row["id"], _who(world, not_a_partner))
        assert exc.value.status_code == 403
    assert arepo._MOCK_REQUESTS[0]["status"] == "pending" and world["saved"] == []
    # A request somehow recorded as a Partner's own is not theirs to approve.
    arepo._MOCK_REQUESTS[0]["requested_by"] = "p1"
    with pytest.raises(HTTPException) as exc:
        svc.approve(FIRM, row["id"], _who(world, "p1"))
    assert exc.value.status_code == 403 and "your own access" in exc.value.detail
    assert world["saved"] == []


def test_a_person_who_left_or_was_suspended_since_is_not_changed_and_the_request_stays_pending(world):
    row = _ask(world, "e1")
    world["users"].rows["e1"]["is_active"] = False
    with pytest.raises(HTTPException) as exc:
        svc.approve(FIRM, row["id"], _who(world, "p1"))
    assert exc.value.status_code == 409 and "suspended" in exc.value.detail
    assert world["saved"] == [] and arepo._MOCK_REQUESTS[0]["status"] == "pending"
    del world["users"].rows["e1"]
    with pytest.raises(HTTPException) as exc:
        svc.approve(FIRM, row["id"], _who(world, "p1"))
    assert exc.value.status_code == 409 and "no longer a member" in exc.value.detail
    assert world["saved"] == []


def test_a_rejection_tells_the_asker_with_the_reason_and_writes_nothing(world):
    row = _ask(world, "e1")
    world["notes"].rows.clear()
    out = svc.reject(FIRM, row["id"], _who(world, "p1"), "payroll is the Manager's this year")
    assert out["status"] == "rejected" and world["saved"] == []
    assert len(world["notes"].rows) == 1
    note = world["notes"].rows[0]
    assert note["user_id"] == "e1" and note["title"] == "Your request for access was declined"
    assert "payroll is the Manager's this year" in note["body"]
    # A notice that cannot be written does not undo the decision.
    other = _ask(world, "r1")
    world["notes"].fail = True
    assert svc.reject(FIRM, other["id"], _who(world, "p1"), None)["status"] == "rejected"


def test_the_handler_names_no_table_of_its_own_and_calls_the_team_screens_function():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(access))
    tables = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table"]
    assert tables == [], "the access-request service writes or reads a table itself"
    execute = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
    called = {c.func.id for c in ast.walk(execute) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "set_permissions" in called


# ── the asker's own view, and the doors ──────────────────────────────────────

def test_the_asker_reads_their_own_requests_and_nobody_elses(world):
    mine = _ask(world, "e1")
    _ask(world, "r1")
    svc.reject(FIRM, mine["id"], _who(world, "p1"), "not now")
    again = _ask(world, "e1")
    rows = access.mine(FIRM, _who(world, "e1"))
    assert [r["id"] for r in rows] == [again["id"], mine["id"]]
    assert rows[0]["status"] == "pending" and rows[0]["reason"] is None
    assert rows[1]["status"] == "rejected" and rows[1]["reason"] == "not now"
    assert set(rows[0]) == {"id", "resource", "action", "status", "asked_at", "decided_at", "reason"}, "the asker is told more than their own request"
    assert access.mine(FIRM, _who(world, "m1")) == []


def _client(user):
    app = FastAPI()
    app.include_router(approvals_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_a_reviewer_reaches_the_door_of_this_request_and_not_the_general_one(world):
    reviewer = _who(world, "r1")
    made = _client(reviewer).post("/api/approvals/access-requests", json={"resource": "accounting", "action": "read", "asked_from": "Accounting"})
    assert made.status_code == 200, made.text
    assert made.json()["data"]["status"] == "pending" and set(made.json()["data"]) == {"id", "status", "asked_at"}
    listed = _client(reviewer).get("/api/approvals/access-requests/mine")
    assert listed.status_code == 200 and [r["resource"] for r in listed.json()["data"]["requests"]] == ["accounting"]
    # The inbox and the general door stay closed to them.
    assert _client(reviewer).get("/api/approvals").status_code == 403
    assert _client(reviewer).post("/api/approvals", json={"request_type": "access_request", "payload": {"resource": "gst", "action": "compute"}}).status_code == 403


def test_no_request_by_id_route_can_answer_for_the_two_doors_and_they_ask_every_member_of_staffs_pair():
    """The two doors were declared ahead of `GET /api/approvals/{request_id}` so that it could not answer for their addresses. That read was
    deleted on 21-11-2026 (POST-A-547: no screen opened it), so the rule is restated as what it protects: any route under the prefix whose
    address is one parameter, of the same verb as a door, is mounted after that door."""
    paths = [(sorted(getattr(r, "methods", []) or []), getattr(r, "path", "")) for r in main.app.routes]
    post = paths.index((["POST"], "/api/approvals/access-requests"))
    mine = paths.index((["GET"], "/api/approvals/access-requests/mine"))
    for at, (methods, path) in enumerate(paths):
        if path == "/api/approvals/{request_id}":
            if "POST" in methods:
                assert post < at, "a POST request-by-id route would answer for the access-request door"
        if path.startswith("/api/approvals/{request_id}/") and path.count("/") == 4 and "GET" in methods:
            assert mine < at, "a GET route of two segments under a request id would answer for the asker's own list"
    assert (["GET"], "/api/approvals/{request_id}") not in paths, "the read of one request is back: give it a screen or delete it"

    def pairs(path, method):
        route = next(r for r in main.app.routes if getattr(r, "path", "") == path and method in (getattr(r, "methods", set()) or set()))
        return {d.call.__name__ for d in route.dependant.dependencies if getattr(d.call, "__name__", "").startswith("rbac_")}
    assert pairs("/api/approvals/access-requests", "POST") == {"rbac_identity_write"}
    assert pairs("/api/approvals/access-requests/mine", "GET") == {"rbac_identity_read"}
