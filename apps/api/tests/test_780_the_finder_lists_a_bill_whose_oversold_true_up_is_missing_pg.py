"""The finder lists a bill whose oversold true-up entry is missing, and says which listed documents a retry cannot finish (migration 780, POST-A-092).

Real Postgres, throwaway database. Migration 780 replaces `public.documents_with_unrecorded_stock` (579, 581, 620) with one more shape and a
`hand_fix` column on every found document. What only a real database shows: that the new shape is found by the SQL and a whole bill is not, that a
true-up entry which stands (or which was reversed or deleted) is read right, that a bill with a nil-cost line is not mistaken for a free-goods line,
that the old shapes and the CA's marks behave as they did, and that the privileges are the ones 579 gave.
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
MIGRATION = next(API_ROOT.glob("migrations/780_the_finder_lists_a_bill_whose_oversold_true_up_is_missing_*[!k].sql"))
ROLLBACK = next(API_ROOT.glob("migrations/780_*_rollback.sql"))

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="requires HARNESS_PG + psql",
)

FIRM, CLIENT = "f7800000-0000-0000-0000-000000000001", "c7800000-0000-0000-0000-000000000001"
GOOD_A, GOOD_B = "17800000-0000-0000-0000-000000000001", "17800000-0000-0000-0000-000000000002"
VENDOR = "d7800000-0000-0000-0000-000000000001"
SENTINEL_JOURNAL = "b7800000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e780_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO service_catalogue (id, firm_id, client_id, name, kind, unit, hsn_sac) VALUES
                ('{GOOD_A}', '{FIRM}', '{CLIENT}', 'Good A', 'good', 'Nos', '8471'),
                ('{GOOD_B}', '{FIRM}', '{CLIENT}', 'Good B', 'good', 'Nos', '8471');
            INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Vend');
            INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type)
                VALUES ('{SENTINEL_JOURNAL}', '{FIRM}', '{CLIENT}', '2026-04-20', 'a receipt journal', 'Journal');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _bill(dsn, n, lines, *, status="received"):
    """A purchase bill with the given (item, taxable_paise) lines; returns its id."""
    bill = str(uuid.UUID(f"b7801000-0000-0000-0000-{n:012d}"))
    sql = (f"INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, status) "
           f"VALUES ('{bill}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'B-{n}', '2026-04-20', '{status}');")
    for item, taxable in lines:
        sql += (f" INSERT INTO purchase_bill_lines (bill_id, description, quantity, taxable_amount_paise, service_catalogue_id)"
                f" VALUES ('{bill}', 'x', 3, {taxable}, '{item}');")
    assert _psql(dsn, sql).returncode == 0
    return bill


def _row(dsn, bill, item, *, value, journal=False, short=False):
    """A stock-in row of 3 units. `short` is a row written while the item was already below nil (the quantity before it was -2)."""
    r = _psql(dsn, f"""
        INSERT INTO inventory_stock_ledger (firm_id, client_id, service_catalogue_id, movement_date, movement_type, quantity_delta,
            unit_cost_paise, value_delta_paise, running_qty_units, running_avg_cost_paise, running_value_paise, source_type, source_id,
            journal_entry_id)
        VALUES ('{FIRM}', '{CLIENT}', '{item}', '2026-04-20', 'purchase', 3, 0, {value}, {1 if short else 3}, 0, 0, 'purchase_bill', '{bill}',
                {f"'{SENTINEL_JOURNAL}'" if journal else "NULL"});""")
    assert r.returncode == 0, r.stderr


def _true_up(dsn, bill, *, reversed_=False, deleted=False):
    j = str(uuid.uuid4())
    extra_cols = (", is_reversed" if reversed_ else "") + (", deleted_at" if deleted else "")
    extra_vals = (", true" if reversed_ else "") + (", now()" if deleted else "")
    r = _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, reference_no, source_type, source_id{extra_cols})
        VALUES ('{j}', '{FIRM}', '{CLIENT}', '2026-04-20', 'Oversold cost true-up', 'Journal', 'PB-{bill[-6:]}-COGSTRUEUP', 'purchase_bill', '{bill}'{extra_vals});""")
    assert r.returncode == 0, r.stderr


def _charge(dsn, bill):
    r = _psql(dsn, f"""INSERT INTO purchase_bill_landed_costs (firm_id, client_id, bill_id, description, amount_paise)
                       VALUES ('{FIRM}', '{CLIENT}', '{bill}', 'Freight inward', 12500);""")
    assert r.returncode == 0, r.stderr


