"""The statutory identity, the payroll settings and the PT registrations of a client take the client's assignment scope and the
internal practice's Partner-only guard (migration 531, POST-A-299 second tranche).

WHAT WAS WRONG
    `client_statutory_identity` (the TAN, EPF establishment code, ESIC employer code and LIN of a client),
    `client_payroll_settings` (whether payroll is switched on for a client, by whom and when) and `client_pt_registrations`
    (its professional-tax certificate numbers by state) carried a NOT NULL client and a firm policy, and a role tier on writes,
    and nothing per client. Migration 519 took every write away from the signed-in role, so what was open was the READ: a member
    of the firm assigned to no client, or to a different one, listed the three for every client of the firm, and for the
    internal practice, which 074 makes a Partner's.

WHAT THIS HOLDS (for each of the three tables, the proof is the same)
    * THE POLICIES: the six exist, RESTRICTIVE and FOR ALL, in the once-per-query form of migrations 525 to 530, the scope
      asking the caller's clients and a Partner's branch in the USING and in the WITH CHECK, the guard asking the practice.
    * WHO SEES WHAT: a Partner reads the rows of client A, client B and the internal practice; a Manager, an Executive and a
      Reviewer assigned to A read A's and nothing else; a Manager or a Reviewer assigned to nothing, a suspended Partner and a
      Partner of another firm read none; a Manager or a Reviewer assigned to the practice as well still does not read its row;
      and in a firm that never set up its internal practice (`firms.internal_client_id` NULL) an assigned member still reads
      their client's row and the guard hides nothing it should not.
    * THE WRITE SIDE IS STILL UNGRANTED (519): the signed-in role holds no INSERT, UPDATE, DELETE or TRUNCATE on any of the
      three, so that a later GRANT is seen beside these policies. And the policies ARE the second lock: with the writes
      granted in a throwaway database, an assigned Manager writes their own client's row and is refused another's, an update
      or a delete of another client's row matches nothing, a row cannot be MOVED to a client the person may not see, and a
      Partner writes for every client, the practice included.
    * NO ONE ELSE IS LET IN OR OUT: an employee or a portal contact never had a branch on these tables (the firm policy asks
      `get_my_firm_id()`, which is NULL for anyone without a `users` row), so a signed-in principal with no `users` row reads
      none of the three before and after.
    * THE ROLLBACK returns the firm-wide read exactly and a re-apply hides the rows again; a second run changes nothing; and
      the plan asks the caller's clients once per query.

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

from tests._signed_in_payroll_writes import give_the_signed_in_payroll_access_back

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the statutory-identity proof requires HARNESS_PG + psql",
)

FIRM = "53100000-0000-0000-0000-000000000001"
OTHER_FIRM = "53100000-0000-0000-0000-000000000002"
CLIENT_A = "53100000-0000-0000-0000-0000000000a1"
CLIENT_B = "53100000-0000-0000-0000-0000000000b2"
INTERNAL = "53100000-0000-0000-0000-0000000000c3"
STRANGER = "53100000-1111-0000-0000-0000000000ff"          # an authenticated principal with NO users row (an employee, a portal contact)
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("53100000-0000-0000-0000-00000000000a", "53100000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("53100000-0000-0000-0000-00000000000b", "53100000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_none": ("53100000-0000-0000-0000-00000000000c", "53100000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("53100000-0000-0000-0000-00000000000e", "53100000-1111-0000-0000-000000000004", "Executive", FIRM),
    "reviewer_a": ("53100000-0000-0000-0000-000000000011", "53100000-1111-0000-0000-000000000007", "Reviewer", FIRM),
    "reviewer_none": ("53100000-0000-0000-0000-000000000012", "53100000-1111-0000-0000-000000000008", "Reviewer", FIRM),
    "suspended": ("53100000-0000-0000-0000-00000000000f", "53100000-1111-0000-0000-000000000005", "Partner", FIRM),
    "other_firm": ("53100000-0000-0000-0000-000000000010", "53100000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}

MIGRATION = next(p for p in MIGRATIONS.glob("531_the_statutory_identity_and_the_two_payroll_settings_tables_take_the_clients_assignment_scope*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("531_the_statutory_identity_and_the_two_payroll_settings_tables_take_the_clients_assignment_scope*_rollback.sql"))

_F = f"'{FIRM}'"


def _cl(client: str) -> str:
    return f"'{client}'"


# one entry per table: seed(client) is an admin INSERT of the client's row; insert(client) is a FRESH row for that client,
# written as the person under test (the seeded row of a client is removed first where the unique key holds the client)
SPECS: dict[str, dict] = {
    "client_statutory_identity": {
        "seed": lambda c: f"INSERT INTO client_statutory_identity (firm_id, client_id, tan) VALUES ({_F}, {_cl(c)}, 'ABCD12345E')",
        "insert": lambda c: f"INSERT INTO client_statutory_identity (firm_id, client_id, tan) VALUES ({_F}, {_cl(c)}, 'WXYZ98765Q')",
        "touch": "tan = tan",
    },
    "client_payroll_settings": {
        "seed": lambda c: f"INSERT INTO client_payroll_settings (firm_id, client_id, payroll_enabled) VALUES ({_F}, {_cl(c)}, true)",
        "insert": lambda c: f"INSERT INTO client_payroll_settings (firm_id, client_id, payroll_enabled) VALUES ({_F}, {_cl(c)}, false)",
        "touch": "payroll_enabled = payroll_enabled",
    },
    "client_pt_registrations": {
        "seed": lambda c: f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) VALUES ({_F}, {_cl(c)}, 'MH', 'R-1')",
        "insert": lambda c: f"INSERT INTO client_pt_registrations (firm_id, client_id, state, ptrc_number) VALUES ({_F}, {_cl(c)}, 'KA', 'R-2')",
        "touch": "state = state",
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
    name = f"e531_{uuid.uuid4().hex[:12]}"
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
        give_the_signed_in_payroll_access_back(d)
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
def test_the_signed_in_role_still_holds_no_write_on_the_table(dsn, table):
    """519's REVOKE is the control for writes. If a later migration grants one back, this fails beside the policies that would
    then be the only lock."""
    got = _rows(dsn, f"""SELECT string_agg(privilege_type, ',' ORDER BY privilege_type)
                           FROM information_schema.role_table_grants
                          WHERE table_schema = 'public' AND table_name = '{table}' AND grantee IN ('authenticated', 'anon', 'PUBLIC')""")
    assert got == [["SELECT"]], f"{table}: {got}"
    # `role_table_grants` does not list a COLUMN-level grant, which is the shape migrations 326 and 332 first gave this table
    for role in ("authenticated", "anon"):
        for priv in ("INSERT", "UPDATE"):
            held = _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.{table}', '{priv}') OR "
                              f"has_any_column_privilege('{role}', 'public.{table}', '{priv}')")
            assert held == [["f"]], f"{table}: {role} holds {priv}"


@pytest.mark.parametrize("table", TABLES)
def test_an_assigned_manager_writes_for_their_client_and_is_refused_for_another_once_writes_are_granted(dsn, table):
    """The second lock: with the writes granted in this throwaway database the policies' WITH CHECK is what refuses."""
    spec = SPECS[table]
    _grant_writes(dsn)
    for client in (CLIENT_A, CLIENT_B, INTERNAL):          # the unique key holds the client: clear the seeded rows first
        assert _psql(dsn, f"DELETE FROM {table} WHERE client_id = '{client}'").returncode == 0
    assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_A)) == "1", f"an assigned Manager cannot add a {table} row for their own client"
    assert _count_op(dsn, "manager_a", spec["insert"](CLIENT_B)) == "err", f"a {table} row was added for a client the Manager is not assigned to"
    assert _count_op(dsn, "manager_none", spec["insert"](CLIENT_A)) == "err", f"a Manager assigned to nothing added a {table} row"
    assert _count_op(dsn, "manager_a", spec["insert"](INTERNAL)) == "err", f"a Manager (not assigned to it) added a {table} row for the practice"
    assert _count_op(dsn, "executive_a", spec["insert"](CLIENT_A)) == "err", f"an Executive added a {table} row: the role tier has gone"
    assert _count_op(dsn, "reviewer_a", spec["insert"](CLIENT_A)) == "err", f"a Reviewer added a {table} row: the role tier has gone"


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
