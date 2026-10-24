"""Migration 540 — a signed-in member who is not a Partner can no longer clear the client of eleven more tables (or the workflow of an
onboarding task) or move a shared account onto one client, and the signed-in role can no longer delete a client row (POST-A-326,
POST-A-303).

WHAT WAS WRONG
    * A member assigned to a client could `UPDATE ... SET client_id = NULL` on that client's row in any table whose client may be
      NULL, and the assignment scope, which admits a client-less row to every member of the firm, then showed it to everybody.
      Migration 537 closed that move on four tables; eleven more had it open (`activity_logs`, `ai_evidence`, `ai_signals`,
      `chart_of_accounts`, `client_lifecycle_events`, `knowledge_articles`, `mca_filings`, `proposals`, `reminders`,
      `scheduled_reports`, `task_recurring_configs`, `time_entries`: twelve, the chart being the one that is also moved the other
      way) and so did the child column `onboarding_tasks.workflow_id`.
    * The signed-in role held DELETE on `clients`. The API soft-deletes and the browser never deletes, so nothing used it, but a
      Partner's own token could delete a client row over PostgREST, cascading into the client's child tables and turning its Tally
      jobs and letters into firm-wide rows.

WHAT THIS HOLDS (a real database, the roles production uses)
    * THE TWELVE CLEARING TRIGGERS: a Manager's update to NULL on each column is refused (42501 and a sentence) and the row is
      unchanged; a Partner, the privileged client and the database owner may clear it; an update that does not clear it, a write
      that leaves a NULL column NULL, filling a NULL, and a write that names the column and sends the value it already has (the
      mark-sent shape) are untouched.
    * THE CHART: any change of `chart_of_accounts.client_id` by a Manager (clearing a client's account, or setting a shared
      account's client) is refused, a Partner, the privileged client and the owner may, and an update of another column is
      untouched.
    * THE CATALOGUE RULE: every table in a database built from the migrations that has a nullable `client_id` and an UPDATE grant on
      it (table or column level) for the signed-in role carries one of the two guards on that column, or is named below with its
      reason (`notifications`: read by its recipient and not by the client's assignees), so a table added later fails here; the
      that are read-only to the signed-in role are found by their GRANT and not by a list.
    * `clients`: the signed-in and anonymous roles hold no DELETE, TRUNCATE, REFERENCES or TRIGGER, at table or column level, even
      when the platform's defaults granted everything first (the worst case, which a database built from the migrations does not
      show); `authenticated` keeps SELECT, INSERT and UPDATE and the browser's reads, inserts and updates of a client still work;
      the service role keeps its four and the firm purge still removes a firm's clients; a Partner's delete of a bare client is
      refused with the privilege and, with the privilege handed back in a copy, the policy still refuses a Manager, an Executive
      and a Reviewer who ARE assigned to the client (the second lock; an unassigned client would be hidden by the assignment scope
      whether or not the policy existed) and a negative control shows the same delete passing once the policy is neutralised.
    * THE MIGRATION: applies twice to the same result, the rollback gives the earlier behaviour back and a re-apply closes it again,
      and the statements that take table locks run inside one block in both files.

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
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the clearing-guard proof requires HARNESS_PG + psql",
)

_STEM = "540_a_member_who_is_not_a_partner_cannot_clear_the_client_of_eleven_more_tables_and_nobody_signed_in_can_delete_a_client"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
FUNCTION = "refuse_a_signed_in_member_clearing_the_parent_of_a_row"
FUNCTION2 = "refuse_a_signed_in_member_changing_the_client_of_a_row"

FIRM = "54000000-0000-0000-0000-000000000001"
CLIENT_A = "54000000-0000-0000-0000-0000000000a1"
CLIENT_B = "54000000-0000-0000-0000-0000000000b2"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("54000000-0000-0000-0000-00000000000a", "54000000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("54000000-0000-0000-0000-00000000000b", "54000000-1111-0000-0000-000000000002", "Manager"),
    "manager_none": ("54000000-0000-0000-0000-00000000000c", "54000000-1111-0000-0000-000000000003", "Manager"),
    "executive_a": ("54000000-0000-0000-0000-00000000000e", "54000000-1111-0000-0000-000000000004", "Executive"),
    "reviewer_a": ("54000000-0000-0000-0000-00000000000f", "54000000-1111-0000-0000-000000000005", "Reviewer"),
}
_F = f"'{FIRM}'"

# the twelve columns the clearing function guards here: (table, column); the chart has its own function
CLEARABLE = [("activity_logs", "client_id"), ("ai_evidence", "client_id"), ("ai_signals", "client_id"),
             ("client_lifecycle_events", "client_id"), ("knowledge_articles", "client_id"), ("mca_filings", "client_id"),
             ("proposals", "client_id"), ("reminders", "client_id"), ("scheduled_reports", "client_id"),
             ("task_recurring_configs", "client_id"), ("time_entries", "client_id"), ("onboarding_tasks", "workflow_id")]
CHART = ("chart_of_accounts", "client_id")
EXEMPT_FROM_THE_CATALOGUE_RULE = {"notifications": "a notification is read by its recipient; its client is a label and not an access path"}
# the four 537 guarded, so the catalogue rule can be seen to cover the whole family
GUARDED_BY_537 = {"engagements", "properties", "tally_migration_jobs"}      # (and customer_payment_events, whose column is payment_id)
# migrations 505, 509 and 536 (a sandbox table nothing reads or writes); found by their grant and not by this list
READ_ONLY_TO_THE_SIGNED_IN_ROLE = {"ai_recommendations", "workflow_instances", "demo_filings"}


def _q(value) -> str:
    return "NULL" if value is None else f"'{value}'"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    if who in ("service_role", "owner"):
        return "SET request.jwt.claims = '{\"role\": \"service_role\"}'; " + ("SET ROLE service_role; " if who == "service_role" else "")
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _count_op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err:<SQLSTATE> <message>` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err:% %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _count_as(dsn: str, who: str, table: str, where: str = "true") -> int:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + f"SELECT count(*) FROM {table} WHERE {where};"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return int([line for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"][-1])


def _refused(outcome: str, sqlstate: str = "42501") -> bool:
    return outcome.startswith(f"err:{sqlstate}")


# ── THE SEED ─────────────────────────────────────────────────────────────────────

def _values(table: str, n: int, ids: dict) -> dict:
    """The columns a row needs besides the firm and the client."""
    return {
        "activity_logs": {"action": "'client_created'", "description": _q(f"log {n}")},
        "ai_evidence": {"evidence_type": _q(f"e{n}")},
        "ai_signals": {"signal_type": _q(f"s{n}")},
        "chart_of_accounts": {"account_code": _q(f"9{n:03d}"), "account_name": _q(f"Account {n}"), "account_type": "'Asset'"},
        "client_lifecycle_events": {"event_type": _q(f"t{n}")},
        "knowledge_articles": {"scope": "'client'", "title": _q(f"Article {n}")},
        "mca_filings": {"form_type": "'AOC-4'", "due_date": "'2026-10-30'"},
        "proposals": {"proposal_no": _q(f"P-{n}"), "title": _q(f"Proposal {n}")},
        "reminders": {"reminder_type": "'email'", "scheduled_for": "'2026-11-01 10:00+00'"},
        "scheduled_reports": {"report_type": "'pl'", "frequency": "'monthly'"},
        "task_recurring_configs": {"frequency": "'monthly'", "next_due_date": "'2026-11-01'"},
        "time_entries": {"user_id": _q(PEOPLE["manager_a"][0]), "started_at": "'2026-10-01 09:00+00'"},
    }[table]


def _insert(table: str, cols: dict) -> str:
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(cols.values())})"


class World:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.ids: dict[str, dict[str, str]] = {}

    def put(self, table: str, tag: str, cols: dict) -> str:
        sql = "SET session_replication_role = replica; " + _insert(table, cols) + " RETURNING id;"
        got = [line for line in _rows(self.dsn, sql) if re.fullmatch(r"[0-9a-f-]{36}", line[0])]
        assert got, f"no id back from the seed of {table}/{tag}"
        self.ids.setdefault(table, {})[tag] = got[0][0]
        return got[0][0]

    def row(self, table: str, tag: str) -> str:
        return self.ids[table][tag]


def _seed(w: World) -> None:
    ids: dict = {}
    # a client's row ("A") and a firm-level one ("N": no client, open to the firm) in each of the eleven client tables
    for n, (table, _column) in enumerate(CLEARABLE[:-1] + [CHART], start=1):
        for tag, client in (("A", CLIENT_A), ("N", None)):
            cols = {"firm_id": _F, "client_id": _q(client), **_values(table, n * 10 + (0 if tag == "A" else 1), ids)}
            if table == "knowledge_articles" and tag == "N":
                cols["scope"] = "'firm'"
            w.put(table, tag, cols)
    # an onboarding workflow of client A, a task under it ("A") and a task with no workflow ("N")
    wf = w.put("onboarding_workflows", "A", {"firm_id": _F, "client_id": _q(CLIENT_A)})
    w.put("onboarding_tasks", "A", {"firm_id": _F, "workflow_id": _q(wf), "task_name": "'collect KYC'"})
    w.put("onboarding_tasks", "N", {"firm_id": _F, "workflow_id": "NULL", "task_name": "'orphan'"})
    w.ids["onboarding_workflows"] = {"A": wf}


@pytest.fixture(scope="module")
def seeded(pg_template):
    admin = _ADMIN.strip()
    name = f"e540s_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create the seeded database")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        assigned = ", ".join(f"('{FIRM}', '{PEOPLE[n][0]}', '{CLIENT_A}')" for n in ("manager_a", "executive_a", "reviewer_a"))
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
        """)
        assert seed.returncode == 0, seed.stderr
        w = World(d)
        _seed(w)
        yield name, w.ids
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def world(seeded):
    template, ids = seeded
    admin = _ADMIN.strip()
    name = f"e540_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        w = World(f"{admin} dbname={name}")
        w.ids = {table: dict(rows) for table, rows in ids.items()}
        # Migration 543 took every privilege on activity_logs, ai_evidence and ai_signals away from the signed-in role (nothing reads
        # or writes them). The trigger of this migration stays on them as a SECOND LOCK, and this file measures that lock: the
        # privilege is handed back in the throwaway copy, as a later grant or the platform's defaults might hand it back.
        handed_back = _psql(w.dsn, "GRANT SELECT, UPDATE ON public.activity_logs, public.ai_evidence, public.ai_signals TO authenticated;")
        assert handed_back.returncode == 0, handed_back.stderr
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE TWELVE TRIGGERS ──────────────────────────────────────────────────────────

