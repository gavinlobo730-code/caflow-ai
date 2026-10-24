"""Migration 542 — the two FX record tables and the portal session log are written by the API only and read by the members assigned to
the client (ledger POST-A-299, the last tranche).

WHAT WAS WRONG
    `fx_adjustments`, `fx_revaluations` and `client_portal_sessions` carried a NOT NULL client and a firm policy and nothing else, and
    the signed-in role held INSERT, UPDATE and DELETE on them (migrations 149, 156 and 194), so any member of the firm, an unassigned
    Reviewer included, read AND wrote them over PostgREST: a realised or unrealised FX figure that the FX reports and the vendor
    statement read back, a revaluation row the next revaluation diffs against (a forged one changes the next journal), and a portal
    session the client-health score reads login recency from.

WHAT THIS HOLDS (real Postgres, as each person)
    * THE PRIVILEGES: a signed-in role effectively holds no INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES or TRIGGER (table, column or
      through PUBLIC) on the three tables and still SELECTs; the service role keeps its writes; proved from the worst case too (a
      database that granted everything to PUBLIC, anon and authenticated first and then applied the migration) and from the other end
      (a database where the signed-in role held nothing).
    * THE FORGERIES are each refused by the privilege, as a Partner, an assigned Manager, an assigned Executive, an assigned Reviewer
      and two members assigned to nothing: an FX adjustment inserted, rewritten and deleted, a revaluation row inserted, rewritten and
      deleted, and a portal session inserted and deleted; the rows are untouched afterwards. Every one of them but the TRUNCATE works
      without this migration (the migrations that created the tables granted INSERT, UPDATE and DELETE; TRUNCATE only the platform's
      defaults do, and the worst-case test above covers that revoke), which is the negative control.
    * THE POLICIES (for each of the three): the two exist (six in all), RESTRICTIVE and FOR ALL, in the once-per-query form of
      migrations 525 to 536; a Partner reads every row, a Manager, Executive and Reviewer assigned to A read A's and nothing else, a
      person assigned to nothing, a suspended Partner, a Partner of another firm and a principal with no member row read none; the
      internal practice is a Partner's even for a person assigned to it; a firm that never set up its practice still shows an assigned
      member their client's row.
    * THE POLICIES ARE THE SECOND LOCK: with the writes granted back in a throwaway database an assigned Manager writes their own
      client's row and is refused another's and the practice's, an update or a delete of another client's row matches nothing, a row
      cannot be MOVED to a client the person may not see, and a Partner writes for every client. (No role tier is added: the revoked
      grant is the control, and the routes ask the role.)
    * NOTHING THE PRODUCT DOES BREAKS: the service role inserts, updates and deletes all three, and an assigned member still reads
      their client's rows.
    * THE LOCKS: the policy and grant statements of both files sit inside one DO block that first asks for the three tables' lock
      WITHOUT QUEUEING (a busy table is waited for, nothing queues behind us, and a table that stays busy fails the file after
      fifteen seconds in its own words and changes nothing); the migration also turns row security ON for the three tables and its
      closing check fails when it is off.
    * THE ROLLBACK gives back what 149, 156 and 194 granted and the forgery works again (the negative control); a re-apply ends it; a
      second run changes nothing; and the plan asks the caller's clients once per query.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the FX record and portal session proof requires HARNESS_PG + psql",
)

FIRM = "54200000-0000-0000-0000-000000000001"
OTHER_FIRM = "54200000-0000-0000-0000-000000000002"
CLIENT_A = "54200000-0000-0000-0000-0000000000a1"
CLIENT_B = "54200000-0000-0000-0000-0000000000b2"
INTERNAL = "54200000-0000-0000-0000-0000000000c3"
STRANGER = "54200000-1111-0000-0000-0000000000ff"          # an authenticated principal with NO users row (an employee, a portal contact)
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("54200000-0000-0000-0000-00000000000a", "54200000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("54200000-0000-0000-0000-00000000000b", "54200000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_none": ("54200000-0000-0000-0000-00000000000c", "54200000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("54200000-0000-0000-0000-00000000000e", "54200000-1111-0000-0000-000000000004", "Executive", FIRM),
    "reviewer_a": ("54200000-0000-0000-0000-000000000011", "54200000-1111-0000-0000-000000000007", "Reviewer", FIRM),
    "reviewer_none": ("54200000-0000-0000-0000-000000000012", "54200000-1111-0000-0000-000000000008", "Reviewer", FIRM),
    "suspended": ("54200000-0000-0000-0000-00000000000f", "54200000-1111-0000-0000-000000000005", "Partner", FIRM),
    "other_firm": ("54200000-0000-0000-0000-000000000010", "54200000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}

_STEM = "542_the_fx_record_tables_and_the_portal_session_log_are_written_by_the_api_only_and_read_by_the_assigned"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

_F = f"'{FIRM}'"


def _cl(client: str) -> str:
    return f"'{client}'"


_SESSION_COLS = "(firm_id, client_id, email)"

# one entry per table: seed(client) is an admin INSERT of the client's row; insert(client) is a FRESH row for that client,
# written as the person under test
SPECS: dict[str, dict] = {
    "fx_adjustments": {
        "seed": lambda c: f"INSERT INTO fx_adjustments (firm_id, client_id, kind, currency, base_delta_paise) VALUES ({_F}, {_cl(c)}, 'realized', 'USD', 100)",
        "insert": lambda c: f"INSERT INTO fx_adjustments (firm_id, client_id, kind, currency, base_delta_paise) VALUES ({_F}, {_cl(c)}, 'unrealized', 'USD', 200)",
        "touch": "base_delta_paise = base_delta_paise",
    },
    "fx_revaluations": {
        "seed": lambda c: f"INSERT INTO fx_revaluations (firm_id, client_id, period_end, currency, item_type, closing_rate, target_adjustment_paise, delta_paise) VALUES ({_F}, {_cl(c)}, '2026-03-31', 'USD', 'receivable', 84, 400, 400)",
        "insert": lambda c: f"INSERT INTO fx_revaluations (firm_id, client_id, period_end, currency, item_type, closing_rate, target_adjustment_paise, delta_paise) VALUES ({_F}, {_cl(c)}, '2026-06-30', 'USD', 'payable', 85, 500, 500)",
        "touch": "delta_paise = delta_paise",
    },
    "client_portal_sessions": {
        "seed": lambda c: f"INSERT INTO client_portal_sessions {_SESSION_COLS} VALUES ({_F}, {_cl(c)}, 'contact-{c[-2:]}@t.in')",
        "insert": lambda c: f"INSERT INTO client_portal_sessions {_SESSION_COLS} VALUES ({_F}, {_cl(c)}, 'fresh-{c[-2:]}@t.in')",
        "touch": "email = email",
    },
}
TABLES = list(SPECS)
POLICIES = {t: [f"{t}_assignment_scope", f"{t}_internal_partner_only"] for t in TABLES}
EXPECTED_READS = {"partner": 3, "manager_a": 1, "manager_none": 0, "executive_a": 1, "reviewer_a": 1, "reviewer_none": 0,
                  "suspended": 0, "other_firm": 0}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _sub(who: str) -> str:
    return STRANGER if who == "stranger" else PEOPLE[who][1]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{_sub(who)}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _lines_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _count_as(dsn: str, who: str, table: str) -> int:
    return int(_lines_as(dsn, who, f"SELECT count(*) FROM {table};")[-1])


def _count_op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err'; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _grant_writes(dsn: str) -> None:
    """The throwaway database only: give the signed-in role the writes 519 took away, so the policies' WITH CHECK is what is
    being asked (the second lock) and not the missing grant."""
    for table in TABLES:
        done = _psql(dsn, f"GRANT INSERT, UPDATE, DELETE ON public.{table} TO authenticated;")
        assert done.returncode == 0, done.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e542_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items()) + f", ('{STRANGER}', 'employee@t.in')"
        members = ", ".join(
            f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', {'false' if n == 'suspended' else 'true'})"
            for n, (i, a, r, f) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                 VALUES ('{INTERNAL}', '{FIRM}', 'The practice', 'Proprietorship', true);
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["reviewer_a"][0]}', '{CLIENT_A}');
        """)
        assert seed.returncode == 0, seed.stderr
        for table, spec in SPECS.items():
            for client in (CLIENT_A, CLIENT_B, INTERNAL):
                done = _psql(d, spec["seed"](client))
                assert done.returncode == 0, f"seeding {table} for {client}: {done.stderr}"
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE POLICIES ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_the_policies_are_restrictive_for_all_and_ask_the_callers_clients_once_per_query(dsn, table):
    for name in POLICIES[table]:
        got = _rows(dsn, f"""SELECT p.polpermissive, p.polcmd, regexp_replace(pg_get_expr(p.polqual, p.polrelid), '\\s+', ' ', 'g'),
                                    regexp_replace(pg_get_expr(p.polwithcheck, p.polrelid), '\\s+', ' ', 'g')
                               FROM pg_policy p WHERE p.polrelid = 'public.{table}'::regclass AND p.polname = '{name}'""")
        assert got, f"{table} has no {name} policy"
        permissive, cmd, qual, check = got[0]
        assert permissive == "f" and cmd == "*", f"{name} is not RESTRICTIVE FOR ALL: {got[0]}"
        assert qual and check, f"{name} has no USING or no WITH CHECK"
        assert "can_access_client" not in qual + check, f"{name} calls can_access_client once per row"
        if name.endswith("_assignment_scope"):
            assert "my_assigned_client_ids" in qual and "my_assigned_client_ids" in check, got[0]
            assert "Partner" in qual and "Partner" in check, f"{name}: a Partner's branch is missing from the USING or the WITH CHECK"
        else:
            assert "my_internal_client_id" in qual and "Partner" in qual, got[0]
            assert "my_internal_client_id" in check and "Partner" in check, f"{name}: the WITH CHECK lost the guard or the Partner branch"


