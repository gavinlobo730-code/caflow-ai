"""
Migration 332, proved against real PostgreSQL.

WHAT IS BEING PROVED
    1. THE BROWSER CANNOT WRITE THE COLUMN. Not "is filtered out" — the
       statement is REFUSED, `permission denied`. RLS could not do this: a
       policy is per ROW, and a Manager legitimately writes the same row's input
       cut-off. Column privileges are per COLUMN, and a denied one RAISES where
       a denied policy silently skips the row.

    2. THE REVOKE-THEN-GRANT ORDER IS LOad-BEARING. PostgreSQL holds table-level
       and column-level privileges separately, and a table-level UPDATE grant
       already covers every column — so REVOKE UPDATE (payroll_enabled) against
       a role holding the table grant does NOTHING. The table privilege has to
       go first. This suite would pass on the wrong migration if it only checked
       that the column exists.

    3. THE BACKFILL IS NEITHER "EVERYBODY" NOR "NOBODY". DEFAULT false is right
       for a client created tomorrow and wrong for one whose payroll the firm
       already runs; shipping the default alone would switch payroll off for
       every live client at once. A client with a payroll EMPLOYEE or a payroll
       RUN is enabled, and one with neither is not.

    4. payroll_enabled_by stays NULL on a backfilled row. The honest answer to
       "which Partner decided this" is that nobody did — the same choice
       migration 326 made for attendance.entered_by.

NEGATIVE CONTROL
    Drop the REVOKE and keep the GRANTs and
    test_a_manager_cannot_switch_payroll_on_from_the_browser fails — the table
    grant still covers the column. Drop the backfill and
    test_a_client_that_already_has_payroll_is_enabled fails. Stamp a user id on
    the backfill and test_a_backfilled_row_claims_no_author fails.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="payroll enablement proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000332"
# WITH payroll already: an employee. WITH a run only. WITH neither.
CLI_EMP = "bbbbbbbb-0000-0000-0000-000000000332"
CLI_RUN = "bbbbbbbb-0000-0000-0000-000000000333"
CLI_NONE = "bbbbbbbb-0000-0000-0000-000000000334"
MANAGER = "dddddddd-0000-0000-0000-000000000332"
MIGRATION = "332_payroll_is_switched_on_for_a_client_by_a_partner.sql"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _client(cid: str, name: str) -> str:
    return (f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) "
            f"VALUES ('{cid}','{FIRM}','{name}','Private Limited','AAACA1234E');")


@pytest.fixture()
def db(pg_template):
    """A database where the three clients exist BEFORE migration 332 runs.

    That ordering is the whole point of the backfill tests: the template has
    every migration applied, so seeding after the fact would prove nothing.
    Migration 332's backfill is therefore re-run by hand here, against rows that
    look exactly like the ones production had when it first applied.
    """
    admin = _ADMIN.strip()
    name = f"m332_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert MIGRATION not in pg_template.failed, (
            "migration 332 did not apply — everything below would pass vacuously")
        stmts = [
            f"INSERT INTO auth.users (id, email) VALUES ('{MANAGER}','mgr332@t.in');",
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F332','f332@t.in');",
            _client(CLI_EMP, "Has employees"),
            _client(CLI_RUN, "Has a run"),
            _client(CLI_NONE, "Has neither"),
            f"INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) "
            f"VALUES ('{MANAGER}','{FIRM}','{MANAGER}','mgr332@t.in','Mgr','Manager');",
            f"INSERT INTO payroll_employees (id, firm_id, client_id, name) VALUES "
            f"(gen_random_uuid(),'{FIRM}','{CLI_EMP}','Asha');",
            f"INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES "
            f"(gen_random_uuid(),'{FIRM}','{CLI_RUN}','2026-08','draft');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


BACKFILL = f"""
INSERT INTO public.client_payroll_settings (firm_id, client_id, payroll_enabled)
SELECT DISTINCT c.firm_id, c.id, true
FROM public.clients c
WHERE (EXISTS (SELECT 1 FROM public.payroll_employees e
               WHERE e.client_id = c.id AND e.firm_id = c.firm_id)
       OR EXISTS (SELECT 1 FROM public.payroll_runs r
                  WHERE r.client_id = c.id AND r.firm_id = c.firm_id))
  AND NOT EXISTS (SELECT 1 FROM public.client_payroll_settings s
                  WHERE s.client_id = c.id AND s.firm_id = c.firm_id);
