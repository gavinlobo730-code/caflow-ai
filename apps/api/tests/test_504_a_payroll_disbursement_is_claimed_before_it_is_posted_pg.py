"""A payroll disbursement is claimed in the database before it is posted (migration 504, POST-A-239).

WHAT THIS PROVES AND WHY IT NEEDS A REAL DATABASE

The API claims a finalized run by one conditional UPDATE on `payroll_runs.disbursement_claimed_at` and posts the
salary disbursement only if that UPDATE changed a row. The mock suite can stage the interleaving but cannot show that
two real sessions are serialised by the row lock: that the second one waits for the first to commit and then, seeing the
claim, changes nothing. That is the whole guarantee, so it is driven here with two connections.

It also holds the two things the column must not disturb: migration 498's rule that a signed-in session cannot write a
finalized run (so nobody can clear or forge a claim on one), and that the API's role can.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from tests._signed_in_payroll_writes import give_the_signed_in_payroll_access_back

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the disbursement claim is a row-lock guarantee and needs a real Postgres",
)

FIRM = "f5040000-0000-0000-0000-000000000001"
CLIENT = "c5040000-0000-0000-0000-000000000001"
RUN = "4b040000-0000-0000-0000-000000000001"
JOURNAL = "10504000-0000-0000-0000-000000000001"
DISBURSEMENT = "10504000-0000-0000-0000-000000000002"

#: What PostgREST sends for the API's two claim attempts (`_claim_the_run_for_disbursement`), written out: the run nobody
#: holds, then the run whose claim has lapsed.
CLAIM_FREE = f"""
    UPDATE payroll_runs SET disbursement_claimed_at = now()
     WHERE id = '{RUN}' AND firm_id = '{FIRM}' AND status = 'finalized' AND disbursement_claimed_at IS NULL
    RETURNING id
