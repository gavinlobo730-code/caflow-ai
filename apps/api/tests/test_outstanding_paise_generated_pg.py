"""
Migration 278 — outstanding_paise is computed by Postgres, and stays computed.

WHY THIS NEEDS A REAL DATABASE
    A generated column exists only in Postgres. Every test double in the suite
    has to imitate it (tests/e2e_harness._apply_generated), and an imitation that
    quietly diverges from the real definition is exactly the failure this file
    exists to catch: AR and AP aging now FILTER on this column, so a wrong value
    does not produce a wrong total — it makes an open invoice disappear from
    aging altogether.

WHAT IS ASSERTED
    The formulas, including the credit/debit-note terms that CGST Act §34 puts
    there; that the column follows its parts on UPDATE, which is the whole point
    of GENERATED over a column the application maintains; that NULLs coalesce
    rather than poisoning the row out of the filter; that it cannot be written
    directly; and that the partial indexes the aging queries were shaped around
    actually exist.
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
    reason="generated-column proof requires HARNESS_PG + psql",
)

FIRM = "f8000000-0000-0000-0000-000000000001"
CLIENT = "c8000000-0000-0000-0000-000000000001"
CUST = "c8800000-0000-0000-0000-000000000001"
VEND = "e8800000-0000-0000-0000-000000000001"

SEED = f"""
INSERT INTO firms (id,name,email) VALUES ('{FIRM}','Gen','g@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type)
  VALUES ('{CLIENT}','{FIRM}','Gen Co','Proprietorship');
INSERT INTO customers (id,firm_id,client_id,name) VALUES ('{CUST}','{FIRM}','{CLIENT}','Buyer');
INSERT INTO vendors  (id,firm_id,client_id,name) VALUES ('{VEND}','{FIRM}','{CLIENT}','Seller');
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"gencol_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _invoice(dsn, iid: str, total, paid=0, credited=0, debit_note=0, status="issued"):
    return _psql(dsn, f"""
        INSERT INTO client_sales_invoices
          (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
           total_paise, paid_paise, credited_paise, debit_note_paise, status)
        VALUES ('{iid}','{FIRM}','{CLIENT}','{CUST}','INV-{iid[:4]}','2026-06-01','2026-06-30',
                {total}, {paid}, {credited}, {debit_note}, '{status}');""")


def _bill(dsn, bid: str, net, paid=0, debited=0, credit_note=0, status="received"):
    return _psql(dsn, f"""
        INSERT INTO purchase_bills
          (id, firm_id, client_id, vendor_id, bill_no, bill_date, due_date,
           net_payable_paise, paid_paise, debited_paise, credit_note_paise, status)
        VALUES ('{bid}','{FIRM}','{CLIENT}','{VEND}','BILL-{bid[:4]}','2026-06-01','2026-06-30',
                {net}, {paid}, {debited}, {credit_note}, '{status}');""")


def _out(dsn, table: str, rid: str) -> str:
    return _psql(dsn, f"SELECT outstanding_paise FROM {table} WHERE id='{rid}';",
                 tuples=True).stdout.strip()


ID1 = "11111111-1111-1111-1111-111111111111"
ID2 = "22222222-2222-2222-2222-222222222222"


# ── The formulas ─────────────────────────────────────────────────────────────

def test_ar_outstanding_is_total_plus_debit_notes_less_paid_and_credited(db):
    """CGST Act §34: a debit note increases what is recoverable, a credit note
    reduces it. Aging must follow the amount actually recoverable, not the
    invoice's face value."""
    assert _invoice(db, ID1, total=100000, paid=30000, credited=5000, debit_note=2000).returncode == 0
    assert _out(db, "client_sales_invoices", ID1) == "67000"   # 100000 + 2000 - 30000 - 5000


def test_ap_outstanding_is_net_payable_plus_credit_notes_less_paid_and_debited(db):
    assert _bill(db, ID1, net=80000, paid=20000, debited=3000, credit_note=1000).returncode == 0
    assert _out(db, "purchase_bills", ID1) == "58000"          # 80000 + 1000 - 20000 - 3000


def test_it_follows_its_parts_when_a_payment_lands(db):
    """The reason it is GENERATED and not a column the application keeps in
    step: there is no write path that can forget."""
    assert _invoice(db, ID1, total=100000).returncode == 0
    assert _out(db, "client_sales_invoices", ID1) == "100000"
    assert _psql(db, f"UPDATE client_sales_invoices SET paid_paise = 100000 WHERE id='{ID1}';").returncode == 0
    assert _out(db, "client_sales_invoices", ID1) == "0", "a settled invoice must fall out of aging"


def test_nulls_coalesce_instead_of_poisoning_the_row(db):
    """These columns are nullable. Without COALESCE the whole expression is NULL,
    and `outstanding_paise > 0` then silently drops the invoice — an open debt
    vanishing from aging rather than raising anything."""
    assert _psql(db, f"""
        INSERT INTO client_sales_invoices
          (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
           total_paise, status)
        VALUES ('{ID1}','{FIRM}','{CLIENT}','{CUST}','INV-N','2026-06-01','2026-06-30',
                100000, 'issued');""").returncode == 0
    assert _out(db, "client_sales_invoices", ID1) == "100000"


def test_it_cannot_be_written_directly(db):
    """If it could, a caller could set an invoice's outstanding figure to
    anything and aging would believe it."""
    r = _psql(db, f"""
        INSERT INTO client_sales_invoices
          (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
           total_paise, outstanding_paise, status)
        VALUES ('{ID2}','{FIRM}','{CLIENT}','{CUST}','INV-X','2026-06-01','2026-06-30',
                100000, 1, 'issued');""")
    assert r.returncode != 0
    assert "generated" in r.stderr.lower(), r.stderr


# ── The filter the aging queries actually send ───────────────────────────────

def test_the_aging_filter_returns_only_open_documents(db):
    """The whole point: settled and cancelled documents stop crossing the wire.
    Before this, every invoice a client had ever raised was fetched and dropped
    in Python — 5,655 rows on the live client, to list the ones still open."""
    assert _invoice(db, ID1, total=100000).returncode == 0                       # open
    assert _invoice(db, ID2, total=100000, paid=100000).returncode == 0          # settled
    assert _invoice(db, "33333333-3333-3333-3333-333333333333",
                    total=100000, status="cancelled").returncode == 0            # cancelled
    assert _invoice(db, "44444444-4444-4444-4444-444444444444",
                    total=100000, status="draft").returncode == 0                # draft

    got = _psql(db, f"""
        SELECT count(*) FROM client_sales_invoices
         WHERE firm_id='{FIRM}' AND client_id='{CLIENT}' AND deleted_at IS NULL
           AND status NOT IN ('draft','cancelled') AND outstanding_paise > 0;""", tuples=True)
    assert got.stdout.strip() == "1", "the aging filter is not narrowing to open documents"


def test_a_credit_note_can_take_an_invoice_out_of_aging(db):
    """Fully credit-noted is not 'paid', but it is not outstanding either."""
    assert _invoice(db, ID1, total=100000, credited=100000).returncode == 0
    assert _out(db, "client_sales_invoices", ID1) == "0"


# ── The indexes the queries were shaped around ───────────────────────────────

@pytest.mark.parametrize("index,table", [
    ("idx_csi_open_for_aging", "client_sales_invoices"),
    ("idx_pb_open_for_aging", "purchase_bills"),
])
def test_the_partial_index_exists(db, index, table):
    """Partial, matching the filter exactly — so on a mature client the index
    stays the size of the answer while the table grows."""
    r = _psql(db, f"""
        SELECT indexdef FROM pg_indexes
         WHERE schemaname='public' AND tablename='{table}' AND indexname='{index}';""",
        tuples=True)
    definition = r.stdout.strip()
    assert definition, f"{index} is missing"
    assert "outstanding_paise > 0" in definition, f"{index} is not partial on outstanding: {definition}"


# ── The doubles must agree with the database ─────────────────────────────────

def test_the_test_doubles_compute_the_same_thing(db):
    """tests/e2e_harness._apply_generated imitates this column for every fake DB
    in the suite. An imitation that drifts would make the mock-mode tests agree
    with each other and disagree with production — so it is checked against the
    real column here, which is the only place both exist at once."""
    from tests.e2e_harness import _apply_generated

    cases = [
        dict(total=100000, paid=30000, credited=5000, debit_note=2000),
        dict(total=0, paid=0, credited=0, debit_note=0),
        dict(total=50000, paid=50000, credited=0, debit_note=0),
        dict(total=50000, paid=0, credited=60000, debit_note=0),      # over-credited: negative
    ]
    for i, c in enumerate(cases):
        rid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"gencol.{i}"))
        assert _invoice(db, rid, **c).returncode == 0
        rows = [{"total_paise": c["total"], "paid_paise": c["paid"],
                 "credited_paise": c["credited"], "debit_note_paise": c["debit_note"]}]
        _apply_generated("client_sales_invoices", rows)
        assert str(rows[0]["outstanding_paise"]) == _out(db, "client_sales_invoices", rid), (
            f"double and database disagree on {c}"
        )
