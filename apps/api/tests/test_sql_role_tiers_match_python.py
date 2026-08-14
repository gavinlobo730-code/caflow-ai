"""
Migration 260's role tiers must equal the ones in core/permissions.py.

Migration 260 states each table's minimum role as a literal — 'Manager' for
chart_of_accounts, 'Partner' for fee_invoices. Those came from reading the
rbac() guard on the endpoint that writes the same table, but once written down
in SQL they are a SECOND copy of the matrix, and a second copy drifts. If
accounting:write is later opened to Executive, the API changes and the database
silently stays stricter — the browser path keeps refusing writes the API allows,
which surfaces as an intermittent, unexplainable failure on one screen.

So the migration is parsed and compared, rather than trusted. This runs in the
ordinary test job (no PostgreSQL needed) so it guards every change, not only the
ones that reach the migrations CI job.

It deliberately does NOT check the table→resource mapping — that mapping is a
judgement about which endpoint owns which table, argued in the migration's own
comments and unverifiable from here. What it checks is that, given the resource,
the tier is right.
"""
import re
from pathlib import Path

import pytest

from core.permissions import PERMISSIONS, ROLE_HIERARCHY, Role

MIGRATIONS = [
    Path(__file__).resolve().parents[1] / "migrations" / "260_role_aware_write_policies.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "261_role_aware_write_policies_part2.sql",
]

# table -> (resource, write_action, delete_action_or_None)
#
# `None` for delete means the resource has no `delete` action in the matrix, so
# the migration reuses the write tier — removing a row is at least as privileged
# as changing one. That choice is asserted below rather than assumed.
OWNERS = {
    "chart_of_accounts": ("accounting", "write", None),
    "clients":           ("client",     "write", "delete"),
    "customers":         ("client",     "write", "delete"),
    "tasks":             ("task",       "write", "delete"),
    "documents":         ("document",   "write", "delete"),
    "fee_invoices":      ("billing",    "write", None),
    "fee_engagements":   ("billing",    "write", None),
    "mca_filings":       ("mca",        "write", None),
    "firms":             ("firm",       "write", None),
    # Added by migration 261. Where a resource has no `write` action, the column
    # names the action standing in for it, and the migration's header argues why.
    "attendance":             ("payroll",    "write",   None),
    "leave_balances":         ("payroll",    "write",   None),
    "compliance_calendar":    ("compliance", "write",   "delete"),
    "it_notices":             ("income_tax", "compute", "approve"),
    "tax_audits":             ("income_tax", "compute", "approve"),
    "tax_planning_records":   ("income_tax", "compute", "approve"),
    "shared_reports":         ("report",     "write",   None),
    "scheduled_reports":      ("report",     "write",   None),
    "client_documents":       ("document",   "write",   "delete"),
    "document_requests":      ("portal",     "write",   None),
    "suppliers":              ("accounting", "write",   None),
    "msme_payments":          ("accounting", "write",   None),
    "client_timeline_events": ("timeline",   "write",   "delete"),
}


def _declared() -> dict[str, tuple[str, str]]:
    """table -> (min_role_for_write, min_role_for_delete), read out of the SQL."""
    src = "\n".join(m.read_text(encoding="utf-8") for m in MIGRATIONS)
    rows = re.findall(
        r"\[\s*'([a-z_]+)'\s*,\s*'([A-Za-z]+)'\s*,\s*'([A-Za-z]+)'\s*\]", src)
    return {t: (w, d) for t, w, d in rows}


def _minimum_role(resource: str, action: str) -> str:
    """The least-privileged role holding resource:action."""
    allowed = PERMISSIONS[resource][action]
    return min(allowed, key=lambda r: ROLE_HIERARCHY.index(r)).value


def test_the_migration_was_parsed_at_all():
    """Vacuity guard: if the array's formatting changes, every comparison below
    would iterate an empty dict and pass."""
    declared = _declared()

    assert len(declared) == len(OWNERS), (
        f"parsed {sorted(declared)} from the migration but expected {sorted(OWNERS)} — "
        "the policy array's shape probably changed"
    )


