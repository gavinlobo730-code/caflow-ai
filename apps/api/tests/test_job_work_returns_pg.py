"""Migration 462 — goods that come back from a job worker in lots, on real
PostgreSQL (GST-30).

WHY THIS NEEDS A REAL DATABASE. The decisions in the migration are CONSTRAINTS
and grants rather than code, and none of them is observable in mock mode, where
the in-memory double accepts anything:

  * a return that returns nothing AND wastes nothing is refused, while a return
    that only records waste is allowed (the form has a column for it);
  * quantities are NUMERIC(10,3), the column every quantity in this schema is,
    and neither may be negative;
  * the job worker's own challan, its date and the nature of the work are
    NULLABLE with NO default — NULL is "not recorded", never "none", and the
    ITC-04 statement names each return still missing one;
  * NO balance is stored: what is outstanding is the line's quantity less its
    returns, derived on every read (migration 278's reasoning);
  * the grant model — the browser may read, only the service role writes — and
    the RESTRICTIVE assignment-scope policy migration 084's loop has never
    applied to a table created since (see 370);
  * the migration is additive and idempotent, and its rollback REFUSES while a
    challan is part returned, because dropping the returns would make it read as
    having nothing returned and CGST s.143(3) would then deem the whole of it
    supplied on the day it left.

Runs only when HARNESS_PG is set + psql on PATH, like every other *_pg test.
"""
from __future__ import annotations

import os
import pathlib
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
TABLE = "delivery_challan_returns"

_MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations"
_UP = _MIGRATIONS / "462_job_work_comes_back_in_lots_and_itc_04_reports_each_return.sql"
_DOWN = _MIGRATIONS / ("462_job_work_comes_back_in_lots_and_itc_04_reports_each_return"
                       "_rollback.sql")


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _run_file(dsn: str, path: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"],
                          input=path.read_text(encoding="utf-8"),
                          capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line for line in r.stdout.strip().splitlines() if line]


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"jobwork_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn,
             f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
            VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _challan(dsn: str, no: str = "JW/1", status: str = "issued") -> tuple[str, str]:
    """A job-work challan with one line of ten. Returns (challan_id, line_id)."""
    cid, lid = str(uuid.uuid4()), str(uuid.uuid4())
    r = _psql(dsn, f"""
        INSERT INTO delivery_challans
          (id, firm_id, client_id, document_no, document_date, reason, status, goods_kind)
        VALUES ('{cid}', '{FIRM}', '{CLIENT}', '{no}', DATE '2026-05-10',
                'job_work', '{status}', 'inputs');
        INSERT INTO delivery_challan_lines
          (id, firm_id, client_id, challan_id, description, quantity, unit)
        VALUES ('{lid}', '{FIRM}', '{CLIENT}', '{cid}', 'Steel bar', 10, 'NOS');
    """)
    assert r.returncode == 0, r.stderr
    return cid, lid


def _came_back(dsn: str, cid: str, lid: str, *, returned="4", wasted="0",
               jw_no="'JW/22'", on="2026-08-20") -> subprocess.CompletedProcess:
    return _psql(dsn, f"""
        INSERT INTO delivery_challan_returns
          (firm_id, client_id, challan_id, challan_line_id, returned_on,
           quantity_returned, quantity_lost_or_wasted, job_worker_challan_no)
        VALUES ('{FIRM}', '{CLIENT}', '{cid}', '{lid}', DATE '{on}',
                {returned}, {wasted}, {jw_no});
    """)


# ── the table, its security and its grants ───────────────────────────────────

def test_the_table_exists_with_row_level_security_on(db):
    assert _rows(db, f"SELECT to_regclass('public.{TABLE}');") == [TABLE]
    assert _rows(db, f"SELECT relrowsecurity FROM pg_class "
                     f"WHERE oid = 'public.{TABLE}'::regclass;") == ["t"]


