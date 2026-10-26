"""The engagement letters take the client's assignment scope and the internal practice's Partner-only guard, and twenty tables
that hang from a client table are visible only where the row they hang from is (migration 529, POST-A-299 `engagements`,
POST-A-302, POST-A-305's two task tables).

WHAT WAS WRONG
    `engagements` (an engagement letter: the fee, the scope of work, the signatory; the client is nullable because a letter
    can be raised against a lead) carried a firm policy and nothing per client, and twenty tables that name the row they hang
    from and not a client (the four credit and debit note allocations, the letters' events, the payment events, the document
    extractions, the ITR versions, the onboarding tasks, the recurring-journal and recurring-bill runs, the three workflow
    logs, the year-end checklist, review and notes tables, the task tags and the task timeline) carried only a firm policy too.
    A member of the firm assigned to no client read every client's rows in all of them over PostgREST, and changed or deleted
    them in the ones they could write.

WHAT THIS HOLDS (for each of the twenty-one tables, the proof is the same; six of them are read-only to a signed-in session,
so for those the proof is the policies, the reads and the plan, and a test fails the day a write grant is added to one)
    * THE POLICIES: the twenty-two exist, RESTRICTIVE and FOR ALL, in the once-per-query form of migrations 525 to 528, and a
      child's names the parent (both parents, for an allocation).
    * WHO SEES WHAT: a Partner reads the rows of client A, client B, the firm's internal practice and the lead's letter; a
      Manager and an Executive assigned to A read A's and the lead's and nothing else; a Manager assigned to nothing reads the
      lead's only; a suspended Partner and a Partner of another firm read none. A row with NO parent (a payment event with no
      payment, an onboarding task with no workflow) and a letter with no client stay open to the firm.
    * WHO CHANGES WHAT: an assigned Manager inserts a child for their own client's parent; an insert onto another client's
      parent is refused by the database, as is an insert onto a parent of their own and a document of another client's (an
      allocation names TWO rows and the refusal is for either), and an update that MOVES a row onto such a parent. An update or a
      delete of another client's row matches nothing. A Partner does all of it for every client, the practice included.
    * THE LETTERS' OWN GUARD: a Manager assigned to the internal practice still reads none of its letters and adds none
      (the guard alone refuses it: they are assigned, so the scope admits the client).
    * THE FIRM WITH NO INTERNAL PRACTICE: a letter with no client is open to the firm, and a Manager can raise one.
    * THE THREE TABLES PRODUCTION DOES NOT HAVE: the migration applies, and rolls back, on a database without them.
    * THE ROLLBACK returns the firm-wide behaviour exactly, and a re-apply hides the rows again; a second run changes nothing;
      and the plan asks the caller's clients once per query.

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

from tests._signed_in_document_access import give_the_signed_in_document_access_back

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the engagement-letters scope proof requires HARNESS_PG + psql",
)

FIRM = "52900000-0000-0000-0000-000000000001"
OTHER_FIRM = "52900000-0000-0000-0000-000000000002"
CLIENT_A = "52900000-0000-0000-0000-0000000000a1"
CLIENT_B = "52900000-0000-0000-0000-0000000000b2"
INTERNAL = "52900000-0000-0000-0000-0000000000c3"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("52900000-0000-0000-0000-00000000000a", "52900000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager_a": ("52900000-0000-0000-0000-00000000000b", "52900000-1111-0000-0000-000000000002", "Manager", FIRM),
    "manager_none": ("52900000-0000-0000-0000-00000000000c", "52900000-1111-0000-0000-000000000003", "Manager", FIRM),
    "executive_a": ("52900000-0000-0000-0000-00000000000e", "52900000-1111-0000-0000-000000000004", "Executive", FIRM),
    "suspended": ("52900000-0000-0000-0000-00000000000f", "52900000-1111-0000-0000-000000000005", "Partner", FIRM),
    "other_firm": ("52900000-0000-0000-0000-000000000010", "52900000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
PARTNER_ID = PEOPLE["partner"][0]

_STEM = "529_the_engagement_letters_take_the_clients_assignment_scope_and_twenty_children_follow_their_parent"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"

_F = f"'{FIRM}'"
CLIENTS = {"A": CLIENT_A, "B": CLIENT_B, "I": INTERNAL}


def _q(value) -> str:
    return "NULL" if value is None else f"'{value}'"


# ── THE TWENTY-ONE TABLES ────────────────────────────────────────────────────────────────────────────────────────────
# parents of each child: (parent table, the column that points at it). Two entries = a row that hangs from two rows.
CHILDREN: dict[str, list[tuple[str, str]]] = {
    "engagement_events": [("engagements", "engagement_id")],
    "credit_note_allocations": [("credit_notes", "credit_note_id"), ("client_sales_invoices", "sales_invoice_id")],
    "debit_note_allocations": [("debit_notes", "debit_note_id"), ("purchase_bills", "purchase_bill_id")],
    "purchase_credit_note_allocations": [("purchase_credit_notes", "credit_note_id"), ("purchase_bills", "purchase_bill_id")],
    "sales_debit_note_allocations": [("sales_debit_notes", "debit_note_id"), ("client_sales_invoices", "sales_invoice_id")],
    "customer_payment_events": [("customer_payments", "payment_id")],
    "document_extractions": [("documents", "document_id")],
    "itr_filing_versions": [("itr_filings", "itr_filing_id")],
    "notes_to_accounts": [("year_end_engagements", "engagement_id")],
    "onboarding_tasks": [("onboarding_workflows", "workflow_id")],
    "recurring_journal_runs": [("recurring_journal_templates", "template_id")],
    "recurring_purchase_bill_runs": [("recurring_purchase_bill_templates", "template_id")],
    "workflow_approvals": [("workflow_instances", "instance_id")],
    "workflow_executions": [("workflow_instances", "instance_id")],
    "workflow_failures": [("workflow_instances", "instance_id")],
    "year_end_checklist_items": [("year_end_engagements", "engagement_id")],
    "year_end_checklists": [("year_end_engagements", "engagement_id")],
    "year_end_reviews": [("year_end_engagements", "engagement_id")],
    "task_tags": [("tasks", "task_id")],
    "task_timeline_events": [("tasks", "task_id")],
}
# a signed-in session is granted SELECT and nothing else on these six (their rows are written with the API's privileged client):
# the proof for them is the reads, the policies and the plan, and `test_the_tables_a_signed_in_session_cannot_write_are_the_ones_
# this_file_says` fails the day a write grant is added, so that the write proof applies to them from then on
READ_ONLY = {"credit_note_allocations", "task_tags", "task_timeline_events", "workflow_approvals", "workflow_executions",
             "workflow_failures"}
WRITABLE_CHILDREN = [t for t in CHILDREN if t not in READ_ONLY]
WRITABLE = ["engagements", *WRITABLE_CHILDREN]
NULLABLE_PARENT = {"customer_payment_events", "onboarding_tasks"}          # a row with no parent stays open to the firm
ABSENT_FROM_PRODUCTION = ("notes_to_accounts", "year_end_checklists", "year_end_reviews")
# a second row a child MAY name (the column is nullable): the policy asks it too when it is set
OPTIONAL_LINKS = {
    "recurring_journal_runs": ("journal_entries", "journal_entry_id"),
    "recurring_purchase_bill_runs": ("purchase_bills", "purchase_bill_id"),
    "notes_to_accounts": ("financial_statement_versions", "version_id"),
}
ALL_TABLES = ["engagements", *CHILDREN]
POLICIES = {"engagements": ["engagements_assignment_scope", "engagements_internal_partner_only"]}
POLICIES.update({t: [f"{t}_parent_visible"] for t in CHILDREN})
# parents that carry the internal practice's Partner-only guard: a child of one of these only follows a parent that hides the
# practice's rows from a member assigned to it. Since migration 537 (POST-A-306) every parent of a child here does, so every
# table of this file is checked for it.
GUARDED_PARENTS = {"engagements", "credit_notes", "client_sales_invoices", "purchase_bills", "customer_payments", "documents",
                   "year_end_engagements", "debit_notes", "purchase_credit_notes", "sales_debit_notes", "onboarding_workflows",
                   "tasks", "recurring_journal_templates", "recurring_purchase_bill_templates", "workflow_instances", "itr_filings"}
PRACTICE_TABLES = ["engagements"] + [t for t, ps in CHILDREN.items() if all(p in GUARDED_PARENTS for p, _c in ps)]

# the rows of the parents, as SQL literals. `n` is 1 for the seeded row and 2 for the row a person under test inserts, so a
# unique key never refuses an insert for the wrong reason; `r` holds the ids already made for the same tag.
PARENT_ORDER = ["client_sales_invoices", "purchase_bills", "credit_notes", "debit_notes", "purchase_credit_notes",
                "sales_debit_notes", "customer_payments", "documents", "itr_filings", "year_end_engagements",
                "onboarding_workflows", "recurring_journal_templates", "recurring_purchase_bill_templates",
                "workflow_instances", "tasks", "engagements", "journal_entries", "financial_statement_versions"]


def _parent_cols(table: str, n: int, tag: str, r: dict) -> dict:
    cust, vend = r.get("customer"), r.get("vendor")
    return {
        "client_sales_invoices": {"customer_id": _q(cust), "invoice_no": _q(f"INV-{n}-{tag}"), "invoice_date": "'2026-04-01'"},
        "purchase_bills": {"vendor_id": _q(vend), "bill_date": "'2026-04-01'"},
        "credit_notes": {"customer_id": _q(cust), "credit_note_no": _q(f"CN-{n}-{tag}"), "credit_note_date": "'2026-04-01'"},
        "debit_notes": {"vendor_id": _q(vend), "debit_note_no": _q(f"DN-{n}-{tag}"), "debit_note_date": "'2026-04-01'"},
        "purchase_credit_notes": {"vendor_id": _q(vend), "credit_note_no": _q(f"PCN-{n}-{tag}"), "credit_note_date": "'2026-04-01'"},
        "sales_debit_notes": {"customer_id": _q(cust), "debit_note_no": _q(f"SDN-{n}-{tag}"), "debit_note_date": "'2026-04-01'"},
        "customer_payments": {"customer_id": _q(cust), "invoice_id": _q(r.get("client_sales_invoices")), "amount_paise": "100",
                              "provider": "'razorpay'"},
        "documents": {"document_type": "'FORM16'", "file_name": _q(f"d-{tag}.pdf"), "file_path": _q(f"/d-{tag}.pdf")},
        "itr_filings": {"financial_year": "'2025-26'", "assessment_year": "'2026-27'", "itr_form": "'ITR-1'",
                        "created_by": _q(PARTNER_ID)},
        "year_end_engagements": {"financial_year": "'2025-26'", "fy_start": "'2025-04-01'", "fy_end": "'2026-03-31'",
                                 "created_by": _q(PARTNER_ID)},
        "onboarding_workflows": {},
        "recurring_journal_templates": {"name": _q(f"rj-{tag}"), "frequency": "'monthly'", "start_date": "'2026-04-01'",
                                        "next_run_date": "'2026-05-01'"},
        "recurring_purchase_bill_templates": {"vendor_id": _q(vend), "title": _q(f"rp-{tag}"), "frequency": "'monthly'",
                                              "start_date": "'2026-04-01'", "next_run_date": "'2026-05-01'"},
        "workflow_instances": {"template_id": _q(r.get("workflow_template")), "trigger_event": "'x'"},
        "tasks": {"title": _q(f"task-{tag}")},
        "engagements": {"engagement_number": _q(f"EL-{n}-{tag}"), "title": _q(f"Letter {tag}")},
        "journal_entries": {"entry_date": "'2026-04-01'", "narration": _q(f"je-{tag}"), "entry_type": "'Journal'"},
        "financial_statement_versions": {"engagement_id": _q(r.get("year_end_engagements")), "statement_data": "'{}'",
                                         "trial_balance_hash": _q(f"h-{tag}"), "created_by": _q(PARTNER_ID),
                                         "financial_year": "'2025-26'"},
    }[table]


# the columns of a child other than the firm and the row(s) it hangs from, as SQL literals
def _child_cols(table: str, n: int) -> dict:
    return {
        "engagement_events": {"event_type": "'created'"},
        "credit_note_allocations": {"allocated_paise": "100"},
        "debit_note_allocations": {"allocated_paise": "100"},
        "purchase_credit_note_allocations": {"allocated_paise": "100"},
        "sales_debit_note_allocations": {"allocated_paise": "100"},
        "customer_payment_events": {"provider": "'razorpay'"},
        "document_extractions": {},
        "itr_filing_versions": {"version": str(n), "created_by": _q(PARTNER_ID)},
        "notes_to_accounts": {"note_type": "'custom'", "note_number": str(n), "title": "'t'", "content_data": "'{}'",
                              "created_by": _q(PARTNER_ID)},
        "onboarding_tasks": {"task_name": _q(f"t{n}")},
        "recurring_journal_runs": {"occurrence_date": f"'2026-0{4 + n}-01'"},
        "recurring_purchase_bill_runs": {"occurrence_date": f"'2026-0{4 + n}-01'"},
        "workflow_approvals": {"approver_role": "'Partner'", "title": "'t'"},
        "workflow_executions": {"event_type": "'x'"},
        "workflow_failures": {"error_type": "'x'", "error_message": "'x'"},
        "year_end_checklist_items": {"category": "'c'", "item_code": _q(f"i{n}"), "item_label": "'l'"},
        "year_end_checklists": {"category": "'c'", "item_code": _q(f"i{n}"), "item_label": "'l'", "status": "'pending'"},
        "year_end_reviews": {"reviewed_by": _q(PARTNER_ID), "review_type": "'prepared'", "action": "'submitted'"},
        "task_tags": {"tag": _q(f"tag{n}")},
        "task_timeline_events": {"event_type": "'x'"},
    }[table]


def _insert(table: str, cols: dict) -> str:
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(cols.values())})"


def _child_insert(table: str, parents: dict, n: int = 2, link=None) -> str:
    """The INSERT of a child naming the given row for each of its parents (a missing key is a NULL parent), and `link` as the
    optional second row of the three children that may name one."""
    cols = {"firm_id": _F}
    for parent, fk in CHILDREN[table]:
        cols[fk] = _q(parents.get(parent))
    if link is not None:
        cols[OPTIONAL_LINKS[table][1]] = _q(link)
    cols.update(_child_cols(table, n))
    return _insert(table, cols)


def _expected_reads(table: str) -> dict:
    # the lead's letter, the event on it, the payment event with no payment and the task with no workflow have no client
    # and are open to the firm
    if table == "engagements" or table in NULLABLE_PARENT or table == "engagement_events":
        return {"partner": 4, "manager_a": 2, "manager_none": 1, "executive_a": 2, "suspended": 0, "other_firm": 0}
    return {"partner": 3, "manager_a": 1, "manager_none": 0, "executive_a": 1, "suspended": 0, "other_firm": 0}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-1", "-f", str(path)], capture_output=True, text=True)


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


class World:
    """The dsn of a throwaway database and the id of every row seeded into it: `ids[table][tag]` with tag A, B, I (the
    internal practice) or N (no client / no parent)."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.ids: dict[str, dict[str, str]] = {}

    def one(self, sql: str) -> str:
        return _rows(self.dsn, sql)[0][0]

    def put(self, table: str, tag: str, cols: dict) -> str:
        sql = "SET session_replication_role = replica; " + _insert(table, cols) + " RETURNING id;"
        got = [line for line in _rows(self.dsn, sql) if re.fullmatch(r"[0-9a-f-]{36}", line[0])]
        assert got, f"no id back from the seed of {table}/{tag}"
        self.ids.setdefault(table, {})[tag] = got[0][0]
        return got[0][0]

    def row(self, table: str, tag: str) -> str:
        return self.ids[table][tag]

    def parents(self, table: str, tag: str) -> dict:
        return {p: self.ids[p][tag] for p, _fk in CHILDREN[table] if tag in self.ids.get(p, {})}


