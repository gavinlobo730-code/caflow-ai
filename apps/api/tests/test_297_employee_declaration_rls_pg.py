"""
Migration 297 — proves an employee may file their own declaration and nothing else.

WHAT IS AT STAKE
    Form 12BB is the employee's statement (Rule 26C), so the self-service
    portal has to be able to write it. Migration 296 created the tables
    staff-only, which is right for a CA keying in a paper form and leaves the
    portal unable to do the one thing it exists for.

    Widening a write path on a table holding one person's salary reliefs is
    exactly where an RLS mistake costs something. Three separate boundaries
    have to hold at once, and each is tested here against real PostgreSQL
    rather than reasoned about:

      1. ROW scope   — an employee reaches their own declaration and no other's.
      2. COLUMN scope — an employee may declare an amount but never verify it.
                        A row policy cannot express this, so 297 uses a trigger;
                        these tests are what prove the trigger fires.
      3. TIME scope   — once the CA has verified the proofs the employee can no
                        longer move the figures underneath them.

Simulates an authenticated PostgREST session exactly as
test_262_employee_portal_rls_pg.py does: `SET request.jwt.claims` +
`SET ROLE authenticated`, matching how the Supabase pooler sets up a request.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
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
    reason="employee declaration RLS proof requires HARNESS_PG + psql",
)

EMP_A = "cccccccc-0000-0000-0000-0000000002a1"
EMP_B = "cccccccc-0000-0000-0000-0000000002b1"
AUTH_A = "22222222-2222-2222-2222-222222222297"
AUTH_B = "33333333-3333-3333-3333-333333333297"
AUTH_STAFF = "11111111-1111-1111-1111-111111111297"
FIRM = "aaaaaaaa-0000-0000-0000-000000000297"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000297"
DECL_A = "dddddddd-0000-0000-0000-0000000002a1"
DECL_B = "dddddddd-0000-0000-0000-0000000002b1"
FY = "2026-27"

RENT_A = 24000000   # ₹2,40,000 in paise
RENT_B = 60000000   # ₹6,00,000 in paise — unmistakably not A's


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
    """One firm, one staff Partner, two portal employees, one declaration each."""
    admin = _ADMIN.strip()
    dbname = f"m297_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert "297_let_an_employee_file_their_own_declaration.sql" not in pg_template.failed
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_STAFF}','staff297@test.in'),
              ('{AUTH_A}','emp-a297@test.in'),
              ('{AUTH_B}','emp-b297@test.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M297 Firm','m297@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT}','{FIRM}','M297 Client','Private Limited');
            INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
              (gen_random_uuid(),'{FIRM}','{AUTH_STAFF}','Staff','staff297@test.in','Partner');
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled)
              VALUES ('{EMP_A}','{FIRM}','{CLIENT}','Employee A','{AUTH_A}',true),
                     ('{EMP_B}','{FIRM}','{CLIENT}','Employee B','{AUTH_B}',true);
            INSERT INTO payroll_it_declarations
              (id, firm_id, client_id, employee_id, fy, regime, status,
               rent_paid_declared_paise, landlord_name, landlord_pan)
              VALUES
              ('{DECL_A}','{FIRM}','{CLIENT}','{EMP_A}','{FY}','old','submitted',
               {RENT_A},'A Landlord','ABCDE1234F'),
              ('{DECL_B}','{FIRM}','{CLIENT}','{EMP_B}','{FY}','old','submitted',
               {RENT_B},'B Landlord','ABCDE1234F');
            INSERT INTO payroll_it_declaration_items
              (id, firm_id, declaration_id, section, label, amount_declared_paise)
              VALUES (gen_random_uuid(),'{FIRM}','{DECL_A}','80C','PPF',15000000),
                     (gen_random_uuid(),'{FIRM}','{DECL_B}','80C','ELSS',15000000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _scalar(dsn: str, auth: str, sql: str) -> str:
    r = _psql(dsn, _as(auth) + sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _refused(dsn: str, auth: str, sql: str) -> subprocess.CompletedProcess:
    """Run as `auth` and require the statement to be REFUSED.

    A row-level policy silently affects zero rows rather than erroring, so an
    UPDATE that RLS blocks returns 0 with returncode 0. Both shapes count as a
    refusal; what must never happen is the write landing.
    """
    return _psql(dsn, _as(auth) + sql)


# ─── 1. Row scope ────────────────────────────────────────────────────────────

def test_employee_reads_their_own_declaration(seeded):
    assert _scalar(seeded, AUTH_A,
                   "SELECT rent_paid_declared_paise FROM payroll_it_declarations;"
                   ) == str(RENT_A)


def test_employee_cannot_read_another_employees_declaration(seeded):
    """The disclosure this migration risks: a colleague's rent, landlord and
    investments."""
    r = _psql(seeded, _as(AUTH_A) +
              "SELECT rent_paid_declared_paise FROM payroll_it_declarations ORDER BY 1;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [str(RENT_A)], "employee can read another's declaration"


def test_employee_cannot_read_another_employees_items(seeded):
    assert _scalar(seeded, AUTH_A,
                   "SELECT count(*) FROM payroll_it_declaration_items;") == "1"
    assert _scalar(seeded, AUTH_A,
                   "SELECT label FROM payroll_it_declaration_items;") == "PPF"


def test_employee_can_file_their_own_declaration(seeded):
    """The point of the migration. Before 297 this inserted nothing: 296's
    restrictive policy required Manager, which no employee is."""
    _psql(seeded, f"DELETE FROM payroll_it_declarations WHERE id='{DECL_A}';")
    r = _psql(seeded, _as(AUTH_A) + f"""
        INSERT INTO payroll_it_declarations
          (firm_id, client_id, employee_id, fy, regime, rent_paid_declared_paise)
        VALUES ('{FIRM}','{CLIENT}','{EMP_A}','{FY}','old', 12000000);
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(seeded, AUTH_A,
                   "SELECT rent_paid_declared_paise FROM payroll_it_declarations;") == "12000000"


