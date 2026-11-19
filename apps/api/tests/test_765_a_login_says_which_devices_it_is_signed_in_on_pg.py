"""Migration 765 on a real database: the sessions a login is signed in on, the mark of "sign out my other sessions", and the
second-device notice (POST-A-486).

WHAT ONLY POSTGRES CAN PROVE
    * the shape: one row per (person, session id); a blank session id is refused; an ended session says how it ended and an open one
      does not; "how" is one of the four the code writes;
    * the tenancy: a session names a member of its own firm (the person-column trigger), and deleting the member takes the row;
    * the privileges: neither the signed-in role nor anon holds any privilege on `login_sessions`, the service role writes it, and a
      signed-in select, insert, update and delete are refused;
    * the insert the repository makes: ignore-duplicates answers a row for a NEW session and none for a known one, which is how a
      second device is noticed exactly once;
    * the two marks on `users` and the session id on `login_events` exist, and the notification type is accepted while the older
      ones still are and an unknown one is not;
    * the migration runs twice, and its rollback removes all of it, after which it applies again.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(p for p in API_ROOT.glob("migrations/765_*.sql") if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/765_*_rollback.sql"))
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

SESSIONS = "public.login_sessions"
FIRM, OTHER_FIRM = "76500000-0000-0000-0000-000000000001", "76500000-0000-0000-0000-000000000002"
PEOPLE = {            # name: (users.id, auth id, role, firm)
    "partner": ("76500000-0000-0000-0000-00000000000a", "76500000-1111-0000-0000-000000000001", "Partner", FIRM),
    "manager": ("76500000-0000-0000-0000-00000000000b", "76500000-1111-0000-0000-000000000002", "Manager", FIRM),
    "other_firm": ("76500000-0000-0000-0000-000000000010", "76500000-1111-0000-0000-000000000006", "Partner", OTHER_FIRM),
}
ME = PEOPLE["manager"][0]


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run(dsn: str, path: Path) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _as(who: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; "
            "SET ROLE authenticated; ")


def _refused_as(dsn: str, who: str, sql: str) -> bool:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as(who) + sql], capture_output=True, text=True)
    return r.returncode != 0 and "permission denied" in r.stderr


def _session(dsn: str, *, session_id: str = "s1", user: str = ME, firm: str = FIRM, ended: str = "NULL", how: str = "NULL"):
    return _psql(dsn, f"INSERT INTO {SESSIONS} (firm_id, user_id, session_id, ip, user_agent, ended_at, ended_how) "
                      f"VALUES ('{firm}', '{user}', '{session_id}', '203.0.113.9', 'Chrome', {ended}, {how});")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e765_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r, _f) in PEOPLE.items())
        members = ", ".join(f"('{i}', '{f}', '{a}', '{n}@t.in', '{n}', '{r}', true)" for n, (i, a, r, f) in PEOPLE.items())
        _ok(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_a_session_is_one_row_per_person_and_session_id(dsn):
    assert _session(dsn).returncode == 0
    dup = _session(dsn)
    assert dup.returncode != 0 and "login_sessions_one_per_session" in dup.stderr, dup.stderr
    assert _session(dsn, session_id="s2").returncode == 0, "another session of the same person is another row"
    assert _session(dsn, user=PEOPLE["partner"][0]).returncode == 0, "the same session id under another person is another row"
    blank = _session(dsn, session_id="  ")
    assert blank.returncode != 0 and "login_sessions_a_session_id_is_not_blank" in blank.stderr


def test_an_ended_session_says_how_and_an_open_one_does_not(dsn):
    assert _session(dsn, session_id="a", ended="now()", how="'signed_out'").returncode == 0
    assert _session(dsn, session_id="b", ended="now()", how="'other_sessions'").returncode == 0
    assert _session(dsn, session_id="c", ended="now()").returncode != 0, "an end with no reason"
    assert _session(dsn, session_id="d", how="'forced'").returncode != 0, "a reason with no end"
    assert _session(dsn, session_id="e", ended="now()", how="'because'").returncode != 0, "a reason nothing writes"


def test_a_session_names_a_member_of_its_own_firm_and_goes_with_the_member(dsn):
    r = _session(dsn, user=PEOPLE["other_firm"][0])           # OTHER_FIRM's member under FIRM's row
    assert r.returncode != 0 and "belong to another firm" in r.stderr, r.stderr
    assert _session(dsn).returncode == 0
    _ok(dsn, f"DELETE FROM users WHERE id = '{ME}'")
    assert _val(dsn, f"SELECT count(*) FROM {SESSIONS}") == "0"


def test_ignore_duplicates_answers_a_row_for_a_new_session_and_none_for_a_known_one(dsn):
    """What the repository's upsert does: a second announcement of one session answers nothing, so only the first tells the Partners."""
    sql = (f"INSERT INTO {SESSIONS} (firm_id, user_id, session_id) VALUES ('{FIRM}', '{ME}', 'new') "
           "ON CONFLICT (user_id, session_id) DO NOTHING RETURNING id")
    assert len(_val(dsn, sql)) == 36
    assert _val(dsn, sql) == ""


