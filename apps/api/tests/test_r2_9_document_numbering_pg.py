"""
R2.9 — document-number uniqueness for debit notes, receipts, purchase
payments, proven on real PostgreSQL.

Background
----------
routers/debit_notes.py::_next_dn_seq and services/receipt_service.py::
_next_receipt_seq both compute a per-(firm, client, FY) sequence (CGST
Rule 46/53 — each client is its own supplier series); routers/
purchase_payments.py::_next_payment_seq computes a per-(firm, FY) sequence
(a firm-wide voucher series). None of the three backing tables had ANY
uniqueness constraint on its number column (migrations 050, 145), so a
genuine concurrent race could commit two rows with an identical number, and
services/numbering.py's retry (already used by debit_notes) could never
actually fire.

Migration 159 adds the missing constraints, matching each table's real
generator scope, preceded by a de-dup step for any duplicate already
committed under the unenforced gap (see the migration file's own docstring
for the exact renumbering rule).

Runs only when HARNESS_PG is set + psql on PATH (same gate as the other
real-Postgres tests); skips in the mock-mode CI job. The `migrations` CI job
runs it against its Postgres service.
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
MIGRATION_159 = API_ROOT / "migrations" / "159_document_numbering_uniqueness.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="document-numbering uniqueness proof requires HARNESS_PG + psql",
)

FIRM = "44444444-4444-4444-4444-444444444444"
CLIENT_A = "55555555-5555-5555-5555-555555555555"
CLIENT_B = "66666666-6666-6666-6666-666666666666"
CUST_A = "77777777-7777-7777-7777-777777777777"
CUST_B = "88888888-8888-8888-8888-888888888888"
VENDOR_A = "99999999-9999-9999-9999-999999999999"

SEED = f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}','Test CA Firm R2.9','r29@test.in');
INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
  ('{CLIENT_A}','{FIRM}','R2.9 Client A Pvt Ltd','Private Limited'),
  ('{CLIENT_B}','{FIRM}','R2.9 Client B Pvt Ltd','Private Limited');
INSERT INTO customers (id, firm_id, client_id, name) VALUES
  ('{CUST_A}','{FIRM}','{CLIENT_A}','Cust A'),
  ('{CUST_B}','{FIRM}','{CLIENT_B}','Cust B');
INSERT INTO vendors (id, firm_id, client_id, name) VALUES
  ('{VENDOR_A}','{FIRM}','{CLIENT_A}','Vendor A');
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def seeded_db():
    admin = _ADMIN.strip()
    dbname = f"r29_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dsn", dsn,
             "--with-compat", "--only-schema", "--continue-on-error", "--json"],
            capture_output=True, text=True, cwd=str(API_ROOT),
        )
        import json
        report = json.loads(proc.stdout)
        failed = {f["file"] for f in report["failed"]}
        assert "145_debit_notes.sql" not in failed
        assert "159_document_numbering_uniqueness.sql" not in failed
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _insert_debit_note(dsn, client_id, vendor_id, no, day):
    return _psql(dsn, (
        "INSERT INTO debit_notes (firm_id, client_id, vendor_id, debit_note_no, debit_note_date) VALUES "
        f"('{FIRM}','{client_id}','{vendor_id}','{no}','{day}');"
    ))


def _insert_receipt(dsn, client_id, customer_id, no, day):
    return _psql(dsn, (
        "INSERT INTO receipts (firm_id, client_id, customer_id, receipt_no, receipt_date) VALUES "
        f"('{FIRM}','{client_id}','{customer_id}','{no}','{day}');"
    ))


def _insert_payment(dsn, client_id, vendor_id, no, day):
    return _psql(dsn, (
        "INSERT INTO purchase_payments (firm_id, client_id, vendor_id, payment_no, payment_date) VALUES "
        f"('{FIRM}','{client_id}','{vendor_id}','{no}','{day}');"
    ))


# ─── debit_notes: per-client uniqueness ──────────────────────────────────────

def test_two_clients_can_share_debit_note_number(seeded_db):
    dsn = seeded_db
    a = _insert_debit_note(dsn, CLIENT_A, VENDOR_A, "DN-2526-0001", "2026-04-05")
    assert a.returncode == 0, a.stderr
    b = _insert_debit_note(dsn, CLIENT_B, VENDOR_A, "DN-2526-0001", "2026-04-06")
    assert b.returncode == 0, f"debit notes must be scoped per-client: {b.stderr}"


def test_same_client_duplicate_debit_note_number_rejected(seeded_db):
    dsn = seeded_db
    assert _insert_debit_note(dsn, CLIENT_A, VENDOR_A, "DN-2526-0001", "2026-04-05").returncode == 0
    dup = _insert_debit_note(dsn, CLIENT_A, VENDOR_A, "DN-2526-0001", "2026-04-07")
    assert dup.returncode != 0, "same-client duplicate debit_note_no must now be rejected"
    assert "unique" in dup.stderr.lower() or "duplicate key" in dup.stderr.lower()


# ─── receipts: per-client uniqueness ──────────────────────────────────────────

def test_two_clients_can_share_receipt_number(seeded_db):
    dsn = seeded_db
    a = _insert_receipt(dsn, CLIENT_A, CUST_A, "RCPT-2526-0001", "2026-04-05")
    assert a.returncode == 0, a.stderr
    b = _insert_receipt(dsn, CLIENT_B, CUST_B, "RCPT-2526-0001", "2026-04-06")
    assert b.returncode == 0, f"receipts must be scoped per-client: {b.stderr}"


def test_same_client_duplicate_receipt_number_rejected(seeded_db):
    dsn = seeded_db
    assert _insert_receipt(dsn, CLIENT_A, CUST_A, "RCPT-2526-0001", "2026-04-05").returncode == 0
    dup = _insert_receipt(dsn, CLIENT_A, CUST_A, "RCPT-2526-0001", "2026-04-07")
    assert dup.returncode != 0, "same-client duplicate receipt_no must now be rejected"
    assert "unique" in dup.stderr.lower() or "duplicate key" in dup.stderr.lower()


# ─── purchase_payments: per-FIRM uniqueness (not per-client) ────────────────
# _next_payment_seq (routers/purchase_payments.py) counts per (firm_id, fy) with
# no client_id filter — a firm-wide voucher series, unlike the other two.

def test_same_firm_duplicate_payment_number_rejected_even_across_clients(seeded_db):
    dsn = seeded_db
    a = _insert_payment(dsn, CLIENT_A, VENDOR_A, "VPMT-2526-0001", "2026-04-05")
    assert a.returncode == 0, a.stderr
    dup = _insert_payment(dsn, CLIENT_B, VENDOR_A, "VPMT-2526-0001", "2026-04-06")
    assert dup.returncode != 0, (
        "purchase_payments numbering is per-firm (matching _next_payment_seq), "
        "so a duplicate must be rejected even for a different client"
    )
    assert "unique" in dup.stderr.lower() or "duplicate key" in dup.stderr.lower()


def test_different_firm_can_reuse_payment_number(seeded_db):
    dsn = seeded_db
    other_firm = str(uuid.uuid4())
    seed_other = _psql(dsn, f"INSERT INTO firms (id, name, email) VALUES ('{other_firm}','Other Firm','o@test.in');")
    assert seed_other.returncode == 0, seed_other.stderr
    other_client = str(uuid.uuid4())
    other_vendor = str(uuid.uuid4())
    seed_rows = _psql(dsn, (
        f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES "
        f"('{other_client}','{other_firm}','Other Client','Private Limited');"
        f"INSERT INTO vendors (id, firm_id, client_id, name) VALUES "
        f"('{other_vendor}','{other_firm}','{other_client}','Other Vendor');"
    ))
    assert seed_rows.returncode == 0, seed_rows.stderr
    a = _insert_payment(dsn, CLIENT_A, VENDOR_A, "VPMT-2526-0001", "2026-04-05")
    assert a.returncode == 0, a.stderr
    b = _psql(dsn, (
        "INSERT INTO purchase_payments (firm_id, client_id, vendor_id, payment_no, payment_date) VALUES "
        f"('{other_firm}','{other_client}','{other_vendor}','VPMT-2526-0001','2026-04-06');"
    ))
    assert b.returncode == 0, f"a different firm must be able to reuse the same payment_no: {b.stderr}"


# ─── de-dup: migration 159 must safely repair pre-existing duplicates ───────
# Simulates a database that reached production BEFORE this fix existed and
# already has genuine numbering collisions (the exact scenario the bug allowed).

def test_migration_dedups_preexisting_duplicates_before_adding_constraint(seeded_db):
    dsn = seeded_db

    # Drop the constraint migration 159 already added, to reproduce the
    # unenforced pre-159 state on this otherwise-fully-migrated database.
    drop = _psql(dsn, "ALTER TABLE receipts DROP CONSTRAINT receipts_firm_client_receipt_no_key;")
    assert drop.returncode == 0, drop.stderr

    # Two receipts for the SAME client sharing one receipt_no — only possible
    # pre-159 (a genuine collision the missing constraint used to allow).
    older = _psql(dsn, (
        "INSERT INTO receipts (id, firm_id, client_id, customer_id, receipt_no, receipt_date, created_at) VALUES "
        f"(gen_random_uuid(), '{FIRM}','{CLIENT_A}','{CUST_A}','RCPT-2526-0007','2026-04-01','2026-04-01T10:00:00Z');"
    ))
    assert older.returncode == 0, older.stderr
    newer = _psql(dsn, (
        "INSERT INTO receipts (id, firm_id, client_id, customer_id, receipt_no, receipt_date, created_at) VALUES "
        f"(gen_random_uuid(), '{FIRM}','{CLIENT_A}','{CUST_A}','RCPT-2526-0007','2026-04-02','2026-04-01T10:00:01Z');"
    ))
    assert newer.returncode == 0, newer.stderr

    # Re-apply migration 159 directly (idempotent DO-blocks + IF NOT EXISTS
    # guards make this safe to run again) to exercise its de-dup path.
    rerun = _psql(dsn, MIGRATION_159.read_text())
    assert rerun.returncode == 0, rerun.stderr

    rows = _psql(
        dsn,
        "SELECT receipt_no FROM receipts WHERE firm_id='%s' AND client_id='%s' "
        "AND receipt_date IN ('2026-04-01','2026-04-02') ORDER BY receipt_date;" % (FIRM, CLIENT_A),
        tuples=True,
    )
    assert rows.returncode == 0, rows.stderr
    numbers = [n for n in rows.stdout.strip().splitlines() if n]
    assert numbers == ["RCPT-2526-0007", "RCPT-2526-0007-DUP2"], (
        "the earlier row must keep its original number; the later duplicate "
        f"must be renumbered with a -DUPn suffix; got {numbers}"
    )

    # The constraint must be back in place and enforced going forward.
    still_unique = _insert_receipt(dsn, CLIENT_A, CUST_A, "RCPT-2526-0007", "2026-04-08")
    assert still_unique.returncode != 0, "constraint must be re-added and enforced after de-dup"
