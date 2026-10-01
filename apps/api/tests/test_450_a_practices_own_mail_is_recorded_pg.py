"""Migration 450 on real PostgreSQL — the practice's own mail is recorded, a
person chooses which of it they get, and the pieces it leans on exist.

WHAT IS PROVEN HERE
    * `notifications_type_check` accepts the new 'portal_message', STILL accepts
      every value migration 157 accepted ('workflow' stands for the whole list —
      a replacement that re-derived from 122 would have lost it), and refuses a
      value in neither;
    * `user_notification_preferences` holds one answer per (person, event); a
      staff member can write and read THEIR OWN row and nobody else's — a
      Partner does not edit a colleague's mail;
    * `practice_email_log`: two SENT rows with one dedupe key are refused (the
      database is what makes a re-run send none), a FAILED row carries no key
      and repeats freely, an event mail with no key repeats freely; a browser
      session can READ the rows addressed to it (a Partner reads the firm's) and
      can never INSERT one;
    * `document_requests.due_date` exists and is nullable — the column the POST
      door named for its whole life;
    * the partial index the firm-wide unread count leans on exists.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test; it
cannot run in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "45000000-0000-0000-0000-0000000000f1"
OTHER_FIRM = "45000000-0000-0000-0000-0000000000f2"
CLIENT = "45000000-0000-0000-0000-0000000000c1"
PARTNER_ID = "45000000-0000-0000-0000-00000000b001"
PREPARER_ID = "45000000-0000-0000-0000-00000000b002"
COLLEAGUE_ID = "45000000-0000-0000-0000-00000000b003"
PARTNER_AUTH = "45000000-0000-0000-0000-00000000a001"
PREPARER_AUTH = "45000000-0000-0000-0000-00000000a002"
COLLEAGUE_AUTH = "45000000-0000-0000-0000-00000000a003"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _as(dsn: str, auth_uid: str, sql: str) -> subprocess.CompletedProcess:
    """An authenticated PostgREST session, the way test_r440 simulates one."""
    return _psql(dsn, f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; "
                      f"SET ROLE authenticated; {sql}")


def _as_scalar(dsn: str, auth_uid: str, sql: str) -> str:
    return _scalar(dsn, f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; "
                        f"SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m450_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{PARTNER_AUTH}', 'p@t.in'), ('{PREPARER_AUTH}', 'e@t.in'), ('{COLLEAGUE_AUTH}', 'c@t.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}', 'F1', 'f1@t.in'), ('{OTHER_FIRM}', 'F2', 'f2@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{PARTNER_ID}', '{FIRM}', '{PARTNER_AUTH}', 'p@t.in', 'Partner', 'Partner', true),
              ('{PREPARER_ID}', '{FIRM}', '{PREPARER_AUTH}', 'e@t.in', 'Preparer', 'Executive', true),
              ('{COLLEAGUE_ID}', '{FIRM}', '{COLLEAGUE_AUTH}', 'c@t.in', 'Colleague', 'Executive', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan)
              VALUES ('{CLIENT}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _notification(type_: str) -> str:
    return (f"INSERT INTO notifications (firm_id, user_id, type, title, body) "
            f"VALUES ('{FIRM}', '{PREPARER_ID}', '{type_}', 't', 'b');")


# ── notifications.type ───────────────────────────────────────────────────────

def test_the_new_notification_type_is_accepted(db):
    assert _psql(db, _notification("portal_message")).returncode == 0


@pytest.mark.parametrize("old", ["task_assigned", "compliance_due", "due_soon", "task_overdue",
                                 "recurring_generated", "workflow"])
def test_every_type_an_earlier_migration_accepted_is_still_accepted(db, old):
    """'workflow' is the one a re-derivation from 122 would have lost."""
    assert _psql(db, _notification(old)).returncode == 0


def test_a_type_in_no_list_is_still_refused(db):
    r = _psql(db, _notification("nonsense"))
    assert r.returncode != 0 and "notifications_type_check" in r.stderr


# ── per-person email preferences ─────────────────────────────────────────────

def _pref(user: str, event: str, enabled: str, firm: str = FIRM) -> str:
    return (f"INSERT INTO user_notification_preferences (firm_id, user_id, event_type, email_enabled) "
            f"VALUES ('{firm}', '{user}', '{event}', {enabled});")


def test_one_answer_per_person_per_event(db):
    assert _psql(db, _pref(PREPARER_ID, "task_overdue", "false")).returncode == 0
    again = _psql(db, _pref(PREPARER_ID, "task_overdue", "true"))
    assert again.returncode != 0 and "user_notification_preferences_pkey" in again.stderr


def test_the_third_state_is_the_absence_of_the_row_not_a_null(db):
    r = _psql(db, f"INSERT INTO user_notification_preferences (firm_id, user_id, event_type, email_enabled) "
                  f"VALUES ('{FIRM}', '{PREPARER_ID}', 'task_assigned', NULL);")
    assert r.returncode != 0 and "email_enabled" in r.stderr


def test_a_person_writes_and_reads_their_own_preference(db):
    assert _as(db, PREPARER_AUTH, _pref(PREPARER_ID, "task_overdue", "false")).returncode == 0
    assert _as_scalar(db, PREPARER_AUTH,
                      "SELECT count(*) FROM user_notification_preferences;") == "1"


def test_a_person_cannot_write_a_colleagues_preference(db):
    r = _as(db, PREPARER_AUTH, _pref(COLLEAGUE_ID, "task_overdue", "false"))
    assert r.returncode != 0 and "row-level security" in r.stderr.lower()


def test_not_even_a_partner_edits_a_colleagues_mail(db):
    assert _psql(db, _pref(COLLEAGUE_ID, "task_overdue", "false")).returncode == 0
    assert _as_scalar(db, PARTNER_AUTH,
                      "SELECT count(*) FROM user_notification_preferences;") == "0"
    r = _as(db, PARTNER_AUTH,
            f"UPDATE user_notification_preferences SET email_enabled = true "
            f"WHERE user_id = '{COLLEAGUE_ID}';")
    assert r.returncode == 0, "an UPDATE the policy filters matches no row; it is not an error"
    assert _scalar(db, f"SELECT email_enabled FROM user_notification_preferences "
                       f"WHERE user_id = '{COLLEAGUE_ID}';") == "f"


def test_a_preference_cannot_name_another_firms_person_as_its_own_firm(db):
    r = _as(db, PREPARER_AUTH, _pref(PREPARER_ID, "task_overdue", "false", firm=OTHER_FIRM))
    assert r.returncode != 0 and "row-level security" in r.stderr.lower()


# ── the record of sends ──────────────────────────────────────────────────────

def _log(status: str, key: str | None, user: str = PREPARER_ID, kind: str = "staff") -> str:
    k = "NULL" if key is None else f"'{key}'"
    return (f"INSERT INTO practice_email_log "
            f"(firm_id, event_type, recipient_kind, recipient_user_id, recipient_email, "
            f" ref_type, ref_id, tier, sent_for_date, dedupe_key, status) "
            f"VALUES ('{FIRM}', 'compliance_deadline', '{kind}', '{user}', 'e@t.in', "
            f" 'compliance_record', 'r1', 'due_7', DATE '2026-10-13', {k}, '{status}');")


def test_two_sent_rows_with_one_dedupe_key_are_refused(db):
    key = "compliance_deadline|e@t.in|r1|due_7|2026-10-13"
    assert _psql(db, _log("sent", key)).returncode == 0
    again = _psql(db, _log("sent", key))
    assert again.returncode != 0 and "uq_practice_email_log_sent" in again.stderr


def test_a_failed_attempt_carries_no_key_and_never_blocks_the_retry(db):
    assert _psql(db, _log("failed", None)).returncode == 0
    assert _psql(db, _log("failed", None)).returncode == 0
    assert _psql(db, _log("sent", "compliance_deadline|e@t.in|r1|due_7|2026-10-13")).returncode == 0


def test_an_event_mail_with_no_key_repeats_freely(db):
    assert _psql(db, _log("sent", None)).returncode == 0
    assert _psql(db, _log("sent", None)).returncode == 0


def test_the_same_key_in_another_firm_is_not_a_collision(db):
    key = "compliance_deadline|e@t.in|r1|due_7|2026-10-13"
    assert _psql(db, _log("sent", key)).returncode == 0
    other = (f"INSERT INTO practice_email_log (firm_id, event_type, recipient_email, sent_for_date, "
             f"dedupe_key, status) VALUES ('{OTHER_FIRM}', 'compliance_deadline', 'e@t.in', "
             f"DATE '2026-10-13', '{key}', 'sent');")
    assert _psql(db, other).returncode == 0


def test_a_status_outside_sent_and_failed_is_refused(db):
    r = _psql(db, _log("skipped", None))
    assert r.returncode != 0 and "practice_email_log_status_check" in r.stderr


def test_a_recipient_kind_outside_staff_and_client_contact_is_refused(db):
    r = _psql(db, _log("sent", None, kind="customer"))
    assert r.returncode != 0 and "recipient_kind" in r.stderr


def test_a_staff_member_reads_only_the_mail_sent_to_them(db):
    assert _psql(db, _log("sent", None, user=PREPARER_ID)).returncode == 0
    assert _psql(db, _log("sent", None, user=COLLEAGUE_ID)).returncode == 0
    assert _as_scalar(db, PREPARER_AUTH, "SELECT count(*) FROM practice_email_log;") == "1"


def test_a_partner_reads_the_firms_whole_record(db):
    assert _psql(db, _log("sent", None, user=PREPARER_ID)).returncode == 0
    assert _psql(db, _log("sent", None, user=COLLEAGUE_ID)).returncode == 0
    assert _as_scalar(db, PARTNER_AUTH, "SELECT count(*) FROM practice_email_log;") == "2"


def test_a_browser_session_can_never_insert_a_record_that_a_mail_was_sent(db):
    r = _as(db, PARTNER_AUTH, _log("sent", None))
    assert r.returncode != 0, "authenticated holds SELECT only"


# ── the pieces it leans on ───────────────────────────────────────────────────

def test_a_document_request_can_say_when_it_is_needed_by(db):
    ok = _psql(db, f"INSERT INTO document_requests (firm_id, client_id, title, due_date) "
                   f"VALUES ('{FIRM}', '{CLIENT}', 'Bank statement', DATE '2026-10-20');")
    assert ok.returncode == 0, ok.stderr
    also = _psql(db, f"INSERT INTO document_requests (firm_id, client_id, title) "
                     f"VALUES ('{FIRM}', '{CLIENT}', 'No date');")
    assert also.returncode == 0, "nullable: no default, no backfill"


def test_the_unread_count_has_its_partial_index(db):
    assert _scalar(db, "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
                       "AND indexname = 'idx_portal_messages_unread_from_client';") == "1"


def test_the_migration_is_re_runnable(db, pg_template):
    """Idempotent: applying the file a second time changes nothing and errors on
    nothing — a migration can be re-applied out of band."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations" /
           "450_a_practices_own_mail_is_recorded_and_a_person_chooses_which_they_get.sql"
           ).read_text(encoding="utf-8")
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", "-"],
                       input=sql, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