def test_employee_can_update_their_own_declaration(seeded):
    r = _psql(seeded, _as(AUTH_A) +
              "UPDATE payroll_it_declarations SET rent_paid_declared_paise = 30000000;")
    assert r.returncode == 0, r.stderr
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT rent_paid_declared_paise FROM payroll_it_declarations "
                   f"WHERE id='{DECL_A}';") == "30000000"


def test_employee_cannot_file_a_declaration_for_someone_else(seeded):
    r = _refused(seeded, AUTH_A, f"""
        INSERT INTO payroll_it_declarations
          (firm_id, client_id, employee_id, fy, regime)
        VALUES ('{FIRM}','{CLIENT}','{EMP_B}','2027-28','old');
    """)
    assert r.returncode != 0, "employee filed a declaration in another's name"


def test_employee_cannot_edit_another_employees_declaration(seeded):
    _refused(seeded, AUTH_A,
             f"UPDATE payroll_it_declarations SET rent_paid_declared_paise = 1 "
             f"WHERE id='{DECL_B}';")
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT rent_paid_declared_paise FROM payroll_it_declarations "
                   f"WHERE id='{DECL_B}';") == str(RENT_B), "B's declaration was altered"


def test_employee_cannot_delete_a_declaration(seeded):
    """Withdrawing a claim is an edit to nil, which leaves a record. A delete
    would leave none."""
    _refused(seeded, AUTH_A, f"DELETE FROM payroll_it_declarations WHERE id='{DECL_A}';")
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT count(*) FROM payroll_it_declarations WHERE id='{DECL_A}';") == "1"


def test_employee_cannot_move_their_declaration_to_another_client(seeded):
    r = _refused(seeded, AUTH_A,
                 f"UPDATE payroll_it_declarations SET employee_id='{EMP_B}' "
                 f"WHERE id='{DECL_A}';")
    assert r.returncode != 0
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT employee_id FROM payroll_it_declarations "
                   f"WHERE id='{DECL_A}';") == EMP_A


# ─── 2. Column scope: nobody verifies their own proofs ───────────────────────

def test_employee_cannot_verify_their_own_rent(seeded):
    r = _refused(seeded, AUTH_A,
                 "UPDATE payroll_it_declarations SET rent_paid_verified_paise = 30000000;")
    assert r.returncode != 0, "employee verified their own rent"
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT rent_paid_verified_paise FROM payroll_it_declarations "
                   f"WHERE id='{DECL_A}';") == "0"


def test_employee_cannot_mark_their_own_proofs_verified(seeded):
    """The single most valuable write to steal: proofs_verified is what keeps a
    declared figure reducing tax after the Q4 cutoff."""
    r = _refused(seeded, AUTH_A,
                 "UPDATE payroll_it_declarations SET proofs_verified = true;")
    assert r.returncode != 0
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT proofs_verified FROM payroll_it_declarations "
                   f"WHERE id='{DECL_A}';") == "f"


