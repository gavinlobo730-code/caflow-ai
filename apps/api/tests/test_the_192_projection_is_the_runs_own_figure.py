"""
GET /api/payroll/tds-projection — §192 for one employee, month by month (PAY-10).

WHAT THIS REPLACES
    `apps/web/lib/services/payrollTdsEstimate.ts`: a slab ladder, a §87A rebate
    and §2(29C) surcharge brackets in the browser, hard-coded to FY 2025-26 and
    deliberately not FY-versioned. It had no old regime, read no declaration,
    and divided the year by twelve — which is the arithmetic §192(3) exists to
    displace.

    The property that matters is not "the endpoint returns a number". It is
    that the number is `_compute_slip`'s — the SAME function the payroll run
    pays from — so what the screen projects for November is what November's
    run deducts.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test"}
FY = "2026-27"
CLIENT = "C1"
EMP = "E1"


@pytest.fixture
def app_db(monkeypatch):
    import routers.payroll as payroll_mod
    db = FakeDB()
    monkeypatch.setattr(payroll_mod, "_db", lambda: db)
    app = FastAPI()
    app.include_router(payroll_mod.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False), db


def _employee(db, **over):
    row = {
        "id": EMP, "firm_id": "F1", "client_id": CLIENT, "status": "active",
        "name": "A Salaried Person",
        "basic_paise": 2_00_000_00, "hra_percent": 0, "da_percent": 0,
        "lta_paise": 0, "medical_paise": 0, "special_allowance_paise": 0,
        "other_allowances_paise": 0,
        "pf_applicable": False, "esi_applicable": False, "pt_applicable": False,
        "joining_date": "2020-04-01",
    }
    row.update(over)
    db.seed("payroll_employees", row)
    return row


def _released_run(db, month, tds_paise, gross_paise=2_00_000_00):
    run = db.seed("payroll_runs", {"firm_id": "F1", "client_id": CLIENT,
                                   "month": month, "status": "finalized"})
    db.seed("payroll_slips", {"run_id": run["id"], "employee_id": EMP,
                              "gross_paise": gross_paise, "tds_paise": tds_paise})
    return run


def _get(client, **over):
    params = {"client_id": CLIENT, "employee_id": EMP, "financial_year": FY}
    params.update(over)
    return client.get("/api/payroll/tds-projection", params=params)


# ── The shape of the answer ──────────────────────────────────────────────────

def test_it_answers_twelve_months_of_the_financial_year_april_to_march(app_db):
    client, db = app_db
    _employee(db)
    d = _get(client).json()["data"]
    assert [m["month"] for m in d["months"]] == [
        "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09",
        "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]


def test_a_month_with_no_released_run_carries_the_projection_and_says_it_is_not_actual(app_db):
    client, db = app_db
    _employee(db)
    d = _get(client).json()["data"]
    assert all(m["actual"] is False for m in d["months"])
    assert d["months_paid"] == 0
    assert d["deducted_so_far_paise"] == 0


def test_a_released_month_carries_what_it_ACTUALLY_deducted(app_db):
    client, db = app_db
    _employee(db)
    _released_run(db, "2026-04", tds_paise=7_777_00)
    d = _get(client).json()["data"]
    april = next(m for m in d["months"] if m["month"] == "2026-04")
    assert april["actual"] is True
    assert april["tds_paise"] == 7_777_00
    assert d["deducted_so_far_paise"] == 7_777_00
    assert d["months_paid"] == 1


def test_a_DRAFT_run_has_deducted_nothing_and_is_not_read_as_actual(app_db):
    """PAY-04, one screen over. A draft run has withheld no tax; showing its
    figure as deducted credits the employee with tax nobody paid over, and
    §192(3) would then spread too little over the months that remain."""
    client, db = app_db
    _employee(db)
    run = db.seed("payroll_runs", {"firm_id": "F1", "client_id": CLIENT,
                                   "month": "2026-04", "status": "draft"})
    db.seed("payroll_slips", {"run_id": run["id"], "employee_id": EMP,
                              "gross_paise": 2_00_000_00, "tds_paise": 9_999_00})
    d = _get(client).json()["data"]
    assert d["deducted_so_far_paise"] == 0
    assert next(m for m in d["months"] if m["month"] == "2026-04")["actual"] is False


def test_another_employees_slip_is_not_counted(app_db):
    client, db = app_db
    _employee(db)
    run = db.seed("payroll_runs", {"firm_id": "F1", "client_id": CLIENT,
                                   "month": "2026-04", "status": "finalized"})
    db.seed("payroll_slips", {"run_id": run["id"], "employee_id": "E2",
                              "gross_paise": 5_00_000_00, "tds_paise": 50_000_00})
    d = _get(client).json()["data"]
    assert d["deducted_so_far_paise"] == 0


def test_a_run_in_a_DIFFERENT_financial_year_is_not_counted(app_db):
    """§192(3) adjusts for deductions "during the financial year" — that one."""
    client, db = app_db
    _employee(db)
    _released_run(db, "2026-03", tds_paise=8_000_00)   # FY 2025-26
    d = _get(client).json()["data"]
    assert d["deducted_so_far_paise"] == 0
    assert d["months_paid"] == 0


# ── The figure itself ────────────────────────────────────────────────────────

def test_the_projected_month_is_exactly_what_compute_slip_would_deduct(app_db):
    """The whole point. Not "a plausible number" — the run's own."""
    import routers.payroll as payroll_mod
    client, db = app_db
    emp = _employee(db)
    d = _get(client).json()["data"]
    expected = payroll_mod._compute_slip(
        emp, None, fy=FY, pt_month=4,
        esi_covered_at_period_start=False, declaration=None,
        tds_already_deducted_paise=0, months_already_paid=0,
        gross_already_paid_paise=0, months_employed_in_fy=12,
        firm_pt_slabs=[], pt_on=date(2026, 4, 30), perquisites_paise=0,
        one_time=None,
    )["tds_paise"]
    assert d["projected_monthly_paise"] == expected
    assert expected > 0, "the fixture must actually attract §192 tax"


