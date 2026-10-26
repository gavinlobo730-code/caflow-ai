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
WRITE. Apart from the payroll tables (migrations 485 and 490), the fee tables (495) and the
tables that hold a client's bank lines (524), no table's READ policy asks the grid, so a screen that reads a table straight from the browser
is not stopped by a per-person block, and the Team screen says so in a sentence
the API serves (`services.user_permission_service.DENIAL_REACH_NOTICE`). The
last section is the guard that keeps that sentence true: it reads `pg_policies`
on the migrated schema and fails the day any OTHER public table's SELECT or ALL
policy asks the grid, or the day no write policy does. Making a read follow the
grid is a decision and a migration; whoever makes it rewrites the notice in the
same commit and turns the case below into its opposite, as 485 did for payroll
(`test_a_block_on_reading_payroll_hides_it_from_a_direct_read`).

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

from tests._signed_in_bank_access import give_the_signed_in_bank_access_back
from tests._signed_in_document_access import give_the_signed_in_document_access_back
from tests._signed_in_payroll_writes import give_the_signed_in_payroll_access_back, give_the_signed_in_writes_back

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


def _owner_count(dsn: str, select: str) -> str:
    """The row count as the database owner sees it (psql's bare value, no header or footer)."""
    done = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c", select],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


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
        # Migration 549 is the FIRST lock on every payroll table the grid guards (no signed-in privilege at all); this module
        # measures the SECOND (the grid in the policies), so the privilege it took is given back in this throwaway database.
        # Migration 499's write privileges stay revoked unless a test gives them back, as it always has.
        give_the_signed_in_payroll_access_back(d)
        # and migration 550's, for the bank tables this module's read-tier tests ask.
        give_the_signed_in_bank_access_back(d)
        # and migration 551's, for the document tables this module's direct-read tests ask.
        give_the_signed_in_document_access_back(d)
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
# different surface (files, not a table) and is outside this scan: the one
# Storage SELECT that asked the grid, `year_end_exports_storage_select` (469), was
# dropped with the other object policies by migration 551 (POST-A-339), and the
# notice now says stored files are opened only through the server; that is held by
# `test_551_*_pg.py`, which asks every actor.

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


def _scalar_lines_as(dsn: str, auth_user_id: str, sql: str) -> list[str]:
    """Every line a statement prints, as that person, without the two status lines `_as` adds."""
    r = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(auth_user_id) + sql],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines()
            if line.strip() and line.strip() not in ("SET",)]


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


#: The tables whose SELECT policy asks the grid on purpose (migrations 485 and 490). attendance, leave_balances, the two
#: declaration tables and the seven employee-keyed payroll tables are scoped through `payroll_employees` by a
#: subquery, so they follow it without naming a function and do not appear here (nor do the settlement components and
#: run transitions, which follow their settlement and their run).
READ_THROUGH_THE_GRID = {"payroll_employees", "payroll_runs", "payroll_slips",
                         # 490: the three payroll tables keyed on the client and not on an employee or a run
                         "salary_structures", "statutory_remittances", "epfo_ecr_filings", "bonus_declarations",
                         # 495: the practice's fee tables ask billing:read, a Partner's by default
                         "fee_engagements", "fee_invoices", "fee_receipts",
                         # 524: a client's bank lines ask banking:read, an Executive's by default. NOT bank_accounts
                         # (the master the payment pickers read) and not the column mappings
                         "bank_transactions", "bank_statements", "bank_transaction_splits",
                         "bank_reconciliations", "bank_reconciliation_matches", "bank_matching_rules"}


