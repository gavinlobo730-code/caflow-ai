"""Migration 391 on real PostgreSQL (ACC-14).

WHY THIS NEEDS A REAL DATABASE. The whole design rests on two facts about the
schema that mock mode cannot show: that `outstanding_paise` is a GENERATED
column computed from `total_paise` on one table and from `net_payable_paise` on
the other (migration 278), and that an opening document therefore shows up in
the ageing reads — `deleted_at IS NULL AND outstanding_paise > 0` — exactly like
any other. If either were wrong, every opening document would be outstanding at
zero and invisible to the schedules this exists to populate, silently.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
CUSTOMER = "33333333-3333-3333-3333-333333333333"
VENDOR = "44444444-4444-4444-4444-444444444444"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"opendoc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO customers (id, firm_id, client_id, name, opening_balance_paise)
            VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Acme', 100000);
            INSERT INTO vendors (id, firm_id, client_id, name, opening_balance_paise)
            VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Bolt', 50000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _open_invoice(dsn, no="OLD/22", amount=60000):
    return _psql(dsn, f"""
        INSERT INTO client_sales_invoices
          (firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
           total_paise, status, is_opening)
        VALUES ('{FIRM}', '{CLIENT}', '{CUSTOMER}', '{no}', '2026-03-20',
                '2026-04-19', {amount}, 'issued', TRUE);
    """)


def _open_bill(dsn, no="OLDB/9", amount=50000):
    return _psql(dsn, f"""
        INSERT INTO purchase_bills
          (firm_id, client_id, vendor_id, bill_no, bill_date, due_date,
           total_paise, net_payable_paise, status, is_opening)
        VALUES ('{FIRM}', '{CLIENT}', '{VENDOR}', '{no}', '2026-03-20',
                '2026-04-19', {amount}, {amount}, 'received', TRUE);
    """)


def test_the_flag_defaults_to_false_on_both_tables(db):
    """Every document already in a live database stays an ordinary one, so
    nothing already filed changes."""
    for table in ("client_sales_invoices", "purchase_bills"):
        assert _rows(db, f"""
            SELECT column_default FROM information_schema.columns
             WHERE table_schema='public' AND table_name='{table}'
               AND column_name='is_opening';
        """) == ["false"]


def test_an_opening_invoice_is_OUTSTANDING_IN_FULL(db):
    """The generated column (migration 278) is what every ageing read filters
    on. If it came out at zero the document would exist and age to nothing."""
    assert _open_invoice(db).returncode == 0
    assert _rows(db, f"""
        SELECT outstanding_paise FROM client_sales_invoices
         WHERE client_id = '{CLIENT}' AND is_opening;
    """) == ["60000"]


def test_an_opening_BILL_needs_net_payable_paise_and_this_proves_it(db):
    """`purchase_bills.outstanding_paise` is generated from net_payable_paise,
    NOT total_paise — the one asymmetry between the two tables, and the one
    that would make every opening bill invisible to AP ageing."""
    assert _open_bill(db).returncode == 0
    assert _rows(db, f"""
        SELECT outstanding_paise FROM purchase_bills
         WHERE client_id = '{CLIENT}' AND is_opening;
    """) == ["50000"]

    # And the proof it is net_payable and not total: a bill with only the total
    # set comes out at zero.
    assert _psql(db, f"""
        INSERT INTO purchase_bills
          (firm_id, client_id, vendor_id, bill_no, bill_date, total_paise,
           status, is_opening)
        VALUES ('{FIRM}', '{CLIENT}', '{VENDOR}', 'TOTALONLY', '2026-03-20',
                50000, 'received', TRUE);
    """).returncode == 0
    assert _rows(db, f"""
        SELECT outstanding_paise FROM purchase_bills
         WHERE bill_no = 'TOTALONLY';
    """) == ["0"]


def test_an_opening_document_is_found_by_the_AGEING_READ(db):
    """The exact predicate `ar_aging` / `ap_aging` use."""
    assert _open_invoice(db).returncode == 0
    assert _open_bill(db).returncode == 0
    assert _rows(db, f"""
        SELECT count(*) FROM client_sales_invoices
         WHERE firm_id='{FIRM}' AND client_id='{CLIENT}'
           AND deleted_at IS NULL
           AND status NOT IN ('draft','cancelled')
           AND outstanding_paise > 0;
    """) == ["1"]
    assert _rows(db, f"""
        SELECT count(*) FROM purchase_bills
         WHERE firm_id='{FIRM}' AND client_id='{CLIENT}'
           AND deleted_at IS NULL
           AND status NOT IN ('draft','cancelled')
           AND outstanding_paise > 0;
    """) == ["1"]


def test_an_opening_invoice_still_obeys_the_per_client_number_uniqueness(db):
    """Migration 151 makes `invoice_no` unique per client. A carried-over number
    that collides with one this client will issue is a real conflict the CA has
    to resolve, so it is refused rather than allowed through."""
    assert _open_invoice(db).returncode == 0
    second = _open_invoice(db)
    assert second.returncode != 0
    assert "unique" in (second.stderr or "").lower()


def test_the_rollback_refuses_while_an_opening_document_exists(db):
    rollback = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "migrations"
        / "391_an_opening_balance_is_made_of_documents_rollback.sql")
    assert _open_invoice(db).returncode == 0
    out = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q",
                          "-f", str(rollback)], capture_output=True, text=True)
    assert out.returncode != 0
    assert "Refusing to roll back 391" in (out.stderr or "")
    # And the column is still there — a refused rollback must change nothing.
    assert _rows(db, """
        SELECT count(*) FROM information_schema.columns
         WHERE table_name='client_sales_invoices' AND column_name='is_opening';
    """) == ["1"]


def test_the_rollback_SUCCEEDS_once_the_documents_are_gone(db):
    rollback = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "migrations"
        / "391_an_opening_balance_is_made_of_documents_rollback.sql")
    out = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q",
                          "-f", str(rollback)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert _rows(db, """
        SELECT count(*) FROM information_schema.columns
         WHERE table_name='purchase_bills' AND column_name='is_opening';
    """) == ["0"]