def test_the_seed_is_what_the_tests_below_assume(world):
    """A vacuity guard: every table has the two rows, and the member reaches the client's row and, since the scope admits it, the
    firm-level one."""
    for table, column in CLEARABLE + [CHART]:
        for tag, expect in (("A", "t"), ("N", "f")):
            assert _rows(world.dsn, f"SELECT {column} IS NOT NULL FROM {table} WHERE id = '{world.row(table, tag)}'") == [[expect]], (table, tag)


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_manager_assigned_to_the_client_cannot_clear_it(world, table, column):
    row = world.row(table, "A")
    outcome = _count_op(world.dsn, "manager_a", f"UPDATE {table} SET {column} = NULL WHERE id = '{row}'")
    assert _refused(outcome), f"manager_a cleared {table}.{column}: {outcome}"
    assert "Only a Partner" in outcome and table in outcome, outcome
    assert _rows(world.dsn, f"SELECT {column} IS NOT NULL FROM {table} WHERE id = '{row}'") == [["t"]], f"{table}.{column} was cleared"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_partner_the_privileged_client_and_the_owner_may_clear_it(world, table, column):
    row = world.row(table, "A")
    for who in ("partner", "service_role", "owner"):
        assert _count_op(world.dsn, who, f"UPDATE {table} SET {column} = NULL WHERE id = '{row}'") == "1", f"{who} was refused on {table}"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_write_that_names_the_column_and_sends_the_value_it_has_is_untouched(world, table, column):
    """The mark-sent route of `reminders` re-sends the whole row it read, so the client goes back as it was."""
    row = world.row(table, "A")
    assert _count_op(world.dsn, "manager_a", f"UPDATE {table} SET {column} = {column} WHERE id = '{row}'") == "1"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_write_that_leaves_a_null_column_null_is_not_clearing_it(world, table, column):
    row = world.row(table, "N")
    assert _count_op(world.dsn, "manager_none", f"UPDATE {table} SET {column} = NULL WHERE id = '{row}'") == "1"
    assert _count_op(world.dsn, "manager_none", f"UPDATE {table} SET {column} = {column} WHERE id = '{row}'") == "1"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_filling_a_null_column_is_not_clearing_it(world, table, column):
    value = world.row("onboarding_workflows", "A") if column == "workflow_id" else CLIENT_A
    assert _count_op(world.dsn, "manager_a", f"UPDATE {table} SET {column} = '{value}' WHERE id = '{world.row(table, 'N')}'") == "1"


