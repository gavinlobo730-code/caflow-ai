"""
Migration 439 — `public.fx_rates` must be writable by the role the API
actually runs as under USE_USER_JWT.

THE BUG THIS PINS

    render.yaml has USE_USER_JWT=true in production, so
    core/supabase_client.get_supabase() — what routers/currencies.py's
    record_fx_rate calls — makes every request as the Postgres role
    `authenticated`, with RLS enforced. Migration 146 enabled RLS on
    `public.fx_rates` and created only a SELECT policy (`read_fx_rates`);
    migration 194's systematic sweep correctly granted `authenticated` SELECT
    on it and nothing else, because SELECT was the only authenticated-scoped
    policy for it to find. There was never an INSERT or UPDATE policy, and
    never an INSERT or UPDATE GRANT to `authenticated` — so the one write
    action Settings > Multi-Currency > Exchange Rates exists for failed with
    SQLSTATE 42501 on every call, surfaced by core/exceptions.py as "The
    server is not permitted to write this table."

    A mock-mode test (tests/test_a_rate_can_be_recorded_at_all.py) cannot see
    this at all: mock mode never touches Postgres, so it proves the
    application logic and says nothing about GRANTs or RLS. This is the test
    that actually runs the write as `authenticated`, the way PostgREST does.

Runs only when HARNESS_PG is set + psql is on PATH — the same gate as the
other DB tests.
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
    reason="fx_rates write-privilege proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


# Every currency `fx_rates` FKs against has to exist first (migration 146
# seeds the ISO 4217 master, USD and INR both included).
_AS_AUTHENTICATED = "SET LOCAL ROLE authenticated;"


@pytest.fixture()
def seeded_db(pg_template):
    """Clone conftest's session-scoped migrated template rather than replaying
    the whole migration set per test — the same pattern every other
    *_pg.py test uses."""
    admin = _ADMIN.strip()
    dbname = f"fxrls_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={dbname}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_authenticated_can_insert_a_rate(seeded_db):
    """The regression test — the exact call PUT /api/currencies/rates makes,
    run as the role production actually executes it under."""
    r = _psql(seeded_db, _AS_AUTHENTICATED + """
        INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
        VALUES ('USD', 'INR', '2026-06-30', 'booking', 83.42, 'manual');
    """)
    assert r.returncode == 0, (
        f"authenticated could not INSERT into fx_rates: {r.stderr}\n"
        "This is the exact SQLSTATE 42501 the CA saw as "
        "'The server is not permitted to write this table.'"
    )
    count = _psql(seeded_db, "SELECT count(*) FROM public.fx_rates;", tuples=True)
    assert count.stdout.strip() == "1"


def test_authenticated_can_update_a_rate(seeded_db):
    """A correction — the ordinary case ('somebody typed 83.42 for 84.32') —
    goes through UPDATE, not a second INSERT (the unique key on
    (base, quote, rate_date, rate_type, source) would reject that)."""
    seed = _psql(seeded_db, """
        INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
        VALUES ('USD', 'INR', '2026-06-30', 'booking', 83.42, 'manual');
    """)
    assert seed.returncode == 0, f"fixture seed failed: {seed.stderr}"

    r = _psql(seeded_db, _AS_AUTHENTICATED + """
        UPDATE public.fx_rates SET rate = 84.32
         WHERE base='USD' AND quote='INR' AND rate_date='2026-06-30'
           AND rate_type='booking' AND source='manual';
    """)
    assert r.returncode == 0, (
        f"authenticated could not UPDATE fx_rates: {r.stderr}")
    rate = _psql(seeded_db, "SELECT rate FROM public.fx_rates;", tuples=True)
    assert rate.stdout.strip().startswith("84.32")


def test_authenticated_can_still_only_read_not_delete(seeded_db):
    """The fix is scoped: it grants INSERT and UPDATE, nothing more. There is
    no delete endpoint for a recorded rate, so DELETE must still be refused —
    proving this migration did not paper over the gap with a blanket grant."""
    seed = _psql(seeded_db, """
        INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
        VALUES ('USD', 'INR', '2026-06-30', 'booking', 83.42, 'manual');
    """)
    assert seed.returncode == 0

    select_ok = _psql(seeded_db, _AS_AUTHENTICATED + "SELECT * FROM public.fx_rates;")
    assert select_ok.returncode == 0, "the pre-existing read must be untouched"

    delete_refused = _psql(seeded_db, _AS_AUTHENTICATED + "DELETE FROM public.fx_rates;")
    assert delete_refused.returncode != 0, (
        "authenticated could DELETE from fx_rates — this migration must only "
        "grant INSERT and UPDATE"
    )
    assert "permission denied" in (delete_refused.stderr or "").lower()
