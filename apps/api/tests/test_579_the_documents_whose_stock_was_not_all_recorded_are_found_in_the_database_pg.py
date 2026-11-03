"""The database finds the documents whose stock effect was not all recorded (migration 579, POST-A-092 items 1 and 2).

`public.documents_with_unrecorded_stock(firm, client)` answers, in one round trip, which live documents of the four kinds carry an owed
goods line that has no stock-ledger row, or a stock row with a value and no journal behind it. Only a real database can show that the
counting is right, that a document that is whole is NOT listed, and that no signed-in role can call it. Real Postgres, throwaway database.
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
MIGRATION = next(API_ROOT.glob("migrations/579_the_documents_whose_stock_was_not_all_recorded_are_found_in_the_database.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/579_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="requires HARNESS_PG + psql",
)

FIRM, OTHER_FIRM = "f5790000-0000-0000-0000-000000000001", "f5790000-0000-0000-0000-0000000000ff"
CLIENT, OTHER_CLIENT = "c5790000-0000-0000-0000-000000000001", "c5790000-0000-0000-0000-000000000002"
GOOD_A, GOOD_B, SERVICE, OTHERS_GOOD = (f"15790000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3, 4))
VENDOR, CUSTOMER = "d5790000-0000-0000-0000-000000000001", "e5790000-0000-0000-0000-000000000001"
OTHER_CUSTOMER = "e5790000-0000-0000-0000-000000000002"
JOURNAL = "b5790000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e579_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
                ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{OTHER_CLIENT}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) VALUES
                ('{GOOD_A}', '{FIRM}', '{CLIENT}', 'Good A', 'good', 'Nos', '8471'),
                ('{GOOD_B}', '{FIRM}', '{CLIENT}', 'Good B', 'good', 'Nos', '8471'),
                ('{SERVICE}', '{FIRM}', '{CLIENT}', 'Audit', 'service', 'Nos', '9983'),
                ('{OTHERS_GOOD}', '{FIRM}', '{OTHER_CLIENT}', 'Good of B', 'good', 'Nos', '8471');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust'),
                ('{OTHER_CUSTOMER}', '{FIRM}', '{OTHER_CLIENT}', 'Cust of B');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Vend');
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type)
                VALUES ('{JOURNAL}', '{FIRM}', '{CLIENT}', '2026-04-20', 'a journal', 'Journal');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _invoice(dsn, n, items, *, status="issued", extra="", client=CLIENT, quantity=2):
    inv = str(uuid.UUID(f"a5790000-0000-0000-0000-{n:012d}"))
    cols = "id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise"
    vals = (f"'{inv}', '{FIRM}', '{client}', '{CUSTOMER if client == CLIENT else OTHER_CUSTOMER}', 'INV-{n}', '2026-04-20', 100, "
            f"'{status}', 0, 0")
    if extra:
        cols += ", " + extra.split("=")[0]
        vals += ", " + extra.split("=")[1]
    sql = f"INSERT INTO client_sales_invoices ({cols}) VALUES ({vals});"
    for item in items:
        sql += (f" INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, quantity, service_catalogue_id)"
                f" VALUES ('{inv}', 'line', {quantity}, '{item}');")
    assert _psql(dsn, sql).returncode == 0
    return inv


def _move(dsn, kind, doc, item, *, movement="sale", value=-1000, journal=False, client=CLIENT):
    r = _psql(dsn, f"""
        INSERT INTO inventory_stock_ledger (firm_id, client_id, service_catalogue_id, movement_date, movement_type, quantity_delta,
            unit_cost_paise, value_delta_paise, running_qty_units, running_avg_cost_paise, running_value_paise, source_type, source_id,
            journal_entry_id)
        VALUES ('{FIRM}', '{client}', '{item}', '2026-04-20', '{movement}', 1, 0, {value}, 0, 0, 0, '{kind}', '{doc}',
                {f"'{JOURNAL}'" if journal else "NULL"});""")
    assert r.returncode == 0, r.stderr


def _found(dsn, client=CLIENT, firm=FIRM, role=None) -> dict:
    prefix = f"SET ROLE {role}; " if role else ""
    r = _psql(dsn, f"{prefix}SELECT public.documents_with_unrecorded_stock('{firm}'::uuid, '{client}'::uuid);", tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _refs(answer) -> dict:
    return {d["reference"]: (d["owed_lines"], d["moved_lines"], d["unjournalled_rows"]) for d in answer["documents"]}


def test_the_sales_side_lists_exactly_the_documents_that_are_not_whole(dsn):
    none_moved = _invoice(dsn, 1, [GOOD_A, GOOD_B])
    part_moved = _invoice(dsn, 2, [GOOD_A, GOOD_B])
    _move(dsn, "sales_invoice", part_moved, GOOD_A, journal=True)
    no_journal = _invoice(dsn, 3, [GOOD_A])
    _move(dsn, "sales_invoice", no_journal, GOOD_A, journal=False)
    whole = _invoice(dsn, 4, [GOOD_A])
    _move(dsn, "sales_invoice", whole, GOOD_A, journal=True)
    oversold = _invoice(dsn, 5, [GOOD_A])
    _move(dsn, "sales_invoice", oversold, GOOD_A, value=0, journal=False)  # no cost basis: owes no journal
    answer = _found(dsn)
    assert _refs(answer) == {"INV-1": (2, 0, 0), "INV-2": (2, 1, 0), "INV-3": (1, 1, 1)}, _refs(answer)
    assert answer["total"] == 3 and none_moved and whole and oversold


def test_what_is_not_a_live_goods_document_is_never_listed(dsn):
    _invoice(dsn, 10, [GOOD_A], status="draft")
    _invoice(dsn, 11, [GOOD_A], status="cancelled")
    _invoice(dsn, 12, [GOOD_A], extra="deleted_at='2026-04-30'")
    _invoice(dsn, 13, [GOOD_A], extra="is_opening=true")
    _invoice(dsn, 14, [SERVICE])                      # a service is not a goods line
    _invoice(dsn, 15, [OTHERS_GOOD])                  # another client's item is not this client's goods line
    _invoice(dsn, 16, [GOOD_A], quantity=0)           # nothing to move
    _invoice(dsn, 17, [GOOD_A], client=OTHER_CLIENT)  # another client's document
    assert _found(dsn) == {"total": 0, "documents": []}
    assert _refs(_found(dsn, client=OTHER_CLIENT)) == {}, "another client's invoice names this client's item, which is not its goods line"


def test_paid_and_part_paid_documents_are_live(dsn):
    _invoice(dsn, 20, [GOOD_A], status="paid")
    _invoice(dsn, 21, [GOOD_A], status="partially_paid")
    assert set(_refs(_found(dsn))) == {"INV-20", "INV-21"}


def test_the_purchase_credit_and_debit_sides_are_found_by_their_own_movement_types(dsn):
    bill, bill_nil, cn, dn = (str(uuid.UUID(f"b5791000-0000-0000-0000-{n:012d}")) for n in (1, 2, 3, 4))
    sql = f"""
        INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, status)
            VALUES ('{bill}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'B-1', '2026-04-20', 'received'),
                   ('{bill_nil}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'B-NIL', '2026-04-20', 'received');
        INSERT INTO purchase_bill_lines (bill_id, description, quantity, taxable_amount_paise, service_catalogue_id)
            VALUES ('{bill}', 'x', 3, 300000, '{GOOD_A}'), ('{bill_nil}', 'x', 3, 0, '{GOOD_A}');
        INSERT INTO credit_notes (id, firm_id, client_id, customer_id, credit_note_no, credit_note_date, status)
            VALUES ('{cn}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'CN-1', '2026-04-20', 'issued');
        INSERT INTO credit_note_lines (credit_note_id, description, quantity, service_catalogue_id) VALUES ('{cn}', 'x', 1, '{GOOD_A}');
        INSERT INTO debit_notes (id, firm_id, client_id, vendor_id, debit_note_no, debit_note_date, status)
            VALUES ('{dn}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'DN-1', '2026-04-20', 'issued');
        INSERT INTO debit_note_lines (debit_note_id, quantity, service_catalogue_id) VALUES ('{dn}', 1, '{GOOD_A}');
    """
    assert _psql(dsn, sql).returncode == 0
    assert _refs(_found(dsn)) == {"B-1": (1, 0, 0), "CN-1": (1, 0, 0), "DN-1": (1, 0, 0)}, "a bill line with a nil taxable value is not owed"
    _move(dsn, "purchase_bill", bill, GOOD_A, movement="purchase", value=300000, journal=True)
    _move(dsn, "credit_note", cn, GOOD_A, movement="sale_return", value=500, journal=True)
    _move(dsn, "debit_note", dn, GOOD_A, movement="purchase_return", value=-500, journal=True)
    assert _found(dsn) == {"total": 0, "documents": []}
    # A reversal row (a cancellation's) is not the document's own movement: it must not make a missing line look present.
    other = str(uuid.UUID("b5791000-0000-0000-0000-000000000009"))
    assert _psql(dsn, f"""INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, status)
                          VALUES ('{other}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'B-REV', '2026-04-20', 'received');
                          INSERT INTO purchase_bill_lines (bill_id, description, quantity, taxable_amount_paise, service_catalogue_id)
                          VALUES ('{other}', 'x', 1, 100, '{GOOD_A}');""").returncode == 0
    _move(dsn, "purchase_bill", other, GOOD_A, movement="purchase_reversal", value=-100, journal=False)
    assert _refs(_found(dsn)) == {"B-REV": (1, 0, 0)}


def test_the_list_is_capped_at_two_hundred_and_the_total_is_not(dsn):
    n = 205
    sql = "".join(
        f"INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status, paid_paise, credited_paise) "
        f"VALUES ('{uuid.UUID(f'a5792000-0000-0000-0000-{i:012d}')}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'C-{i:04d}', '2026-04-20', 1, 'issued', 0, 0);"
        f"INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, quantity, service_catalogue_id) "
        f"VALUES ('{uuid.UUID(f'a5792000-0000-0000-0000-{i:012d}')}', 'l', 1, '{GOOD_A}');" for i in range(n))
    assert _psql(dsn, sql).returncode == 0
    answer = _found(dsn)
    assert answer["total"] == n and len(answer["documents"]) == 200


def test_nobody_signed_in_can_call_it_and_the_server_can(dsn):
    # Supabase grants EXECUTE on every new public function to the signed-in roles by default, and this throwaway database does not:
    # replay that default and apply the migration again, so the REVOKE in it is what is being tested and not an empty default.
    assert _psql(dsn, "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated; "
                      "DROP FUNCTION public.documents_with_unrecorded_stock(uuid, uuid);").returncode == 0
    assert _psql(dsn, MIGRATION.read_text()).returncode == 0
    for role in ("authenticated", "anon"):
        r = _psql(dsn, f"SET ROLE {role}; SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);")
        assert r.returncode != 0 and "permission denied" in r.stderr, (role, r.stderr)
    assert _found(dsn, role="service_role") == {"total": 0, "documents": []}


def test_the_closing_check_is_alone_enough_and_the_rollback_drops_the_function(dsn):
    text = MIGRATION.read_text()
    check = text[text.index("DO $$"):]
    assert _psql(dsn, check).returncode == 0
    assert _psql(dsn, "GRANT EXECUTE ON FUNCTION public.documents_with_unrecorded_stock(uuid, uuid) TO authenticated;").returncode == 0
    spoiled = _psql(dsn, check)
    assert spoiled.returncode != 0 and "executable by a signed-in or anonymous role" in spoiled.stderr
    assert _psql(dsn, ROLLBACK.read_text()).returncode == 0
    assert _psql(dsn, "SELECT to_regprocedure('public.documents_with_unrecorded_stock(uuid, uuid)') IS NULL;", tuples=True).stdout.strip() == "t"
    assert _psql(dsn, text).returncode == 0, "a re-apply gives it back"
