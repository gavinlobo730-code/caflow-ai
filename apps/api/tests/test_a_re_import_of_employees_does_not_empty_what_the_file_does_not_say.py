"""POST-A-472: re-importing an employee file is the edit of each matched employee, and empties nothing the file does not say.

A row whose employee code was on file used to write the whole payload, so a file of codes, names and basic pay wrote NULL over every matched
employee's PAN, UAN, ESI number and bank details (and HRA 40%, PF and ESI on, every allowance nil), and the import said "N updated". The edit
of an employee refuses emptying an identifier on file (POST-A-399 / POST-A-465); the import is a second door to the same action.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_mod
from domain.payroll import employee_import as importer
from models.payroll import EMPLOYEE_IDENTIFIERS, EmployeeImportIn, EmployeeUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-REIMPORT"
USER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1", "email": "ca@f.test", "role": "Partner"}

ON_FILE = {
    "pan": "ABCPR1234K", "uan": "100200300400", "esi_number": "3100123456", "bank_account_no": "001122334455",
    "bank_ifsc": "HDFC0001234", "bank_name": "HDFC Bank", "designation": "Accountant", "department": "Finance",
    "date_of_birth": "1985-04-03", "joining_date": "2020-06-01", "hra_percent": 50.0, "da_percent": 5.0,
    "lta_paise": 200_000, "medical_paise": 125_000, "other_allowances_paise": 0, "special_allowance_paise": 300_000,
    "pf_applicable": False, "esi_applicable": False, "pt_applicable": True, "pt_state": "MH", "gender": "female",
    "aadhaar_last4": "9876", "eps_eligible": False, "gratuity_act_covered": False,
}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme Pvt Ltd", "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "CPS-1", "firm_id": FIRM, "client_id": "CLI", "payroll_enabled": True,
                                       "inputs_due_day": 5})
    d.seed("payroll_employees", {"id": "EMP-1", "firm_id": FIRM, "client_id": "CLI", "status": "active", "name": "Asha Rao",
                                 "employee_code": "EMP001", "basic_paise": 3_000_000, **ON_FILE})
    d.seed("payroll_employees", {"id": "EMP-2", "firm_id": FIRM, "client_id": "CLI", "status": "active", "name": "Ravi Kumar",
                                 "employee_code": "EMP002", "basic_paise": 4_500_000, "pan": None, "uan": None})
    return d


def _import(rows, **kw):
    return payroll_mod.import_employees(EmployeeImportIn(client_id="CLI", rows=rows, **kw), current_user=USER)


def _stored(db, employee_id):
    return next(r for r in db.rows("payroll_employees") if r["id"] == employee_id)


def test_a_file_of_codes_names_and_basic_changes_the_basic_and_nothing_else(db):
    out = _import([{"employee_code": "EMP001", "name": "Asha Rao", "basic": "32000"}])["data"]
    assert out["updated"] == 1 and out["created"] == 0
    row = _stored(db, "EMP-1")
    assert row["basic_paise"] == 3_200_000
    for key, value in ON_FILE.items():
        assert row[key] == value, f"{key} was overwritten by a column the file does not carry"


def test_a_blank_cell_over_an_identifier_on_file_refuses_the_whole_file_in_the_edit_s_sentence(db):
    for identifier in EMPLOYEE_IDENTIFIERS:
        with pytest.raises(HTTPException) as e:
            _import([{"employee_code": "EMP002", "name": "Ravi Kumar", "basic": "46000"},
                     {"employee_code": "EMP001", "name": "Asha Rao", "basic": "32000", identifier: ""}])
        assert e.value.status_code == 422
        problems = e.value.detail["problems"]
        assert len(problems) == 1 and problems[0].startswith("Row 2: ")
        assert f"The {EMPLOYEE_IDENTIFIERS[identifier]} on file can be corrected but not removed" in problems[0]
        assert "nothing was imported" in e.value.detail["message"]
        assert _stored(db, "EMP-1")[identifier] == ON_FILE[identifier]
        assert _stored(db, "EMP-2")["basic_paise"] == 4_500_000, "the clean row of a refused file is not written either"


def test_a_blank_identifier_over_nothing_on_file_is_not_a_refusal_and_writes_nothing(db):
    out = _import([{"employee_code": "EMP002", "name": "Ravi Kumar", "basic": "46000", "pan": "", "uan": ""}])["data"]
    assert out["updated"] == 1
    assert _stored(db, "EMP-2")["pan"] is None and _stored(db, "EMP-2")["basic_paise"] == 4_600_000


def test_a_blank_cell_clears_what_the_edit_clears_and_leaves_everything_else(db):
    blanks = {column: "" for column in importer.COLUMN_FIELDS if column not in ("employee_code", "name", "basic")
              and column not in importer.IDENTIFIERS}
    _import([{"employee_code": "EMP001", "name": "Asha Rao", "basic": "30000", **blanks}])
    row = _stored(db, "EMP-1")
    for key, value in ON_FILE.items():
        if key in importer.CLEARED_WHEN_BLANK:
            assert row[key] is None, f"an emptied {key} is cleared, as on the edit"
        else:
            assert row[key] == value, f"a blank {key} cell is 'not changed', as an empty box is on the edit"


def test_a_cell_with_a_value_is_written_as_before(db):
    _import([{"employee_code": "EMP001", "name": "Asha Rao", "basic": "30000", "pan": "ABCPR9999Z", "lta": "0",
              "pf_applicable": "yes", "hra_percent": "40", "designation": "Senior Accountant"}])
    row = _stored(db, "EMP-1")
    assert (row["pan"], row["lta_paise"], row["pf_applicable"], row["hra_percent"], row["designation"]) == (
        "ABCPR9999Z", 0, True, 40.0, "Senior Accountant")


def test_a_new_employee_still_takes_the_file_s_defaults(db):
    _import([{"employee_code": "EMP003", "name": "New Person", "basic": "20000"}])
    row = next(r for r in db.rows("payroll_employees") if r.get("employee_code") == "EMP003")
    assert row["hra_percent"] == importer.DEFAULT_HRA_PERCENT and row["pf_applicable"] is True


def test_the_importer_s_blank_rules_are_the_edit_s():
    assert importer.CLEARED_WHEN_BLANK == EmployeeUpdateIn.CLEARABLE
    assert set(importer.IDENTIFIERS) == set(EMPLOYEE_IDENTIFIERS)
    assert {column for column, _req in importer.COLUMNS} == set(importer.COLUMN_FIELDS)
