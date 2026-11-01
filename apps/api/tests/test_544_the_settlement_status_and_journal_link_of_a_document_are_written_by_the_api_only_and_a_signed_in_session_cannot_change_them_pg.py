"""Migration 544 — the settlement, status and journal link of an invoice, bill or note are written by the API only, and a signed-in
session cannot change them (POST-A-331, step 2).

WHAT WAS WRONG
    Migration 541 froze the particulars of an issued document and left the columns that say what has been settled against it, what
    state it is in and which journal entry it posted writable by a member who holds the tier, because the API wrote them AS THE
    CALLER. A member could mark an invoice paid or set its paid amount to anything, cancel an invoice or re-issue a cancelled one,
    issue a draft over PostgREST with none of the API's issue checks, and point a document at another journal entry. The API's
    writers moved to the privileged client first (`services/document_header_writer`), and this migration takes the permission away.

WHAT THIS HOLDS (a real database, as each person)
    * THE COLUMNS: for each of the six header tables, a Manager's and a Partner's change of each settlement column is refused with
      42501 and the sentence naming EXACTLY the columns changed, on a draft and on a document that is not; a statement that sends
      the value the row holds is not a change, and a statement that changes a soft column beside it is written, read back; the
      other columns are judged by migration 541 as before. The list is pinned from four sides: the trigger's arguments, its
      `UPDATE OF` list, the Python guard's own SETTLEMENT set, and 541's own allowed list (read from the catalogue), every column of
      which that is not watched here must be named in SOFT with a reason.
    * INSERT (judged by the `role` setting): a document is not born with a settlement (a paid amount, a negative one, an applied
      amount, a journal link, an issue stamp) not by a plain insert, not by an upsert's candidate or update branch, and not by
      `numbered_document_atomic`, the SECURITY DEFINER function that inserts the four note tables (the review of this migration
      found that a `current_user` test let it through); a draft or an opening document at the defaults is taken, and so is the row the
      API builds for an opening document.
    * WHO IS JUDGED, FOR AN UPDATE: `current_user`. The privileged client and the owner change everything; a SECURITY DEFINER
      function owned by the owner passes when a Manager calls it, and its SECURITY INVOKER twin is refused (the one difference the
      design stands on); the real `settle_receipt_atomic` still settles an invoice when the server calls it; the anonymous role is judged in a
      worst case. A foreign-key SET NULL passes because it runs as the table's owner, and there is NO exemption for a write made
      from inside another trigger: one that writes a settlement as the signed-in caller is refused. No function of the schema writes
      these tables except the two named, which is pinned from the function sources, dynamic SQL included.
    * A NAME THAT IS NOT A COLUMN (a watched column renamed later) makes the trigger refuse the write in its own words instead of
      silently ceasing to judge it.
    * THE MIGRATION: the function is SECURITY INVOKER, pins its search path, is not executable by a signed-in role even when the
      platform granted it first, the lock-taking statements run inside one block in both files with the lock mode, the retry count
      and the lock timeout pinned, that block waits for a busy table WITHOUT holding the other five (read off the runner's own
      locks) and gives up with its own sentence after fifteen seconds (the rollback too), a re-apply neither waits for a reader nor
      changes anything, the closing check fails after each of its spoilings on every one of the six tables, and the rollback
      brings the forgery back (the negative control) while a re-apply ends it.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import ast
import json
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
    reason="the settlement-column proof requires HARNESS_PG + psql",
)

_STEM = "544_the_settlement_status_and_journal_link_of_a_document_are_written_by_the_api_only_and_a_signed_in_session_cannot_change_them"
FUNCTION = "refuse_a_signed_in_change_of_a_documents_settlement"
TRIGGER = "a_documents_settlement_is_written_by_the_api_only"
TRIGGER_541 = "a_document_that_is_not_a_draft_keeps_its_particulars"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
GUARD_TEST = API_ROOT / "tests" / "test_the_document_header_writers_use_the_privileged_client_and_name_the_firm_and_client.py"

FIRM = "54400000-0000-0000-0000-000000000001"
CLIENT_A = "54400000-0000-0000-0000-0000000000a1"
CLIENT_B = "54400000-0000-0000-0000-0000000000b2"
BANK_ACC = "54400000-0000-0000-0000-0000000000c1"
AR_ACC = "54400000-0000-0000-0000-0000000000c2"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("54400000-0000-0000-0000-00000000000a", "54400000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("54400000-0000-0000-0000-00000000000b", "54400000-1111-0000-0000-000000000002", "Manager"),
    "reviewer_a": ("54400000-0000-0000-0000-00000000000f", "54400000-1111-0000-0000-000000000005", "Reviewer"),
}
CLIENT_A_MEMBERS = ("manager_a", "reviewer_a")
_F = f"'{FIRM}'"

# table -> (label, the status a document that is not a draft is in, may be created as an opening document)
SPECS = {
    "client_sales_invoices": ("invoice", "issued", True),
    "purchase_bills": ("bill", "received", True),
    "credit_notes": ("credit note", "issued", False),
    "debit_notes": ("debit note", "issued", False),
    "purchase_credit_notes": ("purchase credit note", "issued", False),
    "sales_debit_notes": ("sales debit note", "issued", False),
}
TABLES = list(SPECS)
OPENING_TABLES = [t for t in TABLES if SPECS[t][2]]

#: The columns each trigger watches, in the order the migration writes them. A column a later migration adds that says what has been
#: settled, what state a document is in or which journal entry it posted is caught by the classification test below (migration 541's
#: allowed list is read from the catalogue) until it is put here (and in the migration) or named in SOFT with a reason.
WATCHED = {
    "client_sales_invoices": ["status", "journal_entry_id", "issued_at", "paid_paise", "paid_txn", "credited_paise", "debit_note_paise"],
    "purchase_bills": ["status", "journal_entry_id", "received_at", "cancelled_at", "paid_paise", "paid_txn", "debited_paise", "credit_note_paise"],
    "credit_notes": ["status", "journal_entry_id", "applied_paise"],
    "debit_notes": ["status", "journal_entry_id", "applied_paise"],
    "purchase_credit_notes": ["status", "journal_entry_id", "applied_paise"],
    "sales_debit_notes": ["status", "journal_entry_id", "applied_paise"],
}
#: The watched columns migration 541 still lets a signed-in session change on a document that is not a draft: these are the ones that
#: only this migration closes. The other watched columns are frozen by 541 as well, whose refusal comes first on such a document.
ALLOWED_BY_541 = {
    "client_sales_invoices": {"status", "journal_entry_id", "paid_paise", "paid_txn", "credited_paise", "debit_note_paise"},
    "purchase_bills": {"status", "cancelled_at", "journal_entry_id", "paid_paise", "paid_txn", "debited_paise", "credit_note_paise"},
    "credit_notes": set(), "debit_notes": set(), "purchase_credit_notes": set(), "sales_debit_notes": set(),
}
#: Every column of the six tables that migration 541 lets a signed-in session change on a document that is not a draft, and that this
#: migration does NOT watch, with the reason it stays writable. The list is derived from the live catalogue (the arguments of 541's
#: trigger) and compared with this one in both directions, so a column a later migration adds to 541's allowed list fails here until
#: somebody has decided whether it is a settlement. (Every other column is frozen by 541 on a document that is not a draft, and a
#: draft is the API's to judge, which is POST-A-335.)
SOFT = {
    "client_sales_invoices": {
        "reference_no": "a reference the CA types", "notes": "free text", "due_date": "the payment terms", "credit_days": "the payment terms",
        "shipping_bill_no": "the export's shipping bill, declared once it exists", "shipping_bill_date": "as shipping_bill_no",
        "port_code": "as shipping_bill_no", "updated_at": "a stamp",
        "last_reminded_at": "collections metadata: when a reminder went out", "reminder_count": "collections metadata",
        "is_overdue": "collections metadata, derived", "days_overdue": "collections metadata, derived",
        "aging_bucket": "collections metadata, derived", "last_internal_followup_at": "an internal follow-up stamp",
        "internal_followup_count": "an internal follow-up counter",
    },
    "purchase_bills": {
        "notes": "free text", "due_date": "the payment terms", "credit_days": "the payment terms", "our_reference": "a reference the CA types",
        "document_url": "the attached document", "form_15ca_ack_no": "a Form 15CA reference the CA records",
        "form_15ca_filed_on": "as form_15ca_ack_no", "form_15cb_udin": "a Form 15CB reference the CA records", "updated_at": "a stamp",
        "landed_cost_basis": "how freight is apportioned across the lines",
    },
    "credit_notes": {"notes": "free text", "updated_at": "a stamp"},
    "debit_notes": {"notes": "free text", "document_url": "the attached document"},
    "purchase_credit_notes": {"notes": "free text", "document_url": "the attached document"},
    "sales_debit_notes": {"notes": "free text", "updated_at": "a stamp"},
}
TRIGGER_541 = "a_document_that_is_not_a_draft_keeps_its_particulars"


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
    if who == "anon":
        return "SET request.jwt.claims = '{\"role\": \"anon\"}'; SET ROLE anon; "
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err:<SQLSTATE> <message>` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err:% %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _commit_as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    """Run `sql` as `who` and KEEP it, so that what it did can be read back as the owner."""
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + sql], capture_output=True, text=True)


def _named(outcome: str) -> set[str]:
    """The columns this trigger's refusal names: the words between 'have its' and 'changed' (an UPDATE) or after 'already carrying'
    and before ' :' (an INSERT)."""
    m = re.search(r"cannot have its (.+?) changed from a signed-in session", outcome) or re.search(r"already carrying (.+?) : what has", outcome)
    return {c.strip() for c in m.group(1).split(",")} if m else set()


def _by_the_settlement_trigger(outcome: str, *columns: str) -> bool:
    """Refused by THIS trigger (migration 541's refusal is also 42501, with another sentence; so is a row-security one), and naming
    EXACTLY the columns given, so that a sentence which merely contains the word 'status' proves nothing."""
    return (outcome.startswith("err:42501") and "what has been settled against a document" in outcome
            and (not columns or _named(outcome) == set(columns)))


def _by_541(outcome: str) -> bool:
    return outcome.startswith("err:42501") and "from a signed-in session" in outcome and "what has been settled against" not in outcome


def _wrote(outcome: str) -> bool:
    return outcome == "1"


# ── THE SEED ────────────────────────────────────────────────────────────────

def _insert(table: str, cols: dict) -> str:
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(cols.values())})"


def _header_values(table: str, status: str, n: int, ids: dict) -> dict:
    cust, vend = ids["customer"], ids["vendor"]
    base = {"firm_id": _F, "client_id": _q(CLIENT_A), "status": _q(status)}
    return {
        "client_sales_invoices": {"customer_id": _q(cust), "invoice_no": _q(f"INV-{n}"), "invoice_date": "'2026-04-01'"},
        "purchase_bills": {"vendor_id": _q(vend), "bill_no": _q(f"B-{n}"), "bill_date": "'2026-04-01'"},
        "credit_notes": {"customer_id": _q(cust), "credit_note_no": _q(f"CN-{n}"), "credit_note_date": "'2026-04-01'"},
        "debit_notes": {"vendor_id": _q(vend), "debit_note_no": _q(f"DN-{n}"), "debit_note_date": "'2026-04-01'"},
        "purchase_credit_notes": {"vendor_id": _q(vend), "credit_note_no": _q(f"PCN-{n}"), "credit_note_date": "'2026-04-01'"},
        "sales_debit_notes": {"customer_id": _q(cust), "debit_note_no": _q(f"SDN-{n}"), "debit_note_date": "'2026-04-01'"},
    }[table] | base


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

    def owner(self, sql: str) -> None:
        done = _psql(self.dsn, "SET session_replication_role = replica; " + sql)
        assert done.returncode == 0, done.stderr

    def value(self, sql: str) -> str:
        return _rows(self.dsn, sql)[0][0]


def _seed(w: World) -> None:
    ids = {"customer": w.value(f"SELECT id FROM customers WHERE client_id = '{CLIENT_A}'"),
           "vendor": w.put("vendors", "x", {"firm_id": _F, "client_id": _q(CLIENT_A), "name": "'vendor'"})}
    n = 0
    for table, (_label, non_draft, opening) in SPECS.items():
        for tag, status in (("draft", "draft"), ("issued", non_draft)):
            n += 1
            w.put(table, tag, _header_values(table, status, n, ids))
        if opening:
            n += 1
            w.put(table, "opening", _header_values(table, non_draft, n, ids) | {"is_opening": "true"})
    entry = _rows(w.dsn, "SET session_replication_role = replica; INSERT INTO journal_entries (firm_id, client_id, entry_date, narration, entry_type) "
                         f"VALUES ('{FIRM}', '{CLIENT_A}', '2026-04-01', 'seed', 'Journal') RETURNING id;")
    w.ids["journal"] = {"x": [r[0] for r in entry if re.fullmatch(r"[0-9a-f-]{36}", r[0])][0]}


@pytest.fixture(scope="module")
def seeded(pg_template):
    admin = _ADMIN.strip()
    name = f"e544s_{uuid.uuid4().hex[:12]}"
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
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO customers (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT_A}', 'cust A');
            INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
              ('{BANK_ACC}', '{FIRM}', '{CLIENT_A}', 'BANK-1', 'Bank Account', 'Asset'),
              ('{AR_ACC}', '{FIRM}', '{CLIENT_A}', 'AR-1', 'Trade Receivables', 'Asset');
            -- two functions that write an invoice's settlement, one as its owner and one as the caller: the difference the design
            -- stands on
            CREATE FUNCTION public.t544_as_owner(doc uuid) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS
              $f$ UPDATE client_sales_invoices SET paid_paise = 5, status = 'partially_paid' WHERE id = doc $f$;
            CREATE FUNCTION public.t544_as_caller(doc uuid) RETURNS void LANGUAGE sql SECURITY INVOKER SET search_path = public AS
              $f$ UPDATE client_sales_invoices SET paid_paise = 5, status = 'partially_paid' WHERE id = doc $f$;
            GRANT EXECUTE ON FUNCTION public.t544_as_owner(uuid), public.t544_as_caller(uuid) TO authenticated;
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
    name = f"e544_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        w = World(f"{admin} dbname={name}")
        w.ids = {table: dict(rows) for table, rows in ids.items()}
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _ids(world: World) -> dict:
    return {"customer": world.value("SELECT id FROM customers LIMIT 1"), "vendor": world.row("vendors", "x")}


def _non_draft(table: str) -> str:
    return SPECS[table][1]


def _column_info(dsn: str, table: str) -> dict:
    return {r[0]: r[1] for r in _rows(
        dsn, f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{table}' "
             "ORDER BY ordinal_position")}


def _refused_value(world: World, table: str, col: str) -> str:
    """A value that differs from what the row holds. It need not satisfy the column's CHECK or foreign key: this trigger runs first."""
    ty = _column_info(world.dsn, table)[col]
    if col == "status":
        return "'cancelled'"
    if ty == "uuid":
        return "gen_random_uuid()"
    if ty == "timestamp with time zone":
        return f"COALESCE({col}, now()) + interval '1 day'"
    return f"COALESCE({col}, 0) + 1"


def _valid_value(world: World, table: str, col: str) -> str:
    """A value the whole row accepts, for the callers the trigger lets through."""
    if col == "status":
        return "'draft'"
    if col == "journal_entry_id":
        return f"'{world.row('journal', 'x')}'"
    return _refused_value(world, table, col)


def _default_insert_value(world: World, table: str, col: str) -> str:
    """A value that is NOT the column's default (zero or NULL), valid for its type, for an INSERT that must be refused."""
    ty = _column_info(world.dsn, table)[col]
    if ty == "uuid":
        return "gen_random_uuid()"
    if ty == "timestamp with time zone":
        return "now()"
    return "1"


SETTLEMENT_CASES = [(t, c) for t in TABLES for c in WATCHED[t]]
INSERT_CASES = [(t, c) for t in TABLES for c in WATCHED[t] if c != "status"]


# ── THE LIST, PINNED FROM THREE SIDES ───────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_the_trigger_is_the_one_written_with_exactly_the_columns_pinned_here(world, table):
    got = _rows(world.dsn, f"SELECT tgtype::int, tgenabled::text, encode(tgargs, 'hex'), "
                           f"(SELECT string_agg(a.attname::text, ',' ORDER BY a.attname) FROM unnest(tgattr) k(num) "
                           f"   JOIN pg_attribute a ON a.attrelid = tgrelid AND a.attnum = k.num) "
                           f"FROM pg_trigger WHERE tgrelid = 'public.{table}'::regclass AND tgname = '{TRIGGER}' AND NOT tgisinternal")
    assert len(got) == 1, got
    tgtype, enabled, args, columns = got[0]
    assert (tgtype, enabled) == ("23", "O"), "ROW + BEFORE + INSERT + UPDATE, enabled"
    cols, label = bytes.fromhex(args).decode().split("\x00")[:2]
    assert cols.split(",") == WATCHED[table] and label == SPECS[table][0], (cols, label)
    assert columns == ",".join(sorted(WATCHED[table])), "the UPDATE OF list is not the argument list"


@pytest.mark.parametrize("table", TABLES)
def test_every_column_541_leaves_writable_is_watched_here_or_named_soft_with_a_reason(world, table):
    """Migration 541's allowed list is read from the catalogue, so a column added to it later cannot slip past this migration unseen:
    it must be put in WATCHED (and the trigger) or in SOFT with a reason. No name heuristic stands in for that."""
    got = _rows(world.dsn, f"SELECT encode(tgargs, 'hex') FROM pg_trigger WHERE tgrelid = 'public.{table}'::regclass "
                           f"AND tgname = '{TRIGGER_541}' AND NOT tgisinternal")
    assert len(got) == 1, got
    allowed_541 = set(bytes.fromhex(got[0][0]).decode().split("\x00")[0].split(","))
    assert allowed_541 - set(WATCHED[table]) == set(SOFT[table]), (
        f"{table}: 541 allows {sorted(allowed_541 - set(WATCHED[table]) - set(SOFT[table]))} that is neither watched nor named soft; "
        f"named soft but not allowed by 541: {sorted(set(SOFT[table]) - (allowed_541 - set(WATCHED[table])))}")
    columns = set(_column_info(world.dsn, table))
    assert set(WATCHED[table]) <= columns and set(SOFT[table]) <= columns, "a named column does not exist"
    assert ALLOWED_BY_541[table] == set(WATCHED[table]) & allowed_541, (table, "ALLOWED_BY_541 is the watched columns 541 leaves open")


def test_the_python_guards_settlement_set_is_the_set_this_migration_watches(world):
    """The API's writers were moved by a static check over SETTLEMENT; the database refuses the same columns. If one learns a column
    the other does not know, the writer moved for nothing or the refusal catches a writer the check never saw."""
    tree = ast.parse(GUARD_TEST.read_text())
    settlement = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                      if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "SETTLEMENT" for t in n.targets))
    for table in TABLES:
        columns = set(_column_info(world.dsn, table))
        assert settlement & columns == set(WATCHED[table]), (table, sorted((settlement & columns) ^ set(WATCHED[table])))


