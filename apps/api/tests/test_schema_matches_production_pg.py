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

WHAT IT DELIBERATELY DOES NOT ASSERT

Only that one direction. The same comparison reports six other categories —
tables and columns present on one side only, type differences, the safe
nullability direction — and every one of them is real drift worth knowing about.
None of them can reject an insert, so none of them is a build failure. Asserting
on all seven would make this test a permanent 156-item complaint that somebody
turns off.

THE FIXTURE IS A SNAPSHOT

tests/fixtures/production_schema_2026-08-31.json is what production looked like
on one day, so this can run in CI without production credentials. It goes stale
by design; see that directory's README for how to refresh it.
"""
from __future__ import annotations

import importlib.util
import json
import os
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
