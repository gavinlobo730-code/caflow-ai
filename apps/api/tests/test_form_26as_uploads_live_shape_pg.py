"""
Migration 291 must apply to the shape the LIVE database actually has.

WHY THIS EXISTS
    291 passed every local check and then failed against production:

        291_form_26as_reconciliation_redesign.sql
        ERROR:  column "status" does not exist

    `form_26as_uploads` has two different shapes. Migration 052 declares it with
    file_url / raw_data / reconciliation_result / status / created_by. The live
    database has none of those: it has uploaded_by, NOT NULL, instead.

    Nothing compared them. The CI template is built from the migrations with
    --continue-on-error, so every local run, every migration test and both
    column checkers only ever saw the 052 shape — while the live table has
    always been the other one. A migration can therefore be green here and
    broken there, and the only signal is a production failure after merge.

    The same blind spot had already caused a live bug. A previous audit saw
    create_upload writing `uploaded_by`, concluded from migration 052 that no
    such column exists, and removed it — deleting the one column production
    requires. Every 26AS upload has failed on the live database since, which is
    why form_26as_uploads holds zero rows there. See
    tests/test_phase14_tax_integrations.py::
    test_create_upload_real_branch_inserts_valid_columns.

WHAT THIS CHECKS
    Every statement in 291 that touches form_26as_uploads, replayed against a
    table built to the LIVE shape rather than the migration's. The statements
    are read out of the migration file itself, so this cannot drift away from
    what actually runs.

    It does not make the two shapes agree — 291's converging ALTER does that.
    It checks that the migration survives meeting the real one.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

MIGRATION = (Path(__file__).resolve().parents[1]
             / "migrations" / "291_form_26as_reconciliation_redesign.sql")
_HARNESS_PG = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql",
)

# The live table, column for column, as read from the production database on
# 2026-08-30 — the day 291 failed against it. uploaded_by is NOT NULL with no
# default, which is what the removed insert key violated.
LIVE_SHAPE = """
CREATE TABLE public.form_26as_uploads (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL,
  client_id       UUID NOT NULL,
  financial_year  TEXT NOT NULL,
  document_id     UUID,
  parse_status    TEXT NOT NULL DEFAULT 'pending',
  total_records   INTEGER NOT NULL DEFAULT 0,
  parse_errors    JSONB NOT NULL DEFAULT '[]',
  uploaded_by     UUID NOT NULL,
  uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  parsed_at       TIMESTAMPTZ
);
"""


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def statements_touching_uploads() -> list[str]:
    """Every statement in 291 that names form_26as_uploads, in file order.

    Read from the migration rather than restated here, so the test exercises
    what actually ships. COMMENT ON is included: it names columns too, and a
    comment on a column that does not exist is an error like any other.
    """
    body = _strip_sql_comments(MIGRATION.read_text(encoding="utf-8"))
    out = []
    for raw in body.split(";"):
        stmt = raw.strip()
        if stmt and "form_26as_uploads" in stmt:
            out.append(stmt + ";")
    return out


@_NEEDS_PG
def test_the_migration_has_statements_for_this_table():
    """Guard the guard: a rename would otherwise make this vacuously pass."""
    stmts = statements_touching_uploads()
    assert len(stmts) >= 3, stmts
    assert any(s.lstrip().upper().startswith("ALTER TABLE") for s in stmts)
    assert any(s.lstrip().upper().startswith("UPDATE") for s in stmts)


@_NEEDS_PG
def test_migration_291_applies_to_the_live_table_shape():
    """The exact failure: 'column "status" does not exist' on the backfill."""
    admin = _HARNESS_PG.strip()
    admin_dsn = f"{admin} dbname=postgres"
    name = f"caflow_liveshape_{uuid.uuid4().hex[:12]}"

    if _psql(admin_dsn, f'CREATE DATABASE "{name}";').returncode != 0:
        pytest.skip("could not create the scratch database")

    dsn = f"{admin} dbname={name}"
    try:
        created = _psql(dsn, LIVE_SHAPE)
        assert created.returncode == 0, created.stderr

        for stmt in statements_touching_uploads():
            res = _psql(dsn, stmt)
            assert res.returncode == 0, (
                f"migration 291 fails against the live table shape.\n"
                f"statement: {stmt[:200]}\nerror: {res.stderr.strip()}"
            )

        # The converging ALTER must leave BOTH identity columns present, since
        # the insert names both to satisfy the live NOT NULL and the template.
        cols = _psql(dsn, (
            "SELECT string_agg(column_name, ',' ORDER BY column_name) "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='form_26as_uploads';"
        ))
        assert cols.returncode == 0, cols.stderr
        present = cols.stdout
        for column in ("uploaded_by", "created_by", "status",
                       "reconciliation_result", "source"):
            assert column in present, f"{column} missing after 291: {present}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')
