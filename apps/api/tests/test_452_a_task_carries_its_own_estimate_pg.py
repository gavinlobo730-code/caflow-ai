"""Migration 452 on real PostgreSQL — a task carries its own estimate of how long
it takes (practice_management-24).

WHAT IS PROVEN HERE
    * `tasks.estimated_minutes` exists, is NULLABLE with NO DEFAULT (NULL is
      "nobody estimated this" — never 0) and no existing row was given a figure;
    * it accepts a positive whole number of minutes, refuses 0 and a negative —
      which is also what stops a browser that writes `tasks` straight over
      PostgREST from storing a 0 the API would have refused;
    * a signed-in browser session can still create a task WITHOUT it (the column
      rides on `tasks`' own RLS and adds no required field), and can read it back;
    * the file applies twice and its rollback removes the column and the CHECK.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test; it
cannot run in the mock-mode job.
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

FIRM = "52000000-0000-0000-0000-0000000000f1"
CLIENT = "52000000-0000-0000-0000-0000000000c1"
PARTNER_ID = "52000000-0000-0000-0000-00000000b001"
PARTNER_AUTH = "52000000-0000-0000-0000-00000000a001"

_MIGRATIONS = os.path.join(os.path.dirname(__file__), "..", "migrations")
_FILE = os.path.join(_MIGRATIONS, "452_a_task_carries_its_own_estimate_of_how_long_it_takes.sql")
_ROLLBACK = os.path.join(_MIGRATIONS, "452_a_task_carries_its_own_estimate_of_how_long_it_takes_rollback.sql")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _file(dsn: str, path: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", path],
                          capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m452_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'p@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
              VALUES ('{PARTNER_ID}', '{FIRM}', '{PARTNER_AUTH}', 'p@t.in', 'Partner', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
              VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _task(extra_cols: str = "", extra_vals: str = "") -> str:
    return (f"INSERT INTO tasks (firm_id, client_id, title{extra_cols}) "
            f"VALUES ('{FIRM}', '{CLIENT}', 'T'{extra_vals}) RETURNING id;")


def test_the_column_is_nullable_with_no_default(db):
    row = _scalar(db, "SELECT is_nullable || '|' || coalesce(column_default, 'none') "
                      "FROM information_schema.columns WHERE table_schema='public' "
                      "AND table_name='tasks' AND column_name='estimated_minutes'")
    assert row == "YES|none", f"NULL is 'nobody estimated this', which is not 0. Got {row!r}"


def test_a_task_made_without_an_estimate_has_none(db):
    assert _psql(db, _task()).returncode == 0
    assert _scalar(db, "SELECT count(*) FROM tasks WHERE estimated_minutes IS NOT NULL") == "0"


@pytest.mark.parametrize("minutes", [1, 90, 180, 14400])
def test_a_positive_whole_number_of_minutes_is_stored(db, minutes):
    assert _psql(db, _task(", estimated_minutes", f", {minutes}")).returncode == 0
    assert _scalar(db, "SELECT estimated_minutes FROM tasks") == str(minutes)


@pytest.mark.parametrize("bad", [0, -1, -180])
def test_zero_and_a_negative_are_refused(db, bad):
    """There is no estimate of nothing, and a 0 in this column would make a firm's
    work look free in the forecast that exists to say it is not."""
    r = _psql(db, _task(", estimated_minutes", f", {bad}"))
    assert r.returncode != 0 and "tasks_estimated_minutes_check" in r.stderr


def test_the_estimate_cannot_be_zeroed_by_an_update_either(db):
    assert _psql(db, _task(", estimated_minutes", ", 60")).returncode == 0
    r = _psql(db, "UPDATE tasks SET estimated_minutes = 0;")
    assert r.returncode != 0 and "tasks_estimated_minutes_check" in r.stderr
    assert _psql(db, "UPDATE tasks SET estimated_minutes = NULL;").returncode == 0, "it can be taken off"


def test_a_signed_in_session_can_create_a_task_without_it_and_read_it_back(db):
    """No required field was added: the browser's own `createTask` insert, which
    names no estimate, still works under the caller's RLS."""
    r = _psql(db, f"SET request.jwt.claims = '{{\"sub\": \"{PARTNER_AUTH}\"}}'; SET ROLE authenticated; "
                  f"INSERT INTO tasks (firm_id, client_id, title) VALUES ('{FIRM}', '{CLIENT}', 'browser');")
    assert r.returncode == 0, r.stderr
    seen = _scalar(db, f"SET request.jwt.claims = '{{\"sub\": \"{PARTNER_AUTH}\"}}'; SET ROLE authenticated; "
                       f"SELECT count(*) FROM tasks WHERE title = 'browser' AND estimated_minutes IS NULL")
    assert seen == "1"


def test_the_migration_applies_twice(db):
    assert _file(db, _FILE).returncode == 0
    assert _file(db, _FILE).returncode == 0


def test_the_rollback_removes_the_column_and_its_check(db):
    r = _file(db, _ROLLBACK)
    assert r.returncode == 0, r.stderr
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='tasks' "
                       "AND column_name='estimated_minutes'") == "0"
    assert _scalar(db, "SELECT count(*) FROM pg_constraint WHERE conname='tasks_estimated_minutes_check'") == "0"
    assert _file(db, _FILE).returncode == 0, "and it can be re-applied after a rollback"
