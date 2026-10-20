"""The assignment scope reads the caller's clients once per query, not once per row (migration 526).

WHAT WAS WRONG
    Policies on tables with a `client_id` (the RESTRICTIVE `<table>_assignment_scope` policy of migration 084 on the tables
    that got it, and the per-command and portal-composite policies later migrations wrote) call `can_access_client((client_id)::text)`:
    a Partner sees every client, anyone else the clients they are assigned to. The function is a SECURITY DEFINER SQL
    function with a `SET search_path`, so Postgres cannot inline it, and it takes the ROW's client, so it cannot be hoisted
    out of the row. Each call runs `get_my_role()`, `get_my_user_id()` and, for anyone but a Partner, an `EXISTS` on
    `user_client_assignments`. Measured on 100,000 rows as a signed-in session: 13,232 ms for a Partner and 33,818 ms for a
    Manager, against 12 to 30 ms and 51 ms for the equivalent set-based expression, which returned the same rows.

WHAT THIS HOLDS
    * THE RULE: after the migrations no policy in `public` calls `can_access_client`; a policy a later migration writes with
      it fails here and its author uses the set-based form (or the helper `my_assigned_client_ids()`).
    * THE PLAN: a signed-in scan of a client-keyed table, as a person who is not a Partner, carries the caller's clients as a
      HASHED sub-plan built from `my_assigned_client_ids()` and never the function inside a Filter.
    * THE SAME PREDICATE, over every SHAPE a policy takes and every kind of person. Eight synthetic policies are written
      with the OLD call, each on a table of its own (restrictive policies AND together, so on one shared table the first
      would hide what the others do): FOR ALL with the same USING and WITH CHECK (the real 084 shape), SELECT alone, SELECT
      with a portal-style OR branch, INSERT alone, UPDATE with a USING that differs from its WITH CHECK, DELETE alone, an
      EXISTS over `clients` on a qualified column, a column that is not `client_id`, and two calls in one expression. Six
      people try every operation on rows of client A, client B and no client: a Partner, a Manager assigned to client A, a
      Manager assigned to nothing, an Executive assigned to client A, a SUSPENDED Partner and a Partner of ANOTHER firm.
      The migration is applied; every person gets the same answer to every operation on every table. A shape that every
      firm member answers alike for the operation it governs fails the test, because it could not tell a wrong rewrite apart.
    * THE DRIFT GUARD DOES NOT SEE IT: the guard snapshot hashes every policy after folding the new shape back to the call,
      so the hashes of all the policies are identical with the migration applied and with it rolled back (the production
      snapshot holds the call; the comparison with that snapshot is `test_guards_match_production_pg`).
    * THE ROLLBACK returns the raw text of every policy it rewrote, and re-applying the migration gives the same text again.

Simulates an authenticated PostgREST session the way `_supabase_compat_bootstrap.sql`'s auth.uid() shim expects.
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
MIGRATIONS = API_ROOT / "migrations"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the assignment-scope proof requires HARNESS_PG + psql",
)

FIRM = "52600000-0000-0000-0000-000000000001"
OTHER_FIRM = "52600000-0000-0000-0000-000000000002"
CLIENT_A = "52600000-0000-0000-0000-0000000000a1"
CLIENT_B = "52600000-0000-0000-0000-0000000000b2"
PEOPLE = {            # name: (users.id, auth id, role)
    "partner": ("52600000-0000-0000-0000-00000000000a", "52600000-1111-0000-0000-000000000001", "Partner"),
    "manager_a": ("52600000-0000-0000-0000-00000000000b", "52600000-1111-0000-0000-000000000002", "Manager"),
    "manager_none": ("52600000-0000-0000-0000-00000000000c", "52600000-1111-0000-0000-000000000003", "Manager"),
    "executive_a": ("52600000-0000-0000-0000-00000000000e", "52600000-1111-0000-0000-000000000004", "Executive"),
    "suspended": ("52600000-0000-0000-0000-00000000000f", "52600000-1111-0000-0000-000000000005", "Partner"),
    "other_firm": ("52600000-0000-0000-0000-000000000010", "52600000-1111-0000-0000-000000000006", "Partner"),
}
FIRM_MEMBERS = ("partner", "manager_a", "manager_none", "executive_a")

MIGRATION = next(p for p in MIGRATIONS.glob("526_the_assignment_scope_reads_the_callers_clients_once_per_query*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("526_the_assignment_scope_reads_the_callers_clients_once_per_query*_rollback.sql"))


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _psql_file(dsn: str, path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def _as(who: str) -> str:
    return f"SET request.jwt.claims = '{{\"sub\": \"{PEOPLE[who][1]}\", \"role\": \"authenticated\"}}'; SET ROLE authenticated; "


def _lines_as(dsn: str, who: str, sql: str) -> list[str]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _as(who) + sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.strip() for line in r.stdout.splitlines() if line.strip() and line.strip() != "SET"]


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e526_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        auth = ", ".join(f"('{a}', '{n}@t.in')" for n, (_i, a, _r) in PEOPLE.items())
        members = ", ".join(
            f"('{i}', '{OTHER_FIRM if n == 'other_firm' else FIRM}', '{a}', '{n}@t.in', '{n}', '{r}', {'false' if n == 'suspended' else 'true'})"
            for n, (i, a, r) in PEOPLE.items())
        seed = _psql(d, f"""
            INSERT INTO auth.users (id, email) VALUES {auth};
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in'), ('{OTHER_FIRM}', 'G', 'g@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES {members};
            INSERT INTO user_client_assignments (firm_id, user_id, client_id)
                 VALUES ('{FIRM}', '{PEOPLE["manager_a"][0]}', '{CLIENT_A}'),
                        ('{FIRM}', '{PEOPLE["executive_a"][0]}', '{CLIENT_A}');
        """)
        assert seed.returncode == 0, seed.stderr
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _folded(column: str) -> str:
    """A policy expression as one line (a deparsed CASE or EXISTS can run over several)."""
    return f"regexp_replace(coalesce(pg_get_expr(p.{column}, p.polrelid), ''), '\\s+', ' ', 'g')"


# ── THE RULE ────────────────────────────────────────────────────────────────────

def test_no_policy_in_public_calls_can_access_client_once_per_row(dsn):
    offenders = [r[0] for r in _rows(dsn, f"""
        SELECT c.relname || '.' || p.polname
          FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND ({_folded('polqual')} ~ 'can_access_client' OR {_folded('polwithcheck')} ~ 'can_access_client')
         ORDER BY 1""")]
    assert not offenders, (
        f"{len(offenders)} policies call can_access_client once per row (13 s per 100,000 rows as a Partner); use the "
        f"set-based form migration 526 writes, or my_assigned_client_ids(): {offenders[:10]}")


def test_the_rule_is_not_vacuous_many_policies_read_the_callers_clients_as_a_set(dsn):
    got = _rows(dsn, f"""SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                          WHERE n.nspname = 'public' AND {_folded('polqual')} ~ 'my_assigned_client_ids'""")
    assert int(got[0][0]) > 150, f"only {got[0][0]} policies use the caller's clients as a set: the migration did not run or the scan reads nothing"


def test_the_helper_answers_the_callers_clients_and_nothing_for_anyone_else(dsn):
    assert _lines_as(dsn, "manager_a", "SELECT public.my_assigned_client_ids();") == [CLIENT_A]
    assert _lines_as(dsn, "executive_a", "SELECT public.my_assigned_client_ids();") == [CLIENT_A]
    assert _lines_as(dsn, "manager_none", "SELECT public.my_assigned_client_ids();") == []
    assert _lines_as(dsn, "partner", "SELECT public.my_assigned_client_ids();") == [], "a Partner is not assigned; their reach comes from the role"
    assert _lines_as(dsn, "suspended", "SELECT public.my_assigned_client_ids();") == [], "a member who is no longer live has no clients"
    assert _lines_as(dsn, "other_firm", "SELECT public.my_assigned_client_ids();") == []


def test_anon_can_call_the_helper_and_it_answers_nothing(dsn):
    """It is an RLS predicate helper, in the class migration 337 left executable on purpose: the policies it sits in have no
    TO clause, so anon evaluates them, and a role without EXECUTE gets an error out of a quiet denial."""
    r = subprocess.run(["psql", dsn, "-X", "-tA", "-c", "SET ROLE anon; SELECT count(*) FROM public.my_assigned_client_ids();"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1].strip() == "0"


def test_an_anonymous_read_of_a_table_anon_may_select_is_never_a_permission_error_out_of_the_assignment_scope(dsn):
    """Supabase's default privileges give anon a table privilege on public tables, and 44 of them answered an anonymous
    count with 0 rows before this migration. A first draft revoked the helper from anon and every one of them answered
    `permission denied for function my_assigned_client_ids` instead. The scan grants SELECT inside a transaction it rolls
    back, so it changes nothing."""
    script = """
        BEGIN;
        DO $$ DECLARE r record; BEGIN
          FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r' LOOP
            EXECUTE format('GRANT SELECT ON public.%I TO anon', r.relname);
          END LOOP;
        END $$;
        SET ROLE anon;
        DO $$ DECLARE r record; n bigint; ok int := 0; denied text := ''; BEGIN
          FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r' LOOP
            BEGIN
              EXECUTE format('SELECT count(*) FROM public.%I', r.relname) INTO n;
              ok := ok + 1;
            EXCEPTION WHEN insufficient_privilege THEN
              IF SQLERRM ~ 'my_assigned_client_ids|can_access_client' THEN denied := denied || r.relname || ' '; END IF;
            END;
          END LOOP;
          RAISE NOTICE 'answered=%', ok;
          RAISE NOTICE 'denied=%', denied;
        END $$;
        ROLLBACK;
    """
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", script], capture_output=True, text=True)
    got = dict(re.findall(r"NOTICE:\s+(\w+)=(.*)", r.stderr))
    assert "answered" in got, r.stderr[-500:]
    assert int(got["answered"]) > 150, f"only {got['answered']} tables answered an anonymous count: the scan reads nothing"
    assert got["denied"].strip() == "", f"an anonymous read is a permission error out of the assignment scope on: {got['denied']}"


# ── THE PLAN ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["journal_entries", "client_sales_invoices", "receipts", "purchase_bills", "tasks"])
def test_a_signed_in_scan_builds_the_callers_clients_once(dsn, table):
    plan = _lines_as(dsn, "manager_a", f"EXPLAIN (VERBOSE, COSTS OFF) SELECT count(*) FROM {table};")
    joined = "\n".join(plan)
    assert "can_access_client" not in joined, f"{table}'s plan calls can_access_client:\n{joined}"
    # the caller's clients are a HASHED sub-plan (built once, probed per row) that reads my_assigned_client_ids() ...
    filters = [line for line in plan if "Filter:" in line or "Index Cond:" in line]
    hashed = {m.group(1) for line in filters for m in re.finditer(r"hashed SubPlan (\d+)", line)}
    assert hashed, f"{table}'s plan has no hashed sub-plan in a Filter:\n{joined}"
    assert any(re.search(rf"^\s*SubPlan {n}\s*$", joined, re.M)
               and re.search(rf"^\s*SubPlan {n}\s*\n(?:.*\n)*?.*my_assigned_client_ids\(\)", joined + "\n", re.M)
               for n in hashed), f"no hashed sub-plan of {table} reads my_assigned_client_ids():\n{joined}"
    # ... and no sub-plan in a Filter is anything else (a correlated or un-hashed one would run per row)
    for line in filters:
        assert not re.search(r"(?<!hashed )SubPlan \d+", line), f"{table}'s Filter carries a sub-plan that is not hashed:\n{joined}"


# ── THE SAME PREDICATE, OVER EVERY SHAPE AND EVERY KIND OF PERSON ───────────────

_OLD = "can_access_client((client_id)::text)"
_ALL_OPS = ("select", "insert", "update", "move", "delete")

#: Synthetic policies written with the OLD call, each on a table of its own.
#: (name, kind, command, using, with check, the operations the shape governs)
_SHAPES = [
    ("scope_all", "RESTRICTIVE", "ALL", _OLD, _OLD, _ALL_OPS),
    ("select_only", "RESTRICTIVE", "SELECT", _OLD, None, ("select",)),
    ("portal_or", "RESTRICTIVE", "SELECT", f"{_OLD} OR n >= 100", None, ("select",)),
    ("insert_check", "RESTRICTIVE", "INSERT", None, _OLD, ("insert",)),
    ("update_split", "RESTRICTIVE", "UPDATE", _OLD, "can_access_client((other_client)::text)", ("update", "move")),
    ("delete_only", "RESTRICTIVE", "DELETE", _OLD, None, ("delete",)),
    ("exists_form", "RESTRICTIVE", "SELECT",
     "EXISTS (SELECT 1 FROM public.clients c WHERE c.id = \"Shape exists_form\".client_id AND can_access_client((c.id)::text))"
     " OR \"Shape exists_form\".client_id IS NULL", None, ("select",)),
    ("other_column", "RESTRICTIVE", "SELECT", "can_access_client((other_client)::text)", None, ("select",)),
    ("two_calls", "RESTRICTIVE", "SELECT", f"{_OLD} AND can_access_client((other_client)::text)", None, ("select",)),
]

#: (n, client, other_client). other_client equals client_id for n 1, 2, 5, 6 and is the OTHER client for 3, 4, 7, 8, so a
#: rewrite that read the wrong column, or built a WITH CHECK from the USING, changes an answer. Row 100 is the portal row.
_ROWS = [
    (1, CLIENT_A, CLIENT_A), (2, CLIENT_A, CLIENT_A), (3, CLIENT_A, CLIENT_B), (4, CLIENT_A, CLIENT_B),
    (5, CLIENT_B, CLIENT_B), (6, CLIENT_B, CLIENT_B), (7, CLIENT_B, CLIENT_A), (8, CLIENT_B, CLIENT_A),
    (9, None, None), (10, None, None), (100, CLIENT_B, CLIENT_B),
]


def _tbl(name: str) -> str:
    return f'public."Shape {name}"'


def _lit(v: str | None) -> str:
    return "NULL" if v is None else f"'{v}'"


def _build_shapes(dsn: str) -> None:
    values = ", ".join(f"('{FIRM}', {_lit(c)}, {_lit(o)}, {n})" for n, c, o in _ROWS)
    stmts: list[str] = []
    for name, kind, command, using, check, _ops in _SHAPES:
        t = _tbl(name)
        stmts += [
            f"CREATE TABLE {t} (id serial PRIMARY KEY, firm_id uuid NOT NULL, client_id uuid, other_client uuid, n int NOT NULL);",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO authenticated;",
            f'GRANT USAGE ON SEQUENCE public."Shape {name}_id_seq" TO authenticated;',
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;",
            f'CREATE POLICY "firm {name}" ON {t} AS PERMISSIVE FOR ALL TO authenticated '
            f"USING (firm_id = (SELECT get_my_firm_id())) WITH CHECK (firm_id = (SELECT get_my_firm_id()));",
            f"INSERT INTO {t} (firm_id, client_id, other_client, n) VALUES {values};",
        ]
        clause = f'CREATE POLICY "shape {name}" ON {t} AS {kind} FOR {command} TO authenticated'
        if using:
            clause += f" USING ({using})"
        if check:
            clause += f" WITH CHECK ({check})"
        stmts.append(clause + ";")
    done = _psql(dsn, "\n".join(stmts))
    assert done.returncode == 0, done.stderr


def _is_old(dsn: str, policy_name: str) -> bool:
    got = _rows(dsn, f"""SELECT count(*) FROM pg_policy p WHERE p.polname = '{policy_name}'
                          AND ({_folded('polqual')} ~ 'can_access_client' OR {_folded('polwithcheck')} ~ 'can_access_client')""")
    return int(got[0][0]) == 1


def _count_op(tag: str, dml: str) -> str:
    """Run one statement, report its row count (or `err` when the database refuses it), and undo it."""
    return (f"DO $$ DECLARE c bigint; BEGIN BEGIN {dml}; GET DIAGNOSTICS c = ROW_COUNT; RAISE NOTICE '{tag}=%', c; "
            f"RAISE EXCEPTION 'undo' USING ERRCODE = 'P0001'; "
            f"EXCEPTION WHEN SQLSTATE 'P0001' THEN NULL; WHEN OTHERS THEN RAISE NOTICE '{tag}=err'; END; END $$;")


def _outcomes_as(dsn: str, who: str, name: str) -> dict:
    """What `who` gets from every operation on the shape's table, in one session."""
    t = _tbl(name)
    parts = [_as(who),
             f"DO $$ DECLARE s text; BEGIN SELECT coalesce(string_agg(n::text, ',' ORDER BY n), '-') INTO s FROM {t}; "
             f"RAISE NOTICE 'select=%', s; END $$;"]
    for k in (1, 3, 5, 7, 9):              # client A / A with other B / client B / B with other A / no client
        parts.append(_count_op(f"update{k}", f"UPDATE {t} SET n = n WHERE n = {k}"))
    for k in (1, 5):                        # moving a row to client B: the new row meets the WITH CHECK
        parts.append(_count_op(f"move{k}", f"UPDATE {t} SET client_id = '{CLIENT_B}', other_client = '{CLIENT_B}' WHERE n = {k}"))
    for label, c in (("A", _lit(CLIENT_A)), ("B", _lit(CLIENT_B)), ("none", "NULL")):
        parts.append(_count_op(f"insert{label}", f"INSERT INTO {t} (firm_id, client_id, other_client, n) VALUES ('{FIRM}', {c}, {c}, 99)"))
    for k in (1, 5, 9):
        parts.append(_count_op(f"delete{k}", f"DELETE FROM {t} WHERE n = {k}"))
    r = subprocess.run(["psql", dsn, "-X", "-q", "-c", " ".join(parts)], capture_output=True, text=True)
    got = dict(re.findall(r"NOTICE:\s+(\w+)=(.*)", r.stderr))
    assert "select" in got, f"{who} on {name}: {r.stderr[-400:]}"
    return got


