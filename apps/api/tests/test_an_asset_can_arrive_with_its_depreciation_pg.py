"""Migration 456 on real PostgreSQL (accounting-18).

WHY THIS NEEDS A REAL DATABASE. The mock suite stores an asset in a dict and so
cannot say whether the column exists, what type it is, whether an old row reads
as NULL, whether the migration can be applied a second time, or whether it left
the browser's read-only access to this table exactly as migration 245 set it. The
whole design rests on the fact that `opening_position_date` is a nullable DATE
that every asset acquired here leaves NULL — if it came out NOT NULL or
defaulted, every existing asset would read as "brought over" and the
register-integrity check for a missing acquisition journal would go silent on
real defects.

These self-skip without HARNESS_PG and psql. They cannot be run in the
environment this was written in, and say so rather than pretending otherwise.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

API_ROOT = Path(__file__).resolve().parents[1]
FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"


def _migration() -> Path:
    return next((API_ROOT / "migrations").glob("456_*.sql"))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"opening_asset_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _ordinary_asset(dsn, code="TAG-1"):
    """What `create_asset` writes: no position, accumulated depreciation at nil."""
    return _psql(dsn, f"""
        INSERT INTO fixed_assets
          (firm_id, client_id, asset_code, asset_name, asset_category, purchase_date,
           purchase_cost_paise, depreciation_method)
        VALUES ('{FIRM}', '{CLIENT}', '{code}', 'Lathe', 'Plant & Machinery',
                '2025-06-12', 10000000, 'WDV');
    """)


def _opening_asset(dsn, code="TAG-2", position="2026-03-31"):
    """What the register import writes."""
    return _psql(dsn, f"""
        INSERT INTO fixed_assets
          (firm_id, client_id, asset_code, asset_name, asset_category, purchase_date,
           purchase_cost_paise, depreciation_method, wdv_rate_percent,
           accumulated_depreciation_paise, current_wdv_paise,
           depreciation_posted_through, opening_position_date)
        VALUES ('{FIRM}', '{CLIENT}', '{code}', 'Press', 'Plant & Machinery',
                '2021-06-12', 10000000, 'WDV', 15.00,
                4000000, 6000000, '{position}', '{position}');
    """)


def test_the_column_is_a_nullable_date_with_no_default(db):
    """Nullable and undefaulted, because NULL is TRUE of every asset that exists:
    each was acquired through `create_asset`, which posts an acquisition."""
    assert _rows(db, """
        SELECT data_type || '|' || is_nullable || '|' || coalesce(column_default, '')
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'fixed_assets'
           AND column_name = 'opening_position_date';
    """) == ["date|YES|"]


def test_an_asset_acquired_here_carries_no_position(db):
    assert _ordinary_asset(db).returncode == 0
    assert _rows(db, f"""
        SELECT coalesce(opening_position_date::text, 'null'),
               accumulated_depreciation_paise::text
          FROM fixed_assets WHERE client_id = '{CLIENT}' AND asset_code = 'TAG-1';
    """) == ["null|0"]


def test_an_opening_asset_keeps_its_whole_position(db):
    assert _opening_asset(db).returncode == 0
    assert _rows(db, f"""
        SELECT opening_position_date::text || '|' || depreciation_posted_through::text
               || '|' || accumulated_depreciation_paise::text
               || '|' || current_wdv_paise::text
          FROM fixed_assets WHERE client_id = '{CLIENT}' AND asset_code = 'TAG-2';
    """) == ["2026-03-31|2026-03-31|4000000|6000000"]


def test_a_code_is_still_one_asset_for_an_opening_asset_too(db):
    """Migration 351's unique index is what makes a re-upload recognisable and a
    deleted asset's code unusable; the new column must not have loosened it."""
    assert _opening_asset(db, code="TAG-9").returncode == 0
    again = _opening_asset(db, code="TAG-9")
    assert again.returncode != 0, "a second asset with the same code must be refused"
    assert _ordinary_asset(db, code="TAG-9").returncode != 0


def test_the_migration_can_be_applied_a_second_time(db):
    """Idempotent: the apply job runs on every push to main, and a re-run must be
    a no-op rather than an error that blocks every migration behind it."""
    for _ in range(2):
        r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q",
                            "-f", str(_migration())], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    assert _rows(db, """
        SELECT count(*)::text FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'fixed_assets'
           AND column_name = 'opening_position_date';
    """) == ["1"]


def test_an_existing_asset_is_untouched_by_a_second_application(db):
    assert _opening_asset(db).returncode == 0
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(_migration())],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert _rows(db, f"""
        SELECT opening_position_date::text FROM fixed_assets
         WHERE client_id = '{CLIENT}' AND asset_code = 'TAG-2';
    """) == ["2026-03-31"]


def test_the_browser_stays_read_only_on_the_new_column(db):
    """Migrations 166 and 245 revoked INSERT and UPDATE on this table from
    `authenticated`, so a direct write cannot bypass the router that decides what
    an asset's position may be. The migration adds no grant, and this proves it."""
    assert _rows(db, """
        SELECT has_column_privilege('authenticated', 'public.fixed_assets',
                                    'opening_position_date', 'INSERT')::text
            || '|' ||
               has_column_privilege('authenticated', 'public.fixed_assets',
                                    'opening_position_date', 'UPDATE')::text;
    """) == ["false|false"]
