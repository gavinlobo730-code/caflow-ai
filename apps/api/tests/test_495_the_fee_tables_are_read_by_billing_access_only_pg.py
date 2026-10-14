"""Migration 495 — the practice's fee tables are read only by someone who holds billing access.

THE BUG THIS PINS (ledger POST-B-024)
    core/permissions reserves the practice's own fee economics to `billing:read` (a Partner's, or a grant on the Team
    screen). `fee_engagements` and `fee_invoices` carried a firm rule and an assignment scope and no read tier, so an
    assigned Manager, Executive or Reviewer read the fees of every client assigned to them with their own sign-in;
    `fee_receipts` has no client_id and only a firm-wide select rule, so EVERY member of the firm read every client's
    fee receipts. The access matrix reported both as deviation classes for weeks.

WHAT IS ASSERTED, AS A REAL AUTHENTICATED SESSION
    * a Partner reads all three tables, every client;
    * a Manager, an Executive and a Reviewer read NOTHING from any of them (zero rows, not an error: row security's
      usual silence, which is why the screens that read these tables were put behind FeeAccessGate first);
    * the per-person grid counts both ways: a Manager the grid GRANTS `billing:read` reads, but only the clients assigned
      to them (the assignment scope that already exists), and a receipt follows its invoice; a Partner the grid DENIES
      reads nothing;
    * another firm's Partner reads nothing of this firm's;
    * the writes are as they were (a Partner-only tier): a Manager still cannot insert a fee invoice;
    * the migration is idempotent;
    * its own rollback puts the hole back, which is the negative control that makes the rest mean something.

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
MIGRATIONS = API_ROOT / "migrations"
MIGRATION = MIGRATIONS / "495_the_practices_fee_tables_are_read_only_by_someone_with_billing_access.sql"
ROLLBACK = MIGRATIONS / "495_the_practices_fee_tables_are_read_only_by_someone_with_billing_access_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the fee-table read-tier proofs require HARNESS_PG + psql",
)

FIRM, OTHER_FIRM = "aaaaaaaa-0000-0000-0000-000000000495", "aaaaaaaa-0000-0000-0000-00000000f495"
CLIENT_A, CLIENT_B = "cccccccc-0000-0000-0000-00000000a495", "cccccccc-0000-0000-0000-00000000b495"
ENG_A, ENG_B = "eeeeeeee-0000-0000-0000-00000000a495", "eeeeeeee-0000-0000-0000-00000000b495"
INV_A, INV_B = "dddddddd-0000-0000-0000-00000000a495", "dddddddd-0000-0000-0000-00000000b495"

#: who -> (role, firm, grid decision on billing:read or None, assigned to client A only?)
ACTORS = {
    "partner": ("Partner", FIRM, None),
    "partner_denied": ("Partner", FIRM, False),
    "manager": ("Manager", FIRM, None),
    "manager_granted": ("Manager", FIRM, True),
    "executive": ("Executive", FIRM, None),
    "reviewer": ("Reviewer", FIRM, None),
    "other_partner": ("Partner", OTHER_FIRM, None),
}
AUTH = {k: f"11111111-1111-1111-1111-{i:012d}" for i, k in enumerate(ACTORS, start=1)}
USER = {k: f"bbbbbbbb-1111-1111-1111-{i:012d}" for i, k in enumerate(ACTORS, start=1)}
TABLES = ("fee_engagements", "fee_invoices", "fee_receipts")


def _psql(dsn: str, sql: str, tuples: bool = True) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else []) + ["-f", "-"]
    return subprocess.run(args, input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _as(dsn: str, who: str, sql: str) -> subprocess.CompletedProcess:
    claims = json.dumps({"sub": AUTH[who], "role": "authenticated"})
    return _psql(dsn, f"SET request.jwt.claims = '{claims}'; SET ROLE authenticated; {sql}")


def _count(dsn: str, who: str, table: str) -> int:
    r = _as(dsn, who, f"SELECT count(*) FROM {table};")
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1])


def _apply(dsn: str, path: Path) -> None:
    r = _psql(dsn, path.read_text(), tuples=False)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"feetier_m495_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        auth_rows = ", ".join(f"('{v}', '{k}@m495.test')" for k, v in AUTH.items())
        users = ", ".join(f"('{USER[k]}', '{firm}', '{AUTH[k]}', '{k}@m495.test', '{k}', '{role}', true)"
                          for k, (role, firm, _g) in ACTORS.items())
        # Everyone in this firm is assigned to client A only; a Partner reaches every client without an assignment.
        assigned = ", ".join(f"('{FIRM}', '{USER[k]}', '{CLIENT_A}')" for k, (_r, firm, _g) in ACTORS.items() if firm == FIRM)
        grid = ", ".join(f"('{firm}', '{USER[k]}', 'billing', 'read', {str(g).lower()})"
                         for k, (_r, firm, g) in ACTORS.items() if g is not None)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES {auth_rows};
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}','M495 Firm','m495@test.in'), ('{OTHER_FIRM}','M495 Other','m495o@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {users};
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
              ('{CLIENT_A}','{FIRM}','Client A','Private Limited'), ('{CLIENT_B}','{FIRM}','Client B','Private Limited');
            INSERT INTO user_client_assignments (firm_id, user_id, client_id) VALUES {assigned};
            INSERT INTO user_permissions (firm_id, user_id, resource, action, granted) VALUES {grid};
            INSERT INTO fee_engagements (id, firm_id, client_id, service_type, fee_paise) VALUES
              ('{ENG_A}','{FIRM}','{CLIENT_A}','GST Filing', 100000), ('{ENG_B}','{FIRM}','{CLIENT_B}','GST Filing', 200000);
            INSERT INTO fee_invoices (id, firm_id, client_id, engagement_id, invoice_no, amount_paise, total_paise) VALUES
              ('{INV_A}','{FIRM}','{CLIENT_A}','{ENG_A}','INV-A-1', 100000, 118000),
              ('{INV_B}','{FIRM}','{CLIENT_B}','{ENG_B}','INV-B-1', 200000, 236000);
            INSERT INTO fee_receipts (firm_id, invoice_id, amount_paise) VALUES
              ('{FIRM}','{INV_A}', 50000), ('{FIRM}','{INV_B}', 70000);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── who reads what ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("table", TABLES)
def test_a_partner_reads_every_clients_fees(db, table):
    assert _count(db, "partner", table) == 2


@pytest.mark.parametrize("who", ["manager", "executive", "reviewer", "partner_denied", "other_partner"])
@pytest.mark.parametrize("table", TABLES)
def test_nobody_else_reads_the_practices_fees(db, who, table):
    assert _count(db, who, table) == 0, f"{who} read {table}"


@pytest.mark.parametrize("table", TABLES)
def test_a_manager_the_grid_gives_billing_reads_only_the_clients_assigned_to_them(db, table):
    assert _count(db, "manager_granted", table) == 1, "the assignment scope still confines a granted Manager to client A"
    assert _ok(db, f"SELECT count(*) FROM {table} t;") == "2", "the seed holds two of each"


def test_a_receipt_follows_its_invoice_for_a_granted_manager(db):
    r = _as(db, "manager_granted", "SELECT invoice_id FROM fee_receipts;")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == INV_A


def test_the_writes_are_as_they_were(db):
    r = _as(db, "manager_granted",
            f"INSERT INTO fee_invoices (firm_id, client_id, invoice_no) VALUES ('{FIRM}', '{CLIENT_A}', 'INV-X');")
    assert r.returncode != 0, "a granted reader is not a writer: the write tier is still the Partner's"


# ── the migration itself ─────────────────────────────────────────────────────────────────────────
def test_495_is_idempotent(db):
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    assert _count(db, "executive", "fee_receipts") == 0


def test_its_own_rollback_puts_the_hole_back(db):
    """The negative control: without it the assertions above would pass on a database that never had a hole."""
    _apply(db, ROLLBACK)
    assert _count(db, "manager", "fee_engagements") == 1, "an assigned Manager reads their client's engagement"
    assert _count(db, "executive", "fee_invoices") == 1, "an assigned Executive reads their client's invoice"
    assert _count(db, "reviewer", "fee_receipts") == 2, "every member of the firm reads every fee receipt"
    _apply(db, MIGRATION)
    assert _count(db, "manager", "fee_engagements") == 0
    assert _count(db, "reviewer", "fee_receipts") == 0
