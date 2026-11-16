"""Migration 615, proved against real PostgreSQL: a credit or debit note carries GST compensation cess (POST-A-058).

WHAT WAS WRONG
    Migration 374 gave the invoice and the bill a compensation cess and not the four s.34 note tables, so a note against a cess-bearing
    document adjusted the value and the GST and left the cess. And the function every note's first save goes through
    (`numbered_document_atomic__unguarded`, last defined by migration 576) inserts its lines with a FIXED column list, so a cess the
    API put on a note line would have been dropped there without an error even once the columns existed.

WHAT THIS HOLDS
    * THE CASE, for each of the four note kinds: the call the API makes stores both limbs and the derived cess on the line; the same call
      through the function as 576 left it stores none of them (the negative control: the test sees the hole); the header stores its
      cess from the keys it is given;
    * a line or header that names no cess stores 0, and every column the function stored before it still stores;
    * the eight columns are NOT NULL, default 0 and refuse a negative value;
    * the function's attributes are 576's (SECURITY DEFINER, its search path, no EXECUTE for a signed-in role);
    * the rollback restores 576's text and drops the columns, and the file can be run again.

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
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_STEM = "615_a_credit_or_debit_note_carries_compensation_cess"
FILE, ROLLBACK = MIGRATIONS / f"{_STEM}.sql", MIGRATIONS / f"{_STEM}_rollback.sql"
BEFORE = MIGRATIONS / "576_a_credit_or_debit_note_line_keeps_its_unit_and_its_catalogue_item.sql"
FUNCTION = "public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text)"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the note-cess proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, PARTY, ITEM = (str(uuid.uuid4()) for _ in range(4))

#: (header table, header payload extra, lines table, the line table's foreign key)
KINDS = {
    "credit_notes": ("credit_notes", {"customer_id": PARTY, "credit_note_no": "CN-615-{n}", "credit_note_date": "2026-04-05"}, "credit_note_lines", "credit_note_id"),
    "debit_notes": ("debit_notes", {"vendor_id": PARTY, "debit_note_date": "2026-04-05"}, "debit_note_lines", "debit_note_id"),
    "purchase_credit_notes": ("purchase_credit_notes", {"vendor_id": PARTY, "credit_note_date": "2026-04-05"}, "purchase_credit_note_lines", "credit_note_id"),
    "sales_debit_notes": ("sales_debit_notes", {"customer_id": PARTY, "debit_note_no": "DN-615-{n}", "debit_note_date": "2026-04-05"}, "sales_debit_note_lines", "debit_note_id"),
}
CESS_COLUMNS = ("cess_rate_bps", "cess_specific_paise_per_unit", "cess_paise")


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql], capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _body(dsn: str) -> str:
    return _scalar(dsn, f"SELECT md5(prosrc) FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t615_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert not any(f.startswith("615_") for f in pg_template.failed), pg_template.failed
        yield f"{admin} dbname={name}"
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


_n = iter(range(1, 10_000))


def _record(dsn: str, kind: str, lines: list[dict], **header_extra) -> str:
    """The call the API makes: the wrapper, with a header the way the router builds it. Foreign keys are set aside (the parties are not the
    point), constraints and defaults are not. Returns the new note's id."""
    table, extra, lines_table, fk = KINDS[kind]
    n = next(_n)
    header = {"firm_id": FIRM, "client_id": CLIENT, **{k: (v.format(n=n) if isinstance(v, str) else v) for k, v in extra.items()},
              **header_extra}
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    r = _run(dsn, "SET session_replication_role = replica; "
                  f"SELECT public.numbered_document_atomic('{table}', '{j(header)}'::jsonb, '{lines_table}', '{j(lines)}'::jsonb, '{fk}');")
    assert r.returncode == 0, r.stderr
    return _scalar(dsn, f"SELECT id FROM {table} ORDER BY created_at DESC, id LIMIT 1;")


def _lines(dsn: str, kind: str, note: str) -> list[dict]:
    _table, _extra, lines_table, fk = KINDS[kind]
    out = _scalar(dsn, f"SELECT coalesce(json_agg(row_to_json(l) ORDER BY description), '[]'::json)::text FROM {lines_table} l WHERE {fk} = '{note}';")
    return json.loads(out)


