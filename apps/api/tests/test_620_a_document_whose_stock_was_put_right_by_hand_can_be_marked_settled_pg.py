"""Migration 620 on a real database: a document whose stock effect the CA put right by hand can be marked settled, and the finder stops listing it (POST-A-092).

WHAT ONLY POSTGRES CAN PROVE
    The mock-mode file (`test_a_document_whose_stock_was_put_right_by_hand_can_be_marked_settled.py`) holds the service and the routes over an in-memory double.
    Here:
    * `public.documents_with_unrecorded_stock` (migration 581's body plus one condition) does not list a document that has a mark, `total` does not count it, a
      mark of ANOTHER client or ANOTHER kind of document with the same id hides nothing, taking the mark away lists the document again, and what 581 listed apart
      from marked documents is unchanged (a service line, a draft, a note that says no goods came back);
    * the table: one mark per document, a kind of the four, a reason that is not blank and not over 500 characters, a reference over 200 refused, a client of
      another firm refused by the firm check of 565, and the firm's and the client's deletion take their marks with them;
    * the privileges: no signed-in or anonymous role holds any privilege on the table, the service role holds the four verbs, and the finder is executable by the
      service role alone;
    * the migration runs twice, and its rollback puts 581's finder back (a marked document is listed again), drops the table, and applies again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")
MIGRATION = next(API_ROOT.glob("migrations/620_a_document_whose_stock_was_put_right_by_hand_can_be_marked_settled.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/620_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="requires HARNESS_PG + psql",
)

FIRM, OTHER_FIRM = "f6200000-0000-0000-0000-000000000001", "f6200000-0000-0000-0000-000000000002"
CLIENT, OTHER_CLIENT, FOREIGN_CLIENT = (f"c6200000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
GOOD = "16200000-0000-0000-0000-000000000001"
CUSTOMER, VENDOR = "e6200000-0000-0000-0000-000000000001", "d6200000-0000-0000-0000-000000000001"
USER = "a6200000-0000-0000-0000-000000000001"
TABLE = "public.stock_effect_settlements"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e620_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        _ok(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{OTHER_CLIENT}', '{FIRM}', 'B', 'Proprietorship'),
                ('{FOREIGN_CLIENT}', '{OTHER_FIRM}', 'C', 'Proprietorship');
            INSERT INTO auth.users (id, email) VALUES ('a6200000-1111-0000-0000-000000000001', 'u@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                VALUES ('{USER}', '{FIRM}', 'a6200000-1111-0000-0000-000000000001', 'u@t.in', 'Asha Rao', 'Partner', true);
            INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac)
                VALUES ('{GOOD}', '{FIRM}', '{CLIENT}', 'Good', 'good', 'Nos', '8471');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Vend');""")
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _invoice(dsn, n, *, client=CLIENT, status="issued"):
    doc = str(uuid.UUID(f"b6200000-0000-0000-0000-{n:012d}"))
    _ok(dsn, f"""INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                 VALUES ('{doc}', '{FIRM}', '{client}', '{CUSTOMER}', 'INV-{n}', '2025-06-05', 100, '{status}', 0, 0);
                 INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, quantity, service_catalogue_id) VALUES ('{doc}', 'line', 2, '{GOOD}');""")
    return doc


def _bill(dsn, n):
    doc = str(uuid.UUID(f"b6200000-0000-0000-0001-{n:012d}"))
    _ok(dsn, f"""INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, total_paise, status)
                 VALUES ('{doc}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'BILL-{n}', '2025-06-05', 100, 'received');
                 INSERT INTO purchase_bill_lines (bill_id, description, quantity, taxable_amount_paise, service_catalogue_id)
                 VALUES ('{doc}', 'line', 2, 100, '{GOOD}');""")
    return doc


def _mark(dsn, kind, doc, *, client=CLIENT, firm=FIRM, reason="Adjusted by hand", extra_cols="", extra_vals=""):
    return _psql(dsn, f"""INSERT INTO {TABLE} (firm_id, client_id, document_kind, document_id, reason, reference, settled_by, settled_by_name{extra_cols})
                          VALUES ('{firm}', '{client}', '{kind}', '{doc}', $r${reason}$r$, 'REF', '{USER}', 'Asha Rao'{extra_vals});""")


