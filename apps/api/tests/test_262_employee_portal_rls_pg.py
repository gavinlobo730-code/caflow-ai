"""
Migration 262 — proves the employee portal's read access on real PostgreSQL.

THE BUG THIS PINS
    app/portal/employee/page.tsx reads payroll_employees, payroll_slips and
    leave_balances. Before 262 an employee could read NONE of them — not even
    their own payroll_employees row, despite migration 031 adding
    `employee_sees_own_record` for exactly that purpose.

    031's policy is PERMISSIVE and correct; it just never had any effect,
    because a RESTRICTIVE policy added later ANDs with it:

        payroll_employees_assignment_scope  RESTRICTIVE  ALL
          USING can_access_client(client_id::text)

    can_access_client() collapses to NULL for a portal employee (client_id is
    NOT NULL; get_my_role() reads `users`, where a portal employee has no row,
    so `NULL = 'Partner'` is NULL not false; the assignment EXISTS is false),
    and RLS treats NULL as deny.

    That is why every count below was 0 before this migration. The tests are
    written so a revert fails loudly on BOTH halves — the reads that must now
    work, and the writes that must still not.

WHY THERE IS A STRUCTURAL TEST AS WELL AS BEHAVIOURAL ONES
    262 widens a RESTRICTIVE policy, the one policy class that can only be
    loosened by editing it in place. The obvious mistake is to widen the FOR
    ALL form; 262 splits it per command and puts the employee branch only on
    SELECT.

    Mutation testing showed the behavioural tests CANNOT see that difference:
    putting the employee branch on the UPDATE policy too leaves all of
    test_employee_cannot_* passing. That is not a missing assertion, it is an
    equivalent mutant — an employee is already blocked from writing by the
    PERMISSIVE layer (own_firm is gated on get_my_firm_id(), NULL for an
    employee; employee_sees_own_record is SELECT-only), so the RESTRICTIVE arm
    never gets to matter.

    The split earns its keep against the NEXT change: add a permissive write
    policy for employees — "let them edit their own bank details" — and a
    widened FOR ALL restrictive policy silently hands them their salary fields
    too. A property with no behavioural signature today has to be pinned on
    shape, which is what test_no_write_policy_admits_an_employee does. The
    behavioural test_employee_cannot_* tests stay because they pin the outcome
    a reader actually cares about, whichever layer delivers it.

Simulates an authenticated PostgREST session the way
_supabase_compat_bootstrap.sql's auth.uid()/auth.jwt() shims expect:
`SET request.jwt.claims = '{"sub": "<auth_user_id>"}'` + `SET ROLE
authenticated`, matching how the Supabase connection pooler sets up a request.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

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
    reason="employee portal RLS proof requires HARNESS_PG + psql",
)

# Fixed ids keep the assertions readable — GROSS_A vs GROSS_B is the whole
# point of the isolation tests, so the numbers are deliberately unmistakable.
EMP_A = "cccccccc-0000-0000-0000-00000000000a"
EMP_B = "cccccccc-0000-0000-0000-00000000000b"
AUTH_A = "22222222-2222-2222-2222-222222222222"
AUTH_B = "33333333-3333-3333-3333-333333333333"
AUTH_STAFF = "11111111-1111-1111-1111-111111111111"
SLIP_A = "eeeeeeee-0000-0000-0000-00000000000a"
RUN = "dddddddd-0000-0000-0000-000000000001"
FIRM = "aaaaaaaa-0000-0000-0000-000000000001"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000001"
GROSS_A = 5000000   # ₹50,000.00 in paise
GROSS_B = 9000000   # ₹90,000.00 in paise


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
            f"SET ROLE authenticated; ")


@pytest.fixture()
def seeded(pg_template):
    """One firm, one staff Partner, two portal employees each with a payslip
    and a leave balance, both in the SAME payroll run.

    Same run on purpose: it makes the payroll_runs test meaningful. A run is
    visible to an employee because it produced one of THEIR slips, and both
    employees legitimately see the same run row — what neither may see is the
    other's slip hanging off it.

    FINALIZED on purpose, since migration 323. The column defaults to 'draft',
    and this fixture used to take the default — so every assertion below was
    silently testing a run the employee should never have seen at all. 323 is
    what makes release part of the question; test_323_*.py owns the draft case.
    """
    admin = _ADMIN.strip()
    dbname = f"m262_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert "262_employee_portal_read_access.sql" not in pg_template.failed
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_STAFF}','staff@test.in'),
              ('{AUTH_A}','emp-a@test.in'),
              ('{AUTH_B}','emp-b@test.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M262 Firm','m262@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT}','{FIRM}','M262 Client','Private Limited');
            INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
              (gen_random_uuid(),'{FIRM}','{AUTH_STAFF}','Staff','staff@test.in','Partner');
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled)
              VALUES ('{EMP_A}','{FIRM}','{CLIENT}','Employee A','{AUTH_A}',true),
                     ('{EMP_B}','{FIRM}','{CLIENT}','Employee B','{AUTH_B}',true);
            INSERT INTO payroll_runs (id, firm_id, client_id, month, status)
              VALUES ('{RUN}','{FIRM}','{CLIENT}','2026-06','finalized');
            INSERT INTO payroll_slips (id, run_id, employee_id, gross_paise, net_paise) VALUES
              ('{SLIP_A}','{RUN}','{EMP_A}',{GROSS_A},4500000),
              ('eeeeeeee-0000-0000-0000-00000000000b','{RUN}','{EMP_B}',{GROSS_B},8100000);
            INSERT INTO leave_balances (id, firm_id, employee_id, year) VALUES
              (gen_random_uuid(),'{FIRM}','{EMP_A}',2026),
              (gen_random_uuid(),'{FIRM}','{EMP_B}',2026);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _scalar(dsn: str, auth: str, sql: str) -> str:
    r = _psql(dsn, _as(auth) + sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ─── reads that must now work ────────────────────────────────────────────────

def test_employee_sees_own_record(seeded):
    """031's policy finally takes effect. Before 262 this was ''."""
    assert _scalar(seeded, AUTH_A, "SELECT name FROM payroll_employees;") == "Employee A"


