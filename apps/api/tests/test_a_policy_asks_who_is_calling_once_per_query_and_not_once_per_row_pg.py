"""A row-security policy calls the helper that says who is asking once per QUERY, not once per ROW (migration 525).

WHAT WAS WRONG
    `firm_id = get_my_firm_id()`, `my_permission('payroll', 'read', 'Manager')`, `my_role_at_least('Manager')`,
    `get_my_role() = 'Partner'`: a policy that calls one of these bare has Postgres call it for EVERY ROW a query touches,
    because only a call wrapped in a scalar sub-select, `(SELECT fn(...))`, is planned as an InitPlan and evaluated once.
    The helpers are SECURITY DEFINER functions with a `SET search_path`, so they cannot be inlined. Measured on this schema,
    100,000 rows, `SELECT count(*)` as a signed-in session: 5,537 ms with the firm policy bare and 13 ms wrapped; 61,115 ms
    with a bare `my_permission` tier policy and 6,262 ms wrapped (both measured with the firm policy still bare beside it,
    so about 5.5 s of the 6.3 s is the firm policy; the tier policy's own wrapped cost is under a second). 603 policy
    expressions called `get_my_firm_id()`, 339 `my_permission(...)`, 183 `my_role_at_least(...)`, 128 `get_my_role()` and
    108 `my_internal_client_id()` (a count of the migrated schema's catalog at the time, which this module does not
    reproduce).

WHAT THIS HOLDS
    * THE RULE: after the migrations, no policy in `public` calls a helper with constant arguments outside a sub-select.
      Read from `pg_policy`, so a policy a later migration writes bare fails here and the author wraps it.
    * THE PLAN, which is what the rule is for: a signed-in session's `EXPLAIN` of a scan of a firm table has an InitPlan
      and does not carry the helper inside a Filter.
    * THE REWRITE IS THE SAME PREDICATE. The role-by-table matrix proves it over every table the browser reaches; this
      module proves it over every SHAPE a policy can take, which the repository's own policies do not all exercise: AND, OR,
      NOT, CASE, a call inside an EXISTS, a WITH CHECK alone, an UPDATE with both clauses, a JWT claim, a qualified name,
      a table and a policy whose names need quoting, restrictive and permissive. EACH SHAPE HAS ITS OWN TABLE, with only a
      permissive "everything" policy beside it where the shape is restrictive, so the shape under test is the only thing
      deciding what an actor sees; seven actors (a Partner, a Manager and an Executive of one firm, a suspended member of
      it, a Partner of another firm, a signed-in person with no staff row, and the Manager's own identity carrying a JWT
      whose role claim is not `authenticated`) run against rows of two firms and an internal client, and a shape whose
      outcomes do not differ between actors fails as vacuous. The same rows are visible, insertable and updatable to the
      same actors before and after, after the rollback, and after a second run changes nothing.
    * THE ROLLBACK unwraps EVERY wrapped helper call in a `public` policy, including the calls earlier migrations wrote
      wrapped by hand (it cannot tell its own wrapping from theirs), leaves alone only migration 524's `*_banking_read_tier`
      policies, and a re-apply wraps them all again with every answer unchanged.

Simulates an authenticated PostgREST session the way `_supabase_compat_bootstrap.sql`'s auth.uid() shim expects.
Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests._signed_in_payroll_writes import give_the_signed_in_payroll_access_back

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the policy-evaluation proof requires HARNESS_PG + psql",
)

FIRM = "52500000-0000-0000-0000-000000000001"
OTHER_FIRM = "52500000-0000-0000-0000-000000000002"
CLIENT = "52500000-0000-0000-0000-0000000000c1"
PARTNER = "52500000-0000-0000-0000-00000000000a"
MANAGER = "52500000-0000-0000-0000-00000000000b"
EXECUTIVE = "52500000-0000-0000-0000-00000000000e"
INTERNAL = "52500000-0000-0000-0000-0000000000c2"   # the firm's own practice-client
SUSPENDED = "52500000-0000-0000-0000-00000000000f"
OTHER_PARTNER = "52500000-0000-0000-0000-00000000000d"
AUTH = {
    "partner": "52500000-1111-0000-0000-000000000001",
    "manager": "52500000-1111-0000-0000-000000000002",
    "executive": "52500000-1111-0000-0000-000000000003",
    "suspended": "52500000-1111-0000-0000-000000000004",
    "other_firm": "52500000-1111-0000-0000-000000000005",
    "stranger": "52500000-1111-0000-0000-000000000006",     # signed in, and nobody's staff row
}
#: Who is asking: (the auth user, the JWT's `role` claim). The last actor is the Manager's own identity carrying a token whose
#: role claim is not `authenticated`, which only a policy that reads the claim can tell apart from the Manager.
ACTORS = {
    "partner": (AUTH["partner"], "authenticated"),
    "manager": (AUTH["manager"], "authenticated"),
    "executive": (AUTH["executive"], "authenticated"),
    "suspended": (AUTH["suspended"], "authenticated"),
    "other_firm": (AUTH["other_firm"], "authenticated"),
    "stranger": (AUTH["stranger"], "authenticated"),
    "wrong_claim": (AUTH["manager"], "anon"),
}

#: The helpers whose calls, with constant arguments, are wrapped. The same list the migration, the guard snapshot's fold and
#: the rollback carry; the three are pinned to each other below.
HELPERS = ("get_my_firm_id", "get_my_role", "get_my_user_id", "my_internal_client_id", "my_permission", "my_role_at_least")
#: A call of one of them, or of auth.uid/jwt/role, that is not the target of a sub-select.
BARE = (r"(?<!SELECT )(?<![A-Za-z_.])((?:public\.)?(?:" + "|".join(HELPERS) + r")\([^()]*\)|auth\.(?:uid|jwt|role)\(\))")

MIGRATION = next(p for p in MIGRATIONS.glob("525_a_policy_asks_who_is_calling_once_per_query_*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("525_a_policy_asks_who_is_calling_once_per_query_*_rollback.sql"))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    auth_user_id, claim = ACTORS[who]
    return f"SET request.jwt.claims = '{{\"sub\": \"{auth_user_id}\", \"role\": \"{claim}\"}}'; SET ROLE authenticated; "


def _lines_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e525_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH["partner"]}', 'p@t.in'), ('{AUTH["manager"]}', 'm@t.in'),
                                                      ('{AUTH["executive"]}', 'e@t.in'), ('{AUTH["suspended"]}', 's@t.in'),
                                                      ('{AUTH["other_firm"]}', 'o@t.in'), ('{AUTH["stranger"]}', 'x@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT}', '{FIRM}', 'C', 'Proprietorship'), ('{INTERNAL}', '{FIRM}', 'Our own practice', 'Proprietorship');
            UPDATE firms SET internal_client_id = '{INTERNAL}' WHERE id = '{FIRM}';
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER}', '{FIRM}', '{AUTH["partner"]}', 'p@t.in', 'P', 'Partner', true),
                        ('{MANAGER}', '{FIRM}', '{AUTH["manager"]}', 'm@t.in', 'M', 'Manager', true),
                        ('{EXECUTIVE}', '{FIRM}', '{AUTH["executive"]}', 'e@t.in', 'E', 'Executive', true),
                        ('{SUSPENDED}', '{FIRM}', '{AUTH["suspended"]}', 's@t.in', 'S', 'Manager', false),
                        ('{OTHER_PARTNER}', '{OTHER_FIRM}', '{AUTH["other_firm"]}', 'o@t.in', 'O', 'Partner', true);
        """)
        assert seed.returncode == 0, seed.stderr
        give_the_signed_in_payroll_access_back(d)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── THE RULE ────────────────────────────────────────────────────────────────────

