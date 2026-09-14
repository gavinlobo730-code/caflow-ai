"""Migration 393 — the purchase order and the goods receipt, on real PostgreSQL
(PUR-25).

WHY THIS NEEDS A REAL DATABASE. Four of the design decisions are CONSTRAINTS
rather than code, and none is observable in mock mode:

  * `received_on` NOT NULL — the date CGST s.16(2)(b) and MSMED s.2(b) both
    turn on, and a receipt without it answers neither;
  * the objection pair's ORDER, which is s.2(b)'s Explanation, second limb;
  * `rejected_qty` bounded by what actually arrived, because s.16(2)(b) asks
    what was RECEIVED and s.2(b) what was ACCEPTED and one number cannot answer
    both;
  * the grant model — all four tables are READ from the browser and written
    only through `rbac()`.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
import re
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
VENDOR = "33333333-3333-3333-3333-333333333333"

TABLES = ("purchase_orders", "purchase_order_lines", "goods_receipt_notes",
          "goods_receipt_lines")
MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"purchasecycle_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn,
             f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO vendors (id, firm_id, client_id, name)
            VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Acme Tools');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _order(dsn, *, no="PO/1", date="2026-04-01", status="draft"):
    return _psql(dsn, f"""
        INSERT INTO purchase_orders
          (firm_id, client_id, vendor_id, document_no, document_date, status)
        VALUES ('{FIRM}', '{CLIENT}', '{VENDOR}', '{no}', DATE '{date}',
                '{status}');
    """)


def _receipt(dsn, *, no="GRN/1", received="DATE '2026-04-05'",
             raised="NULL", removed="NULL", status="draft"):
    return _psql(dsn, f"""
        INSERT INTO goods_receipt_notes
          (firm_id, client_id, vendor_id, document_no, received_on, status,
           objection_raised_on, objection_removed_on)
        VALUES ('{FIRM}', '{CLIENT}', '{VENDOR}', '{no}', {received},
                '{status}', {raised}, {removed});
    """)


def _one_receipt(dsn) -> str:
    assert _receipt(dsn).returncode == 0
    return _rows(dsn, "SELECT id FROM goods_receipt_notes LIMIT 1;")[0]


def _receipt_line(dsn, receipt_id, *, qty="10", rejected="0"):
    return _psql(dsn, f"""
        INSERT INTO goods_receipt_lines
          (firm_id, client_id, receipt_id, description, quantity, rejected_qty)
        VALUES ('{FIRM}', '{CLIENT}', '{receipt_id}', 'Casting', {qty},
                {rejected});
    """)


# ── the tables exist and are guarded ────────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_the_table_exists(db, table):
    assert _rows(db, f"SELECT to_regclass('public.{table}');") == [f"{table}"]


@pytest.mark.parametrize("table", TABLES)
def test_row_level_security_is_on(db, table):
    assert _rows(db,
        f"SELECT relrowsecurity FROM pg_class "
        f"WHERE oid = 'public.{table}'::regclass;") == ["t"]


@pytest.mark.parametrize("table", TABLES)
def test_the_browser_may_read_and_may_not_write(db, table):
    granted = set(_rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{table}'
           AND grantee = 'authenticated';"""))
    assert granted == {"SELECT"}, granted
    service = set(_rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{table}'
           AND grantee = 'service_role';"""))
    assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= service


@pytest.mark.parametrize("table", TABLES)
def test_the_table_is_assignment_scoped(db, table):
    """Migration 084's loop has never run again (see 370), so a table created
    now is firm-wide unless it says otherwise."""
    policies = _rows(db, f"""
        SELECT polname FROM pg_policy
         WHERE polrelid = 'public.{table}'::regclass
           AND polpermissive = false;""")
    assert f"{table}_assignment_scope" in policies, policies


# ── the date both statutes turn on ──────────────────────────────────────────

def test_a_goods_receipt_MUST_carry_the_day_the_goods_arrived(db):
    """CGST s.16(2)(b) asks whether the goods have been received and MSMED
    s.2(b) runs the clock from the day of delivery. A receipt with no date
    answers neither."""
    assert _rows(db, """
        SELECT is_nullable FROM information_schema.columns
         WHERE table_name = 'goods_receipt_notes'
           AND column_name = 'received_on';""") == ["NO"]
    assert _receipt(db, received="NULL").returncode != 0
    assert _receipt(db, no="GRN/OK").returncode == 0


def test_an_objection_cannot_be_REMOVED_before_it_was_RAISED(db):
    """MSMED s.2(b), Explanation, second limb: where the buyer objects in
    writing, the day of acceptance is the day the objection is REMOVED."""
    assert _receipt(db, no="G/A", raised="DATE '2026-04-10'",
                    removed="DATE '2026-04-20'").returncode == 0
    assert _receipt(db, no="G/B", raised="DATE '2026-04-20'",
                    removed="DATE '2026-04-10'").returncode != 0
    # And a removal with no objection behind it is not the second limb at all.
    assert _receipt(db, no="G/C", removed="DATE '2026-04-20'").returncode != 0
    # Same day is fine — raised and settled at once.
    assert _receipt(db, no="G/D", raised="DATE '2026-04-10'",
                    removed="DATE '2026-04-10'").returncode == 0


def test_more_cannot_be_rejected_than_arrived(db):
    rid = _one_receipt(db)
    assert _receipt_line(db, rid, qty="10", rejected="10").returncode == 0
    assert _receipt_line(db, rid, qty="10", rejected="0").returncode == 0
    assert _receipt_line(db, rid, qty="10", rejected="10.001").returncode != 0
    assert _receipt_line(db, rid, qty="10", rejected="-1").returncode != 0


# ── status vocabularies match the engines ───────────────────────────────────

def test_the_order_status_check_speaks_the_engines_vocabulary(db):
    from domain.purchases import order_cycle as oc
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.purchase_orders'::regclass
           AND conname = 'purchase_orders_status_check';""")
    assert definition, "the status CHECK is gone"
    assert set(re.findall(r"'([^']*)'", definition[0])) == set(oc.ORDER_STATUSES)


