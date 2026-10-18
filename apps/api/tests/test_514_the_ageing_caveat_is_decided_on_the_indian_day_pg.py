"""Migration 514 — the ageing schedule's "balance outstanding today" caveat is decided on the Indian day (ledger POST-A-252).

THE DEFECT
    `public.schedule_iii_ageing` printed its caveat ("Amounts are each document's balance outstanding TODAY ...") when
    `p_as_of < CURRENT_DATE`. `CURRENT_DATE` is the date in the SESSION'S time zone, and the hosting platform's sessions are
    UTC, so between 00:00 and 05:30 IST the SQL's "today" was the previous Indian day: a schedule as at the previous Indian day
    carried no caveat although a document settled since is missing from it. The Python twin is given the Indian day, so the
    two halves answered the same question differently.

WHAT IS HELD
    * (no database) the migration's body is the body of the migration that LAST defined the function before it (found by
      scanning the migration directory, so it cannot be pointed at a stale ancestor), changed in the caveat's condition and its
      closing comment and nowhere else, and it no longer says `CURRENT_DATE`;
    * (database) whatever the session's time zone, the caveat is present for a schedule as at the previous Indian day and
      absent for one as at the Indian day and the next. Two session zones are tried, one far behind India and one far ahead
      (UTC-12 and UTC+14), because at any instant at least one of them has a date different from the Indian day, so the old
      `CURRENT_DATE` fails this test at every hour of the day and not only in the five and a half hours the defect shows;
    * (database) the function is still STABLE and SECURITY DEFINER with the same search path, and still executable by
      `authenticated` and not `anon`;
    * (database) the rollback puts the session's day back, which is the negative control: with it applied the same probes
      disagree in at least one zone.

Runs only when HARNESS_PG is set + psql on PATH (the derivation check runs always).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_STEM = "514_the_ageing_caveat_is_decided_on_the_indian_day"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the ageing-caveat proofs require HARNESS_PG + psql",
)

CAVEAT = "as_at_is_current_balance"
FIRM = "f5140000-0000-0000-0000-000000000001"
CLIENT = "c5140000-0000-0000-0000-000000000001"


# ── no database ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _function_block(sql: str) -> str:
    """From the CREATE to the end of the function's own GRANT (or to the end of the file when the definer wrote none)."""
    start = sql.index("CREATE OR REPLACE FUNCTION public.schedule_iii_ageing(")
    grant = re.search(r"GRANT EXECUTE ON FUNCTION public\.schedule_iii_ageing\(uuid, uuid, date\)\s+TO authenticated;",
                      sql[start:])
    return sql[start:start + grant.end()] if grant else sql[start:]


def _ancestor() -> tuple[str, str]:
    """The (file name, function block) of the highest-numbered migration BELOW this one that defines the function."""
    own = int(_STEM.split("_", 1)[0])
    best = None
    for path in sorted(MIGRATIONS.glob("[0-9]*.sql")):
        number = int(path.name.split("_", 1)[0])
        if number >= own or path.name.endswith("_rollback.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        if "CREATE OR REPLACE FUNCTION public.schedule_iii_ageing(" in text:
            best = (path.name, _function_block(text))
    assert best is not None
    return best


def test_the_body_is_the_last_definers_body_with_the_caveat_condition_changed_and_nothing_else():
    name, ancestor = _ancestor()
    assert name.startswith("436_"), f"the last definer is {name}: derive this migration from it, not from memory"
    mine = _function_block(MIGRATION.read_text(encoding="utf-8"))
    expected = ancestor.replace("WHERE p_as_of < CURRENT_DATE", "WHERE p_as_of < (now() AT TIME ZONE 'Asia/Kolkata')::date")
    expected = expected.replace("'Migrations 303, 305 and 436.'", "'Migrations 303, 305, 436 and 514.'")
    assert mine == expected


def test_the_new_body_asks_no_session_clock():
    mine = _function_block(MIGRATION.read_text(encoding="utf-8"))
    assert "CURRENT_DATE" not in mine.upper() and "CURRENT_TIMESTAMP" not in mine.upper()
    assert mine.count("Asia/Kolkata") == 1


def test_the_rollback_is_the_ancestors_body_verbatim():
    _name, ancestor = _ancestor()
    assert _function_block(ROLLBACK.read_text(encoding="utf-8")) == ancestor


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"ageing_m514_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M514 Firm','m514@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


#: One zone far behind India and one far ahead: at any instant at least one has a calendar date other than the Indian day.
ZONES = ("Etc/GMT+12", "Pacific/Kiritimati")


def _caveat_for(dsn: str, zone: str, offset_days: int) -> bool:
    """Whether the caveat is present for a schedule as at (Indian day + offset), in a session whose zone is `zone`."""
    out = _ok(dsn, f"""
        SET timezone = '{zone}';
        SELECT (public.schedule_iii_ageing('{FIRM}'::uuid, '{CLIENT}'::uuid,
                    ((now() AT TIME ZONE 'Asia/Kolkata')::date + ({offset_days}))) -> 'gaps') @> '[{{"code": "{CAVEAT}"}}]'::jsonb;""")
    return out.splitlines()[-1] == "t"


@_NEEDS_PG
@pytest.mark.parametrize("zone", ZONES)
def test_the_caveat_is_present_for_the_previous_indian_day_in_any_session_zone(db, zone):
    assert _caveat_for(db, zone, -1) is True


@_NEEDS_PG
@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("offset", [0, 1])
def test_the_caveat_is_absent_for_the_indian_day_and_the_next_in_any_session_zone(db, zone, offset):
    assert _caveat_for(db, zone, offset) is False


@_NEEDS_PG
def test_the_function_is_still_stable_security_definer_and_granted_as_before(db):
    row = _ok(db, """
        SELECT p.provolatile::text || '|' || p.prosecdef::text || '|' || coalesce(array_to_string(p.proconfig, ','), '') || '|'
               || has_function_privilege('authenticated', p.oid, 'EXECUTE')::text || '|'
               || has_function_privilege('anon', p.oid, 'EXECUTE')::text
          FROM pg_proc p WHERE p.proname = 'schedule_iii_ageing' AND p.pronamespace = 'public'::regnamespace;""")
    assert row == "s|true|search_path=public, pg_catalog|true|false", row


@_NEEDS_PG
def test_the_function_text_in_the_database_is_the_new_one(db):
    src = _ok(db, "SELECT prosrc FROM pg_proc WHERE proname='schedule_iii_ageing' AND pronamespace='public'::regnamespace;")
    assert "Asia/Kolkata" in src and "CURRENT_DATE" not in src


@_NEEDS_PG
def test_the_migration_is_idempotent(db):
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert _caveat_for(db, ZONES[0], -1) is True


@_NEEDS_PG
def test_the_rollback_restores_the_session_day_so_each_probe_above_was_the_migration(db):
    assert _psql(db, ROLLBACK.read_text(encoding="utf-8")).returncode == 0
    probes = [(zone, offset, _caveat_for(db, zone, offset)) for zone in ZONES for offset in (-1, 0, 1)]
    expected = {(zone, offset): offset < 0 for zone in ZONES for offset in (-1, 0, 1)}
    assert any(got != expected[(zone, offset)] for zone, offset, got in probes), (
        f"with the old CURRENT_DATE every probe still agreed with the Indian day: the test would not have caught the defect "
        f"({probes})")
    assert _psql(db, MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert all(_caveat_for(db, zone, offset) == expected[(zone, offset)] for zone in ZONES for offset in (-1, 0, 1))