def _folded(column: str) -> str:
    """A policy expression as one line (a deparsed CASE or EXISTS can run over several)."""
    return f"regexp_replace(coalesce(pg_get_expr(p.{column}, p.polrelid), ''), '\\s+', ' ', 'g')"


def test_no_policy_calls_a_helper_once_per_row(dsn):
    # the pattern is applied in SQL (Postgres' own regex engine, the one the migration uses), as dollar-quoted text
    offenders = [r[0] for r in _rows(dsn, f"""
            SELECT c.relname || '.' || p.polname
              FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND ({_folded('polqual')} ~ $re${BARE}$re$ OR {_folded('polwithcheck')} ~ $re${BARE}$re$)
             ORDER BY 1""")]
    assert not offenders, (
        f"{len(offenders)} policies call a helper once per row; write the call as (SELECT fn(...)) in the policy "
        f"(migration 525 explains why, with the measurements): {offenders[:12]}")


def test_the_scan_is_not_vacuous_the_schema_has_many_policies_that_are_wrapped(dsn):
    wrapped = _rows(dsn, """
        SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND coalesce(pg_get_expr(p.polqual, p.polrelid), '') ~ '\\( SELECT (get_my_firm_id|get_my_role|my_permission|my_role_at_least)\\(';""")
    assert int(wrapped[0][0]) > 300, f"only {wrapped[0][0]} policies are wrapped: the migration did not run or the scan reads nothing"


