"""The seeded payroll says who is insured under the ESI Act and under which registrations the employer files (PRE-A-004).

What was wrong: the seeder sent no `esi_applicable` and no IP number, and `EmployeeIn` defaults `esi_applicable` to True, so all
twelve seeded employees were flagged as insured. The ESIC return (`domain/payroll/esic.build_esic_return`) lists every flagged
employee as a member with their whole wages and names every one with no IP number as a problem, and the payroll exceptions list
(`domain/payroll/exceptions.for_employee`) named all twelve: a page of gaps on the one client that exists to show payroll. And only
the TAN was recorded, so the ECR and ESIC panels named the establishment and employer codes as missing.

These tests hold the fixture's coverage to the ENGINE (`routers/payroll._compute_slip`, which the run pays from), the codes to a
seed's marking, and the seeder's bodies to what the fixture says. The payroll stage cannot run in mock mode (the employee and run
doors answer constants), so the seeder's bodies are read off the recorder the body-shape test uses.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from domain.demo import fixture
from domain.payroll.esic import IP_NUMBER_RE, build_esic_return
from domain.payroll.exceptions import for_employee

FY = "2025-26"
FIRM = fixture.build(FY)
PAYROLL_CLIENTS = [c for c in FIRM.clients if c.employees]
EMPLOYEES = [(c, e) for c in PAYROLL_CLIENTS for e in c.employees]


def _as_stored(e: fixture.DemoEmployee, n: int) -> dict:
    """The employee row as the seeder's create body writes it, with the defaults `EmployeeIn` gives what it does not send."""
    return {"id": f"emp-{n}", "name": e.name, "pan": e.pan, "uan": e.uan, "basic_paise": e.basic_paise,
            "hra_percent": e.hra_percent, "special_allowance_paise": e.special_paise, "pf_applicable": True,
            "esi_applicable": e.esi_applicable, "esi_number": e.esi_number, "pt_applicable": False,
            "bank_account_no": e.bank_account_no, "bank_ifsc": e.bank_ifsc, "bank_name": e.bank_name,
            "joining_date": e.doj}


def test_the_fixture_has_somebody_the_esi_engine_reaches_and_somebody_it_does_not():
    assert EMPLOYEES, "the fixture runs no payroll"
    covered = [e for _, e in EMPLOYEES if e.esi_applicable]
    assert covered, "nobody is insured, so the ESIC return is empty"
    assert len(covered) < len(EMPLOYEES), "everybody is insured, so the ceiling is never shown"


@pytest.mark.parametrize("client,employee", EMPLOYEES, ids=[f"{c.name}:{e.name}" for c, e in EMPLOYEES])
def test_an_employee_is_insured_exactly_when_the_engine_deducts_esi_from_a_full_month(client, employee):
    """Asked of the engine with the employee flagged as insured: it deducts nothing from wages above the ceiling for somebody not
    covered at the start of the period, which is the only state an employee who joined on the first day of the year can be in."""
    from routers.payroll import _compute_slip
    slip = _compute_slip({**_as_stored(employee, 0), "esi_applicable": True}, None, fy=FY)
    engine_says = int(slip["esi_employee_paise"]) > 0
    assert employee.esi_applicable is engine_says
    assert fixture.esi_wages_paise(employee.basic_paise, employee.hra_percent, employee.special_paise) == int(
        slip["gross_paise"]), "the fixture's ESI wages are not the engine's gross for a full month with no one-time earning"


@pytest.mark.parametrize("client,employee", EMPLOYEES, ids=[f"{c.name}:{e.name}" for c, e in EMPLOYEES])
def test_an_insured_employee_has_an_ip_number_and_nobody_else_does(client, employee):
    if employee.esi_applicable:
        assert employee.esi_number and IP_NUMBER_RE.match(employee.esi_number), employee
    else:
        assert employee.esi_number is None, employee


def test_the_ip_numbers_are_distinct():
    numbers = [e.esi_number for _, e in EMPLOYEES if e.esi_number]
    assert len(numbers) == len(set(numbers))


