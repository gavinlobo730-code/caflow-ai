"""A request is CLAIMED before its action runs, so two decisions cannot both act (ledger POST-A-007).

WHAT WAS WRONG
    `approval_service.approve` read the request, checked it was pending, ran the registered handler (the real mutation: a
    user created, a role changed, an assignment moved) and only then wrote `status = approved`
    unconditionally. Two approvals landing together both passed the check, so the handler ran twice; and a rejection
    could land after an approval whose action had already run and overwrite it. `reject` and `cancel` had the same
    read-then-write gap.

WHAT IS HELD
    * of two simultaneous approvals exactly one runs the handler and the other is refused with 409;
    * a rejection or a cancellation that arrives while the handler is running is refused and cannot overwrite the
      approval (the request already reads `approved` while its action runs);
    * a handler that FAILS puts the request back to pending, with the decider cleared, so it can be approved again,
      and the failure reaches the caller unchanged;
    * the decision on the real table is one `UPDATE ... WHERE status = 'pending'` (`decide_if_pending`), so the claim
      is the database's and not this process's: a request that is no longer pending returns nothing;
    * when the claim comes back empty (somebody decided between the read and the write) approve, reject and cancel each
      answer 409 and the action does not run;
    * the chart-of-accounts request types are retired: they cannot be raised, a stored one cannot be approved (it stays
      pending, and can still be rejected), because their handlers wrote an in-memory chart and reported success.

The first two are driven with real threads against the mock store, whose claim is under a lock standing in for the
statement's atomicity.
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

import repositories.approval_repository as arepo
import services.approval_service as svc
from tests.e2e_harness import FakeDB

FIRM = "F1"
PARTNER = {"id": "p", "firm_id": FIRM, "role": "Partner", "email": "p@f"}
PARTNER_2 = {"id": "p2", "firm_id": FIRM, "role": "Partner", "email": "p2@f"}
EXEC = {"id": "e", "firm_id": FIRM, "role": "Executive", "email": "e@f"}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    arepo._MOCK_REQUESTS.clear()
    monkeypatch.setattr(svc, "log_event", lambda *a, **k: None)
    yield
    arepo._MOCK_REQUESTS.clear()


class _Handler:
    """A registered action that counts its runs and can be held open or made to fail."""

    def __init__(self, fail: Exception | None = None):
        self.runs = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = fail
        self._lock = threading.Lock()

    def __call__(self, firm_id, payload):
        with self._lock:
            self.runs += 1
        self.started.set()
        assert self.release.wait(timeout=10), "the test never released the handler"
        if self.fail:
            raise self.fail
        return {"done": True}


@pytest.fixture()
def handler(monkeypatch):
    h = _Handler()
    monkeypatch.setitem(svc._SPECS, "probe_action", {
        "required": [], "summary": lambda p: "probe", "handler": h})
    return h


def _request() -> str:
    return svc.create_request(FIRM, "probe_action", {}, EXEC)["id"]


def test_two_simultaneous_approvals_run_the_action_once(handler):
    rid = _request()
    handler.release.clear()
    outcomes: list = []

    def go(who):
        try:
            outcomes.append(("ok", svc.approve(FIRM, rid, who)["status"]))
        except HTTPException as exc:
            outcomes.append(("refused", exc.status_code))

    first = threading.Thread(target=go, args=(PARTNER,))
    first.start()
    assert handler.started.wait(timeout=10)       # the first holds the claim and is inside the handler
    second = threading.Thread(target=go, args=(PARTNER_2,))
    second.start()
    second.join(timeout=10)                        # refused without waiting for the first to finish
    handler.release.set()
    first.join(timeout=10)

    assert handler.runs == 1, "the action ran more than once"
    assert sorted(outcomes) == [("ok", "approved"), ("refused", 409)], outcomes
    [row] = arepo._MOCK_REQUESTS
    assert row["status"] == "approved" and row["decided_by"] == "p" and row["result"] == {"done": True}


def test_a_rejection_that_arrives_while_the_action_runs_cannot_overwrite_the_approval(handler):
    rid = _request()
    handler.release.clear()
    t = threading.Thread(target=svc.approve, args=(FIRM, rid, PARTNER))
    t.start()
    assert handler.started.wait(timeout=10)
    with pytest.raises(HTTPException) as e:
        svc.reject(FIRM, rid, PARTNER_2, "changed my mind")
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        svc.cancel(FIRM, rid, PARTNER_2)
    assert e.value.status_code == 409
    handler.release.set()
    t.join(timeout=10)
    assert arepo._MOCK_REQUESTS[0]["status"] == "approved"
    assert arepo._MOCK_REQUESTS[0]["reason"] is None


def test_a_failed_action_puts_the_request_back_and_the_failure_reaches_the_caller(monkeypatch):
    boom = _Handler(fail=HTTPException(400, "Invalid role"))
    monkeypatch.setitem(svc._SPECS, "probe_action", {"required": [], "summary": lambda p: "probe", "handler": boom})
    rid = _request()
    with pytest.raises(HTTPException) as e:
        svc.approve(FIRM, rid, PARTNER)
    assert e.value.status_code == 400 and e.value.detail == "Invalid role"
    [row] = arepo._MOCK_REQUESTS
    assert row["status"] == "pending"
    assert row["decided_by"] is None and row["decided_by_email"] is None and row["decided_at"] is None
    # and it can be decided again
    boom.fail = None
    assert svc.approve(FIRM, rid, PARTNER)["status"] == "approved"
    assert boom.runs == 2


def test_a_request_decided_one_way_cannot_be_decided_another(handler):
    rid = _request()
    svc.reject(FIRM, rid, PARTNER, "no")
    for decide in (lambda: svc.approve(FIRM, rid, PARTNER), lambda: svc.reject(FIRM, rid, PARTNER),
                   lambda: svc.cancel(FIRM, rid, PARTNER)):
        with pytest.raises(HTTPException) as e:
            decide()
        assert e.value.status_code == 409
    assert handler.runs == 0


def test_the_table_decision_is_one_conditional_update(monkeypatch):
    """On the real table the claim is `UPDATE ... WHERE status = 'pending'`: a request no longer pending returns nothing."""
    db = FakeDB()
    db.seed("approval_requests", {"id": "r1", "firm_id": FIRM, "status": "pending"})
    monkeypatch.setattr(arepo, "_USE_MOCK", False)
    monkeypatch.setattr(arepo, "_db", lambda: db)
    repo = arepo.ApprovalRepository()
    first = repo.decide_if_pending(FIRM, "r1", {"status": "approved", "decided_by": "p"})
    second = repo.decide_if_pending(FIRM, "r1", {"status": "rejected", "decided_by": "p2"})
    assert first and first["status"] == "approved"
    assert second is None
    assert db.rows("approval_requests")[0]["status"] == "approved"
    assert db.rows("approval_requests")[0]["decided_by"] == "p"


def test_a_request_of_another_firm_is_never_claimed(monkeypatch):
    db = FakeDB()
    db.seed("approval_requests", {"id": "r1", "firm_id": "F2", "status": "pending"})
    monkeypatch.setattr(arepo, "_USE_MOCK", False)
    monkeypatch.setattr(arepo, "_db", lambda: db)
    assert arepo.ApprovalRepository().decide_if_pending(FIRM, "r1", {"status": "approved"}) is None
    assert db.rows("approval_requests")[0]["status"] == "pending"


def test_a_claim_that_comes_back_empty_refuses_approve_reject_and_cancel(handler, monkeypatch):
    """The three branches the threaded tests do not reach on their own: the read said pending, the write found it
    decided. (Each fails against a service that ignores the claim's answer.)"""
    rid = _request()
    monkeypatch.setattr(arepo.approval_repo, "decide_if_pending", lambda *a, **k: None)
    for decide in (lambda: svc.approve(FIRM, rid, PARTNER), lambda: svc.reject(FIRM, rid, PARTNER, "no"),
                   lambda: svc.cancel(FIRM, rid, PARTNER)):
        with pytest.raises(HTTPException) as e:
            decide()
        assert e.value.status_code == 409 and e.value.detail == "Request already decided"
    assert handler.runs == 0, "the action ran although the decision was not ours"
    assert arepo._MOCK_REQUESTS[0]["status"] == "pending"


def test_the_chart_of_accounts_request_types_are_retired():
    for retired in ("coa_create", "coa_update", "coa_delete"):
        assert retired not in svc.REQUEST_TYPES and retired in svc.RETIRED_TYPES
        with pytest.raises(HTTPException) as e:
            svc.create_request(FIRM, retired, {"account_name": "x", "account_type": "asset", "account_id": "a"}, EXEC)
        assert e.value.status_code == 400


def test_a_stored_request_of_a_retired_type_cannot_be_approved_but_can_be_rejected():
    row = arepo.approval_repo.create({
        "firm_id": FIRM, "request_type": "coa_create", "summary": "Create account x", "payload": {},
        "status": "pending", "requested_by": "e", "requested_by_email": "e@f"})
    with pytest.raises(HTTPException) as e:
        svc.approve(FIRM, row["id"], PARTNER)
    assert e.value.status_code == 409 and "no longer be carried out" in e.value.detail
    assert arepo._MOCK_REQUESTS[0]["status"] == "pending", "a refused approval must not decide the request"
    assert svc.reject(FIRM, row["id"], PARTNER, "retired")["status"] == "rejected"


def test_a_handler_failure_that_is_not_an_exception_class_we_catch_is_not_swallowed(monkeypatch):
    """`except Exception`, not `BaseException`: an interpreter shutdown or a cancellation must not be turned into a
    database write on the way out. The request then stays `approved` with no result, which the record states."""
    class Stop(BaseException):
        pass

    def stop(firm_id, payload):
        raise Stop()

    monkeypatch.setitem(svc._SPECS, "probe_action", {"required": [], "summary": lambda p: "probe", "handler": stop})
    rid = _request()
    with pytest.raises(Stop):
        svc.approve(FIRM, rid, PARTNER)
    assert arepo._MOCK_REQUESTS[0]["status"] == "approved"
