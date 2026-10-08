"""A payroll reversal records the reason the CA wrote (PRE-A-015, found by driving the Release tab in a browser).

WHAT WAS WRONG
    The Release tab's Reverse button opens a prompt, "Say why", refuses a reason under ten characters, and its
    own comment said "the server records it on the transition log". The request it then sent was
    `POST /api/payroll/runs/{id}/reverse` with NO body, and `reverse_run` took no reason: the sentence a CA wrote
    while they knew why was thrown away, the screen said otherwise, and a month later the log said only that a
    run was reopened. Found when a scripted browser typed a reason and read the request the stub received (an
    empty string).

WHAT THE FIX IS
    An OPTIONAL body `{"reason": "..."}`. When one is sent it is checked (under ten characters is a 422 in the
    screen's own words, over 500 is a 422), and recorded on the run's timeline event and on the audit log, whose
    actor is the AUTH id (`test_the_audit_log_names_one_kind_of_actor`). It is NOT written to
    `payroll_run_transitions.override_reason`: migration 328 gives that column one meaning, "this release went
    ahead over gaps", and ties its CHECK to a move into finalized or paid. A column of its own is a migration
    and is not built here.

    No body keeps today's behaviour exactly, which `test_a_reversal_is_a_move_like_any_other` pins with two
    positional arguments, so the new parameter goes last.

NEGATIVE CONTROL
    Remove `body` from `reverse_run` (or stop passing `reason` to the timeline and the audit log) and the first,
    second and fourth tests fail; drop `_reversal_reason` and the 422 tests fail.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.payroll as payroll_mod
from core.auth import get_current_user
from tests.e2e_harness import FakeDB

FIRM = "FIRM-REV"
PARTNER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@f.test", "role": "Partner"}
REASON = "Wrong attendance imported for September"


@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    db.seed("payroll_runs", {
        "id": "RUN-1", "firm_id": FIRM, "client_id": "CLI", "month": "2026-09", "status": "finalized",
        "journal_entry_id": "JE-ACCRUAL", "disbursement_journal_entry_id": None,
        "finalized_at": "2026-10-03T00:00:00Z",
    })
    reversed_entries: list = []
    from services.phase2_journal_service import phase2_journal_service
    from services.period_validation_service import period_validation_service
    monkeypatch.setattr(phase2_journal_service, "reverse_entry", lambda *a, **k: reversed_entries.append(a))
    monkeypatch.setattr(period_validation_service, "validate_posting_date", lambda *a, **k: None)
    timeline: list = []
    monkeypatch.setattr(payroll_mod.timeline_service, "log", lambda *a, **k: timeline.append((a, k)))
    audit: list = []
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: audit.append((a, k)))
    app = FastAPI()
    app.include_router(payroll_mod.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False), db, reversed_entries, timeline, audit


def _post(client, body=None):
    return client.post("/api/payroll/runs/RUN-1/reverse", **({"json": body} if body is not None else {}))


def test_the_reason_is_on_the_timeline_event(world):
    client, _db, _rev, timeline, _audit = world
    r = _post(client, {"reason": REASON})
    assert r.status_code == 200, r.text
    descriptions = [a[3] for a, _k in timeline if a[2] == "Payroll Reversed"]
    assert len(descriptions) == 1
    assert REASON in descriptions[0], f"the reason is not on the timeline event: {descriptions[0]!r}"


def test_the_reason_is_on_the_audit_log_under_the_auth_id(world):
    client, _db, _rev, _timeline, audit = world
    assert _post(client, {"reason": REASON}).status_code == 200
    assert len(audit) == 1
    args, kwargs = audit[0]
    assert args[:4] == (FIRM, "payroll_run", "RUN-1", "status_change")
    # audit_log.actor_id takes the AUTH id, the mirror image of created_by (CLAUDE.md, the audit-log bullet).
    assert kwargs["actor_id"] == "auth-1" and kwargs["actor_id"] != PARTNER["id"]
    assert kwargs["metadata"]["reason"] == REASON
    assert kwargs["metadata"]["what"] == "reverse"
    assert kwargs["old_data"] == {"status": "finalized"} and kwargs["new_data"] == {"status": "review"}


def test_the_reason_is_trimmed_before_it_is_kept(world):
    client, _db, _rev, _timeline, audit = world
    assert _post(client, {"reason": f"   {REASON}   \n"}).status_code == 200
    assert audit[0][1]["metadata"]["reason"] == REASON


def test_a_reason_under_ten_characters_is_refused_and_nothing_is_reversed(world):
    client, db, reversed_entries, timeline, audit = world
    r = _post(client, {"reason": "short"})
    assert r.status_code == 422
    assert r.json()["detail"] == "A reversal needs a reason of at least 10 characters."
    assert reversed_entries == [], "a journal was reversed although the reason was refused"
    assert next(x for x in db.rows("payroll_runs") if x["id"] == "RUN-1")["status"] == "finalized"
    assert timeline == [] and audit == []


def test_a_reason_over_500_characters_is_refused_not_cut_off(world):
    client, _db, reversed_entries, _timeline, _audit = world
    r = _post(client, {"reason": "x" * 501})
    assert r.status_code == 422
    assert "500" in r.json()["detail"]
    assert reversed_entries == []


@pytest.mark.parametrize("body", [None, {}, {"reason": None}, {"reason": ""}, {"reason": "   "}])
def test_no_reason_is_the_behaviour_it_always_was(world, body):
    """An older client, a script and an empty prompt answer all behave as before: the run is reversed, the
    timeline says what it always said, and no audit row is added for a reason nobody gave."""
    client, db, reversed_entries, timeline, audit = world
    r = _post(client, body)
    assert r.status_code == 200, r.text
    assert next(x for x in db.rows("payroll_runs") if x["id"] == "RUN-1")["status"] == "review"
    descriptions = [a[3] for a, _k in timeline if a[2] == "Payroll Reversed"]
    assert descriptions == ["Payroll for 2026-09 reversed and reopened for correction"]
    assert audit == []
    assert len(reversed_entries) == 1


def test_the_reason_never_goes_into_the_override_reason_column(world):
    """`override_reason` means a release went ahead over gaps (migration 328); a reversal's reason there would
    make the transition log say the opposite of what it means."""
    client, db, _rev, _timeline, _audit = world
    assert _post(client, {"reason": REASON}).status_code == 200
    row = next(t for t in db.rows("payroll_run_transitions") if t["run_id"] == "RUN-1")
    assert row["override_reason"] is None and row["to_status"] == "review"


def test_the_browser_sends_the_reason_it_collected():
    """The other half, from the side that owns the endpoint: the client method posts a body carrying the reason,
    and the Release tab hands it the trimmed text. Both were absent when the reason was thrown away."""
    from pathlib import Path
    web = Path(__file__).resolve().parents[2] / "web"
    api = (web / "lib" / "api" / "index.ts").read_text(encoding="utf-8")
    assert "reverseRun: (runId: string, reason?: string)" in api
    assert "JSON.stringify({ reason: reason.trim() })" in api
    page = (web / "app" / "clients" / "[id]" / "payroll" / "page.tsx").read_text(encoding="utf-8")
    assert "api.payroll.reverseRun(run.id, reason.trim())" in page
    assert "The server records it\n    // on the transition log" not in page, "the false comment is back"
