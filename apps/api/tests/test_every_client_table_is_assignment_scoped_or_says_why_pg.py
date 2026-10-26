"""Every table with a `client_id` that a signed-in person can reach is assignment-scoped, or is on a list that says why not.

WHY THIS EXISTS
    `test_a_table_the_browser_reads_is_assignment_scoped_pg` holds the rule for the tables the BROWSER reads, and
    `test_a_client_table_a_migration_creates_is_assignment_scoped` for a table a NEW migration creates. The ones in
    between - a `client_id` table that exists, that no screen reads through PostgREST, and that carries a firm policy and
    nothing per client - were left on a stated premise: "nothing reaches them from the browser, and the backend bypasses
    row security". Neither half holds. PostgREST answers for every table `authenticated` is granted whatever the browser
    reads (the anon key and the person's own JWT are all it takes), and the API runs under the caller's sign-in when
    USE_USER_JWT is on, which is the production default. So a Manager assigned to no client could read and change another
    client's rows in those tables with their own sign-in.

    Migration 527 closed the bank's children, 528 eleven more tables and five children, 529 the engagement letters and
    twenty children (the `children` list is empty now), 531 the statutory identity, the payroll settings and the PT
    registrations, and 532 the year locks. This test is the ratchet for the rest: the list in
    `tests/fixtures/assignment_scope_exceptions.json` is exactly the tables that still carry no RESTRICTIVE policy asking
    `my_assigned_client_ids()` / `can_access_client`, with the reason each is not done, and it can only shrink.

    A SECOND POPULATION, FOUND WHILE WRITING 528: the tables WITHOUT a `client_id` that hang from a client table (an
    allocation, a line, a version, a log, a step) and carry a bare firm policy. They name no client of their own, so the
    first rule could not see them, and a person assigned to no client reads the child of a row they cannot read. A child
    is FOLLOWING its parent when, for every command it is granted, either a RESTRICTIVE policy asks the assignment scope
    or reads a client table (a subquery over the parent, read as the caller, so the parent's own scope applies inside it),
    or every PERMISSIVE policy does (or is a personal door such as an employee's own payslips), or no permissive policy
    covers the command at all (a command with no permissive policy is closed). A permissive policy computed from the row,
    the firm and the role alone ADMITS THE WHOLE FIRM, and a role tier is not a scope. The children are found by the
    foreign keys, transitively, and the references of a policy are read from `pg_depend`, not from its text.

    WHAT THE CHILD RULE CANNOT SEE, SAID PLAINLY (the independent review of 528 built each on a throwaway database):
      * it reads what a policy REFERS TO, not what it ADMITS: a policy that mentions a client table in an OR branch that lets
        everyone in, or one that reads `clients` uncorrelated, or one written through `users` and `auth.uid()`, is classified
        as following a client and does not. It is a ratchet against the next careless policy, not a proof, and the
        behavioural half is the data-driven proof of each migration (`test_the_staff_only_client_tables_take_..._pg.py`);
      * it needs a foreign key: a table that names the row it hangs from without one is not in the population unless it is
        named in `NAMED_LINKS` below (`task_tags` and `task_timeline_events` have a `task_id` and no constraint, so they are
        named; `ri_cross_client_signals`, whose `client_ids` array pointed at no table at all, was not, and was dropped by
        migration 538; POST-A-305 lists the third population that would find such tables);
      * it does not read `relrowsecurity` or a policy's roles (no table needs that today).
    A child that follows a client table which ITSELF has no scope is not protected by it, so a policy that reads only tables
    on the `pending` list is flagged (`test_a_child_does_not_borrow_its_scope_from_a_table_that_has_none`).

WHAT THIS HOLDS
    * A table with a `client_id` and a grant to `authenticated` is SCOPED, or is on the list. Scoped means that for EACH
      command `authenticated` is granted (select, insert, update, delete; a column grant counts) a RESTRICTIVE policy
      asks the assignment scope for that command or for ALL. A policy for SELECT alone does not scope a table whose
      writes are granted, which is the shape a looser rule would have waved through.
    * A table on the list that has since gained the scope is removed from it (a stale entry hides the next gap), and a
      table on the list that no longer exists, or no longer reaches `authenticated`, is removed too.
    * A `parent` entry is verified (a policy of the table asks the parent table named), an `own` entry is verified (the
      policy it names exists), and a `pending` entry names the ledger item that closes it. A new table cannot be added as
      'pending' without that.
    * The same for the CHILDREN, on their own list (`children` in the file): a child that hangs from a client table follows
      it or is listed, a listed child that now follows it is removed, and an entry names the ledger item that closes it.
    * The classifier that says whether a child follows its parent is a pure function with its own tests, which run in the
      mock-mode job too; the scan of the real schema runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_HARNESS_PG = os.environ.get("HARNESS_PG")
pg_only = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

EXCEPTIONS = Path(__file__).resolve().parent / "fixtures" / "assignment_scope_exceptions.json"

# Every `client_id` base table the `authenticated` role can reach (a table grant, or a column grant: migration 497 hides
# one column of client_portal_users that way), with whether every command it is granted is covered by a RESTRICTIVE policy
# that asks the assignment scope, and the text of every policy so a `parent` / `own` entry can be checked.
_QUERY = """
SELECT coalesce(json_agg(x ORDER BY x.tbl), '[]'::json) FROM (
  SELECT c.relname::text AS tbl,
         NOT EXISTS (
           SELECT 1 FROM (VALUES ('r', 'SELECT'), ('a', 'INSERT'), ('w', 'UPDATE'), ('d', 'DELETE')) AS k(cmd, priv)
            WHERE (has_table_privilege('authenticated', c.oid, k.priv)
                   OR (k.priv <> 'DELETE' AND has_any_column_privilege('authenticated', c.oid, k.priv)))
              AND NOT EXISTS (SELECT 1 FROM pg_policy p
                               WHERE p.polrelid = c.oid AND NOT p.polpermissive AND p.polcmd IN ('*', k.cmd::"char")
                                 AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '') || ' ' ||
                                      coalesce(pg_get_expr(p.polwithcheck, p.polrelid), ''))
                                     ~ 'my_assigned_client_ids|can_access_client')) AS scoped,
         coalesce((SELECT json_agg(json_build_object('name', p.polname,
                                                     'expr', coalesce(pg_get_expr(p.polqual, p.polrelid), '') || ' ' ||
                                                             coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')))
                     FROM pg_policy p WHERE p.polrelid = c.oid), '[]'::json) AS policies
    FROM pg_class c
   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
     AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attisdropped)
     AND (EXISTS (SELECT 1 FROM information_schema.role_table_grants g
                   WHERE g.table_schema = 'public' AND g.table_name = c.relname AND g.grantee = 'authenticated')
          OR has_any_column_privilege('authenticated', c.oid, 'SELECT, INSERT, UPDATE, REFERENCES'))
) x;
"""

# The CHILDREN: base tables with no `client_id` of their own that hang, directly or through another such table, from a
# table that has one (or from `clients`), and that `authenticated` can reach. `firms` is not a parent: it points at its own
# internal client, and following that arrow reaches every table of the firm. What each policy reads is taken from pg_depend
# (the tables and the functions its expressions refer to), not from its text, so an alias, a line break or a schema prefix
# cannot hide it.
_CHILD_QUERY = """
WITH RECURSIVE named(child, parent) AS (VALUES __NAMED__), keyed AS (
  SELECT c.oid FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
     AND (c.relname = 'clients' OR EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attisdropped))
), kids(oid) AS (
  SELECT c.oid FROM pg_class c JOIN named n ON n.child = c.relname
   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
     AND NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attisdropped)
  UNION
  SELECT c.oid FROM pg_class c JOIN pg_constraint f ON f.conrelid = c.oid AND f.contype = 'f'
   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.relname <> 'firms'
     AND f.confrelid IN (SELECT oid FROM keyed)
     AND NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attisdropped)
  UNION
  SELECT c.oid FROM kids k JOIN pg_constraint f ON f.confrelid = k.oid AND f.contype = 'f' JOIN pg_class c ON c.oid = f.conrelid
   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.oid <> k.oid AND c.relname <> 'firms'
     AND NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'client_id' AND NOT a.attisdropped)
)
SELECT json_build_object(
  'keyed', (SELECT coalesce(json_agg(regexp_replace(oid::regclass::text, '^public\\.', '')), '[]'::json) FROM keyed),
  'children', (SELECT coalesce(json_agg(json_build_object(
      'tbl', c.relname::text,
      'granted', (SELECT coalesce(json_agg(k.cmd), '[]'::json)
                    FROM (VALUES ('r', 'SELECT'), ('a', 'INSERT'), ('w', 'UPDATE'), ('d', 'DELETE')) AS k(cmd, priv)
                   WHERE has_table_privilege('authenticated', c.oid, k.priv)
                      OR (k.priv <> 'DELETE' AND has_any_column_privilege('authenticated', c.oid, k.priv))),
      'parents', (SELECT coalesce(json_agg(DISTINCT x.parent), '[]'::json)
                    FROM (SELECT regexp_replace(f.confrelid::regclass::text, '^public\\.', '') AS parent
                            FROM pg_constraint f WHERE f.conrelid = c.oid AND f.contype = 'f'
                          UNION SELECT n.parent FROM named n WHERE n.child = c.relname) x),
      'policies', (SELECT coalesce(json_agg(json_build_object(
                      'name', p.polname, 'permissive', p.polpermissive, 'cmd', p.polcmd::text,
                      'tables', (SELECT coalesce(json_agg(DISTINCT regexp_replace(d.refobjid::regclass::text, '^public\\.', '')), '[]'::json)
                                   FROM pg_depend d
                                  WHERE d.classid = 'pg_policy'::regclass AND d.objid = p.oid
                                    AND d.refclassid = 'pg_class'::regclass AND d.refobjid <> c.oid),
                      'funcs', (SELECT coalesce(json_agg(DISTINCT q.proname), '[]'::json)
                                  FROM pg_depend d JOIN pg_proc q ON q.oid = d.refobjid
                                 WHERE d.classid = 'pg_policy'::regclass AND d.objid = p.oid AND d.refclassid = 'pg_proc'::regclass))),
                    '[]'::json)
                    FROM pg_policy p WHERE p.polrelid = c.oid)) ORDER BY c.relname), '[]'::json)
     FROM pg_class c
    WHERE c.oid IN (SELECT oid FROM kids)
      AND (has_any_column_privilege('authenticated', c.oid, 'SELECT, INSERT, UPDATE') OR has_table_privilege('authenticated', c.oid, 'DELETE'))));