def test_employee_sees_own_payslip(seeded):
    assert _scalar(seeded, AUTH_A, "SELECT gross_paise FROM payroll_slips;") == str(GROSS_A)


def test_employee_sees_own_leave_balance(seeded):
    assert _scalar(seeded, AUTH_A, "SELECT count(*) FROM leave_balances;") == "1"


def test_employee_sees_the_run_behind_their_payslip(seeded):
    """The portal reads payroll_slips with a payroll_runs!inner(month) embed,
    and PostgREST's inner join drops the slip unless the parent run is visible.
    Without this policy the payslips tab would stay empty even with the slip
    policy in place — the failure mode that is invisible in a policy listing."""
    assert _scalar(seeded, AUTH_A, "SELECT month FROM payroll_runs;") == "2026-06"


def test_the_salary_slips_view_resolves_for_an_employee(seeded):
    """salary_slips (migration 072) is security_invoker and JOINs payroll_runs,
    so it needs BOTH new policies to return anything. It is the view the portal
    was originally built against, and the API's payslip PDF endpoint shares its
    slip id, so it has to work for an employee too — not just the direct query
    the page uses today."""
    got = _scalar(seeded, AUTH_A,
                  "SELECT month||'/'||year||'/'||gross_salary_paise FROM salary_slips;")
    assert got == f"6/2026/{GROSS_A}"


# ─── isolation: one employee must never see another ──────────────────────────

