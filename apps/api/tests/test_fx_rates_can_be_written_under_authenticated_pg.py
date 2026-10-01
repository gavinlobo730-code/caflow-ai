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

MIGRATION 470 CHANGED WHO THESE TESTS WRITE AS
    They proved 439's repair by writing as `authenticated` with NO identity at
    all — they modelled the privilege gap and, in doing so, modelled exactly
    the caller 470 closes: a signed-in principal who is nobody in particular
    writing the rate every firm's AS 11 revaluation reads. They now write as a
    seeded PARTNER, which is the call `PUT /api/currencies/rates` actually
    makes (`rbac("settings", "write")` is Partner-only), and the second half of
    this file is the other side — who may NOT, and what may not be written.

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
FIRM = "aaaaaaaa-0000-0000-0000-000000000470"
AUTH_PARTNER = "11111111-1111-1111-1111-111111111470"
AUTH_EXEC = "22222222-2222-2222-2222-222222222470"
AUTH_STRANGER = "99999999-9999-9999-9999-999999999470"   # a portal client: no users row
USER_PARTNER = "bbbbbbbb-0000-0000-0000-00000000a470"
USER_EXEC = "bbbbbbbb-0000-0000-0000-00000000b470"


def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\", "
            f"\"role\": \"authenticated\"}}'; SET ROLE authenticated; ")


#: The caller the API actually is: a Partner, as `authenticated`.
_AS_PARTNER = _as(AUTH_PARTNER)


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
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{AUTH_PARTNER}','p470@test.in'), ('{AUTH_EXEC}','e470@test.in'),
              ('{AUTH_STRANGER}','s470@test.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M470 Firm','m470@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role) VALUES
              ('{USER_PARTNER}','{FIRM}','{AUTH_PARTNER}','p470@test.in','Partner 470','Partner'),
              ('{USER_EXEC}',  '{FIRM}','{AUTH_EXEC}',   'e470@test.in','Exec 470','Executive');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def test_authenticated_can_insert_a_rate(seeded_db):
    """The regression test — the exact call PUT /api/currencies/rates makes,
    run as the role production actually executes it under."""
    r = _psql(seeded_db, _AS_PARTNER + """
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

    r = _psql(seeded_db, _AS_PARTNER + """
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

    select_ok = _psql(seeded_db, _AS_PARTNER + "SELECT * FROM public.fx_rates;")
    assert select_ok.returncode == 0, "the pre-existing read must be untouched"

    delete_refused = _psql(seeded_db, _AS_PARTNER + "DELETE FROM public.fx_rates;")
    assert delete_refused.returncode != 0, (
        "authenticated could DELETE from fx_rates — this migration must only "
        "grant INSERT and UPDATE"
    )
    assert "permission denied" in (delete_refused.stderr or "").lower()


# ── migration 470: who may NOT, and what may not be written ───────────────────
_SEED_RATE = """
    INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
    VALUES ('USD', 'INR', '2026-06-30', 'booking', 83.42, 'manual');
"""
_SEED_PROVIDER_RATE = """
    INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
    VALUES ('USD', 'INR', '2026-06-30', 'closing', 83.10, 'rbi');
"""
_INSERT_MANUAL = """
    INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
    VALUES ('USD', 'INR', '2026-07-01', 'booking', 84.00, 'manual');
"""


def _rate(dsn: str, where: str) -> str:
    return _psql(dsn, f"SELECT rate FROM public.fx_rates WHERE {where};",
                 tuples=True).stdout.strip()


@pytest.mark.parametrize("who", [AUTH_EXEC, AUTH_STRANGER], ids=["a member who is not a Partner",
                                                                "a principal with no users row"])
def test_only_a_partner_may_insert_a_rate(seeded_db, who):
    """The executive is staff and the stranger is a portal client or an employee:
    neither may write the rate every firm's year-end revaluation reads, however
    they reach the table. The route said so; now the table does."""
    r = _psql(seeded_db, _as(who) + _INSERT_MANUAL)
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr
    assert _psql(seeded_db, "SELECT count(*) FROM public.fx_rates;",
                 tuples=True).stdout.strip() == "0"


@pytest.mark.parametrize("who", [AUTH_EXEC, AUTH_STRANGER], ids=["a member who is not a Partner",
                                                                "a principal with no users row"])
def test_only_a_partner_may_correct_a_rate(seeded_db, who):
    """An UPDATE that RLS filters out is not an error — it touches zero rows —
    so the assertion is on the figure, not on the exit code."""
    assert _psql(seeded_db, _SEED_RATE).returncode == 0
    r = _psql(seeded_db, _as(who) +
              "UPDATE public.fx_rates SET rate = 1.00 WHERE source = 'manual';")
    assert r.returncode == 0, r.stderr
    assert _rate(seeded_db, "source = 'manual'").startswith("83.42"), (
        "a principal who is not a Partner overwrote a shared exchange rate")


def test_a_suspended_partner_may_not_write_a_rate_either(seeded_db):
    """468's rule reaches this table through my_permission → get_my_user_id."""
    assert _psql(seeded_db, _SEED_RATE).returncode == 0
    assert _psql(seeded_db, f"UPDATE users SET is_active = false WHERE id = '{USER_PARTNER}';"
                 ).returncode == 0
    r = _psql(seeded_db, _AS_PARTNER + _INSERT_MANUAL)
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr
    _psql(seeded_db, _AS_PARTNER +
          "UPDATE public.fx_rates SET rate = 1.00 WHERE source = 'manual';")
    assert _rate(seeded_db, "source = 'manual'").startswith("83.42")


def test_a_partner_may_not_write_a_row_that_is_not_manual(seeded_db):
    """`source` is the provider identifier. `record_fx_rate` always writes
    'manual' and takes no other; a row from a feed is the backend's, so even a
    Partner may neither add one nor rewrite one."""
    r = _psql(seeded_db, _AS_PARTNER + """
        INSERT INTO public.fx_rates (base, quote, rate_date, rate_type, rate, source)
        VALUES ('USD', 'INR', '2026-07-01', 'closing', 90.00, 'rbi');
    """)
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr

    assert _psql(seeded_db, _SEED_PROVIDER_RATE).returncode == 0   # the backend's own write
    _psql(seeded_db, _AS_PARTNER +
          "UPDATE public.fx_rates SET rate = 1.00 WHERE source = 'rbi';")
    assert _rate(seeded_db, "source = 'rbi'").startswith("83.10"), (
        "a member rewrote a provider's rate")
    # ... and cannot launder a manual row into a provider's by renaming it.
    assert _psql(seeded_db, _SEED_RATE).returncode == 0
    r = _psql(seeded_db, _AS_PARTNER +
              "UPDATE public.fx_rates SET source = 'rbi' WHERE source = 'manual';")
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr


def test_a_rate_is_still_readable_by_anyone_signed_in(seeded_db):
    """A rate is a fact about the world, and a portal client's own foreign
    invoice resolves one. 470 narrows the writes and leaves `read_fx_rates`."""
    assert _psql(seeded_db, _SEED_RATE).returncode == 0
    for who in (AUTH_PARTNER, AUTH_EXEC, AUTH_STRANGER):
        out = _psql(seeded_db, _as(who) + "SELECT count(*) FROM public.fx_rates;", tuples=True)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip().splitlines()[-1] == "1", who
