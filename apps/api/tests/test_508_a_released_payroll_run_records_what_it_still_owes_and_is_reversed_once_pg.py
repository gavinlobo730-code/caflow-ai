"""A released payroll run records the loan write-down it still owes, and a reversal is claimed (migration 508,
POST-A-253 and POST-A-254).

WHAT THIS PROVES AND WHY IT NEEDS A REAL DATABASE

The API takes the reversal lease with one conditional UPDATE on `payroll_runs.reversal_claimed_at` and reverses only if
that UPDATE changed a row, then reopens the run with an UPDATE conditional on the claim it took. The mock suite can stage
an interleaving but cannot show that two real sessions are serialised by the row lock, which is the whole guarantee, so it
is driven here with two connections. It also holds that the owed-write-down record is written in the release's own UPDATE
and cleared only by the stamp that wrote it, and that a signed-in session can write neither column on a released run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the reversal claim is a row-lock guarantee and needs a real Postgres",
)

FIRM = "f5080000-0000-0000-0000-000000000001"
CLIENT = "c5080000-0000-0000-0000-000000000001"
RUN = "4b080000-0000-0000-0000-000000000001"
JOURNAL = "10508000-0000-0000-0000-000000000001"

#: What PostgREST sends for the API's two reversal-claim attempts (`_claim_the_run_for_reversal`), written out: the run
#: nobody holds, then the run whose claim has lapsed.
CLAIM_FREE = f"""
    UPDATE payroll_runs SET reversal_claimed_at = now()
     WHERE id = '{RUN}' AND firm_id = '{FIRM}' AND status IN ('finalized', 'paid') AND reversal_claimed_at IS NULL
    RETURNING id
"""
CLAIM_LAPSED = f"""
    UPDATE payroll_runs SET reversal_claimed_at = now()
     WHERE id = '{RUN}' AND firm_id = '{FIRM}' AND status IN ('finalized', 'paid')
       AND reversal_claimed_at < now() - interval '15 minutes'
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
    name = f"claim508_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    seed = _psql(dsn, f"""
        INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Reversal Co', 'a@reversal.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'Payer Ltd', 'Private Limited');
        INSERT INTO payroll_runs (id, firm_id, client_id, month, status, journal_entry_id)
          VALUES ('{RUN}', '{FIRM}', '{CLIENT}', '2026-07', 'finalized', NULL);
    """)
    assert seed.returncode == 0, seed.stderr
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.mark.parametrize("column", ["loan_writedown_owed_at", "reversal_claimed_at"])
def test_each_column_is_a_nullable_timestamp_with_no_default_and_existing_rows_are_unmarked(db, column):
    row = _one(db, "SELECT data_type || '|' || is_nullable || '|' || COALESCE(column_default, 'none') "
                   f"FROM information_schema.columns WHERE table_name='payroll_runs' AND column_name='{column}';")
    assert row == "timestamp with time zone|YES|none"
    assert _one(db, f"SELECT {column} IS NULL FROM payroll_runs WHERE id='{RUN}';") == "t"


def test_a_reversal_claim_is_taken_once_and_a_lapsed_one_can_be_taken_again(db):
    assert _claim(db) == RUN, "the first request gets the run"
    assert _claim(db) == "", "a claim taken a moment ago is held"
    _psql(db, f"UPDATE payroll_runs SET reversal_claimed_at = now() - interval '20 minutes' WHERE id='{RUN}';")
    assert _claim(db) == RUN, "a claim older than fifteen minutes has lapsed"


def test_a_paid_run_can_be_claimed_and_a_run_that_is_not_released_cannot(db):
    _psql(db, f"UPDATE payroll_runs SET status='review' WHERE id='{RUN}';")
    assert _claim(db) == "", "a run in review has nothing to reverse"


def test_two_sessions_claiming_a_reversal_at_the_same_moment_are_serialised_and_only_one_gets_the_run(db):
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


def test_the_reopen_is_conditional_on_the_claim_that_was_taken(db):
    """`reverse_run` reopens the run with an UPDATE that carries the claim it took. A request whose lease lapsed and was
    taken over holds a stamp that no longer matches, so its reopen changes no row."""
    assert _claim(db) == RUN
    stamp = _one(db, f"SELECT reversal_claimed_at FROM payroll_runs WHERE id='{RUN}';")

    def reopen(on: str) -> subprocess.CompletedProcess:
        return _psql(db, f"""BEGIN; SET LOCAL ROLE service_role;
            UPDATE payroll_runs SET status='review', journal_entry_id=NULL, finalized_at=NULL,
                   disbursement_claimed_at=NULL, loan_writedown_owed_at=NULL, reversal_claimed_at=NULL
             WHERE id='{RUN}' AND firm_id='{FIRM}' AND reversal_claimed_at = {on} RETURNING id; COMMIT;""", tuples=True)

    other = reopen("'1999-01-01T00:00:00+00:00'")
    assert other.returncode == 0 and RUN not in other.stdout, "another request's stamp must not match"
    ok = reopen(f"'{stamp}'")
    assert ok.returncode == 0 and RUN in ok.stdout
    assert _one(db, f"SELECT status || '|' || (reversal_claimed_at IS NULL)::text FROM payroll_runs WHERE id='{RUN}';") == "review|true"


def _journal(dsn: str) -> None:
    _psql(dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type)
          VALUES ('{JOURNAL}', '{FIRM}', '{CLIENT}', '2026-07-31', 'PAY-2026-07', 'x', 'Journal');
    """)