"""

# A table that names the row it hangs from in a column that carries no foreign key (so the scan above cannot find it): child ->
# parent. Written out by hand on purpose and checked against the schema by `test_a_named_link_is_a_real_child`, so a rename
# is a red test and not a table that quietly leaves the population (POST-A-305).
NAMED_LINKS = {"task_tags": ("tasks", "task_id"), "task_timeline_events": ("tasks", "task_id")}   # child: (parent, the column)

# What a policy may call and still be "computed from the row, the firm and the role alone". Anything else it calls is a
# personal door (an employee's own payslips, a portal contact's own receipts) and narrows the policy to a person.
FIRM_ONLY_FUNCTIONS = frozenset({"get_my_firm_id", "get_my_role", "my_role_at_least", "my_permission"})
SCOPE_FUNCTIONS = frozenset({"my_assigned_client_ids", "can_access_client"})


def _follows_a_client(policy: dict, keyed: frozenset) -> bool:
    """The policy asks the assignment scope, or reads a client table as the caller (so that table's own scope applies)."""
    return bool(set(policy["funcs"]) & SCOPE_FUNCTIONS) or bool(set(policy["tables"]) & keyed)


def _admits_the_whole_firm(policy: dict, keyed: frozenset) -> bool:
    """Computed from the row, the firm and the role alone: every member of the firm (at a tier) passes it for every client.
    A role tier is not a scope, so `my_permission(...)` and `my_role_at_least(...)` do not narrow it."""
    return not _follows_a_client(policy, keyed) and set(policy["funcs"]) <= FIRM_ONLY_FUNCTIONS


def _covers(policy: dict, cmd: str) -> bool:
    return policy["cmd"] in ("*", cmd)


def unscoped_commands(child: dict, keyed: frozenset) -> list[str]:
    """The commands the child is granted to `authenticated` that a member assigned to no client can still use on any client's
    rows: a command is safe when a RESTRICTIVE policy covering it follows a client, or when no PERMISSIVE policy covering it
    admits the whole firm (a command with no permissive policy is closed)."""
    bad = []
    for cmd in child["granted"]:
        if any(not p["permissive"] and _covers(p, cmd) and _follows_a_client(p, keyed) for p in child["policies"]):
            continue
        if any(p["permissive"] and _covers(p, cmd) and _admits_the_whole_firm(p, keyed) for p in child["policies"]):
            bad.append(cmd)
    return bad


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql], capture_output=True, text=True)