# ── UPDATE: THE COLUMNS ARE REFUSED ─────────────────────────────────────────

@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table,col", SETTLEMENT_CASES)
def test_a_change_of_a_settlement_column_of_a_document_that_is_not_a_draft_is_refused(world, table, col, who):
    """Where migration 541 already froze the column its refusal comes first and is the one asserted; where 541 left it writable (the
    settlement columns it names as open) the refusal is this migration's, in its words, naming exactly that column."""
    doc = world.row(table, "issued")
    out = _op(world.dsn, who, f"UPDATE {table} SET {col} = {_refused_value(world, table, col)} WHERE id = '{doc}'")
    if col in ALLOWED_BY_541[table]:
        assert _by_the_settlement_trigger(out, col) and f"The {SPECS[table][0]} cannot have its" in out, f"{table}.{col}: {out}"
    else:
        assert _by_541(out) and col in out, f"{table}.{col}: {out}"


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table,col", SETTLEMENT_CASES)
def test_a_change_of_a_settlement_column_of_a_draft_is_refused_too(world, table, col, who):
    """A draft's update is migration 541's API-judged: issuing it over PostgREST is exactly what this closes. Here 541 says nothing,
    so every refusal is this migration's."""
    doc = world.row(table, "draft")
    value = f"'{_non_draft(table)}'" if col == "status" else _refused_value(world, table, col)
    out = _op(world.dsn, who, f"UPDATE {table} SET {col} = {value} WHERE id = '{doc}'")
    assert _by_the_settlement_trigger(out, col) and f"The {SPECS[table][0]} cannot have its" in out, f"{table}.{col}: {out}"


