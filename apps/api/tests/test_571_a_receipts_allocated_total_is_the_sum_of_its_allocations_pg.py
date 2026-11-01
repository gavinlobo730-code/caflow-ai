"""A receipt's allocated total is the sum of its allocation rows, and the database keeps it (migration 571, POST-A-369), on real Postgres.

THE DEFECT: `receipts.allocated_paise` was never written by anything, so on production all 101 receipts held 0 while their allocation
rows covered each in full, and the Receipts tab printed "Allocated ₹0.00" beside "Unallocated ₹0.00" for a receipt of any size.

WHAT THIS HOLDS: a normal receipt through `settle_receipt_atomic` (the path the API takes) carries the sum of what it allocated; the
allocation route's rewrite (delete the rows, insert the new ones) and a changed amount follow; a row moved to another receipt recomputes
BOTH; the corrected figure is the same whatever order statements arrive in (a sum, not a delta); the backfill in the migration corrects
old receipts and leaves one with no allocations at 0; the migration runs twice without harm; and the trigger function is not offered to
any signed-in role. It counts LIVE rows only: reversing a receipt voids its rows and the total goes to nothing; and two writers on
one receipt at once both end in the total of both (the trigger takes the receipt's lock before it sums).

Runs only when HARNESS_PG is set and psql is on the path; skips in the mock-mode job. The migration CI job runs it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATION = next((API_ROOT / "migrations").glob("571_a_receipts_allocated_total_is_the_sum_of_its_allocations_and_the_database_keeps_it.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="this proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, CUSTOMER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
BANK_ACC, AR_ACC = str(uuid.uuid4()), str(uuid.uuid4())
INV_A, INV_B = str(uuid.uuid4()), str(uuid.uuid4())


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _seed(dsn: str) -> None:
    sql = f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','571 Firm','f571@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','571 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}','{FIRM}','{CLIENT}','571 Customer');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'),
      ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset');
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES ('{INV_A}','{FIRM}','{CLIENT}','{CUSTOMER}','SINV-A','2026-04-01',100000,'issued',0,0),
           ('{INV_B}','{FIRM}','{CLIENT}','{CUSTOMER}','SINV-B','2026-04-02',100000,'issued',0,0);
    """
    r = _run(dsn, sql)
    assert r.returncode == 0, r.stderr


