"""The receipt total's trigger takes a lock a foreign-key check can share, and writes the receipt only when the total changes (migration 572, POST-A-369), on real Postgres.

WHAT THE REVIEW OF MIGRATION 571 FOUND, AND THIS HOLDS:

1. THE LOCK. 571 locked the receipt with FOR UPDATE inside the trigger. Every insert into `receipt_allocations` first runs its foreign-key check on
   `receipt_id`, which holds FOR KEY SHARE on the receipt, and FOR UPDATE conflicts with KEY SHARE. So two transactions that each held the key
   share and then reached the trigger waited on one another and Postgres aborted one (40P01). 572 asks FOR NO KEY UPDATE, which does not conflict with
   KEY SHARE and still conflicts with itself. Two tests: a held KEY SHARE does not stand in the way of an allocation insert, and two transactions that
   both hold the key share before either inserts both commit and end in the total of both. A control proves each test's premise (that a
   FOR UPDATE would have been refused while the key share was held), so a test cannot pass by the key share never having been taken.

2. THE WRITE. 571's trigger rewrote the receipt on every call even when the total was already right, and a multi-row statement calls it once per
   row, so the receipt got a new version (and, where an acting person is carried, a full `update` row in `audit_log`) for each row after the first.
   572 writes only when the figure differs. Tests: a statement that changes nothing leaves the receipt's row version where it was; a real
   change moves it; a two-row change leaves ONE `audit_log` row for the receipt, not two.

Also: the migration runs twice without harm, and the trigger function is still offered to no signed-in role.

Runs only when HARNESS_PG is set and psql is on the path; skips in the mock-mode job. The migration CI job runs it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATION = next((API_ROOT / "migrations").glob("572_a_receipts_total_trigger_locks_without_blocking_a_key_check_and_writes_only_a_change.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="this proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, CUSTOMER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
BANK_ACC, AR_ACC = str(uuid.uuid4()), str(uuid.uuid4())
INV_A, INV_B = str(uuid.uuid4()), str(uuid.uuid4())
ACTOR = str(uuid.uuid4())


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _seed(dsn: str) -> None:
    sql = f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','572 Firm','f572@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','572 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}','{FIRM}','{CLIENT}','572 Customer');
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
    return _scalar(dsn, f"SELECT id FROM receipts WHERE firm_id='{FIRM}' AND receipt_no='{receipt_no}';")


def _allocated(dsn: str, receipt_id: str) -> int:
    return int(_scalar(dsn, f"SELECT allocated_paise FROM receipts WHERE id='{receipt_id}';"))


def _version(dsn: str, receipt_id: str) -> str:
    """The receipt row's current version: xmin changes with every UPDATE of the row, whether or not a value changed."""
    return _scalar(dsn, f"SELECT xmin::text FROM receipts WHERE id='{receipt_id}';")