# ── WHO SEES WHAT ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_each_person_reads_only_the_rows_of_the_clients_they_may_see(dsn, table):
    seen = {who: _count_as(dsn, who, table) for who in PEOPLE}
    assert seen == EXPECTED_READS, f"{table}: {seen}"


@pytest.mark.parametrize("table", TABLES)
def test_the_internal_practice_is_a_partners_even_for_a_person_assigned_to_it(dsn, table):
    for who in ("manager_a", "reviewer_a"):
        assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                          f"VALUES ('{FIRM}', '{PEOPLE[who][0]}', '{INTERNAL}');").returncode == 0
    for who in ("manager_a", "reviewer_a"):
        assert _count_as(dsn, who, table) == EXPECTED_READS[who], (
            f"{table}: an assignment to the internal practice opened its row to {who}")
    assert _count_as(dsn, "partner", table) == EXPECTED_READS["partner"]


@pytest.mark.parametrize("table", TABLES)
def test_in_a_firm_that_never_set_up_its_internal_practice_an_assigned_member_still_reads_their_clients_row(dsn, table):
    """`firms.internal_client_id` is NULL for a firm whose onboarding never provisioned its practice (migration 405 measured one
    of two firms in that state). The guard compares the row's client with it, and `NULL <> x` is NULL, so a guard written with
    `<>` instead of `IS DISTINCT FROM` hid every row from every non-Partner of such a firm. The clients stay behind the scope."""
    assert _psql(dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    assert {who: _count_as(dsn, who, table) for who in ("partner", "manager_a", "executive_a", "reviewer_a", "manager_none", "reviewer_none")} == {
        "partner": 3, "manager_a": 1, "executive_a": 1, "reviewer_a": 1, "manager_none": 0, "reviewer_none": 0}, table


@pytest.mark.parametrize("table", TABLES)
def test_the_scope_holds_the_line_without_the_firm_policy(dsn, table):
    """A principal with no member row, a suspended Partner and a person assigned to nothing read none because the FIRM policy
    says so, and they would read none if these policies did not exist. Widen the firm policy in this throwaway database (a
    permissive `USING (true)` for the signed-in role) and ask again: what is left is the scope itself, and a role that is
    NULL (no member row) must come out as a denial and not as a pass."""
    assert _psql(dsn, f'CREATE POLICY "widened" ON public.{table} FOR SELECT TO authenticated USING (true);').returncode == 0
    seen = {who: _count_as(dsn, who, table) for who in ("stranger", "suspended", "manager_none", "reviewer_none", "manager_a", "reviewer_a", "partner")}
    assert seen == {"stranger": 0, "suspended": 0, "manager_none": 0, "reviewer_none": 0, "manager_a": 1, "reviewer_a": 1, "partner": 3}, (
        f"{table}: {seen}")


@pytest.mark.parametrize("table", TABLES)
def test_a_signed_in_principal_with_no_member_row_reads_none_before_and_after(dsn, table):
    """An employee or a portal contact has no `users` row, so the firm policy never gave them these tables: there is no branch
    to keep, and none was lost."""
    assert _count_as(dsn, "stranger", table) == 0
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    assert _count_as(dsn, "stranger", table) == 0, f"{table}: the firm policy let a principal with no member row in"


# ── THE WRITE SIDE ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_a_signed_in_role_effectively_holds_no_write_on_the_table_at_any_level_and_still_reads_it(dsn, table):
    for role in ("authenticated", "anon"):
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{verb}')") == [["f"]], (table, role, verb)
        for verb in ("INSERT", "UPDATE"):
            assert _rows(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{table}', '{verb}')") == [["f"]], (table, role, verb)
    held = _rows(dsn, f"""SELECT a.privilege_type FROM pg_class c, aclexplode(c.relacl) a
                           WHERE c.oid = 'public.{table}'::regclass AND a.grantee = 0""")          # grantee 0 is PUBLIC
    assert held == [], f"{table}: PUBLIC holds {held}"
    assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT')") == [["t"]]
    assert _rows(dsn, f"SELECT has_table_privilege('anon', 'public.{table}', 'SELECT')") == [["f"]]
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', '{verb}')") == [["t"]], (table, verb)


def test_the_migration_takes_every_privilege_away_from_a_database_that_granted_them_all(dsn):
    """Production's platform defaults grant a good deal more than a database built from the migrations does (anon and
    service_role directly; PUBLIC is added here as a harmless superset), so the revocation is proved from the worst case: grant
    everything first, then apply the migration."""
    for table in TABLES:
        assert _psql(dsn, f"GRANT ALL ON public.{table} TO PUBLIC, anon, authenticated;").returncode == 0
    assert _rows(dsn, "SELECT has_table_privilege('anon', 'public.fx_adjustments', 'UPDATE')") == [["t"]], "the fixture must start open"
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for table in TABLES:
        for role in ("authenticated", "anon"):
            for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{verb}')") == [["f"]], (table, role, verb)
        held = _rows(dsn, f"SELECT a.privilege_type FROM pg_class c, aclexplode(c.relacl) a "
                          f"WHERE c.oid = 'public.{table}'::regclass AND a.grantee = 0")
        assert held == [], (table, held)
        assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT')") == [["t"]]
        assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', 'INSERT')") == [["t"]]


def test_the_migration_gives_the_signed_in_role_its_read_back_on_a_database_that_held_none(dsn):
    """The worst case above starts from `GRANT ALL`, where the signed-in role already holds SELECT, so a migration that forgot to
    grant it would pass. Start from the other end: a database where `authenticated` holds nothing on the three tables, and the
    migration must hand back exactly the read (and the service role keeps its writes)."""
    for table in TABLES:
        assert _psql(dsn, f"REVOKE ALL ON public.{table} FROM PUBLIC, anon, authenticated;").returncode == 0
        assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT')") == [["f"]], "the fixture must start closed"
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for table in TABLES:
        assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', 'SELECT')") == [["t"]], table
        for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', '{verb}')") == [["f"]], (table, verb)
        assert _rows(dsn, f"SELECT has_table_privilege('anon', 'public.{table}', 'SELECT')") == [["f"]], table
        assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', 'INSERT')") == [["t"]], table


# ── THE FORGERIES THE REVIEW REPRODUCED ─────────────────────────────────────────

DENIED = "permission denied for table"


@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "reviewer_a", "manager_none", "reviewer_none"])
def test_every_forgery_is_refused_by_the_privilege_and_the_rows_are_untouched(dsn, who):
    def digest(t):       # the row count and a digest of every row's content, so that "untouched" means the values and not just the count
        return _rows(dsn, f"SELECT count(*), md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) FROM {t} x")
    before = {t: digest(t) for t in TABLES}
    forgeries = {
        "insert an FX adjustment": SPECS["fx_adjustments"]["insert"](CLIENT_A),
        "rewrite an FX adjustment": f"UPDATE fx_adjustments SET base_delta_paise = 99999999 WHERE client_id = '{CLIENT_A}'",
        "delete an FX adjustment": f"DELETE FROM fx_adjustments WHERE client_id = '{CLIENT_A}'",
        "insert a revaluation run": SPECS["fx_revaluations"]["insert"](CLIENT_A),
        "rewrite a revaluation run": f"UPDATE fx_revaluations SET delta_paise = 99999999 WHERE client_id = '{CLIENT_A}'",
        "delete a revaluation run": f"DELETE FROM fx_revaluations WHERE client_id = '{CLIENT_A}'",
        "insert a portal session": SPECS["client_portal_sessions"]["insert"](CLIENT_A),
        "delete a portal session": f"DELETE FROM client_portal_sessions WHERE client_id = '{CLIENT_A}'",
        "truncate the FX adjustments": "TRUNCATE fx_adjustments",
    }
    for label, sql in forgeries.items():
        r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + sql], capture_output=True, text=True)
        assert r.returncode != 0 and DENIED in r.stderr, (who, label, r.stderr[-200:])
    assert {t: digest(t) for t in TABLES} == before
    assert _rows(dsn, "SELECT base_delta_paise FROM fx_adjustments WHERE client_id = '%s'" % CLIENT_A) == [["100"]]
    assert _rows(dsn, "SELECT delta_paise FROM fx_revaluations WHERE client_id = '%s'" % CLIENT_A) == [["400"]]