"""
CLAIM_LAPSED = f"""
    UPDATE payroll_runs SET disbursement_claimed_at = now()
     WHERE id = '{RUN}' AND firm_id = '{FIRM}' AND status = 'finalized'
       AND disbursement_claimed_at < now() - interval '15 minutes'
    RETURNING id
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _one(dsn: str, sql: str) -> str:
    res = _psql(dsn, sql, tuples=True)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def _claim(dsn: str) -> str:
    """The API's two attempts in order; the id of the run if either changed a row, else empty."""
    return _one(dsn, CLAIM_FREE) or _one(dsn, CLAIM_LAPSED)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"claim504_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    seed = _psql(dsn, f"""
        INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Claim Co', 'a@claim.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'Payer Ltd', 'Private Limited');
        INSERT INTO payroll_runs (id, firm_id, client_id, month, status, journal_entry_id)
          VALUES ('{RUN}', '{FIRM}', '{CLIENT}', '2026-07', 'finalized', NULL);
    """)
    assert seed.returncode == 0, seed.stderr
    try:
        give_the_signed_in_payroll_access_back(dsn)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_the_column_is_a_nullable_timestamp_with_no_default(db):
    row = _one(db, "SELECT data_type || '|' || is_nullable || '|' || COALESCE(column_default, 'none') "
                   "FROM information_schema.columns WHERE table_name='payroll_runs' "
                   "AND column_name='disbursement_claimed_at';")
    assert row == "timestamp with time zone|YES|none"
    assert _one(db, f"SELECT disbursement_claimed_at IS NULL FROM payroll_runs WHERE id='{RUN}';") == "t"


def test_a_claim_is_taken_once_and_a_lapsed_one_can_be_taken_again(db):
    assert _claim(db) == RUN, "the first request gets the run"
    assert _claim(db) == "", "a claim taken a moment ago is held"
    _psql(db, f"UPDATE payroll_runs SET disbursement_claimed_at = now() - interval '20 minutes' WHERE id='{RUN}';")
    assert _claim(db) == RUN, "a claim older than fifteen minutes has lapsed"


def test_a_run_that_is_not_finalized_cannot_be_claimed(db):
    _psql(db, f"UPDATE payroll_runs SET status='review' WHERE id='{RUN}';")
    assert _claim(db) == ""


def test_two_sessions_claiming_at_the_same_moment_are_serialised_and_only_one_gets_the_run(db):
    """Session one claims and holds its transaction open; session two sends the same claim while it is open. Postgres makes
    the second wait on the row lock and, once the first commits, re-reads the row: the claim is there, so it changes
    nothing. This is the property the API relies on and the mock suite cannot show."""
    first = subprocess.Popen(
        ["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c",
         f"BEGIN; {CLAIM_FREE}; SELECT pg_sleep(2.5); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.8)
    started = time.monotonic()
    second = _psql(db, CLAIM_FREE, tuples=True)
    waited = time.monotonic() - started
    out, err = first.communicate(timeout=30)
    assert first.returncode == 0, err
    assert second.returncode == 0, second.stderr
    assert RUN in out, "the first session got the run"
    assert second.stdout.strip() == "", "the second session must change no row"
    assert waited > 1.0, f"the second claim returned after {waited:.2f}s: it did not wait on the first session's lock"


def test_the_api_role_can_write_the_claim_on_a_finalized_run(db):
    api = _psql(db, f"BEGIN; SET LOCAL ROLE service_role; {CLAIM_FREE}; COMMIT;", tuples=True)
    assert api.returncode == 0, api.stderr
    assert RUN in api.stdout


def test_a_signed_in_session_cannot_write_a_payroll_run_at_all_and_the_trigger_would_refuse_it_if_it_could(db):
    """Two layers, each shown separately. Migration 499 revokes UPDATE on payroll_runs from the signed-in roles, so the
    refusal is a missing privilege. Migration 498's trigger is the second lock: grant the privilege back inside this
    scratch database and the trigger still refuses a change to a finalized run. Neither the claim nor its release can be
    forged from a browser session."""
    for role in ("authenticated", "anon"):
        assert _one(db, f"SELECT has_table_privilege('{role}', 'public.payroll_runs', 'UPDATE');") == "f", role
        refused = _psql(db, f"BEGIN; SET LOCAL ROLE {role}; "
                            f"UPDATE payroll_runs SET disbursement_claimed_at = NULL WHERE id='{RUN}'; COMMIT;")
        assert refused.returncode != 0 and "permission denied" in refused.stderr, refused.stderr

    # In this scratch copy only: hand the privilege back and switch row security off, so that the row is visible to the
    # signed-in role and the trigger (which only fires for a row the statement can reach) is what decides.
    assert _psql(db, "GRANT UPDATE ON public.payroll_runs TO authenticated; "
                     "ALTER TABLE public.payroll_runs DISABLE ROW LEVEL SECURITY;").returncode == 0
    trigger = _psql(db, f"BEGIN; SET LOCAL ROLE authenticated; "
                        f"UPDATE payroll_runs SET disbursement_claimed_at = NULL WHERE id='{RUN}'; COMMIT;")
    assert trigger.returncode != 0 and "cannot be changed from a signed-in session" in trigger.stderr, trigger.stderr


def _journals(dsn: str) -> None:
    _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type)
          VALUES ('{JOURNAL}', '{FIRM}', '{CLIENT}', '2026-07-31', 'PAY-2026-07', 'x', 'Journal'),
                 ('{DISBURSEMENT}', '{FIRM}', '{CLIENT}', '2026-08-01', 'PAY-DISB-2026-07', 'x', 'Payment');
    """)


#: What `finalize_run` sends to claim a run: one conditional UPDATE that carries the journal id (migration 498's evidence).
RELEASE = f"""
    UPDATE payroll_runs SET status = 'finalized', finalized_at = now(), journal_entry_id = '{JOURNAL}',
           disbursement_claimed_at = NULL
     WHERE id = '{RUN}' AND firm_id = '{FIRM}' AND status NOT IN ('finalized', 'paid')
    RETURNING id
"""