def _seed(w: World) -> None:
    for tag, client in CLIENTS.items():
        r = {"customer": w.one(f"SELECT id FROM customers WHERE client_id = '{client}'"), "tag": tag,
             "workflow_template": w.one(f"SELECT id FROM workflow_templates WHERE firm_id = '{FIRM}'")}
        r["vendor"] = w.put("vendors", tag, {"firm_id": _F, "client_id": _q(client), "name": _q(f"vendor {tag}")})
        for table in PARENT_ORDER:
            cols = {"firm_id": _F, "client_id": _q(client), **_parent_cols(table, 1, tag, r)}
            r[table] = w.put(table, tag, cols)
        # a second invoice and a second bill of the same client: the SEEDED allocations name these, so that the row a person
        # under test inserts (the first invoice, the first bill) never meets the seed on the pair's unique key
        for table in ("client_sales_invoices", "purchase_bills"):
            cols = {"firm_id": _F, "client_id": _q(client), **_parent_cols(table, 1, tag + "2", r)}
            w.put(table, tag + "2", cols)
        for table in CHILDREN:
            parents = w.parents(table, tag)
            cols = {"firm_id": _F}
            for index, (parent, fk) in enumerate(CHILDREN[table]):
                second = index == 1
                cols[fk] = _q(w.ids[parent][tag + "2"] if second else parents[parent])
            cols.update(_child_cols(table, 1))
            w.put(table, tag, cols)
    # the rows with no client or no parent
    lead = w.put("engagements", "N", {"firm_id": _F, "client_id": "NULL", **_parent_cols("engagements", 1, "N", {})})
    w.put("engagement_events", "N", {"firm_id": _F, "engagement_id": _q(lead), **_child_cols("engagement_events", 1)})
    for table in sorted(NULLABLE_PARENT):
        (_parent, fk), = CHILDREN[table]
        w.put(table, "N", {"firm_id": _F, fk: "NULL", **_child_cols(table, 1)})


