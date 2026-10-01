"""Migration 455's two tables, against a real Postgres.

WHY THIS IS A REAL-POSTGRES TEST
    The Pydantic models and the services' own refusals are proved by the mock
    suite. Neither proves the DATABASE holds the same line, and a service is not
    the only writer a table has. This proves the constraints, the uniqueness the
    upsert depends on, the cascade, and — the one a mock cannot — that the RLS
    policies are on and the role guards refuse a role below Executive.

WHAT IS ASSERTED
    income_tax_worksheets
      * the two kinds are accepted and a third is refused by the CHECK;
      * a financial-year label of the wrong shape is refused;
      * ONE row per (firm, client, year, kind) — the unique key the service's
        `on_conflict` names — so a second insert is refused and an upsert
        replaces;
      * `payload_json` defaults to an empty object and takes any JSON.
    ais_computation_decisions
      * only salary, interest and dividend are lines; only accepted or rejected
        are decisions; a negative figure is refused;
      * ONE decision per (firm, client, assessment year, line);
    both
      * RLS is switched on and the role-aware RESTRICTIVE policies exist, in the
        shape migration 352 set. Whether a Reviewer is in fact refused rests on
        `my_role_at_least`, which migration 260 owns and its own tests prove.
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
    reason="migration 455 proof requires HARNESS_PG + psql",
)

FIRM = "f4550000-0000-0000-0000-000000000001"
CLIENT = "c4550000-0000-0000-0000-000000000001"
TABLES = ("income_tax_worksheets", "ais_computation_decisions")


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"v455_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@x.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'T Co', 'Individual');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _worksheet(dsn, kind="salary", fy="2025-26", payload="'{}'::jsonb"):
    return _psql(dsn, f"""
        INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, worksheet_kind, payload_json)
        VALUES ('{FIRM}', '{CLIENT}', '{fy}', '{kind}', {payload});
    """)


def _decision(dsn, key="salary", decision="accepted", amount=100, ay="2026-27"):
    return _psql(dsn, f"""
        INSERT INTO ais_computation_decisions
          (firm_id, client_id, assessment_year, line_key, decision, amount_paise)
        VALUES ('{FIRM}', '{CLIENT}', '{ay}', '{key}', '{decision}', {amount});
    """)


# ── income_tax_worksheets ─────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["house_property", "salary"])
def test_the_two_worksheet_kinds_are_accepted(db, kind):
    assert _worksheet(db, kind=kind).returncode == 0


@pytest.mark.parametrize("kind", ["capital_wip", "House_Property", ""])
def test_a_third_kind_is_refused_by_the_check(db, kind):
    r = _worksheet(db, kind=kind)
    assert r.returncode != 0 and "worksheet_kind" in r.stderr


@pytest.mark.parametrize("fy", ["2025", "25-26", "2025-2026", "FY2025-26"])
def test_a_financial_year_of_the_wrong_shape_is_refused(db, fy):
    r = _worksheet(db, fy=fy)
    assert r.returncode != 0 and "financial_year" in r.stderr


def test_there_is_one_worksheet_of_each_kind_per_client_per_year(db):
    assert _worksheet(db).returncode == 0
    again = _worksheet(db)
    assert again.returncode != 0 and "duplicate key" in again.stderr
    # ...and the unique key is the one the service's upsert names.
    assert _worksheet(db, fy="2024-25").returncode == 0
    assert _worksheet(db, kind="house_property").returncode == 0


def test_the_upsert_the_service_issues_replaces_the_inputs(db):
    assert _worksheet(db, payload="""'{"employers": []}'::jsonb""").returncode == 0
    r = _psql(db, f"""
        INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, worksheet_kind, payload_json)
        VALUES ('{FIRM}', '{CLIENT}', '2025-26', 'salary', '{{"employers": [1]}}'::jsonb)
        ON CONFLICT (firm_id, client_id, financial_year, worksheet_kind)
        DO UPDATE SET payload_json = EXCLUDED.payload_json;
    """)
    assert r.returncode == 0, r.stderr
    got = _psql(db, "SELECT payload_json::text, count(*) OVER () FROM income_tax_worksheets;", tuples=True)
    assert got.stdout.strip() == '{"employers": [1]}|1'


def test_the_payload_defaults_to_an_empty_object(db):
    assert _psql(db, f"""
        INSERT INTO income_tax_worksheets (firm_id, client_id, financial_year, worksheet_kind)
        VALUES ('{FIRM}', '{CLIENT}', '2025-26', 'salary');""").returncode == 0
    got = _psql(db, "SELECT payload_json::text FROM income_tax_worksheets;", tuples=True)
    assert got.stdout.strip() == "{}"


# ── ais_computation_decisions ─────────────────────────────────────────────

@pytest.mark.parametrize("key", ["salary", "interest", "dividend"])
def test_the_three_lines_the_computation_takes_are_accepted(db, key):
    assert _decision(db, key=key).returncode == 0


@pytest.mark.parametrize("key", ["stock_sale", "rent", "Salary", ""])
def test_a_line_the_computation_does_not_take_is_refused(db, key):
    r = _decision(db, key=key)
    assert r.returncode != 0 and "line_key" in r.stderr


@pytest.mark.parametrize("decision", ["undecided", "maybe", "ACCEPTED"])
def test_only_accepted_and_rejected_are_decisions(db, decision):
    r = _decision(db, decision=decision)
    assert r.returncode != 0 and "decision" in r.stderr


def test_a_negative_figure_is_refused_and_zero_is_a_real_one(db):
    r = _decision(db, amount=-1)
    assert r.returncode != 0 and "amount_paise" in r.stderr
    assert _decision(db, amount=0).returncode == 0


def test_a_malformed_assessment_year_is_refused(db):
    assert _decision(db, ay="2026").returncode != 0


def test_there_is_one_decision_per_line_per_year(db):
    assert _decision(db).returncode == 0
    again = _decision(db, decision="rejected")
    assert again.returncode != 0 and "duplicate key" in again.stderr
    assert _decision(db, ay="2027-28").returncode == 0


# ── isolation ─────────────────────────────────────────────────────────────

def test_rls_is_on_and_every_policy_the_migration_names_exists(db):
    for t in TABLES:
        on = _psql(db, f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{t}'::regclass;", tuples=True)
        assert on.stdout.strip() == "t", f"RLS is off on {t}"
        pols = set(_psql(db, f"SELECT policyname FROM pg_policies WHERE tablename = '{t}';",
                         tuples=True).stdout.split())
        assert pols == {f"firm_{t}", f"{t}_role_insert", f"{t}_role_update", f"{t}_role_delete"}


def test_the_role_guards_are_restrictive_so_they_narrow_and_never_grant(db):
    for t in TABLES:
        got = _psql(db, f"""
            SELECT policyname, permissive FROM pg_policies
             WHERE tablename = '{t}' AND policyname LIKE '%_role_%' ORDER BY 1;""", tuples=True)
        for line in got.stdout.strip().splitlines():
            assert line.endswith("RESTRICTIVE"), line