def test_employee_sees_only_their_own_payslip(seeded):
    """The disclosure this whole migration risks. A wrong scope here leaks a
    colleague's salary."""
    r = _psql(seeded, _as(AUTH_A) + "SELECT gross_paise FROM payroll_slips ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [str(GROSS_A)], "employee can see another employee's payslip"


def test_employee_cannot_see_the_other_employees_record(seeded):
    assert _scalar(seeded, AUTH_A, f"SELECT count(*) FROM payroll_employees WHERE id='{EMP_B}';") == "0"


def test_employee_cannot_see_the_other_employees_leave_balance(seeded):
    assert _scalar(seeded, AUTH_A, f"SELECT count(*) FROM leave_balances WHERE employee_id='{EMP_B}';") == "0"


def test_an_authenticated_stranger_sees_nothing(seeded):
    """A logged-in identity that is neither staff nor an employee — e.g. a
    client-portal contact."""
    stranger = str(uuid.uuid4())
    assert _scalar(seeded, stranger,
                   "SELECT (SELECT count(*) FROM payroll_employees)"
                   "+(SELECT count(*) FROM payroll_slips)"
                   "+(SELECT count(*) FROM leave_balances)"
                   "+(SELECT count(*) FROM payroll_runs);") == "0"


# ─── writes that must still be denied ────────────────────────────────────────

def test_employee_cannot_raise_their_own_pay(seeded):
    """The reason the RESTRICTIVE policy is split per command instead of just
    widened. UPDATE reports 0 rows rather than erroring: RLS filters the row out
    of the update set, which is the intended outcome."""
    r = _psql(seeded, _as(AUTH_A) + f"UPDATE payroll_employees SET basic_paise=99999999 WHERE id='{EMP_A}';")
    assert r.returncode == 0, r.stderr
    assert _psql(seeded, f"SELECT basic_paise FROM payroll_employees WHERE id='{EMP_A}';",
                 tuples=True).stdout.strip() == "0"


def test_employee_cannot_edit_their_own_payslip(seeded):
    r = _psql(seeded, _as(AUTH_A) + f"UPDATE payroll_slips SET net_paise=99999999 WHERE id='{SLIP_A}';")
    assert r.returncode == 0, r.stderr
    assert _psql(seeded, f"SELECT net_paise FROM payroll_slips WHERE id='{SLIP_A}';",
                 tuples=True).stdout.strip() == "4500000"


def test_employee_cannot_delete_their_own_record(seeded):
    r = _psql(seeded, _as(AUTH_A) + f"DELETE FROM payroll_employees WHERE id='{EMP_A}';")
    assert r.returncode == 0, r.stderr
    assert _psql(seeded, f"SELECT count(*) FROM payroll_employees WHERE id='{EMP_A}';",
                 tuples=True).stdout.strip() == "1"


def test_employee_cannot_invent_a_payslip(seeded):
    r = _psql(seeded, _as(AUTH_A) +
              f"INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
              f"VALUES ('{RUN}','{EMP_A}',1,1);")
    assert r.returncode != 0
    assert "row-level security" in r.stderr.lower()


# ─── the portal_enabled switch actually withdraws access ─────────────────────

def test_switching_the_portal_off_withdraws_the_data(seeded):
    """Not cosmetic: the page filters on portal_enabled, but a filter in the
    page is not a control — anyone can call PostgREST directly. 262 gates the
    rows on the same flag so switching it off is a real revocation."""
    assert _scalar(seeded, AUTH_A, "SELECT count(*) FROM payroll_slips;") == "1"

    off = _psql(seeded, f"UPDATE payroll_employees SET portal_enabled=false WHERE id='{EMP_A}';")
    assert off.returncode == 0, off.stderr

    assert _scalar(seeded, AUTH_A,
                   "SELECT (SELECT count(*) FROM payroll_employees)"
                   "+(SELECT count(*) FROM payroll_slips)"
                   "+(SELECT count(*) FROM leave_balances)"
                   "+(SELECT count(*) FROM payroll_runs);") == "0"


# ─── staff must be completely unaffected ─────────────────────────────────────

def test_staff_still_see_the_whole_firm(seeded):
    """262 rewrites policies staff depend on (one FOR ALL split into four).
    A mistake there would break the payroll screen for the CA — a far worse
    outcome than the portal staying blank."""
    assert _scalar(seeded, AUTH_STAFF,
                   "SELECT (SELECT count(*) FROM payroll_employees)||'/'"
                   "||(SELECT count(*) FROM payroll_slips)||'/'"
                   "||(SELECT count(*) FROM leave_balances)||'/'"
                   "||(SELECT count(*) FROM payroll_runs);") == "2/2/2/1"


def test_staff_can_still_write_payroll(seeded):
    """The per-command split must not have dropped the staff write path."""
    r = _psql(seeded, _as(AUTH_STAFF) +
              f"UPDATE payroll_employees SET designation='Senior' WHERE id='{EMP_A}';")
    assert r.returncode == 0, r.stderr
    assert _psql(seeded, f"SELECT designation FROM payroll_employees WHERE id='{EMP_A}';",
                 tuples=True).stdout.strip() == "Senior"


def test_no_write_policy_admits_an_employee(seeded):
    """The employee branch must appear on SELECT policies ONLY.

    This is the structural half described in the module docstring: it has no
    behavioural signature today, so it is asserted on policy shape. It fails
    the moment someone re-merges the split back into a FOR ALL policy, or
    copies the `my_employee_ids()` branch onto a write verb — either of which
    turns a future employee-write policy into a salary-editing hole.
    """
    r = _psql(seeded,
              "SELECT tablename||'.'||policyname||' ('||cmd||')' "
              "FROM pg_policies WHERE schemaname='public' "
              "  AND tablename IN ('payroll_employees','payroll_runs','payroll_slips','leave_balances') "
              "  AND cmd <> 'SELECT' "
              "  AND (coalesce(qual,'')||coalesce(with_check,'')) "
              "      ~ 'my_employee_ids|my_payroll_run_ids' "
              "ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    offenders = [x for x in r.stdout.split("\n") if x.strip()]
    assert not offenders, (
        "these non-SELECT policies let a portal employee through:\n  "
        + "\n  ".join(offenders)
        + "\nThe employee exception is read-only by design — see migration 262."
    )


def test_the_assignment_scope_policies_are_still_split_per_command(seeded):
    """Vacuity guard for the test above: if the FOR ALL policies came back, the
    employee branch could sit on an ALL policy, which pg_policies reports as
    cmd='ALL' — not matched by `cmd <> 'SELECT'` in the way a reader expects,
    and the check above would pass while the property was broken."""
    r = _psql(seeded,
              "SELECT tablename||'.'||policyname FROM pg_policies "
              "WHERE schemaname='public' AND permissive='RESTRICTIVE' AND cmd='ALL' "
              "  AND tablename IN ('payroll_employees','payroll_runs') "
              "  AND policyname LIKE '%assignment_scope%' ORDER BY 1;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert not r.stdout.strip(), (
        f"assignment-scope policy is FOR ALL again: {r.stdout.strip()} — "
        "262 split these per command so the employee read exception cannot "
        "reach a write verb.")


def test_one_auth_identity_cannot_own_two_employee_records(seeded):
    """Every policy above scopes by auth_user_id. Without the unique index two
    employee rows could share one, and each would see the other's payslips —
    the precise leak these policies exist to prevent."""
    r = _psql(seeded, f"UPDATE payroll_employees SET auth_user_id='{AUTH_A}' WHERE id='{EMP_B}';")
    assert r.returncode != 0
    assert "unique" in r.stderr.lower() or "duplicate" in r.stderr.lower()