@pytest.fixture(scope="module")
def seeded(pg_template):
    """One database, seeded once for the module: the firm, its people, three clients and a row of each table for each of them.
    Every test works in a CLONE of it (`CREATE DATABASE ... TEMPLATE`), so a test that changes things changes its own copy, and
    the hundred and thirty statements of the seed are not run again for each of the hundred and fifty tests."""
    admin = _ADMIN.strip()
    name = f"e529s_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create the seeded database")
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
            INSERT INTO customers (firm_id, client_id, name)
                 VALUES ('{FIRM}', '{CLIENT_A}', 'cust A'), ('{FIRM}', '{CLIENT_B}', 'cust B'), ('{FIRM}', '{INTERNAL}', 'cust I');
            INSERT INTO workflow_templates (firm_id, name, trigger_type) VALUES ('{FIRM}', 'wf', 'manual');
        """)
        assert seed.returncode == 0, seed.stderr
        w = World(d)
        _seed(w)
        # Migration 551 (POST-A-339) is the FIRST lock on `document_extractions` (no signed-in privilege at all); this module
        # measures the SECOND (the parent scope in the policy), so the privilege it took is given back in this throwaway database.
        give_the_signed_in_document_access_back(d)
        yield name, w.ids
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def world(seeded):
    template, ids = seeded
    admin = _ADMIN.strip()
    name = f"e529_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{template}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        w = World(f"{admin} dbname={name}")
        w.ids = {table: dict(rows) for table, rows in ids.items()}
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── WHAT A SIGNED-IN SESSION CAN WRITE ──────────────────────────────────────────

def test_the_tables_a_signed_in_session_cannot_write_are_the_ones_this_file_says(world):
    """The write proof below covers the tables the `authenticated` role is granted a write on. The six that are read-only
    today are named in READ_ONLY; if a grant is added to one, this fails and the write proof must cover it, and if one of the
    others loses its write grants this fails too, so the list is not a place where a table can hide."""
    rows = _rows(world.dsn, "SELECT c.relname, (has_table_privilege('authenticated', c.oid, 'INSERT') "
                            "OR has_table_privilege('authenticated', c.oid, 'UPDATE') OR has_table_privilege('authenticated', c.oid, 'DELETE') "
                            "OR has_any_column_privilege('authenticated', c.oid, 'INSERT') OR has_any_column_privilege('authenticated', c.oid, 'UPDATE')) "
                            f"FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY(ARRAY{ALL_TABLES})")
    read_only = {name for name, writable in rows if writable == "f"}
    assert {name for name, _w in rows} == set(ALL_TABLES)
    assert read_only == READ_ONLY, f"read-only tables are now {sorted(read_only)}"


# ── THE POLICIES ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ALL_TABLES)
def test_the_policies_are_restrictive_for_all_and_ask_the_callers_clients_once_per_query(world, table):
    dsn = world.dsn
    for name in POLICIES[table]:
        got = _rows(dsn, f"""SELECT p.polpermissive, p.polcmd, regexp_replace(pg_get_expr(p.polqual, p.polrelid), '\\s+', ' ', 'g'),
                                    regexp_replace(pg_get_expr(p.polwithcheck, p.polrelid), '\\s+', ' ', 'g')
                               FROM pg_policy p WHERE p.polrelid = 'public.{table}'::regclass AND p.polname = '{name}'""")
        assert got, f"{table} has no {name} policy"
        permissive, cmd, qual, check = got[0]
        assert permissive == "f" and cmd == "*", f"{name} is not RESTRICTIVE FOR ALL: {got[0]}"
        assert qual and check, f"{name} has no USING or no WITH CHECK"
        assert qual == check, f"{name}: the WITH CHECK is not the USING (a write is judged by a different rule than a read)"
        assert "can_access_client" not in qual + check, f"{name} calls can_access_client once per row"
        for helper in ("get_my_role", "my_internal_client_id"):
            assert (qual + check).count(f"{helper}()") == (qual + check).count(f"SELECT {helper}()"), (
                f"{name}: {helper}() is asked once per row, not once per query (it must sit in a (SELECT ...)): {got[0]}")
        if name.endswith("_assignment_scope"):
            assert "my_assigned_client_ids" in qual and "my_assigned_client_ids" in check, got[0]
            assert "Partner" in qual and "Partner" in check, f"{name}: a Partner's branch is missing from the USING or the WITH CHECK"
        if name.endswith("_internal_partner_only"):
            assert "my_internal_client_id" in qual and "Partner" in qual, got[0]
            assert "my_internal_client_id" in check and "Partner" in check, f"{name}: the WITH CHECK lost the guard or the Partner branch"
            assert "client_id IS NULL" in qual and "client_id IS NULL" in check, (
                f"{name}: a letter with no client is hidden in a firm with no internal practice")
        if name.endswith("_parent_visible"):
            for parent, col in CHILDREN[table]:
                assert parent in qual and parent in check and col in qual and col in check, (
                    f"{name} does not ask for {parent} through {col}: {got[0]}")


# ── WHO SEES WHAT ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ALL_TABLES)
def test_each_person_reads_only_the_rows_of_the_clients_they_may_see(world, table):
    seen = {who: _count_as(world.dsn, who, table) for who in PEOPLE}
    assert seen == _expected_reads(table), f"{table}: {seen}"


@pytest.mark.parametrize("table", PRACTICE_TABLES)
def test_the_internal_practice_is_a_partners_even_for_a_person_assigned_to_it(world, table):
    assert _psql(world.dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                            f"VALUES ('{FIRM}', '{PEOPLE['manager_a'][0]}', '{INTERNAL}');").returncode == 0
    assert _count_as(world.dsn, "manager_a", table) == _expected_reads(table)["manager_a"], (
        f"{table}: an assignment to the internal practice opened its rows to a Manager")
    assert _count_as(world.dsn, "partner", table) == _expected_reads(table)["partner"]


# ── WHO CHANGES WHAT ────────────────────────────────────────────────────────────

def _all(world: World, tag: str, table: str) -> dict:
    return world.parents(table, tag)


@pytest.mark.parametrize("table", WRITABLE_CHILDREN)
def test_an_assigned_manager_inserts_under_their_clients_row_and_is_refused_under_another(world, table):
    dsn = world.dsn
    mine, theirs = _all(world, "A", table), _all(world, "B", table)
    assert _count_op(dsn, "manager_a", _child_insert(table, mine)) == "1", (
        f"an assigned Manager cannot add a row to {table} under their own client's row")
    assert _count_op(dsn, "manager_a", _child_insert(table, theirs)) == "err", (
        f"a row was added to {table} under a row of a client the Manager is not assigned to")
    assert _count_op(dsn, "manager_none", _child_insert(table, mine)) == "err", (
        f"a Manager assigned to nothing added a row to {table}")
    if len(CHILDREN[table]) == 2:
        # an allocation names two rows, a note and the document it is allocated against: one of them being theirs is not enough
        for i in (0, 1):
            mixed = {**mine, CHILDREN[table][i][0]: theirs[CHILDREN[table][i][0]]}
            assert _count_op(dsn, "manager_a", _child_insert(table, mixed)) == "err", (
                f"{table}: a row naming {CHILDREN[table][i][0]} of another client was added because the other row was theirs")


@pytest.mark.parametrize("table", WRITABLE_CHILDREN)
def test_an_update_cannot_move_a_row_onto_a_parent_the_person_may_not_see(world, table):
    dsn = world.dsn
    # the target's own row would collide on a unique key (a version number, an occurrence date) and refuse the move for the
    # wrong reason: take it away, as the admin, so that only a policy can refuse it
    assert _psql(dsn, f"DELETE FROM {table} WHERE id = '{world.row(table, 'B')}'").returncode == 0
    for parent, fk in CHILDREN[table]:
        target = world.row(parent, "B")
        assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {fk} = '{target}' WHERE id = '{world.row(table, 'A')}'") == "err", (
            f"an assigned Manager moved a {table} row onto another client's {parent}")
        # the same move by a Partner is allowed: it was the policy that refused the Manager, not a key or a check
        assert _count_op(dsn, "partner", f"UPDATE {table} SET {fk} = '{target}' WHERE id = '{world.row(table, 'A')}'") == "1", (
            f"a Partner cannot move a {table} row onto another client's {parent}")


@pytest.mark.parametrize("table", WRITABLE)
def test_an_update_or_a_delete_of_another_clients_row_matches_nothing_and_of_their_own_matches(world, table):
    dsn = world.dsn
    own, other = world.row(table, "A"), world.row(table, "B")
    touch = "firm_id = firm_id"      # an update that changes nothing is still judged by the policy's USING and WITH CHECK
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE id = '{other}'") == "0", f"updated another client's {table} row"
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{other}'") == "0", f"deleted another client's {table} row"
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {touch} WHERE id = '{own}'") == "1", f"cannot update their own client's {table} row"
    assert _count_op(dsn, "manager_a", f"DELETE FROM {table} WHERE id = '{own}'") == "1", f"cannot delete their own client's {table} row"
    assert _count_op(dsn, "manager_none", f"DELETE FROM {table} WHERE id = '{own}'") == "0", "a person assigned to nothing deleted a row"
    assert _count_op(dsn, "manager_none", f"UPDATE {table} SET {touch} WHERE id = '{own}'") == "0", "a person assigned to nothing updated a row"
    assert _count_op(dsn, "partner", f"DELETE FROM {table} WHERE id = '{other}'") == "1", f"a Partner cannot delete a client's {table} row"


@pytest.mark.parametrize("table", WRITABLE_CHILDREN)
def test_a_partner_inserts_under_every_clients_row_the_internal_practice_included(world, table):
    """The WITH CHECK reads the parent as the caller, so a Partner is admitted by the parent's own Partner branch: a slip that
    asked for a role in the child's policy would lock the owner out of adding a row to every client but the first."""
    for tag in ("A", "B", "I"):
        assert _count_op(world.dsn, "partner", _child_insert(table, _all(world, tag, table))) == "1", (
            f"a Partner cannot add a {table} row under {tag}'s row")


