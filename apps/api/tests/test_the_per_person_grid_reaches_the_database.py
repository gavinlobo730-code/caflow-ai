"""Migration 415's SQL says the same thing `core/permissions.py` says.

G2's last half. Migration 403 made access per person and `rbac()` resolves it;
migration 260's RLS asked the ROLE and nothing else, so a per-person grant
passed the API and was refused by Postgres. 415 puts `public.my_permission`
under those nine policies.

THE SQL DELIBERATELY HOLDS NO VOCABULARY — 403's own comment says a hand-copied
list of (resource, action) pairs in SQL would be a second authority — so what
keeps the two in step is this file, reading the pairs back OUT of the migration
and asserting each against PERMISSIONS. The one list 415 does have to repeat is
the four-pair Partner backstop, and that is pinned here too.

PINNED FROM THE PYTHON SIDE ON PURPOSE. A guard written beside the SQL would
assert the migration against a copy of itself and pass whenever both drifted
together — the Schedule III caption lesson, this codebase's most repeated one.

The behavioural proof that the three states actually resolve is the sibling
`_pg` module; this one runs in the mock-mode job, where there is no database.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.permissions import PERMISSIONS, UNREVOKABLE_FOR_PARTNER, is_known_permission

MIGRATION = (Path(__file__).resolve().parents[1]
             / "migrations" / "415_the_per_person_grid_reaches_the_database.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _policy_table() -> list[tuple[str, str, str, str]]:
    """The `pol` array: (table, resource, insert/update role, delete role)."""
    m = re.search(r"pol text\[\]\[\] := ARRAY\[(.*?)\n  \];", _sql(), re.S)
    assert m, "migration 415's policy array could not be read"
    rows = []
    for line in m.group(1).splitlines():
        cells = re.findall(r"'([^']*)'", line)
        if len(cells) == 4:
            rows.append(tuple(cells))  # type: ignore[arg-type]
    return rows


def test_every_pair_a_policy_names_is_one_permissions_defines():
    """A pair PERMISSIONS does not define resolves closed for EVERYBODY.

    `resolve_permission` treats an unknown pair as inert and falls through to
    `can`, which fails closed — right for a stale ROW, and a locked-out table if
    a POLICY names one. The SQL cannot check this; this is where it is checked.
    """
    for table, resource, _w, _d in _policy_table():
        assert is_known_permission(resource, "write"), (
            f"415 guards {table} with {resource}:write and PERMISSIONS has no "
            f"such pair — every write to that table would be refused")


def test_the_delete_action_falls_back_exactly_where_the_matrix_has_none():
    """260's rule about the ROLE, restated about the PAIR.

    Where a resource defines no `delete`, the policy must ask `write` instead —
    asking for a delete action that does not exist would refuse every delete.
    The migration expresses this as a CASE over four resource names; this
    asserts the split is the one PERMISSIONS actually has.
    """
    m = re.search(r"del_act := CASE WHEN res IN \((.*?)\)", _sql(), re.S)
    assert m, "415's delete-action CASE could not be read"
    has_delete = {r for r in re.findall(r"'([^']*)'", m.group(1))}
    assert has_delete, "the CASE parsed as empty"

    for table, resource, _w, _d in _policy_table():
        expected = is_known_permission(resource, "delete")
        assert (resource in has_delete) is expected, (
            f"{resource} {'has' if expected else 'has no'} a delete action in "
            f"PERMISSIONS but 415 {'lists' if resource in has_delete else 'omits'} "
            f"it — {table}'s DELETE policy asks the wrong one")


def test_the_partner_backstop_is_the_same_four_pairs():
    """The one list 415 has to repeat, pinned to the authority.

    Without it the grid is unrepairable: the only person who could restore
    access is the one whose access was removed, and `team:write` is the only
    thing that can write the table.
    """
    m = re.search(r"\(my_permission\.resource, my_permission\.action\) IN\s*\n\s*\((.*?)\)\s*\n",
                  _sql(), re.S)
    assert m, "415's Partner backstop list could not be read"
    pairs = set(re.findall(r"\('([^']+)','([^']+)'\)", m.group(1)))
    assert pairs == set(UNREVOKABLE_FOR_PARTNER), (
        f"415's Partner backstop and UNREVOKABLE_FOR_PARTNER disagree: "
        f"only-in-SQL {sorted(pairs - set(UNREVOKABLE_FOR_PARTNER))}, "
        f"only-in-Python {sorted(set(UNREVOKABLE_FOR_PARTNER) - pairs)}")


def test_the_role_minimums_are_260s_own_and_unchanged():
    """415 re-points the predicate and moves no table's tier.

    That is what makes it safe to merge: with an empty `user_permissions` —
    403 wrote no backfill — it reproduces today's behaviour exactly.
    """
    before = (Path(__file__).resolve().parents[1]
              / "migrations" / "260_role_aware_write_policies.sql").read_text(encoding="utf-8")
    m = re.search(r"pol\s+text\[\]\[\] := ARRAY\[(.*?)\n  \];", before, re.S)
    assert m, "migration 260's policy array could not be read"
    old: dict[str, tuple[str, str]] = {}
    for line in m.group(1).splitlines():
        cells = re.findall(r"'([^']*)'", line)
        if len(cells) == 3:
            old[cells[0]] = (cells[1], cells[2])
    assert len(old) == 9, f"parsed {len(old)} tables from 260, expected 9"

    new = {t: (w, d) for t, _res, w, d in _policy_table()}
    assert new == old, (
        "415 changed a table's minimum ROLE. It is only meant to change the "
        f"PREDICATE: {sorted(k for k in new if new[k] != old.get(k))}")


def test_the_no_row_branch_calls_the_one_hierarchy():
    """It must not restate the role ladder.

    `role_rank` carries the legacy aliases — owner, admin, article, staff,
    viewer — and a second ladder in 415 would drop them for these nine tables
    only.
    """
    sql = _sql()
    assert "RETURN public.my_role_at_least(minimum_role);" in sql, (
        "415's no-row branch no longer defers to my_role_at_least")
    # The only place a rank is compared directly is the Partner backstop, which
    # asks a specific role rather than the policy's own minimum.
    ranks = re.findall(r"role_rank\(('[^']*'|[\w.]+\(\))\)", sql)
    assert set(ranks) == {"public.get_my_role()", "'Partner'"}, (
        f"415 compares role ranks somewhere new: {sorted(set(ranks))}")


def test_these_guards_are_not_vacuous():
    """Each parser, on the thing it parses, from this file.

    Four guards in this repository's history went quietly inert by parsing
    nothing and asserting over an empty set.
    """
    table = _policy_table()
    assert len(table) == 9, f"the policy array parsed as {len(table)} rows"
    assert ("fee_engagements", "billing", "Partner", "Partner") in table
    assert ("tasks", "task", "Executive", "Manager") in table

    assert len(UNREVOKABLE_FOR_PARTNER) == 4, "the backstop list changed size"
    assert ("team", "write") in UNREVOKABLE_FOR_PARTNER

    assert is_known_permission("client", "delete"), "PERMISSIONS moved under the delete test"
    for r in ("accounting", "mca", "firm", "billing"):
        assert not is_known_permission(r, "delete"), (
            f"{r} gained a delete action — 415's CASE needs it")
    assert set(PERMISSIONS) >= {"billing", "client", "task", "document", "firm"}


# ── migration 524: a client's bank lines ask banking:read, at PERMISSIONS' own floor ─────────────────────────────

MIGRATION_524 = next((Path(__file__).resolve().parents[1] / "migrations")
                     .glob("524_the_database_asks_the_banking_tier_*_read.sql"))
ROLLBACK_524 = next((Path(__file__).resolve().parents[1] / "migrations")
                    .glob("524_the_database_asks_the_banking_tier_*_read_rollback.sql"))


def _floor(resource: str, action: str) -> str:
    """The lowest role PERMISSIONS lets do `resource:action`: the minimum a policy must name."""
    from core.permissions import ROLE_HIERARCHY
    allowed = PERMISSIONS[resource][action]
    return next(r.value for r in ROLE_HIERARCHY if r in allowed)


def _524_policies() -> list[tuple[str, str]]:
    """(table, the floor the policy names) for every policy 524 creates."""
    sql = MIGRATION_524.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'CREATE POLICY "([a-z_]+)" ON public\.([a-z_]+)\s+'
                         r"AS RESTRICTIVE FOR SELECT TO authenticated\s+"
                         r"USING \(\(SELECT public\.my_permission\('([a-z]+)', '([a-z]+)', '([A-Za-z]+)'\)\)\);", sql):
        _name, table, resource, action, floor = m.groups()
        assert (resource, action) == ("banking", "read"), (table, resource, action)
        out.append((table, floor))
    return out


def test_524_names_banking_read_at_the_floor_permissions_gives_it():
    """The floor the policies name is the one `rbac("banking", "read")` resolves a role through, so a per-person
    yes or no and the role fallback mean the same thing at the route and at the table."""
    assert is_known_permission("banking", "read")
    floor = _floor("banking", "read")
    assert floor == "Executive", f"PERMISSIONS moved banking:read's floor to {floor}: the policies of 524 must follow"
    policies = _524_policies()
    assert {f for _t, f in policies} == {floor}, policies


def test_524_wraps_the_call_so_it_is_asked_once_per_query_and_not_once_per_row():
    """The spelling that makes the rule true on a table of 100,000 lines (61 s against 6 s, measured); the plan-level
    proof is in the real-Postgres sibling. Every call in the migration is inside `(SELECT ...)`."""
    sql = MIGRATION_524.read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    calls = len(re.findall(r"my_permission\(", code))
    wrapped = len(re.findall(r"\(SELECT public\.my_permission\(", code))
    assert calls == wrapped == 6, (calls, wrapped)


def test_524_covers_six_tables_and_its_rollback_drops_exactly_those_policies():
    sql = MIGRATION_524.read_text(encoding="utf-8")
    created = set(re.findall(r'CREATE POLICY "([a-z_]+)"', sql))
    dropped_by_rollback = set(re.findall(r'DROP POLICY IF EXISTS "([a-z_]+)"', ROLLBACK_524.read_text(encoding="utf-8")))
    assert len(created) == 6 and created == dropped_by_rollback, (created, dropped_by_rollback)
    assert {t for t, _f in _524_policies()} == {
        "bank_transactions", "bank_statements", "bank_transaction_splits",
        "bank_reconciliations", "bank_reconciliation_matches", "bank_matching_rules"}
    # the closing check counts what the migration creates
    assert "IF n <> 6 THEN" in sql
    # bank_accounts is left out on purpose (the payment pickers read it); a policy there would be a decision
    assert "bank_accounts" not in re.findall(r"ON public\.([a-z_]+)", sql)