# ── NOTHING THE PRODUCT DOES BREAKS ─────────────────────────────────────────────

def test_the_service_role_inserts_updates_and_deletes_all_three_tables(dsn):
    def as_service(sql: str) -> subprocess.CompletedProcess:
        return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", "SET ROLE service_role; " + sql],
                              capture_output=True, text=True)
    for table in TABLES:
        spec = SPECS[table]
        done = as_service(f"{spec['insert'](CLIENT_A)}; UPDATE {table} SET {spec['touch']} WHERE client_id = '{CLIENT_A}';")
        assert done.returncode == 0, (table, done.stderr)
    for table in TABLES:
        assert as_service(f"DELETE FROM {table} WHERE client_id = '{CLIENT_B}'").returncode == 0, table


@pytest.mark.parametrize("who", ["manager_a", "executive_a", "reviewer_a"])
def test_an_assigned_member_still_reads_their_clients_rows_and_nobody_elses(dsn, who):
    """What the API does under the caller's own sign-in (USE_USER_JWT): the FX reports, the vendor statement and the health score read
    these tables, and SELECT is kept."""
    for table in TABLES:
        assert _lines_as(dsn, who, f"SELECT client_id FROM {table} ORDER BY 1;")[-1] == CLIENT_A, table


@pytest.mark.parametrize("table", TABLES)
def test_an_assigned_member_writes_for_their_client_and_is_refused_for_another_once_writes_are_granted(dsn, table):
    """The second lock: with the writes granted in this throwaway database the policies' WITH CHECK is what refuses."""
    spec = SPECS[table]
    _grant_writes(dsn)
    for client in (CLIENT_A, CLIENT_B, INTERNAL):          # the unique key holds the client: clear the seeded rows first
        assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{client}'").returncode == 0
    assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_A)) == "1", f"an assigned Manager cannot add a {table} row for their own client"
    assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_B)) == "err", f"a {table} row was added for a client the Manager is not assigned to"
    assert _count_op(dsn, "manager_none", spec["insert"](CLIENT_A)) == "err", f"a Manager assigned to nothing added a {table} row"
    assert _count_op(dsn, "manager_a", spec["insert"](INTERNAL)) == "err", f"a Manager (not assigned to it) added a {table} row for the practice"
    # no role tier is added here on purpose: the REVOKED GRANT is the control (the routes ask the role), so with the grant
    # given back an assigned Executive writes their client's row and the scope still refuses every other client's
    assert _count_op(dsn, "executive_a", spec["insert"](CLIENT_A)) == "1", f"an assigned Executive cannot write their own client's {table} row"
    assert _count_op(dsn, "executive_a", spec["insert"](CLIENT_B)) == "err", f"an assigned Executive added a {table} row for another client"
    assert _count_op(dsn, "reviewer_a", spec["insert"](CLIENT_B)) == "err", f"an assigned Reviewer added a {table} row for another client"