TWO_PARENTS = [t for t, ps in CHILDREN.items() if len(ps) == 2]


@pytest.mark.parametrize("table", TWO_PARENTS)
def test_an_allocation_naming_a_row_of_two_clients_is_seen_only_by_someone_who_may_see_both(world, table):
    """The seeded allocations name two rows of ONE client, so reading them cannot tell a policy that asks for one of its two
    parents from a policy that asks for both. Two rows made by the admin that each name a row of client A and a row of client
    B (a state the API never writes, which is why it is the one to test): a Partner reads both, and a person assigned to A
    reads neither, whichever of the two parents is the one that is theirs. This is the proof for the read-only
    `credit_note_allocations`, whose writes cannot be tried."""
    (first, fk1), (second, fk2) = CHILDREN[table]
    mixed = []
    for one, other in ((world.row(first, "A"), world.row(second, "B")), (world.row(first, "B"), world.row(second, "A"))):
        cols = {"firm_id": _F, fk1: _q(one), fk2: _q(other), **_child_cols(table, 3)}
        mixed.append(world.put(table, f"mixed{len(mixed)}", cols))
    ids = ", ".join(f"'{m}'" for m in mixed)
    seen = {who: int(_lines_as(world.dsn, who, f"SELECT count(*) FROM {table} WHERE id IN ({ids});")[-1])
            for who in ("partner", "manager_a", "executive_a", "manager_none")}
    assert seen == {"partner": 2, "manager_a": 0, "executive_a": 0, "manager_none": 0}, f"{table}: {seen}"