def test_only_the_payroll_fee_and_bank_line_tables_are_read_through_the_grid(dsn):
    """THE GUARD BEHIND "THE DATABASE DOES NOT LOOK AT THIS GRID WHEN A TABLE
    IS READ", NOW WITH ONE NAMED EXCEPTION.

    A Partner who unticks Documents or Bank for a Manager leaves that Manager
    able to select the data straight from the browser, because no read policy
    on those tables asks `user_permissions`. That is what the Team screen says.
    Payroll is the exception since migration 485, the fee tables since 495 and
    a client's bank lines since 524, and the notice says so. The
    day a SELECT or ALL policy on any OTHER public table asks the grid, that
    sentence is wrong in the SAFE direction and still wrong, and this is where
    it is found; the day payroll stops asking, it is wrong in the other.
    """
    names = _functions_that_ask_the_grid(dsn)
    reads = {t for s, t, p, c, qual, _wc in _policies(dsn)
             if s == "public" and c in ("SELECT", "ALL") and _asks(qual, names)}
    assert reads == READ_THROUGH_THE_GRID, (
        f"the tables read through the per-person grid are {sorted(reads)}, and the notice names exactly "
        f"{sorted(READ_THROUGH_THE_GRID)}. If that is deliberate, rewrite {_NOTICE} in the same commit "
        "and turn test_a_block_on_reading_does_not_hide_a_table_read_directly into its opposite "
        "for the table.")
    # and the sentence names each family the policies enforce (the mock-mode sibling holds the wording)
    from services.user_permission_service import DENIAL_REACH_NOTICE
    text = DENIAL_REACH_NOTICE.lower()
    for family, table in (("payroll", "payroll_employees"), ("billing", "fee_engagements"),
                          ("banking", "bank_transactions")):
        assert table in reads and family in text, (family, table)


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
# (documents and bank accounts among them)",
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


