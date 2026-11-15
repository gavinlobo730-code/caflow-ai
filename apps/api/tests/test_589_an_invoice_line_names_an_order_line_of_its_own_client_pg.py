"""Migration 589 on a real database: a sales invoice line names the sales-order line it bills, and only one of its own client's
(POST-A-104).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode file (`test_an_invoice_line_bills_the_order_line_it_names.py`) holds the API's checks. Here: the column exists and is
    nullable (an invoice that bills no order is written exactly as before), the trigger refuses a line naming another client's order
    line (and one of another firm's), on an INSERT and on an UPDATE of the column, while a line of the same client is accepted; an order
    line an invoice bills cannot be deleted from under it (ON DELETE RESTRICT); the trigger function cannot be called by a signed-in
    role; the migration is idempotent; and its rollback removes all four pieces. The negative control: after the rollback, the same
    column with its key and no trigger takes a sibling client's order line, so the refusal is the trigger's.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = os.environ.get("HARNESS_PG")
MIGRATION = next(API_ROOT.glob("migrations/589_a_sales_invoice_line_names_the_order_line_it_bills.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/589_*_rollback.sql"))

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

FIRM, OTHER_FIRM = "f5890000-0000-0000-0000-000000000001", "f5890000-0000-0000-0000-0000000000ff"
CLIENT, SIBLING, FOREIGN = (f"c5890000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
CUSTOMER, SIBLING_CUSTOMER, FOREIGN_CUSTOMER = (f"e5890000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
ORDER, SIBLING_ORDER, FOREIGN_ORDER = (f"a5890000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
LINE, SIBLING_LINE, FOREIGN_LINE = (f"b5890000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
INVOICE = "d5890000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run(dsn: str, path: Path) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e589_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        _ok(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{SIBLING}', '{FIRM}', 'B', 'Proprietorship'),
                ('{FOREIGN}', '{OTHER_FIRM}', 'C', 'Proprietorship');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust'),
                ('{SIBLING_CUSTOMER}', '{FIRM}', '{SIBLING}', 'Cust B'), ('{FOREIGN_CUSTOMER}', '{OTHER_FIRM}', '{FOREIGN}', 'Cust C');
            INSERT INTO sales_orders (id, firm_id, client_id, customer_id, document_no, document_date, status) VALUES
                ('{ORDER}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'SO/1', '2026-04-01', 'confirmed'),
                ('{SIBLING_ORDER}', '{FIRM}', '{SIBLING}', '{SIBLING_CUSTOMER}', 'SO/1', '2026-04-01', 'confirmed'),
                ('{FOREIGN_ORDER}', '{OTHER_FIRM}', '{FOREIGN}', '{FOREIGN_CUSTOMER}', 'SO/1', '2026-04-01', 'confirmed');
            INSERT INTO sales_order_lines (id, firm_id, client_id, order_id, description, quantity) VALUES
                ('{LINE}', '{FIRM}', '{CLIENT}', '{ORDER}', 'Widget', 10),
                ('{SIBLING_LINE}', '{FIRM}', '{SIBLING}', '{SIBLING_ORDER}', 'Widget', 10),
                ('{FOREIGN_LINE}', '{OTHER_FIRM}', '{FOREIGN}', '{FOREIGN_ORDER}', 'Widget', 10);
            INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date) VALUES
                ('{INVOICE}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-1', '2026-04-10');
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _line(dsn: str, order_line, *, n: int = 1) -> subprocess.CompletedProcess:
    value = "NULL" if order_line is None else f"'{order_line}'"
    return _psql(dsn, f"""INSERT INTO client_sales_invoice_lines (id, sales_invoice_id, description, quantity, rate_paise, sales_order_line_id)
                          VALUES ('{uuid.UUID(int=n)}', '{INVOICE}', 'Widget', 1, 100, {value});""")


def test_a_line_of_the_same_client_is_accepted_and_one_that_names_none_is_written_as_before(dsn):
    assert _line(dsn, None, n=1).returncode == 0
    assert _line(dsn, LINE, n=2).returncode == 0
    assert _val(dsn, f"SELECT count(*) FROM client_sales_invoice_lines WHERE sales_order_line_id = '{LINE}'") == "1"


@pytest.mark.parametrize("other", [SIBLING_LINE, FOREIGN_LINE], ids=["a sibling client's", "another firm's"])
def test_a_line_naming_another_clients_order_line_is_refused_on_insert_and_on_update(dsn, other):
    r = _line(dsn, other, n=3)
    assert r.returncode != 0 and "own client" in r.stderr
    assert _line(dsn, None, n=4).returncode == 0
    r = _psql(dsn, f"UPDATE client_sales_invoice_lines SET sales_order_line_id = '{other}' WHERE id = '{uuid.UUID(int=4)}';")
    assert r.returncode != 0 and "own client" in r.stderr


def test_an_order_line_an_invoice_bills_is_not_deleted_from_under_it(dsn):
    assert _line(dsn, LINE, n=5).returncode == 0
    r = _psql(dsn, f"DELETE FROM sales_order_lines WHERE id = '{LINE}';")
    assert r.returncode != 0 and "violates foreign key" in r.stderr
    assert _val(dsn, f"SELECT count(*) FROM sales_order_lines WHERE id = '{LINE}'") == "1"


def test_the_trigger_function_is_not_callable_by_a_signed_in_role_and_the_column_is_nullable(dsn):
    fn = "public.assert_invoice_line_names_its_clients_order_line()"
    assert _val(dsn, f"SELECT has_function_privilege('authenticated', '{fn}', 'EXECUTE')") == "f"
    assert _val(dsn, f"SELECT has_function_privilege('anon', '{fn}', 'EXECUTE')") == "f"
    assert _val(dsn, """SELECT is_nullable FROM information_schema.columns
                        WHERE table_name = 'client_sales_invoice_lines' AND column_name = 'sales_order_line_id'""") == "YES"


def test_the_migration_is_idempotent_and_its_rollback_stops_the_refusal(dsn):
    _run(dsn, MIGRATION)                                      # a second run changes nothing and fails nothing
    assert _line(dsn, SIBLING_LINE, n=6).returncode != 0
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)                                       # the rollback is safe to run twice
    assert _val(dsn, """SELECT count(*) FROM information_schema.columns
                        WHERE table_name = 'client_sales_invoice_lines' AND column_name = 'sales_order_line_id'""") == "0"
    assert _val(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'assert_invoice_line_names_its_clients_order_line'") == "0"
    # THE NEGATIVE CONTROL: the same column with its key and no trigger takes a sibling client's order line, so the refusal above is
    # the trigger's and not the key's.
    _ok(dsn, "ALTER TABLE client_sales_invoice_lines ADD COLUMN sales_order_line_id UUID REFERENCES sales_order_lines(id);")
    assert _line(dsn, SIBLING_LINE, n=7).returncode == 0
    _ok(dsn, f"DELETE FROM client_sales_invoice_lines WHERE id = '{uuid.UUID(int=7)}';"
             "ALTER TABLE client_sales_invoice_lines DROP COLUMN sales_order_line_id;")
    _run(dsn, MIGRATION)                                      # and the migration applies again on top of its rollback
    assert _line(dsn, LINE, n=8).returncode == 0
    assert _line(dsn, SIBLING_LINE, n=9).returncode != 0
