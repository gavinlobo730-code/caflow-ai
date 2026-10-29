"""The "is this code / service still used?" checks run against the real schema, and every table that carries the code or the
service link is read or named (ledger POST-A-312).

WHY A DATABASE
    The mock-mode half is `test_the_usage_checks_see_the_note_and_recurring_purchase_tables.py`. A wrong column or table name in
    one of these queries makes every purge and every delete answer "unable to delete", and a double that answers any column
    never notices. So `_find_service_usage` runs here against the migration-built schema, as the privileged client the route
    uses (the signed-in double of `tests/_signed_in_postgrest.py`, as `service_role`). `_find_hsn_usage` asks PostgREST for an
    embedded `!inner` filter on the document's firm, which no double here models, so its chain is proved from the schema: each
    line table has exactly ONE foreign key to the document it names (two would make PostgREST refuse the embed as ambiguous),
    the document has `firm_id`, the line has `hsn_sac`, and the join that foreign key defines finds the document for the firm
    that owns it and for no other.

WHAT IS HELD
    * a code used on a sales debit note line, a purchase credit note line or a recurring purchase bill template line is reachable
      through the relationship `_find_hsn_usage` embeds, for the firm that owns the document and not for another firm;
    * a service on an issued note, or on a template that is not archived, is found, and on a draft note or an archived template
      it is not;
    * THE RULE, over the schema: every table with a `service_catalogue_id` column is one `_find_service_usage` reads or is on
      `SERVICE_LINK_NOT_READ`, and every table with an `hsn_sac` column is one `_find_hsn_usage` reads or is on
      `HSN_NOT_READ`. Both lists are shrink-only: a table that is now read, or that no longer exists, fails the list. The next
      table to carry the link is a red test here and not a code someone purged;
    * (POST-A-324) a service on a quotation, an order, a challan, a purchase order or a goods receipt is found in every state
      those families allow except draft and cancelled, a stock count line in a count that was not abandoned and a batch that
      was not soft-deleted are found, and a code on any of the five documents is reachable through the relationship the purge
      embeds, for the firm that owns it and not for another.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

import routers.firm_hsn_library as hsn_library
import routers.service_catalogue as service_catalogue
from tests._signed_in_postgrest import SignedInDb

API_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the usage-check proof requires HARNESS_PG + psql",
)

FIRM = "31200000-0000-0000-0000-000000000001"
OTHER_FIRM = "31200000-0000-0000-0000-000000000002"
CLIENT = "31200000-0000-0000-0000-0000000000c1"
OTHER_CLIENT = "31200000-0000-0000-0000-0000000000c2"
CUSTOMER = "31200000-0000-0000-0000-0000000000d1"
OTHER_CUSTOMER = "31200000-0000-0000-0000-0000000000d2"
VENDOR = "31200000-0000-0000-0000-0000000000e1"
OTHER_VENDOR = "31200000-0000-0000-0000-0000000000e2"
SERVICE = "31200000-0000-0000-0000-0000000000a1"
NEIGHBOUR_SERVICE = "31200000-0000-0000-0000-0000000000a2"

# Tables that carry the service link and that `_find_service_usage` does not read, each with the reason it is not read.
# The five documents before the tax invoice and the bill, the stock count lines and the batches were on this list until
# POST-A-324 and are read now. What is left cascades a delete and has no document behind it.
SERVICE_LINK_NOT_READ = {
    "price_list_items": "CASCADE; a price entry is a pre-fill for an invoice line's rate and nothing else (the price-list "
                        "design record), so it goes with the item it prices (POST-A-324)",
}

# Tables that carry `hsn_sac` and that `_find_hsn_usage` does not read.
HSN_NOT_READ = {
    "hsn_sac_preferences": "a learned suggestion (description to code, with a use count), not a document: it records no use of a code",
}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def world(pg_template):
    admin = _ADMIN.strip()
    name = f"e312_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship'), ('{OTHER_CLIENT}', '{OTHER_FIRM}', 'B', 'Proprietorship');
            INSERT INTO customers (id, firm_id, client_id, name)
                 VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'C'), ('{OTHER_CUSTOMER}', '{OTHER_FIRM}', '{OTHER_CLIENT}', 'D');
            INSERT INTO vendors (id, firm_id, client_id, name)
                 VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'V'), ('{OTHER_VENDOR}', '{OTHER_FIRM}', '{OTHER_CLIENT}', 'W');
            INSERT INTO service_catalogue (id, firm_id, client_id, name)
                 VALUES ('{SERVICE}', '{FIRM}', '{CLIENT}', 'S'), ('{NEIGHBOUR_SERVICE}', '{FIRM}', '{CLIENT}', 'T');
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.db = SignedInDb(dsn, role="service_role")
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sales_debit_note(w, *, firm=FIRM, client=CLIENT, customer=CUSTOMER, status="issued", hsn=None, service=None) -> str:
    nid = str(uuid.uuid4())
    sql = f"""
        INSERT INTO sales_debit_notes (id, firm_id, client_id, customer_id, debit_note_no, debit_note_date, status)
             VALUES ('{nid}', '{firm}', '{client}', '{customer}', 'SDN-{nid[:8]}', '2026-04-10', '{status}');
        INSERT INTO sales_debit_note_lines (debit_note_id, description, hsn_sac, service_catalogue_id)
             VALUES ('{nid}', 'line', {f"'{hsn}'" if hsn else 'NULL'}, {f"'{service}'" if service else 'NULL'});
    """
    assert _psql(w.dsn, sql).returncode == 0
    return nid


def _purchase_credit_note(w, *, firm=FIRM, client=CLIENT, vendor=VENDOR, status="issued", hsn=None, service=None) -> str:
    nid = str(uuid.uuid4())
    sql = f"""
        INSERT INTO purchase_credit_notes (id, firm_id, client_id, vendor_id, credit_note_date, status)
             VALUES ('{nid}', '{firm}', '{client}', '{vendor}', '2026-04-10', '{status}');
        INSERT INTO purchase_credit_note_lines (credit_note_id, description, hsn_sac, service_catalogue_id)
             VALUES ('{nid}', 'line', {f"'{hsn}'" if hsn else 'NULL'}, {f"'{service}'" if service else 'NULL'});
    """
    assert _psql(w.dsn, sql).returncode == 0
    return nid


def _template(w, *, firm=FIRM, client=CLIENT, vendor=VENDOR, status="active", hsn=None, service=None) -> str:
    tid = str(uuid.uuid4())
    sql = f"""
        INSERT INTO recurring_purchase_bill_templates (id, firm_id, client_id, vendor_id, title, frequency, start_date, next_run_date, status)
             VALUES ('{tid}', '{firm}', '{client}', '{vendor}', 'Rent', 'monthly', '2026-04-01', '2026-05-01', '{status}');
        INSERT INTO recurring_purchase_bill_template_lines (template_id, description, hsn_sac, service_catalogue_id)
             VALUES ('{tid}', 'line', {f"'{hsn}'" if hsn else 'NULL'}, {f"'{service}'" if service else 'NULL'});
    """
    assert _psql(w.dsn, sql).returncode == 0
    return tid


# The five documents before the tax invoice and the bill (migrations 392 and 393), each with its parent, its line table, the
# line's foreign key to the parent and the states it allows. Every one has a draft and a cancelled state.
CYCLE_FAMILIES = {
    "a sales quotation": ("sales_quotations", "sales_quotation_lines", "quotation_id",
                          ["draft", "sent", "accepted", "declined", "converted", "cancelled"]),
    "a sales order": ("sales_orders", "sales_order_lines", "order_id",
                      ["draft", "confirmed", "partially_delivered", "delivered", "closed", "cancelled"]),
    "a delivery challan": ("delivery_challans", "delivery_challan_lines", "challan_id",
                           ["draft", "issued", "received_back", "cancelled"]),
    "a purchase order": ("purchase_orders", "purchase_order_lines", "order_id",
                         ["draft", "approved", "partially_received", "received", "closed", "cancelled"]),
    "a goods receipt": ("goods_receipt_notes", "goods_receipt_lines", "receipt_id", ["draft", "recorded", "cancelled"]),
}


def _cycle_document(w, label: str, *, firm=FIRM, client=CLIENT, status="draft", hsn=None, service=None) -> str:
    """One document of a family with one line, carrying the code and the service link it is given."""
    parent, line_table, fk, _states = CYCLE_FAMILIES[label]
    did = str(uuid.uuid4())
    no = f"D{did[:8]}"
    columns = {
        "sales_quotations": f"(id, firm_id, client_id, customer_id, kind, document_no, document_date, status) "
                            f"VALUES ('{did}', '{firm}', '{client}', '{CUSTOMER}', 'quotation', '{no}', '2026-04-10', '{status}')",
        "sales_orders": f"(id, firm_id, client_id, customer_id, document_no, document_date, status) "
                        f"VALUES ('{did}', '{firm}', '{client}', '{CUSTOMER}', '{no}', '2026-04-10', '{status}')",
        "delivery_challans": f"(id, firm_id, client_id, document_no, document_date, reason, status) "
                             f"VALUES ('{did}', '{firm}', '{client}', '{no}', '2026-04-10', 'job_work', '{status}')",
        "purchase_orders": f"(id, firm_id, client_id, vendor_id, document_no, document_date, status) "
                           f"VALUES ('{did}', '{firm}', '{client}', '{VENDOR}', '{no}', '2026-04-10', '{status}')",
        "goods_receipt_notes": f"(id, firm_id, client_id, vendor_id, document_no, received_on, status) "
                               f"VALUES ('{did}', '{firm}', '{client}', '{VENDOR}', '{no}', '2026-04-10', '{status}')",
    }[parent]
    sql = f"""
        INSERT INTO {parent} {columns};
        INSERT INTO {line_table} (firm_id, client_id, {fk}, description, hsn_sac, service_catalogue_id)
             VALUES ('{firm}', '{client}', '{did}', 'line', {f"'{hsn}'" if hsn else 'NULL'}, {f"'{service}'" if service else 'NULL'});
    """
    result = _psql(w.dsn, sql)
    assert result.returncode == 0, result.stderr
    return did


def _count_line(w, *, session_status="open", service=SERVICE) -> str:
    sid = str(uuid.uuid4())
    sql = f"""
        INSERT INTO stock_count_sessions (id, firm_id, client_id, count_date, reference_no, status)
             VALUES ('{sid}', '{FIRM}', '{CLIENT}', '2026-04-{10 + uuid.uuid4().int % 15}', 'C-{sid[:8]}', '{session_status}');
        INSERT INTO stock_count_lines (firm_id, client_id, session_id, service_catalogue_id)
             VALUES ('{FIRM}', '{CLIENT}', '{sid}', '{service}');
    """
    result = _psql(w.dsn, sql)
    assert result.returncode == 0, result.stderr
    return sid


def _batch(w, *, deleted=False, service=SERVICE) -> str:
    bid = str(uuid.uuid4())
    sql = f"""INSERT INTO inventory_batches (id, firm_id, client_id, service_catalogue_id, batch_no, deleted_at)
                   VALUES ('{bid}', '{FIRM}', '{CLIENT}', '{service}', 'B-{bid[:8]}', {"now()" if deleted else "NULL"});"""
    result = _psql(w.dsn, sql)
    assert result.returncode == 0, result.stderr
    return bid


def _purge(w, ids: list[str]) -> None:
    tables = [("sales_debit_notes", "id"), ("purchase_credit_notes", "id"), ("recurring_purchase_bill_templates", "id"),
              ("sales_quotations", "id"), ("sales_orders", "id"), ("delivery_challans", "id"), ("purchase_orders", "id"),
              ("goods_receipt_notes", "id"), ("stock_count_sessions", "id"), ("inventory_batches", "id")]
    quoted = ", ".join(f"'{i}'" for i in ids)
    for table, column in tables:
        assert _psql(w.dsn, f"DELETE FROM {table} WHERE {column} IN ({quoted});").returncode == 0


# ── the real queries ─────────────────────────────────────────────────────────────

def _embed_chain(world, line_table: str, parent_table: str) -> tuple[str, int]:
    """The foreign key PostgREST resolves `parent!inner(firm_id)` through, and how many there are from the line to the parent."""
    rows = _rows(world.dsn, f"""
        SELECT a.attname FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
         WHERE c.contype = 'f' AND c.conrelid = 'public.{line_table}'::regclass AND c.confrelid = 'public.{parent_table}'::regclass""")
    return (rows[0][0] if rows else ""), len(rows)


@pytest.mark.parametrize("make,line_table,parent_table,label", [
    (_sales_debit_note, "sales_debit_note_lines", "sales_debit_notes", "a sales debit note"),
    (_purchase_credit_note, "purchase_credit_note_lines", "purchase_credit_notes", "a purchase credit note"),
    (_template, "recurring_purchase_bill_template_lines", "recurring_purchase_bill_templates", "a recurring purchase bill template"),
    *[((lambda w, hsn=None, _label=label: _cycle_document(w, _label, hsn=hsn)), line_table, parent, label)
      for label, (parent, line_table, _fk, _states) in CYCLE_FAMILIES.items()],
])
def test_a_code_on_one_of_the_eight_tables_is_reachable_through_the_relationship_the_check_embeds(world, make, line_table, parent_table, label):
    # the entry the check holds is the one this proof is about
    assert (label, line_table, parent_table) in hsn_library._USAGE_CHECKS
    fk_column, how_many = _embed_chain(world, line_table, parent_table)
    assert how_many == 1, f"{line_table} has {how_many} foreign keys to {parent_table}: PostgREST refuses an ambiguous embed"
    assert _rows(world.dsn, f"SELECT 1 FROM information_schema.columns WHERE table_name = '{parent_table}' AND column_name = 'firm_id'")
    assert _rows(world.dsn, f"SELECT 1 FROM information_schema.columns WHERE table_name = '{line_table}' AND column_name = 'hsn_sac'")
    code = f"99{uuid.uuid4().int % 10_000:04d}"
    made = make(world, hsn=code)
    try:
        def found(firm: str, hsn: str) -> int:
            return len(_rows(world.dsn, f"""
                SELECT 1 FROM {line_table} l JOIN {parent_table} p ON p.id = l.{fk_column}
                 WHERE l.hsn_sac = '{hsn}' AND p.firm_id = '{firm}' LIMIT 1"""))
        assert found(FIRM, code) == 1
        assert found(OTHER_FIRM, code) == 0, "another firm's code was reported as used"
        assert found(FIRM, "000000") == 0
    finally:
        _purge(world, [made])


def test_a_service_on_an_issued_note_is_found_and_on_a_draft_one_is_not(world):
    issued_debit, draft_debit = _sales_debit_note(world, service=SERVICE), _sales_debit_note(world, status="draft", service=NEIGHBOUR_SERVICE)
    try:
        assert service_catalogue._find_service_usage(world.db, SERVICE) == ["a sales debit note"]
        assert service_catalogue._find_service_usage(world.db, NEIGHBOUR_SERVICE) == []
    finally:
        _purge(world, [issued_debit, draft_debit])
    issued_credit, draft_credit = _purchase_credit_note(world, service=SERVICE), _purchase_credit_note(world, status="draft", service=NEIGHBOUR_SERVICE)
    try:
        assert service_catalogue._find_service_usage(world.db, SERVICE) == ["a purchase credit note"]
        assert service_catalogue._find_service_usage(world.db, NEIGHBOUR_SERVICE) == []
    finally:
        _purge(world, [issued_credit, draft_credit])


@pytest.mark.parametrize("status,found", [("active", True), ("paused", True), ("archived", False)])
def test_a_service_on_a_recurring_purchase_bill_template_is_found_unless_the_template_is_archived(world, status, found):
    made = _template(world, status=status, service=SERVICE)
    try:
        assert service_catalogue._find_service_usage(world.db, SERVICE) == (["a recurring purchase bill template"] if found else [])
        assert service_catalogue._find_service_usage(world.db, NEIGHBOUR_SERVICE) == []
    finally:
        _purge(world, [made])


@pytest.mark.parametrize("label,status", [
    (label, status) for label, (_p, _l, _f, states) in CYCLE_FAMILIES.items() for status in states
])
def test_a_service_on_a_document_before_the_invoice_is_found_in_every_state_but_draft_and_cancelled(world, label, status):
    """Each family's own vocabulary is walked, so a state added to a family's CHECK later is a state this test must be given."""
    made = _cycle_document(world, label, status=status, service=SERVICE)
    try:
        expected = [] if status in ("draft", "cancelled") else [label]
        assert service_catalogue._find_service_usage(world.db, SERVICE) == expected, (label, status)
        assert service_catalogue._find_service_usage(world.db, NEIGHBOUR_SERVICE) == []
    finally:
        _purge(world, [made])


def test_the_states_the_test_walks_are_the_ones_the_schema_allows(world):
    """The vocabulary above is copied from migrations 392 and 393; this reads each CHECK so a copy that drifts fails here."""
    import re
    for label, (parent, _line, _fk, states) in CYCLE_FAMILIES.items():
        rows = _rows(world.dsn, f"""
            SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c
             WHERE c.conrelid = 'public.{parent}'::regclass AND c.contype = 'c' AND pg_get_constraintdef(c.oid) LIKE '%status%'""")
        allowed = {m for r in rows for m in re.findall(r"'([a-z_]+)'::text", r[0])}
        assert allowed == set(states), (label, sorted(allowed ^ set(states)))


@pytest.mark.parametrize("session_status,found", [("open", True), ("posted", True), ("abandoned", False)])
def test_a_service_on_a_stock_count_line_is_found_unless_the_count_was_abandoned(world, session_status, found):
    made = _count_line(world, session_status=session_status)
    try:
        assert service_catalogue._find_service_usage(world.db, SERVICE) == (["a physical stock count"] if found else [])
        assert service_catalogue._find_service_usage(world.db, NEIGHBOUR_SERVICE) == []
    finally:
        _purge(world, [made])


@pytest.mark.parametrize("deleted,found", [(False, True), (True, False)])
def test_a_service_on_a_batch_is_found_unless_the_batch_was_soft_deleted(world, deleted, found):
    made = _batch(world, deleted=deleted)
    try:
        assert service_catalogue._find_service_usage(world.db, SERVICE) == (["a stock batch"] if found else [])
    finally:
        _purge(world, [made])


def test_the_double_answers_an_in_filter_over_a_list_and_nothing_for_an_empty_list(world):
    """The check reads the parents of the lines it found with `in_`; the signed-in double learned that call for this proof, so it
    is tested here rather than trusted."""
    table = world.db.table
    both = table("service_catalogue").select("id").in_("id", [SERVICE, NEIGHBOUR_SERVICE]).execute().data
    assert {r["id"] for r in both} == {SERVICE, NEIGHBOUR_SERVICE}
    one = table("service_catalogue").select("id").in_("id", [SERVICE, "31200000-0000-0000-0000-00000000ffff"]).execute().data
    assert [r["id"] for r in one] == [SERVICE]
    assert table("service_catalogue").select("id").in_("id", []).execute().data == []
    both_filters = table("service_catalogue").select("id").eq("firm_id", FIRM).in_("id", [NEIGHBOUR_SERVICE]).execute().data
    assert [r["id"] for r in both_filters] == [NEIGHBOUR_SERVICE]


# ── THE RULE: every table that carries the code or the link is read, or is named ──

def _tables_with_column(world, column: str) -> set[str]:
    rows = _rows(world.dsn, f"""
        SELECT c.table_name FROM information_schema.columns c
          JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = 'public' AND c.column_name = '{column}' AND t.table_type = 'BASE TABLE'""")
    return {r[0] for r in rows}


def _tables_named_in(function) -> set[str]:
    import inspect
    tree = ast.parse(inspect.getsource(function).lstrip())
    return {call.args[0].value for call in ast.walk(tree)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "table"
            and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)}


def test_every_table_that_carries_the_service_link_is_read_or_named(world):
    carrying = _tables_with_column(world, "service_catalogue_id")
    read = {line_table for _label, line_table, _fk, _parent in service_catalogue._SERVICE_USAGE_CHECKS} \
        | _tables_named_in(service_catalogue._find_service_usage)
    assert {"sales_debit_note_lines", "purchase_credit_note_lines", "recurring_purchase_bill_template_lines"} <= read
    unread = carrying - read
    assert unread == set(SERVICE_LINK_NOT_READ), (
        f"a table that carries service_catalogue_id is neither read by _find_service_usage nor named with its reason: "
        f"{sorted(unread - set(SERVICE_LINK_NOT_READ))}; or a named one is now read / gone (shrink-only list): "
        f"{sorted(set(SERVICE_LINK_NOT_READ) - unread)}")


def test_every_table_that_carries_hsn_sac_is_read_or_named(world):
    carrying = _tables_with_column(world, "hsn_sac")
    read = {table for _label, table, _parent in hsn_library._USAGE_CHECKS}
    assert {"sales_debit_note_lines", "purchase_credit_note_lines", "recurring_purchase_bill_template_lines"} <= read
    unread = carrying - read
    assert unread == set(HSN_NOT_READ), (
        f"a table that carries hsn_sac is neither read by _find_hsn_usage nor named with its reason: "
        f"{sorted(unread - set(HSN_NOT_READ))}; or a named one is now read / gone (shrink-only list): "
        f"{sorted(set(HSN_NOT_READ) - unread)}")
