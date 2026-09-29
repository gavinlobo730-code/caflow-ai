"""
Migration 441 — proves a portal client can create and activate their own
online-payment link on real PostgreSQL, and that the bug this migration
fixes (a raw 42501 on `customer_payment_links`) is real without it.

THE BUG, IN ONE SENTENCE
    `POST /api/portal/self/invoices/{id}/pay` (routers/portal_data.py ->
    services/payment_service.create_link) runs under the portal client's OWN
    per-user JWT (core.supabase_client.get_supabase(), under
    USE_USER_JWT=true), and `customer_payment_links_assignment_scope`
    (RESTRICTIVE FOR ALL, `can_access_client(client_id)`) ANDs with the
    table's ONE permissive policy (`firm_customer_payment_links`,
    `firm_id = get_my_firm_id()`) — both of which read NULL for a portal
    principal, who has no `public.users` row — so both the INSERT and the
    immediately-following UPDATE (activating the link with the provider's
    short_url) were refused. The same shape as the sibling `portal_messages`
    fix, and a second, independent way to be refused that portal_messages
    did not have (it already carried a portal-friendly PERMISSIVE policy;
    this table did not).

WHY BOTH INSERT AND UPDATE ARE PROVEN
    `create_link` does an INSERT and then, after calling the payment
    provider, an UPDATE of the SAME row (setting status='active' and the
    provider's short_url) on the SAME db handle — i.e. the same portal-client
    session. A fix that only widened INSERT would still 42501 one line later.

WHY THE SEED GOES THROUGH AN "INTERNAL CLIENT", RATHER THAN JUST INSERTING A
ROW WITH client_id = THE PORTAL MEMBER'S OWN CLIENT
    `customer_payment_links.client_id` is NEVER the portal member's own
    external client id — every row this table ever holds is a fee invoice's
    own `client_id`, which `services/payment_service.create_link` copies
    straight off `client_sales_invoices`, and a fee invoice is booked on the
    FIRM'S OWN internal-client books (`firms.internal_client_id`, the "G3"
    Firm-as-Internal-Client pattern) with the real client recorded only as
    the CUSTOMER on it, via `client_firm_customer_links`. A seed that instead
    inserted `client_id = <the portal member's own client id>` directly would
    pass this file's assertions while proving nothing about the row the real
    code produces — an early draft of this file did exactly that, and it
    took tracing `create_link` end to end (see the migration's own header)
    to find the mistake before it shipped. This seed reproduces the real
    shape: an internal client, a customer under it per external client, and
    `client_firm_customer_links` joining the two — the same chain
    `portal_data_service.resolve_fee_scope` walks before the router ever
    reaches `create_link`.

Simulates an authenticated PostgREST session the way
_supabase_compat_bootstrap.sql's auth.uid()/auth.jwt() shims expect:
`SET request.jwt.claims = '{"sub": "<auth_user_id>"}'` + `SET ROLE
authenticated`, matching how the Supabase connection pooler sets up a
request — the same technique tests/test_262_employee_portal_rls_pg.py uses
for the sibling portal-employee principal.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import importlib.util
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
MIGRATIONS_DIR = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")
_THIS_MIGRATION = "441_a_portal_client_may_pay_their_own_invoice.sql"

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="online-payment portal RLS proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-4441-0000-0000-000000000001"
INTERNAL_CLIENT = "ffffffff-4441-0000-0000-000000000001"  # firms.internal_client_id — G3
CLIENT_MINE = "bbbbbbbb-4441-0000-0000-000000000001"       # the portal member's OWN (external) client
CLIENT_THEIRS = "bbbbbbbb-4441-0000-0000-000000000002"
AUTH_STAFF = "11111111-4441-0000-0000-000000000001"
AUTH_PORTAL = "22222222-4441-0000-0000-000000000001"
# Customers under the INTERNAL client's own books — one per external client,
# per client_firm_customer_links' G3 uniqueness (firm_id, client_id).
INTERNAL_CUSTOMER_MINE = "cccccccc-4441-0000-0000-000000000001"
INTERNAL_CUSTOMER_THEIRS = "cccccccc-4441-0000-0000-000000000002"
INVOICE_MINE = "dddddddd-4441-0000-0000-000000000001"
INVOICE_THEIRS = "dddddddd-4441-0000-0000-000000000002"
LINK_MINE = "eeeeeeee-4441-0000-0000-000000000001"
LINK_THEIRS = "eeeeeeee-4441-0000-0000-000000000002"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
            f"SET ROLE authenticated; ")


def _insert_link_sql(link_id: str, internal_customer_id: str, invoice_id: str,
                      status: str = "created") -> str:
    """Exactly the shape services/payment_service.create_link inserts:
    client_id is ALWAYS the firm's own internal client (see the module
    docstring); customer_id is the internal customer representing the real
    client being billed."""
    return (f"INSERT INTO customer_payment_links "
            f"(id, firm_id, client_id, customer_id, invoice_id, amount_paise, provider, status) "
            f"VALUES ('{link_id}','{FIRM}','{INTERNAL_CLIENT}','{internal_customer_id}',"
            f"'{invoice_id}',118000,'razorpay','{status}');")


_SEED_SQL = f"""
    INSERT INTO auth.users (id, email) VALUES
      ('{AUTH_STAFF}','staff@m441.test.in'),
      ('{AUTH_PORTAL}','portal@m441.test.in');
    INSERT INTO firms (id, name, email) VALUES ('{FIRM}','M441 Firm','m441@test.in');
    -- The firm's OWN "client" row (G3 Firm-as-Internal-Client) — every fee
    -- invoice and payment link this firm raises is booked under THIS id.
    INSERT INTO clients (id, firm_id, client_name, entity_type, is_internal) VALUES
      ('{INTERNAL_CLIENT}','{FIRM}','M441 Firm (internal)','Private Limited',true);
    UPDATE firms SET internal_client_id = '{INTERNAL_CLIENT}' WHERE id = '{FIRM}';
    -- The two REAL (external) practice clients.
    INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
      ('{CLIENT_MINE}','{FIRM}','M441 Client Mine','Private Limited'),
      ('{CLIENT_THEIRS}','{FIRM}','M441 Client Theirs','Private Limited');
    INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES
      (gen_random_uuid(),'{FIRM}','{AUTH_STAFF}','Staff','staff@m441.test.in','Partner');
    -- Migration 109's multi-contact link — the live portal-client path.
    INSERT INTO client_portal_users (id, firm_id, client_id, email, auth_user_id, status)
      VALUES (gen_random_uuid(),'{FIRM}','{CLIENT_MINE}','portal@m441.test.in','{AUTH_PORTAL}','active');
    -- Customers under the INTERNAL client's books, one per external client.
    INSERT INTO customers (id, firm_id, client_id, name) VALUES
      ('{INTERNAL_CUSTOMER_MINE}','{FIRM}','{INTERNAL_CLIENT}','M441 Client Mine (as customer)'),
      ('{INTERNAL_CUSTOMER_THEIRS}','{FIRM}','{INTERNAL_CLIENT}','M441 Client Theirs (as customer)');
    -- G3: which external client each internal customer represents.
    INSERT INTO client_firm_customer_links (firm_id, client_id, internal_customer_id) VALUES
      ('{FIRM}','{CLIENT_MINE}','{INTERNAL_CUSTOMER_MINE}'),
      ('{FIRM}','{CLIENT_THEIRS}','{INTERNAL_CUSTOMER_THEIRS}');
    -- The fee invoices, booked on the INTERNAL client, billed to each customer.
    INSERT INTO client_sales_invoices
      (id, firm_id, client_id, customer_id, invoice_no, invoice_date, total_paise)
      VALUES ('{INVOICE_MINE}','{FIRM}','{INTERNAL_CLIENT}','{INTERNAL_CUSTOMER_MINE}',
              'INV-M441-1','2026-06-01',118000),
             ('{INVOICE_THEIRS}','{FIRM}','{INTERNAL_CLIENT}','{INTERNAL_CUSTOMER_THEIRS}',
              'INV-M441-2','2026-06-01',118000);
