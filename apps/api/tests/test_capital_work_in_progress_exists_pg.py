"""Migration 397 — capital work-in-progress, on real PostgreSQL (FA-11a).

WHY THIS NEEDS A REAL DATABASE. Four of the design decisions are constraints
rather than code, and none is observable in mock mode where the in-memory
double accepts anything:

  * the CHECK that a capitalised project carries its date and a live one does
    not — the note and the register would otherwise disagree about the same
    project;
  * the NULLABILITY of the two approval columns, which is what makes "overdue"
    and "over budget" refusable rather than defaulted;
  * `amount_paise > 0` on a tranche, because a zero-cost addition would sit in
    an ageing band saying nothing;
  * the seeded Capital Work-in-Progress account and, more to the point, its
    SUBTYPE — `schedule_iii.classify` buckets on it, so a wrong one presents an
    asset under construction as one in use.

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


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"cwip_{uuid.uuid4().hex[:12]}"
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


def _project(dsn, **cols):
    base = {"firm_id": f"'{FIRM}'", "client_id": f"'{CLIENT}'",
            "project_name": "'New factory'", "started_on": "DATE '2024-04-01'"}
    base.update(cols)
    return _psql(dsn, "INSERT INTO capital_work_in_progress (" + ", ".join(base)
                 + ") VALUES (" + ", ".join(base.values()) + ");")


def _one(dsn) -> str:
    assert _project(dsn).returncode == 0
    return _rows(dsn, "SELECT id FROM capital_work_in_progress LIMIT 1;")[0]


def _cost(dsn, cwip_id, **cols):
    base = {"firm_id": f"'{FIRM}'", "client_id": f"'{CLIENT}'",
            "cwip_id": f"'{cwip_id}'", "incurred_on": "DATE '2025-06-01'",
            "description": "'Contractor bill'", "amount_paise": "1000000"}
    base.update(cols)
    return _psql(dsn, "INSERT INTO cwip_additions (" + ", ".join(base)
                 + ") VALUES (" + ", ".join(base.values()) + ");")


# ── the project ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["in_progress", "suspended", "abandoned"])
def test_every_live_status_is_accepted(db, status):
    assert _project(db, status=f"'{status}'").returncode == 0


def test_an_unknown_status_is_refused(db):
    assert _project(db, status="'half_done'").returncode != 0


def test_a_capitalised_project_must_carry_its_date(db):
    """Otherwise the ageing note still sees it as work-in-progress while the
    register already holds the asset, and the two disagree about one project."""
    assert _project(db, status="'capitalised'").returncode != 0
    assert _project(db, status="'capitalised'",
                    capitalised_on="DATE '2026-01-15'").returncode == 0


def test_a_live_project_must_NOT_carry_a_capitalisation_date(db):
    assert _project(db, capitalised_on="DATE '2026-01-15'").returncode != 0


def test_the_two_approval_columns_are_nullable_with_no_default(db):
    """THE REFUSAL DEPENDS ON THIS. Schedule III's completion schedule measures
    overdue and over-budget against the ORIGINAL approval; a default would make
    every project either permanently overdue or permanently on budget, and the
    engine would have nothing to name as undeterminable."""
    assert _project(db).returncode == 0
    got = _rows(db, "SELECT coalesce(approved_completion_date::text, 'NULL'), "
                    "coalesce(approved_cost_paise::text, 'NULL') "
                    "FROM capital_work_in_progress;")
    assert got == ["NULL|NULL"]
    defaults = _rows(db, """
        SELECT column_name, coalesce(column_default, 'NONE')
          FROM information_schema.columns
         WHERE table_name = 'capital_work_in_progress'
           AND column_name IN ('approved_completion_date', 'approved_cost_paise');
    """)
    assert sorted(defaults) == ["approved_completion_date|NONE",
                                "approved_cost_paise|NONE"]


def test_an_approved_cost_of_nothing_is_refused(db):
    """Zero is not an approval; it is an approval of nothing, which would make
    every project instantly over budget."""
    assert _project(db, approved_cost_paise="0").returncode != 0


def test_a_project_code_is_unique_per_client(db):
    assert _project(db, project_code="'CWIP-1'").returncode == 0
    assert _project(db, project_code="'CWIP-1'").returncode != 0


# ── the tranches ────────────────────────────────────────────────────────────

def test_a_cost_of_nothing_is_refused(db):
    cwip_id = _one(db)
    assert _cost(db, cwip_id, amount_paise="0").returncode != 0
    assert _cost(db, cwip_id, amount_paise="-1").returncode != 0
    assert _cost(db, cwip_id).returncode == 0


def test_a_tranche_must_say_when_it_was_incurred(db):
    """The column the whole ageing schedule is built on."""
    cwip_id = _one(db)
    assert _cost(db, cwip_id, incurred_on="NULL").returncode != 0


def test_deleting_a_project_takes_its_costs_with_it(db):
    cwip_id = _one(db)
    assert _cost(db, cwip_id).returncode == 0
    assert _psql(db, f"DELETE FROM capital_work_in_progress WHERE id = '{cwip_id}';").returncode == 0
    assert _rows(db, "SELECT count(*) FROM cwip_additions;") == ["0"]


# ── the account ─────────────────────────────────────────────────────────────

def test_the_seed_reaches_a_firm_that_had_a_chart_when_the_migration_RAN(db):
    """The seed is per firm and selects from the charts that existed.

    THE THROWAWAY DATABASE HAS NO FIRM AT MIGRATION TIME, so nothing is seeded
    here — which is not a defect in the test, it is the real behaviour and the
    reason `cwip_service.NOT_POSTED` exists: a firm created afterwards has no
    Capital Work-in-Progress account, `_find_account` raises, and the addition
    is recorded with a gap saying the balance sheet does not yet include it
    rather than reported as posted. Migration 389's Customs Duty account has
    exactly the same shape.

    What IS asserted is the INSERT itself, replayed against a firm that now has
    a chart — because that is what the migration does for every firm that had
    one, and a mistake in it (a colliding code, a wrong subtype) would be
    invisible in a database where the SELECT found nothing to begin with.
    """
    assert _psql(db, f"""
        INSERT INTO chart_of_accounts (firm_id, client_id, account_code,
                                       account_name, account_type,
                                       account_subtype, is_active)
        VALUES ('{FIRM}', NULL, '1501', 'Office Equipment', 'Asset',
                'Fixed Asset', TRUE),
               ('{FIRM}', NULL, '1502', 'Computers & Laptops', 'Asset',
                'Fixed Asset', TRUE),
               ('{FIRM}', NULL, '1503', 'Furniture & Fixtures', 'Asset',
                'Fixed Asset', TRUE);
    """).returncode == 0

    replay = _psql(db, """
        INSERT INTO public.chart_of_accounts
          (firm_id, client_id, account_code, account_name, account_type,
           account_subtype, is_active, system_account_key)
        SELECT DISTINCT c.firm_id, NULL::uuid, '1504', 'Capital Work-in-Progress',
               'Asset', 'Capital Work-in-Progress', TRUE, 'cwip'
        FROM public.chart_of_accounts c
        WHERE c.client_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM public.chart_of_accounts r
            WHERE r.firm_id = c.firm_id AND r.client_id IS NULL
              AND (r.system_account_key = 'cwip'
                   OR r.account_name ILIKE 'Capital Work-in-Progress'))
        ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;
    """)
    assert replay.returncode == 0, replay.stderr

    # 1504 BECAUSE 1501-1503 ARE TAKEN (migration 011). `ON CONFLICT DO
    # NOTHING` would have skipped a colliding insert silently — an account
    # nobody could find rather than an error anybody would see, which is
    # migration 389's recorded lesson.
    got = _rows(db, """
        SELECT account_code, account_name, account_type, account_subtype
          FROM chart_of_accounts WHERE system_account_key = 'cwip';
    """)
    assert got == ["1504|Capital Work-in-Progress|Asset|Capital Work-in-Progress"]


def test_the_seeded_subtype_is_the_one_the_classifier_reads(db):
    """THE SUBTYPE IS LOAD-BEARING. `schedule_iii.bs_bucket` buckets on it, and
    'Fixed Asset' here would fold the balance into Tangible Fixed Assets and
    undo the presentation this whole migration exists for."""
    from domain.reporting.schedule_iii import bs_bucket
    assert bs_bucket("Asset", "Capital Work-in-Progress") == "Capital Work-in-Progress"


# ── the guards ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["capital_work_in_progress", "cwip_additions"])
def test_row_level_security_is_on_and_both_policies_exist(db, table):
    assert _rows(db, f"SELECT relrowsecurity FROM pg_class "
                     f"WHERE relname = '{table}';") == ["t"]
    kinds = _rows(db, f"""
        SELECT polname, polpermissive FROM pg_policy
         WHERE polrelid = '{table}'::regclass ORDER BY polname;
    """)
    # One PERMISSIVE firm policy and one RESTRICTIVE assignment-scope policy.
    # Migration 084's DO loop has never re-run, so a table added since is
    # firm-wide unless its own migration declares the second (CLAUDE.md).
    assert any(k.endswith("|t") for k in kinds), kinds
    assert any(k.endswith("|f") for k in kinds), kinds
