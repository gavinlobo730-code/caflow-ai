"""
Migration 271 — the posting kernel's RPC must be callable by the role the API
actually runs as, and must not become a hole when it is.

THE BUG THIS PINS
    Every manual journal post returned HTTP 500. Postgres logged
    `42501 permission denied for table journal_entries` against the
    post_journal_atomic RPC, as `authenticator`/`authenticated`. `authenticated`
    holds SELECT on journal_entries and journal_lines and nothing else, and the
    function was SECURITY INVOKER, so its INSERT ran with the caller's
    privileges. With USE_USER_JWT on, the caller IS the end user. Its three
    sibling atomic RPCs (numbered_document_atomic, settle_receipt_atomic,
    record_fee_receipt_atomic) were all already SECURITY DEFINER, which is why
    invoices and receipts kept working while the general ledger could not be
    written at all.

WHAT IS ASSERTED
    * the catalogue facts (SECURITY DEFINER, search_path pinned) — cheap, and
      they are the whole fix;
    * that PUBLIC/anon cannot execute it, because SECURITY DEFINER without that
      revoke would hand the ledger to anyone holding the published anon key;
    * end to end, as a real `authenticated` session with a real JWT claim: a
      journal posts. This is the regression test — it is the thing that was
      broken, exercised the way production exercises it.
    * that the tenant guard replacing the bypassed RLS actually refuses a
      cross-firm firm_id, an unassigned client, and the firm's internal client
      for a non-Partner;
    * that a service_role/background call (no JWT) is NOT caught by the guard,
      so the nightly sweep and every service-role posting path still work.

Runs only when HARNESS_PG is set + psql is on PATH — the same gate as the other
DB tests. The `migrations` CI job runs it against its real Postgres 16.
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

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="journal-posting privilege proof requires HARNESS_PG + psql",
)

FIRM = "f1000000-0000-0000-0000-000000000001"
OTHER_FIRM = "f1000000-0000-0000-0000-000000000002"
CLIENT = "c1000000-0000-0000-0000-000000000001"
UNASSIGNED_CLIENT = "c1000000-0000-0000-0000-000000000002"
INTERNAL_CLIENT = "c1000000-0000-0000-0000-000000000003"
ACC_AR = "a1000000-0000-0000-0000-000000000001"
ACC_SALES = "a1000000-0000-0000-0000-000000000002"

# The executive's Supabase auth id — what auth.uid() resolves to in the session.
EXEC_AUTH = "11111111-1111-1111-1111-111111111111"
EXEC_USER = "d1000000-0000-0000-0000-000000000001"

SEED = f"""
-- users.auth_user_id FKs to auth.users, so the Supabase-side row comes first.
INSERT INTO auth.users (id) VALUES ('{EXEC_AUTH}') ON CONFLICT DO NOTHING;
INSERT INTO firms (id,name,email,internal_client_id) VALUES ('{FIRM}','F','f@t.in',NULL);
INSERT INTO firms (id,name,email) VALUES ('{OTHER_FIRM}','G','g@t.in');
INSERT INTO clients (id,firm_id,client_name,entity_type) VALUES
  ('{CLIENT}','{FIRM}','Assigned','Proprietorship'),
  ('{UNASSIGNED_CLIENT}','{FIRM}','Unassigned','Proprietorship'),
  ('{INTERNAL_CLIENT}','{FIRM}','The Firm Itself','Proprietorship');
UPDATE firms SET internal_client_id='{INTERNAL_CLIENT}' WHERE id='{FIRM}';
INSERT INTO chart_of_accounts (id,firm_id,client_id,account_code,account_name,account_type) VALUES
  ('{ACC_AR}','{FIRM}',NULL,'1100','Trade Receivables','Asset'),
  ('{ACC_SALES}','{FIRM}',NULL,'4000','Sales Revenue','Revenue');
INSERT INTO users (id,firm_id,full_name,email,role,auth_user_id)
  VALUES ('{EXEC_USER}','{FIRM}','Exec','exec@t.in','Executive','{EXEC_AUTH}');
