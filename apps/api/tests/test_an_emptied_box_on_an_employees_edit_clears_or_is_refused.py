"""An employee's edit clears a designation or a department the person emptied, and refuses to empty an identifier on file (POST-A-399, third slice).

`update_employee` read its body with `model_dump(exclude_none=True)`, and the employee form sends an emptied box as null, so a person who emptied
the designation, the department, the PAN, the UAN or the bank account and pressed Save was told it was saved and found the old value when the
employee was opened again. Now:
  * the designation, the department and the bank name, soft particulars a person typed, are cleared (written NULL) when sent empty (the bank name is
    read by no return and no payment, so refusing to empty it with a reason about returns was false);
  * the PAN, the UAN, the ESI number, the bank account number and the IFSC are corrected and never removed: emptied over a value on
    file, the edit is refused in one sentence and nothing is written; emptied over nothing, nothing happens;
  * every other null still reads "not sent", so a request that names only the status changes nothing else.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as pr
from models.payroll import EMPLOYEE_IDENTIFIERS, EmployeeUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "F1"
CALLER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a1", "email": "p@firm.test"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [pr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM})
    d.seed("payroll_employees", {
        "id": "e-01", "firm_id": FIRM, "client_id": "CLI", "name": "Asha", "designation": "Analyst", "department": "Accounts",
        "pan": "ABCPA1234K", "uan": "100200300401", "esi_number": "3100123456", "bank_account_no": "000123456789",
        "bank_ifsc": "HDFC0001234", "bank_name": "HDFC Bank", "pf_applicable": True, "status": "active", "is_active": True})
    return d


def _row(db):
    return db.rows("payroll_employees")[0]


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_emptied_designation_and_department_are_cleared(db, empty):
    pr.update_employee("e-01", EmployeeUpdateIn(designation=empty, department=empty), CALLER)
    assert (_row(db)["designation"], _row(db)["department"]) == (None, None)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_emptied_bank_name_is_cleared_and_the_bank_account_is_kept(db, empty):
    pr.update_employee("e-01", EmployeeUpdateIn(bank_name=empty), CALLER)
    assert (_row(db)["bank_name"], _row(db)["bank_account_no"], _row(db)["bank_ifsc"]) == (None, "000123456789", "HDFC0001234")


def test_the_bank_name_is_not_an_identifier_the_edit_refuses_to_empty():
    assert "bank_name" not in EMPLOYEE_IDENTIFIERS and {"bank_account_no", "bank_ifsc"} <= set(EMPLOYEE_IDENTIFIERS)


def test_a_field_not_sent_is_left_alone(db):
    pr.update_employee("e-01", EmployeeUpdateIn(status="active"), CALLER)
    assert (_row(db)["designation"], _row(db)["department"], _row(db)["pan"]) == ("Analyst", "Accounts", "ABCPA1234K")


@pytest.mark.parametrize("field", sorted(EMPLOYEE_IDENTIFIERS))
def test_an_identifier_on_file_emptied_is_refused_in_a_sentence_and_nothing_is_written(db, field):
    before = dict(_row(db))
    with pytest.raises(HTTPException) as refused:
        pr.update_employee("e-01", EmployeeUpdateIn(**{field: None, "designation": "Senior Analyst"}), CALLER)
    assert refused.value.status_code == 422
    assert refused.value.detail.startswith(f"The {EMPLOYEE_IDENTIFIERS[field]} on file can be corrected but not removed")
    assert "documents already issued to this party" not in refused.value.detail, "the party masters' sentence is not true of an employee"
    assert _row(db) == before, "a refused edit wrote something"


def test_an_identifier_emptied_over_nothing_is_not_refused(db):
    _row(db)["esi_number"] = None
    pr.update_employee("e-01", EmployeeUpdateIn(esi_number=None, designation="Lead"), CALLER)
    assert (_row(db)["esi_number"], _row(db)["designation"]) == (None, "Lead")


def test_a_corrected_identifier_is_written(db):
    pr.update_employee("e-01", EmployeeUpdateIn(bank_name="ICICI Bank"), CALLER)
    assert _row(db)["bank_name"] == "ICICI Bank"


def test_the_employee_handler_is_off_the_list_of_handlers_that_cannot_clear():
    from pathlib import Path
    listed = (Path(__file__).resolve().parent / "fixtures" / "patch_handlers_that_cannot_clear.txt").read_text(encoding="utf-8")
    assert "routers/payroll.py::update_employee" not in listed


# ── the box says the server's sentence (POST-A-465) ──────────────────────────────────────────────────────────────

def test_the_employee_forms_list_and_sentence_are_the_servers():
    """Held from the side that owns the rule: `lib/payroll/employeeIdentifiers.ts` names the same identifiers, in the same order and with the same
    words, and carries `EMPLOYEE_IDENTIFIER_WHY` word for word, so the box says what the route will refuse."""
    import re
    from pathlib import Path

    from models.payroll import EMPLOYEE_IDENTIFIER_WHY, EMPLOYEE_IDENTIFIERS

    ts = (Path(__file__).resolve().parents[2] / "web" / "lib" / "payroll" / "employeeIdentifiers.ts").read_text(encoding="utf-8")
    block = re.search(r"export const EMPLOYEE_IDENTIFIERS = \{(.*?)\} as const;", ts, re.S)
    assert block, "the browser's list is not where it was"
    browser = dict(re.findall(r'(\w+): "([^"]+)"', block.group(1)))
    assert list(browser.items()) == list(EMPLOYEE_IDENTIFIERS.items())
    assert ('"' + EMPLOYEE_IDENTIFIER_WHY + '"') in ts, "the browser's reason is not the server's"
