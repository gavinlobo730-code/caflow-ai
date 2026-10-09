"""A per-person grant reaches Postgres, and a per-person refusal does too.

G2's last half, proved rather than asserted on shape. Migration 415 puts
`public.my_permission` under migration 260's nine RESTRICTIVE write policies,
so the three states `core.permissions.resolve_permission` has — a row says yes,
a row says no, there is no row — mean the same thing to the database that they
mean to `rbac()`.

WHY THIS NEEDED A REAL DATABASE. The sibling module pins 415's SQL against
PERMISSIONS by reading the file, which catches a drifted list and cannot catch
a predicate that does not do what it says. The interesting case is a MANAGER
inserting into `fee_engagements`: `billing:write` is Partner, so the role says
no, the grid says yes, and only Postgres can settle which one the policy asked.

WHAT EACH CASE IS FOR
  * no row, senior enough       — the ordinary path, unchanged by 415. This is
                                  the one that proves the migration is safe to
                                  merge: `user_permissions` is empty in
                                  production (403 wrote no backfill), so every
                                  write today takes this branch.
  * no row, too junior          — the refusal 260 already gave.
  * row says yes, too junior    — THE FINDING. Before 415 this was refused.
  * row says no, senior enough  — the other direction, which a firm uses to
                                  take one person off billing without moving
                                  their role.
  * a Partner denied `team:write` — the backstop. Without it the grid is
                                  unrepairable.

THE OTHER HALF, WHICH THIS MODULE ALSO HOLDS (POST-A-005). Everything above is a
WRITE. No table's READ policy asks the grid, so a screen that reads a table
straight from the browser is not stopped by a per-person block, and the Team
screen says so in a sentence the API serves
(`services.user_permission_service.DENIAL_REACH_NOTICE`). The last section is
the guard that keeps that sentence true: it reads `pg_policies` on the migrated
schema and fails the day a public table's SELECT or ALL policy asks the grid,
or the day no write policy does. Making reads follow the grid is a decision
(POST-B-004 for payroll) and a migration; whoever makes it rewrites the notice
in the same commit and turns the cases below into their opposites.

Simulates an authenticated PostgREST session the way
`_supabase_compat_bootstrap.sql`'s auth.uid() shim expects: `SET
request.jwt.claims = '{"sub": "<auth_user_id>"}'` + `SET ROLE authenticated`.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import re
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
    reason="the per-person RLS proof requires HARNESS_PG + psql",
)

FIRM = "41500000-0000-0000-0000-000000000001"
CLIENT = "41500000-0000-0000-0000-0000000000c1"
PARTNER = "41500000-0000-0000-0000-00000000000a"
MANAGER = "41500000-0000-0000-0000-00000000000b"
AUTH_PARTNER = "41500000-1111-0000-0000-000000000001"
AUTH_MANAGER = "41500000-1111-0000-0000-000000000002"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _as(auth_user_id: str) -> str:
    return (f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\"}}'; "
            f"SET ROLE authenticated; ")


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e415_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES
                   ('{AUTH_PARTNER}', 'p@t.in'), ('{AUTH_MANAGER}', 'm@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role)
                 VALUES ('{PARTNER}', '{FIRM}', '{AUTH_PARTNER}', 'p@t.in', 'P', 'Partner'),
                        ('{MANAGER}', '{FIRM}', '{AUTH_MANAGER}', 'm@t.in', 'M', 'Manager');
            -- Migration 084's `<table>_assignment_scope` is a SECOND restrictive
            -- policy and an ORTHOGONAL question: the grid says which MODULE a
            -- person may use, the assignment says which CLIENTS' books they see.
            -- A Partner short-circuits to TRUE; everyone else needs a row. Seeded
            -- so this module measures the permission and not the scope, and
            -- `test_a_grant_is_a_module_not_a_scope` below measures the other way
            -- round.
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{MANAGER}', '{CLIENT}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _grant(dsn: str, user_id: str, resource: str, action: str, granted: bool) -> None:
    r = _psql(dsn, f"""
        INSERT INTO user_permissions (firm_id, user_id, resource, action, granted)
             VALUES ('{FIRM}', '{user_id}', '{resource}', '{action}', {str(granted).lower()})
        ON CONFLICT (user_id, resource, action)
          DO UPDATE SET granted = EXCLUDED.granted;
    """)
    assert r.returncode == 0, r.stderr


def _insert_engagement(dsn: str, auth_user_id: str) -> subprocess.CompletedProcess:
    """One fee engagement, as that person. `fee_paise` is what makes this
    `billing` rather than `engagement` — see routers/engagements.py."""
    return _psql(dsn, _as(auth_user_id) + f"""
        INSERT INTO fee_engagements
               (firm_id, client_id, service_type, fee_paise, billing_cycle, start_date, status)
        VALUES ('{FIRM}', '{CLIENT}', 'GST Filing', 2500000, 'Monthly', '2026-04-01', 'Active');
    """)


# ── The five states ──────────────────────────────────────────────────────────

def test_no_row_and_senior_enough_is_allowed(dsn):
    """The branch every write in production takes today.

    `user_permissions` is empty (403 wrote no backfill), so this is the whole
    of 415's blast radius: if this case changed, the migration would not be
    safe to merge.
    """
    r = _insert_engagement(dsn, AUTH_PARTNER)
    assert r.returncode == 0, r.stderr


def test_no_row_and_too_junior_is_refused(dsn):
    """What 260 already gave. `billing:write` is Partner."""
    r = _insert_engagement(dsn, AUTH_MANAGER)
    assert r.returncode != 0, "a Manager inserted a fee engagement with no grant"
    assert "policy" in (r.stderr or "").lower(), r.stderr


def test_a_grant_reaches_the_database(dsn):
    """THE FINDING. Before 415 this was refused, silently, as a save failure.

    A Partner puts one Manager on billing through the Team screen; `rbac()`
    honours it and Postgres did not.
    """
    before = _insert_engagement(dsn, AUTH_MANAGER)
    assert before.returncode != 0, "premise: the Manager could already write"

    _grant(dsn, MANAGER, "billing", "write", True)

    after = _insert_engagement(dsn, AUTH_MANAGER)
    assert after.returncode == 0, (
        "a per-person billing:write grant still does not reach the database:\n"
        + (after.stderr or ""))


def test_a_refusal_reaches_the_database_too(dsn):
    """The other direction — taking one person off billing without demoting
    them. A control that can only widen is not the grid."""
    before = _insert_engagement(dsn, AUTH_PARTNER)
    assert before.returncode == 0, "premise: the Partner could already write"

    _grant(dsn, PARTNER, "billing", "write", False)

    after = _insert_engagement(dsn, AUTH_PARTNER)
    assert after.returncode != 0, "a per-person refusal did not reach the database"


def test_a_partner_keeps_the_four_pairs_the_grid_itself_rests_on(dsn):
    """`firms` is guarded by `firm:write`, which is revokable; `firm:admin` and
    the two `team` pairs are not, because the only person who could undo the
    row is the one it locked out.

    Proved on the FUNCTION rather than through a table, because none of the
    nine tables is guarded by one of the four pairs — which is itself the
    reason the backstop lives in `my_permission` and not in a policy.
    """
    _grant(dsn, PARTNER, "team", "write", False)
    _grant(dsn, MANAGER, "team", "write", False)

    def answer(auth_user_id: str) -> str:
        r = subprocess.run(
            ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
             _as(auth_user_id) + "SELECT public.my_permission('team','write','Partner');"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        # `_as` is two SET statements in the same -c, and psql prints a status
        # line for each. The answer is the last line.
        return r.stdout.strip().splitlines()[-1].strip()

    assert answer(AUTH_PARTNER) == "t", "a Partner was locked out of the access screen"
    assert answer(AUTH_MANAGER) == "f", (
        "the backstop leaked to a non-Partner — it must be the role test AND "
        "the pair, not either")


def test_an_unrelated_pair_is_untouched_by_a_grant(dsn):
    """A grant is one pair, not a tier.

    `billing:write` on the Manager must not let them write `firms`, which is
    `firm:write` at Partner. The three-state resolver is per pair and this is
    what stops a module grant reading as a promotion.

    MEASURED ON THE EFFECT, NOT THE EXIT CODE, and the difference is not
    cosmetic: a RESTRICTIVE policy's USING clause FILTERS the rows an UPDATE can
    see, so a refused UPDATE is `UPDATE 0` and psql exits 0. An exit-code
    assertion here passes whether the policy works or not — it did, on the
    first run of this file.
    """
    _grant(dsn, MANAGER, "billing", "write", True)
    r = _psql(dsn, _as(AUTH_MANAGER) +
              f"UPDATE firms SET name = 'renamed' WHERE id = '{FIRM}';")
    name = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c",
         f"SELECT name FROM firms WHERE id = '{FIRM}';"],
        capture_output=True, text=True)
    assert name.returncode == 0, name.stderr
    assert name.stdout.strip() == "F", (
        f"a billing grant widened access to the firm record (name is now "
        f"{name.stdout.strip()!r}, psql exit {r.returncode})")


def test_a_grant_is_a_module_not_a_scope(dsn):
    """The grid and the client-assignment scope are two questions.

    `core.authz._FIRMWIDE_ROLES` is `{Partner}`, and migration 084 gives every
    client-scoped table a RESTRICTIVE `<table>_assignment_scope` policy that a
    Partner short-circuits and everyone else satisfies with a
    `user_client_assignments` row. Granting `billing:write` must not hand a
    Manager a client they are not on — that would let a firm widen client
    access while believing they had granted a module, which is exactly why
    migration 403 left the role answering the SQL policies and the scope alone.
    """
    _grant(dsn, MANAGER, "billing", "write", True)
    r = _psql(dsn, f"DELETE FROM user_client_assignments WHERE user_id = '{MANAGER}';")
    assert r.returncode == 0, r.stderr

    after = _insert_engagement(dsn, AUTH_MANAGER)
    assert after.returncode != 0, (
        "a module grant reached a client the person is not assigned to")
    assert "assignment_scope" in (after.stderr or ""), after.stderr


# ── What the grid does NOT reach: reading a table (POST-A-005) ───────────────
#
# The Team screen tells a Partner what a block reaches, in a sentence the API
# serves (`DENIAL_REACH_NOTICE`): the database does not look at the grid when a
# table is read, and a direct write is checked against it on some tables only.
# Both are claims about `pg_policies`, so they are held HERE, on the schema the
# migrations build, and not on a copy of the migration text.
#
# THE RULE, NOT A LIST OF TABLES. The first test asks whether any SELECT or ALL
# policy on a public table calls the grid — `my_permission` itself or any
# function that calls it, found through `pg_proc` to a fixed point, so a wrapper
# a later migration writes is as visible as the function it wraps. Storage is a
# different surface (files, not a table) and is outside the sentence: the one
# Storage SELECT that asks the grid, `year_end_exports_storage_select` (469), is
# deliberately not in scope here, and the notice names it as the one read the grid reaches.

_NOTICE = "services.user_permission_service.DENIAL_REACH_NOTICE"


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _scalar_as(dsn: str, auth_user_id: str, sql: str) -> str:
    """One value, as that person. `_as` is two SETs in the same -c and psql
    prints a status line for each, so the answer is the last line."""
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(auth_user_id) + sql],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1].strip()


def _functions_that_ask_the_grid(dsn: str) -> set[str]:
    """`my_permission` and every function whose body calls one of them."""
    found = {"my_permission"}
    while True:
        names = "|".join(sorted(found))
        rows = _rows(dsn, f"""
            SELECT DISTINCT p.proname
              FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
               AND p.prosrc ~* '\\m({names})\\M';
        """)
        new = {r[0] for r in rows}
        if new <= found:
            return found
        found |= new


def _policies(dsn: str) -> list[tuple[str, str, str, str, str, str]]:
    """(schema, table, policy, command, USING, WITH CHECK), whitespace folded."""
    rows = _rows(dsn, """
        SELECT schemaname, tablename, policyname, cmd,
               regexp_replace(coalesce(qual, ''), '\\s+', ' ', 'g'),
               regexp_replace(coalesce(with_check, ''), '\\s+', ' ', 'g')
          FROM pg_policies ORDER BY 1, 2, 3;
    """)
    assert rows, "pg_policies came back empty — the scan below would pass on nothing"
    return [tuple(r) for r in rows]  # type: ignore[misc]


def _asks(expr: str, names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\s*\(", expr) for n in names)


def test_no_public_table_is_read_through_the_grid(dsn):
    """THE GUARD BEHIND "THE DATABASE DOES NOT LOOK AT THIS GRID WHEN A TABLE
    IS READ".

    A Partner who unticks Payroll, Documents or Bank for a Manager leaves that
    Manager able to select the data straight from the browser, because no read
    policy asks `user_permissions`. That is what the Team screen now says. The
    day a SELECT or ALL policy on a public table asks the grid, that sentence is
    wrong in the SAFE direction and still wrong, and this is where it is found.
    """
    names = _functions_that_ask_the_grid(dsn)
    reads = [(t, p, c) for s, t, p, c, qual, _wc in _policies(dsn)
             if s == "public" and c in ("SELECT", "ALL") and _asks(qual, names)]
    assert not reads, (
        "a public table is now read through the per-person grid: "
        f"{reads}. If that is deliberate, rewrite {_NOTICE} in the same commit "
        "(it says no table read asks the grid) and turn "
        "test_a_block_on_reading_does_not_hide_a_table_read_directly into its "
        "opposite for that table.")


def test_some_but_not_all_tables_are_written_through_the_grid(dsn):
    """THE OTHER HALF OF THE SENTENCE: "direct writes are checked against this
    grid on some tables only".

    Both words are claims. "Some" — the scan must see migration 415's tables,
    or the guard above passes on a scan that finds nothing and the notice
    promises a protection that is not there. "Only" — a write policy that asks
    the role and not the grid still exists (261, 296, 345, 346, 359 and later),
    so a firm cannot read "checked" as "all".
    """
    names = _functions_that_ask_the_grid(dsn)
    grid_written: set[str] = set()
    any_written: set[str] = set()
    for s, t, _p, c, qual, wc in _policies(dsn):
        if s != "public" or c not in ("INSERT", "UPDATE", "DELETE", "ALL"):
            continue
        any_written.add(t)
        if _asks(qual, names) or _asks(wc, names):
            grid_written.add(t)
    assert "fee_engagements" in grid_written, (
        "the scan cannot see migration 415's write policies, which the cases "
        "above prove behaviourally — the read guard is passing on nothing")
    assert grid_written < any_written, (
        f"every table with a write policy is now written through the grid; "
        f"{_NOTICE} says 'some tables only' and must be rewritten")


# What the sentence calls "several screens read tables directly from the browser
# (payroll attendance and reports, documents and bank accounts among them)",
# measured instead of assumed: one table per family, with the permission pair a
# Partner would block to keep a Manager out of it and the role floor that pair
# is written with, so `my_permission` is asked the question the grid answers.
_READ_PROBES = [
    pytest.param(
        "document", "Reviewer",
        "INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path) "
        "VALUES ('{firm}', '{client}', 'OTHER', 'a.pdf', 'p/a.pdf');",
        "SELECT count(*) FROM documents;", id="documents"),
    pytest.param(
        "banking", "Executive",
        "INSERT INTO bank_accounts (firm_id, client_id, bank_name, account_no) "
        "VALUES ('{firm}', '{client}', 'Test Bank', '000111222');",
        "SELECT count(*) FROM bank_accounts;", id="bank_accounts"),
    pytest.param(
        "payroll", "Manager",
        "INSERT INTO payroll_employees (firm_id, client_id, name) "
        "VALUES ('{firm}', '{client}', 'E');",
        "SELECT count(*) FROM payroll_employees;", id="payroll_employees"),
]


@pytest.mark.parametrize("resource,floor,seed,select", _READ_PROBES)
def test_a_block_on_reading_does_not_hide_a_table_read_directly(
        dsn, resource, floor, seed, select):
    """The finding, end to end: block `<resource>:read` for an assigned Manager
    and the same JWT's PostgREST-style SELECT still returns the row.

    Three steps, each of which would otherwise be assumed: the Manager reads the
    row before any block (so the probe is not vacuous), the grid then answers NO
    for this person on this pair (so the block really is in force — the same
    function the write policies ask), and the row is still there.
    """
    seeded = _psql(dsn, seed.format(firm=FIRM, client=CLIENT))
    assert seeded.returncode == 0, seeded.stderr

    before = _scalar_as(dsn, AUTH_MANAGER, select)
    assert before == "1", f"premise: the assigned Manager could not read the row ({before!r})"

    _grant(dsn, MANAGER, resource, "read", False)
    asked = _scalar_as(
        dsn, AUTH_MANAGER, f"SELECT public.my_permission('{resource}','read','{floor}');")
    assert asked == "f", f"premise: the grid does not refuse {resource}:read ({asked!r})"

    after = _scalar_as(dsn, AUTH_MANAGER, select)
    assert after == "1", (
        f"a per-person block on {resource}:read now hides the table from a direct "
        f"read ({after!r} rows). If that is deliberate, rewrite {_NOTICE} in the "
        "same commit: it tells a Partner that reading a table directly is not "
        "checked against this grid.")
