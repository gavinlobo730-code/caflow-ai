"""Eight more doors ask whose the row is before they store a link to it (POST-A-353, the survey of the fields no rule read).

WHAT WAS WRONG
    `test_a_request_that_names_a_row_asks_whose_it_is.py` reads the request models for fifteen kinds of named row. A survey on 2-11-2026 of
    every other field that ends in `_id` (59 names) read each door that stores one and found eight that stored the id as typed, each a
    plain foreign key that any row in the database satisfies, and each verified in the code before it was fixed:
      * a director and an MCA filing named any company (`company_id`; the company view lists directors by company and firm alone, so a
        director of one client showed under a sibling's company);
      * a reminder named any task (`task_id`);
      * a proposal named any firm's lead (`lead_id`, a firm-level row, so the question is the firm's);
      * an XBRL package named any year-end engagement (`year_end_engagement_id`);
      * an ESI or professional-tax remittance named any payroll run (`run_id`);
      * a revised or updated income-tax return named any filing (`original_filing_id`), and the earlier filing's ACKNOWLEDGEMENT NUMBER
        AND FILING DATE were copied from it into the new return when the caller left them blank, so a sibling client's receipt was
        read across and echoed in the response;
      * a billing schedule named any firm's service (`service_id`, the practice's own catalogue), which pinned another firm's service as in
        use (its delete is refused while a schedule names it) and told the caller whether the id exists anywhere.
    A ninth finding is a wording tell and not a link: the task-dependency door answered "Dependency task not found" for an id that does
    not exist and the default "Not found" for one in a client the caller cannot reach.
    WHAT THE SURVEY FOUND ALREADY ASKED, and so left alone: the order and challan lines, the price list, a party credit's document, the
    opening document's party, the ITC reversal parent, the GSTR-9C reconciliation, the AIS upload, the ageing target, the bank batch,
    match and transfer pair, the engagement's lead, the entity relationship, the bulk assignment and the time entry's engagement.

WHAT THIS HOLDS (mock mode: a fake database with two clients of one firm and a second firm)
    * each helper in `services/named_row_ownership.py`: the client's own row passes, a sibling client's, another firm's, a missing one and
      a deleted one (for tasks) are the same 404 with the same words, and nothing named asks nothing;
    * each of the eight doors: the sibling's id is refused in those words and NOTHING IS STORED, and the same request with the client's own
      id is not stopped by the question (the control: the refusal is the client);
    * the dependency door answers an unreachable task in the words of a missing one.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.billing as billing_router
import routers.itr_workspace as itr_router
import routers.lifecycle as lifecycle_router
import routers.mca_workspace as mca_router
import routers.payroll as payroll_router
import routers.reminders as reminders_router
import routers.task_extras as task_extras_router
import routers.time_tracking as time_router
import routers.xbrl_engine as xbrl_router
import services.billing_service as billing_service
import services.internal_client_service as internal_service
from core.auth import get_current_user
from services import named_row_ownership as own
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
OTHER_FIRM = "22222222-2222-2222-2222-222222222222"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
INTERNAL = "cccccccc-cccc-cccc-cccc-cccccccccccc"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


def _world() -> FakeDB:
    db = FakeDB()
    db.seed("firms", {"id": FIRM, "internal_client_id": INTERNAL})
    for client in (A, B, INTERNAL):
        db.seed("clients", {"id": client, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    for tag, client in (("a", A), ("b", B)):
        db.seed("mca_companies", {"id": f"company-{tag}", "firm_id": FIRM, "client_id": client, "company_name": f"Co {tag}"})
        db.seed("tasks", {"id": f"task-{tag}", "firm_id": FIRM, "client_id": client, "title": f"Task {tag}", "deleted_at": None})
        db.seed("year_end_engagements", {"id": f"yee-{tag}", "firm_id": FIRM, "client_id": client})
        db.seed("payroll_runs", {"id": f"run-{tag}", "firm_id": FIRM, "client_id": client})
        db.seed("itr_filings", {"id": f"filing-{tag}", "firm_id": FIRM, "client_id": client, "acknowledgement_number": f"ACK-{tag}",
                                "filing_date": "2025-07-31"})
    db.seed("tasks", {"id": "task-gone", "firm_id": FIRM, "client_id": A, "title": "Deleted", "deleted_at": "2026-01-01T00:00:00Z"})
    db.seed("leads", {"id": "lead-1", "firm_id": FIRM, "name": "Lead"})
    db.seed("leads", {"id": "lead-other", "firm_id": OTHER_FIRM, "name": "Other firm's lead"})
    db.seed("mca_companies", {"id": "company-other-firm", "firm_id": OTHER_FIRM, "client_id": "zzzz", "company_name": "Elsewhere"})
    db.seed("service_catalogue", {"id": "svc-practice", "firm_id": FIRM, "client_id": INTERNAL, "name": "Retainer"})
    db.seed("service_catalogue", {"id": "svc-client-b", "firm_id": FIRM, "client_id": B, "name": "B's own item"})
    db.seed("service_catalogue", {"id": "svc-other-firm", "firm_id": OTHER_FIRM, "client_id": "yyyy", "name": "Other firm"})
    return db


@pytest.fixture()
def world(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [mca_router, billing_service, internal_service])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(internal_service, "_db", lambda: db, raising=False)
    monkeypatch.setattr(billing_service, "_db", lambda: db, raising=False)
    monkeypatch.setattr(lifecycle_router, "_db", lambda: db, raising=False)
    monkeypatch.setattr(payroll_router, "_db", lambda: db, raising=False)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _client(*routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _refused(res, words: str):
    assert res.status_code == 404 and res.json()["detail"] == words, (res.status_code, res.text)


def _not_stopped(res, words: str):
    """The control: the same request with the client's own id is not refused by THE QUESTION. What the rest of the door does with it (a
    fake database does not carry every table a door goes on to write) is not this test's subject, so a body that is not JSON passes."""
    try:
        detail = res.json().get("detail")
    except ValueError:
        detail = None
    assert detail != words, res.text