def test_the_browser_may_read_and_may_not_write(db):
    granted = set(_rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{TABLE}'
           AND grantee = 'authenticated';"""))
    assert granted == {"SELECT"}, granted
    service = set(_rows(db, f"""
        SELECT privilege_type FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name = '{TABLE}'
           AND grantee = 'service_role';"""))
    assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= service


def test_the_table_is_assignment_scoped_by_a_restrictive_policy_for_all_commands(db):
    """Migration 084's loop has never run again (see 370), so a `client_id`
    table created now is firm-wide unless it says otherwise: an unassigned
    Manager could read another client's job-work movements."""
    rows = _rows(db, f"""
        SELECT polname || '|' || polcmd::text || '|' || polpermissive::text || '|' ||
               (pg_get_expr(polqual, polrelid) ILIKE '%can_access_client%')::text || '|' ||
               (pg_get_expr(polwithcheck, polrelid) ILIKE '%can_access_client%')::text
          FROM pg_policy
         WHERE polrelid = 'public.{TABLE}'::regclass
           AND polname = '{TABLE}_assignment_scope';""")
    # polcmd '*' is FOR ALL; polpermissive false is RESTRICTIVE; USING and
    # WITH CHECK both ask can_access_client.
    assert rows == [f"{TABLE}_assignment_scope|*|false|true|true"], rows


def test_a_firm_wide_read_policy_exists_beside_it(db):
    assert _rows(db, f"""
        SELECT polname FROM pg_policy
         WHERE polrelid = 'public.{TABLE}'::regclass AND polpermissive = true;
    """) == [f"firm_staff_read_{TABLE}"]


# ── what is stored, and what is not ──────────────────────────────────────────

def test_quantities_are_numeric_10_3(db):
    for col in ("quantity_returned", "quantity_lost_or_wasted"):
        assert _rows(db, f"""
            SELECT data_type || '|' || numeric_precision || '|' || numeric_scale
              FROM information_schema.columns
             WHERE table_name = '{TABLE}' AND column_name = '{col}';
        """) == ["numeric|10|3"], col


def test_no_outstanding_balance_is_stored(db):
    cols = set(_rows(db, f"""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = '{TABLE}';"""))
    assert not {c for c in cols if "outstanding" in c or "balance" in c or "remaining" in c}, cols
    assert {"quantity_returned", "quantity_lost_or_wasted", "returned_on"} <= cols


@pytest.mark.parametrize("col", ["job_worker_challan_no", "job_worker_challan_date",
                                 "nature_of_job_work"])
def test_the_job_workers_particulars_are_nullable_with_no_default(db, col):
    """NULL is 'not recorded', never 'none': the statement names each return
    still missing one instead of printing a blank into the form's column."""
    assert _rows(db, f"""
        SELECT is_nullable || '|' || coalesce(column_default, '-')
          FROM information_schema.columns
         WHERE table_name = '{TABLE}' AND column_name = '{col}';
    """) == ["YES|-"]


def test_a_return_with_no_job_worker_challan_can_be_recorded(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid, jw_no="NULL").returncode == 0


def test_a_blank_job_worker_challan_number_is_refused(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid, jw_no="'   '").returncode != 0


# ── the CHECKs ───────────────────────────────────────────────────────────────

def test_a_return_that_returns_nothing_and_wastes_nothing_is_refused(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid, returned="0", wasted="0").returncode != 0


def test_a_return_that_only_records_waste_is_allowed(db):
    """The form has a column for it, and a lot can arrive as scrap alone."""
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid, returned="0", wasted="2").returncode == 0


@pytest.mark.parametrize("returned,wasted", [("-1", "2"), ("3", "-1")])
def test_a_negative_quantity_is_refused(db, returned, wasted):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid, returned=returned, wasted=wasted).returncode != 0


def test_a_return_must_name_a_real_challan_line(db):
    cid, _ = _challan(db)
    assert _came_back(db, cid, str(uuid.uuid4())).returncode != 0


def test_deleting_a_challan_takes_its_returns_with_it(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid).returncode == 0
    assert _psql(db, f"DELETE FROM delivery_challans WHERE id = '{cid}';").returncode == 0
    assert _rows(db, f"SELECT count(*) FROM {TABLE};") == ["0"]


def test_the_statement_reads_a_window_of_returns_through_an_index(db):
    assert _rows(db, f"""
        SELECT indexdef FROM pg_indexes
         WHERE schemaname = 'public' AND tablename = '{TABLE}'
           AND indexname = 'idx_delivery_challan_returns_client_date';
    """), "the (firm, client, returned_on) index is gone"


# ── additive and idempotent ──────────────────────────────────────────────────

def test_the_migration_applies_twice_and_changes_nothing_the_second_time(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid).returncode == 0
    r = _run_file(db, _UP)
    assert r.returncode == 0, r.stderr
    assert _rows(db, f"SELECT count(*) FROM {TABLE};") == ["1"], (
        "re-applying the migration must not touch a recorded return")


def test_the_migration_touches_no_existing_table(db):
    src = _UP.read_text(encoding="utf-8")
    assert "ALTER TABLE public.delivery_challans" not in src
    assert "ALTER TABLE public.delivery_challan_lines" not in src
    assert "DROP TABLE" not in src


# ── the rollback refuses while a clock is running on part-returned goods ─────

def test_the_rollback_refuses_while_a_challan_is_part_returned(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid).returncode == 0       # 4 of 10 are back
    r = _run_file(db, _DOWN)
    assert r.returncode != 0, "the rollback ran with part-returned goods still out"
    assert "Refusing to roll back 462" in r.stderr
    assert _rows(db, f"SELECT to_regclass('public.{TABLE}');") == [TABLE]
    assert _rows(db, f"SELECT count(*) FROM {TABLE};") == ["1"]


def test_the_rollback_runs_once_the_challan_is_marked_received_back(db):
    cid, lid = _challan(db)
    assert _came_back(db, cid, lid).returncode == 0
    assert _psql(db, f"""
        UPDATE delivery_challans SET received_back_on = DATE '2026-09-01',
               status = 'received_back' WHERE id = '{cid}';""").returncode == 0
    r = _run_file(db, _DOWN)
    assert r.returncode == 0, r.stderr
    assert _rows(db, f"SELECT to_regclass('public.{TABLE}');") in ([], [""])


def test_the_rollback_runs_when_nothing_was_ever_returned(db):
    _challan(db)
    r = _run_file(db, _DOWN)
    assert r.returncode == 0, r.stderr
