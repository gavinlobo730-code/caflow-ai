"""Migration 525, its rollback and the guard snapshot's fold name the same helpers (mock-mode companion of the _pg module).

The wrap (525), the unwrap (its rollback) and the fold that keeps a wrapped policy from reading as drift from production
(`scripts/db/guard_snapshot.GUARD_SQL`) are three regular expressions over one list of helper functions. If one gains a
helper and the others do not, a policy is wrapped that the snapshot cannot fold back (a false drift report), or unwrapped
that was never wrapped. This holds the three lists equal, and holds each to the helpers that really are constant-argument
STABLE session readers.
"""
import re
from pathlib import Path

from scripts.db.guard_snapshot import GUARD_SQL

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION = next(p for p in MIGRATIONS.glob("525_a_policy_asks_who_is_calling_once_per_query_*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next(MIGRATIONS.glob("525_a_policy_asks_who_is_calling_once_per_query_*_rollback.sql"))

HELPERS = {"get_my_firm_id", "get_my_role", "get_my_user_id", "my_internal_client_id", "my_permission", "my_role_at_least"}


def _list(text: str) -> set[str]:
    found = re.search(r"\(\?:((?:get_my_firm_id|get_my_role)[^)]*)\)", text)
    assert found, "no helper list found"
    return set(found.group(1).split("|"))


def test_the_three_lists_are_the_same_list():
    assert _list(MIGRATION.read_text()) == HELPERS
    assert _list(ROLLBACK.read_text()) == HELPERS
    assert _list(GUARD_SQL) == HELPERS


def test_the_migration_wraps_only_a_call_that_is_not_already_wrapped_and_only_with_constant_arguments():
    sql = MIGRATION.read_text()
    assert "(?<!SELECT )" in sql, "a second run would wrap a call twice"
    assert r"\([^()]*\)" in sql, "an argument list that can hold a column or a nested call would be hoisted out of its row"
    assert "can_access_client" not in "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--")), (
        "can_access_client takes the row's client: it cannot be wrapped this way")


def test_the_migration_checks_its_own_work_and_reads_only_the_public_schema():
    code = "\n".join(l for l in MIGRATION.read_text().splitlines() if not l.lstrip().startswith("--"))
    assert "RAISE EXCEPTION" in code
    assert "ns.nspname = 'public'" in code, "the storage schema's policies belong to the Storage service"
    assert "ALTER POLICY" in code and "DROP POLICY" not in code and "CREATE POLICY" not in code, (
        "a rewrite that drops and recreates a policy opens a window with none; ALTER POLICY does not")
