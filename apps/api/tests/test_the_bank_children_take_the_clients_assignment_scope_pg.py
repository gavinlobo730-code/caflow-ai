"""The children of a client's bank lines take the client's assignment scope and the internal practice's Partner-only
guard (migration 527, POST-A-005).

WHAT WAS WRONG
    `bank_transactions`, `bank_statements` and `bank_reconciliations` carry a RESTRICTIVE assignment scope (084) and a
    RESTRICTIVE internal-practice guard (074). Three of their children - `bank_transaction_splits`, `bank_matching_rules`
    and `bank_reconciliation_matches` - carried a firm policy (and, since 524, the banking read tier) and nothing per
    client, so a member of the firm assigned to nothing could read, change and delete another client's splits, rules and
    matches over PostgREST, and insert a split or a rule into a client they are not assigned to.

    `bank_statement_column_mappings` is deliberately NOT scoped: the firm-wide second look of `find_mapping` (BANK-26)
    reuses a layout drawn for one account on another account of the practice. It is an `own` entry in
    `tests/fixtures/assignment_scope_exceptions.json`.

WHAT THIS HOLDS
    * THE POLICIES: the six exist, RESTRICTIVE and FOR ALL, written in the once-per-query form of migrations 525 and 526
      (they ask `my_assigned_client_ids()` and never `can_access_client`).
    * WHO SEES WHAT: a Partner reads the rows of client A, client B and the firm's internal practice; a Manager and an
      Executive assigned to A read A's and nothing else; a Manager assigned to nothing, a suspended Partner and a
      Partner of another firm read none of them; and a Manager assigned to the internal practice as well still does not
      read its rows, because the internal-practice guard is a Partner's whatever the assignments say.
    * WHO CHANGES WHAT: an assigned person inserts, updates and deletes the rows of their own client and an insert for a
      client they are not assigned to is refused by the database, as is an update that MOVES a row to such a client or a
      split onto such a client's bank line; an update or a delete of another client's row matches nothing. A Partner
      does all of it for every client, the internal practice included (the WITH CHECK keeps the Partner branch). A match,
      which has no client of its own, follows the bank line it belongs to.
    * THE ROLLBACK returns the firm-wide behaviour exactly, and a re-apply hides the rows again.
    * THE PLAN asks the caller's clients once per query.

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
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the bank-children proof requires HARNESS_PG + psql",
)

FIRM = "52700000-0000-0000-0000-000000000001"
OTHER_FIRM = "52700000-0000-0000-0000-000000000002"
CLIENT_A = "52700000-0000-0000-0000-0000000000a1"
CLIENT_B = "52700000-0000-0000-0000-0000000000b2"
INTERNAL = "52700000-0000-0000-0000-0000000000c3"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("52700000-0000-0000-0000-00000000000a", "52700000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("52700000-0000-0000-0000-00000000000b", "52700000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_none": ("52700000-0000-0000-0000-00000000000c", "52700000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("52700000-0000-0000-0000-00000000000e", "52700000-1111-0000-0000-000000000004", "Executive", FIRM),
    "suspended": ("52700000-0000-0000-0000-00000000000f", "52700000-1111-0000-0000-000000000005", "Partner", FIRM),
    "other_firm": ("52700000-0000-0000-0000-000000000010", "52700000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}

CHILDREN = ["bank_transaction_splits", "bank_matching_rules", "bank_reconciliation_matches"]
POLICIES = {
    "bank_transaction_splits": ["bank_transaction_splits_assignment_scope", "bank_transaction_splits_internal_partner_only",
                                "bank_transaction_splits_parent_visible"],
    "bank_matching_rules": ["bank_matching_rules_assignment_scope", "bank_matching_rules_internal_partner_only"],
    "bank_reconciliation_matches": ["bank_reconciliation_matches_parent_visible"],
}

MIGRATION = next(p for p in MIGRATIONS.glob("527_the_bank_children_take_the_clients_assignment_scope*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("527_the_bank_children_take_the_clients_assignment_scope*_rollback.sql"))

_ACCT = "(SELECT id FROM chart_of_accounts WHERE firm_id = '%s' LIMIT 1)" % FIRM
_SPLIT = ("INSERT INTO bank_transaction_splits (firm_id, client_id, bank_transaction_id, account_id, amount_paise) "
          "VALUES ('%s', '%s', '%s', " + _ACCT + ", 5)")
_RULE = "INSERT INTO bank_matching_rules (firm_id, client_id, rule_name) VALUES ('%s', '%s', 'probe')"
_MATCH = "INSERT INTO bank_reconciliation_matches (firm_id, bank_transaction_id, match_type) VALUES ('%s', '%s', 'manual')"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _lines_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


def _seed_client(dsn: str, client: str, tag: str) -> None:
    sql = (
        f"WITH s AS (INSERT INTO bank_statements (firm_id, client_id, bank_name, statement_from, statement_to) "
        f"VALUES ('{FIRM}', '{client}', 'Bank {tag}', '2026-04-01', '2026-04-30') RETURNING id), "
        f"t AS (INSERT INTO bank_transactions (statement_id, firm_id, client_id, transaction_date, description) "
        f"SELECT id, '{FIRM}', '{client}', '2026-04-02', 'UPI/{tag}' FROM s RETURNING id), "
        f"sp AS (INSERT INTO bank_transaction_splits (firm_id, client_id, bank_transaction_id, account_id, amount_paise) "
        f"SELECT '{FIRM}', '{client}', t.id, {_ACCT}, 100 FROM t RETURNING id), "
        f"m AS (INSERT INTO bank_reconciliation_matches (firm_id, bank_transaction_id, match_type) "
        f"SELECT '{FIRM}', t.id, 'manual' FROM t RETURNING id) "
        f"INSERT INTO bank_matching_rules (firm_id, client_id, rule_name) VALUES ('{FIRM}', '{client}', 'rule {tag}');")
    done = _psql(dsn, sql)
    assert done.returncode == 0, done.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e527_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items())
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
                        ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}');
            INSERT INTO chart_of_accounts (firm_id, account_code, account_name, account_type)
                 VALUES ('{FIRM}', '9999', 'Probe', 'Expense');
        """)
        assert seed.returncode == 0, seed.stderr
        for client, tag in ((CLIENT_A, "A"), (CLIENT_B, "B"), (INTERNAL, "I")):
            _seed_client(d, client, tag)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


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