# ── the helpers ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("call,own_id,words", [
    (lambda db, i: own.mca_company_is_the_clients(db, FIRM, A, i), "company-a", "That company was not found."),
    (lambda db, i: own.task_is_the_clients(db, FIRM, A, i), "task-a", "That task was not found."),
    (lambda db, i: own.year_end_engagement_is_the_clients(db, FIRM, A, i), "yee-a", "That year-end engagement was not found."),
    (lambda db, i: own.payroll_run_is_the_clients(db, FIRM, A, i), "run-a", "That payroll run was not found."),
    (lambda db, i: own.itr_filing_is_the_clients(db, FIRM, A, i), "filing-a", "That filing was not found."),
])
def test_a_client_row_helper_passes_its_own_and_refuses_a_stranger_a_missing_one_and_another_firms_alike(world, call, own_id, words):
    call(world, own_id)                                    # the client's own: no answer is the pass
    sibling = own_id[:-1] + "b"
    for stranger in (sibling, "nothing-by-that-id", "company-other-firm"):
        with pytest.raises(HTTPException) as caught:
            call(world, stranger)
        assert caught.value.status_code == 404 and caught.value.detail == words, (stranger, caught.value.detail)


def test_a_deleted_task_is_refused_like_a_missing_one(world):
    with pytest.raises(HTTPException) as caught:
        own.task_is_the_clients(world, FIRM, A, "task-gone")
    assert caught.value.detail == "That task was not found."


def test_a_lead_is_the_firms_and_a_leads_of_another_firm_is_not(world):
    own.lead_is_the_firms(world, FIRM, "lead-1")
    for stranger in ("lead-other", "no-such-lead"):
        with pytest.raises(HTTPException) as caught:
            own.lead_is_the_firms(world, FIRM, stranger)
        assert caught.value.detail == "That lead was not found."


def test_a_service_is_the_practices_own_and_neither_a_clients_nor_another_firms_is(world):
    own.service_is_the_practices(world, FIRM, "svc-practice")
    for stranger in ("svc-client-b", "svc-other-firm", "no-such-service"):
        with pytest.raises(HTTPException) as caught:
            own.service_is_the_practices(world, FIRM, stranger)
        assert caught.value.detail == "That service was not found.", stranger


@pytest.mark.parametrize("call", [
    lambda db: own.mca_company_is_the_clients(db, FIRM, A, None), lambda db: own.task_is_the_clients(db, FIRM, A, ""),
    lambda db: own.lead_is_the_firms(db, FIRM, None), lambda db: own.year_end_engagement_is_the_clients(db, FIRM, A, "  "),
    lambda db: own.payroll_run_is_the_clients(db, FIRM, A, None), lambda db: own.itr_filing_is_the_clients(db, FIRM, A, None),
    lambda db: own.service_is_the_practices(db, FIRM, None),
])
def test_nothing_named_asks_nothing(world, call):
    call(world)


