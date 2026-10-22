"""A client's year locks are visible to the members who post into that client, and written by the API alone (migration 532,
POST-A-314, the third tranche of POST-A-299).

WHAT WAS WRONG
    Migration 289 wrote the only policy of `client_year_locks` as `firm_id = (auth.jwt() ->> 'firm_id')::uuid`, a claim this
    project never issues, so row security refused every row of the table to every signed-in session (the shape migration 154
    found on three other families of tables). Two things follow once the API runs under the caller's sign-in, which is the
    production default:
      * the INSERT that locks a client's year when its year-end is finalised is refused, after the engagement was written as
        `locked`;
      * `period_closure_reason` and `period_lock_reason` are SECURITY INVOKER and read the table directly, so under a signed-in
        session they answer NULL (open) for a year the administrator sees as closed. The posting kernel asks the first, with
        the request's own client, and the pre-checks of documents ask the second: a finalised year did not stop a signed-in
        session posting into it.

WHAT THIS HOLDS
    * THE POLICIES: the canonical firm policy (FOR ALL, `get_my_firm_id()` in the USING and the WITH CHECK, no token claim),
      the two RESTRICTIVE FOR ALL policies every client table carries (the caller's clients asked once per query, the internal
      practice a Partner's), and three RESTRICTIVE write policies that ask for a Partner.
    * WHO SEES WHAT: a Partner reads every lock of the firm; a Manager, an Executive and a Reviewer assigned to a client read
      that client's locks and nobody else's; a person assigned to nothing, a suspended Partner, a Partner of another firm and a
      signed-in principal with no member row read none; the internal practice's lock is a Partner's even for a person assigned to
      it; and in a firm with no internal practice an assigned member still reads their client's lock.
    * THE CHECKS SEE THE LOCK: `period_closure_reason` and `period_lock_reason`, asked as each person, answer the sentence for
      the clients that person can reach and NULL for the others; with the migration rolled back every signed-in person,
      a Partner included, gets NULL for a year the administrator reads as closed (the defect, reproduced).
    * THE WRITE SIDE IS THE API'S: the signed-in roles hold no INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES or TRIGGER on the
      table at table or column level and anon reads nothing; and, with the writes granted in a throwaway database, the policies
      are the second lock: a Partner writes for their firm, and a Manager, an Executive and a Reviewer, however assigned, are
      refused, an update or delete of a lock by anyone else matches nothing, and a Partner of another firm cannot touch it.
    * THE ROLLBACK restores migration 289's state exactly and a re-apply restores this one; a second run changes nothing.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
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
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the year-lock proof requires HARNESS_PG + psql",
)

FIRM = "53200000-0000-0000-0000-000000000001"
OTHER_FIRM = "53200000-0000-0000-0000-000000000002"
CLIENT_A = "53200000-0000-0000-0000-0000000000a1"
CLIENT_B = "53200000-0000-0000-0000-0000000000b2"
INTERNAL = "53200000-0000-0000-0000-0000000000c3"
STRANGER = "53200000-1111-0000-0000-0000000000ff"          # an authenticated principal with NO users row (an employee, a portal contact)
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("53200000-0000-0000-0000-00000000000a", "53200000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("53200000-0000-0000-0000-00000000000b", "53200000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_none": ("53200000-0000-0000-0000-00000000000c", "53200000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("53200000-0000-0000-0000-00000000000e", "53200000-1111-0000-0000-000000000004", "Executive", FIRM),
    "reviewer_a": ("53200000-0000-0000-0000-000000000011", "53200000-1111-0000-0000-000000000007", "Reviewer", FIRM),
    "reviewer_none": ("53200000-0000-0000-0000-000000000012", "53200000-1111-0000-0000-000000000008", "Reviewer", FIRM),
    "client_role": ("53200000-0000-0000-0000-000000000013", "53200000-1111-0000-0000-000000000009", "Client", FIRM),
    "suspended": ("53200000-0000-0000-0000-00000000000f", "53200000-1111-0000-0000-000000000005", "Partner", FIRM),
    "other_firm": ("53200000-0000-0000-0000-000000000010", "53200000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}

MIGRATION = next(p for p in MIGRATIONS.glob("532_a_clients_year_locks_are_visible_to_the_members_who_post_into_it_and_written_by_the_api_only*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("532_a_clients_year_locks_are_visible_to_the_members_who_post_into_it_and_written_by_the_api_only*_rollback.sql"))

TABLE = "client_year_locks"
FY = "2025-26"
DAY = "2025-09-30"                                         # inside FY 2025-26
RESTRICTIVE_READ = ["client_year_locks_assignment_scope", "client_year_locks_internal_partner_only"]
RESTRICTIVE_WRITE = {"client_year_locks_role_insert": "a", "client_year_locks_role_update": "w", "client_year_locks_role_delete": "d"}
EXPECTED_READS = {"partner": 3, "manager_a": 1, "executive_a": 1, "reviewer_a": 1, "client_role": 1, "manager_none": 0, "reviewer_none": 0,
                  "suspended": 0, "other_firm": 0}
CLOSED = "is closed for this client"


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


def _count_as(dsn: str, who: str) -> int:
    return int(_lines_as(dsn, who, f"SELECT count(*) FROM {TABLE};")[-1])


def _count_op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err'; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _reason_as(dsn: str, who: str, fn: str, client: str) -> str:
    """What `public.<fn>` answers to this person for this client's day: the sentence, or `<open>`."""
    return _lines_as(dsn, who, f"SELECT coalesce(public.{fn}('{FIRM}', '{client}', '{DAY}'::date), '<open>');")[-1]


