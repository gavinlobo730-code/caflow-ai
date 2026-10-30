"""Migration 566 — a row names a member of its own firm (ledger POST-A-361, the second half of POST-A-304).

WHAT WAS WRONG
    Migration 565 made the database refuse a row that names a client of another firm. The same shape was open for the columns that name a
    MEMBER (`created_by`, `assigned_to`, `reviewed_by`, `user_id` and the rest, every one a foreign key to `users`): a Partner of firm G,
    a foreign-key check that bypasses row security and a firm policy that asks `firm_id` alone stored a row of G that named a member of
    firm F. Migration 530 had closed it for the two tables that decide access and for nothing else.

WHAT THIS HOLDS (real Postgres)
    * THE REVIEW'S OWN SHAPE: a signed-in Partner of firm G inserting a row of G's whose member column names a member of F is refused by
      the trigger in its own words, naming the column, and the same statement is ACCEPTED with the trigger disabled (the negative control:
      the test sees the hole it closes).
    * Every member column of a table is asked, not only the first: a task with its own `assigned_to` and a foreign `assignee_id` is refused.
    * An insert is judged as a STATEMENT: one bad row in a batch fails the whole batch.
    * An UPDATE that moves a row to another firm's member, or to another firm while keeping its member, is refused; an update that touches
      neither is not asked anything, so a row that already breaks the rule can still be edited and repaired.
    * WHAT IT DELIBERATELY LEAVES ALONE: a NULL member, and a row with no firm at all.
    * THE CATALOG: every plain table with a uuid `firm_id` and a single-column foreign key to `users` carries both triggers, no other table
      carries them, the trigger functions are SECURITY DEFINER with a pinned search path, and nobody signed in may run the installer.
    * The installer picks up a column added later when it is called again, and drops its triggers from a table that has no member column.
    * The apply-time report counts the rows that already break the rule and changes none of them; the migration is idempotent; its rollback
      takes every trigger away and the review's case goes through again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_STEM = "566_a_row_names_a_member_of_its_own_firm"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

F = "56600000-0000-0000-0000-00000000000f"          # firm F
G = "56600000-0000-0000-0000-000000000009"          # firm G
C_G = "56600000-0000-0000-0000-0000000000a1"        # a client of G
PARTNER_AUTH = "56600000-1111-0000-0000-000000000001"
PARTNER_G = "56600000-0000-0000-0000-00000000000b"  # a Partner of G, the signed-in caller
MEMBER_G = "56600000-0000-0000-0000-0000000000b2"   # another member of G
MEMBER_F = "56600000-0000-0000-0000-0000000000f0"   # a member of F

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the member-in-firm proof requires HARNESS_PG + psql",
)

TRIGGERS = ("row_member_in_firm_ins", "row_member_in_firm_upd")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _signed_in_partner(sql: str, dsn: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": PARTNER_AUTH, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _run_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    """A migration file as the runner runs it: warnings kept (the runner keeps the `migration NNN:` ones)."""
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)],
                          capture_output=True, text=True, env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _godown(member: str | None, name: str = "g1") -> str:
    by = f"'{member}'" if member else "NULL"
    return f"INSERT INTO public.godowns (firm_id, client_id, name, created_by) VALUES ('{G}', '{C_G}', '{name}', {by});"


def _task(assigned_to: str | None, assignee_id: str | None, title: str = "t1") -> str:
    a = f"'{assigned_to}'" if assigned_to else "NULL"
    b = f"'{assignee_id}'" if assignee_id else "NULL"
    return (f"INSERT INTO public.tasks (firm_id, client_id, title, assigned_to, assignee_id) "
            f"VALUES ('{G}', '{C_G}', '{title}', {a}, {b});")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m566_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'partner@m566.test');
            INSERT INTO firms (id, name, email) VALUES ('{F}', 'M566 F', 'f@m566.test'), ('{G}', 'M566 G', 'g@m566.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
                 ('{PARTNER_G}', '{G}', '{PARTNER_AUTH}', 'partner@m566.test', 'P', 'Partner', true),
                 ('{MEMBER_G}', '{G}', NULL, 'g2@m566.test', 'G2', 'Manager', true),
                 ('{MEMBER_F}', '{F}', NULL, 'f1@m566.test', 'F1', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{C_G}', '{G}', 'CG', 'Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the review's own shape ────────────────────────────────────────────────────────────────────────────────────────
def test_a_signed_in_partner_of_one_firm_cannot_store_a_row_naming_another_firms_member(db):
    r = _signed_in_partner(_godown(MEMBER_F), db)
    assert r.returncode != 0 and "another firm" in r.stderr and "created_by" in r.stderr, r.stderr or "it succeeded"
    assert _ok(db, "SELECT count(*) FROM public.godowns;") == "0"


def test_the_same_statement_is_accepted_without_the_trigger_and_so_the_test_sees_the_hole(db):
    """The negative control. Row security lets the Partner of G write a row of G's and the foreign key lets it name any member."""
    _ok(db, "ALTER TABLE public.godowns DISABLE TRIGGER row_member_in_firm_ins;")
    r = _signed_in_partner(_godown(MEMBER_F), db)
    assert r.returncode == 0, f"the review's case should be accepted with the trigger off: {r.stderr}"
    assert _ok(db, "SELECT count(*) FROM public.godowns;") == "1"