@pytest.mark.parametrize("table", list(OPTIONAL_LINKS))
def test_a_row_that_names_an_optional_second_row_of_another_client_is_refused(world, table):
    """A recurring-journal run may name its journal entry, a recurring-bill run its bill and a note to the accounts its
    statement version. Written under the Manager's own template, naming another client's row would have been accepted (and an
    id that exists answered differently from one that does not, which tells a person which ids are real): the policy asks that
    row too when the column is set. The same statements by a Partner succeed, so it is the policy that refused them."""
    dsn = world.dsn
    link_table, column = OPTIONAL_LINKS[table]
    mine, own, theirs = _all(world, "A", table), world.row(link_table, "A"), world.row(link_table, "B")
    assert _count_op(dsn, "manager_a", _child_insert(table, mine)) == "1", "no second row at all is refused"
    assert _count_op(dsn, "manager_a", _child_insert(table, mine, link=own)) == "1", "the Manager's own second row is refused"
    assert _count_op(dsn, "manager_a", _child_insert(table, mine, link=theirs)) == "err", (
        f"{table}: a row was written naming another client's {link_table} row")
    assert _count_op(dsn, "partner", _child_insert(table, mine, link=theirs)) == "1"
    seeded = world.row(table, "A")
    assert _count_op(dsn, "manager_a", f"UPDATE {table} SET {column} = '{theirs}' WHERE id = '{seeded}'") == "err", (
        f"{table}: a row was pointed at another client's {link_table} row")
    assert _count_op(dsn, "partner", f"UPDATE {table} SET {column} = '{theirs}' WHERE id = '{seeded}'") == "1"


