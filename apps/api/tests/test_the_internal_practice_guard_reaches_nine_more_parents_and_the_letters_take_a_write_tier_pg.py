"""The internal practice's Partner-only guard reaches nine more parent tables, an engagement letter and its events take a role tier
on writes, and a member who is not a Partner cannot clear a row's client to open it to the firm (migration 537, ledger POST-A-306
and POST-A-309).

WHAT WAS WRONG
    * Nine parent tables (`debit_notes`, `purchase_credit_notes`, `sales_debit_notes`, `onboarding_workflows`, `tasks`,
      `recurring_journal_templates`, `recurring_purchase_bill_templates`, `workflow_instances`, `itr_filings`) carried the
      assignment scope and not the `<table>_internal_partner_only` guard, so a member assigned to the internal practice (only
      possible by a direct insert into the assignment table) read and wrote the practice's rows there, and in the twenty
      children of migration 529 that follow them.
    * `engagements` and `engagement_events` carried no role tier on writes, while every route that writes them asks
      `client:write` (a Manager's by default): a Reviewer assigned to a client could update or delete that client's letter over
      PostgREST, and a member assigned to nothing could delete a lead's letter.
    * A Partner's direct insert into the assignment table could assign the practice to a non-Partner, after which the member
      read the practice's rows in the ~110 assigned-scoped tables that never took the guard.
    * A member assigned to a client could `UPDATE ... SET client_id = NULL` on that client's letter, property or Tally job (or
      `payment_id = NULL` on a payment event), which puts the row in the part of the table that is open to the whole firm.

WHAT THIS HOLDS (a real database, the roles production uses)
    * THE GUARDS: nine RESTRICTIVE FOR ALL policies, the USING the WITH CHECK, the role and the practice's id asked once per
      query, and `client_id IS NULL OR` only on the one table whose client may be NULL.
    * WHO SEES WHAT: a Partner reads the client's rows and the practice's; a Manager assigned to the client AND to the practice
      reads the client's only; a Manager assigned to nothing reads none (and the firm-level workflow instance).
    * WHO WRITES WHAT: the member assigned to the practice adds nothing for it, changes nothing of it, moves nothing onto it,
      and still does all of it for their own client; a Partner does all of it.
    * THE ASSIGNMENT TABLE: a Partner's direct insert or update cannot assign the internal practice to anybody (a client of the
      firm is assigned as before, and a stale row can still be deleted).
    * THE LETTERS' TIER: a Partner and a Manager write a client's letter, a lead's letter and their events; an Executive, a
      Reviewer and a Manager the grid has denied `client:write` do not (an update or delete matches nothing, an insert is
      refused); an Executive the grid has granted it does. Reads are unchanged.
    * THE CLEARED CLIENT: a Manager's update to NULL on each of the four columns is refused with 42501 and a sentence, the row
      is unchanged, and a Partner's, the privileged client's and the database owner's are not; filling a NULL (a lead's letter
      linked to the client just made) and every update that does not clear are untouched; the foreign-key `SET NULL` of a
      client's deletion, run as the owner, is not judged.
    * THE MIGRATION: applies twice to the same result, the rollback restores the earlier behaviour exactly and a re-apply hides
      the rows again, and the trigger function is executable by no browser role.

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

from tests._signed_in_document_writes import give_the_signed_in_writes_back

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the internal-practice guard proof requires HARNESS_PG + psql",
)

_STEM = "537_the_internal_practice_guard_reaches_nine_more_parents_and_an_engagement_letter_takes_a_write_tier"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

FIRM = "53700000-0000-0000-0000-000000000001"
CLIENT_A = "53700000-0000-0000-0000-0000000000a1"
CLIENT_B = "53700000-0000-0000-0000-0000000000b2"
INTERNAL = "53700000-0000-0000-0000-0000000000c3"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("53700000-0000-0000-0000-00000000000a", "53700000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("53700000-0000-0000-0000-00000000000b", "53700000-1111-0000-0000-000000000002", "Manager"),
    "manager_none": ("53700000-0000-0000-0000-00000000000c", "53700000-1111-0000-0000-000000000003", "Manager"),
    "executive_a": ("53700000-0000-0000-0000-00000000000e", "53700000-1111-0000-0000-000000000004", "Executive"),
    "reviewer_a": ("53700000-0000-0000-0000-00000000000f", "53700000-1111-0000-0000-000000000005", "Reviewer"),
    "reviewer_none": ("53700000-0000-0000-0000-000000000010", "53700000-1111-0000-0000-000000000006", "Reviewer"),
    "executive_granted": ("53700000-0000-0000-0000-000000000011", "53700000-1111-0000-0000-000000000007", "Executive"),
    "manager_denied": ("53700000-0000-0000-0000-000000000012", "53700000-1111-0000-0000-000000000008", "Manager"),
}
CLIENT_A_MEMBERS = ("manager_a", "executive_a", "reviewer_a", "executive_granted", "manager_denied")
_F = f"'{FIRM}'"

# the nine parents the practice guard is added to, with the columns a row needs besides the firm and the client
NINE = ["debit_notes", "purchase_credit_notes", "sales_debit_notes", "onboarding_workflows", "tasks",
        "recurring_journal_templates", "recurring_purchase_bill_templates", "workflow_instances", "itr_filings"]
NULLABLE_CLIENT = {"workflow_instances"}                      # a workflow can run for the firm
NOT_WRITABLE = {"workflow_instances",                         # the signed-in role holds no write grant on it
                "recurring_journal_templates", "recurring_purchase_bill_templates"}   # nor, since migration 562, on these two
WRITABLE_NINE = [t for t in NINE if t not in NOT_WRITABLE]
CLEARABLE = [("engagements", "client_id"), ("customer_payment_events", "payment_id"),
             ("properties", "client_id"), ("tally_migration_jobs", "client_id")]


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


def _count_as(dsn: str, who: str, table: str) -> int:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + f"SELECT count(*) FROM {table};"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return int([line for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"][-1])


def _count_op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err:<SQLSTATE>` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err:% %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _refused(outcome: str, sqlstate: str = "42501") -> bool:
    return outcome.startswith(f"err:{sqlstate}")


# ── THE SEED ─────────────────────────────────────────────────────────────────────

def _parent_values(table: str, n: int, ids: dict) -> dict:
    cust, vend = ids["customer"], ids["vendor"]
    return {
        "debit_notes": {"vendor_id": _q(vend), "debit_note_no": _q(f"DN-{n}"), "debit_note_date": "'2026-04-01'"},
        "purchase_credit_notes": {"vendor_id": _q(vend), "credit_note_no": _q(f"PCN-{n}"), "credit_note_date": "'2026-04-01'"},
        "sales_debit_notes": {"customer_id": _q(cust), "debit_note_no": _q(f"SDN-{n}"), "debit_note_date": "'2026-04-01'"},
        "onboarding_workflows": {},
        "tasks": {"title": _q(f"task-{n}")},
        "recurring_journal_templates": {"name": _q(f"rj-{n}"), "frequency": "'monthly'", "start_date": "'2026-04-01'",
                                        "next_run_date": "'2026-05-01'"},
        "recurring_purchase_bill_templates": {"vendor_id": _q(vend), "title": _q(f"rp-{n}"), "frequency": "'monthly'",
                                              "start_date": "'2026-04-01'", "next_run_date": "'2026-05-01'"},
        "workflow_instances": {"template_id": _q(ids["template"]), "trigger_event": "'x'"},
        # one original return per client, year and form: the row a test inserts (n >= 50) is for the year before the seeded one
        "itr_filings": {"financial_year": "'2025-26'" if n < 50 else "'2024-25'",
                        "assessment_year": "'2026-27'" if n < 50 else "'2025-26'", "itr_form": "'ITR-1'",
                        "created_by": _q(PEOPLE["partner"][0])},
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
    one = lambda sql: _rows(w.dsn, sql)[0][0]
    ids = {"customer": one(f"SELECT id FROM customers WHERE client_id = '{CLIENT_A}'"),
           "vendor": w.put("vendors", "x", {"firm_id": _F, "client_id": _q(CLIENT_A), "name": "'vendor'"}),
           "template": one(f"SELECT id FROM workflow_templates WHERE firm_id = '{FIRM}'")}
    for tag, client in (("A", CLIENT_A), ("I", INTERNAL)):
        for n, table in enumerate(NINE, start=1):
            w.put(table, tag, {"firm_id": _F, "client_id": _q(client), **_parent_values(table, n, ids)})
    # the firm-level workflow instance: no client, open to the firm
    w.put("workflow_instances", "N", {"firm_id": _F, "client_id": "NULL", **_parent_values("workflow_instances", 9, ids)})
    # the letters: a client's, the practice's and a lead's, and an event on the client's and on the lead's
    for tag, client in (("A", CLIENT_A), ("I", INTERNAL), ("N", None)):
        w.put("engagements", tag, {"firm_id": _F, "client_id": _q(client), "engagement_number": _q(f"EL-{tag}"), "title": _q(f"Letter {tag}")})
    for tag in ("A", "N"):
        w.put("engagement_events", tag, {"firm_id": _F, "engagement_id": _q(w.row("engagements", tag)), "event_type": "'created'"})
    # a payment of client A and its event, an unmatched event, a property and a Tally job of client A
    invoice = w.put("client_sales_invoices", "A", {"firm_id": _F, "client_id": _q(CLIENT_A), "customer_id": _q(ids["customer"]),
                                                  "invoice_no": "'INV-1'", "invoice_date": "'2026-04-01'"})
    payment = w.put("customer_payments", "A", {"firm_id": _F, "client_id": _q(CLIENT_A), "customer_id": _q(ids["customer"]),
                                              "invoice_id": _q(invoice), "amount_paise": "100", "provider": "'razorpay'"})
    w.put("customer_payment_events", "A", {"firm_id": _F, "payment_id": _q(payment), "provider": "'razorpay'"})
    w.put("customer_payment_events", "N", {"firm_id": _F, "payment_id": "NULL", "provider": "'razorpay'"})
    w.ids["customer_payments"] = {"A": payment}
    w.put("properties", "A", {"firm_id": _F, "client_id": _q(CLIENT_A)})
    w.put("properties", "N", {"firm_id": _F, "client_id": "NULL"})                  # a firm-level property: no client, open to the firm
    for tag, client in (("A", CLIENT_A), ("N", None)):
        w.put("tally_migration_jobs", tag, {"firm_id": _F, "client_id": _q(client), "name": _q(f"{tag} books"), "source_file_name": "'a.xml'",
                                           "target_financial_year": "'2025-26'", "created_by": _q(PEOPLE["partner"][0])})


@pytest.fixture(scope="module")
def seeded(pg_template):
    admin = _ADMIN.strip()
    name = f"e537s_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create the seeded database")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r) in PEOPLE.items())
        assigned = ", ".join(f"('{FIRM}', '{PEOPLE[n][0]}', '{CLIENT_A}')" for n in CLIENT_A_MEMBERS)
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                 VALUES ('{INTERNAL}', '{FIRM}', 'The practice', 'Proprietorship', true);
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{INTERNAL}');
            INSERT INTO user_permissions (firm_id, user_id, resource, action, granted)
                 VALUES ('{FIRM}', '{PEOPLE["executive_granted"][0]}', 'client', 'write', true),
                        ('{FIRM}', '{PEOPLE["manager_denied"][0]}', 'client', 'write', false);
            INSERT INTO customers (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT_A}', 'cust A');
            INSERT INTO workflow_templates (firm_id, name, trigger_type) VALUES ('{FIRM}', 'wf', 'manual');
        """)
        assert seed.returncode == 0, seed.stderr
        w = World(d)
        _seed(w)
        # Migration 563 took the signed-in write on the six document headers and their lines; this file measures the SECOND lock (the
        # policies and the triggers), so the write is given back on this throwaway copy once its rows are seeded.
        give_the_signed_in_writes_back(d)
        yield name, w.ids
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def world(seeded):
    template, ids = seeded
    admin = _ADMIN.strip()
    name = f"e537_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        w = World(f"{admin} dbname={name}")
        w.ids = {table: dict(rows) for table, rows in ids.items()}
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE NINE GUARDS ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", NINE)
def test_the_guard_is_restrictive_for_all_asks_once_per_query_and_says_null_only_where_the_client_may_be(world, table):
    got = _rows(world.dsn, f"""SELECT p.polpermissive, p.polcmd, regexp_replace(pg_get_expr(p.polqual, p.polrelid), '\\s+', ' ', 'g'),
                                      regexp_replace(pg_get_expr(p.polwithcheck, p.polrelid), '\\s+', ' ', 'g')
                                 FROM pg_policy p WHERE p.polrelid = 'public.{table}'::regclass AND p.polname = '{table}_internal_partner_only'""")
    assert got, f"{table} has no {table}_internal_partner_only policy"
    permissive, cmd, qual, check = got[0]
    assert permissive == "f" and cmd == "*", got[0]
    assert qual and qual == check, f"{table}: the WITH CHECK is not the USING"
    for helper in ("get_my_role", "my_internal_client_id"):
        assert (qual + check).count(f"{helper}()") == (qual + check).count(f"SELECT {helper}()") > 0, (
            f"{table}: {helper}() is asked once per row, not once per query: {got[0]}")
    assert "Partner" in qual and "Partner" in check
    nullable = _rows(world.dsn, f"SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'public' "
                                f"AND table_name = '{table}' AND column_name = 'client_id'")[0][0] == "YES"
    assert nullable == (table in NULLABLE_CLIENT), f"{table}: the column's nullability changed; the guard's form must follow it"
    assert ("client_id IS NULL" in qual and "client_id IS NULL" in check) == nullable, (
        f"{table}: `client_id IS NULL OR` belongs on a nullable client and nowhere else: {got[0]}")


