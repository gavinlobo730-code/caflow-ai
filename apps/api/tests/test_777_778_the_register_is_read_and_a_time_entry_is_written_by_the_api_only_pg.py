"""Migrations 777 and 778: no signed-in session reads the related-party register, and a time entry is written by the API only
(POST-A-544 and POST-A-546, the database halves).

Both take a privilege away from the signed-in role, after the change that moved the server's own statements to its own client
(merged as 40b2234d). Proved against real PostgreSQL because a privilege is a fact about the database: the mock suite cannot
tell whether `authenticated` may read or write a table.

WHAT IS ASSERTED
  * 777: `authenticated` and `anon` hold NOTHING on `entities`, `entity_relationships` and `entity_to_entity_relationships`
    (table level and column level), a signed-in session's SELECT is refused with a permission error, and `service_role` reads
    and writes them.
  * 778: `authenticated` and `anon` hold no INSERT, UPDATE or DELETE on `time_entries`, a signed-in session's write of each
    kind is refused with a permission error, its READ still works, and `service_role` writes it.
  * Each migration runs twice, and each rollback gives back exactly what was taken (the register's read; the time entry's
    three writes) and the migration applies again after it.
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
M777 = API_ROOT / "migrations" / "777_no_signed_in_session_reads_the_related_party_register.sql"
R777 = API_ROOT / "migrations" / "777_no_signed_in_session_reads_the_related_party_register_rollback.sql"
M778 = API_ROOT / "migrations" / "778_a_time_entry_is_written_by_the_api_only.sql"
R778 = API_ROOT / "migrations" / "778_a_time_entry_is_written_by_the_api_only_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the proof of migrations 777 and 778 requires HARNESS_PG + psql",
)

REGISTER = ("entities", "entity_relationships", "entity_to_entity_relationships")


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m777_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        for migration in (M777, M778):
            assert migration.name not in pg_template.failed, f"{migration.name} did not apply: everything below would pass vacuously"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _holds(dsn: str, role: str, table: str, verb: str) -> bool:
    out = _psql(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{verb}')::text;", tuples=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip() == "true"


def _as_signed_in(dsn: str, statement: str) -> subprocess.CompletedProcess:
    """One statement as the signed-in role, rolled back whatever happens."""
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; {statement}; ROLLBACK;")


# ── 777 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", REGISTER)
def test_no_signed_in_role_holds_anything_on_the_register(db, table):
    for role in ("authenticated", "anon"):
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert not _holds(db, role, table, verb), f"{role} holds {verb} on {table}"
        cols = _psql(db, f"SELECT (has_any_column_privilege('{role}', 'public.{table}', 'SELECT') OR "
                         f"has_any_column_privilege('{role}', 'public.{table}', 'UPDATE') OR "
                         f"has_any_column_privilege('{role}', 'public.{table}', 'INSERT'))::text;", tuples=True)
        assert cols.stdout.strip() == "false", f"{role} holds a column-level privilege on {table}"


@pytest.mark.parametrize("table", REGISTER)
def test_a_signed_in_sessions_read_of_the_register_is_refused_and_the_servers_own_is_not(db, table):
    refused = _as_signed_in(db, f"SELECT count(*) FROM public.{table}")
    assert refused.returncode != 0 and "permission denied" in refused.stderr, refused.stderr
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "service_role", table, verb), f"service_role lost {verb} on {table}"
    served = _psql(db, f"BEGIN; SET LOCAL ROLE service_role; SELECT count(*) FROM public.{table}; ROLLBACK;")
    assert served.returncode == 0, served.stderr


def test_the_register_migration_runs_twice_and_its_rollback_gives_the_read_back_and_nothing_else(db):
    again = _psql_file(db, M777)
    assert again.returncode == 0, again.stderr
    back = _psql_file(db, R777)
    assert back.returncode == 0, back.stderr
    for table in REGISTER:
        assert _holds(db, "authenticated", table, "SELECT"), f"the rollback did not give the read of {table} back"
        for verb in ("INSERT", "UPDATE", "DELETE"):
            assert not _holds(db, "authenticated", table, verb), f"the rollback gave back {verb} on {table}, which migration 562 took"
        assert not _holds(db, "anon", table, "SELECT"), f"the rollback gave anon a read of {table}"
    forward = _psql_file(db, M777)
    assert forward.returncode == 0, forward.stderr
    assert not any(_holds(db, "authenticated", t, "SELECT") for t in REGISTER)


# ── 778 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_signed_in_role_holds_a_write_of_a_time_entry_and_the_read_stays(db):
    for role in ("authenticated", "anon"):
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not _holds(db, role, "time_entries", verb), f"{role} holds {verb} on time_entries"
        cols = _psql(db, f"SELECT (has_any_column_privilege('{role}', 'public.time_entries', 'UPDATE') OR "
                         f"has_any_column_privilege('{role}', 'public.time_entries', 'INSERT'))::text;", tuples=True)
        assert cols.stdout.strip() == "false", f"{role} holds a column-level write on time_entries"
    assert _holds(db, "authenticated", "time_entries", "SELECT"), "the signed-in role lost the READ, which the Time screens make as the caller"
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "service_role", "time_entries", verb), f"service_role lost {verb} on time_entries"


@pytest.mark.parametrize("statement", [
    "INSERT INTO public.time_entries (id) VALUES (gen_random_uuid())",
    "UPDATE public.time_entries SET billed_invoice_id = NULL",
    "UPDATE public.time_entries SET billable_rate_paise = 1, hourly_rate_paise = 1",
    "DELETE FROM public.time_entries",
])
def test_a_signed_in_sessions_write_of_a_time_entry_is_refused_as_a_permission(db, statement):
    refused = _as_signed_in(db, statement)
    assert refused.returncode != 0 and "permission denied for table time_entries" in refused.stderr, refused.stderr


def test_a_signed_in_session_still_reads_time_entries(db):
    read = _as_signed_in(db, "SELECT count(*) FROM public.time_entries")
    assert read.returncode == 0, read.stderr


def test_the_time_entry_migration_runs_twice_and_its_rollback_gives_the_three_writes_back(db):
    again = _psql_file(db, M778)
    assert again.returncode == 0, again.stderr
    back = _psql_file(db, R778)
    assert back.returncode == 0, back.stderr
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert _holds(db, "authenticated", "time_entries", verb), f"the rollback did not give {verb} back"
    assert not _holds(db, "authenticated", "time_entries", "TRUNCATE")
    forward = _psql_file(db, M778)
    assert forward.returncode == 0, forward.stderr
    assert not any(_holds(db, "authenticated", "time_entries", v) for v in ("INSERT", "UPDATE", "DELETE"))
