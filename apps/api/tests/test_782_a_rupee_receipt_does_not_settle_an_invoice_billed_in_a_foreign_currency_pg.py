"""Migration 782, proved against real PostgreSQL: the receipt function refuses a rupee receipt an invoice billed in a foreign currency
(ledger POST-A-576). The API refuses it first, in a person's words; this is the second lock, and this file is its proof.

WHAT THIS HOLDS
    * the call is refused in the function's words and leaves nothing (no entry, no receipt, no allocation; the invoice as it was);
    * THE NEGATIVE CONTROL: through the function 782 replaced (its rollback, migration 781's body) the same call is accepted and leaves the
      invoice 'paid' with its foreign amount untouched, which is the defect;
    * a rupee receipt on a rupee invoice and a foreign receipt on a foreign invoice are stored as before;
    * the body is migration 781's with the one refusal added and nothing else changed (the two texts are compared), its attributes and
      grants are untouched, and both files run twice.

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

_S782 = "782_a_rupee_receipt_does_not_settle_an_invoice_billed_in_a_foreign_currency"
F782, R782 = MIGRATIONS / f"{_S782}.sql", MIGRATIONS / f"{_S782}_rollback.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the rupee-receipt proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, CUSTOMER = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
BANK_ACC, AR_ACC = str(uuid.uuid4()), str(uuid.uuid4())
INV_USD, INV_INR = str(uuid.uuid4()), str(uuid.uuid4())
FUNCTION = "public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)"


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
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','782 Firm','f782@test.in');
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','782 Client','Private Limited');
    INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}','{FIRM}','{CLIENT}','782 Customer');
    INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
      ('{BANK_ACC}','{FIRM}','{CLIENT}','BANK-1','Bank Account','Asset'), ('{AR_ACC}','{FIRM}','{CLIENT}','AR-1','Trade Receivables','Asset');
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise,
                                       txn_currency, exchange_rate, txn_total, paid_txn)
    VALUES ('{INV_USD}','{FIRM}','{CLIENT}','{CUSTOMER}','USD-1','2026-04-01',8000000,'issued',0,0,'USD',80,100000,0);
    INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
    VALUES ('{INV_INR}','{FIRM}','{CLIENT}','{CUSTOMER}','INR-1','2026-04-01',100000,'issued',0,0);""")
    assert r.returncode == 0, r.stderr


def _rupee(receipt_no: str, amount: int, invoice: str) -> str:
    """The call the API's rupee receipt makes, allocating the whole amount to `invoice`."""
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT, "customer_id": CUSTOMER, "receipt_no": receipt_no,
               "receipt_date": "2026-04-05", "amount_paise": amount, "tds_paise": 0, "unallocated_paise": 0, "payment_mode": "bank"}
    entry = {"firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-04-05", "reference_no": receipt_no, "narration": "Receipt",
             "entry_type": "Receipt", "is_posted": True, "status": "posted", "source_type": "receipt", "source_id": receipt["id"]}
    lines = [{"account_id": BANK_ACC, "debit_paise": amount, "credit_paise": 0, "narration": "bank"},
             {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": amount, "narration": "ar"}]
    allocs = [{"sales_invoice_id": invoice, "allocated_paise": amount}]
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    return f"SELECT public.settle_receipt_atomic('{j(receipt)}'::jsonb,'{j(entry)}'::jsonb,'{j(lines)}'::jsonb,'{j(allocs)}'::jsonb)::text;"


def _counts(dsn: str) -> str:
    return _scalar(dsn, "SELECT (SELECT count(*) FROM journal_entries) || '/' || (SELECT count(*) FROM receipts) || '/' || (SELECT count(*) FROM receipt_allocations);")


def _invoice(dsn: str, invoice: str) -> str:
    return _scalar(dsn, f"SELECT status || '/' || paid_paise || '/' || COALESCE(paid_txn, 0) FROM client_sales_invoices WHERE id = '{invoice}';")


def _body(dsn: str) -> str:
    return _scalar(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t782_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("782_") for f in pg_template.failed), pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_rupee_receipt_is_refused_an_invoice_billed_in_usd_and_leaves_nothing(db):
    before = _counts(db)
    r = _run(db, _rupee("R-782-1", 8000000, INV_USD))
    assert r.returncode != 0 and "the receipt is in INR and invoice" in r.stderr and "is billed in USD" in r.stderr, r.stderr
    assert _counts(db) == before == "0/0/0" and _invoice(db, INV_USD) == "issued/0/0"


def test_the_function_782_replaced_accepts_it_and_leaves_the_invoice_paid_with_its_foreign_amount_untouched(db):
    """The negative control: the same call through migration 781's body, which is the defect."""
    assert _file(db, R782).returncode == 0
    r = _run(db, _rupee("R-782-2", 8000000, INV_USD))
    assert r.returncode == 0, r.stderr
    assert _invoice(db, INV_USD) == "paid/8000000/0", "the control no longer shows the defect"


def test_a_rupee_receipt_on_a_rupee_invoice_is_recorded_as_before(db):
    r = _run(db, _rupee("R-782-3", 100000, INV_INR))
    assert r.returncode == 0, r.stderr
    assert _counts(db) == "1/1/1" and _invoice(db, INV_INR) == "paid/100000/0"


def test_the_body_is_migration_781s_with_the_one_refusal_added(db):
    with_782 = _body(db)
    assert _file(db, R782).returncode == 0
    with_781 = _body(db)
    start = with_782.index("    -- A RUPEE receipt does not settle an invoice billed in a foreign currency (migration 782).")
    end = with_782.index("    IF v_new_paid + COALESCE(v_credited_paise, 0) > v_total_paise THEN")
    block = with_782[start:end]
    assert "IF NOT v_foreign AND v_invoice_ccy <> 'INR' THEN" in block and block.count("RAISE EXCEPTION") == 1
    assert with_782[:start] + with_782[end:] == with_781, "782 changed something other than the one refusal"
    assert _file(db, F782).returncode == 0 and _body(db) == with_782
    assert _file(db, F782).returncode == 0 and _body(db) == with_782, "running 782 twice changed the function"
    assert _file(db, R782).returncode == 0 and _file(db, R782).returncode == 0 and _body(db) == with_781


def test_the_function_keeps_its_attributes_and_who_may_execute_it(db):
    row = json.loads(_scalar(db, f"""SELECT json_build_object('definer', p.prosecdef, 'config', p.proconfig,
        'auth', has_function_privilege('authenticated', p.oid, 'EXECUTE'), 'anon', has_function_privilege('anon', p.oid, 'EXECUTE'),
        'service', has_function_privilege('service_role', p.oid, 'EXECUTE'))::text FROM pg_proc p WHERE p.oid = '{FUNCTION}'::regprocedure;"""))
    assert row == {"definer": True, "config": ["search_path=public, pg_catalog"], "auth": False, "anon": False, "service": True}