def test_a_signed_in_partner_still_stores_a_row_naming_a_member_of_their_own_firm(db):
    assert _signed_in_partner(_godown(MEMBER_G), db).returncode == 0
    assert _signed_in_partner(_godown(PARTNER_G, "g2"), db).returncode == 0


def test_every_member_column_of_a_table_is_asked_and_not_only_the_first(db):
    both_own = _signed_in_partner(_task(MEMBER_G, PARTNER_G), db)
    assert both_own.returncode == 0, both_own.stderr
    r = _signed_in_partner(_task(MEMBER_G, MEMBER_F, "t2"), db)
    assert r.returncode != 0 and "assignee_id" in r.stderr and "another firm" in r.stderr, r.stderr or "it succeeded"
    r = _signed_in_partner(_task(MEMBER_F, MEMBER_G, "t3"), db)
    assert r.returncode != 0 and "assigned_to" in r.stderr, r.stderr or "it succeeded"


# ── an insert is judged as a statement ────────────────────────────────────────────────────────────────────────────
def test_one_bad_row_in_a_batch_fails_the_whole_batch(db):
    r = _psql(db, f"""INSERT INTO public.godowns (firm_id, client_id, name, created_by) VALUES
        ('{G}', '{C_G}', 'GOOD', '{MEMBER_G}'), ('{G}', '{C_G}', 'BAD', '{MEMBER_F}');""")
    assert r.returncode != 0 and "another firm" in r.stderr
    assert _ok(db, "SELECT count(*) FROM public.godowns;") == "0"


# ── an update ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_update_that_names_another_firms_member_is_refused(db):
    _ok(db, _godown(MEMBER_G))
    r = _psql(db, f"UPDATE public.godowns SET created_by = '{MEMBER_F}' WHERE name = 'g1';")
    assert r.returncode != 0 and "another firm" in r.stderr
    assert _ok(db, "SELECT created_by FROM public.godowns WHERE name = 'g1';") == MEMBER_G


