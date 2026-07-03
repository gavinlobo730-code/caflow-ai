"""
Tier 2 R2.4 — database tenancy backstop regression tests (F1, F4).

core.authz.can_access_client's own regression tests live in
test_authz_engine.py (the F1 fix itself: firm-wide roles are still
firm-BOUND, not "any client anywhere"). This file locks the three concrete
F4-class IDOR bugs found while scoping R2.4: endpoints that looked up a row
by its own id (run_id / client_id / filing_id) without ALSO filtering by the
caller's firm_id, so a user who merely knew or guessed another firm's row id
could read or mutate it regardless of the central authz guard.

Each test seeds one row belonging to firm F1 and proves:
  * a caller from F1 (the owning firm) can still reach it, and
  * a caller from F2 (a different firm) gets 404 — not 500, not silent success.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user
from domain.income_tax import itr_workflow

PARTNER_F1 = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p1@f1.test"}
PARTNER_F2 = {"id": "u2", "firm_id": "F2", "role": "Partner", "email": "p2@f2.test"}


def _client_for(app: FastAPI, user: dict) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── payroll.py: finalize_run / update_run_status ─────────────────────────────

@pytest.fixture
def payroll_app(monkeypatch):
    import routers.payroll as payroll_mod
    db = FakeDB()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    app = FastAPI()
    app.include_router(payroll_mod.router)
    return app, db


def test_update_run_status_cross_firm_is_404(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    r = _client_for(app, PARTNER_F2).patch(f"/api/payroll/runs/{run['id']}/status", json={"status": "review"})
    assert r.status_code == 404
    assert db.rows("payroll_runs")[0]["status"] == "draft"  # untouched


def test_update_run_status_own_firm_succeeds(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    r = _client_for(app, PARTNER_F1).patch(f"/api/payroll/runs/{run['id']}/status", json={"status": "review"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "review"


def test_finalize_run_cross_firm_is_404_before_any_journal_posting(payroll_app, monkeypatch):
    app, db = payroll_app
    posted = []
    monkeypatch.setattr(
        "services.phase2_journal_service.Phase2JournalService.journal_for_payroll",
        lambda self, run, firm_id, client_id: posted.append(run) or "JE-FAKE",
    )
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "draft",
        "total_gross_paise": 100000_00, "month": "2026-06",
    })
    r = _client_for(app, PARTNER_F2).post(f"/api/payroll/runs/{run['id']}/finalize")
    assert r.status_code == 404
    assert not posted, "a cross-firm run must never reach journal posting"
    assert db.rows("payroll_runs")[0]["status"] == "draft"  # untouched


def test_finalize_run_own_firm_succeeds(payroll_app, monkeypatch):
    app, db = payroll_app
    monkeypatch.setattr(
        "services.phase2_journal_service.Phase2JournalService.journal_for_payroll",
        lambda self, run, firm_id, client_id: "JE-FAKE",
    )
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "draft",
        "total_gross_paise": 100000_00, "month": "2026-06",
    })
    r = _client_for(app, PARTNER_F1).post(f"/api/payroll/runs/{run['id']}/finalize")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "finalized"


# ── gst_workspace.py: save_gstr9 / get_gstr9 ──────────────────────────────────

@pytest.fixture
def gst_app(monkeypatch):
    import routers.gst_workspace as gst_mod
    db = FakeDB()
    monkeypatch.setattr(gst_mod, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(gst_mod.router)
    return app, db


def test_get_gstr9_cross_firm_is_hidden(gst_app):
    app, db = gst_app
    db.seed("gstr1_returns", {
        "firm_id": "F1", "client_id": "C1", "financial_year": "2025-26",
        "return_type": "gstr9", "payload_json": {"secret": "F1 annual return"},
    })
    r = _client_for(app, PARTNER_F2).get("/api/gst-workspace/gstr9",
                                          params={"client_id": "C1", "financial_year": "2025-26"})
    assert r.status_code == 200  # endpoint itself always 200s; the DATA must be absent
    assert r.json()["data"] is None


def test_get_gstr9_own_firm_succeeds(gst_app):
    app, db = gst_app
    db.seed("gstr1_returns", {
        "firm_id": "F1", "client_id": "C1", "financial_year": "2025-26",
        "return_type": "gstr9", "payload_json": {"secret": "F1 annual return"},
    })
    r = _client_for(app, PARTNER_F1).get("/api/gst-workspace/gstr9",
                                          params={"client_id": "C1", "financial_year": "2025-26"})
    assert r.json()["data"] is not None
    assert r.json()["data"]["payload_json"]["secret"] == "F1 annual return"


def test_save_gstr9_cannot_overwrite_another_firms_draft(gst_app, monkeypatch):
    app, db = gst_app
    import routers.gst_workspace as gst_mod
    monkeypatch.setattr(gst_mod.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    existing = db.seed("gstr1_returns", {
        "firm_id": "F1", "client_id": "C1", "financial_year": "2025-26",
        "return_type": "gstr9", "payload_json": {"secret": "F1's real draft"},
    })
    r = _client_for(app, PARTNER_F2).post("/api/gst-workspace/gstr9", json={
        "client_id": "C1", "financial_year": "2025-26",
        "payload_json": {"secret": "overwritten by attacker"},
    })
    assert r.status_code == 200  # the endpoint itself always 200s
    # F1's original row must be untouched; the attacker's call created a
    # SEPARATE (harmlessly firm-B-stamped) row instead of overwriting it.
    f1_row = next(row for row in db.rows("gstr1_returns") if row["id"] == existing["id"])
    assert f1_row["payload_json"]["secret"] == "F1's real draft"


# ── domain/income_tax/itr_workflow.py: save_itr_version ───────────────────────
# Tested at the domain-function level (not via routers/itr_workspace.py's
# TestClient) because itr_workflow._supabase() calls a function
# (core.supabase_client.get_supabase_client) that does not exist anywhere in
# this codebase -- a separate, pre-existing production-breaking bug affecting
# 9 files (see docs/audits/2026-07-02-executive-product-audit.md, noted as a
# new finding during this milestone, out of R2.4's scope to fix). Every real
# (non-mock) call into this module is unreachable in production today, so
# monkeypatching _supabase directly is what actually isolates and proves this
# fix's logic.

def test_save_itr_version_rejects_another_firms_filing_id(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(itr_workflow, "_USE_MOCK", False)
    monkeypatch.setattr(itr_workflow, "_supabase", lambda: db)
    db.seed("itr_filings", {"id": "FIL-F1", "firm_id": "F1"})

    with pytest.raises(ValueError, match="Filing not found"):
        itr_workflow.save_itr_version("F2", "FIL-F1", {"schedule": "BS"}, "u2")
    assert db.rows("itr_filing_versions") == []  # nothing was inserted


def test_save_itr_version_own_firm_succeeds(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(itr_workflow, "_USE_MOCK", False)
    monkeypatch.setattr(itr_workflow, "_supabase", lambda: db)
    db.seed("itr_filings", {"id": "FIL-F1", "firm_id": "F1"})

    ver = itr_workflow.save_itr_version("F1", "FIL-F1", {"schedule": "BS"}, "u1")
    assert ver["version"] == 1
    assert ver["itr_filing_id"] == "FIL-F1"
