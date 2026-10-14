"""Two more doors that read payroll under the caller's own sign-in, held to the same rule (migration 485).

Migration 485 shows payroll rows to a person only when they hold `payroll:read`, and shows everyone else NOTHING and no
error. A door that reads payroll for such a person must refuse or say it could not look; it must never report an
empty answer as a true one.

  * THE FILING WALK-THROUGHS. `/api/filing-demo/capabilities` offers a flow and `/preview` builds it only for a person
    who may read the flow's module, judged by `can_user` (the per-person grid) and not by the role alone: a Manager a
    Partner has blocked from payroll is refused the PF and ESI walk-throughs in the same words as an Executive, instead
    of meeting "run not found".
  * THE BANK-ACCOUNT DELETE CHECK. It asks whether a payroll run was paid from the account. Read through the caller's
    sign-in, an Executive would get an empty answer and the account would be offered for deletion although it paid
    payroll. The one fact is read through the service client, scoped to the firm.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import routers.banking as rb
import routers.filing_demo as rfd
from core.auth import get_current_user
from main import app
from services import filing_demo
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"
client = TestClient(app)


def _as(role: str, overrides=None):
    app.dependency_overrides[get_current_user] = lambda: {
        "id": f"{role}-1", "role": role, "firm_id": FIRM, "permission_overrides": overrides or {}}


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def flows(monkeypatch):
    """The payroll walk-throughs replaced by a recorder: what is under test is who is let in, not the script."""
    built: list[str] = []
    for name in ("pf", "esi"):
        monkeypatch.setitem(filing_demo.FLOWS, name,
                            (lambda *a, _n=name, **k: built.append(_n) or {"stages": [], "flow": _n}, "payroll"))
    monkeypatch.setattr(rfd, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    return built


def _preview(flow: str):
    return client.post(f"/api/filing-demo/{flow}/preview", json={"client_id": CLIENT, "ref": {"run_id": "R1"}}).json()


def test_a_manager_is_offered_and_built_the_payroll_walk_throughs(flows):
    _as("Manager")
    assert {"pf", "esi"} <= set(client.get("/api/filing-demo/capabilities").json()["data"]["flows"])
    assert _preview("pf")["success"] is True and flows == ["pf"]


def test_an_executive_is_neither_offered_nor_built_them(flows):
    _as("Executive")
    assert not {"pf", "esi"} & set(client.get("/api/filing-demo/capabilities").json()["data"]["flows"])
    body = _preview("pf")
    assert body["success"] is False and "do not have access" in body["error"] and flows == []


def test_the_per_person_grid_decides_not_the_role_alone(flows):
    """A Manager blocked from payroll:read is refused; an Executive granted it is let in (can_user, not can)."""
    _as("Manager", {"payroll:read": False})
    assert "pf" not in client.get("/api/filing-demo/capabilities").json()["data"]["flows"]
    assert _preview("esi")["success"] is False and flows == []
    _as("Executive", {"payroll:read": True})
    assert "pf" in client.get("/api/filing-demo/capabilities").json()["data"]["flows"]
    assert _preview("pf")["success"] is True and flows == ["pf"]


# ── the bank-account delete check ────────────────────────────────────────────

def _bank_db() -> FakeDB:
    """What the CALLER's sign-in sees: the bank account, and no payroll rows (row security filtered them)."""
    db = FakeDB()
    db.seed("bank_accounts", {"id": "A1", "firm_id": FIRM, "client_id": CLIENT, "coa_account_id": None})
    return db


def _service_db_with_a_run() -> FakeDB:
    db = FakeDB()
    db.seed("payroll_runs", {"id": "PR1", "firm_id": FIRM, "client_id": CLIENT, "paid_from_account_id": "A1"})
    db.seed("payroll_runs", {"id": "PR2", "firm_id": "FIRM-B", "client_id": "X", "paid_from_account_id": "A1"})
    return db


def test_an_account_that_paid_payroll_is_blocked_even_when_the_caller_cannot_see_the_run(monkeypatch):
    monkeypatch.setattr(rb, "_service_db", lambda: _service_db_with_a_run())
    blockers, _latest = rb._delete_blockers(_bank_db(), FIRM, CLIENT, [{"id": "A1", "coa_account_id": None}])
    assert any("payroll" in reason for reason in blockers["A1"]), blockers


def test_the_negative_control_the_callers_own_sign_in_alone_says_deletable(monkeypatch):
    """Without the service read the probe sees nothing and the account is offered for deletion: the defect."""
    monkeypatch.setattr(rb, "_service_db", lambda: None)
    blockers, _latest = rb._delete_blockers(_bank_db(), FIRM, CLIENT, [{"id": "A1", "coa_account_id": None}])
    assert blockers["A1"] == []


def test_another_firms_run_is_not_a_blocker(monkeypatch):
    other = FakeDB()
    other.seed("payroll_runs", {"id": "PR9", "firm_id": "FIRM-B", "client_id": "X", "paid_from_account_id": "A1"})
    monkeypatch.setattr(rb, "_service_db", lambda: other)
    blockers, _latest = rb._delete_blockers(_bank_db(), FIRM, CLIENT, [{"id": "A1", "coa_account_id": None}])
    assert not any("payroll" in reason for reason in blockers["A1"]), blockers