def test_the_release_claim_changes_one_row_once_and_is_serialised_across_two_sessions(db):
    _journals(db)
    _psql(db, f"UPDATE payroll_runs SET status='review', journal_entry_id=NULL WHERE id='{RUN}';")

    first = subprocess.Popen(
        ["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c",
         f"BEGIN; SET LOCAL ROLE service_role; {RELEASE}; SELECT pg_sleep(2.5); COMMIT;"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.8)
    started = time.monotonic()
    second = _psql(db, f"BEGIN; SET LOCAL ROLE service_role; {RELEASE}; COMMIT;", tuples=True)
    waited = time.monotonic() - started
    out, err = first.communicate(timeout=30)
    assert first.returncode == 0, err
    assert second.returncode == 0, second.stderr
    assert RUN in out, "the first session released the run"
    assert RUN not in second.stdout, "the second session must change no row"
    assert waited > 1.0, f"the second release returned after {waited:.2f}s: it did not wait on the first session's lock"
    assert _one(db, f"SELECT status FROM payroll_runs WHERE id='{RUN}';") == "finalized"


def test_the_paid_write_is_conditional_on_the_run_and_the_claim_and_still_needs_both_journals(db):
    """The write `disburse_run` makes after posting: status paid, the disbursement journal, and the claim cleared, but
    only on a finalized run that still carries THIS request's claim. Migration 498's evidence rule is untouched."""
    _journals(db)
    _psql(db, f"UPDATE payroll_runs SET journal_entry_id='{JOURNAL}' WHERE id='{RUN}';")
    assert _one(db, CLAIM_FREE) == RUN
    stamp = _one(db, f"SELECT disbursement_claimed_at FROM payroll_runs WHERE id='{RUN}';")

    def paid(extra: str, journal: str = f"'{DISBURSEMENT}'") -> subprocess.CompletedProcess:
        return _psql(db, f"""BEGIN; SET LOCAL ROLE service_role;
            UPDATE payroll_runs SET status='paid', paid_at=now(), disbursement_journal_entry_id={journal},
                   disbursement_claimed_at=NULL
             WHERE id='{RUN}' AND firm_id='{FIRM}' AND status='finalized' {extra} RETURNING id; COMMIT;""", tuples=True)

    other = paid("AND disbursement_claimed_at = '1999-01-01T00:00:00+00:00'")
    assert other.returncode == 0 and RUN not in other.stdout, "another request's claim stamp must not match"
    without = paid(f"AND disbursement_claimed_at = '{stamp}'", journal="NULL")
    assert without.returncode != 0 and "disbursement journal" in without.stderr, "a run is never paid without its journal"
    ok = paid(f"AND disbursement_claimed_at = '{stamp}'")
    assert ok.returncode == 0 and RUN in ok.stdout
    assert _one(db, f"SELECT status || '|' || (disbursement_claimed_at IS NULL)::text FROM payroll_runs WHERE id='{RUN}';") == "paid|true"

    _psql(db, f"UPDATE payroll_runs SET status='review' WHERE id='{RUN}';")                  # a reversal reopens the run
    again = paid(f"AND disbursement_claimed_at = '{stamp}'")
    assert again.returncode == 0 and RUN not in again.stdout, "a reopened run must not be marked paid by a late write"


def test_the_rollback_drops_the_column_and_the_migration_can_be_applied_again(db):
    rollback = MIGRATIONS / "504_a_payroll_disbursement_is_claimed_before_it_is_posted_rollback.sql"
    forward = MIGRATIONS / "504_a_payroll_disbursement_is_claimed_before_it_is_posted.sql"
    assert _psql(db, rollback.read_text(encoding="utf-8")).returncode == 0
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='payroll_runs' "
                    "AND column_name='disbursement_claimed_at';") == "0"
    assert _psql(db, forward.read_text(encoding="utf-8")).returncode == 0
    assert _psql(db, forward.read_text(encoding="utf-8")).returncode == 0, "applying it twice must not fail"
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='payroll_runs' "
                    "AND column_name='disbursement_claimed_at';") == "1"