@pytest.mark.parametrize("table,col", SETTLEMENT_CASES)
def test_a_statement_that_sends_the_value_the_row_holds_is_not_a_change(world, table, col):
    for tag in ("draft", "issued"):
        doc = world.row(table, tag)
        assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET {col} = {col} WHERE id = '{doc}'")), (table, col, tag)


@pytest.mark.parametrize("tag", ["draft", "issued"])
@pytest.mark.parametrize("table", TABLES)
def test_a_whole_row_patch_that_changes_a_soft_column_and_sends_every_settlement_column_unchanged_is_written_in_full(world, table, tag):
    """The shape of a form that sends the whole row back. The trigger fires (a watched column is named), lets it through and must
    hand back the row it was given: a write the trigger lets through is read back, not merely counted."""
    doc = world.row(table, tag)
    watched = ", ".join(f"{c}::text" for c in WATCHED[table])
    before = _rows(world.dsn, f"SELECT {watched} FROM {table} WHERE id = '{doc}'")
    sets = ", ".join(f"{c} = {c}" for c in WATCHED[table])
    done = _commit_as(world.dsn, "manager_a", f"UPDATE {table} SET {sets}, notes = 'edited in full' WHERE id = '{doc}'")
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT notes FROM {table} WHERE id = '{doc}'") == [["edited in full"]]
    assert _rows(world.dsn, f"SELECT {watched} FROM {table} WHERE id = '{doc}'") == before


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table", TABLES)
def test_a_refused_statement_names_the_columns_it_refused_and_writes_nothing_beside_them(world, table, who):
    doc = world.row(table, "draft")
    col = WATCHED[table][-1]
    before = _rows(world.dsn, f"SELECT coalesce(notes, ''), {col}::text FROM {table} WHERE id = '{doc}'")
    done = _commit_as(world.dsn, who, f"UPDATE {table} SET notes = 'changed', {col} = {_refused_value(world, table, col)} WHERE id = '{doc}'")
    assert done.returncode != 0 and f"cannot have its {col} changed from a signed-in session" in done.stderr, done.stderr
    assert _rows(world.dsn, f"SELECT coalesce(notes, ''), {col}::text FROM {table} WHERE id = '{doc}'") == before


@pytest.mark.parametrize("table", TABLES)
def test_a_soft_column_is_still_changed_by_a_manager_and_is_there_afterwards(world, table):
    doc = world.row(table, "issued")
    done = _commit_as(world.dsn, "manager_a", f"UPDATE {table} SET notes = 'a note' WHERE id = '{doc}'")
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT notes FROM {table} WHERE id = '{doc}'") == [["a note"]]


_SOFT_VALUES = {"reference_no": "'ref'", "reminder_count": "COALESCE(reminder_count, 0) + 1", "is_overdue": "NOT COALESCE(is_overdue, false)",
                "last_reminded_at": "now()", "landed_cost_basis": "'quantity'", "due_date": "'2026-12-31'", "our_reference": "'ours'",
                "credit_days": "COALESCE(credit_days, 0) + 1", "days_overdue": "COALESCE(days_overdue, 0) + 1",
                "aging_bucket": "'90+'", "last_internal_followup_at": "now()", "internal_followup_count": "COALESCE(internal_followup_count, 0) + 1",
                "shipping_bill_no": "'SB-1'", "port_code": "'INBOM1'", "shipping_bill_date": "'2026-04-02'", "document_url": "'https://x.test/d.pdf'",
                "form_15ca_ack_no": "'ACK-1'", "form_15ca_filed_on": "'2026-04-02'", "form_15cb_udin": "'UDIN-1'", "updated_at": "now()"}
SOFT_CASES = [(t, c) for t in TABLES for c in SOFT[t] if c != "notes"]