# ── payroll: the opposite case, since migration 485 ──────────────────────────
# One table per family: the three that name the grid, and the four children that follow their employee through a
# subquery (the declaration items follow their declaration, which follows the employee). Each is seeded as the administrator (the seed is not what is tested), read by an assigned Manager
# before any block (so the probe is not vacuous), then read again with `payroll:read` refused for that person.
_PAYROLL_READ_PROBES = [
    pytest.param("INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{firm}', '{client}', 'E');",
                 "SELECT count(*) FROM payroll_employees;", id="payroll_employees"),
    pytest.param("INSERT INTO payroll_runs (firm_id, client_id, month) VALUES ('{firm}', '{client}', '2026-04');",
                 "SELECT count(*) FROM payroll_runs;", id="payroll_runs"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id), "
                 "r AS (INSERT INTO payroll_runs (firm_id, client_id, month) "
                 "VALUES ('{firm}', '{client}', '2026-04') RETURNING id) "
                 "INSERT INTO payroll_slips (run_id, employee_id, gross_paise, net_paise) "
                 "SELECT r.id, e.id, 100, 100 FROM e, r;",
                 "SELECT count(*) FROM payroll_slips;", id="payroll_slips"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id) "
                 "INSERT INTO attendance (firm_id, employee_id, month, year) SELECT '{firm}', id, 4, 2026 FROM e;",
                 "SELECT count(*) FROM attendance;", id="attendance"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id) "
                 "INSERT INTO leave_balances (firm_id, employee_id, year) SELECT '{firm}', id, 2026 FROM e;",
                 "SELECT count(*) FROM leave_balances;", id="leave_balances"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id) "
                 "INSERT INTO payroll_it_declarations (firm_id, client_id, employee_id, fy) "
                 "SELECT '{firm}', '{client}', id, '2026-27' FROM e;",
                 "SELECT count(*) FROM payroll_it_declarations;", id="payroll_it_declarations"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id), "
                 "d AS (INSERT INTO payroll_it_declarations (firm_id, client_id, employee_id, fy) "
                 "SELECT '{firm}', '{client}', id, '2026-27' FROM e RETURNING id) "
                 "INSERT INTO payroll_it_declaration_items (firm_id, declaration_id, section) "
                 "SELECT '{firm}', id, '80C' FROM d;",
                 "SELECT count(*) FROM payroll_it_declaration_items;", id="payroll_it_declaration_items"),
    # 490: the twelve other payroll tables, one probe per KIND of scoping. Employee-keyed (through the employee),
    # parent-keyed (a settlement's lines through the settlement, a run's history through the run) and client-keyed
    # (the tier asked by name).
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id) "
                 "INSERT INTO payroll_salary_revisions (firm_id, client_id, employee_id, effective_from) "
                 "SELECT '{firm}', '{client}', id, '2026-04-01' FROM e;",
                 "SELECT count(*) FROM payroll_salary_revisions;", id="payroll_salary_revisions"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id) "
                 "INSERT INTO payroll_loans (firm_id, client_id, employee_id) "
                 "SELECT '{firm}', '{client}', id FROM e;",
                 "SELECT count(*) FROM payroll_loans;", id="payroll_loans"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id) "
                 "INSERT INTO payroll_perquisites (firm_id, client_id, employee_id, fy, label) "
                 "SELECT '{firm}', '{client}', id, '2026-27', 'P' FROM e;",
                 "SELECT count(*) FROM payroll_perquisites;", id="payroll_perquisites"),
    pytest.param("WITH e AS (INSERT INTO payroll_employees (firm_id, client_id, name) "
                 "VALUES ('{firm}', '{client}', 'E') RETURNING id), "
                 "s AS (INSERT INTO payroll_settlements (firm_id, client_id, employee_id, fy, leaving_date) "
                 "SELECT '{firm}', '{client}', id, '2026-27', '2026-09-30' FROM e RETURNING id) "
                 "INSERT INTO payroll_settlement_components (firm_id, settlement_id, label) "
                 "SELECT '{firm}', id, 'L' FROM s;",
                 "SELECT count(*) FROM payroll_settlement_components;", id="payroll_settlement_components"),
    pytest.param("INSERT INTO payroll_runs (firm_id, client_id, month) VALUES ('{firm}', '{client}', '2026-04'); "
                 "INSERT INTO payroll_run_transitions (firm_id, run_id, to_status) "
                 "SELECT '{firm}', id, 'draft' FROM payroll_runs WHERE client_id = '{client}';",
                 "SELECT count(*) FROM payroll_run_transitions;", id="payroll_run_transitions"),
    pytest.param("INSERT INTO salary_structures (firm_id, client_id, name) VALUES ('{firm}', '{client}', 'S');",
                 "SELECT count(*) FROM salary_structures;", id="salary_structures"),
    pytest.param("INSERT INTO epfo_ecr_filings (firm_id, client_id, wage_month, return_type, submitted_on) "
                 "VALUES ('{firm}', '{client}', '2026-04', 'regular', '2026-05-10');",
                 "SELECT count(*) FROM epfo_ecr_filings;", id="epfo_ecr_filings"),
    pytest.param("INSERT INTO bonus_declarations (firm_id, client_id, accounting_year) "
                 "VALUES ('{firm}', '{client}', '2026-27');",
                 "SELECT count(*) FROM bonus_declarations;", id="bonus_declarations"),
]


@pytest.mark.parametrize("seed,select", _PAYROLL_READ_PROBES)
def test_a_block_on_reading_payroll_hides_it_from_a_direct_read(dsn, seed, select):
    """The Team screen's notice says a payroll block is enforced by the database too. Block `payroll:read` for an
    assigned Manager and the same JWT's PostgREST-style SELECT returns nothing, on the three tables that name the grid
    and on the four children that follow their employee (attendance, leave and both declaration tables)."""
    seeded = _psql(dsn, seed.format(firm=FIRM, client=CLIENT))
    assert seeded.returncode == 0, seeded.stderr

    before = _scalar_as(dsn, AUTH_MANAGER, select)
    assert before == "1", f"premise: the assigned Manager could not read the row ({before!r})"

    _grant(dsn, MANAGER, "payroll", "read", False)
    asked = _scalar_as(dsn, AUTH_MANAGER, "SELECT public.my_permission('payroll','read','Manager');")
    assert asked == "f", f"premise: the grid does not refuse payroll:read ({asked!r})"

    after = _scalar_as(dsn, AUTH_MANAGER, select)
    assert after == "0", (
        f"a per-person block on payroll:read no longer hides the table from a direct read ({after!r} rows): "
        f"{_NOTICE} says the database enforces it for payroll")


