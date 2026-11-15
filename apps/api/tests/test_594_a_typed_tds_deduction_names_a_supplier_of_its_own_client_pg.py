"""Migration 594 on a real database: a deduction typed on the TDS screen may name the supplier it was paid to, and only one of its own
client's (POST-A-078).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode tests that part 2 of POST-A-078 adds hold the API's arithmetic. Here:
    the column exists and is nullable (a typed deduction paid to someone who is not a supplier is written exactly as before); the shared
    guard of migration 565 now carries the table's vendor triggers and refuses a supplier of a sibling client and one of another firm, on
    an INSERT and on an UPDATE of the column, and an UPDATE that moves a named row to another client; a row a purchase bill or a vendor
    advance wrote cannot carry a supplier (the CHECK); a supplier a typed deduction names cannot be deleted from under it (ON DELETE
    RESTRICT); the backfill names a supplier only where exactly one active, not non-resident supplier of the row's own client holds the
    row's PAN, compared in capitals and without spaces, and leaves every other row as it was; the migration is idempotent; and its
    rollback removes every piece it added and leaves the client-in-firm triggers the table had. The negative control: after the rollback,
    the same column with its key and no trigger takes a sibling client's supplier, so the refusal is the guard's.

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
MIGRATION = next(API_ROOT.glob("migrations/594_a_typed_tds_deduction_may_name_its_supplier.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/594_*_rollback.sql"))

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

FIRM, OTHER_FIRM = "f5940000-0000-0000-0000-000000000001", "f5940000-0000-0000-0000-0000000000ff"
CLIENT, SIBLING, FOREIGN = (f"c5940000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
VENDOR, SIBLING_VENDOR, FOREIGN_VENDOR = (f"e5940000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
TWIN_A, TWIN_B, RETIRED, ONLY_RETIRED, ABROAD = (f"e5940000-0000-0000-0000-00000000001{n}" for n in (1, 2, 3, 4, 5))
BILL = "b5940000-0000-0000-0000-000000000001"

PAN = "ABCPK1234F"            # held by VENDOR alone among CLIENT's active suppliers (RETIRED, inactive, holds it too)
TWIN_PAN = "AAKCT5678G"       # held by two active suppliers of CLIENT
RETIRED_PAN = "AAFFR9012H"    # held only by an inactive supplier of CLIENT
SIBLING_PAN = "AAJPS3456K"    # held by a supplier of the sibling client only
ABROAD_PAN = "AAKCA7788M"     # held only by a non-resident supplier of CLIENT
REFUSED = "to another client"   # migration 565's guard, in its own words ("that belong" on an insert, "that belongs" on an update)


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
    name = f"e594_{uuid.uuid4().hex[:12]}"
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
            INSERT INTO vendors (id, firm_id, client_id, name, pan, is_active, residential_status) VALUES
                ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Kapoor Associates', '{PAN}', true, 'resident'),
                ('{RETIRED}', '{FIRM}', '{CLIENT}', 'Kapoor Associates (old)', '{PAN}', false, NULL),
                ('{TWIN_A}', '{FIRM}', '{CLIENT}', 'Tara Traders', '{TWIN_PAN}', true, NULL),
                ('{TWIN_B}', '{FIRM}', '{CLIENT}', 'Tara Traders (Pune)', '{TWIN_PAN}', true, NULL),
                ('{ONLY_RETIRED}', '{FIRM}', '{CLIENT}', 'Ravi Fabricators', '{RETIRED_PAN}', false, NULL),
                ('{ABROAD}', '{FIRM}', '{CLIENT}', 'Helvetica Design AG', '{ABROAD_PAN}', true, 'non_resident'),
                ('{SIBLING_VENDOR}', '{FIRM}', '{SIBLING}', 'Sharma & Co', '{SIBLING_PAN}', true, NULL),
                ('{FOREIGN_VENDOR}', '{OTHER_FIRM}', '{FOREIGN}', 'Elsewhere Ltd', '{PAN}', true, NULL);
            INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, total_paise, net_payable_paise)
              VALUES ('{BILL}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'KA/001', '2026-05-10', 3000000, 2700000);
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _typed(dsn: str, n: int, *, vendor=None, pan: str = PAN, client: str = CLIENT, firm: str = FIRM,
           bill=None) -> subprocess.CompletedProcess:
    v = "NULL" if vendor is None else f"'{vendor}'"
    b = "NULL" if bill is None else f"'{bill}'"
    return _psql(dsn, f"""
        INSERT INTO tds_deductions (id, firm_id, client_id, vendor_id, purchase_bill_id, deductee_name, deductee_pan, section,
                                    transaction_date, payment_amount_paise, tds_rate_pct, tds_paise)
        VALUES ('{uuid.UUID(int=n)}', '{firm}', '{client}', {v}, {b}, 'Payee {n}', '{pan}', '194J', '2026-06-0{1 + n % 9}',
                3000000, 10, 300000);""")


def _vendor_of(dsn: str, n: int) -> str:
    return _val(dsn, f"SELECT coalesce(vendor_id::text, 'none') FROM tds_deductions WHERE id = '{uuid.UUID(int=n)}'")


def test_a_supplier_of_the_same_client_is_accepted_and_a_row_that_names_none_is_written_as_before(dsn):
    assert _typed(dsn, 1).returncode == 0
    assert _typed(dsn, 2, vendor=VENDOR).returncode == 0
    assert _vendor_of(dsn, 1) == "none" and _vendor_of(dsn, 2) == VENDOR
    assert _val(dsn, """SELECT is_nullable FROM information_schema.columns
                        WHERE table_name = 'tds_deductions' AND column_name = 'vendor_id'""") == "YES"


@pytest.mark.parametrize("other", [SIBLING_VENDOR, FOREIGN_VENDOR], ids=["a sibling client's", "another firm's"])
def test_a_supplier_of_another_client_is_refused_on_insert_and_on_update(dsn, other):
    r = _typed(dsn, 3, vendor=other)
    assert r.returncode != 0 and REFUSED in r.stderr
    assert _typed(dsn, 4).returncode == 0
    r = _psql(dsn, f"UPDATE tds_deductions SET vendor_id = '{other}' WHERE id = '{uuid.UUID(int=4)}';")
    assert r.returncode != 0 and REFUSED in r.stderr
    assert _vendor_of(dsn, 4) == "none"


def test_a_named_row_cannot_be_moved_to_another_client_with_its_supplier(dsn):
    assert _typed(dsn, 5, vendor=VENDOR).returncode == 0
    r = _psql(dsn, f"UPDATE tds_deductions SET client_id = '{SIBLING}' WHERE id = '{uuid.UUID(int=5)}';")
    assert r.returncode != 0 and REFUSED in r.stderr
    assert _val(dsn, f"SELECT client_id FROM tds_deductions WHERE id = '{uuid.UUID(int=5)}'") == CLIENT


def test_a_row_a_purchase_bill_wrote_cannot_carry_a_supplier(dsn):
    r = _typed(dsn, 6, vendor=VENDOR, bill=BILL)
    assert r.returncode != 0 and "tds_deductions_supplier_only_on_a_typed_row" in r.stderr
    assert _typed(dsn, 7, bill=BILL).returncode == 0                      # the bill's own row, with no supplier, is written as before
    r = _psql(dsn, f"UPDATE tds_deductions SET vendor_id = '{VENDOR}' WHERE id = '{uuid.UUID(int=7)}';")
    assert r.returncode != 0 and "tds_deductions_supplier_only_on_a_typed_row" in r.stderr


def test_a_supplier_a_typed_deduction_names_is_not_deleted_from_under_it(dsn):
    assert _typed(dsn, 8, vendor=VENDOR).returncode == 0
    _ok(dsn, f"DELETE FROM purchase_bills WHERE id = '{BILL}';")          # the bill is not what holds the supplier
    r = _psql(dsn, f"DELETE FROM vendors WHERE id = '{VENDOR}';")
    assert r.returncode != 0 and "violates foreign key" in r.stderr
    assert _val(dsn, f"SELECT count(*) FROM vendors WHERE id = '{VENDOR}'") == "1"


_TRIGGERS = """SELECT string_agg(tgname, ',' ORDER BY tgname) FROM pg_trigger
                WHERE tgrelid = 'public.tds_deductions'::regclass AND tgname LIKE 'row\\_%' AND NOT tgisinternal"""


def test_the_shared_guard_carries_the_vendor_triggers_and_no_trigger_of_its_own(dsn):
    assert _val(dsn, _TRIGGERS) == "row_client_in_firm_ins,row_client_in_firm_upd,row_vendor_in_client_ins,row_vendor_in_client_upd"
    assert _val(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'assert_tds_deduction_names_its_clients_supplier'") == "0"


def test_the_backfill_names_a_supplier_only_where_exactly_one_active_supplier_of_the_client_holds_the_pan(dsn):
    # Rows written as they were before the migration, then the migration run again: its backfill is the same statement.
    rows = {
        11: dict(pan=PAN),                                # one active holder (the inactive one does not count) -> VENDOR
        12: dict(pan=" abcpk1234f "),                     # the same PAN typed in small letters with spaces -> VENDOR
        13: dict(pan=TWIN_PAN),                           # two active holders -> none
        14: dict(pan=RETIRED_PAN),                        # only an inactive holder -> none
        15: dict(pan=SIBLING_PAN),                        # held by a supplier of another client -> none
        16: dict(pan="PANNOTAVBL"),                       # not a PAN -> none
        19: dict(pan=ABROAD_PAN),                         # held only by a non-resident supplier -> none (s.195 is not charged here)
        17: dict(pan=PAN, bill=BILL),                     # the bill's own row -> none, whoever holds its PAN
        18: dict(pan=PAN, client=SIBLING),                # another client's typed row -> none (its client has no such supplier)
    }
    for n, kw in rows.items():
        assert _typed(dsn, n, **kw).returncode == 0
    _run(dsn, MIGRATION)
    got = {n: _vendor_of(dsn, n) for n in rows}
    assert got == {11: VENDOR, 12: VENDOR, 13: "none", 14: "none", 15: "none", 16: "none", 17: "none", 18: "none", 19: "none"}
    # A row that already names a supplier is not re-pointed by a later run.
    _ok(dsn, f"UPDATE tds_deductions SET vendor_id = NULL WHERE id = '{uuid.UUID(int=11)}';"
             f"UPDATE tds_deductions SET vendor_id = '{TWIN_A}', deductee_pan = '{TWIN_PAN}' WHERE id = '{uuid.UUID(int=13)}';")
    _run(dsn, MIGRATION)
    assert _vendor_of(dsn, 11) == VENDOR and _vendor_of(dsn, 13) == TWIN_A


def test_the_migration_is_idempotent_and_its_rollback_stops_the_refusal(dsn):
    _run(dsn, MIGRATION)                                      # a second run changes nothing and fails nothing
    assert _typed(dsn, 21, vendor=SIBLING_VENDOR).returncode != 0
    assert _val(dsn, "SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_tds_deductions_typed_supplier'") == "1"
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)                                       # the rollback is safe to run twice
    assert _val(dsn, """SELECT count(*) FROM information_schema.columns
                        WHERE table_name = 'tds_deductions' AND column_name = 'vendor_id'""") == "0"
    assert _val(dsn, _TRIGGERS) == "row_client_in_firm_ins,row_client_in_firm_upd"   # the table's own, as before 594
    assert _val(dsn, "SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_tds_deductions_typed_supplier'") == "0"
    assert _val(dsn, """SELECT count(*) FROM pg_constraint
                        WHERE conname = 'tds_deductions_supplier_only_on_a_typed_row'""") == "0"
    # THE NEGATIVE CONTROL: the same column with its key and no trigger takes a sibling client's supplier, so the refusal above is the
    # guard's and not the key's.
    _ok(dsn, "ALTER TABLE tds_deductions ADD COLUMN vendor_id UUID REFERENCES vendors(id);")
    assert _typed(dsn, 22, vendor=SIBLING_VENDOR).returncode == 0
    _ok(dsn, f"DELETE FROM tds_deductions WHERE id = '{uuid.UUID(int=22)}';"
             "ALTER TABLE tds_deductions DROP COLUMN vendor_id;")
    _run(dsn, MIGRATION)                                      # and the migration applies again on top of its rollback
    assert _typed(dsn, 23, vendor=VENDOR).returncode == 0
    assert _typed(dsn, 24, vendor=SIBLING_VENDOR).returncode != 0
