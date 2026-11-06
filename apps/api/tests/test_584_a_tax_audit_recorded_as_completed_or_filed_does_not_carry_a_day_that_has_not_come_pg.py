"""Migration 584 — a tax audit recorded as completed or filed does not carry a day that has not come (ledger POST-A-393, item 1).

THE GAP THIS PINS
    `tax_audits.audit_date` and `filing_date` are written from the browser straight to the table, and nothing at any layer checked them: a row recorded as FILED could carry a filing date next
    month, a statement the ITR acknowledgement's door refuses for the same kind of fact. The rule is the plain order of events: an audit recorded as COMPLETED or FILED has an audit date that
    has come; one recorded as FILED has a filing date that has come; an audit that is not started or in progress may carry a PLANNED date. "Come" is India's day.

WHAT IS ASSERTED, AGAINST A REAL DATABASE
    * an insert as completed or filed with an audit date ahead, and as filed with a filing date ahead, is refused in a sentence that carries the hint the screen reads, and writes nothing;
    * the same dates on a not-started or in-progress audit are accepted (a planned day), and today in India is accepted (the boundary);
    * moving an audit to completed or filed with such a day is refused and the row keeps its status; changing the day itself on a finished audit is asked too;
    * a row that ALREADY carries such a day (nothing ever checked) is not locked: an unrelated edit goes through, a change to another day ahead is refused, a change to a day that has come is accepted;
    * the migration is idempotent, reports how many rows already carry such a day and changes none of them, and its rollback puts the gap back (the negative control that makes the rest mean something).
    India's day is read in SQL as `now() AT TIME ZONE 'Asia/Kolkata'`. Most proofs derive their days from the same expression, which cannot show the zone matters (a test and a function that both read
    the wrong zone agree). So the clock is also FAKED: the function pins `search_path TO 'public', 'pg_catalog'` (as the recent trigger functions do), so a `public.now()` of the throwaway database IS
    the clock for the trigger, and the proofs are run at 01:30 IST on 9 October (the 8th in UTC and in Los Angeles) and at 22:30 IST on the 8th, under three session time zones. A function reading
    UTC's date, the session's zone or `CURRENT_DATE` fails at one of those instants; the source pin reads the function with its comments removed, because the header names the zone too.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
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
MIGRATION = MIGRATIONS / "584_a_tax_audit_recorded_as_completed_or_filed_does_not_carry_a_day_that_has_not_come.sql"
ROLLBACK = MIGRATIONS / "584_a_tax_audit_recorded_as_completed_or_filed_does_not_carry_a_day_that_has_not_come_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

FIRM = "aaaaaaaa-0000-0000-0000-000000000584"
CLIENT = "cccccccc-0000-0000-0000-000000000584"
HINT = "tax_audits_dates_follow_the_status"

IST_TODAY = "(now() AT TIME ZONE 'Asia/Kolkata')::date"
AHEAD = f"({IST_TODAY} + 1)"
AHEAD_MORE = f"({IST_TODAY} + 5)"
BEHIND = f"({IST_TODAY} - 3)"


def _code_of(path: Path) -> str:
    """The SQL with its `--` comments removed: the header names the zone and the clock in prose, which would satisfy a pin the code itself no longer met."""
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))


def test_the_function_reads_india_s_day_once_and_names_the_hint_the_screen_reads():
    """Source pin that needs no database, on the code and not the comments: ONE clock reading, in India's zone, and the hint is the one the page maps."""
    sql = _code_of(MIGRATION)
    body = sql[sql.index("CREATE OR REPLACE FUNCTION public.tax_audit_dates_follow_the_status()"):sql.index("COMMENT ON FUNCTION public.tax_audit_dates_follow_the_status()")]
    assert re.search(r"v_today\s+date\s*:=\s*\(now\(\)\s+AT\s+TIME\s+ZONE\s+'Asia/Kolkata'\)::date\s*;", body), "the day must be India's, taken once"
    assert len(re.findall(r"\bnow\s*\(", body)) == 1, "a second reading of the clock would be a second opinion about what today is"
    for forbidden in ("current_date", "current_timestamp", "localtimestamp", "clock_timestamp", "statement_timestamp", "transaction_timestamp", "timeofday"):
        assert forbidden not in body.lower(), f"{forbidden} is the server's or the session's day, not India's"
    assert len(re.findall(r"\bv_today\b", body)) == 5, "the declaration, the two comparisons and the two sentences are all made against the one day"
    assert re.search(r"SET\s+search_path\s+TO\s+'public',\s*'pg_catalog'", body), "the function does not pin its search_path (the fake clock below relies on `public` coming first)"
    assert "DD Mon YYYY" in body and "DD/MM/YYYY" not in body, "the days in the sentence are written as every screen writes a day"
    assert f"HINT = '{HINT}'" in body and "ERRCODE = '23514'" in body
    assert body.count(f"HINT = '{HINT}'") == 2 and body.count("ERRCODE = '23514'") == 2, "both refusals carry the hint the screen reads"


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    if not _ADMIN or shutil.which("psql") is None or not RUNNER.exists():
        pytest.skip("the tax audit date proofs require HARNESS_PG + psql")
    admin = _ADMIN.strip()
    dbname = f"taxaudit_m584_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M584 Firm','m584@test.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}','{FIRM}','Client A','Private Limited');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


