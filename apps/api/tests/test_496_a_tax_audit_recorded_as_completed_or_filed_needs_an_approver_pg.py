"""Migration 496 — a tax audit recorded as completed or filed changes only in the hands of someone who may approve income tax.

THE BUG THIS PINS (ledger POST-A-226)
    `tax_audits` takes its writes from anyone with `income_tax:compute` (Executive), and the Tax Audit tracker writes the
    table straight from the browser, including `status = 'completed'` or `'filed'` with a UDIN, an acknowledgement number
    and a filing date. The matching ITR filing record is Manager-tier and goes through the API, so an Executive could say
    the audit was done when the same Executive could not say the return was. A row policy cannot see a TRANSITION; what it
    CAN see is the status a row has and the status it is given, which is what the migration asks.

WHAT IS ASSERTED, AS A REAL AUTHENTICATED SESSION
    * an Executive creates and progresses an audit that is not started or in progress, and deletes one;
    * an Executive can NOT give an audit the status `completed` or `filed`, insert one already in either, touch one that is
      ALREADY in either (the UPDATE finds zero rows) or delete it;
    * a Manager and a Partner record an audit as completed or filed, reopen it and delete it;
    * the per-person grid counts both ways: an Executive the grid GRANTS `income_tax:approve` records an audit, and a
      Manager it DENIES cannot;
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
MIGRATION = MIGRATIONS / "496_a_tax_audit_recorded_as_completed_or_filed_changes_only_in_the_hands_of_someone_who_may_approve.sql"
ROLLBACK = MIGRATIONS / "496_a_tax_audit_recorded_as_completed_or_filed_changes_only_in_the_hands_of_someone_who_may_approve_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the tax audit state-tier proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000496"
CLIENT = "cccccccc-0000-0000-0000-00000000a496"
TABLE = "tax_audits"

#: who -> (role, grid decision on income_tax:approve or None)
ACTORS = {
    "partner": ("Partner", None),
    "manager": ("Manager", None),
    "manager_denied": ("Manager", False),
    "executive": ("Executive", None),
    "executive_granted": ("Executive", True),
}
AUTH = {k: f"11111111-1111-1111-1111-{i:012d}" for i, k in enumerate(ACTORS, start=1)}
USER = {k: f"bbbbbbbb-1111-1111-1111-{i:012d}" for i, k in enumerate(ACTORS, start=1)}

#: financial_year tells the seeded rows apart (the table is UNIQUE(client_id, financial_year))
OPEN, DONE, FILED = "2025-26", "2024-25", "2023-24"


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


def _changed(dsn: str, who: str, set_clause: str, form: str) -> int:
    """Rows an UPDATE reached, as `who`."""
    r = _as(dsn, who, f"WITH u AS (UPDATE {TABLE} SET {set_clause} WHERE financial_year = '{form}' RETURNING 1) "
                      "SELECT count(*) FROM u;")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _refused(dsn: str, who: str, set_clause: str, form: str) -> bool:
    """True when row security REFUSED the new row (an error), as opposed to finding nothing to change."""
    r = _as(dsn, who, f"UPDATE {TABLE} SET {set_clause} WHERE financial_year = '{form}';")
    return r.returncode != 0 and "row-level security" in r.stderr


def _deleted(dsn: str, who: str, form: str) -> int:
    r = _as(dsn, who, f"WITH d AS (DELETE FROM {TABLE} WHERE financial_year = '{form}' RETURNING 1) SELECT count(*) FROM d;")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _insert(dsn: str, who: str, form: str, status: str) -> subprocess.CompletedProcess:
    return _as(dsn, who, f"INSERT INTO {TABLE} (firm_id, client_id, financial_year, status) "
                         f"VALUES ('{FIRM}', '{CLIENT}', '{form}', '{status}');")


def _reseed(dsn: str) -> None:
    _ok(dsn, f"""
        DELETE FROM {TABLE};
        INSERT INTO {TABLE} (firm_id, client_id, financial_year, status) VALUES
          ('{FIRM}', '{CLIENT}', '{OPEN}', 'not_started'),
          ('{FIRM}', '{CLIENT}', '{DONE}', 'completed'),
          ('{FIRM}', '{CLIENT}', '{FILED}', 'filed');""")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"taxaudit_m496_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m496.test')" for k, v in AUTH.items())
        users = ", ".join(f"('{USER[k]}', '{FIRM}', '{AUTH[k]}', '{k}@m496.test', '{k}', '{role}', true)"
                          for k, (role, _g) in ACTORS.items())
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT}')" for k in ACTORS)
        grid = ", ".join(f"('{FIRM}', '{USER[k]}', 'income_tax', 'approve', {str(g).lower()})"
                         for k, (_r, g) in ACTORS.items() if g is not None)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M496 Firm','m496@test.in');
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


# ── the executive progresses, and cannot record as completed or filed, reopen or delete ──────────
def test_an_executive_creates_and_progresses_an_unfinished_audit(db):
    _reseed(db)
    assert _insert(db, "executive", "2022-23", "not_started").returncode == 0
    assert _changed(db, "executive", "status = 'in_progress', auditor_name = 'A. Auditor'", OPEN) == 1
    assert _changed(db, "executive", "status = 'not_started'", OPEN) == 1
    assert _deleted(db, "executive", OPEN) == 0, "delete stays at the Manager tier (migration 261)"


@pytest.mark.parametrize("terminal", ["completed", "filed"])
def test_an_executive_cannot_record_an_audit_as_completed_or_filed(db, terminal):
    _reseed(db)
    assert _refused(db, "executive", f"status = '{terminal}', udin = '26123456ABCDEF1234'", OPEN)
    assert _ok(db, f"SELECT status FROM {TABLE} WHERE financial_year = '{OPEN}';") == "not_started"
    r = _insert(db, "executive", "2022-23", terminal)
    assert r.returncode != 0 and "row-level security" in r.stderr


@pytest.mark.parametrize("year, kept", [(DONE, "completed"), (FILED, "filed")])
def test_an_executive_cannot_touch_an_audit_that_is_already_completed_or_filed(db, year, kept):
    _reseed(db)
    assert _changed(db, "executive", "status = 'in_progress'", year) == 0, "reopened it"
    assert _changed(db, "executive", "udin = 'ALTERED'", year) == 0, "rewrote its UDIN"
    assert _deleted(db, "executive", year) == 0, "deleted it"
    assert _ok(db, f"SELECT status FROM {TABLE} WHERE financial_year = '{year}';") == kept


# ── the approvers ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["partner", "manager", "executive_granted"])
def test_someone_who_may_approve_records_and_reopens_a_finished_audit(db, who):
    _reseed(db)
    assert _changed(db, who, "status = 'completed', udin = '26123456ABCDEF1234'", OPEN) == 1
    assert _changed(db, who, "status = 'filed', ack_number = 'ACK1'", OPEN) == 1
    assert _changed(db, who, "status = 'in_progress'", DONE) == 1
    assert _changed(db, who, "status = 'in_progress'", FILED) == 1
    _reseed(db)
    # Delete also passes migration 261's ROLE-based policy (Manager and above; the grid is not asked there), so an
    # Executive the grid GRANTS approval records and reopens an audit but still does not delete one.
    assert _deleted(db, who, FILED) == (0 if who == "executive_granted" else 1)


def test_a_manager_the_grid_denies_is_treated_as_an_executive(db):
    _reseed(db)
    assert _refused(db, "manager_denied", "status = 'completed'", OPEN)
    assert _changed(db, "manager_denied", "status = 'in_progress'", DONE) == 0
    assert _deleted(db, "manager_denied", FILED) == 0
    assert _changed(db, "manager_denied", "status = 'in_progress'", OPEN) == 1


# ── the migration itself ─────────────────────────────────────────────────────────────────────────
def test_496_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    _reseed(db)
    assert _refused(db, "executive", "status = 'completed'", OPEN)


def test_its_own_rollback_puts_the_hole_back(db):
    """The negative control: without it the assertions above would pass on a database that never had a hole."""
    _apply(db, ROLLBACK)
    _reseed(db)
    assert _changed(db, "executive", "status = 'completed'", OPEN) == 1, "record as completed"
    assert _changed(db, "executive", "status = 'in_progress'", FILED) == 1, "reopen a filed audit"
    _apply(db, MIGRATION)
    _reseed(db)
    assert _refused(db, "executive", "status = 'completed'", OPEN)
