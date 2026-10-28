"""The twelve return-workpaper and stock-count tables grant no write to a signed-in role and every write to the service role (POST-A-323).

This is the premise of `test_the_return_workpaper_tables_are_written_with_the_privileged_client_only.py`: the writers have to be on the
privileged client BECAUSE the database will not let the caller's own session write these tables. It was read from production on
28-10-2026 (no INSERT, UPDATE or DELETE for `authenticated` at table or column level on any of the twelve, all twelve empty) and is
held here against the migration-built database, so a future migration that grants a write back, or a thirteenth table built the same
way without its REVOKE, is noticed where the privilege is defined. A real-Postgres test is the only place this can be seen: the
in-memory double accepts any caller.

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_ADMIN = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(not _ADMIN or not shutil.which("psql"), reason="needs HARNESS_PG and psql on PATH")

TABLES = (
    "gstr4_annual_b2b_supplies", "gstr4_annual_b2b_rc_supplies", "gstr4_annual_urp_supplies", "gstr4_annual_import_of_services",
    "gstr9c_reconciliations", "gstr9c_rate_wise_lines", "gstr9c_expense_lines",
    "ecommerce_operator_supplies", "ecommerce_operator_unregistered_supplies",
    "rcm_documents", "stock_count_sessions", "stock_count_lines",
)
SIGNED_IN = ("authenticated", "anon")


def _rows(pg_template, sql: str) -> list[str]:
    dsn = f"{_ADMIN.strip()} dbname={pg_template.name}"
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


def _quoted(items) -> str:
    return ", ".join("'%s'" % i for i in items)


def test_every_table_exists_in_the_migration_built_database(pg_template):
    found = _rows(pg_template, f"select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                               f"where n.nspname = 'public' and c.relkind = 'r' and relname in ({_quoted(TABLES)})")
    assert sorted(found) == sorted(TABLES), set(TABLES) - set(found)


def test_no_signed_in_role_holds_a_write_on_any_of_them_at_table_or_column_level(pg_template):
    held = _rows(pg_template, f"""
        select r.rolname || ' ' || c.relname || ' ' || v.verb
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        cross join pg_roles r
        cross join (values ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) v(verb)
        where n.nspname = 'public' and c.relname in ({_quoted(TABLES)}) and r.rolname in ({_quoted(SIGNED_IN)})
          and (has_table_privilege(r.rolname, c.oid, v.verb)
               or (v.verb in ('INSERT', 'UPDATE') and has_any_column_privilege(r.rolname, c.oid, v.verb)))
        order by 1""")
    assert held == [], f"a signed-in role can write these directly, so the writers' choice of client no longer decides who may: {held}"


def test_the_service_role_keeps_every_write_the_api_makes(pg_template):
    missing = _rows(pg_template, f"""
        select c.relname || ' ' || v.verb
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        cross join (values ('INSERT'), ('UPDATE')) v(verb)
        where n.nspname = 'public' and c.relname in ({_quoted(TABLES)})
          and not has_table_privilege('service_role', c.oid, v.verb)
        order by 1""")
    assert missing == [], f"the privileged client could not write: {missing}"


def test_row_security_is_on_for_all_twelve(pg_template):
    off = _rows(pg_template, f"select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                             f"where n.nspname = 'public' and relname in ({_quoted(TABLES)}) and not relrowsecurity")
    assert off == [], off
