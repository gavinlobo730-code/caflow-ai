"""
R3.1b — proves migration 164's capital_gains RLS/grant hardening on real
PostgreSQL.

Migration 030's firm_staff_manage_capital_gains policy was FOR ALL, scoped
only by firm_id — combined with a table-level GRANT INSERT/UPDATE/DELETE TO
authenticated, ANY authenticated firm staff member could directly write a
capital_gains row from the browser with self-reported gain_type/
tax_rate_percent/indexed_cost_paise, bypassing all server-side computation.
This file proves, against a real Postgres 16 instance with every migration
applied: an authenticated firm-staff session can still SELECT its own firm's
capital-gains records, but INSERT/UPDATE/DELETE are all rejected with
"permission denied" — and the service_role-backed backend path (the only
real mutation path) is unaffected.

Simulates an authenticated PostgREST session the same way
test_r3_0_client_portal_users_rls_pg.py does: `SET request.jwt.claims` + `SET
ROLE authenticated` in one psql session.

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
    reason="capital_gains RLS proof requires HARNESS_PG + psql",
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
    dbname = f"r31b_{uuid.uuid4().hex[:12]}"
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
        assert "030_supplier_tds_and_credit.sql" not in failed
        assert "164_harden_capital_gains_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    # capital_gains predates migration 084 (assignment-scoped RLS, Module
    # 9.0/M5), so -- unlike client_portal_users (migration 109, which
    # postdates 084 and was never swept into its dynamic per-table loop) --
    # this table ALSO carries an "AS RESTRICTIVE" capital_gains_assignment_scope
    # policy requiring can_access_client(client_id): true for Partner
    # (firm-wide), false for any other role without an explicit
    # user_client_assignments row. Using role='Partner' here keeps this
    # test focused on R3.1b's actual fix (SELECT allowed, writes denied)
    # rather than re-exercising that separate, already-covered feature.
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    record = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.1b Firm','r31b@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.1b Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Partner');
        INSERT INTO capital_gains
          (id, firm_id, client_id, asset_description, asset_type, purchase_date, sale_date,
           purchase_cost_paise, sale_value_paise, indexed_cost_paise, gain_type, tax_rate_percent)
          VALUES ('{record}','{firm1}','{client1}','Reliance shares','equity_shares',
                  '2020-01-01','2023-01-01',10000000,40000000,10000000,'LTCG',12.5);
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1,
            "staff_auth_id": staff_auth_id, "record": record}


def _as_authenticated(auth_user_id: str) -> str:
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_own_firm_staff_can_still_select(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT asset_description FROM capital_gains WHERE id = '{seeded['record']}';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Reliance shares"


def test_authenticated_insert_is_denied(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO capital_gains (id, firm_id, client_id, asset_description, "
              f"asset_type, purchase_date, sale_date, purchase_cost_paise, sale_value_paise, "
              f"gain_type, tax_rate_percent) VALUES ('{new_id}','{seeded['firm1']}',"
              f"'{seeded['client1']}','Self-reported asset','equity_shares','2020-01-01',"
              f"'2023-01-01',1,999999999,'LTCG',0.01);")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE capital_gains SET tax_rate_percent = 0.01 WHERE id = '{seeded['record']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_delete_is_denied(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM capital_gains WHERE id = '{seeded['record']}';")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"INSERT INTO capital_gains (id, firm_id, client_id, asset_description, "
              f"asset_type, purchase_date, sale_date, purchase_cost_paise, sale_value_paise, "
              f"gain_type, tax_rate_percent) VALUES ('{new_id}','{seeded['firm1']}',"
              f"'{seeded['client1']}','Backend-inserted','equity_shares','2020-01-01',"
              f"'2023-01-01',10000000,40000000,'LTCG',12.5); "
              f"UPDATE capital_gains SET tax_rate_percent = 20 WHERE id = '{new_id}'; "
              f"DELETE FROM capital_gains WHERE id = '{new_id}';")
    assert r.returncode == 0, r.stderr
