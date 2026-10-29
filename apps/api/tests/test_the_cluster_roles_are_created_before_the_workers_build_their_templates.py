"""The real-Postgres suite can run on several workers, because the cluster-wide roles are created once before any of them builds a template (POST-A-037).

WHAT THE CHANGE IS, AND WHAT WAS NOT PROVED
    The real-Postgres job ran one worker, 63 to 79 minutes on every backend change. Run on four (`-n 4 --dist loadfile`), the whole suite
    (5,692 tests) passed in 43 minutes on a four-core machine with nothing else removed. The tests are safe to spread: each builds a
    database of its own, named uniquely, from a per-worker template. The one thing they share is the CLUSTER, and a role belongs to the
    cluster: every worker's template build runs the compat bootstrap, which creates the Supabase roles (`anon`, `authenticated`,
    `service_role`, `authenticator`, `supabase_storage_admin`) if they are missing, so on a fresh cluster two workers could both find a
    role missing and both create it. `conftest._ensure_cluster_roles` creates them once, under a file lock, before the first template
    build, so the question does not arise. THAT RACE WAS NOT REPRODUCED: four concurrent bootstraps on a fresh cluster all succeeded, and
    so did two four-worker runs of the old fixture on fresh clusters; ONE first run of the old fixture on a fresh cluster failed in
    every test with an empty runner output, for a reason that was not found and did not recur. The lock is a precaution, kept because
    it costs a few milliseconds, and this note is here so nobody reads it as a measured fix.

WHAT IS HELD (no database)
    * the statements `conftest` runs are the bootstrap's own: the same roles with the same attributes and the same membership grant, so
      a role added to or changed in the bootstrap is a red test here and not a race in CI;
    * the fixture asks for the roles before it creates its template database, and the lock is taken by every worker (a file in the
      temporary directory keyed by the cluster, not by the process);
    * the workflow's own command (workers, by file, with the slowest-test list) is held by `test_ci_reports_coverage_and_runs_in_parallel.py`,
      which owns that line.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import conftest

API = Path(__file__).resolve().parent.parent
BOOTSTRAP = (API / "migrations" / "_supabase_compat_bootstrap.sql").read_text()


def _create_roles(sql: str) -> set[str]:
    return {" ".join(m.group(0).split()) for m in re.finditer(r"CREATE ROLE [^;]+;", sql)}


def test_the_roles_created_up_front_are_the_bootstraps_own():
    assert _create_roles(conftest._ROLES_SQL) == _create_roles(BOOTSTRAP)
    assert len(_create_roles(BOOTSTRAP)) == 5, "a role was added to or removed from the bootstrap: read why before changing this"
    membership = "GRANT anon, authenticated, service_role TO authenticator;"
    assert membership in conftest._ROLES_SQL and membership in BOOTSTRAP


def test_the_template_fixture_asks_for_the_roles_before_it_creates_a_database():
    source = (API / "tests" / "conftest.py").read_text()
    fixture = source[source.index("def pg_template():"):]
    assert fixture.index("_ensure_cluster_roles(admin_dsn)") < fixture.index('CREATE DATABASE "{name}"')


def test_the_roles_are_created_under_a_lock_every_worker_takes():
    body = (API / "tests" / "conftest.py").read_text()
    helper = body[body.index("def _ensure_cluster_roles"):body.index("class PgTemplate")]
    assert "fcntl.flock(lock, fcntl.LOCK_EX)" in helper and "tempfile.gettempdir()" in helper
    assert "os.getpid" not in helper and "PYTEST_XDIST_WORKER" not in helper, "the lock key must be the cluster, never the worker"
