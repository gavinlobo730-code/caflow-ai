"""
R3.11 — proves migration 167's numbered_document_atomic RPC on real
PostgreSQL: header + lines commit together, and a lines-insert failure
rolls back the header too (no orphan draft the way two separate unguarded
inserts could leave).

Background: routers/debit_notes.py::create_debit_note and routers/
credit_notes.py::create_credit_note both inserted a numbered header via
insert_with_number(), then inserted the line rows as a second, unguarded
call with no compensation — a lines-insert failure left the header
(already committed) orphaned with zero lines. Same root cause
post_journal_atomic (152) and settle_receipt_atomic (160/162) already
fixed for journals and receipts; this migration applies the identical
fix to debit/credit notes via one shared function (their line tables
share an identical column shape).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode
CI job.
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
    reason="numbered_document_atomic proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000001"
CLIENT = "aaaaaaaa-0000-0000-0000-000000000002"
VENDOR = "aaaaaaaa-0000-0000-0000-000000000003"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def seeded_db():
    admin = _ADMIN.strip()
    dbname = f"r311_{uuid.uuid4().hex[:12]}"
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
        report = json.loads(proc.stdout)
        failed = {f["file"] for f in report["failed"]}
        assert "145_debit_notes.sql" not in failed
        assert "167_numbered_document_lines_atomic.sql" not in failed
        seed = _psql(dsn, (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','R3.11 Firm','r311@test.in');"
            f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES "
            f"  ('{CLIENT}','{FIRM}','R3.11 Client','Private Limited');"
            f"INSERT INTO vendors (id, firm_id, client_id, name) VALUES "
            f"  ('{VENDOR}','{FIRM}','{CLIENT}','R3.11 Vendor');"
        ))
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _header_json(no: str) -> str:
    return (
        "jsonb_build_object("
        f"'firm_id','{FIRM}','client_id','{CLIENT}','vendor_id','{VENDOR}',"
        f"'debit_note_no','{no}','debit_note_date','2024-06-01',"
        "'taxable_amount_paise',100000,'total_paise',118000,'status','draft')"
    )


_ONE_LINE = (
    "jsonb_build_array(jsonb_build_object("
    "'description','Returned goods','hsn_sac','9983','quantity',1,'rate_paise',100000,"
    "'gst_rate_bps',1800,'taxable_amount_paise',100000,'cgst_paise',9000,'sgst_paise',9000,"
    "'igst_paise',0,'line_total_paise',118000))"
)


def test_header_and_lines_commit_together_on_success(seeded_db):
    dsn = seeded_db
    r = _psql(dsn, (
        f"SELECT numbered_document_atomic('debit_notes', {_header_json('DN-2425-0001')}, "
        f"'debit_note_lines', {_ONE_LINE}, 'debit_note_id');"
    ))
    assert r.returncode == 0, r.stderr

    r = _psql(dsn, "SELECT count(*) FROM debit_notes;", tuples=True)
    assert r.stdout.strip() == "1"
    r = _psql(dsn, "SELECT count(*) FROM debit_note_lines;", tuples=True)
    assert r.stdout.strip() == "1"

    r = _psql(dsn, (
        "SELECT dn.debit_note_no FROM debit_note_lines dnl "
        "JOIN debit_notes dn ON dn.id = dnl.debit_note_id "
        "WHERE dnl.description = 'Returned goods';"
    ), tuples=True)
    assert r.stdout.strip() == "DN-2425-0001"


def test_lines_insert_failure_rolls_back_the_header_too(seeded_db):
    """The actual R3.11 bug: previously, a lines-insert failure left the
    already-committed header orphaned. Now both are one transaction."""
    dsn = seeded_db
    r = _psql(dsn, (
        f"SELECT numbered_document_atomic('debit_notes', {_header_json('DN-2425-SHOULD-NOT-EXIST')}, "
        "'debit_note_lines_does_not_exist', "
        f"{_ONE_LINE}, 'debit_note_id');"
    ))
    assert r.returncode != 0
    assert "does not exist" in r.stderr.lower()

    r = _psql(dsn, "SELECT count(*) FROM debit_notes WHERE debit_note_no = 'DN-2425-SHOULD-NOT-EXIST';",
              tuples=True)
    assert r.stdout.strip() == "0"  # no orphan header


def test_zero_lines_is_a_valid_header_only_insert(seeded_db):
    """Some documents legitimately have no line items at the point of
    creation -- the RPC must not require at least one."""
    dsn = seeded_db
    r = _psql(dsn, (
        f"SELECT numbered_document_atomic('debit_notes', {_header_json('DN-2425-0002')}, "
        "'debit_note_lines', '[]'::jsonb, 'debit_note_id');"
    ))
    assert r.returncode == 0, r.stderr
    r = _psql(dsn, "SELECT count(*) FROM debit_notes WHERE debit_note_no = 'DN-2425-0002';", tuples=True)
    assert r.stdout.strip() == "1"
