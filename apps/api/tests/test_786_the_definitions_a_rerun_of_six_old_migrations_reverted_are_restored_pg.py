"""Migration 786, proved against real PostgreSQL: a second run of six old migrations undoes later definitions, and 786 puts every
one of them back (ledger POST-A-583).

WHAT HAPPENED
    On 27-11-2026 the comments of eight applied migrations were edited by a rename sweep. The runner runs a file again when its
    checksum changes, so the next push to main ran 245, 269, 274, 306, 318 and 440 a second time on production (442 and 443
    failed). Read on production the next morning, read-only: `post_journal_atomic` was migration 274's body again and a signed-in
    session could execute it, `my_portal_client_ids()` was migration 440's, and the four `portal_messages_assignment_scope`
    policies called `can_access_client` once per row again.

WHAT THIS HOLDS
    * THE INCIDENT, REPRODUCED: on a database built from the migrations, the six files run again change exactly those seven
      things and nothing else. "Nothing else" is a comparison of every function (body, security, settings and who may execute it),
      every policy, every table and sequence privilege of the anonymous, signed-in and service roles and of PUBLIC, every
      constraint, column default, trigger and default privilege in the schema. The bodies it finds are the ones production had
      (the same md5), which is what ties this test to what was read there.
    * THE REPAIR: 786 run after them leaves that whole comparison identical to the database before the second run, and says in a
      warning the runner keeps how many policies it rewrote (four).
    * ON A DATABASE NOBODY DAMAGED, 786 CHANGES NOTHING, and it can run twice.
    * WHAT THE DAMAGE MEANT, AND THAT IT IS OVER: after the second run a signed-in role may execute the posting function and the
      function no longer asks who is calling; after 786 it may not, and it does.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

F786 = MIGRATIONS / "786_the_definitions_a_rerun_of_six_old_migrations_reverted_are_restored.sql"
R786 = MIGRATIONS / "786_the_definitions_a_rerun_of_six_old_migrations_reverted_are_restored_rollback.sql"

#: The six that ran a second time on production on 27-11-2026, in the order the runner took them.
RAN_AGAIN = (
    "245_fix_194_grant_regression.sql",
    "269_service_role_grant_gap.sql",
    "274_reversal_stamps_its_original_atomically.sql",
    "306_service_role_can_write_the_money_documents.sql",
    "318_status_vocabularies_the_code_and_production_disagree_on.sql",
    "440_a_portal_client_may_post_their_own_message.sql",
)

#: md5 of the function bodies production held on 28-11-2026 (read-only), which are the bodies of migrations 274 and 440.
PRODUCTION_HAD = {"post_journal_atomic": "868b695a94743fbc9ffe6aa794da85ad", "my_portal_client_ids": "36d056ff1bcc2e3c06fd952e68998cf2"}

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the repair's proof requires HARNESS_PG + psql",
)

#: One line per thing a migration can define or grant in the schema, keyed so that two snapshots compare line by line.
SNAPSHOT = r"""
select line from (
  select 'fn|' || p.proname || '|' || pg_get_function_identity_arguments(p.oid) || '|' || md5(p.prosrc) || '|' || p.prosecdef || '|' || p.provolatile::text || '|' || coalesce(p.proconfig::text, '') || '|exec:'
         || has_function_privilege('anon', p.oid, 'EXECUTE') || ',' || has_function_privilege('authenticated', p.oid, 'EXECUTE') || ',' || has_function_privilege('service_role', p.oid, 'EXECUTE')
         || ',public=' || exists (select 1 from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a where a.grantee = 0 and a.privilege_type = 'EXECUTE') as line
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public'
  union all
  select 'policy|' || tablename || '|' || policyname || '|' || permissive || '|' || cmd || '|' || roles::text || '|' || coalesce(qual, '-') || '|' || coalesce(with_check, '-')
    from pg_policies where schemaname = 'public'
  union all
  select 'priv|' || c.relname || '|' || c.relkind::text || '|' || r.r || '|' || concat(
           case when has_table_privilege(r.r, c.oid, 'SELECT') then 'S' else '-' end, case when has_table_privilege(r.r, c.oid, 'INSERT') then 'I' else '-' end,
           case when has_table_privilege(r.r, c.oid, 'UPDATE') then 'U' else '-' end, case when has_table_privilege(r.r, c.oid, 'DELETE') then 'D' else '-' end,
           case when has_table_privilege(r.r, c.oid, 'TRUNCATE') then 'T' else '-' end, case when has_table_privilege(r.r, c.oid, 'REFERENCES') then 'R' else '-' end,
           case when has_table_privilege(r.r, c.oid, 'TRIGGER') then 'G' else '-' end)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace, (values ('anon'), ('authenticated'), ('service_role')) r(r)
   where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm')
  union all
  select 'pubpriv|' || c.relname || '|' || coalesce((select string_agg(a.privilege_type, ',' order by a.privilege_type) from aclexplode(c.relacl) a where a.grantee = 0), '')
    from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm', 'S')
  union all
  select 'seq|' || c.relname || '|' || r.r || '|' || has_sequence_privilege(r.r, c.oid, 'USAGE') || ',' || has_sequence_privilege(r.r, c.oid, 'SELECT') || ',' || has_sequence_privilege(r.r, c.oid, 'UPDATE')
    from pg_class c join pg_namespace n on n.oid = c.relnamespace, (values ('anon'), ('authenticated'), ('service_role')) r(r)
   where n.nspname = 'public' and c.relkind = 'S'
  union all
  select 'con|' || conrelid::regclass::text || '|' || conname || '|' || pg_get_constraintdef(oid) from pg_constraint where connamespace = 'public'::regnamespace
  union all
  select 'default|' || table_name || '|' || column_name || '|' || coalesce(column_default, '') from information_schema.columns where table_schema = 'public' and column_default is not null
  union all
  select 'trigger|' || tgrelid::regclass::text || '|' || tgname || '|' || tgenabled::text || '|' || pg_get_triggerdef(oid) from pg_trigger where not tgisinternal and tgrelid::regclass::text not like 'pg_%'
  union all
  select 'defacl|' || defaclrole::regrole::text || '|' || coalesce(defaclnamespace::regnamespace::text, '') || '|' || defaclobjtype::text || '|' ||
         (select string_agg(a.grantee::text || ':' || a.privilege_type, ',' order by a.grantee, a.privilege_type) from aclexplode(defaclacl) a) from pg_default_acl
) s order by line;
"""

#: The seven lines the second run changes, by the part of the line that does not change.
REVERTED = (
    "fn|post_journal_atomic|p_entry jsonb, p_lines jsonb|",
    "fn|my_portal_client_ids||",
    "policy|portal_messages|portal_messages_assignment_scope|",
    "policy|portal_messages|portal_messages_assignment_scope_select|",
    "policy|portal_messages|portal_messages_assignment_scope_insert|",
    "policy|portal_messages|portal_messages_assignment_scope_delete|",
)


def _psql(dsn: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", *args], capture_output=True, text=True,
                          env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _scalar(dsn: str, sql: str) -> str:
    r = _psql(dsn, "-tA", "-c", sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _snapshot(dsn: str) -> list[str]:
    r = _psql(dsn, "-tA", "-c", SNAPSHOT)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) > 5000, "the snapshot is too small to be the schema"
    return lines


def _apply(dsn: str, path: Path, *, wrapped: bool = False) -> subprocess.CompletedProcess:
    """A file the way the runner feeds it: one psql, stopping at the first error, in one transaction where the runner wraps it."""
    return _psql(dsn, *(["--single-transaction"] if wrapped else []), "-f", str(path))


def _run_the_six_again(dsn: str) -> None:
    for name in RAN_AGAIN:
        r = _apply(dsn, MIGRATIONS / name)
        assert r.returncode == 0, f"{name}: {r.stderr[:400]}"


def _changed(before: list[str], after: list[str]) -> list[str]:
    return sorted(set(before) ^ set(after))


def _signed_in_may_post(dsn: str) -> bool:
    return _scalar(dsn, "select has_function_privilege('authenticated', 'public.post_journal_atomic(jsonb, jsonb)', 'EXECUTE')") == "t"


def _asks_who_is_calling(dsn: str) -> bool:
    return _scalar(dsn, "select position('assert_caller_acts_for' in prosrc) > 0 from pg_proc where proname = 'post_journal_atomic' "
                        "and pronamespace = 'public'::regnamespace") == "t"


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t786_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, "-c", f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert not any(f.startswith("786_") for f in pg_template.failed), pg_template.failed
        yield f"{admin} dbname={name}"
    finally:
        _psql(admin_dsn, "-c", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_the_six_files_run_again_undo_exactly_seven_definitions_and_786_puts_every_one_back(db):
    before = _snapshot(db)
    assert not _signed_in_may_post(db) and _asks_who_is_calling(db)

    # the incident
    _run_the_six_again(db)
    damaged = _snapshot(db)
    changed = _changed(before, damaged)
    assert changed, "the second run changed nothing: this test no longer reproduces what happened"
    stray = [ln for ln in changed if not ln.startswith(REVERTED)]
    assert stray == [], "the second run changed something this test does not name:\n" + "\n".join(ln[:200] for ln in stray)
    for key in REVERTED:
        assert sum(ln.startswith(key) for ln in changed) == 2, f"{key} was not changed by the second run"
    # ... and it is the damage production showed: the same two bodies, a signed-in role able to post, nobody asked who is calling
    for fn, md5 in PRODUCTION_HAD.items():
        assert _scalar(db, f"select md5(prosrc) from pg_proc where proname = '{fn}' and pronamespace = 'public'::regnamespace") == md5
    assert _signed_in_may_post(db) and not _asks_who_is_calling(db)
    assert int(_scalar(db, "select count(*) from pg_policies where schemaname = 'public' and "
                           "(coalesce(qual, '') ~ 'can_access_client' or coalesce(with_check, '') ~ 'can_access_client')")) == 4

    # the repair
    r = _apply(db, F786, wrapped=True)
    assert r.returncode == 0, r.stderr
    assert "migration 786: 4 policies were put back" in r.stderr, r.stderr
    after = _snapshot(db)
    assert _changed(before, after) == [], "786 did not put everything back:\n" + "\n".join(ln[:200] for ln in _changed(before, after))
    assert not _signed_in_may_post(db) and _asks_who_is_calling(db)


def test_on_a_database_nobody_damaged_786_changes_nothing_and_runs_twice(db):
    before = _snapshot(db)
    for _ in range(2):
        r = _apply(db, F786, wrapped=True)
        assert r.returncode == 0, r.stderr
        assert "migration 786: 0 policies were put back" in r.stderr, r.stderr
    assert _changed(before, _snapshot(db)) == []


def test_a_signed_in_session_is_refused_the_posting_function_again(db):
    call = "SET ROLE authenticated; SELECT public.post_journal_atomic('{}'::jsonb, '[]'::jsonb);"
    _run_the_six_again(db)
    opened = _psql(db, "-c", call)
    assert "permission denied" not in opened.stderr, "the control did not open the door, so the next assertion proves nothing"
    # the old body RUNS for a signed-in caller: what refuses is its own check of an empty payload, not the door
    assert "ERROR:  post_journal_atomic: refusing to post a zero-value journal entry" in opened.stderr, opened.stderr
    assert _apply(db, F786, wrapped=True).returncode == 0
    refused = _psql(db, "-c", call)
    assert refused.returncode != 0 and "permission denied for function post_journal_atomic" in refused.stderr, refused.stderr


def test_the_portal_function_leaves_a_deleted_client_out_again(db):
    body = "select prosrc from pg_proc where proname = 'my_portal_client_ids' and pronamespace = 'public'::regnamespace"
    _run_the_six_again(db)
    assert "deleted_at" not in _scalar(db, body)
    assert _apply(db, F786, wrapped=True).returncode == 0
    assert _scalar(db, body).count("deleted_at IS NULL") == 2


def test_the_rollback_file_runs_and_changes_nothing(db):
    before = _snapshot(db)
    r = _apply(db, R786)
    assert r.returncode == 0, r.stderr
    assert _changed(before, _snapshot(db)) == []