def test_a_grant_of_payroll_read_reaches_an_executive_and_its_absence_does_not(dsn):
    """THE FINDING IN ITS OWN DIRECTION: with no row an assigned Executive reads no employee (the role floor is
    Manager), and a Partner's per-person yes makes the same SELECT return the row."""
    executive, auth_exec = "41500000-0000-0000-0000-00000000000e", "41500000-1111-0000-0000-000000000003"
    seeded = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{auth_exec}', 'e@t.in');
        INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role)
             VALUES ('{executive}', '{FIRM}', '{auth_exec}', 'e@t.in', 'E', 'Executive');
        INSERT INTO user_client_assignments (firm_id, user_id, client_id)
             VALUES ('{FIRM}', '{executive}', '{CLIENT}');
        INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT}', 'E');
    """)
    assert seeded.returncode == 0, seeded.stderr
    select = "SELECT count(*) FROM payroll_employees;"

    assert _scalar_as(dsn, auth_exec, select) == "0", "an Executive with no grant read payroll"
    _grant(dsn, executive, "payroll", "read", True)
    assert _scalar_as(dsn, auth_exec, select) == "1", "a per-person payroll:read grant did not reach the database"


# ── billing: the practice's fee tables, since migration 495 ──────────────────
# `billing:read` is a Partner's by default, so an assigned Manager reads nothing until the Partner grants it, and a
# grant that is then withdrawn hides the table again. Each table is seeded as the administrator.
_FEE_SEED = ("WITH g AS (INSERT INTO fee_engagements (firm_id, client_id, service_type) "
             "VALUES ('{firm}', '{client}', 'GST Filing') RETURNING id), "
             "i AS (INSERT INTO fee_invoices (firm_id, client_id, engagement_id, invoice_no) "
             "SELECT '{firm}', '{client}', id, 'INV-1' FROM g RETURNING id) "
             "INSERT INTO fee_receipts (firm_id, invoice_id, amount_paise) SELECT '{firm}', id, 100 FROM i;")


@pytest.mark.parametrize("table", ["fee_engagements", "fee_invoices", "fee_receipts"])
def test_billing_read_is_a_partners_unless_granted_and_a_withdrawn_grant_hides_the_table_again(dsn, table):
    seeded = _psql(dsn, _FEE_SEED.format(firm=FIRM, client=CLIENT))
    assert seeded.returncode == 0, seeded.stderr
    select = f"SELECT count(*) FROM {table};"

    assert _scalar_as(dsn, AUTH_MANAGER, select) == "0", "an assigned Manager with no grant read the practice's fees"
    _grant(dsn, MANAGER, "billing", "read", True)
    assert _scalar_as(dsn, AUTH_MANAGER, select) == "1", "a per-person billing:read grant did not reach the database"
    _grant(dsn, MANAGER, "billing", "read", False)
    asked = _scalar_as(dsn, AUTH_MANAGER, "SELECT public.my_permission('billing','read','Partner');")
    assert asked == "f", f"premise: the grid does not refuse billing:read ({asked!r})"
    assert _scalar_as(dsn, AUTH_MANAGER, select) == "0", (
        f"a per-person block on billing:read no longer hides {table} from a direct read: {_NOTICE} says the "
        "database enforces it for billing")


# ── banking: a client's bank lines, since migration 524 ──────────────────────
# `banking:read` is an Executive's by default and the API asks it on every banking route. The six tables below hold the
# client's statements, lines, splits, reconciliations and matching rules; each read asks the grid through a policy
# (524). One row of each is seeded as the administrator, in one statement, because the splits and matches hang off a
# line and the line off a statement.
_BANK_SEED = ("WITH s AS (INSERT INTO bank_statements (firm_id, client_id, bank_name, statement_from, statement_to) "
              "VALUES ('{firm}', '{client}', 'Test Bank', '2026-04-01', '2026-04-30') RETURNING id), "
              "t AS (INSERT INTO bank_transactions (statement_id, firm_id, client_id, transaction_date, description) "
              "SELECT id, '{firm}', '{client}', '2026-04-02', 'UPI/ZOMATO' FROM s RETURNING id), "
              "a AS (INSERT INTO chart_of_accounts (firm_id, account_code, account_name, account_type) "
              "VALUES ('{firm}', '9999', 'Probe', 'Expense') RETURNING id), "
              "sp AS (INSERT INTO bank_transaction_splits (firm_id, client_id, bank_transaction_id, account_id, amount_paise) "
              "SELECT '{firm}', '{client}', t.id, a.id, 100 FROM t, a RETURNING id), "
              "r AS (INSERT INTO bank_reconciliations (firm_id, client_id, period_start, period_end) "
              "VALUES ('{firm}', '{client}', '2026-04-01', '2026-04-30') RETURNING id), "
              "m AS (INSERT INTO bank_reconciliation_matches (firm_id, bank_transaction_id, match_type) "
              "SELECT '{firm}', t.id, 'manual' FROM t RETURNING id) "
              "INSERT INTO bank_matching_rules (firm_id, client_id, rule_name) VALUES ('{firm}', '{client}', 'Probe rule');")
_BANK_LINE_TABLES = ["bank_transactions", "bank_statements", "bank_transaction_splits",
                     "bank_reconciliations", "bank_reconciliation_matches", "bank_matching_rules"]


@pytest.mark.parametrize("table", _BANK_LINE_TABLES)
def test_a_block_on_reading_banking_hides_a_clients_bank_lines_from_a_direct_read(dsn, table):
    """The Team screen's notice says a banking block is enforced by the database for the lines of a client's bank. Block
    `banking:read` for an assigned Manager and the same JWT's PostgREST-style SELECT returns nothing, on all six tables;
    before the block the Manager reads the row (so the probe is not vacuous)."""
    seeded = _psql(dsn, _BANK_SEED.format(firm=FIRM, client=CLIENT))
    assert seeded.returncode == 0, seeded.stderr
    select = f"SELECT count(*) FROM {table};"

    before = _scalar_as(dsn, AUTH_MANAGER, select)
    assert before == "1", f"premise: the assigned Manager could not read the row ({before!r})"

    _grant(dsn, MANAGER, "banking", "read", False)
    asked = _scalar_as(dsn, AUTH_MANAGER, "SELECT public.my_permission('banking','read','Executive');")
    assert asked == "f", f"premise: the grid does not refuse banking:read ({asked!r})"

    after = _scalar_as(dsn, AUTH_MANAGER, select)
    assert after == "0", (
        f"a per-person block on banking:read no longer hides {table} from a direct read ({after!r} rows): "
        f"{_NOTICE} says the database enforces it for a client's bank lines")


def test_a_block_on_banking_leaves_the_bank_account_master_and_the_ledger_readable(dsn):
    """WHAT 524 DELIBERATELY LEAVES ALONE, measured. The payment pickers on receipts, vendor payments and fixed assets
    read `bank_accounts` from the browser for people who use those screens without Banking, and the journal a bank line
    posted is the books, not the bank's data: blocking Banking must not take either away."""
    seeded = _psql(dsn, _BANK_SEED.format(firm=FIRM, client=CLIENT) +
                   f" INSERT INTO bank_accounts (firm_id, client_id, bank_name, account_no) "
                   f"VALUES ('{FIRM}', '{CLIENT}', 'Test Bank', '000111222');"
                   f" INSERT INTO journal_entries (firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted) "
                   f"VALUES ('{FIRM}', '{CLIENT}', '2026-04-02', 'J-1', 'probe', 'Journal', false);")
    assert seeded.returncode == 0, seeded.stderr
    _grant(dsn, MANAGER, "banking", "read", False)
    for table in ("bank_accounts", "journal_entries"):
        n = _scalar_as(dsn, AUTH_MANAGER, f"SELECT count(*) FROM {table};")
        assert n == "1", f"blocking banking:read hid {table} ({n!r}), which 524 leaves alone"