# ── THE PLAN ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["journal_entries", "clients", "payroll_runs", "client_sales_invoices", "fee_invoices"])
def test_a_signed_in_scan_asks_who_is_calling_once(dsn, table):
    plan = _lines_as(dsn, "manager", f"EXPLAIN SELECT count(*) FROM {table};")
    assert any("InitPlan" in line for line in plan), f"no InitPlan in the plan for {table}:\n" + "\n".join(plan)
    filters = [line for line in plan if "Filter" in line]
    for helper in HELPERS:
        assert not any(helper in line for line in filters), (
            f"{table}'s plan calls {helper} inside a Filter, which is once per row:\n" + "\n".join(plan))


# ── THE REWRITE IS THE SAME PREDICATE, OVER EVERY SHAPE ─────────────────────────

#: Synthetic policies written BARE, one per shape, each on a table of its own. (name, kind, command, using, with check)
#: A restrictive shape gets a permissive "everything" policy beside it, so it is the only thing deciding what is seen.
_SHAPES = [
    ("firm", "PERMISSIVE", "SELECT", "firm_id = get_my_firm_id()", None),
    ("and_role", "RESTRICTIVE", "SELECT", "firm_id = get_my_firm_id() AND get_my_role() IN ('Partner', 'Manager')", None),
    ("or_tier", "PERMISSIVE", "SELECT", "my_permission('billing', 'read', 'Partner') OR n % 2 = 0", None),
    ("not_atleast", "RESTRICTIVE", "SELECT", "NOT (my_role_at_least('Manager') AND n > 4)", None),
    ("case_when", "RESTRICTIVE", "SELECT",
     "CASE WHEN get_my_role() = 'Partner' THEN true WHEN get_my_role() = 'Manager' THEN n <= 6 ELSE n <= 2 END", None),
    ("exists_user", "RESTRICTIVE", "SELECT",
     "EXISTS (SELECT 1 FROM public.users u WHERE u.id = get_my_user_id() AND u.is_active)", None),
    ("internal", "RESTRICTIVE", "SELECT", "get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id()", None),
    ("claim", "RESTRICTIVE", "SELECT", "auth.role() = 'authenticated' AND auth.uid() IS NOT NULL", None),
    ("qualified", "RESTRICTIVE", "SELECT", "public.get_my_firm_id() IS NOT NULL", None),
    ("insert_only", "PERMISSIVE", "INSERT", None, "firm_id = get_my_firm_id() AND my_role_at_least('Executive')"),
    ("update_both", "PERMISSIVE", "UPDATE", "firm_id = get_my_firm_id()", "firm_id = get_my_firm_id() AND get_my_role() <> 'Executive'"),
]