OTHER_COLUMN = {"activity_logs": "description = 'edited'", "ai_evidence": "evidence_type = 'edited'", "ai_signals": "signal_type = 'edited'",
                "chart_of_accounts": "account_name = 'Renamed'", "client_lifecycle_events": "event_type = 'edited'",
                "knowledge_articles": "title = 'Renamed'",
                "mca_filings": "status = 'in_progress'", "proposals": "title = 'Renamed'", "reminders": "status = 'sent'",
                "scheduled_reports": "is_active = false", "task_recurring_configs": "is_active = false",
                "time_entries": "description = 'edited'", "onboarding_tasks": "task_name = 'renamed'"}


@pytest.mark.parametrize("table,column", CLEARABLE + [CHART])
def test_an_update_of_another_column_is_untouched(world, table, column):
    row = world.row(table, "A")
    assert _count_op(world.dsn, "manager_a", f"UPDATE {table} SET {OTHER_COLUMN[table]} WHERE id = '{row}'") == "1"


def test_the_trigger_fires_only_when_the_column_is_named(world):
    """BEFORE UPDATE OF <column>: a statement that does not name the column never runs the function, which is what keeps the cost
    off every other update of these tables."""
    for table, column in CLEARABLE + [CHART]:
        fn = FUNCTION2 if (table, column) == CHART else FUNCTION
        defs = _rows(world.dsn, f"SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t WHERE t.tgrelid = 'public.{table}'::regclass "
                                f"AND NOT t.tgisinternal AND t.tgfoid = 'public.{fn}()'::regprocedure")
        assert len(defs) == 1, (table, defs)
        assert f"BEFORE UPDATE OF {column} ON public.{table}" in defs[0][0] and f"{fn}('{column}')" in defs[0][0], defs[0][0]