@pytest.mark.parametrize("table", TABLES)
def test_an_assigned_manager_who_is_also_assigned_to_the_practice_is_refused_its_row_by_the_guard_alone(dsn, table):
    spec = SPECS[table]
    _grant_writes(dsn)
    assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                      f"VALUES ('{FIRM}', '{PEOPLE['manager_a'][0]}', '{INTERNAL}');").returncode == 0
    assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{INTERNAL}'").returncode == 0
    assert _count_op(dsn, "manager_a", spec["insert"](INTERNAL)) == "err", (
        f"{table}: a Manager assigned to the practice added its row: only the internal-practice guard can refuse it")


@pytest.mark.parametrize("table", TABLES)
def test_an_update_or_a_delete_of_another_clients_row_matches_nothing_and_a_row_cannot_be_moved(dsn, table):
    spec = SPECS[table]
    _grant_writes(dsn)
    touch = spec["touch"]
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE client_id = '{CLIENT_B}'") == "0", f"updated another client's {table} row"
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE client_id = '{CLIENT_B}'") == "0", f"deleted another client's {table} row"
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE client_id = '{CLIENT_A}'") == "1", f"cannot update their own client's {table} row"
    assert _count_op(dsn, "manager_none", f"UPDATE {table} SET {touch} WHERE client_id = '{CLIENT_A}'") == "0", "a person assigned to nothing updated a row"
    assert _count_op(dsn, "manager_none", f"DELETE FROM {table} WHERE client_id = '{CLIENT_A}'") == "0", "a person assigned to nothing deleted a row"
    assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{CLIENT_B}'").returncode == 0     # so only a policy can refuse the move
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "err", (
        f"an assigned Manager moved a {table} row to a client they are not assigned to")
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE client_id = '{CLIENT_A}'") == "1", f"cannot delete their own client's {table} row"


