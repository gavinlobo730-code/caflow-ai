"""Migration 772 — the people of a permanently deleted firm are told their firm is closed (POST-A-499).

`public.closed_account_markers` is the stamp that survives the member row a purge deletes: one row per sign-in account, the instant the firm was
deleted and how. Proved against real PostgreSQL because the mock suite cannot tell whether the CHECK bites, whether the primary key supports the
API's upsert, or who may touch the table.
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
FORWARD = API_ROOT / "migrations" / "772_a_purged_firms_people_are_told_their_firm_is_closed.sql"
ROLLBACK = API_ROOT / "migrations" / "772_a_purged_firms_people_are_told_their_firm_is_closed_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 772 proof requires HARNESS_PG + psql",
)

PERSON = "11111111-0000-4000-8000-000000000772"
OTHER = "22222222-0000-4000-8000-000000000772"


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
    name = f"m772_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert FORWARD.name not in pg_template.failed, "migration 772 did not apply: everything below would pass vacuously"
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _marker(who: str = PERSON, how: str = "firm_purged") -> str:
    return f"INSERT INTO public.closed_account_markers (auth_user_id, closed_how) VALUES ('{who}', '{how}');"


def test_the_columns_exist_with_their_types_and_nullability(db):
    out = _psql(db, "SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ',' ORDER BY column_name) "
                    "FROM information_schema.columns WHERE table_schema='public' AND table_name='closed_account_markers';", tuples=True)
    assert out.stdout.strip() == "auth_user_id:uuid:NO,closed_at:timestamp with time zone:NO,closed_how:text:NO"


def test_the_instant_defaults_to_now(db):
    assert _psql(db, _marker()).returncode == 0
    near = _psql(db, "SELECT abs(extract(epoch FROM (now() - closed_at))) < 60 FROM public.closed_account_markers;", tuples=True)
    assert near.stdout.strip() == "t"


def test_only_a_known_way_of_closing_is_accepted(db):
    refused = _psql(db, _marker(how="somebody_felt_like_it"))
    assert refused.returncode != 0 and "closed_account_markers_how_is_known" in refused.stderr


def test_one_row_per_account_and_the_api_upsert_moves_its_instant(db):
    assert _psql(db, _marker()).returncode == 0
    twice = _psql(db, _marker())
    assert twice.returncode != 0 and "closed_account_markers_pkey" in twice.stderr
    assert _psql(db, "UPDATE public.closed_account_markers SET closed_at = now() - interval '2 days';").returncode == 0
    upserted = _psql(db, f"INSERT INTO public.closed_account_markers (auth_user_id, closed_at, closed_how) "
                         f"VALUES ('{PERSON}', now(), 'firm_purged') ON CONFLICT (auth_user_id) DO UPDATE SET closed_at = EXCLUDED.closed_at, "
                         f"closed_how = EXCLUDED.closed_how;")
    assert upserted.returncode == 0, upserted.stderr
    one = _psql(db, "SELECT count(*) || '|' || (max(closed_at) > now() - interval '1 minute') FROM public.closed_account_markers;", tuples=True)
    assert one.stdout.strip() == "1|true"


def test_a_marker_needs_no_member_row_nor_a_sign_in_account_to_exist(db):
    # The row it describes is gone and the sign-in account lives in another schema, so there is deliberately no foreign key.
    fk = _psql(db, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'public.closed_account_markers'::regclass AND contype = 'f';", tuples=True)
    assert fk.stdout.strip() == "0"
    assert _psql(db, _marker(OTHER)).returncode == 0


@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_a_signed_in_or_signed_out_browser_can_neither_read_nor_write_it(db, role):
    assert _psql(db, _marker()).returncode == 0
    for sql in ("SELECT count(*) FROM public.closed_account_markers;",
                _marker(OTHER),
                "UPDATE public.closed_account_markers SET closed_at = now() + interval '10 years';",
                "DELETE FROM public.closed_account_markers;"):
        refused = _psql(db, f"SET ROLE {role}; {sql}")
        assert refused.returncode != 0 and "permission denied" in refused.stderr, f"{role} ran: {sql}\n{refused.stderr}"


def test_only_the_privileged_api_client_reads_and_writes_it(db):
    ok = _psql(db, f"SET ROLE service_role; {_marker()} SELECT count(*) FROM public.closed_account_markers; "
                   "UPDATE public.closed_account_markers SET closed_at = now(); DELETE FROM public.closed_account_markers;")
    assert ok.returncode == 0, ok.stderr


def test_row_security_is_on_and_there_is_no_policy_to_widen_it(db):
    on = _psql(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.closed_account_markers'::regclass;", tuples=True)
    assert on.stdout.strip() == "t"
    policies = _psql(db, "SELECT count(*) FROM pg_policy WHERE polrelid = 'public.closed_account_markers'::regclass;", tuples=True)
    assert policies.stdout.strip() == "0"


def test_the_table_holds_no_name_and_no_address(db):
    cols = _psql(db, "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns "
                     "WHERE table_schema='public' AND table_name='closed_account_markers';", tuples=True)
    assert not any(word in cols.stdout for word in ("name", "email", "pan", "phone", "address")), cols.stdout


def test_the_migration_can_run_twice(db):
    assert _psql(db, _marker()).returncode == 0
    assert _psql_file(db, FORWARD).returncode == 0
    assert _psql(db, "SELECT count(*) FROM public.closed_account_markers;", tuples=True).stdout.strip() == "1", "re-running the migration lost a row"


def test_the_rollback_drops_the_table_and_the_migration_comes_back(db):
    assert _psql_file(db, ROLLBACK).returncode == 0
    assert _psql(db, "SELECT to_regclass('public.closed_account_markers') IS NULL;", tuples=True).stdout.strip() == "t"
    assert _psql_file(db, FORWARD).returncode == 0
    assert _psql(db, "SELECT to_regclass('public.closed_account_markers') IS NOT NULL;", tuples=True).stdout.strip() == "t"