@pytest.fixture(scope="module")
def catalog(pg_template):
    admin = _HARNESS_PG.strip()
    name = f"e527c_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        r = _psql(f"{admin} dbname={name}", _QUERY)
        assert r.returncode == 0, r.stderr
        named = ", ".join(f"('{c}', '{p}')" for c, (p, _col) in NAMED_LINKS.items()) or "('', '')"     # an empty VALUES list is a syntax error
        kids = _psql(f"{admin} dbname={name}", _CHILD_QUERY.replace("__NAMED__", named))
        assert kids.returncode == 0, kids.stderr
        child_data = json.loads(kids.stdout)
        return {
            "population": {row["tbl"]: row for row in json.loads(r.stdout)},
            "keyed": frozenset(child_data["keyed"]),
            "children": {c["tbl"]: c for c in child_data["children"]},
        }
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pytest.fixture(scope="module")
def catalog_columns(pg_template):
    admin = _HARNESS_PG.strip()
    names = ", ".join(f"'{c}'" for c in NAMED_LINKS) or "''"
    r = _psql(f"{admin} dbname={pg_template.name}",
              f"SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name IN ({names})")
    assert r.returncode == 0, r.stderr
    out: dict = {}
    for line in r.stdout.splitlines():
        table, _, column = line.partition("|")
        out.setdefault(table, []).append(column)
    return out


