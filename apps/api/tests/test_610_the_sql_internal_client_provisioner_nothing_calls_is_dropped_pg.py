"""Migration 610 — the SQL copy of the internal-client provisioner, which nothing calls, is dropped (ledger POST-A-169).

WHAT IS HELD
    * After the migrations, `public.provision_internal_client(uuid, text, text, text, text)` does not exist, and the Python provisioner
      (`services/internal_client_service.provision`) is the only one: no module of the API, of the browser or of the migrations after
      the one that drops it names the SQL function.
    * The helper the row policies call, `my_internal_client_id()`, and the one-internal-client index are untouched.
    * The rollback recreates the function as 073 wrote it, executable by the service role alone (086), and the migration then applies
      again and drops it (idempotent).

Runs only when HARNESS_PG is set + psql on PATH; the source half runs everywhere.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
_STEM = "610_the_sql_internal_client_provisioner_nothing_calls_is_dropped"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")
_SIGNATURE = "public.provision_internal_client(uuid,text,text,text,text)"

_NEEDS_PG = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None,
                               reason="the function proofs require HARNESS_PG + psql")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m610_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert f"{_STEM}.sql" not in pg_template.failed, "migration 610 did not apply, so everything below would pass vacuously"
        yield f"{admin} dbname={dbname}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_nothing_in_the_api_the_browser_or_a_later_migration_calls_the_sql_provisioner():
    """The premise of the drop, held: a caller added later fails here before it fails in production."""
    callers = []
    web = API_ROOT.parent / "web"
    roots = [(API_ROOT / d, "*.py") for d in ("routers", "services", "domain", "repositories", "jobs", "core", "models", "scripts")]
    roots += [(web / d, ext) for d in ("app", "components", "lib") for ext in ("*.ts", "*.tsx")]
    for root, pattern in roots:
        for path in root.rglob(pattern):
            if "provision_internal_client" in path.read_text(encoding="utf-8", errors="ignore"):
                callers.append(str(path.relative_to(API_ROOT.parent)))
    for path in sorted((API_ROOT / "migrations").glob("*.sql")):
        if not path.name[:3].isdigit():
            continue
        if int(path.name[:3]) > 610 and not path.name.endswith("_rollback.sql") and re.search(
                r"provision_internal_client\s*\(", path.read_text(encoding="utf-8")):
            callers.append(path.name)
    assert not callers, f"the SQL provisioner migration 610 drops is called from: {callers}"
    assert "def provision(" in (API_ROOT / "services" / "internal_client_service.py").read_text(encoding="utf-8")


@_NEEDS_PG
def test_the_sql_provisioner_is_gone_and_the_policy_helper_and_the_index_are_not(db):
    assert _ok(db, f"SELECT to_regprocedure('{_SIGNATURE}') IS NULL;") == "t"
    assert _ok(db, "SELECT to_regprocedure('public.my_internal_client_id()') IS NOT NULL;") == "t"
    assert _ok(db, "SELECT to_regclass('public.uq_clients_one_internal_per_firm') IS NOT NULL;") == "t"


@_NEEDS_PG
def test_the_rollback_restores_it_for_the_service_role_alone_and_the_migration_applies_again(db):
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    assert _ok(db, f"SELECT to_regprocedure('{_SIGNATURE}') IS NOT NULL;") == "t"
    grants = _ok(db, f"""
        SELECT string_agg(r, ',' ORDER BY r) FROM (
          SELECT r FROM unnest(ARRAY['anon','authenticated','service_role']) r
           WHERE has_function_privilege(r, '{_SIGNATURE}', 'EXECUTE')) x;""")
    assert grants == "service_role"
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    assert _ok(db, f"SELECT to_regprocedure('{_SIGNATURE}') IS NULL;") == "t"
