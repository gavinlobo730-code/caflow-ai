"""Migration 549: a signed-in session reads and writes none of the payroll tables (POST-A-339, the payroll group).

WHAT IS HELD
    * THE GROUP IS A RULE, NOT A LIST OF FILES. The twenty-three tables and the view the migration revokes are exactly the payroll
      set `tests/_sensitive_tables.py` names (the `payroll_` prefix, found in the migrations themselves, plus the unprefixed payroll
      tables), so a `payroll_x` table created next month is a failure here until it is in the migration. That part needs no database.
    * NOTHING IS LEFT TO A SIGNED-IN ROLE. `authenticated` and `anon` hold no privilege on any of them, effective (through PUBLIC,
      through membership of another role, or on a column), and a PostgREST-shaped call as either is refused by the database with
      "permission denied for table" on each of SELECT, INSERT, UPDATE and DELETE.
    * THE API IS UNAFFECTED: the service role reads every one, and holds INSERT, UPDATE and DELETE on every table.
    * THE POLICIES STAY: the second lock (migration 499's reasoning). Apply and rollback leave every row policy byte for byte as it
      was, and no policy or view of ANOTHER table reads a payroll table (a signed-in read of that other table would otherwise start
      failing for everyone, the day this grant went).
    * THE ROLLBACK IS EXACT: it gives back what the earlier migrations granted (SELECT on all, the three writes, the view for anon)
      and nothing more, and the migration can be applied again afterwards and twice in a row.
    * THE CLOSING CHECK IS A CHECK: a privilege that reaches `authenticated` through another role's membership survives a REVOKE
      from `authenticated`, and the migration refuses (rolls back) rather than report a lockdown it did not make; so does a service
      role left without a privilege the API needs.

Runs only when HARNESS_PG is set + psql on PATH; the group rule needs neither and runs in the mock-mode job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests._sensitive_tables import PAYROLL_TABLES
from tests._signed_in_postgrest import SignedInDb, SignedInError

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATION = MIGRATIONS / "549_a_signed_in_session_reads_and_writes_none_of_the_payroll_tables.sql"
ROLLBACK = MIGRATIONS / "549_a_signed_in_session_reads_and_writes_none_of_the_payroll_tables_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the payroll revoke proof requires HARNESS_PG + psql",
)

VIEW = "salary_slips"
#: What a database built from the migrations granted before 549, written out (not derived from the migration under test).
WRITABLE_BEFORE = {"payroll_it_declarations", "payroll_it_declaration_items", "firm_pt_slabs"}
AUTH_ID = "54901000-0000-0000-0000-00000000000a"


def _array_in(path: Path) -> set[str]:
    sql = re.sub(r"--[^\n]*", "", path.read_text())
    body = re.search(r"(?:tables text\[\] := ARRAY\[|FOREACH t IN ARRAY ARRAY\[)(.*?)\]", sql, re.S).group(1)
    return set(re.findall(r"'([a-z_]+)'", body))


def _payroll_prefixed_tables_the_migrations_create() -> set[str]:
    created, dropped = set(), set()
    for path in MIGRATIONS.glob("*.sql"):
        if path.name.endswith("_rollback.sql"):
            continue
        sql = re.sub(r"--[^\n]*", "", path.read_text())
        created |= set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(?:public\.)?(payroll_[a-z_]+)", sql))
        dropped |= set(re.findall(r"DROP TABLE (?:IF EXISTS )?(?:public\.)?(payroll_[a-z_]+)", sql))
    return created - dropped


def _group() -> set[str]:
    """The tables (not the view) of the payroll group, by the rule."""
    return (set(PAYROLL_TABLES) - {VIEW}) | _payroll_prefixed_tables_the_migrations_create()


# ── no database: the group is the rule's ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_migration_revokes_exactly_the_payroll_group_and_the_rollback_restores_exactly_it():
    group = _group()
    assert _array_in(MIGRATION) == group, (
        f"migration 549 and the payroll tables differ: missing {sorted(group - _array_in(MIGRATION))}, "
        f"extra {sorted(_array_in(MIGRATION) - group)}")
    restored = _array_in(ROLLBACK)
    assert restored == group, (sorted(group ^ restored))
    assert len(group) == 23, "the header of the migration says twenty-three; change both together"


def test_the_prefixed_tables_are_found_in_the_migrations_and_not_assumed():
    found = _payroll_prefixed_tables_the_migrations_create()
    assert {"payroll_employees", "payroll_runs", "payroll_slips", "payroll_it_declarations"} <= found
    assert not found & {"salary_slips", "attendance"}


# ── a database ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _query(dsn: str, sql: str):
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.splitlines() if line.strip()]


def _apply_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "--single-transaction", "-f", str(path)],
                          capture_output=True, text=True)


def _privileges(dsn: str, role: str, relations: list[str]) -> dict[str, list[str]]:
    """{relation: [the verbs `role` effectively holds]}, asked of the database (PUBLIC, membership and column level included)."""
    names = ", ".join(f"'{r}'" for r in relations)
    rows = _query(dsn, f"""
        SELECT r.rel || '|' || coalesce(string_agg(v.verb, ',' ORDER BY v.verb) FILTER (WHERE
            has_table_privilege('{role}', 'public.' || r.rel, v.verb)
            OR (v.verb IN ('SELECT', 'INSERT', 'UPDATE') AND has_any_column_privilege('{role}', 'public.' || r.rel, v.verb))), '')
        FROM unnest(ARRAY[{names}]) AS r(rel)
        CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS v(verb)
        GROUP BY r.rel ORDER BY r.rel""")
    return {line.split("|")[0]: [v for v in line.split("|")[1].split(",") if v] for line in rows}


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e549_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _relations() -> list[str]:
    return sorted(_group()) + [VIEW]


@_NEEDS_PG
def test_the_group_exists_in_a_migrated_database_exactly_as_the_rule_says(dsn):
    present = set(_query(dsn, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p') "
                              "AND (relname LIKE 'payroll\\_%' OR relname = ANY(ARRAY["
                              + ", ".join(f"'{t}'" for t in sorted(PAYROLL_TABLES - {VIEW})) + "]))"))
    assert present == _group(), sorted(present ^ _group())
    assert _query(dsn, f"SELECT relkind FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relname = '{VIEW}'") == ["v"]


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_no_signed_in_role_holds_any_privilege_on_a_payroll_table_or_the_view(dsn, role):
    held = {rel: verbs for rel, verbs in _privileges(dsn, role, _relations()).items() if verbs}
    assert held == {}, f"{role} still holds: {held}"


@_NEEDS_PG
def test_what_the_hosting_platform_hands_out_by_default_and_a_grant_to_public_are_taken_too(dsn):
    """A database built from the migrations alone holds only the SELECT/INSERT/UPDATE/DELETE the earlier migrations granted. The
    hosting platform's default privileges also give `anon` and `authenticated` TRUNCATE (and REFERENCES and TRIGGER) on every table,
    and a table can be granted to PUBLIC; production held the first. This puts all of it there (the rollback first, then every
    privilege the platform adds, then SELECT to PUBLIC) and applies the migration: nothing a row can be read or changed or removed
    through is left, and REFERENCES and TRIGGER, which are not privileges on rows, are, as the header says, left alone."""
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    tables = ", ".join(f"public.{t}" for t in sorted(_group()))
    done = _psql(dsn, f"GRANT ALL ON {tables} TO authenticated, anon; GRANT SELECT ON {tables}, public.{VIEW} TO PUBLIC;")
    assert done.returncode == 0, done.stderr
    applied = _apply_file(dsn, MIGRATION)
    assert applied.returncode == 0, applied.stderr
    for role in ("authenticated", "anon"):
        held = {rel: verbs for rel, verbs in _privileges(dsn, role, _relations()).items() if verbs}
        assert held == {}, f"{role} still holds: {held}"
        assert all(_query(dsn, f"SELECT has_table_privilege('{role}', 'public.{t}', 'REFERENCES') AND has_table_privilege('{role}', 'public.{t}', 'TRIGGER')")
                   == ["t"] for t in sorted(_group())), "REFERENCES and TRIGGER are privileges on no row and are left as they were"


@_NEEDS_PG
def test_the_service_role_keeps_what_the_api_needs(dsn):
    held = _privileges(dsn, "service_role", _relations())
    for table in _group():
        assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= set(held[table]), (table, held[table])
    assert "SELECT" in held[VIEW]
    server = SignedInDb(dsn, role="service_role")
    for table in _relations():
        assert isinstance(server.table(table).select("*").limit(1).execute().data, list), table


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_postgrest_shaped_call_as_a_signed_in_role_is_refused_on_every_verb(dsn, role):
    db = SignedInDb(dsn, role=role, auth_user_id=AUTH_ID if role == "authenticated" else None)
    refused = []
    for table in _relations():
        calls = {"select": lambda t=table: db.table(t).select("*").limit(1).execute()}
        if table != VIEW:
            calls |= {"insert": lambda t=table: db.table(t).insert({"id": str(uuid.uuid4())}).execute(),
                      "update": lambda t=table: db.table(t).update({"id": str(uuid.uuid4())}).eq("id", str(uuid.uuid4())).execute(),
                      "delete": lambda t=table: db.table(t).delete().eq("id", str(uuid.uuid4())).execute()}
        for verb, call in calls.items():
            with pytest.raises(SignedInError) as caught:
                call()
            # The database names the first relation it will not let the role touch. On a table whose row policy reads another
            # payroll table that can be the other one (a policy's sub-query is checked with the caller's own privileges), so the
            # message is held to its shape and the privileges test above holds that the table itself is refused.
            if not re.search(r"permission denied for (table|view) [a-z_]+", caught.value.message):
                refused.append((table, verb, caught.value.message[:120]))
    assert refused == [], refused


@_NEEDS_PG
def test_no_policy_or_view_of_another_table_reads_a_payroll_table(dsn):
    names = ", ".join(f"'{t}'" for t in _relations())
    rows = _query(dsn, f"""
        SELECT 'policy ' || pc.relname || '.' || p.polname || ' reads ' || s.relname
        FROM pg_depend d JOIN pg_policy p ON d.classid = 'pg_policy'::regclass AND d.objid = p.oid
        JOIN pg_class s ON s.oid = d.refobjid AND s.relnamespace = 'public'::regnamespace AND s.relname IN ({names})
        JOIN pg_class pc ON pc.oid = p.polrelid AND pc.relname NOT IN ({names})
        UNION ALL
        SELECT 'view ' || vc.relname || ' reads ' || s.relname
        FROM pg_depend d JOIN pg_rewrite rw ON d.classid = 'pg_rewrite'::regclass AND d.objid = rw.oid
        JOIN pg_class vc ON vc.oid = rw.ev_class AND vc.relkind IN ('v', 'm') AND vc.relname NOT IN ({names})
        JOIN pg_class s ON s.oid = d.refobjid AND s.relnamespace = 'public'::regnamespace AND s.relname IN ({names})""")
    assert rows == [], rows


def _policies(dsn: str) -> list[str]:
    names = ", ".join(f"'{t}'" for t in sorted(_group()))
    return _query(dsn, f"""
        SELECT c.relname || '|' || p.polname || '|' || p.polcmd::text || '|' || p.polpermissive::text || '|'
               || regexp_replace(coalesce(pg_get_expr(p.polqual, p.polrelid), ''), '\\s+', ' ', 'g') || '|'
               || regexp_replace(coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''), '\\s+', ' ', 'g')
        FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname IN ({names}) ORDER BY 1""")


@_NEEDS_PG
def test_apply_and_rollback_leave_every_row_policy_as_it_was_and_the_second_lock_is_there(dsn):
    before = _policies(dsn)
    assert len(before) >= 100, "the payroll tables lost their row policies: the second lock is gone"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _policies(dsn) == before
    assert _apply_file(dsn, MIGRATION).returncode == 0
    assert _policies(dsn) == before
    assert {r.split("|")[0] for r in before} == _group(), "every table keeps at least one policy"


@_NEEDS_PG
def test_the_rollback_gives_back_what_the_earlier_migrations_granted_and_nothing_more(dsn):
    done = _apply_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    auth = _privileges(dsn, "authenticated", _relations())
    expected = {t: (["DELETE", "INSERT", "SELECT", "UPDATE"] if t in WRITABLE_BEFORE else ["SELECT"]) for t in _group()}
    expected[VIEW] = ["SELECT"]
    assert auth == expected
    assert _privileges(dsn, "anon", _relations()) == {t: ([] if t != VIEW else ["SELECT"]) for t in _relations()}
    # and the migration locks it all again, twice in a row
    for _ in range(2):
        again = _apply_file(dsn, MIGRATION)
        assert again.returncode == 0, again.stderr
    assert {r: v for r, v in _privileges(dsn, "authenticated", _relations()).items() if v} == {}


@_NEEDS_PG
def test_the_closing_check_refuses_a_privilege_a_revoke_by_the_owner_cannot_take(dsn):
    """A REVOKE removes only the grants its own grantor made. A privilege that another role handed to `authenticated` (it holds the
    privilege WITH GRANT OPTION) survives it, and the closing check, which asks the EFFECTIVE privilege, refuses the whole
    migration instead of reporting a lockdown it did not make. (Membership of another role does not do it here: the signed-in
    roles are NOINHERIT, as the hosting platform makes them, so a privilege held through membership is not theirs until they
    SET ROLE.)"""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"g549_{uuid.uuid4().hex[:8]}"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT SELECT ON public.payroll_loans TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT SELECT ON public.payroll_loans TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0
        assert "authenticated still holds SELECT on payroll_loans" in refused.stderr, refused.stderr
        # the whole migration rolled back: nothing else was revoked
        assert "SELECT" in _privileges(dsn, "authenticated", ["payroll_runs"])["payroll_runs"]
    finally:
        _psql(dsn, f"REVOKE ALL ON public.payroll_loans FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_the_closing_check_refuses_a_column_privilege_a_table_level_revoke_cannot_take(dsn):
    """The same, one level down: a column-level SELECT that another role handed to `authenticated` is not a table privilege
    (`has_table_privilege` says no) and is not removed by the owner's table-level REVOKE, so only the column check sees it."""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"c549_{uuid.uuid4().hex[:8]}"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT SELECT (id) ON public.payroll_loans TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT SELECT (id) ON public.payroll_loans TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0
        assert "authenticated still holds a column-level privilege on payroll_loans" in refused.stderr, refused.stderr
        assert "SELECT" in _privileges(dsn, "authenticated", ["payroll_runs"])["payroll_runs"]
    finally:
        _psql(dsn, f"REVOKE ALL ON public.payroll_loans FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_the_closing_check_refuses_a_service_role_that_can_no_longer_read_a_table(dsn):
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "REVOKE SELECT ON public.payroll_loans FROM service_role").returncode == 0
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "service_role no longer reads payroll_loans" in refused.stderr, refused.stderr


@_NEEDS_PG
def test_the_closing_check_refuses_a_service_role_left_without_a_privilege_the_api_needs(dsn):
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "REVOKE UPDATE ON public.payroll_runs FROM service_role").returncode == 0
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "service_role no longer holds UPDATE on payroll_runs" in refused.stderr, refused.stderr