"""


def _enabled(dsn: str, cid: str) -> str:
    return _psql(dsn, "SELECT coalesce(bool_or(payroll_enabled), false) "
                      f"FROM client_payroll_settings WHERE client_id = '{cid}';",
                 tuples=True).stdout.strip()


# ─── 1. the default, and what it means ──────────────────────────────────────

def test_a_new_row_is_not_enabled(db):
    """DEFAULT false. A client created tomorrow is not a payroll client until
    somebody says so."""
    assert _psql(db, "INSERT INTO client_payroll_settings (firm_id, client_id) "
                     f"VALUES ('{FIRM}','{CLI_NONE}');").returncode == 0
    assert _enabled(db, CLI_NONE) == "f"


# ─── 2. the backfill is neither everybody nor nobody ────────────────────────

def test_a_client_that_already_has_payroll_is_enabled(db):
    """An employee row is the provisioning act this switch exists to gate, and a
    run is proof somebody has already been paid. Either is a decision that was
    made — just never recorded, because there was nowhere to record it."""
    assert _psql(db, BACKFILL).returncode == 0
    assert _enabled(db, CLI_EMP) == "t", "a client with employees must stay enabled"
    assert _enabled(db, CLI_RUN) == "t", "a client with a run must stay enabled"


def test_a_client_with_no_payroll_is_left_alone(db):
    assert _psql(db, BACKFILL).returncode == 0
    out = _psql(db, "SELECT count(*) FROM client_payroll_settings "
                    f"WHERE client_id = '{CLI_NONE}';", tuples=True)
    assert out.stdout.strip() == "0", "no row at all, which is the same answer as false"


def test_a_backfilled_row_claims_no_author(db):
    """The honest answer to "which Partner decided this" is that nobody did.
    Stamping any user id would assert an authorship that did not happen — the
    same choice migration 326 made for attendance.entered_by."""
    assert _psql(db, BACKFILL).returncode == 0
    out = _psql(db, "SELECT payroll_enabled_by IS NULL AND payroll_enabled_on IS NULL "
                    f"FROM client_payroll_settings WHERE client_id = '{CLI_EMP}';",
                tuples=True)
    assert out.stdout.strip() == "t"


# ─── 3. the browser cannot write the column ─────────────────────────────────

def _as_manager(dsn: str, sql: str) -> subprocess.CompletedProcess:
    """As the signed-in user, the way the frontend reaches this table.

    SET LOCAL ROLE authenticated matters: the table is owned by postgres and an
    owner bypasses both RLS and its own column grants.
    """
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                      'SET LOCAL request.jwt.claims = \'{"sub":"' + MANAGER + '"}\'; ' 
                      f"{sql} ROLLBACK;")


def test_a_manager_can_still_set_the_input_cutoff(db):
    """The columns migration 326 gave them are untouched. If this fails the
    revoke took away too much."""
    r = _as_manager(db, "INSERT INTO client_payroll_settings "
                        f"(firm_id, client_id, inputs_due_day) "
                        f"VALUES ('{FIRM}','{CLI_NONE}', 5);")
    assert r.returncode == 0, r.stderr


def test_a_manager_cannot_switch_payroll_on_from_the_browser(db):
    """A column privilege, not a policy — so the statement is REFUSED rather
    than silently writing nothing, which is what an RLS refusal would have
    looked like (CLAUDE.md: a denied UPDATE does not raise).

    PostgreSQL words this "permission denied for TABLE", not "for column", even
    though the table privilege is exactly what was revoked and the granted
    columns still work — see the test above, which passes. The asserted fact is
    the refusal, not the wording."""
    r = _as_manager(db, "INSERT INTO client_payroll_settings "
                        f"(firm_id, client_id, payroll_enabled) "
                        f"VALUES ('{FIRM}','{CLI_NONE}', true);")
    assert r.returncode != 0, "a Manager switched payroll on straight from the browser"
    assert "permission denied" in r.stderr
    assert "client_payroll_settings" in r.stderr


def test_a_manager_cannot_switch_payroll_on_by_update_either(db):
    assert _psql(db, "INSERT INTO client_payroll_settings (firm_id, client_id) "
                     f"VALUES ('{FIRM}','{CLI_NONE}');").returncode == 0
    r = _as_manager(db, "UPDATE client_payroll_settings SET payroll_enabled = true "
                        f"WHERE client_id = '{CLI_NONE}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr


def test_a_row_inserted_from_the_browser_takes_the_default(db):
    """A Manager setting a cut-off for a new client does not thereby switch
    payroll on for them. INSERT is granted on the other columns only, so
    payroll_enabled takes DEFAULT false."""
    r = _psql(db, "BEGIN; SET LOCAL ROLE authenticated; "
                  f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{MANAGER}\"}}'; "
                  "INSERT INTO client_payroll_settings (firm_id, client_id, inputs_due_day) "
                  f"VALUES ('{FIRM}','{CLI_NONE}', 7); "
                  "SELECT payroll_enabled FROM client_payroll_settings "
                  f"WHERE client_id = '{CLI_NONE}'; COMMIT;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert [ln for ln in r.stdout.split() if ln in ("t", "f")][-1] == "f"


def test_reading_the_flag_is_open(db):
    """The screen has to know whether to offer payroll at all, so SELECT is
    untouched. Only writing is closed."""
    assert _psql(db, "INSERT INTO client_payroll_settings (firm_id, client_id) "
                     f"VALUES ('{FIRM}','{CLI_NONE}');").returncode == 0
    r = _as_manager(db, "SELECT payroll_enabled FROM client_payroll_settings "
                        f"WHERE client_id = '{CLI_NONE}';")
    assert r.returncode == 0, r.stderr


def test_the_api_can_still_write_it(db):
    """service_role's grants are untouched, which is what makes the API the one
    door. rbac("payroll", "enable") is Partner-only on the other side of it."""
    assert _psql(db, "INSERT INTO client_payroll_settings (firm_id, client_id) "
                     f"VALUES ('{FIRM}','{CLI_NONE}');").returncode == 0
    r = _psql(db, "BEGIN; SET LOCAL ROLE service_role; "
                  "UPDATE client_payroll_settings SET payroll_enabled = true "
                  f"WHERE client_id = '{CLI_NONE}'; ROLLBACK;")
    assert r.returncode == 0, r.stderr
