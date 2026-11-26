"""Migration 682 — correcting or deleting a posted manual journal is the server's call alone (follow-up to POST-A-456).

WHAT WAS WRONG
    The API holds a correction and a delete of a posted manual journal to the firm's journal-approval switch (migration 681), but the two
    database functions that do the work, `edit_posted_journal` and `discard_posted_journal`, were executable by `authenticated` (migration
    486), and their own guard asks `accounting` `write`, not the switch. With the switch on, a Manager could rewrite or delete an approved
    entry with a hand-made PostgREST call.

WHAT THIS HOLDS (real Postgres)
    * after 682 neither function is executable by `authenticated`, `anon` or PUBLIC, and both are by `service_role`;
    * a signed-in caller is refused by the privilege itself (before any body runs), and the service role reaches the body;
    * it is idempotent, and its rollback hands the grant back (the negative control: a signed-in call reaches the body again).
Runs only when HARNESS_PG is set + psql on PATH (the fixture skips otherwise).
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
_STEM = "682_correcting_or_deleting_a_posted_manual_journal_is_the_servers_call_alone"
MIGRATION = MIGRATIONS / f"{_STEM}.sql"
ROLLBACK = MIGRATIONS / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")
FIRM = "68200000-0000-0000-0000-000000000001"
CLIENT = "68200000-0000-0000-0000-000000000002"
ENTRY = "68200000-0000-0000-0000-0000000000ee"
EDIT = "public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid)"
DISCARD = "public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean)"
CALLS = {
    "edit": f"SELECT public.edit_posted_journal('{FIRM}', '{CLIENT}', '{ENTRY}', '[]'::jsonb, NULL, NULL, NULL, NULL);",
    "discard": f"SELECT public.discard_posted_journal('{FIRM}', '{CLIENT}', '{ENTRY}', NULL, false);",
}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _signed_in(sql: str) -> str:
    claims = json.dumps({"sub": str(uuid.uuid4()), "role": "authenticated"})
    return f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}"


@pytest.fixture()
def db(pg_template):
    admin = (_ADMIN or "").strip()
    name = f"m682_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _privileges(dsn: str, fn: str) -> dict[str, str]:
    return {role: _ok(dsn, f"SELECT has_function_privilege('{role}', '{fn}'::regprocedure, 'EXECUTE');")
            for role in ("authenticated", "anon", "service_role")}


@pytest.mark.parametrize("fn", [EDIT, DISCARD], ids=["edit", "discard"])
def test_only_the_service_role_executes_either_function(db, fn):
    assert _privileges(db, fn) == {"authenticated": "f", "anon": "f", "service_role": "t"}
    assert _ok(db, f"SELECT count(*) FROM aclexplode((SELECT proacl FROM pg_proc WHERE oid = '{fn}'::regprocedure)) a "
                   "WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE';") == "0", "PUBLIC still executes it"


@pytest.mark.parametrize("call", ["edit", "discard"])
def test_a_signed_in_call_is_refused_by_the_privilege_and_the_service_role_reaches_the_body(db, call):
    refused = _psql(db, _signed_in(CALLS[call]))
    assert refused.returncode != 0 and "permission denied for function" in refused.stderr, refused.stderr
    reached = _psql(db, "SET ROLE service_role; " + CALLS[call])
    assert "permission denied for function" not in reached.stderr, reached.stderr


@pytest.mark.parametrize("call", ["edit", "discard"])
def test_682_is_idempotent_and_its_rollback_hands_the_grant_back(db, call):
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    assert "permission denied for function" in _psql(db, _signed_in(CALLS[call])).stderr
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    for fn in (EDIT, DISCARD):
        assert _privileges(db, fn)["authenticated"] == "t"
    back = _psql(db, _signed_in(CALLS[call]))
    assert back.returncode != 0 and "permission denied for function" not in back.stderr, (
        "with the grant handed back a signed-in call reaches the wrapper, which refuses it for its own reason")
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    assert _privileges(db, EDIT)["authenticated"] == "f" and _privileges(db, DISCARD)["authenticated"] == "f"