@pytest.fixture(scope="module")
def population(catalog):
    return catalog["population"]


@pytest.fixture(scope="module")
def children(catalog):
    return catalog["children"]


@pytest.fixture(scope="module")
def keyed(catalog):
    return catalog["keyed"]


@pytest.fixture(scope="module")
def listed() -> dict:
    return json.loads(EXCEPTIONS.read_text())["tables"]


@pytest.fixture(scope="module")
def listed_children() -> dict:
    return json.loads(EXCEPTIONS.read_text())["children"]


# ── the classifier, in the mock-mode job too ──────────────────────────────────────────────────────────────────────

KEYED = frozenset({"clients", "journal_entries", "payroll_employees"})


def _policy(name, *, permissive=True, cmd="*", tables=(), funcs=()):
    return {"name": name, "permissive": permissive, "cmd": cmd, "tables": list(tables), "funcs": list(funcs)}


def _child(policies, granted=("r", "a", "w", "d")):
    return {"tbl": "child", "granted": list(granted), "parents": ["x"], "policies": policies}


def test_a_bare_firm_policy_admits_the_whole_firm():
    child = _child([_policy("firm", funcs=["get_my_firm_id"])])
    assert unscoped_commands(child, KEYED) == ["r", "a", "w", "d"]


def test_a_role_tier_is_not_a_scope():
    child = _child([_policy("firm", funcs=["get_my_firm_id"]),
                    _policy("tier", permissive=False, cmd="a", funcs=["my_permission"])])
    assert unscoped_commands(child, KEYED) == ["r", "a", "w", "d"]