"""


def _seed(dsn: str) -> None:
    r = _psql(dsn, _SEED_SQL)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def seeded(pg_template):
    admin = _ADMIN.strip()
    dbname = f"m441_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        assert _THIS_MIGRATION not in pg_template.failed
        _seed(dsn)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ─── the fix: a portal client can create + activate their own link ──────────

def test_portal_client_can_create_their_own_payment_link(seeded):
    r = _psql(seeded, _as(AUTH_PORTAL) +
              _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    assert r.returncode == 0, r.stderr


def test_portal_client_can_read_their_own_payment_link(seeded):
    _psql(seeded, _as(AUTH_PORTAL) +
          _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    r = _psql(seeded, _as(AUTH_PORTAL) +
              f"SELECT status FROM customer_payment_links WHERE id='{LINK_MINE}';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "created"


def test_portal_client_can_activate_their_own_payment_link(seeded):
    """create_link's own SECOND write in the same session: setting
    status='active' with the provider's short_url after the gateway call.
    Without the UPDATE branch of the fix this is the second 42501, one line
    after the INSERT — the reason this migration's split has four commands
    where the sibling portal_messages fix needed three."""
    _psql(seeded, _as(AUTH_PORTAL) +
          _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    r = _psql(seeded, _as(AUTH_PORTAL) +
              f"UPDATE customer_payment_links SET status='active', "
              f"short_url='https://pay.example/x' WHERE id='{LINK_MINE}';")
    assert r.returncode == 0, r.stderr
    check = _psql(seeded, f"SELECT status, short_url FROM customer_payment_links "
                          f"WHERE id='{LINK_MINE}';", tuples=True)
    assert check.stdout.strip() == "active|https://pay.example/x"


def test_portal_client_can_reuse_an_idempotent_read_of_their_own_open_link(seeded):
    """The idempotency SELECT create_link runs before it inserts — silently
    denied (empty result, not an error) before this migration, so a portal
    client's second click always minted a duplicate link instead of reusing
    the open one. Proves it now finds its own row."""
    _psql(seeded, _as(AUTH_PORTAL) +
          _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE, status="active"))
    r = _psql(seeded, _as(AUTH_PORTAL) +
              f"SELECT count(*) FROM customer_payment_links "
              f"WHERE firm_id='{FIRM}' AND invoice_id='{INVOICE_MINE}' "
              f"AND amount_paise=118000 AND status IN ('created','active');", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1"


# ─── isolation: a portal client must never reach another client's link ──────
#
# client_id is IDENTICAL on every row here (always the one internal client for
# this firm), which is exactly why a client_id-only check could never
# distinguish "my payment link" from "theirs" for a portal principal — the
# isolation these tests prove rests entirely on the customer_id branch.

def test_portal_client_cannot_create_a_link_for_another_clients_invoice(seeded):
    r = _psql(seeded, _as(AUTH_PORTAL) +
              _insert_link_sql(LINK_THEIRS, INTERNAL_CUSTOMER_THEIRS, INVOICE_THEIRS))
    assert r.returncode != 0, "a portal client inserted a payment link for a client they are not a member of"
    assert "row-level security" in r.stderr.lower()


def test_portal_client_cannot_read_another_clients_payment_link(seeded):
    _psql(seeded, _insert_link_sql(LINK_THEIRS, INTERNAL_CUSTOMER_THEIRS, INVOICE_THEIRS))
    r = _psql(seeded, _as(AUTH_PORTAL) +
              f"SELECT count(*) FROM customer_payment_links WHERE id='{LINK_THEIRS}';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0"


def test_portal_client_cannot_activate_another_clients_link(seeded):
    """RLS filters the row out of the UPDATE's target set rather than erroring
    — the same 'zero rows affected, no error' outcome migration 262's
    equivalent write-isolation test expects."""
    _psql(seeded, _insert_link_sql(LINK_THEIRS, INTERNAL_CUSTOMER_THEIRS, INVOICE_THEIRS))
    r = _psql(seeded, _as(AUTH_PORTAL) +
              f"UPDATE customer_payment_links SET status='active' WHERE id='{LINK_THEIRS}';")
    assert r.returncode == 0, r.stderr
    check = _psql(seeded, f"SELECT status FROM customer_payment_links WHERE id='{LINK_THEIRS}';",
                 tuples=True)
    assert check.stdout.strip() == "created", "a portal client activated another client's payment link"


def test_an_unaffiliated_stranger_sees_nothing(seeded):
    """A logged-in identity that is neither staff nor a member of this firm's
    portal at all."""
    _psql(seeded, _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    stranger = str(uuid.uuid4())
    r = _psql(seeded, _as(stranger) + "SELECT count(*) FROM customer_payment_links;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0"


# ─── staff must be completely unaffected ─────────────────────────────────────

def test_staff_can_still_create_a_payment_link(seeded):
    r = _psql(seeded, _as(AUTH_STAFF) +
              _insert_link_sql(str(uuid.uuid4()), INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    assert r.returncode == 0, r.stderr


def test_staff_can_still_see_every_link_in_their_firm(seeded):
    _psql(seeded, _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    _psql(seeded, _insert_link_sql(LINK_THEIRS, INTERNAL_CUSTOMER_THEIRS, INVOICE_THEIRS))
    r = _psql(seeded, _as(AUTH_STAFF) + "SELECT count(*) FROM customer_payment_links;", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "2"


# ─── structural guard: the split lives per-command, and DELETE stays narrow ─

def test_the_assignment_scope_is_split_per_command_not_for_all(seeded):
    """The mirror of test_262's structural guard: the widened lane must not
    be a single FOR ALL restrictive policy, or a later write verb inherits the
    portal-client branch by accident."""
    r = _psql(seeded,
              "SELECT policyname FROM pg_policies WHERE schemaname='public' "
              "AND tablename='customer_payment_links' AND permissive='RESTRICTIVE' "
              "AND cmd='ALL' AND policyname LIKE '%assignment_scope%';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert not r.stdout.strip(), (
        f"a FOR ALL restrictive assignment-scope policy is back on "
        f"customer_payment_links: {r.stdout.strip()}")


def test_delete_stays_narrow_nobody_widened_a_write_nobody_uses(seeded):
    r = _psql(seeded,
              "SELECT qual FROM pg_policies WHERE schemaname='public' "
              "AND tablename='customer_payment_links' AND permissive='RESTRICTIVE' "
              "AND cmd='DELETE' AND policyname LIKE '%assignment_scope%';", tuples=True)
    assert r.returncode == 0, r.stderr
    qual = r.stdout.strip()
    assert qual, "no restrictive DELETE policy found on customer_payment_links"
    assert "my_portal_customer_ids" not in qual, (
        "DELETE gained the portal-client branch; nothing deletes this table's "
        "rows and the table's own GRANT never included DELETE — widening "
        "here would be widening a write nobody can even reach.")


def test_a_portal_permissive_policy_now_exists_where_none_did(seeded):
    r = _psql(seeded,
              "SELECT count(*) FROM pg_policies WHERE schemaname='public' "
              "AND tablename='customer_payment_links' AND permissive='PERMISSIVE' "
              "AND qual LIKE '%my_portal_customer_ids%';", tuples=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1"


def test_the_portal_branch_reads_customer_id_never_client_id(seeded):
    """Pins the correction this migration's header records: client_id is
    always the firm's OWN internal client on this table, so a portal-client
    branch keyed on client_id would match no row create_link ever inserts.
    Fails the moment somebody 'simplifies' this back to the sibling's own
    client_id-keyed shape."""
    r = _psql(seeded,
              "SELECT policyname||':'||coalesce(qual,'')||coalesce(with_check,'') "
              "FROM pg_policies WHERE schemaname='public' "
              "AND tablename='customer_payment_links' "
              "AND (coalesce(qual,'')||coalesce(with_check,'')) LIKE '%my_portal%';",
              tuples=True)
    assert r.returncode == 0, r.stderr
    lines = [x for x in r.stdout.split("\n") if x.strip()]
    assert lines, "no policy references the portal-client helpers at all"
    offenders = [x for x in lines if "my_portal_client_ids" in x and "my_portal_customer_ids" not in x]
    assert not offenders, (
        f"a policy keys the portal-client branch on client_id "
        f"(my_portal_client_ids) rather than customer_id "
        f"(my_portal_customer_ids): {offenders}")


# ─── negative control: the bug is real without this migration ─────────────

def _known_pre_existing_failures() -> set[str]:
    """The R2.6 migration-ordering drift backlog test_migrations_apply.py
    tracks as a baseline — a fresh build of the WHOLE migration set (this
    migration included) carries these same ten failures; `pg_template.failed`
    is exactly this set, which the `seeded` fixture above checks this
    migration is not a member of. The 'before this migration' build must
    tolerate the identical, already-documented baseline rather than demand a
    clean apply that even the ordinary template does not have — otherwise
    this negative control would fail on drift this migration did not cause
    and has no way to fix."""
    spec = importlib.util.spec_from_file_location(
        "_m441_baseline_probe", Path(__file__).resolve().parent / "test_migrations_apply.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.EXPECTED_MIGRATION_FAILURES)


def _apply_migrations_without_this_one() -> str:
    """A throwaway database built from every migration EXCEPT this one — the
    schema exactly as it stood the moment before this fix — to prove the
    42501 this migration exists to close is real, and not a premise merely
    assumed from the portal_messages sibling."""
    admin = _ADMIN.strip()
    admin_dsn = f"{admin} dbname=postgres"
    name = f"m441_before_{uuid.uuid4().hex[:12]}"
    tmp = tempfile.mkdtemp(prefix="m441_before_migrations_")
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.name == _THIS_MIGRATION:
            continue
        shutil.copy(f, Path(tmp) / f.name)

    created = subprocess.run(
        ["psql", admin_dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", f'CREATE DATABASE "{name}";'],
        capture_output=True, text=True)
    assert created.returncode == 0, created.stderr

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--dsn", f"{admin} dbname={name}",
         "--with-compat", "--only-schema", "--continue-on-error",
         "--migrations-dir", tmp, "--json"],
        capture_output=True, text=True, cwd=str(API_ROOT))
    report = json.loads(proc.stdout)
    failed = {f["file"] for f in report["failed"]}
    unexpected = failed - _known_pre_existing_failures()
    assert not unexpected, (
        f"the 'before this migration' build failed on migrations OUTSIDE the "
        f"documented R2.6 baseline, which invalidates the negative control: "
        f"{[f for f in report['failed'] if f['file'] in unexpected]}")
    return name


@pytest.fixture(scope="module")
def before_this_migration():
    if not _ADMIN or shutil.which("psql") is None or not RUNNER.exists():
        pytest.skip("real-Postgres harness requires HARNESS_PG + psql")
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    name = _apply_migrations_without_this_one()
    dsn = f"{_ADMIN.strip()} dbname={name}"
    try:
        _seed(dsn)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def test_before_this_migration_a_portal_clients_insert_is_refused_with_42501(before_this_migration):
    """The negative control: revert this migration (apply every other one and
    stop) and confirm the identical statement that now succeeds is refused
    the way the bug report describes — a raw row-level-security violation on
    the INSERT, the same shape as portal_messages before its own fix."""
    r = _psql(before_this_migration, _as(AUTH_PORTAL) +
              _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    assert r.returncode != 0, (
        "the pre-fix migration set let the portal client's INSERT through — "
        "the negative control found no bug to fix")
    assert "row-level security" in r.stderr.lower()


def test_before_this_migration_the_activating_update_is_also_refused(before_this_migration):
    """The second, easy-to-miss half: even a caller who widened only the
    INSERT (the literal shape of the portal_messages fix) would still 42501
    here, one line after create_link's own INSERT succeeds."""
    staff_insert = _psql(before_this_migration,
                         _insert_link_sql(LINK_MINE, INTERNAL_CUSTOMER_MINE, INVOICE_MINE))
    assert staff_insert.returncode == 0, staff_insert.stderr
    r = _psql(before_this_migration, _as(AUTH_PORTAL) +
              f"UPDATE customer_payment_links SET status='active' WHERE id='{LINK_MINE}';")
    # RLS on UPDATE denies by filtering the target row out (0 rows, no error)
    # UNLESS the permissive gate itself also fails, in which case Postgres
    # raises. Either way the row must NOT be activated.
    check = _psql(before_this_migration,
                 f"SELECT status FROM customer_payment_links WHERE id='{LINK_MINE}';", tuples=True)
    assert check.stdout.strip() == "created", (
        "the pre-fix migration set let the portal client's UPDATE through")
