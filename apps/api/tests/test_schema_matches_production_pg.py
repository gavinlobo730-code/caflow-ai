"""
The migrations must not call a column optional that production requires.

WHY THIS DIRECTION AND NO OTHER

Of every way the migrations and the live database can disagree, one has
actually cost this product a working feature:

    a column that is NOT NULL with no default in production, and merely
    nullable in the migrations.

Code written from the migrations omits it. Every check in this repository
passes, because the CI template is built FROM the migrations. Every insert is
rejected in production. Nothing surfaces it.

That is not hypothetical. An audit read migration 052, concluded
form_26as_uploads.uploaded_by did not exist, and deleted the code that wrote it.
The column exists in production, is NOT NULL, has no default — so every 26AS
upload failed there, silently, while the whole suite stayed green. The audit was
careful. It read the wrong source, and no check could tell it so.

This is that check. Migration 292 closed the 35 columns the first run found;
this stops the set growing back.

AND, SINCE MIGRATION 293, THAT NO COLUMN'S TYPE DISAGREES

The seventeen type differences 293 closed were a milder fault than the
nullability one — none of them rejects an insert outright — but two of them
could still have produced a wrong answer rather than an error:
tally_migration_jobs.source_file_size_bytes was integer in production and
bigint here, so a Tally export over 2.1 GB overflowed there and passed here;
the uuid-vs-text columns accepted a non-uuid string on one side and not the
other. That set is at zero now, so it is cheap to hold there, and a type
difference is always a bug in one of the two places.

A THIRD DIRECTION, ASSERTED SINCE MIGRATION 294

An earlier version of this docstring said the remaining categories "cannot
reject an insert, so none of them is a build failure". That was wrong about one
of them, and the error cost four working features.

columns_missing_from_live — a column the MIGRATIONS declare and production does
not have — rejects the insert every time code writes to it. It is the exact
mirror of the category above, and just as fatal:

    year_end_adjustments.client_id            routers/year_end_adjustments.py:201
    financial_statement_versions.statement_data   routers/year_end_statements.py:149
    account_group_mappings.statement_type/account_name
                                              routers/year_end_mappings.py:348-349
    filings.firm_id                           services/gst_filing_record_service.py

All four failed in production while this suite stayed green. The last is the
worst: public.filings is what journal_period_lock_reason reads (266, 267), so a
row that never gets written is a period that never locks, and entries stay
editable after the return covering them is filed.

Migration 294 added all 31 that are real, and the snapshot below was refreshed
against production once it applied, so the set is now asserted. The 32nd,
clients_external.is_test, is excluded on principle rather than by name:
clients_external is a VIEW on both sides, its two definitions select different
columns, and nothing inserts into it. The exclusion is derived by asking the
database which relations are views, so a table can never fall through it.

WHAT IT STILL DELIBERATELY DOES NOT ASSERT

Tables present on one side only, and the safe nullability direction. Those are
real drift worth knowing about, but a table the other side lacks breaks no
write, and nullability in the safe direction accepts more than it must rather
than less. Asserting on everything would make this a permanent triple-figure
complaint that somebody turns off.

THE FIXTURE IS A SNAPSHOT

tests/fixtures/production_schema_2026-08-31.json is what production looked like
on one day, so this can run in CI without production credentials. It goes stale
by design; see that directory's README for how to refresh it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "production_schema_2026-08-31.json"

_spec = importlib.util.spec_from_file_location(
    "schema_drift", _ROOT / "scripts" / "db" / "schema_drift.py")
schema_drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(schema_drift)

_snap_spec = importlib.util.spec_from_file_location(
    "schema_snapshot", _ROOT / "scripts" / "db" / "schema_snapshot.py")
schema_snapshot = importlib.util.module_from_spec(_snap_spec)
_snap_spec.loader.exec_module(schema_snapshot)

_HARNESS_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(
    not _HARNESS_PG or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")


def _declared_snapshot(template_name: str) -> dict:
    """Introspect a clone of the migration-built template.

    The SAME query as the fixture was captured with — schema_snapshot's
    INTROSPECT_SQL — because two sides introspected differently would diff the
    questions rather than the schemas.
    """
    admin = _HARNESS_PG.strip()
    name = f"caflow_drift_{uuid.uuid4().hex[:12]}"
    subprocess.run(["psql", f"{admin} dbname=postgres", "-v", "ON_ERROR_STOP=1",
                    "-X", "-q", "-c", f'CREATE DATABASE "{name}" TEMPLATE "{template_name}";'],
                   capture_output=True, text=True, check=True)
    try:
        return schema_snapshot.normalise(
            schema_snapshot.snapshot_via_psql(f"{admin} dbname={name}"))
    finally:
        subprocess.run(["psql", f"{admin} dbname=postgres", "-X", "-q", "-c",
                        f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);'],
                       capture_output=True, text=True)


def _columns_added_after_the_snapshot() -> set:
    """Column names mentioned by migrations newer than the fixture's high-water
    mark — the ones production has not been given yet.

    Deliberately coarse: any identifier appearing in those files counts. The
    alternative is parsing SQL, and being over-generous here costs only that a
    genuinely-drifted column sharing a name with an in-flight one goes
    unreported for one release, while being under-generous fails every PR that
    adds a column. The set is small — only unmerged migrations — so the
    over-generosity is bounded by what is actually in flight.
    """
    meta_path = _FIXTURE.with_suffix(".meta.json")
    if not meta_path.exists():
        return set()
    through = json.loads(meta_path.read_text(encoding="utf-8"))["applied_through_migration"]
    names: set = set()
    for sql in sorted((_ROOT / "migrations").glob("*.sql")):
        head = sql.name.split("_", 1)[0]
        if not head.isdigit() or int(head) <= through:
            continue
        names |= set(re.findall(r"[a-z_][a-z0-9_]*", sql.read_text(encoding="utf-8").lower()))
    return names


def _view_names(template_name: str) -> set:
    """Relations in the template that are views, not base tables."""
    admin = _HARNESS_PG.strip()
    out = subprocess.run(
        ["psql", f"{admin} dbname={template_name}", "-X", "-tA", "-c",
         "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
         "WHERE n.nspname='public' AND c.relkind IN ('v','m');"],
        capture_output=True, text=True, check=True)
    return set(out.stdout.split())


@pytest.fixture(scope="module")
def report(pg_template):
    declared = _declared_snapshot(pg_template.name)
    live = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return schema_drift.diff(declared, live)


# ── The assertion ─────────────────────────────────────────────────────────────

@_NEEDS_PG
def test_no_column_is_required_in_production_and_optional_in_the_migrations(report):
    offenders = report["live_requires_but_migrations_do_not"]
    assert not offenders, (
        "These columns are NOT NULL with no default in production, and nullable "
        "in the migrations. Code written from the migrations will omit them and "
        "every insert will be rejected in production, while this suite stays "
        "green — which is exactly how form_26as_uploads.uploaded_by was lost.\n"
        "Declare them NOT NULL in a migration (see 292 for the pattern), or, if "
        "production is wrong, change production.\n  "
        + "\n  ".join(offenders))


@_NEEDS_PG
def test_no_column_the_code_writes_is_missing_from_production(report, pg_template):
    """A column the migrations declare and production lacks rejects the insert.

    TWO EXCLUSIONS, BOTH DERIVED RATHER THAN LISTED BY HAND.

    Views, because a view's columns are computed and nothing inserts into one.
    The set comes from the database, never from an allowlist — a TABLE that
    slipped into such a list would hide exactly the fault being asserted.

    And columns introduced by a migration NEWER than the snapshot. The first
    version of this test lacked that and was wrong: the fixture records
    production at a moment in time, so the repo is legitimately ahead of it by
    however many migrations have not merged yet, and forbidding that made the
    ordinary act of adding a column in a migration fail its own PR. What the
    check is actually for is a column that has been declared for MONTHS and
    never reached production — like the 31 that broke four features — not one
    that will land the moment this branch merges.

    The high-water mark lives in the fixture's .meta.json beside it, and a
    column is only excused if a migration above that mark actually mentions it.
    An offender nobody can attribute to an in-flight migration still fails,
    which is the safe direction.
    """
    views = _view_names(pg_template.name)
    in_flight = _columns_added_after_the_snapshot()
    offenders = [o for o in report["columns_missing_from_live"]
                 if o.split(".", 1)[0] not in views
                 and o.split(".", 1)[1] not in in_flight]
    assert not offenders, (
        "These columns exist in the migrations and NOT in production. Any code "
        "that writes one has every insert rejected there while this suite stays "
        "green — that is how year-end adjustments, statement versions, account "
        "mappings and the filings row behind period locking were all broken at "
        "once.\n"
        "Add them in a migration (294 is the pattern, including how to tighten a "
        "NOT NULL only where it is safe).\n  "
        + "\n  ".join(offenders))


@_NEEDS_PG
def test_no_column_has_a_different_type_in_production(report):
    offenders = report["type_differs"]
    assert not offenders, (
        "These columns have one type in the migrations and another in production. "
        "Migration 293 took this set to zero; anything here is new drift.\n"
        "Decide which side is right — production is not automatically correct, and "
        "293 resolved its seventeen four different ways — then write a migration "
        "that converges them. 293 is the pattern, including how to handle a column "
        "an RLS policy references.\n  "
        + "\n  ".join(offenders))


# ── Guard the guard ───────────────────────────────────────────────────────────

@_NEEDS_PG
def test_the_comparison_actually_ran(report):
    """A fixture that failed to load, or a template that came back empty, would
    make the assertion above pass by comparing nothing to nothing."""
    assert sum(len(v) for v in report.values()) > 0, (
        "The comparison found NO differences at all, which is not plausible — "
        "the first real run found 191. Something compared nothing.")


@_NEEDS_PG
def test_the_fixture_describes_a_real_schema():
    live = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert len(live) > 200, "the production snapshot looks truncated"
    # A table this product certainly has, with a column it certainly requires.
    assert live["journal_entries"]["client_id"]["nullable"] == "NO"


@_NEEDS_PG
def test_a_planted_offender_would_be_caught():
    """Prove the assertion has teeth without waiting for a real regression."""
    declared = {"t": {"c": {"type": "uuid", "nullable": "YES", "default": ""}}}
    live = {"t": {"c": {"type": "uuid", "nullable": "NO", "default": ""}}}
    assert schema_drift.diff(declared, live)["live_requires_but_migrations_do_not"] == ["t.c"]
