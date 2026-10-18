"""Migration 518 on real PostgreSQL: an invoice has one live IRN record (POST-A-263).

WHAT IS PROVEN HERE
    * a second e-invoice record for one invoice is refused by the DATABASE (23505, naming the index) while the first is a draft or
      generated, so two requests at the same moment cannot both prepare one;
    * a CANCELLED record does not count: an invoice carries any number of cancelled records and one live one, and cancelling the
      live one makes room for the next;
    * a record that names no invoice is unconstrained (an invoice raised outside the product), and another invoice is unaffected;
    * e-way bills are NOT unique: an invoice may carry several (a second consignment, a new vehicle);
    * the per-invoice indexes exist and are partial; migration 518 is idempotent and its rollback removes all three, after which a
      second live record is accepted again (the negative control for every refusal above).

Runs only when HARNESS_PG is set and psql is on PATH, like every *_pg test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "51800000-0000-0000-0000-0000000000f1"
CLIENT = "51800000-0000-0000-0000-0000000000c1"
CUSTOMER = "51800000-0000-0000-0000-0000000000d2"
INVOICE_1 = "51800000-0000-0000-0000-0000000000a1"
INVOICE_2 = "51800000-0000-0000-0000-0000000000a2"
USER_ID = "51800000-0000-0000-0000-00000000b001"
USER_AUTH = "51800000-0000-0000-0000-00000000a001"


def _file(rollback: bool) -> Path:
    return next(p for p in sorted(MIGRATIONS.glob("518_*.sql")) if ("rollback" in p.name) == rollback)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _run_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(path)],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m518_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert _file(False).name not in pg_template.failed, (
            "migration 518 did not apply, so everything below would pass vacuously")
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{USER_AUTH}', 'p518@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F518', 'f518@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
              VALUES ('{USER_ID}', '{FIRM}', '{USER_AUTH}', 'p518@t.in', 'Partner', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
              VALUES ('{CLIENT}', '{FIRM}', 'C518', 'Private Limited', 'AAACA1234A');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Acme');
            INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
                                               total_paise, status)
              VALUES ('{INVOICE_1}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-1', '2026-05-01', '2026-05-31', 118000, 'issued'),
                     ('{INVOICE_2}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-2', '2026-05-02', '2026-06-01', 118000, 'issued');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _irn(dsn: str, invoice: str | None, status: str = "draft") -> subprocess.CompletedProcess:
    inv = f"'{invoice}'" if invoice else "NULL"
    return _psql(dsn, f"""
        INSERT INTO einvoice_records (firm_id, client_id, sales_invoice_id, invoice_number, invoice_date, status, created_by)
        VALUES ('{FIRM}', '{CLIENT}', {inv}, 'N', '2026-07-06', '{status}', '{USER_ID}');
    """)


def _ewb(dsn: str, invoice: str | None) -> subprocess.CompletedProcess:
    inv = f"'{invoice}'" if invoice else "NULL"
    return _psql(dsn, f"""
        INSERT INTO eway_bill_records (firm_id, client_id, sales_invoice_id, invoice_number, created_by)
        VALUES ('{FIRM}', '{CLIENT}', {inv}, 'N', '{USER_ID}');
    """)


def _ok(r: subprocess.CompletedProcess) -> None:
    """The statement was accepted; the database's own words are the failure message."""
    assert r.returncode == 0, r.stderr


def _refused(r: subprocess.CompletedProcess) -> None:
    """The statement was refused by the unique index (and by nothing else: a different failure would pass a bare != 0)."""
    assert r.returncode != 0, "the insert was accepted"
    assert "uq_einvoice_records_one_live_per_invoice" in r.stderr, r.stderr


def _count(dsn: str, sql: str) -> int:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip())


# ── the refusal ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("first, second", [
    ("draft", "draft"), ("draft", "generated"), ("generated", "draft"), ("generated", "generated"),
])
def test_a_second_live_record_for_one_invoice_is_refused(db, first, second):
    _ok(_irn(db, INVOICE_1, first))
    _refused(_irn(db, INVOICE_1, second))