@pytest.mark.parametrize("table,col", SOFT_CASES)
def test_every_soft_column_541_allows_is_still_changed_and_is_there_afterwards(world, table, col):
    doc = world.row(table, "issued")
    before = _rows(world.dsn, f"SELECT {col}::text FROM {table} WHERE id = '{doc}'")
    done = _commit_as(world.dsn, "manager_a", f"UPDATE {table} SET {col} = {_SOFT_VALUES[col]} WHERE id = '{doc}'")
    assert done.returncode == 0, (table, col, done.stderr)
    if col != "updated_at":                                # a stamp is also moved by the table's own trigger
        assert _rows(world.dsn, f"SELECT {col}::text FROM {table} WHERE id = '{doc}'") != before, (table, col)


@pytest.mark.parametrize("table", TABLES)
def test_a_frozen_column_is_still_refused_by_migration_541_and_in_its_own_words(world, table):
    doc = world.row(table, "issued")
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET total_paise = total_paise + 1 WHERE id = '{doc}'")
    assert _by_541(out) and "total_paise" in out, out


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table", TABLES)
def test_a_draft_is_still_edited_freely_in_everything_but_its_settlement(world, table, who):
    doc = world.row(table, "draft")
    assert _wrote(_op(world.dsn, who, f"UPDATE {table} SET total_paise = total_paise + 1, taxable_amount_paise = 5 WHERE id = '{doc}'"))


@pytest.mark.parametrize("table", TABLES)
def test_issuing_a_draft_over_postgrest_is_refused_and_it_stays_a_draft(world, table):
    doc = world.row(table, "draft")
    done = _commit_as(world.dsn, "manager_a", f"UPDATE {table} SET status = '{_non_draft(table)}', total_paise = 5000 WHERE id = '{doc}'")
    assert done.returncode != 0 and "cannot have its status changed from a signed-in session" in done.stderr, done.stderr
    assert _rows(world.dsn, f"SELECT status, total_paise FROM {table} WHERE id = '{doc}'") == [["draft", "0"]]


@pytest.mark.parametrize("table", ["client_sales_invoices", "purchase_bills"])
def test_cancelling_an_issued_invoice_or_bill_over_postgrest_is_refused(world, table):
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET status = 'cancelled' WHERE id = '{world.row(table, 'issued')}'")
    assert _by_the_settlement_trigger(out, "status"), out


@pytest.mark.parametrize("table", ["client_sales_invoices", "purchase_bills"])
def test_marking_an_invoice_or_bill_paid_by_hand_is_refused(world, table):
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET status = 'paid', paid_paise = total_paise + 100 WHERE id = '{world.row(table, 'issued')}'")
    assert _by_the_settlement_trigger(out, "paid_paise", "status"), out


def test_the_refusal_names_every_column_it_refused_in_a_stable_order(world):
    doc = world.row("purchase_bills", "issued")
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'paid', paid_paise = 5, debited_paise = 5 WHERE id = '{doc}'")
    assert _by_the_settlement_trigger(out, "debited_paise", "paid_paise", "status"), out
    assert "cannot have its debited_paise, paid_paise, status changed" in out, out


# ── INSERT (judged by the role setting) ─────────────────────────────────────

@pytest.mark.parametrize("table,col", INSERT_CASES)
def test_a_document_is_not_born_with_a_settlement(world, table, col):
    values = _header_values(table, "draft", 800, _ids(world)) | {col: _default_insert_value(world, table, col)}
    out = _op(world.dsn, "manager_a", _insert(table, values))
    assert _by_the_settlement_trigger(out, col) and f"A {SPECS[table][0]} cannot be created from a signed-in session" in out, f"{table}.{col}: {out}"


@pytest.mark.parametrize("table,col", [(t, c) for t, c in INSERT_CASES if c.endswith("_paise") or c == "paid_txn"])
def test_a_document_is_not_born_with_a_negative_settlement_either(world, table, col):
    values = _header_values(table, "draft", 807, _ids(world)) | {col: "-1"}
    out = _op(world.dsn, "manager_a", _insert(table, values))
    assert _by_the_settlement_trigger(out, col), f"{table}.{col}: {out}"


@pytest.mark.parametrize("table", TABLES)
def test_an_insert_naming_several_settlement_columns_names_them_all(world, table):
    cols = [c for c in WATCHED[table] if c != "status"]
    values = _header_values(table, "draft", 808, _ids(world)) | {c: _default_insert_value(world, table, c) for c in cols}
    out = _op(world.dsn, "manager_a", _insert(table, values))
    assert _by_the_settlement_trigger(out, *cols), out
    assert f"already carrying {', '.join(sorted(cols))} :" in out, out


@pytest.mark.parametrize("table", TABLES)
def test_a_draft_inserted_with_the_defaults_or_with_explicit_zeros_and_nulls_is_taken(world, table):
    values = _header_values(table, "draft", 801, _ids(world))
    assert _wrote(_op(world.dsn, "manager_a", _insert(table, values)))
    zeros = {c: ("NULL" if c in ("journal_entry_id", "issued_at", "received_at", "cancelled_at") else "0")
             for c in WATCHED[table] if c != "status"}
    assert _wrote(_op(world.dsn, "manager_a", _insert(table, _header_values(table, "draft", 802, _ids(world)) | zeros)))


@pytest.mark.parametrize("table", OPENING_TABLES)
def test_an_opening_document_is_still_inserted(world, table):
    values = _header_values(table, _non_draft(table), 803, _ids(world)) | {"is_opening": "true", "total_paise": "5000"}
    assert _wrote(_op(world.dsn, "manager_a", _insert(table, values)))


@pytest.mark.parametrize("kind", ["receivable", "payable"])
def test_the_row_the_api_builds_for_an_opening_document_is_still_taken(world, kind):
    from domain.accounting import opening_documents as od
    party = _ids(world)["customer" if kind == od.RECEIVABLE else "vendor"]
    row = od.row_for(kind=kind, firm_id=FIRM, client_id=CLIENT_A, party_id=party, document_no="OPEN-API-544", document_date="2026-03-31",
                     due_date="2026-04-30", outstanding_paise=12345, notes="carried over")
    values = {k: ("NULL" if v is None else "true" if v is True else "false" if v is False else str(v) if isinstance(v, int) else _q(v))
              for k, v in row.items()}
    assert _wrote(_op(world.dsn, "manager_a", _insert(od.TABLES[kind], values)))


def test_an_upserts_insert_candidate_and_its_update_branch_are_both_judged(world):
    """The candidate is a draft (migration 541 admits a draft, or an opening document, and nothing else), so what refuses is this
    migration: once for a candidate that carries a settlement, once for the update branch that writes one into the row it conflicts with."""
    inv = world.row("client_sales_invoices", "issued")
    key = world.value(f"SELECT invoice_no FROM client_sales_invoices WHERE id = '{inv}'")
    values = _header_values("client_sales_invoices", "draft", 804, _ids(world)) | {"invoice_no": _q(key)}
    on = "ON CONFLICT (firm_id, client_id, invoice_no) WHERE deleted_at IS NULL DO UPDATE SET"
    update_branch = _op(world.dsn, "manager_a", _insert("client_sales_invoices", values) + f" {on} paid_paise = 5")
    assert _by_the_settlement_trigger(update_branch, "paid_paise") and "cannot have its" in update_branch, update_branch
    candidate = _op(world.dsn, "manager_a", _insert("client_sales_invoices", values | {"paid_paise": "5"}) + f" {on} notes = 'x'")
    assert _by_the_settlement_trigger(candidate, "paid_paise") and "cannot be created" in candidate, candidate
    harmless = _op(world.dsn, "manager_a", _insert("client_sales_invoices", values) + f" {on} notes = 'x'")
    assert _wrote(harmless), harmless                      # an upsert that settles nothing is taken


_NOTE_TABLES = ["credit_notes", "debit_notes", "purchase_credit_notes", "sales_debit_notes"]
#: what the wrapper accepts: (header table, lines table, the lines' foreign key column) - its own whitelist, migration 486
_NUMBERED = {"credit_notes": ("credit_note_lines", "credit_note_id"), "debit_notes": ("debit_note_lines", "debit_note_id"),
             "purchase_credit_notes": ("purchase_credit_note_lines", "credit_note_id"), "sales_debit_notes": ("sales_debit_note_lines", "debit_note_id")}


