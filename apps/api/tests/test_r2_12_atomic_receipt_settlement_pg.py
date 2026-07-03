"""
R2.12 — full receipt→AR→journal atomicity, proven on real PostgreSQL.

settle_receipt_atomic (migration 160) posts the journal header+lines, the
receipt row, and every allocation's row-locked invoice update in ONE database
transaction. This is the property that can only be proven against a real
Postgres — a plpgsql function body is a single transaction, so this file's
whole point is confirming that a failure ANYWHERE in the function (a bad
invoice id, an over-allocation, a receipt_no collision) leaves ZERO partial
state behind: no orphan journal header, no orphan lines, no receipt row, no
mutated invoice.

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
    reason="atomic receipt settlement proof requires HARNESS_PG + psql",
)

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())
CUSTOMER = str(uuid.uuid4())
BANK_ACC = str(uuid.uuid4())
AR_ACC = str(uuid.uuid4())
TDS_RECV_ACC = str(uuid.uuid4())


def _psql_json(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
        capture_output=True, text=True,
    )


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _seed_sql(invoice_id: str, total_paise: int = 100000) -> str:
    return f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','R2.12 Test Firm','r212@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
      ('{CLIENT}','{FIRM}','R2.12 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES
      ('{CUSTOMER}','{FIRM}','{CLIENT}','R2.12 Customer');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'),
      ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset'),
      ('{TDS_RECV_ACC}','{FIRM}','{CLIENT}','TDS-1','TDS Receivable','Asset');
    INSERT INTO client_sales_invoices
      (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES
      ('{invoice_id}','{FIRM}','{CLIENT}','{CUSTOMER}','SINV-1','2026-04-01',{total_paise},'issued',0,0);
    """


def _settle_sql(
    receipt_id: str, journal_id: str, receipt_no: str, invoice_id: str,
    amount_paise: int, allocated_paise: int, entry_date: str = "2026-04-05",
) -> str:
    """Build the exact settle_receipt_atomic(...) call the Python layer issues,
    matching services/receipt_service.py::_settle_receipt_via_atomic_rpc."""
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
         "narration": "Trade receivable cleared (cash + TDS)", "rate_type": "booking", "rate_date": entry_date},
    ])
    p_allocations = json.dumps([{"sales_invoice_id": invoice_id, "allocated_paise": allocated_paise}])
    return (
        f"SELECT settle_receipt_atomic('{p_receipt}'::jsonb, '{p_journal_entry}'::jsonb, "
        f"'{p_journal_lines}'::jsonb, '{p_allocations}'::jsonb);"
    )


@pytest.fixture()
def migrated_db():
    admin = _ADMIN.strip()
    dbname = f"r212_{uuid.uuid4().hex[:12]}"
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
        assert "160_atomic_receipt_settlement.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_successful_settlement_posts_journal_receipt_and_updates_invoice(migrated_db):
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, total_paise=100000))
    assert seed.returncode == 0, seed.stderr

    receipt_id = str(uuid.uuid4())
    journal_id = str(uuid.uuid4())
    r = _psql(dsn, _settle_sql(receipt_id, journal_id, "RCPT-2526-0001", invoice_id, 100000, 100000))
    assert r.returncode == 0, r.stderr

    entries = _psql_json(dsn, "SELECT count(*) FROM journal_entries WHERE firm_id='%s';" % FIRM)
    assert entries.stdout.strip() == "1"

    lines = _psql_json(
        dsn,
        "SELECT sum(debit_paise), sum(credit_paise) FROM journal_lines jl "
        "JOIN journal_entries je ON je.id = jl.journal_entry_id WHERE je.firm_id='%s';" % FIRM,
    )
    debit, credit = lines.stdout.strip().split("|")
    assert int(debit) == int(credit) == 100000

    receipts = _psql_json(
        dsn,
        "SELECT receipt_no, journal_entry_id IS NOT NULL FROM receipts WHERE firm_id='%s';" % FIRM,
    )
    receipt_no, has_journal = receipts.stdout.strip().split("|")
    assert receipt_no == "RCPT-2526-0001"
    assert has_journal == "t"

    allocs = _psql_json(dsn, "SELECT count(*) FROM receipt_allocations;")
    assert allocs.stdout.strip() == "1"

    inv = _psql_json(
        dsn,
        f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';",
    )
    paid, status = inv.stdout.strip().split("|")
    assert int(paid) == 100000
    assert status == "paid"


def test_partial_settlement_leaves_partially_paid(migrated_db):
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, total_paise=100000))
    assert seed.returncode == 0, seed.stderr

    r = _psql(dsn, _settle_sql(str(uuid.uuid4()), str(uuid.uuid4()), "RCPT-2526-0001", invoice_id, 40000, 40000))
    assert r.returncode == 0, r.stderr

    inv = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid, status = inv.stdout.strip().split("|")
    assert int(paid) == 40000
    assert status == "partially_paid"

    # A second, sequential settlement completes it.
    r2 = _psql(dsn, _settle_sql(str(uuid.uuid4()), str(uuid.uuid4()), "RCPT-2526-0002", invoice_id, 60000, 60000,
                                 entry_date="2026-04-10"))
    assert r2.returncode == 0, r2.stderr
    inv2 = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid2, status2 = inv2.stdout.strip().split("|")
    assert int(paid2) == 100000
    assert status2 == "paid"

    receipts = _psql_json(dsn, "SELECT count(*) FROM receipts WHERE firm_id='%s';" % FIRM)
    assert receipts.stdout.strip() == "2"