@pytest.mark.parametrize("table", NINE)
def test_the_practices_rows_are_a_partners_even_for_a_member_assigned_to_the_practice(world, table):
    firm_level = 1 if table in NULLABLE_CLIENT else 0
    seen = {who: _count_as(world.dsn, who, table) for who in ("partner", "manager_a", "manager_none", "executive_a")}
    assert seen == {"partner": 2 + firm_level, "manager_a": 1 + firm_level, "manager_none": firm_level,
                    "executive_a": 1 + firm_level}, f"{table}: {seen}"


@pytest.mark.parametrize("table", WRITABLE_NINE)
def test_a_member_assigned_to_the_practice_writes_nothing_for_it_and_everything_for_their_own_client(world, table):
    dsn = world.dsn
    own, practice = world.row(table, "A"), world.row(table, "I")
    ids = {"customer": _rows(dsn, f"SELECT id FROM customers WHERE client_id = '{CLIENT_A}'")[0][0],
           "vendor": world.row("vendors", "x"), "template": _rows(dsn, "SELECT id FROM workflow_templates")[0][0]}
    n = NINE.index(table) + 50                    # a natural key the seeded row does not hold
    insert = lambda client: _insert(table, {"firm_id": _F, "client_id": _q(client), **_parent_values(table, n, ids)})
    touch = "firm_id = firm_id"
    assert _count_op(dsn, "manager_a", insert(CLIENT_A)) == "1", f"{table}: cannot add a row for their own client"
    assert _refused(_count_op(dsn, "manager_a", insert(INTERNAL))), f"{table}: a member assigned to the practice added a row for it"
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE id = '{practice}'") == "0", f"{table}: updated the practice's row"
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{practice}'") == "0", f"{table}: deleted the practice's row"
    assert _refused(_count_op(dsn, "manager_a", f"UPDATE {table} SET client_id = '{INTERNAL}' WHERE id = '{own}'")), (
        f"{table}: moved a row of their own client onto the practice")
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE id = '{own}'") == "1"
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{own}'") == "1"
    # a Partner is not judged by the guard
    assert _count_op(dsn, "partner", insert(INTERNAL)) == "1", f"{table}: the guard refused a Partner"
    assert _count_op(dsn, "partner", f"DELETE FROM {table} WHERE id = '{practice}'") == "1"


