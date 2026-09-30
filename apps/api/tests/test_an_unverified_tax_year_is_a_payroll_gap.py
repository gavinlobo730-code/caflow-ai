"""PAYROLL-09 — the CA is told, on the run itself, when §192 is withheld at rates
nobody has confirmed.

`statutory_rates.verified` was never read by the payroll router or the
declarations module. A run for FY 2026-27 — whose registry entry is last year's
figures carried forward — withheld tax, posted the journal and released with no
sign of it, although §192(1) makes the EMPLOYER liable for a shortfall with
§201(1A) interest on top. The release path already has a gap list that demands a
typed reason; this is the gap that belongs in it, and the next April repeats it.

These tests use the REAL registry (no monkeypatch of the gap), so they break the
day a year is verified and say so — see `test_the_premise_*`.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_mod
from domain.income_tax.statutory_rates import RATES_BY_FY, LATEST_VERIFIED_FY
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-RATES"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1",
          "email": "ca@f.test", "role": "Partner"}
REASON = "Rates for this year checked against the Finance Act by the partner."

UNVERIFIED = sorted(fy for fy, r in RATES_BY_FY.items() if not r.verified)
VERIFIED = LATEST_VERIFIED_FY


def _first_month_of(fy: str) -> str:
    return f"{fy[:4]}-06"


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM})
    d.seed("client_payroll_settings", {"id": "cps-1", "firm_id": FIRM, "client_id": "CLI",
                                        "payroll_enabled": True})
    for name in ("Salaries Expense", "Net Salary Payable", "PF Payable",
                 "ESI Payable", "PT Payable", "TDS Payable - Salary"):
        d.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                     "account_name": name, "is_active": True})
    d.seed("payroll_employees", {
        "id": "e-1", "firm_id": FIRM, "client_id": "CLI", "name": "Asha",
        "basic_paise": 5_000_000, "hra_percent": 0.0, "da_percent": 0.0,
        "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
        "special_allowance_paise": 0, "pf_applicable": False,
        "esi_applicable": False, "pt_applicable": False,
        "is_active": True, "status": "active"})
    return d


def _attend(db, month: str):
    y, m = int(month[:4]), int(month[5:7])
    db.seed("attendance", {"firm_id": FIRM, "employee_id": "e-1", "month": m,
                           "year": y, "working_days": 26, "days_present": 26,
                           "casual_leaves": 0, "sick_leaves": 0,
                           "earned_leaves": 0, "lop_days": 0})


def _draft(db, month: str) -> dict:
    _attend(db, month)
    out = payroll_mod.create_run(
        payroll_mod.PayrollRunIn(client_id="CLI", month=month), CALLER)
    assert out["success"] is True
    return out["data"]


def _rate_gaps(gaps):
    return [g for g in gaps if "§192" in g and "nobody has confirmed" in g]


# ── the premise ──────────────────────────────────────────────────────────────

def test_the_premise_the_registry_holds_an_unverified_year():
    """If no year were unverified, every case below would be vacuous."""
    assert UNVERIFIED, "no unverified year in the registry — these tests prove nothing"
    assert VERIFIED not in UNVERIFIED


# ── the draft says so ────────────────────────────────────────────────────────

def test_a_run_for_an_unverified_year_names_the_year_in_its_statutory_gaps(db):
    fy = UNVERIFIED[0]
    data = _draft(db, _first_month_of(fy))
    gaps = _rate_gaps(data["statutory_gaps"])
    assert len(gaps) == 1, "once per run, not once per employee"
    assert f"FY {fy}" in gaps[0]
    assert "carried forward" in gaps[0]


def test_a_run_for_a_verified_year_says_nothing_about_rates(db):
    data = _draft(db, _first_month_of(VERIFIED))
    assert _rate_gaps(data["statutory_gaps"]) == []


def test_the_gap_is_asked_of_the_payroll_period_not_of_today(db):
    """A March run belongs to the FY that ends in it, and the month before an
    FY begins belongs to the one before — whatever today's date is."""
    fy = UNVERIFIED[0]
    start = int(fy[:4])
    last_month = _draft(db, f"{start + 1}-03")
    assert any(f"FY {fy}" in g for g in _rate_gaps(last_month["statutory_gaps"]))
    month_before = _draft(db, f"{start}-03")
    assert not any(f"FY {fy}" in g for g in _rate_gaps(month_before["statutory_gaps"]))


# ── the release asks for the typed reason ────────────────────────────────────

def test_finalising_a_run_for_an_unverified_year_needs_a_reason(db):
    fy = UNVERIFIED[0]
    run = _draft(db, _first_month_of(fy))
    with pytest.raises(HTTPException) as e:
        payroll_mod.finalize_run(run["id"], CALLER)
    assert e.value.status_code == 409
    assert any(f"FY {fy}" in g and "§192" in g for g in e.value.detail["gaps"])


def test_a_written_reason_releases_it_and_the_gap_is_on_the_log(db):
    fy = UNVERIFIED[0]
    run = _draft(db, _first_month_of(fy))
    out = payroll_mod.finalize_run(run["id"], CALLER,
                                   payroll_mod.ReleaseIn(override_reason=REASON))
    assert out["success"] is True
    [row] = [t for t in db.rows("payroll_run_transitions") if t["run_id"] == run["id"]]
    assert row["override_reason"] == REASON
    assert any(f"FY {fy}" in g for g in row["gaps"])


def test_a_verified_year_finalises_with_no_reason(db):
    run = _draft(db, _first_month_of(VERIFIED))
    out = payroll_mod.finalize_run(run["id"], CALLER)
    assert out["success"] is True
    assert out["data"]["overridden_gaps"] == []


def test_verifying_the_year_clears_the_gap_without_touching_the_run(db, monkeypatch):
    """The gap is RECOMPUTED at the release, never read from the draft — the
    rule `_release_gaps` already states. So the day somebody verifies a year the
    partner is no longer asked, and the draft does not have to be rebuilt."""
    fy = UNVERIFIED[0]
    run = _draft(db, _first_month_of(fy))
    with pytest.raises(HTTPException):
        payroll_mod.finalize_run(run["id"], CALLER)
    monkeypatch.setattr(payroll_mod, "income_tax_rate_gap", lambda _fy: None)
    assert payroll_mod.finalize_run(run["id"], CALLER)["success"] is True


# ── the helper itself ────────────────────────────────────────────────────────

def test_the_sentence_is_the_registrys_own_under_a_prefix_saying_what_rests_on_it():
    from domain.income_tax.statutory_rates import fy_rate_gap
    fy = UNVERIFIED[0]
    [line] = payroll_mod._withholding_rate_gap(fy)
    assert fy_rate_gap(fy) in line
    assert "§192" in line and "nobody has confirmed" in line


def test_a_verified_year_adds_nothing():
    assert payroll_mod._withholding_rate_gap(VERIFIED) == []
