"""
Migration 330, proved against real PostgreSQL.

WHAT IS BEING PROVED
    1. source_structure_id is PROVENANCE, not a live link. It records which
       structure produced a revision and nothing more: a structure cannot reach
       back and change one, because editing a template would otherwise silently
       restate every employee on it — months already posted to the general
       ledger included.

    2. ON DELETE SET NULL, and that is the whole point of the choice. Deleting a
       template must not delete somebody's pay history, and it must not be
       blocked by it either. The revision survives with its figures intact and
       simply stops naming a structure that no longer exists.

    3. NULL is a permitted, ordinary state. A revision keyed in by hand did not
       come from a structure, and saying so is the honest answer — most rows
       will read NULL.

NEGATIVE CONTROL
    Make the reference ON DELETE CASCADE and test_deleting_a_structure_keeps_the_pay_history
    fails with the revision gone. Make it NOT NULL and
    test_a_hand_keyed_revision_names_no_structure fails.

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
    reason="salary structure provenance proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000330"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000330"
EMP = "cccccccc-0000-0000-0000-000000000330"
STRUCT = "dddddddd-0000-0000-0000-000000000330"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m330_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "330_a_salary_revision_records_the_structure_that_produced_it.sql" \
            not in pg_template.failed, (
                "migration 330 did not apply — everything below would pass vacuously")
        stmts = [
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F330','f330@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}','{FIRM}','C330','Private Limited','AAACA1234E');",
            f"INSERT INTO payroll_employees (id, firm_id, client_id, name) VALUES "
            f"('{EMP}','{FIRM}','{CLIENT}','Asha');",
            f"INSERT INTO salary_structures (id, firm_id, client_id, name) VALUES "
            f"('{STRUCT}','{FIRM}','{CLIENT}','Junior');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _revision(structure: str | None = STRUCT, basic: int = 2_000_000) -> str:
    src = f"'{structure}'" if structure else "NULL"
    return (f"INSERT INTO payroll_salary_revisions "
            f"(firm_id, client_id, employee_id, effective_from, basic_paise, "
            f" source_structure_id) "
            f"VALUES ('{FIRM}','{CLIENT}','{EMP}','2026-10-01',{basic},{src});")


def test_a_revision_can_name_the_structure_that_produced_it(db):
    assert _psql(db, _revision()).returncode == 0
    assert _psql(db, "SELECT source_structure_id FROM payroll_salary_revisions;",
                 tuples=True).stdout.strip() == STRUCT


def test_a_hand_keyed_revision_names_no_structure(db):
    """Most rows will read NULL: a revision typed in did not come from a
    template, and saying so is the honest answer."""
    assert _psql(db, _revision(structure=None)).returncode == 0
    assert _psql(db, "SELECT source_structure_id IS NULL FROM payroll_salary_revisions;",
                 tuples=True).stdout.strip() == "t"


def test_a_structure_that_does_not_exist_is_refused(db):
    """It is a real reference, not a free-text label — a revision claiming a
    structure nobody can look at would be provenance in name only."""
    r = _psql(db, _revision(structure="eeeeeeee-0000-0000-0000-000000000330"))
    assert r.returncode != 0
    assert "foreign key" in r.stderr.lower()


def test_deleting_a_structure_keeps_the_pay_history(db):
    """ON DELETE SET NULL, and that is the whole point of the choice. Deleting a
    template must not delete somebody's pay history — and must not be blocked by
    it either."""
    assert _psql(db, _revision()).returncode == 0
    r = _psql(db, f"DELETE FROM salary_structures WHERE id = '{STRUCT}';")
    assert r.returncode == 0, r.stderr
    out = _psql(db, "SELECT count(*), max(basic_paise), "
                    "bool_and(source_structure_id IS NULL) "
                    "FROM payroll_salary_revisions;", tuples=True)
    assert out.stdout.strip() == "1|2000000|t"


def test_the_structure_cannot_reach_back_and_change_a_revision(db):
    """There is no trigger and no generated column tying them: editing the
    template leaves every revision it produced exactly as it was, which is why
    a revision is safe to pay from."""
    assert _psql(db, _revision()).returncode == 0
    assert _psql(db, f"UPDATE salary_structures SET basic_percent = 99 "
                     f"WHERE id = '{STRUCT}';").returncode == 0
    assert _psql(db, "SELECT basic_paise FROM payroll_salary_revisions;",
                 tuples=True).stdout.strip() == "2000000"


def test_the_misleading_ctc_comments_are_corrected(db):
    """Migration 054 called the percentages "% of CTC", which cannot be what
    they mean: an Indian CTC includes the employer's PF, itself 12% of basic, so
    basic as a percentage of CTC is circular."""
    r = _psql(db, "SELECT col_description('public.salary_structures'::regclass, "
                  "  (SELECT ordinal_position FROM information_schema.columns "
                  "   WHERE table_name='salary_structures' AND column_name='basic_percent'));",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert "MONTHLY GROSS" in r.stdout
    assert "circular" in r.stdout


def test_special_percent_says_it_is_not_used(db):
    """It cannot be honoured alongside a fixed medical_paise, and a column that
    looks usable and is not is worse than one that says so."""
    r = _psql(db, "SELECT col_description('public.salary_structures'::regclass, "
                  "  (SELECT ordinal_position FROM information_schema.columns "
                  "   WHERE table_name='salary_structures' AND column_name='special_percent'));",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert "NOT USED" in r.stdout
