"""GET /api/payroll/runs/{id}/handoff — the month, assembled once.

The companion to test_the_handoff_says_what_goes_in_which_box.py, which tests
the pure assembly. This drives the real endpoint against a FakeDB, because three
things can only go wrong here: the professional tax must be summed PER STATE off
the slips (the run header holds one number for the month, and one number cannot
be paid to two authorities), a draft run must be refused, and the response must
never carry a field a CA could type a secret into.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as pay
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
          "email": "ca@f.test", "role": "Partner"}
MONTH = "2026-09"


def _slip(emp_id, **over):
    row = {
        "run_id": "RUN-1", "employee_id": emp_id, "gross_paise": 5_00_000,
        "net_paise": 4_40_000, "pf_employee_paise": 18_000,
        "pf_employer_paise": 18_000, "pf_employer_eps_paise": 12_500,
        "pf_employer_epf_paise": 5_500, "pf_wages_paise": 15_00_00,
        "esi_employee_paise": 0, "esi_employer_paise": 0,
        "pt_paise": 20_000, "tds_paise": 0, "lop_days": 0,
        "paid_days": 30, "esi_wages_paise": 0,
    }
    row.update(over)
    return row


def _setup(monkeypatch, *, status="finalized", employees=None, slips=None,
           registrations=None):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pay])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme"})
    db.seed("payroll_runs", {
        "id": "RUN-1", "firm_id": FIRM, "client_id": "CLI", "month": MONTH,
        "status": status, "total_edli_paise": 9_000,
        "total_pf_admin_paise": 50_000, "headcount": 2})
    for emp in (employees if employees is not None else [
            {"id": "E1", "name": "Asha", "uan": "100000000001",
             "pf_applicable": True, "eps_eligible": True, "esi_number": None,
             "esi_applicable": False, "pt_applicable": True,
             "pt_state": "Maharashtra"},
            {"id": "E2", "name": "Bimal", "uan": "100000000002",
             "pf_applicable": True, "eps_eligible": True, "esi_number": None,
             "esi_applicable": False, "pt_applicable": True,
             "pt_state": "Karnataka"}]):
        db.seed("payroll_employees", {"firm_id": FIRM, "client_id": "CLI", **emp})
    for s in (slips if slips is not None
              else [_slip("E1"), _slip("E2", pt_paise=15_000)]):
        db.seed("payroll_slips", s)
    db.seed("client_statutory_identity", {
        "firm_id": FIRM, "client_id": "CLI", "tan": "MUMF12345G",
        "epf_establishment_code": "MHBAN0012345000",
        "esic_employer_code": "31000123450001099"})
    for reg in (registrations if registrations is not None
                else [{"state": "MAHARASHTRA", "ptrc_number": "27999999999P"}]):
        db.seed("client_pt_registrations",
                {"firm_id": FIRM, "client_id": "CLI", **reg})
    return db


def _handoff(monkeypatch, **over):
    _setup(monkeypatch, **over)
    res = pay.run_handoff("RUN-1", CALLER)
    assert res["success"] is True, res
    return res["data"]


def _by_key(data):
    return {o["key"]: o for o in data["obligations"]}


# ── the obligations a month raises ───────────────────────────────────────────

def test_a_month_raises_epf_esic_and_one_panel_per_pt_state(monkeypatch):
    data = _handoff(monkeypatch)
    assert [o["key"] for o in data["obligations"]] == [
        "epf", "esic", "professional_tax:KARNATAKA",
        "professional_tax:MAHARASHTRA"]


def test_professional_tax_is_summed_per_state_off_the_slips(monkeypatch):
    """payroll_runs.total_pt_paise is ONE number for the month. A client with
    staff in two states owes two authorities on two due dates against two
    certificates — so the figure has to come from the slips, joined to the
    employee's own pt_state."""
    panels = _by_key(_handoff(monkeypatch))
    mh = panels["professional_tax:MAHARASHTRA"]["confirm"]
    ka = panels["professional_tax:KARNATAKA"]["confirm"]
    assert [f["amount_paise"] for f in mh if f["label"].startswith("Profess")] == [20_000]
    assert [f["amount_paise"] for f in ka if f["label"].startswith("Profess")] == [15_000]
    assert [f["count"] for f in mh if f["label"] == "Employees"] == [1]