@pytest.mark.parametrize("call", [
    lambda: own.mca_company_is_the_clients(None, FIRM, A, "x"), lambda: own.task_is_the_clients(None, FIRM, A, "x"),
    lambda: own.lead_is_the_firms(None, FIRM, "x"), lambda: own.year_end_engagement_is_the_clients(None, FIRM, A, "x"),
    lambda: own.payroll_run_is_the_clients(None, FIRM, A, "x"), lambda: own.itr_filing_is_the_clients(None, FIRM, A, "x"),
    lambda: own.service_is_the_practices(None, FIRM, "x"),
])
def test_no_database_asks_nothing(call):
    call()


# ── the doors ────────────────────────────────────────────────────────────────────────────────────────

def test_a_director_names_a_company_of_its_own_client_only(world):
    body = {"client_id": A, "din": "01234567", "name": "D", "designation": "Director"}
    client = _client(mca_router)
    _refused(client.post("/api/mca-workspace/directors", json={**body, "company_id": "company-b"}), "That company was not found.")
    assert world.rows("mca_directors") == [], "nothing was stored for the sibling's company"
    _not_stopped(client.post("/api/mca-workspace/directors", json={**body, "company_id": "company-a"}), "That company was not found.")


def test_an_mca_filing_names_a_company_of_its_own_client_only(world):
    body = {"client_id": A, "form_type": "AOC-4", "financial_year": "2025-26"}
    client = _client(mca_router)
    _refused(client.post("/api/mca-workspace/filings", json={**body, "company_id": "company-b"}), "That company was not found.")
    assert world.rows("mca_filings") == []
    _not_stopped(client.post("/api/mca-workspace/filings", json={**body, "company_id": "company-a"}), "That company was not found.")


def test_a_reminder_names_a_task_of_its_own_client_only(world):
    body = {"client_id": A, "reminder_type": "task_due", "scheduled_for": "2026-05-01T09:00:00"}
    client = _client(reminders_router)
    _refused(client.post("/api/reminders", json={**body, "task_id": "task-b"}), "That task was not found.")
    assert world.rows("reminders") == []
    _not_stopped(client.post("/api/reminders", json={**body, "task_id": "task-a"}), "That task was not found.")


def test_a_proposal_names_a_lead_of_its_own_firm_only(world):
    client = _client(lifecycle_router)
    _refused(client.post("/api/lifecycle/proposals", json={"client_id": A, "title": "P", "lead_id": "lead-other"}), "That lead was not found.")
    assert world.rows("proposals") == []
    _not_stopped(client.post("/api/lifecycle/proposals", json={"client_id": A, "title": "P", "lead_id": "lead-1"}), "That lead was not found.")


def test_an_xbrl_package_names_a_year_end_engagement_of_its_own_client_only(world, monkeypatch):
    body = {"client_id": A, "financial_year": "2025-26"}
    client = _client(xbrl_router)
    _refused(client.post("/api/xbrl/packages", json={**body, "year_end_engagement_id": "yee-b"}), "That year-end engagement was not found.")
    assert world.rows("xbrl_packages") == []
    _not_stopped(client.post("/api/xbrl/packages", json={**body, "year_end_engagement_id": "yee-a"}), "That year-end engagement was not found.")


def test_a_remittance_names_a_payroll_run_of_its_own_client_only(world):
    body = {"scheme": "esi", "wage_month": "2026-04"}
    client = _client(payroll_router)
    _refused(client.post(f"/api/payroll/clients/{A}/remittances", json={**body, "run_id": "run-b"}), "That payroll run was not found.")
    assert world.rows("statutory_remittances") == []
    _not_stopped(client.post(f"/api/payroll/clients/{A}/remittances", json={**body, "run_id": "run-a"}), "That payroll run was not found.")


def test_a_revised_return_names_a_filing_of_its_own_client_only_and_a_siblings_receipt_is_not_copied(world):
    body = {"client_id": A, "financial_year": "2025-26", "assessment_year": "2026-27", "itr_form": "ITR-3", "return_type": "revised"}
    client = _client(itr_router)
    res = client.post("/api/itr/filings", json={**body, "original_filing_id": "filing-b"})
    _refused(res, "That filing was not found.")
    assert "ACK-b" not in res.text, "the sibling's acknowledgement number must not be echoed"
    assert [f["id"] for f in world.rows("itr_filings")] == ["filing-a", "filing-b"], "no return was created for the sibling's filing"
    _not_stopped(client.post("/api/itr/filings", json={**body, "original_filing_id": "filing-a"}), "That filing was not found.")


def test_a_billing_schedule_names_a_service_of_the_practices_own_catalogue_only(world):
    body = {"client_id": A, "arrangement": "retainer", "cadence": "monthly", "amount_paise": 100_000}
    client = _client(billing_router)
    for stranger in ("svc-client-b", "svc-other-firm"):
        _refused(client.post("/api/billing/schedules", json={**body, "service_id": stranger}), "That service was not found.")
    assert world.rows("billing_schedules") == []
    _not_stopped(client.post("/api/billing/schedules", json={**body, "service_id": "svc-practice"}), "That service was not found.")
    assert [r["service_id"] for r in world.rows("billing_schedules")] == ["svc-practice"]