def test_an_update_that_moves_a_row_to_another_firm_while_keeping_its_member_is_refused(db):
    _ok(db, _godown(MEMBER_G))
    # The client has to follow the firm for 565's own check to pass, so the one that fires is this migration's.
    _ok(db, f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('56600000-0000-0000-0000-0000000000f1', '{F}', 'CF', 'Private Limited');")
    r = _psql(db, f"UPDATE public.godowns SET firm_id = '{F}', client_id = '56600000-0000-0000-0000-0000000000f1' WHERE name = 'g1';")
    assert r.returncode != 0 and "member" in r.stderr and "another firm" in r.stderr, r.stderr


def test_a_row_that_already_breaks_the_rule_can_still_be_edited_and_repaired(db):
    """The triggers fire on writes that touch a member column or the firm. A row found by the apply-time report is not bricked."""
    _ok(db, "ALTER TABLE public.godowns DISABLE TRIGGER row_member_in_firm_ins;")
    _ok(db, _godown(MEMBER_F))
    _ok(db, "ALTER TABLE public.godowns ENABLE TRIGGER row_member_in_firm_ins;")
    _ok(db, "UPDATE public.godowns SET name = 'edited' WHERE name = 'g1';")
    _ok(db, f"UPDATE public.godowns SET created_by = '{MEMBER_F}' WHERE name = 'edited';")  # same value: not a change
    _ok(db, f"UPDATE public.godowns SET created_by = '{MEMBER_G}' WHERE name = 'edited';")  # the repair
    assert _ok(db, "SELECT created_by FROM public.godowns WHERE name = 'edited';") == MEMBER_G


# ── what it deliberately leaves alone ─────────────────────────────────────────────────────────────────────────────
def test_a_null_member_is_not_refused(db):
    _ok(db, _godown(None))
    _ok(db, _task(None, None))


def test_a_row_that_belongs_to_no_firm_is_not_refused(db):
    """`clients.firm_id` is nullable, and `assigned_manager` is a foreign key to users: a client with no firm names no tenant."""
    _ok(db, f"INSERT INTO clients (firm_id, client_name, entity_type, assigned_manager) VALUES (NULL, 'NOFIRM', 'Private Limited', '{MEMBER_F}');")


# ── the catalog ───────────────────────────────────────────────────────────────────────────────────────────────────
def _tables_with_member_columns(db: str) -> dict[str, list[str]]:
    rows = _ok(db, """
        SELECT c.oid::regclass::text, public.member_columns_of(c.oid::regclass)::text
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r'
           AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'firm_id'
                          AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped)
           AND cardinality(public.member_columns_of(c.oid::regclass)) > 0;""")
    out: dict[str, list[str]] = {}
    for line in rows.splitlines():
        table, cols = line.split("|")
        out[table.removeprefix("public.")] = cols.strip("{}").split(",")
    return out


def _tables_with_trigger(db: str, name: str) -> set[str]:
    rows = _ok(db, f"SELECT tgrelid::regclass::text FROM pg_trigger WHERE NOT tgisinternal AND tgname = '{name}';")
    return {r.removeprefix("public.") for r in rows.splitlines()}


def test_every_table_with_a_firm_and_a_foreign_key_to_users_carries_both_member_triggers_and_no_other_does(db):
    tables = _tables_with_member_columns(db)
    assert len(tables) >= 90, f"only {len(tables)} tables found: the scan has stopped seeing the schema"
    assert sum(len(c) for c in tables.values()) >= 110
    for trigger in TRIGGERS:
        got = _tables_with_trigger(db, trigger)
        assert got == set(tables), (f"{trigger}: missing {sorted(set(tables) - got)}, extra {sorted(got - set(tables))}. "
                                    "Call public.guard_member_firm('<table>') in the migration that creates the table or adds the column.")


def test_the_trigger_names_exactly_the_columns_the_catalog_finds(db):
    tables = _tables_with_member_columns(db)
    defs = _ok(db, "SELECT pg_get_triggerdef(g.oid) FROM pg_trigger g WHERE NOT g.tgisinternal AND g.tgname = 'row_member_in_firm_ins';")
    seen = set()
    for line in defs.splitlines():
        table = re.search(r" ON public\.(\w+) ", line).group(1)
        named = sorted(re.findall(r"'(\w+)'", line.split("EXECUTE FUNCTION", 1)[1]))
        assert named == sorted(tables[table]), (table, named, tables[table])
        seen.add(table)
    assert seen == set(tables)


def test_the_trigger_functions_are_security_definer_with_a_pinned_search_path(db):
    rows = _ok(db, """
        SELECT p.proname, p.prosecdef, p.proconfig::text FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.proname IN ('assert_inserted_rows_name_a_member_of_their_firm', 'assert_updated_row_names_a_member_of_its_firm') ORDER BY 1;""")
    lines = rows.splitlines()
    assert len(lines) == 2, lines
    for line in lines:
        name, secdef, config = line.split("|")
        assert secdef == "t" and "search_path" in config, line


def test_nobody_signed_in_may_run_the_installer(db):
    for role in ("anon", "authenticated"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', 'public.guard_member_firm(regclass)', 'EXECUTE');") == "f", role
    assert _ok(db, "SELECT has_function_privilege(0::oid, 'public.guard_member_firm(regclass)', 'EXECUTE');") == "f", "public"


def test_the_installer_refuses_a_table_without_a_firm(db):
    r = _psql(db, "SELECT public.guard_member_firm('public.fx_rates'::regclass);")
    assert r.returncode != 0 and "has no uuid firm_id" in r.stderr


def test_the_installer_picks_up_a_column_added_later_when_it_is_called_again_and_drops_its_triggers_when_none_is_left(db):
    _ok(db, """CREATE TABLE public.m566_probe (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), firm_id uuid NOT NULL,
                  created_by uuid REFERENCES public.users(id));
                SELECT public.guard_member_firm('public.m566_probe');""")
    assert "m566_probe" in _tables_with_trigger(db, "row_member_in_firm_ins")
    assert _psql(db, f"INSERT INTO public.m566_probe (firm_id, created_by) VALUES ('{G}', '{MEMBER_F}');").returncode != 0
    # A second member column, added after the triggers were installed: unchecked until the installer is called again.
    _ok(db, "ALTER TABLE public.m566_probe ADD COLUMN reviewed_by uuid REFERENCES public.users(id);")
    assert _psql(db, f"INSERT INTO public.m566_probe (firm_id, reviewed_by) VALUES ('{G}', '{MEMBER_F}');").returncode == 0
    _ok(db, "SELECT public.guard_member_firm('public.m566_probe');")
    assert _psql(db, f"INSERT INTO public.m566_probe (firm_id, reviewed_by) VALUES ('{G}', '{MEMBER_F}');").returncode != 0
    # A trigger that names a column depends on it, so dropping the column is refused until the triggers are dropped: the failure is
    # loud and its hint says what to do, and a migration that drops or retypes a member column drops the triggers first and calls
    # the installer after.
    refused = _psql(db, "ALTER TABLE public.m566_probe DROP COLUMN created_by;")
    assert refused.returncode != 0 and "row_member_in_firm_upd" in refused.stderr, refused.stderr
    # No member column left: the installer takes its triggers away instead of leaving a stale list.
    _ok(db, "DROP TRIGGER row_member_in_firm_ins ON public.m566_probe; DROP TRIGGER row_member_in_firm_upd ON public.m566_probe; "
            "ALTER TABLE public.m566_probe DROP COLUMN created_by, DROP COLUMN reviewed_by; SELECT public.guard_member_firm('public.m566_probe');")
    assert "m566_probe" not in _tables_with_trigger(db, "row_member_in_firm_ins")


# ── the report, idempotence, the rollback ─────────────────────────────────────────────────────────────────────────
def test_the_apply_time_report_counts_what_already_breaks_the_rule_and_changes_none_of_it(db):
    _ok(db, "ALTER TABLE public.godowns DISABLE TRIGGER row_member_in_firm_ins;")
    _ok(db, _godown(MEMBER_F))
    _ok(db, "ALTER TABLE public.godowns ENABLE TRIGGER row_member_in_firm_ins;")
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "migration 566:" in r.stderr and "1 existing row(s) in 1 table column(s) already name a member of another firm" in r.stderr, r.stderr
    assert _ok(db, "SELECT count(*) FROM public.godowns;") == "1"


def test_a_clean_database_reports_none(db):
    r = _run_file(db, MIGRATION)
    assert r.returncode == 0, r.stderr
    assert "0 existing row(s) in 0 table column(s) already name a member of another firm" in r.stderr


def test_the_migration_is_idempotent(db):
    before = {t: _tables_with_trigger(db, t) for t in TRIGGERS}
    assert _run_file(db, MIGRATION).returncode == 0
    assert {t: _tables_with_trigger(db, t) for t in TRIGGERS} == before


def test_the_rollback_takes_every_trigger_away_and_the_review_case_goes_through_again(db):
    assert _signed_in_partner(_godown(MEMBER_F, "BEFORE"), db).returncode != 0, "refused while the triggers are on"
    back = _run_file(db, ROLLBACK)
    assert back.returncode == 0, back.stderr
    for trigger in TRIGGERS:
        assert _tables_with_trigger(db, trigger) == set(), trigger
    assert _ok(db, "SELECT count(*) FROM pg_proc WHERE proname IN ('guard_member_firm', 'member_columns_of') "
                   "OR proname ~ '^assert_(inserted_rows|updated_row)_names?_a_member';") == "0"
    assert _signed_in_partner(_godown(MEMBER_F, "AFTER"), db).returncode == 0, "the rollback should give the old behaviour back"
    assert _run_file(db, MIGRATION).returncode == 0
    assert _signed_in_partner(_godown(MEMBER_F, "AGAIN"), db).returncode != 0
