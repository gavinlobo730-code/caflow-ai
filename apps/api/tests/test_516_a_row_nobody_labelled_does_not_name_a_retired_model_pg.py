"""Migration 516 — a row nobody labelled does not name a model that has been retired (ledger POST-A-165).

Migration 069 gave `ai_messages`, `ai_summaries` and `ai_recommendations` a `model_used` default naming a model Groq retired
for this account on 29-09-2026. The code stamps the real label on every row it writes; the default was left for a writer that
forgets, which would record its row as answered by a model that never saw it.

WHAT IS HELD
    * on a migrated database none of the three columns carries a default, and an insert that omits the label stores NULL;
    * no migration after 516 puts a default back on one of them (a source scan, so it runs without a database);
    * the migration changes metadata only: an existing label is left exactly as it was;
    * it skips a table that does not exist, is idempotent, and its rollback restores the default (the negative control).

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_STEM = "516_a_row_nobody_labelled_does_not_name_a_retired_model"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")
RETIRED = "llama-3.3-70b-versatile"
TABLES = ("ai_messages", "ai_summaries", "ai_recommendations")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the column-default proofs require HARNESS_PG + psql",
)


def test_no_later_migration_puts_the_retired_default_back():
    offenders = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        number = int(path.name[:3])
        if number <= 516 or path.name.endswith("_rollback.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"model_used[^;]*DEFAULT", text, re.I | re.S):
            offenders.append(path.name)
    assert not offenders, offenders


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"modelused_m516_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _defaults(dsn: str) -> dict[str, str]:
    rows = _ok(dsn, """
        SELECT c.relname || '|' || coalesce(pg_get_expr(d.adbin, d.adrelid), '')
          FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
          LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
         WHERE c.relnamespace = 'public'::regnamespace AND c.relname IN ('ai_messages','ai_summaries','ai_recommendations')
           AND a.attname = 'model_used' AND NOT a.attisdropped ORDER BY 1;""").splitlines()
    return dict(r.split("|", 1) for r in rows)


@_NEEDS_PG
def test_no_column_carries_a_default_on_a_migrated_database(db):
    got = _defaults(db)
    if not got:
        pytest.skip("this scratch database has none of the three tables (migration 070/071 stop part-way)")
    assert set(got) <= set(TABLES) and all(v == "" for v in got.values()), got


@_NEEDS_PG
def test_the_rollback_puts_the_retired_default_back_which_is_the_negative_control(db):
    if not _defaults(db):
        pytest.skip("this scratch database has none of the three tables")
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert all(v == f"'{RETIRED}'::text" for v in _defaults(db).values()), _defaults(db)


@_NEEDS_PG
def test_an_existing_label_is_left_alone_and_an_unlabelled_row_stores_null(db):
    tables = _defaults(db)
    if "ai_summaries" not in tables:
        pytest.skip("this scratch database has no ai_summaries")
    # restore the old default, label one row with it, apply the migration, and look at both rows
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    firm = "aaaaaaaa-0000-0000-0000-000000000516"
    _ok(db, f"""
        INSERT INTO firms (id, name, email) VALUES ('{firm}', 'M516 Firm', 'm516@test.in');
        INSERT INTO ai_summaries (id, firm_id, summary_type, title, content, generated_at)
             VALUES ('bbbbbbbb-0000-0000-0000-000000000516', '{firm}', 'compliance', 't', 'c', now());
    """)
    assert _ok(db, "SELECT model_used FROM ai_summaries WHERE id = 'bbbbbbbb-0000-0000-0000-000000000516';") == RETIRED
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    assert _ok(db, "SELECT model_used FROM ai_summaries WHERE id = 'bbbbbbbb-0000-0000-0000-000000000516';") == RETIRED
    _ok(db, f"""
        INSERT INTO ai_summaries (id, firm_id, summary_type, title, content, generated_at)
             VALUES ('cccccccc-0000-0000-0000-000000000516', '{firm}', 'compliance', 't2', 'c2', now());
    """)
    assert _ok(db, "SELECT coalesce(model_used, '<null>') FROM ai_summaries "
                   "WHERE id = 'cccccccc-0000-0000-0000-000000000516';") == "<null>"


@_NEEDS_PG
def test_516_is_idempotent_and_skips_a_table_that_is_not_there(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
        assert r.returncode == 0, r.stderr
    _ok(db, "DROP TABLE IF EXISTS public.ai_recommendations CASCADE;")
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