def _settle(dsn: str, receipt_no: str, amount: int, allocations: list[tuple[str, int]]) -> str:
    """One receipt through settle_receipt_atomic, the call the API's plain receipt makes. Returns the receipt id."""
    receipt_id = str(uuid.uuid4())
    allocated = sum(a for _, a in allocations)
    p_receipt = json.dumps({
        "id": receipt_id, "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER, "receipt_no": receipt_no,
        "receipt_date": "2026-04-05", "amount_paise": amount, "tds_paise": 0, "unallocated_paise": amount - allocated,
        "payment_mode": "bank", "reference_no": "", "notes": "",
    })
    p_entry = json.dumps({"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05", "reference_no": receipt_no,
                          "narration": "Receipt", "entry_type": "Receipt", "is_posted": True, "status": "posted"})
    p_lines = json.dumps([
        {"account_id": BANK_ACC, "debit_paise": amount, "credit_paise": 0, "narration": "bank", "rate_type": "booking", "rate_date": "2026-04-05"},
        {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": amount, "narration": "ar", "rate_type": "booking", "rate_date": "2026-04-05"},
    ])
    p_allocs = json.dumps([{"sales_invoice_id": i, "allocated_paise": a} for i, a in allocations])
    r = _run(dsn, f"SELECT settle_receipt_atomic('{p_receipt}'::jsonb,'{p_entry}'::jsonb,'{p_lines}'::jsonb,'{p_allocs}'::jsonb);")
    assert r.returncode == 0, r.stderr
    # The function names the receipt it writes itself, so the id is read back by the number the test gave it.
    return _scalar(dsn, f"SELECT id FROM receipts WHERE firm_id='{FIRM}' AND receipt_no='{receipt_no}';")


def _allocated(dsn: str, receipt_id: str) -> int:
    return int(_scalar(dsn, f"SELECT allocated_paise FROM receipts WHERE id='{receipt_id}';"))


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t571_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("571_") for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_receipt_through_the_api_path_carries_the_sum_of_what_it_allocated(db):
    receipt = _settle(db, "RCPT-571-1", 100000, [(INV_A, 40000), (INV_B, 60000)])
    assert _allocated(db, receipt) == 100000, "the allocated total was left at its default of 0"
    assert int(_scalar(db, f"SELECT unallocated_paise FROM receipts WHERE id='{receipt}';")) == 0, "the maintained column was disturbed"


def test_a_partly_allocated_receipt_and_an_advance_say_so(db):
    part = _settle(db, "RCPT-571-2", 100000, [(INV_A, 40000)])
    assert _allocated(db, part) == 40000
    assert int(_scalar(db, f"SELECT unallocated_paise FROM receipts WHERE id='{part}';")) == 60000
    # An advance with no allocation rows stays at nothing allocated, as it should: the trigger never ran for it.
    advance = _settle(db, "RCPT-571-3", 50000, [])
    assert _allocated(db, advance) == 0


def test_the_allocation_routes_rewrite_and_a_changed_amount_follow(db):
    receipt = _settle(db, "RCPT-571-4", 100000, [(INV_A, 40000), (INV_B, 60000)])
    # What the allocation route does: delete this receipt's rows, insert the new set.
    assert _run(db, f"DELETE FROM receipt_allocations WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 0, "deleting every allocation did not bring the total back to nothing"
    assert _run(db, f"INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{receipt}','{INV_A}',25000);").returncode == 0
    assert _allocated(db, receipt) == 25000
    assert _run(db, f"UPDATE receipt_allocations SET allocated_paise = 30000 WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 30000


def test_a_row_moved_to_another_receipt_recomputes_both(db):
    first = _settle(db, "RCPT-571-5", 100000, [(INV_A, 40000)])
    second = _settle(db, "RCPT-571-6", 100000, [(INV_B, 70000)])
    assert (_allocated(db, first), _allocated(db, second)) == (40000, 70000)
    assert _run(db, f"UPDATE receipt_allocations SET receipt_id='{second}' WHERE receipt_id='{first}';").returncode == 0
    assert (_allocated(db, first), _allocated(db, second)) == (0, 110000)


def test_the_total_is_a_sum_and_not_a_delta(db):
    """Setting a row to the amount it already has, or the same statement twice, leaves the same total."""
    receipt = _settle(db, "RCPT-571-7", 100000, [(INV_A, 40000)])
    for _ in range(2):
        assert _run(db, f"UPDATE receipt_allocations SET allocated_paise = allocated_paise WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 40000
    # A total forced wrong by hand is put right by the next change to ANY of the receipt's rows, from the rows.
    assert _run(db, f"UPDATE receipts SET allocated_paise = 999 WHERE id='{receipt}';").returncode == 0
    assert _run(db, f"UPDATE receipt_allocations SET allocated_paise = 41000 WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 41000


def _backfill_block() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    m = re.search(r"DO \$\$.*?END \$\$;", text, re.S)
    assert m, "the migration has no backfill block"
    return m.group(0)


def test_a_reversed_receipt_applies_to_nothing_and_a_restored_row_counts_again(db):
    """Reversal voids the allocation rows (migration 215); the total follows, and follows back if a row is un-voided."""
    receipt = _settle(db, "RCPT-571-11", 100000, [(INV_A, 40000), (INV_B, 60000)])
    assert _allocated(db, receipt) == 100000
    assert _run(db, f"UPDATE receipt_allocations SET is_voided = true WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 0, "a reversed receipt still reports what its voided rows allocated"
    assert _run(db, f"UPDATE receipt_allocations SET is_voided = false WHERE receipt_id='{receipt}' AND sales_invoice_id='{INV_A}';").returncode == 0
    assert _allocated(db, receipt) == 40000, "only the live row should count"


def test_two_writers_on_one_receipt_at_once_both_end_in_the_total(db):
    """tx1 inserts a row and holds its transaction open; tx2 inserts the receipt's other row meanwhile and must wait for tx1's lock.
    Without the lock taken before the sum, tx2 sums before tx1 commits and writes a total missing tx1's row."""
    receipt = _settle(db, "RCPT-571-12", 100000, [])
    first = subprocess.Popen(
        ["psql", db, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c",
         f"INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{receipt}','{INV_A}',40000); SELECT pg_sleep(3);"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    second = subprocess.Popen(
        ["psql", db, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c",
         f"INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{receipt}','{INV_B}',60000);"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out1, err1 = first.communicate(timeout=60)
    out2, err2 = second.communicate(timeout=60)
    assert first.returncode == 0, err1
    assert second.returncode == 0, err2
    assert _allocated(db, receipt) == 100000, "the second writer's total was missing the first writer's row"


def test_the_backfill_corrects_old_receipts_and_leaves_one_with_no_allocations_alone(db):
    old = _settle(db, "RCPT-571-8", 100000, [(INV_A, 40000), (INV_B, 60000)])
    advance = _settle(db, "RCPT-571-9", 50000, [])
    # Make them look like production before the trigger: the column at its default.
    assert _run(db, f"UPDATE receipts SET allocated_paise = 0 WHERE id IN ('{old}','{advance}');").returncode == 0
    assert _allocated(db, old) == 0
    r = _run(db, _backfill_block())
    assert r.returncode == 0, r.stderr
    assert "1 receipt(s) had an allocated total that differed" in r.stderr, r.stderr
    assert (_allocated(db, old), _allocated(db, advance)) == (100000, 0)
    # A receipt whose rows are all voided is put at nothing even if something had left a figure on it.
    reversed_ = _settle(db, "RCPT-571-13", 80000, [(INV_A, 30000)])
    assert _run(db, f"UPDATE receipt_allocations SET is_voided = true WHERE receipt_id='{reversed_}';").returncode == 0
    assert _run(db, f"UPDATE receipts SET allocated_paise = 30000 WHERE id='{reversed_}';").returncode == 0
    fixed = _run(db, _backfill_block())
    assert "1 receipt(s) had an allocated total that differed" in fixed.stderr, fixed.stderr
    assert _allocated(db, reversed_) == 0
    # Run again: nothing is left to correct.
    again = _run(db, _backfill_block())
    assert "0 receipt(s) had an allocated total that differed" in again.stderr, again.stderr


def test_the_whole_migration_runs_twice_without_harm(db):
    receipt = _settle(db, "RCPT-571-10", 100000, [(INV_A, 40000)])
    for _ in range(2):
        r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert _allocated(db, receipt) == 40000
    assert _scalar(db, "SELECT count(*) FROM pg_trigger WHERE tgname='receipt_allocations_keep_total' AND NOT tgisinternal;") == "1"


def test_the_trigger_function_is_offered_to_no_signed_in_role(db):
    for role in ("anon", "authenticated"):
        has = _scalar(db, f"SELECT has_function_privilege('{role}', 'public.keep_receipt_allocated_total()', 'EXECUTE');")
        assert has == "f", f"{role} may execute the trigger function"
