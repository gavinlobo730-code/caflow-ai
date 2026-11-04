"""A credit or debit note says whether its goods came back, and the finder of unrecorded stock believes it (migration 581, POST-A-371).

`public.documents_with_unrecorded_stock` (migration 579) lists the live documents that owe a stock movement and have none. A credit or debit
note that says NO goods came back owes none, so it must never be listed (the Inventory tab would offer to move goods that never moved); one
that says YES, and one that says nothing (every note written before the column), are listed exactly as before. Real Postgres.
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
MIGRATION = next(API_ROOT.glob("migrations/581_a_credit_or_debit_note_says_whether_the_goods_it_names_came_back.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/581_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="requires HARNESS_PG + psql",
)

FIRM, CLIENT = "f5810000-0000-0000-0000-000000000001", "c5810000-0000-0000-0000-000000000001"
GOOD, SERVICE = "15810000-0000-0000-0000-000000000001", "15810000-0000-0000-0000-000000000002"
CUSTOMER, VENDOR = "e5810000-0000-0000-0000-000000000001", "d5810000-0000-0000-0000-000000000001"


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
    name = f"e581_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        _ok(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) VALUES
                ('{GOOD}', '{FIRM}', '{CLIENT}', 'Good', 'good', 'Nos', '8471'), ('{SERVICE}', '{FIRM}', '{CLIENT}', 'Advice', 'service', 'Nos', '9983');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Vend');""")
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _note(dsn, kind, n, goods_returned, *, item=GOOD, status="issued"):
    """A credit note (kind 'credit_note') or a purchase debit note ('debit_note') with one line of quantity 2 and no stock row."""
    note_id = str(uuid.UUID(f"a5810000-0000-0000-0000-{n:012d}"))
    flag = {True: "true", False: "false", None: "NULL"}[goods_returned]
    if kind == "credit_note":
        _ok(dsn, f"""INSERT INTO credit_notes (id, firm_id, client_id, customer_id, credit_note_no, credit_note_date, status, goods_returned)
                     VALUES ('{note_id}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'CN-{n}', '2025-06-05', '{status}', {flag});
                     INSERT INTO credit_note_lines (credit_note_id, description, quantity, service_catalogue_id)
                     VALUES ('{note_id}', 'line', 2, '{item}');""")
    else:
        _ok(dsn, f"""INSERT INTO debit_notes (id, firm_id, client_id, vendor_id, debit_note_no, debit_note_date, status, goods_returned)
                     VALUES ('{note_id}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'DN-{n}', '2025-06-05', '{status}', {flag});
                     INSERT INTO debit_note_lines (debit_note_id, description, quantity, service_catalogue_id)
                     VALUES ('{note_id}', 'line', 2, '{item}');""")
    return note_id


def _found(dsn) -> dict[str, tuple[str, int]]:
    out = _val(dsn, f"SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);")
    return {d["reference"]: (d["kind"], d["owed_lines"]) for d in json.loads(out)["documents"]}


def test_a_note_that_says_no_goods_came_back_owes_no_stock_and_is_never_listed(dsn):
    _note(dsn, "credit_note", 1, True)
    _note(dsn, "credit_note", 2, None)
    _note(dsn, "credit_note", 3, False)
    _note(dsn, "debit_note", 4, True)
    _note(dsn, "debit_note", 5, None)
    _note(dsn, "debit_note", 6, False)
    assert _found(dsn) == {"CN-1": ("credit_note", 1), "CN-2": ("credit_note", 1),
                           "DN-4": ("debit_note", 1), "DN-5": ("debit_note", 1)}, _found(dsn)


def test_what_579_listed_apart_from_the_notes_is_unchanged(dsn):
    _note(dsn, "credit_note", 10, True, status="draft")           # a draft owes nothing yet
    _note(dsn, "credit_note", 12, True, item=SERVICE)             # a service is not a goods line
    _ok(dsn, f"""INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise, status,
                                                    paid_paise, credited_paise)
                 VALUES ('b5810000-0000-0000-0000-000000000001', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-1', '2025-06-05', 100, 'issued', 0, 0);
                 INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, quantity, service_catalogue_id)
                 VALUES ('b5810000-0000-0000-0000-000000000001', 'line', 2, '{GOOD}');""")
    assert _found(dsn) == {"INV-1": ("sales_invoice", 1)}


def test_a_stated_no_is_not_listed_even_with_a_valued_stock_row_and_no_journal(dsn):
    """A note that was marked 'no' after goods had already moved is a hand correction the CA made; the finder is about what is OWED."""
    note = _note(dsn, "credit_note", 20, False)
    _ok(dsn, f"""INSERT INTO inventory_stock_ledger (firm_id, client_id, service_catalogue_id, movement_date, movement_type, quantity_delta,
                    unit_cost_paise, value_delta_paise, running_qty_units, running_avg_cost_paise, running_value_paise, source_type, source_id)
                 VALUES ('{FIRM}', '{CLIENT}', '{GOOD}', '2025-06-05', 'sale_return', 2, 100, 200, 2, 100, 200, 'credit_note', '{note}');""")
    assert _found(dsn) == {}


def test_the_columns_are_nullable_with_no_default_so_no_old_note_acquires_an_answer(dsn):
    for table in ("credit_notes", "debit_notes"):
        row = _val(dsn, f"""SELECT data_type || '|' || is_nullable || '|' || coalesce(column_default, '-')
                              FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{table}' AND column_name = 'goods_returned';""")
        assert row == "boolean|YES|-", (table, row)
    note = _note(dsn, "credit_note", 30, None)
    assert _val(dsn, f"SELECT coalesce(goods_returned::text, 'null') FROM credit_notes WHERE id = '{note}';") == "null"


def test_no_signed_in_or_anonymous_role_can_call_the_finder_and_the_service_role_can(dsn):
    sig = "public.documents_with_unrecorded_stock(uuid, uuid)"
    assert _val(dsn, f"SELECT has_function_privilege('authenticated', '{sig}', 'EXECUTE') OR has_function_privilege('anon', '{sig}', 'EXECUTE');") == "f"
    assert _val(dsn, f"SELECT has_function_privilege('service_role', '{sig}', 'EXECUTE');") == "t"
    refused = _psql(dsn, f"SET ROLE authenticated; SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);")
    assert refused.returncode != 0 and "permission denied" in refused.stderr


def test_the_migration_applies_again_and_the_rollback_restores_579_and_takes_the_columns_away(dsn):
    _note(dsn, "credit_note", 40, False)
    again = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
    assert _found(dsn) == {}, "re-applying keeps the stated answer"
    back = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(ROLLBACK)], capture_output=True, text=True)
    assert back.returncode == 0, back.stderr
    assert _val(dsn, "SELECT count(*) FROM information_schema.columns WHERE column_name = 'goods_returned' AND table_name IN ('credit_notes', 'debit_notes');") == "0"
    sig = "public.documents_with_unrecorded_stock(uuid, uuid)"
    assert _val(dsn, f"SELECT has_function_privilege('authenticated', '{sig}', 'EXECUTE');") == "f"
    # 579's finder is back: the note (its answer gone with the column) is owed again, as before the migration
    assert _found(dsn) == {"CN-40": ("credit_note", 1)}
    re_applied = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(MIGRATION)], capture_output=True, text=True)
    assert re_applied.returncode == 0, re_applied.stderr
