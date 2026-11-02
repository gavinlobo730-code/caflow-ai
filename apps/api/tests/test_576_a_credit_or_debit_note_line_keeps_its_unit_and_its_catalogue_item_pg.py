"""Migration 576, proved against real PostgreSQL: a credit or debit note line recorded through the numbering function keeps its unit and its
catalogue item (POST-A-370; the same defect as the receipt's, migrations 574 and 575).

WHAT WAS WRONG
    The four note kinds are recorded through `numbered_document_atomic` (body: `numbered_document_atomic__unguarded`, migration 167 renamed behind a
    caller check by 486). The header is inserted from the keys the caller sends, so a new header column is stored; the LINES are inserted with a fixed
    column list written before the note routers began sending `unit` (they send `ln.get("unit") or "NOS"`) and `service_catalogue_id`, and all four
    line tables carry both columns, so both were dropped without an error. On production (read 2-11-2026) none of the six note lines had either.
    A note line without a unit reaches the GSTR-1 HSN summary as the fallback code OTH.

WHAT THIS HOLDS
    * THE CASE, for each of the four note kinds: the call the API makes stores the unit and the catalogue item on the line; the same call through the
      ROLLED-BACK function stores neither (the negative control: the test sees the hole);
    * absent and blank values are NULL; every other column the function stored it still stores, with its old defaults (quantity 1, the amounts 0);
    * the attributes are exactly the previous function's (SECURITY DEFINER, its search path, no EXECUTE for a signed-in role), the rollback restores
      the text production held (md5 pinned) and the file can be run again.

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

_STEM = "576_a_credit_or_debit_note_line_keeps_its_unit_and_its_catalogue_item"
FILE, ROLLBACK = MIGRATIONS / f"{_STEM}.sql", MIGRATIONS / f"{_STEM}_rollback.sql"
#: What production held before 576 (read on 2-11-2026).
PRODUCTION_BEFORE_576 = ("ebae3374c33ddfc6e67ccceeadbc1948", 1376)
FUNCTION = "public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text)"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the note-line proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, PARTY, ITEM = (str(uuid.uuid4()) for _ in range(4))

#: (header table, header payload extra, lines table, the line table's foreign key)
KINDS = {
    "credit_notes": ("credit_notes", {"customer_id": PARTY, "credit_note_no": "CN-576-{n}", "credit_note_date": "2026-04-05"}, "credit_note_lines", "credit_note_id"),
    "debit_notes": ("debit_notes", {"vendor_id": PARTY, "debit_note_date": "2026-04-05"}, "debit_note_lines", "debit_note_id"),
    "purchase_credit_notes": ("purchase_credit_notes", {"vendor_id": PARTY, "credit_note_date": "2026-04-05"}, "purchase_credit_note_lines", "credit_note_id"),
    "sales_debit_notes": ("sales_debit_notes", {"customer_id": PARTY, "debit_note_no": "DN-576-{n}", "debit_note_date": "2026-04-05"}, "sales_debit_note_lines", "debit_note_id"),
}


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql], capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _body(dsn: str) -> tuple[str, int]:
    digest, length = _scalar(dsn, f"SELECT md5(prosrc) || '|' || length(prosrc) FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;").split("|")
    return digest, int(length)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t576_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert not any(f.startswith("576_") for f in pg_template.failed), pg_template.failed
        yield f"{admin} dbname={name}"
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


_n = iter(range(1, 10_000))


def _record(dsn: str, kind: str, lines: list[dict]) -> str:
    """The call the API makes: the wrapper, with a header the way the router builds it. Foreign keys are set aside (the parties are not the
    point), constraints and defaults are not. Returns the new note's id."""
    table, extra, lines_table, fk = KINDS[kind]
    n = next(_n)
    header = {"firm_id": FIRM, "client_id": CLIENT, **{k: (v.format(n=n) if isinstance(v, str) else v) for k, v in extra.items()}}
    j = lambda x: json.dumps(x).replace("'", "''")          # noqa: E731
    r = _run(dsn, "SET session_replication_role = replica; "
                  f"SELECT public.numbered_document_atomic('{table}', '{j(header)}'::jsonb, '{lines_table}', '{j(lines)}'::jsonb, '{fk}');")
    assert r.returncode == 0, r.stderr
    return _scalar(dsn, f"SELECT id FROM {table} ORDER BY created_at DESC, id LIMIT 1;")


def _lines(dsn: str, kind: str, note: str) -> list[dict]:
    table, _extra, lines_table, fk = KINDS[kind]
    out = _scalar(dsn, f"SELECT coalesce(json_agg(row_to_json(l) ORDER BY description), '[]'::json)::text FROM {lines_table} l WHERE {fk} = '{note}';")
    return json.loads(out)


LINE = {"description": "Widget", "hsn_sac": "8479", "quantity": 2, "unit": "KGS", "rate_paise": 5000, "gst_rate_bps": 1800,
        "taxable_amount_paise": 10000, "cgst_paise": 900, "sgst_paise": 900, "igst_paise": 0, "line_total_paise": 11800, "service_catalogue_id": ITEM}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_note_kind_keeps_the_unit_and_the_catalogue_item_of_its_lines(db, kind):
    note = _record(db, kind, [LINE])
    (line,) = _lines(db, kind, note)
    assert (line["unit"], line["service_catalogue_id"]) == ("KGS", ITEM)
    assert (line["description"], line["hsn_sac"], float(line["quantity"]), line["rate_paise"], line["gst_rate_bps"], line["line_total_paise"]) == \
        ("Widget", "8479", 2.0, 5000, 1800, 11800), "a column the function always stored changed"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_same_call_loses_both_through_the_function_before_576_and_so_the_test_sees_the_hole(db, kind):
    assert _file(db, ROLLBACK).returncode == 0
    note = _record(db, kind, [LINE])
    (line,) = _lines(db, kind, note)
    assert (line["unit"], line["service_catalogue_id"]) == (None, None), "the control must show the lines losing both"
    assert line["hsn_sac"] == "8479" and line["line_total_paise"] == 11800


