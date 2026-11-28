"""Migration 785, proved against real PostgreSQL: the receipt function refuses an invoice issued to another customer of the same
client, and stores a receipt against its own customer's invoices exactly as migration 782's body did (ledger POST-A-580, the
receipt half).

WHAT THIS HOLDS
    * a rupee receipt and a foreign receipt that name another customer's invoice are refused whole and leave nothing, even when the
      receipt's own customer's invoice is named first;
    * the function 785 replaced accepts the same call and marks the other customer's invoice paid (the negative control);
    * a receipt against its own customer's invoices is recorded as before;
    * the invoices of one receipt are locked in id order (POST-A-581): two receipts across the same two invoices, named in opposite
      orders, are both recorded, the second after the first, and neither is killed as a deadlock. (The order the function took
      them in before was the database's own choice and could not be forced from outside, so the defect is not reproduced here: what
      holds the fix is the function's text, read from the database, and this run of the two.)
    * the body is migration 782's with the one refusal added (and one variable and one selected column to read it) and the one
      ORDER BY, and nothing else; both files run twice; the rollback restores 782's body; the attributes and who may execute are
      unchanged.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_S785 = "785_a_receipt_does_not_settle_an_invoice_issued_to_another_customer"
F785, R785 = MIGRATIONS / f"{_S785}.sql", MIGRATIONS / f"{_S785}_rollback.sql"
F782 = MIGRATIONS / "782_a_rupee_receipt_does_not_settle_an_invoice_billed_in_a_foreign_currency.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the other-customer proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, PAYER, OTHER = (str(uuid.uuid4()) for _ in range(4))
BANK_ACC, AR_ACC = str(uuid.uuid4()), str(uuid.uuid4())
MINE, MINE_2, THEIRS, THEIRS_USD = (str(uuid.uuid4()) for _ in range(4))
FUNCTION = "public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"
REFUSAL = "was issued to another customer"


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True,
                          env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _seed(dsn: str) -> None:
    r = _run(dsn, f"""
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','785 Firm','f785@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','785 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{PAYER}','{FIRM}','{CLIENT}','The One Who Pays'), ('{OTHER}','{FIRM}','{CLIENT}','Somebody Else');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'), ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset');
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES ('{MINE}','{FIRM}','{CLIENT}','{PAYER}','MINE-1','2026-04-01',100000,'issued',0,0),
           ('{MINE_2}','{FIRM}','{CLIENT}','{PAYER}','MINE-2','2026-04-01',100000,'issued',0,0),
           ('{THEIRS}','{FIRM}','{CLIENT}','{OTHER}','THEIRS-1','2026-04-01',100000,'issued',0,0);
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise,
                                       txn_currency, exchange_rate, txn_total, paid_txn)
    VALUES ('{THEIRS_USD}','{FIRM}','{CLIENT}','{OTHER}','THEIRS-USD','2026-04-01',8000000,'issued',0,0,'USD',80,100000,0);""")
    assert r.returncode == 0, r.stderr


def _call(receipt: dict, lines: list, allocs: list, day: str = "2026-04-05") -> str:
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": day, "reference_no": receipt["receipt_no"], "narration": "Receipt",
             "entry_type": "Receipt", "is_posted": True, "status": "posted", "source_type": "receipt", "source_id": receipt["id"]}
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    return f"SELECT public.settle_receipt_atomic('{j(receipt)}'::jsonb,'{j(entry)}'::jsonb,'{j(lines)}'::jsonb,'{j(allocs)}'::jsonb)::text;"


def _rupee(receipt_no: str, allocations: list[tuple[str, int]], day: str = "2026-04-05") -> str:
    """The call the API's rupee receipt makes for the payer, allocating to each (invoice, amount)."""
    amount = sum(a for _i, a in allocations)
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "customer_id": PAYER, "receipt_no": receipt_no,
               "receipt_date": day, "amount_paise": amount, "tds_paise": 0, "unallocated_paise": 0, "payment_mode": "bank"}
    lines = [{"account_id": BANK_ACC, "debit_paise": amount, "credit_paise": 0, "narration": "bank"},
             {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": amount, "narration": "ar"}]
    return _call(receipt, lines, [{"sales_invoice_id": i, "allocated_paise": a} for i, a in allocations], day)


def _foreign(receipt_no: str, invoice: str) -> str:
    """1,000.00 USD from the payer at 80 against `invoice` (no exchange difference: the invoice is booked at 80)."""
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "customer_id": PAYER, "receipt_no": receipt_no,
               "receipt_date": "2026-04-05", "amount_paise": 8000000, "tds_paise": 0, "unallocated_paise": 0, "payment_mode": "bank",
               "txn_currency": "USD", "exchange_rate": "80", "txn_amount": 100000, "rate_source": "manual-override", "rate_type": "booking",
               "rate_date": "2026-04-05", "rate_overridden": True}
    both = {"txn_currency": "USD", "base_currency": "INR", "exchange_rate": "80", "rate_source": "manual-override", "rate_type": "booking",
            "rate_date": "2026-04-05"}
    lines = [{"account_id": BANK_ACC, "debit_paise": 8000000, "credit_paise": 0, "narration": "bank", "txn_debit": 100000, "txn_credit": 0, **both},
             {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": 8000000, "narration": "ar", "txn_debit": 0, "txn_credit": 100000, **both}]
    return _call(receipt, lines, [{"sales_invoice_id": invoice, "allocated_paise": 8000000, "allocated_txn": 100000,
                                   "expect_paid_paise": 0, "expect_paid_txn": 0, "expect_credited_paise": 0}])


def _counts(dsn: str) -> str:
    return _scalar(dsn, "SELECT (SELECT count(*) FROM journal_entries) || '/' || (SELECT count(*) FROM receipts) || '/' || (SELECT count(*) FROM receipt_allocations);")


def _invoice(dsn: str, invoice: str) -> str:
    return _scalar(dsn, f"SELECT status || '/' || paid_paise || '/' || COALESCE(paid_txn, 0) FROM client_sales_invoices WHERE id = '{invoice}';")


def _body(dsn: str) -> str:
    return _scalar(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t785_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("785_") for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        # this file is about 785's own body, whatever a later migration may define
        assert _file(dsn, F785).returncode == 0
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_rupee_receipt_is_refused_another_customers_invoice_and_leaves_nothing_not_even_its_own_invoices_settlement(db):
    before = _counts(db)
    r = _run(db, _rupee("R-785-1", [(MINE, 100000), (THEIRS, 50000)]))
    assert r.returncode != 0 and REFUSAL in r.stderr, r.stderr
    assert _counts(db) == before == "0/0/0"
    assert (_invoice(db, MINE), _invoice(db, THEIRS)) == ("issued/0/0", "issued/0/0")


def test_a_foreign_receipt_is_refused_another_customers_invoice(db):
    r = _run(db, _foreign("R-785-2", THEIRS_USD))
    assert r.returncode != 0 and REFUSAL in r.stderr, r.stderr
    assert _counts(db) == "0/0/0" and _invoice(db, THEIRS_USD) == "issued/0/0"
    assert _scalar(db, "SELECT count(*) FROM fx_adjustments;") == "0"


def test_the_function_785_replaced_accepts_it_and_marks_the_other_customers_invoice_paid(db):
    """The negative control: the same call through migration 782's body, which is the defect."""
    assert _file(db, R785).returncode == 0
    r = _run(db, _rupee("R-785-3", [(THEIRS, 100000)]))
    assert r.returncode == 0, r.stderr
    assert _invoice(db, THEIRS) == "paid/100000/0", "the control no longer shows the defect"
    assert _scalar(db, "SELECT customer_id::text FROM receipts WHERE receipt_no = 'R-785-3';") == PAYER


def test_a_receipt_against_its_own_customers_invoice_is_recorded_as_before(db):
    r = _run(db, _rupee("R-785-4", [(MINE, 60000)]))
    assert r.returncode == 0, r.stderr
    assert _counts(db) == "1/1/1" and _invoice(db, MINE) == "partially_paid/60000/0"


def test_the_body_is_migration_782s_with_the_one_refusal_added(db):
    with_785 = _body(db)
    assert _file(db, R785).returncode == 0
    rolled_back = _body(db)
    assert _file(db, F782).returncode == 0 and _body(db) == rolled_back, "the rollback does not hold the body migration 782 defines"
    # take out exactly what 785 adds: the variable, the selected column, the INTO target and the refusal block
    stripped = with_785.replace("  v_invoice_customer  uuid;      -- migration 785\n", "", 1)
    stripped = stripped.replace("COALESCE(paid_txn, 0), customer_id\n", "COALESCE(paid_txn, 0)\n", 1)
    stripped = stripped.replace("v_txn_total, v_paid_txn, v_invoice_customer\n", "v_txn_total, v_paid_txn\n", 1)
    ordered = stripped.index("     -- migration 785 (POST-A-581): in one order")
    loop = stripped.index("  LOOP\n", ordered)
    assert stripped[ordered:loop].rstrip().endswith("ORDER BY 1") and stripped[ordered:loop].count("\n") == 3
    stripped = stripped[:ordered] + stripped[loop:]
    start = stripped.index("    -- One customer's receipt does not settle another customer's invoice (migration 785, POST-A-580)")
    end = stripped.index("    -- task #227: a draft invoice was never issued")
    block = stripped[start:end]
    assert "IF v_invoice_customer IS DISTINCT FROM NULLIF(p_receipt->>'customer_id', '')::uuid THEN" in block and block.count("RAISE EXCEPTION") == 1
    assert stripped[:start] + stripped[end:] == rolled_back, "785 changed something other than the one refusal"
    assert _file(db, F785).returncode == 0 and _body(db) == with_785
    assert _file(db, F785).returncode == 0 and _body(db) == with_785, "running 785 twice changed the function"
    assert _file(db, R785).returncode == 0 and _file(db, R785).returncode == 0 and _body(db) == rolled_back


def test_two_receipts_across_the_same_two_invoices_named_in_opposite_orders_are_both_recorded_and_neither_is_killed(db):
    """POST-A-581. The first holds its transaction open; the second, which names the same two invoices the other way round, waits and
    is then recorded. With the invoices taken in id order neither can hold one and wait for the other."""
    import time
    first = _rupee("R-785-5", [(MINE, 30000), (MINE_2, 30000)])
    second = _rupee("R-785-6", [(MINE_2, 30000), (MINE, 30000)], day="2026-05-05")        # another month: only the invoices are shared
    holder = subprocess.Popen(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", f"BEGIN; {first} SELECT pg_sleep(3); COMMIT;"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if _scalar(db, "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation WHERE c.relname = 'client_sales_invoices' AND l.mode = 'RowShareLock';") != "0":
                break
            time.sleep(0.1)
        started = time.time()
        r = _run(db, second)
        waited = time.time() - started
    finally:
        _out, err = holder.communicate(timeout=30)
    assert holder.returncode == 0, err
    assert r.returncode == 0 and "deadlock" not in r.stderr, r.stderr
    assert waited > 1.0, f"the second receipt did not wait for the first ({waited:.2f}s): the two were not in each other's way"
    assert (_invoice(db, MINE), _invoice(db, MINE_2)) == ("partially_paid/60000/0", "partially_paid/60000/0")
    body = _body(db)
    assert "GROUP BY (x->>'sales_invoice_id')::uuid" in body and "\n     ORDER BY 1\n  LOOP" in body


def test_the_function_keeps_its_attributes_and_who_may_execute_it(db):
    row = json.loads(_scalar(db, f"""SELECT json_build_object('definer', p.prosecdef, 'config', p.proconfig,
        'auth', has_function_privilege('authenticated', p.oid, 'EXECUTE'), 'anon', has_function_privilege('anon', p.oid, 'EXECUTE'),
        'service', has_function_privilege('service_role', p.oid, 'EXECUTE'))::text FROM pg_proc p WHERE p.oid = '{FUNCTION}'::regprocedure;"""))
    assert row == {"definer": True, "config": ["search_path=public, pg_catalog"], "auth": False, "anon": False, "service": True}