def _found(dsn) -> dict:
    out = json.loads(_val(dsn, f"SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);"))
    return {"total": out["total"], "references": sorted(d["reference"] for d in out["documents"])}


# ── the finder ───────────────────────────────────────────────────────────────

def test_a_marked_document_is_not_listed_and_is_not_counted_and_taking_the_mark_away_lists_it_again(dsn):
    a, b = _invoice(dsn, 1), _invoice(dsn, 2)
    assert _found(dsn) == {"total": 2, "references": ["INV-1", "INV-2"]}
    _ok(dsn, f"INSERT INTO {TABLE} (firm_id, client_id, document_kind, document_id, reason) VALUES ('{FIRM}', '{CLIENT}', 'sales_invoice', '{a}', 'done');")
    assert _found(dsn) == {"total": 1, "references": ["INV-2"]}, "total does not count the marked document either"
    _ok(dsn, f"DELETE FROM {TABLE} WHERE document_id = '{a}';")
    assert _found(dsn) == {"total": 2, "references": ["INV-1", "INV-2"]}
    assert b


def test_a_mark_of_another_client_or_another_kind_of_document_hides_nothing(dsn):
    doc = _invoice(dsn, 3)
    _ok(dsn, f"""INSERT INTO {TABLE} (firm_id, client_id, document_kind, document_id, reason) VALUES
                 ('{FIRM}', '{OTHER_CLIENT}', 'sales_invoice', '{doc}', 'a mark in another client naming the same id'),
                 ('{FIRM}', '{CLIENT}', 'purchase_bill', '{doc}', 'a mark of another kind naming the same id');""")
    assert _found(dsn) == {"total": 1, "references": ["INV-3"]}


def test_what_581_listed_apart_from_marked_documents_is_unchanged(dsn):
    _invoice(dsn, 4)
    _bill(dsn, 5)
    _invoice(dsn, 6, status="draft")                                  # a draft owes nothing yet
    service = "26200000-0000-0000-0000-000000000009"
    _ok(dsn, f"""INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) VALUES ('{service}', '{FIRM}', '{CLIENT}', 'Advice', 'service', 'Nos', '9983');
                 INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise)
                 VALUES ('b6200000-0000-0000-0000-0000000000a7', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-7', '2025-06-05', 100, 'issued', 0, 0);
                 INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, quantity, service_catalogue_id)
                 VALUES ('b6200000-0000-0000-0000-0000000000a7', 'line', 2, '{service}');""")   # a service line is not a goods line
    assert _found(dsn) == {"total": 2, "references": ["BILL-5", "INV-4"]}


# ── the table ────────────────────────────────────────────────────────────────

def test_one_mark_per_document(dsn):
    doc = _invoice(dsn, 8)
    assert _mark(dsn, "sales_invoice", doc).returncode == 0
    again = _mark(dsn, "sales_invoice", doc, reason="again")
    assert again.returncode != 0 and "stock_effect_settlements_one_per_document" in again.stderr


@pytest.mark.parametrize("kind, reason, why", [
    ("credit_note", "ok", None), ("debit_note", "ok", None), ("purchase_bill", "ok", None),
    ("receipt", "ok", "stock_effect_settlements_kind"),
    ("sales_invoice", "", "stock_effect_settlements_reason"), ("sales_invoice", "   ", "stock_effect_settlements_reason"),
    ("sales_invoice", "x" * 501, "stock_effect_settlements_reason"), ("sales_invoice", "x" * 500, None),
])
def test_the_kind_is_one_of_the_four_and_the_reason_says_something_and_is_not_over_500(dsn, kind, reason, why):
    got = _mark(dsn, kind, str(uuid.uuid4()), reason=reason)
    if why is None:
        assert got.returncode == 0, got.stderr
    else:
        assert got.returncode != 0 and why in got.stderr, got.stderr


def test_a_reference_over_200_characters_is_refused(dsn):
    got = _psql(dsn, f"""INSERT INTO {TABLE} (firm_id, client_id, document_kind, document_id, reason, reference)
                         VALUES ('{FIRM}', '{CLIENT}', 'sales_invoice', '{uuid.uuid4()}', 'ok', '{"r" * 201}');""")
    assert got.returncode != 0 and "stock_effect_settlements_lines" in got.stderr


