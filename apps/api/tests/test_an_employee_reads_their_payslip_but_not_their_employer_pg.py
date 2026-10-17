"""Why the employee's payslip download reads its employer block with the privileged client (ledger POST-A-220).

THE QUESTION
    `routers/portal_employee.employee_payslip_pdf` proves the slip is the caller's own and released, then renders it with
    `services.payslip_pdf_service.get_payslip_pdf`. Every read in that renderer used `core.supabase_client.get_supabase`,
    which with `USE_USER_JWT` on (the production default) is the CALLER's own sign-in, row security in force. An employee
    principal has no `users` row, so `get_my_firm_id()` is NULL for them. If row security hides the `clients` row the
    letterhead is read from, `load_employer` raises "not found" and the route answers 409 to every employee for every
    slip: a download that ownership had already approved, refused by a screen that says the payslip cannot be produced.

WHAT IS HELD (a real database, the employee signed in as a role with a JWT whose `sub` is their auth id)
    * the reads the renderer makes on the employee's OWN sign-in work: their slip joined to their own employee row and to the
      released run (the columns the renderer selects), and the year-to-date rows;
    * the `clients` row the employer block is read from, and the registrations beside it, are NOT readable: that is the
      reason the route passes the privileged client for the employer block, and only for it;
    * THE SERVICE FUNCTIONS THEMSELVES run unmodified against that database (a duck-typed client that sends each query
      as the employee's own sign-in): `load_employer` on the employee's sign-in refuses (the old 409), `load_employer`
      handed the privileged client returns the letterhead AND the registrations, and `load_ytd` on the employee's
      sign-in still counts their own released runs;
    * a colleague's slip is not readable on the employee's own sign-in either (so keeping the slip and year-to-date reads
      on the employee's own sign-in leaves the database as a second check on whose slip it is).

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the employee payslip read proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000220"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000220"
EMP_A = "cccccccc-0000-0000-0000-00000000022a"
EMP_B = "cccccccc-0000-0000-0000-00000000022b"
AUTH_A = "22222222-2222-2222-2222-000000000220"
AUTH_B = "33333333-3333-3333-3333-000000000220"
AUTH_STAFF = "11111111-1111-1111-1111-000000000220"
RUN = "dddddddd-0000-0000-0000-000000000220"
SLIP_A = "eeeeeeee-0000-0000-0000-00000000022a"
SLIP_B = "eeeeeeee-0000-0000-0000-00000000022b"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as_employee_a(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = f'{{"sub": "{AUTH_A}", "role": "authenticated"}}'
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _count(dsn: str, sql: str) -> int:
    r = _as_employee_a(dsn, sql)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"slip_m220_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_STAFF}','staff@m220.test'), ('{AUTH_A}','a@m220.test'), ('{AUTH_B}','b@m220.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M220 Firm','m220@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, legal_name)
              VALUES ('{CLIENT}','{FIRM}','M220 Employer','Private Limited','M220 Employer Pvt Ltd');
            INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role)
              VALUES (gen_random_uuid(),'{FIRM}','{AUTH_STAFF}','Staff','staff@m220.test','Partner');
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled)
              VALUES ('{EMP_A}','{FIRM}','{CLIENT}','Employee A','{AUTH_A}',true),
                     ('{EMP_B}','{FIRM}','{CLIENT}','Employee B','{AUTH_B}',true);
            INSERT INTO payroll_runs (id, firm_id, client_id, month, status)
              VALUES ('{RUN}','{FIRM}','{CLIENT}','2026-06','finalized');
            INSERT INTO payroll_slips (id, run_id, employee_id, gross_paise, net_paise)
              VALUES ('{SLIP_A}','{RUN}','{EMP_A}',5000000,4500000), ('{SLIP_B}','{RUN}','{EMP_B}',9000000,8100000);
            INSERT INTO client_statutory_identity (firm_id, client_id, tan) VALUES ('{FIRM}','{CLIENT}','MUMA12345B');
        """, tuples=False)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_the_employee_reads_their_own_slip_with_the_employee_and_run_the_renderer_selects(db):
    n = _count(db, f"""
        SELECT count(*) FROM payroll_slips s
          JOIN payroll_employees e ON e.id = s.employee_id
          JOIN payroll_runs r ON r.id = s.run_id
         WHERE s.id = '{SLIP_A}';""")
    assert n == 1, "the employee cannot read their own slip with its employee and run: the renderer would fail earlier"


