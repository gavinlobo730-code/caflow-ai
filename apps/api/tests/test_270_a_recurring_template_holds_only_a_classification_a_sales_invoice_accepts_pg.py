"""
R270 — proves migration 270 on real PostgreSQL: a recurring template can hold
the GSTR-1 classification, and cannot hold one a sales invoice would refuse.

WHY THE VOCABULARIES MUST MATCH EXACTLY
    services/recurring_invoice_service.py copies the template's classification
    onto the invoice it generates. If the template's CHECK were ever looser than
    client_sales_invoices' (migration 268), the template would save fine and the
    INVOICE insert would fail — inside generate_for_occurrence, which runs
    unattended as part of the 06:00 IST sweep. The failure would surface as a
    scheduler_runs row nobody reads, on a day the CA believes their recurring
    invoices went out.

    So this asserts the two tables agree, rather than asserting migration 270's
    literal text. A future widening of either side fails here.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
    reason="recurring-template classification proof requires HARNESS_PG + psql",
)

TEMPLATES = "recurring_invoice_templates"
INVOICES = "client_sales_invoices"
COLUMNS = ("supply_type", "invoice_type", "is_reverse_charge")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A", "-c", sql],
        capture_output=True, text=True,
    )


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r270_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _column(dsn: str, table: str, column: str) -> tuple[str, str]:
    """(column_default, is_nullable) — empty default reads as ''."""
    r = _psql(dsn, f"""
        SELECT coalesce(column_default, '') || '|' || is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = '{table}'
          AND column_name = '{column}';
    """)
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip()
    assert out, f"{table}.{column} does not exist"
    default, _, nullable = out.partition("|")
    return default, nullable


def _check_clause(dsn: str, table: str, column: str) -> str:
    """The CHECK constraint text mentioning this column, normalised."""
    r = _psql(dsn, f"""
        SELECT pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public' AND t.relname = '{table}'
          AND c.contype = 'c' AND pg_get_constraintdef(c.oid) LIKE '%{column}%';
    """)
    assert r.returncode == 0, r.stderr
    return " ".join(r.stdout.split())


# ── The columns exist, with the behaviour existing templates already had ──────

def test_template_has_the_three_classification_columns(migrated_db):
    for column in COLUMNS:
        _column(migrated_db, TEMPLATES, column)   # asserts existence


@pytest.mark.parametrize("column,expected_default", [
    ("supply_type", "'taxable'::text"),
    ("invoice_type", "'Regular'::text"),
    ("is_reverse_charge", "false"),
])
def test_defaults_preserve_pre_migration_behaviour(migrated_db, column, expected_default):
    """A template written before 270 must keep generating exactly what it did:
    a plain domestic taxable sale."""
    default, nullable = _column(migrated_db, TEMPLATES, column)
    assert default == expected_default, f"{column} default is {default!r}"
    assert nullable == "NO", f"{column} must be NOT NULL so generation never reads a null"


# ── The vocabularies agree with the invoice's ─────────────────────────────────

@pytest.mark.parametrize("column", ["supply_type", "invoice_type"])
def test_template_vocabulary_matches_the_invoice(migrated_db, column):
    """If these drift, a template saves and the generated INSERT fails inside an
    unattended job."""
    template_check = _check_clause(migrated_db, TEMPLATES, column)
    invoice_check = _check_clause(migrated_db, INVOICES, column)
    assert template_check, f"no CHECK on {TEMPLATES}.{column}"
    assert invoice_check, f"no CHECK on {INVOICES}.{column}"

    def values(clause: str) -> set[str]:
        import re
        return set(re.findall(r"'([a-zA-Z_]+)'::text", clause))

    assert values(template_check) == values(invoice_check), (
        f"{column} vocabularies differ — template {values(template_check)} "
        f"vs invoice {values(invoice_check)}"
    )


def test_database_rejects_a_value_outside_the_vocabulary(migrated_db):
    r = _psql(migrated_db, f"""
        INSERT INTO {TEMPLATES}
            (firm_id, client_id, customer_id, title, frequency, start_date, next_run_date, supply_type)
        VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),
                'probe', 'monthly', '2026-06-01', '2026-06-01', 'exemtp');
    """)
    assert r.returncode != 0, "a supply_type outside the vocabulary was accepted"
    assert "check constraint" in r.stderr.lower(), r.stderr