@pytest.mark.parametrize("table", list(OPTIONAL_LINKS))
def test_a_row_naming_a_second_row_of_another_client_is_seen_only_by_someone_who_may_see_both(world, table):
    """The seeded rows name none, so reading them cannot tell a policy that asks the second row from one that does not. Two
    rows made by the admin, each under one client's parent and naming the other client's second row: a Partner reads both and
    a person assigned to A reads neither."""
    link_table, column = OPTIONAL_LINKS[table]
    ids = []
    for first, second in (("A", "B"), ("B", "A")):
        parents = world.parents(table, first)
        cols = {"firm_id": _F, column: _q(world.row(link_table, second))}
        for parent, fk in CHILDREN[table]:
            cols[fk] = _q(parents[parent])
        cols.update(_child_cols(table, 3))
        ids.append(world.put(table, f"linked{len(ids)}", cols))
    where = ", ".join(f"'{i}'" for i in ids)
    seen = {who: int(_lines_as(world.dsn, who, f"SELECT count(*) FROM {table} WHERE id IN ({where});")[-1])
            for who in ("partner", "manager_a", "executive_a", "manager_none")}
    assert seen == {"partner": 2, "manager_a": 0, "executive_a": 0, "manager_none": 0}, f"{table}: {seen}"


def test_a_childs_policy_reads_every_client_table_it_points_at(world):
    """The catalog rule calls a child covered when its policy reads ANY client table, so a child with two links to client rows
    is held only as far as the second one is asked about. This is the other half: every foreign key a child has to a table
    with a `client_id` is a table its `_parent_visible` policy reads (from pg_depend, not from its text), so a link added to
    one of the twenty tables later makes this fail until the policy asks it too."""
    pointed = _rows(world.dsn, f"""
        SELECT DISTINCT c.relname, regexp_replace(f.confrelid::regclass::text, '^public\\.', '')
          FROM pg_constraint f JOIN pg_class c ON c.oid = f.conrelid
         WHERE f.contype = 'f' AND c.relnamespace = 'public'::regnamespace AND c.relname = ANY(ARRAY{list(CHILDREN)})
           AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = f.confrelid AND a.attname = 'client_id' AND NOT a.attisdropped)""")
    read = {tuple(r) for r in _rows(world.dsn, f"""
        SELECT DISTINCT c.relname, regexp_replace(d.refobjid::regclass::text, '^public\\.', '')
          FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
          JOIN pg_depend d ON d.classid = 'pg_policy'::regclass AND d.objid = p.oid AND d.refclassid = 'pg_class'::regclass
                          AND d.refobjid <> c.oid
         WHERE p.polname = c.relname || '_parent_visible' AND c.relname = ANY(ARRAY{list(CHILDREN)})""")}
    assert pointed, "the scan found no foreign keys: it reads nothing"
    missing = sorted(tuple(r) for r in pointed if tuple(r) not in read)
    assert not missing, f"a child points at a client table its _parent_visible policy does not read: {missing}"