@pytest.mark.parametrize("table", TABLES)
def test_a_partner_writes_for_every_client_the_internal_practice_included(dsn, table):
    """The WITH CHECK keeps the Partner branch: a slip that dropped it from the scope or the guard would lock the owner out."""
    spec = SPECS[table]
    _grant_writes(dsn)
    for client in (CLIENT_A, CLIENT_B, INTERNAL):
        assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{client}'").returncode == 0
    for client in (CLIENT_A, CLIENT_B, INTERNAL):
        assert _count_op(dsn, "partner", spec["insert"](client)) == "1", f"a Partner cannot add a {table} row for {client}"


@pytest.mark.parametrize("table", TABLES)
def test_a_partner_moves_a_row_to_another_client_and_to_the_internal_practice(dsn, table):
    _grant_writes(dsn)
    for client in (CLIENT_B, INTERNAL):
        assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{client}'").returncode == 0
    assert _count_op(dsn, "partner", f"UPDATE {table} SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "1", (
        f"a Partner cannot move a {table} row to another client")
    assert _count_op(dsn, "partner", f"UPDATE {table} SET client_id = '{INTERNAL}' WHERE client_id = '{CLIENT_A}'") == "1", (
        f"a Partner cannot move a {table} row to the internal practice")


# ── THE ROLLBACK, AND THE PLAN ──────────────────────────────────────────────────