def _numbered_header(world: World, table: str, **extra) -> str:
    party = ("customer_id", _ids(world)["customer"]) if table in ("credit_notes", "sales_debit_notes") else ("vendor_id", _ids(world)["vendor"])
    number_col = {"credit_notes": "credit_note_no", "purchase_credit_notes": "credit_note_no",
                  "debit_notes": "debit_note_no", "sales_debit_notes": "debit_note_no"}[table]
    date_col = number_col[:-3] + "_date"
    keys = {"firm_id": FIRM, "client_id": CLIENT_A, party[0]: party[1], number_col: "NUM-544", date_col: "2026-06-01", "status": "draft", **extra}
    return "jsonb_build_object(" + ", ".join(f"'{k}', " + (str(v) if isinstance(v, (int, float)) else f"'{v}'") for k, v in keys.items()) + ")"


@pytest.mark.parametrize("col,value", [("applied_paise", 118000), ("journal_entry_id", "uuid"), ("applied_paise", -5)])
@pytest.mark.parametrize("table", _NOTE_TABLES)
def test_numbered_document_atomic_does_not_give_a_manager_the_owners_pass_on_an_insert(world, table, col, value):
    """The review found it: that function is SECURITY DEFINER and inserts the note from whatever header it is handed, so a trigger
    judging `current_user` on an INSERT let a Manager create a note already carrying a paid amount or a journal link through the
    RPC. The INSERT is judged by the role setting, which stays the caller's inside it."""
    extra = {col: world.row("journal", "x") if value == "uuid" else value}
    sql = f"SELECT numbered_document_atomic('{table}', {_numbered_header(world, table, **extra)}, '{_NUMBERED[table][0]}', '[]'::jsonb, '{_NUMBERED[table][1]}');"
    done = _commit_as(world.dsn, "manager_a", sql)
    assert done.returncode != 0 and "what has been settled against a document" in done.stderr and f"already carrying {col}" in done.stderr, done.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM {table} WHERE {'credit_note_no' if 'credit' in table else 'debit_note_no'} = 'NUM-544'") == [["0"]]


@pytest.mark.parametrize("table", _NOTE_TABLES)
def test_numbered_document_atomic_still_creates_a_clean_note_for_a_manager(world, table):
    sql = f"SELECT numbered_document_atomic('{table}', {_numbered_header(world, table)}, '{_NUMBERED[table][0]}', '[]'::jsonb, '{_NUMBERED[table][1]}');"
    done = _commit_as(world.dsn, "manager_a", sql)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT status, applied_paise::text, coalesce(journal_entry_id::text, '') FROM {table} "
                            f"WHERE {'credit_note_no' if 'credit' in table else 'debit_note_no'} = 'NUM-544'") == [["draft", "0", ""]]


# ── WHO IS JUDGED ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["service_role", "owner"])
@pytest.mark.parametrize("table", TABLES)
def test_the_privileged_client_and_the_owner_change_every_settlement_column_and_insert_one_born_with_a_settlement(world, table, who):
    doc = world.row(table, "issued")
    for col in WATCHED[table]:
        out = _op(world.dsn, who, f"UPDATE {table} SET {col} = {_valid_value(world, table, col)} WHERE id = '{doc}'")
        assert _wrote(out), (table, col, who, out)
    born = _header_values(table, "draft", 805, _ids(world)) | {"journal_entry_id": _q(world.row("journal", "x"))}
    assert _wrote(_op(world.dsn, who, _insert(table, born | {c: "1" for c in WATCHED[table] if c.endswith("_paise")})))


def test_a_function_that_runs_as_its_owner_settles_for_a_manager_and_its_invoker_twin_is_refused(world):
    """The difference the whole design stands on, shown in a function that is not the product's: inside a SECURITY DEFINER function
    the statement runs as the function's owner, and inside a SECURITY INVOKER one as the caller."""
    inv = world.row("client_sales_invoices", "issued")
    done = _commit_as(world.dsn, "manager_a", f"SELECT public.t544_as_owner('{inv}')")
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id = '{inv}'") == [["5", "partially_paid"]]
    inv2 = world.row("client_sales_invoices", "opening")
    out = _op(world.dsn, "manager_a", f"PERFORM public.t544_as_caller('{inv2}')")
    assert _by_the_settlement_trigger(out, "paid_paise", "status"), out


def test_the_real_receipt_settlement_still_settles_an_invoice_when_the_server_posts_it(world):
    """`settle_receipt_atomic` is what the API's plain rupee receipt calls and what the trigger must not refuse: it is SECURITY DEFINER,
    runs as its owner, and writes the invoice's paid amount and status inside the database. The `role` setting migrations 498 to 543
    test would have judged it as the caller. It is called as the SERVER, as the API calls it since migration 546 took the signed-in
    grant away (a Manager's own token is refused by the privilege, which test_546_... asserts)."""
    inv = world.row("client_sales_invoices", "issued")
    world.owner(f"UPDATE client_sales_invoices SET total_paise = 100000 WHERE id = '{inv}'")
    cust = _ids(world)["customer"]
    receipt = {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": CLIENT_A, "customer_id": cust, "receipt_no": "RCPT-544-1",
               "receipt_date": "2026-04-05", "amount_paise": 100000, "tds_paise": 0, "unallocated_paise": 0, "payment_mode": "bank",
               "reference_no": "", "notes": ""}
    entry = {"firm_id": FIRM, "client_id": CLIENT_A, "entry_date": "2026-04-05", "reference_no": "RCPT-544-1", "narration": "Receipt",
             "entry_type": "Receipt", "is_posted": True, "status": "posted"}
    lines = [{"account_id": BANK_ACC, "debit_paise": 100000, "credit_paise": 0, "narration": "bank", "rate_type": "booking", "rate_date": "2026-04-05"},
             {"account_id": AR_ACC, "debit_paise": 0, "credit_paise": 100000, "narration": "ar", "rate_type": "booking", "rate_date": "2026-04-05"}]
    alloc = [{"sales_invoice_id": inv, "allocated_paise": 100000}]
    sql = (f"SELECT settle_receipt_atomic('{json.dumps(receipt)}'::jsonb, '{json.dumps(entry)}'::jsonb, "
           f"'{json.dumps(lines)}'::jsonb, '{json.dumps(alloc)}'::jsonb);")
    done = _commit_as(world.dsn, "service_role", sql)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT paid_paise, status FROM client_sales_invoices WHERE id = '{inv}'") == [["100000", "paid"]]
    # and the same invoice cannot be pushed further by hand
    assert _by_the_settlement_trigger(_op(world.dsn, "manager_a", f"UPDATE client_sales_invoices SET paid_paise = 0 WHERE id = '{inv}'"), "paid_paise")


