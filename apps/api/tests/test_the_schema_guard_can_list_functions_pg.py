"""get_public_schema_functions() (migration 475) answers what core/schema_guard.live_functions expects, and only to service_role (ops-19).

Two things only a real database can show. The first is the SHAPE: the guard proves it received the whole list by
comparing `total_functions` with the names it parsed, so the function's own count and its own list have to agree
on a real catalogue, overloads included. The second is the PRIVILEGE: CREATE FUNCTION gives EXECUTE to PUBLIC and
Supabase's default privileges add anon and authenticated, so a list of every function name in the schema is
reachable by the published anon key unless each is revoked by name (migration 141's lesson: `REVOKE ... FROM anon`
against a privilege that came from PUBLIC is a no-op that reads like a revoke).

Skipped without HARNESS_PG and psql. NOT RUN where it was written, which had no Postgres; the CI `migrations` job
is its first execution.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from core.schema_guard import live_functions

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the function-list proof requires HARNESS_PG + psql",
)

SIGNATURE = "public.get_public_schema_functions()"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"fnlist_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _payload(dsn: str) -> dict:
    r = _psql(dsn, f"SELECT {SIGNATURE}::text;")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def test_the_function_was_created_by_the_migration(pg_template):
    assert "475_the_schema_guard_can_read_which_functions_exist.sql" not in pg_template.failed


def test_the_count_and_the_list_agree_on_a_real_catalogue(db):
    p = _payload(db)
    names = p["functions"]
    assert isinstance(p["total_functions"], int) and p["total_functions"] > 50
    assert len(names) == p["total_functions"] == len(set(names)), "total_functions is of DISTINCT names"
    assert names == sorted(names)


def test_it_lists_the_functions_the_code_calls(db):
    names = set(_payload(db)["functions"])
    for must in ("get_public_schema_functions", "get_public_schema_columns", "post_journal_atomic",
                 "journal_period_lock_reason", "numbered_document_atomic"):
        assert must in names, must


def test_what_the_python_reads_is_what_the_database_sends(db):
    """live_functions() proves completeness itself; hand it the real payload and it must accept it."""
    payload = _payload(db)

    class _Resp:
        data = payload

    class _Rpc:
        def execute(self):
            return _Resp()

    class _Db:
        def rpc(self, name, params):
            assert name == "get_public_schema_functions"
            return _Rpc()

    got = live_functions(_Db())
    assert got is not None and "post_journal_atomic" in got


def _privilege(dsn: str, role: str) -> str:
    r = _psql(dsn, f"SELECT has_function_privilege('{role}', '{SIGNATURE}', 'EXECUTE');")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_only_the_service_role_may_list_the_functions(db, role):
    assert _privilege(db, role) == "f", (
        f"{role} can EXECUTE {SIGNATURE}. A revoke written only against anon is a no-op when the privilege "
        "came from PUBLIC; the migration revokes PUBLIC, anon and authenticated by name.")


def test_the_service_role_keeps_it(db):
    assert _privilege(db, "service_role") == "t"
