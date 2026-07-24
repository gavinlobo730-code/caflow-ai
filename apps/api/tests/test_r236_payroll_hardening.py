"""
Task #236 — audit-pass-3 payroll gaps: reopened-run double journal posting,
a dead-end reversal path, HRA/DA/LOP float-arithmetic rounding, an unclamped
lop_factor, and a fail-open payslip-PDF tenant check.

Router-level tests follow the established TestClient pattern from
test_tenancy_backstop.py (payroll_app fixture + FakeDB).
"""
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.payroll as payroll_mod
from tests.e2e_harness import FakeDB
from core.auth import get_current_user

PARTNER_F1 = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p1@f1.test"}
PARTNER_F2 = {"id": "u2", "firm_id": "F2", "role": "Partner", "email": "p2@f2.test"}


def _client_for(app: FastAPI, user: dict) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def payroll_app(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    monkeypatch.setattr(payroll_mod.timeline_service, "log", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(payroll_mod.router)
    return app, db


# ── update_run_status: block reverting a "paid" run, not just "finalized" ──

def test_update_run_status_rejects_reverting_paid_run(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "paid", "month": "2026-06",
    })
    r = _client_for(app, PARTNER_F1).patch(f"/api/payroll/runs/{run['id']}/status", json={"status": "draft"})
    assert r.status_code == 404
    assert db.rows("payroll_runs")[0]["status"] == "paid"  # untouched


def test_update_run_status_still_rejects_reverting_finalized_run(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "finalized", "month": "2026-06",
    })
    r = _client_for(app, PARTNER_F1).patch(f"/api/payroll/runs/{run['id']}/status", json={"status": "draft"})
    assert r.status_code == 404


def test_update_run_status_still_allows_draft_to_review(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "draft", "month": "2026-06",
    })
    r = _client_for(app, PARTNER_F1).patch(f"/api/payroll/runs/{run['id']}/status", json={"status": "review"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "review"


def test_a_paid_run_can_no_longer_be_reopened_and_double_finalized(payroll_app, monkeypatch):
    """End-to-end reproduction of the exact bug: revert -> re-finalize used to
    post a second accrual journal for the same month. The revert step must now
    be rejected outright, so finalize_run is never reached a second time."""
    app, db = payroll_app
    posted = []
    monkeypatch.setattr(
        "services.phase2_journal_service.Phase2JournalService.journal_for_payroll",
        lambda self, run, firm_id, client_id: posted.append(run) or "JE-2",
    )
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "paid", "month": "2026-06",
        "total_gross_paise": 100000_00, "journal_entry_id": "JE-1",
    })
    client = _client_for(app, PARTNER_F1)
    revert = client.patch(f"/api/payroll/runs/{run['id']}/status", json={"status": "review"})
    assert revert.status_code == 404
    refinalize = client.post(f"/api/payroll/runs/{run['id']}/finalize")
    # finalize_run's own status=="finalized" guard doesn't fire since status
    # is still "paid" -- but the run was never reverted to review/draft, so
    # its accrual journal was never re-posted either.
    assert not posted, "no second accrual journal should ever be posted"


# ── reverse_run: the new dedicated reversal path ────────────────────────────

def test_reverse_run_reverses_both_journals_and_resets_state(payroll_app, monkeypatch):
    app, db = payroll_app
    monkeypatch.setattr(
        "services.period_validation_service.period_validation_service.validate_posting_date",
        lambda *a, **k: None,
    )
    reversed_ids = []
    monkeypatch.setattr(
        "services.phase2_journal_service.phase2_journal_service.reverse_entry",
        lambda self_db_or_self, *a, **k: reversed_ids.append(a[1]) or f"REV-{a[1]}",
    )
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "paid", "month": "2026-06",
        "journal_entry_id": "JE-ACCRUAL", "disbursement_journal_entry_id": "JE-DISBURSE",
        "finalized_at": "2026-06-30T00:00:00Z", "paid_at": "2026-07-01T00:00:00Z",
        "paid_from_account_id": "ba-1", "payment_reference": "REF123",
    })
    r = _client_for(app, PARTNER_F1).post(f"/api/payroll/runs/{run['id']}/reverse")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "review"

    # Both journals reversed, disbursement first (it depends on the accrual).
    assert reversed_ids == ["JE-DISBURSE", "JE-ACCRUAL"]

    row = db.rows("payroll_runs")[0]
    assert row["status"] == "review"
    assert row["journal_entry_id"] is None
    assert row["disbursement_journal_entry_id"] is None
    assert row["finalized_at"] is None
    assert row["paid_at"] is None
    assert row["paid_from_account_id"] is None
    assert row["payment_reference"] is None


def test_reverse_run_on_finalized_only_reverses_accrual(payroll_app, monkeypatch):
    app, db = payroll_app
    monkeypatch.setattr(
        "services.period_validation_service.period_validation_service.validate_posting_date",
        lambda *a, **k: None,
    )
    reversed_ids = []
    monkeypatch.setattr(
        "services.phase2_journal_service.phase2_journal_service.reverse_entry",
        lambda self_db_or_self, *a, **k: reversed_ids.append(a[1]) or f"REV-{a[1]}",
    )
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "finalized", "month": "2026-06",
        "journal_entry_id": "JE-ACCRUAL",
    })
    r = _client_for(app, PARTNER_F1).post(f"/api/payroll/runs/{run['id']}/reverse")
    assert r.status_code == 200
    assert reversed_ids == ["JE-ACCRUAL"]


