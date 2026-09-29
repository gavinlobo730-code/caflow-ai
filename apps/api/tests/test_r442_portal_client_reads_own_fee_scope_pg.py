"""
R442 — proves migration 442's fix on real PostgreSQL: a portal client's own
`resolve_fee_scope` lookup against `client_firm_customer_links` now succeeds,
end to end through the real Python service function and through one of its
six real callers — not merely through a hand-written probe query.

BUILDING ON THE SIBLING INVESTIGATIONS
    `client_firm_customer_links` (migration 073, Guardrail G3) is read once,
    by `services/portal_data_service.resolve_fee_scope`, which every one of
    `list_invoices`, `dues`, `invoice_in_scope`, `reminder_history`,
    `statement` and `statement_pdf` calls FIRST. Under `USE_USER_JWT=true`
    (on in production per render.yaml), that read runs on the portal
    principal's own per-user-JWT connection — genuinely RLS-constrained.
    Migration 073's own CREATE TABLE declares one PERMISSIVE policy
    (Partner-only), and a naive reading of that one file would say the table
    has a single policy and no RESTRICTIVE layer to widen. Building the FULL
    migration set and reading `pg_policies` shows the real shape is THREE
    policies — the identical stack the two sibling fixes (`portal_messages`,
    migration 440 on an unmerged branch; `customer_payment_links`, migration
    441) each closed on their own tables: migration 074's dynamic loop adds
    `client_firm_customer_links_internal_partner_only` (RESTRICTIVE) because
    the table is in 074's own `tbls` array, and migration 084's dynamic loop
    adds `client_firm_customer_links_assignment_scope` (RESTRICTIVE) because
    the table already existed, with a `client_id` column, by the time 084
    ran. See migration 442's own header for the full derivation.

WHAT THIS FILE PROVES, IN TWO LAYERS
    Layer 1 (raw SQL, `SET request.jwt.claims` + `SET ROLE authenticated` —
    the same technique test_r246_users_column_grant_pg.py /
    test_r440_portal_client_can_post_a_message_pg.py use): a portal client's
    own SELECT against their own row is denied (zero rows, not an error —
    RLS's usual silence) on a database built from every migration EXCEPT 442
    (the negative control), and succeeds on a database built from the full
    set INCLUDING 442. A different portal client, an unassigned staff member,
    and every write (INSERT/UPDATE/DELETE) are all unaffected in both cases.

    Layer 2 (the real Python service function): `services.portal_data_
    service.resolve_fee_scope` and `services.portal_data_service.
    invoice_in_scope` (one of the six real callers) are called DIRECTLY —
    not re-implemented — against a `db` double whose `.table(...)` calls
    execute real SQL over the SAME two real-Postgres connections Layer 1
    uses (the portal client's RLS-constrained session for
    `client_firm_customer_links`; an admin/superuser session, which bypasses
    RLS the way `service_role` does in production, for every other table
    reached by these two functions). This is not mocking the fix under test:
    `client_firm_customer_links` — the ONLY table this migration touches —
    is always read through the real, RLS-constrained portal session, in
    both the before and after builds.

    `get_internal_client_id` (the OTHER thing `resolve_fee_scope` calls
    first) is monkeypatched to return the seeded value directly, because in
    production it reads through `get_service_supabase()` — a wholly separate,
    already-service-role connection this migration does not touch — and in
    this bare pytest process (no `SUPABASE_URL`) that function's own
    `_USE_MOCK` short-circuit would return `None` regardless of what the real
    database holds, which would test nothing about `client_firm_customer_
    links` at all.

    Why the OTHER tables (`client_sales_invoices`) are routed through the
    admin/no-RLS session rather than also being RLS-tested here: they are
    reachable from a portal-authenticated route with EXACTLY this migration's
    defect shape (no PERMISSIVE lane a portal principal can satisfy) and are
    NOT part of this migration or task — confirmed independently while
    writing this file (`pg_policies` on `client_sales_invoices` shows the
    identical three-policy stack with no portal-friendly PERMISSIVE lane).
    Routing them through admin here isolates what THIS migration's fix
    changes (whether `resolve_fee_scope`'s own query now resolves, and
    whether a caller past it actually reaches its second query) from that
    separate, unfixed, and out-of-scope gap — reported alongside this
    migration, not silently patched over inside a test.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI
job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
REAL_MIGRATIONS_DIR = API_ROOT / "migrations"
THIS_MIGRATION = "442_a_portal_client_may_read_their_own_fee_scope_link.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="fee-scope RLS proof requires HARNESS_PG + psql",
)

FIRM = "f4420000-0000-0000-0000-0000000000f1"
INTERNAL_CLIENT = "c4420000-0000-0000-0000-0000000000c0"
EXT1 = "c4420000-0000-0000-0000-0000000000c1"          # portal client 1's own practice client
EXT2 = "c4420000-0000-0000-0000-0000000000c2"          # portal client 2's own practice client
CUST1 = "d4420000-0000-0000-0000-0000000000d1"         # EXT1, as a customer in the internal client's books
CUST2 = "d4420000-0000-0000-0000-0000000000d2"
PORTAL_AUTH_1 = "a4420000-0000-0000-0000-00000000a001"
PORTAL_AUTH_2 = "a4420000-0000-0000-0000-00000000a002"
UNASSIGNED_STAFF_AUTH = "a4420000-0000-0000-0000-00000000a003"
UNASSIGNED_STAFF_ID = "b4420000-0000-0000-0000-00000000b003"
PARTNER_AUTH = "a4420000-0000-0000-0000-00000000a004"
PARTNER_ID = "b4420000-0000-0000-0000-00000000b004"
INVOICE_1 = "e4420000-0000-0000-0000-0000000000e1"     # a real fee invoice on EXT1's own scope


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    """Runs as the admin role — Postgres superuser, bypasses RLS like service_role."""
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
        capture_output=True, text=True,
    )


def _count(dsn: str, sql: str) -> int:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip() or "0")


def _as(dsn: str, auth_uid: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(
        dsn,
        f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; SET ROLE authenticated; {sql}",
    )


def _as_count(dsn: str, auth_uid: str, sql: str) -> int:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; SET ROLE authenticated; {sql}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip().splitlines()[-1] or "0")


_SEED_SQL = f"""
INSERT INTO auth.users (id, email) VALUES
  ('{PORTAL_AUTH_1}', 'client1@t.in'),
  ('{PORTAL_AUTH_2}', 'client2@t.in'),
  ('{UNASSIGNED_STAFF_AUTH}', 'staff1@t.in'),
  ('{PARTNER_AUTH}', 'partner@t.in');
INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F1', 'f1@t.in');
INSERT INTO clients (id, firm_id, client_name, entity_type, pan, is_internal) VALUES
  ('{INTERNAL_CLIENT}', '{FIRM}', 'Internal Books', 'Private Limited', 'AAACI1234A', true),
  ('{EXT1}', '{FIRM}', 'C1', 'Private Limited', 'AAACA1234A', false),
  ('{EXT2}', '{FIRM}', 'C2', 'Private Limited', 'AAACB1234A', false);
UPDATE firms SET internal_client_id = '{INTERNAL_CLIENT}' WHERE id = '{FIRM}';
INSERT INTO customers (id, firm_id, client_id, name) VALUES
  ('{CUST1}', '{FIRM}', '{INTERNAL_CLIENT}', 'C1 as customer'),
  ('{CUST2}', '{FIRM}', '{INTERNAL_CLIENT}', 'C2 as customer');
INSERT INTO client_firm_customer_links (firm_id, client_id, internal_customer_id) VALUES
  ('{FIRM}', '{EXT1}', '{CUST1}'),
  ('{FIRM}', '{EXT2}', '{CUST2}');
INSERT INTO client_portal_users (firm_id, client_id, email, auth_user_id, status) VALUES
  ('{FIRM}', '{EXT1}', 'client1@t.in', '{PORTAL_AUTH_1}', 'active'),
  ('{FIRM}', '{EXT2}', 'client2@t.in', '{PORTAL_AUTH_2}', 'active');
INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
  ('{UNASSIGNED_STAFF_ID}', '{FIRM}', '{UNASSIGNED_STAFF_AUTH}', 'staff1@t.in', 'Unassigned', 'Executive', true),
  ('{PARTNER_ID}', '{FIRM}', '{PARTNER_AUTH}', 'partner@t.in', 'The Partner', 'Partner', true);
INSERT INTO client_sales_invoices
  (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
   taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_paise, status)
  VALUES
  ('{INVOICE_1}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST1}', 'FEE/0001',
   '2026-04-01', '2026-04-30', 100000, 9000, 9000, 0, 118000, 'issued');
