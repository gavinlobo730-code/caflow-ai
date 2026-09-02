"""
Migration 308's CHECK constraints, against a real Postgres.

WHY THIS IS A REAL-POSTGRES TEST
    The Pydantic models refuse a bad residential_status or a country name where
    a code belongs, and mock-mode tests prove that. Neither proves the DATABASE
    refuses it — and the frontend writes ~83 tables directly through PostgREST
    (CLAUDE.md), so a column whose only guard is a Pydantic model is a column
    with a way round it.

    'nonresident' stored instead of 'non_resident' reads as unclassified
    everywhere downstream: is_non_resident() returns False, the deduction goes
    to 26Q, and the CA who typed it believes the vendor is classified. That is
    the failure the CHECK exists to make impossible.

    The country CHECK is the same argument at the other end: Form 27Q takes an
    ISO 3166-1 alpha-2 code, so 'United Arab Emirates' in that column is an FVU
    rejection discovered at filing, months after the deduction was made.
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
    reason="migration 308 constraint proof requires HARNESS_PG + psql",
)

FIRM = "f3080000-0000-0000-0000-000000000001"
CLIENT = "c3080000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"vresid_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@x.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'T Co', 'Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert_vendor(dsn: str, name: str, **cols) -> subprocess.CompletedProcess:
    keys = ", ".join(cols)
    vals = ", ".join("NULL" if v is None else f"'{v}'" for v in cols.values())
    lead = f", {keys}" if keys else ""
    tail = f", {vals}" if vals else ""
    return _psql(dsn, f"""
        INSERT INTO vendors (firm_id, client_id, name{lead})
        VALUES ('{FIRM}', '{CLIENT}', '{name}'{tail});
    """)


# ── residential_status ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["resident", "non_resident"])
def test_the_two_real_values_are_accepted(db, value):
    assert _insert_vendor(db, f"V {value}", residential_status=value).returncode == 0


def test_a_vendor_with_no_residential_status_is_accepted(db):
    """Every row that existed before migration 308 is in this state. A NOT NULL
    here would have made the whole vendor master unwritable on deploy."""
    r = _insert_vendor(db, "Legacy Vendor")
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT count(*) FROM vendors WHERE residential_status IS NULL;",
                tuples=True)
    assert got.stdout.strip() == "1"


@pytest.mark.parametrize("value", ["nonresident", "non resident", "NON_RESIDENT",
                                   "Resident", "nri", "foreign"])
def test_a_near_miss_status_is_refused_by_the_database(db, value):
    """Not merely wrong — SILENTLY wrong. Anything the CHECK lets through that
    is not exactly 'non_resident' reads as unclassified to is_non_resident(),
    so the deduction goes to 26Q while the CA believes it is classified."""
    r = _insert_vendor(db, f"Bad {value}", residential_status=value)
    assert r.returncode != 0, f"the database accepted residential_status={value!r}"
    assert "vendors_residential_status_check" in r.stderr


# ── country_of_residence ─────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["AE", "SG", "US", "CH"])
def test_an_iso_alpha_2_code_is_accepted(db, value):
    assert _insert_vendor(db, f"NR {value}", residential_status="non_resident",
                          country_of_residence=value).returncode == 0


@pytest.mark.parametrize("value", ["United Arab Emirates", "ae", "UAE", "A", "AE1", "  "])
def test_anything_that_is_not_an_iso_code_is_refused(db, value):
    """Lowercase included: the column is compared and reported as-is, and 'ae'
    is not the code Form 27Q takes."""
    r = _insert_vendor(db, f"Bad {value}", residential_status="non_resident",
                       country_of_residence=value)
    assert r.returncode != 0, f"the database accepted country_of_residence={value!r}"
    assert "vendors_country_of_residence_check" in r.stderr


def test_the_database_does_not_itself_require_a_country_for_a_non_resident(db):
    """Deliberate division of labour. The API refuses to CREATE a non-resident
    without a country, because that is a decision a human is making right then.
    The column stays nullable so a bulk import or a data fix can classify a
    vendor first and chase the country afterwards, rather than the whole write
    failing at the database with no explanation."""
    assert _insert_vendor(db, "NR pending", residential_status="non_resident").returncode == 0


# ── the deduction row ────────────────────────────────────────────────────────

def test_the_deduction_table_takes_the_27q_identifiers(db):
    r = _psql(db, f"""
        INSERT INTO tds_deductions
          (firm_id, client_id, deductee_name, section, transaction_date,
           payment_amount_paise, tds_rate_pct, tds_paise, return_type,
           country_of_residence, deductee_tin)
        VALUES ('{FIRM}', '{CLIENT}', 'Helvetica Design AG', '195', '2025-10-25',
                50000000, 20.00, 10000000, '27Q', 'CH', 'CHE-113.456.789');
    """)
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT return_type || '|' || country_of_residence || '|' || "
                    "deductee_tin FROM tds_deductions;", tuples=True)
    assert got.stdout.strip() == "27Q|CH|CHE-113.456.789"


def test_27q_was_already_an_allowed_return_type(db):
    """Migration 014's CHECK has allowed 24Q/26Q/27Q/27EQ since the table
    existed — so what was missing was never the column, only anything that
    could decide which one to write."""
    r = _psql(db, "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                  "WHERE conrelid = 'public.tds_deductions'::regclass "
                  "AND pg_get_constraintdef(oid) LIKE '%return_type%';", tuples=True)
    assert "27Q" in r.stdout


def test_the_27q_lookup_index_exists(db):
    """Assembling 27Q for a quarter reads exactly the non-26Q rows; without the
    index that is a scan of every deduction the firm has ever recorded."""
    got = _psql(db, "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'idx_tds_deductions_return_type';", tuples=True)
    assert "return_type" in got.stdout and "transaction_date" in got.stdout


# ── Migration 309: what a s.195 withholding needs ───────────────────────────

def test_every_nature_the_engine_prices_is_accepted_by_the_column(db):
    """The CHECK is generated from domain/tds/section_195_rates.ALL_NATURES. A
    nature the engine can price and the database refuses is a vendor that
    cannot be saved; one the database allows and the engine cannot price is a
    vendor that saves and a bill that never books."""
    from domain.tds.section_195_rates import ALL_NATURES
    for i, nature in enumerate(ALL_NATURES):
        r = _insert_vendor(db, f"NR {i}", residential_status="non_resident",
                           country_of_residence="CH",
                           section_195_nature_of_income=nature)
        assert r.returncode == 0, f"{nature} rejected by the CHECK: {r.stderr}"


@pytest.mark.parametrize("value", ["consultancy", "ROYALTY", "fees for technical services",
                                   "business_profits", ""])
def test_a_nature_the_rate_table_does_not_price_is_refused(db, value):
    r = _insert_vendor(db, f"Bad {value}", residential_status="non_resident",
                       country_of_residence="CH", section_195_nature_of_income=value)
    assert r.returncode != 0, f"the database accepted nature={value!r}"
    assert "vendors_section_195_nature_check" in r.stderr


@pytest.mark.parametrize("bps", [0, 500, 1000, 10000])
def test_a_treaty_rate_within_range_is_accepted(db, bps):
    """Zero is a real treaty rate, not an unset one — several agreements tax
    nothing where there is no permanent establishment."""
    r = _psql(db, f"""
        INSERT INTO vendors (firm_id, client_id, name, residential_status,
                             country_of_residence, treaty_rate_bps)
        VALUES ('{FIRM}', '{CLIENT}', 'T {bps}', 'non_resident', 'CH', {bps});
    """)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("bps", [-1, 10001, 100000])
def test_a_treaty_rate_outside_zero_to_one_hundred_percent_is_refused(db, bps):
    """A negative rate would refund tax out of a withholding; above 100% takes
    more than the payment. Both are typos, and both reach the deduction."""
    r = _psql(db, f"""
        INSERT INTO vendors (firm_id, client_id, name, treaty_rate_bps)
        VALUES ('{FIRM}', '{CLIENT}', 'Bad {bps}', {bps});
    """)
    assert r.returncode != 0, f"the database accepted treaty_rate_bps={bps}"
    assert "vendors_treaty_rate_bps_check" in r.stderr


def test_the_three_evidence_flags_default_to_false_not_null(db):
    """A NULL 'do we hold a TRC' read as truthy anywhere would apply treaty
    relief nobody established. They are NOT NULL DEFAULT false for that."""
    assert _insert_vendor(db, "Plain").returncode == 0
    got = _psql(db, "SELECT trc_on_file::text || form_10f_on_file::text || "
                    "no_pe_declaration_on_file::text FROM vendors WHERE name = 'Plain';",
                tuples=True)
    assert got.stdout.strip() == "falsefalsefalse"


def test_the_bill_and_the_deduction_carry_the_surcharge_and_cess_split(db):
    """Form 27Q reports tax, surcharge and cess in separate columns of the
    deductee annexure, so the split has to survive from the bill to the
    register. Both default to 0, which is what a resident-section bill is."""
    for table in ("purchase_bills", "tds_deductions"):
        cols = _psql(db, f"""
            SELECT column_name || ':' || column_default
              FROM information_schema.columns
             WHERE table_schema='public' AND table_name='{table}'
               AND column_name IN ('tds_surcharge_paise','tds_cess_paise',
                                   'surcharge_paise','cess_paise')
             ORDER BY 1;""", tuples=True)
        lines = [l for l in cols.stdout.strip().split("\n") if l]
        assert len(lines) == 2, f"{table}: {lines}"
        for line in lines:
            assert line.endswith(":0"), f"{table} {line} — must default to 0"
