"""A §32 block names the row of the return it is declared on (migration 552, POST-A-070).

WHAT THIS IS FOR
    Depreciation is charged on a BLOCK, a nature at a rate (§2(11)). The block register (migration 357) holds the rate and a name the CA
    chose and no nature, and the return's Schedule DPM and DOA are a fixed set of rows, each a nature at a rate, so a block cannot be
    placed on the return without a fact only the CA holds. Migration 552 adds `income_tax_asset_blocks.itr_schedule_row`: the Department's
    own key for the row (`PlantMachinery.Rate15`, `Building.Rate10`, `Land`).

WHAT THIS HOLDS (real Postgres)
    * THE COLUMN: text, nullable, NO default (a block placed on a row nobody chose prints a figure against the wrong nature), and a
      block that existed before the migration reads NULL.
    * THE CHECK IS THE SHAPE OF A KEY AND NOT ITS MEMBERSHIP: every key the committed schemas yield for ITR-3, ITR-5 and ITR-6 is
      accepted (so a form's new row needs no migration), and what is not a key (empty, a caption, a rate with no digits, a path with a
      third segment, spaces, a statement smuggled in) is refused.
    * NOTHING ELSE MOVED: the four policies, the grants, the unique key, and the rate and opening value of an existing block.
    * THE UPSERT THE API MAKES carries the row on a conflict, and an upsert that omits the column leaves a recorded row as it was.
    * THE ROLLBACK drops the column and its check, a re-apply brings them back, applying twice changes nothing.

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
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the block-row proof requires HARNESS_PG + psql",
)

FIRM = "55200000-0000-0000-0000-000000000001"
CLIENT = "55200000-0000-0000-0000-0000000000a1"
MIGRATION = next(p for p in MIGRATIONS.glob("552_a_block_of_assets_names_the_row_of_the_return*.sql") if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("552_a_block_of_assets_names_the_row_of_the_return*_rollback.sql"))
TABLE = "public.income_tax_asset_blocks"
CHECK = "income_tax_asset_blocks_itr_schedule_row_shape"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _one(dsn: str, sql: str) -> str:
    return _rows(dsn, sql)[0][0]


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e552_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert(dsn: str, key: str = "P&M 15%", row: str | None = None, rate: int = 15, wdv: int = 1000000) -> subprocess.CompletedProcess:
    cols = "firm_id, client_id, financial_year, block_key, rate_percent, opening_wdv_paise"
    vals = f"'{FIRM}', '{CLIENT}', '2025-26', '{key}', {rate}, {wdv}"
    if row is not None:
        cols += ", itr_schedule_row"
        vals += f", '{row}'"
    return _psql(dsn, f"INSERT INTO {TABLE} ({cols}) VALUES ({vals});")


# ── the column ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_column_is_nullable_text_with_no_default(dsn):
    r = _rows(dsn, "SELECT data_type, is_nullable, coalesce(column_default, '-') FROM information_schema.columns "
                   "WHERE table_schema='public' AND table_name='income_tax_asset_blocks' AND column_name='itr_schedule_row'")
    assert r == [["text", "YES", "-"]]


def test_a_block_written_without_it_reads_null(dsn):
    assert _insert(dsn).returncode == 0
    assert _one(dsn, f"SELECT coalesce(itr_schedule_row, 'NULL') FROM {TABLE}") == "NULL"


def test_the_column_has_a_comment_that_says_what_null_means(dsn):
    c = _one(dsn, "SELECT col_description('public.income_tax_asset_blocks'::regclass, "
                  "(SELECT attnum FROM pg_attribute WHERE attrelid='public.income_tax_asset_blocks'::regclass AND attname='itr_schedule_row'))")
    assert "NULL = nobody has said" in c and "NATURE" in c


# ── the check is the shape of a key, not its membership ──────────────────────────────────────────────────────────────────────────
def _vocabulary() -> list[str]:
    import sys
    sys.path.insert(0, str(API_ROOT))
    from domain.income_tax import itr_depreciation_rows as R
    return sorted({k for f in R.FORMS for k in R.keys_for(f)})


def test_every_key_the_committed_schemas_yield_is_accepted(dsn):
    keys = _vocabulary()
    assert len(keys) >= 11, keys
    for i, key in enumerate(keys):
        r = _insert(dsn, key=f"block {i}", row=key, rate=0)
        assert r.returncode == 0, (key, r.stderr)


@pytest.mark.parametrize("bad", ["", " ", "Plant and machinery", "PlantMachinery.Rate", "PlantMachinery.Rate1234", "PlantMachinery.15",
                                 "PlantMachinery.Rate15.DepreciationDetail", "Plant Machinery.Rate15", " Land", "Land ",
                                 "Land'; DROP TABLE firms; --", "Plant_Machinery", "1Land", "PlantMachinery.rate15"])
def test_what_is_not_a_key_is_refused(dsn, bad):
    r = _insert(dsn, row=bad.replace("'", "''"))
    assert r.returncode != 0 and CHECK in r.stderr, (bad, r.stderr)


def test_the_check_exists_once_and_is_named(dsn):
    assert _one(dsn, f"SELECT count(*) FROM pg_constraint WHERE conrelid = '{TABLE}'::regclass AND conname = '{CHECK}'") == "1"


# ── nothing else moved ───────────────────────────────────────────────────────────────────────────────────────────────────────────
_POLICIES = ("SELECT policyname, cmd, permissive, coalesce(qual, '-'), coalesce(with_check, '-') FROM pg_policies "
             "WHERE schemaname='public' AND tablename='income_tax_asset_blocks' ORDER BY 1")
_GRANTS = ("SELECT grantee, privilege_type FROM information_schema.role_table_grants "
           "WHERE table_schema='public' AND table_name='income_tax_asset_blocks' ORDER BY 1, 2")


def test_the_policies_grants_and_unique_key_are_what_the_migrations_before_made_them_and_552_changes_none_of_them(dsn):
    """Later migrations added an assignment-scope policy and an internal-practice one to this table, so the claim is not 'the four of 357'
    but that this migration, applied again and rolled back and applied again, leaves every policy and grant exactly as it found them."""
    policies, grants = _rows(dsn, _POLICIES), _rows(dsn, _GRANTS)
    assert {"firm_income_tax_asset_blocks", "income_tax_asset_blocks_role_insert", "income_tax_asset_blocks_role_update",
            "income_tax_asset_blocks_role_delete"} <= {r[0] for r in policies}
    assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= {r[1] for r in grants if r[0] == "authenticated"}
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert (_rows(dsn, _POLICIES), _rows(dsn, _GRANTS)) == (policies, grants)
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert (_rows(dsn, _POLICIES), _rows(dsn, _GRANTS)) == (policies, grants)
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert (_rows(dsn, _POLICIES), _rows(dsn, _GRANTS)) == (policies, grants)
    assert _insert(dsn).returncode == 0
    dup = _insert(dsn)
    assert dup.returncode != 0 and "duplicate key" in dup.stderr


def test_an_existing_blocks_rate_and_opening_value_are_untouched_by_a_reapply(dsn):
    assert _insert(dsn, rate=15, wdv=123456789).returncode == 0
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _rows(dsn, f"SELECT rate_percent, opening_wdv_paise, itr_schedule_row IS NULL FROM {TABLE}") == [["15", "123456789", "t"]]


# ── the upsert the API makes ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _upsert(dsn: str, with_row: str | None, set_row: bool, wdv: int) -> subprocess.CompletedProcess:
    cols = "firm_id, client_id, financial_year, block_key, rate_percent, opening_wdv_paise"
    vals = f"'{FIRM}', '{CLIENT}', '2025-26', 'P&M 15%', 15, {wdv}"
    sets = "rate_percent = EXCLUDED.rate_percent, opening_wdv_paise = EXCLUDED.opening_wdv_paise"
    if set_row:
        cols += ", itr_schedule_row"
        vals += ", " + ("NULL" if with_row is None else f"'{with_row}'")
        sets += ", itr_schedule_row = EXCLUDED.itr_schedule_row"
    return _psql(dsn, f"INSERT INTO {TABLE} ({cols}) VALUES ({vals}) "
                      f"ON CONFLICT (firm_id, client_id, financial_year, block_key) DO UPDATE SET {sets};")


def test_an_upsert_carries_the_row_and_an_upsert_that_omits_it_keeps_it(dsn):
    assert _upsert(dsn, "PlantMachinery.Rate15", True, 100).returncode == 0
    assert _upsert(dsn, None, False, 200).returncode == 0                # an older screen: no column named
    assert _rows(dsn, f"SELECT opening_wdv_paise, itr_schedule_row FROM {TABLE}") == [["200", "PlantMachinery.Rate15"]]
    assert _upsert(dsn, None, True, 300).returncode == 0                 # sending null clears it on purpose
    assert _rows(dsn, f"SELECT opening_wdv_paise, coalesce(itr_schedule_row, 'NULL') FROM {TABLE}") == [["300", "NULL"]]


# ── the rollback and the re-apply ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_rollback_drops_the_column_and_its_check_and_a_reapply_brings_them_back(dsn):
    assert _insert(dsn, row="PlantMachinery.Rate15").returncode == 0
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _one(dsn, "SELECT count(*) FROM information_schema.columns WHERE table_name='income_tax_asset_blocks' "
                     "AND column_name='itr_schedule_row'") == "0"
    assert _one(dsn, f"SELECT count(*) FROM pg_constraint WHERE conrelid = '{TABLE}'::regclass AND conname = '{CHECK}'") == "0"
    assert _one(dsn, f"SELECT count(*) FROM {TABLE}") == "1"               # the block itself is untouched
    assert _psql_file(dsn, ROLLBACK).returncode == 0                       # and a second rollback is a no-op
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _rows(dsn, f"SELECT itr_schedule_row IS NULL FROM {TABLE}") == [["t"]]   # the recorded row was lost with the column
    assert _insert(dsn, key="again", row="Building.Rate10", rate=10).returncode == 0


def test_applying_twice_changes_nothing(dsn):
    before = _rows(dsn, "SELECT conname FROM pg_constraint WHERE conrelid = 'public.income_tax_asset_blocks'::regclass ORDER BY 1")
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _rows(dsn, "SELECT conname FROM pg_constraint WHERE conrelid = 'public.income_tax_asset_blocks'::regclass ORDER BY 1") == before
