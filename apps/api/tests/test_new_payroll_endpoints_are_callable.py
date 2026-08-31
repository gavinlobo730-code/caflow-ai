"""
Every payroll endpoint added in this batch is actually CALLED at least once.

WHY THIS FILE EXISTS

Four of these endpoints shipped with `assert_not_internal_for_payroll(client_id)`
— one argument, where the function requires two. Every one of them would have
raised TypeError on its first real request. Nothing caught it, because the work
was tested at the domain level (the statutory arithmetic, which is where the
interesting mistakes are) and no test ever went through the router.

Domain tests cannot see a wiring mistake. These are deliberately shallow — they
assert almost nothing about the answer — because their whole job is to execute
the handler end to end and let a TypeError, a NameError or a missing column
surface. The arithmetic is tested properly elsewhere.
"""
from datetime import date

import pytest

import routers.payroll as pr
from models.payroll import DeclarationIn, DeclarationVerifyIn

CLIENT = "11111111-1111-1111-1111-111111111111"
EMPLOYEE = "22222222-2222-2222-2222-222222222222"
USER = {"id": "u1", "firm_id": "f1", "auth_user_id": "a1", "role": "Partner"}


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """Mock mode: every handler takes its `if not db` branch and returns the
    empty shape. That is enough — the bug this file exists for happens BEFORE
    any query, in the guards and the argument wiring."""
    monkeypatch.setattr(pr, "_db", lambda: None)
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)


def test_upsert_declaration_is_callable():
    body = DeclarationIn(client_id=CLIENT, employee_id=EMPLOYEE, fy="2026-27",
                         regime="old")
    assert pr.upsert_declaration(body, USER)["success"]


def test_list_declarations_is_callable():
    assert pr.list_declarations(client_id=CLIENT, fy="2026-27",
                                current_user=USER)["success"]


def test_verify_declaration_is_callable():
    body = DeclarationVerifyIn(client_id=CLIENT)
    assert pr.verify_declaration("d1", body, USER)["success"]


def test_statutory_position_is_callable():
    assert pr.statutory_position(client_id=CLIENT, month="2026-07",
                                 current_user=USER)["success"]


def test_statutory_position_refuses_a_malformed_month():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        pr.statutory_position(client_id=CLIENT, month="July", current_user=USER)
    assert e.value.status_code == 422


def test_preview_settlement_is_callable():
    body = pr.SettlementIn(client_id=CLIENT, leaving_date="2026-09-30")
    assert pr.preview_settlement(EMPLOYEE, body, USER)["success"]


def test_arrears_relief_is_callable():
    body = pr.ArrearsReliefIn(client_id=CLIENT, receipt_fy="2026-27",
                              total_income_receipt_year_paise=20_00_000 * 100)
    assert pr.arrears_relief(EMPLOYEE, body, USER)["success"]


def test_value_perquisites_is_callable():
    body = pr.PerquisiteValuationIn(client_id=CLIENT, fy="2026-27",
                                    salary_for_rule_3_paise=10_00_000 * 100,
                                    accommodation=True, population_lakh=50)
    out = pr.value_perquisites(EMPLOYEE, body, USER)
    assert out["success"]
    assert out["data"]["total_paise"] > 0


def test_record_perquisites_is_callable():
    body = pr.PerquisiteRecordIn(client_id=CLIENT, fy="2026-27", items=[])
    assert pr.record_perquisites(EMPLOYEE, body, USER)["success"]


def test_add_salary_revision_is_callable():
    body = pr.SalaryRevisionIn(client_id=CLIENT, effective_from="2026-10-01",
                            basic_paise=60_000 * 100)
    assert pr.add_salary_revision(EMPLOYEE, body, USER)["success"]


def test_add_salary_revision_refuses_a_malformed_date():
    from fastapi import HTTPException
    body = pr.SalaryRevisionIn(client_id=CLIENT, effective_from="next October",
                            basic_paise=60_000 * 100)
    with pytest.raises(HTTPException) as e:
        pr.add_salary_revision(EMPLOYEE, body, USER)
    assert e.value.status_code == 422


def test_list_salary_revisions_is_callable():
    assert pr.list_salary_revisions(EMPLOYEE, client_id=CLIENT,
                                    current_user=USER)["success"]


def test_add_employee_loan_is_callable_and_flags_an_interest_free_one():
    """Rule 3(7)(i): an interest-free loan is a perquisite. An employer who
    records only the recovery has an unvalued perquisite in the Form 16."""
    body = pr.EmployeeLoanIn(client_id=CLIENT, principal_paise=1_00_000 * 100,
                          monthly_instalment_paise=10_000 * 100,
                          interest_rate_bps=0)
    out = pr.add_employee_loan(EMPLOYEE, body, USER)
    assert out["success"]
    assert any("Rule 3(7)(i)" in n for n in out["data"]["notices"])


def test_list_employee_loans_is_callable():
    assert pr.list_employee_loans(EMPLOYEE, client_id=CLIENT,
                                  current_user=USER)["success"]