"""

_INSERT_ATTEMPT = (
    f"INSERT INTO client_firm_customer_links (firm_id, client_id, internal_customer_id) "
    f"VALUES ('{FIRM}', '{EXT1}', '{CUST2}');"
)


# ── Build two throwaway databases: one WITHOUT migration 442 (negative
#    control), one WITH it (the shared session-scoped `pg_template`, which
#    already includes every .sql file on disk — migration 442 included). ──

@pytest.fixture(scope="module")
def pre_fix_template():
    """A template DB built from every migration file EXCEPT 442 itself — the
    negative control this migration's own fix is measured against."""
    admin = _ADMIN.strip()
    name = f"r442_pre_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}";').returncode != 0:
        pytest.skip("could not create pre-fix template db")

    tmp_dir = tempfile.mkdtemp(prefix="r442_migrations_")
    try:
        for f in REAL_MIGRATIONS_DIR.glob("*.sql"):
            if f.name == THIS_MIGRATION:
                continue
            shutil.copy2(f, Path(tmp_dir) / f.name)

        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dsn", f"{admin} dbname={name}",
             "--with-compat", "--only-schema", "--continue-on-error", "--json",
             "--migrations-dir", tmp_dir],
            capture_output=True, text=True, cwd=str(API_ROOT),
        )
        report = json.loads(proc.stdout)
        applied = set(report.get("applied", [])) | {f["file"] for f in report.get("failed", [])}
        assert THIS_MIGRATION not in applied, (
            "the pre-fix template must not have applied migration 442 at all"
        )
        yield name
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture()
def pre_fix_db(pre_fix_template):
    admin = _ADMIN.strip()
    dbname = f"r442prec_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pre_fix_template}";').returncode != 0:
        pytest.skip("could not clone pre-fix template db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, _SEED_SQL)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def post_fix_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r442postc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the shared (post-fix) template db")
    dsn = f"{admin} dbname={dbname}"
    try:
        seed = _psql(dsn, _SEED_SQL)
        assert seed.returncode == 0, f"seed failed: {seed.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── Sanity: the pre-fix build really does lack this migration's policy ───────

def test_the_pre_fix_build_really_lacks_the_new_policy(pre_fix_db):
    n = _count(pre_fix_db,
               "SELECT count(*) FROM pg_policies WHERE tablename='client_firm_customer_links' "
               "AND policyname='client_firm_customer_links_portal_client_select';")
    assert n == 0, "the negative-control build must not carry this migration's policy"


def test_the_post_fix_build_carries_the_new_policy(post_fix_db):
    n = _count(post_fix_db,
               "SELECT count(*) FROM pg_policies WHERE tablename='client_firm_customer_links' "
               "AND policyname='client_firm_customer_links_portal_client_select';")
    assert n == 1


# ── Layer 1: raw SQL, negative control (BEFORE migration 442) ───────────────

def test_negative_control_a_portal_client_cannot_read_their_own_link_row(pre_fix_db):
    """This is the bug, reproduced on a database that never had migration 442.
    A SELECT an RLS RESTRICTIVE policy blocks returns zero rows, not an
    error — the exact silence resolve_fee_scope's own callers cannot
    distinguish from 'this client genuinely has no fee scope yet'."""
    n = _as_count(pre_fix_db, PORTAL_AUTH_1,
                  f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT1}';")
    assert n == 0


def test_negative_control_admin_confirms_the_row_really_exists(pre_fix_db):
    """Sanity: the row IS there when read without RLS in the way — proves the
    zero above is an RLS denial, not a seeding mistake."""
    n = _count(pre_fix_db, f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT1}';")
    assert n == 1


# ── Layer 1: raw SQL, the fix (AFTER migration 442) ──────────────────────────

def test_a_portal_client_can_read_their_own_link_row(post_fix_db):
    """The bug, fixed. Before migration 442 this returned 0 (see the negative
    control above)."""
    n = _as_count(post_fix_db, PORTAL_AUTH_1,
                  f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT1}';")
    assert n == 1


def test_a_portal_client_still_cannot_see_a_different_clients_link_row(post_fix_db):
    """Cross-tenant isolation: PORTAL_AUTH_1 must not see EXT2's own row."""
    n = _as_count(post_fix_db, PORTAL_AUTH_1,
                  f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT2}';")
    assert n == 0


def test_a_different_portal_client_sees_only_their_own(post_fix_db):
    n = _as_count(post_fix_db, PORTAL_AUTH_2,
                  f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT2}';")
    assert n == 1
    n2 = _as_count(post_fix_db, PORTAL_AUTH_2,
                   f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT1}';")
    assert n2 == 0


def test_an_unfiltered_select_by_a_portal_client_still_returns_only_their_own_row(post_fix_db):
    """The new policy is not accidentally firm-wide: an unfiltered SELECT by
    PORTAL_AUTH_1 must still return exactly one row (their own), not both."""
    n = _as_count(post_fix_db, PORTAL_AUTH_1, "SELECT count(*) FROM client_firm_customer_links;")
    assert n == 1