def test_the_annual_estimate_is_what_was_withheld_plus_what_the_spread_will_withhold(app_db):
    """NOT twelve times the monthly figure — that double counts the months
    already run, which is what annual-over-twelve in the browser did."""
    client, db = app_db
    _employee(db)
    _released_run(db, "2026-04", tds_paise=5_000_00)
    _released_run(db, "2026-05", tds_paise=5_000_00)
    d = _get(client).json()["data"]
    remaining = sum(1 for m in d["months"] if not m["actual"])
    assert remaining == 10
    assert d["estimated_annual_tds_paise"] == (
        10_000_00 + d["projected_monthly_paise"] * 10)


def test_192_3_spreads_over_the_months_that_REMAIN(app_db):
    """An employee with ten months already withheld has the rest of the year's
    tax spread over two, not twelve. The monthly figure therefore RISES as the
    year runs out, which is exactly what §192(3) does and what annual/12
    could never express."""
    client, db = app_db
    _employee(db)
    early = _get(client).json()["data"]["projected_monthly_paise"]

    for i, mo in enumerate(["2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
                            "2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]):
        _released_run(db, mo, tds_paise=0)
    late = _get(client).json()["data"]["projected_monthly_paise"]
    assert late > early


def test_the_ytd_figures_reach_the_engine_EXACTLY_as_the_run_passes_them(app_db):
    """§192(3) needs three facts about the year so far, and this pins all
    three at once against `_compute_slip` called with them by hand.

    MISSED ON THE FIRST PASS. `test_192_3_spreads_over_the_months_that_REMAIN`
    below asserts the monthly figure RISES as the year runs out, and it does —
    but zeroing `months_already_paid` also lengthens `months_left`, which
    inflates `annual_gross`, which raises the tax too. So the test passed on a
    mutation that had thrown the whole §192(3) adjustment away. It stays,
    because the rising figure is the property a CA sees; this one isolates the
    arithmetic behind it.
    """
    import routers.payroll as payroll_mod
    client, db = app_db
    emp = _employee(db)
    for mo in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]:
        _released_run(db, mo, tds_paise=3_000_00)

    d = _get(client).json()["data"]
    assert d["months_paid"] == 6
    assert d["deducted_so_far_paise"] == 18_000_00

    expected = payroll_mod._compute_slip(
        emp, None, fy=FY, pt_month=10,
        esi_covered_at_period_start=False, declaration=None,
        tds_already_deducted_paise=18_000_00,
        months_already_paid=6,
        gross_already_paid_paise=6 * 2_00_000_00,
        months_employed_in_fy=12,
        firm_pt_slabs=[], pt_on=date(2026, 10, 31), perquisites_paise=0,
        one_time=None,
    )["tds_paise"]
    assert d["projected_monthly_paise"] == expected


def test_a_year_fully_run_projects_nothing_and_says_why(app_db):
    client, db = app_db
    _employee(db)
    for y, m in [(2026, x) for x in range(4, 13)] + [(2027, x) for x in range(1, 4)]:
        _released_run(db, f"{y:04d}-{m:02d}", tds_paise=1_000_00)
    d = _get(client).json()["data"]
    assert d["projected_monthly_paise"] == 0
    assert d["estimated_annual_tds_paise"] == 12_000_00
    assert any("nothing left to project" in g for g in d["gaps"])


# ── What a projection cannot see, and says ───────────────────────────────────

def test_it_names_what_a_projection_cannot_see(app_db):
    client, db = app_db
    _employee(db)
    d = _get(client).json()["data"]
    joined = " ".join(d["gaps"])
    assert "full month's attendance" in joined
    assert "§192(3)" in joined


def test_no_submitted_declaration_is_NAMED_rather_than_read_as_none_needed(app_db):
    """§115BAC(1A)'s default is what is withheld, and that is a fact about the
    figure the CA is looking at — not a silent assumption."""
    client, db = app_db
    _employee(db)
    d = _get(client).json()["data"]
    assert any("§115BAC(1A) default" in g for g in d["gaps"])


def test_a_submitted_declaration_reaches_the_projection_and_lowers_the_tax(app_db):
    """The browser copy read no declaration at all, so an employee who had
    declared a deduction was shown the undeclared figure all year.

    §80CCD(2) is the head used here deliberately: payroll withholds on the
    §115BAC(1A) default, and §115BAC(2) allows §80CCD(2) and nothing else from
    Chapter VI-A — so it is the one deduction that can move this figure
    without the employee also switching regime."""
    client, db = app_db
    _employee(db)
    before = _get(client).json()["data"]["projected_monthly_paise"]
    assert before > 0, "the fixture must attract tax for this to mean anything"

    head = db.seed("payroll_it_declarations", {
        "firm_id": "F1", "client_id": CLIENT, "employee_id": EMP, "fy": FY,
        "regime": "new", "status": "submitted"})
    db.seed("payroll_it_declaration_items", {
        "declaration_id": head["id"], "section": "80CCD(2)",
        "amount_declared_paise": 2_40_000_00, "status": "declared"})
    after = _get(client).json()["data"]["projected_monthly_paise"]
    assert after < before, "the declaration did not reach the §192 computation"


def test_a_DRAFT_declaration_is_the_employee_still_typing_and_does_not_move_the_figure(app_db):
    client, db = app_db
    _employee(db)
    before = _get(client).json()["data"]["projected_monthly_paise"]
    head = db.seed("payroll_it_declarations", {
        "firm_id": "F1", "client_id": CLIENT, "employee_id": EMP, "fy": FY,
        "regime": "new", "status": "draft"})
    db.seed("payroll_it_declaration_items", {
        "declaration_id": head["id"], "section": "80CCD(2)",
        "amount_declared_paise": 2_40_000_00, "status": "declared"})
    assert _get(client).json()["data"]["projected_monthly_paise"] == before


# ── Scope and refusals ───────────────────────────────────────────────────────

def test_an_employee_of_another_firm_is_not_found(app_db):
    client, db = app_db
    db.seed("payroll_employees", {"id": EMP, "firm_id": "F2", "client_id": CLIENT,
                                  "status": "active", "basic_paise": 1_00_000_00})
    body = _get(client).json()
    assert body["success"] is False
    assert body["error"] == "Employee not found"


def test_a_malformed_financial_year_is_refused_by_the_type(app_db):
    """FYLabel in Annotated position, not in the default — CLAUDE.md records
    that `fy: FYLabel = Query(...)` validates nothing at all."""
    client, db = app_db
    _employee(db)
    assert _get(client, financial_year="2026-28").status_code == 422
    assert _get(client, financial_year="nonsense").status_code == 422


def test_the_gross_the_projection_rests_on_is_served_too(app_db):
    """The screen showed an "Est. Annual Gross" of its own — the last slip's
    gross times twelve, which is wrong for a mid-year joiner and for anyone
    whose pay was revised."""
    client, db = app_db
    _employee(db)
    d = _get(client).json()["data"]
    assert d["projected_monthly_gross_paise"] == 2_00_000_00
    assert d["estimated_annual_gross_paise"] == 24_00_000_00


def test_a_mid_year_joiner_is_projected_over_the_months_they_are_employed(app_db):
    """"estimated income ... for that financial year" is as long as the
    employment. A twelve-month figure on a six-month employee taxes income
    they will never receive — and the browser copy multiplied the last slip's
    gross by twelve unconditionally."""
    import routers.payroll as payroll_mod
    client, db = app_db
    _employee(db, joining_date="2026-10-01")
    joiner = _get(client).json()["data"]["projected_monthly_paise"]

    db.rows("payroll_employees").clear()
    _employee(db)
    all_year = _get(client).json()["data"]["projected_monthly_paise"]

    assert payroll_mod._months_employed_in_fy("2026-10-01", FY) == 6
    assert joiner < all_year, (
        "a six-month employee on the same salary must be projected less tax "
        "than one employed the whole year")


def test_the_browser_estimator_module_is_gone(app_db):
    """The deletion is pinned from the frontend too
    (scripts/tds-is-computed-by-the-engine-not-the-browser.test.ts); this is
    the half that fails in the Python suite, which is the required check."""
    import pathlib
    web = pathlib.Path(__file__).resolve().parents[2] / "web"
    assert not (web / "lib/services/payrollTdsEstimate.ts").exists()