-- Assigned to CLIENT and INTERNAL_CLIENT, deliberately NOT to UNASSIGNED_CLIENT.
INSERT INTO user_client_assignments (user_id,client_id,firm_id) VALUES
  ('{EXEC_USER}','{CLIENT}','{FIRM}'),
  ('{EXEC_USER}','{INTERNAL_CLIENT}','{FIRM}');
"""


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _entry(ref: str, firm: str = FIRM, client: str = CLIENT) -> str:
    return json.dumps({
        "firm_id": firm, "client_id": client, "entry_date": "2026-08-20",
        "reference_no": ref, "narration": "Credit Sales", "entry_type": "Journal",
        "is_posted": True, "status": "posted",
    }).replace("'", "''")


def _lines() -> str:
    return json.dumps([
        {"account_id": ACC_AR, "debit_paise": 5000000, "credit_paise": 0},
        {"account_id": ACC_SALES, "debit_paise": 0, "credit_paise": 5000000},
    ]).replace("'", "''")


def _as_end_user(ref: str, firm: str = FIRM, client: str = CLIENT,
                 auth_uid: str = EXEC_AUTH) -> str:
    """The call exactly as PostgREST makes it: role `authenticated`, with the
    caller's JWT claims in the session so auth.uid() resolves."""
    claims = json.dumps({"sub": auth_uid, "role": "authenticated"}).replace("'", "''")
    return (
        f"SET LOCAL ROLE authenticated; "
        f"SELECT set_config('request.jwt.claims', '{claims}', true); "
        f"SELECT post_journal_atomic('{_entry(ref, firm, client)}'::jsonb, '{_lines()}'::jsonb);"
    )


@pytest.fixture()
def seeded_db(pg_template):
    """Clone conftest's session-scoped migrated template rather than replaying
    ~270 migrations per test — the same pattern every other *_pg.py test uses.
    Isolation is unchanged: each test still gets its own database."""
    admin = _ADMIN.strip()
    dbname = f"jpriv_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, SEED)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


def _entries(dsn: str, ref: str) -> int:
    r = _psql(dsn, f"SELECT count(*) FROM journal_entries WHERE reference_no='{ref}';", tuples=True)
    return int(r.stdout.strip())


# ── The fix itself ───────────────────────────────────────────────────────────

def test_rpc_is_security_definer_with_pinned_search_path(seeded_db):
    r = _psql(seeded_db, """
        SELECT p.prosecdef, coalesce(array_to_string(p.proconfig, ','), '')
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname='public' AND p.proname='post_journal_atomic';
    """, tuples=True)
    secdef, config = r.stdout.strip().split("|")
    assert secdef == "t", "post_journal_atomic must be SECURITY DEFINER — it is the only way to write the GL"
    assert "search_path" in config, "a SECURITY DEFINER function must pin its search_path"


def test_anon_and_public_cannot_execute_the_rpc(seeded_db):
    """The anon key ships in the browser bundle. SECURITY DEFINER + PUBLIC EXECUTE
    would mean anyone at all could post to any firm's ledger."""
    r = _psql(seeded_db, """
        SELECT has_function_privilege('anon', 'public.post_journal_atomic(jsonb,jsonb)', 'EXECUTE'),
               has_function_privilege('authenticated', 'public.post_journal_atomic(jsonb,jsonb)', 'EXECUTE'),
               has_function_privilege('service_role', 'public.post_journal_atomic(jsonb,jsonb)', 'EXECUTE');
    """, tuples=True)
    anon, authed, service = r.stdout.strip().split("|")
    assert anon == "f", "anon must NOT be able to execute the posting RPC"
    assert authed == "t", "the API runs as `authenticated` under USE_USER_JWT — it must be able to"
    assert service == "t", "background jobs run as service_role — they must be able to"


def test_authenticated_end_user_can_post_a_journal(seeded_db):
    """THE regression. This is the exact call that returned 42501 in production."""
    r = _psql(seeded_db, _as_end_user("JNL-001"), tuples=True)
    assert r.returncode == 0, f"an assigned user must be able to post a journal: {r.stderr}"
    assert _entries(seeded_db, "JNL-001") == 1
    lines = _psql(seeded_db, "SELECT count(*) FROM journal_lines;", tuples=True)
    assert int(lines.stdout.strip()) == 2