def _tbl(name: str) -> str:
    return f'public."Shape {name}"'   # a name that needs quoting, for the table and (below) the policy


def _build_shapes(dsn: str) -> None:
    stmts: list[str] = []
    for name, kind, command, using, check in _SHAPES:
        t = _tbl(name)
        stmts += [
            f'CREATE TABLE {t} (id serial PRIMARY KEY, firm_id uuid NOT NULL, client_id uuid, n int NOT NULL);',
            f'GRANT SELECT, INSERT, UPDATE ON {t} TO authenticated;',
            f'GRANT USAGE ON SEQUENCE public."Shape {name}_id_seq" TO authenticated;',
            f'ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;',
            # the firm's own rows: six for the client, two for its internal client; another firm's three beside them
            f"INSERT INTO {t} (firm_id, client_id, n) SELECT '{FIRM}', CASE WHEN g <= 6 THEN '{CLIENT}'::uuid ELSE '{INTERNAL}'::uuid END, g "
            f"FROM generate_series(1, 8) g;",
            f"INSERT INTO {t} (firm_id, client_id, n) SELECT '{OTHER_FIRM}', '{CLIENT}', g FROM generate_series(11, 13) g;",
        ]
        if kind == "RESTRICTIVE" or command != "SELECT":
            stmts.append(f'CREATE POLICY "everything {name}" ON {t} AS PERMISSIVE FOR SELECT TO authenticated USING (true);')
        clause = f'CREATE POLICY "shape {name}" ON {t} AS {kind} FOR {command} TO authenticated'
        if using:
            clause += f" USING ({using})"
        if check:
            clause += f" WITH CHECK ({check})"
        stmts.append(clause + ";")
    done = _psql(dsn, "\n".join(stmts))
    assert done.returncode == 0, done.stderr


def _is_bare(dsn: str, policy_name: str) -> bool:
    got = _rows(dsn, f"""SELECT count(*) FROM pg_policy p
                          WHERE p.polname = '{policy_name}'
                            AND ({_folded('polqual')} ~ $re${BARE}$re$ OR {_folded('polwithcheck')} ~ $re${BARE}$re$)""")
    return int(got[0][0]) == 1


def _select_outcome(dsn: str, who: str, name: str) -> tuple:
    return tuple(_lines_as(dsn, who, f"SELECT coalesce(string_agg(n::text, ',' ORDER BY n), '-') FROM {_tbl(name)};"))


def _insert_outcome(dsn: str, who: str, name: str) -> bool:
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", _as(who) +
                        f"INSERT INTO {_tbl(name)} (firm_id, client_id, n) VALUES ('{FIRM}', '{CLIENT}', 99);"],
                       capture_output=True, text=True)
    _psql(dsn, f"DELETE FROM {_tbl(name)} WHERE n = 99;")
    return r.returncode == 0


