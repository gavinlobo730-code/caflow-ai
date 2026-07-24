"""
Task #230 — proves migration 238's firm-scoped UNIQUE constraint on
advance_tax_payments against a real Postgres 16 instance.

Before this migration, UNIQUE(client_id, financial_year, installment_number)
had no firm_id component — the exact key routers/income_tax.py::
save_advance_tax's upsert used. Even with the app-level assert_client_access
guard (added in the same task) as the primary fix, this proves the schema
itself no longer permits a second firm's row for the same
(client_id, fy, installment_number) to collide with — and silently
overwrite — the owning firm's real row: they now coexist as two distinct
rows scoped by firm_id, so an upsert from a different firm can never clobber
another firm's data at the database layer either.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
    reason="advance_tax_payments firm-scoped unique proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db():
    admin = _ADMIN.strip()
    dbname = f"r230at_{uuid.uuid4().hex[:12]}"
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
        assert "035_complete_missing_pages.sql" not in failed
        assert "238_advance_tax_payments_firm_scoped_unique.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    firm2 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    record = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R230 Firm One','r230f1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm2}','R230 Firm Two','r230f2@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R230 Client','Private Limited');
        INSERT INTO advance_tax_payments
          (id, firm_id, client_id, financial_year, installment_number, due_date,
           required_percent, estimated_tax_paise, paid_amount_paise)
          VALUES ('{record}','{firm1}','{client1}','2024-25',1,'2024-06-15',15,100000000,15000000);
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "firm2": firm2, "client1": client1, "record": record}


def test_new_constraint_is_firm_scoped(seeded):
    """Confirms the constraint shape: (firm_id, client_id, financial_year,
    installment_number), not the old client_id-only key."""
    dsn = seeded["dsn"]
    r = _psql(dsn, """
        SELECT string_agg(a.attname, ',' ORDER BY a.attnum)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
        WHERE t.relname = 'advance_tax_payments' AND c.contype = 'u';
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    cols = set(r.stdout.strip().split(","))
    assert cols == {"firm_id", "client_id", "financial_year", "installment_number"}


def test_cross_firm_upsert_no_longer_collides_with_owning_firms_row(seeded):
    """The attack this closes: firm2's upsert targets the SAME client_id/fy/
    installment as firm1's real row (client1 actually belongs to firm1 — this
    simulates the pre-fix state where the app-level check was bypassable).
    Before migration 238, ON CONFLICT(client_id, financial_year,
    installment_number) would have matched firm1's row and overwritten it.
    After the fix, firm_id is part of the key, so this creates an
    independent row instead — firm1's real data is untouched."""
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    upsert = _psql(dsn, f"""
        INSERT INTO advance_tax_payments
          (id, firm_id, client_id, financial_year, installment_number, due_date,
           required_percent, estimated_tax_paise, paid_amount_paise)
        VALUES ('{new_id}','{seeded["firm2"]}','{seeded["client1"]}','2024-25',1,
                '2024-06-15',15,999999999,888888888)
        ON CONFLICT (firm_id, client_id, financial_year, installment_number)
        DO UPDATE SET paid_amount_paise = EXCLUDED.paid_amount_paise;
    """)
    assert upsert.returncode == 0, upsert.stderr

    # firm1's original row is untouched.
    r1 = _psql(dsn, f"SELECT paid_amount_paise FROM advance_tax_payments WHERE id = '{seeded['record']}';",
              tuples=True)
    assert r1.returncode == 0, r1.stderr
    assert r1.stdout.strip() == "15000000"

    # firm2's row exists as an independent record, not a clobber of firm1's.
    r2 = _psql(dsn, f"SELECT paid_amount_paise FROM advance_tax_payments WHERE id = '{new_id}';",
              tuples=True)
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "888888888"

    total = _psql(dsn, "SELECT count(*) FROM advance_tax_payments;", tuples=True)
    assert total.stdout.strip() == "2"


def test_same_firm_upsert_still_updates_in_place(seeded):
    """Sanity check: the legitimate case (same firm re-saving the same
    installment) still upserts onto the SAME row, not a new one."""
    dsn = seeded["dsn"]
    upsert = _psql(dsn, f"""
        INSERT INTO advance_tax_payments
          (id, firm_id, client_id, financial_year, installment_number, due_date,
           required_percent, estimated_tax_paise, paid_amount_paise)
        VALUES ('{uuid.uuid4()}','{seeded["firm1"]}','{seeded["client1"]}','2024-25',1,
                '2024-06-15',15,100000000,50000000)
        ON CONFLICT (firm_id, client_id, financial_year, installment_number)
        DO UPDATE SET paid_amount_paise = EXCLUDED.paid_amount_paise;
    """)
    assert upsert.returncode == 0, upsert.stderr
    r = _psql(dsn, f"SELECT id, paid_amount_paise FROM advance_tax_payments WHERE firm_id = '{seeded['firm1']}';",
              tuples=True)
    assert r.stdout.strip() == f"{seeded['record']}|50000000"