_YEARS = iter(f"{y}-{str(y + 1)[2:]}" for y in range(2000, 2090))


def _insert(dsn: str, status: str, audit: str = "NULL", filing: str = "NULL", year: str | None = None) -> subprocess.CompletedProcess:
    year = year or next(_YEARS)
    return _psql(dsn, f"INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) "
                      f"VALUES ('{FIRM}', '{CLIENT}', '{year}', '{status}', {audit}, {filing});")


def _count(dsn: str) -> int:
    return int(_ok(dsn, "SELECT count(*) FROM tax_audits;"))


def _refused_in_the_screens_words(r: subprocess.CompletedProcess, *, field: str) -> None:
    assert r.returncode != 0, "the audit was recorded with a day that has not come"
    assert f"The {field} date of a tax audit recorded as" in r.stderr
    assert "that day has not come (today in India is" in r.stderr
    assert HINT in r.stderr, "the hint the screen reads is missing"


# ── an insert ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["completed", "filed"])
def test_an_audit_recorded_as_done_cannot_carry_an_audit_date_that_has_not_come(db, status):
    r = _insert(db, status, audit=AHEAD)
    _refused_in_the_screens_words(r, field="audit")
    assert _count(db) == 0, "a row was written over the refusal"


def test_an_audit_recorded_as_filed_cannot_carry_a_filing_date_that_has_not_come(db):
    r = _insert(db, "filed", audit=BEHIND, filing=AHEAD)
    _refused_in_the_screens_words(r, field="filing")
    assert _count(db) == 0


@pytest.mark.parametrize("status", ["not_started", "in_progress"])
def test_an_audit_that_is_not_done_may_carry_a_planned_day(db, status):
    assert _insert(db, status, audit=AHEAD_MORE, filing=AHEAD_MORE).returncode == 0
    assert _count(db) == 1


def test_a_completed_audit_may_carry_a_filing_date_that_has_not_come_because_it_is_not_filed(db):
    """Only a status that says the filing happened makes the filing date a statement of fact."""
    assert _insert(db, "completed", audit=BEHIND, filing=AHEAD).returncode == 0


@pytest.mark.parametrize("status", ["completed", "filed"])
def test_today_in_india_and_earlier_are_accepted(db, status):
    assert _insert(db, status, audit=IST_TODAY, filing=IST_TODAY if status == "filed" else "NULL").returncode == 0
    assert _insert(db, status, audit=BEHIND, filing=BEHIND if status == "filed" else "NULL").returncode == 0
    assert _insert(db, status).returncode == 0, "both dates stay optional"
    assert _count(db) == 3