@pytest.mark.parametrize("table", TABLES)
def test_the_anonymous_role_is_judged_as_well(world, table):
    """Production's platform defaults grant `anon` every privilege on a public table and row security is all that keeps it out; a
    database built from the migrations grants it nothing. The worst case: `anon` is granted the writes and row security is off, so
    the trigger is the only thing between it and a settlement. Every watched column is tried, as an update of a draft and as an insert."""
    done = _psql(world.dsn, f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO anon; ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    assert done.returncode == 0, done.stderr
    draft = world.row(table, "draft")
    assert _wrote(_op(world.dsn, "anon", f"UPDATE {table} SET total_paise = total_paise + 1 WHERE id = '{draft}'")), "the worst case was not made"
    for col in WATCHED[table]:
        value = f"'{_non_draft(table)}'" if col == "status" else _refused_value(world, table, col)
        assert _by_the_settlement_trigger(_op(world.dsn, "anon", f"UPDATE {table} SET {col} = {value} WHERE id = '{draft}'"), col), (table, col)
        if col != "status":
            born = _header_values(table, "draft", 806, _ids(world)) | {col: _default_insert_value(world, table, col)}
            assert _by_the_settlement_trigger(_op(world.dsn, "anon", _insert(table, born)), col), (table, col)


def test_a_foreign_key_set_null_of_the_journal_link_passes_because_it_runs_as_the_tables_owner(world):
    """The invoice's journal link is ON DELETE SET NULL. PostgreSQL runs a referential action as the owner of the table it updates, so
    `current_user` inside it is the owner and the trigger lets it through with no rule of its own (an earlier version of this migration
    exempted it by trigger depth, which the review showed to be redundant and a bypass for any other nested write). No signed-in
    session can delete a journal entry (the grant is revoked), so the worst case is made: `authenticated` is granted the delete and
    row security is off, so that the entry is deleted AS the signed-in role."""
    inv = world.row("client_sales_invoices", "issued")
    entry = world.row("journal", "x")
    assert _psql(world.dsn, "GRANT DELETE ON journal_entries TO authenticated; ALTER TABLE journal_entries DISABLE ROW LEVEL SECURITY;").returncode == 0
    world.owner(f"UPDATE client_sales_invoices SET journal_entry_id = '{entry}' WHERE id = '{inv}'")
    # the same column changed directly is refused (by 541, which keeps a link once made)
    direct = _op(world.dsn, "manager_a", f"UPDATE client_sales_invoices SET journal_entry_id = NULL WHERE id = '{inv}'")
    assert direct.startswith("err:42501") and "journal" in direct, direct
    done = _commit_as(world.dsn, "manager_a", f"DELETE FROM journal_entries WHERE id = '{entry}'")
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT coalesce(journal_entry_id::text, 'null') FROM client_sales_invoices WHERE id = '{inv}'") == [["null"]]


def test_a_write_made_from_inside_another_trigger_as_the_signed_in_caller_is_judged_like_any_other(world):
    """There is no exemption for a nested write. A SECURITY INVOKER trigger on another table that writes a settlement runs as the
    caller, so it is refused (an UPDATE) and so is a document it inserts carrying one. The schema has no such trigger (the test after
    this one); this is what would happen if somebody wrote one."""
    done = _psql(world.dsn, """
        CREATE TABLE public.t544_probe (id int);
        GRANT INSERT ON public.t544_probe TO authenticated;
        CREATE FUNCTION public.t544_probe_fn() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS
          $f$ BEGIN UPDATE public.client_sales_invoices SET paid_paise = 7 WHERE status = 'issued'; RETURN NEW; END $f$;
        CREATE TRIGGER t544_probe_t AFTER INSERT ON public.t544_probe FOR EACH ROW EXECUTE FUNCTION public.t544_probe_fn();
    """)
    assert done.returncode == 0, done.stderr
    out = _op(world.dsn, "manager_a", "INSERT INTO public.t544_probe VALUES (1)")
    assert _by_the_settlement_trigger(out, "paid_paise"), out
    # and a nested INSERT of a document born with a settlement
    values = _header_values("credit_notes", "draft", 809, _ids(world)) | {"applied_paise": "5"}
    assert _psql(world.dsn, "CREATE OR REPLACE FUNCTION public.t544_probe_fn() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS "
                            f"$f$ BEGIN {_insert('credit_notes', values)}; RETURN NEW; END $f$;").returncode == 0
    out = _op(world.dsn, "manager_a", "INSERT INTO public.t544_probe VALUES (2)")
    assert _by_the_settlement_trigger(out, "applied_paise"), out
    # the same write by the same statement as the owner (an owner-run migration, say) is not judged, and is written
    assert _psql(world.dsn, "CREATE OR REPLACE FUNCTION public.t544_probe_fn() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS "
                            "$f$ BEGIN UPDATE public.client_sales_invoices SET paid_paise = 7 WHERE status = 'issued'; RETURN NEW; END $f$;").returncode == 0
    inv = world.row("client_sales_invoices", "issued")
    assert _commit_as(world.dsn, "owner", "INSERT INTO public.t544_probe VALUES (3)").returncode == 0
    assert _rows(world.dsn, f"SELECT paid_paise FROM client_sales_invoices WHERE id = '{inv}'") == [["7"]]


def test_a_watched_name_that_is_not_a_column_makes_the_trigger_refuse_the_write_in_its_own_words(world):
    """A column renamed after the migration would otherwise read as NULL on both sides of an UPDATE and as the default on an INSERT,
    and stop being judged without a sound, while the `UPDATE OF` list (stored by column number) kept firing."""
    assert _psql(world.dsn, "ALTER TABLE purchase_bills RENAME COLUMN debited_paise TO debited_amount_paise").returncode == 0
    doc = world.row("purchase_bills", "issued")
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET paid_paise = paid_paise + 1 WHERE id = '{doc}'")
    assert out.startswith("err:42703") and "names debited_paise which is not a column of the row" in out, out
    out = _op(world.dsn, "manager_a", _insert("purchase_bills", _header_values("purchase_bills", "draft", 810, _ids(world))))
    assert out.startswith("err:42703") and "debited_paise" in out, out
    # the owner and the privileged client are not asked, and so are not stopped by the rename
    assert _wrote(_op(world.dsn, "service_role", f"UPDATE purchase_bills SET paid_paise = paid_paise + 1 WHERE id = '{doc}'"))


def test_the_functions_that_can_write_a_header_table_are_exactly_the_ones_named_here(world):
    """No trigger function writes a header table, and the only database functions that can are the two below, found from their
    SOURCES: by name (a literal INSERT, UPDATE or DELETE against one of the six), and by dynamic SQL (EXECUTE with an INSERT or an
    UPDATE, which names its table in a variable and so is invisible to a name scan: `numbered_document_atomic__unguarded` is one, and
    was the bypass the review found)."""
    out = _rows(world.dsn, "SELECT json_agg(json_build_object('n', p.proname, 's', p.prosrc, 't', p.prorettype = 'trigger'::regtype))::text "
                           "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.prokind = 'f' "
                           "AND p.proname NOT LIKE 't544\\_%'")
    functions = json.loads("".join(row[0] for row in out))
    named = re.compile(r"\b(insert\s+into|update|delete\s+from)\s+(only\s+)?(public\.)?(%s)\b" % "|".join(TABLES), re.I)
    dynamic = re.compile(r"\bexecute\b", re.I)
    assert {f["n"] for f in functions if f["t"] and named.search(f["s"] or "")} == set(), "a trigger function writes a header table"
    assert {f["n"] for f in functions if named.search(f["s"] or "")} == {"settle_receipt_atomic__unguarded"}
    writes = re.compile(r"\b(insert|update)\b", re.I)
    assert {f["n"] for f in functions if dynamic.search(f["s"] or "") and writes.search(f["s"] or "")} == {
        "guard_client_firm",                              # migration 565's installer: EXECUTE format of CREATE and DROP TRIGGER, writes no row
        "guard_journal_entry",                            # migration 573's installer: the same, for the ledger-entry check
        "guard_ledger_account",                           # migration 570's installer: the same, for the ledger-account check
        "guard_member_firm",                              # migration 566's installer: the same, for the member check
        "numbered_document_atomic__unguarded",            # INSERT of the four note tables: judged by the role setting, so not a bypass
        "post_journal_atomic__unguarded",                 # the journal tables only
        "refuse_a_signed_in_edit_of_lines_of_a_non_draft_document",   # migration 539's trigger: the line tables only
        "replace_draft_document_lines",                   # migration 560 (POST-A-332): the line tables only, SECURITY INVOKER, the header locked first
    }


# ── THE FUNCTION ────────────────────────────────────────────────────────────

def test_the_function_is_security_invoker_pins_its_search_path_and_is_not_executable_by_a_signed_in_role(world):
    fn = f"public.{FUNCTION}()"
    row = _rows(world.dsn, f"SELECT prosecdef::text, coalesce(array_to_string(proconfig, ','), '') FROM pg_proc WHERE oid = '{fn}'::regprocedure")
    assert row == [["false", "search_path=public, pg_temp"]], row
    probe = f"SELECT has_function_privilege('authenticated', '{fn}', 'EXECUTE'), has_function_privilege('anon', '{fn}', 'EXECUTE')"
    assert _rows(world.dsn, probe) == [["f", "f"]]
    assert _psql(world.dsn, f"GRANT EXECUTE ON FUNCTION {fn} TO PUBLIC, anon, authenticated;").returncode == 0
    assert _rows(world.dsn, probe) == [["t", "t"]], "the worst case was not made"
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, probe) == [["f", "f"]]