def _all_outcomes(dsn: str) -> dict:
    return {(name, who): _outcomes_as(dsn, who, name) for name, *_ in _SHAPES for who in PEOPLE}


def _operation_keys(op: str) -> list[str]:
    return {"select": ["select"], "update": [f"update{k}" for k in (1, 3, 5, 7, 9)], "move": ["move1", "move5"],
            "insert": ["insertA", "insertB", "insertnone"], "delete": ["delete1", "delete5", "delete9"]}[op]


def _snapshot(dsn: str) -> list:
    return _rows(dsn, f"SELECT p.polname, {_folded('polqual')}, {_folded('polwithcheck')} FROM pg_policy p ORDER BY 1")


def test_every_shape_is_the_same_predicate_for_every_kind_of_person(dsn):
    _build_shapes(dsn)
    before = _all_outcomes(dsn)

    # the premises, so the comparison below can fail: for every shape, on each operation it governs, the people who are
    # members of the firm do not all get the same answer to at least one of the rows tried (a row with no client is
    # open to everyone, as the function had it, so not every row can tell people apart)
    for name, _kind, _command, _using, _check, ops in _SHAPES:
        for op in ops:
            tells_apart = [key for key in _operation_keys(op) if len({before[(name, who)][key] for who in FIRM_MEMBERS}) > 1]
            assert tells_apart, f"{name}: {op} gives every member of the firm the same answer to every row tried, so it cannot tell a wrong rewrite apart"
    for name, *_ in _SHAPES:
        assert _is_old(dsn, f"shape {name}"), f"premise: the {name} policy does not call can_access_client"

    first = _psql_file(dsn, MIGRATION)
    assert first.returncode == 0, first.stderr
    for name, *_ in _SHAPES:
        assert not _is_old(dsn, f"shape {name}"), f"the {name} policy still calls can_access_client"

    after = _all_outcomes(dsn)
    changed = sorted(k for k in before if before[k] != after[k])
    assert not changed, "the rewrite changed what someone can see, insert, update or delete: " + "; ".join(
        f"{n}/{who}: " + ", ".join(f"{key} {before[(n, who)][key]}->{after[(n, who)][key]}" for key in before[(n, who)] if before[(n, who)][key] != after[(n, who)][key])
        for n, who in changed[:4])

    snapshot = _snapshot(dsn)
    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _snapshot(dsn) == snapshot, "a second run of the migration changed a policy"


