"""
R3.9a — proves migration 171's RLS/grant hardening on journal_entries and
journal_lines (System of record for the general ledger) on real PostgreSQL.

Two live frontend pages wrote directly to these tables, bypassing the
backend's single atomic posting kernel (manual_journal_service ->
phase2_journal_service._create_journal / post_journal_atomic):
apps/web/app/clients/[id]/accounting/page.tsx's "New Journal Entry" form
(two separate, non-atomic inserts — the exact F2 "orphan posted entry" bug
class R1.6 was meant to have closed everywhere) and apps/web/app/accounting/
recurring/page.tsx's "Post Now" action (an insert targeting nonexistent
total_debit_paise/total_credit_paise columns, followed by an insert into
journal_entry_lines, a read-only JOIN view — this one failed outright with
a schema error every time, confirmed separately against this same harness).
Both call sites are now fixed to POST through /api/accounting/journal
instead.

Proves, against a real Postgres 16 instance with every migration applied:
an authenticated firm-Partner session can still SELECT its own firm's
journal_entries/journal_lines, but INSERT/UPDATE/DELETE are all rejected
with "permission denied" — and the service_role-backed backend path
(the only path the posting kernel actually uses) is unaffected.

journal_entries predates migration 084 (assignment-scoped RLS) and carries
a client_id column, so it ALSO gets an "AS RESTRICTIVE" can_access_client()
policy requiring Partner (firm-wide) or an explicit assignment row — same
subtlety documented in test_r3_1b_capital_gains_rls_pg.py and
test_r3_13e_compliance_tasks_rls_pg.py. Using role='Partner' keeps this
test focused on migration 171's actual fix.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job.
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
    reason="journal_entries/journal_lines RLS proof requires HARNESS_PG + psql",
)


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db():
    admin = _ADMIN.strip()
    dbname = f"r39a_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dsn", dsn,
             "--with-compat", "--only-schema", "--continue-on-error", "--json"],
            capture_output=True, text=True, cwd=str(API_ROOT),
        )
        report = json.loads(proc.stdout)
        failed = {f["file"] for f in report["failed"]}
        assert "001_initial_schema.sql" not in failed
        assert "003_phase3a_foundation.sql" not in failed
        assert "171_harden_journal_entries_lines_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    account_dr = str(uuid.uuid4())
    account_cr = str(uuid.uuid4())
    entry = str(uuid.uuid4())
    line = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.9a Firm','r39a@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.9a Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Partner');
        INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type) VALUES
          ('{account_dr}','{firm1}',NULL,'5001','Rent Expense','Expense'),
          ('{account_cr}','{firm1}',NULL,'2001','Bank','Asset');
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status)
          VALUES ('{entry}','{firm1}','{client1}','2026-06-01','Rent for June','Journal',true,'posted');
        INSERT INTO journal_lines (id, journal_entry_id, account_id, debit_paise, credit_paise) VALUES
          ('{line}','{entry}','{account_dr}',1000000,0);
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1,
            "staff_auth_id": staff_auth_id, "entry": entry, "line": line,
            "account_dr": account_dr, "account_cr": account_cr}


def _as_authenticated(auth_user_id: str) -> str:
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_own_firm_staff_can_still_select_entries(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT narration FROM journal_entries WHERE id = '{seeded['entry']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Rent for June"


def test_own_firm_staff_can_still_select_lines(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT debit_paise FROM journal_lines WHERE id = '{seeded['line']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1000000"


def test_authenticated_insert_entry_is_denied(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}','2026-06-02','Sneaky entry','Journal');")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_entry_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE journal_entries SET narration = 'tampered' WHERE id = '{seeded['entry']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_delete_entry_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM journal_entries WHERE id = '{seeded['entry']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_insert_line_is_denied(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO journal_lines (id, journal_entry_id, account_id, debit_paise, credit_paise) "
              f"VALUES ('{new_id}','{seeded['entry']}','{seeded['account_cr']}',0,1000000);")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_line_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE journal_lines SET debit_paise = 1 WHERE id = '{seeded['line']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_delete_line_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM journal_lines WHERE id = '{seeded['line']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(seeded):
    dsn = seeded["dsn"]
    new_entry = str(uuid.uuid4())
    new_line = str(uuid.uuid4())
    # Draft (not posted) so the update below doesn't hit the (correct, separate)
    # prevent_posted_journal_update immutability trigger — this test proves
    # service_role isn't blocked by RLS/grants, not that posted entries are
    # mutable (they deliberately aren't, for anyone, including service_role).
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"INSERT INTO journal_entries (id, firm_id, client_id, entry_date, narration, entry_type, is_posted, status) "
              f"VALUES ('{new_entry}','{seeded['firm1']}','{seeded['client1']}','2026-06-03','Kernel-posted entry','Journal',false,'draft'); "
              f"INSERT INTO journal_lines (id, journal_entry_id, account_id, debit_paise, credit_paise) VALUES "
              f"('{new_line}','{new_entry}','{seeded['account_dr']}',500000,0); "
              f"UPDATE journal_entries SET narration = 'updated' WHERE id = '{new_entry}'; "
              f"DELETE FROM journal_lines WHERE id = '{new_line}'; "
              f"DELETE FROM journal_entries WHERE id = '{new_entry}';")
    assert r.returncode == 0, r.stderr