# ── an update ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_moving_an_audit_to_completed_or_filed_with_such_a_day_is_refused_and_the_row_keeps_its_status(db):
    _ok(db, f"INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) "
            f"VALUES ('{FIRM}', '{CLIENT}', '2024-25', 'in_progress', {AHEAD}, {AHEAD});")
    r = _psql(db, "UPDATE tax_audits SET status = 'completed' WHERE financial_year = '2024-25';")
    _refused_in_the_screens_words(r, field="audit")
    r = _psql(db, f"UPDATE tax_audits SET status = 'filed', audit_date = {BEHIND} WHERE financial_year = '2024-25';")
    _refused_in_the_screens_words(r, field="filing")
    assert _ok(db, "SELECT status FROM tax_audits WHERE financial_year = '2024-25';") == "in_progress"
    # …and with both days that have come, the same move is accepted
    assert _psql(db, f"UPDATE tax_audits SET status = 'filed', audit_date = {BEHIND}, filing_date = {IST_TODAY} WHERE financial_year = '2024-25';").returncode == 0


def test_changing_the_day_on_a_finished_audit_is_asked_too(db):
    _ok(db, f"INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) "
            f"VALUES ('{FIRM}', '{CLIENT}', '2023-24', 'filed', {BEHIND}, {BEHIND});")
    _refused_in_the_screens_words(_psql(db, f"UPDATE tax_audits SET filing_date = {AHEAD} WHERE financial_year = '2023-24';"), field="filing")
    _refused_in_the_screens_words(_psql(db, f"UPDATE tax_audits SET audit_date = {AHEAD} WHERE financial_year = '2023-24';"), field="audit")
    assert _psql(db, f"UPDATE tax_audits SET audit_date = {IST_TODAY} WHERE financial_year = '2023-24';").returncode == 0


def test_a_row_that_already_carries_such_a_day_is_not_locked_by_an_unrelated_edit(db):
    """Nothing ever checked these two columns, so a production row may be ahead. It is asked about only when somebody touches the status or the day."""
    _ok(db, "ALTER TABLE tax_audits DISABLE TRIGGER tax_audit_dates_follow_the_status;")
    _ok(db, f"INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) "
            f"VALUES ('{FIRM}', '{CLIENT}', '2022-23', 'filed', {AHEAD}, {AHEAD});")
    _ok(db, "ALTER TABLE tax_audits ENABLE TRIGGER tax_audit_dates_follow_the_status;")
    assert _psql(db, "UPDATE tax_audits SET udin = '26123456ABCDEF1234', ack_number = 'ACK-1' WHERE financial_year = '2022-23';").returncode == 0, \
        "an edit of the UDIN was refused because of a day nobody touched"
    # touching the day: another day ahead is refused, a day that has come is accepted
    _refused_in_the_screens_words(_psql(db, f"UPDATE tax_audits SET filing_date = {AHEAD_MORE} WHERE financial_year = '2022-23';"), field="filing")
    assert _psql(db, f"UPDATE tax_audits SET filing_date = {BEHIND}, audit_date = {BEHIND} WHERE financial_year = '2022-23';").returncode == 0


# ── the migration itself ─────────────────────────────────────────────────────────────────────────────────────────
def _apply(dsn: str, path: Path) -> subprocess.CompletedProcess:
    r = _psql(dsn, path.read_text(encoding="utf-8"), tuples=False)
    assert r.returncode == 0, r.stderr
    return r


def test_584_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE tgname = 'tax_audit_dates_follow_the_status' AND NOT tgisinternal;") == "1"
    _refused_in_the_screens_words(_insert(db, "filed", audit=BEHIND, filing=AHEAD), field="filing")


