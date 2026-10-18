"""Migration 503 — a signed-in member writes only the workflow templates (and steps) of its OWN firm, never a system one.

THE HOLE (ledger POST-A-249)
    `workflow_templates` carried the policy "firm_isolation": PERMISSIVE, FOR ALL, `USING (firm_id = get_my_firm_id() OR
    is_system = true)` with no WITH CHECK. For INSERT and UPDATE Postgres uses the USING expression as the check, so any
    signed-in member of ANY firm could insert a template saying `is_system = true` under any `firm_id`, and update or delete
    a system template every firm reads. `workflow_steps` had the same shape through its template. Read from production on
    17-10-2026, with `authenticated` holding INSERT, UPDATE and DELETE on both.

WHAT IS HELD (every probe runs as `authenticated` with a member's own JWT claim, so row security is genuinely asked)
    * a member reads their own firm's templates and any system template, and nothing of another firm's, and the steps of
      the same;
    * a member cannot plant a system template, under their own firm or another's, cannot write another firm's template,
      cannot update or delete a system template, and cannot turn their own template into a system one;
    * a member still creates, edits and deletes their OWN firm's non-system templates and the steps beneath them, and cannot
      write the steps of a system template or another firm's;
    * `service_role`, which the API's privileged client and any seed path use, still writes a system template;
    * the migration is idempotent; its closing check FAILS it if a permissive policy that admits `is_system = true` to a
      write is present; and its own rollback puts the hole back (the negative control, run for the cross-firm insert).

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests._signed_in_workflow_writes import give_the_signed_in_writes_back

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_STEM = "503_a_signed_in_session_writes_only_workflow_templates_of_its_own_firm_and_never_a_system_one"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None,
                               reason="the workflow-template policy proofs require HARNESS_PG + psql")

FIRM_A, FIRM_B = "aaaaaaaa-0000-0000-0000-000000000503", "bbbbbbbb-0000-0000-0000-000000000503"
AUTH_A, AUTH_B = "11111111-1111-1111-1111-00000000a503", "22222222-2222-2222-2222-00000000b503"
USER_A, USER_B = "cccccccc-1111-1111-1111-00000000a503", "dddddddd-2222-2222-2222-00000000b503"
SYSTEM_T, TEMPLATE_A, TEMPLATE_B = (f"eeeeeeee-0000-0000-0000-00000000000{i}" for i in (1, 2, 3))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    done = _psql(dsn, sql)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _as_member_of_a(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH_A, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _count_changed(dsn: str, statement: str) -> int:
    """Rows a signed-in member's UPDATE/DELETE actually changed. Row security hides a row from the statement rather than
    raising, so 'refused' for these two is a count of zero."""
    done = _as_member_of_a(dsn, f"WITH changed AS ({statement} RETURNING 1) SELECT count(*) FROM changed;")
    assert done.returncode == 0, done.stderr
    return int(done.stdout.strip().splitlines()[-1])


def _refused(done: subprocess.CompletedProcess) -> bool:
    return done.returncode != 0 and "row-level security" in done.stderr


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"wftemplates_m503_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_A}', 'a@m503.test'), ('{AUTH_B}', 'b@m503.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM_A}', 'Firm A', 'a@m503.test'), ('{FIRM_B}', 'Firm B', 'b@m503.test');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
                 ('{USER_A}', '{FIRM_A}', '{AUTH_A}', 'a@m503.test', 'A', 'Manager', true),
                 ('{USER_B}', '{FIRM_B}', '{AUTH_B}', 'b@m503.test', 'B', 'Manager', true);
            INSERT INTO workflow_templates (id, firm_id, name, trigger_type, is_system) VALUES
                 ('{SYSTEM_T}',  '{FIRM_B}', 'Shipped template', 'gst_due', true),
                 ('{TEMPLATE_A}', '{FIRM_A}', 'A own',  'manual', false),
                 ('{TEMPLATE_B}', '{FIRM_B}', 'B own',  'manual', false);
            INSERT INTO workflow_steps (template_id, step_order, step_type, name) VALUES
                 ('{SYSTEM_T}', 1, 'action', 'system step'),
                 ('{TEMPLATE_A}', 1, 'action', 'a step'),
                 ('{TEMPLATE_B}', 1, 'action', 'b step');
        """)
        assert seed.returncode == 0, seed.stderr
        # Migration 509 took the signed-in write away (the FIRST lock); this module measures the row policies (the SECOND), and
        # a write refused for want of the privilege says nothing about them. See `_signed_in_workflow_writes`.
        give_the_signed_in_writes_back(dsn)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _names(done: subprocess.CompletedProcess) -> set[str]:
    assert done.returncode == 0, done.stderr
    return {line for line in done.stdout.strip().splitlines() if line}


# ── reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_a_member_reads_their_own_templates_and_the_system_ones_and_nothing_of_another_firm(db):
    got = _names(_as_member_of_a(db, "SELECT name FROM workflow_templates ORDER BY name;"))
    assert got == {"A own", "Shipped template"}, got


@_NEEDS_PG
def test_a_member_reads_the_steps_of_their_own_and_of_system_templates_only(db):
    got = _names(_as_member_of_a(db, "SELECT name FROM workflow_steps ORDER BY name;"))
    assert got == {"a step", "system step"}, got


# ── writing templates ────────────────────────────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
@pytest.mark.parametrize("firm", [FIRM_A, FIRM_B], ids=["under-own-firm", "under-another-firm"])
def test_a_member_cannot_plant_a_system_template(db, firm):
    done = _as_member_of_a(db, f"INSERT INTO workflow_templates (firm_id, name, trigger_type, is_system) "
                               f"VALUES ('{firm}', 'planted', 'manual', true);")
    assert _refused(done), done.stderr
    assert _ok(db, "SELECT count(*) FROM workflow_templates WHERE name = 'planted';") == "0"


@_NEEDS_PG
def test_a_member_cannot_write_a_template_for_another_firm(db):
    done = _as_member_of_a(db, f"INSERT INTO workflow_templates (firm_id, name, trigger_type) "
                               f"VALUES ('{FIRM_B}', 'for b', 'manual');")
    assert _refused(done), done.stderr
    assert _count_changed(db, f"UPDATE workflow_templates SET name = 'hijacked' WHERE id = '{TEMPLATE_B}'") == 0
    assert _count_changed(db, f"DELETE FROM workflow_templates WHERE id = '{TEMPLATE_B}'") == 0
    assert _ok(db, f"SELECT name FROM workflow_templates WHERE id = '{TEMPLATE_B}';") == "B own"


@_NEEDS_PG
def test_a_member_cannot_change_or_delete_a_system_template(db):
    assert _count_changed(db, f"UPDATE workflow_templates SET name = 'hijacked' WHERE id = '{SYSTEM_T}'") == 0
    assert _count_changed(db, f"DELETE FROM workflow_templates WHERE id = '{SYSTEM_T}'") == 0
    assert _ok(db, f"SELECT name FROM workflow_templates WHERE id = '{SYSTEM_T}';") == "Shipped template"


@_NEEDS_PG
def test_a_member_cannot_turn_their_own_template_into_a_system_one(db):
    done = _as_member_of_a(db, f"UPDATE workflow_templates SET is_system = true WHERE id = '{TEMPLATE_A}';")
    assert _refused(done), done.stderr
    assert _ok(db, f"SELECT is_system FROM workflow_templates WHERE id = '{TEMPLATE_A}';") == "f"


@_NEEDS_PG
def test_a_member_still_creates_edits_and_deletes_their_own_firms_templates(db):
    made = _as_member_of_a(db, f"INSERT INTO workflow_templates (firm_id, name, trigger_type) "
                               f"VALUES ('{FIRM_A}', 'new own', 'manual');")
    assert made.returncode == 0, made.stderr
    assert _count_changed(db, "UPDATE workflow_templates SET name = 'renamed own' WHERE name = 'new own'") == 1
    assert _count_changed(db, "DELETE FROM workflow_templates WHERE name = 'renamed own'") == 1
    assert _count_changed(db, f"UPDATE workflow_templates SET name = 'A edited' WHERE id = '{TEMPLATE_A}'") == 1


