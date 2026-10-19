"""The schema guard expects columns on tables that exist, and never on a word from the SQL around them.

WHAT WAS WRONG
    Migration 521 added a column with `ALTER TABLE IF EXISTS public.fixed_deposits ADD COLUMN IF NOT EXISTS ...`.
    core/schema_guard parsed migrations with a pattern that knew `public.` and `ONLY` but not `IF EXISTS`, so it read
    the table as "if" and expected a column `if.maturity_amount_is_estimate` that no database can ever hold. The
    verdict is "schema_drift", /health answers 503, and Render's healthCheckPath is what gates a deploy's cut-over:
    from the merge of 521 every API deploy would have been held back, while the migration itself and the web build
    went live. Nothing in the suite noticed, because every parse test used the three spellings the pattern already
    knew and no test compared what the guard expects with a database the migrations built.

WHAT IS HELD
    * every word PostgreSQL allows between `ALTER TABLE` and the table name is consumed (`IF EXISTS`, `ONLY`, both,
      in either letter case, with the schema or without, over a line break), and the columns land on the real table;
    * a table written with a schema other than `public` is not expected, because the live read is of the public
      schema alone;
    * THE RULE, over the real migration history and not over a list of spellings: every table the guard expects is a
      table some migration creates, or one the exclusion list excuses. A word taken for a table (`if`, `only`,
      `exists`, a schema) is neither, so the next statement shape this parser does not know fails here and not in
      production;
    * migration 521's column is expected on `fixed_deposits`, which is the case that reached production.
    The end-to-end half, a migrated database reading as free of column drift, is
    tests/test_the_migrated_database_has_no_column_drift_pg.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.schema_guard import SUPERSEDED_TABLES, expected_columns_from_migrations

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

_CREATE_TABLE = re.compile(
    r"CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:(?:public|\"public\")\.)?\"?(\w+)\"?",
    re.IGNORECASE,
)


def _parse(tmp_path, sql: str) -> dict:
    (tmp_path / "001_x.sql").write_text(sql)
    return expected_columns_from_migrations(tmp_path)


@pytest.mark.parametrize("head", [
    "ALTER TABLE fixed_deposits",
    "ALTER TABLE public.fixed_deposits",
    "ALTER TABLE ONLY fixed_deposits",
    "ALTER TABLE ONLY public.fixed_deposits",
    "ALTER TABLE IF EXISTS fixed_deposits",
    "ALTER TABLE IF EXISTS public.fixed_deposits",
    "ALTER TABLE IF EXISTS ONLY public.fixed_deposits",
    "alter table if exists public.fixed_deposits",
    "ALTER TABLE   IF   EXISTS\n    public.fixed_deposits",
    "ALTER TABLE IF EXISTS PUBLIC.Fixed_Deposits",
])
def test_every_word_before_the_table_name_is_read_as_a_modifier_and_not_as_the_table(tmp_path, head):
    got = _parse(tmp_path, f"{head}\n    ADD COLUMN IF NOT EXISTS maturity_amount_is_estimate BOOLEAN NOT NULL DEFAULT true;\n")
    assert got == {"fixed_deposits": {"maturity_amount_is_estimate"}}, (head, got)


def test_two_statements_in_one_file_each_land_on_their_own_table(tmp_path):
    got = _parse(tmp_path,
                 "ALTER TABLE IF EXISTS public.a ADD COLUMN IF NOT EXISTS x INT;\n"
                 "ALTER TABLE public.b ADD COLUMN IF NOT EXISTS y INT, ADD COLUMN IF NOT EXISTS z INT;\n")
    assert got == {"a": {"x"}, "b": {"y", "z"}}


@pytest.mark.parametrize("head", ["ALTER TABLE auth.users", "ALTER TABLE IF EXISTS storage.objects"])
def test_a_table_in_another_schema_is_not_expected_in_the_public_one(tmp_path, head):
    assert _parse(tmp_path, f"{head} ADD COLUMN IF NOT EXISTS x INT;\n") == {}


def test_a_statement_with_no_added_column_expects_nothing(tmp_path):
    assert _parse(tmp_path, "ALTER TABLE IF EXISTS public.a DROP COLUMN IF EXISTS x;\n") == {}


def _without_comments(sql: str) -> str:
    """A comment that says "CREATE TABLE IF NOT EXISTS" (migrations 094 and 320 do) would name the table "if"."""
    return re.sub(r"--[^\n]*", " ", re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL))


def _created_tables() -> set[str]:
    out: set[str] = set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name.startswith("_"):
            continue
        out |= {m.lower() for m in _CREATE_TABLE.findall(_without_comments(path.read_text(errors="ignore")))}
    return out


def test_every_table_the_guard_expects_is_one_a_migration_creates_or_the_exclusion_list_excuses():
    expected = expected_columns_from_migrations()
    assert len(expected) > 50, "the parser read almost nothing, so this rule would pass having looked at nothing"
    not_a_table = sorted(set(expected) - _created_tables() - set(SUPERSEDED_TABLES))
    assert not not_a_table, (
        f"the schema guard expects columns on {not_a_table}, which no migration creates. A word of the SQL around a "
        "table name was taken for the table (that is how 'if' reached production), so /health would answer 503 "
        "'schema_drift' for good. Teach core/schema_guard._ALTER_TABLE_BLOCK the statement shape.")


def test_migration_521s_column_is_expected_on_fixed_deposits_and_no_table_is_called_if():
    expected = expected_columns_from_migrations()
    assert "maturity_amount_is_estimate" in expected.get("fixed_deposits", set())
    for word in ("if", "only", "exists", "public"):
        assert word not in expected, f"{word!r} is a word of the SQL, not a table"