def test_an_insert_that_asks_its_row_back_meets_the_read_policy_of_a_person_blocked_from_reading(dsn):
    """WHAT THE MIGRATION'S HEADER SAYS ABOUT INSERT, MEASURED. The API inserts with the new row asked back
    (`return=representation`, which is INSERT ... RETURNING) and Postgres checks that row against the SELECT policies
    too, so a person a Partner left with `banking:write` and without `banking:read` is refused at the database on every
    insert the API makes for them; a bare INSERT, which asks nothing back, is not touched by a SELECT policy. That state is
    refused at the door now (`tests/test_a_banking_route_also_asks_for_banking_read.py`), which is why this is the second
    lock and not the first; this test is here so the sentence in the migration cannot drift from what the database does."""
    insert = (f"INSERT INTO bank_statements (firm_id, client_id, bank_name, statement_from, statement_to) "
              f"VALUES ('{FIRM}', '{CLIENT}', 'Test Bank', '2026-04-01', '2026-04-30')")

    before = _psql(dsn, _as(AUTH_MANAGER) + insert + " RETURNING id;")
    assert before.returncode == 0, f"premise: an assigned Manager could not insert a statement ({before.stderr!r})"

    _grant(dsn, MANAGER, "banking", "read", False)
    asked = _scalar_as(dsn, AUTH_MANAGER, "SELECT public.my_permission('banking','write','Executive');")
    assert asked == "t", f"premise: the grid refuses banking:write as well ({asked!r})"

    returning = _psql(dsn, _as(AUTH_MANAGER) + insert + " RETURNING id;")
    assert returning.returncode != 0 and "row-level security" in returning.stderr, (
        "an INSERT ... RETURNING by a person blocked from reading banking was not refused by the read policy: the "
        f"migration 524 header and the design record say it is ({returning.stderr!r})")

    bare = _psql(dsn, _as(AUTH_MANAGER) + insert + ";")
    assert bare.returncode == 0, f"a bare INSERT (no row asked back) was refused by a SELECT policy ({bare.stderr!r})"


