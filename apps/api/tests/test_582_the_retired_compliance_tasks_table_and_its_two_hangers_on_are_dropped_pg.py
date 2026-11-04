"""The retired compliance "System B" table, its view and the one foreign key into it are dropped, and only if it is empty
(migration 582, POST-A-322). Real Postgres.

The migration-built database already runs 582, so the "before" state is rebuilt by hand in a throwaway clone (a table, the view over it
and the constraint `filings` had into it) and the migration file is run against that: what it does to an empty table, to a table holding
a row (nothing at all), to a table with a dependent object nobody listed (nothing at all: no CASCADE), and to a database that has none
of it (nothing, and no error).
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
MIGRATION = next(API_ROOT.glob("migrations/582_the_retired_compliance_tasks_table_*[!k].sql"))
ROLLBACK = next(API_ROOT.glob("migrations/582_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="requires HARNESS_PG + psql",
)

FIRM = "f5820000-0000-0000-0000-000000000001"
TASK = "75820000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str | None = None, *, path: Path | None = None, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    args += ["-f", str(path)] if path else ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _present(dsn: str) -> dict[str, bool]:
    """Which of the three objects exist, and whether the `filings` column does."""
    return {
        "table": _val(dsn, "SELECT to_regclass('public.compliance_tasks') IS NOT NULL") == "t",
        "view": _val(dsn, "SELECT to_regclass('public.compliance_entries') IS NOT NULL") == "t",
        "constraint": _val(dsn, "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'filings_compliance_task_id_fkey')") == "t",
        "column": _val(dsn, "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                            "AND table_name = 'filings' AND column_name = 'compliance_task_id')") == "t",
    }


def _rebuild_before(dsn: str, *, with_row: bool = False) -> None:
    """The state production was in before 582: the table, the view over it, and the constraint on `filings`."""
    _ok(dsn, """
        CREATE TABLE public.compliance_tasks (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), firm_id uuid, status text);
        CREATE VIEW public.compliance_entries AS SELECT * FROM public.compliance_tasks;
        ALTER TABLE public.filings ADD CONSTRAINT filings_compliance_task_id_fkey
            FOREIGN KEY (compliance_task_id) REFERENCES public.compliance_tasks(id);""")
    if with_row:
        _ok(dsn, f"INSERT INTO public.compliance_tasks (id, firm_id, status) VALUES ('{TASK}', '{FIRM}', 'open');")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e582_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_database_built_from_the_migrations_has_none_of_the_three_and_keeps_the_column(dsn):
    assert _present(dsn) == {"table": False, "view": False, "constraint": False, "column": True}


def test_an_empty_table_its_view_and_the_one_constraint_are_dropped_and_the_filings_column_stays(dsn):
    _rebuild_before(dsn)
    assert _present(dsn) == {"table": True, "view": True, "constraint": True, "column": True}
    r = _psql(dsn, path=MIGRATION)
    assert r.returncode == 0, r.stderr
    assert _present(dsn) == {"table": False, "view": False, "constraint": False, "column": True}


def test_a_table_holding_a_row_is_refused_in_words_and_nothing_at_all_is_dropped(dsn):
    _rebuild_before(dsn, with_row=True)
    r = _psql(dsn, path=MIGRATION)
    assert r.returncode != 0
    assert "holds 1 row" in r.stderr and "Nothing was dropped" in r.stderr, r.stderr
    assert _present(dsn) == {"table": True, "view": True, "constraint": True, "column": True}
    assert _val(dsn, "SELECT count(*) FROM public.compliance_tasks") == "1"


def test_a_dependent_object_nobody_listed_stops_it_and_the_view_and_constraint_it_had_already_dropped_come_back(dsn):
    """No CASCADE: a view over the table that the migration does not name makes the DROP TABLE fail, and the whole migration is one
    statement block, so the view and the constraint it dropped first are restored with it."""
    _rebuild_before(dsn)
    _ok(dsn, "CREATE VIEW public.some_other_reader AS SELECT id FROM public.compliance_tasks;")
    r = _psql(dsn, path=MIGRATION)
    assert r.returncode != 0
    assert "some_other_reader" in r.stderr or "depend" in r.stderr, r.stderr
    assert _present(dsn) == {"table": True, "view": True, "constraint": True, "column": True}


def test_it_is_safe_on_a_database_that_has_none_of_it_and_safe_to_run_twice(dsn):
    for _ in range(2):
        r = _psql(dsn, path=MIGRATION)
        assert r.returncode == 0, r.stderr
    assert _present(dsn) == {"table": False, "view": False, "constraint": False, "column": True}


def test_the_rollback_runs_and_says_what_it_cannot_undo(dsn):
    r = _psql(dsn, path=ROLLBACK)
    assert r.returncode == 0, r.stderr
    text = ROLLBACK.read_text()
    assert "NOT recreated" in text and "held no row" in text