def _tx_of(dsn: str, client: str) -> str:
    return _rows(dsn, f"SELECT id FROM bank_transactions WHERE client_id = '{client}'")[0][0]


# ── THE POLICIES ────────────────────────────────────────────────────────────────

def test_the_six_policies_are_restrictive_for_all_and_ask_the_callers_clients_once_per_query(dsn):
    for table, names in POLICIES.items():
        for name in names:
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
            if name.endswith("_internal_partner_only"):
                assert "my_internal_client_id" in qual and "Partner" in qual, got[0]
                assert "my_internal_client_id" in check and "Partner" in check, f"{name}: the WITH CHECK lost the guard or the Partner branch"
            if name.endswith("_parent_visible"):
                assert "bank_transactions" in qual and "bank_transactions" in check, got[0]


def test_the_column_mappings_are_deliberately_not_scoped(dsn):
    """BANK-26: the firm-wide second look of find_mapping reuses a layout drawn for one account on another. A scope on
    reads would end that for everyone but a Partner, so the table keeps its firm policy and the role tier on writes."""
    names = {r[0] for r in _rows(dsn, "SELECT polname FROM pg_policy WHERE polrelid = 'public.bank_statement_column_mappings'::regclass")}
    assert not {n for n in names if n.endswith(("_assignment_scope", "_internal_partner_only", "_parent_visible"))}, names


