"""Migration 706 — a hub worklist leaves the firm's own practice out of the clients it lists (POST-A-457, Guardrail G2).

WHAT WAS WRONG
    `hub_client_worklist` (migration 486's guarded wrapper) left the practice (`clients.is_internal`) out only for a signed-in caller who is
    not a Partner, so a Partner, and the API's own service-role call, saw it listed among the firm's clients on every hub tile.

WHAT THIS HOLDS (real Postgres)
    * the API's service-role call and a signed-in Partner get no row for the practice, and every other client's row is unchanged;
    * a list that names the practice does not bring it back;
    * the Python twin agrees with the function on the same rows;
    * the wrapper still asks who is calling (`assert_caller_acts_for`) and is granted as 486 left it;
    * the negative control: with 706's own rollback applied (486's wrapper), the practice is listed again for the service role.
Runs only when HARNESS_PG is set + psql on PATH.
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
ROLLBACK = MIGRATIONS / "706_a_hub_worklist_leaves_the_firms_own_practice_out_rollback.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the worklist proof requires HARNESS_PG + psql",
)

FIRM = "70600000-0000-0000-0000-000000000001"
A = "70600000-0000-0000-0000-0000000000a1"
P = "70600000-0000-0000-0000-0000000000f1"
PARTNER_AUTH = "70600000-1111-0000-0000-000000000001"
PARTNER = "70600000-0000-0000-0000-00000000000b"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m706_{uuid.uuid4().hex[:10]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        _ok(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER_AUTH}', 'p@m706.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M706 Firm', 'm706@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER}', '{FIRM}', '{PARTNER_AUTH}', 'p@m706.test', 'P', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{A}', '{FIRM}', 'Acme', 'LLP');
            INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal)
                 VALUES ('{P}', '{FIRM}', 'Our Practice', 'Partnership', true);
            INSERT INTO fixed_assets (id, firm_id, client_id, asset_name, asset_category, purchase_date, purchase_cost_paise)
                 VALUES (gen_random_uuid(), '{FIRM}', '{A}', 'Plant', 'Plant and Machinery', DATE '2025-04-01', 100000),
                        (gen_random_uuid(), '{FIRM}', '{P}', 'Laptop', 'Plant and Machinery', DATE '2025-04-01', 100000),
                        (gen_random_uuid(), '{FIRM}', '{P}', 'Desk', 'Plant and Machinery', DATE '2025-04-01', 100000);
        """)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _worklist(dsn: str, *, partner: bool = False, ids: str = "NULL::uuid[]") -> list[tuple[str, int]]:
    head = ""
    if partner:
        claims = json.dumps({"sub": PARTNER_AUTH, "role": "authenticated"})
        head = f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; "
    out = _ok(dsn, head + f"SELECT client_id::text || '|' || signal FROM public.hub_client_worklist('{FIRM}', 'fixed_assets', {ids}) "
                          "ORDER BY client_id;")
    return [(ln.split("|")[0], int(ln.split("|")[1])) for ln in out.splitlines() if ln.strip()]


def test_the_service_role_and_a_partner_get_no_row_for_the_practice(db):
    assert _worklist(db) == [(A, 1)]
    assert _worklist(db, partner=True) == [(A, 1)]


def test_a_list_that_names_the_practice_does_not_bring_it_back(db):
    assert _worklist(db, ids=f"ARRAY['{A}', '{P}']::uuid[]") == [(A, 1)]
    assert _worklist(db, ids=f"ARRAY['{P}']::uuid[]") == []


def test_the_python_twin_agrees(db, monkeypatch):
    from services import hub_worklist_service
    from tests._hub_worklist_double import Double

    def rows(sql, cols):
        out = _ok(db, sql)
        return [dict(zip(cols, ln.split("|"), strict=True)) for ln in out.splitlines() if ln.strip()]

    assets = [{**r, "depreciation_posted_through": None}
              for r in rows(f"SELECT id, firm_id, client_id FROM fixed_assets WHERE firm_id = '{FIRM}' ORDER BY id;",
                            ["id", "firm_id", "client_id"])]
    clients = [{**r, "is_internal": r["is_internal"] == "t", "legal_name": None, "entity_type": None}
               for r in rows(f"SELECT id, firm_id, client_name, is_internal FROM clients WHERE firm_id = '{FIRM}';",
                             ["id", "firm_id", "client_name", "is_internal"])]
    d = Double({"fixed_assets": assets, "clients": clients})
    monkeypatch.setattr(hub_worklist_service, "_db", lambda: d)
    monkeypatch.setattr(hub_worklist_service, "effective_client_ids", lambda u: None)
    out = hub_worklist_service.worklist({"firm_id": FIRM}, "fixed_assets")
    assert sorted((r["client_id"], r["signal"]) for r in out["rows"]) == _worklist(db)
    assert out["clients_examined"] == 1


def test_the_wrapper_still_asks_who_is_calling_and_keeps_its_grants(db):
    src = _ok(db, "SELECT prosrc FROM pg_proc WHERE oid = 'public.hub_client_worklist(uuid, text, uuid[])'::regprocedure;")
    assert "assert_caller_acts_for('hub_client_worklist'" in src
    assert _ok(db, "SELECT has_function_privilege('authenticated', 'public.hub_client_worklist(uuid, text, uuid[])', 'EXECUTE');") == "t"
    assert _ok(db, "SELECT has_function_privilege('anon', 'public.hub_client_worklist(uuid, text, uuid[])', 'EXECUTE');") == "f"
    assert _ok(db, "SELECT prosecdef FROM pg_proc WHERE oid = 'public.hub_client_worklist(uuid, text, uuid[])'::regprocedure;") == "t"


def test_its_own_rollback_lists_the_practice_again(db):
    """The negative control: 486's wrapper hands the service role every client, the practice included."""
    _ok(db, ROLLBACK.read_text(encoding="utf-8"))
    assert _worklist(db) == [(A, 1), (P, 2)]
