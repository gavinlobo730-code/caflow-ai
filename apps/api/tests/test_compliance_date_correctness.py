"""
Phase 2 — Compliance & Statutory Date Correctness (backend).

GST, MCA, Income Tax, and the shared compliance-obligation/record engine (the
backend for both the per-client Compliance Calendar and the firm-wide
Compliance Dashboard) all resolve "today" and financial-year defaults via the
shared core.ist_clock helper — not a bare UTC server clock — so an obligation
generated, escalated, or bucketed right at the 31 March / 1 April IST boundary
lands in the correct financial year and status bucket instead of silently
falling into the prior one.

Each test freezes core.ist_clock's notion of "now" (see test_ist_clock.py for
the freeze mechanics — this is the same one-point freeze used there and in
test_ist_date_correctness.py) and drives the real production function or
router end-to-end.
"""
import datetime as _datetime_module
from datetime import datetime, timezone

import pytest

import core.ist_clock as ist_clock
import services.compliance_obligation_service as cos
import domain.compliance_record_service as crs
import domain.income_tax.statutory_rates as statutory_rates
import routers.gst_workspace as gst_workspace
import routers.mca_workspace as mca_workspace
import routers.income_tax as income_tax_router
from repositories.compliance_records_repository import compliance_records_repo

CLIENT = "CLIENT-COMPLIANCE-TEST"


def _freeze_utc(monkeypatch, utc_iso: str) -> datetime:
    """Freeze the shared IST clock to a fixed UTC instant. Patches
    core.ist_clock's own `datetime` symbol, which every caller of
    ist_today()/ist_now() resolves through regardless of where it's
    imported — one freeze point covers GST, MCA, Income Tax, and the
    shared compliance engine."""
    fixed = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _FrozenDateTime)
    return fixed


# ── 1. Shared compliance engine — aggregate_dashboard / calendar / escalate ──
# ── / _current_fy (backs both the Compliance Calendar and Dashboard) ────────

def test_current_fy_resolves_via_ist_across_fy_boundary(monkeypatch):
    # 31 Mar 23:59 UTC == 1 Apr 05:29 IST — a CA in India already sees the new
    # financial year; the bare-UTC bug would resolve FY 2025-26 here instead.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert cos._current_fy() == "2026-27"


def test_current_fy_mid_year_unaffected(monkeypatch):
    _freeze_utc(monkeypatch, "2026-07-05T09:00:00")
    assert cos._current_fy() == "2026-27"


