"""Migration 774, against a real Postgres: a person's guided-tips columns exist as the API expects, and a signed-in session cannot write them
(POST-A-531).

WHY A DATABASE TEST. The API writes `users.guided_tips_on` and `users.guided_tips_seen` with its privileged client and names the person and the
firm on every query (`tests/test_a_person_keeps_their_guided_tips.py` holds that half). The other half is a fact about grants: a signed-in
session reaches `users` straight over PostgREST, where it may write its own NAME and nothing else, and a column added later takes no grant by
itself. That is true only while nobody grants UPDATE on the table as a whole, so it is asserted here and not assumed: a tip marked "closed"
from a hand-made request would be harmless, but a column on `users` that a browser can write is a habit this product does not start.

WHAT IS ASSERTED, in a migration-built database
    * `guided_tips_on` is a nullable boolean with no default (NULL = never chosen), `guided_tips_seen` is a NOT NULL text[] defaulting to
      the empty list, so a row that existed before the migration reads as "never chosen, nothing closed";
    * neither `authenticated` nor `anon` holds UPDATE or INSERT on either column.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_ADMIN = os.environ.get("HARNESS_PG")
pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

COLUMNS = ("guided_tips_on", "guided_tips_seen")


def _ask(pg_template, sql: str) -> str:
    dsn = f"{_ADMIN.strip()} dbname={pg_template.name}"
    done = subprocess.run(["psql", dsn, "-X", "-q", "-tA", "-c", sql], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_two_columns_are_the_shape_the_api_reads(pg_template):
    rows = _ask(pg_template, (
        "select column_name || '|' || data_type || '|' || udt_name || '|' || is_nullable || '|' || coalesce(column_default, '') "
        "from information_schema.columns where table_schema = 'public' and table_name = 'users' "
        "and column_name in ('guided_tips_on', 'guided_tips_seen') order by column_name;")).splitlines()
    assert rows == [
        "guided_tips_on|boolean|bool|YES|",
        "guided_tips_seen|ARRAY|_text|NO|'{}'::text[]",
    ], rows


@pytest.mark.parametrize("role", ["authenticated", "anon"])
@pytest.mark.parametrize("column", COLUMNS)
@pytest.mark.parametrize("privilege", ["UPDATE", "INSERT"])
def test_a_signed_in_session_cannot_write_either_column(pg_template, role, column, privilege):
    answer = _ask(pg_template, f"select has_column_privilege('{role}', 'public.users', '{column}', '{privilege}')::text;")
    assert answer == "false", (
        f"{role} holds {privilege} on users.{column}: a browser could set a person's guided-tips preference without the API "
        "(migration 774 says these columns are written by the server only)")