# ── THE LETTERS ─────────────────────────────────────────────────────────────────

def _letter(n: int, client, tag: str = "x") -> str:
    return _insert("engagements", {"firm_id": _F, "client_id": _q(client), **_parent_cols("engagements", n, tag, {})})


def test_an_assigned_manager_raises_a_letter_for_their_client_or_for_a_lead_and_not_for_another_client(world):
    dsn = world.dsn
    assert _count_op(dsn, "manager_a", _letter(2, CLIENT_A, "m1")) == "1"
    assert _count_op(dsn, "manager_a", _letter(2, CLIENT_B, "m2")) == "err", "a letter was raised for a client the Manager is not assigned to"
    assert _count_op(dsn, "manager_a", _letter(2, None, "m3")) == "1", "a Manager cannot raise a letter for a lead"
    assert _count_op(dsn, "manager_none", _letter(2, CLIENT_A, "m4")) == "err"
    assert _count_op(dsn, "manager_none", _letter(2, None, "m5")) == "1", "a Manager assigned to nothing cannot raise a letter for a lead"
    for tag, client in (("a", CLIENT_A), ("b", CLIENT_B), ("i", INTERNAL)):
        assert _count_op(dsn, "partner", _letter(2, client, f"p{tag}")) == "1", f"a Partner cannot raise a letter for {tag}"


def test_an_update_cannot_move_a_letter_to_a_client_the_person_may_not_see_and_a_partner_may(world):
    dsn = world.dsn
    own = world.row("engagements", "A")
    assert _count_op(dsn, "manager_a", f"UPDATE engagements SET client_id = '{CLIENT_B}' WHERE id = '{own}'") == "err"
    assert _count_op(dsn, "manager_a", f"UPDATE engagements SET client_id = '{INTERNAL}' WHERE id = '{own}'") == "err"
    assert _count_op(dsn, "partner", f"UPDATE engagements SET client_id = '{CLIENT_B}' WHERE id = '{own}'") == "1"
    assert _count_op(dsn, "partner", f"UPDATE engagements SET client_id = '{INTERNAL}' WHERE id = '{own}'") == "1"
    # a person who cannot see a client's letter cannot give it no client
    assert _count_op(dsn, "manager_none", f"UPDATE engagements SET client_id = NULL WHERE id = '{own}'") == "0"


def test_a_person_assigned_to_the_practice_is_still_refused_its_letters_by_the_guard_alone(world):
    """The WITH CHECK of the internal-practice guard, exercised by someone who is not a Partner: they are assigned to the
    practice, so the assignment scope admits its client to them, and only the guard can refuse the insert."""
    dsn = world.dsn
    assert _psql(dsn, f"INSERT INTO user_client_assignments (firm_id, user_id, client_id) "
                      f"VALUES ('{FIRM}', '{PEOPLE['manager_a'][0]}', '{INTERNAL}');").returncode == 0
    assert _count_op(dsn, "manager_a", _letter(2, INTERNAL, "g1")) == "err", "a Manager assigned to the practice raised a letter for it"
    assert _count_op(dsn, "manager_a", f"UPDATE engagements SET client_id = '{INTERNAL}' WHERE id = '{world.row('engagements', 'A')}'") == "err"
    assert _count_op(dsn, "manager_a", _letter(2, CLIENT_A, "g2")) == "1", "the guard refused a letter of the Manager's own client"
    assert _count_op(dsn, "partner", _letter(2, INTERNAL, "g3")) == "1", "the guard refused a Partner"


