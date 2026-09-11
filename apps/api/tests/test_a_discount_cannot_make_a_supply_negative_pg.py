"""
Migration 364 — the table refuses what §15 cannot represent.

WHY THESE ARE ON THE TABLE AND NOT ONLY IN THE SERVICE
    `domain/gst/discount.py` refuses a discount larger than the line, and the
    router turns that into a 422. That is the right place for the MESSAGE. It is
    not the right place for the RULE: a value of supply cannot be negative under
    any section of the Act, and `client_sales_invoice_lines` is written by more
    than one path already (create, the delete-and-reinsert edit, the bulk
    importer) and could grow another. Same reasoning as migration 360 — the rule
    belongs to the table, not to whoever happens to be writing.

WHAT EACH CONSTRAINT IS FOR
    * `discount_paise >= 0` — a discount is money taken OFF. A negative one is a
      surcharge, and a surcharge on an invoice is a line, not a discount.
    * `taxable_amount_paise >= 0` — which is exactly "the discount is not more
      than the gross", because the gross is taxable + discount. Stating it this
      way rather than as a comparison means it also catches a negative taxable
      value arrived at some other way.
    * the percentage range — 0 to 10000 bps. 100% is a legitimate
      free-of-charge line and is where it stops; anything above is not a
      percentage of anything.
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
    reason="requires HARNESS_PG + psql",
)

FIRM = "f3640000-0000-0000-0000-000000000001"
CLIENT = "c3640000-0000-0000-0000-000000000001"
CUSTOMER = "d3640000-0000-0000-0000-000000000001"
INVOICE = "e3640000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


SEED = f"""
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Discount Co', 'd@x.in');
INSERT INTO clients (id, firm_id, client_name, entity_type)
  VALUES ('{CLIENT}', '{FIRM}', 'Seller', 'Private Limited');
INSERT INTO customers (id, firm_id, client_id, name)
  VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Buyer');
INSERT INTO client_sales_invoices
  (id, firm_id, client_id, customer_id, invoice_no, invoice_date,
   taxable_amount_paise, total_paise)
  VALUES ('{INVOICE}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-1', '2026-04-01',
          95000, 112100);
"""


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"disc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    r = _psql(dsn, SEED)
    assert r.returncode == 0, r.stderr
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _line(dsn: str, *, discount: int = 0, taxable: int = 95_000,
          pct: str = "NULL") -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO client_sales_invoice_lines
          (sales_invoice_id, description, quantity, rate_paise,
           taxable_amount_paise, discount_paise, discount_percent_bps)
        VALUES ('{INVOICE}', 'Widget', 1, 100000, {taxable}, {discount}, {pct});
    """)


# ── The line ─────────────────────────────────────────────────────────────────

def test_an_ordinary_discounted_line_is_accepted(db):
    r = _line(db, discount=5_000, taxable=95_000, pct="500")
    assert r.returncode == 0, r.stderr


def test_a_line_with_no_discount_is_accepted(db):
    """Every line written before migration 364 is this one — the column
    defaults to 0 and the percentage to NULL."""
    r = _psql(db, f"""
        INSERT INTO client_sales_invoice_lines
          (sales_invoice_id, description, quantity, rate_paise, taxable_amount_paise)
        VALUES ('{INVOICE}', 'Widget', 1, 100000, 100000);
        SELECT discount_paise, discount_percent_bps IS NULL
          FROM client_sales_invoice_lines WHERE sales_invoice_id = '{INVOICE}';
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0|t"


def test_a_negative_discount_is_refused(db):
    r = _line(db, discount=-1)
    assert r.returncode != 0
    assert "discount_non_negative" in r.stderr


def test_a_negative_value_of_supply_is_refused(db):
    """Which is the same rule as "the discount is not more than the gross",
    because the gross is taxable + discount."""
    r = _line(db, discount=5_000, taxable=-1)
    assert r.returncode != 0
    assert "discount_non_negative" in r.stderr


def test_a_free_of_charge_line_is_accepted(db):
    """100% off is a real thing — a sample, a replacement under warranty — and
    it is where the range stops."""
    r = _line(db, discount=1_00_000, taxable=0, pct="10000")
    assert r.returncode == 0, r.stderr


def test_a_percentage_above_a_hundred_is_refused(db):
    r = _line(db, discount=5_000, taxable=95_000, pct="10001")
    assert r.returncode != 0
    assert "discount_percent_range" in r.stderr


def test_a_negative_percentage_is_refused(db):
    r = _line(db, discount=5_000, taxable=95_000, pct="-1")
    assert r.returncode != 0
    assert "discount_percent_range" in r.stderr


# ── The invoice header ───────────────────────────────────────────────────────

def test_the_header_refuses_a_negative_discount(db):
    r = _psql(db, f"""
        UPDATE client_sales_invoices SET discount_paise = -1 WHERE id = '{INVOICE}';
    """)
    assert r.returncode != 0
    assert "discount_non_negative" in r.stderr


def test_the_header_refuses_a_percentage_above_a_hundred(db):
    r = _psql(db, f"""
        UPDATE client_sales_invoices SET discount_percent_bps = 10001
        WHERE id = '{INVOICE}';
    """)
    assert r.returncode != 0
    assert "discount_percent_range" in r.stderr


def test_the_header_accepts_an_ordinary_discount(db):
    r = _psql(db, f"""
        UPDATE client_sales_invoices
           SET discount_paise = 5000, discount_percent_bps = 500
         WHERE id = '{INVOICE}';
    """)
    assert r.returncode == 0, r.stderr


# ── §15(3)(b) is a different remedy, and the schema says so ──────────────────

def test_no_note_table_grew_a_discount_column(db):
    """A post-supply discount is excluded only where it was agreed before the
    supply, is linked to the invoices, and the recipient has reversed the
    attributable ITC (§15(3)(b)). That is the §34 note itself, not a field on
    one — and a column here would be the invitation to treat it as a field."""
    r = _psql(db, """
        SELECT string_agg(DISTINCT table_name, ', ' ORDER BY table_name)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name LIKE 'discount%';
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    tables = sorted((r.stdout.strip() or "").split(", ")) if r.stdout.strip() else []
    assert tables == ["client_sales_invoice_lines", "client_sales_invoices"], tables