def test_a_reviewer_reads_no_bank_line_until_the_grid_says_so_and_stops_when_it_is_withdrawn(dsn):
    """THE FLOOR AND THE GRID, BOTH WAYS. `PERMISSIONS["banking"]["read"]` is Executive and above, so an assigned
    Reviewer with no grid entry reads nothing (before 524 they read the client's whole statement over PostgREST); a
    Partner's per-person yes makes the same SELECT return the row, and withdrawing it hides it again."""
    reviewer, auth_rev = "41500000-0000-0000-0000-0000000000f1", "41500000-1111-0000-0000-0000000000f1"
    seeded = _psql(dsn, f"""
        INSERT INTO auth.users (id, email) VALUES ('{auth_rev}', 'r@t.in');
        INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role)
             VALUES ('{reviewer}', '{FIRM}', '{auth_rev}', 'r@t.in', 'R', 'Reviewer');
        INSERT INTO user_client_assignments (firm_id, user_id, client_id)
             VALUES ('{FIRM}', '{reviewer}', '{CLIENT}');
    """ + _BANK_SEED.format(firm=FIRM, client=CLIENT))
    assert seeded.returncode == 0, seeded.stderr
    # every one of the six tables, because the floor is written once per table and a policy that names a lower one
    # for a single table is exactly the slip a read of one table cannot see
    for table in _BANK_LINE_TABLES:
        select = f"SELECT count(*) FROM {table};"
        assert _scalar_as(dsn, AUTH_MANAGER, select) == "1", f"premise: the assigned Manager cannot read {table}"
        assert _scalar_as(dsn, auth_rev, select) == "0", f"a Reviewer with no grant read {table}"
    _grant(dsn, reviewer, "banking", "read", True)
    for table in _BANK_LINE_TABLES:
        assert _scalar_as(dsn, auth_rev, f"SELECT count(*) FROM {table};") == "1", (
            f"a per-person banking:read grant did not reach {table}")
    _grant(dsn, reviewer, "banking", "read", False)
    for table in _BANK_LINE_TABLES:
        assert _scalar_as(dsn, auth_rev, f"SELECT count(*) FROM {table};") == "0", (
            f"a withdrawn banking:read grant still reads {table}")


