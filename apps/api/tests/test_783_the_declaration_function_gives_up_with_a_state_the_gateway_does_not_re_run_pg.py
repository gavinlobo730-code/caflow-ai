"""Migration 783, proved against real PostgreSQL: `file_it_declaration` gives up with a state of its own (DC001) and is otherwise the
function migration 548 defined (ledger POST-A-577).

WHAT THIS HOLDS
    * the function's source raises DC001 and nowhere mentions 40001;
    * the body is migration 548's with that one RAISE's state changed and a comment beside it, and nothing else (the two texts are
      compared); the rollback restores 548's body exactly, and both files run twice;
    * the security mode, the search path and the grants are untouched.
    What it does NOT hold: the give-up itself is not provoked here (it needs another session to take the same row three times running
    between the function's tries); the function's behaviour is held by test_548_..._pg.py, which runs against this body.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
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
MIGRATIONS = API_ROOT / "migrations"
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

_S783 = "783_the_declaration_function_gives_up_with_a_state_the_gateway_does_not_re_run"
F783, R783 = MIGRATIONS / f"{_S783}.sql", MIGRATIONS / f"{_S783}_rollback.sql"
F548 = MIGRATIONS / "548_a_tax_declaration_is_filed_in_one_transaction_by_the_server_alone.sql"
FUNCTION = "public.file_it_declaration(jsonb, jsonb, boolean)"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the declaration-function proof requires HARNESS_PG + psql",
)


def _run(dsn: str, sql: str, *, scalar: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if scalar else []) + ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = _run(dsn, sql, scalar=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True,
                          env={**os.environ, "PGOPTIONS": "-c client_min_messages=warning"})


def _body(dsn: str) -> str:
    return _scalar(dsn, f"SELECT prosrc FROM pg_proc WHERE oid = '{FUNCTION}'::regprocedure;")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"t783_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _run(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not any(f.startswith("783_") for f in pg_template.failed), pg_template.failed
        yield dsn
    finally:
        _run(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_the_function_gives_up_with_its_own_state_and_is_otherwise_migration_548s(db):
    with_783 = _body(db)
    assert "USING ERRCODE = 'DC001';" in with_783 and "40001" not in with_783
    assert _file(db, R783).returncode == 0
    with_548 = _body(db)
    assert with_548.count("USING ERRCODE = '40001';") == 1
    # take 783's comment out and put the state back: what is left must be 548's text, character for character
    start = with_783.index("            -- DC001, a state of this function's own (migration 783)")
    end = with_783.index("            RAISE EXCEPTION 'file_it_declaration: could not take the declaration")
    assert with_783[start:end].count("\n") == 3 and all(line.lstrip().startswith("--") for line in with_783[start:end].splitlines())
    assert (with_783[:start] + with_783[end:]).replace("USING ERRCODE = 'DC001';", "USING ERRCODE = '40001';") == with_548
    # the rollback is 548's own body, and both files run twice
    assert _file(db, F548).returncode == 0 and _body(db) == with_548, "the rollback is not the body migration 548 defines"
    assert _file(db, F783).returncode == 0 and _body(db) == with_783
    assert _file(db, F783).returncode == 0 and _body(db) == with_783, "running 783 twice changed the function"
    assert _file(db, R783).returncode == 0 and _file(db, R783).returncode == 0 and _body(db) == with_548


def test_the_function_keeps_its_security_mode_its_search_path_and_its_grants(db):
    row = json.loads(_scalar(db, f"""SELECT json_build_object('definer', p.prosecdef, 'config', p.proconfig,
        'auth', has_function_privilege('authenticated', p.oid, 'EXECUTE'), 'anon', has_function_privilege('anon', p.oid, 'EXECUTE'),
        'service', has_function_privilege('service_role', p.oid, 'EXECUTE'))::text FROM pg_proc p WHERE p.oid = '{FUNCTION}'::regprocedure;"""))
    assert row == {"definer": False, "config": ["search_path=public, pg_temp"], "auth": False, "anon": False, "service": True}