# ── THE CHART: ANY CHANGE OF THE CLIENT ──────────────────────────────────────────────

def test_a_manager_cannot_clear_a_clients_account_or_set_a_shared_accounts_client(world):
    """Both directions: clearing puts the account in every client's chart, setting takes a shared account from every other client
    (their postings to it are then refused by migration 360's trigger until a Partner moves it back)."""
    mine, shared = world.row("chart_of_accounts", "A"), world.row("chart_of_accounts", "N")
    cleared = _count_op(world.dsn, "manager_a", f"UPDATE chart_of_accounts SET client_id = NULL WHERE id = '{mine}'")
    captured = _count_op(world.dsn, "manager_a", f"UPDATE chart_of_accounts SET client_id = '{CLIENT_A}' WHERE id = '{shared}'")
    for outcome in (cleared, captured):
        assert _refused(outcome) and "Only a Partner can change the client_id of a chart_of_accounts row" in outcome, outcome
    assert _rows(world.dsn, f"SELECT client_id IS NOT NULL FROM chart_of_accounts WHERE id = '{mine}'") == [["t"]]
    assert _rows(world.dsn, f"SELECT client_id IS NULL FROM chart_of_accounts WHERE id = '{shared}'") == [["t"]]


def test_a_partner_the_privileged_client_and_the_owner_may_change_an_accounts_client(world):
    mine, shared = world.row("chart_of_accounts", "A"), world.row("chart_of_accounts", "N")
    for who in ("partner", "service_role", "owner"):
        assert _count_op(world.dsn, who, f"UPDATE chart_of_accounts SET client_id = NULL WHERE id = '{mine}'") == "1", who
        assert _count_op(world.dsn, who, f"UPDATE chart_of_accounts SET client_id = '{CLIENT_A}' WHERE id = '{shared}'") == "1", who


def test_the_chart_writes_that_do_not_change_the_client_are_untouched(world):
    mine, shared = world.row("chart_of_accounts", "A"), world.row("chart_of_accounts", "N")
    assert _count_op(world.dsn, "manager_a", f"UPDATE chart_of_accounts SET client_id = client_id WHERE id = '{mine}'") == "1"
    assert _count_op(world.dsn, "manager_a", f"UPDATE chart_of_accounts SET client_id = NULL WHERE id = '{shared}'") == "1"      # NULL to NULL
    assert _count_op(world.dsn, "manager_a", f"UPDATE chart_of_accounts SET account_name = 'Renamed' WHERE id = '{shared}'") == "1"


# ── THE CATALOGUE RULE ────────────────────────────────────────────────────────────