def test_aggregate_dashboard_buckets_use_ist_today(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    records = [
        {"due_date": "2026-03-31", "status": "In Progress"},   # 1 day overdue as of 1 Apr IST
        {"due_date": "2026-04-01", "status": "Not Started"},   # due today (IST)
        {"due_date": "2026-04-05", "status": "Not Started"},   # due this week
        {"due_date": "2026-04-01", "status": "Filed"},         # excluded — not open
    ]
    agg = cos.aggregate_dashboard(records)
    assert agg["summary"]["overdue"] == 1
    assert agg["summary"]["due_this_week"] == 2
    assert agg["summary"]["open_obligations"] == 3


def test_calendar_buckets_use_ist_today(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    firm = "FIRM-CALENDAR-TEST"
    compliance_records_repo.create({"firm_id": firm, "client_id": CLIENT, "compliance_type": "GST",
                                    "obligation_type": "GSTR3B", "due_date": "2026-03-31", "status": "Not Started"})
    compliance_records_repo.create({"firm_id": firm, "client_id": CLIENT, "compliance_type": "MCA",
                                    "obligation_type": "MCA_AOC4", "due_date": "2026-04-10", "status": "Not Started"})
    result = cos.calendar(firm)
    assert [r["due_date"] for r in result["overdue"]] == ["2026-03-31"]
    assert [r["due_date"] for r in result["upcoming"]] == ["2026-04-10"]


def test_escalate_tier_uses_ist_today(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    monkeypatch.setattr("services.timeline_service.timeline_service.log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None)
    firm = "FIRM-ESCALATE-TEST"
    rec = compliance_records_repo.create({"firm_id": firm, "client_id": CLIENT, "compliance_type": "GST",
                                          "obligation_type": "GSTR1", "due_date": "2026-03-31", "status": "Not Started"})
    result = cos.escalate(firm)
    assert result["overdue"] == 1
    updated = compliance_records_repo.find_by_id(rec["id"])
    assert updated["last_escalated_tier"] == "overdue"


# ── 2. compliance_record_service — risk scoring + Filed/Completed dates ─────

def test_compute_risk_score_critical_when_overdue_via_ist(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    record = {"status": "In Progress", "due_date": "2026-03-31", "created_at": "2026-01-01T00:00:00Z"}
    assert crs._compute_risk_score(record) == 90


def test_compute_risk_score_not_yet_critical_when_due_today_via_ist(monkeypatch):
    # Due exactly today (1 Apr IST) is 0 days away — not overdue yet, but
    # inside the <=7-day HIGH-urgency band.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    record = {"status": "In Progress", "due_date": "2026-04-01", "created_at": "2026-01-01T00:00:00Z"}
    assert crs._compute_risk_score(record) == 75


def test_update_record_filed_date_uses_ist(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    firm = "FIRM-UPDATE-RECORD-TEST"
    rec = compliance_records_repo.create({"firm_id": firm, "client_id": CLIENT, "compliance_type": "GST",
                                          "obligation_type": "GSTR1", "due_date": "2026-04-05", "status": "Ready To File"})
    updated = crs.compliance_record_service.update_record(rec["id"], {"status": "Filed"})
    assert updated["filed_date"] == "2026-04-01"


def test_get_firm_summary_due_this_week_uses_ist(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    firm = "FIRM-SUMMARY-TEST"
    compliance_records_repo.create({"firm_id": firm, "client_id": CLIENT, "compliance_type": "GST",
                                    "obligation_type": "GSTR1", "due_date": "2026-04-01", "status": "Not Started"})
    summary = crs.compliance_record_service.get_firm_summary(firm_id=firm)
    assert summary["due_this_week"] == 1


# ── 3. GST module ────────────────────────────────────────────────────────────

def test_gst_dashboard_current_period_uses_ist_today(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    resp = gst_workspace.gst_dashboard(client_id=CLIENT, current_user={"firm_id": "FIRM-GST-TEST"})
    assert resp["success"] is True
    assert resp["data"]["upcoming_due_dates"]["current_period"] == "042026"


# ── 4. MCA module ────────────────────────────────────────────────────────────

def test_mca_calendar_status_uses_ist_today(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    resp = mca_workspace.mca_calendar(client_id=CLIENT, agm_date="2025-09-30",
                                      current_user={"firm_id": "FIRM-MCA-TEST"})
    aoc4 = next(e for e in resp["data"]["calendar"] if e["form_type"] == "AOC-4")
    assert aoc4["status"] == "overdue"   # AGM +30 days = 2025-10-30, long past by 1 Apr 2026


def test_mca_complete_filing_date_default_uses_ist(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    captured = {}

    def _spy(filing_id, body, current_user):
        captured["filing_date"] = body.filing_date
        return {"success": True, "data": {}, "error": None}

    monkeypatch.setattr(mca_workspace, "update_filing_status", _spy)
    body = mca_workspace.UpdateFilingStatusRequest(status="filed", ca_approved=True)
    mca_workspace.complete_filing("FILING-1", body, current_user={"firm_id": "FIRM-MCA-TEST"})
    assert captured["filing_date"] == "2026-04-01"


# ── 5. Income Tax module ─────────────────────────────────────────────────────

def test_income_tax_current_fy_via_ist(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert statutory_rates.current_fy() == "2026-27"


def test_income_tax_rates_for_defaults_to_ist_fy(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    assert statutory_rates.rates_for() is statutory_rates.RATES_BY_FY["2026-27"]


def test_advance_tax_paid_date_accepts_same_day_ist_payment(monkeypatch):
    # 1 Apr IST has already arrived; a payment dated 1 Apr is NOT in the
    # future, even though the server's bare UTC clock still reads 31 Mar.
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    payload = income_tax_router.AdvanceTaxInstallmentInput(
        installment_number=1, paid_amount_paise=100000, paid_date="2026-04-01")
    assert payload.paid_date.isoformat() == "2026-04-01"


def test_advance_tax_paid_date_still_rejects_genuine_future_date(monkeypatch):
    _freeze_utc(monkeypatch, "2026-03-31T23:59:00")
    with pytest.raises(ValueError):
        income_tax_router.AdvanceTaxInstallmentInput(
            installment_number=1, paid_amount_paise=100000, paid_date="2026-04-02")