def test_a_permissive_policy_that_is_only_a_role_tier_still_admits_the_whole_firm():
    """A tier decides WHO at the firm, never WHICH client: a permissive policy built from get_my_firm_id, my_role_at_least
    and my_permission alone lets every member at that tier into every client's rows. (A mutation that counted the tier
    functions as personal doors survived until this was written.)"""
    for funcs in (["get_my_firm_id", "my_role_at_least"], ["my_permission"], ["get_my_firm_id", "get_my_role", "my_permission"]):
        child = _child([_policy("tier", funcs=funcs)])
        assert unscoped_commands(child, KEYED) == ["r", "a", "w", "d"], funcs


def test_a_restrictive_policy_that_reads_the_parent_or_asks_the_scope_closes_the_command_it_covers():
    reads_parent = _policy("parent", permissive=False, tables=["journal_entries"])
    asks_scope = _policy("scope", permissive=False, cmd="r", funcs=["my_assigned_client_ids"])
    firm = _policy("firm", funcs=["get_my_firm_id"])
    assert unscoped_commands(_child([firm, reads_parent]), KEYED) == []
    assert unscoped_commands(_child([firm, asks_scope]), KEYED) == ["a", "w", "d"]


def test_a_permissive_policy_that_reads_a_client_table_follows_it():
    child = _child([_policy("lines", funcs=["get_my_firm_id"], tables=["journal_entries"])])
    assert unscoped_commands(child, KEYED) == []


def test_a_personal_door_is_narrow_but_does_not_cancel_a_bare_firm_policy_beside_it():
    mine = _policy("own", cmd="r", funcs=["my_employee_ids"])
    firm = _policy("firm", funcs=["get_my_firm_id"])
    assert unscoped_commands(_child([mine], granted=("r",)), KEYED) == []
    assert unscoped_commands(_child([mine, firm], granted=("r",)), KEYED) == ["r"]


def test_a_command_with_no_permissive_policy_is_closed_and_an_ungranted_one_is_ignored():
    only_select = _child([_policy("read", cmd="r", funcs=["get_my_firm_id"])])
    assert unscoped_commands(only_select, KEYED) == ["r"]
    assert unscoped_commands(_child([_policy("read", cmd="r", funcs=["get_my_firm_id"])], granted=("r", "w")), KEYED) == ["r"]
    assert unscoped_commands(_child([_policy("read", cmd="r", funcs=["get_my_firm_id"])], granted=("a",)), KEYED) == []


# ── the tables that carry a client_id ─────────────────────────────────────────────────────────────────────────────

@pg_only
def test_the_population_is_not_vacuous(population):
    assert len(population) > 150, f"only {len(population)} tables with a client_id reach authenticated: the scan reads nothing"
    assert sum(1 for t in population.values() if t["scoped"]) > 140


@pg_only
def test_every_client_table_asks_the_assignment_scope_or_is_on_the_list(population, listed):
    gaps = sorted(t for t, row in population.items() if not row["scoped"] and t not in listed)
    assert not gaps, (
        f"{len(gaps)} tables with a client_id carry no RESTRICTIVE policy asking the assignment scope and are not on "
        "tests/fixtures/assignment_scope_exceptions.json. A member of the firm assigned to no client can read and write "
        "them over PostgREST with their own sign-in. Add a `<table>_assignment_scope` policy written as migrations 526 "
        "and 527 write it (COALESCE(client_id::text IS NULL OR (SELECT get_my_role()) = 'Partner' OR client_id::text IN "
        "(SELECT my_assigned_client_ids()), false) in the USING and the WITH CHECK), or say why not in the list: "
        + ", ".join(gaps))


