"""Migration 519 — the declaration tables ask the per-person grid, and three client-level payroll tables are written by the API only.

WHAT IS HELD (ledger POST-A-219, parts 1 and 3)
    PART 1 — `payroll_it_declarations` and `payroll_it_declaration_items`
      * all six restrictive write policies ask `my_permission('payroll','write',...)`: a Manager with NO grid row still writes (the
        floor is unchanged, so production's empty `user_permissions` behaves as before), and with `payroll:write` refused for that
        person the same statements are refused (the finding), on the declaration, its items, and (for a Partner) the delete;
      * the other direction: an Executive the grid grants `payroll:write` and `payroll:read` can write;
      * the EMPLOYEE's own unverified declaration is still writable by the employee, whatever the grid says about any staff member;
      * the policies in the migration-built database are the ones this file names, and the rollback puts them back on the role.
    PART 2 — `client_payroll_settings`, `client_statutory_identity`, `client_pt_registrations`
      * a signed-in role EFFECTIVELY holds no INSERT, UPDATE, DELETE or TRUNCATE on any of them, at table level, column level (332
        gave `client_payroll_settings` column grants) or through PUBLIC; reading is unaffected; `service_role` keeps its writes;
      * an assigned Manager is refused by the PRIVILEGE, not by a policy;
      * the migration removes what the hosting platform's defaults give, fails itself when a write cannot be revoked, skips a table
        that does not exist, and is idempotent; its own rollback puts the grants back, which is the negative control.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests._signed_in_payroll_writes import give_the_signed_in_payroll_access_back

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_STEM = "519_the_declaration_tables_ask_the_grid_and_the_three_client_payroll_tables_are_written_by_the_api_only"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the privilege and policy proofs require HARNESS_PG + psql",
)

FIRM = "51900000-0000-0000-0000-000000000001"
CLIENT = "51900000-0000-0000-0000-0000000000c1"
PARTNER, MANAGER, EXECUTIVE = (f"51900000-0000-0000-0000-00000000000{c}" for c in "abe")
AUTH_PARTNER, AUTH_MANAGER, AUTH_EXECUTIVE, AUTH_EMPLOYEE = (
    f"51900000-1111-0000-0000-00000000000{c}" for c in "abef")
EMPLOYEE = "51900000-0000-0000-0000-0000000000e1"
DECLARATION = "51900000-0000-0000-0000-0000000000d1"
ITEM = "51900000-0000-0000-0000-0000000000d2"
TABLES = ("client_payroll_settings", "client_statutory_identity", "client_pt_registrations")
WRITES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, auth: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": auth, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _last(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1].strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"decl_m519_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert f"{_STEM}.sql" not in pg_template.failed, "migration 519 did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_PARTNER}','p@m519.test'), ('{AUTH_MANAGER}','m@m519.test'),
              ('{AUTH_EXECUTIVE}','e@m519.test'), ('{AUTH_EMPLOYEE}','emp@m519.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M519 Firm','m519@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{PARTNER}','{FIRM}','{AUTH_PARTNER}','p@m519.test','P','Partner',true),
              ('{MANAGER}','{FIRM}','{AUTH_MANAGER}','m@m519.test','M','Manager',true),
              ('{EXECUTIVE}','{FIRM}','{AUTH_EXECUTIVE}','e@m519.test','E','Executive',true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES
              ('{FIRM}','{PARTNER}','{CLIENT}'), ('{FIRM}','{MANAGER}','{CLIENT}'), ('{FIRM}','{EXECUTIVE}','{CLIENT}');
            INSERT INTO payroll_employees (id, firm_id, client_id, name, auth_user_id, portal_enabled)
              VALUES ('{EMPLOYEE}','{FIRM}','{CLIENT}','Employee','{AUTH_EMPLOYEE}',true);
            INSERT INTO payroll_it_declarations (id, firm_id, client_id, employee_id, fy, regime, status, rent_paid_declared_paise)
              VALUES ('{DECLARATION}','{FIRM}','{CLIENT}','{EMPLOYEE}','2026-27','old','submitted',100);
            INSERT INTO payroll_it_declaration_items (id, firm_id, declaration_id, section, label, amount_declared_paise)
              VALUES ('{ITEM}','{FIRM}','{DECLARATION}','80C','PPF',100);
            INSERT INTO client_payroll_settings (firm_id, client_id, inputs_due_day) VALUES ('{FIRM}','{CLIENT}',5);
            INSERT INTO client_statutory_identity (firm_id, client_id, tan) VALUES ('{FIRM}','{CLIENT}','MUMA12345B');
            INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number)
              VALUES ('{FIRM}','{CLIENT}','MH','PTRC-1');
        """)
        assert seed.returncode == 0, seed.stderr
        give_the_signed_in_payroll_access_back(dsn)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _grant(dsn: str, user: str, resource: str, action: str, granted: bool) -> None:
    _ok(dsn, f"""INSERT INTO user_permissions (firm_id, user_id, resource, action, granted)
                 VALUES ('{FIRM}','{user}','{resource}','{action}',{str(granted).lower()})
                 ON CONFLICT (user_id, resource, action) DO UPDATE SET granted = EXCLUDED.granted;""")


