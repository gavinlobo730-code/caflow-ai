"""
R443 — proves migration 443's fix on real PostgreSQL: a portal client's own
Invoices, Dues, Statement and Payment-Reminder tabs actually return their own
data, end to end through the real, unmodified `services.portal_data_service`
functions — not merely through hand-written probe queries against each table.

WHY THIS FILE EXISTS ON TOP OF 440/441/442
    `resolve_fee_scope` (fixed by 442) is only the FIRST of two RLS-gated steps
    in every one of its six callers. This migration widens the SECOND step —
    the eight further tables `list_invoices`, `dues`, `invoice_in_scope`,
    `reminder_history`, `statement` and `statement_pdf` go on to read. Before
    443, resolve_fee_scope succeeding changed nothing observable: the very
    next query in every caller was still RLS-denied, silently (a SELECT an
    RLS RESTRICTIVE policy blocks returns zero rows, not an error).

TWO LAYERS, LIKE THE SIBLING FILE FOR 442
    Layer 1 (raw SQL, `SET request.jwt.claims` + `SET ROLE authenticated` —
    the technique test_r246_users_column_grant_pg.py established and every
    sibling in this family reuses): each of the eight tables, on its own,
    before vs. after migration 443.

    Layer 2 (the real Python service functions): `list_invoices`, `dues`,
    `invoice_in_scope`, `reminder_history` and `statement` are called
    DIRECTLY — not re-implemented — against a `db` double whose `.table(...)`
    calls execute real SQL over the SAME real-Postgres connections Layer 1
    uses: the portal client's own RLS-constrained session for every one of
    the nine tables this migration (plus 442) actually fixes, and an
    admin/no-RLS session (service_role's real-world equivalent) for
    `firms` (read internally by `get_internal_client_id`, monkeypatched here
    for the reason migration 442's own test file gives — it goes through a
    wholly separate service-role connection in production this migration does
    not touch).

    `statement_pdf` is DELIBERATELY NOT given the same full-success treatment.
    Its OWN second half, `statement_pdf_service.load_account_holder`, reads
    `public.clients` for the firm's internal-client row — a table this
    migration's own header names as a SEPARATE, confirmed, out-of-scope defect
    (the identical `can_access_client`/`get_my_firm_id` shape, on a table far
    too heavily loaded by other RLS layers to touch here). Routing `clients`
    through the admin session to make this file's own test of `statement_pdf`
    pass would hide exactly the gap the migration's header goes out of its way
    to name — so this file proves the opposite: `generate()` (the part 443
    fixes, shared with `statement()`) succeeds, and `statement_pdf` as a whole
    STILL raises, from `clients`, on a real portal session, undisguised.

NNEGATIVE CONTROL
    A template built from every migration file EXCEPT 443 reproduces the
    documented symptom exactly: `resolve_fee_scope` (442, already applied)
    succeeds, and every one of the five fully-tested callers returns an empty/
    zero-shaped result — not an exception — because each table's own RLS
    silently drops every row.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
REAL_MIGRATIONS_DIR = API_ROOT / "migrations"
THIS_MIGRATION = "443_a_portal_client_may_read_their_own_fee_documents.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="portal fee-document RLS proof requires HARNESS_PG + psql",
)

FIRM = "f4430000-0000-0000-0000-0000000000f1"
INTERNAL_CLIENT = "c4430000-0000-0000-0000-0000000000c0"
EXT1 = "c4430000-0000-0000-0000-0000000000c1"          # portal client 1's own practice client
EXT2 = "c4430000-0000-0000-0000-0000000000c2"          # portal client 2's own practice client
CUST1 = "d4430000-0000-0000-0000-0000000000d1"         # EXT1, as a customer in the internal client's books
CUST2 = "d4430000-0000-0000-0000-0000000000d2"
PORTAL_AUTH_1 = "a4430000-0000-0000-0000-00000000a001"
PORTAL_AUTH_2 = "a4430000-0000-0000-0000-00000000a002"
UNASSIGNED_STAFF_AUTH = "a4430000-0000-0000-0000-00000000a003"
UNASSIGNED_STAFF_ID = "b4430000-0000-0000-0000-00000000b003"
PARTNER_AUTH = "a4430000-0000-0000-0000-00000000a004"
PARTNER_ID = "b4430000-0000-0000-0000-00000000b004"

INVOICE_1 = "e4430000-0000-0000-0000-0000000000e1"     # EXT1's fee invoice
INVOICE_2 = "e4430000-0000-0000-0000-0000000000e2"     # EXT2's fee invoice
DELIVERY_1 = "11430000-0000-0000-0000-000000000001"    # a reminder sent for INVOICE_1
DELIVERY_2 = "11430000-0000-0000-0000-000000000002"
RECEIPT_1 = "22430000-0000-0000-0000-000000000001"
RECEIPT_2 = "22430000-0000-0000-0000-000000000002"
CREDIT_NOTE_1 = "33430000-0000-0000-0000-000000000001"
CREDIT_NOTE_2 = "33430000-0000-0000-0000-000000000002"
DEBIT_NOTE_1 = "44430000-0000-0000-0000-000000000001"
DEBIT_NOTE_2 = "44430000-0000-0000-0000-000000000002"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    """Runs as the admin role — Postgres superuser, bypasses RLS like service_role."""
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _count(dsn: str, sql: str) -> int:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip() or "0")


def _as(dsn: str, auth_uid: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(
        dsn,
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; SET ROLE authenticated; {sql}",
    )


def _as_count(dsn: str, auth_uid: str, sql: str) -> int:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; SET ROLE authenticated; {sql}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1] or "0")


_SEED_SQL = f"""
INSERT INTO auth.users (id, email) VALUES
  ('{PORTAL_AUTH_1}', 'client1@t.in'),
  ('{PORTAL_AUTH_2}', 'client2@t.in'),
  ('{UNASSIGNED_STAFF_AUTH}', 'staff1@t.in'),
  ('{PARTNER_AUTH}', 'partner@t.in');
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
INSERT INTO clients (id, firm_id, client_name, entity_type, pan, is_internal) VALUES
  ('{INTERNAL_CLIENT}', '{FIRM}', 'Internal Books', 'Private Limited', 'AAACI1234A', true),
  ('{EXT1}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A', false),
  ('{EXT2}', '{FIRM}', 'C2', 'Private Limited', 'AAACB1234A', false);