def test_the_rollback_returns_every_shape_to_the_same_answers_too(dsn):
    _build_shapes(dsn)
    before = _all_outcomes(dsn)
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _psql_file(dsn, ROLLBACK).returncode == 0
    for name, *_ in _SHAPES:
        assert _is_old(dsn, f"shape {name}"), f"the rollback did not put the call back in the {name} policy"
    assert _all_outcomes(dsn) == before, "the rolled-back policies answer differently from the originals"
    assert _psql_file(dsn, MIGRATION).returncode == 0
    assert _all_outcomes(dsn) == before, "re-applying the migration after the rollback changed an answer"


def test_a_row_with_no_client_is_visible_to_everyone_in_the_firm_as_the_function_had_it(dsn):
    _build_shapes(dsn)
    assert _psql_file(dsn, MIGRATION).returncode == 0
    for who in FIRM_MEMBERS:
        seen = _outcomes_as(dsn, who, "select_only")["select"].split(",")
        assert "9" in seen and "10" in seen, (who, seen)
    for who in ("suspended", "other_firm"):
        assert _outcomes_as(dsn, who, "select_only")["select"] == "-", f"{who} sees rows of the firm"


# ── THE DRIFT GUARD DOES NOT SEE IT, AND THE ROLLBACK IS EXACT ──────────────────

