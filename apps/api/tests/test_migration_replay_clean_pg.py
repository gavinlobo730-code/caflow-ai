"""
The migration set must replay onto an EMPTY database with zero failures.

This is the invariant nobody was asserting. Individual *_pg.py tests each check
that *their* migration is not in `pg_template.failed`, which is a useful ratchet
per feature — but it means a migration nobody wrote a test for can fail forever
and CI stays green. The runner is invoked with --continue-on-error (deliberately:
one run should surface EVERY failure, not stop at the first), and its non-zero
exit code is swallowed by the harness. So the only thing that can make a broken
replay visible is an assertion on the report itself.

Why this matters beyond tidiness: a migration set that cannot build itself from
scratch cannot provision a new environment, cannot be used for disaster
recovery, and makes "apply the pending migrations" unsafe against any database
whose state you have not personally verified. It also means the schema CI tests
against is not the schema production runs — they drift silently, in both
directions, and every test written against the CI schema is testing a shape no
deployment has.

--continue-on-error is intentionally KEPT. Removing it would stop the run at the
first failure and hide the rest; the fix is to assert on the full report, which
is what this does.
"""
import pytest


# Migrations that still cannot apply to an empty database. This list may only
# ever SHRINK — a new entry means someone shipped a migration that cannot be
# replayed, which is exactly the class of defect this file exists to stop.
#
# Every one has the same root cause: the file names an object that a LATER
# migration creates, or that no migration creates at all because it was added
# by hand in production. They have never applied cleanly; they only ever "worked"
# against a database that already happened to have the object.
STILL_FAILING = {
    # FK to task_recurring_configs, which migration 063 creates — 18 files later.
    "045_assignment_rules.sql",
    # RLS policy over purchase_bill_lines.purchase_bill_id.
    "053_hardening.sql",
    # Seeds chart_of_accounts.is_system; no migration adds that column.
    "054_v13_payroll_assets_banking.sql",
    # More bank_transactions.bank_account_id references (the 094/095 bank-feed
    # foundation adds that column later). One was fixed; others remain.
    "055_v131_hardening.sql",
    # More GRANTs over tables later migrations create (pending_invites, ...).
    "095_grant_reconciliation.sql",
    # ALTER FUNCTION over prevent_snapshot_mutation(), which no migration creates.
    "144_security_search_path_and_rls.sql",
}


def test_migration_replay_failures_only_ever_shrink(pg_template):
    """The ratchet. New failures are forbidden; fixing one means deleting it
    from STILL_FAILING, which is why the set can only get smaller."""
    failed = set(pg_template.failed)

    regressions = sorted(failed - STILL_FAILING)
    assert not regressions, (
        f"{len(regressions)} migration(s) newly fail to apply to an empty "
        f"database:\n  " + "\n  ".join(regressions) +
        "\n\nA migration must be replayable from scratch. Fix it rather than "
        "adding it to STILL_FAILING."
    )

    fixed = sorted(STILL_FAILING - failed)
    assert not fixed, (
        f"these migrations now apply cleanly: {fixed}\nRemove them from "
        "STILL_FAILING so the ratchet tightens."
    )


def test_the_replay_actually_applied_a_realistic_number_of_migrations(pg_template):
    """Guard against the assertion above passing vacuously.

    If the runner ever fails to discover migrations (bad glob, wrong directory,
    a refactor of migration_files()), `failed` would be empty and the test above
    would pass while nothing had been applied at all. Pin a floor that tracks
    the real count loosely.
    """
    applied = pg_template.report.get("applied", [])

    assert len(applied) >= 250, (
        f"only {len(applied)} migrations applied — the replay looks vacuous, "
        "which would make the zero-failures assertion meaningless."
    )


def test_no_rollback_file_is_mistaken_for_a_forward_migration(pg_template):
    """migrations/ contains *_rollback.sql operational scripts alongside the
    forward timeline, and the runner globs every numbered .sql — so each
    rollback runs immediately after the migration it undoes.

    Empirically this is survivable today (a full replay still produces a
    working schema, because later files re-establish what the rollbacks drop),
    which is why this is an assertion about the OUTCOME rather than about the
    file list: it pins the objects whose loss would be catastrophic and silent.
    If a future rollback edit starts actually removing one of these, this fails
    instead of shipping a schema missing its authorization primitives.
    """
    missing = _missing_functions(pg_template)

    assert not missing, (
        f"rollback files removed authorization primitives that nothing "
        f"re-created: {sorted(missing)}"
    )


_REQUIRED_FUNCTIONS = ("can_access_client", "get_my_role", "provision_internal_client")


def _missing_functions(pg_template) -> set:
    """Which of the load-bearing functions are absent from the replayed schema.

    Empty today; non-empty means a rollback file started actually biting.
    can_access_client is the client-assignment primitive every audited router
    depends on, so its silent removal is the worst case this guards.
    """
    import os
    import subprocess

    names = "','".join(_REQUIRED_FUNCTIONS)
    check = (
        "SELECT string_agg(p.proname, ',') FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        f"WHERE n.nspname = 'public' AND p.proname IN ('{names}')"
    )
    r = subprocess.run(
        ["psql", f"{os.environ.get('HARNESS_PG', '')} dbname={pg_template.name}",
         "-tA", "-X", "-q", "-c", check],
        capture_output=True, text=True,
    )
    present = set((r.stdout or "").strip().split(",")) - {""}
    return set(_REQUIRED_FUNCTIONS) - present