@pg_only
def test_a_table_that_gained_the_scope_or_left_the_schema_is_removed_from_the_list(population, listed):
    stale = sorted(t for t in listed if t not in population)
    assert not stale, f"these listed tables no longer have a client_id or no longer reach authenticated: {stale}"
    gained = sorted(t for t in listed if population[t]["scoped"])
    assert not gained, f"these listed tables now carry the assignment scope; remove them from the list: {gained}"


def _entry_problems(table: str, entry: dict, policies: list) -> list[str]:
    problems: list[str] = []
    kind, why = entry.get("kind"), (entry.get("why") or "").strip()
    if not why:
        problems.append(f"{table}: no reason")
    if kind == "parent":
        via = entry.get("via", "")
        if not any(re.search(rf"\b{re.escape(via)}\b", p["expr"]) for p in policies):
            problems.append(f"{table}: no policy of the table asks its parent {via!r}")
    elif kind == "own":
        if not any(p["name"] == entry.get("policy") for p in policies):
            problems.append(f"{table}: the policy {entry.get('policy')!r} does not exist")
    elif kind == "source":
        if table != "user_client_assignments":
            problems.append(f"{table}: only user_client_assignments is the assignment source")
    elif kind == "pending":
        if not re.fullmatch(r"POST-A-\d+", entry.get("ledger", "")):
            problems.append(f"{table}: a pending entry names the ledger item that closes it")
    else:
        problems.append(f"{table}: unknown kind {kind!r}")
    return problems


@pg_only
def test_every_entry_is_verified_for_the_reason_it_gives(population, listed):
    problems: list[str] = []
    for table, entry in sorted(listed.items()):
        policies = population[table]["policies"] if table in population else []
        problems += _entry_problems(table, entry, policies)
    assert not problems, "\n".join(problems)


def _ledger_text() -> str:
    return "\n".join(p.read_text() for p in (Path(__file__).resolve().parents[3] / "docs" / "open-items").glob("*.md"))


def test_a_pending_entry_names_a_ledger_item_that_exists(listed, listed_children):
    ledger = _ledger_text()
    missing = sorted({e["ledger"] for e in [*listed.values(), *listed_children.values()] if e.get("kind") == "pending"
                      if not re.search(rf"\*\*{re.escape(e['ledger'])}\*\*", ledger)})
    assert not missing, f"the ledger holds no open item {missing}: close the table's entry when the item closes"


# ── the tables that hang from a client table ──────────────────────────────────────────────────────────────────────

@pg_only
def test_the_child_population_is_not_vacuous(children, keyed):
    assert len(children) > 35, f"only {len(children)} child tables found: the scan reads nothing"
    assert len(keyed) > 150
    assert sum(1 for c in children.values() if not unscoped_commands(c, keyed)) > 25, "almost no child follows its parent"
    assert "journal_lines" in children and not unscoped_commands(children["journal_lines"], keyed), (
        "journal_lines follows journal_entries by a subquery; the classifier no longer sees that")


@pg_only
def test_a_named_link_is_a_real_child(children, keyed, catalog_columns):
    """`NAMED_LINKS` is typed by hand, so each entry is checked against the schema three ways: the child carries the column
    named, the parent is a table with a client of its own, and a policy of the child READS that parent (from pg_depend). The
    last is the one that cannot be satisfied by the list itself, which the scan adds to the child's parents whatever it says."""
    for child, (parent, column) in NAMED_LINKS.items():
        assert child in children, f"{child} is named as hanging from {parent} but the scan does not find it as a child"
        assert parent in keyed, f"{child}: {parent} is not a table with a client of its own"
        assert any(parent in policy["tables"] for policy in children[child]["policies"]), (
            f"{child} is named as hanging from {parent} through {column}, and no policy of it reads {parent}")
        assert column in catalog_columns.get(child, []), f"{child} has no column {column}"


