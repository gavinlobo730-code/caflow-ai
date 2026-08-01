"""
Task #226 fix — GST/TDS schema-drift proof, on real PostgreSQL.

Background
----------
routers/gst_workspace.py's save_gstr1/save_gstr3b/save_gstr9 have always
inserted total_taxable_paise/total_igst_paise/total_cgst_paise/
total_sgst_paise/total_cess_paise/tax_liability_paise/itc_claimed_paise/
net_tax_paise/total_tax_paise columns that migration 036 never created on
gstr1_returns/gstr3b_returns — every "save draft" call has been failing
against real Postgres (masked behind a generic "Unable to complete GST
operation" try/except; only the in-memory mock store's tests
(test_phase3_gst.py) ever exercised these inserts).

domain/income_tax/form26as_service.py's create_upload/save_parsed_records
(and, independently, routers/tds_workspace.py's upload_form26as) write
parse_status/total_records/parsed_at/document_id onto form_26as_uploads —
none of which migration 052 created either.

Migration 234 adds all of these columns additively (same repair pattern as
155/157/158/232/233: a new migration, never editing 036/052). This test
performs the EXACT insert/update payloads the fixed routers/services build,
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
    reason="GST/TDS schema-drift proof requires HARNESS_PG + psql",
)

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"gsttds_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        # 036 (creates gstr1_returns/gstr3b_returns), 052 (creates
        # form_26as_uploads), and 234 (adds the missing columns) must all
        # apply cleanly — that's the only thing this proof depends on.
        assert "036_gst_engine.sql" not in failed
        assert "052_phase3_compliance.sql" not in failed
        assert "234_gst_tds_schema_drift_fixes.sql" not in failed
        # firms/clients rows the FK-constrained inserts below need.
        firm_ins = _psql(dsn, f"INSERT INTO public.firms (id, name, email) "
                              f"VALUES ('{FIRM}', 'Test Firm', 'firm@test.com');")
        assert firm_ins.returncode == 0, firm_ins.stderr
        client_ins = _psql(
            dsn,
            f"INSERT INTO public.clients (id, firm_id, client_name, entity_type, pan) "
            f"VALUES ('{CLIENT}', '{FIRM}', 'Test Client', 'Private Limited', 'AAAAA9999A');",
        )
        assert client_ins.returncode == 0, client_ins.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_gstr1_returns_has_total_columns(migrated_db):
    """Also proves financial_year/return_type exist — migration 053 also adds
    them, but 053 fails to apply cleanly in a fresh run (a separate,
    already-documented R2.6 drift-backlog bug — see
    test_migrations_apply.py's EXPECTED_MIGRATION_FAILURES), so migration 234
    re-asserts them idempotently to not depend on 053 succeeding."""
    r = _psql(
        migrated_db,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='gstr1_returns' AND table_schema='public' "
        "AND column_name IN ('total_taxable_paise','total_igst_paise',"
        "'total_cgst_paise','total_sgst_paise','total_cess_paise','total_tax_paise',"
        "'return_type','financial_year') "
        "ORDER BY column_name;",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    cols = {c for c in r.stdout.strip().splitlines() if c}
    assert cols == {
        "total_cess_paise", "total_cgst_paise", "total_igst_paise",
        "total_sgst_paise", "total_taxable_paise", "total_tax_paise",
        "return_type", "financial_year",
    }


def test_gstr3b_returns_has_summary_columns(migrated_db):
    """Also proves gstin/summary_json exist — migration 036's CREATE TABLE
    never included either on gstr3b_returns (it only has payload_json, unlike
    gstr1_returns which has both), even though save_gstr3b has always
    inserted them."""
    r = _psql(
        migrated_db,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='gstr3b_returns' AND table_schema='public' "
        "AND column_name IN ('tax_liability_paise','itc_claimed_paise','net_tax_paise','gstin','summary_json') "
        "ORDER BY column_name;",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    cols = {c for c in r.stdout.strip().splitlines() if c}
    assert cols == {
        "itc_claimed_paise", "net_tax_paise", "tax_liability_paise",
        "gstin", "summary_json",
    }


def test_form_26as_uploads_has_pipeline_columns(migrated_db):
    r = _psql(
        migrated_db,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='form_26as_uploads' AND table_schema='public' "
        "AND column_name IN ('document_id','parse_status','total_records','parsed_at','parse_errors') "
        "ORDER BY column_name;",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    cols = {c for c in r.stdout.strip().splitlines() if c}
    assert cols == {"document_id", "parse_errors", "parse_status", "parsed_at", "total_records"}


def test_save_gstr1_insert_payload_succeeds(migrated_db):
    """Exact shape of the INSERT built in gst_workspace.save_gstr1 must
    succeed against real PG."""
    return_id = str(uuid.uuid4())
    insert_sql = f"""
    INSERT INTO public.gstr1_returns
        (id, firm_id, client_id, period, gstin, payload_json, summary_json,
         total_taxable_paise, total_igst_paise, total_cgst_paise,
         total_sgst_paise, total_cess_paise, status, created_at)
    VALUES
        ('{return_id}', '{FIRM}', '{CLIENT}', '042025', '27AABCU9603R1ZX',
         '{{}}'::jsonb, '{{}}'::jsonb, 10000000, 0, 900000, 900000, 0,
         'draft', NOW());
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr


def test_save_gstr9_insert_payload_succeeds(migrated_db):
    """Exact shape of the INSERT built in gst_workspace.save_gstr9 (which
    reuses gstr1_returns, return_type='gstr9') must succeed against real PG.
    gstin is included — gstr1_returns.gstin is NOT NULL and the original
    GSTR9In model never collected it (a second bug this proof test caught)."""
    return_id = str(uuid.uuid4())
    insert_sql = f"""
    INSERT INTO public.gstr1_returns
        (id, firm_id, client_id, financial_year, period, return_type, gstin, status,
         payload_json, summary_json, total_taxable_paise, total_igst_paise,
         total_cgst_paise, total_sgst_paise, total_tax_paise, created_at)
    VALUES
        ('{return_id}', '{FIRM}', '{CLIENT}', '2025-26', 'FY2025-26', 'gstr9', '27AABCU9603R1ZX', 'draft',
         '{{}}'::jsonb, '{{}}'::jsonb, 500000000, 0, 45000000, 45000000, 90000000, NOW());
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr


def test_save_gstr3b_insert_payload_succeeds(migrated_db):
    """Exact shape of the INSERT built in gst_workspace.save_gstr3b must
    succeed against real PG."""
    return_id = str(uuid.uuid4())
    insert_sql = f"""
    INSERT INTO public.gstr3b_returns
        (id, firm_id, client_id, period, gstin, payload_json, summary_json,
         tax_liability_paise, itc_claimed_paise, net_tax_paise, status, created_at)
    VALUES
        ('{return_id}', '{FIRM}', '{CLIENT}', '042025', '27AABCU9603R1ZX',
         '{{}}'::jsonb, '{{}}'::jsonb, 1800000, 500000, 1300000, 'draft', NOW());
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr


def test_form26as_create_upload_insert_succeeds(migrated_db):
    """Exact shape of the INSERT built in form26as_service.create_upload
    (real, non-mock branch) must succeed against real PG."""
    upload_id = str(uuid.uuid4())
    insert_sql = f"""
    INSERT INTO public.form_26as_uploads
        (id, firm_id, client_id, financial_year, document_id, created_by)
    VALUES
        ('{upload_id}', '{FIRM}', '{CLIENT}', '2025-26', NULL, '{FIRM}');
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr

    # Exact shape of the UPDATE built in form26as_service.save_parsed_records.
    update_sql = f"""
    UPDATE public.form_26as_uploads
    SET parse_status = 'parsed', total_records = 5, parsed_at = NOW()
    WHERE id = '{upload_id}';
    """
    r2 = _psql(migrated_db, update_sql)
    assert r2.returncode == 0, r2.stderr

    check = _psql(
        migrated_db,
        f"SELECT parse_status, total_records FROM public.form_26as_uploads WHERE id='{upload_id}';",
        tuples=True,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "parsed|5"


def test_tds_workspace_upload_form26as_insert_succeeds(migrated_db):
    """Exact shape of the INSERT built in tds_workspace.upload_form26as
    (fixed to insert `record`, matching the real columns) must succeed."""
    upload_id = str(uuid.uuid4())
    insert_sql = f"""
    INSERT INTO public.form_26as_uploads
        (id, firm_id, client_id, financial_year, file_url, raw_data,
         reconciliation_result, status, created_by, uploaded_at)
    VALUES
        ('{upload_id}', '{FIRM}', '{CLIENT}', '2025-26', NULL, '{{}}'::jsonb,
         '{{}}'::jsonb, 'reconciled', '{FIRM}', NOW());
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr


def test_tds_certificate_pending_status_insert_succeeds(migrated_db):
    """tds_certificates.status='pending' (the fixed value, replacing the
    invalid 'draft') must satisfy the real CHECK constraint (migration 037)."""
    cert_id = str(uuid.uuid4())
    insert_sql = f"""
    INSERT INTO public.tds_certificates
        (id, firm_id, client_id, certificate_type, deductee_name, deductee_pan,
         financial_year, tds_deducted_paise, status)
    VALUES
        ('{cert_id}', '{FIRM}', '{CLIENT}', '16A', 'Vendor Pvt Ltd', 'AAAAA9999A',
         '2025-26', 500000, 'pending');
    """
    r = _psql(migrated_db, insert_sql)
    assert r.returncode == 0, r.stderr
