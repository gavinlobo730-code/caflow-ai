"""
R2.8 fix phase — government_notices ca_approved/ca_approved_by/ca_approved_at
columns, proven on real PostgreSQL.

Background
----------
Migration 052 created public.government_notices without ca_approved /
ca_approved_by / ca_approved_at, but routers/document_intelligence_v2.py has
always read and written all three:
  * POST /notices/extract inserts "ca_approved": False on every new notice —
    the honest-extraction success path R2.8's own tests assert works
    end-to-end (in _USE_MOCK mode only).
  * POST /notices/{id}/approve updates ca_approved / ca_approved_by /
    ca_approved_at as the required human-in-the-loop CA approval step.

Against real Postgres/PostgREST (SUPABASE_URL configured, _USE_MOCK=False)
both the insert and the update referenced columns absent from the schema,
so even a genuine, non-fabricated Groq extraction was never persisted in
production — the milestone's own new tests only exercise the in-memory mock
store and could never catch this (test_r2_8_ai_extraction.py).

Migration 158 adds the three missing columns additively (same repair pattern
as 155/157: a new migration, never editing 052). This test performs the
EXACT insert/update payloads routers/document_intelligence_v2.py builds
against a freshly-migrated throwaway database, so a future regression that
drops/renames these columns fails loudly here instead of silently 500ing in
production.

Runs only when HARNESS_PG is set + psql on PATH (same gate as the other
real-Postgres tests); skips in the mock-mode CI job. The `migrations` CI job
runs it against its Postgres service.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="government_notices ca_approved proof requires HARNESS_PG + psql",
)

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())
NOTICE = str(uuid.uuid4())
TASK = str(uuid.uuid4())
APPROVER = str(uuid.uuid4())


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r28fix_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        # 052 (creates the table) and 158 (adds the columns) must both apply
        # cleanly — that's the only thing this proof depends on.
        assert "052_phase3_compliance.sql" not in failed
        assert "158_government_notices_ca_approval_columns.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_government_notices_has_ca_approval_columns(migrated_db):
    r = _psql(
        migrated_db,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='government_notices' AND table_schema='public' "
        "AND column_name IN ('ca_approved','ca_approved_by','ca_approved_at') "
        "ORDER BY column_name;",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    cols = {c for c in r.stdout.strip().splitlines() if c}
    assert cols == {"ca_approved", "ca_approved_at", "ca_approved_by"}


def test_notice_extract_insert_payload_succeeds(migrated_db):
    """Exact shape of the INSERT built in document_intelligence_v2.extract_notice
    (record dict, including "ca_approved": False) must succeed against real PG."""
    insert_sql = f"""
    INSERT INTO public.government_notices
        (id, firm_id, client_id, notice_type, authority, reference_no,
         issue_date, response_due_date, description, source_document_url,
         extracted_data, status, ca_approved, task_id, created_at, updated_at)
    VALUES
        ('{NOTICE}', '{FIRM}', '{CLIENT}', 'gst_scrutiny', 'GSTN', 'REF/2026/001',
         '2026-06-01', '2026-07-15', 'Respond to GST scrutiny notice.', NULL,
         '{{"authority": "GSTN"}}'::jsonb, 'open', FALSE, '{TASK}', NOW(), NOW());
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr

    check = _psql(
        migrated_db,
        f"SELECT ca_approved, ca_approved_by, ca_approved_at FROM public.government_notices WHERE id='{NOTICE}';",
        tuples=True,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "f||"  # ca_approved=false, by/at NULL


def test_notice_approve_update_payload_succeeds(migrated_db):
    """Exact shape of the UPDATE built in document_intelligence_v2.approve_notice
    (ca_approved / ca_approved_by / ca_approved_at) must succeed against real PG."""
    seed = _psql(
        migrated_db,
        f"""
        INSERT INTO public.government_notices
            (id, firm_id, client_id, notice_type, authority, status, ca_approved)
        VALUES ('{NOTICE}', '{FIRM}', '{CLIENT}', 'gst_scrutiny', 'GSTN', 'open', FALSE);
        """,
    )
    assert seed.returncode == 0, seed.stderr

    update_sql = f"""
    UPDATE public.government_notices
    SET ca_approved = TRUE, ca_approved_by = '{APPROVER}', ca_approved_at = NOW(), updated_at = NOW()
    WHERE id = '{NOTICE}';
    """
    r = _psql(migrated_db, update_sql)
    assert r.returncode == 0, r.stderr

    check = _psql(
        migrated_db,
        f"SELECT ca_approved, ca_approved_by FROM public.government_notices WHERE id='{NOTICE}';",
        tuples=True,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == f"t|{APPROVER}"
