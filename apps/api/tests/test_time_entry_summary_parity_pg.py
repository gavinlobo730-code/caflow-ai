"""Migration 586: the database's time summary equals the Python twin, exactly, and no signed-in session can call it (POST-A-156).

WHY THIS FILE
    `public.time_entry_summary` sums one member's finished time where the rows are, because the answer is a few numbers (CLAUDE.md's
    reporting rule). `domain.time_summary.summarise` has to survive for mock mode and local development, which makes two
    implementations of one rule; they are safe only while something proves they agree. Every scenario is declared once and fed to
    both: the SQL is called with the instants `ist_day_window` gives for the same Indian days the Python is given.

WHAT ONLY POSTGRES CAN PROVE
    * that 18:30 UTC is the next Indian day under a real timestamptz comparison (the in-memory doubles compare text);
    * that the per-client order with no client last is the same as Python's;
    * that EXECUTE is refused to `authenticated` and `anon` and allowed to `service_role`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import date
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from core.ist_clock import ist_day_window  # noqa: E402
from domain.time_summary import summarise  # noqa: E402

FIRM = "f5860000-0000-0000-0000-000000000001"
OTHER_FIRM = "f5860000-0000-0000-0000-0000000000ff"
ME = "e5860000-0000-0000-0000-000000000001"
SOMEONE = "e5860000-0000-0000-0000-000000000002"
C1 = "c5860000-0000-0000-0000-000000000001"
C2 = "c5860000-0000-0000-0000-000000000002"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _e(started, minutes, *, billable=True, client=C1, ended=True, user=ME, firm=FIRM, no_duration=False):
    return {"firm_id": firm, "user_id": user, "client_id": client, "started_at": started, "is_billable": billable,
            "ended_at": "2026-11-20T10:00:00+00:00" if ended else None,
            "duration_minutes": None if (no_duration or not ended) else minutes}


SCENARIO = [
    _e("2026-11-09T04:00:00+00:00", 60),
    _e("2026-11-09T05:00:00+00:00", 30, billable=False),
    _e("2026-11-10T06:00:00+00:00", 45, client=None),
    _e("2026-11-08T18:30:00+00:00", 20, client=C2),          # 00:00 IST on the 9th
    _e("2026-11-08T18:29:59+00:00", 999),                    # 23:59:59 IST on the 8th
    _e("2026-11-15T18:29:59+00:00", 7, client=C2, billable=False),   # 23:59:59 IST on the 15th: the week's last second
    _e("2026-11-15T18:30:00+00:00", 888),                    # 00:00 IST on the 16th: the next week
    _e("2026-11-11T07:00:00+00:00", 0, ended=False),         # running
    _e("2026-11-11T08:00:00+00:00", 15, no_duration=True),   # ended, no duration
    _e("2026-11-12T04:00:00+00:00", 0),                      # finished in no time: counted (a truth test on the minutes would drop it)
    {**_e("2026-11-12T05:00:00+00:00", 25), "ended_at": None},  # a duration recorded but not ended: running, in no total
    _e("2026-11-10T04:00:00+00:00", 500, user=SOMEONE),      # somebody else's
    _e("2026-11-10T04:00:00+00:00", 700, firm=OTHER_FIRM),   # another firm's
]

WINDOWS = [
    (date(2026, 11, 9), date(2026, 11, 15)),
    (date(2026, 11, 8), date(2026, 11, 8)),
    (date(2026, 11, 1), date(2026, 11, 30)),
    (date(2026, 11, 16), date(2026, 11, 16)),
    (date(2025, 1, 1), date(2025, 1, 31)),
]


def _lit(v):
    return "NULL" if v is None else ("true" if v is True else "false" if v is False else f"'{v}'" if isinstance(v, str) else str(v))


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"timepar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    rows = ",\n".join(
        f"({_lit(e['firm_id'])}, {_lit(e['user_id'])}, {_lit(e['client_id'])}, {_lit(e['started_at'])}, {_lit(e['ended_at'])}, "
        f"{_lit(e['duration_minutes'])}, {_lit(e['is_billable'])})" for e in SCENARIO)
    seeded = _psql(dsn, "INSERT INTO time_entries (firm_id, user_id, client_id, started_at, ended_at, duration_minutes, is_billable) "
                        f"VALUES\n{rows};")
    assert seeded.returncode == 0, seeded.stderr
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _sql(dsn: str, first: date, last: date, *, user=ME, firm=FIRM) -> dict:
    start, end = ist_day_window(first, last)
    r = _psql(dsn, f"SELECT public.time_entry_summary('{firm}'::uuid, '{user}'::uuid, '{start}'::timestamptz, '{end}'::timestamptz);",
              tuples=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


def _python(first: date, last: date, *, user=ME, firm=FIRM) -> dict:
    return summarise([e for e in SCENARIO if e["user_id"] == user and e["firm_id"] == firm], first, last)


@pytest.mark.parametrize("first,last", WINDOWS, ids=[f"{a}..{b}" for a, b in WINDOWS])
def test_the_database_and_the_twin_give_the_same_answer(db, first, last):
    assert _sql(db, first, last) == _python(first, last)


def test_the_parity_is_about_something(db):
    """Not two empty answers agreeing: the week's figures are the ones the scenario was built to produce."""
    week = _sql(db, date(2026, 11, 9), date(2026, 11, 15))
    assert (week["total_minutes"], week["billable_minutes"], week["entries_count"], week["running"]) == (162, 125, 6, 2)
    assert [r["client_id"] for r in week["by_client"]] == [C1, C2, None]
    assert _sql(db, date(2026, 11, 8), date(2026, 11, 8))["total_minutes"] == 999
    assert _sql(db, date(2026, 11, 16), date(2026, 11, 16))["total_minutes"] == 888


def test_no_signed_in_session_can_call_it_and_the_service_role_can(db):
    call = (f"SELECT public.time_entry_summary('{FIRM}'::uuid, '{ME}'::uuid, '2026-11-09T00:00:00+05:30', "
            "'2026-11-16T00:00:00+05:30');")
    for role in ("authenticated", "anon"):
        r = _psql(db, f"SET ROLE {role}; {call}")
        assert r.returncode != 0 and "permission denied" in r.stderr, (role, r.stderr)
    ok = _psql(db, f"SET ROLE service_role; {call}", tuples=True)
    assert ok.returncode == 0, ok.stderr