def _guard_hashes(dsn: str) -> dict:
    from scripts.db.guard_snapshot import normalise, snapshot_via_psql
    return {k: v["expr_md5"] for k, v in normalise(snapshot_via_psql(dsn))["policy"].items()}


def _raw_policies(dsn: str) -> list:
    return _rows(dsn, f"SELECT c.relname, p.polname, {_folded('polqual')}, {_folded('polwithcheck')} FROM pg_policy p "
                      "JOIN pg_class c ON c.oid = p.polrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                      "WHERE n.nspname = 'public' ORDER BY 1, 2")


def test_the_drift_guard_hashes_every_policy_the_same_migrated_and_rolled_back_and_the_rollback_restores_the_text(dsn):
    after = _guard_hashes(dsn)
    raw_after = _raw_policies(dsn)
    assert len(after) > 1000, "the guard snapshot read almost no policy"

    rolled = _psql_file(dsn, ROLLBACK)
    assert rolled.returncode == 0, rolled.stderr
    before = _guard_hashes(dsn)
    assert before == after, (
        "the guard snapshot sees the rewrite as drift in: "
        f"{sorted(k for k in before if before[k] != after.get(k))[:8]}")
    raw_before = _raw_policies(dsn)
    assert raw_before != raw_after, "premise: the rollback did not change any policy text"
    assert any("can_access_client" in r[2] for r in raw_before), "the rollback did not return the call"
    assert not _rows(dsn, "SELECT 1 FROM pg_proc WHERE proname = 'my_assigned_client_ids'"), "the rollback left the helper behind"

    again = _psql_file(dsn, MIGRATION)
    assert again.returncode == 0, again.stderr
    assert _raw_policies(dsn) == raw_after, "re-applying the migration after the rollback did not give the same policies"
