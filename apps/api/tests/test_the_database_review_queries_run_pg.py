"""Every block of the monthly database review is valid against a real Postgres (ops-32).

`scripts/db/monthly_review.sql` is what a person pastes into the Supabase SQL editor once a month to read
the database's size, connections, slow statements and index health. It is only useful if it RUNS: a query
that names a column a Postgres version renamed fails at the moment somebody is trying to find out why the
database is slow, and the conclusion drawn from an error is "nothing to see". So each numbered block is run
here, alone (the editor runs one at a time), on a scratch database that has the ordinary catalogs and
`pg_stat_statements` in an `extensions` schema, which is where Supabase puts it.

TWO THINGS THIS DOES NOT DO, AND SAYS SO
    * It does not check that the numbers mean what the runbook says. `docs/operations/database-monitoring.md`
      does, and is read by a person.
    * Block 4 reads `pg_stat_statements`, whose view cannot be SELECTED from unless the library is preloaded
      at server start — and a CI Postgres service is not started that way. So block 4 is run under EXPLAIN,
      which plans the statement (and so checks every column and the schema) without executing the function.
      Blocks 1-3 and 5-13 are executed for real.

Runs only with HARNESS_PG and psql, like every `_pg` test; the default mock-mode job skips it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

SQL = Path(__file__).resolve().parents[1] / "scripts" / "db" / "monthly_review.sql"
HARNESS_PG = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not HARNESS_PG or shutil.which("psql") is None, reason="real-Postgres harness requires HARNESS_PG + psql")


def _psql(dbname: str, sql: str, *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", f"{HARNESS_PG.strip()} dbname={dbname}", "-c", sql],
        capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"psql failed:\n{proc.stderr}\n--- for ---\n{sql[:600]}")
    return proc


def _blocks() -> dict[int, str]:
    """{number: statement}, split on the `-- [n]` headers, comments inside a block kept (they are documentation)."""
    text = SQL.read_text(encoding="utf-8")
    parts = re.split(r"^-- \[(\d+)\] .*$", text, flags=re.M)
    # parts = [preamble, "1", body1, "2", body2, ...]
    return {int(n): body.strip() for n, body in zip(parts[1::2], parts[2::2])}


@pytest.fixture(scope="module")
def scratch():
    name = "ops32_" + uuid.uuid4().hex[:8]
    _psql("postgres", f'create database "{name}"')
    try:
        # Some ordinary tables, so the statistics views have something to describe, and an index nothing reads.
        _psql(name, """
            create table ledger (id bigserial primary key, amount_paise bigint, note text);
            insert into ledger (amount_paise, note) select g, 'x' from generate_series(1, 2000) g;
            create index ledger_unused_idx on ledger (note);
            create table spare (id int);
            create unique index spare_unique_idx on spare (id);
            analyze;
        """)
        _psql(name, "create schema extensions")
        ext = _psql(name, "create extension pg_stat_statements with schema extensions", check=False)
        yield name, ext.returncode == 0
    finally:
        _psql("postgres", f'drop database if exists "{name}" with (force)', check=False)


def test_the_file_has_the_blocks_the_runbook_names():
    """Vacuity guard: a split that finds nothing would let every test below pass over an empty list."""
    blocks = _blocks()
    assert sorted(blocks) == list(range(1, 14)), sorted(blocks)
    for n, body in blocks.items():
        assert re.search(r"\bselect\b", body, re.I), f"block {n} has no SELECT"


def test_the_file_contains_nothing_that_writes():
    """READ-ONLY is the property that makes it safe to run against production, so it is asserted on the text."""
    code = "\n".join(l for l in SQL.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))
    for verb in ("insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke", "vacuum",
                 "reindex", "pg_terminate_backend", "pg_cancel_backend", "pg_stat_reset"):
        assert not re.search(rf"\b{verb}\b", code, re.I), f"{verb} appears in a review that must be read-only"


@pytest.mark.parametrize("number", list(range(1, 14)))
def test_each_block_runs_on_its_own(scratch, number):
    name, have_extension = scratch
    body = _blocks()[number]
    if number == 4:
        if not have_extension:
            pytest.skip("pg_stat_statements is not installable on this Postgres")
        # Planned, not executed: the view cannot be read unless the library is preloaded at server start.
        _psql(name, "explain " + body.rstrip(";"))
    else:
        _psql(name, body)


def test_the_size_block_sees_the_table_that_was_made(scratch):
    name, _ = scratch
    out = _psql(name, _blocks()[1]).stdout
    assert "ledger" in out


def test_the_index_block_finds_an_index_nothing_reads_and_not_a_primary_key(scratch):
    name, _ = scratch
    _psql(name, "select pg_stat_reset()")                   # the scratch db only; nothing has scanned ledger_unused_idx
    out = _psql(name, _blocks()[8]).stdout
    assert "ledger_unused_idx" in out
    assert "ledger_pkey" not in out, "a primary key enforces something whether or not it is read"
    assert "spare_unique_idx" not in out, "so does a unique index that is not the primary key"


def test_the_connections_block_counts_this_connection(scratch):
    name, _ = scratch
    out = _psql(name, _blocks()[5]).stdout.strip().split("|")
    assert int(out[0]) >= int(out[1]) >= 1, out      # max_connections >= in_use >= the connection asking