def test_a_client_of_another_firm_is_refused_by_the_firm_check(dsn):
    got = _mark(dsn, "sales_invoice", str(uuid.uuid4()), client=FOREIGN_CLIENT)
    assert got.returncode != 0, "a mark naming a client that is not the firm's was stored"


def test_a_clients_deletion_takes_its_marks_with_it(dsn):
    _ok(dsn, f"INSERT INTO {TABLE} (firm_id, client_id, document_kind, document_id, reason) VALUES ('{FIRM}', '{OTHER_CLIENT}', 'sales_invoice', '{uuid.uuid4()}', 'x');")
    _ok(dsn, f"DELETE FROM clients WHERE id = '{OTHER_CLIENT}';")
    assert _val(dsn, f"SELECT count(*) FROM {TABLE};") == "0"


def test_the_policies_that_scope_a_client_table_are_declared(dsn):
    assert _val(dsn, f"SELECT relrowsecurity FROM pg_class WHERE oid = '{TABLE}'::regclass;") == "t"
    names = _val(dsn, f"SELECT string_agg(polname || ':' || CASE WHEN polpermissive THEN 'P' ELSE 'R' END, ',' ORDER BY polname) FROM pg_policy WHERE polrelid = '{TABLE}'::regclass;")
    assert names == ("stock_effect_settlements_assignment_scope:R,stock_effect_settlements_firm_isolation:P,"
                     "stock_effect_settlements_internal_partner_only:R"), names


# ── the privileges ───────────────────────────────────────────────────────────

def test_no_signed_in_or_anonymous_role_holds_any_privilege_and_the_service_role_holds_the_four_verbs(dsn):
    for role in ("authenticated", "anon"):
        assert _val(dsn, f"SELECT has_table_privilege('{role}', '{TABLE}', 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER');") == "f", role
        cols = _val(dsn, f"SELECT count(*) FROM information_schema.column_privileges WHERE table_name = 'stock_effect_settlements' AND grantee = '{role}';")
        assert cols == "0", (role, cols)
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _val(dsn, f"SELECT has_table_privilege('service_role', '{TABLE}', '{verb}');") == "t", verb
    refused = _psql(dsn, f"SET ROLE authenticated; SELECT * FROM {TABLE};")
    assert refused.returncode != 0 and "permission denied" in refused.stderr


def test_the_finder_is_executable_by_the_service_role_alone(dsn):
    sig = "public.documents_with_unrecorded_stock(uuid, uuid)"
    assert _val(dsn, f"SELECT has_function_privilege('authenticated', '{sig}', 'EXECUTE') OR has_function_privilege('anon', '{sig}', 'EXECUTE');") == "f"
    assert _val(dsn, f"SELECT has_function_privilege('service_role', '{sig}', 'EXECUTE');") == "t"
    refused = _psql(dsn, f"SET ROLE authenticated; SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);")
    assert refused.returncode != 0 and "permission denied" in refused.stderr


# ── applying twice, and the rollback ─────────────────────────────────────────

def test_the_migration_applies_again_and_the_rollback_restores_581s_finder_and_drops_the_table(dsn):
    doc = _invoice(dsn, 9)
    _ok(dsn, f"INSERT INTO {TABLE} (firm_id, client_id, document_kind, document_id, reason) VALUES ('{FIRM}', '{CLIENT}', 'sales_invoice', '{doc}', 'done');")
    again = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
    assert _found(dsn) == {"total": 0, "references": []}, "re-applying keeps the mark and the finder's condition"
    back = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(ROLLBACK)], capture_output=True, text=True)
    assert back.returncode == 0, back.stderr
    assert _val(dsn, f"SELECT to_regclass('{TABLE}') IS NULL;") == "t"
    assert _found(dsn) == {"total": 1, "references": ["INV-9"]}, "581's finder is back: the document is listed again"
    sig = "public.documents_with_unrecorded_stock(uuid, uuid)"
    assert _val(dsn, f"SELECT has_function_privilege('authenticated', '{sig}', 'EXECUTE');") == "f"
    re_applied = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
    assert re_applied.returncode == 0, re_applied.stderr
