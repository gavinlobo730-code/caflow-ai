"""A migration that fails on its third statement leaves no partial effect, in a real Postgres (ops-16).

tests/test_the_migration_runner_is_atomic_and_remembers.py proves how the runner CALLS psql against a
stand-in. This is the half that needs a server: that the database really rolls the file back, that the
tracking row goes with it, that a file carrying its own BEGIN/COMMIT or a CREATE INDEX CONCURRENTLY still
applies (a second wrapper would break the first and a transaction block forbids the second), and that a second
run over the same broken file exits non-zero without retrying it.

It builds its own migration set in a temporary directory (`--migrations-dir`) and its own empty database, so it
neither depends on nor disturbs the real set. Skipped without HARNESS_PG and psql, like every *_pg.py.

NOT RUN WHERE IT WAS WRITTEN: the environment had no Postgres. The SQL below is plain and was read twice; the
CI `migrations` job, which sets HARNESS_PG, is its first real execution.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the atomicity proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql],
                          capture_output=True, text=True)


@pytest.fixture()
def db():
    admin = _ADMIN.strip()
    name = f"atomic_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}";').returncode != 0:
        pytest.skip("could not create a database")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _run(dsn: str, directory: Path, *flags: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dsn", dsn, "--migrations-dir", str(directory), "--json", *flags],
        capture_output=True, text=True, cwd=str(API_ROOT))
    return proc.returncode, json.loads(proc.stdout)


def _one(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _write(directory: Path, name: str, text: str) -> None:
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(text)


THIRD_STATEMENT_FAILS = (
    "CREATE TABLE ops16_probe (id int);\n"
    "INSERT INTO ops16_probe VALUES (1);\n"
    "INSERT INTO ops16_no_such_table VALUES (1);\n"
)


def test_a_file_that_fails_on_its_third_statement_leaves_no_partial_effect(db, tmp_path):
    _write(tmp_path, "900_probe.sql", THIRD_STATEMENT_FAILS)
    code, report = _run(db, tmp_path)

    assert code == 1 and [f["file"] for f in report["failed"]] == ["900_probe.sql"]
    assert _one(db, "SELECT to_regclass('public.ops16_probe') IS NULL") == "t", (
        "the first two statements were committed: the file is not atomic")
    assert _one(db, "SELECT count(*) FROM schema_migrations WHERE filename = '900_probe.sql'") == "0"
    assert _one(db, "SELECT attempts FROM schema_migration_failures WHERE filename = '900_probe.sql'") == "1"


def test_a_second_run_over_the_same_broken_file_exits_non_zero_without_retrying(db, tmp_path):
    _write(tmp_path, "900_probe.sql", THIRD_STATEMENT_FAILS)
    _run(db, tmp_path)
    code, report = _run(db, tmp_path)

    assert code == 1, "a remembered failure must keep the pipeline red"
    assert report["failed"] == [] and report["unresolved_failures"] == ["900_probe.sql"]
    assert report["ok"] is False
    assert _one(db, "SELECT attempts FROM schema_migration_failures WHERE filename = '900_probe.sql'") == "1", (
        "a failure that is remembered is not retried")


def test_fixing_the_file_applies_it_and_turns_the_pipeline_green(db, tmp_path):
    _write(tmp_path, "900_probe.sql", THIRD_STATEMENT_FAILS)
    _run(db, tmp_path)
    _write(tmp_path, "900_probe.sql", "CREATE TABLE ops16_probe (id int);\nINSERT INTO ops16_probe VALUES (1);\n")
    code, report = _run(db, tmp_path)

    assert code == 0 and report["applied"] == ["900_probe.sql"] and report["ok"] is True
    assert _one(db, "SELECT count(*) FROM ops16_probe") == "1"
    assert _one(db, "SELECT count(*) FROM schema_migration_failures") == "0"


def test_a_file_with_its_own_begin_and_commit_applies_and_is_not_wrapped_twice(db, tmp_path):
    _write(tmp_path, "900_own.sql", "BEGIN;\nCREATE TABLE ops16_own (id int);\nCOMMIT;\n")
    code, report = _run(db, tmp_path)

    assert code == 0 and report["applied"] == ["900_own.sql"]
    assert "own transaction" in report["not_atomic"]["900_own.sql"]
    assert _one(db, "SELECT to_regclass('public.ops16_own') IS NOT NULL") == "t"
    assert _one(db, "SELECT count(*) FROM schema_migrations WHERE filename = '900_own.sql'") == "1"


def test_a_failure_inside_a_files_own_transaction_still_rolls_it_back(db, tmp_path):
    _write(tmp_path, "900_own.sql",
           "BEGIN;\nCREATE TABLE ops16_own (id int);\nINSERT INTO ops16_no_such_table VALUES (1);\nCOMMIT;\n")
    code, _ = _run(db, tmp_path)

    assert code == 1
    assert _one(db, "SELECT to_regclass('public.ops16_own') IS NULL") == "t"


def test_create_index_concurrently_applies_because_it_is_not_wrapped(db, tmp_path):
    """A transaction block forbids it, so a runner that wrapped every file would fail the first migration that
    needs it. The scanner sees the keyword and leaves the file alone."""
    _write(tmp_path, "900_index.sql",
           "CREATE TABLE ops16_c (id int);\nCREATE INDEX CONCURRENTLY ops16_c_i ON ops16_c (id);\n")
    code, report = _run(db, tmp_path)

    assert code == 0 and "CONCURRENTLY" in report["not_atomic"]["900_index.sql"]
    assert _one(db, "SELECT to_regclass('public.ops16_c_i') IS NOT NULL") == "t"


def test_a_marked_file_runs_without_a_wrapper(db, tmp_path):
    _write(tmp_path, "900_marked.sql", "-- migration: no-transaction - exercised by the test\nCREATE TABLE ops16_m (id int);\n")
    code, report = _run(db, tmp_path)

    assert code == 0 and "no-transaction" in report["not_atomic"]["900_marked.sql"]


def test_the_tracking_row_is_part_of_the_transaction(db, tmp_path):
    """The statement that records a migration as applied is inside the same transaction as the migration, so a
    migration cannot be applied with its row missing (it would run again next time) or recorded without having
    applied. Proved the first way round: a file whose LAST statement fails records nothing."""
    _write(tmp_path, "900_last.sql", "CREATE TABLE ops16_l (id int);\nSELECT 1/0;\n")
    code, _ = _run(db, tmp_path)

    assert code == 1
    assert _one(db, "SELECT to_regclass('public.ops16_l') IS NULL") == "t"
    assert _one(db, "SELECT count(*) FROM schema_migrations WHERE filename = '900_last.sql'") == "0"