@pytest.mark.parametrize("table", ["engagements", "engagement_events"])
def test_a_letter_with_no_client_is_open_to_the_firm_where_no_internal_practice_is_set_up(world, table):
    """A firm whose onboarding never provisioned its internal practice has `firms.internal_client_id` NULL (migration 405
    measured one of two firms in that state). The guard compares the row's client with it, and NULL IS DISTINCT FROM NULL is
    FALSE, so a guard without `client_id IS NULL OR` hid every lead's letter from, and refused it to, every non-Partner of
    that firm. The fixture sets the practice; this is the other state."""
    dsn = world.dsn
    assert _psql(dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    assert {who: _count_as(dsn, who, table) for who in ("partner", "manager_a", "manager_none", "executive_a")} == {
        "partner": 4, "manager_a": 2, "manager_none": 1, "executive_a": 2}, f"{table}: the letter with no client is not open to the firm"


def test_a_manager_can_raise_a_letter_for_a_lead_where_no_internal_practice_is_set_up(world):
    assert _psql(world.dsn, f"UPDATE firms SET internal_client_id = NULL WHERE id = '{FIRM}'").returncode == 0
    for who in ("manager_a", "manager_none"):
        assert _count_op(world.dsn, who, _letter(2, None, "u1")) == "1", f"{who} cannot raise a lead's letter in a firm with no internal practice"
    # the letters of a client stay behind the assignment scope in that state, and the guard has not widened them
    assert _count_op(world.dsn, "manager_none", _letter(2, CLIENT_A, "u2")) == "err"


def test_an_event_on_the_leads_letter_is_added_by_anyone_in_the_firm_and_on_a_clients_letter_only_by_those_assigned(world):
    dsn = world.dsn
    lead = {"engagements": world.row("engagements", "N")}
    assert _count_op(dsn, "manager_none", _child_insert("engagement_events", lead)) == "1"
    assert _count_op(dsn, "manager_none", _child_insert("engagement_events", _all(world, "A", "engagement_events"))) == "err"
    assert _count_op(dsn, "manager_a", _child_insert("engagement_events", _all(world, "A", "engagement_events"))) == "1"


# ── A ROW WITH NO PARENT ────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", sorted(NULLABLE_PARENT))
def test_a_row_with_no_parent_stays_open_to_the_firm_and_is_added_by_anyone_in_it(world, table):
    """`customer_payment_events.payment_id` and `onboarding_tasks.workflow_id` may be NULL (an event before it is matched to a
    payment, a task before it is put on a workflow). Such a row names no client, so it is the firm's, as it was."""
    dsn = world.dsn
    assert _count_as(dsn, "manager_none", table) == 1
    assert _count_op(dsn, "manager_none", _child_insert(table, {})) == "1", f"{table}: a row with no parent cannot be added"
    assert _count_op(dsn, "manager_none", _child_insert(table, _all(world, "A", table))) == "err", (
        f"{table}: a person assigned to nothing added a row under a client's row")


# ── THE THREE TABLES PRODUCTION DOES NOT HAVE ───────────────────────────────────

def test_the_migration_applies_and_rolls_back_on_a_database_without_the_three_year_end_tables(world):
    """`notes_to_accounts`, `year_end_checklists` and `year_end_reviews` are in a database built from the migrations and not in
    production: the policy is created only where the table exists, and the rest of the migration is not skipped."""
    dsn = world.dsn
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    for table in ABSENT_FROM_PRODUCTION:
        assert _psql(dsn, f"DROP TABLE {table} CASCADE").returncode == 0
    applied = _psql_file(dsn, MIGRATION)
    assert applied.returncode == 0, applied.stderr
    have = {row[0] for row in _rows(dsn, "SELECT polname FROM pg_policy WHERE polname LIKE '%_parent_visible' "
                                         "OR polname LIKE 'engagements_%'")}
    assert {n for names in POLICIES.values() for n in names if not any(n.startswith(t) for t in ABSENT_FROM_PRODUCTION)} <= have
    assert not any(n.startswith(t) for n in have for t in ABSENT_FROM_PRODUCTION)
    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr


# ── THE ROLLBACK, AND THE PLAN ──────────────────────────────────────────────────

def test_the_rollback_returns_the_firm_wide_read_and_a_reapply_hides_the_rows_again(world):
    dsn = world.dsn
    before = {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in ALL_TABLES}
    assert all(v["manager_none"] == _expected_reads(t)["manager_none"] for t, v in before.items()), before

    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    for table in ALL_TABLES:
        assert _count_as(dsn, "manager_none", table) == _expected_reads(table)["partner"], (
            f"after the rollback {table} is not firm-wide again")
        assert not _rows(dsn, f"SELECT 1 FROM pg_policy WHERE polrelid = 'public.{table}'::regclass "
                              f"AND polname = ANY(ARRAY{POLICIES[table]})")

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert {t: {who: _count_as(dsn, who, t) for who in ("manager_none", "manager_a")} for t in ALL_TABLES} == before


def test_a_second_run_of_the_migration_changes_nothing(world):
    def snapshot() -> list:
        return _rows(world.dsn, "SELECT c.relname, p.polname, p.polpermissive, p.polcmd, pg_get_expr(p.polqual, p.polrelid), "
                                "pg_get_expr(p.polwithcheck, p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                                f"WHERE c.relname = ANY(ARRAY{ALL_TABLES}) ORDER BY 1, 2")
    first = snapshot()
    assert _psql_file(world.dsn, MIGRATION).returncode == 0
    assert snapshot() == first


@pytest.mark.parametrize("table", ALL_TABLES)
def test_a_signed_in_scan_asks_the_callers_clients_once(world, table):
    plan = "\n".join(_lines_as(world.dsn, "manager_a", f"EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM {table};"))
    assert "can_access_client" not in plan, plan
    if table == "engagements":
        assert re.search(r"hashed SubPlan \d+", plan) and "my_assigned_client_ids()" in plan, plan
    else:       # a child with no client of its own reads its parent, which asks the set
        assert "SubPlan" in plan, plan