@pytest.mark.parametrize("table", sorted(OWNERS))
def test_write_tier_matches_the_matrix(table):
    resource, write_action, _ = OWNERS[table]
    declared_write, _ = _declared()[table]

    assert declared_write == _minimum_role(resource, write_action), (
        f"migration 260 requires {declared_write!r} to write {table}, but "
        f"{resource}:{write_action} admits {_minimum_role(resource, write_action)} and up"
    )


@pytest.mark.parametrize("table", sorted(OWNERS))
def test_delete_tier_matches_the_matrix_or_falls_back_to_write(table):
    resource, write_action, delete_action = OWNERS[table]
    _, declared_delete = _declared()[table]

    if delete_action is None:
        assert "delete" not in PERMISSIONS[resource], (
            f"{resource} now HAS a delete action — the migration is still using "
            f"the {write_action} tier for deleting {table}"
        )
        expected = _minimum_role(resource, write_action)
    else:
        expected = _minimum_role(resource, delete_action)

    assert declared_delete == expected


@pytest.mark.parametrize("table", sorted(OWNERS))
def test_deleting_is_never_easier_than_writing(table):
    """Independent of the matrix: whatever the tiers say, a role that cannot
    change a row must not be able to remove it."""
    write, delete = _declared()[table]
    rank = {r.value: i for i, r in enumerate(ROLE_HIERARCHY)}

    assert rank[delete] >= rank[write], f"{table}: delete ({delete}) below write ({write})"


@pytest.mark.parametrize("table", sorted(OWNERS))
def test_each_guarded_permission_is_a_hierarchy_tier(table):
    """`my_role_at_least(X)` can only express "X and everyone above". If a
    permission is ever granted to a non-contiguous set — document:approve is
    already {Partner, Manager, Reviewer}, skipping Executive — then no minimum
    role describes it, and a policy pretending otherwise would quietly grant or
    deny the wrong people.
    """
    resource, write_action, delete_action = OWNERS[table]

    for action in (write_action, delete_action):
        if action is None:
            continue
        allowed = PERMISSIONS[resource][action]
        lowest = min(ROLE_HIERARCHY.index(r) for r in allowed)
        tier = set(ROLE_HIERARCHY[lowest:])
        assert allowed == tier, (
            f"{resource}:{action} is {sorted(r.value for r in allowed)}, which is not "
            f"'{ROLE_HIERARCHY[lowest].value} and above' — migration 260 cannot express it"
        )


def test_the_sql_legacy_role_map_matches_python():
    """role_rank() normalises owner/admin/article/staff/viewer for the same
    reason LEGACY_ROLE_MAP exists. Held in step here so a change to one is a
    failing test rather than a Partner locked out of their own firm."""
    from core.permissions import LEGACY_ROLE_MAP

    src = MIGRATIONS[0].read_text(encoding="utf-8")
    ranks = dict(re.findall(r"WHEN '([a-z]+)'\s+THEN (-?\d+)", src))

    for legacy, canonical in LEGACY_ROLE_MAP.items():
        assert legacy in ranks, f"role_rank() does not handle the legacy role {legacy!r}"
        assert ranks[legacy] == ranks[canonical.value.lower()], (
            f"role_rank({legacy!r}) does not match role_rank({canonical.value!r}); "
            f"LEGACY_ROLE_MAP maps them together"
        )


def test_every_canonical_role_is_ranked():
    src = MIGRATIONS[0].read_text(encoding="utf-8")
    ranks = dict(re.findall(r"WHEN '([a-z]+)'\s+THEN (-?\d+)", src))

    for role in Role:
        assert role.value.lower() in ranks, f"role_rank() does not handle {role.value}"

    # And the ranking must agree with ROLE_HIERARCHY's order, not merely exist.
    ordered = sorted((int(ranks[r.value.lower()]), r.value) for r in Role)
    assert [name for _, name in ordered] == [r.value for r in ROLE_HIERARCHY]