def test_the_banking_tier_is_asked_once_per_query_and_not_once_per_row(dsn):
    """THE RULE, NOT A SPELLING. `my_permission` is a STABLE plpgsql function that reads a table, and a policy that
    calls it bare has it called once per ROW: measured on 100,000 rows the same count took 5.4 s with no tier policy,
    61.1 s with the bare call and 6.3 s with the call in `(SELECT ...)`, where the planner evaluates it once as an
    InitPlan. So the plan a signed-in person gets for each table must carry an InitPlan and must not carry the
    function inside a Filter."""
    for table in _BANK_LINE_TABLES:
        plan = _scalar_lines_as(dsn, AUTH_MANAGER, f"EXPLAIN SELECT count(*) FROM {table};")
        assert any("InitPlan" in line for line in plan), (
            f"the plan for {table} has no InitPlan, so the banking tier is evaluated per row:\n" + "\n".join(plan))
        filters = [line for line in plan if "Filter" in line]
        assert filters, f"premise: the plan for {table} has no Filter line to inspect:\n" + "\n".join(plan)
        assert not any("my_permission" in line for line in filters), (
            f"{table}'s plan calls my_permission inside a Filter, which is once per row:\n" + "\n".join(plan))


# ── payroll WRITES: the privilege (first lock) and the grid clause of the policies (second lock) ───────────────────────────
# Migration 490 put `my_permission('payroll', 'write', 'Manager')` under the writes of the other payroll tables, and
# these probes proved that a block on writing refused a direct insert. Migration 499 then revoked the write privilege on
# seventeen payroll tables from every signed-in session, because the browser never writes them and a Manager's tier was
# enough to choose the figure a Partner's finalise posts (ledger POST-A-234). The policies remain as the second lock, so
# BOTH are proved here: with the privilege in place an assigned Manager, even WITH an explicit grid grant of
# `payroll:write`, is refused by the privilege and can still read; and with the privilege given back (the migration's
# own rollback, in the throwaway database) a per-person block on `payroll:write` still stops the insert by row security,
# which is the clause the grid reaches the database through.
_PAYROLL_WRITE_PROBES = [
    pytest.param("INSERT INTO salary_structures (firm_id, client_id, name) VALUES ('{firm}', '{client}', 'S2');",
                 "SELECT count(*) FROM salary_structures;", id="salary_structures"),
    pytest.param("INSERT INTO epfo_ecr_filings (firm_id, client_id, wage_month, return_type, submitted_on) "
                 "VALUES ('{firm}', '{client}', '2026-05', 'regular', '2026-06-10');",
                 "SELECT count(*) FROM epfo_ecr_filings;", id="epfo_ecr_filings"),
    pytest.param("INSERT INTO bonus_declarations (firm_id, client_id, accounting_year) "
                 "VALUES ('{firm}', '{client}', '2027-28');",
                 "SELECT count(*) FROM bonus_declarations;", id="bonus_declarations"),
    pytest.param("INSERT INTO payroll_loans (firm_id, client_id, employee_id) "
                 "SELECT '{firm}', '{client}', id FROM payroll_employees LIMIT 1;",
                 "SELECT count(*) FROM payroll_loans;", id="payroll_loans"),
    pytest.param("INSERT INTO payroll_perquisites (firm_id, client_id, employee_id, fy, label) "
                 "SELECT '{firm}', '{client}', id, '2026-27', 'P' FROM payroll_employees LIMIT 1;",
                 "SELECT count(*) FROM payroll_perquisites;", id="payroll_perquisites"),
    pytest.param("INSERT INTO payroll_runs (firm_id, client_id, month) VALUES ('{firm}', '{client}', '2026-05');",
                 "SELECT count(*) FROM payroll_runs;", id="payroll_runs"),
    pytest.param("INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{firm}', '{client}', 'E2');",
                 "SELECT count(*) FROM payroll_employees;", id="payroll_employees"),
]