def test_the_rollback_returns_the_firm_wide_read_and_a_reapply_hides_the_rows_again(dsn):
    before = {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in TABLES}
    assert all(v["manager_none"] == 0 for v in before.values()), before

    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    for table in TABLES:
        assert _count_as(dsn, "manager_none", table) == 3, f"after the rollback {table} is not firm-wide again"
        assert not _rows(dsn, f"SELECT 1 FROM pg_policy WHERE polrelid = 'public.{table}'::regclass AND polname = ANY(ARRAY{POLICIES[table]})")

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in TABLES} == before


def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it_again(dsn):
    forge = f"UPDATE fx_revaluations SET delta_paise = 99999999 WHERE client_id = '{CLIENT_A}'"
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as("reviewer_a") + forge], capture_output=True, text=True)
    assert r.returncode != 0 and DENIED in r.stderr
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as("reviewer_a") + forge], capture_output=True, text=True)
    assert r.returncode == 0, f"after the rollback the Reviewer's forgery works again (the negative control): {r.stderr}"
    # the rollback gives back exactly what the migrations had granted, table by table (a rollback that forgot one table's
    # grant would leave the forgery closed on it and the test above green)
    restored = {table: ("SELECT", "INSERT", "UPDATE", "DELETE") for table in TABLES}
    for table, privileges in restored.items():
        for privilege in privileges:
            assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{table}', '{privilege}')") == [["t"]], (
                f"the rollback did not give {privilege} on {table} back to the signed-in role")
    for _ in range(2):
        assert _psql_file(dsn, MIGRATION).returncode == 0
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as("reviewer_a") + forge], capture_output=True, text=True)
    assert r.returncode != 0 and DENIED in r.stderr


def test_a_second_run_of_the_migration_changes_nothing(dsn):
    def snapshot() -> list:
        return _rows(dsn, "SELECT c.relname, p.polname, p.polpermissive, p.polcmd, pg_get_expr(p.polqual, p.polrelid), "
                          "pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                          f"WHERE c.relname = ANY(ARRAY{TABLES}) ORDER BY 1, 2")
    first = snapshot()
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert snapshot() == first


@pytest.mark.parametrize("table", TABLES)
def test_a_signed_in_scan_asks_the_callers_clients_once(dsn, table):
    lines = _lines_as(dsn, "manager_a", f"EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM {table};")
    plan = "\n".join(lines)
    assert "can_access_client" not in plan, plan
    assert re.search(r"hashed SubPlan \d+", plan) and "my_assigned_client_ids()" in plan, plan
    # the role and the practice are asked ONCE (an InitPlan), not per row: a bare call would sit in the Filter itself
    filters = " ".join(line for line in lines if "Filter:" in line)
    assert "get_my_role()" not in filters and "my_internal_client_id()" not in filters, (
        f"{table}: a helper is called once per row, not once per query:\n{plan}")
    assert "get_my_role()" in plan and "my_internal_client_id()" in plan and plan.count("InitPlan") >= 2, plan


# ── THE LOCKS, AND THE MIGRATION'S OWN CHECK ────────────────────────────────────

def _dollar_quoted_bodies(sql: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"\$(\w*)\$(.*?)\$\1\$", sql, flags=re.S)]


def _outside_the_bodies(sql: str) -> str:
    return re.sub(r"\$(\w*)\$.*?\$\1\$", " ", sql, flags=re.S)


@pytest.mark.parametrize("path, creates", [(MIGRATION, True), (ROLLBACK, False)], ids=["migration", "rollback"])
def test_the_statements_that_lock_the_tables_run_inside_one_block(path, creates):
    """DROP POLICY, CREATE POLICY and ALTER TABLE take ACCESS EXCLUSIVE on the table until the migration commits (GRANT and REVOKE take
    no table lock and sit in the block so that the file is one unit), and the runner sends a top-level statement per round trip, so a
    lock taken at the top level is held across every round trip that follows."""
    sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    left = re.findall(r"\b(?:CREATE\s+POLICY|DROP\s+POLICY|GRANT|REVOKE|LOCK\s+TABLE|ALTER\s+TABLE)\b[^;]*", _outside_the_bodies(sql), flags=re.I)
    assert left == [], f"a statement that takes a table lock stands at the top level: {left[:2]}"
    holders = [b for b in _dollar_quoted_bodies(sql) if re.search(r"\b(?:CREATE|DROP)\s+POLICY\b", b, flags=re.I)]
    assert len(holders) == 1, f"{len(holders)} blocks hold the policy statements, expected exactly one"
    assert len(re.findall(r"\bDROP POLICY IF EXISTS\b", holders[0])) == 6
    # the lock is asked for on all three tables at once, without queueing, and retried
    lock = re.findall(r"\bLOCK TABLE\b([^;]*);", holders[0])
    assert len(lock) == 1 and all(f"public.{t}" in lock[0] for t in TABLES) and "NOWAIT" in lock[0] and "ACCESS EXCLUSIVE" in lock[0], lock
    assert "lock_not_available" in holders[0] and "pg_sleep" in holders[0]
    assert "set_config('lock_timeout'" in sql, "the file no longer sets a lock timeout"
    if creates:
        assert len(re.findall(r"\bCREATE POLICY\b", holders[0])) == 6
        assert len(re.findall(r"\bREVOKE ALL\b", holders[0])) == 3
        assert len(re.findall(r"\bENABLE ROW LEVEL SECURITY\b", holders[0])) == 3
        assert len(re.findall(r"\bGRANT SELECT, INSERT, UPDATE, DELETE ON public\.\w+ TO service_role\b", holders[0])) == 3


