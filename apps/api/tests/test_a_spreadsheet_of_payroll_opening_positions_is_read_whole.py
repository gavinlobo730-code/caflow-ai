"""POST-A-082, part 2: a spreadsheet of payroll opening positions, read on the server and refused whole.

The API took many positions at once and had no file reader, so a client coming over mid-year with sixty employees meant sixty forms. The
file is now read the way the employee import reads one (the browser sends the cells as text, every decision is the server's, one problem
anywhere writes nothing, every problem comes back at once keyed to the spreadsheet row), and the rows it yields are asked exactly what the
form's PUT asks.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as P
from domain.payroll import opening_position_import as reader
from models.payroll import OpeningPositionsImportIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-OPI", "CLI-OPI"
CALLER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@f.test", "role": "Partner"}


def _row(**kw) -> dict:
    base = {"employee_code": "EMP001", "first_month_here": "2026-10", "months_paid": "6", "gross": "3,00,000", "tds": "6000",
            "pf_employee": "10800", "pf_employer": "10800", "esi_employee": "0", "esi_employer": "0", "pt": "1200",
            "esi_contributed_earlier_in_period": "", "source_note": "Tally payroll register, Sept 2026"}
    base.update(kw)
    return base


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [P])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps", "firm_id": FIRM, "client_id": CLIENT, "payroll_enabled": True})
    for emp_id, code, name, joined in (("e-a", "EMP001", "Asha", "2020-04-01"), ("e-b", "EMP002", "Bala", "2026-08-10")):
        d.seed("payroll_employees", {"id": emp_id, "firm_id": FIRM, "client_id": CLIENT, "name": name, "employee_code": code,
                                     "status": "active", "joining_date": joined})
    d.seed("payroll_employees", {"id": "e-x", "firm_id": "OTHER", "client_id": "CLI-X", "name": "Stranger",
                                 "employee_code": "EMP009", "status": "active", "joining_date": "2020-04-01"})
    return d


def _import(rows, **kw):
    return P.import_opening_positions(OpeningPositionsImportIn(client_id=CLIENT, rows=rows, **kw), current_user=CALLER)


def test_a_clean_file_records_each_row_as_the_form_would(db):
    out = _import([_row(), _row(employee_code="emp002", months_paid="2", gross="80000", tds="0", pf_employee="0",
                                pf_employer="0", pt="400", esi_contributed_earlier_in_period="no")])["data"]
    assert out["recorded"] == 2
    got = {r["employee_id"]: r for r in db.rows("payroll_opening_positions")}
    assert got["e-a"]["gross_paise"] == 30_000_000 and got["e-a"]["tds_paise"] == 600_000
    assert got["e-a"]["first_month_here"] == "2026-10-01" and got["e-a"]["financial_year"] == "2026-27"
    assert got["e-a"]["esi_contributed_earlier_in_period"] is None, "a blank answer is not known, not no"
    assert got["e-b"]["esi_contributed_earlier_in_period"] is False
    assert all(r["firm_id"] == FIRM and r["client_id"] == CLIENT for r in got.values())


def test_one_bad_row_writes_nothing_and_every_problem_comes_back_keyed_to_its_row(db):
    with pytest.raises(HTTPException) as e:
        _import([_row(), _row(employee_code="EMP002", gross=""), _row(employee_code="EMP404")])
    assert e.value.status_code == 422
    problems = e.value.detail["problems"]
    assert any(p.startswith("Row 2: gross is required") for p in problems)
    assert any(p.startswith("Row 3: ") and "EMP404" in p for p in problems)
    assert "nothing was recorded" in e.value.detail["message"]
    assert db.rows("payroll_opening_positions") == []


def test_the_form_s_own_checks_are_asked_of_the_file_and_name_the_row(db):
    # Bala joined in August, so at most two months of 2026-27 fall before October.
    with pytest.raises(HTTPException) as e:
        _import([_row(employee_code="EMP002", months_paid="6")])
    assert any(p.startswith("Row 1 (Bala): ") and "joined in 2026-08" in p for p in e.value.detail["problems"])
    assert db.rows("payroll_opening_positions") == []


def test_an_employee_of_another_firm_is_not_on_this_roster(db):
    with pytest.raises(HTTPException) as e:
        _import([_row(employee_code="EMP009")])
    assert any("EMP009" in p for p in e.value.detail["problems"])
    assert db.rows("payroll_opening_positions") == []


def test_a_month_already_released_before_the_first_month_refuses_the_file(db):
    db.seed("payroll_runs", {"id": "run-sep", "firm_id": FIRM, "client_id": CLIENT, "month": "2026-09", "status": "finalized"})
    db.seed("payroll_slips", {"id": "s1", "run_id": "run-sep", "employee_id": "e-a"})
    with pytest.raises(HTTPException) as e:
        _import([_row()])
    assert e.value.status_code == 422 and any("counted twice" in p for p in e.value.detail["problems"])
    assert db.rows("payroll_opening_positions") == []


def test_a_dry_run_says_what_would_be_recorded_and_writes_nothing(db):
    out = _import([_row()], dry_run=True)["data"]
    assert out["would_record"] == 1 and out["dry_run"] is True
    assert db.rows("payroll_opening_positions") == []


def test_a_named_twice_employee_is_refused(db):
    with pytest.raises(HTTPException) as e:
        _import([_row(), _row(employee_code="emp001")])
    assert any("named twice" in p for p in e.value.detail["problems"])


@pytest.mark.parametrize("cells, fragment", [
    ({"first_month_here": "10/2026"}, "first_month_here must be a month"),
    ({"first_month_here": "2026-10-15"}, "first_month_here must be a month"),
    ({"months_paid": "six"}, "months_paid must be a whole number"),
    ({"tds": "1.005"}, "tds must be an amount"),
    ({"pt": "-5"}, "pt may not be negative"),
    ({"esi_contributed_earlier_in_period": "maybe"}, 'got "maybe"'),
    ({"employee_code": ""}, "employee_code is required"),
])
def test_a_cell_that_is_not_what_its_column_holds_is_refused_not_coerced(cells, fragment):
    result = reader.read([_row(**cells)], employee_by_code={"emp001": "e-a"})
    assert not result.ok and any(fragment in p for p in result.problems), result.problems


def test_a_workbook_date_on_the_first_of_a_month_is_that_month_and_amounts_are_exact_paise():
    result = reader.read([_row(first_month_here="2026-10-01", gross="1145.30")], employee_by_code={"emp001": "e-a"})
    assert result.ok
    body = result.rows[0][1]
    assert body["first_month_here"] == "2026-10" and body["gross_paise"] == 114_530


def test_the_template_is_a_header_and_every_column_fills_a_field_of_the_form_s_model():
    from models.payroll import OpeningPositionIn
    assert reader.template_csv().count("\n") == 1
    assert {f for _c, f, _r in reader.COLUMNS} == set(OpeningPositionIn.model_fields)


def test_the_form_s_put_still_records_and_still_refuses_an_employee_off_the_roster(db):
    from models.payroll import OpeningPositionIn, OpeningPositionsIn
    good = OpeningPositionIn(employee_id="e-a", first_month_here="2026-10", months_paid=6, gross_paise=30_000_000, tds_paise=600_000,
                             pf_employee_paise=0, pf_employer_paise=0, esi_employee_paise=0, esi_employer_paise=0, pt_paise=0)
    with pytest.raises(HTTPException) as e:
        P.put_opening_positions(OpeningPositionsIn(client_id=CLIENT, rows=[good.model_copy(update={"employee_id": "e-x"})]),
                                current_user=CALLER)
    assert e.value.status_code == 422 and "not on this client's roster" in e.value.detail
    assert db.rows("payroll_opening_positions") == []
    assert P.put_opening_positions(OpeningPositionsIn(client_id=CLIENT, rows=[good]), current_user=CALLER)["data"]["saved"] == 1
    assert db.rows("payroll_opening_positions")[0]["employee_id"] == "e-a"


def test_the_browser_s_column_list_mirrors_the_server_s():
    """A column the browser offers and the server ignores is filled in and silently does nothing; the server is the authority."""
    import re
    from pathlib import Path
    web = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "imports" / "mappers.ts"
    if not web.exists():
        pytest.skip("apps/web not present in this checkout")
    text = web.read_text()
    block = text[text.index("export const OPENING_POSITION_IMPORT_COLUMNS"):]
    block = block[:block.index("];")]
    browser = re.findall(r'\{\s*key:\s*"([^"]+)",[^}]*required:\s*(true|false)', block)
    assert [k for k, _r in browser] == [c for c, _f, _req in reader.COLUMNS]
    # The dialog drops a row with a blank REQUIRED cell before the server sees it, which defeats "refused whole": the server is the one
    # that refuses a blank, so no column is required in the browser's list.
    assert all(r == "false" for _k, r in browser)


# ── what the independent review found in this reader ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cell", ["₹", ",", " , ", "₹ ,", "   "])
def test_a_cell_holding_only_a_currency_sign_or_a_separator_is_blank_and_refused_never_read_as_nil(cell):
    result = reader.read([_row(gross=cell)], employee_by_code={"emp001": "e-a"})
    assert not result.ok and any("gross is required" in p for p in result.problems), result.problems


def test_an_amount_beyond_what_the_column_holds_is_refused_in_its_row_not_left_to_fail_mid_write():
    result = reader.read([_row(gross="9" * 25)], employee_by_code={"emp001": "e-a"})
    assert not result.ok and any("gross is too large to record" in p for p in result.problems), result.problems


def test_a_code_two_employees_hold_apart_from_capitals_is_refused_and_never_matched_to_one_of_them():
    from domain.payroll.employee_import import code_index
    index = code_index([{"id": "e-1", "employee_code": "EMP001"}, {"id": "e-2", "employee_code": "emp001 "},
                        {"id": "e-3", "employee_code": "EMP002"}, {"id": "e-4", "employee_code": None}])
    assert index == {"emp001": None, "emp002": "e-3"}
    result = reader.read([_row(employee_code="Emp001")], employee_by_code=index)
    assert not result.ok and any("matches more than one employee" in p for p in result.problems), result.problems
    assert reader.read([_row(employee_code="EMP002")], employee_by_code=index).ok
