"""Migration 471 on real PostgreSQL — a scheduled job is claimed before it runs (ops-14).

WHAT IS PROVEN HERE, AND WHY IT HAS TO BE REAL POSTGRES
    The guarantee is that two instances racing for one (job, day, firm) get ONE winner. That is
    a property of `INSERT ... ON CONFLICT DO UPDATE ... WHERE` under concurrency — a second
    claimant waits on the first's uncommitted row, then evaluates the WHERE against the row the
    first left — and no in-memory model can prove it. So the race below is real: several psql
    sessions each open a transaction, claim, HOLD the transaction open for a second and a half
    and commit, so the losers are genuinely queued behind the winner's lock.

    * the claim state machine, as a table (`_claim_scenarios.py`) — the SAME table the
      in-memory store is held to in the mock-mode suite, so the two implementations cannot
      drift apart without one of the two files failing;
    * a fresh claim among N concurrent claimants has exactly one winner, and the losers are
      told "running";
    * so does a TAKEOVER of an expired claim — the crash path — among N concurrent claimants;
    * a lease outside 30 seconds to a day is refused by the function;
    * `prune` deletes old days and nothing else, and refuses to keep fewer than two;
    * the table and the four functions are the service role's alone: RLS is on with no policy,
      `anon` and `authenticated` hold no privilege on the table and no EXECUTE on the functions;
    * the production store's writer (jobs/claims.PostgrestClaimStore) and these functions
      cannot drift: the parameter names it sends are asserted against the function signatures
      in the mock-mode file, which can run without a database.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _claim_scenarios import D1, FIRM_A, FIRM_B, JOB, SCENARIOS, run as run_scenario  # noqa: E402

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _as_role(dsn: str, role: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SET ROLE {role}; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m471_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM_A}', 'F1', 'f1@t.in'), ('{FIRM_B}', 'F2', 'f2@t.in');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _claim_sql(job, date, firm, key, owner, force=False, retry_after=0, lease=600) -> str:
    return (f"SELECT public.claim_scheduler_job('{job}', '{date}', '{firm}', '{owner}', "
            f"'{key}', {lease}, {str(force).lower()}, {retry_after});")


class _PgAdapter:
    def __init__(self, dsn):
        self.dsn = dsn

    def claim(self, job, date, firm, key, owner, force, retry_after):
        return json.loads(_scalar(self.dsn, _claim_sql(job, date, firm, key, owner, force, retry_after)))

    def finish(self, claim_id, owner, status):
        return _scalar(self.dsn, f"SELECT public.finish_scheduler_claim('{claim_id}', '{owner}', '{status}');") == "t"

    def renew(self, claim_id, owner):
        return _scalar(self.dsn, f"SELECT public.renew_scheduler_claim('{claim_id}', '{owner}', 600);") == "t"

    def expire(self, job, date, firm, key):
        r = _psql(self.dsn, "UPDATE public.scheduler_claims SET expires_at = now() - interval '1 second' "
                            f"WHERE job_name='{job}' AND run_date='{date}' AND firm_id='{firm}' AND claim_key='{key}';")
        assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_the_sql_follows_the_claim_table(db, name):
    run_scenario(_PgAdapter(db), SCENARIOS[name])


# ── the race ─────────────────────────────────────────────────────────────────

def _race(dsn: str, sql_for_owner, owners: list[str], hold_seconds: float = 1.5) -> list[dict]:
    """Every owner opens a transaction, runs its claim, HOLDS the transaction open, then commits.
    Started together, so the later ones queue on the earlier one's row. Returns each owner's
    claim result."""
    procs = []
    for owner in owners:
        script = (f"BEGIN;\n{sql_for_owner(owner)}\nSELECT pg_sleep({hold_seconds});\nCOMMIT;\n")
        p = subprocess.Popen(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-f", "-"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        p.stdin.write(script)
        p.stdin.close()
        procs.append(p)
    out = []
    for p in procs:
        stdout, stderr = p.stdout.read(), p.stderr.read()
        p.wait(timeout=60)
        assert p.returncode == 0, stderr
        line = next(l for l in stdout.splitlines() if l.startswith("{"))
        out.append(json.loads(line))
    return out


def test_four_instances_racing_for_a_fresh_claim_have_exactly_one_winner(db):
    owners = [f"inst-{i}" for i in range(4)]
    results = _race(db, lambda o: _claim_sql(JOB, D1, FIRM_A, "", o), owners)
    winners = [r for r in results if r["claimed"]]
    losers = [r for r in results if not r["claimed"]]
    assert len(winners) == 1, results
    assert len(losers) == 3 and all(r["status"] == "running" for r in losers), results
    assert _scalar(db, "SELECT count(*) FROM public.scheduler_claims;") == "1"
    assert _scalar(db, "SELECT status FROM public.scheduler_claims;") == "running"


def test_four_instances_racing_to_take_over_a_dead_holders_claim_have_exactly_one_winner(db):
    """The crash path under contention: the old holder's lease has run out and every survivor
    tries at once. The row is locked by whoever gets there first; the rest re-evaluate the WHERE
    against the row the winner left — now running, with a fresh lease — and are refused."""
    adapter = _PgAdapter(db)
    first = adapter.claim(JOB, D1, FIRM_A, "", "dead-inst", False, 0)
    assert first["claimed"]
    adapter.expire(JOB, D1, FIRM_A, "")
    owners = [f"survivor-{i}" for i in range(4)]
    results = _race(db, lambda o: _claim_sql(JOB, D1, FIRM_A, "", o), owners)
    winners = [r for r in results if r["claimed"]]
    assert len(winners) == 1, results
    assert winners[0]["attempt"] == 2
    assert all(r["status"] == "running" for r in results if not r["claimed"]), results
    assert _scalar(db, "SELECT attempt FROM public.scheduler_claims;") == "2"


def test_racing_claims_for_different_firms_all_win(db):
    """The lock is per (job, day, firm, key): firms do not queue behind each other."""
    firms = [FIRM_A, FIRM_B]
    results = _race(db, lambda o: _claim_sql(JOB, D1, o, "", "same-inst"), firms)
    assert [r["claimed"] for r in results] == [True, True]


# ── the guards in the function ───────────────────────────────────────────────

@pytest.mark.parametrize("lease", [0, 29, 86401])
def test_a_lease_outside_thirty_seconds_to_a_day_is_refused(db, lease):
    r = _psql(db, _claim_sql(JOB, D1, FIRM_A, "", "x", lease=lease))
    assert r.returncode != 0 and "lease" in r.stderr


def test_a_status_other_than_success_or_failed_cannot_end_a_claim(db):
    got = _PgAdapter(db).claim(JOB, D1, FIRM_A, "", "x", False, 0)
    r = _psql(db, f"SELECT public.finish_scheduler_claim('{got['id']}', 'x', 'running');")
    assert r.returncode != 0 and "success or failed" in r.stderr


def test_a_claim_row_cannot_carry_a_status_the_check_does_not_name(db):
    _PgAdapter(db).claim(JOB, D1, FIRM_A, "", "x", False, 0)
    r = _psql(db, "UPDATE public.scheduler_claims SET status = 'weird';")
    assert r.returncode != 0 and "violates check constraint" in r.stderr


def test_a_claim_needs_a_firm_that_exists(db):
    r = _psql(db, _claim_sql(JOB, D1, "47100000-0000-0000-0000-0000000000ff", "", "x"))
    assert r.returncode != 0 and "foreign key" in r.stderr


# ── prune ────────────────────────────────────────────────────────────────────

def test_prune_forgets_old_days_and_keeps_recent_ones(db):
    a = _PgAdapter(db)
    a.claim(JOB, "2026-01-01", FIRM_A, "", "x", False, 0)
    a.claim(JOB, "2999-01-01", FIRM_A, "", "x", False, 0)
    assert _scalar(db, "SELECT public.prune_scheduler_claims(30);") == "1"
    assert _scalar(db, "SELECT count(*) FROM public.scheduler_claims;") == "1"
    assert _scalar(db, "SELECT run_date FROM public.scheduler_claims;") == "2999-01-01"


def test_prune_will_not_keep_fewer_than_two_days(db):
    r = _psql(db, "SELECT public.prune_scheduler_claims(1);")
    assert r.returncode != 0 and "at least two days" in r.stderr


# ── who can touch it ─────────────────────────────────────────────────────────

def test_the_table_has_rls_on_and_no_policy(db):
    assert _scalar(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.scheduler_claims'::regclass;") == "t"
    assert _scalar(db, "SELECT count(*) FROM pg_policy WHERE polrelid = 'public.scheduler_claims'::regclass;") == "0"


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_a_browser_role_has_no_privilege_on_the_table(db, role):
    for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _scalar(db, f"SELECT has_table_privilege('{role}', 'public.scheduler_claims', '{priv}');") == "f", (role, priv)
    r = _as_role(db, role, "SELECT count(*) FROM public.scheduler_claims;")
    assert r.returncode != 0 and "permission denied" in r.stderr


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("fn", [
    "claim_scheduler_job(text, date, uuid, text, text, integer, boolean, integer)",
    "renew_scheduler_claim(uuid, text, integer)",
    "finish_scheduler_claim(uuid, text, text)",
    "prune_scheduler_claims(integer)",
])
def test_a_browser_role_cannot_execute_a_claim_function(db, role, fn):
    assert _scalar(db, f"SELECT has_function_privilege('{role}', 'public.{fn}', 'EXECUTE');") == "f"


def test_the_service_role_can_execute_all_four_and_write_the_table(db):
    for fn in ("claim_scheduler_job(text, date, uuid, text, text, integer, boolean, integer)",
               "renew_scheduler_claim(uuid, text, integer)",
               "finish_scheduler_claim(uuid, text, text)",
               "prune_scheduler_claims(integer)"):
        assert _scalar(db, f"SELECT has_function_privilege('service_role', 'public.{fn}', 'EXECUTE');") == "t", fn
    r = _as_role(db, "service_role", _claim_sql(JOB, D1, FIRM_A, "", "svc"))
    assert r.returncode == 0, r.stderr