def _family(dsn: str) -> list[list[str]]:
    """(table, signed-in role can UPDATE client_id, carries one of the two guards on client_id) for every table with a nullable
    `client_id`, read from the catalogue and not from a list and whatever the scope policy is called. The privilege is asked at
    column level, because this repo grants columns to the signed-in role (a table-level answer would miss a column-only grant)."""
    return _rows(dsn, f"""
        SELECT c.relname, has_column_privilege('authenticated', c.oid, 'client_id', 'UPDATE'),
               EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_attribute ta ON ta.attrelid = t.tgrelid AND ta.attnum = ANY (t.tgattr)
                        WHERE t.tgrelid = c.oid AND NOT t.tgisinternal AND t.tgenabled = 'O' AND ta.attname = 'client_id'
                          AND t.tgfoid IN ('public.{FUNCTION}()'::regprocedure, 'public.{FUNCTION2}()'::regprocedure))
          FROM pg_class c
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attnotnull AND NOT a.attisdropped
         WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
         ORDER BY 1""")


def _unguarded_and_writable(rows: list[list[str]]) -> set[str]:
    return {r[0] for r in rows if r[1] == "t" and r[2] != "t"} - set(EXEMPT_FROM_THE_CATALOGUE_RULE)


def test_every_table_with_a_nullable_client_and_a_write_grant_carries_a_guard(world):
    """Derived from the catalogue and not from a list: a table that a later migration adds with a nullable `client_id`, or a column
    grant that a later change gives the signed-in role, fails here until the column carries a trigger (or the table is named in
    EXEMPT_FROM_THE_CATALOGUE_RULE with its reason). `knowledge_articles` slipped past a first version of this rule because its
    scope policy is called `_assignment` and the rule keyed on `_assignment_scope`."""
    rows = _family(world.dsn)
    guarded = {r[0] for r in rows if r[2] == "t"}
    read_only = {r[0] for r in rows if r[1] == "f"}
    assert _unguarded_and_writable(rows) == set(), f"a signed-in member can clear the client of: {sorted(_unguarded_and_writable(rows))}"
    assert read_only == READ_ONLY_TO_THE_SIGNED_IN_ROLE, f"the tables the signed-in role cannot write changed: {sorted(read_only)}"
    expected = {t for t, c in CLEARABLE if c == "client_id"} | {CHART[0]} | GUARDED_BY_537
    assert guarded == expected, f"the guarded set is not the one this family is known by: missing {sorted(expected - guarded)}, extra {sorted(guarded - expected)}"
    assert len(guarded) == 15, "the eleven and the chart of 540 and the three of 537 that guard a client column"
    assert {r[0] for r in rows} == guarded | read_only | set(EXEMPT_FROM_THE_CATALOGUE_RULE), "a table with a nullable client is neither guarded nor named"


def test_the_rule_sees_a_table_the_moment_the_signed_in_role_can_write_it(world):
    """Give a read-only table its UPDATE back (a platform default, a dashboard change), or only a COLUMN grant, and the rule must
    name it; take a guard away from a guarded one and it must name that too."""
    assert _unguarded_and_writable(_family(world.dsn)) == set()
    assert _psql(world.dsn, "GRANT UPDATE ON public.ai_recommendations TO authenticated;").returncode == 0
    assert _unguarded_and_writable(_family(world.dsn)) == {"ai_recommendations"}
    assert _psql(world.dsn, "REVOKE UPDATE ON public.ai_recommendations FROM authenticated; "
                            "GRANT UPDATE (client_id) ON public.workflow_instances TO authenticated;").returncode == 0
    assert _unguarded_and_writable(_family(world.dsn)) == {"workflow_instances"}, "a column-only grant must be seen"
    assert _psql(world.dsn, "DROP TRIGGER a_time_entry_keeps_its_client_unless_a_partner_clears_it ON public.time_entries;").returncode == 0
    assert _unguarded_and_writable(_family(world.dsn)) == {"workflow_instances", "time_entries"}


# ── THE CLIENTS TABLE ─────────────────────────────────────────────────────────────

def _privs(dsn: str, role: str) -> dict:
    out = {}
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        out[verb] = _rows(dsn, f"SELECT has_table_privilege('{role}', 'public.clients', '{verb}')")[0][0] == "t"
    out["column_references"] = _rows(dsn, f"SELECT has_any_column_privilege('{role}', 'public.clients', 'REFERENCES')")[0][0] == "t"
    return out


def _acl(dsn: str, grantee: str) -> list[str]:
    """What the ACL itself lists for a grantee on `clients` (PUBLIC is grantee 0): all versions' verbs, MAINTAIN included."""
    cond = "a.grantee = 0" if grantee == "PUBLIC" else f"a.grantee = (SELECT oid FROM pg_roles WHERE rolname = '{grantee}')"
    return sorted(r[0] for r in _rows(dsn, "SELECT a.privilege_type FROM pg_class c, aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) a "
                                           f"WHERE c.oid = 'public.clients'::regclass AND {cond}"))