# ── writing steps ────────────────────────────────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
@pytest.mark.parametrize("template,why", [(SYSTEM_T, "a system template"), (TEMPLATE_B, "another firm's template")])
def test_a_member_cannot_write_the_steps_of_a_template_that_is_not_their_firms(db, template, why):
    done = _as_member_of_a(db, f"INSERT INTO workflow_steps (template_id, step_order, step_type, name) "
                               f"VALUES ('{template}', 9, 'action', 'planted');")
    assert _refused(done), f"{why}: {done.stderr}"
    assert _count_changed(db, f"UPDATE workflow_steps SET name = 'hijacked' WHERE template_id = '{template}'") == 0
    assert _count_changed(db, f"DELETE FROM workflow_steps WHERE template_id = '{template}'") == 0
    assert _ok(db, f"SELECT count(*) FROM workflow_steps WHERE template_id = '{template}' AND name <> 'hijacked';") == "1"


@_NEEDS_PG
def test_a_member_cannot_move_a_step_onto_a_template_that_is_not_their_firms(db):
    done = _as_member_of_a(db, f"UPDATE workflow_steps SET template_id = '{SYSTEM_T}' WHERE template_id = '{TEMPLATE_A}';")
    assert _refused(done), done.stderr


@_NEEDS_PG
def test_a_member_still_writes_the_steps_of_their_own_firms_template(db):
    made = _as_member_of_a(db, f"INSERT INTO workflow_steps (template_id, step_order, step_type, name) "
                               f"VALUES ('{TEMPLATE_A}', 2, 'action', 'second');")
    assert made.returncode == 0, made.stderr
    assert _count_changed(db, "UPDATE workflow_steps SET name = 'second edited' WHERE name = 'second'") == 1
    assert _count_changed(db, "DELETE FROM workflow_steps WHERE name = 'second edited'") == 1


# ── what is not touched ──────────────────────────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_the_privileged_client_still_writes_a_system_template(db):
    done = _psql(db, "SET ROLE service_role; INSERT INTO workflow_templates (firm_id, name, trigger_type, is_system) "
                     f"VALUES ('{FIRM_A}', 'seeded', 'manual', true);")
    assert done.returncode == 0, done.stderr
    assert _ok(db, "SELECT count(*) FROM workflow_templates WHERE name = 'seeded' AND is_system;") == "1"


# ── the migration itself ─────────────────────────────────────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_the_migration_is_idempotent(db):
    for _ in range(2):
        assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    got = _names(_as_member_of_a(db, "SELECT name FROM workflow_templates ORDER BY name;"))
    assert got == {"A own", "Shipped template"}


@_NEEDS_PG
def test_negative_control_the_rollback_puts_the_hole_back_and_the_migration_closes_it_again(db):
    plant = f"INSERT INTO workflow_templates (firm_id, name, trigger_type, is_system) VALUES ('{FIRM_B}', 'planted', 'x', true);"
    assert _refused(_as_member_of_a(db, plant)), "the migration should already refuse the plant"
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    reopened = _as_member_of_a(db, plant)
    assert reopened.returncode == 0, f"the rollback should re-open the hole: {reopened.stderr}"
    assert _count_changed(db, f"UPDATE workflow_templates SET name = 'hijacked' WHERE id = '{SYSTEM_T}'") == 1
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _refused(_as_member_of_a(db, plant.replace("'planted'", "'planted again'")))


@_NEEDS_PG
def test_the_closing_check_fails_the_migration_if_a_permissive_policy_still_admits_a_system_row(db):
    assert _psql(db, "CREATE POLICY door ON workflow_templates AS PERMISSIVE FOR ALL TO authenticated "
                     "USING (is_system = true);").returncode == 0
    done = _psql(db, MIGRATION.read_text(encoding="utf-8"))
    assert done.returncode != 0 and "still admits a system workflow row to a write" in done.stderr, done.stderr
