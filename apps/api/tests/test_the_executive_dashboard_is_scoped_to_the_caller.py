"""
The executive dashboard and the copilot's global context answer for the CALLER's
clients (ai-09).

WHAT WAS WRONG
    `get_executive_dashboard` called `find_all(firm_id)` and used `allowed_client_ids`
    only as part of the CACHE KEY, so a scoped Manager or Executive got every other
    client's name back in `churn_signals`, and the whole firm's overdue-task and
    workflow counts — with the cache correctly keeping their answer apart from a
    Partner's, which made it look handled. `_build_context` narrowed the client
    count but read overdue tasks and compliance records for the whole firm.

    tests/test_copilot_intelligence_is_scoped_to_the_caller.py covers the other
    intelligence endpoints and the row filters; not this one.
"""
from __future__ import annotations

import asyncio
import json

import pytest

import domain.ai_copilot_service as mod

FIRM = "f1"
MINE, THEIRS = "c-mine", "c-theirs"
MY_NAME, THEIR_NAME = "MyOwnClientPvtLtd", "ZZSomebodyElsesAtRiskClient"


class _Clients:
    def find_all(self, **kw):
        return [
            {"id": MINE, "client_name": MY_NAME, "health_score": 30, "status": "active"},
            {"id": THEIRS, "client_name": THEIR_NAME, "health_score": 20, "status": "active"},
        ]


class _Tasks:
    def find_overdue(self, **kw):
        return [{"id": "t1", "client_id": MINE}, {"id": "t2", "client_id": THEIRS},
                {"id": "t3", "client_id": THEIRS}]


class _Compliance:
    def find_all(self, **kw):
        return [
            {"client_id": MINE, "status": "Overdue", "due_date": "2026-01-01"},
            {"client_id": THEIRS, "status": "Overdue", "due_date": "2026-01-01"},
            {"client_id": THEIRS, "status": "Overdue", "due_date": "2026-01-01"},
        ]


class _Workflows:
    """Failures and approvals hang off an instance that may have a client."""
    OWNERS = {"i-mine": MINE, "i-theirs": THEIRS}

    def list_failures(self, firm_id, **kw):
        return [{"instance_id": "i-mine"}, {"instance_id": "i-theirs"}, {"instance_id": "i-theirs"}]

    def list_approvals(self, firm_id, **kw):
        return [{"instance_id": "i-theirs"}]

    def list_templates(self, firm_id, **kw):
        return [{"is_active": True}]

    def client_ids_for_instances(self, firm_id, ids):
        return {i: self.OWNERS[i] for i in ids if i in self.OWNERS}


class _Repo:
    def __init__(self):
        self.stored: list[dict] = []

    def get_summary(self, *a, **k):
        return None

    def upsert_summary(self, firm_id, kind, entity, row):
        self.stored.append(row)
        return row

    def list_recommendations(self, *a, **k):
        return []


@pytest.fixture
def world(monkeypatch):
    repo = _Repo()
    svc = mod.ai_copilot_service
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(mod, "_get_task_repo", lambda: _Tasks())
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    monkeypatch.setattr(mod, "_get_workflow_repo", lambda: _Workflows())
    monkeypatch.setattr(svc, "_repo", repo)

    async def _no_model(messages):
        return "summary", 0
    monkeypatch.setattr(svc, "_call_groq", _no_model)
    return svc, repo


def _dashboard(svc, scope):
    return asyncio.run(svc.get_executive_dashboard(FIRM, allowed_client_ids=scope))


# ── the leak ─────────────────────────────────────────────────────────────────

def test_a_scoped_caller_sees_none_of_the_other_clients_names(world):
    svc, repo = world
    out = _dashboard(svc, {MINE})
    blob = json.dumps(out) + json.dumps(repo.stored)
    assert THEIR_NAME not in blob, "an unassigned client's name reached a scoped caller"
    assert MY_NAME in blob, "and the caller's OWN client still shows — it is narrowed, not emptied"


def test_the_cached_summary_a_scoped_answer_leaves_behind_names_no_one_else(world):
    svc, repo = world
    _dashboard(svc, {MINE})
    assert THEIR_NAME not in json.dumps(repo.stored)


def test_the_counts_are_the_callers_own(world):
    svc, _ = world
    out = _dashboard(svc, {MINE})
    assert out["client_risk_insights"]["compliance_failures"] == 1, "one overdue task of theirs, not three"
    assert out["firm_health_summary"]["pending_approvals"] == 0, "the only approval is another client's"
    assert out["firm_health_summary"]["critical_actions"] == 1 + 1, "one critical client + one failure"
    assert out["analysed_client_count"] == 1


def test_a_scoped_answer_says_it_is_scoped(world):
    svc, _ = world
    assert _dashboard(svc, {MINE})["scoped"] is True


def test_an_empty_scope_sees_no_client_at_all(world):
    """An empty set means NO clients, never 'no filter' — the distinction the whole
    shape turns on."""
    svc, _ = world
    out = _dashboard(svc, set())
    assert out["analysed_client_count"] == 0
    assert out["churn_signals"] == []
    assert THEIR_NAME not in json.dumps(out) and MY_NAME not in json.dumps(out)


# ── the negative control: a Partner is not narrowed ──────────────────────────

def test_a_partner_still_sees_the_whole_practice(world):
    svc, _ = world
    out = _dashboard(svc, None)
    names = {c["client_name"] for c in out["churn_signals"]}
    assert names == {MY_NAME, THEIR_NAME}
    assert out["scoped"] is False
    assert out["analysed_client_count"] == 2
    assert out["client_risk_insights"]["compliance_failures"] == 3


# ── the copilot's global context, the second half of the finding ─────────────

def _context(svc, scope):
    return svc._build_context(FIRM, "global", None, scope)


def test_the_global_context_counts_only_the_callers_overdue_work(world):
    svc, _ = world
    scoped = _context(svc, {MINE})
    assert "OVERDUE TASKS: 1" in scoped
    assert "OVERDUE COMPLIANCE FILINGS: 1" in scoped
    assert "TOTAL CLIENTS: 1" in scoped
    # The workflow counts were the same leak in the same function: a scoped
    # caller was told about every client's failures and approvals.
    assert "UNRESOLVED WORKFLOW FAILURES: 1" in scoped
    assert "PENDING APPROVALS: 0" in scoped


def test_the_global_context_for_a_partner_is_unchanged(world):
    svc, _ = world
    full = _context(svc, None)
    assert "OVERDUE TASKS: 3" in full
    assert "OVERDUE COMPLIANCE FILINGS: 3" in full
    assert "UNRESOLVED WORKFLOW FAILURES: 3" in full
    assert "PENDING APPROVALS: 1" in full
    assert "TOTAL CLIENTS: 2" in full
