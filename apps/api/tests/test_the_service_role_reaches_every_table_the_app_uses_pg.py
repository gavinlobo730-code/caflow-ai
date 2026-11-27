"""
R269 — proves on real PostgreSQL that the backend's own role can reach every
table the app uses: read what it reads, and write what it writes.

Migration 306 changed what this file asserts about five of them. It used to pin
receipts, receipt_allocations, credit_notes, purchase_bills and
purchase_payments as SELECT-only for service_role, following migration 096's
"the reporting engine never writes to these tables". That is true of the
reporting engine and false of the ROLE: the document-creation endpoints run as
service_role as well, so the narrowing broke every purchase bill, receipt and
vendor payment created through the API. The assertion is now the other way up,
and a general write-side invariant sits beside it so the next occurrence is
caught by shape rather than by name.

WHY THIS IS A REAL-POSTGRES TEST AND NOT A MOCK ONE
    Grants do not exist in mock mode. The gap this closes was invisible to the
    entire mock-mode suite for as long as it existed, and only surfaced when the
    daily sweep finally ran in production and five job/firm pairs came back with
    SQLSTATE 42501. A mock test would have passed throughout.

THE INVARIANT, NOT THE 86 INSTANCES
    test_no_table_grants_authenticated_without_service_role is the one that
    matters. Naming the tables that were broken on 2026-08-17 would pass forever
    the moment they were fixed; asserting the SHAPE fails the next time a
    migration creates a table and grants only `authenticated`, which is how 86
    of them accumulated in the first place.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="service_role grant proof requires HARNESS_PG + psql",
)

# The five documents the backend both reads AND writes. 096 granted them SELECT
# because the reporting engine was raising 42501 on reads; 269 carried that
# forward as a least-privilege decision and this file used to pin them
# write-less. Migration 306 undoes that: routers/purchase_bills.py,
# routers/receipts.py and routers/purchase_payments.py all write these through
# get_supabase(), which is the service-role client whenever USE_USER_JWT is off
# or no caller token is present. See 306's header for the whole argument.
MONEY_DOCUMENTS = (
    "receipts",
    "receipt_allocations",
    "credit_notes",
    "purchase_bills",
    "purchase_payments",
)

# The three that actually failed in production on 2026-08-17, kept as a
# regression anchor alongside the general invariant.
FAILED_IN_PRODUCTION = ("task_recurring_configs", "fee_invoices", "fee_engagements")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A", "-c", sql],
        capture_output=True, text=True,
    )


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r269_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _rows(result: subprocess.CompletedProcess) -> list[str]:
    return [line for line in result.stdout.strip().splitlines() if line]


# ── The invariant ─────────────────────────────────────────────────────────────

def test_no_table_grants_authenticated_without_service_role(migrated_db):
    """If `authenticated` can SELECT it, the backend's own role must be able to.

    This is the shape the 86-table gap had. A new table granted only to
    `authenticated` fails here rather than in production six weeks later.
    """
    result = _psql(migrated_db, """
        WITH sel AS (
          SELECT table_name, grantee
          FROM information_schema.role_table_grants
          WHERE table_schema = 'public' AND privilege_type = 'SELECT'
            AND grantee IN ('service_role', 'authenticated')
          GROUP BY table_name, grantee
        )
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
          AND EXISTS (SELECT 1 FROM sel WHERE sel.table_name = t.table_name
                        AND sel.grantee = 'authenticated')
          AND NOT EXISTS (SELECT 1 FROM sel WHERE sel.table_name = t.table_name
                            AND sel.grantee = 'service_role')
        ORDER BY t.table_name;
    """)
    assert result.returncode == 0, result.stderr
    missing = _rows(result)
    assert not missing, (
        "these tables let `authenticated` SELECT but not service_role — the "
        "backend's background jobs will fail on them with SQLSTATE 42501: "
        f"{missing}"
    )


def test_the_three_that_failed_in_production_are_readable(migrated_db):
    for table in FAILED_IN_PRODUCTION:
        result = _psql(
            migrated_db,
            f"SELECT has_table_privilege('service_role', 'public.{table}', 'SELECT');",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "t", f"service_role cannot SELECT {table}"


def test_jobs_can_write_where_they_must(migrated_db):
    """recurring_generation stamps last_generated_at; invoice_overdue flips a
    status. Read access alone would just move the 42501 one line down."""
    for table in ("task_recurring_configs", "fee_invoices"):
        result = _psql(
            migrated_db,
            f"SELECT has_table_privilege('service_role', 'public.{table}', 'UPDATE');",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "t", f"service_role cannot UPDATE {table}"


# ── The money documents (migration 306) ──────────────────────────────────────

def test_reporting_tables_stay_readable(migrated_db):
    for table in MONEY_DOCUMENTS:
        result = _psql(
            migrated_db,
            f"SELECT has_table_privilege('service_role', 'public.{table}', 'SELECT');",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "t", f"reporting reads {table} — SELECT is required"


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE", "DELETE"])
def test_the_money_documents_are_writable_by_the_backend(migrated_db, privilege):
    """The assertion this file used to make was the exact opposite, and it was
    wrong — it pinned a least-privilege narrowing that broke the feature.

    096 reasoned "the reporting engine never writes to these tables", which is
    true of the reporting engine and not of the role. The document-creation
    endpoints run as service_role too and write all five, so with USE_USER_JWT
    off every purchase bill, receipt and vendor payment failed with 42501
    before RLS was consulted. Found by driving a client through a full year:
    24 of 24 bills failed, one GRANT and 24 of 24 posted.
    """
    for table in MONEY_DOCUMENTS:
        result = _psql(
            migrated_db,
            f"SELECT has_table_privilege('service_role', 'public.{table}', '{privilege}');",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "t", (
            f"service_role cannot {privilege} {table} — the endpoint that creates "
            "this document runs as service_role and will fail with SQLSTATE 42501"
        )


def test_no_table_grants_authenticated_write_without_service_role(migrated_db):
    """The invariant that makes the five names unnecessary.

    Its SELECT twin above catches a table granted READ to `authenticated` only.
    This is the write side, and it is the one that would have caught migration
    050's original omission, 193's repeat on debit_notes, and the five this
    file used to assert in the wrong direction. Asserting the SHAPE fails the
    next occurrence; naming tables passes forever once they are fixed.

    A header whose LINES are writable and itself is not is the specific
    incoherence this stops: on production before migration 306,
    purchase_bill_lines had INSERT and purchase_bills did not.
    """
    result = _psql(migrated_db, """
        WITH w AS (
          SELECT table_name, grantee
          FROM information_schema.role_table_grants
          WHERE table_schema = 'public' AND privilege_type = 'INSERT'
            AND grantee IN ('service_role', 'authenticated')
          GROUP BY table_name, grantee
        )
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
          AND EXISTS (SELECT 1 FROM w WHERE w.table_name = t.table_name
                        AND w.grantee = 'authenticated')
          AND NOT EXISTS (SELECT 1 FROM w WHERE w.table_name = t.table_name
                            AND w.grantee = 'service_role')
        ORDER BY t.table_name;
    """)
    assert result.returncode == 0, result.stderr
    missing = _rows(result)
    assert not missing, (
        "these tables let `authenticated` INSERT but not service_role — every "
        "backend write to them fails with SQLSTATE 42501 before RLS is even "
        f"evaluated: {missing}"
    )


# ── The pattern guard ─────────────────────────────────────────────────────────

def test_default_privileges_cover_future_tables(migrated_db):
    """Step 5 of the migration. Without it the next table granted only to
    `authenticated` reopens the gap, which is how 86 of them accumulated."""
    created = _psql(migrated_db, "CREATE TABLE public.r269_probe (id int primary key);")
    assert created.returncode == 0, created.stderr

    result = _psql(
        migrated_db,
        "SELECT has_table_privilege('service_role', 'public.r269_probe', 'SELECT');",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "t", (
        "a newly created table did not inherit service_role SELECT — the "
        "ALTER DEFAULT PRIVILEGES in migration 269 is not taking effect"
    )
