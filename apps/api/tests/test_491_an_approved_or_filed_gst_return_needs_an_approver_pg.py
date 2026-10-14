"""Migration 491 — an approved or filed GST return changes only in the hands of someone who may approve GST returns.

THE BUG THIS PINS (ledger POST-A-223 and POST-A-224)
    `gstr1_returns` and `gstr3b_returns` take their writes from anyone with `gst:compute` (Executive). The API reserves
    APPROVING a return and RECORDING IT AS FILED to `gst:approve` (Manager) and refuses to delete a filed one, but a row
    policy cannot see a TRANSITION, so with their own sign-in an Executive could approve a return, mark one filed with an
    ARN (no `filings` row, so no period lock), reopen an approved or filed one, rewrite an approved payload and delete a
    filed return. What a row policy CAN see is the status a row has and the status it is given, which is what the
    migration asks.

WHAT IS ASSERTED, FOR BOTH TABLES, AS A REAL AUTHENTICATED SESSION
    * an Executive prepares: inserts a draft, moves it to validated and back, deletes their draft;
    * an Executive can NOT give a return `ca_approved` or `submitted`, insert one in either state, touch a return that
      is ALREADY in either state (the UPDATE finds zero rows), or delete one;
    * a Manager and a Partner approve, reopen and delete an approved return; NOBODY signed in deletes a submitted one;
    * the per-person grid counts both ways: an Executive the grid GRANTS `gst:approve` approves, and a Manager it DENIES
      cannot;
    * the migration is idempotent;
    * its own rollback puts the hole back, which is the negative control that makes the rest mean something.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
MIGRATIONS = API_ROOT / "migrations"
MIGRATION = MIGRATIONS / "491_an_approved_or_filed_gst_return_changes_only_in_the_hands_of_someone_who_may_approve.sql"
ROLLBACK = MIGRATIONS / "491_an_approved_or_filed_gst_return_changes_only_in_the_hands_of_someone_who_may_approve_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the GST return state-tier proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000491"
CLIENT = "cccccccc-0000-0000-0000-00000000a491"
GSTIN = "27AAPFU0939F1ZV"
TABLES = ("gstr1_returns", "gstr3b_returns")

#: who -> (role, grid decision on gst:approve or None)
ACTORS = {
    "partner": ("Partner", None),
    "manager": ("Manager", None),
    "manager_denied": ("Manager", False),
    "executive": ("Executive", None),
    "executive_granted": ("Executive", True),
}
AUTH = {k: f"11111111-1111-1111-1111-{i:012d}" for i, k in enumerate(ACTORS, start=1)}
USER = {k: f"bbbbbbbb-1111-1111-1111-{i:012d}" for i, k in enumerate(ACTORS, start=1)}

DRAFT, APPROVED, SUBMITTED = "012026", "022026", "032026"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _changed(dsn: str, who: str, table: str, set_clause: str, period: str) -> int:
    """Rows an UPDATE reached, as `who`; an error counts as a test failure only when the caller expects none."""
    r = _as(dsn, who, f"WITH u AS (UPDATE {table} SET {set_clause} WHERE period = '{period}' RETURNING 1) "
                      "SELECT count(*) FROM u;")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _refused(dsn: str, who: str, table: str, set_clause: str, period: str) -> bool:
    """True when row security REFUSED the new row (an error), as opposed to finding nothing to change."""
    r = _as(dsn, who, f"UPDATE {table} SET {set_clause} WHERE period = '{period}';")
    return r.returncode != 0 and "row-level security" in r.stderr


def _deleted(dsn: str, who: str, table: str, period: str) -> int:
    r = _as(dsn, who, f"WITH d AS (DELETE FROM {table} WHERE period = '{period}' RETURNING 1) SELECT count(*) FROM d;")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _insert(dsn: str, who: str, table: str, period: str, status: str) -> subprocess.CompletedProcess:
    return _as(dsn, who, f"INSERT INTO {table} (firm_id, client_id, period, gstin, status) "
                         f"VALUES ('{FIRM}', '{CLIENT}', '{period}', '{GSTIN}', '{status}');")


def _reseed(dsn: str, table: str) -> None:
    _ok(dsn, f"""
        DELETE FROM {table};
        INSERT INTO {table} (firm_id, client_id, period, gstin, status) VALUES
          ('{FIRM}', '{CLIENT}', '{DRAFT}', '{GSTIN}', 'draft'),
          ('{FIRM}', '{CLIENT}', '{APPROVED}', '{GSTIN}', 'ca_approved'),
          ('{FIRM}', '{CLIENT}', '{SUBMITTED}', '{GSTIN}', 'submitted');""")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"gststate_m491_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m491.test')" for k, v in AUTH.items())
        users = ", ".join(f"('{USER[k]}', '{FIRM}', '{AUTH[k]}', '{k}@m491.test', '{k}', '{role}', true)"
                          for k, (role, _g) in ACTORS.items())
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT}')" for k in ACTORS)
        grid = ", ".join(f"('{FIRM}', '{USER[k]}', 'gst', 'approve', {str(g).lower()})"
                         for k, (_r, g) in ACTORS.items() if g is not None)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M491 Firm','m491@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) VALUES {grid};
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _apply(dsn: str, path: Path) -> None:
    r = _psql(dsn, path.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr


# ── the executive prepares, and cannot approve, file, reopen or delete ──────────────────────────
@pytest.mark.parametrize("table", TABLES)
def test_an_executive_prepares_a_draft(db, table):
    _reseed(db, table)
    assert _insert(db, "executive", table, "042026", "draft").returncode == 0
    assert _changed(db, "executive", table, "status = 'validated'", DRAFT) == 1
    assert _changed(db, "executive", table, "status = 'draft'", DRAFT) == 1
    assert _deleted(db, "executive", table, DRAFT) == 1


@pytest.mark.parametrize("table", TABLES)
def test_an_executive_cannot_approve_or_file_a_return(db, table):
    _reseed(db, table)
    assert _refused(db, "executive", table, "status = 'ca_approved', ca_approved_by = NULL", DRAFT)
    assert _refused(db, "executive", table, "status = 'submitted', arn = 'AA270126123456A'", DRAFT)
    assert _ok(db, f"SELECT status FROM {table} WHERE period = '{DRAFT}';") == "draft"
    for status in ("ca_approved", "submitted"):
        r = _insert(db, "executive", table, "042026", status)
        assert r.returncode != 0 and "row-level security" in r.stderr, status


@pytest.mark.parametrize("table", TABLES)
def test_an_executive_cannot_touch_a_return_that_is_already_approved_or_filed(db, table):
    _reseed(db, table)
    for period in (APPROVED, SUBMITTED):
        assert _changed(db, "executive", table, "status = 'draft'", period) == 0, f"reopened {period}"
        assert _changed(db, "executive", table, "updated_at = now()", period) == 0, f"rewrote {period}"
        assert _deleted(db, "executive", table, period) == 0, f"deleted {period}"
    assert _ok(db, f"SELECT string_agg(status, ',' ORDER BY period) FROM {table};") == "draft,ca_approved,submitted"


# ── the approvers ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("who", ["partner", "manager", "executive_granted"])
def test_someone_who_may_approve_approves_reopens_and_deletes_an_approved_return(db, table, who):
    _reseed(db, table)
    assert _changed(db, who, table, "status = 'ca_approved'", DRAFT) == 1
    assert _changed(db, who, table, "status = 'draft'", APPROVED) == 1
    _reseed(db, table)
    assert _deleted(db, who, table, APPROVED) == 1


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("who", ["partner", "manager", "executive_granted", "executive", "manager_denied"])
def test_nobody_signed_in_deletes_a_filed_return(db, table, who):
    _reseed(db, table)
    assert _deleted(db, who, table, SUBMITTED) == 0
    assert _ok(db, f"SELECT count(*) FROM {table} WHERE period = '{SUBMITTED}';") == "1"


@pytest.mark.parametrize("table", TABLES)
def test_a_manager_the_grid_denies_is_treated_as_an_executive(db, table):
    _reseed(db, table)
    assert _refused(db, "manager_denied", table, "status = 'ca_approved'", DRAFT)
    assert _changed(db, "manager_denied", table, "status = 'draft'", APPROVED) == 0
    assert _deleted(db, "manager_denied", table, APPROVED) == 0
    assert _changed(db, "manager_denied", table, "status = 'validated'", DRAFT) == 1


# ── the migration itself ─────────────────────────────────────────────────────────────────────────
def test_491_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    for table in TABLES:
        _reseed(db, table)
        assert _refused(db, "executive", table, "status = 'ca_approved'", DRAFT)


def test_its_own_rollback_puts_the_hole_back(db):
    """The negative control: without it the assertions above would pass on a database that never had a hole."""
    _apply(db, ROLLBACK)
    for table in TABLES:
        _reseed(db, table)
        assert _changed(db, "executive", table, "status = 'ca_approved'", DRAFT) == 1, "approve"
        assert _changed(db, "executive", table, "status = 'draft'", SUBMITTED) == 1, "reopen a filed return"
        assert _deleted(db, "executive", table, APPROVED) == 1, "delete an approved return"
    _apply(db, MIGRATION)
    for table in TABLES:
        _reseed(db, table)
        assert _refused(db, "executive", table, "status = 'ca_approved'", DRAFT)
