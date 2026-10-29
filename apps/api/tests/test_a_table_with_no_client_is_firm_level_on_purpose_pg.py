"""Every table with NO client at all that a signed-in person can reach is on a reviewed list, says what kind of table it is, and
has its writes held by a tier or by the person's own row (POST-A-305).

WHY THIS EXISTS
    `test_every_client_table_is_assignment_scoped_or_says_why_pg` holds the tables that carry a `client_id` (the first
    population) and the tables that hang from one by a foreign key (the second). A table in NEITHER was invisible to it:
    no client column, no path to a client table, so nothing asserted that it is firm-wide ON PURPOSE. Two reviews found
    that shape by hand (the independent review of migration 528 found `ri_cross_client_signals`, `ri_entities` and
    `ri_entity_relationships` with a bare firm policy and writes for every member; migration 562 found seventeen firm-level
    tables whose writes every member held), and each was a finding and not a red test.

    This is the THIRD population: every public base table that `authenticated` can reach (a table grant or a column grant)
    that has no `client_id` and no foreign-key path to a table that has one (the same scan the second population uses,
    NAMED_LINKS included). It is the firm's own records, the reference data every firm shares, and the rows that belong to a
    person.

WHAT THIS HOLDS
    * A table of that shape is on `tests/fixtures/firm_level_tables.json`, with a category and a reason. A new table of the
      shape is a red test and not a finding, and a listed table that left the shape (it gained a client, lost its grant,
      was dropped) is a red test too, so a stale entry cannot hide the next gap.
    * The CATEGORY is verified against the table's own policies, so a reason cannot claim what the policies do not say:
      `reference` (no firm column, no policy asks a firm or reads another table: every firm sees the same rows),
      `parent` (no firm column; a policy reads the row it hangs from), `scoped` (a policy asks the assignment scope),
      `personal` (a policy covering SELECT asks who the person is), `tiered` (a policy covering SELECT asks a role or a
      permission) and `firm_wide` (a permissive policy covering SELECT asks the firm, and nothing covering SELECT narrows it
      by tier, person or client: every member of the firm reads it, and that is the point).
    * The WRITES recorded for a table (a = insert, w = update, d = delete) are EXACTLY what `authenticated` is granted, so a
      table that gains a write is a red test until somebody who reads the diff changes the fixture.
    * Every write a table is granted is HELD by a tier, a permission or the person's own row: for each granted command either
      a RESTRICTIVE policy covering it asks `get_my_role`, `my_role_at_least`, `my_permission`, `auth.uid()` or
      `get_my_user_id`, or every PERMISSIVE policy covering it does, or no permissive policy covers it at all (the command is
      closed). A bare firm policy beside a granted write is the shape migration 562 found seventeen times.

WHAT THIS CANNOT SEE, SAID PLAINLY
    * It reads what a policy REFERS TO (from `pg_depend`), not what it ADMITS: a policy that names `my_role_at_least` with the
      lowest floor is a tier by this rule. The floor is a decision, and the real-Postgres matrix test
      (`test_rls_actor_by_table_matrix_pg`) is the proof of what each role can do.
    * A category is checked against the policies, not against the data: `entities` holds a date of birth and a PAN and is
      read by every member of the firm. Whether it should be is the open question POST-A-357, and this file
      records that the list was reviewed, not that the decision is right.
    * It sees tables, not views and not functions.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from tests.test_every_client_table_is_assignment_scoped_or_says_why_pg import NAMED_LINKS, SCOPE_FUNCTIONS, _psql

_HARNESS_PG = os.environ.get("HARNESS_PG")
pg_only = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "firm_level_tables.json"

CATEGORIES = ("reference", "parent", "scoped", "personal", "tiered", "firm_wide")
FIRM_FUNCTIONS = frozenset({"get_my_firm_id"})
TIER_FUNCTIONS = frozenset({"get_my_role", "my_role_at_least", "my_permission"})
PERSON_FUNCTIONS = frozenset({"uid", "get_my_user_id"})      # `uid` is auth.uid()
GUARD_FUNCTIONS = TIER_FUNCTIONS | PERSON_FUNCTIONS
WRITE_COMMANDS = ("a", "w", "d")

# The base tables `authenticated` can reach that have no client_id and no foreign-key path to a table that has one. The
# recursion is the one `test_every_client_table_is_assignment_scoped_or_says_why_pg._CHILD_QUERY` uses to find the second
# population, so the two cannot disagree about where the second ends and this begins. A policy's references are read from
# pg_depend (the tables and the functions its expressions refer to), not from its text.
_QUERY = """
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
SELECT coalesce(json_agg(json_build_object(
  'tbl', c.relname::text,
  'has_firm', EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'firm_id' AND NOT a.attisdropped),
  'granted', (SELECT coalesce(json_agg(k.cmd), '[]'::json)
                FROM (VALUES ('r', 'SELECT'), ('a', 'INSERT'), ('w', 'UPDATE'), ('d', 'DELETE')) AS k(cmd, priv)
               WHERE has_table_privilege('authenticated', c.oid, k.priv)
                  OR (k.priv <> 'DELETE' AND has_any_column_privilege('authenticated', c.oid, k.priv))),
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
 WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
   AND c.oid NOT IN (SELECT oid FROM keyed) AND c.oid NOT IN (SELECT oid FROM kids)
   AND (has_any_column_privilege('authenticated', c.oid, 'SELECT, INSERT, UPDATE') OR has_table_privilege('authenticated', c.oid, 'DELETE'));
"""


# ── the rules, as pure functions, so the mock-mode job tests them too ─────────────────────────────────────────────────

def _covers(policy: dict, cmd: str) -> bool:
    return policy["cmd"] in ("*", cmd)


def _asks(policy: dict, functions: frozenset) -> bool:
    return bool(set(policy["funcs"]) & functions)


def unguarded_writes(table: dict) -> list[str]:
    """The write commands the table is granted that are held by nothing narrower than the firm. A command is safe when a
    RESTRICTIVE policy covering it asks a tier, a permission or the person (a restrictive policy narrows every permissive one
    beside it), or when every PERMISSIVE policy covering it does (permissive policies are OR-ed, so ONE bare firm policy
    among them admits the whole firm), or when no permissive policy covers it at all (a command with no permissive policy is
    closed whatever else is granted)."""
    bad = []
    for cmd in WRITE_COMMANDS:
        if cmd not in table["granted"]:
            continue
        covering = [p for p in table["policies"] if _covers(p, cmd)]
        if any(not p["permissive"] and _asks(p, GUARD_FUNCTIONS) for p in covering):
            continue
        permissive = [p for p in covering if p["permissive"]]
        if not permissive or all(_asks(p, GUARD_FUNCTIONS) for p in permissive):
            continue
        bad.append(cmd)
    return bad


def category_problem(table: dict, category: str) -> str | None:
    """Why the table is not what its listed category says, or None."""
    reading = [p for p in table["policies"] if _covers(p, "r")]
    if category == "reference":
        if table["has_firm"]:
            return "it has a firm column, so it is not the same rows for every firm"
        if any(_asks(p, FIRM_FUNCTIONS) or p["tables"] for p in table["policies"]):
            return "a policy of it asks a firm or reads another table"
    elif category == "parent":
        if table["has_firm"]:
            return "it has a firm column of its own, so it does not hang from a parent"
        if not any(p["tables"] for p in table["policies"]):
            return "no policy of it reads the row it hangs from"
    elif category == "scoped":
        if not any(_asks(p, SCOPE_FUNCTIONS) for p in table["policies"]):
            return "no policy of it asks the assignment scope"
    elif category == "personal":
        if not any(_asks(p, PERSON_FUNCTIONS) for p in reading):
            return "no policy covering SELECT asks who the person is"
    elif category == "tiered":
        if not any(_asks(p, TIER_FUNCTIONS) for p in reading):
            return "no policy covering SELECT asks a role or a permission"
    elif category == "firm_wide":
        if not any(p["permissive"] and _asks(p, FIRM_FUNCTIONS) for p in reading):
            return "no permissive policy covering SELECT asks the firm"
        narrowed = [p["name"] for p in reading if _asks(p, TIER_FUNCTIONS | PERSON_FUNCTIONS | SCOPE_FUNCTIONS)]
        if narrowed:
            return f"a policy covering SELECT narrows it by tier, person or client ({', '.join(narrowed)}), so it is not read by every member"
    else:
        return f"unknown category {category!r}"
    return None


def _policy(name, *, permissive=True, cmd="*", tables=(), funcs=()):
    return {"name": name, "permissive": permissive, "cmd": cmd, "tables": list(tables), "funcs": list(funcs)}


def _table(policies, granted=("r",), has_firm=True):
    return {"tbl": "t", "has_firm": has_firm, "granted": list(granted), "policies": policies}


def test_a_bare_firm_policy_beside_a_granted_write_is_unguarded():
    """The shape migration 562 found seventeen times."""
    t = _table([_policy("firm", funcs=["get_my_firm_id"])], granted=("r", "a", "w", "d"))
    assert unguarded_writes(t) == ["a", "w", "d"]


def test_a_restrictive_tier_holds_the_command_it_covers_and_only_that_one():
    firm = _policy("firm", funcs=["get_my_firm_id"])
    t = _table([firm, _policy("tier", permissive=False, cmd="a", funcs=["my_role_at_least"])], granted=("r", "a", "w"))
    assert unguarded_writes(t) == ["w"]


def test_one_bare_permissive_policy_among_guarded_ones_admits_the_whole_firm():
    guarded = _policy("owner", cmd="w", funcs=["uid"])
    bare = _policy("firm", cmd="w", funcs=["get_my_firm_id"])
    assert unguarded_writes(_table([guarded], granted=("w",))) == []
    assert unguarded_writes(_table([guarded, bare], granted=("w",))) == ["w"]


def test_a_command_no_permissive_policy_covers_is_closed_and_an_ungranted_one_is_ignored():
    assert unguarded_writes(_table([_policy("read", cmd="r", funcs=["get_my_firm_id"])], granted=("r", "a"))) == []
    firm = _policy("firm", funcs=["get_my_firm_id"])
    assert unguarded_writes(_table([firm], granted=("r",))) == []


def test_a_restrictive_policy_that_asks_nothing_about_the_person_holds_nothing():
    t = _table([_policy("firm", funcs=["get_my_firm_id"]),
                _policy("shape", permissive=False, cmd="*", funcs=["is_system_row"])], granted=("a",))
    assert unguarded_writes(t) == ["a"]


def test_each_category_is_refused_a_table_that_is_not_that_kind():
    firm_read = _policy("firm", funcs=["get_my_firm_id"], cmd="r")
    tier_read = _policy("tier", funcs=["get_my_firm_id", "get_my_role"], cmd="r")
    own_read = _policy("own", permissive=False, funcs=["uid"], cmd="r")
    through_parent = _policy("via", tables=["tasks"], funcs=["get_my_firm_id"], cmd="*")
    scoped = _policy("scope", permissive=False, funcs=["my_assigned_client_ids"], cmd="*")
    everyone = _policy("all", cmd="r")

    assert category_problem(_table([everyone], has_firm=False), "reference") is None
    assert category_problem(_table([firm_read], has_firm=False), "reference")            # asks a firm
    assert category_problem(_table([everyone], has_firm=True), "reference")              # a firm column
    assert category_problem(_table([through_parent], has_firm=False), "parent") is None
    assert category_problem(_table([firm_read], has_firm=False), "parent")               # reads no parent
    assert category_problem(_table([through_parent], has_firm=True), "parent")           # has a firm column
    assert category_problem(_table([firm_read, scoped]), "scoped") is None
    assert category_problem(_table([firm_read]), "scoped")
    assert category_problem(_table([firm_read, own_read]), "personal") is None
    assert category_problem(_table([firm_read]), "personal")
    assert category_problem(_table([tier_read]), "tiered") is None
    assert category_problem(_table([firm_read]), "tiered")
    assert category_problem(_table([firm_read]), "firm_wide") is None
    assert category_problem(_table([everyone]), "firm_wide")                             # no firm asked
    assert category_problem(_table([tier_read]), "firm_wide")                            # a tier narrows it
    assert category_problem(_table([firm_read, own_read]), "firm_wide")                  # a person narrows it
    assert category_problem(_table([firm_read]), "no_such_kind")


def test_a_write_policy_does_not_narrow_a_firm_wide_read():
    """`firms` and `dtaa_treaty_rates` are read by every member and written at a tier; the tier is on the write commands."""
    t = _table([_policy("firm", funcs=["get_my_firm_id"]),
                _policy("w", permissive=False, cmd="w", funcs=["my_permission"])], granted=("r", "w"))
    assert category_problem(t, "firm_wide") is None
    assert unguarded_writes(t) == []


# ── the fixture, in the mock-mode job too ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def listed() -> dict:
    return json.loads(FIXTURE.read_text())["tables"]


def test_every_entry_has_a_known_category_a_writes_string_and_a_reason(listed):
    problems = []
    for name, entry in sorted(listed.items()):
        if entry.get("category") not in CATEGORIES:
            problems.append(f"{name}: unknown category {entry.get('category')!r}")
        writes = entry.get("writes")
        if not isinstance(writes, str) or writes != "".join(c for c in "awd" if c in writes):
            problems.append(f"{name}: `writes` is a string of a, w and d in that order, not {writes!r}")
        if len((entry.get("why") or "").strip()) < 40:
            problems.append(f"{name}: a reason that says why this table is firm-level on purpose")
    assert not problems, "\n".join(problems)


def test_a_table_with_a_client_is_not_in_this_list(listed):
    """The first two populations own these; a name here would be a table that was already scoped elsewhere."""
    assert not {"clients", "journal_entries", "journal_lines", "chart_of_accounts", "purchase_bills"} & set(listed)


# ── the schema ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def population(pg_template):
    admin = _HARNESS_PG.strip()
    name = f"e305_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    try:
        named = ", ".join(f"('{c}', '{p}')" for c, (p, _col) in NAMED_LINKS.items()) or "('', '')"
        r = _psql(f"{admin} dbname={name}", _QUERY.replace("__NAMED__", named))
        assert r.returncode == 0, r.stderr
        return {row["tbl"]: row for row in json.loads(r.stdout)}
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


@pg_only
def test_the_population_is_not_vacuous(population):
    assert len(population) > 30, f"only {len(population)} tables with no client reach authenticated: the scan reads nothing"
    assert {"firms", "users", "audit_log", "currencies"} <= set(population)
    assert not {"clients", "journal_entries", "journal_lines"} & set(population)


@pg_only
def test_every_table_with_no_client_is_on_the_list(population, listed):
    gaps = sorted(t for t in population if t not in listed)
    assert not gaps, (
        f"{len(gaps)} tables have no client and no path to one, are reachable by a signed-in person and are not on "
        "tests/fixtures/firm_level_tables.json. Say what kind of table each is and why it is firm-level on purpose (a "
        "category, the write commands the signed-in role holds, and a reason), or give it a client_id and the assignment "
        "scope: " + ", ".join(gaps))


@pg_only
def test_a_listed_table_that_left_the_shape_is_removed(population, listed):
    stale = sorted(t for t in listed if t not in population)
    assert not stale, (
        f"these listed tables no longer exist, gained a client (or a path to one) or no longer reach authenticated; remove "
        f"them from the list: {stale}")


@pg_only
def test_the_category_is_true_of_the_table(population, listed):
    problems = []
    for name, entry in sorted(listed.items()):
        if name in population:
            why_not = category_problem(population[name], entry["category"])
            if why_not:
                problems.append(f"{name} is listed as {entry['category']}, but {why_not}")
    assert not problems, "\n".join(problems)


@pg_only
def test_the_writes_recorded_are_the_writes_granted(population, listed):
    problems = []
    for name, entry in sorted(listed.items()):
        if name in population:
            granted = "".join(c for c in "awd" if c in population[name]["granted"])
            if granted != entry["writes"]:
                problems.append(f"{name}: the fixture records writes {entry['writes']!r} and the signed-in role holds {granted!r}")
    assert not problems, (
        "a write granted or taken away changes who can change a firm-wide table over PostgREST; read the change and edit "
        "the fixture in the same diff:\n" + "\n".join(problems))


@pg_only
def test_every_write_a_signed_in_person_holds_on_a_table_with_no_client_is_held_by_a_tier_or_their_own_row(population):
    problems = [f"{name}: {unguarded_writes(table)} granted to authenticated with no tier, permission or own-row policy holding them"
                for name, table in sorted(population.items()) if unguarded_writes(table)]
    assert not problems, (
        "a member who may only read can write these over PostgREST with their own sign-in. Either take the write away "
        "(REVOKE INSERT, UPDATE, DELETE ... FROM authenticated, as migration 562 does, after the API writes the table with the "
        "privileged client), or add a RESTRICTIVE policy asking my_permission(...) or my_role_at_least(...) for the command:\n"
        + "\n".join(problems))
