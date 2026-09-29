"""
Migration 437 — a timeline event's financial_year must match its own
document's date, not the day the event happened to be written.

WHY THIS FILE EXISTS
    This is a one-off DATA correction (an UPDATE, no DDL), which this repo has
    no established per-migration test pattern for (checked: migration 399, the
    closest analogue — a column back-fill — has no dedicated _pg.py test
    either). This file is that pattern for a data correction: seed a small
    fixture with the EXACT wrong shape the bug produced, run the migration's
    own SQL FILE (not a reimplementation of its CASE expression — a copy could
    drift from what actually ships), and assert both that it corrects the
    wrong rows and leaves already-right rows untouched on a second run
    (idempotent).

    `pg_template` (tests/conftest.py) already applies the FULL migration set,
    437 included, before this file's `db` fixture clones it — so by the time a
    test gets its database, 437 has already run once against EMPTY
    client_sales_invoices/purchase_bills/client_timeline_events tables (a
    no-op). Seeding WRONG data into that already-migrated, empty-of-real-rows
    database and running 437's SQL file a SECOND time is exactly the scenario
    that matters: it exercises the identical statements production runs, both
    for correctness and for idempotency (a third run changes nothing further).

⚠️ NOT RUN IN THIS ENVIRONMENT'S SANDBOX: HARNESS_PG requires a live
Postgres 16 the sandbox could not safely provide without weakening its own
authentication (see the migration's own commit message). It self-skips
without HARNESS_PG + psql, exactly like every other test_*_pg.py in this
suite, and should be exercised in CI.
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
MIGRATION_FILE = API_ROOT / "migrations" / "437_a_timeline_events_financial_year_is_its_documents_own.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists() or not MIGRATION_FILE.exists(),
    reason="migration 437's data-correction SQL requires HARNESS_PG + psql",
)

FIRM = "f4370000-0000-0000-0000-000000000001"
CLIENT = "c4370000-0000-0000-0000-000000000001"
CUSTOMER = "94370000-0000-0000-0000-000000000001"
VENDOR = "94370000-0000-0000-0000-000000000002"
INVOICE_ID = "14370000-0000-0000-0000-000000000001"
BILL_ID = "14370000-0000-0000-0000-000000000002"
UNTOUCHED_INVOICE_ID = "14370000-0000-0000-0000-000000000003"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _run_migration_file(dsn: str) -> subprocess.CompletedProcess:
    """Executes the ACTUAL migration file, unmodified — never a hand-copied
    version of its CASE expression, which could silently drift from what
    ships."""
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-f", str(MIGRATION_FILE)],
        capture_output=True, text=True,
    )


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    admin_dsn = f"{admin} dbname=postgres"
    name = f"tl437_{uuid.uuid4().hex[:12]}"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _seed(dsn: str) -> None:
    r = _psql(dsn, f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', '437 Test Firm', 'a@437test.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', '437 Test Client', 'Private Limited');
INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Test Customer');
INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Test Vendor');

-- An invoice DATED in FY 2025-26 (15 Jan 2026) but — per the bug this
-- migration fixes — its timeline event was stamped with the FY it was
-- POSTED in, 2026-27 (e.g. entered months later, or a backdated Tally
-- migration entry).
INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date)
  VALUES ('{INVOICE_ID}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-437-TEST', '2026-01-15');
INSERT INTO client_timeline_events
  (client_id, firm_id, financial_year, category, event_type, title, entity_type, entity_id)
  VALUES ('{CLIENT}', '{FIRM}', '2026-27', 'accounting', 'invoice_posted',
          'Sales Invoice INV-437-TEST posted', 'sales_invoice', '{INVOICE_ID}');

-- A bill DATED in FY 2024-25 (20 Feb 2025) wrongly stamped 2026-27.
INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date)
  VALUES ('{BILL_ID}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'BILL-437-TEST', '2025-02-20');
INSERT INTO client_timeline_events
  (client_id, firm_id, financial_year, category, event_type, title, entity_type, entity_id)
  VALUES ('{CLIENT}', '{FIRM}', '2026-27', 'accounting', 'bill_posted',
          'Purchase Bill BILL-437-TEST posted', 'purchase_bill', '{BILL_ID}');

-- A SECOND invoice, dated 10 May 2026 (FY 2026-27), whose event was ALREADY
-- stamped correctly (972cb98 shipped) — must not be touched, and must not
-- appear in the migration's own row-count either.
INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date)
  VALUES ('{UNTOUCHED_INVOICE_ID}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-437-OK', '2026-05-10');
INSERT INTO client_timeline_events
  (client_id, firm_id, financial_year, category, event_type, title, entity_type, entity_id)
  VALUES ('{CLIENT}', '{FIRM}', '2026-27', 'accounting', 'invoice_posted',
          'Sales Invoice INV-437-OK posted', 'sales_invoice', '{UNTOUCHED_INVOICE_ID}');
""")
    assert r.returncode == 0, f"seed failed: {r.stderr}"