def test_the_year_to_date_rows_are_readable_on_the_employees_own_sign_in(db):
    assert _count(db, f"SELECT count(*) FROM payroll_runs WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}' "
                      "AND month IN ('2026-04','2026-05','2026-06');") == 1
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE run_id = '{RUN}' "
                      f"AND employee_id IN ('{EMP_A}');") == 1


def test_a_colleagues_slip_is_not_readable_on_the_employees_own_sign_in(db):
    assert _count(db, f"SELECT count(*) FROM payroll_slips WHERE id = '{SLIP_B}';") == 0


def test_the_employer_row_is_hidden_from_the_employee_which_is_why_the_route_passes_the_privileged_client(db):
    assert _count(db, f"SELECT count(*) FROM clients WHERE id = '{CLIENT}' AND firm_id = '{FIRM}';") == 0
    # the registrations beside it (TAN, establishment codes): a failure there is swallowed by the renderer and the line
    # is silently left off the payslip
    r = _as_employee_a(db, f"SELECT count(*) FROM client_statutory_identity WHERE client_id = '{CLIENT}';")
    assert (r.returncode != 0 and "permission denied" in r.stderr) or r.stdout.strip().splitlines()[-1] == "0", (
        r.stdout, r.stderr)
    # and the privileged connection (the admin here) does see the row, so the empty answer is row security and not a
    # missing seed
    assert _psql(db, f"SELECT count(*) FROM clients WHERE id = '{CLIENT}';").stdout.strip() == "1"


# ── the real service functions, run unmodified through the employee's own sign-in ─────────────────────────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Just enough of the Supabase client's chainable builder for `load_employer` and `load_ytd` to run UNMODIFIED."""

    def __init__(self, table: str, run):
        self._table, self._run = table, run
        self._select, self._where, self._single = "*", [], False

    def select(self, cols, *a, **k):
        self._select = cols
        return self

    @staticmethod
    def _q(v) -> str:
        return "'" + str(v).replace("'", "''") + "'"

    def eq(self, col, val):
        self._where.append(f"{col} = {self._q(val)}")
        return self

    def in_(self, col, vals):
        vals = list(vals)
        self._where.append("1=0" if not vals else f"{col} IN ({','.join(self._q(v) for v in vals)})")
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        sql = f"SELECT {self._select} FROM {self._table}"
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        rows = self._run(sql)
        return _Result((rows[0] if rows else None) if self._single else rows)


class _SignInDb:
    """A client whose every query is sent as `auth_uid`'s own sign-in (the authenticated role with that JWT subject), or
    on the privileged connection when no uid is given. A refusal by the database raises, as PostgREST's error does."""

    def __init__(self, dsn: str, auth_uid: str | None):
        self._dsn, self._uid = dsn, auth_uid

    def _run(self, sql: str):
        wrapped = f"SELECT coalesce(json_agg(t), '[]'::json)::text FROM ({sql}) t;"
        if self._uid:
            claims = f'{{"sub": "{self._uid}", "role": "authenticated"}}'
            wrapped = f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; " + wrapped
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", wrapped],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else []

    def table(self, name: str):
        return _Query(name, self._run)


def test_load_employer_on_the_employees_own_sign_in_refuses_which_is_the_old_409(db):
    from services import payslip_pdf_service

    with pytest.raises(ValueError, match="not found for firm"):
        payslip_pdf_service.load_employer(FIRM, CLIENT, db=_SignInDb(db, AUTH_A))


def test_load_employer_handed_the_privileged_client_returns_the_letterhead_and_the_registrations(db):
    from services import payslip_pdf_service

    got = payslip_pdf_service.load_employer(FIRM, CLIENT, db=_SignInDb(db, None))
    assert got["client_name"] == "M220 Employer"
    assert got["tan"] == "MUMA12345B"


def test_load_ytd_on_the_employees_own_sign_in_counts_their_own_released_run_and_nobody_elses(monkeypatch, db):
    import core.supabase_client as sc
    from services import payslip_pdf_service

    monkeypatch.setattr(sc, "get_supabase", lambda: _SignInDb(db, AUTH_A))
    got = payslip_pdf_service.load_ytd(FIRM, CLIENT, "2026-06", [EMP_A, EMP_B])
    assert set(got) == {EMP_A}, "the employee's own sign-in must see their own slip and not their colleague's"