@pytest.mark.parametrize("client", PAYROLL_CLIENTS, ids=[c.name for c in PAYROLL_CLIENTS])
def test_the_esic_return_carries_every_insured_employee_and_names_no_problem(client):
    from routers.payroll import _compute_slip
    employees = {f"emp-{n}": _as_stored(e, n) for n, e in enumerate(client.employees)}
    slips = []
    for eid, emp in employees.items():
        s = _compute_slip(emp, None, fy=FY)
        slips.append({"employee_id": eid, "gross_paise": s["gross_paise"], "lop_days": 0,
                      "esi_employee_paise": s["esi_employee_paise"], "esi_employer_paise": s["esi_employer_paise"]})
    ret = build_esic_return(slips=slips, employees_by_id=employees, days_in_month=30)
    assert ret.problems == []
    assert len(ret.members) == sum(1 for e in client.employees if e.esi_applicable)


@pytest.mark.parametrize("client,employee", EMPLOYEES, ids=[f"{c.name}:{e.name}" for c, e in EMPLOYEES])
def test_the_payroll_exceptions_list_names_no_esi_gap(client, employee):
    kinds = {x["kind"] for x in for_employee(_as_stored(employee, 0), fy=FY)}
    assert "esic_ip" not in kinds


def test_a_year_the_payroll_registry_does_not_hold_decides_no_coverage():
    other = fixture.build("2024-25")
    assert {e.esi_applicable for c in other.clients for e in c.employees} == {None}
    assert {e.esi_number for c in other.clients for e in c.employees} == {None}


def test_the_employer_codes_are_a_seeds_and_the_esic_code_is_only_where_somebody_is_insured():
    for c in FIRM.clients:
        regs = fixture.payroll_registrations(c)
        if not c.employees:
            assert regs == {}, c.name
            continue
        assert regs["epf_establishment_code"].startswith("SEED-"), c.name
        insured = any(e.esi_applicable for e in c.employees)
        assert ("esic_employer_code" in regs) is insured, c.name
        if insured:
            assert regs["esic_employer_code"].startswith("SEED-")
    assert any("esic_employer_code" in fixture.payroll_registrations(c) for c in FIRM.clients)


def test_the_identity_gaps_are_closed_by_what_is_recorded():
    from domain.payroll.identity import ecr_gaps, esic_gaps
    for c in PAYROLL_CLIENTS:
        regs = fixture.payroll_registrations(c)
        assert ecr_gaps(regs) == []
        if any(e.esi_applicable for e in c.employees):
            assert esic_gaps(regs) == []


# ── The seeder's bodies ─────────────────────────────────────────────────────────

def _recorded_run():
    spec = importlib.util.spec_from_file_location(
        "body_test", Path(__file__).resolve().parent / "test_every_body_the_seeder_sends_is_one_its_door_accepts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from main import app
    seeder = mod._seeder()
    rec = mod._Recorder(mod._doors(app))
    seeder.seed(rec, fixture.build(), add_to_existing=False)
    assert not rec.invalid, rec.invalid
    return rec


@pytest.fixture(scope="module")
def run():
    return _recorded_run()


def test_every_employee_body_says_whether_they_are_insured(run):
    bodies = [b for m, p, b in run.requests if (m, p) == ("POST", "/api/payroll/employees")]
    assert len(bodies) == len(EMPLOYEES)
    for b, (_, e) in zip(bodies, EMPLOYEES, strict=True):
        assert b["esi_applicable"] is e.esi_applicable
        assert b["esi_number"] == e.esi_number


def test_the_employer_codes_are_recorded_after_payroll_is_switched_on_once_per_payroll_client(run):
    puts = [(i, b) for i, (m, p, b) in enumerate(run.requests)
            if (m, p) == ("PUT", "/api/payroll/statutory-identity") and "epf_establishment_code" in b]
    assert len(puts) == len(PAYROLL_CLIENTS)
    enablements = [i for i, (m, p, _) in enumerate(run.requests) if (m, p) == ("PUT", "/api/payroll/enablement")]
    for (i, b), on in zip(puts, enablements, strict=True):
        assert on < i, "a payroll registration was sent before payroll was switched on, which the door refuses"
        assert "tan" not in b, "the TAN is recorded by its own body"
    expected = [{k: v for k, v in fixture.payroll_registrations(c).items()} for c in PAYROLL_CLIENTS]
    assert [{k: v for k, v in b.items() if k != "client_id"} for _, b in puts] == expected
