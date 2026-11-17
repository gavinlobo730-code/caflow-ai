"""A person named on a client's work can open that client, and a notice about a client goes only to someone who can (POST-A-451).

WHAT WAS WRONG
    The doors that name a person (an obligation's preparer, reviewer and approver, a task's assignee, a recurring task's assignee, a fee
    engagement's people, a notification's recipient) asked only whether the person was a member of the firm. A Manager could give a
    client's GSTR-3B to an Executive who is not assigned to that client; the nightly run then mailed the Executive the client's name and
    the obligation's period, and put a notification on their list with no client on it, so the list's own client rule kept it. The
    Executive could not open the client to do the work. The task-escalation engine (switched off until a firm writes a rule) handed an
    overdue task to "the first Manager" and told "the first Manager" about it, whoever they were assigned to. And the unread count on
    Notifications counted the notifications the list beside it hid.

WHAT IS ASSERTED
    * The rule (`core.authz.member_reaches_client`): a Partner reaches every client, anyone else the clients assigned to them.
    * The door (`named_row_ownership.member_reaches_client`): 422 in one sentence that says what to do, after the 404 a stranger gets, and
      nothing asked when no person, no client or no database is named.
    * Each door that names a person on a client's row asks it, found from the routers' source by RULE: a route that asks whether a person
      is a member of the firm and handles a `client_id` also asks whether the person can open the client.
    * The obligation, the task (create, reassign, and moving a task to a client its assignee cannot open), the recurring task, the
      engagement and the notification each refuse the unassigned person and store nothing, and accept the assigned one and a Partner.
    * The nightly reminders go to the people who can open the client, carry the client, and the audit row names who was not told.
    * The escalation engine picks and tells only people who can open the task's client, and its notices carry the client.
    * The unread count counts the notifications the list shows.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.authz as authz
import routers.compliance_ops as compliance_ops_router
import routers.engagements as engagements_router
import routers.notifications as notifications_router
import routers.task_recurring as task_recurring_router
import routers.tasks as tasks_router
from core.auth import get_current_user
from services import named_row_ownership as nro
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parents[1]
FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PARTNER = {"id": "partner-1", "firm_id": FIRM, "auth_user_id": "auth-p", "role": "Partner", "email": "p@example.test"}
WORDS = getattr(nro, "NOT_ASSIGNED_TO_THE_CLIENT", "(the sentence is missing)")

#: Who is assigned to which client in this world: the Executive to A only.
ASSIGNED = {("exec-a", A)}


@pytest.fixture()
def staff(monkeypatch):
    db = FakeDB()
    db.seed("users", {"id": "partner-1", "firm_id": FIRM, "role": "Partner", "full_name": "Priya Partner"})
    db.seed("users", {"id": "exec-a", "firm_id": FIRM, "role": "Executive", "full_name": "Asha Exec"})
    db.seed("users", {"id": "manager-x", "firm_id": FIRM, "role": "Manager", "full_name": "Mohan Manager"})
    wire_e2e(monkeypatch, db, [])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(authz, "is_client_assigned", lambda uid, cid, fid: (str(uid), str(cid)) in ASSIGNED and fid == FIRM)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _client(*routers, user=PARTNER) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _refused(res):
    assert res.status_code == 422 and res.json()["detail"] == WORDS, (res.status_code, res.text)


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_partner_reaches_every_client_and_anyone_else_the_clients_assigned_to_them(staff):
    assert authz.member_reaches_client({"id": "partner-1", "role": "Partner"}, B, FIRM)
    assert authz.member_reaches_client({"id": "exec-a", "role": "Executive"}, A, FIRM)
    assert not authz.member_reaches_client({"id": "exec-a", "role": "Executive"}, B, FIRM)
    assert not authz.member_reaches_client({"id": "manager-x", "role": "Manager"}, A, FIRM), "a Manager is assigned like anyone else"
    assert authz.member_reaches_client({"id": "exec-a", "role": "Executive"}, None, FIRM), "a row with no client asks nothing"


def test_the_door_refuses_in_a_sentence_after_the_strangers_404_and_asks_nothing_when_nothing_is_named(staff):
    assert nro.member_reaches_client(staff, FIRM, "exec-a", A) is None
    assert nro.member_reaches_client(staff, FIRM, "partner-1", B) is None
    with pytest.raises(HTTPException) as e:
        nro.member_reaches_client(staff, FIRM, "exec-a", B)
    assert (e.value.status_code, e.value.detail) == (422, WORDS)
    with pytest.raises(HTTPException) as stranger:
        nro.member_reaches_client(staff, FIRM, "no-such-member", A)
    assert (stranger.value.status_code, stranger.value.detail) == (404, "That team member was not found.")
    for person, client, db in ((None, B, staff), ("", B, staff), ("exec-a", None, staff), ("exec-a", "", staff), ("exec-a", B, None)):
        assert nro.member_reaches_client(db, FIRM, person, client) is None
    assert "Partner can assign them" in WORDS and "Team, Assignments" in WORDS


# ── the rule over the routers ────────────────────────────────────────────────────────────────────────────────────────────────
def _route_functions():
    for path in sorted((API / "routers").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path.name, node


def _calls(node, name: str) -> bool:
    return any(isinstance(n, ast.Call) and (getattr(n.func, "attr", None) == name or getattr(n.func, "id", None) == name)
               for n in ast.walk(node))


#: Routes that ask whether a person is the firm's and handle a `client_id`, yet name a person who is not put on the client's work.
#: Each with its reason. Empty today, and an entry that stops matching is a failure below.
NOT_A_CLIENTS_WORK: dict = {}


def test_every_route_that_names_a_person_on_a_clients_row_asks_whether_they_can_open_it():
    asked, missing = [], []
    for module, fn in _route_functions():
        src = ast.unparse(fn)
        if not _calls(fn, "member_is_the_firms") or "client_id" not in src:
            continue
        if _calls(fn, "member_reaches_client"):
            asked.append((module, fn.name))
        elif (module, fn.name) not in NOT_A_CLIENTS_WORK:
            missing.append((module, fn.name))
    assert missing == [], f"these name a person on a client's row and do not ask whether the person can open the client: {missing}"
    assert len(asked) >= 6, f"only {asked} ask: the scan is not seeing the doors"
    seen = set(asked) | set(missing)
    assert [k for k in NOT_A_CLIENTS_WORK if k in seen and k in asked] == [], "an exempted door asks now: delete its entry"
    for door in [("compliance_ops.py", "assign_obligation"), ("engagements.py", "create_engagement"),
                 ("engagements.py", "update_engagement"), ("notifications.py", "create_notification"),
                 ("task_recurring.py", "create_recurring"), ("task_recurring.py", "update_recurring")]:
        assert door in asked, door


def test_the_task_doors_ask_the_same_rule_through_the_person_they_already_read():
    src = (API / "routers" / "tasks.py").read_text()
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert _calls(fns["create_task"], "member_reaches_client"), "create_task no longer asks whether its assignee can open the client"
    assert _calls(fns["update_task"], "_assignee_can_open_the_client"), "update_task no longer asks whether its assignee can open the client"
    assert _calls(fns["_assignee_can_open_the_client"], "member_reaches_client")


# ── each door ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_obligation_is_given_only_to_people_who_can_open_its_client(staff, monkeypatch):
    saved = []
    monkeypatch.setattr(compliance_ops_router, "_assert_obligation_scope", lambda *a, **k: {"id": "rec-1", "client_id": B})
    monkeypatch.setattr(compliance_ops_router.obligations, "assign", lambda *a, **k: saved.append(k) or {"id": "rec-1"})
    client = _client(compliance_ops_router)
    for field in ("preparer_id", "reviewer_id", "approver_id"):
        _refused(client.post("/api/compliance/obligations/rec-1/assign", json={field: "exec-a"}))
    assert saved == []
    assert client.post("/api/compliance/obligations/rec-1/assign", json={"preparer_id": "partner-1"}).status_code == 200
    monkeypatch.setattr(compliance_ops_router, "_assert_obligation_scope", lambda *a, **k: {"id": "rec-1", "client_id": A})
    assert client.post("/api/compliance/obligations/rec-1/assign", json={"preparer_id": "exec-a"}).status_code == 200
    assert len(saved) == 2


@pytest.fixture()
def task_store(monkeypatch, staff):
    rows = {"task-1": {"id": "task-1", "firm_id": FIRM, "client_id": A, "status": "todo", "assigned_to": "exec-a", "title": "File"}}
    users = {u["id"]: u for u in staff.rows("users")}
    import repositories.user_repository as ur
    monkeypatch.setattr(ur.user_repo, "find_by_id", lambda uid, firm_id=None: users.get(uid))
    monkeypatch.setattr(tasks_router.client_repo, "find_by_id", lambda cid, fid=None: {"id": cid, "firm_id": FIRM})
    monkeypatch.setattr(tasks_router.task_repo, "find_by_id", lambda tid: rows.get(tid))
    monkeypatch.setattr(tasks_router.task_repo, "create", lambda row: rows.setdefault("task-new", {"id": "task-new", **row}))
    monkeypatch.setattr(tasks_router.task_repo, "update", lambda tid, row: rows[tid].update(row) or rows[tid])
    monkeypatch.setattr(tasks_router, "log_activity", lambda *a, **k: None)
    monkeypatch.setattr(tasks_router, "log_event", lambda *a, **k: None)
    return rows


def test_a_task_is_given_only_to_someone_who_can_open_its_client(task_store):
    client = _client(tasks_router)
    _refused(client.post("/api/tasks", json={"client_id": B, "title": "Reconcile", "assigned_to": "exec-a"}))
    assert "task-new" not in task_store
    ok = client.post("/api/tasks", json={"client_id": A, "title": "Reconcile", "assigned_to": "exec-a"})
    assert ok.status_code == 200, ok.text


def test_a_task_is_not_reassigned_to_someone_who_cannot_open_it_nor_moved_away_from_its_assignee(task_store):
    client = _client(tasks_router)
    task_store["task-1"]["client_id"] = B
    task_store["task-1"]["assigned_to"] = "partner-1"
    _refused(client.patch("/api/tasks/task-1", json={"assigned_to": "exec-a"}))
    assert task_store["task-1"]["assigned_to"] == "partner-1"
    task_store["task-1"].update({"client_id": A, "assigned_to": "exec-a"})
    _refused(client.patch("/api/tasks/task-1", json={"client_id": B}))
    assert task_store["task-1"]["client_id"] == A, "the task was moved to a client its assignee cannot open"
    ok = client.patch("/api/tasks/task-1", json={"client_id": B, "assigned_to": "partner-1"})
    assert ok.status_code == 200, ok.text


def test_a_recurring_task_is_given_only_to_someone_who_can_open_its_client(staff, monkeypatch):
    monkeypatch.setattr(task_recurring_router, "_get_db", lambda: staff)
    client = _client(task_recurring_router)
    body = {"title": "Monthly close", "frequency": "monthly", "next_due_date": "2026-12-01"}
    _refused(client.post("/api/task-recurring", json={**body, "client_id": B, "assignee_id": "exec-a"}))
    assert staff.rows("task_recurring_configs") == []
    assert client.post("/api/task-recurring", json={**body, "client_id": A, "assignee_id": "exec-a"}).status_code == 200
    assert client.post("/api/task-recurring", json={**body, "assignee_id": "exec-a"}).status_code == 200, "no client asks nothing"
    staff.seed("task_recurring_configs", {"id": "cfg-1", "firm_id": FIRM, "client_id": A, "assignee_id": "exec-a", "title": "T"})
    _refused(client.put("/api/task-recurring/cfg-1", json={"client_id": B}))
    assert [r for r in staff.rows("task_recurring_configs") if r["id"] == "cfg-1"][0]["client_id"] == A


def test_an_engagements_people_can_open_its_client(staff, monkeypatch):
    calls = {"create": [], "update": []}
    monkeypatch.setattr(engagements_router.client_repo, "find_by_id", lambda *a, **k: {"id": B, "firm_id": FIRM})
    monkeypatch.setattr(engagements_router.engagement_repo, "find_by_id",
                        lambda *a, **k: {"id": "eng-1", "firm_id": FIRM, "client_id": B, "fee_paise": 1, "assigned_to": "partner-1"})
    monkeypatch.setattr(engagements_router.engagement_repo, "create", lambda row: calls["create"].append(row) or {"id": "e", **row})
    monkeypatch.setattr(engagements_router.engagement_repo, "update", lambda i, row: calls["update"].append(row) or {"id": i, **row})
    client = _client(engagements_router)
    base = {"client_id": B, "service_type": "GST", "fee_paise": 100, "billing_cycle": "monthly", "start_date": "2026-04-01"}
    for field in ("assigned_to", "reviewer_id"):
        _refused(client.post("/api/engagements", json={**base, field: "exec-a"}))
        _refused(client.patch("/api/engagements/eng-1", json={field: "exec-a"}))
    assert calls == {"create": [], "update": []}
    assert client.post("/api/engagements", json={**base, "assigned_to": "partner-1"}).status_code == 200
    assert client.patch("/api/engagements/eng-1", json={"fee_paise": 200}).status_code == 200, "a change naming nobody asks nothing"


def test_a_notification_about_a_client_is_addressed_only_to_someone_who_can_open_it(staff, monkeypatch):
    created = []
    monkeypatch.setattr(notifications_router.notifications_repo, "create", lambda row: created.append(row) or {"id": "n", **row})
    client = _client(notifications_router)
    body = {"type": "info", "title": "Hello", "body": "About a client"}
    _refused(client.post("/api/notifications", json={**body, "user_id": "exec-a", "client_id": B}))
    assert created == []
    assert client.post("/api/notifications", json={**body, "user_id": "exec-a", "client_id": A}).status_code == 200
    assert client.post("/api/notifications", json={**body, "user_id": "exec-a"}).status_code == 200, "a firm-level notice"


# ── the nightly reminders ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_nightly_reminder_goes_to_the_people_who_can_open_the_client_and_names_the_client(staff, monkeypatch):
    from services import compliance_obligation_service as cos
    import repositories.user_repository as ur
    import repositories.notifications_repository as nr
    import services.audit_service as audit
    users = {u["id"]: u for u in staff.rows("users")}
    reads = []
    monkeypatch.setattr(ur.user_repo, "find_by_id", lambda uid, firm_id=None: reads.append(uid) or users.get(uid))
    sent, audited = [], []
    monkeypatch.setattr(nr.notifications_repo, "create", lambda row, **k: sent.append(row) or row)
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: audited.append(k))
    rec = {"id": "rec-1", "client_id": B, "obligation_type": "GSTR3B", "period_label": "GSTR-3B October 2026",
           "due_date": "2026-11-20", "preparer_id": "exec-a", "reviewer_id": "partner-1", "approver_id": None}
    cache: dict = {}
    told = cos._notify_internal(FIRM, rec, "due_3", None, cache)
    assert told == {"partner-1"}
    assert [(n["user_id"], n["client_id"]) for n in sent] == [("partner-1", B)]
    assert audited[-1]["metadata"]["not_told_cannot_open_the_client"] == ["exec-a"]
    # The sweep asks about each person once per client.
    cos._notify_internal(FIRM, {**rec, "id": "rec-2"}, "due_3", None, cache)
    assert sorted(reads) == ["exec-a", "partner-1"]
    sent.clear()
    assert cos._notify_internal(FIRM, {**rec, "id": "rec-3", "client_id": A}, "due_3", None) == {"exec-a", "partner-1"}


# ── the escalation engine ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_escalation_engine_picks_and_tells_only_people_who_can_open_the_tasks_client(staff, monkeypatch):
    from services import escalation_service as es
    import repositories.user_repository as ur
    people = staff.rows("users")
    monkeypatch.setattr(ur.user_repo, "find_all", lambda firm_id=None, role=None: [u for u in people if u["role"] == role])
    monkeypatch.setattr(es, "user_repo", ur.user_repo)
    svc = es.EscalationService()
    assert svc._find_least_busy_user(FIRM, "Executive", client_id=B) is None
    assert svc._find_least_busy_user(FIRM, "Executive", client_id=A)["id"] == "exec-a"
    # No Manager is assigned to A, so the Partner is told.
    assert svc._find_manager_for_task(FIRM, {"client_id": A, "assigned_to": "exec-a"})["id"] == "partner-1"
    sent = []
    monkeypatch.setattr(es, "notifications_repo", type("R", (), {"create": staticmethod(lambda row: sent.append(row) or row)}))
    task = {"id": "t-1", "client_id": B, "title": "File"}
    assert svc._create_escalation_notification(FIRM, task, "due_soon", "Executive", 2) is None
    assert svc._create_escalation_notification(FIRM, task, "due_soon", "Partner", 2)["client_id"] == B
    src = (API / "services" / "escalation_service.py").read_text()
    assert src.count('"client_id": task.get("client_id")') == 3, "every escalation notice carries the task's client"


# ── the unread count ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_unread_count_counts_what_the_list_shows(monkeypatch):
    import repositories.notifications_repository as nr
    monkeypatch.setattr(nr, "_USE_MOCK", True)
    monkeypatch.setattr(nr, "MOCK_NOTIFICATIONS", [
        {"id": "1", "is_read": False, "client_id": None},
        {"id": "2", "is_read": False, "client_id": A},
        {"id": "3", "is_read": False, "client_id": B},
        {"id": "4", "is_read": True, "client_id": A},
    ])
    repo = nr.notifications_repo
    assert repo.count_unread() == 3
    assert repo.count_unread(client_ids={A}) == 2
    assert repo.count_unread(client_ids=set()) == 1
    seen = {}
    monkeypatch.setattr(notifications_router.notifications_repo, "count_unread", lambda **kw: seen.update(kw) or 0)
    monkeypatch.setattr(notifications_router, "effective_client_ids", lambda user: {A})
    _client(notifications_router, user={"id": "exec-a", "firm_id": FIRM, "role": "Executive"}).get("/api/notifications/count")
    assert seen["client_ids"] == {A}


# ── the unread count, on the database branch ─────────────────────────────────────────────────────────────────────────────────
class _Recorder:
    """A chainable query double that records every filter, for the branch the mock-mode test above never reaches."""

    def __init__(self):
        self.calls: list = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return call

    def execute(self):
        return type("R", (), {"count": 7, "data": []})()


def _production_count(monkeypatch, **kw):
    import repositories.notifications_repository as nr
    rec = _Recorder()
    monkeypatch.setattr(nr, "_USE_MOCK", False)
    monkeypatch.setattr(nr, "_get_db", lambda: type("D", (), {"table": staticmethod(lambda name: rec)})())
    assert nr.notifications_repo.count_unread(**kw) == 7
    return rec.calls


def test_the_unread_count_filters_by_the_readers_clients_on_the_database_too(monkeypatch):
    calls = _production_count(monkeypatch, firm_id=FIRM, user_id="exec-a", client_ids={B, A})
    assert ("or_", (f"client_id.is.null,client_id.in.({A},{B})",)) in calls, "the ids are sorted and the unassigned rows are kept"
    assert ("eq", ("firm_id", FIRM)) in calls and ("eq", ("user_id", "exec-a")) in calls
    assert ("eq", ("is_read", False)) in calls and ("eq", ("is_archived", False)) in calls
    assert ("or_", ("client_id.is.null",)) in _production_count(monkeypatch, client_ids=set()), "an empty reach counts only the rows naming no client"
    assert not [c for c in _production_count(monkeypatch, client_ids=None) if c[0] == "or_"], "no reach asks no narrowing"


# ── review of the batch: an unchanged assignee, the template door, the nightly mail, an unreadable reach ────────────────────────
def test_a_task_saved_with_the_assignee_it_already_has_is_not_refused_when_that_assignee_lost_the_client(task_store):
    client = _client(tasks_router)
    task_store["task-1"].update({"client_id": B, "assigned_to": "exec-a"})   # exec-a is assigned to A only
    ok = client.patch("/api/tasks/task-1", json={"title": "Renamed", "assigned_to": "exec-a"})
    assert ok.status_code == 200, ok.text
    assert task_store["task-1"]["title"] == "Renamed"
    task_store["task-1"]["assigned_to"] = "partner-1"
    _refused(client.patch("/api/tasks/task-1", json={"title": "Again", "assigned_to": "exec-a"}))
    assert task_store["task-1"]["title"] == "Renamed", "a NEW assignee who cannot open the client is still refused"


@pytest.fixture()
def template_door(monkeypatch, staff):
    import routers.task_templates as tt
    monkeypatch.setattr(tt.task_template_repo, "find_by_id", lambda tid, firm_id=None: {"id": tid, "firm_id": FIRM, "name": "Monthly close"})
    monkeypatch.setattr(tt, "assert_client_access", lambda *a, **k: None)
    return tt


def test_a_task_made_from_a_template_is_given_only_to_someone_who_can_open_its_client(staff, template_door):
    client = _client(template_door)
    url = "/api/task-templates/tpl-1/instantiate"
    _refused(client.post(url, json={"client_id": B, "assignee_id": "exec-a"}))
    assert staff.rows("tasks") == [], "nothing was stored"
    stranger = client.post(url, json={"client_id": A, "assignee_id": "not-a-member"})
    assert stranger.status_code == 404, stranger.text
    assert client.post(url, json={"client_id": A, "assignee_id": "exec-a"}).status_code == 200
    assert client.post(url, json={"client_id": B, "assignee_id": "partner-1"}).status_code == 200
    assert client.post(url, json={"client_id": B}).status_code == 200, "no assignee asks nothing"
    assert [t["assignee_id"] for t in staff.rows("tasks")] == ["exec-a", "partner-1", None]


def test_the_overdue_task_mail_is_not_sent_for_a_client_the_assignee_cannot_open(staff, monkeypatch):
    from datetime import date
    import services.practice_mail_service as mail
    users = {u["id"]: {**u, "email": f"{u['id']}@example.test"} for u in staff.rows("users")}
    monkeypatch.setattr(mail, "_staff_member", lambda firm_id, uid: users.get(uid))
    monkeypatch.setattr(mail, "_recently_mailed", lambda *a, **k: {})
    asked = []
    monkeypatch.setattr(mail, "client_names", lambda firm_id, ids: asked.append(sorted(str(i) for i in ids if i)) or {})
    delivered = []
    monkeypatch.setattr(mail, "deliver", lambda firm_id, event, person, refs, send, day=None: delivered.append((person["id"], [r.ref_id for r in refs])) or "sent")
    task = {"firm_id": FIRM, "title": "File", "due_date": "2026-10-01", "status": "todo"}
    tasks = [{**task, "id": "t-a", "client_id": A, "assigned_to": "exec-a"},
             {**task, "id": "t-b", "client_id": B, "assigned_to": "exec-a"},
             {**task, "id": "t-c", "client_id": B, "assigned_to": "partner-1"}]
    out = mail.send_overdue_task_mails(FIRM, tasks, today=date(2026, 10, 14))
    assert sorted(delivered) == [("exec-a", ["t-a"]), ("partner-1", ["t-c"])], "exec-a is mailed about A and not about B"
    assert out == {"sent": 2}
    assert asked == [[A, B]], "the client's name is read only for the tasks that will be mailed"
    delivered.clear()
    assert mail.send_overdue_task_mails(FIRM, [tasks[1]], today=date(2026, 10, 14)) == {} and delivered == []


def test_an_unreadable_reach_tells_nobody_and_does_not_stop_the_sweep(staff, monkeypatch):
    from services import compliance_obligation_service as cos
    import repositories.notifications_repository as nr
    import services.audit_service as audit

    def unreadable(*a, **k):
        raise RuntimeError("assignments table unreachable")

    monkeypatch.setattr(cos, "_people_who_can_open", unreadable)
    sent, audited = [], []
    monkeypatch.setattr(nr.notifications_repo, "create", lambda row, **k: sent.append(row) or row)
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: audited.append(k))
    rec = {"id": "rec-1", "client_id": A, "obligation_type": "GSTR3B", "period_label": "GSTR-3B October 2026",
           "due_date": "2026-11-20", "preparer_id": "exec-a", "reviewer_id": "partner-1", "approver_id": None}
    assert cos._notify_internal(FIRM, rec, "due_3", None, {}) == set(), "nobody unchecked is told"
    assert sent == []
    assert audited[-1]["metadata"]["not_told_reach_unreadable"] is True
    assert audited[-1]["metadata"]["not_told_cannot_open_the_client"] == [], "an unread reach is not 'cannot open'"


# ── the rule, over every route that writes a person next to a client ─────────────────────────────────────────────────────────
_PERSON_KEYS = {"assigned_to", "assignee_id", "preparer_id"}


def _writes_a_person(fn) -> bool:
    """Whether the function builds a row (a dict literal, a keyword or a subscript store) with one of the person keys."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value in _PERSON_KEYS for k in n.keys):
            return True
        # A keyword names a person on a row only when the call writes one; `list_tasks(assigned_to=...)` is a filter.
        if isinstance(n, ast.Call) and any(w in (getattr(n.func, "attr", None) or getattr(n.func, "id", "")).lower()
                                           for w in ("create", "insert", "update", "assign", "upsert", "set_")):
            if any(k.arg in _PERSON_KEYS for k in n.keywords):
                return True
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and isinstance(n.slice, ast.Constant) and n.slice.value in _PERSON_KEYS:
            return True
    return False


#: Routes that write a person key beside a `client_id` and name nobody who is handed the client's work. Each with its reason.
NAMES_NOBODY_ON_THE_WORK: dict = {}


def test_every_route_that_writes_an_assignee_key_next_to_a_client_asks_whether_they_can_open_it():
    asked, missing = [], []
    for module, fn in _route_functions():
        if not any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "post", "put", "patch", "delete")
                   for d in fn.decorator_list):
            continue
        if not _writes_a_person(fn) or "client_id" not in ast.unparse(fn):
            continue
        if _calls(fn, "member_reaches_client") or _calls(fn, "_assignee_can_open_the_client"):
            asked.append((module, fn.name))
        elif (module, fn.name) not in NAMES_NOBODY_ON_THE_WORK:
            missing.append((module, fn.name))
    assert missing == [], f"these write a person next to a client and never ask whether the person can open it: {missing}"
    assert ("task_templates.py", "instantiate_template") in asked and ("tasks.py", "update_task") in asked, asked
    assert len(asked) >= 5, f"only {asked}: the scan is not seeing the doors"
