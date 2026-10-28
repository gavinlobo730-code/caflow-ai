"""Migration 556 — `clients.health_score`, the column nothing writes, is dropped, and the view that named it is recreated (ledger POST-A-283).

WHAT IS HELD
    * The column is gone from `clients` and from `clients_external`, and a client can still be created and read without it.
    * THE VIEW IS STILL THE VIEW: it excludes the firm's own internal client (Guardrail G2), it is `security_invoker` so the caller's row
      security on `clients` applies through it (a signed-in member of one firm does not see another firm's client), it is readable by the
      three roles that read it before and is not writable through.
    * Everything the view exposes is still a column of `clients`, and the view lost nothing but `health_score`.
    * The rollback puts the column back at 100 and the view back with it, and the migration applies again afterwards (idempotent).

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
_STEM = "556_the_unwritten_clients_health_score_column_is_dropped"
MIGRATION = API_ROOT / "migrations" / f"{_STEM}.sql"
ROLLBACK = API_ROOT / "migrations" / f"{_STEM}_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

_NEEDS_PG = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the view and column proofs require HARNESS_PG + psql",
)

FIRM_A, FIRM_B = "55400000-0000-0000-0000-00000000000a", "55400000-0000-0000-0000-00000000000b"
CLIENT_A, CLIENT_A_INTERNAL, CLIENT_B = ("55400000-0000-0000-0000-0000000000c1", "55400000-0000-0000-0000-0000000000c2",
                                         "55400000-0000-0000-0000-0000000000c3")
USER_A, AUTH_A = "55400000-0000-0000-0000-0000000000a1", "55400000-1111-0000-0000-0000000000a1"

# The columns the view named in production on 28-10-2026, less the one dropped here.
VIEW_COLUMNS = [
    "id", "client_name", "entity_type", "pan", "gstin", "mobile", "email", "address_line1", "address_line2", "city", "state",
    "pincode", "state_code", "financial_year_start", "financial_year_end", "gst_registration_date", "gst_filing_frequency",
    "assigned_to", "status", "notes", "created_at", "updated_at", "deleted_at", "firm_id", "legal_name", "trade_name",
    "constitution", "assigned_manager", "assigned_executive", "onboarding_status", "phone", "portal_enabled", "portal_user_id",
    "portal_invited_at", "credit_limit_paise", "payment_terms_days", "is_internal",
]


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"], input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as_user(dsn: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH_A, "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"hs_m554_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert f"{_STEM}.sql" not in pg_template.failed, "migration 556 did not apply, so everything below would pass vacuously"
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_A}', 'a@m554hs.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM_A}', 'Firm A', 'a@m554hs.in'), ('{FIRM_B}', 'Firm B', 'b@m554hs.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
              VALUES ('{USER_A}', '{FIRM_A}', '{AUTH_A}', 'a@m554hs.test', 'A', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT_A}', '{FIRM_A}', 'Client A', 'Private Limited'), ('{CLIENT_B}', '{FIRM_B}', 'Client B', 'Private Limited');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
              VALUES ('{CLIENT_A_INTERNAL}', '{FIRM_A}', 'Firm A itself', 'Partnership', true);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@_NEEDS_PG
def test_the_column_is_gone_from_the_table_and_the_view_and_a_client_is_still_readable(db):
    assert _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND column_name='health_score' "
                   "AND table_name IN ('clients', 'clients_external');") == "0"
    assert _ok(db, f"SELECT client_name FROM clients WHERE id = '{CLIENT_A}';") == "Client A"
    assert _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='health_scores' "
                   "AND column_name = 'health_score';") in ("0", "1"), "the engine's own table is not this migration's to judge"


@_NEEDS_PG
def test_the_view_still_excludes_the_internal_client_and_exposes_exactly_the_old_list_less_health_score(db):
    assert _ok(db, "SELECT count(*) FROM clients_external;") == "2", "the internal client must stay out of the view (Guardrail G2)"
    assert _ok(db, f"SELECT count(*) FROM clients_external WHERE id = '{CLIENT_A_INTERNAL}';") == "0"
    cols = _ok(db, "SELECT string_agg(column_name, ',' ORDER BY ordinal_position) FROM information_schema.columns "
                   "WHERE table_schema='public' AND table_name='clients_external';").split(",")
    assert cols == VIEW_COLUMNS
    missing = _ok(db, "SELECT string_agg(v.column_name, ',') FROM information_schema.columns v "
                      "WHERE v.table_schema='public' AND v.table_name='clients_external' AND NOT EXISTS ("
                      "SELECT 1 FROM information_schema.columns c WHERE c.table_schema='public' AND c.table_name='clients' "
                      "AND c.column_name = v.column_name);")
    assert missing == "", f"the view names columns clients does not have: {missing}"


@_NEEDS_PG
def test_the_view_keeps_the_callers_row_security_and_its_grants(db):
    assert _ok(db, "SELECT 'security_invoker=true' = ANY(reloptions) FROM pg_class WHERE oid = 'public.clients_external'::regclass;") == "t"
    for role in ("anon", "authenticated", "service_role"):
        assert _ok(db, f"SELECT has_table_privilege('{role}', 'public.clients_external', 'SELECT');") == "t", role
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert _ok(db, f"SELECT has_table_privilege('authenticated', 'public.clients_external', '{verb}');") == "f", verb
    # A signed-in member of firm A sees firm A's client and not firm B's, through the view.
    seen = _as_user(db, "SELECT string_agg(client_name, ',' ORDER BY client_name) FROM clients_external;")
    assert seen.returncode == 0, seen.stderr
    names = seen.stdout.strip().splitlines()[-1]
    assert "Client A" in names, f"the member of firm A sees nothing through the view, so the next assertion would pass vacuously: {names!r}"
    assert "Client B" not in names, f"the view let another firm's client through: {names!r}"
    assert "Firm A itself" not in names, "and the internal client stays out for a signed-in member too"


@_NEEDS_PG
def test_the_rollback_restores_the_column_and_the_view_and_the_migration_applies_again(db):
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    assert _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND column_name='health_score' "
                   "AND table_name IN ('clients', 'clients_external');") == "2"
    assert _ok(db, f"SELECT health_score FROM clients WHERE id = '{CLIENT_A}';") == "100"
    assert _ok(db, "SELECT count(*) FROM clients_external;") == "2"
    _ok(db, MIGRATION.read_text(encoding="utf-8"))
    assert _ok(db, "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND column_name='health_score' "
                   "AND table_name IN ('clients', 'clients_external');") == "0"
    assert _ok(db, "SELECT count(*) FROM clients_external;") == "2", "and the migration is idempotent"
