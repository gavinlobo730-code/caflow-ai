"""Every table on the list of tables the signed-in role cannot write is one in the migration-built database (POST-A-354).

`test_a_write_of_a_table_the_signed_in_role_cannot_write_is_made_on_a_client_that_can.py` holds every writer of those tables to a client
that can write them, on the premise that the signed-in database roles (`authenticated` and `anon`) hold no INSERT, UPDATE or DELETE on
them. The list was read from production on 28-10-2026. This file holds the premise where the privilege is defined: each name on the
list that exists in a database built from the migrations is checked against the privileges themselves, at table level and at column
level, so a later migration that grants a write back to a signed-in role (and so makes the list wrong) fails here and says which table.

A table on the list that the migrations do not create is reported in the failure message of the third test and is not a failure: it
exists only in production (a backup table, a platform table), and the rule over the source cannot write it either.

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ADMIN = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(not _ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

LIST_FILE = Path(__file__).resolve().parent / "fixtures" / "tables_the_signed_in_role_cannot_write.txt"
CLOSED = [ln.strip() for ln in LIST_FILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
SIGNED_IN = ("authenticated", "anon")

def _rows(pg_template, sql: str) -> list[str]:
    dsn = f"{_ADMIN.strip()} dbname={pg_template.name}"
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


def _quoted(items) -> str:
    return ", ".join("'%s'" % i for i in items)


def test_no_listed_table_can_be_written_by_a_signed_in_role_at_table_or_column_level(pg_template):
    # Every listed table, with no exception list: `hsn_master` and `tds_section_limits` were the two production closed and the migrations
    # did not, and migration 558 closed them (POST-A-355). A table closed only by a statement no migration carries fails here by name.
    held = _held(pg_template, CLOSED)
    assert held == [], ("a signed-in role can write these tables directly, so the list is wrong and the writers' choice of client no "
                        f"longer decides who may write them: {held}")


def _held(pg_template, tables: list[str]) -> list[str]:
    return _rows(pg_template, f"""
        select r.rolname || ' ' || c.relname || ' ' || v.verb
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        cross join pg_roles r
        cross join (values ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) v(verb)
        where n.nspname = 'public' and c.relkind = 'r' and c.relname in ({_quoted(tables)}) and r.rolname in ({_quoted(SIGNED_IN)})
          and (has_table_privilege(r.rolname, c.oid, v.verb)
               or (v.verb in ('INSERT', 'UPDATE') and has_any_column_privilege(r.rolname, c.oid, v.verb)))
        order by 1""")


def test_the_two_reference_tables_production_closed_are_on_the_list_and_closed_by_a_migration(pg_template):
    assert {"hsn_master", "tds_section_limits"} <= set(CLOSED), "the list lost a table migration 558 closes"
    assert _held(pg_template, ["hsn_master", "tds_section_limits"]) == []


def test_the_list_is_mostly_tables_the_migrations_create(pg_template):
    present = set(_rows(pg_template, f"select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                                     f"where n.nspname = 'public' and c.relkind = 'r' and c.relname in ({_quoted(CLOSED)})"))
    assert len(present) >= 140, f"only {len(present)} of {len(CLOSED)} listed tables exist in the migration-built database"


def test_the_names_on_the_list_that_only_production_has(pg_template):
    present = set(_rows(pg_template, f"select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                                     f"where n.nspname = 'public' and c.relkind = 'r' and c.relname in ({_quoted(CLOSED)})"))
    only_production = sorted(set(CLOSED) - present)
    assert len(only_production) <= 12, f"{len(only_production)} listed tables are not built by the migrations: {only_production}"