def test_the_signed_in_and_anonymous_roles_hold_only_what_the_product_uses_on_clients(world):
    assert _acl(world.dsn, "authenticated") == ["INSERT", "SELECT", "UPDATE"], _acl(world.dsn, "authenticated")
    assert _acl(world.dsn, "anon") == [] and _acl(world.dsn, "PUBLIC") == []
    auth, anon = _privs(world.dsn, "authenticated"), _privs(world.dsn, "anon")
    assert auth == {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False, "TRUNCATE": False, "REFERENCES": False,
                    "TRIGGER": False, "column_references": False}, auth
    assert not any(anon.values()), anon
    assert _acl(world.dsn, "service_role") == ["DELETE", "INSERT", "SELECT", "UPDATE"], _acl(world.dsn, "service_role")


def test_the_worst_case_every_privilege_granted_first_still_ends_closed(world):
    """A database built from the migrations does not carry the platform's default privileges, so a REVOKE of something nobody
    granted looks fine there. This grants everything to the three roles first, at table and column level (and takes the service
    role's own grant away), and applies the migration again."""
    done = _psql(world.dsn, "GRANT ALL ON public.clients TO PUBLIC, anon, authenticated; REVOKE ALL ON public.clients FROM service_role; "
                            "GRANT REFERENCES (id) ON public.clients TO anon, authenticated;")
    assert done.returncode == 0, done.stderr
    assert "DELETE" in _acl(world.dsn, "anon") and "TRUNCATE" in _acl(world.dsn, "authenticated"), "the worst case was not made"
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    test_the_signed_in_and_anonymous_roles_hold_only_what_the_product_uses_on_clients(world)