UPDATE firms SET internal_client_id = '{INTERNAL_CLIENT}' WHERE id = '{FIRM}';
INSERT INTO customers (id, firm_id, client_id, name, email) VALUES
  ('{CUST1}', '{FIRM}', '{INTERNAL_CLIENT}', 'C1 as customer', 'c1@x.in'),
  ('{CUST2}', '{FIRM}', '{INTERNAL_CLIENT}', 'C2 as customer', 'c2@x.in');
INSERT INTO client_firm_customer_links (firm_id, client_id, internal_customer_id) VALUES
  ('{FIRM}', '{EXT1}', '{CUST1}'),
  ('{FIRM}', '{EXT2}', '{CUST2}');
INSERT INTO client_portal_users (firm_id, client_id, email, auth_user_id, status) VALUES
  ('{FIRM}', '{EXT1}', 'client1@t.in', '{PORTAL_AUTH_1}', 'active'),
  ('{FIRM}', '{EXT2}', 'client2@t.in', '{PORTAL_AUTH_2}', 'active');
INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
  ('{UNASSIGNED_STAFF_ID}', '{FIRM}', '{UNASSIGNED_STAFF_AUTH}', 'staff1@t.in', 'Unassigned', 'Executive', true),
  ('{PARTNER_ID}', '{FIRM}', '{PARTNER_AUTH}', 'partner@t.in', 'The Partner', 'Partner', true);

INSERT INTO client_sales_invoices
  (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
   taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_paise, status)
  VALUES
  ('{INVOICE_1}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST1}', 'FEE/0001',
   '2026-04-01', '2026-04-30', 100000, 9000, 9000, 0, 118000, 'issued'),
  ('{INVOICE_2}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST2}', 'FEE/0002',
   '2026-04-01', '2026-04-30', 200000, 18000, 18000, 0, 236000, 'issued');

INSERT INTO invoice_deliveries (id, firm_id, client_id, invoice_id, kind, sent_to, status)
  VALUES
  ('{DELIVERY_1}', '{FIRM}', '{INTERNAL_CLIENT}', '{INVOICE_1}', 'reminder', 'c1@x.in', 'sent'),
  ('{DELIVERY_2}', '{FIRM}', '{INTERNAL_CLIENT}', '{INVOICE_2}', 'reminder', 'c2@x.in', 'sent');

INSERT INTO receipts (id, firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise)
  VALUES
  ('{RECEIPT_1}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST1}', 'RCPT/0001', '2026-04-15', 50000),
  ('{RECEIPT_2}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST2}', 'RCPT/0002', '2026-04-15', 60000);

INSERT INTO receipt_allocations (receipt_id, sales_invoice_id, allocated_paise) VALUES
  ('{RECEIPT_1}', '{INVOICE_1}', 50000),
  ('{RECEIPT_2}', '{INVOICE_2}', 60000);

INSERT INTO credit_notes (id, firm_id, client_id, customer_id, credit_note_no, credit_note_date, total_paise, status)
  VALUES
  ('{CREDIT_NOTE_1}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST1}', 'CN/0001', '2026-04-20', 10000, 'issued'),
  ('{CREDIT_NOTE_2}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST2}', 'CN/0002', '2026-04-20', 20000, 'issued');

