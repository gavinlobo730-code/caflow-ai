"""
Migration 260, proved against real PostgreSQL: the database refuses a write from
a role too junior for it.

WHY A BEHAVIOURAL TEST AND NOT JUST A POLICY-EXISTS CHECK
    RLS has two ways to look correct and do nothing. A policy created PERMISSIVE
    instead of RESTRICTIVE ORs with the others and WIDENS access. And a policy
    whose predicate is subtly always-true reads fine in pg_policies. Neither is
    visible from the catalogue alone, so these tests connect as `authenticated`
    with a real user's JWT claim and attempt the actual statements.

THE TRAP THIS TEST IS BUILT AROUND
    A denied INSERT raises. A denied UPDATE or DELETE does NOT — PostgreSQL
    silently skips rows failing the USING clause, so the statement "succeeds"
    having changed nothing. A test that asserted "no error" would therefore pass
    whether the policy worked or was missing entirely. Every UPDATE/DELETE case
    below asserts the ROW COUNT, and each says so, because the obvious
    simplification is exactly the one that makes it vacuous.

Gated on HARNESS_PG + psql like its siblings; the `migrations` CI job runs it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="role-write-policy proof requires HARNESS_PG + psql",
)

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
# auth_user_id per role; the last hex digit is the rank, purely for readability.
UID = {
    "Partner":   "a0000000-0000-0000-0000-000000000001",
    "Manager":   "a0000000-0000-0000-0000-000000000002",
    "Executive": "a0000000-0000-0000-0000-000000000003",
    "Reviewer":  "a0000000-0000-0000-0000-000000000004",
}


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _as(dsn: str, role: str, sql: str) -> subprocess.CompletedProcess:
    """Run `sql` as the signed-in user holding `role`.

    SET LOCAL ROLE authenticated matters: the tables are owned by postgres, and
    an owner bypasses RLS entirely, so running these as the migration user would
    make every assertion below pass no matter what the policies said.
    """
    return _psql(
        dsn,
        f"BEGIN; SET LOCAL ROLE authenticated; "
        f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID[role]}\"}}'; "
        f"{sql} ROLLBACK;",
    )


def _rows_changed(dsn: str, role: str, statement: str) -> int:
    """Row count for an UPDATE/DELETE run as `role`.

    Wrapped in a CTE with RETURNING because a policy-denied UPDATE reports
    success with zero rows — the count IS the result being tested.
    """
    r = _psql(
        dsn,
        f"BEGIN; SET LOCAL ROLE authenticated; "
        f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID[role]}\"}}'; "
        f"WITH t AS ({statement} RETURNING 1) SELECT count(*) FROM t; ROLLBACK;",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    return int([ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1])


def _denied(result: subprocess.CompletedProcess) -> bool:
    return result.returncode != 0 and "row-level security" in result.stderr


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"rolepol_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "260_role_aware_write_policies.sql" not in pg_template.failed, (
            "migration 260 did not apply — everything below would pass vacuously"
        )
        rows = [
            f"INSERT INTO auth.users (id, email) VALUES "
            + ", ".join(f"('{u}', '{r}@t.com')" for r, u in UID.items()) + ";",
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'T', 't@t.com');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) "
            f"VALUES ('{CLIENT}', '{FIRM}', 'C', 'Private Limited', 'AAAAA9999A');",
            "INSERT INTO users (id, firm_id, auth_user_id, full_name, email, role) VALUES "
            + ", ".join(f"('{u}', '{FIRM}', '{u}', '{r}', '{r}@t.com', '{r}')"
                        for r, u in UID.items()) + ";",
            # Assignments for everyone below Partner: without them the
            # PRE-EXISTING can_access_client policy denies the write for its own
            # reasons, and this test would be measuring that instead of role.
            "INSERT INTO user_client_assignments (user_id, client_id, firm_id) VALUES "
            + ", ".join(f"('{UID[r]}', '{CLIENT}', '{FIRM}')"
                        for r in ("Manager", "Executive", "Reviewer")) + ";",
        ]
        for sql in rows:
            r = _psql(dsn, sql)
            assert r.returncode == 0, f"{sql[:60]}… → {r.stderr}"
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── The headline fix ─────────────────────────────────────────────────────────

_COA = (f"INSERT INTO chart_of_accounts (firm_id, account_code, account_name, account_type) "
        f"VALUES ('{FIRM}', 'X1', 'n', 'Asset');")


def test_executive_cannot_insert_a_chart_of_accounts_row(db):
    """accounting:write is Manager+. Before 260 an Executive could do this
    straight from the browser, because RLS only checked firm and assignment."""
    assert _denied(_as(db, "Executive", _COA))


def test_reviewer_cannot_insert_a_chart_of_accounts_row(db):
    assert _denied(_as(db, "Reviewer", _COA))


def test_manager_can_still_insert_a_chart_of_accounts_row(db):
    """The other half of the fix. A rule that also blocks the people entitled to
    the action is a rule that gets reverted the same week."""
    r = _as(db, "Manager", _COA)
    assert r.returncode == 0, r.stderr


def test_partner_can_still_insert_a_chart_of_accounts_row(db):
    r = _as(db, "Partner", _COA)
    assert r.returncode == 0, r.stderr


# ── Partner-only: fee economics ──────────────────────────────────────────────

_FEE = (f"INSERT INTO fee_invoices (firm_id, client_id, invoice_no) "
        f"VALUES ('{FIRM}', '{CLIENT}', 'F1');")


def test_manager_cannot_insert_a_fee_invoice(db):
    """billing:* is Partner-only — the matrix calls it fee economics. Manager is
    the interesting case: senior enough for most things, not for this."""
    assert _denied(_as(db, "Manager", _FEE))


def test_partner_can_insert_a_fee_invoice(db):
    r = _as(db, "Partner", _FEE)
    assert r.returncode == 0, r.stderr


# ── Executive-tier: tasks ────────────────────────────────────────────────────

_TASK = f"INSERT INTO tasks (firm_id, client_id, title) VALUES ('{FIRM}', '{CLIENT}', 't');"


def test_executive_can_insert_a_task(db):
    """task:write is Executive+. Proves 260 did not simply raise the bar
    everywhere — the tiers differ per resource and are meant to."""
    r = _as(db, "Executive", _TASK)
    assert r.returncode == 0, r.stderr


def test_reviewer_cannot_insert_a_task(db):
    assert _denied(_as(db, "Reviewer", _TASK))


# ── UPDATE and DELETE deny SILENTLY — assert counts, never just "no error" ───

_FIRM_UPD = f"UPDATE firms SET name = 'renamed' WHERE id = '{FIRM}'"


def test_a_reviewer_update_to_the_firm_changes_nothing(db):
    """firm:write is Partner-only.

    Note what is being asserted: PostgreSQL does not raise for an UPDATE whose
    rows fail the policy's USING clause — it updates zero rows and reports
    success. The Reviewer even passes the SELECT policy and can read the row.
    Only the count distinguishes "blocked" from "worked".
    """
    assert _rows_changed(db, "Reviewer", _FIRM_UPD) == 0


def test_a_partner_update_to_the_firm_changes_the_row(db):
    """The control for the test above: 0 would also be the answer if the WHERE
    clause simply matched nothing, which would make it prove nothing at all."""
    assert _rows_changed(db, "Partner", _FIRM_UPD) == 1


def test_executive_cannot_delete_a_task_but_manager_can(db):
    """task:delete is Manager+, one tier above task:write — so an Executive who
    may create a task still may not remove one. Both directions in one test
    because the pair is the point."""
    seed = (f"INSERT INTO tasks (id, firm_id, client_id, title) VALUES "
            f"('33333333-3333-3333-3333-333333333333', '{FIRM}', '{CLIENT}', 'd');")
    assert _psql(db, seed).returncode == 0

    delete = "DELETE FROM tasks WHERE id = '33333333-3333-3333-3333-333333333333'"
    assert _rows_changed(db, "Executive", delete) == 0
    assert _rows_changed(db, "Manager", delete) == 1


# ── Reads are untouched ──────────────────────────────────────────────────────

def test_a_reviewer_can_still_read_the_tables_this_migration_guards(db):
    """260 adds INSERT/UPDATE/DELETE policies only. If a FOR ALL policy ever
    creeps in, its USING clause would gate SELECT too and silently empty these
    screens for junior staff — a bug that looks like missing data, not a
    permission error."""
    for table in ("chart_of_accounts", "clients", "tasks", "fee_invoices", "firms"):
        r = _psql(
            db,
            f"BEGIN; SET LOCAL ROLE authenticated; "
            f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID['Reviewer']}\"}}'; "
            f"SELECT count(*) FROM {table}; ROLLBACK;",
            tuples=True,
        )
        assert r.returncode == 0, f"{table}: {r.stderr}"


# ── The helper functions ─────────────────────────────────────────────────────

def test_role_rank_orders_the_hierarchy_and_fails_closed_on_junk(db):
    r = _psql(
        db,
        "SELECT public.role_rank('Partner'), public.role_rank('Manager'), "
        "public.role_rank('Executive'), public.role_rank('Reviewer'), "
        "public.role_rank('Client'), public.role_rank('Sorcerer'), "
        "public.role_rank(NULL), public.role_rank('  pArTnEr ');",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    got = [int(x) for x in r.stdout.strip().split("|")]
    # Partner > Manager > Executive > Reviewer > Client; junk and NULL below all
    # of them; case and surrounding whitespace ignored.
    assert got == [4, 3, 2, 1, 0, -1, -1, 4]


def test_legacy_role_strings_rank_with_their_canonical_equivalent(db):
    """A Partner stored as 'owner' under the migration-001/021/022 constraints
    must not be locked out of their own firm by this change."""
    r = _psql(
        db,
        "SELECT public.role_rank('owner'), public.role_rank('admin'), "
        "public.role_rank('article'), public.role_rank('staff'), "
        "public.role_rank('viewer');",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    assert [int(x) for x in r.stdout.strip().split("|")] == [4, 3, 2, 2, 1]


def test_an_unknown_minimum_denies_rather_than_admits(db):
    """A typo in a future policy — my_role_at_least('Managr') — must deny. The
    lazy implementation (rank >= rank, with unknown scoring -1) would ADMIT
    everyone, since every real role outranks -1."""
    r = _psql(
        db,
        f"BEGIN; SET LOCAL ROLE authenticated; "
        f"SET LOCAL request.jwt.claims = '{{\"sub\":\"{UID['Partner']}\"}}'; "
        f"SELECT public.my_role_at_least('Managr'); ROLLBACK;",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    assert [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1] == "f"


# ── Catalogue wiring ─────────────────────────────────────────────────────────

GUARDED = ["chart_of_accounts", "clients", "customers", "tasks", "documents",
           "fee_invoices", "fee_engagements", "mca_filings", "firms"]


def test_every_guarded_table_has_three_restrictive_policies(db):
    """PERMISSIVE would OR with the existing policies and WIDEN access while
    looking, in a diff, exactly like a tightening."""
    names = ", ".join(
        f"'{t}_role_{op}'" for t in GUARDED for op in ("insert", "update", "delete"))
    r = _psql(
        db,
        f"SELECT count(*) FROM pg_policies WHERE schemaname='public' "
        f"AND permissive='RESTRICTIVE' AND policyname IN ({names});",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    assert int(r.stdout.strip()) == len(GUARDED) * 3


def test_no_guarded_table_gained_a_for_all_role_policy(db):
    """FOR ALL would gate SELECT as well — see the read test above."""
    names = ", ".join(
        f"'{t}_role_{op}'" for t in GUARDED for op in ("insert", "update", "delete"))
    r = _psql(
        db,
        f"SELECT count(*) FROM pg_policies WHERE schemaname='public' "
        f"AND policyname IN ({names}) AND cmd NOT IN ('INSERT','UPDATE','DELETE');",
        tuples=True,
    )
    assert r.returncode == 0, r.stderr
    assert int(r.stdout.strip()) == 0
