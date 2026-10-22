"""Migration 538 — sixteen tables that no signed-in route writes are closed to the signed-in role, and the `ri_*` tables that only a
migration-built database had are gone (the dead-table half of POST-A-305).

WHAT WAS WRONG
    `authenticated` held every privilege on sixteen firm-level tables behind a firm policy and no role tier, so any member, a
    Reviewer included, could write them over PostgREST whatever the API checks: among them `invoice_settings`, the bank details
    printed on every invoice. Nothing signed-in writes any of them (ten are used by nothing at all; one is used only by the
    privileged client; four are written only by the privileged client; one had write methods nobody called).

WHAT THIS HOLDS (real Postgres, as each person)
    * THE ELEVEN TABLES THE SIGNED-IN ROLE NEITHER READS NOR WRITES hold no privilege for `authenticated` or `anon` at any level (table, column, through PUBLIC); a
      signed-in Partner, Manager and Reviewer are each refused a read and a write; the service role keeps its privileges.
    * THE FIVE TABLES IT ONLY READS: `authenticated` keeps SELECT and nothing else (table, column, PUBLIC),
      `anon` nothing; a signed-in Partner, Manager and Reviewer read them without error and are refused every write; the service
      role still writes.
    * THE FORGERY: a Reviewer UPDATEs the invoice settings (the bank details on every invoice) and is refused; with the migration
      rolled back the same statement is accepted (the negative control).
    * The `ri_*` tables are absent.
    * THE ROLLBACK gives back what the migrations granted; a re-apply closes the tables again; a second run changes nothing.
    * A PREMISE THAT WAS CHECKED AND IS NOW A TEST: a pending staff invitee's row, with its clear `invite_token`, is read by NO
      signed-in member, because a signed-in session reads only its own `users` row and an invitee has no auth id yet.

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

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the closed-tables proof requires HARNESS_PG + psql",
)

_STEM = "538_tables_no_signed_in_route_writes_are_closed_to_the_signed_in_role"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

FIRM = "53800000-0000-0000-0000-000000000001"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("53800000-0000-0000-0000-00000000000a", "53800000-1111-0000-0000-000000000001", "Partner"),
    "manager": ("53800000-0000-0000-0000-00000000000b", "53800000-1111-0000-0000-000000000002", "Manager"),
    "reviewer": ("53800000-0000-0000-0000-00000000000c", "53800000-1111-0000-0000-000000000003", "Reviewer"),
}
INVITEE = "53800000-0000-0000-0000-0000000000d1"
TOKEN = "t" * 43
NOTHING_USES = ["ai_trigger_registry", "entity_addresses", "entity_documents", "lead_activities", "lead_contacts", "pending_invites",
                "permission_grants", "recurring_journal_template_lines", "retainer_logs", "team_members", "xbrl_tag_mappings"]
READ_ONLY = ["email_templates", "escalation_rules", "firm_branding", "invoice_settings", "invoice_templates"]
RI = ["ri_entities", "ri_cross_client_signals", "ri_entity_relationships", "ri_client_entity_links"]
WRITES = ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _present(dsn: str, table: str) -> None:
    """`xbrl_tag_mappings` is in production and in no migration, so a database built from them does not have it."""
    if _rows(dsn, f"SELECT to_regclass('public.{table}') IS NOT NULL") != [["t"]]:
        pytest.skip(f"public.{table} exists in production only")


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    pre = f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", pre + sql], capture_output=True, text=True)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e538_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO users (id, firm_id, email, full_name, role, is_active, status, invite_token, invite_expires_at)
                 VALUES ('{INVITEE}', '{FIRM}', 'invitee@t.in', 'Invitee', 'Manager', true, 'invited', '{TOKEN}', now() + interval '7 days');
            INSERT INTO invoice_settings (firm_id) VALUES ('{FIRM}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE TEN TABLES NOTHING USES ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", NOTHING_USES)
@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_the_signed_in_and_anonymous_roles_hold_nothing_on_a_table_nothing_uses(dsn, table, role):
    _present(dsn, table)
    for priv in ["SELECT"] + WRITES:
        assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{priv}')") == [["f"]], (table, role, priv)
    assert _rows(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{table}', 'SELECT, INSERT, UPDATE, REFERENCES')") == [["f"]]


@pytest.mark.parametrize("table", NOTHING_USES)
@pytest.mark.parametrize("who", ["partner", "manager", "reviewer"])
def test_a_signed_in_member_is_refused_a_read_and_a_write_of_a_table_nothing_uses(dsn, table, who):
    _present(dsn, table)
    read = _as(dsn, who, f"SELECT count(*) FROM {table};")
    assert read.returncode != 0 and "permission denied" in read.stderr, read.stderr
    write = _as(dsn, who, f"DELETE FROM {table};")
    assert write.returncode != 0 and "permission denied" in write.stderr, write.stderr


# ── THE SIX TABLES ONLY THE PRIVILEGED CLIENT WRITES ────────────────────────────────────────

@pytest.mark.parametrize("table", READ_ONLY)
def test_the_signed_in_role_keeps_its_read_and_holds_no_write_at_any_level(dsn, table):
    assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT')") == [["t"]]
    for priv in WRITES:
        assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', '{priv}')") == [["f"]], (table, priv)
    assert _rows(dsn, f"SELECT has_any_column_privilege('authenticated', 'public.{table}', 'INSERT, UPDATE, REFERENCES')") == [["f"]]
    for priv in ["SELECT"] + WRITES:
        assert _rows(dsn, f"SELECT has_table_privilege('anon', 'public.{table}', '{priv}')") == [["f"]], (table, "anon", priv)


@pytest.mark.parametrize("table", READ_ONLY)
@pytest.mark.parametrize("who", ["partner", "manager", "reviewer"])
def test_a_signed_in_member_still_reads_the_table_and_is_refused_every_write(dsn, table, who):
    read = _as(dsn, who, f"SELECT count(*) FROM {table};")
    assert read.returncode == 0, read.stderr
    for write in (f"DELETE FROM {table};", f"UPDATE {table} SET id = id;", f"TRUNCATE {table};"):
        got = _as(dsn, who, write)
        assert got.returncode != 0 and "permission denied" in got.stderr, (write, got.stderr)
    got = _as(dsn, who, f"INSERT INTO {table} DEFAULT VALUES;")
    assert got.returncode != 0 and "permission denied" in got.stderr, got.stderr


def test_a_member_reads_their_firms_invoice_settings_and_a_reviewer_cannot_change_the_bank_details(dsn):
    for who in PEOPLE:
        got = _as(dsn, who, "SELECT count(*) FROM invoice_settings;")
        assert got.returncode == 0, got.stderr
        assert got.stdout.split()[-1] == "1", (who, got.stdout)
    forged = _as(dsn, "reviewer", "UPDATE invoice_settings SET bank_name = 'Forged Bank', account_number = '1';")
    assert forged.returncode != 0 and "permission denied" in forged.stderr, forged.stderr
    assert _rows(dsn, "SELECT count(*) FROM invoice_settings WHERE bank_name = 'Forged Bank'") == [["0"]]


# ── THE SERVICE ROLE ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", NOTHING_USES + READ_ONLY)
def test_the_service_role_keeps_its_own_privileges(dsn, table):
    _present(dsn, table)
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', '{priv}')") == [["t"]], (table, priv)


def test_the_service_role_still_writes_a_branding_row_and_the_invoice_settings(dsn):
    done = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SET ROLE service_role; INSERT INTO firm_branding (firm_id) VALUES ('{FIRM}') RETURNING 1; "
         f"UPDATE invoice_settings SET bank_name = 'Real Bank' WHERE firm_id = '{FIRM}' RETURNING 1;"],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("table", RI)
def test_the_unused_ri_tables_are_gone(dsn, table):
    assert _rows(dsn, f"SELECT to_regclass('public.{table}') IS NULL") == [["t"]]


# ── THE ROLLBACK ────────────────────────────────────────────────────────────────────────────

def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it_again(dsn):
    done = _psql_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    present = [t for t in NOTHING_USES + READ_ONLY if _rows(dsn, f"SELECT to_regclass('public.{t}') IS NOT NULL") == [["t"]]]
    assert len(present) == 15, present                                  # all but the one table that exists in production only
    for table in present:
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', '{priv}')") == [["t"]], (table, priv)
    forged = _as(dsn, "reviewer", "UPDATE invoice_settings SET bank_name = 'Forged Bank' RETURNING 1;")
    assert forged.returncode == 0, forged.stderr                       # the negative control: the bank details were open to a Reviewer
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    again = _as(dsn, "reviewer", "UPDATE invoice_settings SET bank_name = 'Forged Again';")
    assert again.returncode != 0 and "permission denied" in again.stderr


def test_a_second_run_of_the_migration_changes_nothing(dsn):
    names = ", ".join(f"'{t}'" for t in NOTHING_USES + READ_ONLY)
    sql = f"SELECT c.relname, c.relacl::text FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relname IN ({names}) ORDER BY 1"
    before = _rows(dsn, sql)
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _rows(dsn, sql) == before


# ── A PREMISE THAT WAS CHECKED ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["partner", "manager", "reviewer"])
def test_no_signed_in_member_reads_a_pending_staff_invitees_row_or_its_clear_token(dsn, who):
    """`users` is readable by a signed-in session only for its OWN row, and a pending invitee has no auth id, so the secret
    `accept_invite` matches on is not exposed to the firm. If a policy ever widens the read, this fails."""
    row = _as(dsn, who, f"SELECT count(*) FROM users WHERE id = '{INVITEE}';")
    assert row.returncode == 0, row.stderr
    assert row.stdout.split()[-1] == "0", row.stdout
    token = _as(dsn, who, "SELECT count(*) FROM users WHERE invite_token IS NOT NULL;")
    assert token.returncode == 0, token.stderr
    assert token.stdout.split()[-1] == "0", token.stdout
    everyone = _as(dsn, who, "SELECT count(*) FROM users;")
    assert everyone.stdout.split()[-1] == "1", everyone.stdout      # only their own row


# ── THE WORST CASE: A DATABASE THAT GRANTED EVERYTHING FIRST ────────────────────────────────

def test_the_migration_takes_every_privilege_away_from_a_database_that_granted_them_all(dsn):
    """Supabase's platform defaults give `anon` and `authenticated` far more than the migrations granted (production's ACLs, read on
    22-10-2026: TRUNCATE, REFERENCES and TRIGGER for `anon` on every one of these tables). A database built from the migrations
    does not have those, so a migration that forgot `anon` or PUBLIC would pass every other case here. Grant everything to all
    three, apply the migration again, and ask the effective privilege."""
    present = [t for t in NOTHING_USES + READ_ONLY if _rows(dsn, f"SELECT to_regclass('public.{t}') IS NOT NULL") == [["t"]]]
    for table in present:
        # the service role's own grant is taken away too, so that what it keeps afterwards is the migration's explicit grant and
        # not a leftover (PUBLIC is revoked by the migration, and a service role that held its rights only through PUBLIC would
        # otherwise lose them)
        done = _psql(dsn, f"REVOKE ALL ON public.{table} FROM service_role; GRANT ALL ON public.{table} TO PUBLIC, anon, authenticated;")
        assert done.returncode == 0, done.stderr
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for table in present:
        for role in ("authenticated", "anon"):
            for priv in WRITES:
                assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{priv}')") == [["f"]], (table, role, priv)
            assert _rows(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{table}', 'INSERT, UPDATE, REFERENCES')") == [["f"]], (table, role)
        assert _rows(dsn, f"SELECT has_table_privilege('anon', 'public.{table}', 'SELECT')") == [["f"]], (table, "anon read")
        expected = [["t"]] if table in READ_ONLY else [["f"]]
        assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT')") == expected, (table, "authenticated read")
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', '{priv}')") == [["t"]], (table, priv)