def _fy_of(dsn: str, entity_id: str) -> str:
    r = _psql(dsn, f"SELECT financial_year FROM client_timeline_events WHERE entity_id = '{entity_id}'::uuid;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_a_backdated_invoice_events_fy_is_corrected_to_its_own_invoice_date(db):
    _seed(db)
    assert _fy_of(db, INVOICE_ID) == "2026-27"          # the wrong, as-posted value

    result = _run_migration_file(db)
    assert result.returncode == 0, f"migration 437 failed: {result.stderr}"

    assert _fy_of(db, INVOICE_ID) == "2025-26", (
        "15 Jan 2026 falls in FY 2025-26 (1 Apr 2025 - 31 Mar 2026); the "
        "corrected label must be the INVOICE's own FY, not the FY it was "
        "posted in")


def test_a_backdated_bills_event_fy_is_corrected_to_its_own_bill_date(db):
    _seed(db)
    assert _fy_of(db, BILL_ID) == "2026-27"

    result = _run_migration_file(db)
    assert result.returncode == 0, f"migration 437 failed: {result.stderr}"

    assert _fy_of(db, BILL_ID) == "2024-25", "20 Feb 2025 falls in FY 2024-25"


def test_an_already_correct_event_is_left_untouched(db):
    _seed(db)
    assert _fy_of(db, UNTOUCHED_INVOICE_ID) == "2026-27"

    result = _run_migration_file(db)
    assert result.returncode == 0, f"migration 437 failed: {result.stderr}"

    assert _fy_of(db, UNTOUCHED_INVOICE_ID) == "2026-27", (
        "10 May 2026 IS in FY 2026-27 — this row was already right and the "
        "IS DISTINCT FROM guard must not have touched it")


def test_running_the_migration_a_second_time_changes_nothing_further(db):
    """Idempotency: the scenario production actually needs, since a migration
    is recorded as applied once but this file's own UPDATEs must be safe to
    re-run (e.g. a manual re-application, or this very test suite)."""
    _seed(db)
    first = _run_migration_file(db)
    assert first.returncode == 0, f"migration 437 first run failed: {first.stderr}"

    invoice_fy_after_first = _fy_of(db, INVOICE_ID)
    bill_fy_after_first = _fy_of(db, BILL_ID)
    assert invoice_fy_after_first == "2025-26"
    assert bill_fy_after_first == "2024-25"

    second = _run_migration_file(db)
    assert second.returncode == 0, f"migration 437 second run failed: {second.stderr}"

    assert _fy_of(db, INVOICE_ID) == invoice_fy_after_first
    assert _fy_of(db, BILL_ID) == bill_fy_after_first
    assert _fy_of(db, UNTOUCHED_INVOICE_ID) == "2026-27"


def test_the_correction_matches_ist_fy_label_across_the_1_april_boundary(db):
    """A second pair of documents straddling 31 March / 1 April, to pin the
    boundary itself rather than only mid-year dates."""
    boundary_invoice = "14370000-0000-0000-0000-000000000004"
    boundary_bill = "14370000-0000-0000-0000-000000000005"
    r = _psql(db, f"""
INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date)
  VALUES ('{boundary_invoice}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-437-BOUNDARY', '2026-04-01');
INSERT INTO client_timeline_events
  (client_id, firm_id, financial_year, category, event_type, title, entity_type, entity_id)
  VALUES ('{CLIENT}', '{FIRM}', '2099-99', 'accounting', 'invoice_posted',
          'Sales Invoice INV-437-BOUNDARY posted', 'sales_invoice', '{boundary_invoice}');

INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date)
  VALUES ('{boundary_bill}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'BILL-437-BOUNDARY', '2026-03-31');
INSERT INTO client_timeline_events
  (client_id, firm_id, financial_year, category, event_type, title, entity_type, entity_id)
  VALUES ('{CLIENT}', '{FIRM}', '2099-99', 'accounting', 'bill_posted',
          'Purchase Bill BILL-437-BOUNDARY posted', 'purchase_bill', '{boundary_bill}');
""")
    assert r.returncode == 0, r.stderr

    result = _run_migration_file(db)
    assert result.returncode == 0, f"migration 437 failed: {result.stderr}"

    assert _fy_of(db, boundary_invoice) == "2026-27", "1 April 2026 starts FY 2026-27"
    assert _fy_of(db, boundary_bill) == "2025-26", "31 March 2026 is still FY 2025-26"
