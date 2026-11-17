"""Migration 680 — the MCA filings are written by the API only (ledger POST-A-442).

WHAT WAS WRONG
    Migrations 012 and 041 granted `authenticated` INSERT, UPDATE and DELETE on `mca_filings`, behind the row policies of migrations 260, 415,
    493 and 540. Nothing in `apps/web` writes the table since the firm-level Add Filing moved onto `POST /api/mca-workspace/filings` (part 1,
    16-11-2026), and the API's two writers use the privileged client, so the grant served only a hand-made PostgREST request from a signed-in
    session: a filing with no category, no audit event, no company check and no closing of its obligation.

WHAT THIS HOLDS (real Postgres)
    * THE PRIVILEGES: a signed-in role effectively holds no INSERT, UPDATE, DELETE or TRUNCATE (table level, column level, or through PUBLIC),
      still SELECTs, and the service role keeps its writes.
    * AN ASSIGNED MANAGER is refused an INSERT, an UPDATE and a DELETE BY THE PRIVILEGE, and still reads the table. The statements match no row,
      so the refusal can only be the privilege.
    * THE SERVICE ROLE, which the API's privileged client uses, runs the same three statements.
    * THE WORST CASE: a database that granted everything to PUBLIC, anon and authenticated (a column grant included) and then applied the
      migration holds none of it after; a grant the owner cannot take back fails the migration in its own words.
    * IT IS IDEMPOTENT, and its own rollback gives INSERT, UPDATE and DELETE back, so the refusals above go through (the negative control).
    * NOTHING IN THE BROWSER WRITES THE TABLE (no database needed): no `.from("mca_filings")` in `apps/web` is followed by a write.

The shape is migration 593's (POST-A-443). Runs only when HARNESS_PG is set + psql on PATH, except the two file checks, which run in the mock job as well.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_STEM = "680_the_mca_filings_are_written_by_the_api_only"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

TABLES = ("mca_filings",)
WRITES = ("INSERT", "UPDATE", "DELETE")

FIRM = "68000000-0000-0000-0000-000000000001"
CLIENT = "68000000-0000-0000-0000-0000000000a1"
MANAGER_AUTH = "68000000-1111-0000-0000-000000000001"
MANAGER_USER = "68000000-0000-0000-0000-00000000000b"

# The database tests skip through `pg_template` without HARNESS_PG + psql; the two file checks run in the mock-mode job as well.


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(role: str, sql: str, dsn: str) -> subprocess.CompletedProcess:
    if role == "authenticated":
        claims = json.dumps({"sub": MANAGER_AUTH, "role": "authenticated"})
        return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")
    return _psql(dsn, f"SET ROLE {role}; {sql}")


def _first_column(dsn: str, table: str) -> str:
    return _ok(dsn, f"SELECT attname FROM pg_attribute WHERE attrelid = 'public.{table}'::regclass AND attnum > 0 "
                    "AND NOT attisdropped ORDER BY attnum LIMIT 1;")


def _statement(dsn: str, table: str, verb: str) -> str:
    """A statement of the given verb that names the table and matches NO row, so a refusal can only be the privilege: the privilege check of a
    statement happens before it looks at a row, and a statement that matches none cannot meet a constraint, a trigger or a row policy."""
    col = _first_column(dsn, table)
    return {
        "INSERT": f"INSERT INTO public.{table} ({col}) SELECT {col} FROM public.{table} WHERE false;",
        "UPDATE": f"UPDATE public.{table} SET {col} = {col} WHERE false;",
        "DELETE": f"DELETE FROM public.{table} WHERE false;",
    }[verb]


def _effective_writes(dsn: str, table: str) -> set[str]:
    """`ROLE:VERB` for every write a signed-in role EFFECTIVELY holds on the table: at table level, at column level, or through PUBLIC
    (has_table_privilege and has_any_column_privilege see all three; role_table_grants sees only the first)."""
    rows = _ok(dsn, f"""
        SELECT r.name || ':' || v.verb
          FROM (VALUES ('authenticated'), ('anon')) AS r(name)
          CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) AS v(verb)
         WHERE has_table_privilege(r.name, 'public.{table}', v.verb)
            OR (v.verb IN ('INSERT', 'UPDATE') AND has_any_column_privilege(r.name, 'public.{table}', v.verb));""")
    return set(rows.splitlines())


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m680_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{MANAGER_AUTH}', 'manager@m680.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M680 Firm', 'm680@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{MANAGER_USER}', '{FIRM}', '{MANAGER_AUTH}', 'manager@m680.test', 'M', 'Manager', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'Client A', 'Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{MANAGER_USER}', '{CLIENT}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── no database: the file names the table, and the browser writes none of it ──────────────────────────────────────────────────────────────────
def test_the_migration_names_the_table_and_the_rollback_gives_back_what_was_granted():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "t text := 'mca_filings';" in sql
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in sql and "FROM PUBLIC, authenticated, anon" in sql
    back = ROLLBACK.read_text(encoding="utf-8")
    assert "GRANT INSERT, UPDATE, DELETE ON public.mca_filings TO authenticated" in back
    assert "TRUNCATE" not in back.split("DO $$")[1], "TRUNCATE is a platform default PostgREST does not expose and is not given back"


def test_nothing_in_the_browser_writes_the_table():
    """The premise of the revoke: every `.from("mca_filings")` in `apps/web` is a read. A write found here must move behind the API first."""
    web = API_ROOT.parents[1] / "apps" / "web"
    writes = []
    for path in list(web.rglob("*.ts")) + list(web.rglob("*.tsx")):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"""\.from\(\s*["'`]mca_filings["'`]\s*\)""", text):
            tail = text[m.end():m.end() + 200]
            if re.match(r"\s*\.\s*(insert|update|upsert|delete)\b", tail):
                writes.append(f"{path.relative_to(web)}:{text.count(chr(10), 0, m.start()) + 1}")
    assert writes == [], f"the browser writes mca_filings: {writes}"
    reads = [p for p in (web / "app").rglob("*.tsx") if 'from("mca_filings")' in p.read_text(encoding="utf-8")]
    assert reads, "the scan found no read of the table at all, so it is not looking where the browser reads it"


def test_the_tables_are_on_the_closed_list_the_writer_rule_holds_every_writer_to():
    listed = {ln.strip() for ln in (API_ROOT / "tests" / "fixtures" / "tables_the_signed_in_role_cannot_write.txt")
              .read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}
    assert set(TABLES) <= listed, f"not on the closed list: {sorted(set(TABLES) - listed)}"


# ── the privileges ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("table", TABLES)
def test_a_signed_in_role_holds_no_write_on_the_table_and_still_reads_it(db, table):
    assert _effective_writes(db, table) == set()
    assert _ok(db, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT');") == "t"


@pytest.mark.parametrize("table", TABLES)
def test_the_service_role_keeps_its_writes(db, table):
    for verb in WRITES:
        assert _ok(db, f"SELECT has_table_privilege('service_role', 'public.{table}', '{verb}');") == "t", (table, verb)


@pytest.mark.parametrize("verb", WRITES)
@pytest.mark.parametrize("table", TABLES)
def test_an_assigned_manager_is_refused_by_the_privilege(db, table, verb):
    r = _as("authenticated", _statement(db, table, verb), db)
    assert r.returncode != 0 and f"permission denied for table {table}" in r.stderr, (
        f"{table} {verb}: a signed-in Manager was not refused by the privilege: {r.stderr or 'it succeeded'}")


@pytest.mark.parametrize("table", TABLES)
def test_an_assigned_manager_still_reads_the_table(db, table):
    r = _as("authenticated", f"SELECT count(*) FROM public.{table};", db)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("verb", WRITES)
@pytest.mark.parametrize("table", TABLES)
def test_the_service_role_runs_the_same_statement(db, table, verb):
    r = _as("service_role", _statement(db, table, verb), db)
    assert r.returncode == 0, f"{table} {verb}: the API's privileged client was refused: {r.stderr}"


# ── the worst case, the closing check, idempotence, the rollback ──────────────────────────────────────────────────
def test_what_the_platform_grants_and_what_reaches_a_role_another_way_is_removed(db):
    """The throwaway database holds none of the platform's default privileges, so the TRUNCATE half, the `anon` half, a write through PUBLIC and
    one through a column grant are each given first, then the migration is applied."""
    for table in TABLES:
        _ok(db, f"""
            GRANT INSERT, UPDATE, DELETE, TRUNCATE ON public.{table} TO authenticated, anon;
            GRANT INSERT ON public.{table} TO PUBLIC;
            GRANT UPDATE ({_first_column(db, table)}) ON public.{table} TO authenticated;
        """)
        assert _effective_writes(db, table) >= {"authenticated:INSERT", "authenticated:UPDATE", "authenticated:DELETE",
                                                "authenticated:TRUNCATE", "anon:INSERT", "anon:TRUNCATE"}, table
    r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    for table in TABLES:
        assert _effective_writes(db, table) == set(), table


@pytest.mark.parametrize("table", TABLES)
def test_the_closing_check_fails_the_migration_when_a_write_cannot_be_revoked(db, table):
    """A privilege the migration's own REVOKE cannot remove must fail the migration and not let it finish green with the table still writable.
    The REVOKE removes what the OWNER granted; a grant made by a role holding GRANT OPTION is not the owner's."""
    grantor = f"m680_g_{uuid.uuid4().hex[:8]}"
    _ok(db, f"""
        CREATE ROLE {grantor} NOLOGIN;
        GRANT INSERT ON public.{table} TO {grantor} WITH GRANT OPTION;
        SET ROLE {grantor};
        GRANT INSERT ON public.{table} TO authenticated;
        RESET ROLE;
    """)
    try:
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
        assert r.returncode != 0 and f"migration 680: authenticated still holds INSERT on {table}" in r.stderr, (r.stdout, r.stderr)
    finally:
        _psql(db, f"DROP OWNED BY {grantor}; DROP ROLE IF EXISTS {grantor};")


def test_680_is_idempotent(db):
    for _ in range(2):
        r = _psql(db, MIGRATION.read_text(encoding="utf-8"))
        assert r.returncode == 0, r.stderr
    for table in TABLES:
        assert _effective_writes(db, table) == set(), table


def test_its_own_rollback_gives_the_verbs_back_and_the_refusals_stop(db):
    """The negative control: without the revoke the very statements refused above go through."""
    r = _psql(db, ROLLBACK.read_text(encoding="utf-8"))
    assert r.returncode == 0, r.stderr
    for table in TABLES:
        assert _effective_writes(db, table) == {"authenticated:INSERT", "authenticated:UPDATE", "authenticated:DELETE"}, table
        for verb in WRITES:
            again = _as("authenticated", _statement(db, table, verb), db)
            assert again.returncode == 0, (table, verb, again.stderr)