def _reason_admin(dsn: str, fn: str, client: str) -> str:
    return _rows(dsn, f"SELECT coalesce(public.{fn}('{FIRM}', '{client}', '{DAY}'::date), '<open>')")[0][0]


def _insert_lock(client: str, fy: str = FY, firm: str = FIRM) -> str:
    return f"INSERT INTO {TABLE} (firm_id, client_id, financial_year, reason) VALUES ('{firm}', '{client}', '{fy}', 'test')"


def _grant_writes(dsn: str) -> None:
    """The throwaway database only: give the signed-in role the writes 532 took away, so the policies are what is being asked
    (the second lock) and not the missing grant."""
    done = _psql(dsn, f"GRANT INSERT, UPDATE, DELETE ON public.{TABLE} TO authenticated;")
    assert done.returncode == 0, done.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e532_{uuid.uuid4().hex[:12]}"
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
                        ('{FIRM}', '{PEOPLE["reviewer_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["client_role"][0]}', '{CLIENT_A}');
        """)
        assert seed.returncode == 0, seed.stderr
        for client in (CLIENT_A, CLIENT_B, INTERNAL):
            done = _psql(d, _insert_lock(client))
            assert done.returncode == 0, f"seeding the lock of {client}: {done.stderr}"
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE POLICIES ────────────────────────────────────────────────────────────────

def _policy(dsn: str, name: str) -> list[str]:
    got = _rows(dsn, f"""SELECT p.polpermissive, p.polcmd, regexp_replace(coalesce(pg_get_expr(p.polqual, p.polrelid), ''), '\\s+', ' ', 'g'),
                                regexp_replace(coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''), '\\s+', ' ', 'g'),
                                (SELECT string_agg(r.rolname, ',') FROM pg_roles r WHERE r.oid = ANY(p.polroles))
                           FROM pg_policy p WHERE p.polrelid = 'public.{TABLE}'::regclass AND p.polname = '{name}'""")
    assert got, f"{TABLE} has no {name} policy"
    return got[0]


def test_the_firm_policy_asks_the_callers_firm_and_not_a_token_claim(dsn):
    permissive, cmd, qual, check, roles = _policy(dsn, "client_year_locks_firm_isolation")
    assert permissive == "t" and cmd == "*" and roles == "authenticated", (permissive, cmd, roles)
    for clause in (qual, check):
        assert "get_my_firm_id" in clause and "firm_id" in clause, f"the firm policy does not ask the caller's firm: {clause}"
        assert "jwt" not in clause.lower(), f"the firm policy still reads a token claim: {clause}"
    assert _rows(dsn, f"SELECT count(*) FROM pg_policy WHERE polrelid = 'public.{TABLE}'::regclass AND polpermissive") == [["1"]], (
        "there is another permissive policy on the table: it could let in what the firm policy refuses")


@pytest.mark.parametrize("name", RESTRICTIVE_READ)
def test_the_read_policies_are_restrictive_for_all_and_ask_the_callers_clients_once_per_query(dsn, name):
    permissive, cmd, qual, check, _roles = _policy(dsn, name)
    assert permissive == "f" and cmd == "*", f"{name} is not RESTRICTIVE FOR ALL: {(permissive, cmd)}"
    assert qual and check, f"{name} has no USING or no WITH CHECK"
    assert "can_access_client" not in qual + check, f"{name} calls can_access_client once per row"
    if name.endswith("_assignment_scope"):
        assert "my_assigned_client_ids" in qual and "my_assigned_client_ids" in check, (qual, check)
        assert "Partner" in qual and "Partner" in check, f"{name}: a Partner's branch is missing from the USING or the WITH CHECK"
    else:
        assert "my_internal_client_id" in qual and "Partner" in qual, qual
        assert "my_internal_client_id" in check and "Partner" in check, f"{name}: the WITH CHECK lost the guard or the Partner branch"


@pytest.mark.parametrize("name,cmd", sorted(RESTRICTIVE_WRITE.items()))
def test_the_write_policies_are_restrictive_one_per_verb_and_ask_for_a_partner(dsn, name, cmd):
    permissive, got_cmd, qual, check, _roles = _policy(dsn, name)
    assert permissive == "f" and got_cmd == cmd, f"{name}: {(permissive, got_cmd)}"
    if cmd in ("a", "w"):
        assert "Partner" in check and "get_my_role" in check, f"{name}: the WITH CHECK does not ask for a Partner: {check}"
    if cmd in ("w", "d"):
        assert "Partner" in qual and "get_my_role" in qual, f"{name}: the USING does not ask for a Partner: {qual}"


# ── WHO SEES WHAT ───────────────────────────────────────────────────────────────

def test_each_person_reads_only_the_locks_of_the_clients_they_may_see(dsn):
    seen = {who: _count_as(dsn, who) for who in PEOPLE}
    assert seen == EXPECTED_READS, seen


def test_a_signed_in_principal_with_no_member_row_reads_none(dsn):
    assert _count_as(dsn, "stranger") == 0


def test_the_internal_practice_is_a_partners_even_for_a_person_assigned_to_it(dsn):
    for who in ("manager_a", "reviewer_a"):
        assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                          f"VALUES ('{FIRM}', '{PEOPLE[who][0]}', '{INTERNAL}');").returncode == 0
    for who in ("manager_a", "reviewer_a"):
        assert _count_as(dsn, who) == EXPECTED_READS[who], f"an assignment to the internal practice opened its lock to {who}"
    assert _count_as(dsn, "partner") == EXPECTED_READS["partner"]


def test_in_a_firm_that_never_set_up_its_internal_practice_an_assigned_member_still_reads_their_clients_lock(dsn):
    """`firms.internal_client_id` is NULL for a firm whose onboarding never provisioned its practice. The guard compares the
    row's client with it and `NULL <> x` is NULL, so a guard written `<>` hid every lock from every non-Partner of such a firm."""
    assert _psql(dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    assert {who: _count_as(dsn, who) for who in ("partner", "manager_a", "executive_a", "reviewer_a", "client_role", "manager_none", "reviewer_none")} == {
        "partner": 3, "manager_a": 1, "executive_a": 1, "reviewer_a": 1, "client_role": 1, "manager_none": 0, "reviewer_none": 0}


def test_the_scope_holds_the_line_without_the_firm_policy(dsn):
    """A principal with no member row, a suspended Partner and a person assigned to nothing read none because the FIRM policy
    says so. Widen the firm policy in this throwaway database and ask again: what is left is the scope itself, and a role that
    is NULL (no member row) must come out as a denial and not as a pass."""
    assert _psql(dsn, f'CREATE POLICY "widened" ON public.{TABLE} FOR SELECT TO authenticated USING (true);').returncode == 0
    seen = {who: _count_as(dsn, who) for who in ("stranger", "suspended", "manager_none", "reviewer_none", "manager_a", "reviewer_a", "partner")}
    assert seen == {"stranger": 0, "suspended": 0, "manager_none": 0, "reviewer_none": 0, "manager_a": 1, "reviewer_a": 1, "partner": 3}, seen


# ── THE CHECKS SEE THE LOCK ─────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", ["period_closure_reason", "period_lock_reason"])
def test_the_period_checks_answer_the_sentence_for_the_clients_a_person_can_reach_and_open_for_the_rest(dsn, fn):
    """The two functions are SECURITY INVOKER, so what they answer is what the caller's row security lets them read. The posting
    kernel asks the first and the documents' pre-checks the second, with the request's own client."""
    assert all(CLOSED in _reason_admin(dsn, fn, c) for c in (CLIENT_A, CLIENT_B, INTERNAL)), "the administrator does not read the lock"
    clients = {"A": CLIENT_A, "B": CLIENT_B, "I": INTERNAL}
    expected_closed = {"partner": {"A", "B", "I"}, "manager_a": {"A"}, "executive_a": {"A"}, "reviewer_a": {"A"}, "client_role": {"A"},
                       "manager_none": set(), "reviewer_none": set(), "suspended": set(), "other_firm": set(), "stranger": set()}
    for who, closed in expected_closed.items():
        got = {k for k, c in clients.items() if CLOSED in _reason_as(dsn, who, fn, c)}
        assert got == closed, f"{fn}: {who} reads the year as closed for {sorted(got)}, expected {sorted(closed)}"


def test_before_the_migration_every_signed_in_person_reads_a_finalised_year_as_open(dsn):
    """THE DEFECT, reproduced: roll the migration back (migration 289's state) and the administrator still reads the year as
    closed while a signed-in Partner reads it as open."""
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    for fn in ("period_closure_reason", "period_lock_reason"):
        assert CLOSED in _reason_admin(dsn, fn, CLIENT_A)
        for who in ("partner", "manager_a"):
            assert _reason_as(dsn, who, fn, CLIENT_A) == "<open>", f"{fn}: {who} already read the lock before the migration"
    assert _count_as(dsn, "partner") == 0
    # and the lock cannot be written by the sign-in that finalises the year
    assert _count_op(dsn, "partner", _insert_lock(CLIENT_A, "2024-25")) == "err"


# ── THE WRITE SIDE ──────────────────────────────────────────────────────────────

def test_the_signed_in_roles_hold_no_write_and_anon_reads_nothing(dsn):
    got = _rows(dsn, f"""SELECT string_agg(privilege_type, ',' ORDER BY privilege_type)
                           FROM information_schema.role_table_grants
                          WHERE table_schema = 'public' AND table_name = '{TABLE}' AND grantee IN ('authenticated', 'anon', 'PUBLIC')""")
    assert got == [["SELECT"]], got
    for role in ("authenticated", "anon"):
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{priv}')") == [["f"]], f"{role} holds {priv}"
        for priv in ("INSERT", "UPDATE", "REFERENCES"):
            assert _rows(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{TABLE}', '{priv}')") == [["f"]], (
                f"{role} holds a column-level {priv}")
    assert _rows(dsn, f"SELECT has_table_privilege('anon', 'public.{TABLE}', 'SELECT') OR "
                      f"has_any_column_privilege('anon', 'public.{TABLE}', 'SELECT')") == [["f"]]
    assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{TABLE}', 'SELECT')") == [["t"]]
    for priv in ("INSERT", "UPDATE", "DELETE"):
        assert _rows(dsn, f"SELECT has_table_privilege('service_role', 'public.{TABLE}', '{priv}')") == [["t"]], (
            f"the API (service_role) cannot {priv} the lock table")


def test_the_migration_takes_every_privilege_away_from_a_database_that_granted_them_all(dsn):
    """A database built from the migrations never grants TRUNCATE, REFERENCES, TRIGGER or anything to anon on this table, so the
    test above cannot tell a REVOKE that is missing. Production's default privileges grant ALL on a new table to PUBLIC, anon and
    authenticated: give that back here, apply the migration, and ask again."""
    assert _psql(dsn, f"GRANT ALL ON public.{TABLE} TO PUBLIC, anon, authenticated;").returncode == 0
    for role in ("authenticated", "anon"):
        assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', 'TRUNCATE')") == [["t"]], "the setup did not grant"
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    for role in ("authenticated", "anon"):
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{TABLE}', '{priv}')") == [["f"]], f"{role} still holds {priv}"
        for priv in ("INSERT", "UPDATE", "REFERENCES"):
            assert _rows(dsn, f"SELECT has_any_column_privilege('{role}', 'public.{TABLE}', '{priv}')") == [["f"]], f"{role} {priv} by column"
    assert _rows(dsn, f"SELECT has_table_privilege('anon', 'public.{TABLE}', 'SELECT') OR "
                      f"has_any_column_privilege('anon', 'public.{TABLE}', 'SELECT')") == [["f"]], "anon still reads the table"
    assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{TABLE}', 'SELECT')") == [["t"]]


@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "client_role"])
def test_a_signed_in_session_cannot_write_a_lock_at_all(dsn, who):
    assert _count_op(dsn, who, _insert_lock(CLIENT_A, "2024-25")) == "err"
    assert _count_op(dsn, who, f"UPDATE {TABLE} SET reason = 'x' WHERE client_id = '{CLIENT_A}'") == "err"
    assert _count_op(dsn, who, f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'") == "err"


def test_with_the_writes_granted_a_partner_writes_for_their_firm_and_nobody_else_does(dsn):
    """The second lock: the grant is back in this throwaway database, so the policies are what refuse."""
    _grant_writes(dsn)
    assert _count_op(dsn, "partner", _insert_lock(CLIENT_A, "2024-25")) == "1", "a Partner cannot lock a client's year"
    assert _count_op(dsn, "partner", _insert_lock(INTERNAL, "2024-25")) == "1", "a Partner cannot lock the practice's own year"
    for who in ("manager_a", "executive_a", "reviewer_a", "client_role", "manager_none", "reviewer_none", "suspended", "other_firm"):
        assert _count_op(dsn, who, _insert_lock(CLIENT_A, "2024-25")) == "err", f"{who} locked a client's year"
    # (A row naming ANOTHER firm's client under one's own firm id is accepted by the firm policy; the database does not check a
    # row's client against its firm, which is POST-A-304 and not this migration. It cannot lock this firm's year: every reader
    # filters on the firm.)


def test_with_the_writes_granted_only_a_partner_unlocks_or_moves_a_lock(dsn):
    _grant_writes(dsn)
    for who in ("manager_a", "executive_a", "reviewer_a", "client_role"):
        assert _count_op(dsn, who, f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'") == "0", f"{who} unlocked a client's year"
        assert _count_op(dsn, who, f"UPDATE {TABLE} SET reason = 'x' WHERE client_id = '{CLIENT_A}'") == "0", f"{who} changed a lock"
        assert _count_op(dsn, who, f"UPDATE {TABLE} SET financial_year = '2024-25' WHERE client_id = '{CLIENT_A}'") == "0", (
            f"{who} moved a lock to another year")
    for who in ("other_firm", "manager_none", "suspended"):
        assert _count_op(dsn, who, f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'") == "0", f"{who} unlocked a client's year"
    assert _count_op(dsn, "partner", f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_A}'") == "1", "a Partner cannot unlock a client's year"
    assert _count_op(dsn, "partner", f"UPDATE {TABLE} SET financial_year = '2024-25' WHERE client_id = '{CLIENT_A}'") == "1", (
        "a Partner cannot correct a lock's year")
    assert _psql(dsn, f"DELETE FROM {TABLE} WHERE client_id = '{CLIENT_B}'").returncode == 0     # so only a policy can refuse the move
    assert _count_op(dsn, "partner", f"UPDATE {TABLE} SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "1"


# ── THE ROLLBACK, AND THE PLAN ──────────────────────────────────────────────────

def test_the_rollback_restores_migration_289s_state_and_a_reapply_restores_this_one(dsn):
    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    names = {r[0] for r in _rows(dsn, f"SELECT polname FROM pg_policy WHERE polrelid = 'public.{TABLE}'::regclass")}
    assert names == {"client_year_locks_firm_isolation"}, names
    permissive, cmd, qual, check, roles = _policy(dsn, "client_year_locks_firm_isolation")
    # migration 289's policy exactly as the catalog printed it before 532 (migration 526 had folded the claim into a once-per-query
    # sub-select): permissive, for ALL commands, for PUBLIC (no role named), on a claim this project never issues
    claim = "((( SELECT auth.jwt() AS jwt) ->> 'firm_id'::text))::uuid"
    assert (permissive, cmd, roles) == ("t", "*", ""), (permissive, cmd, roles)
    assert qual == f"(firm_id = {claim})" and check == f"(firm_id = {claim})", (qual, check)
    assert _rows(dsn, f"""SELECT string_agg(privilege_type, ',' ORDER BY privilege_type) FROM information_schema.role_table_grants
                           WHERE table_schema = 'public' AND table_name = '{TABLE}' AND grantee = 'authenticated'""") == [["DELETE,INSERT,SELECT,UPDATE"]]
    assert all(_count_as(dsn, who) == 0 for who in ("partner", "manager_a")), "migration 289's policy refuses every signed-in session"

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert {who: _count_as(dsn, who) for who in PEOPLE} == EXPECTED_READS
    assert _rows(dsn, f"SELECT has_table_privilege('authenticated', 'public.{TABLE}', 'INSERT')") == [["f"]]


def test_the_apply_log_counts_an_engagement_that_reads_locked_with_no_lock_row(dsn):
    """Before 532 a finalise could fail half way and leave an engagement that reads locked with no lock row. The migration changes
    nothing about it and says how many it finds, so that the premise (production holds none) is in the apply log and not assumed."""
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0 and "migration 532: 0 year-end engagement(s) read locked with no lock row" in done.stderr, done.stderr
    partner = PEOPLE["partner"][0]
    assert _psql(dsn, f"""INSERT INTO year_end_engagements (firm_id, client_id, financial_year, fy_start, fy_end, status, created_by) VALUES
        ('{FIRM}', '{CLIENT_B}', '2024-25', '2024-04-01', '2025-03-31', 'locked', '{partner}'),
        ('{FIRM}', '{CLIENT_A}', '{FY}', '2025-04-01', '2026-03-31', 'locked', '{partner}'),
        ('{FIRM}', '{CLIENT_A}', '2024-25', '2024-04-01', '2025-03-31', 'approved', '{partner}')""").returncode == 0
    done = _psql_file(dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    # client A's 2025-26 engagement has its lock (seeded), the 2024-25 one of client B has none, and an approved one is not locked
    assert "migration 532: 1 year-end engagement(s) read locked with no lock row" in done.stderr, done.stderr
    assert _rows(dsn, f"SELECT count(*) FROM {TABLE}") == [["3"]], "the migration wrote or removed a lock row"


def test_a_second_run_of_the_migration_changes_nothing(dsn):
    def snapshot() -> list:
        return _rows(dsn, "SELECT p.polname, p.polpermissive, p.polcmd, pg_get_expr(p.polqual, p.polrelid), "
                          "pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p "
                          f"WHERE p.polrelid = 'public.{TABLE}'::regclass ORDER BY 1") + _rows(
            dsn, f"SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name = '{TABLE}' ORDER BY 1, 2")
    first = snapshot()
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert snapshot() == first


def test_a_signed_in_scan_asks_the_callers_clients_once(dsn):
    lines = _lines_as(dsn, "manager_a", f"EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM {TABLE};")
    plan = "\n".join(lines)
    assert "can_access_client" not in plan, plan
    assert re.search(r"hashed SubPlan \d+", plan) and "my_assigned_client_ids()" in plan, plan
    # the role and the practice are asked ONCE (an InitPlan), not per row: a bare call would sit in the Filter itself
    filters = " ".join(line for line in lines if "Filter:" in line)
    assert "get_my_role()" not in filters and "my_internal_client_id()" not in filters, (
        f"a helper is called once per row, not once per query:\n{plan}")
    assert "get_my_role()" in plan and "my_internal_client_id()" in plan and plan.count("InitPlan") >= 2, plan