def test_the_receipt_status_check_speaks_the_engines_vocabulary(db):
    from domain.purchases import order_cycle as oc
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.goods_receipt_notes'::regclass
           AND conname = 'goods_receipt_notes_status_check';""")
    assert definition, "the status CHECK is gone"
    assert set(re.findall(r"'([^']*)'", definition[0])) == set(oc.GRN_STATUSES)


@pytest.mark.parametrize("status", ["posted", "APPROVED", ""])
def test_a_status_the_engine_does_not_know_is_refused(db, status):
    assert _order(db, status=status).returncode != 0


def test_two_orders_may_not_share_a_number(db):
    assert _order(db, no="PO/9").returncode == 0
    assert _order(db, no="PO/9").returncode != 0
    assert _order(db, no="po/9").returncode != 0


def test_two_receipts_may_not_share_a_number(db):
    assert _receipt(db, no="GRN/9").returncode == 0
    assert _receipt(db, no="GRN/9").returncode != 0
    assert _receipt(db, no="grn/9").returncode != 0


def test_a_blank_number_is_refused(db):
    assert _order(db, no="   ").returncode != 0
    assert _receipt(db, no="   ").returncode != 0


# ── what is deliberately NOT here ───────────────────────────────────────────

def test_no_order_line_stores_a_received_or_billed_quantity(db):
    """Both are FUNCTIONS of the receipts and bills raised against the order,
    so a stored figure is wrong the moment one is cancelled — migration 278's
    reasoning applied to a quantity."""
    cols = set(_rows(db, """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'purchase_order_lines';"""))
    assert "received_qty" not in cols
    assert "billed_qty" not in cols
    assert "quantity" in cols


@pytest.mark.parametrize("table", TABLES)
def test_no_pre_bill_table_carries_a_journal(db, table):
    """The expense, the input credit and the payable all arise when the BILL
    is received. A `journal_entry_id` here would invite a posting path."""
    cols = set(_rows(db, f"""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = '{table}';"""))
    assert not {c for c in cols if "journal" in c}, cols


def test_the_bill_link_is_nullable_and_NOT_back_filled(db):
    """Most purchases a practice sees — fees, rent, utilities — are never
    ordered, so an unlinked line is ordinary; and every bill already on the
    books predates this column, so filling it in would be a guess."""
    assert _rows(db, """
        SELECT is_nullable, coalesce(column_default, '-')
          FROM information_schema.columns
         WHERE table_name = 'purchase_bill_lines'
           AND column_name = 'purchase_order_line_id';""") == ["YES|-"]
    assert _rows(db, """
        SELECT is_nullable FROM information_schema.columns
         WHERE table_name = 'purchase_bills'
           AND column_name = 'purchase_order_id';""") == ["YES"]


# ── the rollback refuses while a receipt exists ─────────────────────────────

def _rollback_sql() -> str:
    return (MIGRATIONS / "393_the_purchase_cycle_before_the_bill_rollback.sql"
            ).read_text(encoding="utf-8")


def test_the_rollback_refuses_while_a_goods_receipt_exists(db):
    """Without the receipt s.43B(h) falls back to the earlier BILL date,
    turning bills paid in time into disallowances with nothing on the screen
    saying the date moved."""
    assert _receipt(db, no="GRN/KEEP", status="recorded").returncode == 0
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=_rollback_sql(), capture_output=True, text=True)
    assert r.returncode != 0, "the rollback ran with a receipt still on file"
    assert "Refusing to roll back 393" in r.stderr
    assert _rows(db, "SELECT to_regclass('public.goods_receipt_notes');") \
        == ["goods_receipt_notes"]


def test_the_rollback_runs_once_the_receipts_are_gone(db):
    assert _receipt(db, no="GRN/GONE", status="cancelled").returncode == 0
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=_rollback_sql(), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for table in TABLES:
        assert _rows(db, f"SELECT to_regclass('public.{table}');") in ([], [""])
    # And the two columns it added come off with it.
    assert _rows(db, """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'purchase_bill_lines'
           AND column_name = 'purchase_order_line_id';""") == []


def test_the_migration_is_rerunnable(db):
    sql = (MIGRATIONS / "393_the_purchase_cycle_before_the_bill.sql"
           ).read_text(encoding="utf-8")
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                       input=sql, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