def test_a_billing_schedule_cannot_be_re_pointed_at_another_firms_service(world):
    world.seed("billing_schedules", {"id": "sched-1", "firm_id": FIRM, "client_id": A, "service_id": "svc-practice", "arrangement": "retainer",
                                     "cadence": "monthly", "amount_paise": 100_000, "is_active": True})
    client = _client(billing_router)
    _refused(client.patch("/api/billing/schedules/sched-1", json={"service_id": "svc-other-firm"}), "That service was not found.")
    assert world.rows("billing_schedules")[0]["service_id"] == "svc-practice"
    own_ = client.patch("/api/billing/schedules/sched-1", json={"service_id": "svc-practice", "amount_paise": 120_000})
    assert own_.status_code == 200, own_.text


def test_a_task_dependency_on_a_task_the_caller_cannot_reach_answers_in_the_words_of_a_missing_one(world, monkeypatch):
    """The first lookup answers 'Dependency task not found' for an id that does not exist; a task of a client the caller is not assigned
    to answered the default 'Not found', which told the caller the id exists."""
    import repositories.task_repository as repo_module
    rows = {"t-1": {"id": "t-1", "client_id": A, "title": "mine"}, "t-hidden": {"id": "t-hidden", "client_id": B, "title": "hidden"}}
    monkeypatch.setattr(task_extras_router.task_repo, "find_by_id", lambda tid, firm_id=None, **k: rows.get(tid))
    caller = {**PARTNER, "role": "Executive", "assigned_client_ids": [A], "allowed_client_ids": [A]}
    import core.authz as authz
    monkeypatch.setattr(authz, "can_access_client", lambda user, cid: cid == A)
    monkeypatch.setattr(task_extras_router, "assert_client_access",
                        lambda user, cid, detail="Not found": (_ for _ in ()).throw(HTTPException(404, detail)) if cid != A else None)
    app = FastAPI()
    app.include_router(task_extras_router.router)
    app.dependency_overrides[get_current_user] = lambda: caller
    http = TestClient(app, raise_server_exceptions=False)
    missing = http.post("/api/tasks/t-1/dependencies", json={"depends_on_task_id": "t-nothing"})
    hidden = http.post("/api/tasks/t-1/dependencies", json={"depends_on_task_id": "t-hidden"})
    assert missing.status_code == hidden.status_code == 404
    assert missing.json()["detail"] == hidden.json()["detail"] == "Dependency task not found", (missing.text, hidden.text)


# ── the ninth door, found by the derived rule and not by the survey ─────────────────────────────────

def test_a_time_entry_and_a_timer_name_a_task_of_their_own_client_only(world):
    """`time_entries.task_id` is a global foreign key; the survey that found the other eight listed the fields by name and this one was found
    when the seven new kinds were added to the derived rule."""
    client = _client(time_router)
    manual = {"client_id": A, "started_at": "2026-05-01T09:00:00", "ended_at": "2026-05-01T10:00:00", "task_id": "task-b"}
    _refused(client.post("/api/time-entries", json=manual), "That task was not found.")
    _refused(client.post("/api/time-entries/start", json={"client_id": A, "task_id": "task-b"}), "That task was not found.")
    assert world.rows("time_entries") == [], "nothing was stored for the sibling's task"
    _not_stopped(client.post("/api/time-entries", json={**manual, "task_id": "task-a"}), "That task was not found.")


def test_a_time_entry_with_no_client_names_a_task_the_caller_can_reach_only(world, monkeypatch):
    # A caller assigned to client A only: a request that names no client is let through, a task of client B is not reachable.
    monkeypatch.setattr(time_router, "assert_client_access",
                        lambda user, cid, detail="Not found": (_ for _ in ()).throw(HTTPException(404, detail)) if cid not in (None, A) else None)
    client = _client(time_router)
    body = {"started_at": "2026-05-01T09:00:00", "ended_at": "2026-05-01T10:00:00"}
    _refused(client.post("/api/time-entries", json={**body, "task_id": "task-b"}), "That task was not found.")
    _refused(client.post("/api/time-entries", json={**body, "task_id": "no-such-task"}), "That task was not found.")
    assert world.rows("time_entries") == []
    _not_stopped(client.post("/api/time-entries", json={**body, "task_id": "task-a"}), "That task was not found.")