def _bare_client(world: World, tag: str) -> str:
    cid = f"54000000-0000-0000-0000-d0000000{tag}00"
    done = _psql(world.dsn, f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{cid}', '{FIRM}', 'Bare {tag}', 'Proprietorship');")
    assert done.returncode == 0, done.stderr
    return cid


@pytest.mark.parametrize("who", ["partner", "manager_a", "executive_a", "reviewer_a", "manager_none"])
def test_nobody_signed_in_deletes_a_client_row(world, who):
    bare = _bare_client(world, "01")
    outcome = _count_op(world.dsn, who, f"DELETE FROM clients WHERE id = '{bare}'")
    assert _refused(outcome) and "permission denied for table clients" in outcome, f"{who}: {outcome}"
    assert _rows(world.dsn, f"SELECT count(*) FROM clients WHERE id = '{bare}'") == [["1"]]


def test_the_service_role_and_the_owner_still_remove_a_client_row(world):
    for who, tag in (("service_role", "02"), ("owner", "03")):
        bare = _bare_client(world, tag)
        assert _count_op(world.dsn, who, f"DELETE FROM clients WHERE id = '{bare}'") == "1", who


def test_the_firm_purge_still_removes_the_firms_clients(world):
    """The one statement that removes client rows: SECURITY DEFINER, executable by the service role only. Run as the backend runs it,
    on the seeded firm, after the revoke."""
    assert _count_as(world.dsn, "service_role", "clients") >= 2
    purge = _psql(world.dsn, "SET request.jwt.claims = '{\"role\": \"service_role\"}'; SET ROLE service_role; "
                             f"SELECT public.platform_purge_firm('{FIRM}');")
    assert purge.returncode == 0, purge.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM clients WHERE firm_id = '{FIRM}'") == [["0"]]


def test_a_partners_delete_no_longer_nulls_a_letter_or_a_tally_job_into_a_firm_wide_row(world):
    """The harm of POST-A-303: the foreign keys `engagements.client_id` and `tally_migration_jobs.client_id` are ON DELETE SET NULL."""
    bare = _bare_client(world, "04")
    assert _psql(world.dsn, f"INSERT INTO engagements (firm_id, client_id, engagement_number, title) VALUES ('{FIRM}', '{bare}', 'EL-bare', 'bare');").returncode == 0
    outcome = _count_op(world.dsn, "partner", f"DELETE FROM clients WHERE id = '{bare}'")
    assert _refused(outcome), outcome
    assert _rows(world.dsn, "SELECT client_id IS NOT NULL FROM engagements WHERE engagement_number = 'EL-bare'") == [["t"]]


def _assigned_bare_client(world: World, tag: str) -> str:
    """A client with no dependants, ASSIGNED to the Manager, the Executive and the Reviewer: the assignment scope shows it to them,
    so what refuses their delete can only be `clients_role_delete`."""
    cid = _bare_client(world, tag)
    rows = ", ".join(f"('{FIRM}', '{PEOPLE[n][0]}', '{cid}')" for n in ("manager_a", "executive_a", "reviewer_a"))
    assert _psql(world.dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {rows};").returncode == 0
    return cid


def test_with_the_privilege_handed_back_the_policy_still_refuses_everyone_but_a_partner(world):
    """The second lock: the `clients_role_delete` policy was not touched, so a privilege restored by a dashboard change or a
    platform default is still refused to a Manager, an Executive and a Reviewer, and the Partner tier is the policy's. The client
    is assigned to them (an unassigned one would be hidden by the assignment scope whether or not the policy existed), and the
    negative control neutralises the policy and shows the same delete passing."""
    assert _psql(world.dsn, "GRANT DELETE ON public.clients TO authenticated;").returncode == 0
    for who in ("manager_a", "executive_a", "reviewer_a"):
        bare = _assigned_bare_client(world, "05")
        assert _count_as(world.dsn, who, "clients", f"id = '{bare}'") == 1, f"{who} does not see the client"
        assert _count_op(world.dsn, who, f"DELETE FROM clients WHERE id = '{bare}'") == "0", who
        assert _psql(world.dsn, f"DELETE FROM clients WHERE id = '{bare}';").returncode == 0
    bare = _assigned_bare_client(world, "06")
    assert _count_op(world.dsn, "partner", f"DELETE FROM clients WHERE id = '{bare}'") == "1"
    # the negative control: with the policy neutralised the Manager's delete of the same kind of client passes
    assert _psql(world.dsn, "ALTER POLICY clients_role_delete ON public.clients USING (true);").returncode == 0
    bare = _assigned_bare_client(world, "07")
    assert _count_op(world.dsn, "manager_a", f"DELETE FROM clients WHERE id = '{bare}'") == "1", "the policy is not what refused the Manager"


def test_what_the_product_does_to_a_client_still_works(world):
    """The browser reads, inserts and updates clients and the API reads and updates them under the caller's own sign-in."""
    assert _count_op(world.dsn, "manager_a", f"UPDATE clients SET client_name = 'Renamed' WHERE id = '{CLIENT_A}'") == "1"
    assert _count_op(world.dsn, "partner", f"UPDATE clients SET client_name = 'Renamed' WHERE id = '{CLIENT_B}'") == "1"
    assert _count_op(world.dsn, "partner", f"INSERT INTO clients (firm_id, client_name, entity_type) VALUES ('{FIRM}', 'New', 'Proprietorship')") == "1"
    assert _count_as(world.dsn, "manager_a", "clients") == 1            # the client the Manager is assigned to, and no other
    assert _count_as(world.dsn, "partner", "clients") == 2         # A and B (the insert above is undone)


# ── THE MIGRATION ────────────────────────────────────────────────────────────────

def _dollar_quoted_bodies(sql: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"\$(\w*)\$(.*?)\$\1\$", sql, flags=re.S)]


def _outside_the_bodies(sql: str) -> str:
    return re.sub(r"\$(\w*)\$.*?\$\1\$", " ", sql, flags=re.S)


@pytest.mark.parametrize("path, creates", [(MIGRATION, True), (ROLLBACK, False)], ids=["migration", "rollback"])
def test_the_statements_that_lock_the_tables_run_inside_one_block(path, creates):
    """CREATE TRIGGER takes SHARE ROW EXCLUSIVE and DROP TRIGGER ACCESS EXCLUSIVE, held to the end of the transaction, and the
    runner sends a top-level statement per round trip (the review of migration 539 measured a table locked for about 15 seconds
    that way). So no such statement stands at the top level and exactly one block holds them."""
    sql = re.sub(r"--[^\n]*", "", path.read_text())      # a comment may say CREATE TRIGGER; only a statement locks
    left = re.findall(r"\b(?:CREATE|DROP)\s+TRIGGER\b[^;]*", _outside_the_bodies(sql), flags=re.I)
    assert left == [], f"a statement that takes a table lock stands at the top level: {left[:2]}"
    holders = [b for b in _dollar_quoted_bodies(sql) if re.search(r"\b(?:CREATE|DROP)\s+TRIGGER\b", b, flags=re.I)]
    assert len(holders) == 1, f"{len(holders)} blocks hold the trigger statements, expected exactly one"
    assert len(re.findall(r"\bDROP TRIGGER IF EXISTS\b", holders[0])) == 13
    if creates:
        assert len(re.findall(r"\bCREATE TRIGGER\b", holders[0])) == 13


def _catalog(dsn: str) -> list:
    return _rows(dsn, "SELECT t.tgrelid::regclass::text, t.tgname, t.tgenabled::text, pg_get_triggerdef(t.oid) FROM pg_trigger t "
                      f"WHERE t.tgfoid IN (SELECT p.oid FROM pg_proc p WHERE p.proname IN ('{FUNCTION}', '{FUNCTION2}')) AND NOT t.tgisinternal ORDER BY 1, 2") + _rows(
        dsn, "SELECT 'acl', coalesce(array_to_string(relacl, ','), '') FROM pg_class WHERE oid = 'public.clients'::regclass")


def test_there_are_seventeen_triggers_on_the_two_functions_and_the_function_is_closed_to_a_browser_role(world):
    cat = _catalog(world.dsn)
    triggers = [r for r in cat if r[0] != "acl"]
    assert len(triggers) == 17, [r[:2] for r in triggers]           # the four of 537, the twelve clearing ones and the chart's
    assert all(r[2] == "O" for r in triggers)
    assert _rows(world.dsn, f"SELECT has_function_privilege('authenticated', 'public.{FUNCTION2}()', 'EXECUTE'), "
                            f"has_function_privilege('anon', 'public.{FUNCTION2}()', 'EXECUTE')") == [["f", "f"]]
    # nor PUBLIC (grantee 0), nor anybody else the migrations' default privileges did not name: only the owner and the service role
    assert _rows(world.dsn, "SELECT count(*) FROM pg_proc p, aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a "
                            f"WHERE p.proname = '{FUNCTION2}' AND a.grantee <> p.proowner "
                            "AND a.grantee <> COALESCE((SELECT oid FROM pg_roles WHERE rolname = 'service_role'), -1)") == [["0"]]


def test_the_account_function_stays_closed_to_a_signed_in_role_when_the_platform_granted_it_first(world):
    """Production's platform defaults grant EXECUTE on a new function in `public` to PUBLIC, anon and authenticated, and a database
    built from the migrations does not, so the revoke is invisible there. The worst case is made here: the three are granted first
    and the migration is applied again."""
    fn = f"public.{FUNCTION2}()"
    probe = f"SELECT has_function_privilege('authenticated', '{fn}', 'EXECUTE'), has_function_privilege('anon', '{fn}', 'EXECUTE')"
    assert _psql(world.dsn, f"GRANT EXECUTE ON FUNCTION {fn} TO PUBLIC, anon, authenticated;").returncode == 0
    assert _rows(world.dsn, probe) == [["t", "t"]], "the worst case was not made"
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, probe) == [["f", "f"]]


