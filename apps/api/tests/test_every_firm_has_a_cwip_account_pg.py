"""Migration 425 — every firm has a Capital Work-in-Progress account, on real Postgres.

Migration 397 seeded the account at code 1504 with `ON CONFLICT DO NOTHING`,
but the chart a firm gets when it onboards through the product
(services/coa_seed_service.STANDARD_COA) has 1504 = Vehicles, so the seed was
skipped for exactly those firms and every CWIP addition then failed to find its
account. 425 picks the lowest FREE code from 1507, per firm.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

_MIGRATION = (pathlib.Path(__file__).resolve().parents[1] / "migrations"
              / "425_every_firm_has_a_capital_work_in_progress_account.sql")

ONBOARDED = "11111111-1111-1111-1111-111111111111"   # STANDARD_COA shape
CROWDED = "33333333-3333-3333-3333-333333333333"      # 1507 already taken too
SERVED = "44444444-4444-4444-4444-444444444444"       # already has one


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


def _account(firm: str, code: str, name: str, subtype: str = "Fixed Asset", key: str = "NULL") -> str:
    return (f"INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, "
            f"account_type, account_subtype, is_active, system_account_key) VALUES "
            f"('{firm}', NULL, '{code}', '{name}', 'Asset', '{subtype}', TRUE, {key});")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"cwip425_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES
              ('{ONBOARDED}', 'Onboarded', 'a@t.in'),
              ('{CROWDED}', 'Crowded', 'b@t.in'),
              ('{SERVED}', 'Served', 'c@t.in');
            {_account(ONBOARDED, '1504', 'Vehicles')}
            {_account(ONBOARDED, '1506', 'Intangible Assets', 'Intangible Asset')}
            {_account(CROWDED, '1504', 'Vehicles')}
            {_account(CROWDED, '1507', 'Leasehold Improvements')}
            {_account(CROWDED, '1508', 'Office Equipment')}
            {_account(SERVED, '1504', 'Capital Work-in-Progress', 'Capital Work-in-Progress', "'cwip'")}
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _apply(dsn: str) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(_MIGRATION)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _cwip(dsn: str, firm: str) -> list[str]:
    return _rows(dsn, f"""SELECT account_code || '|' || account_subtype || '|' ||
                                 coalesce(system_account_key, '-')
                          FROM chart_of_accounts
                          WHERE firm_id = '{firm}' AND account_name ILIKE '%Capital Work-in-Progress%'
                          ORDER BY account_code""")


def test_an_onboarded_firm_gets_the_account_at_the_first_free_code(db):
    assert _cwip(db, ONBOARDED) == []
    _apply(db)
    assert _cwip(db, ONBOARDED) == ["1507|Capital Work-in-Progress|cwip"]


def test_a_firm_whose_1507_is_taken_gets_the_next_free_code(db):
    _apply(db)
    assert _cwip(db, CROWDED) == ["1509|Capital Work-in-Progress|cwip"]


def test_a_firm_that_already_has_one_is_left_alone_and_rerunning_adds_nothing(db):
    _apply(db)
    _apply(db)
    assert _cwip(db, SERVED) == ["1504|Capital Work-in-Progress|cwip"]
    assert _cwip(db, ONBOARDED) == ["1507|Capital Work-in-Progress|cwip"]