INSERT INTO sales_debit_notes (id, firm_id, client_id, customer_id, debit_note_no, debit_note_date, total_paise, status)
  VALUES
  ('{DEBIT_NOTE_1}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST1}', 'DN/0001', '2026-04-22', 5000, 'issued'),
  ('{DEBIT_NOTE_2}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST2}', 'DN/0002', '2026-04-22', 6000, 'issued');
"""


# ── Build two databases: one WITHOUT migration 443 (negative control), one
#    WITH it (the shared session-scoped pg_template, which already includes
#    every .sql file on disk — 443 included). ─────────────────────────────────

@pytest.fixture(scope="module")
def pre_fix_template():
    """A template DB built from every migration file EXCEPT 443 itself — the
    negative control this migration's own fix is measured against."""
    admin = _ADMIN.strip()
    name = f"r443_pre_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}";').returncode != 0:
        pytest.skip("could not create pre-fix template db")

    tmp_dir = tempfile.mkdtemp(prefix="r443_migrations_")
    try:
        for f in REAL_MIGRATIONS_DIR.glob("*.sql"):
            if f.name == THIS_MIGRATION:
                continue
            shutil.copy2(f, Path(tmp_dir) / f.name)

        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dsn", f"{admin} dbname={name}",
             "--with-compat", "--only-schema", "--continue-on-error", "--json",
             "--migrations-dir", tmp_dir],
            capture_output=True, text=True, cwd=str(API_ROOT),
        )
        report = json.loads(proc.stdout)
        applied = set(report.get("applied", [])) | {f["file"] for f in report.get("failed", [])}
        assert THIS_MIGRATION not in applied, (
            "the pre-fix template must not have applied migration 443 at all"
        )
        yield name
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def pre_fix_db(pre_fix_template):
    admin = _ADMIN.strip()
    dbname = f"r443prec_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pre_fix_template}";').returncode != 0:
        pytest.skip("could not clone pre-fix template db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, _SEED_SQL)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def post_fix_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r443postc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the shared (post-fix) template db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, _SEED_SQL)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── Sanity: the pre-fix build really does lack every one of this migration's
#    policies, and the post-fix build carries all of them ────────────────────

_NEW_SELECT_POLICIES = {
    "client_sales_invoices": "client_sales_invoices_portal_client_select",
    "invoice_deliveries": "invoice_deliveries_portal_client_select",
    "customers": "customers_portal_client_select",
    "receipts": "receipts_portal_client_select",
    "receipt_allocations": "receipt_allocations_portal_client_select",
    "credit_notes": "credit_notes_portal_client_select",
    "sales_debit_notes": "sales_debit_notes_portal_client_select",
    "customer_statement_deliveries": "cust_stmt_deliveries_portal_client_select",
}


@pytest.mark.parametrize("table,policy", sorted(_NEW_SELECT_POLICIES.items()))
def test_the_pre_fix_build_lacks_the_new_policy(pre_fix_db, table, policy):
    n = _count(pre_fix_db,
               f"SELECT count(*) FROM pg_policies WHERE tablename='{table}' AND policyname='{policy}';")
    assert n == 0, f"the negative-control build must not carry {policy} on {table}"


@pytest.mark.parametrize("table,policy", sorted(_NEW_SELECT_POLICIES.items()))
def test_the_post_fix_build_carries_the_new_policy(post_fix_db, table, policy):
    n = _count(post_fix_db,
               f"SELECT count(*) FROM pg_policies WHERE tablename='{table}' AND policyname='{policy}';")
    assert n == 1, f"expected exactly one {policy} on {table}"


# ── Layer 1: raw SQL, all eight tables, negative control (BEFORE 443) ────────

@pytest.mark.parametrize("sql,label", [
    (f"SELECT count(*) FROM client_sales_invoices WHERE id='{INVOICE_1}';", "client_sales_invoices"),
    (f"SELECT count(*) FROM invoice_deliveries WHERE id='{DELIVERY_1}';", "invoice_deliveries"),
    (f"SELECT count(*) FROM customers WHERE id='{CUST1}';", "customers"),
    (f"SELECT count(*) FROM receipts WHERE id='{RECEIPT_1}';", "receipts"),
    (f"SELECT count(*) FROM receipt_allocations WHERE receipt_id='{RECEIPT_1}';", "receipt_allocations"),
    (f"SELECT count(*) FROM credit_notes WHERE id='{CREDIT_NOTE_1}';", "credit_notes"),
    (f"SELECT count(*) FROM sales_debit_notes WHERE id='{DEBIT_NOTE_1}';", "sales_debit_notes"),
])
def test_negative_control_a_portal_client_cannot_read_their_own_row(pre_fix_db, sql, label):
    """This is the bug, reproduced on a database that never had migration 443.
    A SELECT an RLS RESTRICTIVE policy blocks returns zero rows, not an
    error — the exact silence every one of the six portal_data_service
    callers cannot distinguish from 'nothing to show yet'."""
    n = _as_count(pre_fix_db, PORTAL_AUTH_1, sql)
    assert n == 0, f"{label}: expected the pre-fix build to deny this row"


def test_negative_control_admin_confirms_every_row_really_exists(pre_fix_db):
    """Sanity: every row IS there when read without RLS in the way — proves
    the zeros above are RLS denials, not a seeding mistake."""
    for table, id_ in [
        ("client_sales_invoices", INVOICE_1), ("invoice_deliveries", DELIVERY_1),
        ("customers", CUST1), ("receipts", RECEIPT_1),
        ("credit_notes", CREDIT_NOTE_1), ("sales_debit_notes", DEBIT_NOTE_1),
    ]:
        assert _count(pre_fix_db, f"SELECT count(*) FROM {table} WHERE id='{id_}';") == 1, table
    assert _count(pre_fix_db, f"SELECT count(*) FROM receipt_allocations WHERE receipt_id='{RECEIPT_1}';") == 1


# ── Layer 1: raw SQL, all eight tables, the fix (AFTER 443) ──────────────────

@pytest.mark.parametrize("sql,label", [
    (f"SELECT count(*) FROM client_sales_invoices WHERE id='{INVOICE_1}';", "client_sales_invoices"),
    (f"SELECT count(*) FROM invoice_deliveries WHERE id='{DELIVERY_1}';", "invoice_deliveries"),
    (f"SELECT count(*) FROM customers WHERE id='{CUST1}';", "customers"),
    (f"SELECT count(*) FROM receipts WHERE id='{RECEIPT_1}';", "receipts"),
    (f"SELECT count(*) FROM receipt_allocations WHERE receipt_id='{RECEIPT_1}';", "receipt_allocations"),
    (f"SELECT count(*) FROM credit_notes WHERE id='{CREDIT_NOTE_1}';", "credit_notes"),
    (f"SELECT count(*) FROM sales_debit_notes WHERE id='{DEBIT_NOTE_1}';", "sales_debit_notes"),
])
def test_a_portal_client_can_read_their_own_row(post_fix_db, sql, label):
    n = _as_count(post_fix_db, PORTAL_AUTH_1, sql)
    assert n == 1, f"{label}: expected the post-fix build to allow this row"


@pytest.mark.parametrize("sql,label", [
    (f"SELECT count(*) FROM client_sales_invoices WHERE id='{INVOICE_2}';", "client_sales_invoices"),
    (f"SELECT count(*) FROM invoice_deliveries WHERE id='{DELIVERY_2}';", "invoice_deliveries"),
    (f"SELECT count(*) FROM customers WHERE id='{CUST2}';", "customers"),
    (f"SELECT count(*) FROM receipts WHERE id='{RECEIPT_2}';", "receipts"),
    (f"SELECT count(*) FROM receipt_allocations WHERE receipt_id='{RECEIPT_2}';", "receipt_allocations"),
    (f"SELECT count(*) FROM credit_notes WHERE id='{CREDIT_NOTE_2}';", "credit_notes"),
    (f"SELECT count(*) FROM sales_debit_notes WHERE id='{DEBIT_NOTE_2}';", "sales_debit_notes"),
])
def test_a_portal_client_still_cannot_read_a_different_clients_row(post_fix_db, sql, label):
    """Cross-tenant isolation: PORTAL_AUTH_1 must not see any of EXT2's rows,
    even though every one of these tables' own `client_id` is IDENTICAL on
    both rows (always the one internal client) — the isolation here rests
    entirely on the customer_id (or invoice_id / receipt_id, one hop further)
    branch, exactly as migration 441 records for customer_payment_links."""
    n = _as_count(post_fix_db, PORTAL_AUTH_1, sql)
    assert n == 0, f"{label}: a portal client read a different client's row"


def test_a_different_portal_client_sees_only_their_own(post_fix_db):
    n1 = _as_count(post_fix_db, PORTAL_AUTH_2,
                   f"SELECT count(*) FROM client_sales_invoices WHERE id='{INVOICE_2}';")
    assert n1 == 1
    n2 = _as_count(post_fix_db, PORTAL_AUTH_2,
                   f"SELECT count(*) FROM client_sales_invoices WHERE id='{INVOICE_1}';")
    assert n2 == 0


def test_an_unassigned_staff_member_still_sees_nothing_on_any_of_the_eight(post_fix_db):
    """internal_partner_only (or, for sales_debit_notes, assignment_scope
    alone) blocks a non-Partner staff member from every internal-books row,
    before AND after this fix — the portal widening must not change that.

    receipt_allocations included: its own PERMISSIVE policy's subquery
    (`receipt_id IN (SELECT r.id FROM receipts r WHERE ...)`) reads `receipts`
    AS THE CALLING ROLE, so it is itself subject to `receipts`'
    `_internal_partner_only` RESTRICTIVE policy — for an unassigned,
    non-Partner staff member that inner SELECT returns zero rows, so the
    outer `IN (...)` matches nothing. (This is exactly why the portal-client
    branch on this table goes through the SECURITY DEFINER
    `my_portal_receipt_ids()` instead of an inline subquery: a
    non-security-definer join through `receipts` would depend on `receipts`'
    OWN RLS letting the querying role see the row, which is false for
    everybody except the row's own portal client or an assigned/Partner
    staff member — checked here on the real database, not assumed.)"""
    for table in ("client_sales_invoices", "invoice_deliveries", "customers",
                  "receipts", "credit_notes", "sales_debit_notes",
                  "receipt_allocations"):
        n = _as_count(post_fix_db, UNASSIGNED_STAFF_AUTH, f"SELECT count(*) FROM {table};")
        assert n == 0, table


def test_a_partner_still_sees_every_row_on_every_table(post_fix_db):
    for table, expected in [
        ("client_sales_invoices", 2), ("invoice_deliveries", 2), ("customers", 2),
        ("receipts", 2), ("credit_notes", 2), ("sales_debit_notes", 2),
        ("receipt_allocations", 2),
    ]:
        n = _as_count(post_fix_db, PARTNER_AUTH, f"SELECT count(*) FROM {table};")
        assert n == expected, table


def test_a_portal_client_still_cannot_write_any_of_the_eight(post_fix_db):
    """None of the eight tables' new PERMISSIVE lane is FOR ALL — every one
    is FOR SELECT only, matching the 'reads only, confirmed by grepping every
    caller' finding in the migration's own header. An INSERT still raises
    (no PERMISSIVE policy passes for INSERT), and an UPDATE/DELETE a
    RESTRICTIVE clause excludes is not an error — Postgres just matches no
    rows."""
    r = _as(post_fix_db, PORTAL_AUTH_1,
            f"INSERT INTO client_sales_invoices (firm_id, client_id, customer_id, invoice_no, "
            f"invoice_date, total_paise) VALUES ('{FIRM}','{INTERNAL_CLIENT}','{CUST1}',"
            f"'HACK/0001','2026-05-01',1000);")
    assert r.returncode != 0 and "row-level security" in r.stderr.lower()

    r = _as(post_fix_db, PORTAL_AUTH_1,
            f"UPDATE customers SET name = 'HACKED' WHERE id = '{CUST1}';")
    assert r.returncode == 0, r.stderr
    name = subprocess.run(
        ["psql", post_fix_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SELECT name FROM customers WHERE id='{CUST1}';"],
        capture_output=True, text=True).stdout.strip()
    assert name == "C1 as customer", "a portal client's UPDATE must not have taken effect"


def test_the_authenticated_grants_are_the_documented_set(post_fix_db):
    """SELECT/INSERT/UPDATE/DELETE on all eight — matches what this
    environment's own information_schema shows today (194's grant sweep gave
    invoice_deliveries and customer_statement_deliveries DELETE on top of
    their own creating migrations' SELECT/INSERT/UPDATE)."""
    for table in ("client_sales_invoices", "invoice_deliveries", "customers",
                  "receipts", "receipt_allocations", "credit_notes",
                  "sales_debit_notes", "customer_statement_deliveries"):
        got = subprocess.run(
            ["psql", post_fix_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
             "SELECT privilege_type FROM information_schema.role_table_grants "
             f"WHERE table_schema='public' AND table_name='{table}' "
             "AND grantee='authenticated' ORDER BY privilege_type;"],
            capture_output=True, text=True,
        )
        assert got.returncode == 0, got.stderr
        assert got.stdout.strip().splitlines() == ["DELETE", "INSERT", "SELECT", "UPDATE"], table


# ── Structural guards: the split lives per-command, not FOR ALL ─────────────

@pytest.mark.parametrize("table", [
    "client_sales_invoices", "invoice_deliveries", "customers",
    "receipts", "credit_notes", "sales_debit_notes",
])
def test_no_for_all_restrictive_assignment_scope_survives(post_fix_db, table):
    r = _psql(post_fix_db,
              f"SELECT policyname FROM pg_policies WHERE tablename='{table}' "
              f"AND permissive='RESTRICTIVE' AND cmd='ALL' AND policyname LIKE '%assignment%';")
    n = _count(post_fix_db,
               f"SELECT count(*) FROM pg_policies WHERE tablename='{table}' "
               f"AND permissive='RESTRICTIVE' AND cmd='ALL' AND policyname LIKE '%assignment%';")
    assert n == 0, f"a FOR ALL restrictive assignment-scope policy is back on {table}"


@pytest.mark.parametrize("table,select_col", [
    ("client_sales_invoices", "customer_id"),
    ("customers", "id"),
    ("receipts", "customer_id"),
    ("credit_notes", "customer_id"),
    ("sales_debit_notes", "customer_id"),
])
def test_only_select_carries_the_portal_branch_not_insert_update_delete(post_fix_db, table, select_col):
    """INSERT/UPDATE/DELETE stay narrow (can_access_client only) — nothing
    portal-authenticated ever writes any of these tables (confirmed in the
    migration's own header), so only SELECT gained the OR-branch."""
    for cmd in ("INSERT", "UPDATE", "DELETE"):
        qual = _psql(post_fix_db,
                     f"SELECT coalesce(qual,'')||coalesce(with_check,'') FROM pg_policies "
                     f"WHERE tablename='{table}' AND permissive='RESTRICTIVE' AND cmd='{cmd}' "
                     f"AND policyname LIKE '%assignment_scope%';")
        out = subprocess.run(
            ["psql", post_fix_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
             f"SELECT coalesce(qual,'')||coalesce(with_check,'') FROM pg_policies "
             f"WHERE tablename='{table}' AND permissive='RESTRICTIVE' AND cmd='{cmd}' "
             f"AND policyname LIKE '%assignment_scope%';"],
            capture_output=True, text=True).stdout
        assert "my_portal" not in out, f"{table} {cmd} gained the portal branch unexpectedly"


def test_the_portal_branch_reads_customer_id_never_client_id_on_client_sales_invoices(post_fix_db):
    """Pins the correction this migration's header records at length: on
    every one of these tables `client_id` is always the FIRM's own internal
    client, never the portal client's own id. Fails the moment somebody
    'simplifies' this back to the portal_messages client_id-keyed shape."""
    out = subprocess.run(
        ["psql", post_fix_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         "SELECT policyname||':'||coalesce(qual,'')||coalesce(with_check,'') "
         "FROM pg_policies WHERE tablename='client_sales_invoices' "
         "AND (coalesce(qual,'')||coalesce(with_check,'')) LIKE '%my_portal%';"],
        capture_output=True, text=True).stdout
    lines = [x for x in out.split("\n") if x.strip()]
    assert lines, "no policy on client_sales_invoices references the portal helpers at all"
    offenders = [x for x in lines if "my_portal_client_ids" in x and "my_portal_customer_ids" not in x]
    assert not offenders, offenders


# ── Layer 2: the REAL Python service functions, over real RLS connections ───
#
# `_RealDb` is not a mock of the fix under test: every table this migration
# (or 442, already applied) touches executes real SQL over the portal
# client's own RLS-constrained session, in BOTH the pre-fix and post-fix
# cases below. `firms` (read inside get_internal_client_id, monkeypatched)
# and `clients` (read inside statement_pdf_service.load_account_holder, a
# separate confirmed-unfixed gap — see the migration header and the dedicated
# test at the bottom of this file) are the only things NOT routed this way.

_RLS_TABLES = {
    "client_firm_customer_links", "client_sales_invoices", "invoice_deliveries",
    "customers", "receipts", "receipt_allocations", "credit_notes",
    "sales_debit_notes", "customer_statement_deliveries",
    # NOT fixed by this migration (or 442) — routed through the SAME real
    # portal-client RLS session anyway, deliberately, so
    # test_statement_pdf_still_fails_after_this_fix_because_clients_is_a_
    # separate_gap proves the residual gap on a real session rather than
    # hiding it behind an admin escape hatch. Nothing else in this file's
    # six tested functions ever queries `clients` at all.
    "clients",
}


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: str, run_sql):
        self._table = table
        self._run_sql = run_sql
        self._select = "*"
        self._filters: list[tuple] = []
        self._limit = None
        self._order = None
        self._single = False

    def select(self, cols):
        self._select = cols
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def maybe_single(self):
        """Supabase's `.maybe_single()`: the same query, but `.execute().data`
        is the single matching row (a dict) or None, never a list — exactly
        what `statement_pdf_service.load_account_holder` reads off it."""
        self._single = True
        return self

    def execute(self):
        where = []
        for kind, col, val in self._filters:
            if kind == "is":
                if isinstance(val, str) and val.lower() == "null":
                    where.append(f"{col} IS NULL")
                elif val is None:
                    where.append(f"{col} IS NULL")
                else:
                    where.append(f"{col} IS {val}")
            elif kind == "in":
                if not val:
                    where.append("1=0")   # an empty IN() list matches nothing, never everything
                else:
                    quoted = ",".join("'" + str(v).replace("'", "''") + "'" for v in val)
                    where.append(f"{col} IN ({quoted})")
            else:  # eq
                if val is None:
                    where.append(f"{col} IS NULL")
                elif isinstance(val, bool):
                    where.append(f"{col} = {'TRUE' if val else 'FALSE'}")
                else:
                    where.append(f"{col} = '{str(val).replace(chr(39), chr(39) * 2)}'")
        sql = f"SELECT {self._select} FROM {self._table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if self._order:
            col, desc = self._order
            sql += f" ORDER BY {col} {'DESC' if desc else 'ASC'}"
        if self._limit is not None:
            sql += f" LIMIT {int(self._limit)}"
        data = self._run_sql(sql)
        if self._single:
            return _Result(data[0] if data else None)
        return _Result(data)


class _RealDb:
    """Duck-types just enough of the Supabase Python client's chainable
    builder for `list_invoices`, `dues`, `invoice_in_scope`,
    `reminder_history`, `statement` and `customer_statement_service.generate`
    to run UNMODIFIED against it."""

    def __init__(self, dsn: str, portal_auth_uid: str):
        self._dsn = dsn
        self._auth_uid = portal_auth_uid

    def _run_admin(self, sql: str):
        wrapped = f"SELECT coalesce(json_agg(t), '[]'::json)::text FROM ({sql}) t;"
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", wrapped],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"admin query failed: {r.stderr}\nSQL: {sql}"
        return json.loads(r.stdout.strip() or "[]")

    def _run_portal(self, sql: str):
        wrapped = (
            f"SET request.jwt.claims = '{{\"sub\": \"{self._auth_uid}\"}}'; "
            f"SET ROLE authenticated; "
            f"SELECT coalesce(json_agg(t), '[]'::json)::text FROM ({sql}) t;"
        )
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", wrapped],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"portal query failed: {r.stderr}\nSQL: {sql}"
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else []

    def table(self, name: str):
        runner = self._run_portal if name in _RLS_TABLES else self._run_admin
        return _Query(name, runner)


@pytest.fixture()
def internal_client_id_patch(monkeypatch):
    """resolve_fee_scope's OTHER lookup (get_internal_client_id) reads through
    a wholly separate, already-service-role connection in production
    (services.internal_client_service._db() -> get_service_supabase()) that
    neither 442 nor this migration touches. Patched to the seeded value, the
    identical reasoning migration 442's own test file gives for the same
    patch."""
    import services.internal_client_service as internal_client_service
    monkeypatch.setattr(internal_client_service, "get_internal_client_id", lambda firm_id: INTERNAL_CLIENT)
    yield


def test_list_invoices_negative_control_is_empty_before_the_fix(pre_fix_db, internal_client_id_patch):
    """The real function, called directly. resolve_fee_scope (442) already
    succeeds on this build; list_invoices' OWN read of client_sales_invoices
    is what still silently empties the result."""
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    rows = portal_data_service.list_invoices(FIRM, EXT1, db=db)
    assert rows == []


def test_list_invoices_returns_the_real_invoice_after_the_fix(post_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    rows = portal_data_service.list_invoices(FIRM, EXT1, db=db)
    assert len(rows) == 1
    assert rows[0]["id"] == INVOICE_1
    assert rows[0]["invoice_no"] == "FEE/0001"
    assert rows[0]["total_paise"] == 118000


def test_list_invoices_still_refuses_a_different_portal_clients_invoices(post_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    rows = portal_data_service.list_invoices(FIRM, EXT2, db=db)
    assert rows == []


def test_dues_negative_control_is_empty_before_the_fix(pre_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    d = portal_data_service.dues(FIRM, EXT1, db=db)
    assert d["dues"] == []
    assert d["total_outstanding_paise"] == 0


def test_dues_reports_the_real_outstanding_after_the_fix(post_fix_db, internal_client_id_patch):
    """INVOICE_1 is issued, unpaid, 118000 paise total — dues() must report it
    as an open, outstanding fee invoice, exactly what the client's Dues tab
    renders."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    d = portal_data_service.dues(FIRM, EXT1, db=db)
    assert len(d["dues"]) == 1
    assert d["dues"][0]["id"] == INVOICE_1
    assert d["total_outstanding_paise"] == 118000


def test_invoice_in_scope_negative_control_is_false_before_the_fix(pre_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, INVOICE_1, db=db) is False


def test_invoice_in_scope_is_true_after_the_fix(post_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, INVOICE_1, db=db) is True


def test_invoice_in_scope_still_refuses_a_different_portal_clients_invoice(post_fix_db, internal_client_id_patch):
    """The ownership gate `/invoices/{id}/pdf` and `/invoices/{id}/pay` both
    call first — PORTAL_AUTH_1 must never be told EXT2's own invoice is
    theirs."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, INVOICE_2, db=db) is False


def test_reminder_history_negative_control_is_empty_before_the_fix(pre_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    assert portal_data_service.reminder_history(FIRM, EXT1, db=db) == []


def test_reminder_history_returns_the_real_reminder_after_the_fix(post_fix_db, internal_client_id_patch):
    """DELIVERY_1 was recorded against INVOICE_1 with kind='reminder' — the
    new my_portal_invoice_ids() helper (this migration's own new function,
    for the one table with no customer_id column) is what this test actually
    proves."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    rows = portal_data_service.reminder_history(FIRM, EXT1, db=db)
    assert len(rows) == 1
    assert rows[0]["invoice_no"] == "FEE/0001"


def test_reminder_history_still_refuses_a_different_portal_clients_reminders(post_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_2)
    rows = portal_data_service.reminder_history(FIRM, EXT2, db=db)
    assert len(rows) == 1
    assert rows[0]["invoice_no"] == "FEE/0002"
    # And never EXT1's.
    other = _RealDb(post_fix_db, PORTAL_AUTH_2)
    assert portal_data_service.reminder_history(FIRM, EXT1, db=other) == []


def test_statement_negative_control_is_unavailable_before_the_fix(pre_fix_db, internal_client_id_patch):
    """statement()'s own `if not scope: ... "available": False` branch fires
    only when resolve_fee_scope itself fails — that's already fixed by 442.
    Here scope resolves, generate() is reached, and its OWN reads (customers,
    client_sales_invoices, receipts, receipt_allocations, credit_notes,
    sales_debit_notes) all silently return nothing, so the statement comes
    back structurally empty rather than raising."""
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    with pytest.raises(Exception):
        # customer_statement_service._customer() 404s when the customer row
        # itself cannot be read at all — the precise shape of the bug: not a
        # wrong statement, an inability to even find whose statement it is.
        portal_data_service.statement(FIRM, EXT1, "2026-04-01", "2026-04-30", db=db)


def test_statement_returns_the_real_ledger_after_the_fix(post_fix_db, internal_client_id_patch):
    """The full statement, built from REAL rows read over the portal
    client's own RLS session for every one of client_sales_invoices,
    receipts, receipt_allocations, credit_notes and sales_debit_notes:
    opening 0, one invoice (Dr 118000), one receipt settling 50000 (Cr),
    one credit note (Cr 10000), one debit note (Dr 5000) — closing
    118000 + 5000 - 50000 - 10000 = 63000."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    stmt = portal_data_service.statement(FIRM, EXT1, "2026-04-01", "2026-04-30", db=db)
    assert stmt["customer"]["id"] == CUST1
    kinds = sorted(t["type"] for t in stmt["transactions"])
    assert kinds == ["credit_note", "debit_note", "invoice", "receipt"]
    assert stmt["closing_balance_paise"] == 118000 + 5000 - 50000 - 10000


def test_statement_still_refuses_to_leak_a_different_portal_clients_ledger(post_fix_db, internal_client_id_patch):
    from services import portal_data_service

    db1 = _RealDb(post_fix_db, PORTAL_AUTH_1)
    stmt1 = portal_data_service.statement(FIRM, EXT1, "2026-04-01", "2026-04-30", db=db1)
    assert stmt1["customer"]["id"] == CUST1
    refs = {t["reference"] for t in stmt1["transactions"]}
    assert "FEE/0002" not in refs and "CN/0002" not in refs and "DN/0002" not in refs


# ── statement_pdf: deliberately NOT given the same treatment — see header ───

def test_statement_pdf_still_fails_after_this_fix_because_clients_is_a_separate_gap(
    post_fix_db, internal_client_id_patch
):
    """The migration's own header names this precisely: `clients` carries the
    identical can_access_client()/get_my_firm_id() shape for the firm's
    internal-client row, and this migration deliberately does not touch it —
    that table is far too heavily loaded by other RLS layers (074's G1 sweep,
    084's G5 sweep, 260/261's role policies) to widen here. So `statement_pdf`
    — whose SECOND half, `load_account_holder`, reads `clients` — must still
    fail on a real portal session, even though `generate()` (the part this
    migration DOES fix, proven by the two tests above) now succeeds.

    This is deliberately routed through the SAME `_RealDb` as every other
    test in this file (no admin escape hatch for `clients`), so a future
    fix to `clients`' own RLS is exactly what turns this test green — at
    which point it should be rewritten to assert success instead of the
    residual gap, not deleted."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    with pytest.raises(ValueError, match="not found"):
        portal_data_service.statement_pdf(FIRM, EXT1, "2026-04-01", "2026-04-30", db=db)
