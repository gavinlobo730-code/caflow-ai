"""Migration 494 — a timeline event can be pinned by staff and rewritten by nobody signed in (ledger POST-A-228).

WHAT THE AUDIT SAW, AND WHAT PRODUCTION HAS
    A database built from the migrations granted `authenticated` UPDATE on every column of `client_timeline_events`
    (migration 045; 056 never revoked it), so a Reviewer could rewrite an event's title, description and actor, or
    soft-delete it. PRODUCTION holds no UPDATE grant at all (read from its catalogue on 14-10-2026), so there the pin
    button was refused for everyone while the screen showed it pinned. The migration makes a migration-built database
    match production and then gives back the one column the screen writes.

WHAT IS ASSERTED, AS A REAL AUTHENTICATED SESSION
    * `authenticated` holds no table-level UPDATE and a column-level UPDATE on `is_pinned` alone;
    * a Reviewer assigned to the client pins and unpins an event;
    * the same Reviewer cannot change its title, its description, who it names, or `deleted_at`, and a Manager cannot either;
    * insert is unaffected (the feed is still written from the browser);
    * the rollback puts the drift back, which is the negative control.

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
ROLLBACK = API_ROOT / "migrations" / "494_a_timeline_event_can_be_pinned_by_staff_and_rewritten_by_nobody_signed_in_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the timeline grant proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000494"
CLIENT = "cccccccc-0000-0000-0000-00000000a494"
EVENT = "eeeeeeee-0000-0000-0000-000000000494"
ACTORS = {"manager": ("Manager", "11111111-1111-1111-1111-000000000001", "bbbbbbbb-1111-1111-1111-000000000001"),
          "reviewer": ("Reviewer", "11111111-1111-1111-1111-000000000002", "bbbbbbbb-1111-1111-1111-000000000002")}


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": ACTORS[who][1], "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"timeline_m494_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{a}', '{k}@m494.test')" for k, (_r, a, _u) in ACTORS.items())
        users = ", ".join(f"('{u}', '{FIRM}', '{a}', '{k}@m494.test', '{k}', '{r}', true)"
                          for k, (r, a, u) in ACTORS.items())
        assigned = ", ".join(f"('{FIRM}', '{u}', '{CLIENT}')" for _r, _a, u in ACTORS.values())
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M494 Firm','m494@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO client_timeline_events (id, firm_id, client_id, financial_year, category, event_type, title)
              VALUES ('{EVENT}','{FIRM}','{CLIENT}','2026-27','general','note','Original title');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _updatable_columns(dsn: str) -> list[str]:
    out = _ok(dsn, "SELECT column_name FROM information_schema.column_privileges "
                   "WHERE table_schema='public' AND table_name='client_timeline_events' "
                   "AND grantee='authenticated' AND privilege_type='UPDATE' ORDER BY 1;")
    return [c for c in out.splitlines() if c]


def _changed(dsn: str, who: str, set_clause: str) -> subprocess.CompletedProcess:
    return _as(dsn, who, f"UPDATE client_timeline_events SET {set_clause} WHERE id = '{EVENT}';")


def test_authenticated_can_update_is_pinned_and_nothing_else(db):
    assert _updatable_columns(db) == ["is_pinned"]
    assert _ok(db, "SELECT has_table_privilege('authenticated','public.client_timeline_events','UPDATE');") == "f"


@pytest.mark.parametrize("who", ["reviewer", "manager"])
def test_staff_pin_and_unpin_an_event(db, who):
    r = _changed(db, who, "is_pinned = true")
    assert r.returncode == 0, r.stderr
    assert _ok(db, f"SELECT is_pinned FROM client_timeline_events WHERE id = '{EVENT}';") == "t"
    assert _changed(db, who, "is_pinned = false").returncode == 0
    assert _ok(db, f"SELECT is_pinned FROM client_timeline_events WHERE id = '{EVENT}';") == "f"


@pytest.mark.parametrize("who", ["reviewer", "manager"])
@pytest.mark.parametrize("set_clause", ["title = 'Rewritten'", "description = 'x'", "actor_name = 'Someone else'",
                                        "deleted_at = now()", "visibility = 'internal'"])
def test_nobody_signed_in_rewrites_an_event(db, who, set_clause):
    r = _changed(db, who, set_clause)
    assert r.returncode != 0 and "permission denied" in r.stderr, set_clause
    assert _ok(db, f"SELECT title FROM client_timeline_events WHERE id = '{EVENT}';") == "Original title"


def test_staff_still_write_the_feed(db):
    r = _as(db, "reviewer", f"INSERT INTO client_timeline_events (firm_id, client_id, financial_year, category, event_type, title) "
                            f"VALUES ('{FIRM}','{CLIENT}','2026-27','general','note','Added by a Reviewer');")
    assert r.returncode == 0, r.stderr


def test_its_own_rollback_puts_the_drift_back(db):
    """The negative control: on the table-level grant a Reviewer rewrites an event.

    Since migration 512 the append-only trigger is a SECOND lock on the same rewrite, so the grant alone no longer lets it
    through: with the trigger in place the rewrite is refused by the trigger (the privilege is back, the event is intact), and
    only with the trigger dropped as well does the drift of 494's rollback show again."""
    r = _psql(db, ROLLBACK.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr
    held = _changed(db, "reviewer", "title = 'Rewritten'")
    assert held.returncode != 0 and "append-only" in held.stderr, held.stderr
    assert _ok(db, f"SELECT title FROM client_timeline_events WHERE id = '{EVENT}';") == "Original title"
    assert _psql(db, "DROP TRIGGER client_timeline_events_append_only ON public.client_timeline_events;").returncode == 0
    assert _changed(db, "reviewer", "title = 'Rewritten'").returncode == 0
    assert _ok(db, f"SELECT title FROM client_timeline_events WHERE id = '{EVENT}';") == "Rewritten"
