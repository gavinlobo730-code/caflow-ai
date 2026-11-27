"""Migration 779 on real Postgres: the two payroll report functions give the figures the Python path gives (POST-A-536).

WHY A REAL DATABASE
    The service keeps its Python path (mock mode, a database without the functions) and asks the database for the sums when it can.
    Two implementations of one rule drift, so the same payslips go through both here and the results are compared figure by figure:
    `payroll_run_summaries` against `run_totals_from_slips`, and `payroll_year_end_totals` against `employee_totals_from_slips`, the
    way `test_cash_flow_sql_parity_pg.py` holds the cash-flow statement. Then what only Postgres can say: another firm's run adds
    nothing, a run id nobody has is zeros, an employee row that is gone gives no employee, and a signed-in session cannot call either
    function.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from services import payroll_report_service as prs

_ADMIN = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(not _ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

FIRM = "77900000-0000-0000-0000-000000000001"
OTHER_FIRM = "77900000-0000-0000-0000-000000000002"
CLIENT = "77900000-0000-0000-0000-0000000000c1"
OTHER_CLIENT = "77900000-0000-0000-0000-0000000000c2"
E1, E2, E3 = (f"77900000-0000-0000-0000-0000000000e{i}" for i in (1, 2, 3))
RUN = {i: f"77900000-0000-0000-0000-0000000000a{i}" for i in (1, 2, 3)}
OTHER_RUN = "77900000-0000-0000-0000-0000000000b1"
NOBODYS_RUN = "77900000-0000-0000-0000-0000000000ff"

#: run -> (month, [slips as (employee, gross, net, tds, pt, pf_ee, pf_er, esi_ee, esi_er)])
SPEC = {
    1: ("2026-04-01", [(E1, 5000000, 4500000, 100000, 20000, 180000, 180000, 0, 0)]),
    2: ("2026-05-01", [(E1, 5000000, 4400000, 120000, 20000, 180000, 180000, 0, 0),
                       (E2, 1800000, 1700000, 0, 0, 0, 0, 13500, 58500)]),
    3: ("2026-06-01", [(E2, 1800000, 1690000, 0, 0, 0, 0, 13500, 58500), (E3, 100, 100, 0, 0, 0, 0, 0, 0)]),
}
NAMES = {E1: ("Asha", "ABCDE1234F", "Clerk", "Ops"), E2: ("bala", None, None, None), E3: ("Chitra", None, "Peon", None)}


def _psql(dsn, sql):
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"c5_pr779_{uuid.uuid4().hex[:12]}"
    if _psql(f"{admin} dbname=postgres", f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        stmts = [
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship'), "
            f"('{OTHER_CLIENT}', '{OTHER_FIRM}', 'D', 'Proprietorship');",
        ]
        for emp, (name_, pan, desig, dept) in NAMES.items():
            q = lambda v: "NULL" if v is None else f"'{v}'"  # noqa: E731
            stmts.append(f"INSERT INTO payroll_employees (id, firm_id, client_id, name, pan, designation, department, status) "
                         f"VALUES ('{emp}', '{FIRM}', '{CLIENT}', '{name_}', {q(pan)}, {q(desig)}, {q(dept)}, 'active');")
        n = 0
        for i, (month, slips) in SPEC.items():
            stmts.append(f"INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES ('{RUN[i]}', '{FIRM}', '{CLIENT}', '{month}', 'finalized');")
            for (emp, gross, net, tds, pt, pf_ee, pf_er, esi_ee, esi_er) in slips:
                n += 1
                stmts.append(
                    "INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise, tds_paise, pt_paise, "
                    "pf_employee_paise, pf_employer_paise, esi_employee_paise, esi_employer_paise) "
                    f"VALUES ('{RUN[i]}', '{emp}', {gross}, {net}, {tds}, {pt}, {pf_ee}, {pf_er}, {esi_ee}, {esi_er});")
        # another firm's run and payslip, which must add nothing for this firm
        stmts.append(f"INSERT INTO payroll_employees (id, firm_id, client_id, name, status) VALUES ('77900000-0000-0000-0000-0000000000e9', '{OTHER_FIRM}', '{OTHER_CLIENT}', 'Zed', 'active');")
        stmts.append(f"INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES ('{OTHER_RUN}', '{OTHER_FIRM}', '{OTHER_CLIENT}', '2026-04-01', 'finalized');")
        stmts.append("INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                     f"VALUES ('{OTHER_RUN}', '77900000-0000-0000-0000-0000000000e9', 999999, 999999);")
        seed = _psql(dsn, "\n".join(stmts))
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(f"{admin} dbname=postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _ids(*ids):
    return "ARRAY[" + ",".join(f"'{i}'" for i in ids) + "]::uuid[]"


def _call(dsn, fn, firm, ids):
    out = _psql(dsn, f"SELECT public.{fn}('{firm}', {_ids(*ids)})")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _slip_rows():
    rows = []
    for i, (_month, slips) in SPEC.items():
        for (emp, gross, net, tds, pt, pf_ee, pf_er, esi_ee, esi_er) in slips:
            name, pan, desig, dept = NAMES[emp]
            rows.append({"run_id": RUN[i], "employee_id": emp, "gross_paise": gross, "net_paise": net, "tds_paise": tds, "pt_paise": pt,
                         "pf_employee_paise": pf_ee, "pf_employer_paise": pf_er, "esi_employee_paise": esi_ee, "esi_employer_paise": esi_er,
                         "payroll_employees": {"name": name, "pan": pan, "designation": desig, "department": dept}})
    return rows


def test_the_run_figures_are_the_ones_the_python_path_adds_up(db):
    ids = [RUN[1], RUN[2], RUN[3], NOBODYS_RUN]
    via_sql = prs.run_totals_from_answer(ids, _call(db, "payroll_run_summaries", FIRM, ids))
    via_python = prs.run_totals_from_slips(ids, _slip_rows())
    assert via_sql == via_python
    assert via_sql[RUN[2]]["slip_count"] == 2 and via_sql[RUN[2]]["esi_count"] == 1 and via_sql[RUN[1]]["pf_count"] == 1
    assert via_sql[NOBODYS_RUN]["slip_count"] == 0


def test_the_year_end_rows_are_the_ones_the_python_path_adds_up(db):
    ids = [RUN[1], RUN[2], RUN[3]]
    via_sql = prs.employee_totals_from_answer(_call(db, "payroll_year_end_totals", FIRM, ids))
    via_python = prs.employee_totals_from_slips(_slip_rows())
    assert via_sql == via_python
    assert [r["employee"]["name"] for r in via_sql] == ["Asha", "bala", "Chitra"], "ordered by name, case-folded"
    assert via_sql[0]["months"] == 2 and via_sql[0]["gross_paise"] == 10000000


def test_another_firms_run_adds_nothing(db):
    ids = [RUN[1], OTHER_RUN]
    assert prs.run_totals_from_answer(ids, _call(db, "payroll_run_summaries", FIRM, ids))[OTHER_RUN]["slip_count"] == 0
    rows = _call(db, "payroll_year_end_totals", FIRM, ids)
    assert sum(r["gross_paise"] for r in rows) == 5000000


def test_an_empty_list_is_an_empty_document_and_not_a_null(db):
    assert _call(db, "payroll_run_summaries", FIRM, []) == []
    assert _call(db, "payroll_year_end_totals", FIRM, []) == []


def test_an_employee_whose_row_is_gone_gives_no_employee(db):
    assert _psql(db, "ALTER TABLE payroll_slips DISABLE TRIGGER USER; ALTER TABLE payroll_slips DROP CONSTRAINT IF EXISTS payroll_slips_employee_id_fkey; "
                     f"DELETE FROM payroll_employees WHERE id = '{E3}';").returncode == 0
    rows = prs.employee_totals_from_answer(_call(db, "payroll_year_end_totals", FIRM, [RUN[3]]))
    gone = [r for r in rows if r["employee_id"] == E3]
    assert gone and gone[0]["employee"] is None


def test_a_signed_in_session_cannot_call_either_function_and_the_service_role_can(db):
    for fn in ("payroll_run_summaries(uuid, uuid[])", "payroll_year_end_totals(uuid, uuid[])"):
        for role in ("authenticated", "anon"):
            assert _psql(db, f"SELECT has_function_privilege('{role}', 'public.{fn}', 'EXECUTE')").stdout.strip() == "f", (fn, role)
        assert _psql(db, f"SELECT has_function_privilege('service_role', 'public.{fn}', 'EXECUTE')").stdout.strip() == "t", fn
