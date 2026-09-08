"""
A closed year can be opened again — ACC-05.

WHAT WAS WRONG
    Finalising a year-end engagement writes a client_year_locks row (migration
    289), and the posting kernel then refuses every entry for that client and
    year with, in its own words:

        "FY 2025-26 is closed for this client — its year-end has been
         finalised. Reopen the year before posting to it."

    There was no way to reopen it. year_lock_service.set_client_lock has taken
    lock=False since 289 and the only caller in the repository passed
    lock=True; routers/year_end.py mapped "locked" to an EMPTY list of
    transitions and _check_engagement_locked 403'd every modification before
    the transition table was even consulted; no screen mentioned
    client_year_locks. The kernel was naming an action the product did not
    have, and a CA's only remedies were a DELETE straight on the table or
    posting the correction into the wrong year.

    Every Indian practice reopens a closed year at least once a season: a
    revised bank interest certificate in October, a §143(1) intimation, an
    audit adjustment found while filing the ITR. Tally's period lock is set and
    cleared at will; Zoho Books lets an admin unlock a closed period with a
    reason.

AND THE LOCK ITSELF NEVER WORKED
    Both routers passed current_user["auth_user_id"] as the actor into
    lock_year_if_completing, and it lands in client_year_locks.locked_by, which
    FKs public.users(id). Production holds no user whose users.id equals their
    auth id (checked: 0 of 2), so the INSERT would raise 23503 AFTER the
    engagement row had already been written status='locked' — leaving the
    engagement finalised and terminal while the client's year stayed open.
    Latent only because production has no year-end engagements yet. Pinned in
    test_users_fk_columns_take_the_internal_id.py.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-partner"}
MANAGER = {"id": "u2", "firm_id": "F1", "role": "Manager",
           "email": "m@f1.test", "auth_user_id": "auth-manager"}


def _client_for(app: FastAPI, user: dict) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def app_db(monkeypatch):
    import routers.year_end_reviews as rev
    import routers.year_end as ye
    import services.year_lock_service as yls
    db = FakeDB()
    for mod in (rev, ye):
        monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(rev, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(yls, "log_event", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(rev.router)
    app.include_router(ye.router)
    return app, db


def _locked_engagement(db, **over):
    row = {"id": "ENG1", "firm_id": "F1", "client_id": "C1",
           "financial_year": "2024-25", "status": "locked",
           "final_approved_by": "u1", "final_approved_at": "2026-09-20T00:00:00Z",
           "locked_at": "2026-09-20T00:00:00Z"}
    row.update(over)
    db.seed("year_end_engagements", row)
    db.seed("client_year_locks", {
        "id": "LK1", "firm_id": "F1", "client_id": "C1",
        "financial_year": "2024-25", "locked_by": "u1",
        "reason": "Year-end engagement finalised"})
    return row


# ── the reopen ───────────────────────────────────────────────────────────────

def test_a_partner_can_reopen_a_finalised_engagement(app_db):
    app, db = app_db
    _locked_engagement(db)

    r = _client_for(app, PARTNER).post(
        "/year-end/engagements/ENG1/reviews/reopen",
        json={"comment": "Revised bank interest certificate received"})

    assert r.status_code == 200, r.text
    assert r.json()["success"] is True
    assert db.rows("year_end_engagements")[0]["status"] == "approved"


def test_reopening_actually_unlocks_the_clients_year(app_db):
    """The engagement row is the workflow. THIS is what the posting kernel
    reads — and it is the half that did not exist."""
    app, db = app_db
    _locked_engagement(db)

    _client_for(app, PARTNER).post(
        "/year-end/engagements/ENG1/reviews/reopen",
        json={"comment": "§143(1) intimation forces a correction"})

    from services.year_lock_service import is_client_year_locked
    assert is_client_year_locked(db, "F1", "C1", "2024-25") is False
    assert db.rows("client_year_locks") == []


def test_the_reason_is_required(app_db):
    """Reopening reverses a Partner's own final approval and lets postings back
    into a closed year. An audit row that records no reason answers nothing at
    the next review."""
    app, db = app_db
    _locked_engagement(db)

    r = _client_for(app, PARTNER).post(
        "/year-end/engagements/ENG1/reviews/reopen", json={"comment": "   "})

    assert r.status_code == 422
    assert "reason" in r.json()["detail"].lower()
    assert db.rows("year_end_engagements")[0]["status"] == "locked", (
        "a refused reopen must not have moved the engagement")


def test_only_a_partner_can_reopen(app_db):
    """A Manager may take an engagement to 'approved' in the ordinary review
    loop. Going there FROM 'locked' is a different act and is Partner-only —
    which is why the guard is keyed on the transition PAIR and not the target."""
    app, db = app_db
    _locked_engagement(db)

    r = _client_for(app, MANAGER).post(
        "/year-end/engagements/ENG1/reviews/reopen",
        json={"comment": "audit adjustment"})

    assert r.status_code == 403
    assert db.rows("year_end_engagements")[0]["status"] == "locked"


def test_an_engagement_that_is_not_locked_cannot_be_reopened(app_db):
    app, db = app_db
    _locked_engagement(db, status="approved")

    r = _client_for(app, PARTNER).post(
        "/year-end/engagements/ENG1/reviews/reopen", json={"comment": "why not"})

    assert r.status_code == 422
    assert "locked" in r.json()["detail"].lower()


def test_the_final_approval_is_not_erased(app_db):
    """final_approved_by/at record that the approval HAPPENED. Clearing them
    would make the history claim it never did. A reopen is an event on top of
    that history, not a rewrite of it — the same append-only posture the
    general ledger takes."""
    app, db = app_db
    _locked_engagement(db)

    _client_for(app, PARTNER).post(
        "/year-end/engagements/ENG1/reviews/reopen",
        json={"comment": "revised certificate"})

    row = db.rows("year_end_engagements")[0]
    assert row["final_approved_by"] == "u1"
    assert row["final_approved_at"] == "2026-09-20T00:00:00Z"
    assert row["reopened_by"] == "u1"
    assert row["reopen_reason"] == "revised certificate"
    assert row["reopened_at"]
    assert row["locked_at"] is None, "the lock timestamp no longer applies"


def test_the_reopen_is_written_to_the_review_history(app_db):
    """Migration 344 extends year_end_review_events' CHECK to hold 'reopened'.
    Without it the insert would violate the constraint and _record_review_event
    swallows its exception — the review trail would be silently missing the one
    event that most needs explaining."""
    app, db = app_db
    _locked_engagement(db)

    _client_for(app, PARTNER).post(
        "/year-end/engagements/ENG1/reviews/reopen",
        json={"comment": "revised certificate"})

    events = db.rows("year_end_review_events")
    assert [e["event_type"] for e in events] == ["reopened"]
    assert events[0]["comment"] == "revised certificate"
    assert events[0]["actor_id"] == "u1", "the INTERNAL user id, not the auth id"


def test_a_reopened_year_can_be_finalised_again(app_db):
    """It lands on 'approved', which is where final-approve takes it from, so
    the Partner re-closes through the ordinary step once the correction is in
    — rather than through a second, parallel path."""
    app, db = app_db
    _locked_engagement(db)
    c = _client_for(app, PARTNER)

    c.post("/year-end/engagements/ENG1/reviews/reopen",
           json={"comment": "revised certificate"})
    r = c.post("/year-end/engagements/ENG1/reviews/final-approve", json={})

    assert r.status_code == 200, r.text
    assert db.rows("year_end_engagements")[0]["status"] == "locked"
    from services.year_lock_service import is_client_year_locked
    assert is_client_year_locked(db, "F1", "C1", "2024-25") is True


# ── the generic transition endpoint agrees with the reviews router ───────────

def test_both_endpoints_leave_the_same_record_behind(app_db):
    """Two endpoints reaching one workflow must write the same columns, or
    which one the CA used becomes a fact you have to know to read the history."""
    app, db = app_db
    _locked_engagement(db)

    _client_for(app, PARTNER).patch(
        "/year-end/engagements/ENG1/status",
        json={"status": "approved", "comment": "revised certificate"})

    row = db.rows("year_end_engagements")[0]
    assert row["reopened_by"] == "u1"
    assert row["reopen_reason"] == "revised certificate"
    assert row["reopened_at"] and row["locked_at"] is None
    assert row["final_approved_by"] == "u1", "the approval still happened"


def test_the_generic_status_endpoint_no_longer_calls_locked_terminal(app_db):
    """Two routers, one workflow. Leaving 'locked' terminal in year_end.py
    while year_end_reviews.py could reopen is the same two-screens-disagree
    shape as GST-14, in the same phase."""
    app, db = app_db
    _locked_engagement(db)

    r = _client_for(app, PARTNER).patch(
        "/year-end/engagements/ENG1/status",
        json={"status": "approved", "comment": "revised certificate"})

    assert r.status_code == 200, r.text
    assert db.rows("year_end_engagements")[0]["status"] == "approved"
    from services.year_lock_service import is_client_year_locked
    assert is_client_year_locked(db, "F1", "C1", "2024-25") is False


def test_the_generic_endpoint_still_refuses_every_other_change_to_a_locked_one(app_db):
    """_check_engagement_locked exempts exactly the reopen and nothing else."""
    app, db = app_db
    _locked_engagement(db)

    r = _client_for(app, PARTNER).patch(
        "/year-end/engagements/ENG1/status",
        json={"status": "draft", "comment": "nope"})

    assert r.status_code == 403
    assert db.rows("year_end_engagements")[0]["status"] == "locked"


def test_the_generic_endpoint_demands_the_reason_too(app_db):
    """The mock branch and the real branch ask the same three questions,
    because they now ask them through one function. They used to be two copies,
    and a rule added to one would silently not hold in the other."""
    app, db = app_db
    _locked_engagement(db)

    r = _client_for(app, PARTNER).patch(
        "/year-end/engagements/ENG1/status", json={"status": "approved"})

    assert r.status_code == 422
    assert "reason" in r.json()["detail"].lower()