def test_the_rollback_puts_the_gap_back(db):
    """The negative control: without the trigger a filed audit with a filing date ahead is recorded, which is what the migration refuses."""
    _apply(db, ROLLBACK)
    assert _ok(db, "SELECT count(*) FROM pg_trigger WHERE tgname = 'tax_audit_dates_follow_the_status';") == "0"
    assert _insert(db, "filed", audit=AHEAD, filing=AHEAD).returncode == 0
    _apply(db, MIGRATION)
    _refused_in_the_screens_words(_insert(db, "filed", audit=BEHIND, filing=AHEAD), field="filing")


def test_the_migration_reports_the_rows_that_already_carry_such_a_day_and_changes_none_of_them(db):
    """Rows written before anything checked are COUNTED when the migration runs (a finding for a person) and left exactly as they are."""
    _ok(db, "ALTER TABLE tax_audits DISABLE TRIGGER tax_audit_dates_follow_the_status;")
    _ok(db, f"""INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) VALUES
        ('{FIRM}', '{CLIENT}', '2019-20', 'filed',       {AHEAD}, {AHEAD}),
        ('{FIRM}', '{CLIENT}', '2020-21', 'completed',   {AHEAD}, {AHEAD}),
        ('{FIRM}', '{CLIENT}', '2021-22', 'in_progress', {AHEAD}, {AHEAD}),
        ('{FIRM}', '{CLIENT}', '2022-23', 'filed',       {BEHIND}, {BEHIND});""")
    before = _ok(db, "SELECT string_agg(financial_year || status || audit_date || filing_date, ',' ORDER BY financial_year) FROM tax_audits;")
    r = _apply(db, MIGRATION)
    assert "migration 584: 2 tax audit(s) recorded as completed or filed already carry an audit date that has not come, and 1 recorded as filed a filing date that has not come (left as they are)" in r.stderr, r.stderr
    assert _ok(db, "SELECT string_agg(financial_year || status || audit_date || filing_date, ',' ORDER BY financial_year) FROM tax_audits;") == before, "the migration changed a row"
    # the planned day on the in-progress audit is no finding, and the trigger is back on
    assert _ok(db, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'tax_audit_dates_follow_the_status' AND NOT tgisinternal;") == "O"


def test_nobody_signed_in_can_call_the_trigger_function_and_the_trigger_still_fires_for_them(db):
    """The function is revoked from PUBLIC, anon and authenticated (it is a trigger, never a call), and a trigger does not ask its caller for EXECUTE: a role that holds no
    privilege on it is still refused a filing date that has not come, in the screen's words."""
    for role in ("anon", "authenticated", "public"):
        assert _ok(db, f"SELECT has_function_privilege('{role}', 'public.tax_audit_dates_follow_the_status()', 'EXECUTE');") == "f", f"{role} may execute the trigger function"
    # A role belongs to the CLUSTER, not to the throwaway database, so it has a name of its own and is dropped here: a fixed name would make the second run of this file fail on "already exists".
    probe = f"m584_probe_{uuid.uuid4().hex[:8]}"
    _ok(db, f"CREATE ROLE {probe} NOLOGIN BYPASSRLS IN ROLE authenticated;")
    try:
        _ok(db, f"GRANT USAGE ON SCHEMA public TO {probe};")
        r = _psql(db, f"SET ROLE {probe}; INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) "
                      f"VALUES ('{FIRM}', '{CLIENT}', '2018-19', 'filed', {BEHIND}, {AHEAD});")
        _refused_in_the_screens_words(r, field="filing")
    finally:
        _psql(db, f"DROP OWNED BY {probe}; DROP ROLE IF EXISTS {probe};")


# ── India's day, with the clock faked ──────────────────────────────────────────────────────────────────────────────
# `now()` in the trigger resolves through the function's own search path, `public` first, so a `public.now()` IS the clock for the trigger. `CURRENT_DATE`, `localtimestamp` and the like are evaluated
# by the executor and ignore it, which is how a function reading them fails here. Each psql call is a fresh session, so the plan of the trigger is made under the faked clock.
#   instant (UTC)          India (IST)               UTC date    Los Angeles
#   2026-10-08 20:00:00    9 Oct 01:30               8 Oct       8 Oct         <- the five and a half hours where UTC's date is still yesterday's
#   2026-10-08 17:00:00    8 Oct 22:30               8 Oct       8 Oct         <- the same date in all three: the day must not simply be moved forward either
INSTANTS = [
    ("2026-10-08 20:00:00+00", "2026-10-09", "2026-10-10"),
    ("2026-10-08 17:00:00+00", "2026-10-08", "2026-10-09"),
]
ZONES = ["UTC", "America/Los_Angeles", "Asia/Kolkata"]


def _install_the_fake_clock(dsn: str) -> None:
    _ok(dsn, "CREATE FUNCTION public.now() RETURNS timestamptz LANGUAGE sql STABLE AS $$ SELECT '2000-01-01 00:00:00+00'::timestamptz $$;")


def _at(dsn: str, instant: str, zone: str, sql: str) -> subprocess.CompletedProcess:
    _ok(dsn, f"CREATE OR REPLACE FUNCTION public.now() RETURNS timestamptz LANGUAGE sql STABLE AS $$ SELECT '{instant}'::timestamptz $$;")
    return _psql(dsn, f"SET TIME ZONE '{zone}'; {sql}")


def _shown(iso: str) -> str:
    """2026-10-09 as the sentence writes it: 09 Oct 2026 (the abbreviations are fixed here, not taken from the machine's locale)."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{iso[8:]} {months[int(iso[5:7]) - 1]} {iso[:4]}"


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("instant,today_in_india,tomorrow_in_india", INSTANTS)
def test_today_is_india_s_whatever_zone_the_session_is_in_and_whatever_date_utc_has(db, instant, today_in_india, tomorrow_in_india, zone):
    _install_the_fake_clock(db)
    row = "INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) VALUES ('{f}', '{c}', '{y}', 'filed', '{a}', '{d}');"
    # the faked clock is the one in force: India's date is what the function says in its own sentence
    refused = _at(db, instant, zone, row.format(f=FIRM, c=CLIENT, y="2017-18", a=today_in_india, d=tomorrow_in_india))
    _refused_in_the_screens_words(refused, field="filing")
    assert f"The filing date of a tax audit recorded as filed cannot be {_shown(tomorrow_in_india)}" in refused.stderr
    assert f"(today in India is {_shown(today_in_india)})" in refused.stderr, refused.stderr
    assert _count(db) == 0
    # India's own day is accepted, for both dates, and so is any earlier one
    assert _at(db, instant, zone, row.format(f=FIRM, c=CLIENT, y="2016-17", a=today_in_india, d=today_in_india)).returncode == 0
    assert _count(db) == 1
    # …and the audit date is judged the same way
    refused_audit = _at(db, instant, zone, row.format(f=FIRM, c=CLIENT, y="2015-16", a=tomorrow_in_india, d=today_in_india))
    _refused_in_the_screens_words(refused_audit, field="audit")
    assert f"(today in India is {_shown(today_in_india)})" in refused_audit.stderr, refused_audit.stderr


def test_the_faked_clock_is_the_clock_the_function_reads(db):
    """The negative control of the two above: with no fake clock in front of the real one, a day ahead of the real India date is what is refused, so the proofs above were made against the fake."""
    real_today = _ok(db, f"SELECT {IST_TODAY};")
    assert real_today > "2026-10-10", "the proofs above pick instants in October 2026, which must be in the past of the real India date to tell the fake clock from the real one"
    r = _psql(db, f"INSERT INTO tax_audits (firm_id, client_id, financial_year, status, audit_date, filing_date) VALUES ('{FIRM}', '{CLIENT}', '2014-15', 'filed', '2026-10-08', '2026-10-10');")
    assert r.returncode == 0, "with the real clock, 10 Oct 2026 has come; the refusal in the tests above can only have been the fake clock's"
