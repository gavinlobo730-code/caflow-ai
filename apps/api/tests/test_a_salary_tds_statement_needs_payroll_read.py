"""A salary-TDS statement is built from payroll, so it needs `payroll:read` (migration 485, POST-B-004).

THE FAULT THIS ANSWERS
    Form 24Q lists every employee with their PAN, the salary paid and the tax withheld, built from the payroll
    runs. `POST /api/tds/24q/from-books` took `tds:compute` (Executive and above) and read those runs with the
    CALLER's own sign-in. Migration 485 makes the database show payroll rows only to a person who holds
    `payroll:read` (Manager and above, or a per-person grant), so an Executive who may compute TDS but not read
    payroll would not have been refused: they would have been handed a statement built from NO rows, with the
    reconciliation line saying no tax had been withheld. An empty answer worded as a true one. The route now needs
    both permissions, and the 24Q filing walk-through, which can compute the same figures when a saved return has
    none, is told whether the caller may read payroll and says so instead of showing an empty quarter.

WHAT IS ASSERTED
    * an Executive is refused (403, naming payroll) and the build is never started;
    * a Manager is let through and the build runs;
    * the permission is the PER-PERSON one: an Executive granted `payroll:read` is let through, a Manager refused
      it is not (the grid the database also asks);
    * the 24Q walk-through for a caller who may not read payroll does not run the from-books fallback and says
      why; the same walk-through for a caller who may does run it (the negative control); a 26Q walk-through
      does not care, because 26Q is built from purchase bills.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import routers.tds as rt
from core.auth import get_current_user
from main import app
from services import tds_return_service
from services.filing_demo import tds_return
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI"
BODY = {"client_id": CLIENT, "financial_year": "2025-26", "quarter": "Q2"}


@pytest.fixture
def built(monkeypatch):
    """The 24Q build replaced by a recorder, and everything the route does before it by a stand-in: what is under
    test is the permission the route asks, not the engine."""
    calls: list[tuple] = []
    monkeypatch.setattr(tds_return_service, "tds_24q_from_books",
                        lambda *a, **k: calls.append(a) or {"total_tds_deducted_paise": 123})
    monkeypatch.setattr(rt, "_deductor_for",
                        lambda *a, **k: SimpleNamespace(tan="T", name="N", pan="P", address="A"))
    monkeypatch.setattr(rt, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    return calls


def _as(role: str, overrides=None):
    app.dependency_overrides[get_current_user] = lambda: {
        "id": f"{role}-1", "role": role, "firm_id": FIRM, "permission_overrides": overrides or {}}


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.pop(get_current_user, None)


client = TestClient(app)


def test_an_executive_is_refused_and_the_build_never_starts(built):
    _as("Executive")
    r = client.post("/api/tds/24q/from-books", json=BODY)
    assert r.status_code == 403 and "payroll" in r.json()["detail"]
    assert built == []


def test_a_manager_is_let_through_and_the_build_runs(built):
    _as("Manager")
    r = client.post("/api/tds/24q/from-books", json=BODY)
    assert r.status_code == 200 and r.json()["data"]["total_tds_deducted_paise"] == 123
    assert len(built) == 1


def test_the_permission_is_the_per_person_one(built):
    _as("Executive", {"payroll:read": True})
    assert client.post("/api/tds/24q/from-books", json=BODY).status_code == 200
    _as("Manager", {"payroll:read": False})
    assert client.post("/api/tds/24q/from-books", json=BODY).status_code == 403
    assert len(built) == 1


# ── the walk-through ─────────────────────────────────────────────────────────

def _db(form: str) -> FakeDB:
    db = FakeDB()
    db.seed("tds_returns", {
        "id": "T1", "firm_id": FIRM, "client_id": CLIENT, "return_type": form,
        "financial_year": "2025-26", "quarter": "Q2", "status": "ca_approved",
        "total_deductions_paise": 0, "total_deposits_paise": 0, "deductee_count": 0})
    return db


def _summary_note(out: dict) -> str:
    return next(s for s in out["stages"] if s["kind"] == "summary")["note"]


@pytest.fixture
def fallback(monkeypatch):
    calls: list[str] = []

    def _books(name):
        def _f(*a, **k):
            calls.append(name)
            return {"total_tds_deducted_paise": 7_00_000, "total_tds_deposited_paise": 7_00_000,
                    "deductee_count": 3}
        return _f

    monkeypatch.setattr(tds_return_service, "tds_24q_from_books", _books("24Q"))
    monkeypatch.setattr(tds_return_service, "tds_26q_from_books", _books("26Q"))
    return calls


def test_a_24q_walk_through_without_payroll_access_does_not_compute_and_says_so(fallback):
    out = tds_return.build(_db("24Q"), FIRM, CLIENT, {"return_id": "T1"}, payroll_readable=False)
    assert fallback == []
    note = _summary_note(out)
    assert "needs access to payroll" in note and "not computed" in note
    assert "zeros are real" not in note, "an unknown must not be worded as a true nil"
    figures = {f["label"]: f for f in next(s for s in out["stages"] if s["kind"] == "summary")["figures"]}
    for label in ("TDS deducted", "TDS deposited", "Deductees"):
        assert figures[label] == {"label": label, "text": "Not computed"}, (
            f"{label} is shown as a value although nobody computed it: {figures[label]}")


def test_the_same_walk_through_with_payroll_access_computes_the_quarter(fallback):
    """The negative control: the refusal above is the access, not an accident of the fixture."""
    out = tds_return.build(_db("24Q"), FIRM, CLIENT, {"return_id": "T1"}, payroll_readable=True)
    assert fallback == ["24Q"]
    assert "computed from the posted books" in _summary_note(out)


def test_a_26q_walk_through_does_not_care(fallback):
    tds_return.build(_db("26Q"), FIRM, CLIENT, {"return_id": "T1"}, payroll_readable=False)
    assert fallback == ["26Q"]