@pg_only
def test_every_child_of_a_client_table_follows_it_or_is_on_the_list(children, keyed, listed_children):
    gaps = sorted(t for t, c in children.items() if unscoped_commands(c, keyed) and t not in listed_children)
    assert not gaps, (
        f"{len(gaps)} tables hang from a client table and admit every member of the firm to every client's rows (a bare "
        "firm policy and no restrictive policy that reads the parent or asks the assignment scope). Add "
        "`<table>_parent_visible`, a RESTRICTIVE FOR ALL policy with EXISTS (SELECT 1 FROM <parent> p WHERE p.id = "
        "<table>.<fk>) in the USING and the WITH CHECK, written with its name as a literal, as migrations 527 and 528 "
        "write it, or list it in the `children` of tests/fixtures/assignment_scope_exceptions.json with the ledger item: "
        + ", ".join(gaps))


@pg_only
def test_a_listed_child_that_now_follows_its_parent_or_left_the_schema_is_removed(children, keyed, listed_children):
    stale = sorted(t for t in listed_children if t not in children)
    assert not stale, f"these listed children no longer exist, hang from no client table or are not reachable: {stale}"
    gained = sorted(t for t in listed_children if not unscoped_commands(children[t], keyed))
    assert not gained, f"these listed children now follow their parent; remove them from the list: {gained}"


@pg_only
def test_every_listed_child_is_verified_for_the_reason_it_gives(children, listed_children):
    problems: list[str] = []
    for table, entry in sorted(listed_children.items()):
        if table not in children:
            continue
        policies = [{"name": p["name"], "expr": " ".join(p["tables"] + p["funcs"])} for p in children[table]["policies"]]
        problems += _entry_problems(table, entry, policies)
        if entry.get("kind") == "pending" and not (set(entry.get("parents", [])) & set(children[table]["parents"])):
            problems.append(f"{table}: `parents` {entry.get('parents')} names none of its foreign-key parents {children[table]['parents']}")
    assert not problems, "\n".join(problems)


# The lists are SHRINK-ONLY. The ceilings are the sizes on the day the rule was last lowered: a new gap cannot join a list
# without raising a constant in a diff somebody reads, and closing one lowers the constant in the same commit.
MAX_LISTED_TABLES = 7
MAX_LISTED_CHILDREN = 0


def test_the_lists_only_shrink(listed, listed_children):
    """The ceiling is the size of the list on the day it was last lowered, and the list has to MATCH it: a table cannot join
    (scope it, or raise the constant in a diff somebody reads), and one that leaves lowers the constant in the same commit, so a
    raised constant with nothing behind it fails too."""
    assert len(listed) == MAX_LISTED_TABLES, (
        f"{len(listed)} client tables are listed against a ceiling of {MAX_LISTED_TABLES}: a table cannot join the list, "
        "scope it (a `<table>_assignment_scope` and a `<table>_internal_partner_only` policy), and lower the ceiling when one leaves")
    assert len(listed_children) == MAX_LISTED_CHILDREN, (
        f"{len(listed_children)} children are listed against a ceiling of {MAX_LISTED_CHILDREN}: add `<table>_parent_visible` "
        "instead of listing, and lower the ceiling when one leaves")


@pg_only
def test_a_child_does_not_borrow_its_scope_from_a_table_that_has_none(children, keyed, listed):
    pending = {t for t, entry in listed.items() if entry.get("kind") == "pending"}
    borrowed = []
    for name, child in sorted(children.items()):
        for policy in child["policies"]:
            if set(policy["funcs"]) & SCOPE_FUNCTIONS:
                continue
            reads = set(policy["tables"]) & keyed
            if reads and reads <= pending:
                borrowed.append(f"{name} ({policy['name']}) reads only {sorted(reads)}")
    assert not borrowed, (
        "these policies follow a client table that carries no assignment scope itself (it is pending on the list), so they "
        "protect nothing yet; scope the parent first or in the same migration: " + "; ".join(borrowed))
