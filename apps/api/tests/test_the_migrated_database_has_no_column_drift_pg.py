"""A database the migrations built reads as free of column drift to the guard that runs at boot.

WHY THIS EXISTS
    core/schema_guard derives the columns the deployed code expects from the migration files and compares them with
    the live schema. Its unit tests fake both sides, so a parser that names a table the migrations never created (it
    read `ALTER TABLE IF EXISTS public.fixed_deposits` as the table "if", migration 521, 19-10-2026) passed every one
    of them while /health answered 503 "schema_drift" on any database at all. The only honest test of "the expected
    columns exist" is to build the database from the same migrations and ask. A migration that adds a column to a
    table another migration only creates conditionally would fail here too, which is the situation worth hearing about
    on the pull request and not at the deploy.

    The call is the production one: `check_schema_drift(db)` reading get_public_schema_columns() (migration 265). The
    database object is a thin psql wrapper, because the function is a database function and PostgREST is not part of
    this harness.

Runs only when HARNESS_PG is set and psql is on the path.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from types import SimpleNamespace

import pytest

from core.schema_guard import check_schema_drift

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="needs HARNESS_PG and psql",
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
                          capture_output=True, text=True)


class _PsqlDb:
    """Just enough of the Supabase client for check_schema_drift: `.rpc(name, {}).execute().data`."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def rpc(self, name: str, params: dict):
        assert name == "get_public_schema_columns" and not params
        dsn = self._dsn

        class _Call:
            def execute(self_inner):
                out = _psql(dsn, "SELECT public.get_public_schema_columns()::text;")
                assert out.returncode == 0, out.stderr
                return SimpleNamespace(data=json.loads(out.stdout))

        return _Call()


@pytest.fixture()
def migrated_dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"drift_{uuid.uuid4().hex[:12]}"
    if _psql(f"{admin} dbname=postgres", f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create a throwaway database")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(f"{admin} dbname=postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_the_boot_check_finds_no_missing_column_on_a_database_the_migrations_built(migrated_dsn):
    verdict = check_schema_drift(_PsqlDb(migrated_dsn))
    assert verdict["checked"] is True, "the schema could not be read in full, so nothing below was checked"
    assert verdict["missing"] == [], (
        f"the guard that runs at boot expects columns a migrated database does not have: {verdict['missing']}. "
        "On production this is /health 503 and a held deploy.")
