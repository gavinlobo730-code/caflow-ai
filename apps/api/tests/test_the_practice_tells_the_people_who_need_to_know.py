"""practice_management-02 and -03 — the practice's own mail goes out, once, to the
right person, and a person can switch it off.

WHAT WAS WRONG
    Four notices in `services/email_service.py` had no callers; a client's portal
    message and a new document request recorded a row and told nobody; the
    escalation sweeps wrote in-app notifications only. The screen that creates a
    document request wrote the table STRAIGHT over PostgREST, because the API door
    for it named a column (`due_date`) the table never had and failed on every
    call.

WHAT IS ASSERTED, through the real routers and the real senders, with the
provider stubbed at the HTTP boundary (`httpx.post`) so the JSON that would have
reached Resend is what is read:

  02  a client's portal message creates a notification for the staff member
      assigned to that client AND mails them — without the words of the message;
      with nobody assigned it reaches the Partner; a new document request mails
      the client's ACTIVE portal contact under the PRACTICE's name with a
      Reply-To that reaches the practice, and tells the CA when nobody could be
      told; the firm-wide unread count drops to nothing once the thread is read.
  03  assigning a task mails the assignee exactly once (and not the person who
      did it); the 7/3/1-day and overdue sweeps send ONE mail per recipient, a
      re-run sends none even when the sweep's own once-a-day guard is bypassed,
      an overdue reminder repeats weekly and never daily; a person with the
      preference off receives none.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _columns_from_migration import table_columns  # noqa: E402
from _schema_checked_db import REAL_COLUMNS, SchemaCheckedDB  # noqa: E402

import routers.notifications as notifications_router  # noqa: E402
import routers.portal as portal_router  # noqa: E402
import routers.portal_data as portal_data_router  # noqa: E402
import services.compliance_obligation_service as ob  # noqa: E402
import services.email_service as es  # noqa: E402
import services.portal_access_service as portal_access  # noqa: E402
import services.portal_data_service as portal_data_service  # noqa: E402
import services.practice_mail_service as mail  # noqa: E402
from core.auth import get_current_user  # noqa: E402
from core.portal_auth import get_current_portal_client  # noqa: E402
from domain import practice_notices as rules  # noqa: E402
from domain.notification_fixtures import MOCK_NOTIFICATIONS  # noqa: E402
from mock_data import CLIENT_INDEX, MOCK_COMPLIANCE_RECORDS  # noqa: E402
from repositories.assignment_repository import _MOCK_ASSIGNMENTS  # noqa: E402
from repositories.compliance_records_repository import compliance_records_repo  # noqa: E402
from repositories.user_repository import user_repo  # noqa: E402

FIRM = "firm-mail-1"
CLIENT = "client-mail-1"
CLIENT_NAME = "Acme Traders Pvt Ltd"
PREPARER = {"id": "u-prep", "firm_id": FIRM, "full_name": "Priya Preparer",
            "email": "priya@gupta-ca.in", "role": "Executive", "is_active": True}
MANAGER = {"id": "u-mgr", "firm_id": FIRM, "full_name": "Mohan Manager",
           "email": "mohan@gupta-ca.in", "role": "Manager", "is_active": True}
PARTNER = {"id": "u-ptr", "firm_id": FIRM, "full_name": "Gita Partner",
           "email": "gita@gupta-ca.in", "role": "Partner", "is_active": True}
PEOPLE = {p["id"]: p for p in (PREPARER, MANAGER, PARTNER)}
PORTAL = {"firm_id": FIRM, "client_id": CLIENT, "contact_id": "ct-1",
          "email": "accounts@acme-traders.in", "name": "Anita Accounts",
          "status": "active", "legacy": False}
DEFAULT_FROM = "PracticeSync AI <noreply@caflow.ai>"


class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"id": "msg-1"}


@pytest.fixture
def wire(monkeypatch):
    """The JSON bodies POSTed to Resend, through the real transports."""
    sent: list[dict] = []
    monkeypatch.setattr(es, "_RESEND_API_KEY", "test-key")
    monkeypatch.setattr(es, "_FROM_EMAIL", DEFAULT_FROM)
    import httpx
    monkeypatch.setattr(
        httpx, "post",
        lambda url, headers=None, json=None, timeout=None: sent.append(json) or _Resp())
    return sent


@pytest.fixture
def world(monkeypatch):
    """A firm with a preparer assigned to one client, a manager and a partner,
    in the mock stores — so the real lookups (assignment, user, client name,
    portal contact) are the ones under test, not a stub standing in for them."""
    mail.reset_mock_stores()
    portal_access.reset_mock_stores()
    MOCK_COMPLIANCE_RECORDS.clear()
    _MOCK_ASSIGNMENTS[:] = [a for a in _MOCK_ASSIGNMENTS if a.get("firm_id") != FIRM]
    before = len(MOCK_NOTIFICATIONS)
    monkeypatch.setitem(CLIENT_INDEX, CLIENT, {"id": CLIENT, "firm_id": FIRM,
                                               "client_name": CLIENT_NAME})
    monkeypatch.setattr(user_repo, "find_by_id",
                        lambda uid, *, firm_id: PEOPLE.get(str(uid)))
    monkeypatch.setattr(user_repo, "find_all",
                        lambda firm_id=None, role=None, **k: [
                            p for p in PEOPLE.values()
                            if (role is None or p["role"] == role)])
    _MOCK_ASSIGNMENTS.append({"id": "a1", "firm_id": FIRM, "user_id": PREPARER["id"],
                              "client_id": CLIENT})
    portal_access.MOCK_PORTAL_CONTACTS.append({
        "id": "ct-1", "firm_id": FIRM, "client_id": CLIENT, "status": "active",
        "email": PORTAL["email"], "name": PORTAL["name"]})
    monkeypatch.setattr("services.timeline_service.timeline_service.log",
                        lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None)
    yield
    del MOCK_NOTIFICATIONS[before:]
    _MOCK_ASSIGNMENTS[:] = [a for a in _MOCK_ASSIGNMENTS if a.get("firm_id") != FIRM]
    MOCK_COMPLIANCE_RECORDS.clear()
    mail.reset_mock_stores()
    portal_access.reset_mock_stores()


def _mine(type_=None):
    return [n for n in MOCK_NOTIFICATIONS
            if n.get("firm_id") == FIRM and (type_ is None or n["type"] == type_)]


def _recipients(wire) -> list[str]:
    return [to for body in wire for to in body["to"]]


def _staff_client(user: dict, *routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _portal_client() -> TestClient:
    app = FastAPI()
    app.include_router(portal_data_router.router)
    app.dependency_overrides[get_current_portal_client] = lambda: PORTAL
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# 02 — a client's message reaches the staff who look after them
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def portal_db(monkeypatch):
    """`portal_messages` as the real schema has it, so a column nobody created
    fails here the way it fails in production."""
    db = SchemaCheckedDB({"portal_messages": []})
    monkeypatch.setattr(portal_data_service, "_db", lambda: db)
    return db


def test_a_client_message_notifies_the_assigned_user_in_the_app_and_by_mail(
        world, wire, portal_db):
    res = _portal_client().post("/api/portal/self/messages",
                                json={"body": "Please send the draft balance sheet"})
    assert res.status_code == 200, res.text

    notes = _mine("portal_message")
    assert [n["user_id"] for n in notes] == [PREPARER["id"]], (
        "the notification must be addressed to the staff member ASSIGNED to the client")
    assert notes[0]["client_id"] == CLIENT
    assert CLIENT_NAME in notes[0]["title"]
    assert notes[0]["action_url"] == f"/client-portal?client={CLIENT}&tab=messages"

    assert _recipients(wire) == [PREPARER["email"]]
    body = wire[0]
    assert body["from"] == DEFAULT_FROM and "reply_to" not in body, (
        "a mail to STAFF goes from the product's own sender, as every internal notice does")
    assert CLIENT_NAME in body["subject"]
    assert "draft balance sheet" not in body["html"], (
        "the words of a client's message are not mailed — mail is not a secure channel")


def test_with_nobody_assigned_the_partner_is_told_rather_than_nobody(world, wire, portal_db):
    _MOCK_ASSIGNMENTS[:] = [a for a in _MOCK_ASSIGNMENTS if a.get("firm_id") != FIRM]
    assert _portal_client().post("/api/portal/self/messages",
                                 json={"body": "Hello"}).status_code == 200
    assert [n["user_id"] for n in _mine("portal_message")] == [PARTNER["id"]]
    assert _recipients(wire) == [PARTNER["email"]]


def test_five_messages_in_a_row_are_one_mail_per_recipient_per_day(world, wire, portal_db):
    c = _portal_client()
    for i in range(5):
        assert c.post("/api/portal/self/messages", json={"body": f"m{i}"}).status_code == 200
    assert len(_recipients(wire)) == 1, "mail is limited to once per client per recipient per day"
    assert len(_mine("portal_message")) == 5, "the in-app notification is per message"


def test_a_failing_notice_never_fails_the_clients_message(world, wire, portal_db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("notifications table is down")
    monkeypatch.setattr("repositories.notifications_repository.notifications_repo.create", boom)
    monkeypatch.setattr(es, "_RESEND_API_KEY", "")
    res = _portal_client().post("/api/portal/self/messages", json={"body": "Hello"})
    assert res.status_code == 200
    assert len(portal_db.rows["portal_messages"]) == 1, "the message is saved regardless"


def test_a_staff_member_with_the_preference_off_is_notified_but_not_mailed(world, wire, portal_db):
    mail.set_preference(FIRM, PREPARER["id"], "portal_message", False)
    assert _portal_client().post("/api/portal/self/messages",
                                 json={"body": "Hello"}).status_code == 200
    assert len(_mine("portal_message")) == 1, "the in-app notification is not a mail preference"
    assert wire == []


# ── a new document request tells the client ──────────────────────────────────

@pytest.fixture
def requests_db(monkeypatch):
    cols = {**REAL_COLUMNS,
            "document_requests": REAL_COLUMNS["document_requests"]
            | table_columns("450_a_practices_own_mail_is_recorded_and_a_person_chooses_which_they_get.sql",
                            "document_requests")}
    db = SchemaCheckedDB({"document_requests": []})
    db.columns = cols
    monkeypatch.setattr(portal_router, "_USE_MOCK", False)
    monkeypatch.setattr(portal_router, "_db", lambda: db)
    return db


def test_a_new_document_request_mails_the_active_portal_contact_as_the_practice(
        world, wire, requests_db, monkeypatch):
    monkeypatch.setattr(mail, "practice_sender", lambda firm_id: ("Gupta & Associates", "partner@gupta-ca.in"))
    res = _staff_client(PARTNER, portal_router).post("/api/portal/document-requests", json={
        "client_id": CLIENT, "title": "April bank statement", "is_urgent": True,
        "due_date": "2026-10-20"})
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["client_notice"] == {"contacts": 1, "emailed": 1, "reason": None}

    assert len(requests_db.rows["document_requests"]) == 1, (
        "the API door writes the row now — it failed on every call before, "
        "naming a column the table did not have")
    assert requests_db.rows["document_requests"][0]["requested_by"] == PARTNER["id"]

    assert _recipients(wire) == [PORTAL["email"]]
    body = wire[0]
    assert body["from"] == "Gupta & Associates <noreply@caflow.ai>", (
        "the practice writing to ITS OWN client goes out under the practice's name")
    assert body["reply_to"] == "partner@gupta-ca.in"
    assert "April bank statement" in body["subject"] and body["subject"].startswith("Urgent:")
    assert "20 Oct 2026" in body["html"]
    assert "upload" not in body["html"].lower(), (
        "the portal's document upload is not built; the mail must not offer one")


def test_a_document_request_for_a_client_with_no_active_contact_says_nobody_was_told(
        world, wire, requests_db):
    portal_access.MOCK_PORTAL_CONTACTS[:] = [
        {"id": "ct-9", "firm_id": FIRM, "client_id": CLIENT, "status": "invited",
         "email": "pending@acme-traders.in", "name": "Not yet"}]
    res = _staff_client(PARTNER, portal_router).post("/api/portal/document-requests", json={
        "client_id": CLIENT, "title": "GST registration certificate"})
    assert res.status_code == 200
    notice = res.json()["data"]["client_notice"]
    assert notice["emailed"] == 0 and notice["contacts"] == 0
    assert "no active portal contact" in notice["reason"]
    assert wire == [], "an invited contact has no account to sign in to, so nobody is mailed"
    assert len(requests_db.rows["document_requests"]) == 1, "the request is still saved"


def test_a_message_from_the_practice_mails_the_client_contact_once_a_day(
        world, wire, monkeypatch):
    monkeypatch.setattr(mail, "practice_sender", lambda firm_id: ("Gupta & Associates", "partner@gupta-ca.in"))
    c = _staff_client(PARTNER, portal_router)
    for text in ("one", "two", "three"):
        assert c.post("/api/portal/messages", json={
            "client_id": CLIENT, "text": text, "from_ca": True}).status_code == 200
    assert _recipients(wire) == [PORTAL["email"]], "one mail per contact per day, not one per message"
    assert wire[0]["from"] == "Gupta & Associates <noreply@caflow.ai>"
    assert "one" not in wire[0]["html"].replace("one mail", ""), "the words stay on the portal"


# ── the firm-wide unread count ───────────────────────────────────────────────

def test_the_unread_count_is_firm_wide_and_drops_to_nothing_once_the_thread_is_read(
        world, wire, portal_db, monkeypatch):
    monkeypatch.setattr(portal_data_service, "_db", lambda: portal_db)
    import domain.portal_service as svc
    svc.reset_mock_stores()
    for i in range(3):
        svc._MOCK_MESSAGES.append({"id": f"m{i}", "firm_id": FIRM, "client_id": CLIENT,
                                   "text": "hi", "from_ca": False,
                                   "created_at": f"2026-10-0{i + 1}T10:00:00Z"})
    svc._MOCK_MESSAGES.append({"id": "mca", "firm_id": FIRM, "client_id": CLIENT,
                               "text": "reply", "from_ca": True, "created_at": "2026-10-04T10:00:00Z"})
    c = _staff_client(PARTNER, portal_router)

    first = c.get("/api/portal/unread").json()["data"]
    assert first["unread_total"] == 3, "only what the CLIENT sent counts"
    assert first["clients"][0]["client_id"] == CLIENT and first["clients"][0]["unread"] == 3
    assert first["clients"][0]["client_name"] == CLIENT_NAME

    assert c.post("/api/portal/messages/read", json={"client_id": CLIENT}).json()["data"] == {
        "marked_read": 3}
    assert c.get("/api/portal/unread").json()["data"]["unread_total"] == 0
    svc.reset_mock_stores()


def test_an_unread_count_never_names_a_client_outside_the_callers_book(world):
    import domain.portal_service as svc
    import services.portal_notice_service as notice
    svc.reset_mock_stores()
    svc._MOCK_MESSAGES.append({"id": "x", "firm_id": FIRM, "client_id": "someone-elses",
                               "text": "hi", "from_ca": False, "created_at": "2026-10-01T00:00:00Z"})
    assert notice.unread_summary(FIRM, {CLIENT})["unread_total"] == 0
    assert notice.unread_summary(FIRM, set())["unread_total"] == 0, (
        "an EMPTY set means nothing, never 'no filter'")
    assert notice.unread_summary(FIRM, None)["unread_total"] == 1
    svc.reset_mock_stores()


# ══════════════════════════════════════════════════════════════════════════════
# 03 — a task assigned to somebody
# ══════════════════════════════════════════════════════════════════════════════

TASK = {"id": "t-1", "firm_id": FIRM, "client_id": CLIENT, "title": "Prepare GSTR-3B",
        "due_date": "2026-10-20", "status": "todo"}


def test_assigning_a_task_mails_the_assignee_exactly_once(world, wire):
    import services.notification_service as ns
    ns.notification_service.notify_task_assigned(TASK, PREPARER, MANAGER)
    assert _recipients(wire) == [PREPARER["email"]]
    assert wire[0]["from"] == DEFAULT_FROM and "reply_to" not in wire[0]
    assert "Prepare GSTR-3B" in wire[0]["subject"]
    assert CLIENT_NAME in wire[0]["html"] and "20 Oct 2026" in wire[0]["html"]
    assert [n["user_id"] for n in _mine("task_assigned")] == [PREPARER["id"]]


def test_nobody_is_mailed_to_say_they_assigned_a_task_to_themselves(world, wire):
    import services.notification_service as ns
    ns.notification_service.notify_task_assigned(TASK, MANAGER, MANAGER)
    assert wire == []


def test_a_reassignment_mails_the_new_assignee_and_not_the_old_one(world, wire):
    import services.notification_service as ns
    ns.notification_service.notify_task_reassigned(
        TASK, MANAGER, PREPARER, "Task load rebalancing", reassigned_by=PARTNER)
    assert _recipients(wire) == [PREPARER["email"]]


def test_the_patch_door_mails_the_new_assignee_once(world, wire, monkeypatch):
    import routers.tasks as tr
    monkeypatch.setattr(tr.task_repo, "find_by_id", lambda tid, firm_id=None, **k: {**TASK, "assigned_to": None})
    monkeypatch.setattr(tr.task_repo, "update", lambda tid, upd: {**TASK, **upd})
    monkeypatch.setattr(tr, "assert_client_access", lambda u, c: None)
    res = _staff_client(PARTNER, tr).patch("/api/tasks/t-1", json={"assigned_to": PREPARER["id"]})
    assert res.status_code == 200, res.text
    assert _recipients(wire) == [PREPARER["email"]]


def test_the_create_door_mails_the_assignee_once(world, wire, monkeypatch):
    import routers.tasks as tr
    monkeypatch.setattr(tr, "assert_client_access", lambda u, c: None)
    monkeypatch.setattr(tr.client_repo, "find_by_id", lambda cid, fid=None: {"id": cid})
    monkeypatch.setattr(tr.task_repo, "create", lambda d: {**d, "id": "t-new"})
    res = _staff_client(PARTNER, tr).post("/api/tasks", json={
        "client_id": CLIENT, "title": "Reconcile bank", "assigned_to": PREPARER["id"]})
    assert res.status_code == 200, res.text
    assert _recipients(wire) == [PREPARER["email"]]


def test_a_person_with_the_preference_off_is_not_mailed_about_an_assignment(world, wire):
    import services.notification_service as ns
    mail.set_preference(FIRM, PREPARER["id"], "task_assigned", False)
    ns.notification_service.notify_task_assigned(TASK, PREPARER, MANAGER)
    assert wire == []
    assert len(_mine("task_assigned")) == 1, "the in-app notification is not a mail preference"


# ── the compliance sweep ─────────────────────────────────────────────────────

def _obligation(period, due, preparer=PREPARER["id"], **extra):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "GST",
        "obligation_type": "GSTR3B", "period_label": period, "due_date": due,
        "status": "Not Started", "preparer_id": preparer, **extra})


def test_the_sweep_sends_one_mail_per_recipient_listing_every_obligation(world, wire):
    _obligation("GSTR-3B September 2026", "2026-10-20")
    _obligation("GSTR-1 September 2026", "2026-10-20")
    result = ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert result == {"escalated": 2, "due_7": 2, "due_3": 0, "due_1": 0, "overdue": 0}, (
        "the answer's shape is pinned by other tests and by the scheduler's run log")
    assert _recipients(wire) == [PREPARER["email"]], "one mail, not one per obligation"
    html = wire[0]["html"]
    assert "GSTR-3B September 2026" in html and "GSTR-1 September 2026" in html
    assert "20 Oct 2026" in html and CLIENT_NAME in html
    assert wire[0]["subject"].startswith("2 compliance deadlines")


def test_a_single_obligation_reads_as_the_single_obligation_notice(world, wire):
    _obligation("GSTR-3B September 2026", "2026-10-20")
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert wire[0]["subject"] == f"Compliance due soon: GSTR-3B September 2026 — {CLIENT_NAME}"


def test_an_immediate_rerun_of_the_sweep_sends_none(world, wire):
    rec = _obligation("GSTR-3B September 2026", "2026-10-20")
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert len(wire) == 1
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert len(wire) == 1, "the sweep's own once-a-day guard"

    # THE SECOND LINE OF DEFENCE. POST /api/compliance/run-escalations and the
    # daily job can both run on the same day, and a record whose escalation
    # bookkeeping was lost would pass the guard above. The mail record must
    # still refuse the second mail.
    compliance_records_repo.update(rec["id"], {"last_escalated_tier": None, "last_escalated_on": None})
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert len(wire) == 1, "the record of sends is what makes a re-run send none"


def test_each_tier_is_its_own_mail(world, wire):
    _obligation("GSTR-3B September 2026", "2026-10-20")
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})      # due_7
    ob.escalate(FIRM, today=date(2026, 10, 17), actor={"auth_user_id": "a"})      # due_3
    ob.escalate(FIRM, today=date(2026, 10, 19), actor={"auth_user_id": "a"})      # due_1
    assert len(wire) == 3


def test_an_overdue_obligation_is_mailed_weekly_and_never_daily(world, wire):
    from datetime import timedelta
    _obligation("GSTR-3B August 2026", "2026-09-20")
    first = date(2026, 9, 21)
    sent_on = []
    for offset in range(15):      # 21 Sep .. 5 Oct, fifteen mornings
        before = len(wire)
        ob.escalate(FIRM, today=first + timedelta(days=offset), actor={"auth_user_id": "a"})
        if len(wire) > before:
            sent_on.append(offset)
    assert sent_on == [0, 7, 14], f"mailed {sent_on} days after the first: weekly, like the in-app notification"


def test_a_person_with_the_deadline_preference_off_gets_no_mail_but_still_the_notification(world, wire):
    mail.set_preference(FIRM, PREPARER["id"], "compliance_deadline", False)
    _obligation("GSTR-3B September 2026", "2026-10-20")
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert wire == []
    assert len(_mine("compliance_due")) == 1


def test_a_failed_send_is_recorded_and_does_not_block_the_retry(world, monkeypatch):
    monkeypatch.setattr(es, "_RESEND_API_KEY", "")
    _obligation("GSTR-3B September 2026", "2026-10-20")
    ob.escalate(FIRM, today=date(2026, 10, 13), actor={"auth_user_id": "a"})
    assert [r["status"] for r in mail.MOCK_LOG] == ["failed"]
    assert mail.MOCK_LOG[0]["dedupe_key"] is None, "a failed attempt must never block the retry"


# ── the task sweeps ──────────────────────────────────────────────────────────

@pytest.fixture
def task_sweep(world, monkeypatch):
    import services.escalation_service as esc
    monkeypatch.setattr(esc.escalation_service, "_log_task_escalation", lambda *a, **k: {})
    monkeypatch.setattr(esc.escalation_rule_repo, "get_applicable_escalations",
                        lambda firm_id, task: [{"id": "r1", "rule_type": "manager_notify"}]
                        if task.get("due_date") and task["due_date"] < "2026-10-14" else [])
    monkeypatch.setattr(esc.user_repo, "find_all",
                        lambda firm_id=None, role=None, **k: [p for p in PEOPLE.values()
                                                              if role is None or p["role"] == role])
    monkeypatch.setattr(esc, "ist_today", lambda: date(2026, 10, 14))
    return esc


def _tasks(monkeypatch, esc, *tasks):
    monkeypatch.setattr(esc.task_repo, "find_all",
                        lambda firm_id=None, **k: [dict(t) for t in tasks])


def test_the_task_sweep_mails_the_manager_once_and_the_assignee_their_own_overdue_list(
        task_sweep, wire, monkeypatch):
    overdue = {"id": "t-od", "firm_id": FIRM, "client_id": CLIENT, "title": "File TDS return",
               "due_date": "2026-10-10", "status": "todo", "assigned_to": PREPARER["id"]}
    _tasks(monkeypatch, task_sweep, overdue)
    monkeypatch.setattr("services.practice_mail_service.ist_today", lambda: date(2026, 10, 14))
    task_sweep.escalation_service.run_all_escalations(FIRM)
    to = sorted(_recipients(wire))
    assert to == sorted([MANAGER["email"], PREPARER["email"]]), (
        "the manager hears it escalated; the assignee hears it is theirs and overdue")
    subjects = {tuple(b["to"]): b["subject"] for b in wire}
    assert subjects[(PREPARER["email"],)] == f"OVERDUE: File TDS return"
    assert subjects[(MANAGER["email"],)] == "Escalation: File TDS return is overdue"


def test_re_running_the_task_sweep_straight_away_sends_none(task_sweep, wire, monkeypatch):
    overdue = {"id": "t-od", "firm_id": FIRM, "client_id": CLIENT, "title": "File TDS return",
               "due_date": "2026-10-10", "status": "todo", "assigned_to": PREPARER["id"]}
    _tasks(monkeypatch, task_sweep, overdue)
    monkeypatch.setattr("services.practice_mail_service.ist_today", lambda: date(2026, 10, 14))
    task_sweep.escalation_service.run_all_escalations(FIRM)
    first = len(wire)
    assert first == 2
    # POST /api/tasks/trigger-escalations has no once-a-day flag and the in-app
    # notifications are not deduplicated — the record of sends is what stops it.
    task_sweep.escalation_service.run_all_escalations(FIRM)
    assert len(wire) == first


def test_an_overdue_task_reminder_repeats_weekly_not_daily(world, wire):
    overdue = {"id": "t-od", "firm_id": FIRM, "client_id": CLIENT, "title": "File TDS return",
               "due_date": "2026-10-01", "status": "todo", "assigned_to": PREPARER["id"]}
    days = []
    for d in range(2, 20):
        before = len(wire)
        mail.send_overdue_task_mails(FIRM, [overdue], today=date(2026, 10, d))
        if len(wire) > before:
            days.append(d)
    assert days == [2, 9, 16]


def test_a_completed_or_unassigned_task_is_never_mailed_as_overdue(world, wire):
    done = {"id": "a", "firm_id": FIRM, "client_id": CLIENT, "title": "x", "due_date": "2026-10-01",
            "status": "completed", "assigned_to": PREPARER["id"]}
    nobody = {"id": "b", "firm_id": FIRM, "client_id": CLIENT, "title": "y", "due_date": "2026-10-01",
              "status": "todo"}
    assert mail.send_overdue_task_mails(FIRM, [done, nobody], today=date(2026, 10, 14)) == {}
    assert wire == []


def test_the_assignee_is_read_from_either_column(world, wire):
    """`tasks` carries both `assigned_to` and `assignee_id`; the API writes only
    the first and the older work-allocation screen read only the second."""
    t = {"id": "t-x", "firm_id": FIRM, "client_id": CLIENT, "title": "Old row",
         "due_date": "2026-10-01", "status": "todo", "assignee_id": PREPARER["id"]}
    mail.send_overdue_task_mails(FIRM, [t], today=date(2026, 10, 14))
    assert _recipients(wire) == [PREPARER["email"]]


# ── preferences, through the router ──────────────────────────────────────────

def test_the_preferences_screen_is_served_the_vocabulary_and_whether_a_choice_was_made(world):
    c = _staff_client(PREPARER, notifications_router)
    events = c.get("/api/notifications/email-preferences").json()["data"]["events"]
    assert [e["event_type"] for e in events] == list(rules.EVENT_TYPES)
    assert all(e["email_enabled"] and e["is_default"] for e in events)

    res = c.put("/api/notifications/email-preferences",
                json={"event_type": "task_overdue", "email_enabled": False})
    assert res.status_code == 200
    by = {e["event_type"]: e for e in res.json()["data"]["events"]}
    assert by["task_overdue"]["email_enabled"] is False and by["task_overdue"]["is_default"] is False
    assert by["task_assigned"]["is_default"] is True, "an untouched event is still the default"

    back = c.put("/api/notifications/email-preferences",
                 json={"event_type": "task_overdue", "email_enabled": True}).json()["data"]["events"]
    assert {e["event_type"]: e for e in back}["task_overdue"]["is_default"] is False, (
        "choosing the default is still a choice, and the screen says so")


def test_an_event_the_product_does_not_define_is_refused_with_a_sentence(world):
    res = _staff_client(PREPARER, notifications_router).put(
        "/api/notifications/email-preferences",
        json={"event_type": "invoice_paid", "email_enabled": True})
    assert res.status_code == 422
    assert "not an event" in res.json()["detail"]


def test_a_preference_is_the_callers_own_and_cannot_name_somebody_else(world):
    c = _staff_client(PREPARER, notifications_router)
    c.put("/api/notifications/email-preferences",
          json={"event_type": "task_assigned", "email_enabled": False, "user_id": MANAGER["id"]})
    assert mail.chosen_preferences(FIRM, MANAGER["id"]) == {}
    assert mail.chosen_preferences(FIRM, PREPARER["id"]) == {"task_assigned": False}


def test_a_person_reads_the_record_of_mail_sent_to_them(world, wire):
    import services.notification_service as ns
    ns.notification_service.notify_task_assigned(TASK, PREPARER, MANAGER)
    rows = _staff_client(PREPARER, notifications_router).get(
        "/api/notifications/email-log").json()["data"]["sent"]
    assert [(r["event_type"], r["status"]) for r in rows] == [("task_assigned", "sent")]
    other = _staff_client(MANAGER, notifications_router).get(
        "/api/notifications/email-log").json()["data"]["sent"]
    assert other == []


# ── the rule module ──────────────────────────────────────────────────────────

def test_no_row_means_the_events_own_default_and_an_unknown_event_is_never_mailed():
    assert rules.wants_email("task_assigned", {}) is True
    assert rules.wants_email("task_assigned", {"task_assigned": False}) is False
    assert rules.wants_email("task_assigned", None) is True
    assert rules.wants_email("something_added_next_year", {"something_added_next_year": True}) is False, (
        "a row written under an older vocabulary cannot switch on a mail somebody adds later")


def test_the_dedupe_key_is_one_inbox_one_thing_one_tier_one_day():
    d = date(2026, 10, 13)
    a = rules.dedupe_key("compliance_deadline", "Ca@Firm.in", "r1", "due_7", d)
    assert a == rules.dedupe_key("compliance_deadline", " ca@firm.in ", "r1", "due_7", d)
    assert a != rules.dedupe_key("compliance_deadline", "ca@firm.in", "r1", "due_3", d)
    assert a != rules.dedupe_key("compliance_deadline", "ca@firm.in", "r2", "due_7", d)
    assert a != rules.dedupe_key("compliance_deadline", "ca@firm.in", "r1", "due_7", date(2026, 10, 14))


def test_an_overdue_reminder_waits_a_week_and_an_unreadable_last_date_errs_toward_sending():
    today = date(2026, 10, 14)
    assert rules.overdue_reminder_is_due(None, today) is True
    assert rules.overdue_reminder_is_due("2026-10-08", today) is False
    assert rules.overdue_reminder_is_due("2026-10-07", today) is True
    assert rules.overdue_reminder_is_due("garbage", today) is True


# ── the production queries, against the real columns ─────────────────────────

class _UpsertingDB(SchemaCheckedDB):
    """The double lacks upsert; this one adds it over `update`/`insert`."""

    def table(self, name):
        q = super().table(name)
        db = self

        def upsert(row, on_conflict=None):
            keys = [k.strip() for k in (on_conflict or "id").split(",")]
            existing = [r for r in db.rows.get(name, []) if all(r.get(k) == row.get(k) for k in keys)]
            if existing:
                existing[0].update(row)
            else:
                db.rows.setdefault(name, []).append(dict(row))
            q._pending = [row]
            return q
        q.upsert = upsert
        return q


def test_the_production_queries_name_only_columns_the_migration_creates(monkeypatch):
    """Mock mode never touches the database, so the DATABASE paths of the new
    service are exercised here against a double that refuses a column the
    migration does not declare — read out of the migration file itself."""
    m = "450_a_practices_own_mail_is_recorded_and_a_person_chooses_which_they_get.sql"
    db = _UpsertingDB({"user_notification_preferences": [], "practice_email_log": []})
    db.columns = {**REAL_COLUMNS,
                  "user_notification_preferences": table_columns(m, "user_notification_preferences"),
                  "practice_email_log": table_columns(m, "practice_email_log")}
    monkeypatch.setattr(mail, "_USE_MOCK", False)
    monkeypatch.setattr(mail, "_db", lambda: db)

    mail.set_preference(FIRM, PREPARER["id"], "task_overdue", False)
    mail.set_preference(FIRM, PREPARER["id"], "task_overdue", True)
    assert mail.chosen_preferences(FIRM, PREPARER["id"]) == {"task_overdue": True}
    assert len(db.rows["user_notification_preferences"]) == 1, "an upsert, not a second row"

    sent = []
    day = date(2026, 10, 13)
    ref = mail.Ref("compliance_record", "r1", "due_7")
    assert mail.deliver(FIRM, "compliance_deadline", PREPARER, [ref],
                        lambda refs: sent.append(refs) or True, day=day) == "sent"
    assert mail.deliver(FIRM, "compliance_deadline", PREPARER, [ref],
                        lambda refs: sent.append(refs) or True, day=day) == "duplicate"
    assert len(sent) == 1
    row = db.rows["practice_email_log"][0]
    assert row["status"] == "sent" and row["dedupe_key"] and row["recipient_kind"] == "staff"
    assert mail.recent_log(FIRM, PREPARER["id"])[0]["event_type"] == "compliance_deadline"


# ── the two assignment doors the first pass of this change did not name ──────

def test_instantiating_a_template_for_somebody_mails_them_like_the_other_doors(world, wire, monkeypatch):
    """`POST /api/task-templates/{id}/instantiate` took an `assignee_id`, wrote it
    on the row and told nobody — not in the app, not by mail."""
    import routers.task_templates as tt

    class _Insert:
        def __init__(self, row):
            self.row = row

        def execute(self):
            class R:
                pass
            r = R()
            r.data = [{**self.row, "id": "t-tpl"}]
            return r

    class _DB:
        def table(self, name):
            assert name == "tasks"
            return self

        def insert(self, row):
            return _Insert(row)

    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB())
    monkeypatch.setattr(tt.task_template_repo, "find_by_id",
                        lambda tid, firm_id=None: {"id": tid, "name": "Monthly GST", "firm_id": FIRM})
    monkeypatch.setattr(tt, "assert_client_access", lambda u, c: None)
    monkeypatch.setattr("repositories.task_extras_repository.task_extras_repo.log_event", lambda **k: None)
    res = _staff_client(PARTNER, tt).post("/api/task-templates/tpl-1/instantiate", json={
        "client_id": CLIENT, "assignee_id": PREPARER["id"], "due_date": "2026-10-20"})
    assert res.status_code == 200, res.text
    assert _recipients(wire) == [PREPARER["email"]]
    assert [n["user_id"] for n in _mine("task_assigned")] == [PREPARER["id"]]


def test_a_task_the_sweep_hands_to_somebody_new_mails_them_once_not_twice(task_sweep, wire, monkeypatch):
    """The `reassign_overdue` rule gives an overdue task to the first person with
    a role. They are mailed that it is theirs — and NOT also in the same sweep
    that it is overdue, which would be two mails about one thing."""
    esc = task_sweep
    overdue = {"id": "t-od", "firm_id": FIRM, "client_id": CLIENT, "title": "File TDS return",
               "due_date": "2026-10-10", "status": "todo", "assigned_to": MANAGER["id"]}
    monkeypatch.setattr(esc.escalation_rule_repo, "get_applicable_escalations",
                        lambda firm_id, task: [{"id": "r2", "rule_type": "reassign_overdue",
                                                "reassign_to_role": "Executive"}])
    _tasks(monkeypatch, esc, overdue)
    updates = []
    monkeypatch.setattr(esc.task_repo, "update", lambda tid, upd: updates.append(upd))
    monkeypatch.setattr(esc.task_extras_repo, "log_event", lambda **k: None)
    monkeypatch.setattr("services.practice_mail_service.ist_today", lambda: date(2026, 10, 14))
    esc.escalation_service.run_all_escalations(FIRM)
    assert updates and updates[0]["assigned_to"] == PREPARER["id"]
    to = _recipients(wire)
    assert to.count(PREPARER["email"]) == 1, f"the new owner got {to.count(PREPARER['email'])} mails"
    subjects = [b["subject"] for b in wire if b["to"] == [PREPARER["email"]]]
    assert subjects == ["New task assigned: File TDS return"]
