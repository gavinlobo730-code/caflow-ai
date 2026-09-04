"""
Migration 328, proved against real PostgreSQL.

WHAT IS BEING PROVED
    1. The rule is a CONSTRAINT, not a convention. A release (finalized/paid)
       with gaps and no reason of substance cannot be written — not "the
       endpoint refuses it", though it does, but the table refuses it too,
       because ~83 tables in this schema are written directly from the browser
       through PostgREST where rbac() never runs.

    2. The log is APPEND-ONLY. There is a SELECT policy and an INSERT policy and
       no others, and UPDATE and DELETE are revoked at the grant level as well —
       so a future migration that adds a broad FOR ALL policy cannot quietly
       reopen them. A log somebody can edit is a claim, not a record.

    3. draft and review are deliberately NOT covered by the rule. They post no
       journal and pay nobody; requiring a reason there would only teach people
       to type "n/a" before the moment it matters.

THE TRAP
    A denied UPDATE does not raise — PostgreSQL silently skips rows failing
    USING, so the statement "succeeds" having changed nothing. Both amend tests
    assert the ROW COUNT, and the DELETE one asserts the row is still there.

NEGATIVE CONTROL
    Drop payroll_release_with_gaps_needs_a_reason and the four rule tests write
    an unexplained release straight in. Add a FOR ALL policy in place of the
    SELECT/INSERT pair, or restore the UPDATE/DELETE grants, and the
    append-only tests fail.

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
    reason="release log proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000328"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000328"
RUN = "cccccccc-0000-0000-0000-000000000328"
PARTNER = "f0000000-0000-0000-0000-000000000328"
REASON = "Client confirmed by email on the 3rd that nobody was on leave."


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _as(dsn: str, sql: str) -> subprocess.CompletedProcess:
    """As the signed-in Partner.

    SET LOCAL ROLE authenticated matters: the table is owned by postgres and an
    owner BYPASSES RLS, so running as the migration user would make the
    append-only assertions pass whatever the policies said.
    """
    return _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                      f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{PARTNER}\"}}'; "
                      f"{sql} ROLLBACK;")


def _rows_changed(dsn: str, statement: str) -> int:
    r = _psql(dsn, f"BEGIN; SET LOCAL ROLE authenticated; "
                   f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{PARTNER}\"}}'; "
                   f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t; ROLLBACK;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m328_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "328_a_release_is_defensible_or_it_is_overridden_in_writing.sql" \
            not in pg_template.failed, (
                "migration 328 did not apply — everything below would pass vacuously")
        stmts = [
            f"INSERT INTO auth.users (id, email) VALUES ('{PARTNER}','p328@t.in');",
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}','F328','f328@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}','{FIRM}','C328','Private Limited','AAACA1234E');",
            f"INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
            f"('{PARTNER}','{FIRM}','{PARTNER}','P','p328@t.in','Partner');",
            f"INSERT INTO user_client_assignments (user_id, client_id, firm_id) VALUES "
            f"('{PARTNER}','{CLIENT}','{FIRM}');",
            f"INSERT INTO payroll_runs (id, firm_id, client_id, month, status) VALUES "
            f"('{RUN}','{FIRM}','{CLIENT}','2026-06','finalized');",
        ]
        for sql in stmts:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:70]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _t(to_status="finalized", gaps="'[]'::jsonb", reason="NULL") -> str:
    return (f"INSERT INTO payroll_run_transitions "
            f"(firm_id, run_id, from_status, to_status, gaps, override_reason, actor_id) "
            f"VALUES ('{FIRM}','{RUN}','draft','{to_status}',{gaps},{reason},'{PARTNER}');")


_ONE_GAP = """'["Asha: no attendance entered for this month."]'::jsonb"""


# ── 1. the rule ──────────────────────────────────────────────────────────────

def test_a_clean_release_needs_no_reason(db):
    """The other half of the rule. [] is a POSITIVE record that the release was
    clean, which is why gaps is NOT NULL."""
    assert _psql(db, _t()).returncode == 0


def test_a_release_with_gaps_and_no_reason_is_refused(db):
    r = _psql(db, _t(gaps=_ONE_GAP))
    assert r.returncode != 0
    assert "payroll_release_with_gaps_needs_a_reason" in r.stderr


def test_a_release_with_gaps_and_a_written_reason_is_accepted(db):
    assert _psql(db, _t(gaps=_ONE_GAP, reason=f"'{REASON}'")).returncode == 0


@pytest.mark.parametrize("reason", ["'ok'", "'.'", "'-'", "'n/a'", "'   '", "''"])
def test_a_token_reason_is_refused(db, reason):
    """Twenty characters is not a quality bar — it is a floor under exactly
    these, which is what a required free-text field collects when nothing asks
    for more."""
    r = _psql(db, _t(gaps=_ONE_GAP, reason=reason))
    assert r.returncode != 0
    assert "payroll_release_with_gaps_needs_a_reason" in r.stderr


def test_paid_is_covered_as_well_as_finalized(db):
    """Both release money or a journal. Covering only 'finalized' would leave
    the disbursement path open."""
    r = _psql(db, _t(to_status="paid", gaps=_ONE_GAP))
    assert r.returncode != 0
    assert "payroll_release_with_gaps_needs_a_reason" in r.stderr


@pytest.mark.parametrize("to_status", ["draft", "review"])
def test_a_move_to_draft_or_review_needs_no_reason(db, to_status):
    """They post no journal and pay nobody. Requiring a reason here would only
    teach people to type "n/a" before the moment it matters."""
    assert _psql(db, _t(to_status=to_status, gaps=_ONE_GAP)).returncode == 0


def test_gaps_must_be_an_array(db):
    """A string or an object would read as "gaps recorded" and enumerate to
    nothing, which is the shape of a silent pass.

    The refusal names the gaps CHECK rather than the release rule, and that is
    what the jsonb_typeof guard in the release CHECK is for: jsonb_array_length
    RAISES on a scalar, and PostgreSQL does not promise an order between CHECK
    constraints, so without it the message was "cannot get array length of a
    scalar" — true, and useless to whoever sent the row.
    """
    r = _psql(db, _t(gaps=''''"none"'::jsonb'''))
    assert r.returncode != 0
    assert "payroll_run_transitions_gaps_check" in r.stderr


def test_an_unknown_status_is_refused(db):
    r = _psql(db, _t(to_status="released"))
    assert r.returncode != 0 and "to_status_check" in r.stderr


def test_from_status_may_be_absent(db):
    """A run created straight into a state has no previous one, and inventing
    'draft' would assert a transition that did not happen."""
    assert _psql(db, _t().replace("'draft'", "NULL")).returncode == 0


# ── 2. append-only ───────────────────────────────────────────────────────────

def test_a_partner_can_append(db):
    assert _as(db, _t()).returncode == 0, "the log has to be writable to be a log"


def test_nobody_can_amend_a_logged_transition(db):
    """DENIED OUTRIGHT, which is stronger than the usual RLS outcome.

    A policy-denied UPDATE does not raise — PostgreSQL silently skips the rows
    and the statement "succeeds" having changed nothing, which is why the other
    tests in this repo assert row counts. Here the grant itself is revoked, so
    the statement is refused before any row is considered. Both barriers hold:
    the policy list below shows no UPDATE policy exists either.
    """
    assert _psql(db, _t(gaps=_ONE_GAP, reason=f"'{REASON}'")).returncode == 0
    r = _as(db, "UPDATE payroll_run_transitions SET override_reason = 'something else';")
    assert r.returncode != 0 and "permission denied" in r.stderr
    assert _psql(db, "SELECT override_reason FROM payroll_run_transitions;",
                 tuples=True).stdout.strip() == REASON


def test_nobody_can_rewrite_the_gaps_that_stood(db):
    """The gaps are the other half of the record. Editing them out would leave
    a reason explaining nothing."""
    assert _psql(db, _t(gaps=_ONE_GAP, reason=f"'{REASON}'")).returncode == 0
    r = _as(db, "UPDATE payroll_run_transitions SET gaps = '[]'::jsonb;")
    assert r.returncode != 0 and "permission denied" in r.stderr


def test_nobody_can_delete_a_logged_transition(db):
    assert _psql(db, _t()).returncode == 0
    r = _as(db, "DELETE FROM payroll_run_transitions;")
    assert r.returncode != 0 and "permission denied" in r.stderr
    assert _psql(db, "SELECT count(*) FROM payroll_run_transitions;",
                 tuples=True).stdout.strip() == "1"


def test_no_update_or_delete_policy_exists_either(db):
    """The second barrier. Restoring the grant alone would not reopen amendment,
    because RLS denies any command it has no policy for — and this asserts the
    policy set is exactly the two it should be, so a broad FOR ALL added later
    fails here rather than silently."""
    r = _psql(db, "SELECT cmd FROM pg_policies "
                  "WHERE tablename = 'payroll_run_transitions' ORDER BY cmd;",
              tuples=True)
    assert r.returncode == 0, r.stderr
    cmds = sorted(ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip())
    assert cmds == ["INSERT", "SELECT"], cmds


def test_update_and_delete_are_revoked_at_the_grant_too(db):
    """Belt and braces: a future migration that adds a broad FOR ALL policy to
    this table cannot quietly reopen them."""
    r = _psql(db, "SELECT privilege_type FROM information_schema.role_table_grants "
                  "WHERE table_name = 'payroll_run_transitions' AND grantee = 'authenticated' "
                  "ORDER BY privilege_type;", tuples=True)
    assert r.returncode == 0, r.stderr
    granted = {ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()}
    assert granted == {"INSERT", "SELECT"}, granted


# ── 3. firm isolation ────────────────────────────────────────────────────────

def test_the_log_is_firm_scoped(db):
    """It names employees and the reasons a Partner gave. It is not less
    sensitive than the run it describes."""
    assert _psql(db, _t()).returncode == 0
    other = "f0000000-0000-0000-0000-000000000329"
    setup = _psql(db, f"""
        INSERT INTO auth.users (id, email) VALUES ('{other}','o328@t.in');
        INSERT INTO firms (id, name, email) VALUES
          ('aaaaaaaa-0000-0000-0000-000000000329','F329','f329@t.in');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          ('{other}','aaaaaaaa-0000-0000-0000-000000000329','{other}','O','o328@t.in','Partner');
    """)
    assert setup.returncode == 0, setup.stderr
    r = _psql(db, f"BEGIN; SET LOCAL ROLE authenticated; "
                  f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{other}\"}}'; "
                  f"SELECT count(*) FROM payroll_run_transitions; ROLLBACK;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1] == "0"
