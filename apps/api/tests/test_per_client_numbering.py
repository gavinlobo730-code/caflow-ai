"""
R1.1 — per-client document numbering (fixes audit finding F6).

Proves, against a real PostgreSQL, that migration 151 lets two bookkeeping
clients of the SAME firm each hold their own SINV-{fy}-0001 / CN-{fy}-0001 (the
collision that previously 500'd the second client and blocked any multi-client
firm), while a duplicate number WITHIN one client is still rejected (statutory
per-supplier uniqueness, CGST Rule 46).

Runs only when HARNESS_PG is set (a keyword DSN without a dbname) and psql is on
PATH — same gate as tests/test_migrations_apply.py; skips in the mock-mode CI
job. The dedicated `migrations` CI job runs it against its Postgres service.
"""
from __future__ import annotations

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
    reason="per-client numbering proof requires HARNESS_PG + psql",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT_A = "22222222-2222-2222-2222-222222222222"
CLIENT_B = "33333333-3333-3333-3333-333333333333"
CUST_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CUST_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

SEED = f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}','Test CA Firm','firm@test.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT_A}','{FIRM}','Client A Pvt Ltd','Private Limited'),
  ('{CLIENT_B}','{FIRM}','Client B Pvt Ltd','Private Limited');
INSERT INTO customers (id, firm_id, client_id, name) VALUES
  ('{CUST_A}','{FIRM}','{CLIENT_A}','Cust A'),
  ('{CUST_B}','{FIRM}','{CLIENT_B}','Cust B');
"""


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


@pytest.fixture()
def seeded_db():
    admin = _ADMIN.strip()
    dbname = f"r11_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Apply the full migration set (with compat bootstrap) up to and incl. 151.
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dsn", dsn,
             "--with-compat", "--only-schema", "--continue-on-error"],
            capture_output=True, text=True, cwd=str(API_ROOT),
        )
        # 151 must be among the cleanly-applied migrations (not the drift baseline).
        assert "applied compat bootstrap" in proc.stderr
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _insert_invoice(dsn: str, client_id: str, customer_id: str, no: str, day: str):
    return _psql(dsn, (
        "INSERT INTO client_sales_invoices "
        "(firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise) VALUES "
        f"('{FIRM}','{client_id}','{customer_id}','{no}','{day}',100000);"
    ))


def _insert_credit_note(dsn: str, client_id: str, customer_id: str, no: str, day: str):
    return _psql(dsn, (
        "INSERT INTO credit_notes "
        "(firm_id, client_id, customer_id, credit_note_no, credit_note_date) VALUES "
        f"('{FIRM}','{client_id}','{customer_id}','{no}','{day}');"
    ))


def test_two_clients_can_share_invoice_number(seeded_db):
    dsn = seeded_db
    # Client A issues SINV-2526-0001.
    a = _insert_invoice(dsn, CLIENT_A, CUST_A, "SINV-2526-0001", "2026-04-05")
    assert a.returncode == 0, a.stderr
    # Client B (same firm) issues the SAME number — was the F6 collision; must now succeed.
    b = _insert_invoice(dsn, CLIENT_B, CUST_B, "SINV-2526-0001", "2026-04-06")
    assert b.returncode == 0, f"F6 regression — 2nd client blocked: {b.stderr}"


def test_same_client_duplicate_invoice_number_rejected(seeded_db):
    dsn = seeded_db
    assert _insert_invoice(dsn, CLIENT_A, CUST_A, "SINV-2526-0001", "2026-04-05").returncode == 0
    dup = _insert_invoice(dsn, CLIENT_A, CUST_A, "SINV-2526-0001", "2026-04-07")
    assert dup.returncode != 0, "same-client duplicate invoice_no must be rejected"
    assert "unique" in dup.stderr.lower() or "duplicate key" in dup.stderr.lower()


def test_two_clients_can_share_credit_note_number(seeded_db):
    dsn = seeded_db
    a = _insert_credit_note(dsn, CLIENT_A, CUST_A, "CN-2526-0001", "2026-04-05")
    assert a.returncode == 0, a.stderr
    b = _insert_credit_note(dsn, CLIENT_B, CUST_B, "CN-2526-0001", "2026-04-06")
    assert b.returncode == 0, f"F6 regression (credit notes) — 2nd client blocked: {b.stderr}"


def test_same_client_duplicate_credit_note_number_rejected(seeded_db):
    dsn = seeded_db
    assert _insert_credit_note(dsn, CLIENT_A, CUST_A, "CN-2526-0001", "2026-04-05").returncode == 0
    dup = _insert_credit_note(dsn, CLIENT_A, CUST_A, "CN-2526-0001", "2026-04-07")
    assert dup.returncode != 0, "same-client duplicate credit_note_no must be rejected"