# ── The guard that replaces the RLS SECURITY DEFINER bypasses ────────────────

def test_cross_firm_firm_id_is_refused(seeded_db):
    """firm_client_isolation, restated in the body."""
    r = _psql(seeded_db, _as_end_user("JNL-XFIRM", firm=OTHER_FIRM), tuples=True)
    assert r.returncode != 0, "posting into another firm must be refused"
    assert "not the caller's firm" in r.stderr, r.stderr
    assert _entries(seeded_db, "JNL-XFIRM") == 0


def test_unassigned_client_is_refused(seeded_db):
    """journal_entries_assignment_scope, restated in the body."""
    r = _psql(seeded_db, _as_end_user("JNL-UNASSIGNED", client=UNASSIGNED_CLIENT), tuples=True)
    assert r.returncode != 0, "posting for an unassigned client must be refused"
    assert "not assigned to the caller" in r.stderr, r.stderr
    assert _entries(seeded_db, "JNL-UNASSIGNED") == 0


def test_internal_client_is_partner_only(seeded_db):
    """journal_entries_internal_partner_only, restated in the body. The executive
    IS assigned to the internal client, so only the role check can refuse this."""
    r = _psql(seeded_db, _as_end_user("JNL-INTERNAL", client=INTERNAL_CLIENT), tuples=True)
    assert r.returncode != 0, "a non-Partner must not post to the firm's internal client"
    assert "only a Partner" in r.stderr, r.stderr
    assert _entries(seeded_db, "JNL-INTERNAL") == 0


def test_valid_jwt_without_a_user_row_is_refused(seeded_db):
    """A JWT that resolves to no users row must be REFUSED, not mistaken for a
    trusted service call. This is why the guard keys on auth.uid() rather than on
    get_my_firm_id() being non-NULL."""
    ghost = "99999999-9999-9999-9999-999999999999"
    r = _psql(seeded_db, _as_end_user("JNL-GHOST", auth_uid=ghost), tuples=True)
    assert r.returncode != 0, "a JWT with no user record must not post"
    assert "no user record" in r.stderr, r.stderr
    assert _entries(seeded_db, "JNL-GHOST") == 0


def test_service_role_call_is_not_caught_by_the_guard(seeded_db):
    """Background jobs and every service-role posting path present no JWT, so
    auth.uid() is NULL and the guard must not apply. Without this, the fix would
    trade a broken UI for a broken nightly sweep."""
    r = _psql(
        seeded_db,
        f"SET LOCAL ROLE service_role; "
        f"SELECT post_journal_atomic('{_entry('JNL-JOB')}'::jsonb, '{_lines()}'::jsonb);",
        tuples=True,
    )
    assert r.returncode == 0, f"service_role must still post without a JWT: {r.stderr}"
    assert _entries(seeded_db, "JNL-JOB") == 1


def test_guard_does_not_disturb_the_balance_checks(seeded_db):
    """Migration 243's DB-level balance guard must still fire, and must fire for an
    end-user caller too — the tenant guard runs first and must not shadow it."""
    imbalanced = json.dumps([
        {"account_id": ACC_AR, "debit_paise": 5000000, "credit_paise": 0},
        {"account_id": ACC_SALES, "debit_paise": 0, "credit_paise": 4000000},
    ]).replace("'", "''")
    claims = json.dumps({"sub": EXEC_AUTH, "role": "authenticated"}).replace("'", "''")
    r = _psql(
        seeded_db,
        f"SET LOCAL ROLE authenticated; "
        f"SELECT set_config('request.jwt.claims', '{claims}', true); "
        f"SELECT post_journal_atomic('{_entry('JNL-IMBAL')}'::jsonb, '{imbalanced}'::jsonb);",
        tuples=True,
    )
    assert r.returncode != 0, "an imbalanced journal must still be refused"
    assert "imbalance" in r.stderr, r.stderr
    assert _entries(seeded_db, "JNL-IMBAL") == 0