def test_absent_and_blank_values_are_null_and_the_old_defaults_stand(db):
    note = _record(db, "credit_notes", [
        {"description": "blank", "unit": "", "service_catalogue_id": ""},
        {"description": "absent"},
        {"description": "null", "unit": None, "service_catalogue_id": None},
    ])
    lines = {l["description"]: l for l in _lines(db, "credit_notes", note)}
    for name in ("blank", "absent", "null"):
        assert (lines[name]["unit"], lines[name]["service_catalogue_id"]) == (None, None), name
        assert float(lines[name]["quantity"]) == 1.0 and lines[name]["rate_paise"] == 0 and lines[name]["line_total_paise"] == 0, name


def _real_rows(dsn: str) -> None:
    """A firm, a client, a customer and one catalogue item of that client, WITH foreign keys enforced (the other tests set them aside)."""
    r = _run(dsn, f"""
      INSERT INTO firms (id, name, email) VALUES ('{FIRM}','576 Firm','f576@test.in');
      INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','576 Client','Private Limited');
      INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{PARTY}','{FIRM}','{CLIENT}','576 Customer');
      INSERT INTO service_catalogue (id, firm_id, client_id, name, kind) VALUES ('{ITEM}','{FIRM}','{CLIENT}','576 Widget','good');""")
    assert r.returncode == 0, r.stderr


def _credit_note_call(dsn: str, number: str, item: str) -> subprocess.CompletedProcess:
    header = {"firm_id": FIRM, "client_id": CLIENT, "customer_id": PARTY, "credit_note_no": number, "credit_note_date": "2026-04-05"}
    return _run(dsn, f"SELECT public.numbered_document_atomic('credit_notes', '{json.dumps(header)}'::jsonb, 'credit_note_lines', "
                     f"'{json.dumps([{'description': 'x', 'service_catalogue_id': item}])}'::jsonb, 'credit_note_id');")


def test_a_catalogue_item_that_is_no_item_is_refused_by_the_key_and_the_note_is_not_left_behind(db):
    """With a real firm, client and customer, so the ONLY thing wrong is the item (an earlier version of this test used a firm that exists in no
    table, failed on the header's key instead and passed against the old function too). The whole call fails together, header and lines."""
    _real_rows(db)
    good = _credit_note_call(db, "CN-576-GOOD", ITEM)
    assert good.returncode == 0, good.stderr
    assert _scalar(db, "SELECT count(*) FROM credit_note_lines WHERE service_catalogue_id IS NOT NULL;") == "1", "the control: a real item is stored"
    bad = _credit_note_call(db, "CN-576-KEY", str(uuid.uuid4()))
    assert bad.returncode != 0 and "credit_note_lines_service_catalogue_id_fkey" in bad.stderr, bad.stderr or "it succeeded"
    assert _scalar(db, "SELECT count(*) FROM credit_notes WHERE credit_note_no = 'CN-576-KEY';") == "0", "the header was left behind"


@pytest.mark.parametrize("kind", ["sales_debit_notes", "purchase_credit_notes"])
def test_two_of_the_four_line_tables_have_no_key_on_the_catalogue_item_and_that_is_a_known_limit(db, kind):
    """Migration 210 declared the column bare on these two (189 gave the other two a key with ON DELETE SET NULL), so an id that names no item is
    stored. The API refuses it first; this pins the limit the migration's header and the design record state, so a key added later turns this red and
    the wording is changed with it."""
    ghost = str(uuid.uuid4())
    note = _record(db, kind, [{"description": "x", "service_catalogue_id": ghost}])
    (line,) = _lines(db, kind, note)
    assert line["service_catalogue_id"] == ghost


def test_the_attributes_are_exactly_the_previous_functions(db):
    assert _scalar(db, f"SELECT prosecdef::text || '|' || array_to_string(proconfig, ',') FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;") == \
        "true|search_path=public, pg_catalog"
    grantees = _scalar(db, f"SELECT string_agg(coalesce(NULLIF(a.grantee, 0)::regrole::text, 'PUBLIC'), ',' ORDER BY 1) "
                           f"FROM pg_proc p, aclexplode(p.proacl) a WHERE p.oid = '{FUNCTION}'::regprocedure;")
    assert grantees == "postgres,service_role", grantees
    for role in ("anon", "authenticated"):
        assert _scalar(db, f"SELECT has_function_privilege('{role}', '{FUNCTION}', 'EXECUTE');") == "f", role


def test_the_rollback_restores_the_text_production_held_and_the_file_can_be_run_again(db):
    """Compared with this file's own body, installed by the file, so a later migration that redefines the function does not break this test."""
    assert _file(db, ROLLBACK).returncode == 0 and _body(db) == PRODUCTION_BEFORE_576, "the rollback is not the function production held before 576"
    assert _file(db, FILE).returncode == 0
    mine = _body(db)
    assert mine != PRODUCTION_BEFORE_576
    assert _file(db, FILE).returncode == 0 and _body(db) == mine, "running the file twice changed the function"
    assert _file(db, ROLLBACK).returncode == 0 and _body(db) == PRODUCTION_BEFORE_576, "the rollback does not undo a second run"