def _psql_background(dsn: str, sql: str) -> subprocess.Popen:
    return subprocess.Popen(["psql", dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t572_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("572_") for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_held_key_share_on_the_receipt_does_not_stand_in_the_way_of_an_allocation(db):
    """Session A holds FOR KEY SHARE on the receipt (what a foreign-key check holds) for a few seconds; session B inserts an allocation
    with a 2-second lock timeout. Under 571's FOR UPDATE the trigger waits for A and B is refused with 55P03; under FOR NO KEY UPDATE it does not."""
    receipt = _settle(db, "RCPT-572-1", 100000, [])
    holder = _psql_background(db, f"BEGIN; SELECT 1 FROM receipts WHERE id='{receipt}' FOR KEY SHARE; SELECT pg_sleep(4); COMMIT;")
    time.sleep(1.0)
    # The control: the premise is real. A FOR UPDATE is refused while the key share is held.
    probe = _run(db, f"SET lock_timeout='300ms'; SELECT 1 FROM receipts WHERE id='{receipt}' FOR UPDATE;")
    assert probe.returncode != 0 and "lock timeout" in probe.stderr, (
        "the key share was not held, so this test proves nothing: " + probe.stderr)
    started = time.monotonic()
    r = _run(db, f"SET lock_timeout='2s'; INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{receipt}','{INV_A}',40000);")
    waited = time.monotonic() - started
    holder.communicate(timeout=60)
    assert r.returncode == 0, "the allocation was refused while a key share was held: " + r.stderr
    assert waited < 2.0, f"the allocation waited {waited:.1f}s for a lock a key share should not hold"
    assert _allocated(db, receipt) == 40000


def test_two_transactions_that_each_hold_the_key_share_before_inserting_both_commit(db):
    """The deadlock the review found: both hold KEY SHARE, then both insert. Under FOR UPDATE each trigger waits for the other's key share and
    Postgres aborts one (40P01); under FOR NO KEY UPDATE the second waits for the first's commit and sums after it."""
    receipt = _settle(db, "RCPT-572-2", 100000, [])
    script = (
        "BEGIN; SELECT 1 FROM receipts WHERE id='{r}' FOR KEY SHARE; SELECT pg_sleep(2); "
        "INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{r}','{inv}',{amt}); COMMIT;"
    )
    first = _psql_background(db, script.format(r=receipt, inv=INV_A, amt=40000))
    second = _psql_background(db, script.format(r=receipt, inv=INV_B, amt=60000))
    _, err1 = first.communicate(timeout=60)
    _, err2 = second.communicate(timeout=60)
    assert first.returncode == 0 and second.returncode == 0, f"a writer was aborted: {err1!r} {err2!r}"
    assert "deadlock" not in (err1 + err2).lower()
    assert _allocated(db, receipt) == 100000, "the second writer's total was missing the first writer's row"


def test_two_writers_without_a_held_key_share_are_still_serialised(db):
    """The lock is still taken before the sum (the reason it exists): tx1 inserts and keeps its transaction open, tx2 inserts the other row
    meanwhile, and the final total has both."""
    receipt = _settle(db, "RCPT-572-3", 100000, [])
    first = _psql_background(db, f"INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{receipt}','{INV_A}',40000); SELECT pg_sleep(3);")
    time.sleep(1.0)
    second = _psql_background(db, f"INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES ('{receipt}','{INV_B}',60000);")
    _, err1 = first.communicate(timeout=60)
    _, err2 = second.communicate(timeout=60)
    assert first.returncode == 0, err1
    assert second.returncode == 0, err2
    assert _allocated(db, receipt) == 100000


def test_a_statement_that_changes_nothing_leaves_the_receipt_row_as_it_was(db):
    receipt = _settle(db, "RCPT-572-4", 100000, [(INV_A, 40000)])
    before = _version(db, receipt)
    # Setting a row to the amount it already has fires the trigger and finds the total already right.
    assert _run(db, f"UPDATE receipt_allocations SET allocated_paise = allocated_paise WHERE receipt_id='{receipt}';").returncode == 0
    assert _version(db, receipt) == before, "a call that found the total already right still wrote the receipt"
    # A change that is real moves the figure and so writes the row.
    assert _run(db, f"UPDATE receipt_allocations SET allocated_paise = 45000 WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 45000
    assert _version(db, receipt) != before, "a real change of the total did not write the receipt"


def test_a_two_row_change_leaves_one_edit_log_row_for_the_receipt_not_two(db):
    """A multi-row statement fires the row trigger once per row. The second call finds the first's figure and writes nothing, so an acting
    person (carried through `app.audit_actor`, migrations 545 and 547) gets ONE `update` row in audit_log for the receipt."""
    receipt = _settle(db, "RCPT-572-5", 100000, [(INV_A, 40000), (INV_B, 60000)])
    sql = (
        f"SET app.audit_actor = '{ACTOR}'; "
        f"UPDATE receipt_allocations SET allocated_paise = allocated_paise - 1000 WHERE receipt_id='{receipt}';"
    )
    assert _run(db, sql).returncode == 0
    assert _allocated(db, receipt) == 98000
    rows = _scalar(db, f"SELECT count(*) FROM audit_log WHERE entity_type='receipt' AND entity_id='{receipt}' AND action='update';")
    assert rows == "1", f"expected one edit-log row for the receipt, found {rows}"


def test_the_whole_migration_runs_twice_without_harm(db):
    receipt = _settle(db, "RCPT-572-6", 100000, [(INV_A, 40000)])
    for _ in range(2):
        r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert _allocated(db, receipt) == 40000
    assert _scalar(db, "SELECT count(*) FROM pg_trigger WHERE tgname='receipt_allocations_keep_total' AND NOT tgisinternal;") == "1"
    assert _run(db, f"UPDATE receipt_allocations SET allocated_paise = 50000 WHERE receipt_id='{receipt}';").returncode == 0
    assert _allocated(db, receipt) == 50000


def test_the_trigger_function_is_still_offered_to_no_signed_in_role(db):
    for role in ("anon", "authenticated"):
        has = _scalar(db, f"SELECT has_function_privilege('{role}', 'public.keep_receipt_allocated_total()', 'EXECUTE');")
        assert has == "f", f"{role} may execute the trigger function"