def test_an_unassigned_staff_member_still_sees_nothing(post_fix_db):
    """This table is Partner-only for STAFF by 073's own design (its header:
    'Amd v1.1 §4.3, Guardrail G3 — Partner-only') — unlike portal_messages or
    customer_payment_links, an assigned-but-non-Partner staff member does NOT
    read this table at all, before or after this fix, because the table's
    lone staff-side PERMISSIVE policy requires get_my_role() = 'Partner'
    unconditionally. The portal-client widening must not change that."""
    n = _as_count(post_fix_db, UNASSIGNED_STAFF_AUTH, "SELECT count(*) FROM client_firm_customer_links;")
    assert n == 0


def test_a_partner_still_sees_every_link_in_the_firm(post_fix_db):
    n = _as_count(post_fix_db, PARTNER_AUTH, "SELECT count(*) FROM client_firm_customer_links;")
    assert n == 2


def test_a_portal_client_still_cannot_insert(post_fix_db):
    r = _as(post_fix_db, PORTAL_AUTH_1, _INSERT_ATTEMPT)
    assert r.returncode != 0 and "row-level security" in r.stderr.lower(), (
        f"expected an RLS refusal, got rc={r.returncode} stderr={r.stderr}"
    )


def test_a_portal_client_still_cannot_update_or_delete_their_own_row(post_fix_db):
    """No portal caller anywhere writes this table (only Partner-gated
    `billing_service.ensure_customer_link` does, staff-only) — see migration
    442's own header. An UPDATE/DELETE a RESTRICTIVE USING clause excludes is
    not an error; Postgres just matches no rows, so this checks the row is
    untouched rather than expecting an exception."""
    r = _as(post_fix_db, PORTAL_AUTH_1,
            f"UPDATE client_firm_customer_links SET internal_customer_id = '{CUST2}' "
            f"WHERE client_id = '{EXT1}';")
    assert r.returncode == 0, r.stderr
    still = _count(post_fix_db,
                   f"SELECT count(*) FROM client_firm_customer_links "
                   f"WHERE client_id='{EXT1}' AND internal_customer_id='{CUST1}';")
    assert still == 1, "the portal client's UPDATE must not have taken effect"

    r = _as(post_fix_db, PORTAL_AUTH_1, f"DELETE FROM client_firm_customer_links WHERE client_id = '{EXT1}';")
    assert r.returncode == 0, r.stderr
    assert _count(post_fix_db, f"SELECT count(*) FROM client_firm_customer_links WHERE client_id='{EXT1}';") == 1, (
        "the portal client's DELETE must not have removed the row"
    )


def test_the_authenticated_grant_is_unchanged(post_fix_db):
    got = subprocess.run(
        ["psql", post_fix_db, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         "SELECT privilege_type FROM information_schema.role_table_grants "
         "WHERE table_schema='public' AND table_name='client_firm_customer_links' "
         "AND grantee='authenticated' ORDER BY privilege_type;"],
        capture_output=True, text=True,
    )
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip().splitlines() == ["DELETE", "INSERT", "SELECT", "UPDATE"]


