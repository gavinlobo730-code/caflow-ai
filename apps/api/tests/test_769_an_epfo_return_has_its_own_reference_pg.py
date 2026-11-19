"""Migration 769 — an EPFO return has its own reference, and its challan has another (POST-A-518).

On EPFO's revamped system the RETURN gets a Return File ID when its file passes the portal's checks, and the CHALLAN that pays its
dues gets a TRRN when it is finalised, after the return is approved. Migration 335 named one reference column `trrn`; 769 adds the
return's own, additively and without a backfill (no row here is a real filing), and says in the column comments what each now
means. Proved against real PostgreSQL because the mock suite cannot tell whether a column exists or what a comment says.
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
FORWARD = API_ROOT / "migrations" / "769_an_epfo_return_has_its_own_reference_and_its_challan_has_another.sql"
ROLLBACK = API_ROOT / "migrations" / "769_an_epfo_return_has_its_own_reference_and_its_challan_has_another_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="migration 769 proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000769"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000769"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)],
                          capture_output=True, text=True)


@pytest.fixture()
def seeded(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m769_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert FORWARD.name not in pg_template.failed
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M769 Firm','m769@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT}','{FIRM}','M769 Client','Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _insert(dsn: str, month: str, extra_cols: str = "", extra_vals: str = "") -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO public.epfo_ecr_filings
          (firm_id, client_id, wage_month, return_type, status, submitted_on{extra_cols})
        VALUES ('{FIRM}','{CLIENT}','{month}','regular','submitted','2026-09-10'{extra_vals});
    """)


def test_the_column_exists_as_nullable_text(seeded):
    out = _psql(seeded, "SELECT data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='epfo_ecr_filings' "
                        "AND column_name='return_file_id';", tuples=True)
    assert out.stdout.strip() == "text|YES", out.stderr


def test_a_return_keeps_its_own_reference_apart_from_its_challans(seeded):
    ins = _insert(seeded, "2026-08", ", return_file_id, trrn", ", '250100001024', '250113000000438'")
    assert ins.returncode == 0, ins.stderr
    row = _psql(seeded, "SELECT return_file_id || '/' || trrn FROM public.epfo_ecr_filings "
                        "WHERE wage_month='2026-08';", tuples=True)
    assert row.stdout.strip() == "250100001024/250113000000438"


def test_a_record_with_neither_reference_still_inserts_and_reads_null(seeded):
    assert _insert(seeded, "2026-07").returncode == 0
    row = _psql(seeded, "SELECT (return_file_id IS NULL)::text || (trrn IS NULL)::text "
                        "FROM public.epfo_ecr_filings WHERE wage_month='2026-07';", tuples=True)
    assert row.stdout.strip() == "truetrue"


def test_the_comments_say_which_reference_is_which(seeded):
    out = _psql(seeded, """
        SELECT col_description('public.epfo_ecr_filings'::regclass, a.attnum)
          FROM pg_attribute a
         WHERE a.attrelid = 'public.epfo_ecr_filings'::regclass AND a.attname = 'return_file_id';
    """, tuples=True)
    assert "Return File ID" in out.stdout and "TRRN" in out.stdout
    trrn = _psql(seeded, """
        SELECT col_description('public.epfo_ecr_filings'::regclass, a.attnum)
          FROM pg_attribute a
         WHERE a.attrelid = 'public.epfo_ecr_filings'::regclass AND a.attname = 'trrn';
    """, tuples=True)
    assert "challan" in trrn.stdout.lower() and "return_file_id" in trrn.stdout


def test_the_migration_can_run_twice(seeded):
    assert _psql_file(seeded, FORWARD).returncode == 0


def test_the_rollback_removes_the_column_and_restores_the_old_comment_and_the_migration_comes_back(seeded):
    assert _psql_file(seeded, ROLLBACK).returncode == 0
    gone = _psql(seeded, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
                         "AND table_name='epfo_ecr_filings' AND column_name='return_file_id';", tuples=True)
    assert gone.stdout.strip() == "0"
    comment = _psql(seeded, """
        SELECT col_description('public.epfo_ecr_filings'::regclass, a.attnum)
          FROM pg_attribute a WHERE a.attrelid = 'public.epfo_ecr_filings'::regclass AND a.attname = 'trrn';
    """, tuples=True)
    assert "Temporary Return Reference Number" in comment.stdout
    assert _psql_file(seeded, FORWARD).returncode == 0