UPDATE_DECLARATION = f"UPDATE payroll_it_declarations SET rent_paid_declared_paise = 777 WHERE id = '{DECLARATION}'; SELECT count(*) FROM payroll_it_declarations WHERE rent_paid_declared_paise = 777;"
INSERT_ITEM = (f"INSERT INTO payroll_it_declaration_items (firm_id, declaration_id, section, label, amount_declared_paise) "
               f"VALUES ('{FIRM}','{DECLARATION}','80D','Health',50); SELECT count(*) FROM payroll_it_declaration_items;")
UPDATE_ITEM = f"UPDATE payroll_it_declaration_items SET amount_declared_paise = 777 WHERE id = '{ITEM}'; SELECT count(*) FROM payroll_it_declaration_items WHERE amount_declared_paise = 777;"
DELETE_ITEM = f"DELETE FROM payroll_it_declaration_items WHERE id = '{ITEM}'; SELECT count(*) FROM payroll_it_declaration_items;"


def _landed(r: subprocess.CompletedProcess, expected: str) -> bool:
    """A statement that a policy blocks either errors (WITH CHECK) or touches no row (USING): count what landed."""
    return r.returncode == 0 and r.stdout.strip().splitlines()[-1].strip() == expected


# ── PART 1: the declaration tables ───────────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_the_six_policies_ask_the_grid_and_keep_their_employee_arm(db):
    rows = _ok(db, """SELECT tablename || '.' || policyname || '|' || coalesce(qual,'') || '|' || coalesce(with_check,'')
                      FROM pg_policies WHERE schemaname='public' AND policyname LIKE '%\\_role\\_%'
                        AND tablename IN ('payroll_it_declarations','payroll_it_declaration_items') ORDER BY 1;""").splitlines()
    assert len(rows) == 6, rows
    for row in rows:
        # A delete asks `finalize` (Partner-only by default) and not `write`: a write grant must not carry a delete with it.
        action = "finalize" if "role_delete" in row else "write"
        assert f"my_permission('payroll'::text, '{action}'::text" in row, row
        assert "my_role_at_least" not in row, row
    for row in rows:
        if "role_delete" in row and "payroll_it_declarations." in row:
            assert "'Partner'" in row and "my_employee_ids" not in row, row       # a header is never deleted by its owner
        elif "payroll_it_declaration_items.payroll_it_declaration_items_role_delete" in row:
            assert "'Partner'" in row and "my_it_declaration_ids" in row, row
        elif "role_insert" in row or "role_update" in row:
            assert "'Manager'" in row, row
            assert "my_employee_ids" in row or "my_it_declaration_ids" in row, row


@_NEEDS_PG
def test_a_manager_with_no_grid_row_still_writes_the_declaration_and_its_items(db):
    """Premise and safety: production's user_permissions is empty, so the floor (Manager) is what decides, as before."""
    assert _landed(_as(db, AUTH_MANAGER, UPDATE_DECLARATION), "1")
    assert _landed(_as(db, AUTH_MANAGER, UPDATE_ITEM), "1")
    assert _landed(_as(db, AUTH_MANAGER, INSERT_ITEM), "2")


@_NEEDS_PG
@pytest.mark.parametrize("statement, expected_if_it_landed", [
    (UPDATE_DECLARATION, "1"), (UPDATE_ITEM, "1"), (INSERT_ITEM, "2"),
], ids=["update the declaration", "update an item", "insert an item"])
def test_a_denial_of_payroll_write_stops_a_manager_writing_a_declaration(db, statement, expected_if_it_landed):
    _grant(db, MANAGER, "payroll", "write", False)
    assert _last(_as(db, AUTH_MANAGER, "SELECT public.my_permission('payroll','write','Manager');")) == "f", "premise"
    assert not _landed(_as(db, AUTH_MANAGER, statement), expected_if_it_landed), "the denial did not reach the database"


