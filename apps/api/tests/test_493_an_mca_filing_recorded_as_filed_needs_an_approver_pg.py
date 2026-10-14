"""Migration 493 — an MCA filing recorded as filed changes only in the hands of someone who may approve MCA filings.

THE BUG THIS PINS (ledger POST-A-225)
    `mca_filings` takes its writes from anyone with `mca:write` (Executive). The API reserves RECORDING A FILING AS FILED
    to `mca:approve` (Manager) with the CA's explicit confirmation, but a row policy cannot see a TRANSITION, so with their
    own sign-in an Executive could write `status = 'filed'` with an SRN and a date straight into the table (the MCA screen
    did exactly that, in three places), create a row already filed, reopen a filed one or delete it. What a row policy CAN
    see is the status a row has and the status it is given, which is what the migration asks.

WHAT IS ASSERTED, AS A REAL AUTHENTICATED SESSION
    * an Executive creates and progresses an unfiled filing (not started, in progress) and deletes one;
    * an Executive can NOT give a filing the status `filed`, insert one already filed, touch a filing that is ALREADY filed
      (the UPDATE finds zero rows) or delete it;
    * a Manager and a Partner record a filing as filed, reopen it and delete it;
    * the per-person grid counts both ways: an Executive the grid GRANTS `mca:approve` records a filing, and a Manager it
      DENIES cannot;
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
MIGRATION = MIGRATIONS / "493_a_filing_recorded_as_filed_changes_only_in_the_hands_of_someone_who_may_approve_mca_filings.sql"
ROLLBACK = MIGRATIONS / "493_a_filing_recorded_as_filed_changes_only_in_the_hands_of_someone_who_may_approve_mca_filings_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the GST return state-tier proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000493"
CLIENT = "cccccccc-0000-0000-0000-00000000a493"
TABLE = "mca_filings"

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

OPEN, FILED = "AOC-4", "MGT-7"      # form_type tells the two rows apart


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
    r = _as(dsn, who, f"WITH u AS (UPDATE {TABLE} SET {set_clause} WHERE form_type = '{form}' RETURNING 1) "
                      "SELECT count(*) FROM u;")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _refused(dsn: str, who: str, set_clause: str, form: str) -> bool:
    """True when row security REFUSED the new row (an error), as opposed to finding nothing to change."""
    r = _as(dsn, who, f"UPDATE {TABLE} SET {set_clause} WHERE form_type = '{form}';")
    return r.returncode != 0 and "row-level security" in r.stderr


def _deleted(dsn: str, who: str, form: str) -> int:
    r = _as(dsn, who, f"WITH d AS (DELETE FROM {TABLE} WHERE form_type = '{form}' RETURNING 1) SELECT count(*) FROM d;")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _insert(dsn: str, who: str, form: str, status: str) -> subprocess.CompletedProcess:
    return _as(dsn, who, f"INSERT INTO {TABLE} (firm_id, client_id, form_type, due_date, status) "
                         f"VALUES ('{FIRM}', '{CLIENT}', '{form}', '2026-10-30', '{status}');")


def _reseed(dsn: str) -> None:
    _ok(dsn, f"""
        DELETE FROM {TABLE};
        INSERT INTO {TABLE} (firm_id, client_id, form_type, due_date, status) VALUES
          ('{FIRM}', '{CLIENT}', '{OPEN}', '2026-10-30', 'not_started'),
          ('{FIRM}', '{CLIENT}', '{FILED}', '2026-11-29', 'filed');""")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"mcastate_m493_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m493.test')" for k, v in AUTH.items())
        users = ", ".join(f"('{USER[k]}', '{FIRM}', '{AUTH[k]}', '{k}@m493.test', '{k}', '{role}', true)"
                          for k, (role, _g) in ACTORS.items())
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT}')" for k in ACTORS)
        grid = ", ".join(f"('{FIRM}', '{USER[k]}', 'mca', 'approve', {str(g).lower()})"
                         for k, (_r, g) in ACTORS.items() if g is not None)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M493 Firm','m493@test.in');
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


# ── the executive progresses, and cannot record as filed, reopen or delete ───────────────────────
def test_an_executive_creates_and_progresses_an_unfiled_filing(db):
    _reseed(db)
    assert _insert(db, "executive", "ADT-1", "not_started").returncode == 0
    assert _changed(db, "executive", "status = 'in_progress'", OPEN) == 1
    assert _changed(db, "executive", "status = 'not_started'", OPEN) == 1
    assert _deleted(db, "executive", OPEN) == 1


def test_an_executive_cannot_record_a_filing_as_filed(db):
    _reseed(db)
    assert _refused(db, "executive", "status = 'filed', srn = 'SRN123'", OPEN)
    assert _ok(db, f"SELECT status FROM {TABLE} WHERE form_type = '{OPEN}';") == "not_started"
    r = _insert(db, "executive", "ADT-1", "filed")
    assert r.returncode != 0 and "row-level security" in r.stderr


def test_an_executive_cannot_touch_a_filing_that_is_already_filed(db):
    _reseed(db)
    assert _changed(db, "executive", "status = 'in_progress'", FILED) == 0, "reopened it"
    assert _changed(db, "executive", "srn = 'SRN-ALTERED'", FILED) == 0, "rewrote its SRN"
    assert _deleted(db, "executive", FILED) == 0, "deleted it"
    assert _ok(db, f"SELECT status FROM {TABLE} WHERE form_type = '{FILED}';") == "filed"


# ── the approvers ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["partner", "manager", "executive_granted"])
def test_someone_who_may_approve_records_reopens_and_deletes_a_filed_filing(db, who):
    _reseed(db)
    assert _changed(db, who, "status = 'filed', srn = 'SRN1'", OPEN) == 1
    assert _changed(db, who, "status = 'in_progress'", FILED) == 1
    _reseed(db)
    assert _deleted(db, who, FILED) == 1


def test_a_manager_the_grid_denies_is_treated_as_an_executive(db):
    _reseed(db)
    assert _refused(db, "manager_denied", "status = 'filed'", OPEN)
    assert _changed(db, "manager_denied", "status = 'in_progress'", FILED) == 0
    assert _deleted(db, "manager_denied", FILED) == 0
    assert _changed(db, "manager_denied", "status = 'in_progress'", OPEN) == 1


# ── the migration itself ─────────────────────────────────────────────────────────────────────────
def test_493_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    _reseed(db)
    assert _refused(db, "executive", "status = 'filed'", OPEN)


def test_its_own_rollback_puts_the_hole_back(db):
    """The negative control: without it the assertions above would pass on a database that never had a hole."""
    _apply(db, ROLLBACK)
    _reseed(db)
    assert _changed(db, "executive", "status = 'filed'", OPEN) == 1, "record as filed"
    assert _changed(db, "executive", "status = 'in_progress'", FILED) == 1, "reopen a filed filing"
    assert _deleted(db, "executive", OPEN) == 1, "delete"
    _apply(db, MIGRATION)
    _reseed(db)
    assert _refused(db, "executive", "status = 'filed'", OPEN)