@pytest.mark.parametrize("insert,select", _PAYROLL_WRITE_PROBES)
def test_a_signed_in_manager_cannot_write_a_payroll_table_even_with_a_grid_grant(request, dsn, insert, select):
    """The privilege is gone for every signed-in session, so the grid's say on writing no longer matters to the database
    for these tables on its own: it is asked in the PracticeSync server, where the write happens."""
    table = request.node.callspec.id
    seeded = _psql(dsn, f"INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT}', 'E');")
    assert seeded.returncode == 0, seeded.stderr
    # the same row is written by the owner, so the Manager's read below counts a row that exists (not a vacuous 0 == 0)
    written = _psql(dsn, insert.format(firm=FIRM, client=CLIENT))
    assert written.returncode == 0, f"premise: the probe statement is malformed: {written.stderr}"
    _grant(dsn, MANAGER, "payroll", "write", True)
    asked = _scalar_as(dsn, AUTH_MANAGER, "SELECT public.my_permission('payroll','write','Manager');")
    assert asked == "t", f"premise: the grid does not grant payroll:write ({asked!r})"

    refused = _psql(dsn, _as(AUTH_MANAGER) + insert.format(firm=FIRM, client=CLIENT))
    assert refused.returncode != 0 and f"permission denied for table {table}" in refused.stderr, (
        f"a signed-in session can write a payroll table the browser never writes: {refused.stderr or 'it succeeded'}")
    everything = _owner_count(dsn, select)                                # what exists, counted by the owner
    assert everything != "0", "premise: nothing exists to read"
    assert _scalar_as(dsn, AUTH_MANAGER, select) == everything, "a refused write must not hide what the Manager could read"


@pytest.mark.parametrize("insert,select", _PAYROLL_WRITE_PROBES)
def test_a_block_on_writing_payroll_stops_a_direct_write_when_the_first_lock_is_lifted(dsn, insert, select):
    """THE SECOND LOCK STILL ASKS THE GRID. With the privilege given back (migration 499's rollback, in this throwaway
    database), an assigned Manager writes the row before any block (so the probe is not vacuous); with `payroll:write`
    refused for that person the same insert is refused by row security, and the rows they could already read are still
    readable, because reading is a different pair. This is the clause migration 490 added; 499 must not leave it
    unmeasured."""
    seeded = _psql(dsn, f"INSERT INTO payroll_employees (firm_id, client_id, name) VALUES ('{FIRM}', '{CLIENT}', 'E');")
    assert seeded.returncode == 0, seeded.stderr
    give_the_signed_in_writes_back(dsn)

    first = _psql(dsn, _as(AUTH_MANAGER) + insert.format(firm=FIRM, client=CLIENT))
    assert first.returncode == 0, f"premise: the assigned Manager could not write before any block: {first.stderr}"

    _grant(dsn, MANAGER, "payroll", "write", False)
    asked = _scalar_as(dsn, AUTH_MANAGER, "SELECT public.my_permission('payroll','write','Manager');")
    assert asked == "f", f"premise: the grid does not refuse payroll:write ({asked!r})"

    refused = _psql(dsn, _as(AUTH_MANAGER) + insert.format(firm=FIRM, client=CLIENT))
    assert refused.returncode != 0 and "row-level security" in refused.stderr, (
        f"a per-person block on payroll:write no longer stops a direct insert: {refused.stderr or 'it succeeded'}")
    everything = _owner_count(dsn, select)                                # what exists, counted by the owner
    assert everything != "0", "premise: nothing exists to read"
    assert _scalar_as(dsn, AUTH_MANAGER, select) == everything, "a block on writing must not hide what could be read"