@_NEEDS_PG
def test_a_denial_stops_a_partner_deleting_and_no_denial_lets_the_partner_delete(db):
    assert _landed(_as(db, AUTH_PARTNER, DELETE_ITEM), "0"), "premise: with no grid row a Partner deletes an item"
    _ok(db, f"INSERT INTO payroll_it_declaration_items (id, firm_id, declaration_id, section, label, amount_declared_paise) "
            f"VALUES ('{ITEM}','{FIRM}','{DECLARATION}','80C','PPF',100);")
    _grant(db, PARTNER, "payroll", "finalize", False)
    assert _last(_as(db, AUTH_PARTNER, "SELECT public.my_permission('payroll','finalize','Partner');")) == "f", "premise"
    assert not _landed(_as(db, AUTH_PARTNER, DELETE_ITEM), "0"), "a Partner denied payroll:finalize still deleted an item"
    assert _ok(db, "SELECT count(*) FROM payroll_it_declaration_items;") == "1"


@_NEEDS_PG
def test_a_write_grant_does_not_carry_a_delete_and_a_finalize_grant_does(db):
    """The delete's floor is Partner and the grid has no delete action: a grant of payroll:WRITE (so that someone can key monthly
    inputs) must not let them delete a declaration, and a deliberate grant of payroll:FINALIZE, which is Partner-only by default,
    does. An independent review of this migration found the first version asked `write` and a write grant carried the delete."""
    assert not _landed(_as(db, AUTH_MANAGER, DELETE_ITEM), "0"), "a Manager deleted an item with no grid row"
    _grant(db, MANAGER, "payroll", "write", True)
    assert not _landed(_as(db, AUTH_MANAGER, DELETE_ITEM), "0"), "a payroll:write grant carried a delete"
    _grant(db, MANAGER, "payroll", "finalize", True)
    assert _landed(_as(db, AUTH_MANAGER, DELETE_ITEM), "0")


@_NEEDS_PG
def test_a_grant_of_payroll_write_and_read_reaches_an_executive(db):
    assert not _landed(_as(db, AUTH_EXECUTIVE, UPDATE_DECLARATION), "1"), "premise: an Executive is below the floor"
    _grant(db, EXECUTIVE, "payroll", "read", True)
    _grant(db, EXECUTIVE, "payroll", "write", True)
    assert _landed(_as(db, AUTH_EXECUTIVE, UPDATE_DECLARATION), "1")


@_NEEDS_PG
def test_the_employees_own_unverified_declaration_is_still_theirs_to_write(db):
    """Every staff member blocked, and the employee still files their own: the employee arm of each policy is untouched."""
    for person in (PARTNER, MANAGER, EXECUTIVE):
        _grant(db, person, "payroll", "write", False)
    assert _landed(_as(db, AUTH_EMPLOYEE, UPDATE_DECLARATION), "1")
    assert _landed(_as(db, AUTH_EMPLOYEE, INSERT_ITEM), "2")
    _ok(db, f"UPDATE payroll_it_declarations SET proofs_verified = true WHERE id = '{DECLARATION}';")
    assert not _landed(_as(db, AUTH_EMPLOYEE, UPDATE_DECLARATION.replace("777", "888")), "1"), \
        "an employee changed a declaration after its proofs were verified"


@_NEEDS_PG
def test_the_rollback_puts_the_role_back_and_a_denial_stops_mattering(db):
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    rows = _ok(db, """SELECT policyname || '|' || coalesce(qual,'') || coalesce(with_check,'')
                      FROM pg_policies WHERE schemaname='public' AND policyname LIKE '%\\_role\\_%'
                        AND tablename IN ('payroll_it_declarations','payroll_it_declaration_items');""").splitlines()
    assert len(rows) == 6 and all("my_role_at_least" in row and "my_permission" not in row for row in rows), rows
    _grant(db, MANAGER, "payroll", "write", False)
    assert _landed(_as(db, AUTH_MANAGER, UPDATE_DECLARATION), "1"), "the negative control: with the role back, the denial is ignored again"


# ── PART 2: the three client-level payroll tables ────────────────────────────────────────────────────

