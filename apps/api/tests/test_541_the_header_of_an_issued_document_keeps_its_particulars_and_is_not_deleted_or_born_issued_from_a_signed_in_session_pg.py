"""Migration 541 — the header of an issued invoice, bill or note keeps its particulars, and a signed-in session cannot delete one or
create one already issued (POST-A-330).

WHAT WAS WRONG
    The six document headers (`client_sales_invoices`, `purchase_bills`, `credit_notes`, `debit_notes`, `purchase_credit_notes`,
    `sales_debit_notes`) carried a role tier and nothing that asks what state the row is in, so a member who holds the tier could,
    over PostgREST and while the API refuses all of it: change an issued document's amounts, tax, party, number or dates; delete it
    with its lines; insert one already issued; soft-delete it; or move it back to `draft`, which opens its lines again and undoes
    migration 539.

WHAT THIS HOLDS (a real database, as each person)
    * THE CLASSIFICATION: every column of each header table is either one a signed-in session may still change on a document that is
      not a draft (the soft fields the API's PATCH allows, the settlement, status and metadata columns the legitimate paths write)
      or frozen; the lists below are explicit, so a column a later migration adds fails here until it is classified, and the
      arguments of each trigger equal the lists.
    * THE FROZEN COLUMNS: a Manager's change of each of them on a document that is not a draft is refused (42501 and the sentence
      naming the column); the allowed columns are not refused; a draft may be changed freely; issuing a draft passes and locks it.
    * THE ONE MOVE BACK: a non-draft document cannot return to `draft`, except the received bill with no journal link, received in
      the last ten minutes, with nothing paid, debited or credited, whose `received_at` is cleared in the same statement (the
      rollback of a receive whose journal failed). Zeroing the amounts first (columns the trigger leaves writable) does not open it
      for a bill received earlier.
    * THE SOFT DELETE is the opening document's alone; a hard DELETE is a draft's alone (Partner included).
    * INSERT: a document is created as a draft, except an opening document.
    * WHAT IS NOT JUDGED: a foreign-key cascade (a Partner's delete of a customer or vendor reaches its issued documents), an
      ON DELETE SET NULL update, the privileged client and the database owner. The anonymous role IS judged (made reachable in a
      worst case).
    * THE MIGRATION: the function is closed to a signed-in role even when the platform granted it first, the lock-taking statements
      run inside one block in both files, that block waits for a busy table WITHOUT holding the other five (a third session writes
      to them throughout) and gives up with its own sentence after fifteen seconds, a second run changes nothing, the rollback
      brings the forgery back (the negative control) and a re-apply ends it.

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
    reason="the header-state proof requires HARNESS_PG + psql",
)

_STEM = "541_the_header_of_an_issued_document_keeps_its_particulars_and_is_not_deleted_or_born_issued_from_a_signed_in_session"
FUNCTION = "refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft"
TRIGGER = "a_document_that_is_not_a_draft_keeps_its_particulars"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

FIRM = "54100000-0000-0000-0000-000000000001"
CLIENT_A = "54100000-0000-0000-0000-0000000000a1"
CLIENT_B = "54100000-0000-0000-0000-0000000000b2"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("54100000-0000-0000-0000-00000000000a", "54100000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("54100000-0000-0000-0000-00000000000b", "54100000-1111-0000-0000-000000000002", "Manager"),
    "reviewer_a": ("54100000-0000-0000-0000-00000000000f", "54100000-1111-0000-0000-000000000005", "Reviewer"),
}
CLIENT_A_MEMBERS = ("manager_a", "reviewer_a")
_F = f"'{FIRM}'"

# table -> (label, may be created as an opening document, statuses it can be in besides draft, the status a Manager moves it to)
SPECS = {
    "client_sales_invoices": ("invoice", True, ["issued", "partially_paid", "paid", "cancelled"]),
    "purchase_bills": ("bill", True, ["received", "partially_paid", "paid", "cancelled"]),
    "credit_notes": ("credit note", False, ["issued"]),
    "debit_notes": ("debit note", False, ["issued"]),
    "purchase_credit_notes": ("purchase credit note", False, ["issued"]),
    "sales_debit_notes": ("sales debit note", False, ["issued"]),
}
TABLES = list(SPECS)
OPENING_TABLES = [t for t in TABLES if SPECS[t][1]]

# EVERY column of each header table, in one of two lists. A column a later migration adds fails the classification test until it is
# put in one of them (and in the trigger's arguments, which another test compares with `allowed`).
CLASSIFIED = {
    "client_sales_invoices": {
        "allowed": [
            'reference_no', 'notes', 'due_date', 'credit_days', 'shipping_bill_no', 'shipping_bill_date', 'port_code',
            'updated_at', 'status', 'journal_entry_id', 'paid_paise', 'paid_txn', 'credited_paise',
            'debit_note_paise', 'last_reminded_at', 'reminder_count', 'is_overdue', 'days_overdue', 'aging_bucket',
            'last_internal_followup_at', 'internal_followup_count'],
        "frozen": [
            'id', 'firm_id', 'client_id', 'customer_id', 'invoice_no', 'invoice_date', 'supply_state_code',
            'is_interstate', 'taxable_amount_paise', 'cgst_paise', 'sgst_paise', 'igst_paise', 'total_gst_paise',
            'total_paise', 'created_by', 'created_at', 'billing_schedule_id', 'billing_period', 'source', 'issued_at',
            'deleted_at', 'recurring_template_id', 'recurring_occurrence', 'txn_currency', 'exchange_rate',
            'txn_taxable', 'txn_total_gst', 'txn_total', 'rate_source', 'rate_type', 'rate_date', 'rate_selected_by',
            'rate_overridden', 'round_off_paise', 'round_off_enabled', 'supply_type', 'invoice_type',
            'is_reverse_charge', 'is_disputed', 'considered_doubtful', 'discount_paise', 'discount_percent_bps',
            'cess_paise', 'is_opening'],
        "generated": ['outstanding_paise', 'txn_outstanding']},
    "purchase_bills": {
        "allowed": [
            'notes', 'due_date', 'credit_days', 'our_reference', 'document_url', 'form_15ca_ack_no',
            'form_15ca_filed_on', 'form_15cb_udin', 'updated_at', 'status', 'cancelled_at', 'journal_entry_id',
            'paid_paise', 'paid_txn', 'debited_paise', 'credit_note_paise', 'landed_cost_basis'],
        "frozen": [
            'id', 'firm_id', 'client_id', 'vendor_id', 'bill_no', 'bill_date', 'taxable_amount_paise', 'cgst_paise',
            'sgst_paise', 'igst_paise', 'total_gst_paise', 'total_paise', 'tds_paise', 'tds_section', 'tds_rate_bps',
            'net_payable_paise', 'is_ai_extracted', 'ai_extraction_data', 'created_at', 'is_reverse_charge',
            'txn_currency', 'exchange_rate', 'txn_taxable', 'txn_total_gst', 'txn_total', 'txn_net_payable',
            'rate_source', 'rate_type', 'rate_date', 'rate_selected_by', 'rate_overridden', 'is_interstate',
            'deleted_at', 'received_at', 'ineligible_itc_igst_paise', 'ineligible_itc_cgst_paise',
            'ineligible_itc_sgst_paise', 'ineligible_itc_cess_paise', 'is_disputed', 'tds_surcharge_paise',
            'tds_cess_paise', 'tds_nature_of_income', 'tds_basis', 'tds_advance_adjusted_paise', 'tds_certificate_no',
            'cess_paise', 'recurring_template_id', 'recurring_occurrence', 'is_opening', 'purchase_order_id'],
        "generated": ['outstanding_paise', 'txn_outstanding']},
    "credit_notes": {
        "allowed": [
            'notes', 'updated_at'],
        "frozen": [
            'id', 'firm_id', 'client_id', 'customer_id', 'sales_invoice_id', 'credit_note_no', 'credit_note_date',
            'reason', 'taxable_amount_paise', 'cgst_paise', 'sgst_paise', 'igst_paise', 'total_paise', 'status',
            'journal_entry_id', 'created_at', 'is_interstate', 'applied_paise', 'total_gst_paise', 'deleted_at'],
        "generated": []},
    "debit_notes": {
        "allowed": [
            'notes', 'document_url'],
        "frozen": [
            'id', 'firm_id', 'client_id', 'vendor_id', 'purchase_bill_id', 'debit_note_no', 'debit_note_date',
            'reason', 'is_interstate', 'is_reverse_charge', 'taxable_amount_paise', 'cgst_paise', 'sgst_paise',
            'igst_paise', 'total_paise', 'total_gst_paise', 'applied_paise', 'status', 'journal_entry_id',
            'created_at', 'created_by', 'deleted_at'],
        "generated": []},
    "purchase_credit_notes": {
        "allowed": [
            'notes', 'document_url'],
        "frozen": [
            'id', 'firm_id', 'client_id', 'vendor_id', 'purchase_bill_id', 'credit_note_no', 'credit_note_date',
            'reason', 'is_interstate', 'is_reverse_charge', 'taxable_amount_paise', 'cgst_paise', 'sgst_paise',
            'igst_paise', 'total_paise', 'total_gst_paise', 'applied_paise', 'status', 'journal_entry_id',
            'created_at', 'created_by', 'deleted_at'],
        "generated": []},
    "sales_debit_notes": {
        "allowed": [
            'notes', 'updated_at'],
        "frozen": [
            'id', 'firm_id', 'client_id', 'customer_id', 'sales_invoice_id', 'debit_note_no', 'debit_note_date',
            'reason', 'is_interstate', 'taxable_amount_paise', 'cgst_paise', 'sgst_paise', 'igst_paise',
            'total_paise', 'total_gst_paise', 'status', 'journal_entry_id', 'applied_paise', 'created_at',
            'deleted_at'],
        "generated": []},
}


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


def _by_the_privilege_not_the_trigger(out: str) -> bool:
    """A refusal that is the table privilege (42501), not this trigger's own refusal."""
    return out.startswith("err:42501") and "permission denied" in out


