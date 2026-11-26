"""Migration 685, proved against real PostgreSQL: a purchase note line says whether its input credit is blocked (POST-A-459).

WHAT WAS WRONG
    A purchase bill line carries CGST Act s.17(5)'s blocked mark (migration 240) and the two purchase-side s.34 notes did not, so a note
    against a blocked line moved the credit ledgers by its whole tax. And the function every note's first save goes through
    (`numbered_document_atomic__unguarded`, last defined by migration 615) inserts its lines with a FIXED column list, so a mark the API
    put on a note line would have been dropped there without an error even once the columns existed.

WHAT THIS HOLDS
    * for the two purchase notes: the call the API makes stores the mark and the reason on the line, and the header's four blocked heads;
      the same call through the function as 615 left it stores the line as eligible (the negative control: the test sees the hole);
    * a line that names no mark stores eligible with no reason, and the two sales notes (whose lines have no such columns) still save;
    * the ten columns are NOT NULL with their defaults (the reason is nullable) and the header heads refuse a negative value;
    * the function's attributes are 615's; the rollback restores 615's text and drops the columns, and the file can be run again.

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

_STEM = "685_a_purchase_note_line_says_whether_its_credit_is_blocked"
FILE, ROLLBACK = MIGRATIONS / f"{_STEM}.sql", MIGRATIONS / f"{_STEM}_rollback.sql"
BEFORE = MIGRATIONS / "615_a_credit_or_debit_note_carries_compensation_cess.sql"
FUNCTION = "public.numbered_document_atomic__unguarded(text, jsonb, text, jsonb, text)"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the note blocked-credit proof requires HARNESS_PG + psql",
)

FIRM, CLIENT, PARTY, ITEM = (str(uuid.uuid4()) for _ in range(4))

#: (header table, header payload extra, lines table, the line table's foreign key)
KINDS = {
    "credit_notes": ("credit_notes", {"customer_id": PARTY, "credit_note_no": "CN-685-{n}", "credit_note_date": "2026-04-05"}, "credit_note_lines", "credit_note_id"),
    "debit_notes": ("debit_notes", {"vendor_id": PARTY, "debit_note_date": "2026-04-05"}, "debit_note_lines", "debit_note_id"),
    "purchase_credit_notes": ("purchase_credit_notes", {"vendor_id": PARTY, "credit_note_date": "2026-04-05"}, "purchase_credit_note_lines", "credit_note_id"),
    "sales_debit_notes": ("sales_debit_notes", {"customer_id": PARTY, "debit_note_no": "DN-685-{n}", "debit_note_date": "2026-04-05"}, "sales_debit_note_lines", "debit_note_id"),
}
PURCHASE = ("debit_notes", "purchase_credit_notes")
HEADS = ("ineligible_itc_cgst_paise", "ineligible_itc_sgst_paise", "ineligible_itc_igst_paise", "ineligible_itc_cess_paise")


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
    name = f"t685_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        assert not any(f.startswith("685_") for f in pg_template.failed), pg_template.failed
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


LINE = {"description": "Club membership", "hsn_sac": "9995", "quantity": 1, "unit": "NOS", "rate_paise": 100000, "gst_rate_bps": 1800,
        "taxable_amount_paise": 100000, "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0, "line_total_paise": 118000,
        "service_catalogue_id": ITEM}
BLOCKED = {**LINE, "itc_eligible": False, "blocked_credit_reason": "17_5_b_club_membership"}


@pytest.mark.parametrize("kind", PURCHASE)
def test_a_purchase_note_keeps_the_mark_and_the_reason_of_its_lines_and_the_blocked_heads_of_its_header(db, kind):
    note = _record(db, kind, [BLOCKED, {**LINE, "description": "Stationery"}],
                   ineligible_itc_cgst_paise=9000, ineligible_itc_sgst_paise=9000)
    lines = _lines(db, kind, note)
    assert [(ln["description"], ln["itc_eligible"], ln["blocked_credit_reason"]) for ln in lines] == [
        ("Club membership", False, "17_5_b_club_membership"), ("Stationery", True, None)]
    assert lines[0]["cgst_paise"] == 9000 and lines[0]["unit"] == "NOS", "a column the function always stored changed"
    table = KINDS[kind][0]
    assert _scalar(db, f"SELECT {', '.join(HEADS)} FROM {table} WHERE id = '{note}';") == "9000|9000|0|0"


@pytest.mark.parametrize("kind", PURCHASE)
def test_the_same_call_loses_the_mark_through_the_function_615_left_and_so_the_test_sees_the_hole(db, kind):
    assert _file(db, BEFORE).returncode == 0
    note = _record(db, kind, [BLOCKED])
    (line,) = _lines(db, kind, note)
    assert (line["itc_eligible"], line["blocked_credit_reason"]) == (True, None), "the control must show the line losing its mark"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_line_that_names_no_mark_is_eligible_and_the_sales_notes_still_save(db, kind):
    note = _record(db, kind, [LINE])
    (line,) = _lines(db, kind, note)
    if kind in PURCHASE:
        assert (line["itc_eligible"], line["blocked_credit_reason"]) == (True, None)
        assert _scalar(db, f"SELECT {' + '.join(HEADS)} FROM {KINDS[kind][0]} WHERE id = '{note}';") == "0"
    else:
        assert "itc_eligible" not in line, "a sales note's line carries no input credit"


def test_the_columns_are_not_null_with_their_defaults_and_the_heads_refuse_a_negative(db):
    rows = _scalar(db, """
        SELECT string_agg(table_name || '.' || column_name || ':' || is_nullable || ':' || coalesce(column_default, '-'), ','
                          ORDER BY table_name, column_name)
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND column_name IN ('itc_eligible', 'blocked_credit_reason', 'ineligible_itc_cgst_paise', 'ineligible_itc_sgst_paise',
                               'ineligible_itc_igst_paise', 'ineligible_itc_cess_paise')
           AND table_name IN ('debit_notes', 'purchase_credit_notes', 'debit_note_lines', 'purchase_credit_note_lines');""").split(",")
    assert len(rows) == 12, rows
    for r in rows:
        if r.endswith(("blocked_credit_reason:YES:-",)):
            continue
        assert r.endswith((":NO:0", ":NO:true")), r
    for kind in PURCHASE:
        table = KINDS[kind][0]
        note = _record(db, kind, [LINE])
        for h in HEADS:
            r = _run(db, f"SET session_replication_role = replica; UPDATE {table} SET {h} = -1 WHERE id = '{note}';")
            assert r.returncode != 0 and "check constraint" in r.stderr, (h, r.stderr or "it succeeded")


def test_the_attributes_are_exactly_615s(db):
    assert _scalar(db, f"SELECT prosecdef::text || '|' || array_to_string(proconfig, ',') FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;") == \
        "true|search_path=public, pg_catalog"
    grantees = _scalar(db, f"SELECT string_agg(coalesce(NULLIF(a.grantee, 0)::regrole::text, 'PUBLIC'), ',' ORDER BY 1) "
                           f"FROM pg_proc p, aclexplode(p.proacl) a WHERE p.oid = '{FUNCTION}'::regprocedure;")
    assert grantees == "postgres,service_role", grantees
    for role in ("anon", "authenticated"):
        assert _scalar(db, f"SELECT has_function_privilege('{role}', '{FUNCTION}', 'EXECUTE');") == "f", role


def test_the_rollback_restores_615_and_drops_the_columns_and_the_file_can_be_run_again(db):
    assert _file(db, BEFORE).returncode == 0
    before = _body(db)
    assert _file(db, FILE).returncode == 0
    mine = _body(db)
    assert mine != before
    assert _file(db, FILE).returncode == 0 and _body(db) == mine, "running the file twice changed the function"
    assert _file(db, ROLLBACK).returncode == 0 and _body(db) == before, "the rollback is not 615's function"
    assert _scalar(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' "
                       "AND column_name IN ('itc_eligible', 'blocked_credit_reason', 'ineligible_itc_cgst_paise') "
                       "AND table_name IN ('debit_notes', 'purchase_credit_notes', 'debit_note_lines', 'purchase_credit_note_lines');") == "0"
    assert _file(db, FILE).returncode == 0 and _body(db) == mine, "the file does not apply again after its rollback"
