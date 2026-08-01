"""
R3.9b — proves migration 172's fee-receipt fix on real PostgreSQL.

apps/web/app/billing/page.tsx's "Record Receipt" flow (linked from
AccountingPanel as "Fee Billing") used to insert directly into fee_receipts
and then unconditionally force-set the paired fee_invoices.status to
'Paid', regardless of the amount entered — a partial receipt marked the
whole invoice fully paid. This proves, against a real Postgres 16 instance
with every migration applied:

  1. record_fee_receipt_atomic() correctly tracks paid_paise and leaves
     status untouched on a partial receipt, then flips to 'Paid' only once
     cumulative receipts cover the total.
  2. authenticated can still SELECT its own firm's fee_invoices/
     fee_receipts, but direct INSERT into fee_receipts and UPDATE on
     fee_invoices are both rejected with "permission denied" — the write
     path now goes exclusively through the RPC (service_role, via the
     backend).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job.
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
    reason="fee_receipts atomic-RPC/RLS proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r39b_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        assert "001_initial_schema.sql" not in failed
        assert "014_complete_missing_tables.sql" not in failed
        assert "172_fee_receipt_atomic_and_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    invoice = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.9b Firm','r39b@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.9b Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Partner');
        INSERT INTO fee_invoices (id, firm_id, client_id, invoice_no, amount_paise, gst_paise, total_paise, status)
          VALUES ('{invoice}','{firm1}','{client1}','INV-R39B-001',50000000,9000000,59000000,'Sent');
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1,
            "staff_auth_id": staff_auth_id, "invoice": invoice}


def _as_authenticated(auth_user_id: str) -> str:
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_partial_receipt_leaves_status_unchanged(seeded):
    dsn, firm1, invoice = seeded["dsn"], seeded["firm1"], seeded["invoice"]
    r = _psql(dsn,
              f"SELECT record_fee_receipt_atomic('{firm1}','{invoice}','2026-07-01',500000,'NEFT','REF1',NULL);")
    assert r.returncode == 0, r.stderr

    check = _psql(dsn, f"SELECT status || ',' || paid_paise FROM fee_invoices WHERE id = '{invoice}';",
                  tuples=True)
    assert check.stdout.strip() == "Sent,500000"


def test_receipt_covering_total_marks_paid(seeded):
    dsn, firm1, invoice = seeded["dsn"], seeded["firm1"], seeded["invoice"]
    _psql(dsn, f"SELECT record_fee_receipt_atomic('{firm1}','{invoice}','2026-07-01',500000,'NEFT','REF1',NULL);")
    r = _psql(dsn,
              f"SELECT record_fee_receipt_atomic('{firm1}','{invoice}','2026-07-02',58500000,'NEFT','REF2',NULL);")
    assert r.returncode == 0, r.stderr

    check = _psql(dsn, f"SELECT status || ',' || paid_paise FROM fee_invoices WHERE id = '{invoice}';",
                  tuples=True)
    assert check.stdout.strip() == "Paid,59000000"

    count = _psql(dsn, f"SELECT count(*) FROM fee_receipts WHERE invoice_id = '{invoice}';", tuples=True)
    assert count.stdout.strip() == "2"


def test_own_firm_staff_can_still_select(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT status FROM fee_invoices WHERE id = '{seeded['invoice']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Sent"


def test_authenticated_insert_receipt_is_denied(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO fee_receipts (id, firm_id, invoice_id, receipt_date, amount_paise, payment_mode) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['invoice']}','2026-07-03',100,'Cash');")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_invoice_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE fee_invoices SET status = 'Paid' WHERE id = '{seeded['invoice']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_service_role_can_still_record_receipts(seeded):
    dsn, firm1, invoice = seeded["dsn"], seeded["firm1"], seeded["invoice"]
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"SELECT record_fee_receipt_atomic('{firm1}','{invoice}','2026-07-04',1000000,'UPI','REF3',NULL);")
    assert r.returncode == 0, r.stderr