def _op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err:<SQLSTATE> <message>` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err:% %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _by_the_trigger(outcome: str) -> bool:
    """Refused by THIS trigger (a row-security refusal is also 42501, with another sentence)."""
    return outcome.startswith("err:42501") and "from a signed-in session" in outcome


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


def _seed(w: World) -> None:
    one = lambda sql: _rows(w.dsn, sql)[0][0]
    ids = {"customer": one(f"SELECT id FROM customers WHERE client_id = '{CLIENT_A}'"),
           "vendor": w.put("vendors", "x", {"firm_id": _F, "client_id": _q(CLIENT_A), "name": "'vendor'"})}
    n = 0
    for table, (_label, opening, others) in SPECS.items():
        for tag in ["draft"] + others:
            n += 1
            w.put(table, tag, _header_values(table, tag, n, ids))
        if opening:
            n += 1
            w.put(table, "opening", _header_values(table, others[0], n, ids) | {"is_opening": "true"})


@pytest.fixture(scope="module")
def seeded(pg_template):
    admin = _ADMIN.strip()
    name = f"e541s_{uuid.uuid4().hex[:12]}"
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
        """)
        assert seed.returncode == 0, seed.stderr
        w = World(d)
        _seed(w)
        # Migration 563 took the signed-in write on the six document headers and their lines; this file measures the SECOND lock (the
        # policies and the triggers), so the write is given back on this throwaway copy once its rows are seeded.
        give_the_signed_in_writes_back(d)
        # Migration 544 refuses a signed-in change of the settlement columns (status, the paid and applied amounts, the journal link),
        # which several cases below change as a Manager to show what 541 leaves open. This file is about 541's rule alone, so the
        # later trigger is switched off in the copy these cases run on; tests/test_544_..._pg.py holds that rule, and the two together.
        for table in SPECS:
            w.owner(f"ALTER TABLE {table} DISABLE TRIGGER a_documents_settlement_is_written_by_the_api_only")
        yield name, w.ids
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def world(seeded):
    template, ids = seeded
    admin = _ADMIN.strip()
    name = f"e541_{uuid.uuid4().hex[:12]}"
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
    return {"customer": _rows(world.dsn, "SELECT id FROM customers LIMIT 1")[0][0], "vendor": world.row("vendors", "x")}


def _non_draft(table: str) -> str:
    return SPECS[table][2][0]


def _column_info(dsn: str, table: str) -> dict:
    return {r[0]: (r[1], r[2]) for r in _rows(
        dsn, f"SELECT column_name, data_type, coalesce(character_maximum_length::text, '') FROM information_schema.columns "
             f"WHERE table_schema = 'public' AND table_name = '{table}' ORDER BY ordinal_position")}


def _different_value(dsn: str, table: str, col: str) -> str:
    """An expression that is valid for the column's type and different from what the row holds."""
    ty, length = _column_info(dsn, table)[col]
    if ty == "uuid":
        return "gen_random_uuid()"
    if ty == "text":
        return f"COALESCE({col}, '') || 'x'"
    if ty == "character":
        n = int(length or 1)
        return f"CASE WHEN {col} = repeat('9', {n}) THEN repeat('8', {n}) ELSE repeat('9', {n}) END"
    if ty == "date":
        return f"COALESCE({col}, current_date) + 1"
    if ty == "timestamp with time zone":
        return f"COALESCE({col}, now()) + interval '1 day'"
    if ty == "boolean":
        return f"NOT COALESCE({col}, false)"
    if ty in ("bigint", "integer", "numeric"):
        return f"COALESCE({col}, 0) + 1"
    if ty == "jsonb":
        return "'{\"z\": 1}'::jsonb"
    raise AssertionError(f"{table}.{col}: no way to make a different value of type {ty}")


FROZEN_CASES = [(t, c) for t in TABLES for c in CLASSIFIED[t]["frozen"]]
ALLOWED_CASES = [(t, c) for t in TABLES for c in CLASSIFIED[t]["allowed"]]


# ── THE CLASSIFICATION ──────────────────────────────────────────────────────

@pytest.mark.parametrize("table", TABLES)
def test_every_column_of_a_header_is_classified_once(world, table):
    columns = set(_column_info(world.dsn, table))
    allowed, frozen, generated = (set(CLASSIFIED[table][k]) for k in ("allowed", "frozen", "generated"))
    assert not (allowed & frozen) and not (generated & (allowed | frozen)), "a column is classified twice"
    assert allowed | frozen | generated == columns, (f"unclassified: {sorted(columns - allowed - frozen - generated)}; classified but absent: "
                                                     f"{sorted((allowed | frozen | generated) - columns)}")
    # a generated column is recomputed AFTER a BEFORE trigger, so the function ignores it by name: these are the catalogue's own
    in_catalogue = {r[0] for r in _rows(world.dsn, f"SELECT attname FROM pg_attribute WHERE attrelid = 'public.{table}'::regclass "
                                                  "AND attnum > 0 AND NOT attisdropped AND attgenerated <> ''")}
    assert in_catalogue == generated, (table, in_catalogue)
    source = _rows(world.dsn, f"SELECT prosrc FROM pg_proc WHERE proname = '{FUNCTION}'")
    assert all(f"'{c}'" in "\n".join(r[0] for r in source) for c in generated), "the function does not ignore a generated column"


@pytest.mark.parametrize("table", TABLES)
def test_the_triggers_arguments_are_the_lists_this_file_pins(world, table):
    got = _rows(world.dsn, f"SELECT encode(tgargs, 'hex') FROM pg_trigger WHERE tgrelid = 'public.{table}'::regclass "
                           f"AND tgname = '{TRIGGER}' AND NOT tgisinternal")
    assert len(got) == 1, got
    allowed, opening, label = bytes.fromhex(got[0][0]).decode().split("\x00")[:-1]
    assert sorted(allowed.split(",")) == sorted(CLASSIFIED[table]["allowed"]), (table, allowed)
    assert opening == (f"opening:{SPECS[table][2][0]}" if SPECS[table][1] else "none") and label == SPECS[table][0]


# ── THE FROZEN COLUMNS ──────────────────────────────────────────────────────

@pytest.mark.parametrize("table,col", FROZEN_CASES)
def test_a_manager_is_refused_a_change_of_each_frozen_column_on_a_document_that_is_not_a_draft(world, table, col):
    doc = world.row(table, _non_draft(table))
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET {col} = {_different_value(world.dsn, table, col)} WHERE id = '{doc}'")
    assert _by_the_trigger(out) and col in out, f"{table}.{col}: {out}"


# a value the column's own CHECK or foreign key accepts, where `_different_value` (valid for the TYPE) is not enough
_VALID_FOR_THE_COLUMN = {
    "status": "'paid'",
    "landed_cost_basis": "'quantity'",
}


@pytest.mark.parametrize("table,col", ALLOWED_CASES)
def test_an_allowed_column_is_changed_by_a_manager_on_a_document_that_is_not_a_draft(world, table, col):
    """The change is WRITTEN (one row), not merely 'not refused by this rule': a value the database refuses for another reason, or a
    row security policy that quietly updates nothing, would otherwise let a column that is in fact frozen pass this test."""
    doc = world.row(table, _non_draft(table))
    if col == "journal_entry_id":
        entry = _rows(world.dsn, "SET session_replication_role = replica; INSERT INTO journal_entries (firm_id, client_id, entry_date, narration, entry_type) "
                                 f"VALUES ('{FIRM}', '{CLIENT_A}', '2026-04-01', 'seed', 'Journal') RETURNING id;")
        value = "'" + [r[0] for r in entry if re.fullmatch(r"[0-9a-f-]{36}", r[0])][0] + "'"
    else:
        value = _VALID_FOR_THE_COLUMN.get(col) or _different_value(world.dsn, table, col)
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET {col} = {value} WHERE id = '{doc}'")
    assert _wrote(out), f"{table}.{col}: {out}"


@pytest.mark.parametrize("table", TABLES)
def test_a_draft_may_be_changed_freely(world, table):
    doc = world.row(table, "draft")
    for col in ("total_paise", "taxable_amount_paise", "is_interstate"):
        assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET {col} = {_different_value(world.dsn, table, col)} WHERE id = '{doc}'")), (table, col)


@pytest.mark.parametrize("table", TABLES)
def test_issuing_a_draft_passes_and_then_locks_it(world, table):
    doc = world.row(table, "draft")
    status = _non_draft(table)
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET status = '{status}', total_paise = 100 WHERE id = '{doc}'"))
    # the same two statements in one session: the edit that follows the issue is refused
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET status = '{status}' WHERE id = '{doc}'; UPDATE {table} SET total_paise = 200 WHERE id = '{doc}'")
    assert _by_the_trigger(out) and "total_paise" in out, out


@pytest.mark.parametrize("table", ["client_sales_invoices", "purchase_bills"])
def test_cancelling_an_issued_document_passes(world, table):
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET status = 'cancelled' WHERE id = '{world.row(table, _non_draft(table))}'"))


@pytest.mark.parametrize("who", ["manager_a", "partner"])
def test_the_partner_is_judged_like_everybody_signed_in(world, who):
    doc = world.row("client_sales_invoices", "issued")
    assert _by_the_trigger(_op(world.dsn, who, f"UPDATE client_sales_invoices SET total_paise = total_paise + 1 WHERE id = '{doc}'"))


# ── BACK TO A DRAFT ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("table,status", [(t, s) for t in TABLES for s in SPECS[t][2] if (t, s) != ("purchase_bills", "received")])
def test_a_document_that_is_not_a_draft_cannot_go_back_to_one(world, table, status):
    """(The received bill is the one document with a way back, asserted on its own below.)"""
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET status = 'draft' WHERE id = '{world.row(table, status)}'")
    assert _by_the_trigger(out) and "moved back to a draft" in out, out


def test_the_received_bill_whose_journal_failed_may_go_back_to_a_draft(world):
    bill = world.row("purchase_bills", "received")
    world.owner(f"UPDATE purchase_bills SET received_at = now() WHERE id = '{bill}'")
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'"))


def test_that_move_is_refused_when_the_journal_was_linked_or_received_at_is_kept_or_anything_else_changes(world):
    bill = world.row("purchase_bills", "received")
    world.owner(f"UPDATE purchase_bills SET received_at = now() WHERE id = '{bill}'")
    kept = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft' WHERE id = '{bill}'")
    more = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL, total_paise = 1 WHERE id = '{bill}'")
    world.owner(f"UPDATE purchase_bills SET journal_entry_id = gen_random_uuid() WHERE id = '{bill}'")
    linked = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'")
    for out in (kept, more, linked):
        assert _by_the_trigger(out) and "moved back to a draft" in out, out


def test_only_a_received_bill_has_that_way_back(world):
    for table in ("client_sales_invoices", "credit_notes"):
        out = _op(world.dsn, "manager_a", f"UPDATE {table} SET status = 'draft' WHERE id = '{world.row(table, 'issued')}'")
        assert _by_the_trigger(out), (table, out)
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{world.row('purchase_bills', 'paid')}'")
    assert _by_the_trigger(out), out


@pytest.mark.parametrize("status", ["partially_paid", "paid", "cancelled"])
def test_a_bill_in_any_other_status_has_no_way_back_even_when_it_looks_like_a_fresh_receive(world, status):
    """Everything else about the exception holds (received just now, no journal link, nothing paid, debited or credited); only the
    status is not `received`. A cancelled bill must not be walked back to a draft this way."""
    bill = world.row("purchase_bills", status)
    world.owner(f"UPDATE purchase_bills SET received_at = now(), paid_paise = 0, debited_paise = 0, credit_note_paise = 0, journal_entry_id = NULL WHERE id = '{bill}'")
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'")
    assert _by_the_trigger(out) and "moved back to a draft" in out, out


def _link_and_receive(world, bill: str, **more) -> None:
    sets = ", ".join(f"{k} = {v}" for k, v in ({"journal_entry_id": "gen_random_uuid()", "received_at": "now()"} | more).items())
    world.owner(f"UPDATE purchase_bills SET {sets} WHERE id = '{bill}'")


def test_a_bill_cannot_be_rewritten_through_the_way_back_to_a_draft_because_its_journal_link_cannot_be_cleared(world):
    """The review's four statements: clear the journal link (an allowed column), move the paid bill back to received (an allowed
    status move), then to a draft with received_at cleared (the one exception, which stood on the link being NULL), after which the
    bill is a draft and everything about it, its lines included, is editable. The first step is the one refused now."""
    bill = world.row("purchase_bills", "paid")
    _link_and_receive(world, bill)
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET journal_entry_id = NULL WHERE id = '{bill}'")
    assert _by_the_trigger(out) and "journal entry it was posted with" in out, out
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET journal_entry_id = gen_random_uuid() WHERE id = '{bill}'")
    assert _by_the_trigger(out) and "journal entry it was posted with" in out, out


@pytest.mark.parametrize("table", ["client_sales_invoices", "purchase_bills"])
def test_a_document_with_no_journal_link_may_be_given_one_and_a_linked_one_keeps_it_through_other_edits(world, table):
    """What the receive, the repost and the issue do: a link is set where there is none (the database may refuse the value for
    another reason, a foreign key; what is asserted is that THIS rule does not). A document that has one is edited as before."""
    doc = world.row(table, _non_draft(table))
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET journal_entry_id = gen_random_uuid() WHERE id = '{doc}'")
    assert not _by_the_trigger(out), out
    world.owner(f"UPDATE {table} SET journal_entry_id = gen_random_uuid() WHERE id = '{doc}'")
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET notes = 'edited' WHERE id = '{doc}'"))


def test_zeroing_the_amounts_first_does_not_open_the_way_back_to_a_draft_for_a_bill_received_earlier(world):
    """The third review's sequence. `paid_paise`, `debited_paise` and `credit_note_paise` are columns the trigger leaves writable, so
    the exception's 'nothing paid, debited or credited' was satisfied by the same member zeroing them in a statement of their own;
    what stops the walk-back of a bill that was received long ago and never got its journal link is that it must be recent."""
    bill = world.row("purchase_bills", "received")
    world.owner(f"UPDATE purchase_bills SET received_at = now() - interval '2 days', paid_paise = 100, debited_paise = 100, credit_note_paise = 100 WHERE id = '{bill}'")
    assert _by_the_trigger(_op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'"))
    zeroed = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET paid_paise = 0, debited_paise = 0, credit_note_paise = 0 WHERE id = '{bill}'; "
                                         f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'")
    assert _by_the_trigger(zeroed) and "moved back to a draft" in zeroed, zeroed


@pytest.mark.parametrize("age,passes", [("9 minutes", True), ("11 minutes", False), ("1 hour", False), ("-5 minutes", True)])
def test_the_way_back_is_for_a_bill_received_in_the_last_ten_minutes(world, age, passes):
    """The receive stamps `received_at` and its rollback runs in the same request. (A stamp a little in the future is clock skew
    between the API and the database and is still 'just received'.)"""
    bill = world.row("purchase_bills", "received")
    world.owner(f"UPDATE purchase_bills SET received_at = now() - interval '{age}' WHERE id = '{bill}'")
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'")
    if passes:
        assert _wrote(out), out
    else:
        assert _by_the_trigger(out) and "moved back to a draft" in out, out


def test_an_opening_bill_has_no_way_back_to_a_draft(world):
    """It is `received` with no journal link and no `received_at` by design, so the exception's old test (a received bill with no
    link) took it back to a draft in ONE statement."""
    bill = world.row("purchase_bills", "opening")
    for prepare in ("", "received_at = now()"):
        if prepare:
            world.owner(f"UPDATE purchase_bills SET {prepare} WHERE id = '{bill}'")
        out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'")
        assert _by_the_trigger(out) and "moved back to a draft" in out, (prepare, out)


@pytest.mark.parametrize("column", ["paid_paise", "debited_paise", "credit_note_paise"])
def test_a_received_bill_with_something_paid_debited_or_credited_against_it_cannot_go_back_to_a_draft(world, column):
    bill = world.row("purchase_bills", "received")
    world.owner(f"UPDATE purchase_bills SET received_at = now(), {column} = 100 WHERE id = '{bill}'")
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft', received_at = NULL WHERE id = '{bill}'")
    assert _by_the_trigger(out) and "moved back to a draft" in out, out


def test_a_bill_that_was_never_stamped_received_cannot_go_back_either(world):
    bill = world.row("purchase_bills", "received")
    world.owner(f"UPDATE purchase_bills SET received_at = NULL WHERE id = '{bill}'")
    out = _op(world.dsn, "manager_a", f"UPDATE purchase_bills SET status = 'draft' WHERE id = '{bill}'")
    assert _by_the_trigger(out) and "moved back to a draft" in out, out


# ── THE SOFT DELETE ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", OPENING_TABLES)
def test_the_soft_delete_of_an_opening_document_passes_and_of_any_other_is_refused(world, table):
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET deleted_at = now() WHERE id = '{world.row(table, 'opening')}'"))
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET deleted_at = now() WHERE id = '{world.row(table, _non_draft(table))}'")
    assert _by_the_trigger(out) and "deleted_at" in out, out


@pytest.mark.parametrize("table", OPENING_TABLES)
def test_an_opening_document_with_something_paid_against_it_is_not_soft_deleted(world, table):
    """The API answers 409 for it; the database now agrees."""
    doc = world.row(table, "opening")
    world.owner(f"UPDATE {table} SET paid_paise = 100 WHERE id = '{doc}'")
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET deleted_at = now() WHERE id = '{doc}'")
    assert _by_the_trigger(out) and "deleted_at" in out, out


@pytest.mark.parametrize("table", [t for t in TABLES if t not in OPENING_TABLES])
def test_a_note_is_never_soft_deleted_once_issued(world, table):
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET deleted_at = now() WHERE id = '{world.row(table, 'issued')}'")
    assert _by_the_trigger(out), out


# ── INSERT ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table", TABLES)
def test_a_document_cannot_be_inserted_already_issued(world, table, who):
    values = _header_values(table, _non_draft(table), 900, _ids(world))
    out = _op(world.dsn, who, _insert(table, values))
    assert _by_the_trigger(out) and "can only be created as a draft" in out, out


@pytest.mark.parametrize("table", TABLES)
def test_a_draft_is_inserted_as_before(world, table):
    assert _wrote(_op(world.dsn, "manager_a", _insert(table, _header_values(table, "draft", 901, _ids(world)))))


@pytest.mark.parametrize("table", OPENING_TABLES)
def test_an_opening_document_is_inserted_issued_or_received_and_nothing_else_is(world, table):
    values = _header_values(table, _non_draft(table), 902, _ids(world))
    assert _wrote(_op(world.dsn, "manager_a", _insert(table, values | {"is_opening": "true"})))
    assert _by_the_trigger(_op(world.dsn, "manager_a", _insert(table, values | {"is_opening": "false"})))


@pytest.mark.parametrize("table", [t for t in TABLES if t not in OPENING_TABLES])
def test_the_opening_exemption_belongs_to_the_table_and_not_to_a_column_a_row_happens_to_carry(world, table):
    """The four note tables have no `is_opening` column today, so the trigger's `opening` argument and the row's own flag say the same
    thing. They are two answers: if a note table ever gains the column, a signed-in session must still not be able to create an issued
    note by setting it (the exemption is for the two tables the API creates opening documents on)."""
    done = _psql(world.dsn, f"ALTER TABLE {table} ADD COLUMN is_opening boolean NOT NULL DEFAULT false")
    assert done.returncode == 0, done.stderr
    values = _header_values(table, _non_draft(table), 904, _ids(world))
    assert _by_the_trigger(_op(world.dsn, "manager_a", _insert(table, values | {"is_opening": "true"})))


_OPENING_LOADS = ["taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_gst_paise", "cess_paise", "tds_paise",
                  "tds_rate_bps", "tds_surcharge_paise", "tds_cess_paise", "tds_advance_adjusted_paise", "ineligible_itc_igst_paise",
                  "ineligible_itc_cgst_paise", "ineligible_itc_sgst_paise", "ineligible_itc_cess_paise", "discount_paise",
                  "discount_percent_bps", "round_off_paise", "paid_paise", "paid_txn", "credited_paise", "debit_note_paise",
                  "debited_paise", "credit_note_paise"]
# what each opening-capable table really carries of them, so a column dropped from the function's list fails the table that has it
_OPENING_LOADS_PRESENT = {"client_sales_invoices": 13, "purchase_bills": 19}


@pytest.mark.parametrize("table", OPENING_TABLES)
def test_an_opening_document_carries_no_tax_no_payment_and_no_journal_entry(world, table):
    """The API writes exactly that (`opening_documents.row_for`), and the exemption is held to it: without this a Manager created an
    issued, paid or cancelled document with real tax in one statement."""
    values = _header_values(table, _non_draft(table), 905, _ids(world)) | {"is_opening": "true"}
    columns = set(_column_info(world.dsn, table))
    tried = 0
    for column in _OPENING_LOADS:
        if column not in columns:
            continue
        tried += 1
        out = _op(world.dsn, "manager_a", _insert(table, values | {column: "1"}))
        assert _by_the_trigger(out) and "carries no tax" in out and column in out, (table, column, out)
    out = _op(world.dsn, "manager_a", _insert(table, values | {"journal_entry_id": "gen_random_uuid()"}))
    assert _by_the_trigger(out) and "journal_entry_id" in out, (table, out)
    assert tried == _OPENING_LOADS_PRESENT[table], (table, tried)   # the columns the table really has; a vacuous pass would try none


@pytest.mark.parametrize("table", OPENING_TABLES)
def test_an_opening_document_is_created_in_the_status_the_api_gives_it_and_no_other(world, table):
    given = _non_draft(table)
    for status in {"issued", "received", "paid", "partially_paid", "cancelled"} - {given}:
        values = _header_values(table, status, 906, _ids(world)) | {"is_opening": "true"}
        out = _op(world.dsn, "manager_a", _insert(table, values))
        assert _by_the_trigger(out) and f"can only be created as {given}" in out, (table, status, out)


@pytest.mark.parametrize("kind", ["receivable", "payable"])
def test_the_row_the_api_builds_for_an_opening_document_is_taken(world, kind):
    """The trigger's idea of an opening document is the API's own: `opening_documents.row_for` is called here and its row inserted
    as a Manager, so the day that function writes a tax column, a payment or a different status this fails instead of the screen."""
    from domain.accounting import opening_documents as od
    party = _ids(world)["customer" if kind == od.RECEIVABLE else "vendor"]
    row = od.row_for(kind=kind, firm_id=FIRM, client_id=CLIENT_A, party_id=party, document_no="OPEN-API-1", document_date="2026-03-31",
                     due_date="2026-04-30", outstanding_paise=12345, notes="carried over")
    values = {k: ("NULL" if v is None else "true" if v is True else "false" if v is False else str(v) if isinstance(v, int) else _q(v))
              for k, v in row.items()}
    assert _wrote(_op(world.dsn, "manager_a", _insert(od.TABLES[kind], values)))


def test_the_opening_document_a_valid_insert_is_still_taken(world):
    for table in OPENING_TABLES:
        values = _header_values(table, _non_draft(table), 907, _ids(world)) | {"is_opening": "true", "total_paise": "5000"}
        assert _wrote(_op(world.dsn, "manager_a", _insert(table, values))), table


# ── DELETE ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table,status", [(t, s) for t in TABLES for s in SPECS[t][2]])
def test_only_a_draft_is_deleted(world, table, status, who):
    out = _op(world.dsn, who, f"DELETE FROM {table} WHERE id = '{world.row(table, status)}'")
    assert _by_the_trigger(out) and "cannot be deleted" in out, out


@pytest.mark.parametrize("table", TABLES)
def test_a_draft_is_deleted_as_before(world, table):
    assert _wrote(_op(world.dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{world.row(table, 'draft')}'"))


def test_a_partners_delete_of_a_customer_cascades_to_its_issued_documents_without_the_trigger_refusing(world):
    """The cascade runs one trigger level deeper than a statement. (The API's own dependency guard decides whether a customer may be
    deleted at all.)"""
    cust = _rows(world.dsn, "SELECT id FROM customers LIMIT 1")[0][0]
    assert _rows(world.dsn, f"SELECT count(*) FROM client_sales_invoices WHERE customer_id = '{cust}' AND status <> 'draft'")[0][0] != "0"
    out = _op(world.dsn, "partner", f"DELETE FROM customers WHERE id = '{cust}'")
    assert _wrote(out), out


def test_a_partners_delete_of_a_vendor_cascades_to_its_issued_bills_without_the_trigger_refusing(world):
    vend = world.row("vendors", "x")
    assert _rows(world.dsn, f"SELECT count(*) FROM purchase_bills WHERE vendor_id = '{vend}' AND status <> 'draft'")[0][0] != "0"
    out = _op(world.dsn, "partner", f"DELETE FROM vendors WHERE id = '{vend}'")
    assert _wrote(out), out


def test_an_on_delete_set_null_update_of_an_issued_invoice_is_not_judged(world):
    """Deleting a recurring template sets `recurring_template_id` to NULL on the invoices it generated, whatever their state.
    Since migration 562 a signed-in session cannot delete a template at all (the API does it as the server), so the delete is made
    as the service role: what is proved is that the cascade is not judged by this trigger, which is still the rule for any
    foreign key's SET NULL on an issued document."""
    tpl = _rows(world.dsn, f"SET session_replication_role = replica; INSERT INTO recurring_invoice_templates (firm_id, client_id, customer_id, title, frequency, start_date, next_run_date) "
                           f"SELECT '{FIRM}', '{CLIENT_A}', id, 'tpl', 'monthly', '2026-04-01', '2026-05-01' FROM customers LIMIT 1 RETURNING id;")
    tpl_id = [r[0] for r in tpl if re.fullmatch(r"[0-9a-f-]{36}", r[0])][0]
    inv = world.row("client_sales_invoices", "issued")
    world.owner(f"UPDATE client_sales_invoices SET recurring_template_id = '{tpl_id}' WHERE id = '{inv}'")
    # the same column changed directly is refused, so the cascade passing is the depth rule and nothing else
    assert _by_the_trigger(_op(world.dsn, "manager_a", f"UPDATE client_sales_invoices SET recurring_template_id = NULL WHERE id = '{inv}'"))
    out = _op(world.dsn, "service_role", f"DELETE FROM recurring_invoice_templates WHERE id = '{tpl_id}'")
    assert _wrote(out), out
    assert _by_the_privilege_not_the_trigger(_op(world.dsn, "manager_a", f"DELETE FROM recurring_invoice_templates WHERE id = '{tpl_id}'")), (
        "a signed-in Manager can still delete a recurring template (migration 562)")


# ── WHAT THE DEPTH RULE LEANS ON ────────────────────────────────────────────

def test_no_trigger_function_writes_the_six_tables_and_the_functions_that_do_are_the_ones_named_here(world):
    """A write reaches this trigger at depth two, and so is not judged, only when it is made from inside ANOTHER TRIGGER (a foreign
    key's cascade is an internal trigger, which is how a cascade is told from a statement). A function called as a statement
    (PostgREST's rpc) writes at depth ONE and is judged like any statement. So the exemption stands on there being no trigger
    function, and no function a trigger function calls, that writes these tables. The first is asserted exactly; the second by
    pinning every function that mentions them, which is a superset (a function a person calls is in it too)."""
    import json
    out = _rows(world.dsn, "SELECT json_agg(json_build_object('n', p.proname, 's', p.prosrc, 't', p.prorettype = 'trigger'::regtype))::text "
                           "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.prokind = 'f'")
    functions = json.loads("".join(row[0] for row in out))
    pattern = re.compile(r"\b(insert\s+into|update|delete\s+from)\s+(only\s+)?(public\.)?(%s)\b" % "|".join(TABLES), re.I)
    writers = {f["n"] for f in functions if pattern.search(f["s"] or "")}
    trigger_writers = {f["n"] for f in functions if f["t"] and pattern.search(f["s"] or "")}
    assert trigger_writers == set(), f"a trigger function writes a header table at depth two, where this trigger does not judge it: {sorted(trigger_writers)}"
    # the receipt settlement writes paid_paise and status on an invoice (columns this trigger allows) and is reached only through its
    # guarded wrapper; the numbered-document function and the firm purge build their statements dynamically, so the scan cannot see
    # them and they are named by hand
    assert writers == {"settle_receipt_atomic__unguarded"}, sorted(writers)
    assert {"numbered_document_atomic__unguarded", "platform_purge_firm"} <= {f["n"] for f in functions}
    triggers = _rows(world.dsn, "SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text = ANY(ARRAY["
                                + ", ".join(f"'{t}'" for t in TABLES) + "]) ORDER BY 1, 2")
    # the audit trigger is AFTER ROW and writes audit_log only; migration 544's trigger reads OLD and NEW and writes nothing
    # and migration 565's six client-in-firm / customer-in-client / vendor-in-client triggers, which read `clients`, `customers` and `vendors` and write nothing
    others = [(t, n) for t, n in triggers if n not in (TRIGGER, "trg_audit_capture", "a_documents_settlement_is_written_by_the_api_only")
              and not re.fullmatch(r"row_(client_in_firm|customer_in_client|vendor_in_client)_(ins|upd)", n)]
    assert others == [], others


# ── WHAT IS NOT JUDGED ──────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["service_role", "owner"])
@pytest.mark.parametrize("table", TABLES)
def test_the_privileged_client_and_the_owner_change_delete_and_insert_anything(world, table, who):
    doc = world.row(table, _non_draft(table))
    assert _wrote(_op(world.dsn, who, f"UPDATE {table} SET total_paise = total_paise + 1 WHERE id = '{doc}'"))
    assert _wrote(_op(world.dsn, who, f"UPDATE {table} SET status = 'draft' WHERE id = '{doc}'"))
    assert _wrote(_op(world.dsn, who, f"DELETE FROM {table} WHERE id = '{doc}'"))
    assert _wrote(_op(world.dsn, who, _insert(table, _header_values(table, _non_draft(table), 903, _ids(world)))))


@pytest.mark.parametrize("table", TABLES)
def test_the_anonymous_role_is_judged_as_well(world, table):
    """Production's platform defaults grant `anon` every privilege on a public table and row security is all that keeps it out; a
    database built from the migrations grants it nothing. The worst case: `anon` is granted the writes and row security is off, so
    the trigger is the only thing between it and an issued document."""
    done = _psql(world.dsn, f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO anon; ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    assert done.returncode == 0, done.stderr
    draft, issued = world.row(table, "draft"), world.row(table, _non_draft(table))
    assert _wrote(_op(world.dsn, "anon", f"UPDATE {table} SET total_paise = total_paise + 1 WHERE id = '{draft}'")), "the worst case was not made"
    assert _by_the_trigger(_op(world.dsn, "anon", f"UPDATE {table} SET total_paise = total_paise + 1 WHERE id = '{issued}'"))
    assert _by_the_trigger(_op(world.dsn, "anon", f"DELETE FROM {table} WHERE id = '{issued}'"))


# ── THE FUNCTION, THE BLOCK, THE ROLLBACK, THE SECOND RUN ───────────────────

def test_the_function_is_not_executable_by_a_signed_in_role_even_when_the_platform_granted_it_first(world):
    fn = f"public.{FUNCTION}()"
    probe = f"SELECT has_function_privilege('authenticated', '{fn}', 'EXECUTE'), has_function_privilege('anon', '{fn}', 'EXECUTE')"
    assert _rows(world.dsn, probe) == [["f", "f"]]
    assert _psql(world.dsn, f"GRANT EXECUTE ON FUNCTION {fn} TO PUBLIC, anon, authenticated;").returncode == 0
    assert _rows(world.dsn, probe) == [["t", "t"]], "the worst case was not made"
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, probe) == [["f", "f"]]


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
    # the lock is asked for all six tables at once, without queueing, and retried
    lock = re.findall(r"\bLOCK TABLE\b([^;]*);", holders[0])
    assert len(lock) == 1 and all(f"public.{t}" in lock[0] for t in TABLES) and "NOWAIT" in lock[0], lock
    assert "lock_not_available" in holders[0] and "pg_sleep" in holders[0]
    if creates:
        assert len(re.findall(r"\bCREATE OR REPLACE TRIGGER\b", holders[0])) == 6
        assert len(re.findall(r"\bCREATE TRIGGER\b", holders[0])) == 0


# ── THE LOCK WAIT ───────────────────────────────────────────────────────────

def _hold(dsn: str, table: str, mode: str, seconds: int) -> subprocess.Popen:
    """A second session that writes `table` (holds `mode`) for `seconds`, started and given a moment to take its lock."""
    import time
    proc = subprocess.Popen(["psql", dsn, "-X", "-q", "-c", f"BEGIN; LOCK TABLE public.{table} IN {mode} MODE; SELECT pg_sleep({seconds}); COMMIT;"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for _ in range(40):
        # this database only: clones of one template share relation numbers, so a holder in another clone (migration 544's test holds
        # purchase_bills too, on another worker under --dist loadfile) would otherwise satisfy this wait
        held = _rows(dsn, f"SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.relation = 'public.{table}'::regclass "
                          f"AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                          f"AND l.mode = '{mode.title().replace(' ', '')}Lock' AND l.granted AND a.query LIKE 'BEGIN; LOCK TABLE%'")
        if held[0][0] != "0":
            return proc
        time.sleep(0.25)
    proc.kill()
    raise AssertionError("the holder never took its lock")


@pytest.mark.parametrize("path, mode", [(MIGRATION, "ROW EXCLUSIVE"), (ROLLBACK, "ACCESS SHARE")], ids=["migration", "rollback"])
def test_a_busy_table_is_waited_for_without_holding_the_other_five(world, path, mode):
    """While one table is held, the block holds NOTHING: a third session writes to all the other five throughout the wait (a plain
    multi-table LOCK would sit on the tables before the busy one and block them), and once the holder commits the file applies."""
    import time
    holder = _hold(world.dsn, "purchase_bills", mode, 5)
    started = time.monotonic()
    runner = subprocess.Popen(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(3):
            time.sleep(0.9)
            assert runner.poll() is None, "the file finished while a table was still held"
            for table in TABLES:
                if table == "purchase_bills":
                    continue
                probe = _psql(world.dsn, f"SET lock_timeout = '1500ms'; BEGIN; LOCK TABLE public.{table} IN ROW EXCLUSIVE MODE; COMMIT;")
                assert probe.returncode == 0, f"{table} was held while the file waited for purchase_bills: {probe.stderr}"
        _out, err = runner.communicate(timeout=60)
    finally:
        holder.wait(timeout=60)
        if runner.poll() is None:
            runner.kill()
    assert runner.returncode == 0, err
    assert time.monotonic() - started >= 3.5, "it did not wait for the holder"
    assert holder.returncode == 0


def test_a_re_apply_does_not_wait_for_a_reader_nor_make_one_wait(world):
    """The review's repro: with the triggers present, a transaction that has only READ the table (ACCESS SHARE) is not a reason for
    the migration to wait, because nothing in it asks for a lock that conflicts with a read; a DROP TRIGGER would have queued
    behind it, blocked every later read and write, and deadlocked a transaction that reads and then writes."""
    import time
    holder = _hold(world.dsn, "purchase_bills", "ACCESS SHARE", 6)
    started = time.monotonic()
    try:
        done = subprocess.run(["psql", world.dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(MIGRATION)], capture_output=True, text=True, timeout=60)
        elapsed = time.monotonic() - started
        probe = _psql(world.dsn, "SET lock_timeout = '1500ms'; BEGIN; LOCK TABLE public.purchase_bills IN ROW EXCLUSIVE MODE; COMMIT;")
    finally:
        holder.wait(timeout=60)
    assert done.returncode == 0, done.stderr
    assert elapsed < 4, f"the re-apply waited {elapsed:.1f}s for a reader"
    assert probe.returncode == 0, probe.stderr


def test_a_table_that_stays_busy_fails_the_migration_after_fifteen_seconds_in_its_own_words_and_changes_nothing(world):
    import time
    before = _catalogue(world.dsn)
    holder = _hold(world.dsn, "client_sales_invoices", "ROW EXCLUSIVE", 30)
    try:
        started = time.monotonic()
        done = _psql_file(world.dsn, MIGRATION)
        waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=30)
    assert done.returncode != 0 and "could not lock the six document header tables in 15 seconds" in done.stderr, done.stderr
    assert 13 <= waited <= 25, waited
    assert _catalogue(world.dsn) == before


def _catalogue(dsn: str) -> list:
    return _rows(dsn, "SELECT tgrelid::regclass::text, tgname, tgenabled::text, encode(tgargs, 'hex'), tgtype::text FROM pg_trigger "
                      f"WHERE tgname = '{TRIGGER}' AND NOT tgisinternal ORDER BY 1") + _rows(
        dsn, f"SELECT 'f', proname, prosecdef::text, md5(prosrc), coalesce(array_to_string(proacl, ','), '') FROM pg_proc WHERE proname = '{FUNCTION}'")


def test_there_are_six_triggers_and_one_function(world):
    cat = _catalogue(world.dsn)
    assert len([r for r in cat if r[0] != "f"]) == 6 and len([r for r in cat if r[0] == "f"]) == 1, cat
    assert all(r[4] == "31" for r in cat if r[0] != "f"), "ROW + BEFORE + INSERT + DELETE + UPDATE"


def test_a_second_run_of_the_migration_changes_nothing(world):
    before = _catalogue(world.dsn)
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _catalogue(world.dsn) == before


def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it(world):
    inv = world.row("client_sales_invoices", "issued")
    forge = f"UPDATE client_sales_invoices SET total_paise = total_paise + 1 WHERE id = '{inv}'"
    assert _by_the_trigger(_op(world.dsn, "manager_a", forge))
    done = _psql_file(world.dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_trigger WHERE tgname = '{TRIGGER}' AND NOT tgisinternal") == [["0"]]
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_proc WHERE proname = '{FUNCTION}'") == [["0"]]
    assert _wrote(_op(world.dsn, "manager_a", forge)), "the negative control: with the migration rolled back the forgery works"
    assert _wrote(_op(world.dsn, "manager_a", f"DELETE FROM client_sales_invoices WHERE id = '{inv}'"))
    again = _psql_file(world.dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _by_the_trigger(_op(world.dsn, "manager_a", forge))