LINE = {"description": "Aerated water", "hsn_sac": "2202", "quantity": 3, "unit": "BTL", "rate_paise": 100000, "gst_rate_bps": 1800,
        "taxable_amount_paise": 300000, "cgst_paise": 27000, "sgst_paise": 27000, "igst_paise": 0,
        "cess_rate_bps": 1200, "cess_specific_paise_per_unit": 400, "cess_paise": 37200,
        "line_total_paise": 391200, "service_catalogue_id": ITEM}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_note_kind_keeps_both_limbs_and_the_cess_of_its_lines_and_its_header(db, kind):
    note = _record(db, kind, [LINE], cess_paise=37200, total_paise=391200)
    (line,) = _lines(db, kind, note)
    assert tuple(line[c] for c in CESS_COLUMNS) == (1200, 400, 37200)
    assert (line["unit"], line["service_catalogue_id"], line["line_total_paise"], line["cgst_paise"]) == ("BTL", ITEM, 391200, 27000), \
        "a column the function always stored changed"
    table = KINDS[kind][0]
    assert _scalar(db, f"SELECT cess_paise FROM {table} WHERE id = '{note}';") == "37200"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_same_call_loses_the_cess_through_the_function_576_left_and_so_the_test_sees_the_hole(db, kind):
    """576's body, installed by its own file over a database that has 615's columns: the lines lose all three cess columns."""
    assert _file(db, BEFORE).returncode == 0
    note = _record(db, kind, [LINE])
    (line,) = _lines(db, kind, note)
    assert tuple(line[c] for c in CESS_COLUMNS) == (0, 0, 0), "the control must show the lines losing the cess"
    assert line["unit"] == "BTL" and line["line_total_paise"] == 391200


def test_a_line_and_a_header_that_name_no_cess_store_nil(db):
    note = _record(db, "credit_notes", [{"description": "absent"}, {"description": "null", "cess_rate_bps": None, "cess_paise": None}])
    for line in _lines(db, "credit_notes", note):
        assert tuple(line[c] for c in CESS_COLUMNS) == (0, 0, 0), line["description"]
        assert float(line["quantity"]) == 1.0 and line["rate_paise"] == 0, line["description"]
    assert _scalar(db, f"SELECT cess_paise FROM credit_notes WHERE id = '{note}';") == "0"


def test_the_eight_columns_are_not_null_default_nil_and_refuse_a_negative(db):
    rows = _scalar(db, """
        SELECT string_agg(table_name || '.' || column_name || ':' || is_nullable || ':' || column_default, ',' ORDER BY table_name, column_name)
          FROM information_schema.columns
         WHERE table_schema = 'public' AND column_name IN ('cess_paise', 'cess_rate_bps', 'cess_specific_paise_per_unit')
           AND table_name IN ('credit_notes', 'sales_debit_notes', 'debit_notes', 'purchase_credit_notes', 'credit_note_lines',
                              'sales_debit_note_lines', 'debit_note_lines', 'purchase_credit_note_lines');""").split(",")
    assert len(rows) == 16, rows
    assert all(r.endswith(":NO:0") for r in rows), rows
    for kind, (table, _extra, lines_table, _fk) in KINDS.items():
        note = _record(db, kind, [LINE])
        for column, where in ((f"{table}.cess_paise", f"UPDATE {table} SET cess_paise = -1 WHERE id = '{note}'"),
                              *((f"{lines_table}.{c}", f"UPDATE {lines_table} SET {c} = -1") for c in CESS_COLUMNS)):
            r = _run(db, f"SET session_replication_role = replica; {where};")
            assert r.returncode != 0 and "check constraint" in r.stderr, (column, r.stderr or "it succeeded")


def test_the_attributes_are_exactly_576s(db):
    assert _scalar(db, f"SELECT prosecdef::text || '|' || array_to_string(proconfig, ',') FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;") == \
        "true|search_path=public, pg_catalog"
    grantees = _scalar(db, f"SELECT string_agg(coalesce(NULLIF(a.grantee, 0)::regrole::text, 'PUBLIC'), ',' ORDER BY 1) "
                           f"FROM pg_proc p, aclexplode(p.proacl) a WHERE p.oid = '{FUNCTION}'::regprocedure;")
    assert grantees == "postgres,service_role", grantees
    for role in ("anon", "authenticated"):
        assert _scalar(db, f"SELECT has_function_privilege('{role}', '{FUNCTION}', 'EXECUTE');") == "f", role


def test_the_rollback_restores_576_and_drops_the_columns_and_the_file_can_be_run_again(db):
    assert _file(db, BEFORE).returncode == 0
    before = _body(db)
    assert _file(db, FILE).returncode == 0
    mine = _body(db)
    assert mine != before
    assert _file(db, FILE).returncode == 0 and _body(db) == mine, "running the file twice changed the function"
    assert _file(db, ROLLBACK).returncode == 0 and _body(db) == before, "the rollback is not 576's function"
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND column_name IN ('cess_paise', 'cess_rate_bps', 'cess_specific_paise_per_unit') "
                       "AND table_name IN ('credit_notes', 'credit_note_lines', 'debit_notes', 'debit_note_lines');") == "0"
    assert _file(db, FILE).returncode == 0 and _body(db) == mine, "the file does not apply again after its rollback"
