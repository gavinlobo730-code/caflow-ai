"""Migration 387 — the physical count's two tables, on real PostgreSQL
(INV-08).

WHY THIS NEEDS A REAL DATABASE. Three of the design decisions are constraints
rather than code: the PARTIAL unique index that allows only one OPEN sheet per
client per date (and deliberately not one posted or abandoned), the
nullability that makes an uncounted line and an undecided s.17(5)(h) refusable
rather than defaulted, and the grant model. None of it is observable in mock
mode, where the in-memory double accepts anything.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
ITEM = "33333333-3333-3333-3333-333333333333"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [l for l in r.stdout.strip().splitlines() if l]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"count_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
            INSERT INTO service_catalogue (id, firm_id, client_id, name, kind)
            VALUES ('{ITEM}', '{FIRM}', '{CLIENT}', 'Widget', 'good');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _session(dsn, *, status="open", date="2026-03-31", ref="PC-1"):
    return _psql(dsn, f"""
        INSERT INTO stock_count_sessions (firm_id, client_id, count_date, reference_no, status)
        VALUES ('{FIRM}', '{CLIENT}', DATE '{date}', '{ref}', '{status}');
    """)


def _line(dsn, session_id, **cols):
    base = {"firm_id": f"'{FIRM}'", "client_id": f"'{CLIENT}'",
            "session_id": f"'{session_id}'", "service_catalogue_id": f"'{ITEM}'"}
    base.update(cols)
    return _psql(dsn, "INSERT INTO stock_count_lines (" + ", ".join(base) + ") VALUES ("
                 + ", ".join(base.values()) + ");")


def _one_session(dsn) -> str:
    assert _session(dsn).returncode == 0
    return _rows(dsn, "SELECT id FROM stock_count_sessions LIMIT 1;")[0]


# ── the sheet ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["open", "posted", "abandoned"])
def test_every_status_the_engine_knows_is_accepted(db, status):
    assert _session(db, status=status).returncode == 0


@pytest.mark.parametrize("status", ["draft", "OPEN", ""])
def test_a_status_the_engine_does_not_know_is_refused(db, status):
    assert _session(db, status=status).returncode != 0


def test_the_status_check_accepts_exactly_the_engines_vocabulary(db):
    from domain.inventory import count_session as cs
    definition = _rows(db, """
        SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'public.stock_count_sessions'::regclass
           AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%status%';
    """)
    assert definition, "the status CHECK is gone"
    assert set(re.findall(r"'([^']*)'", definition[0])) == set(cs.STATUSES)


def test_a_blank_reference_is_refused(db):
    """It is what ties the hundred adjustments to the count."""
    assert _session(db, ref="   ").returncode != 0


def test_only_one_OPEN_sheet_per_client_per_date(db):
    assert _session(db).returncode == 0
    assert _session(db, ref="PC-2").returncode != 0, (
        "two open sheets would post two sets of variances for one stock-take")


def test_a_posted_sheet_does_not_block_a_recount(db):
    """The index is narrowed to the open ones on purpose: an abandoned sheet
    must not block a redo, and a posted one stays on the record."""
    assert _session(db, status="posted").returncode == 0
    assert _session(db, status="abandoned", ref="PC-2").returncode == 0
    assert _session(db, ref="PC-3").returncode == 0


# ── the lines ───────────────────────────────────────────────────────────────

def test_an_uncounted_line_and_an_undecided_reversal_are_both_null(db):
    """NULL means the CA has not answered, and neither zero nor false may
    stand in for that: a zero count writes the item's stock off, and a false
    reversal claims a s.17(5)(h) judgement nobody made."""
    s = _one_session(db)
    assert _line(db, s).returncode == 0
    assert _rows(db, "SELECT counted_qty_units IS NULL, reverse_itc IS NULL "
                     "FROM stock_count_lines;") == ["t|t"]


def test_a_counted_zero_is_kept_as_zero(db):
    s = _one_session(db)
    assert _line(db, s, counted_qty_units="0").returncode == 0
    assert _rows(db, "SELECT counted_qty_units FROM stock_count_lines;") == ["0.000"]


def test_three_decimals_are_kept(db):
    s = _one_session(db)
    assert _line(db, s, counted_qty_units="7.125").returncode == 0
    assert _rows(db, "SELECT counted_qty_units FROM stock_count_lines;") == ["7.125"]


def test_one_line_per_item_per_sheet(db):
    s = _one_session(db)
    assert _line(db, s).returncode == 0
    assert _line(db, s).returncode != 0, "an item cannot be counted twice on one sheet"


def test_the_lines_go_with_the_sheet(db):
    s = _one_session(db)
    assert _line(db, s).returncode == 0
    assert _psql(db, f"DELETE FROM stock_count_sessions WHERE id = '{s}';").returncode == 0
    assert _rows(db, "SELECT count(*) FROM stock_count_lines;") == ["0"]


def test_no_variance_column_exists_on_either_table(db):
    """It is a function of the count date's position, which moves."""
    cols = _rows(db, """
        SELECT table_name || '.' || column_name FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name IN ('stock_count_sessions','stock_count_lines');
    """)
    assert not [c for c in cols if "variance" in c], cols


# ── the guards ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["stock_count_sessions", "stock_count_lines"])
def test_the_browser_gets_select_and_nothing_else(db, table):
    got = _rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='{table}'
           AND grantee='authenticated' ORDER BY privilege_type;
    """)
    assert got == ["SELECT"], got


@pytest.mark.parametrize("table", ["stock_count_sessions", "stock_count_lines"])
def test_row_level_security_is_on_and_the_table_is_assignment_scoped(db, table):
    assert _rows(db, f"SELECT relrowsecurity FROM pg_class "
                     f"WHERE oid = 'public.{table}'::regclass;") == ["t"]
    got = _rows(db, f"""
        SELECT policyname || '|' || permissive FROM pg_policies
         WHERE schemaname='public' AND tablename='{table}' ORDER BY policyname;
    """)
    assert f"{table}_assignment_scope|RESTRICTIVE" in got, got
