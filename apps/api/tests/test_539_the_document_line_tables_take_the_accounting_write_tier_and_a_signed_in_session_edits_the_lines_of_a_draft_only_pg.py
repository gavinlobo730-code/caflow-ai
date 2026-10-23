"""Migration 539 — the document line tables take the accounting write tier, and a signed-in session edits the lines of a draft
document; on any other document it may only correct a unit of measure or clear a catalogue link (POST-A-328).

WHAT WAS WRONG
    Eight line tables carried the parent's READ scope and nothing more: no role tier, no rule about the document's state, no
    trigger. A Reviewer assigned to a client, or an Executive, could change the quantity, rate, HSN or tax of a line of an ISSUED
    invoice, bill or note over PostgREST without touching the header or the journal, while the API refuses that (every note's
    PATCH is draft-only, an invoice or bill replaces its lines only while draft, and the one post-issue edit is a `unit`
    correction).

WHAT THIS HOLDS (real Postgres, as each person)
    * THE TIER, on all eight tables: a Partner, a Manager assigned to the client, an Executive the grid granted `accounting:write`
      write a draft's line; a Reviewer, an Executive the grid did not grant and a Manager the grid denied are refused: an INSERT is
      an error, and an UPDATE or a DELETE finds no row (the policy filters it, as it does for a member the assignment scope hides
      the document from); the people the tier refuses can still READ the line. A Manager assigned to no client is in the matrix
      too, but that person is refused by the assignment scope that was there before the migration, so that case shows the scope
      still holds and says nothing about the tier.
    * THE DRAFT RULE, on the six tables whose documents have a draft: the Manager who may write a draft's line is refused (42501
      and the sentence) an insert, an update and a delete of a line of a document that is issued (or, by table, received, paid,
      partially paid, applied or cancelled); the same writes on a draft pass. Two exceptions, each an UPDATE that changes nothing
      else: a change of `unit` alone on an invoice or bill line of a document that is not cancelled (it fails if it changes anything
      else, if the document is cancelled or if it moves the line to another document), and the foreign-key action of deleting a
      catalogue item (SET NULL on the link) on a line of a CANCELLED document, so deleting a preset used only on drafts and
      cancelled documents works for a Manager and a Partner and deleting one used on an issued document is refused (the code
      tests the SHAPE of the change, so clearing either link directly on a cancelled document's line passes too, and nothing
      else does); the recurring-template
      lines have no state rule. The anonymous role is judged too (made reachable on purpose in a worst case).
    * A RACE: a line write that arrives while its document is being issued waits for the issue and is then refused.
    * WHAT IS NOT JUDGED: the service role and the database owner insert, update and delete the lines of an issued document (the
      API's privileged writers); a Partner's delete of a draft, and of an issued document, removes its lines in the cascade without
      the trigger refusing it; a document built and issued in steps (insert the draft, insert its lines, issue it, try to edit
      them) behaves as the product does.
    * THE MIGRATION: the statements that take the table locks (CREATE and DROP of a policy or a trigger) run inside one block and
      not as seventy top-level statements, in the migration and in its rollback; the trigger function is not executable by a
      signed-in role even when the platform's defaults granted it first;
      the policies ask who is calling once per query; the rollback brings the forgery back (the negative control) and a re-apply
      ends it; a second run leaves every policy, trigger and the function exactly as they were.

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
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the document-line proof requires HARNESS_PG + psql",
)

_STEM = "539_the_document_line_tables_take_the_accounting_write_tier_and_a_signed_in_session_edits_the_lines_of_a_draft_only"
FUNCTION = "refuse_a_signed_in_edit_of_lines_of_a_non_draft_document"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

FIRM = "53900000-0000-0000-0000-000000000001"
CLIENT_A = "53900000-0000-0000-0000-0000000000a1"
CLIENT_B = "53900000-0000-0000-0000-0000000000b2"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("53900000-0000-0000-0000-00000000000a", "53900000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("53900000-0000-0000-0000-00000000000b", "53900000-1111-0000-0000-000000000002", "Manager"),
    "manager_none": ("53900000-0000-0000-0000-00000000000c", "53900000-1111-0000-0000-000000000003", "Manager"),
    "executive_a": ("53900000-0000-0000-0000-00000000000e", "53900000-1111-0000-0000-000000000004", "Executive"),
    "reviewer_a": ("53900000-0000-0000-0000-00000000000f", "53900000-1111-0000-0000-000000000005", "Reviewer"),
    "executive_granted": ("53900000-0000-0000-0000-000000000011", "53900000-1111-0000-0000-000000000007", "Executive"),
    "manager_denied": ("53900000-0000-0000-0000-000000000012", "53900000-1111-0000-0000-000000000008", "Manager"),
}
CLIENT_A_MEMBERS = ("manager_a", "executive_a", "reviewer_a", "executive_granted", "manager_denied")
_F = f"'{FIRM}'"

# table -> (parent, fk column on the line, has a draft state, unit-only exception, statuses a document can be in besides draft)
SPECS = {
    "client_sales_invoice_lines": ("client_sales_invoices", "sales_invoice_id", True, True, ["issued", "partially_paid", "paid", "cancelled"]),
    "purchase_bill_lines": ("purchase_bills", "bill_id", True, True, ["received", "partially_paid", "paid", "cancelled"]),
    "credit_note_lines": ("credit_notes", "credit_note_id", True, False, ["issued", "applied"]),
    "debit_note_lines": ("debit_notes", "debit_note_id", True, False, ["issued"]),
    "purchase_credit_note_lines": ("purchase_credit_notes", "credit_note_id", True, False, ["issued"]),
    "sales_debit_note_lines": ("sales_debit_notes", "debit_note_id", True, False, ["issued"]),
    "recurring_invoice_template_lines": ("recurring_invoice_templates", "template_id", False, False, []),
    "recurring_purchase_bill_template_lines": ("recurring_purchase_bill_templates", "template_id", False, False, []),
}
TABLES = list(SPECS)
WITH_DRAFT = [t for t in TABLES if SPECS[t][2]]
WITH_UNIT = [t for t in TABLES if SPECS[t][3]]
STATE_CASES = [(t, s) for t in WITH_DRAFT for s in SPECS[t][4]]
TIER = {"partner": True, "manager_a": True, "executive_granted": True,
        "reviewer_a": False, "executive_a": False, "manager_denied": False, "manager_none": False}


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
    if who == "anon":
        return "SET request.jwt.claims = '{\"role\": \"anon\"}'; SET ROLE anon; "
    if who in ("service_role", "owner"):
        return "SET request.jwt.claims = '{\"role\": \"service_role\"}'; " + ("SET ROLE service_role; " if who == "service_role" else "")
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _count_as(dsn: str, who: str, table: str) -> int:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + f"SELECT count(*) FROM {table};"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return int([line for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"][-1])


def _op(dsn: str, who: str, dml: str) -> str:
    """Run one statement as `who`, report its row count (or `err:<SQLSTATE> <message>` when the database refuses it), and undo it."""
    do = (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE 'out=%', c; "
          f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
          f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE 'out=err:% %', SQLSTATE, SQLERRM; END; END $$;")
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) + do], capture_output=True, text=True)
    got = re.findall(r"NOTICE:\s+out=(.*)", r.stderr)
    assert got, r.stderr[-400:]
    return got[-1].strip()


def _refused(outcome: str) -> bool:
    return outcome.startswith("err:42501")


def _wrote(outcome: str) -> bool:
    return outcome == "1"


# ── THE SEED ────────────────────────────────────────────────────────────────

def _insert(table: str, cols: dict) -> str:
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(cols.values())})"


def _parent_values(table: str, status: str, n: int, ids: dict) -> dict:
    cust, vend = ids["customer"], ids["vendor"]
    base = {"firm_id": _F, "client_id": _q(CLIENT_A)}
    return {
        "client_sales_invoices": {"customer_id": _q(cust), "invoice_no": _q(f"INV-{n}"), "invoice_date": "'2026-04-01'", "status": _q(status)},
        "purchase_bills": {"vendor_id": _q(vend), "bill_date": "'2026-04-01'", "status": _q(status)},
        "credit_notes": {"customer_id": _q(cust), "credit_note_no": _q(f"CN-{n}"), "credit_note_date": "'2026-04-01'", "status": _q(status)},
        "debit_notes": {"vendor_id": _q(vend), "debit_note_no": _q(f"DN-{n}"), "debit_note_date": "'2026-04-01'", "status": _q(status)},
        "purchase_credit_notes": {"vendor_id": _q(vend), "credit_note_no": _q(f"PCN-{n}"), "credit_note_date": "'2026-04-01'", "status": _q(status)},
        "sales_debit_notes": {"customer_id": _q(cust), "debit_note_no": _q(f"SDN-{n}"), "debit_note_date": "'2026-04-01'", "status": _q(status)},
        "recurring_invoice_templates": {"customer_id": _q(cust), "title": _q(f"ri-{n}"), "frequency": "'monthly'", "start_date": "'2026-04-01'",
                                        "next_run_date": "'2026-05-01'"},
        "recurring_purchase_bill_templates": {"vendor_id": _q(vend), "title": _q(f"rp-{n}"), "frequency": "'monthly'",
                                              "start_date": "'2026-04-01'", "next_run_date": "'2026-05-01'"},
    }[table] | base


def _line_values(table: str, parent_id: str, ids: dict, description: str = "Widget") -> dict:
    _parent, fk, *_ = SPECS[table]
    cols = {fk: _q(parent_id), "description": _q(description)}
    if table == "recurring_invoice_template_lines":
        cols["service_catalogue_id"] = _q(ids["item"])
    if table == "debit_note_lines":
        cols.pop("description")
    if table == "purchase_credit_note_lines":
        cols.pop("description")
    return cols


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
           "item": one(f"SELECT id FROM service_catalogue WHERE client_id = '{CLIENT_A}'")}
    w.ids["const"] = {"item": ids["item"]}
    n = 0
    for table, (parent, _fk, has_draft, _unit, others) in SPECS.items():
        for tag in (["draft"] + others) if has_draft else ["draft"]:
            n += 1
            status = "draft" if tag == "draft" else tag
            pid = w.put(parent, f"{table}:{tag}", _parent_values(parent, status, n, ids))
            w.put(table, f"{tag}", _line_values(table, pid, ids))
            w.ids.setdefault("parent_of", {})[f"{table}:{tag}"] = pid


@pytest.fixture(scope="module")
def seeded(pg_template):
    admin = _ADMIN.strip()
    name = f"e539s_{uuid.uuid4().hex[:12]}"
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
            INSERT INTO user_permissions (firm_id, user_id, resource, action, granted)
                 VALUES ('{FIRM}', '{PEOPLE["executive_granted"][0]}', 'accounting', 'write', true),
                        ('{FIRM}', '{PEOPLE["manager_denied"][0]}', 'accounting', 'write', false);
            INSERT INTO customers (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT_A}', 'cust A');
            INSERT INTO service_catalogue (firm_id, client_id, name, kind) VALUES ('{FIRM}', '{CLIENT_A}', 'Widget', 'service');
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
    name = f"e539_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        w = World(f"{admin} dbname={name}")
        w.ids = {table: dict(rows) for table, rows in ids.items()}
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _new_line(w: World, table: str, tag: str) -> str:
    """An INSERT of a fresh line under the document tagged `tag`."""
    return _insert(table, _line_values(table, w.ids["parent_of"][f"{table}:{tag}"], w.ids["const"], "A second line"))


# ── THE TIER ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", list(TIER))
@pytest.mark.parametrize("table", TABLES)
def test_the_tier_decides_who_writes_a_draft_documents_line(world, table, who):
    may = TIER[who]
    parent, fk, *_ = SPECS[table]
    line = world.row(table, "draft")
    inserted = _op(world.dsn, who, _new_line(world, table, "draft"))
    updated = _op(world.dsn, who, f"UPDATE {table} SET description = 'edited' WHERE id = '{line}'")
    deleted = _op(world.dsn, who, f"DELETE FROM {table} WHERE id = '{line}'")
    if may:
        assert (_wrote(inserted), _wrote(updated), _wrote(deleted)) == (True, True, True), (inserted, updated, deleted)
    else:
        # a refused INSERT is an error (the policy's check); a refused UPDATE or DELETE finds no row (the policy's filter), which is
        # also what a member the assignment scope hides the document from sees
        assert _refused(inserted), inserted
        assert updated == "0" and deleted == "0", (updated, deleted)


@pytest.mark.parametrize("who", ["reviewer_a", "executive_a", "manager_denied"])
@pytest.mark.parametrize("table", TABLES)
def test_a_person_the_tier_refuses_still_reads_the_line(world, table, who):
    assert _count_as(world.dsn, who, table) >= 1


# ── THE DRAFT RULE ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("table,status", STATE_CASES)
def test_a_manager_is_refused_every_write_to_the_lines_of_a_document_that_is_not_a_draft(world, table, status):
    line = world.row(table, status)
    for dml in (_new_line(world, table, status),
                f"UPDATE {table} SET description = 'edited' WHERE id = '{line}'",
                f"DELETE FROM {table} WHERE id = '{line}'"):
        out = _op(world.dsn, "manager_a", dml)
        assert _refused(out), (dml[:40], status, out)
        assert "cannot be changed from a signed-in session" in out, out
        # the sentence names the document and says what to do about it: a cancelled document keeps its lines, any other is corrected by a note
        assert (("keeps its lines as they were" in out) if status == "cancelled" else ("correct an issued document with a credit or debit note" in out)), out
        assert f"that is {status} " in out, out


@pytest.mark.parametrize("table", WITH_DRAFT)
def test_the_same_writes_pass_while_the_document_is_a_draft(world, table):
    line = world.row(table, "draft")
    assert _wrote(_op(world.dsn, "manager_a", _new_line(world, table, "draft")))
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET description = 'edited' WHERE id = '{line}'"))
    assert _wrote(_op(world.dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{line}'"))


@pytest.mark.parametrize("table", [t for t in TABLES if not SPECS[t][2]])
def test_a_template_has_no_state_rule(world, table):
    line = world.row(table, "draft")
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET description = 'edited' WHERE id = '{line}'"))


@pytest.mark.parametrize("table,status", [(t, s) for t, s in STATE_CASES if t in WITH_UNIT and s != "cancelled"])
def test_a_unit_only_correction_passes_on_a_document_that_is_not_cancelled(world, table, status):
    line = world.row(table, status)
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET unit = 'KGS' WHERE id = '{line}'"))
    assert _wrote(_op(world.dsn, "partner", f"UPDATE {table} SET unit = 'KGS' WHERE id = '{line}'"))


@pytest.mark.parametrize("table", WITH_UNIT)
def test_a_unit_correction_that_changes_anything_else_is_refused(world, table):
    line = world.row(table, "paid")
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET unit = 'KGS', description = 'sneaky' WHERE id = '{line}'")
    assert _refused(out), out
    out = _op(world.dsn, "manager_a", f"UPDATE {table} SET description = 'sneaky' WHERE id = '{line}'")
    assert _refused(out), out


@pytest.mark.parametrize("table", WITH_UNIT)
def test_a_unit_correction_on_a_cancelled_document_is_refused(world, table):
    line = world.row(table, "cancelled")
    assert _refused(_op(world.dsn, "manager_a", f"UPDATE {table} SET unit = 'KGS' WHERE id = '{line}'"))


@pytest.mark.parametrize("table", WITH_UNIT)
def test_a_unit_correction_cannot_move_the_line_to_another_document(world, table):
    _parent, fk, *_ = SPECS[table]
    line = world.row(table, "paid")
    draft_parent = world.ids["parent_of"][f"{table}:draft"]
    assert _refused(_op(world.dsn, "manager_a", f"UPDATE {table} SET unit = 'KGS', {fk} = '{draft_parent}' WHERE id = '{line}'"))


@pytest.mark.parametrize("table", ["credit_note_lines", "debit_note_lines", "purchase_credit_note_lines", "sales_debit_note_lines"])
def test_a_note_has_no_unit_exception(world, table):
    line = world.row(table, "issued")
    assert _refused(_op(world.dsn, "manager_a", f"UPDATE {table} SET unit = 'KGS' WHERE id = '{line}'"))


@pytest.mark.parametrize("table", WITH_DRAFT)
def test_a_line_cannot_be_moved_from_a_draft_to_an_issued_document(world, table):
    _parent, fk, _d, _u, others = SPECS[table]
    line = world.row(table, "draft")
    other = world.ids["parent_of"][f"{table}:{others[0]}"]
    assert _refused(_op(world.dsn, "manager_a", f"UPDATE {table} SET {fk} = '{other}' WHERE id = '{line}'"))


@pytest.mark.parametrize("table", WITH_DRAFT)
def test_the_draft_rule_judges_the_anonymous_role_as_well(world, table):
    """Production's platform defaults grant `anon` every privilege on a public table and row security is all that keeps it out; a
    database built from the migrations grants it nothing. The worst case is made here: `anon` is granted the writes and given a
    permissive policy that lets every row through, so the only thing between it and an issued document's line is the trigger."""
    done = _psql(world.dsn, f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO anon; "
                            f"CREATE POLICY anon_worst_case ON {table} AS PERMISSIVE FOR ALL TO anon USING (true) WITH CHECK (true);")
    assert done.returncode == 0, done.stderr
    draft, issued = world.row(table, "draft"), world.row(table, SPECS[table][4][0])
    assert _wrote(_op(world.dsn, "anon", f"UPDATE {table} SET description = 'edited' WHERE id = '{draft}'")), "the worst case was not made"
    for dml in (_new_line(world, table, SPECS[table][4][0]),
                f"UPDATE {table} SET description = 'edited' WHERE id = '{issued}'",
                f"DELETE FROM {table} WHERE id = '{issued}'"):
        out = _op(world.dsn, "anon", dml)
        assert _refused(out) and "cannot be changed from a signed-in session" in out, (dml[:40], out)