def _update_outcome(dsn: str, who: str, name: str) -> bool:
    r = subprocess.run(["psql", dsn, "-X", "-tA", "-c", _as(who) +
                        f"WITH u AS (UPDATE {_tbl(name)} SET n = n WHERE n = 1 AND firm_id = '{FIRM}' RETURNING 1) SELECT count(*) FROM u;"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip().splitlines()[-1].strip() == "1"


def _outcomes(dsn: str, name: str, command: str) -> dict:
    """What every actor gets from the one operation the shape governs."""
    one = {"SELECT": _select_outcome, "INSERT": _insert_outcome, "UPDATE": _update_outcome}[command]
    return {who: one(dsn, who, name) for who in ACTORS}


def _all_outcomes(dsn: str) -> dict:
    return {name: _outcomes(dsn, name, command) for name, _kind, command, *_ in _SHAPES}


def _policies(dsn: str) -> list:
    return _rows(dsn, f"SELECT p.polname, {_folded('polqual')}, {_folded('polwithcheck')} FROM pg_policy p ORDER BY 1")


def test_every_shape_is_the_same_predicate_before_and_after_and_the_second_run_changes_nothing(dsn):
    _build_shapes(dsn)
    before = _all_outcomes(dsn)

    # THE PREMISE, shape by shape: the actors get different answers, so a rewrite that changed the predicate could be seen
    vacuous = [name for name, outcomes in before.items() if len({str(v) for v in outcomes.values()}) < 2]
    assert not vacuous, f"these shapes give every actor the same outcome, so the comparison below cannot fail on them: {vacuous}"

    # and the shapes really are bare to begin with
    for name, *_ in _SHAPES:
        assert _is_bare(dsn, f"shape {name}"), f"premise: the {name} policy is not bare"

    first = _psql_file(dsn, MIGRATION)
    assert first.returncode == 0, first.stderr
    for name, *_ in _SHAPES:
        assert not _is_bare(dsn, f"shape {name}"), f"the {name} policy still calls a helper per row"

    after = _all_outcomes(dsn)
    changed = {name: {who: (before[name][who], after[name][who]) for who in ACTORS if before[name][who] != after[name][who]}
               for name in before if before[name] != after[name]}
    assert not changed, f"the rewrite changed what an actor can see, insert or update: {changed}"

    snapshot = _policies(dsn)
    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _policies(dsn) == snapshot, "a second run of the migration changed a policy"


def test_the_rollback_returns_every_shape_to_the_same_answers_too(dsn):
    """The round trip: bare, wrapped, bare again. The rollback's pattern is the migration's in reverse, so the same actors
    must get the same answers from the unwrapped text as from the original."""
    _build_shapes(dsn)
    before = _all_outcomes(dsn)
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    for name, *_ in _SHAPES:
        assert _is_bare(dsn, f"shape {name}"), f"the rollback left the {name} policy wrapped"
    assert _all_outcomes(dsn) == before, "the rollback changed what an actor can see, insert or update"


def test_the_rewrite_keeps_every_policys_name_kind_command_and_roles(dsn):
    def shape():
        return _rows(dsn, "SELECT polname, polpermissive, polcmd, polroles::text, polrelid::regclass::text FROM pg_policy ORDER BY 5, 1")
    # the migration already ran in the template; unwrap with the rollback, then compare after a re-apply
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    unwrapped = shape()
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert shape() == unwrapped


# ── THE ROLLBACK ────────────────────────────────────────────────────────────────

def test_the_rollback_unwraps_the_policies_and_a_reapply_wraps_them_again(dsn):
    done = _psql_file(dsn, ROLLBACK)
    assert done.returncode == 0, done.stderr
    bare = _rows(dsn, """SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                          WHERE n.nspname = 'public' AND p.polname = 'firm_client_isolation'
                            AND pg_get_expr(p.polqual, p.polrelid) ~ '^\\(firm_id = get_my_firm_id\\(\\)\\)$'""")
    assert int(bare[0][0]) >= 1, "the rollback did not return the firm policy to the per-row call"
    kept = _rows(dsn, """SELECT count(*) FROM pg_policy WHERE polname LIKE '%\\_banking\\_read\\_tier'
                          AND pg_get_expr(polqual, polrelid) ~ '^\\( SELECT my_permission'""")
    banking = _rows(dsn, "SELECT count(*) FROM pg_policy WHERE polname LIKE '%\\_banking\\_read\\_tier'")
    assert kept[0][0] == banking[0][0], "the rollback unwrapped a policy that was written wrapped on purpose"
    if list(MIGRATIONS.glob("524_the_database_asks_the_banking_tier_*.sql")):
        assert int(banking[0][0]) == 6, "migration 524's six policies are not in this schema: the check above read nothing"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    test_no_policy_calls_a_helper_once_per_row(dsn)