def test_employee_cannot_insert_a_pre_verified_declaration(seeded):
    """Blocking UPDATE is not enough on its own — an employee who could INSERT
    a row already marked verified would bypass the check entirely."""
    _psql(seeded, f"DELETE FROM payroll_it_declarations WHERE id='{DECL_A}';")
    r = _refused(seeded, AUTH_A, f"""
        INSERT INTO payroll_it_declarations
          (firm_id, client_id, employee_id, fy, regime,
           rent_paid_declared_paise, rent_paid_verified_paise, proofs_verified)
        VALUES ('{FIRM}','{CLIENT}','{EMP_A}','{FY}','old', 30000000, 30000000, true);
    """)
    assert r.returncode != 0, "employee inserted a declaration already verified"


def test_employee_cannot_verify_a_chapter_via_line(seeded):
    r = _refused(seeded, AUTH_A,
                 "UPDATE payroll_it_declaration_items SET amount_verified_paise = 15000000;")
    assert r.returncode != 0
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT sum(amount_verified_paise) FROM payroll_it_declaration_items "
                   f"WHERE declaration_id='{DECL_A}';") == "0"


def test_employee_cannot_mark_a_line_verified(seeded):
    r = _refused(seeded, AUTH_A,
                 "UPDATE payroll_it_declaration_items SET status = 'verified';")
    assert r.returncode != 0


def test_employee_may_still_replace_their_own_lines(seeded):
    """Re-declaring replaces the whole set, so the owner must be able to delete
    and re-insert their own lines — the one DELETE 297 widens."""
    r = _psql(seeded, _as(AUTH_A) + f"""
        DELETE FROM payroll_it_declaration_items WHERE declaration_id='{DECL_A}';
        INSERT INTO payroll_it_declaration_items
          (firm_id, declaration_id, section, label, amount_declared_paise)
        VALUES ('{FIRM}','{DECL_A}','80D-self','Health cover', 2500000);
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(seeded, AUTH_A,
                   "SELECT label FROM payroll_it_declaration_items;") == "Health cover"


def test_employee_cannot_delete_another_employees_line(seeded):
    _refused(seeded, AUTH_A,
             f"DELETE FROM payroll_it_declaration_items WHERE declaration_id='{DECL_B}';")
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT count(*) FROM payroll_it_declaration_items "
                   f"WHERE declaration_id='{DECL_B}';") == "1"


# ─── 3. Time scope: verified is final, as far as the employee is concerned ───

def test_employee_cannot_edit_a_declaration_after_it_is_verified(seeded):
    """Payroll is withholding on the checked figures by now. Letting the
    employee move them afterwards would leave a verified proof attached to an
    unverified amount."""
    v = _psql(seeded, f"""
        UPDATE payroll_it_declarations
        SET proofs_verified = true, rent_paid_verified_paise = {RENT_A},
            status = 'verified'
        WHERE id='{DECL_A}';
    """)
    assert v.returncode == 0, v.stderr
    _refused(seeded, AUTH_A,
             "UPDATE payroll_it_declarations SET rent_paid_declared_paise = 99900000;")
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT rent_paid_declared_paise FROM payroll_it_declarations "
                   f"WHERE id='{DECL_A}';") == str(RENT_A), "verified declaration was edited"


def test_a_verified_declaration_is_still_readable_by_its_owner(seeded):
    """Locked for writing, not hidden. The employee has to be able to see what
    was allowed — it is the basis of their Form 16."""
    _psql(seeded, f"UPDATE payroll_it_declarations SET proofs_verified = true "
                  f"WHERE id='{DECL_A}';")
    assert _scalar(seeded, AUTH_A,
                   "SELECT rent_paid_declared_paise FROM payroll_it_declarations;"
                   ) == str(RENT_A)


# ─── Staff are unaffected throughout ─────────────────────────────────────────

def test_staff_can_still_verify(seeded):
    r = _psql(seeded, _as(AUTH_STAFF) + f"""
        UPDATE payroll_it_declarations
        SET proofs_verified = true, rent_paid_verified_paise = {RENT_A}
        WHERE id='{DECL_A}';
    """)
    assert r.returncode == 0, r.stderr
    assert _scalar(seeded, AUTH_STAFF,
                   f"SELECT rent_paid_verified_paise FROM payroll_it_declarations "
                   f"WHERE id='{DECL_A}';") == str(RENT_A)


def test_staff_still_see_every_declaration_in_the_firm(seeded):
    assert _scalar(seeded, AUTH_STAFF,
                   "SELECT count(*) FROM payroll_it_declarations;") == "2"