def test_a_trigger_function_closed_to_a_signed_in_role_still_runs_when_the_trigger_fires(world):
    """A trigger function is checked for EXECUTE when the trigger is created, not when it fires: the refusal a Manager gets is the
    function's own sentence and not 'permission denied for function'."""
    out = _op(world.dsn, "manager_a", f"UPDATE client_sales_invoices SET paid_paise = 9 WHERE id = '{world.row('client_sales_invoices', 'issued')}'")
    assert "permission denied" not in out and _by_the_settlement_trigger(out, "paid_paise"), out


# ── THE MIGRATION ───────────────────────────────────────────────────────────

def _dollar_quoted_bodies(sql: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"\$(\w*)\$(.*?)\$\1\$", sql, flags=re.S)]


def _outside_the_bodies(sql: str) -> str:
    return re.sub(r"\$(\w*)\$.*?\$\1\$", " ", sql, flags=re.S)


@pytest.mark.parametrize("path, creates", [(MIGRATION, True), (ROLLBACK, False)], ids=["migration", "rollback"])
def test_the_statements_that_lock_the_tables_run_inside_one_block(path, creates):
    sql = re.sub(r"--[^\n]*", "", path.read_text())
    left = re.findall(r"\b(?:CREATE(?:\s+OR\s+REPLACE)?|DROP)\s+TRIGGER\b[^;]*|\bLOCK\s+TABLE\b[^;]*", _outside_the_bodies(sql), flags=re.I)
    assert left == [], f"a statement that takes a table lock stands at the top level: {left[:2]}"
    holders = [b for b in _dollar_quoted_bodies(sql) if re.search(r"\b(?:CREATE(?:\s+OR\s+REPLACE)?|DROP)\s+TRIGGER\b", b, flags=re.I)]
    assert len(holders) == 1, f"{len(holders)} blocks hold the trigger statements, expected exactly one"
    # the migration never DROPs a trigger it is about to create (DROP takes ACCESS EXCLUSIVE, which on a re-apply queues behind every
    # reader); the rollback drops all six
    assert len(re.findall(r"\bDROP TRIGGER\b", holders[0])) == (0 if creates else 6)
    lock = re.findall(r"\bLOCK TABLE\b([^;]*);", holders[0])
    assert len(lock) == 1 and all(f"public.{t}" in lock[0] for t in TABLES) and "NOWAIT" in lock[0], lock
    assert "lock_not_available" in holders[0] and "pg_sleep" in holders[0]
    if creates:
        assert len(re.findall(r"\bCREATE OR REPLACE TRIGGER\b", holders[0])) == 6
        assert len(re.findall(r"\bCREATE TRIGGER\b", holders[0])) == 0
    # the file's top level holds no CREATE/ALTER/GRANT/REVOKE of a table either: a lock taken there is held across the runner's round trips
    top = _outside_the_bodies(sql)
    assert not re.search(r"\bALTER\s+TABLE\b", top, flags=re.I), "an ALTER TABLE stands at the top level"


def test_the_function_is_declared_security_invoker_in_the_file_and_never_definer():
    """A definer function would see its owner on every call and pass every statement; the file must not say it. An UPDATE is judged
    by `current_user`; the role setting is read once, for an INSERT; nothing is exempted by trigger depth."""
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    head = sql.split("AS $$", 1)[0]
    assert "SECURITY INVOKER" in head, "the function is not declared SECURITY INVOKER"
    assert "SECURITY DEFINER" not in head.upper(), "the function is declared SECURITY DEFINER"
    body = _dollar_quoted_bodies(sql)[0]
    assert "current_user NOT IN ('authenticated', 'anon')" in body, "an UPDATE must be judged by current_user"
    assert body.count("current_setting('role', true)") == 1, "the role setting is read once, for an INSERT"
    assert "pg_trigger_depth" not in body, "nothing is exempted by trigger depth"


@pytest.mark.parametrize("path, mode", [(MIGRATION, "SHARE ROW EXCLUSIVE"), (ROLLBACK, "ACCESS EXCLUSIVE")], ids=["migration", "rollback"])
def test_the_lock_mode_the_retry_count_the_pause_and_the_timeout_are_what_the_header_says(path, mode):
    sql = re.sub(r"--[^\n]*", "", path.read_text())
    assert f"IN {mode} MODE NOWAIT;" in sql, "the lock mode is not the one written"
    assert "IF v_try >= 30 THEN" in sql and "PERFORM pg_sleep(0.5);" in sql, "thirty tries half a second apart is fifteen seconds"
    assert "SELECT set_config('lock_timeout', '15s', true);" in sql, "the file sets no lock timeout"


def _hold(dsn: str, table: str, mode: str, seconds: int) -> subprocess.Popen:
    """A second session that holds `mode` on `table` for `seconds`, started and given a moment to take its lock. It is found in
    pg_locks by its application name AND this database: clones of one template share relation numbers, so a holder in another
    database (migration 541's test holds purchase_bills too, on another worker) would otherwise satisfy this wait."""
    import time
    proc = subprocess.Popen(["psql", dsn, "-X", "-q", "-c", f"BEGIN; LOCK TABLE public.{table} IN {mode} MODE; SELECT pg_sleep({seconds}); COMMIT;"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env={**os.environ, "PGAPPNAME": "t544holder"})
    for _ in range(60):
        held = _rows(dsn, f"SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) "
                          f"WHERE l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                          f"AND l.relation = 'public.{table}'::regclass AND l.mode = '{mode.title().replace(' ', '')}Lock' AND l.granted "
                          f"AND a.application_name = 't544holder'")
        if held[0][0] != "0":
            return proc
        time.sleep(0.25)
    proc.kill()
    raise AssertionError("the holder never took its lock")


def _locks_held_on_the_six_by(dsn: str, application_name: str) -> list[str]:
    return [r[0] for r in _rows(
        dsn, "SELECT c.relname FROM pg_locks l JOIN pg_stat_activity a USING (pid) JOIN pg_class c ON c.oid = l.relation "
             "WHERE l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) AND l.granted "
             f"AND a.application_name = '{application_name}' AND c.relname = ANY(ARRAY[" + ", ".join(f"'{t}'" for t in TABLES) + "]) ORDER BY 1")]


@pytest.mark.parametrize("path, mode", [(MIGRATION, "ROW EXCLUSIVE"), (ROLLBACK, "ACCESS SHARE")], ids=["migration", "rollback"])
def test_a_busy_table_is_waited_for_without_holding_the_other_five(world, path, mode):
    """The last table of the LOCK statement is busy, so an attempt that took the five before it would hold them for as long as it
    waits. Read off the runner's own locks (not off whether a third session can still write), sampled four times: an attempt
    that holds its locks for the whole wait is seen every time, a correct one at most when a sample lands inside the few
    milliseconds of an attempt."""
    import time
    began = time.monotonic()
    holder = _hold(world.dsn, "sales_debit_notes", mode, 10)
    runner = subprocess.Popen(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, text=True, env={**os.environ, "PGAPPNAME": "t544runner"})
    samples = []
    try:
        for _ in range(4):
            time.sleep(1.2)
            assert runner.poll() is None, "the file finished while a table was still held"
            samples.append(_locks_held_on_the_six_by(world.dsn, "t544runner"))
        _out, err = runner.communicate(timeout=90)
    finally:
        holder.wait(timeout=90)
        if runner.poll() is None:
            runner.kill()
    assert runner.returncode == 0, err
    assert sum(1 for held in samples if held) <= 1, f"the file held locks on the other tables while it waited: {samples}"
    assert time.monotonic() - began >= 9.5, "it did not wait for the holder"
    assert holder.returncode == 0


def test_a_re_apply_does_not_wait_for_a_reader(world):
    """A transaction that has only READ a table (ACCESS SHARE) is no reason for the migration to wait: nothing in it asks for a lock
    that conflicts with a read. A DROP TRIGGER would have queued behind it, blocked every later read and write, and deadlocked a
    transaction that reads and then writes (the review of 541 reproduced it). The re-apply finishes while the reader is still there."""
    holder = _hold(world.dsn, "purchase_bills", "ACCESS SHARE", 20)
    try:
        done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(MIGRATION)], capture_output=True, text=True, timeout=60)
        reader_still_there = holder.poll() is None
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert done.returncode == 0, done.stderr
    assert reader_still_there, "the re-apply only finished when the reader did"


