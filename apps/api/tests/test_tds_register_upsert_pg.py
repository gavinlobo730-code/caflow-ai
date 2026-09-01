"""
The TDS register's one-row-per-bill guarantee, against a real Postgres.

WHY THIS IS A REAL-POSTGRES TEST
    tds_register_service does an UPSERT with on_conflict="purchase_bill_id",
    which Postgres resolves by INFERRING an index from that column list. Index
    inference is a database behaviour with a rule that mock mode cannot have:
    a PARTIAL unique index is only inferable when the statement repeats its
    predicate, and PostgREST emits none.

    The first version of migration 307 used a partial index — WHERE
    purchase_bill_id IS NOT NULL — because that reads as the tidier statement
    of intent. Every unit test passed, and the write would have failed in
    production with "there is no unique or exclusion constraint matching the
    ON CONFLICT specification" the first time a bill was received. Only a real
    Postgres shows that.

    So this asserts the two properties the index actually has to have, in the
    database that has to have them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="TDS register upsert proof requires HARNESS_PG + psql",
)

FIRM = "f3070000-0000-0000-0000-000000000001"
CLIENT = "c3070000-0000-0000-0000-000000000001"
VENDOR = "d3070000-0000-0000-0000-000000000001"
BILL = "b3070000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"tdsreg_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@x.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'T Co', 'Private Limited');
            INSERT INTO vendors (id, firm_id, client_id, name)
              VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Pinnacle');
            INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no,
                                        bill_date, total_paise, net_payable_paise)
              VALUES ('{BILL}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'PES/001',
                      '2025-10-25', 2124000, 2088000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _upsert(dsn: str, tds_paise: int) -> subprocess.CompletedProcess:
    """Exactly what PostgREST emits for upsert(on_conflict='purchase_bill_id')."""
    return _psql(dsn, f"""
        INSERT INTO tds_deductions
          (firm_id, client_id, purchase_bill_id, deductee_name, section,
           transaction_date, payment_amount_paise, tds_rate_pct, tds_paise,
           quarter, return_type)
        VALUES ('{FIRM}', '{CLIENT}', '{BILL}', 'Pinnacle', '194C',
                '2025-10-25', 1800000, 20.00, {tds_paise}, 'Q3 2025-26', '26Q')
        ON CONFLICT (purchase_bill_id) DO UPDATE SET tds_paise = EXCLUDED.tds_paise;
    """)


def test_the_upsert_the_service_performs_actually_works(db):
    first = _upsert(db, 36000)
    assert first.returncode == 0, (
        "the ON CONFLICT the service emits was rejected — index inference "
        f"failed, which a partial unique index causes: {first.stderr}")

    second = _upsert(db, 72000)
    assert second.returncode == 0, second.stderr

    rows = _psql(db, f"SELECT count(*), max(tds_paise) FROM tds_deductions "
                     f"WHERE purchase_bill_id = '{BILL}';", tuples=True)
    assert rows.stdout.strip() == "1|72000", (
        "a re-received bill must update its register row, not add a second — "
        "two rows is the same deduction reported twice in 26Q")


def test_several_hand_entered_deductions_can_have_no_bill(db):
    """The register is not only for bills. A plain unique index allows this
    because Postgres treats NULLs as distinct; if that ever changes to NULLS
    NOT DISTINCT, only the first hand-entered row would be accepted."""
    r = _psql(db, f"""
        INSERT INTO tds_deductions
          (firm_id, client_id, deductee_name, section, transaction_date,
           payment_amount_paise, tds_rate_pct, tds_paise)
        VALUES ('{FIRM}', '{CLIENT}', 'Hand 1', '194J', '2025-11-01', 100000, 10, 10000),
               ('{FIRM}', '{CLIENT}', 'Hand 2', '194J', '2025-11-02', 200000, 10, 20000),
               ('{FIRM}', '{CLIENT}', 'Hand 3', '194J', '2025-11-03', 300000, 10, 30000);
    """)
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT count(*) FROM tds_deductions WHERE purchase_bill_id IS NULL;",
                tuples=True)
    assert got.stdout.strip() == "3"


def test_deleting_the_bill_takes_its_deduction_with_it(db):
    assert _upsert(db, 36000).returncode == 0
    r = _psql(db, f"DELETE FROM purchase_bills WHERE id = '{BILL}';")
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT count(*) FROM tds_deductions;", tuples=True)
    assert got.stdout.strip() == "0", (
        "a hard-deleted bill must not leave a deduction behind — it would be "
        "filed in 26Q with no book entry behind it")