# ── THE ASSIGNMENT TABLE ──────────────────────────────────────────────────────────

def _assign(user: str, client: str) -> str:
    return f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES ('{FIRM}', '{PEOPLE[user][0]}', '{client}')"


@pytest.mark.parametrize("user", ["manager_none", "executive_a", "partner"])
def test_a_partner_cannot_assign_the_practice_to_anybody_by_a_direct_insert(world, user):
    dsn = world.dsn
    assert _refused(_count_op(dsn, "partner", _assign(user, INTERNAL))), f"the practice was assigned to {user}"
    assert _count_op(dsn, "partner", _assign(user, CLIENT_B)) == "1", "a client of the firm can no longer be assigned"


def test_a_partner_cannot_move_an_assignment_onto_the_practice_and_can_still_remove_a_stale_one(world):
    dsn = world.dsn
    mine = f"user_id = '{PEOPLE['executive_a'][0]}' AND client_id = '{CLIENT_A}'"
    assert _refused(_count_op(dsn, "partner", f"UPDATE user_client_assignments SET client_id = '{INTERNAL}' WHERE {mine}"))
    assert _count_op(dsn, "partner", f"UPDATE user_client_assignments SET client_id = '{CLIENT_B}' WHERE {mine}") == "1"
    # the seeded assignment of manager_a to the practice stands for the guards above to answer; removing it is allowed
    stale = f"user_id = '{PEOPLE['manager_a'][0]}' AND client_id = '{INTERNAL}'"
    assert _count_op(dsn, "partner", f"DELETE FROM user_client_assignments WHERE {stale}") == "1"
    # and a member who is not a Partner assigns nobody, as before
    assert _refused(_count_op(dsn, "manager_a", _assign("manager_none", CLIENT_B)))