@pytest.mark.parametrize("path, mode, message", [
    (MIGRATION, "ROW EXCLUSIVE", "migration 544: could not lock the six document header tables in 15 seconds"),
    (ROLLBACK, "ACCESS SHARE", "rollback of migration 544: could not lock the six document header tables in 15 seconds"),
], ids=["migration", "rollback"])
def test_a_table_that_stays_busy_fails_the_file_after_fifteen_seconds_in_its_own_words_and_changes_nothing(world, path, mode, message):
    import time
    before = _catalogue(world.dsn)
    holder = _hold(world.dsn, "client_sales_invoices", mode, 60)
    try:
        started = time.monotonic()
        done = _psql_file(world.dsn, path)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert done.returncode != 0 and message in done.stderr, done.stderr
    assert 14 <= waited <= 21, waited
    assert _catalogue(world.dsn) == before


def _catalogue(dsn: str) -> list:
    """Everything the migration makes, except object numbers: the triggers (table, enabled, tgtype, arguments, column list) and the
    function (security mode, body, search path and privileges)."""
    return _rows(dsn, "SELECT tgrelid::regclass::text, tgname, tgenabled::text, encode(tgargs, 'hex'), tgtype::text, "
                      "(SELECT string_agg(a.attname::text, ',' ORDER BY a.attname) FROM unnest(tgattr) k(num) "
                      " JOIN pg_attribute a ON a.attrelid = tgrelid AND a.attnum = k.num) FROM pg_trigger "
                      f"WHERE tgname = '{TRIGGER}' AND NOT tgisinternal ORDER BY 1") + _rows(
        dsn, f"SELECT 'f', proname, prosecdef::text, md5(prosrc), coalesce(array_to_string(proacl, ','), ''), "
             f"coalesce(array_to_string(proconfig, ','), ''), '' FROM pg_proc WHERE proname = '{FUNCTION}'")


def test_there_are_six_triggers_and_one_function_and_migration_541s_six_are_still_there(world):
    cat = _catalogue(world.dsn)
    assert len([r for r in cat if r[0] != "f"]) == 6 and len([r for r in cat if r[0] == "f"]) == 1, cat
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_trigger WHERE tgname = '{TRIGGER_541}' AND NOT tgisinternal") == [["6"]]


def test_a_second_run_of_the_migration_changes_nothing(world):
    before = _catalogue(world.dsn)
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _catalogue(world.dsn) == before


def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it_and_leaves_what_there_was(world):
    inv = world.row("client_sales_invoices", "issued")
    before = _catalogue(world.dsn)
    forge = f"UPDATE client_sales_invoices SET status = 'paid', paid_paise = total_paise + 1 WHERE id = '{inv}'"
    assert _by_the_settlement_trigger(_op(world.dsn, "manager_a", forge), "paid_paise", "status")
    done = _psql_file(world.dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_trigger WHERE tgname = '{TRIGGER}' AND NOT tgisinternal") == [["0"]]
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_proc WHERE proname = '{FUNCTION}'") == [["0"]]
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_trigger WHERE tgname = '{TRIGGER_541}' AND NOT tgisinternal") == [["6"]], "the rollback must leave 541"
    assert _wrote(_op(world.dsn, "manager_a", forge)), "the negative control: with the migration rolled back the forgery works"
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _by_the_settlement_trigger(_op(world.dsn, "manager_a", forge), "paid_paise", "status")
    assert _catalogue(world.dsn) == before, "applying again after the rollback did not leave exactly what the first apply made"


# ── THE CLOSING CHECK ───────────────────────────────────────────────────────

def _closing_check() -> str:
    """The migration's last DO block, the one that checks what the rest did."""
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
    blocks = re.findall(r"DO \$\$.*?END \$\$;", sql, flags=re.S)
    assert len(blocks) == 1 and "prosecdef" in blocks[0], len(blocks)
    return blocks[0]


def test_the_closing_check_passes_on_what_the_migration_made(world):
    done = _psql(world.dsn, _closing_check())
    assert done.returncode == 0, done.stderr


def _make(table: str, *, events: str | None = None, cols: list[str] | None = None, args_cols: list[str] | None = None,
          label: str | None = None, each: str = "ROW", function: str = FUNCTION, args: bool = True) -> str:
    """A trigger of the same name that is NOT the one written, one thing different."""
    cols = WATCHED[table] if cols is None else cols
    args_cols = WATCHED[table] if args_cols is None else args_cols
    label = SPECS[table][0] if label is None else label
    events = events or f"BEFORE INSERT OR UPDATE OF {', '.join(cols)}"
    argument = f"('{','.join(args_cols)}', '{label}')" if args else "('x', 'none', 'x')"
    return f"CREATE OR REPLACE TRIGGER {TRIGGER} {events} ON public.{table} FOR EACH {each} EXECUTE FUNCTION public.{function}{argument}"


def _spoils_of(table: str) -> list[tuple[str, str]]:
    cols = WATCHED[table]
    return [
        ("disabled", f"ALTER TABLE public.{table} DISABLE TRIGGER {TRIGGER}"),
        ("enabled for replica only", f"ALTER TABLE public.{table} ENABLE REPLICA TRIGGER {TRIGGER}"),
        ("enabled always", f"ALTER TABLE public.{table} ENABLE ALWAYS TRIGGER {TRIGGER}"),
        ("dropped", f"DROP TRIGGER {TRIGGER} ON public.{table}"),
        ("without the insert event", _make(table, events=f"BEFORE UPDATE OF {', '.join(cols)}")),
        ("after instead of before", _make(table, events=f"AFTER INSERT OR UPDATE OF {', '.join(cols)}")),
        ("with a delete event as well", _make(table, events=f"BEFORE INSERT OR UPDATE OF {', '.join(cols)} OR DELETE")),
        ("once per statement", _make(table, each="STATEMENT")),
        ("on every update", _make(table, events="BEFORE INSERT OR UPDATE")),
        ("missing a column of the update list", _make(table, cols=cols[:-1])),
        ("with a column too many in the update list", _make(table, cols=cols + ["notes"])),
        ("missing a column of the arguments", _make(table, args_cols=cols[:-1])),
        ("with the arguments in another order", _make(table, args_cols=list(reversed(cols)))),
        ("with another label", _make(table, label="document")),
        ("calling another function", _make(table, function="refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft", args=False)),
        # Everything else identical (name, events, columns, arguments, label): only the function the trigger calls differs. The case
        # above is refused for its ARGUMENTS as well, so it does not prove the check compares the function itself (POST-A-340).
        ("calling another function that takes the same arguments",
         "CREATE OR REPLACE FUNCTION public.zz_a_trigger_function_that_does_nothing() RETURNS trigger LANGUAGE plpgsql "
         "AS $zz$ BEGIN RETURN NEW; END $zz$; "
         + _make(table, function="zz_a_trigger_function_that_does_nothing")),
    ]


_SPOILS = [(f"{t}: {why}", sql, f"settlement trigger on public.{t}") for t in TABLES for why, sql in _spoils_of(t)] + [
    ("function made SECURITY DEFINER", f"ALTER FUNCTION public.{FUNCTION}() SECURITY DEFINER", "SECURITY DEFINER"),
    ("function's search path reset", f"ALTER FUNCTION public.{FUNCTION}() RESET search_path", "does not pin its search path"),
    ("function's search path is public alone", f"ALTER FUNCTION public.{FUNCTION}() SET search_path = public", "does not pin its search path"),
    ("function executable by authenticated", f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}() TO authenticated", "can execute the settlement trigger function"),
    ("function executable by anon", f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}() TO anon", "can execute the settlement trigger function"),
    ("function executable by PUBLIC", f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}() TO PUBLIC", "can execute the settlement trigger function"),
]


@pytest.mark.parametrize("spoil, says", [(sql, says) for _id, sql, says in _SPOILS], ids=[i for i, _s, _w in _SPOILS])
def test_the_closing_check_fails_when_what_it_checks_is_spoiled(world, spoil, says):
    """Run alone after one spoiling statement each, on every one of the six tables: a check that cannot fail is not a check."""
    assert _psql(world.dsn, spoil).returncode == 0
    done = _psql(world.dsn, _closing_check())
    assert done.returncode != 0 and says in done.stderr, done.stderr
