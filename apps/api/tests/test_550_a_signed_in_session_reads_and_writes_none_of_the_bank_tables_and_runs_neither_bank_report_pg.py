"""Migration 550: a signed-in session reads and writes none of the bank tables and runs neither bank report (POST-A-339, the bank group).

WHAT IS HELD
    * THE GROUP IS A RULE, NOT A LIST OF FILES. The eight tables the migration revokes are exactly the `bank_` tables the migrations
      create and do not drop (`tests/_sensitive_tables.py` names the prefix), so a `bank_x` table created next month is a failure
      here until it is in the migration. That part needs no database.
    * NOTHING IS LEFT TO A SIGNED-IN ROLE. `authenticated` and `anon` hold no privilege on any of them, effective (through PUBLIC,
      through another role, or on a column), a PostgREST-shaped call as either is refused by the database on each of SELECT,
      INSERT, UPDATE and DELETE, and neither role may EXECUTE the two reports `bank_register` and `bank_reconciling_items` or
      the foreign bank balances `fx_foreign_bank_balances` (a definer that returns account numbers).
    * THE API IS UNAFFECTED: the service role reads every table, holds INSERT, UPDATE and DELETE on each, and runs both reports.
    * THE POLICIES STAY: the second lock (migration 499's reasoning). Apply and rollback leave every row policy byte for byte as it
      was, and no policy or view of ANOTHER table reads a bank table.
    * THE ROLLBACK IS EXACT: it gives back what the earlier migrations granted (the four verbs on each table, EXECUTE on the two
      reports through PUBLIC) and nothing more, and the migration can be applied again afterwards and twice in a row.
    * THE CLOSING CHECK IS A CHECK: a privilege another role handed to `authenticated` survives a REVOKE by the owner, and the
      migration refuses (rolls back) rather than report a lockdown it did not make; so does a service role left without a privilege
      the API needs, and so does a report the service role could no longer run.

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

from tests._sensitive_tables import SENSITIVE_PREFIXES
from tests._signed_in_postgrest import SignedInDb, SignedInError

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATION = MIGRATIONS / "550_a_signed_in_session_reads_and_writes_none_of_the_bank_tables_and_runs_neither_bank_report.sql"
ROLLBACK = MIGRATIONS / "550_a_signed_in_session_reads_and_writes_none_of_the_bank_tables_and_runs_neither_bank_report_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the bank revoke proof requires HARNESS_PG + psql",
)

AUTH_ID = "55001000-0000-0000-0000-00000000000a"
PREFIX = next(p for p in SENSITIVE_PREFIXES if p.startswith("bank"))
#: The two reports, written out with their argument types (not derived from the migration under test) and a call that a
#: server can make with no data in the database.
REPORTS = {
    "bank_register": ("uuid, uuid, date, date, text, text, text, boolean, integer, integer",
                      {"p_firm": "00000000-0000-0000-0000-000000000001", "p_account": "00000000-0000-0000-0000-000000000002",
                       "p_date_from": None, "p_date_to": None, "p_status": None, "p_q": None, "p_sort": "date",
                       "p_desc": True, "p_limit": 10, "p_offset": 0}),
    "bank_reconciling_items": ("uuid, uuid, uuid, uuid, date, bigint, integer",
                               {"p_firm": "00000000-0000-0000-0000-000000000001", "p_client": "00000000-0000-0000-0000-000000000003",
                                "p_bank_account": "00000000-0000-0000-0000-000000000002",
                                "p_gl_account": "00000000-0000-0000-0000-000000000004", "p_as_of": "2026-03-31",
                                "p_statement_balance": 0, "p_list_cap": 10}),
    # not a report of the bank tables but a SECURITY DEFINER function that returns bank account numbers and balances, closed with them
    "fx_foreign_bank_balances": ("uuid, uuid", {"p_firm": "00000000-0000-0000-0000-000000000001",
                                                "p_client": "00000000-0000-0000-0000-000000000003"}),
}


def _array_in(path: Path) -> set[str]:
    sql = re.sub(r"--[^\n]*", "", path.read_text())
    body = re.search(r"(?:tables text\[\] := ARRAY\[|FOREACH t IN ARRAY ARRAY\[)(.*?)\]", sql, re.S).group(1)
    return set(re.findall(r"'([a-z_]+)'", body))


def _bank_prefixed_tables_the_migrations_create() -> set[str]:
    created, dropped = set(), set()
    for path in MIGRATIONS.glob("*.sql"):
        if path.name.endswith("_rollback.sql"):
            continue
        sql = re.sub(r"--[^\n]*", "", path.read_text())
        created |= set(re.findall(rf"CREATE TABLE (?:IF NOT EXISTS )?(?:public\.)?({PREFIX}[a-z_]+)", sql))
        dropped |= set(re.findall(rf"DROP TABLE (?:IF EXISTS )?(?:public\.)?({PREFIX}[a-z_]+)", sql))
    return created - dropped


def _group() -> set[str]:
    """The tables of the bank group, by the rule."""
    return _bank_prefixed_tables_the_migrations_create()


# ── no database: the group is the rule's ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_migration_revokes_exactly_the_bank_group_and_the_rollback_restores_exactly_it():
    group = _group()
    assert _array_in(MIGRATION) == group, (
        f"migration 550 and the bank tables differ: missing {sorted(group - _array_in(MIGRATION))}, "
        f"extra {sorted(_array_in(MIGRATION) - group)}")
    restored = _array_in(ROLLBACK)
    assert restored == group, (sorted(group ^ restored))
    assert len(group) == 8, "the header of the migration says eight; change both together"


def test_the_prefixed_tables_are_found_in_the_migrations_and_not_assumed():
    found = _bank_prefixed_tables_the_migrations_create()
    assert {"bank_accounts", "bank_statements", "bank_transactions", "bank_transaction_splits"} <= found


def test_the_migration_names_both_reports_and_the_rollback_gives_them_back():
    up, down = MIGRATION.read_text(), ROLLBACK.read_text()
    for name, (args, _params) in REPORTS.items():
        assert f"public.{name}({args})" in up, name
        assert f"public.{name}({args})" in down, name


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


def _can_execute(dsn: str, role: str, report: str) -> bool:
    args = REPORTS[report][0]
    return _query(dsn, f"SELECT has_function_privilege('{role}', 'public.{report}({args})'::regprocedure, 'EXECUTE')")[0] == "t"


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e550_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@_NEEDS_PG
def test_the_group_exists_in_a_migrated_database_exactly_as_the_rule_says(dsn):
    present = set(_query(dsn, "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p') "
                              f"AND relname LIKE '{PREFIX}%'"))
    assert present == _group(), sorted(present ^ _group())


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_no_signed_in_role_holds_any_privilege_on_a_bank_table(dsn, role):
    held = {rel: verbs for rel, verbs in _privileges(dsn, role, sorted(_group())).items() if verbs}
    assert held == {}, f"{role} still holds: {held}"


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
@pytest.mark.parametrize("report", sorted(REPORTS))
def test_no_signed_in_role_may_run_either_report(dsn, role, report):
    assert not _can_execute(dsn, role, report)
    db = SignedInDb(dsn, role=role, auth_user_id=AUTH_ID if role == "authenticated" else None)
    with pytest.raises(SignedInError) as caught:
        db.rpc(report, REPORTS[report][1]).execute()
    assert re.search(r"permission denied for function " + report, caught.value.message), caught.value.message


@_NEEDS_PG
def test_what_the_hosting_platform_hands_out_by_default_and_a_grant_to_public_are_taken_too(dsn):
    """A database built from the migrations alone holds only the four verbs the earlier migrations granted. The hosting platform's
    default privileges also give `anon` and `authenticated` TRUNCATE (and REFERENCES and TRIGGER) on every table, and a table can be
    granted to PUBLIC; production held the first. This puts all of it there (the rollback first, then every privilege the platform
    adds, then SELECT to PUBLIC) and applies the migration: nothing a row can be read or changed or removed through is left, the
    three functions are closed to PUBLIC, `anon` and `authenticated` and open to the service role, and REFERENCES and TRIGGER, which
    are not privileges on rows, are left as they were."""
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    tables = ", ".join(f"public.{t}" for t in sorted(_group()))
    done = _psql(dsn, f"GRANT ALL ON {tables} TO authenticated, anon; GRANT SELECT ON {tables} TO PUBLIC;")
    assert done.returncode == 0, done.stderr
    applied = _apply_file(dsn, MIGRATION)
    assert applied.returncode == 0, applied.stderr
    for role in ("authenticated", "anon"):
        held = {rel: verbs for rel, verbs in _privileges(dsn, role, sorted(_group())).items() if verbs}
        assert held == {}, f"{role} still holds: {held}"
        assert all(_query(dsn, f"SELECT has_table_privilege('{role}', 'public.{t}', 'REFERENCES') AND has_table_privilege('{role}', 'public.{t}', 'TRIGGER')")
                   == ["t"] for t in sorted(_group())), "REFERENCES and TRIGGER are privileges on no row and are left as they were"
        for report in REPORTS:
            assert not _can_execute(dsn, role, report), (role, report)
    for report in REPORTS:
        assert _can_execute(dsn, "service_role", report), report


@_NEEDS_PG
def test_the_service_role_keeps_what_the_api_needs(dsn):
    held = _privileges(dsn, "service_role", sorted(_group()))
    for table in _group():
        assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= set(held[table]), (table, held[table])
    server = SignedInDb(dsn, role="service_role")
    for table in sorted(_group()):
        assert isinstance(server.table(table).select("*").limit(1).execute().data, list), table
    for report in sorted(REPORTS):
        assert _can_execute(dsn, "service_role", report)
        assert isinstance(server.rpc(report, REPORTS[report][1]).execute().data, (list, dict)), report


@_NEEDS_PG
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_postgrest_shaped_call_as_a_signed_in_role_is_refused_on_every_verb(dsn, role):
    db = SignedInDb(dsn, role=role, auth_user_id=AUTH_ID if role == "authenticated" else None)
    refused = []
    for table in sorted(_group()):
        calls = {"select": lambda t=table: db.table(t).select("*").limit(1).execute(),
                 "insert": lambda t=table: db.table(t).insert({"id": str(uuid.uuid4())}).execute(),
                 "update": lambda t=table: db.table(t).update({"id": str(uuid.uuid4())}).eq("id", str(uuid.uuid4())).execute(),
                 "delete": lambda t=table: db.table(t).delete().eq("id", str(uuid.uuid4())).execute()}
        for verb, call in calls.items():
            with pytest.raises(SignedInError) as caught:
                call()
            # The database names the first relation it will not let the role touch; the privileges test above holds that the
            # table itself is refused, so the message is held to its shape.
            if not re.search(r"permission denied for (table|view) [a-z_]+", caught.value.message):
                refused.append((table, verb, caught.value.message[:120]))
    assert refused == [], refused


@_NEEDS_PG
def test_no_policy_or_view_of_another_table_reads_a_bank_table(dsn):
    names = ", ".join(f"'{t}'" for t in sorted(_group()))
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
    assert len(before) >= 30, "the bank tables lost their row policies: the second lock is gone"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _policies(dsn) == before
    assert _apply_file(dsn, MIGRATION).returncode == 0
    assert _policies(dsn) == before
    assert {r.split("|")[0] for r in before} == _group(), "every table keeps at least one policy"


@_NEEDS_PG
def test_the_rollback_gives_back_what_the_earlier_migrations_granted_and_nothing_more(dsn):
    done = _apply_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    auth = _privileges(dsn, "authenticated", sorted(_group()))
    assert auth == {t: ["DELETE", "INSERT", "SELECT", "UPDATE"] for t in _group()}
    assert _privileges(dsn, "anon", sorted(_group())) == {t: [] for t in _group()}
    for role in ("authenticated", "anon", "service_role"):
        for report in REPORTS:
            # migration 281 never gave `anon` the foreign bank balances (it revoked PUBLIC and anon), and the rollback must not either
            expected = not (role == "anon" and report == "fx_foreign_bank_balances")
            assert _can_execute(dsn, role, report) is expected, (role, report)
    # and the migration locks it all again, twice in a row
    for _ in range(2):
        again = _apply_file(dsn, MIGRATION)
        assert again.returncode == 0, again.stderr
    assert {r: v for r, v in _privileges(dsn, "authenticated", sorted(_group())).items() if v} == {}
    for report in REPORTS:
        assert not _can_execute(dsn, "authenticated", report) and not _can_execute(dsn, "anon", report)
        assert _can_execute(dsn, "service_role", report)


@_NEEDS_PG
def test_the_closing_check_refuses_a_privilege_a_revoke_by_the_owner_cannot_take(dsn):
    """A REVOKE removes only the grants its own grantor made. A privilege that another role handed to `authenticated` (it holds the
    privilege WITH GRANT OPTION) survives it, and the closing check, which asks the EFFECTIVE privilege, refuses the whole
    migration instead of reporting a lockdown it did not make. (Membership of another role does not do it here: the signed-in
    roles are NOINHERIT, as the hosting platform makes them.)"""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"g550_{uuid.uuid4().hex[:8]}"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT SELECT ON public.bank_transactions TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT SELECT ON public.bank_transactions TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0
        assert "authenticated still holds SELECT on bank_transactions" in refused.stderr, refused.stderr
        # the whole migration rolled back: nothing else was revoked
        assert "SELECT" in _privileges(dsn, "authenticated", ["bank_accounts"])["bank_accounts"]
        assert _can_execute(dsn, "authenticated", "bank_register")
    finally:
        _psql(dsn, f"REVOKE ALL ON public.bank_transactions FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_the_closing_check_refuses_a_column_privilege_a_table_level_revoke_cannot_take(dsn):
    """The same, one level down: a column-level SELECT that another role handed to `authenticated` is not a table privilege and is
    not removed by the owner's table-level REVOKE, so only the column check sees it."""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"c550_{uuid.uuid4().hex[:8]}"
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT SELECT (id) ON public.bank_transactions TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT SELECT (id) ON public.bank_transactions TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0
        assert "authenticated still holds a column-level privilege on bank_transactions" in refused.stderr, refused.stderr
        assert "SELECT" in _privileges(dsn, "authenticated", ["bank_accounts"])["bank_accounts"]
    finally:
        _psql(dsn, f"REVOKE ALL ON public.bank_transactions FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_the_closing_check_refuses_a_report_a_signed_in_user_could_still_run(dsn):
    """EXECUTE granted to `authenticated` by another role survives the owner's REVOKE the same way a table privilege does."""
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    role = f"f550_{uuid.uuid4().hex[:8]}"
    args = REPORTS["bank_register"][0]
    try:
        assert _psql(admin_dsn, f"CREATE ROLE {role} NOLOGIN").returncode == 0
        done = _psql(dsn, f"GRANT EXECUTE ON FUNCTION public.bank_register({args}) TO {role} WITH GRANT OPTION; SET ROLE {role}; "
                          f"GRANT EXECUTE ON FUNCTION public.bank_register({args}) TO authenticated; RESET ROLE")
        assert done.returncode == 0, done.stderr
        refused = _apply_file(dsn, MIGRATION)
        assert refused.returncode != 0 and "is still executable by a signed-in user" in refused.stderr, refused.stderr
    finally:
        _psql(dsn, f"REVOKE ALL ON FUNCTION public.bank_register({args}) FROM {role} CASCADE")
        _psql(admin_dsn, f"DROP ROLE IF EXISTS {role}")


@_NEEDS_PG
def test_the_closing_check_refuses_a_service_role_left_without_a_privilege_the_api_needs(dsn):
    assert _apply_file(dsn, ROLLBACK).returncode == 0
    assert _psql(dsn, "REVOKE UPDATE ON public.bank_transactions FROM service_role").returncode == 0
    refused = _apply_file(dsn, MIGRATION)
    assert refused.returncode != 0 and "service_role no longer holds UPDATE on bank_transactions" in refused.stderr, refused.stderr