@pytest.mark.parametrize("table", TABLES)
def test_the_closing_check_refuses_a_write_the_signed_in_role_holds_again(dsn, table):
    """The check at the end of the migration reads the ACL itself: run alone, after a write has been granted back, it must fail the
    migration, and for a table-level grant, a column-level one and a grant through PUBLIC alike."""
    sql = MIGRATION.read_text(encoding="utf-8")
    check = sql[sql.rindex("DO $$"):]
    assert _psql(dsn, check).returncode == 0, "the check fails on a database the migration has been applied to"
    for grant in (f"GRANT UPDATE ON public.{table} TO authenticated", f"GRANT INSERT (firm_id) ON public.{table} TO authenticated",
                  f"GRANT DELETE ON public.{table} TO PUBLIC", f"GRANT SELECT ON public.{table} TO anon"):
        assert _psql(dsn, grant).returncode == 0
        refused = _psql(dsn, check)
        assert refused.returncode != 0 and "migration 542" in refused.stderr, (table, grant, refused.stderr[-200:])
        assert _psql_file(dsn, MIGRATION).returncode == 0, "re-applying the migration does not take the grant away again"


@pytest.mark.parametrize("table", TABLES)
def test_the_closing_check_refuses_a_table_that_lost_a_policy_or_that_the_signed_in_role_can_no_longer_read(dsn, table):
    sql = MIGRATION.read_text(encoding="utf-8")
    check = sql[sql.rindex("DO $$"):]
    assert _psql(dsn, f'DROP POLICY "{table}_internal_partner_only" ON public.{table};').returncode == 0
    refused = _psql(dsn, check)
    assert refused.returncode != 0 and "does not carry its two restrictive policies" in refused.stderr, refused.stderr[-200:]
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _psql(dsn, f"REVOKE SELECT ON public.{table} FROM authenticated;").returncode == 0
    refused = _psql(dsn, check)
    assert refused.returncode != 0 and "no longer reads" in refused.stderr, refused.stderr[-200:]
    assert _psql(dsn, f"REVOKE DELETE ON public.{table} FROM service_role;").returncode == 0
    assert _psql(dsn, f"GRANT SELECT ON public.{table} TO authenticated;").returncode == 0
    refused = _psql(dsn, check)
    assert refused.returncode != 0 and "cannot DELETE" in refused.stderr, refused.stderr[-200:]


def _check_alone() -> str:
    sql = MIGRATION.read_text(encoding="utf-8")
    return sql[sql.rindex("DO $$"):]