def test_a_cancelled_record_does_not_count(db):
    _ok(_irn(db, INVOICE_1, "cancelled"))
    _ok(_irn(db, INVOICE_1, "cancelled"))
    _ok(_irn(db, INVOICE_1, "draft"))
    _refused(_irn(db, INVOICE_1, "draft"))


def test_cancelling_the_live_record_makes_room_for_the_next(db):
    _ok(_irn(db, INVOICE_1, "generated"))
    _refused(_irn(db, INVOICE_1, "draft"))
    r = _psql(db, f"UPDATE einvoice_records SET status = 'cancelled' WHERE sales_invoice_id = '{INVOICE_1}';")
    assert r.returncode == 0, r.stderr
    _ok(_irn(db, INVOICE_1, "draft"))


def test_a_cancelled_record_cannot_be_revived_beside_a_live_one(db):
    _ok(_irn(db, INVOICE_1, "cancelled"))
    _ok(_irn(db, INVOICE_1, "draft"))
    r = _psql(db, f"UPDATE einvoice_records SET status = 'draft' WHERE sales_invoice_id = '{INVOICE_1}' AND status = 'cancelled';")
    _refused(r)


def test_another_invoice_and_a_record_naming_no_invoice_are_unconstrained(db):
    _ok(_irn(db, INVOICE_1))
    _ok(_irn(db, INVOICE_2))
    for _ in range(3):
        _ok(_irn(db, None))


# ── e-way bills ───────────────────────────────────────────────────────────────────────────────────────

def test_an_invoice_may_carry_several_e_way_bills(db):
    for _ in range(3):
        r = _ewb(db, INVOICE_1)
        assert r.returncode == 0, r.stderr
    assert _count(db, f"SELECT count(*) FROM eway_bill_records WHERE sales_invoice_id = '{INVOICE_1}'") == 3


# ── the indexes ───────────────────────────────────────────────────────────────────────────────────────

def test_the_indexes_exist_and_are_partial(db):
    rows = _psql(db, """
        SELECT indexname || '|' || indexdef FROM pg_indexes
         WHERE schemaname = 'public'
           AND indexname IN ('uq_einvoice_records_one_live_per_invoice', 'idx_einvoice_records_invoice',
                             'idx_eway_bill_records_invoice')
         ORDER BY indexname;""", tuples=True)
    assert rows.returncode == 0, rows.stderr
    defs = dict(line.split("|", 1) for line in rows.stdout.strip().splitlines())
    assert set(defs) == {"uq_einvoice_records_one_live_per_invoice", "idx_einvoice_records_invoice",
                         "idx_eway_bill_records_invoice"}
    assert "UNIQUE" in defs["uq_einvoice_records_one_live_per_invoice"]
    assert "'cancelled'" in defs["uq_einvoice_records_one_live_per_invoice"]
    assert "UNIQUE" not in defs["idx_einvoice_records_invoice"] and "UNIQUE" not in defs["idx_eway_bill_records_invoice"]
    assert all("sales_invoice_id IS NOT NULL" in d for d in defs.values())


def test_the_migration_is_idempotent(db):
    r = _run_file(db, _file(False))
    assert r.returncode == 0, r.stderr


# ── the rollback is the negative control ────────────────────────────────────────────────────────────────

def test_the_rollback_removes_the_three_indexes_and_the_refusal_with_them(db):
    _ok(_irn(db, INVOICE_1))
    _refused(_irn(db, INVOICE_1))
    r = _run_file(db, _file(True))
    assert r.returncode == 0, r.stderr
    left = _count(db, """SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND indexname IN
        ('uq_einvoice_records_one_live_per_invoice', 'idx_einvoice_records_invoice', 'idx_eway_bill_records_invoice')""")
    assert left == 0
    _ok(_irn(db, INVOICE_1))
