"""Migration 429 — an engagement's standard checklist item exists once, on real Postgres.

The seed-on-read in routers/year_end_checklist.py races when the dashboard and
the Checklist tab both read a new engagement; the unique key is what makes the
seed's ON CONFLICT DO NOTHING actually mean "somebody else already seeded".

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
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
ENG = "55555555-5555-5555-5555-555555555555"
USER = "66666666-6666-6666-6666-666666666666"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"yecl_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO users (id, firm_id, full_name, email, role)
            VALUES ('{USER}', '{FIRM}', 'U', 'u@t.in', 'Partner');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO year_end_engagements
              (id, firm_id, client_id, financial_year, fy_start, fy_end, status, created_by)
            VALUES ('{ENG}', '{FIRM}', '{CLIENT}', '2025-26',
                    DATE '2025-04-01', DATE '2026-03-31', 'draft', '{USER}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _item(code: str) -> str:
    return (f"INSERT INTO year_end_checklist_items (engagement_id, firm_id, category, item_code, "
            f"item_label, sequence_no) VALUES ('{ENG}', '{FIRM}', 'banking', '{code}', 'x', 1)")


def test_a_second_seed_of_the_same_item_is_refused(db):
    assert _psql(db, _item("BANK_REC")).returncode == 0
    second = _psql(db, _item("BANK_REC"))
    assert second.returncode != 0
    assert "year_end_checklist_items_engagement_item_code_key" in second.stderr


def test_the_seed_s_on_conflict_do_nothing_is_a_quiet_no_op(db):
    assert _psql(db, _item("BANK_REC")).returncode == 0
    again = _psql(db, _item("BANK_REC") + " ON CONFLICT (engagement_id, item_code) DO NOTHING")
    assert again.returncode == 0, again.stderr


def test_different_items_of_one_engagement_coexist(db):
    assert _psql(db, _item("BANK_REC")).returncode == 0
    assert _psql(db, _item("GST_FILED")).returncode == 0