def test_a_second_run_of_the_migration_changes_nothing(world):
    before = _catalog(world.dsn)
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _catalog(world.dsn) == before


def test_the_rollback_gives_the_earlier_behaviour_back_and_a_reapply_closes_it_again(world):
    row = world.row("time_entries", "A")
    clear = f"UPDATE time_entries SET client_id = NULL WHERE id = '{row}'"
    bare = _bare_client(world, "07")
    assert _refused(_count_op(world.dsn, "manager_a", clear))
    assert _refused(_count_op(world.dsn, "partner", f"DELETE FROM clients WHERE id = '{bare}'"))

    done = _psql_file(world.dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    after = _catalog(world.dsn)
    assert len([r for r in after if r[0] != "acl"]) == 4, "the rollback left a 540 trigger behind (537's four remain)"
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_proc WHERE proname = '{FUNCTION2}'") == [["0"]], "the rollback left the account function behind"
    assert _count_op(world.dsn, "manager_a", clear) == "1", "the earlier firm-wide clear is back"        # the negative control
    shared = world.row("chart_of_accounts", "N")
    assert _count_op(world.dsn, "manager_a", f"UPDATE chart_of_accounts SET client_id = '{CLIENT_A}' WHERE id = '{shared}'") == "1", "the earlier capture is back"
    assert _count_op(world.dsn, "partner", f"DELETE FROM clients WHERE id = '{bare}'") == "1", "the earlier Partner delete is back"

    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _refused(_count_op(world.dsn, "manager_a", clear))
    bare2 = _bare_client(world, "08")
    assert _refused(_count_op(world.dsn, "partner", f"DELETE FROM clients WHERE id = '{bare2}'"))
