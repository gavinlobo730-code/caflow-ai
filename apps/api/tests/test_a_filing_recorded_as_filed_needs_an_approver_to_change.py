"""An MCA filing recorded as filed changes only in the hands of someone who may approve MCA filings (POST-A-225).

WHAT WAS WRONG
    The MCA screen wrote `status: "filed"`, the SRN and a date straight into `mca_filings` in three places (create,
    mark one, mark a batch), past the route that asks `mca:approve` (Manager and above) and the CA's explicit
    confirmation; the create path supplied TODAY as the date it was filed. The route itself asked the ROLE and not the
    PERSON (`can(role, ...)`, so a Partner's grid decision was ignored), asked nobody about REOPENING or rewriting a
    filing already recorded as filed, and read a zero-row UPDATE as success. Migration 493 asks the database the same
    question with the same pair; this module holds the route's side, so it answers in words first.

WHAT THIS ASSERTS
    * an Executive can not record a filing as filed (the route's own rule, now per person), and a Manager can;
    * an Executive can not reopen or rewrite a filing that is recorded as filed, whatever status they send, and the row is
      exactly as it was; a Manager can;
    * the grid counts both ways: an Executive it GRANTS `mca:approve` may mark filed, a Manager it DENIES may not;
    * a refused UPDATE (zero rows) is not read as success;
    * an Executive still progresses an unfiled filing (in progress, back to not started).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.mca_workspace as mw
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
FILING = "filing-1"


def _user(role, uid, **extra):
    return {"id": uid, "firm_id": FIRM, "auth_user_id": f"auth-{uid}", "email": f"{uid}@f.test", "role": role, **extra}


EXEC = _user("Executive", "exec")
MANAGER = _user("Manager", "mgr")


@pytest.fixture
def world(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(mw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [mw])
    d.seed("mca_filings", {
        "id": FILING, "firm_id": FIRM, "client_id": CLIENT, "form_type": "AOC-4", "status": "not_started",
        "srn": None, "filed_date": None, "due_date": "2026-10-30"})
    return d


def _row(db):
    return [r for r in db.rows("mca_filings") if r["id"] == FILING][0]


def _status(user, status, **kw):
    return mw.update_filing_status(
        FILING, mw.UpdateFilingStatusRequest(status=status, ca_approved=True, **kw), current_user=user)


def _a_filed_filing(world):
    out = _status(MANAGER, "filed", srn="SRN123456", filing_date="2026-10-20")
    assert out["success"] is True, out
    assert _row(world)["status"] == "filed" and _row(world)["srn"] == "SRN123456", "premise: a Manager recorded it"


def test_an_executive_cannot_record_a_filing_as_filed(world):
    with pytest.raises(HTTPException) as e:
        _status(EXEC, "filed", srn="SRN1", filing_date="2026-10-20")
    assert e.value.status_code == 403
    assert _row(world)["status"] == "not_started" and _row(world)["srn"] is None


def test_a_manager_records_a_filing_as_filed(world):
    _a_filed_filing(world)
    assert _row(world)["filed_date"] == "2026-10-20"


def test_an_executive_cannot_reopen_or_rewrite_a_filed_filing(world):
    _a_filed_filing(world)
    before = dict(_row(world))
    for target in ("not_started", "in_progress", "overdue"):
        out = _status(EXEC, target, srn="SRN-ALTERED")
        assert out["success"] is False and "may approve MCA filings" in out["error"], target
    assert _row(world) == before


def test_a_manager_can_reopen_a_filed_filing(world):
    _a_filed_filing(world)
    assert _status(MANAGER, "in_progress")["success"] is True
    assert _row(world)["status"] == "in_progress"


def test_an_executive_still_progresses_an_unfiled_filing(world):
    assert _status(EXEC, "in_progress")["success"] is True
    assert _row(world)["status"] == "in_progress"
    assert _status(EXEC, "not_started")["success"] is True


def test_the_grid_decides_per_person_in_both_directions(world):
    granted = _user("Executive", "exec2", permission_overrides={"mca:approve": True})
    assert _status(granted, "filed", srn="SRN9", filing_date="2026-10-21")["success"] is True
    assert _row(world)["status"] == "filed"

    denied = _user("Manager", "mgr2", permission_overrides={"mca:approve": False})
    with pytest.raises(HTTPException) as e:
        _status(denied, "filed", srn="SRN10", filing_date="2026-10-22")
    assert e.value.status_code == 403
    out = _status(denied, "in_progress")          # a filed filing is the approver's to reopen
    assert out["success"] is False and _row(world)["status"] == "filed"


def test_a_refused_update_is_not_read_as_success(world, monkeypatch):
    real = world.table

    class _NoRows:
        def __init__(self, inner): self._inner = inner
        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name != "update":
                return attr
            def _update(*a, **k):
                class _Empty:
                    def eq(self, *x, **y): return self
                    def execute(self_inner):
                        class _R: data = []
                        return _R()
                return _Empty()
            return _update

    monkeypatch.setattr(world, "table", lambda name: _NoRows(real(name)) if name == "mca_filings" else real(name))

    out = _status(MANAGER, "filed", srn="SRN1", filing_date="2026-10-20")

    assert out["success"] is False and "not changed" in out["error"]