def test_nothing_signed_in_reaches_the_table_and_the_service_role_writes(dsn):
    for role in ("authenticated", "anon"):
        for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert _val(dsn, f"SELECT has_table_privilege('{role}', '{SESSIONS}', '{verb}')") == "f", (role, verb)
        for verb in ("SELECT", "INSERT", "UPDATE"):
            assert _val(dsn, f"SELECT has_any_column_privilege('{role}', '{SESSIONS}', '{verb}')") == "f", (role, verb)
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _val(dsn, f"SELECT has_table_privilege('service_role', '{SESSIONS}', '{verb}')") == "t", verb
    assert _session(dsn).returncode == 0
    assert _refused_as(dsn, "manager", f"SELECT * FROM {SESSIONS}")
    assert _refused_as(dsn, "manager", f"INSERT INTO {SESSIONS} (firm_id, user_id, session_id) VALUES ('{FIRM}', '{ME}', 'x')")
    assert _refused_as(dsn, "manager", f"UPDATE {SESSIONS} SET ended_at = now(), ended_how = 'forced'")
    assert _refused_as(dsn, "manager", f"DELETE FROM {SESSIONS}")


def test_the_marks_and_the_session_id_exist_and_start_empty(dsn):
    cols = _val(dsn, "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns "
                     "WHERE table_schema='public' AND ((table_name='users' AND column_name LIKE 'other_sessions%') "
                     "OR (table_name='login_events' AND column_name='session_id'))")
    assert cols == "other_sessions_kept_session_id,other_sessions_revoked_at,session_id"
    assert _val(dsn, f"SELECT other_sessions_revoked_at IS NULL AND other_sessions_kept_session_id IS NULL FROM users WHERE id = '{ME}'") == "t"
    _ok(dsn, f"INSERT INTO login_events (firm_id, user_id, event, session_id) VALUES ('{FIRM}', '{ME}', 'login', 'sess')")
    _ok(dsn, f"INSERT INTO login_events (firm_id, user_id, event) VALUES ('{FIRM}', '{ME}', 'logout')")


def _notification(dsn: str, kind: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"INSERT INTO notifications (firm_id, user_id, type, title, body, severity) "
                      f"VALUES ('{FIRM}', '{PEOPLE['partner'][0]}', '{kind}', 't', 'b', 'medium');")


def test_the_second_device_notice_is_accepted_and_the_older_types_still_are(dsn):
    for kind in ("second_device", "portal_message", "workflow", "task_assigned", "recurring_generated"):
        r = _notification(dsn, kind)
        assert r.returncode == 0, (kind, r.stderr)
    bad = _notification(dsn, "not_a_type")
    assert bad.returncode != 0 and "notifications_type_check" in bad.stderr


def test_only_a_partner_or_the_recipient_may_write_a_notice_which_is_why_the_api_writes_it_privileged(dsn):
    """Migration 084's recipient policy. A Manager's own session cannot write a notice addressed to a Partner (the second-device notice
    would have told nobody); the service role can. The API therefore writes it with its privileged client."""
    insert = (f"INSERT INTO notifications (firm_id, user_id, type, title, body, severity) "
              f"VALUES ('{FIRM}', '{PEOPLE['partner'][0]}', 'second_device', 't', 'b', 'medium')")
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as("manager") + insert], capture_output=True, text=True)
    assert r.returncode != 0 and "row-level security" in r.stderr, r.stderr
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", "SET ROLE service_role; " + insert],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", _as("partner") + insert], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # and the READ the dedupe makes ("does this Partner already have one unread?"): a Manager's own session sees none of a Partner's rows
    seen_by_manager = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c",
         _as("manager") + f"SELECT count(*) FROM notifications WHERE user_id = '{PEOPLE['partner'][0]}' AND type = 'second_device'"],
        capture_output=True, text=True)
    assert seen_by_manager.returncode == 0 and seen_by_manager.stdout.strip().splitlines()[-1] == "0", seen_by_manager.stdout + seen_by_manager.stderr
    assert _val(dsn, f"SELECT count(*) FROM notifications WHERE user_id = '{PEOPLE['partner'][0]}' AND type = 'second_device'") != "0"


def test_the_migration_runs_twice_and_its_rollback_removes_all_of_it_and_it_applies_again(dsn):
    _run(dsn, MIGRATION)
    assert _session(dsn).returncode == 0
    assert _notification(dsn, "second_device").returncode == 0
    _run(dsn, ROLLBACK)
    assert _val(dsn, "SELECT to_regclass('public.login_sessions') IS NULL") == "t"
    assert _val(dsn, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND "
                     "((table_name='users' AND column_name LIKE 'other_sessions%') OR (table_name='login_events' AND column_name='session_id'))") == "0"
    assert _val(dsn, "SELECT count(*) FROM notifications WHERE type = 'second_device'") == "0"
    assert _notification(dsn, "second_device").returncode != 0, "the rollback takes the type out again"
    assert _notification(dsn, "portal_message").returncode == 0
    _run(dsn, MIGRATION)
    assert _session(dsn).returncode == 0