def test_reverse_run_rejects_run_not_yet_finalized(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {"firm_id": "F1", "client_id": "C1", "status": "draft", "month": "2026-06"})
    r = _client_for(app, PARTNER_F1).post(f"/api/payroll/runs/{run['id']}/reverse")
    assert r.status_code == 400


def test_reverse_run_cross_firm_is_404(payroll_app):
    app, db = payroll_app
    run = db.seed("payroll_runs", {
        "firm_id": "F1", "client_id": "C1", "status": "paid", "month": "2026-06",
        "journal_entry_id": "JE-1",
    })
    r = _client_for(app, PARTNER_F2).post(f"/api/payroll/runs/{run['id']}/reverse")
    assert r.status_code == 404
    assert db.rows("payroll_runs")[0]["status"] == "paid"  # untouched


# ── HRA/DA/LOP: integer/Decimal proration, no float ─────────────────────────

def _exact_decimal_slip_expectation(basic_paise: int, present: int, working: int, hra_percent, da_percent):
    basic = (basic_paise * present) // working
    hra = int((Decimal(basic) * Decimal(str(hra_percent)) / 100).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    da = int((Decimal(basic) * Decimal(str(da_percent)) / 100).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return basic, hra, da


def test_hra_da_matches_exact_decimal_not_float():
    """Reproduces the audit's demonstrated mismatch: basic_paise=815000,
    hra_percent=64.1 -- the old float(hra_percent) path could be off by 1
    paise from the mathematically correct Decimal result."""
    emp = {"basic_paise": 815000, "hra_percent": 64.1, "da_percent": 0,
           "pf_applicable": False, "esi_applicable": False, "pt_applicable": False}
    slip = payroll_mod._compute_slip(emp, attendance=None, fy="2025-26", pt_month=6)
    exp_basic, exp_hra, exp_da = _exact_decimal_slip_expectation(815000, 26, 26, 64.1, 0)
    assert slip["basic_paise"] == exp_basic
    assert slip["hra_paise"] == exp_hra


def test_lop_proration_is_exact_integer_division():
    emp = {"basic_paise": 1000000, "hra_percent": 40, "da_percent": 10,
           "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
           "other_allowances_paise": 0,
           "pf_applicable": False, "esi_applicable": False, "pt_applicable": False}
    attendance = {"working_days": 26, "days_present": 20, "lop_days": 6}
    slip = payroll_mod._compute_slip(emp, attendance=attendance, fy="2025-26", pt_month=6)
    exp_basic = (1000000 * 20) // 26
    assert slip["basic_paise"] == exp_basic


# ── lop_factor clamp: negative / over-range lop_days can't inflate pay ──────

def test_negative_lop_days_does_not_inflate_pay_above_full_salary():
    emp = {"basic_paise": 1000000, "hra_percent": 0, "da_percent": 0,
           "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
           "other_allowances_paise": 0,
           "pf_applicable": False, "esi_applicable": False, "pt_applicable": False}
    attendance = {"working_days": 26, "days_present": 30, "lop_days": -5}
    slip = payroll_mod._compute_slip(emp, attendance=attendance, fy="2025-26", pt_month=6)
    # Clamped to lop_days=0 -> full basic, never more than the declared salary.
    assert slip["basic_paise"] == 1000000


def test_lop_days_exceeding_working_days_floors_pay_at_zero_not_negative():
    emp = {"basic_paise": 1000000, "hra_percent": 0, "da_percent": 0,
           "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
           "other_allowances_paise": 0,
           "pf_applicable": False, "esi_applicable": False, "pt_applicable": False}
    attendance = {"working_days": 26, "days_present": 0, "lop_days": 40}
    slip = payroll_mod._compute_slip(emp, attendance=attendance, fy="2025-26", pt_month=6)
    assert slip["basic_paise"] == 0


# ── payslip PDF: fail closed, not fail open ─────────────────────────────────

def test_get_payslip_pdf_denies_when_firm_id_missing(monkeypatch):
    import services.payslip_pdf_service as svc_mod

    class _Res:
        data = {"id": "slip-1", "payroll_employees": {"name": "E"}, "payroll_runs": {"month": "2026-06", "firm_id": "F1"}}

    class _FakeTable:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return _Res()

    class _FakeDB:
        def table(self, name): return _FakeTable()

    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _FakeDB())
    with pytest.raises(PermissionError):
        svc_mod.get_payslip_pdf("slip-1", None)


def test_get_payslip_pdf_denies_cross_firm(monkeypatch):
    import services.payslip_pdf_service as svc_mod

    class _Res:
        data = {"id": "slip-1", "payroll_employees": {"name": "E"}, "payroll_runs": {"month": "2026-06", "firm_id": "F1"}}

    class _FakeTable:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return _Res()

    class _FakeDB:
        def table(self, name): return _FakeTable()

    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _FakeDB())
    with pytest.raises(PermissionError):
        svc_mod.get_payslip_pdf("slip-1", "F2")
