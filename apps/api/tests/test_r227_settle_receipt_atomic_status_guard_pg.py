"""
Task #227 finding #1, real-Postgres proof — settle_receipt_atomic (migration
235) must reject an allocation against a draft or cancelled invoice at the
DATABASE layer, independent of any application-level check.

create_receipt_core's own Python-side status check (services/receipt_service.py)
already runs before it ever dispatches to this RPC, so in practice the
application never reaches the database with a bad allocation — but the RPC
is SECURITY DEFINER and this invariant must hold for any caller, present or
future, not just the one call site this task also fixed. This file proves
the guard exists in the function body itself, mirroring the structure of
test_r2_12_atomic_receipt_settlement_pg.py.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job. The `migrations` CI job runs it against its Postgres service.
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
    reason="settle_receipt_atomic status-guard proof requires HARNESS_PG + psql",
)

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())
CUSTOMER = str(uuid.uuid4())
BANK_ACC = str(uuid.uuid4())
AR_ACC = str(uuid.uuid4())


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _psql_json(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
        capture_output=True, text=True,
    )


def _seed_sql(invoice_id: str, status: str, total_paise: int = 100000) -> str:
    return f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','R227 Test Firm','r227@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
      ('{CLIENT}','{FIRM}','R227 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES
      ('{CUSTOMER}','{FIRM}','{CLIENT}','R227 Customer');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'),
      ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset');
    INSERT INTO client_sales_invoices
      (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES
      ('{invoice_id}','{FIRM}','{CLIENT}','{CUSTOMER}','SINV-1','2026-04-01',{total_paise},'{status}',0,0);
    """


def _settle_sql(
    receipt_id: str, receipt_no: str, invoice_id: str, amount_paise: int, allocated_paise: int,
    entry_date: str = "2026-04-05",
) -> str:
    p_receipt = json.dumps({
        "id": receipt_id, "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER,
        "receipt_no": receipt_no, "receipt_date": entry_date, "amount_paise": amount_paise,
        "tds_paise": 0, "unallocated_paise": amount_paise - allocated_paise,
        "payment_mode": "bank", "reference_no": "", "notes": "",
    })
    p_journal_entry = json.dumps({
        "firm_id": FIRM, "client_id": CLIENT, "entry_date": entry_date,
        "reference_no": receipt_no, "narration": f"Receipt {receipt_no} from customer",
        "entry_type": "Receipt", "is_posted": True, "status": "posted",
    })
    p_journal_lines = json.dumps([
        {"account_id": BANK_ACC, "debit_paise": amount_paise, "credit_paise": 0,
         "narration": "Cash/bank received from customer", "rate_type": "booking", "rate_date": entry_date},
        {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": amount_paise,
         "narration": "Trade receivable cleared", "rate_type": "booking", "rate_date": entry_date},
    ])
    p_allocations = json.dumps([{"sales_invoice_id": invoice_id, "allocated_paise": allocated_paise}])
    return (
        f"SELECT settle_receipt_atomic('{p_receipt}'::jsonb, '{p_journal_entry}'::jsonb, "
        f"'{p_journal_lines}'::jsonb, '{p_allocations}'::jsonb);"
    )


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r227_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        assert "235_settle_receipt_atomic_invoice_status_guard.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_draft_invoice_is_rejected_and_nothing_partial_is_left(migrated_db):
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, "draft"))
    assert seed.returncode == 0, seed.stderr

    r = _psql(dsn, _settle_sql(str(uuid.uuid4()), "RCPT-2526-0001", invoice_id, 100000, 100000))
    assert r.returncode != 0, "a receipt must not settle against a draft invoice"
    assert "draft" in r.stderr.lower()

    assert _psql_json(dsn, "SELECT count(*) FROM journal_entries WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"
    assert _psql_json(dsn, "SELECT count(*) FROM receipts WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"

    inv = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid, status = inv.stdout.strip().split("|")
    assert int(paid) == 0
    assert status == "draft"


def test_cancelled_invoice_is_rejected_and_nothing_partial_is_left(migrated_db):
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, "cancelled"))
    assert seed.returncode == 0, seed.stderr

    r = _psql(dsn, _settle_sql(str(uuid.uuid4()), "RCPT-2526-0001", invoice_id, 100000, 100000))
    assert r.returncode != 0, "a receipt must not settle against a cancelled invoice"
    assert "cancelled" in r.stderr.lower()

    assert _psql_json(dsn, "SELECT count(*) FROM journal_entries WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"
    assert _psql_json(dsn, "SELECT count(*) FROM receipts WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"


def test_issued_invoice_still_settles_normally(migrated_db):
    """Sanity check: migration 235's guard doesn't collaterally block the
    normal, valid case — same assertion shape as R2.12's own success test."""
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, "issued"))
    assert seed.returncode == 0, seed.stderr

    r = _psql(dsn, _settle_sql(str(uuid.uuid4()), "RCPT-2526-0001", invoice_id, 100000, 100000))
    assert r.returncode == 0, r.stderr

    inv = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid, status = inv.stdout.strip().split("|")
    assert int(paid) == 100000
    assert status == "paid"


def test_partially_paid_invoice_still_settles_normally(migrated_db):
    """partially_paid is a valid, receivable-bearing status — must not be
    caught by the draft/cancelled guard."""
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, "issued", total_paise=100000))
    assert seed.returncode == 0, seed.stderr
    # First settlement moves it to partially_paid.
    first = _psql(dsn, _settle_sql(str(uuid.uuid4()), "RCPT-2526-0001", invoice_id, 40000, 40000))
    assert first.returncode == 0, first.stderr
    inv = _psql_json(dsn, f"SELECT status FROM client_sales_invoices WHERE id='{invoice_id}';")
    assert inv.stdout.strip() == "partially_paid"

    second = _psql(dsn, _settle_sql(str(uuid.uuid4()), "RCPT-2526-0002", invoice_id, 60000, 60000,
                                     entry_date="2026-04-10"))
    assert second.returncode == 0, second.stderr
    inv2 = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid2, status2 = inv2.stdout.strip().split("|")
    assert int(paid2) == 100000
    assert status2 == "paid"
