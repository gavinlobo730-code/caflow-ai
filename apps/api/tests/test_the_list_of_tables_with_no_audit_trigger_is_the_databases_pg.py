"""The list of tables with no audit trigger is the database's (POST-A-167).

`tests/fixtures/tables_without_an_audit_trigger.txt` is what the rule in
`test_a_route_that_writes_a_table_with_no_audit_trigger_records_who_wrote_it.py` walks the routes against; this holds it equal to the tables a
database built from the migrations has no `trg_audit_capture` on, so a table added without the trigger makes the rule ask for its routes.
Skipped without HARNESS_PG and psql (the real-Postgres job runs it).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tables_without_an_audit_trigger.txt"


def audit_less_tables() -> frozenset[str]:
    return frozenset(l.strip() for l in FIXTURE.read_text().splitlines() if l.strip())


_ADMIN = os.environ.get("HARNESS_PG")
pg = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="needs HARNESS_PG and psql")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"auditless_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    try:
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pg
def test_the_fixture_lists_exactly_the_tables_a_migrated_database_has_no_trigger_on(db):
    r = _psql(db, """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r'
           AND NOT EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND t.tgname = 'trg_audit_capture' AND NOT t.tgisinternal)
         ORDER BY 1""")
    assert r.returncode == 0, r.stderr
    real = {l for l in r.stdout.split("\n") if l}
    listed = set(audit_less_tables())
    assert real == listed, (
        f"the database has no audit trigger on {sorted(real - listed)} that the fixture does not list, and the fixture lists "
        f"{sorted(listed - real)} that the database now covers: regenerate tests/fixtures/tables_without_an_audit_trigger.txt")