# ── WHO SEES WHAT ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", CHILDREN)
def test_each_person_reads_only_the_rows_of_the_clients_they_may_see(dsn, table):
    seen = {who: _count_as(dsn, who, table) for who in PEOPLE}
    assert seen == {"partner": 3, "manager_a": 1, "manager_none": 0, "executive_a": 1, "suspended": 0, "other_firm": 0}, (
        f"{table}: {seen}")


@pytest.mark.parametrize("table", CHILDREN)
def test_the_internal_practice_is_a_partners_even_for_a_person_assigned_to_it(dsn, table):
    assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                      f"VALUES ('{FIRM}', '{PEOPLE['manager_a'][0]}', '{INTERNAL}');").returncode == 0
    assert _count_as(dsn, "manager_a", table) == 1, f"{table}: an assignment to the internal practice opened its rows to a Manager"
    assert _count_as(dsn, "partner", table) == 3


# ── WHO CHANGES WHAT ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["manager_a", "executive_a"])
def test_an_assigned_person_inserts_for_their_client_and_is_refused_for_another(dsn, who):
    tx_a, tx_b = _tx_of(dsn, CLIENT_A), _tx_of(dsn, CLIENT_B)
    assert _count_op(dsn, who, _SPLIT % (FIRM, CLIENT_A, tx_a)) == "1", "an assigned person cannot add a split to their own client"
    assert _count_op(dsn, who, _SPLIT % (FIRM, CLIENT_B, tx_b)) == "err", "a split was added to a client the person is not assigned to"
    # a split of the person's own client written onto another client's bank line is refused too: the parent is not theirs
    assert _count_op(dsn, who, _SPLIT % (FIRM, CLIENT_A, tx_b)) == "err", (
        "a split of the person's client was written onto another client's bank line")
    assert _count_op(dsn, who, _RULE % (FIRM, CLIENT_A)) == "1"
    assert _count_op(dsn, who, _RULE % (FIRM, CLIENT_B)) == "err", "a rule was added to a client the person is not assigned to"
    assert _count_op(dsn, who, _MATCH % (FIRM, tx_a)) == "1", "an assigned person cannot add a match to their own client's line"
    assert _count_op(dsn, who, _MATCH % (FIRM, tx_b)) == "err", "a match was added to a line of a client the person is not assigned to"