def _holds(dsn: str, role: str, table: str, verb: str) -> bool:
    return _ok(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{verb}');") == "t"


def _holds_a_column_write(dsn: str, role: str, table: str, verb: str) -> bool:
    return _ok(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{table}', '{verb}');") == "t"


@_NEEDS_PG
@pytest.mark.parametrize("table", ["payroll_it_declarations", "payroll_it_declaration_items"])
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_signed_in_role_cannot_truncate_a_declaration_table_and_the_employee_still_writes_it(db, table, role):
    """TRUNCATE bypasses row security, PostgREST does not expose it, and nothing signed-in needs it: it is taken away from the two
    declaration tables as it was from the others (an independent review of this migration pointed out it had been left). The
    employee's own INSERT and UPDATE, which the browser still uses, are untouched."""
    assert not _holds(db, role, table, "TRUNCATE"), (role, table)
    if role == "authenticated":
        assert _holds(db, role, table, "INSERT") and _holds(db, role, table, "UPDATE")


@_NEEDS_PG
@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_signed_in_role_holds_no_write_on_the_three_tables(db, table, role):
    for verb in WRITES:
        assert not _holds(db, role, table, verb), (role, table, verb)
    assert not _holds_a_column_write(db, role, table, "INSERT") and not _holds_a_column_write(db, role, table, "UPDATE")


@_NEEDS_PG
@pytest.mark.parametrize("table", TABLES)
def test_reading_is_unaffected_and_the_api_keeps_its_writes(db, table):
    assert _holds(db, "authenticated", table, "SELECT")
    seen = _as(db, AUTH_MANAGER, f"SELECT count(*) FROM {table};")
    assert _last(seen) == "1", seen.stderr
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "service_role", table, verb), (table, verb)


PROBES = {
    "client_payroll_settings (insert)": ("INSERT INTO client_payroll_settings (firm_id, client_id, inputs_due_day) "
                                          f"VALUES ('{FIRM}','{CLIENT}',9);"),
    "client_payroll_settings (update)": "UPDATE client_payroll_settings SET inputs_due_day = 9;",
    "client_payroll_settings (delete)": "DELETE FROM client_payroll_settings;",
    "client_statutory_identity (update)": "UPDATE client_statutory_identity SET tan = 'ZZZZ99999Z';",
    "client_statutory_identity (delete)": "DELETE FROM client_statutory_identity;",
    "client_pt_registrations (update)": "UPDATE client_pt_registrations SET ptrc_number = 'FORGED';",
    "client_pt_registrations (delete)": "DELETE FROM client_pt_registrations;",
}


@_NEEDS_PG
@pytest.mark.parametrize("probe", sorted(PROBES))
def test_an_assigned_manager_is_refused_by_the_privilege(db, probe):
    table = probe.split(" ")[0]
    r = _as(db, AUTH_MANAGER, PROBES[probe])
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (probe, r.stderr or "it succeeded")


@_NEEDS_PG
def test_519_removes_what_the_platform_grants_and_what_reaches_a_role_another_way(db):
    _ok(db, """
        GRANT TRUNCATE ON public.client_payroll_settings, public.client_statutory_identity, public.client_pt_registrations
          TO authenticated, anon;
        GRANT INSERT, UPDATE, DELETE ON public.client_statutory_identity TO anon;
        GRANT INSERT ON public.client_pt_registrations TO PUBLIC;
        GRANT UPDATE (tan) ON public.client_statutory_identity TO authenticated;
        GRANT UPDATE (note) ON public.client_payroll_settings TO anon;
    """)
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    for table in TABLES:
        for role in ("authenticated", "anon"):
            for verb in WRITES:
                assert not _holds(db, role, table, verb), (role, table, verb)
            assert not _holds_a_column_write(db, role, table, "INSERT") and not _holds_a_column_write(db, role, table, "UPDATE")


@_NEEDS_PG
def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db):
    grantor = f"m519_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT UPDATE ON public.client_statutory_identity TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT UPDATE ON public.client_statutory_identity TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode != 0 and "migration 519: authenticated still holds UPDATE on public.client_statutory_identity" in r.stderr, (
            r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


@_NEEDS_PG
def test_a_table_that_does_not_exist_is_skipped_not_fatal(db):
    _ok(db, "DROP TABLE public.client_pt_registrations CASCADE;")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr


@_NEEDS_PG
def test_519_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    assert not _holds(db, "authenticated", "client_statutory_identity", "UPDATE")


@_NEEDS_PG
def test_its_own_rollback_puts_the_grants_back(db):
    """The negative control: with the grants back, the statements refused above go through, so each refusal was the privilege."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    for probe in ("client_payroll_settings (update)", "client_statutory_identity (update)", "client_pt_registrations (update)"):
        done = _as(db, AUTH_MANAGER, PROBES[probe])
        assert done.returncode == 0, (probe, done.stderr)
    # migration 332's design survives the round trip: the three enablement columns are still out of a signed-in role's reach
    assert _ok(db, "SELECT has_column_privilege('authenticated','public.client_payroll_settings','payroll_enabled','UPDATE');") == "f"
    assert not _holds(db, "authenticated", "client_statutory_identity", "TRUNCATE")