def _found(dsn, role=None) -> dict:
    prefix = f"SET ROLE {role}; " if role else ""
    r = _psql(dsn, f"{prefix}SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);", tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _fixes(answer) -> dict:
    return {d["reference"]: d["hand_fix"] for d in answer["documents"]}


def test_a_bill_whose_cost_went_to_cover_an_oversold_sale_and_has_no_true_up_entry_is_listed(dsn):
    bill = _bill(dsn, 1, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=0)                       # the whole cost covered units sold while oversold: nil value on the row
    assert _fixes(_found(dsn)) == {"B-1": "oversold_trueup"}


def test_the_same_bill_with_its_true_up_entry_standing_is_whole(dsn):
    bill = _bill(dsn, 2, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=0)
    _true_up(dsn, bill)
    assert _found(dsn) == {"total": 0, "documents": []}


def test_a_true_up_entry_that_was_reversed_or_deleted_does_not_count(dsn):
    reversed_bill = _bill(dsn, 3, [(GOOD_A, 300000)])
    _row(dsn, reversed_bill, GOOD_A, value=0)
    _true_up(dsn, reversed_bill, reversed_=True)
    deleted_bill = _bill(dsn, 4, [(GOOD_A, 300000)])
    _row(dsn, deleted_bill, GOOD_A, value=0)
    _true_up(dsn, deleted_bill, deleted=True)
    assert _fixes(_found(dsn)) == {"B-3": "oversold_trueup", "B-4": "oversold_trueup"}


def test_a_bill_that_only_partly_covered_an_oversold_sale_and_has_no_true_up_entry_is_listed(dsn):
    # a valued, journalled row written while the item was already below nil: a part of the cost belongs in Cost of Goods Sold and the entry for it is missing
    bill = _bill(dsn, 11, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=200000, journal=True, short=True)
    assert _fixes(_found(dsn)) == {"B-11": "oversold_trueup"}


def test_the_same_part_covered_bill_with_its_true_up_entry_standing_is_whole(dsn):
    bill = _bill(dsn, 12, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=200000, journal=True, short=True)
    _true_up(dsn, bill)
    assert _found(dsn) == {"total": 0, "documents": []}


def test_an_ordinary_bill_received_into_stock_that_was_not_short_is_not_listed(dsn):
    bill = _bill(dsn, 13, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=300000, journal=True)
    assert _found(dsn) == {"total": 0, "documents": []}


def test_a_short_row_for_a_line_with_no_cost_owes_no_true_up(dsn):
    bill = _bill(dsn, 14, [(GOOD_B, 0)])
    _row(dsn, bill, GOOD_B, value=0, journal=True, short=True)
    assert _found(dsn) == {"total": 0, "documents": []}


def test_a_nil_row_for_a_line_with_no_cost_is_free_goods_and_not_a_missing_true_up(dsn):
    # a line with a nil taxable value is not owed (579): its nil row is free goods, which owe nothing
    free = _bill(dsn, 5, [(GOOD_B, 0)])
    _row(dsn, free, GOOD_B, value=0)
    assert _found(dsn) == {"total": 0, "documents": []}


def test_a_nil_row_of_another_item_than_the_bills_costed_line_is_not_the_shape(dsn):
    # the bill's costed line is GOOD_A and its row is valued; the nil row is for GOOD_B, whose bill line is free
    bill = _bill(dsn, 6, [(GOOD_A, 300000), (GOOD_B, 0)])
    _row(dsn, bill, GOOD_A, value=300000, journal=True)
    _row(dsn, bill, GOOD_B, value=0)
    assert _found(dsn) == {"total": 0, "documents": []}


def test_a_bill_with_charges_and_unjournalled_stock_says_a_retry_cannot_finish_it(dsn):
    bill = _bill(dsn, 7, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=315000, journal=False)   # valued, no journal: listed by the old rule
    _charge(dsn, bill)
    plain = _bill(dsn, 8, [(GOOD_A, 300000)])
    _row(dsn, plain, GOOD_A, value=300000, journal=False)  # the same shape with no charges: a retry can finish it
    assert _fixes(_found(dsn)) == {"B-7": "landed_charges", "B-8": None}


def test_the_old_shapes_and_the_cas_marks_are_unchanged(dsn):
    none_moved = _bill(dsn, 9, [(GOOD_A, 300000)])        # no stock row at all: the first shape, a retry can finish it
    marked = _bill(dsn, 10, [(GOOD_A, 300000)])
    _row(dsn, marked, GOOD_A, value=0)
    assert _psql(dsn, f"""INSERT INTO stock_effect_settlements (firm_id, client_id, document_kind, document_id, reference, reason)
                          VALUES ('{FIRM}', '{CLIENT}', 'purchase_bill', '{marked}', 'B-10', 'Posted the true-up by hand on 21 April');""").returncode == 0
    assert _fixes(_found(dsn)) == {"B-9": None}, "a marked bill is not listed, and an unmoved one is listed with nothing to do by hand"
    assert none_moved


def test_nobody_signed_in_can_call_it_and_the_server_can(dsn):
    for role in ("anon", "authenticated"):
        r = _psql(dsn, f"SET ROLE {role}; SELECT public.documents_with_unrecorded_stock('{FIRM}'::uuid, '{CLIENT}'::uuid);")
        assert r.returncode != 0 and "permission denied" in r.stderr, role
    assert _found(dsn, role="service_role") == {"total": 0, "documents": []}


def test_the_rollback_puts_the_previous_finder_back_and_the_migration_applies_again(dsn):
    bill = _bill(dsn, 11, [(GOOD_A, 300000)])
    _row(dsn, bill, GOOD_A, value=0)
    assert _fixes(_found(dsn)) == {"B-11": "oversold_trueup"}
    assert _psql(dsn, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    assert _found(dsn) == {"total": 0, "documents": []}     # 620's finder knows no nil-value shape
    assert _psql(dsn, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _fixes(_found(dsn)) == {"B-11": "oversold_trueup"}