# ── Layer 2: the REAL Python service function, over real RLS connections ────
#
# `_RealDb` is not a mock of the fix under test: `.table("client_firm_customer_
# links")` executes real SQL over the portal client's own RLS-constrained
# session in BOTH the pre-fix and post-fix cases below. Every other table name
# executes over the admin (RLS-bypassing) session — see the module docstring
# for exactly why, and what that leaves out of scope.

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table: str, run_sql):
        self._table = table
        self._run_sql = run_sql
        self._select = "*"
        self._filters: list[tuple] = []
        self._limit = None

    def select(self, cols):
        self._select = cols
        return self

    def eq(self, col, val):
        self._filters.append((col, "=", val))
        return self

    def is_(self, col, val):
        self._filters.append((col, "IS", val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        where = []
        for col, op, val in self._filters:
            if op == "IS" and isinstance(val, str) and val.lower() == "null":
                where.append(f"{col} IS NULL")
            elif val is None:
                where.append(f"{col} IS NULL")
            elif isinstance(val, bool):
                where.append(f"{col} = {'TRUE' if val else 'FALSE'}")
            else:
                escaped = str(val).replace("'", "''")
                where.append(f"{col} = '{escaped}'")
        sql = f"SELECT {self._select} FROM {self._table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if self._limit is not None:
            sql += f" LIMIT {int(self._limit)}"
        data = self._run_sql(sql)
        return _Result(data)


class _RealDb:
    """Duck-types just enough of the Supabase Python client's chainable
    builder (`.table().select().eq().is_().limit().execute().data`) for
    `resolve_fee_scope` and `invoice_in_scope` to run unmodified against it."""

    def __init__(self, dsn: str, portal_auth_uid: str, rls_table: str = "client_firm_customer_links"):
        self._dsn = dsn
        self._auth_uid = portal_auth_uid
        self._rls_table = rls_table

    def _run_admin(self, sql: str):
        wrapped = f"SELECT coalesce(json_agg(t), '[]'::json)::text FROM ({sql}) t;"
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", wrapped],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"admin query failed: {r.stderr}\nSQL: {sql}"
        return json.loads(r.stdout.strip() or "[]")

    def _run_portal(self, sql: str):
        wrapped = (
            f"SET request.jwt.claims = '{{\"sub\": \"{self._auth_uid}\"}}'; "
            f"SET ROLE authenticated; "
            f"SELECT coalesce(json_agg(t), '[]'::json)::text FROM ({sql}) t;"
        )
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", wrapped],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"portal query failed: {r.stderr}\nSQL: {sql}"
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else []

    def table(self, name: str):
        runner = self._run_portal if name == self._rls_table else self._run_admin
        return _Query(name, runner)


@pytest.fixture()
def internal_client_id_patch(monkeypatch):
    """resolve_fee_scope's OTHER lookup (get_internal_client_id) reads through
    a wholly separate, already-service-role connection in production
    (services.internal_client_service._db() -> get_service_supabase()) that
    this migration does not touch. In this bare pytest process there is no
    SUPABASE_URL, so that function's own _USE_MOCK short-circuit would return
    None regardless of what the real database holds — patched to the seeded
    value so this test measures ONLY what migration 442 actually changes."""
    import services.internal_client_service as internal_client_service
    monkeypatch.setattr(internal_client_service, "get_internal_client_id", lambda firm_id: INTERNAL_CLIENT)
    yield


def test_resolve_fee_scope_negative_control_returns_none_before_the_fix(pre_fix_db, internal_client_id_patch):
    """The real function, called directly — not re-implemented — against a
    database that never had migration 442. This is the concrete shape of the
    production bug: every one of the six callers' `if not scope: return ...`
    branch fires, silently."""
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    scope = portal_data_service.resolve_fee_scope(FIRM, EXT1, db)
    assert scope is None


def test_resolve_fee_scope_returns_the_real_scope_after_the_fix(post_fix_db, internal_client_id_patch):
    """The bug, fixed, proven through the real function rather than a
    hand-written probe query."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    scope = portal_data_service.resolve_fee_scope(FIRM, EXT1, db)
    assert scope == {"internal_client_id": INTERNAL_CLIENT, "internal_customer_id": CUST1}


def test_resolve_fee_scope_still_refuses_a_different_portal_clients_own_id(post_fix_db, internal_client_id_patch):
    """PORTAL_AUTH_1 asking for EXT2's scope must still get nothing — the
    fix widens visibility of a portal client's OWN row only."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    scope = portal_data_service.resolve_fee_scope(FIRM, EXT2, db)
    assert scope is None


def test_invoice_in_scope_negative_control_returns_false_before_the_fix(pre_fix_db, internal_client_id_patch):
    """One of the six real callers, exercised end to end. INVOICE_1 genuinely
    IS EXT1's own fee invoice (seeded above, on the internal client's books
    against CUST1) — invoice_in_scope must answer True once resolve_fee_scope
    can see the link, and on the pre-fix build it cannot, so this is False
    purely because resolve_fee_scope's own read is blocked (never because
    INVOICE_1 doesn't exist or belongs to someone else)."""
    from services import portal_data_service

    db = _RealDb(pre_fix_db, PORTAL_AUTH_1)
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, INVOICE_1, db) is False


def test_invoice_in_scope_returns_true_after_the_fix(post_fix_db, internal_client_id_patch):
    """The same real caller, same real invoice, the fix applied: now True.
    `client_sales_invoices` is deliberately routed through the admin/no-RLS
    session by `_RealDb` (see the module docstring) — this isolates what
    migration 442 changes (whether the caller reaches its second query at
    all) from that table's own, separate, unfixed RLS gap."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_1)
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, INVOICE_1, db) is True


def test_invoice_in_scope_still_refuses_a_different_portal_clients_invoice(post_fix_db, internal_client_id_patch):
    """PORTAL_AUTH_2 must not be told EXT1's own invoice is in their scope —
    cross-tenant isolation carried all the way through the real caller."""
    from services import portal_data_service

    db = _RealDb(post_fix_db, PORTAL_AUTH_2)
    assert portal_data_service.invoice_in_scope(FIRM, EXT2, INVOICE_1, db) is False