def test_over_allocation_rolls_back_everything(migrated_db):
    """The core R2.12 guarantee: a failure partway through leaves ZERO partial
    state — no orphan journal header, no orphan lines, no receipt row, and
    the invoice untouched."""
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, total_paise=100000))
    assert seed.returncode == 0, seed.stderr

    r = _psql(dsn, _settle_sql(str(uuid.uuid4()), str(uuid.uuid4()), "RCPT-2526-0001", invoice_id, 150000, 150000))
    assert r.returncode != 0, "an over-allocation must fail, not silently succeed"
    assert "outstanding" in r.stderr.lower()

    assert _psql_json(dsn, "SELECT count(*) FROM journal_entries WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"
    assert _psql_json(dsn, "SELECT count(*) FROM journal_lines;").stdout.strip() == "0"
    assert _psql_json(dsn, "SELECT count(*) FROM receipts WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"
    assert _psql_json(dsn, "SELECT count(*) FROM receipt_allocations;").stdout.strip() == "0"

    inv = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid, status = inv.stdout.strip().split("|")
    assert int(paid) == 0
    assert status == "issued"


def test_unknown_invoice_rolls_back_everything(migrated_db):
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, total_paise=100000))
    assert seed.returncode == 0, seed.stderr

    bogus_invoice = str(uuid.uuid4())
    r = _psql(dsn, _settle_sql(str(uuid.uuid4()), str(uuid.uuid4()), "RCPT-2526-0001", bogus_invoice, 50000, 50000))
    assert r.returncode != 0
    assert "not part of this client" in r.stderr.lower() or "books" in r.stderr.lower()

    assert _psql_json(dsn, "SELECT count(*) FROM journal_entries WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"
    assert _psql_json(dsn, "SELECT count(*) FROM receipts WHERE firm_id='%s';" % FIRM).stdout.strip() == "0"


def test_receipt_no_collision_rolls_back_the_journal_too(migrated_db):
    """The exact R2.9-superseding guarantee: a receipt_no collision (migration
    159's UNIQUE constraint) must leave NO journal behind for the losing
    call — unlike the pre-R2.12 compensation path, there is nothing to
    compensate because nothing partial was ever committed."""
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, total_paise=200000))
    assert seed.returncode == 0, seed.stderr

    first = _psql(dsn, _settle_sql(str(uuid.uuid4()), str(uuid.uuid4()), "RCPT-2526-0007", invoice_id, 50000, 50000))
    assert first.returncode == 0, first.stderr

    # Second call reuses the SAME receipt_no for the same firm+client — a
    # genuine numbering collision (migration 159: UNIQUE(firm_id, client_id, receipt_no)).
    second = _psql(dsn, _settle_sql(str(uuid.uuid4()), str(uuid.uuid4()), "RCPT-2526-0007", invoice_id, 30000, 30000,
                                     entry_date="2026-04-06"))
    assert second.returncode != 0, "a receipt_no collision must fail, not silently succeed"

    # Only the FIRST call's journal/receipt exist — the second's attempt left nothing behind.
    assert _psql_json(dsn, "SELECT count(*) FROM journal_entries WHERE firm_id='%s';" % FIRM).stdout.strip() == "1"
    assert _psql_json(dsn, "SELECT count(*) FROM receipts WHERE firm_id='%s';" % FIRM).stdout.strip() == "1"

    inv = _psql_json(dsn, f"SELECT paid_paise FROM client_sales_invoices WHERE id='{invoice_id}';")
    # Only the first (successful) 50000 allocation landed — the second's 30000 never did.
    assert int(inv.stdout.strip()) == 50000


def test_tds_line_included_and_balances(migrated_db):
    """Dr Bank + Dr TDS Receivable / Cr AR — a 3-line journal must still balance."""
    dsn = migrated_db
    invoice_id = str(uuid.uuid4())
    seed = _psql(dsn, _seed_sql(invoice_id, total_paise=118000))
    assert seed.returncode == 0, seed.stderr

    receipt_id = str(uuid.uuid4())
    p_receipt = json.dumps({
        "id": receipt_id, "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER,
        "receipt_no": "RCPT-2526-0009", "receipt_date": "2026-04-05", "amount_paise": 100000,
        "tds_paise": 18000, "unallocated_paise": 0, "payment_mode": "bank",
        "reference_no": "", "notes": "",
    })
    p_journal_entry = json.dumps({
        "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05",
        "reference_no": "RCPT-2526-0009", "narration": "Receipt RCPT-2526-0009 from customer",
        "entry_type": "Receipt", "is_posted": True, "status": "posted",
    })
    p_journal_lines = json.dumps([
        {"account_id": BANK_ACC, "debit_paise": 100000, "credit_paise": 0, "narration": "Cash/bank received"},
        {"account_id": TDS_RECV_ACC, "debit_paise": 18000, "credit_paise": 0, "narration": "TDS receivable"},
        {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": 118000, "narration": "Trade receivable cleared"},
    ])
    p_allocations = json.dumps([{"sales_invoice_id": invoice_id, "allocated_paise": 118000}])
    r = _psql(dsn, (
        f"SELECT settle_receipt_atomic('{p_receipt}'::jsonb, '{p_journal_entry}'::jsonb, "
        f"'{p_journal_lines}'::jsonb, '{p_allocations}'::jsonb);"
    ))
    assert r.returncode == 0, r.stderr

    lines = _psql_json(
        dsn,
        "SELECT sum(debit_paise), sum(credit_paise), count(*) FROM journal_lines jl "
        "JOIN journal_entries je ON je.id = jl.journal_entry_id WHERE je.firm_id='%s';" % FIRM,
    )
    debit, credit, n = lines.stdout.strip().split("|")
    assert int(debit) == int(credit) == 118000
    assert n == "3"

    inv = _psql_json(dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id='{invoice_id}';")
    paid, status = inv.stdout.strip().split("|")
    assert int(paid) == 118000
    assert status == "paid"