# ── WHAT IS NOT JUDGED ──────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["service_role", "owner"])
@pytest.mark.parametrize("table,status", [(t, SPECS[t][4][0]) for t in WITH_DRAFT])
def test_the_privileged_client_and_the_owner_write_the_lines_of_an_issued_document(world, table, status, who):
    line = world.row(table, status)
    assert _wrote(_op(world.dsn, who, f"UPDATE {table} SET description = 'by the server' WHERE id = '{line}'"))


@pytest.mark.parametrize("table", WITH_DRAFT)
def test_deleting_a_draft_removes_its_lines_in_the_cascade(world, table):
    parent, *_ = SPECS[table]
    pid = world.ids["parent_of"][f"{table}:draft"]
    r = _psql(world.dsn, _as("partner") + f"DELETE FROM {parent} WHERE id = '{pid}';")
    # the document may be undeletable for another reason (a policy, a dependent row); what matters is the cascade is not refused by the trigger
    assert "cannot be changed from a signed-in session" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM {table} WHERE id = '{world.row(table, 'draft')}'") == [["0"]]


@pytest.mark.parametrize("table", ["client_sales_invoice_lines", "purchase_bill_lines"])
def test_a_document_built_in_steps_is_editable_while_it_is_a_draft_and_locked_once_issued(world, table):
    parent, fk, _d, _u, others = SPECS[table]
    first = world.ids["parent_of"][f"{table}:draft"]
    # the product's own order: the draft exists, its lines are replaced (delete then insert), then it is issued
    line = world.row(table, "draft")
    assert _wrote(_op(world.dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{line}'"))
    assert _wrote(_op(world.dsn, "manager_a", _new_line(world, table, "draft")))
    done = _psql(world.dsn, f"UPDATE {parent} SET status = '{others[0]}' WHERE id = '{first}'")
    assert done.returncode == 0, done.stderr
    assert _refused(_op(world.dsn, "manager_a", _new_line(world, table, "draft")))
    assert _refused(_op(world.dsn, "manager_a", f"DELETE FROM {table} WHERE {fk} = '{first}'"))


@pytest.mark.parametrize("table", TABLES)
def test_the_write_tier_asks_who_is_calling_once_per_query_and_not_once_per_row(world, table):
    """Migration 525 wrapped every helper call in `(SELECT ...)` so it is evaluated once per query; a policy that calls
    `my_permission(...)` bare is evaluated per row, and `test_a_policy_asks_who_is_calling_once_per_query_and_not_once_per_row_pg`
    refuses it in CI. Asked here too so the three commands of every line table are named and counted in this file."""
    got = _rows(world.dsn, f"SELECT p.polname, p.polcmd, coalesce(pg_get_expr(p.polqual, p.polrelid), ''), "
                           f"coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') FROM pg_policy p "
                           f"WHERE p.polrelid = 'public.{table}'::regclass AND p.polname LIKE '%_write_tier_%' ORDER BY 1")
    assert [r[0] for r in got] == sorted(f"{table}_write_tier_{c}" for c in ("insert", "update", "delete")), got
    assert sorted(r[1] for r in got) == ["a", "d", "w"], got
    for name, _cmd, using, check in got:
        for expr in (using, check):
            assert expr.count("my_permission(") == expr.count("( SELECT my_permission("), f"{name}: {expr}"
        assert "my_permission(" in (using + check), name
        assert "'Manager'" in (using + check) and "'accounting'" in (using + check) and "'write'" in (using + check), name


# ── DELETING A CATALOGUE ITEM: THE FOREIGN KEY'S SET NULL IS AN UPDATE OF THE LINE ──────────────────────────

CATALOGUE_TABLES = ["client_sales_invoice_lines", "purchase_bill_lines", "credit_note_lines", "debit_note_lines"]


def _item_on(world: World, table: str, status: str) -> str:
    """A fresh catalogue item linked, as the owner, to the line of the document in `status`; returns the item's id."""
    item = world.put("service_catalogue", f"{table}:{status}",
                     {"firm_id": _F, "client_id": _q(CLIENT_A), "name": _q(f"item {table} {status}"), "kind": "'service'"})
    done = _psql(world.dsn, f"UPDATE {table} SET service_catalogue_id = '{item}' WHERE id = '{world.row(table, status)}'")
    assert done.returncode == 0, done.stderr
    return item


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table,status", [(t, s) for t in CATALOGUE_TABLES for s in ["draft"] + (["cancelled"] if "cancelled" in SPECS[t][4] else [])])
def test_a_preset_used_only_on_a_draft_or_a_cancelled_document_can_still_be_deleted(world, table, status, who):
    """routers/service_catalogue.py lets a preset go when every document that carries it is a draft or cancelled. The delete's
    ON DELETE SET NULL is an UPDATE of the line under the deleting person's role setting, so it is judged by the trigger."""
    item = _item_on(world, table, status)
    assert _wrote(_op(world.dsn, who, f"DELETE FROM service_catalogue WHERE id = '{item}'"))


@pytest.mark.parametrize("who", ["manager_a", "partner"])
@pytest.mark.parametrize("table", CATALOGUE_TABLES)
def test_a_preset_used_on_an_issued_document_is_not_deleted_by_cutting_the_link(world, table, who):
    item = _item_on(world, table, SPECS[table][4][0])
    out = _op(world.dsn, who, f"DELETE FROM service_catalogue WHERE id = '{item}'")
    assert _refused(out) and "cannot be changed from a signed-in session" in out, out


@pytest.mark.parametrize("table", ["client_sales_invoice_lines", "purchase_bill_lines"])
def test_the_link_exception_changes_nothing_else_on_a_cancelled_documents_line(world, table):
    item = _item_on(world, table, "cancelled")
    line = world.row(table, "cancelled")
    assert _wrote(_op(world.dsn, "manager_a", f"UPDATE {table} SET service_catalogue_id = NULL WHERE id = '{line}'"))
    for change in ("description = 'sneaky'", "service_catalogue_id = NULL, description = 'sneaky'"):
        out = _op(world.dsn, "manager_a", f"UPDATE {table} SET {change} WHERE id = '{line}'")
        assert _refused(out), (change, out)
    other = world.put("service_catalogue", f"{table}:other", {"firm_id": _F, "client_id": _q(CLIENT_A), "name": "'another item'", "kind": "'service'"})
    assert _refused(_op(world.dsn, "manager_a", f"UPDATE {table} SET service_catalogue_id = '{other}' WHERE id = '{line}'"))
    assert item


# ── A WRITE THAT RACES THE ISSUING OF ITS DOCUMENT ──────────────────────────

def test_a_line_write_that_races_the_issuing_of_its_document_waits_and_is_then_refused(world):
    """The trigger reads the parent's status FOR SHARE. Without it the writer reads `draft` (the issuing transaction has not
    committed) and the line lands in a document that is issued a moment later."""
    table = "client_sales_invoice_lines"
    pid = world.ids["parent_of"][f"{table}:draft"]
    issuing = subprocess.Popen(
        ["psql", world.dsn, "-X", "-q", "-c",
         f"BEGIN; UPDATE client_sales_invoices SET status = 'issued' WHERE id = '{pid}'; SELECT pg_sleep(6); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(60):
            held = _rows(world.dsn, "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND query LIKE '%pg_sleep(6)%' "
                                    "AND pid <> pg_backend_pid()")
            if held == [["1"]]:
                break
            time.sleep(0.2)
        else:
            pytest.fail("the issuing transaction never started")
        began = time.monotonic()
        out = _op(world.dsn, "manager_a", _new_line(world, table, "draft"))
        waited = time.monotonic() - began
    finally:
        issuing.communicate(timeout=60)
    assert _refused(out) and "cannot be changed from a signed-in session" in out, out
    assert waited > 2, f"the write did not wait for the issue ({waited:.2f}s)"


# ── THE OWNER, THE SERVICE ROLE AND A DELETE THAT CASCADES ──────────────────

@pytest.mark.parametrize("who", ["service_role", "owner"])
@pytest.mark.parametrize("table", WITH_DRAFT)
def test_the_privileged_client_and_the_owner_also_insert_and_delete_the_lines_of_an_issued_document(world, table, who):
    status = SPECS[table][4][0]
    assert _wrote(_op(world.dsn, who, _new_line(world, table, status)))
    assert _wrote(_op(world.dsn, who, f"DELETE FROM {table} WHERE id = '{world.row(table, status)}'"))


@pytest.mark.parametrize("table", WITH_DRAFT)
def test_deleting_an_issued_document_removes_its_lines_without_the_trigger_refusing_the_cascade(world, table):
    """The branch for a document that cannot be found: by the time the cascade reaches a line its document is gone, so nothing is
    left to judge it by. A signed-in session can no longer delete an issued header itself (migration 541), so the document goes the
    way it still can: with its customer or vendor. The two note tables that name their vendor without a foreign key have no such
    way, so for them the header's own rule is taken out of the way and what is under test is still the line trigger's."""
    parent, _fk, _draft, _unit, states = SPECS[table]
    status = states[0]
    pid = world.ids["parent_of"][f"{table}:{status}"]
    if parent in ("debit_notes", "purchase_credit_notes"):
        done = _psql(world.dsn, f"ALTER TABLE {parent} DISABLE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars;")
        assert done.returncode == 0, done.stderr
        target = f"DELETE FROM {parent} WHERE id = '{pid}';"
    else:
        owner = "customer" if parent in ("client_sales_invoices", "credit_notes", "sales_debit_notes") else "vendor"
        party = _rows(world.dsn, f"SELECT {owner}_id FROM {parent} WHERE id = '{pid}'")[0][0]
        target = f"DELETE FROM {owner}s WHERE id = '{party}';"
    r = _psql(world.dsn, _as("partner") + target)
    assert "cannot be changed from a signed-in session" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stderr
    assert _rows(world.dsn, f"SELECT count(*) FROM {parent} WHERE id = '{pid}'") == [["0"]]
    assert _rows(world.dsn, f"SELECT count(*) FROM {table} WHERE id = '{world.row(table, status)}'") == [["0"]]


# ── THE FUNCTION, THE ROLLBACK, THE SECOND RUN ──────────────────────────────

def test_the_trigger_function_is_not_executable_by_a_signed_in_role(world):
    for role in ("authenticated", "anon"):
        assert _rows(world.dsn, f"SELECT has_function_privilege('{role}', "
                                f"'public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document()', 'EXECUTE')") == [["f"]], role


def test_the_trigger_function_stays_closed_to_a_signed_in_role_when_the_platform_granted_it_first(world):
    """Production's platform defaults grant EXECUTE on a new function in `public` to PUBLIC, anon and authenticated, and a database
    built from the migrations does not, so the revoke is invisible there. The worst case is made here: the three are granted
    first and the migration is applied again."""
    fn = "public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document()"
    probe = f"SELECT has_function_privilege('authenticated', '{fn}', 'EXECUTE'), has_function_privilege('anon', '{fn}', 'EXECUTE')"
    done = _psql(world.dsn, f"GRANT EXECUTE ON FUNCTION {fn} TO PUBLIC, anon, authenticated;")
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, probe) == [["t", "t"]], "the worst case was not made"
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _rows(world.dsn, probe) == [["f", "f"]]


def test_there_are_twenty_four_restrictive_tier_policies_and_six_triggers(world):
    names = ", ".join(f"'{t}'" for t in TABLES)
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname IN ({names}) "
                            f"AND p.polname LIKE '%\\_write\\_tier\\_%' AND NOT p.polpermissive") == [["24"]]
    assert _rows(world.dsn, "SELECT count(*) FROM pg_trigger WHERE tgname = 'a_document_that_is_not_a_draft_keeps_its_lines' AND NOT tgisinternal") == [["6"]]


def _dollar_quoted_bodies(sql: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"\$(\w*)\$(.*?)\$\1\$", sql, flags=re.S)]


def _outside_the_bodies(sql: str) -> str:
    return re.sub(r"\$(\w*)\$.*?\$\1\$", " ", sql, flags=re.S)


@pytest.mark.parametrize("path, creates", [(MIGRATION, True), (ROLLBACK, False)], ids=["migration", "rollback"])
def test_the_statements_that_lock_the_tables_run_inside_one_block(path, creates):
    """CREATE POLICY and DROP POLICY take ACCESS EXCLUSIVE on the table and CREATE TRIGGER and DROP TRIGGER take SHARE ROW
    EXCLUSIVE and ACCESS EXCLUSIVE, all held to the end of the transaction, and the runner sends a top-level statement per
    round trip. A review ran the earlier shape (about seventy top-level statements) through a proxy that added a quarter of a
    second to each round trip: the invoice-lines table was locked for about 15 seconds, past the 8 seconds a signed-in request
    may run in production, and a reader holding a lock on a later table made the apply fail on its lock timeout. In one block the
    locks are held for the milliseconds the DDL takes. So no such statement may stand at the top level, and exactly one block
    holds them."""
    sql = re.sub(r"--[^\n]*", "", path.read_text())      # a comment may say CREATE POLICY; only a statement locks
    left = re.findall(r"\b(?:CREATE|DROP)\s+(?:POLICY|TRIGGER)\b[^;]*", _outside_the_bodies(sql), flags=re.I)
    assert left == [], f"a statement that takes a table lock stands at the top level: {left[:2]}"
    holders = [b for b in _dollar_quoted_bodies(sql) if re.search(r"\b(?:CREATE|DROP)\s+(?:POLICY|TRIGGER)\b", b, flags=re.I)]
    assert len(holders) == 1, f"{len(holders)} blocks hold the lock-taking statements, expected exactly one"
    if creates:
        assert len(re.findall(r"\bCREATE POLICY\s+\w+_write_tier_(?:insert|update|delete)\s+ON\b", holders[0])) == 24, "every policy is written out literally"
        assert len(re.findall(r"\bCREATE TRIGGER\s+a_document_that_is_not_a_draft_keeps_its_lines\b", holders[0])) == 6


def test_the_rollback_brings_the_forgery_back_and_a_reapply_ends_it(world):
    paid = world.row("client_sales_invoice_lines", "paid")
    forgery = f"UPDATE client_sales_invoice_lines SET description = 'forged' WHERE id = '{paid}'"
    assert _refused(_op(world.dsn, "manager_a", forgery))          # the trigger: a Manager may write lines, not a paid invoice's
    assert _op(world.dsn, "reviewer_a", forgery) == "0"            # the tier: a Reviewer's UPDATE finds no row
    done = _psql_file(world.dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    names = ", ".join(f"'{t}'" for t in TABLES)
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname IN ({names}) "
                            f"AND p.polname LIKE '%\\_write\\_tier\\_%'") == [["0"]], "the rollback left a tier policy behind"
    assert _rows(world.dsn, "SELECT count(*) FROM pg_trigger WHERE tgname = 'a_document_that_is_not_a_draft_keeps_its_lines' AND NOT tgisinternal") == [["0"]], \
        "the rollback left a trigger behind"
    assert _rows(world.dsn, f"SELECT count(*) FROM pg_proc WHERE proname = '{FUNCTION}'") == [["0"]], "the rollback left the function behind"
    assert _wrote(_op(world.dsn, "reviewer_a", forgery))        # the negative control: a Reviewer rewrote a paid invoice's line
    assert _wrote(_op(world.dsn, "manager_a", forgery))
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _op(world.dsn, "reviewer_a", forgery) == "0" and _refused(_op(world.dsn, "manager_a", forgery))


def _catalogue(dsn: str) -> list:
    return _rows(dsn, f"""
        SELECT 'p', polrelid::regclass::text, polname, polcmd::text, polpermissive::text,
               coalesce(pg_get_expr(polqual, polrelid), ''), coalesce(pg_get_expr(polwithcheck, polrelid), '')
          FROM pg_policy WHERE polname LIKE '%\\_write\\_tier\\_%' AND polrelid::regclass::text IN ({", ".join(f"'{t}'" for t in TABLES)})
        UNION ALL
        SELECT 't', tgrelid::regclass::text, tgname, tgenabled::text, '', pg_get_triggerdef(oid), ''
          FROM pg_trigger WHERE tgname = 'a_document_that_is_not_a_draft_keeps_its_lines' AND NOT tgisinternal
        UNION ALL
        SELECT 'f', '', proname, prosecdef::text, '', md5(prosrc), coalesce(array_to_string(proacl, ','), '')
          FROM pg_proc WHERE proname = '{FUNCTION}'
        ORDER BY 1, 2, 3""")


def test_a_second_run_of_the_migration_changes_nothing(world):
    before = _catalogue(world.dsn)
    assert len([r for r in before if r[0] == "p"]) == 24 and len([r for r in before if r[0] == "t"]) == 6 and len([r for r in before if r[0] == "f"]) == 1
    done = _psql_file(world.dsn, MIGRATION)
    assert done.returncode == 0, done.stderr
    assert _catalogue(world.dsn) == before
