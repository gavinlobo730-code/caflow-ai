"""
Migration numbering hygiene (database-free) — Tier 2 R2.6, migration-hygiene half.

apps/api/migrations/ files are named `<number>_<description>.sql` and the
runner (scripts/db/apply_migrations.py) applies them in ascending numeric
order, breaking ties between same-numbered files alphabetically by filename.
That tiebreak is deterministic, but a duplicate number is still a naming bug:
it makes the numbering non-sequential-by-design and relies on an implicit,
easy-to-get-wrong ordering rule instead of the number itself expressing order.

This is a ratchet, not a fix: six duplicate-number pairs already exist in the
repo (discovered during the R2.6 RLS-predicate audit) and are NOT renumbered
here, deliberately — renumbering an already-existing migration is only fully
safe before any live database has tracked it by filename in `schema_migrations`,
and per the R2.6 investigation this project's production Supabase has never
had the migration runner applied to it at all yet (audit: "Not applied to
production"). Renumbering is recommended as a one-time cleanup at that point,
not blind, mid-audit, in this milestone. Until then, this test's job is to make
sure the KNOWN set never silently grows: a new migration reusing an existing
number is exactly the kind of mistake this test exists to catch immediately,
the same day it's introduced — not months later when it's much harder to
disentangle.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

_NUMBER_RE = re.compile(r"^(\d+)_")

# Documented, accepted duplicate-number pairs (file stems, without .sql).
# Verified independently: in every pair, neither file references a table/column
# the other creates — the collision is a naming accident, not a hidden ordering
# dependency. See docs/audits/2026-07-02-executive-product-audit.md, R2.6.
KNOWN_DUPLICATE_NUMBERS: dict[str, set[str]] = {
    "045": {"045_assignment_rules.sql", "045_timeline_foundation.sql"},
    "046": {"046_escalation_rules.sql", "046_health_engine_foundation.sql"},
    "094": {"094_banking_b0_foundation.sql", "094_portal_messages.sql"},
    "095": {"095_bank_feed_foundation.sql", "095_grant_reconciliation.sql"},
    "096": {"096_bank_matching_categorization.sql", "096_service_role_reporting_grants.sql"},
    "097": {"097_bank_posting_engine.sql", "097_invoice_deliveries.sql"},
}


def _migrations_by_number() -> dict[str, set[str]]:
    by_number: dict[str, set[str]] = defaultdict(set)
    for path in MIGRATIONS.glob("*.sql"):
        if path.name.endswith("_rollback.sql"):
            continue
        m = _NUMBER_RE.match(path.name)
        if m:
            by_number[m.group(1)].add(path.name)
    return by_number


def test_no_new_duplicate_migration_numbers():
    duplicates = {num: files for num, files in _migrations_by_number().items() if len(files) > 1}

    unexpected = {
        num: files for num, files in duplicates.items()
        if files != KNOWN_DUPLICATE_NUMBERS.get(num)
    }
    assert not unexpected, (
        "New or changed duplicate migration number(s) found: "
        f"{unexpected}. Give the new migration its own next-available number "
        "instead of reusing one — do not add it to KNOWN_DUPLICATE_NUMBERS."
    )

    now_resolved = {
        num for num, files in KNOWN_DUPLICATE_NUMBERS.items()
        if num not in duplicates or duplicates[num] != files
    }
    assert not now_resolved, (
        f"Duplicate numbers {sorted(now_resolved)} are no longer duplicated — "
        "remove them from KNOWN_DUPLICATE_NUMBERS."
    )