def test_the_release_records_the_owed_write_down_in_its_own_update_and_only_its_stamp_clears_it(db):
    _journal(db)
    _psql(db, f"UPDATE payroll_runs SET status='review', journal_entry_id=NULL WHERE id='{RUN}';")
    stamp = "2026-10-18T05:00:00+00:00"
    release = _psql(db, f"""BEGIN; SET LOCAL ROLE service_role;
        UPDATE payroll_runs SET status='finalized', finalized_at=now(), journal_entry_id='{JOURNAL}',
               loan_writedown_owed_at='{stamp}', disbursement_claimed_at=NULL
         WHERE id='{RUN}' AND firm_id='{FIRM}' AND status NOT IN ('finalized','paid') RETURNING id; COMMIT;""", tuples=True)
    assert release.returncode == 0 and RUN in release.stdout, release.stderr
    assert _one(db, f"SELECT loan_writedown_owed_at IS NOT NULL FROM payroll_runs WHERE id='{RUN}';") == "t"

    def clear(on: str) -> subprocess.CompletedProcess:
        return _psql(db, f"""BEGIN; SET LOCAL ROLE service_role;
            UPDATE payroll_runs SET loan_writedown_owed_at=NULL
             WHERE id='{RUN}' AND firm_id='{FIRM}' AND loan_writedown_owed_at = {on} RETURNING id; COMMIT;""", tuples=True)

    stale = clear("'1999-01-01T00:00:00+00:00'")
    assert stale.returncode == 0 and RUN not in stale.stdout, "a different release's stamp must not clear the debt"
    done = clear(f"'{stamp}'")
    assert done.returncode == 0 and RUN in done.stdout
    assert _one(db, f"SELECT loan_writedown_owed_at IS NULL FROM payroll_runs WHERE id='{RUN}';") == "t"


def test_a_signed_in_session_cannot_write_either_column(db):
    for role in ("authenticated", "anon"):
        assert _one(db, f"SELECT has_table_privilege('{role}', 'public.payroll_runs', 'UPDATE');") == "f", role
        for column in ("loan_writedown_owed_at", "reversal_claimed_at"):
            refused = _psql(db, f"BEGIN; SET LOCAL ROLE {role}; "
                                f"UPDATE payroll_runs SET {column} = NULL WHERE id='{RUN}'; COMMIT;")
            assert refused.returncode != 0 and "permission denied" in refused.stderr, refused.stderr


def test_the_api_role_can_write_both_columns_on_a_finalized_run(db):
    api = _psql(db, f"BEGIN; SET LOCAL ROLE service_role; {CLAIM_FREE}; "
                    f"UPDATE payroll_runs SET loan_writedown_owed_at = now() WHERE id='{RUN}' RETURNING id; COMMIT;",
                tuples=True)
    assert api.returncode == 0, api.stderr
    assert RUN in api.stdout


def test_the_rollback_drops_both_columns_and_the_migration_can_be_applied_again(db):
    stem = "508_a_released_payroll_run_records_what_it_still_owes_and_is_reversed_once"
    rollback = MIGRATIONS / f"{stem}_rollback.sql"
    forward = MIGRATIONS / f"{stem}.sql"
    assert _psql(db, rollback.read_text(encoding="utf-8")).returncode == 0
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='payroll_runs' "
                    "AND column_name IN ('loan_writedown_owed_at','reversal_claimed_at');") == "0"
    assert _psql(db, forward.read_text(encoding="utf-8")).returncode == 0
    assert _psql(db, forward.read_text(encoding="utf-8")).returncode == 0, "applying it twice must not fail"
    assert _one(db, "SELECT count(*) FROM information_schema.columns WHERE table_name='payroll_runs' "
                    "AND column_name IN ('loan_writedown_owed_at','reversal_claimed_at');") == "2"
