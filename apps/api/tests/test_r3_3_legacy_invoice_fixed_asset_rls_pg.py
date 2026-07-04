"""
R3.3 — proves migration 166's RLS/grant hardening on sales_invoices and
fixed_assets on real PostgreSQL.

apps/web/app/accounting/invoices/page.tsx and apps/web/app/accounting/
fixed-assets/page.tsx were both reachable only by typing the URL (never
linked from navigation) and wrote directly to these tables from the
browser. sales_invoices duplicates the real, linked invoicing flow's
client_sales_invoices table with zero cross-visibility (the orphan page's
companion line-item insert into "invoice_lines" already fails outright
today -- migration 139 dropped that table years ago as dead/empty schema,
unrelated to this discovery); fixed_assets is the SAME table the real,
linked fixed-assets page uses, but the orphan page bypassed the backend's
depreciation/journal-linkage logic entirely. This file proves, against a
real Postgres 16 instance with every migration applied: an authenticated
firm-staff session can still SELECT its own firm's rows in both tables,
but INSERT/UPDATE/DELETE are all rejected with "permission denied" — and
the service_role-backed backend path (the only remaining real mutation
path for fixed_assets) is unaffected.

Simulates an authenticated PostgREST session the same way
test_r3_1b_capital_gains_rls_pg.py does: `SET request.jwt.claims` + `SET
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
    reason="legacy invoice/fixed-asset RLS proof requires HARNESS_PG + psql",
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
    dbname = f"r33_{uuid.uuid4().hex[:12]}"
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
        assert "014_complete_missing_tables.sql" not in failed
        assert "025_fixed_assets.sql" not in failed
        assert "166_harden_legacy_invoice_and_fixed_asset_rls.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    # sales_invoices (migration 014) and fixed_assets (migration 025) both
    # predate migration 084 (assignment-scoped RLS, Module 9.0/M5) and both
    # have a client_id column, so they ALSO carry an "AS RESTRICTIVE"
    # can_access_client() policy requiring Partner (firm-wide) or an
    # explicit user_client_assignments row -- same subtlety documented in
    # test_r3_1b_capital_gains_rls_pg.py. Using role='Partner' keeps this
    # test focused on R3.3's actual fix (SELECT allowed, writes denied).
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    staff_auth_id = str(uuid.uuid4())
    invoice = str(uuid.uuid4())
    asset = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{staff_auth_id}', 'staff1@test.in');
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.3 Firm','r33@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.3 Client','Private Limited');
        INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
          (gen_random_uuid(), '{firm1}', '{staff_auth_id}', 'Staff One', 'staff1@test.in', 'Partner');
        INSERT INTO sales_invoices (id, firm_id, client_id, invoice_no, subtotal_paise, total_paise)
          VALUES ('{invoice}','{firm1}','{client1}','LEGACY-001',10000,11800);
        INSERT INTO fixed_assets (id, firm_id, client_id, asset_name, asset_category,
          purchase_date, purchase_cost_paise, depreciation_method, useful_life_years)
          VALUES ('{asset}','{firm1}','{client1}','Legacy laptop','Computers',
                  '2024-01-01',10000000,'WDV',3);
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1,
            "staff_auth_id": staff_auth_id, "invoice": invoice, "asset": asset}


def _as_authenticated(auth_user_id: str) -> str:
    return (
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
        f"SET ROLE authenticated; "
    )


def test_own_firm_staff_can_still_select_both_tables(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT invoice_no FROM sales_invoices WHERE id = '{seeded['invoice']}';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "LEGACY-001"

    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"SELECT asset_name FROM fixed_assets WHERE id = '{seeded['asset']}';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "Legacy laptop"


def test_authenticated_insert_is_denied_on_both_tables(seeded):
    dsn = seeded["dsn"]
    new_id = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO sales_invoices (id, firm_id, client_id, invoice_no, subtotal_paise, total_paise) "
              f"VALUES ('{new_id}','{seeded['firm1']}','{seeded['client1']}','HACK-001',1,999999999);")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()

    new_asset = str(uuid.uuid4())
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"INSERT INTO fixed_assets (id, firm_id, client_id, asset_name, asset_category, "
              f"purchase_date, purchase_cost_paise, depreciation_method, useful_life_years) "
              f"VALUES ('{new_asset}','{seeded['firm1']}','{seeded['client1']}','Hacked asset','Computers', "
              f"'2024-01-01',1,'WDV',3);")
    assert r.returncode != 0
    assert "permission denied" in r.stderr.lower()


def test_authenticated_update_is_denied_on_both_tables(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE sales_invoices SET total_paise = 1 WHERE id = '{seeded['invoice']}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower()

    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"UPDATE fixed_assets SET purchase_cost_paise = 1 WHERE id = '{seeded['asset']}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower()


def test_authenticated_delete_is_denied_on_both_tables(seeded):
    dsn = seeded["dsn"]
    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM fixed_assets WHERE id = '{seeded['asset']}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower()

    r = _psql(dsn, _as_authenticated(seeded["staff_auth_id"]) +
              f"DELETE FROM sales_invoices WHERE id = '{seeded['invoice']}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower()


def test_service_role_can_still_do_everything(seeded):
    dsn = seeded["dsn"]
    new_asset = str(uuid.uuid4())
    r = _psql(dsn,
              f"SET ROLE service_role; "
              f"INSERT INTO fixed_assets (id, firm_id, client_id, asset_name, asset_category, "
              f"purchase_date, purchase_cost_paise, depreciation_method, useful_life_years) "
              f"VALUES ('{new_asset}','{seeded['firm1']}','{seeded['client1']}','Backend asset','Computers', "
              f"'2024-01-01',10000000,'WDV',3); "
              f"UPDATE fixed_assets SET purchase_cost_paise = 20000000 WHERE id = '{new_asset}'; "
              f"DELETE FROM fixed_assets WHERE id = '{new_asset}';")
    assert r.returncode == 0, r.stderr