def test_a_state_nobody_was_taxed_in_raises_no_panel(monkeypatch):
    data = _handoff(monkeypatch, slips=[_slip("E1"), _slip("E2", pt_paise=0)])
    assert "professional_tax:KARNATAKA" not in _by_key(data)
    assert "professional_tax:MAHARASHTRA" in _by_key(data)


def test_a_deduction_with_no_state_is_reported_and_not_dropped(monkeypatch):
    """_compute_pt cannot withhold without a state, so this should be
    unreachable — which is exactly why it is reported rather than summed into
    nothing. Money withheld from an employee that no authority will be paid is
    not a rounding difference."""
    data = _handoff(monkeypatch, employees=[
        {"id": "E1", "name": "Asha", "uan": "100000000001",
         "pf_applicable": True, "eps_eligible": True, "esi_number": None,
         "esi_applicable": False, "pt_applicable": True, "pt_state": None}],
        slips=[_slip("E1")])
    assert data["unattributed_pt_paise"] == 20_000
    assert not [o for o in data["obligations"]
                if o["scheme"] == "professional_tax"]


def test_the_ptrc_reaches_the_state_panel(monkeypatch):
    panels = _by_key(_handoff(monkeypatch))
    mh = panels["professional_tax:MAHARASHTRA"]
    ka = panels["professional_tax:KARNATAKA"]
    assert mh["identity"][0]["value"] == "27999999999P"
    assert ka["identity"][0]["value"] is None
    assert ka["blocking"], "a state with no PTRC cannot be deposited to"


def test_the_establishment_and_employer_codes_reach_their_panels(monkeypatch):
    panels = _by_key(_handoff(monkeypatch))
    assert panels["epf"]["identity"][0]["value"] == "MHBAN0012345000"
    assert panels["esic"]["identity"][0]["value"] == "31000123450001099"


def test_edli_and_admin_come_off_the_run_not_the_file(monkeypatch):
    """The ECR carries neither: the portal raises them on the challan. They are
    on payroll_runs because migration 329 put them there when they finally
    reached the ledger."""
    epf = _by_key(_handoff(monkeypatch))["epf"]
    figures = {f["label"]: f for f in epf["confirm"]}
    assert figures["EDLI (A/c 21)"]["amount_paise"] == 9_000
    assert figures["Administrative charges (A/c 2)"]["amount_paise"] == 50_000


# ── what it refuses ──────────────────────────────────────────────────────────

def test_a_draft_run_is_refused_with_the_reason(monkeypatch):
    """The returns report contributions actually made, and a draft run's
    figures can still change."""
    _setup(monkeypatch, status="draft")
    with pytest.raises(HTTPException) as e:
        pay.run_handoff("RUN-1", CALLER)
    assert e.value.status_code == 409
    assert "not finalised" in e.value.detail
    assert "statutory return" in e.value.detail


def test_a_run_of_another_firm_is_not_found(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        pay.run_handoff("RUN-1", {**CALLER, "firm_id": "FIRM-B"})
    assert e.value.status_code == 404


def test_mock_mode_answers_the_shape_rather_than_failing(monkeypatch):
    """No SUPABASE_URL means no database, which is how local dev and the demo
    deployment run. The screen must render an honest empty month rather than a
    500 — see routers/payroll._db."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    data = pay.run_handoff("RUN-1", CALLER)["data"]
    assert data["obligations"] == []
    assert data["month"] is None


# ── the rule that does not bend ──────────────────────────────────────────────

CREDENTIAL_WORDS = ("password", "passcode", "otp", "pin", "captcha",
                    "username", "user id", "login", "credential", "evc")


def test_no_field_in_the_response_is_named_after_a_secret(monkeypatch):
    """Structural, not a review note. This product never signs in to a portal
    on anybody's behalf, and an OTP is typed on the portal — never in the
    software that prepared the return. Every LABEL a CA could type into is
    checked, on every panel the endpoint produced."""
    data = _handoff(monkeypatch)
    for panel in data["obligations"]:
        typed_in = [f["label"] for f in panel["identity"]] + [
            panel.get("record_back") or "", panel["title"]]
        for text in typed_in:
            low = text.lower()
            for word in CREDENTIAL_WORDS:
                assert word not in low, f"{panel['key']}: {text}"


def test_the_disclaimer_says_nothing_is_transmitted(monkeypatch):
    data = _handoff(monkeypatch)
    assert "Nothing here is transmitted" in data["disclaimer"]
    assert "password" in data["disclaimer"], (
        "the disclaimer names the thing it will never ask for, because a CA "
        "coming from another product expects to be asked")