SPOILS = (
    # what the signed-in role may no longer hold, every verb and every level
    [f"GRANT {verb} ON public.fx_revaluations TO authenticated" for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")]
    + [f"GRANT {verb} ON public.client_portal_sessions TO anon" for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")]
    + [f"GRANT {verb} ON public.fx_adjustments TO PUBLIC" for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")]
    + ["GRANT UPDATE (client_id) ON public.fx_adjustments TO authenticated", "GRANT REFERENCES (client_id) ON public.fx_revaluations TO authenticated",
       "GRANT SELECT (client_id) ON public.client_portal_sessions TO anon", "GRANT INSERT (client_id) ON public.fx_adjustments TO anon"]
    # what the service role must keep
    + [f"REVOKE {verb} ON public.fx_revaluations FROM service_role" for verb in ("SELECT", "INSERT", "UPDATE", "DELETE")]
    # what the signed-in role must keep, and the switch every policy hangs from
    + ["REVOKE SELECT ON public.client_portal_sessions FROM authenticated", "ALTER TABLE public.fx_adjustments DISABLE ROW LEVEL SECURITY",
       "ALTER TABLE public.client_portal_sessions DISABLE ROW LEVEL SECURITY"]
    # the two restrictive policies, each of the three ways one can be spoiled: made permissive, narrowed to one command, dropped
    + ["DROP POLICY fx_adjustments_assignment_scope ON public.fx_adjustments; "
       "CREATE POLICY fx_adjustments_assignment_scope ON public.fx_adjustments USING (true)",
       "DROP POLICY client_portal_sessions_internal_partner_only ON public.client_portal_sessions; "
       "CREATE POLICY client_portal_sessions_internal_partner_only ON public.client_portal_sessions AS RESTRICTIVE FOR SELECT USING (true)",
       "DROP POLICY fx_revaluations_assignment_scope ON public.fx_revaluations"]
)


@pytest.mark.parametrize("spoil", SPOILS)
def test_the_closing_check_refuses_each_spoiled_state(dsn, spoil):
    """Run alone after one spoiling statement each: every verb, level and grantee the check claims to read, the service role's four,
    the signed-in role's read, and row security itself. (The review proved the shipped block sound by hand; this keeps it so.)"""
    assert _psql(dsn, _check_alone()).returncode == 0, "the check fails on a database the migration has been applied to"
    assert _psql(dsn, spoil).returncode == 0
    refused = _psql(dsn, _check_alone())
    assert refused.returncode != 0 and "migration 542" in refused.stderr, (spoil, refused.stderr[-200:])


def test_the_migration_turns_row_security_back_on(dsn):
    """Every policy means nothing with row security off; the migration enables it (a no-op where it is on) and the check asks."""
    assert _psql(dsn, "ALTER TABLE public.fx_revaluations DISABLE ROW LEVEL SECURITY;").returncode == 0
    assert _rows(dsn, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.fx_revaluations'::regclass") == [["f"]], "the worst case was not made"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _rows(dsn, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.fx_revaluations'::regclass") == [["t"]]


def test_the_service_roles_four_privileges_are_granted_explicitly_not_inherited(dsn):
    """In the harness the service role holds its privileges directly, so a migration that forgot the explicit GRANT would pass; take
    them away first and see the migration give them back."""
    for table in TABLES:
        assert _psql(dsn, f"REVOKE ALL ON public.{table} FROM service_role;").returncode == 0
    assert _rows(dsn, "SELECT has_table_privilege('service_role', 'public.fx_revaluations', 'INSERT')") == [["f"]], "the worst case was not made"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    for table in TABLES:
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{table}', '{verb}')") == [["t"]], (table, verb)


def _hold(dsn: str, table: str, mode: str, seconds: int) -> subprocess.Popen:
    holder = subprocess.Popen(["psql", dsn, "-X", "-q", "-c", f"BEGIN; LOCK TABLE public.{table} IN {mode} MODE; SELECT pg_sleep({seconds}); COMMIT;"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for _ in range(40):
        held = _rows(dsn, f"SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.relation = 'public.{table}'::regclass "
                          "AND l.granted AND a.query LIKE 'BEGIN; LOCK TABLE%'")
        if held[0][0] != "0":
            return holder
        time.sleep(0.25)
    holder.kill()
    raise AssertionError("the holder never took its lock")


@pytest.mark.parametrize("path", [MIGRATION, ROLLBACK], ids=["migration", "rollback"])
def test_a_busy_table_is_waited_for_without_holding_the_others_and_the_file_then_applies(dsn, path):
    """ACCESS EXCLUSIVE conflicts with everything, so even a reader of fx_revaluations is waited for; while it is, the file holds NOTHING
    (a third session reads the other two tables throughout), and once the holder commits the file applies."""
    holder = _hold(dsn, "fx_revaluations", "ACCESS SHARE", 5)
    started = time.monotonic()
    runner = subprocess.Popen(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(3):
            time.sleep(0.9)
            assert runner.poll() is None, "the file finished while a table was still held"
            for table in ("fx_adjustments", "client_portal_sessions"):
                probe = _psql(dsn, f"SET lock_timeout = '1500ms'; BEGIN; LOCK TABLE public.{table} IN ACCESS SHARE MODE; COMMIT;")
                assert probe.returncode == 0, f"{table} was held while the file waited for fx_revaluations: {probe.stderr}"
        _out, err = runner.communicate(timeout=60)
    finally:
        holder.wait(timeout=60)
        if runner.poll() is None:
            runner.kill()
    assert runner.returncode == 0, err
    assert time.monotonic() - started >= 3.5, "it did not wait for the holder"


def test_a_table_that_stays_busy_fails_the_migration_after_fifteen_seconds_in_its_own_words_and_changes_nothing(dsn):
    def state():
        return _rows(dsn, "SELECT c.relname, coalesce(c.relacl::text, ''), c.relrowsecurity::text, "
                          "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)::text FROM pg_class c "
                          "WHERE c.relname IN ('fx_adjustments', 'fx_revaluations', 'client_portal_sessions') AND c.relkind = 'r' ORDER BY 1")
    before = state()
    holder = _hold(dsn, "client_portal_sessions", "ACCESS SHARE", 40)
    try:
        started = time.monotonic()
        done = _psql_file(dsn, MIGRATION)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert done.returncode != 0 and "could not lock the three FX and portal tables in 15 seconds" in done.stderr, done.stderr
    assert 13 <= waited <= 25, waited
    assert state() == before