@pytest.mark.parametrize("who", ["manager_a", "executive_a"])
def test_an_update_cannot_move_a_row_to_a_client_or_a_line_the_person_may_not_see(dsn, who):
    tx_a, tx_b = _tx_of(dsn, CLIENT_A), _tx_of(dsn, CLIENT_B)
    assert _count_op(dsn, who, f"UPDATE bank_matching_rules SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "err", (
        "an assigned person moved a rule to a client they are not assigned to")
    assert _count_op(dsn, who, f"UPDATE bank_transaction_splits SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "err"
    assert _count_op(dsn, who, f"UPDATE bank_transaction_splits SET bank_transaction_id = '{tx_b}' WHERE client_id = '{CLIENT_A}'") == "err", (
        "an assigned person moved a split onto another client's bank line")
    assert _count_op(dsn, who, f"UPDATE bank_reconciliation_matches SET bank_transaction_id = '{tx_b}' "
                              f"WHERE bank_transaction_id = '{tx_a}'") == "err", (
        "an assigned person moved a match onto another client's bank line")


def test_a_partner_writes_every_clients_rows_the_internal_practice_included(dsn):
    """The WITH CHECK keeps the Partner branch: a slip that dropped it from the scope or the guard would lock the owner out of
    creating bank rules and splits straight after the deploy."""
    for client, tag in ((CLIENT_A, "A"), (CLIENT_B, "B"), (INTERNAL, "I")):
        tx = _tx_of(dsn, client)
        assert _count_op(dsn, "partner", _SPLIT % (FIRM, client, tx)) == "1", f"a Partner cannot add a split for {tag}"
        assert _count_op(dsn, "partner", _RULE % (FIRM, client)) == "1", f"a Partner cannot add a rule for {tag}"
        assert _count_op(dsn, "partner", _MATCH % (FIRM, tx)) == "1", f"a Partner cannot add a match for {tag}"
    assert _count_op(dsn, "partner", f"UPDATE bank_matching_rules SET client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "1", (
        "a Partner cannot move a rule to another client")
    assert _count_op(dsn, "partner", f"UPDATE bank_matching_rules SET client_id = '{INTERNAL}' WHERE client_id = '{CLIENT_A}'") == "1"
    assert _count_op(dsn, "partner", f"UPDATE bank_transaction_splits SET bank_transaction_id = '{_tx_of(dsn, CLIENT_B)}', "
                                     f"client_id = '{CLIENT_B}' WHERE client_id = '{CLIENT_A}'") == "1"


@pytest.mark.parametrize("table", CHILDREN)
def test_an_update_or_a_delete_of_another_clients_row_matches_nothing_and_of_their_own_matches(dsn, table):
    col = {"bank_transaction_splits": "narration", "bank_matching_rules": "rule_name", "bank_reconciliation_matches": "notes"}[table]
    by_line = table != "bank_matching_rules"
    where_a = (f"bank_transaction_id = '{_tx_of(dsn, CLIENT_A)}'" if by_line else f"client_id = '{CLIENT_A}'")
    where_b = (f"bank_transaction_id = '{_tx_of(dsn, CLIENT_B)}'" if by_line else f"client_id = '{CLIENT_B}'")
    for who in ("manager_a", "executive_a"):
        assert _count_op(dsn, who, f"UPDATE {table} SET {col} = 'x' WHERE {where_b}") == "0", f"{who} updated another client's {table} row"
        assert _count_op(dsn, who, f"DELETE FROM {table} WHERE {where_b}") == "0", f"{who} deleted another client's {table} row"
        assert _count_op(dsn, who, f"UPDATE {table} SET {col} = 'x' WHERE {where_a}") == "1", f"{who} cannot update their own client's {table} row"
        assert _count_op(dsn, who, f"DELETE FROM {table} WHERE {where_a}") == "1", f"{who} cannot delete their own client's {table} row"
    assert _count_op(dsn, "manager_none", f"DELETE FROM {table} WHERE {where_a}") == "0", "a person assigned to nothing deleted a row"
    assert _count_op(dsn, "partner", f"DELETE FROM {table} WHERE {where_b}") == "1", "a Partner cannot delete a client's row"


# ── THE ROLLBACK, AND THE PLAN ──────────────────────────────────────────────────

def test_the_rollback_returns_the_firm_wide_read_and_a_reapply_hides_the_rows_again(dsn):
    before = {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in CHILDREN}
    assert all(v["manager_none"] == 0 for v in before.values()), before

    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    for table in CHILDREN:
        assert _count_as(dsn, "manager_none", table) == 3, f"after the rollback {table} is not firm-wide again"
        assert not _rows(dsn, f"SELECT 1 FROM pg_policy WHERE polrelid = 'public.{table}'::regclass AND polname = ANY(ARRAY{POLICIES[table]})")

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in CHILDREN} == before


def test_a_second_run_of_the_migration_changes_nothing(dsn):
    def snapshot() -> list:
        return _rows(dsn, "SELECT c.relname, p.polname, p.polpermissive, p.polcmd, pg_get_expr(p.polqual, p.polrelid), "
                          "pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                          "WHERE c.relname = ANY(ARRAY['bank_transaction_splits','bank_matching_rules',"
                          "'bank_statement_column_mappings','bank_reconciliation_matches']) ORDER BY 1, 2")
    first = snapshot()
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert snapshot() == first


@pytest.mark.parametrize("table", ["bank_transaction_splits", "bank_matching_rules"])
def test_a_signed_in_scan_asks_the_callers_clients_once(dsn, table):
    plan = "\n".join(_lines_as(dsn, "manager_a", f"EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM {table};"))
    assert "can_access_client" not in plan, plan
    assert re.search(r"hashed SubPlan \d+", plan) and "my_assigned_client_ids()" in plan, plan