def test_the_firm_with_no_internal_practice_set_up_assigns_its_clients_as_before(world):
    assert _psql(world.dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    assert _count_op(world.dsn, "partner", _assign("manager_none", CLIENT_B)) == "1"


# ── THE LETTERS' WRITE TIER ──────────────────────────────────────────────────────

def _letter(tag: str, client) -> str:
    return _insert("engagements", {"firm_id": _F, "client_id": _q(client), "engagement_number": _q(f"EL-new-{tag}"), "title": "'new'"})


# who may write a client's letter: the tier is client:write, a Manager's by default, and the grid's word where the person has one
LETTER_WRITERS = {"partner": True, "manager_a": True, "executive_granted": True,
                  "executive_a": False, "reviewer_a": False, "manager_denied": False}


@pytest.mark.parametrize("who,may", sorted(LETTER_WRITERS.items()))
def test_a_clients_letter_is_written_only_by_those_the_tier_admits(world, who, may):
    dsn = world.dsn
    letter = world.row("engagements", "A")
    touch = "title = title"
    if may:
        assert _count_op(dsn, who, _letter("1", CLIENT_A)) == "1", f"{who} cannot raise a letter"
        assert _count_op(dsn, who, f"UPDATE engagements SET {touch} WHERE id = '{letter}'") == "1"
        assert _count_op(dsn, who, f"DELETE FROM engagements WHERE id = '{letter}'") == "1"
    else:
        assert _refused(_count_op(dsn, who, _letter("1", CLIENT_A))), f"{who} raised a letter"
        assert _count_op(dsn, who, f"UPDATE engagements SET {touch} WHERE id = '{letter}'") == "0", f"{who} updated a letter"
        assert _count_op(dsn, who, f"DELETE FROM engagements WHERE id = '{letter}'") == "0", f"{who} deleted a letter"
    # reads are every staff role's, whatever the tier
    assert _count_as(dsn, who, "engagements") == (3 if who == "partner" else 2), f"{who}: the tier changed what a person reads"


@pytest.mark.parametrize("who,may", sorted(LETTER_WRITERS.items()))
def test_a_letters_events_are_written_only_by_those_the_tier_admits(world, who, may):
    dsn = world.dsn
    event = world.row("engagement_events", "A")
    new = _insert("engagement_events", {"firm_id": _F, "engagement_id": _q(world.row("engagements", "A")), "event_type": "'viewed'"})
    if may:
        assert _count_op(dsn, who, new) == "1"
        assert _count_op(dsn, who, f"UPDATE engagement_events SET event_type = 'sent' WHERE id = '{event}'") == "1"
        assert _count_op(dsn, who, f"DELETE FROM engagement_events WHERE id = '{event}'") == "1"
    else:
        assert _refused(_count_op(dsn, who, new)), f"{who} added an event"
        assert _count_op(dsn, who, f"UPDATE engagement_events SET event_type = 'sent' WHERE id = '{event}'") == "0"
        assert _count_op(dsn, who, f"DELETE FROM engagement_events WHERE id = '{event}'") == "0"
    assert _count_as(dsn, who, "engagement_events") == 2, f"{who}: the tier changed what a person reads"


def test_a_lead_s_letter_is_deleted_by_a_manager_assigned_to_nothing_and_not_by_a_reviewer(world):
    """A letter with no client is open to the firm by design; the tier is what says who may remove it."""
    dsn = world.dsn
    lead = world.row("engagements", "N")
    assert _count_op(dsn, "reviewer_none", f"DELETE FROM engagements WHERE id = '{lead}'") == "0", "a Reviewer deleted a lead's letter"
    assert _count_op(dsn, "reviewer_none", f"UPDATE engagements SET title = title WHERE id = '{lead}'") == "0"
    assert _refused(_count_op(dsn, "reviewer_none", _letter("2", None)))
    assert _count_op(dsn, "manager_none", f"UPDATE engagements SET title = title WHERE id = '{lead}'") == "1"
    assert _count_op(dsn, "manager_none", f"DELETE FROM engagements WHERE id = '{lead}'") == "1"
    assert _count_op(dsn, "manager_none", _letter("3", None)) == "1", "a Manager cannot raise a lead's letter"


def test_a_lead_s_letter_is_linked_to_the_client_just_made_by_a_manager(world):
    """`routers/lifecycle._link_signed_letter`: the conversion of a lead stamps the signed letter with the new client, as the
    caller. NULL to a value is not clearing, and it is a write a Manager (client:write) may make."""
    lead = world.row("engagements", "N")
    assert _count_op(world.dsn, "manager_a", f"UPDATE engagements SET client_id = '{CLIENT_A}' WHERE id = '{lead}'") == "1"


# ── THE CLEARED CLIENT ───────────────────────────────────────────────────────────

def _target(world: World, table: str) -> str:
    return world.row(table, "A")


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_member_who_is_not_a_partner_cannot_clear_the_parent_of_a_row(world, table, column):
    dsn, row = world.dsn, _target(world, table)
    for who in ("manager_a", "executive_granted"):
        if table != "engagements" and who == "executive_granted":
            continue            # the tier is the letters'; the other three tables have no tier to separate the two
        outcome = _count_op(dsn, who, f"UPDATE {table} SET {column} = NULL WHERE id = '{row}'")
        assert _refused(outcome), f"{who} cleared {table}.{column}: {outcome}"
        assert "Only a Partner" in outcome, outcome
    assert _rows(dsn, f"SELECT {column} IS NOT NULL FROM {table} WHERE id = '{row}'") == [["t"]], f"{table}.{column} was cleared"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_partner_the_privileged_client_and_the_owner_may_clear_it(world, table, column):
    dsn, row = world.dsn, _target(world, table)
    for who in ("partner", "service_role", "owner"):
        assert _count_op(dsn, who, f"UPDATE {table} SET {column} = NULL WHERE id = '{row}'") == "1", f"{who} was refused"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_an_update_that_does_not_clear_it_is_untouched(world, table, column):
    dsn, row = world.dsn, _target(world, table)
    same = f"{column} = {column}"
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {same} WHERE id = '{row}'") == "1", "an update naming the column unchanged was refused"
    other = {"engagements": "title = 'renamed'", "customer_payment_events": "status = 'seen'", "properties": "updated_at = now()",
             "tally_migration_jobs": "name = 'renamed'"}[table]
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {other} WHERE id = '{row}'") == "1"


@pytest.mark.parametrize("table,column", CLEARABLE)
def test_a_write_that_leaves_a_null_parent_null_is_not_clearing_it(world, table, column):
    """A row with no parent that is written again with no parent (a lead's letter, a firm-level property or Tally job, an event not
    yet matched to a payment) has cleared nothing: the trigger asks that the column HAD a value."""
    row = world.row(table, "N")
    assert _count_op(world.dsn, "manager_none", f"UPDATE {table} SET {column} = NULL WHERE id = '{row}'") == "1"
    assert _count_op(world.dsn, "manager_none", f"UPDATE {table} SET {column} = {column} WHERE id = '{row}'") == "1"


@pytest.mark.parametrize("table,column,tag", [("engagements", "client_id", "N"), ("customer_payment_events", "payment_id", "N")])
def test_filling_a_cleared_parent_is_not_clearing_it(world, table, column, tag):
    """A lead's letter stamped with the client just made, an event matched to its payment afterwards."""
    value = CLIENT_A if column == "client_id" else world.row("customer_payments", "A")
    assert _count_op(world.dsn, "manager_a", f"UPDATE {table} SET {column} = '{value}' WHERE id = '{world.row(table, tag)}'") == "1"


def test_the_foreign_key_set_null_of_a_clients_deletion_run_as_the_owner_is_not_judged(world):
    """`fk_engagements_client` is ON DELETE SET NULL. The cascade runs in the session that deletes the client and the trigger
    reads the role setting, which a foreign-key action does not change: run as the table owner (the firm-purge-shaped case)
    it passes here; inside a signed-in non-Partner session it would be refused, which is harmless because no signed-in path
    deletes a client (the API soft-deletes, and a Partner passes). This covers the owner's session only."""
    dsn = world.dsn
    bare = "53700000-0000-0000-0000-0000000000d4"
    assert _psql(dsn, f"INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{bare}', '{FIRM}', 'Bare', 'Proprietorship');"
                      f"INSERT INTO engagements (firm_id, client_id, engagement_number, title) VALUES ('{FIRM}', '{bare}', 'EL-bare', 'bare');"
                      ).returncode == 0
    gone = _psql(dsn, f"DELETE FROM clients WHERE id = '{bare}';")
    assert gone.returncode == 0, gone.stderr
    assert _rows(dsn, "SELECT client_id IS NULL FROM engagements WHERE engagement_number = 'EL-bare'") == [["t"]]


# ── THE MIGRATION ────────────────────────────────────────────────────────────────

POLICY_NAMES = ([f"{t}_internal_partner_only" for t in NINE]
                + [f"{t}_write_tier_{c}" for t in ("engagements", "engagement_events") for c in ("insert", "update", "delete")])
TRIGGERS = ["a_letter_keeps_its_client_unless_a_partner_clears_it", "a_payment_event_keeps_its_payment_unless_a_partner_clears_it",
            "a_property_keeps_its_client_unless_a_partner_clears_it", "a_tally_job_keeps_its_client_unless_a_partner_clears_it"]


def _catalog(dsn: str) -> list:
    return _rows(dsn, "SELECT c.relname, p.polname, p.polpermissive, p.polcmd, pg_get_expr(p.polqual, p.polrelid), "
                      "pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                      f"WHERE p.polname = ANY(ARRAY{POLICY_NAMES}) ORDER BY 1, 2") + _rows(
        dsn, f"SELECT tgrelid::regclass::text, tgname, tgenabled FROM pg_trigger WHERE tgname = ANY(ARRAY{TRIGGERS}) ORDER BY 1, 2")


def _assignment_policies(dsn: str) -> list:
    return _rows(dsn, "SELECT polname, pg_get_expr(polwithcheck, polrelid) FROM pg_policy "
                      "WHERE polrelid = 'public.user_client_assignments'::regclass AND polcmd IN ('a', 'w') ORDER BY 1")


def test_the_two_assignment_policies_ask_for_the_practice_in_their_check_once_per_query(world):
    got = _assignment_policies(world.dsn)
    assert [r[0] for r in got] == ["partners_insert_assignments", "partners_update_assignments"], got
    for name, check in got:
        assert "client_id IS DISTINCT FROM ( SELECT my_internal_client_id()" in check, f"{name}: {check}"
        for helper in ("get_my_firm_id", "my_permission", "user_is_in_my_firm", "client_is_in_my_firm", "my_internal_client_id"):
            assert helper in check, f"{name} lost {helper}: {check}"


@pytest.mark.parametrize("table", ["engagements", "engagement_events"])
def test_the_write_tier_asks_who_is_calling_once_per_query_and_not_once_per_row(world, table):
    """Migration 525 wrapped every helper call in `(SELECT ...)` so it is evaluated once per query; a policy that calls
    `my_permission(...)` bare is evaluated per row (61 s against 6 s on 100,000 rows) and
    `test_a_policy_asks_who_is_calling_once_per_query_and_not_once_per_row_pg` refuses it in CI."""
    got = _rows(world.dsn, f"SELECT p.polname, coalesce(pg_get_expr(p.polqual, p.polrelid), ''), coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') "
                           f"FROM pg_policy p WHERE p.polrelid = 'public.{table}'::regclass AND p.polname LIKE '%_write_tier_%' ORDER BY 1")
    assert [r[0] for r in got] == sorted(f"{table}_write_tier_{c}" for c in ("insert", "update", "delete")), got
    for name, using, check in got:
        for expr in (using, check):
            assert expr.count("my_permission(") == expr.count("( SELECT my_permission("), f"{name}: {expr}"
        assert "my_permission(" in (using + check), name


def test_the_fifteen_policies_and_four_triggers_exist_and_the_function_is_not_a_browser_role_s(world):
    cat = _catalog(world.dsn)
    assert len([r for r in cat if r[1] in POLICY_NAMES]) == 15, cat
    assert sorted(r[1] for r in cat if r[1] in TRIGGERS) == sorted(TRIGGERS), cat
    assert all(r[2] == "O" for r in cat if r[1] in TRIGGERS)
    assert _rows(world.dsn, "SELECT has_function_privilege('authenticated', 'public.refuse_a_signed_in_member_clearing_the_parent_of_a_row()', 'EXECUTE'), "
                            "has_function_privilege('anon', 'public.refuse_a_signed_in_member_clearing_the_parent_of_a_row()', 'EXECUTE')") == [["f", "f"]]


def test_a_second_run_of_the_migration_changes_nothing(world):
    first, assignment = _catalog(world.dsn), _assignment_policies(world.dsn)
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _catalog(world.dsn) == first and _assignment_policies(world.dsn) == assignment


def test_the_rollback_restores_the_earlier_behaviour_and_a_reapply_closes_it_again(world):
    dsn = world.dsn
    reads = lambda: {t: _count_as(dsn, "manager_a", t) for t in NINE}
    guarded = reads()
    assert guarded["tasks"] == 1

    # rollbacks run in reverse order: migration 540 attaches this migration's trigger function to twelve more columns, and a function
    # that triggers depend on cannot be dropped
    for later in sorted(MIGRATIONS.glob("540_*_rollback.sql")):
        done = _psql_file(dsn, later)
        assert done.returncode == 0, done.stderr
    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    assert _catalog(dsn) == [], "the rollback left something behind"
    opened = reads()
    assert all(opened[t] == guarded[t] + 1 for t in NINE if t not in NULLABLE_CLIENT), opened            # the practice's row is back
    assert opened["workflow_instances"] == guarded["workflow_instances"] + 1
    letter = world.row("engagements", "A")
    assert _count_op(dsn, "partner", _assign("manager_none", INTERNAL)) == "1", "the assignment table does not take the practice again"
    assert _count_op(dsn, "reviewer_a", f"UPDATE engagements SET title = title WHERE id = '{letter}'") == "1", "the earlier firm-wide write is back"
    assert _count_op(dsn, "manager_a", f"UPDATE engagements SET client_id = NULL WHERE id = '{letter}'") == "1"

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert reads() == guarded
    assert _refused(_count_op(dsn, "partner", _assign("manager_none", INTERNAL)))
    assert _count_op(dsn, "reviewer_a", f"UPDATE engagements SET title = title WHERE id = '{letter}'") == "0"
    assert _refused(_count_op(dsn, "manager_a", f"UPDATE engagements SET client_id = NULL WHERE id = '{letter}'"))
