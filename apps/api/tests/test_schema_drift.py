"""
The drift check between what the migrations declare and what the database has.

WHY THIS TOOL EXISTS

Nothing compared the two, and they had diverged. Twice that cost real damage:

  * Migration 291 passed every local check and failed against production with
    `column "status" does not exist` — form_26as_uploads has a different shape
    there than migration 052 declares.

  * Earlier, an audit read migration 052, concluded `uploaded_by` did not exist,
    and deleted the code that wrote it. That column exists in production, is NOT
    NULL, and has no default, so every 26AS upload failed there — silently,
    while the whole test suite passed. The audit was careful. It read the wrong
    source, and no check could tell it so.

Both are the same failure: the CI template is built FROM the migrations, so
every test and both column checkers only ever see what the migrations say.

THE CATEGORY THAT MATTERS

`live_requires_but_migrations_do_not` — a column the database demands, with no
default, that the migrations do not mark required. Code written from the
migrations omits it and every insert is rejected in production. That is exactly
what `uploaded_by` was, and the real run of this tool found 34 more like it.

Everything else in the report is informational by comparison: a column only the
migrations know about cannot break an insert, and a nullable-in-live difference
is the safe direction.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "schema_drift",
    Path(__file__).resolve().parents[1] / "scripts" / "db" / "schema_drift.py")
drift_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(drift_mod)
diff, render = drift_mod.diff, drift_mod.render


def col(type_="text", nullable="YES", default=""):
    return {"type": type_, "nullable": nullable, "default": default}


# ── The failure that started this ─────────────────────────────────────────────

def test_a_required_column_the_migrations_do_not_declare_is_the_headline():
    """form_26as_uploads.uploaded_by, exactly: NOT NULL, no default, absent
    from the migration. Every insert written from the migration is rejected."""
    declared = {"form_26as_uploads": {"id": col()}}
    live = {"form_26as_uploads": {"id": col(),
                                  "uploaded_by": col("uuid", "NO", "")}}
    report = diff(declared, live)
    assert report["live_requires_but_migrations_do_not"] == [
        "form_26as_uploads.uploaded_by"]


def test_a_column_required_in_live_but_nullable_in_the_migrations_is_caught():
    """The same hazard by a different route: the column IS declared, but as
    optional, so code written from the migrations still omits it."""
    declared = {"t": {"c": col(nullable="YES")}}
    live = {"t": {"c": col(nullable="NO")}}
    assert diff(declared, live)["live_requires_but_migrations_do_not"] == ["t.c"]


def test_a_required_column_WITH_a_default_is_not_the_headline():
    """A default means the insert succeeds. Worth reporting, not urgent — and
    conflating the two would bury the 35 that actually reject."""
    declared = {"t": {"id": col()}}
    live = {"t": {"id": col(), "created_at": col("timestamptz", "NO", "now()")}}
    report = diff(declared, live)
    assert report["live_requires_but_migrations_do_not"] == []
    assert report["columns_only_in_live"] == ["t.created_at  [NOT NULL]"]


def test_the_safe_direction_is_not_reported_as_the_dangerous_one():
    """Migrations stricter than live cannot reject an insert."""
    declared = {"t": {"c": col(nullable="NO")}}
    live = {"t": {"c": col(nullable="YES")}}
    report = diff(declared, live)
    assert report["live_requires_but_migrations_do_not"] == []
    assert len(report["nullability_differs"]) == 1


# ── The other categories ──────────────────────────────────────────────────────

def test_a_table_the_migrations_declare_that_is_missing_is_reported():
    assert diff({"t": {"c": col()}}, {})["tables_missing_from_live"] == ["t"]


def test_a_table_only_in_live_is_reported():
    assert diff({}, {"t": {"c": col()}})["tables_only_in_live"] == ["t"]


def test_a_missing_column_is_reported():
    report = diff({"t": {"a": col(), "b": col()}}, {"t": {"a": col()}})
    assert report["columns_missing_from_live"] == ["t.b"]


def test_a_type_difference_is_reported_with_both_sides():
    report = diff({"t": {"c": col("uuid")}}, {"t": {"c": col("text")}})
    assert report["type_differs"] == [
        "t.c: migrations say uuid, live says text"]


def test_the_runners_own_tracking_table_is_not_drift():
    """scripts/db/apply_migrations.py creates schema_migrations itself, so it is
    in every live database and in no migration. Reporting it forever would
    train a reader to ignore the 'only in live' section."""
    assert diff({}, {"schema_migrations": {"filename": col()}})["tables_only_in_live"] == []


# ── Reporting ─────────────────────────────────────────────────────────────────

def test_no_drift_says_so_plainly():
    same = {"t": {"c": col()}}
    assert diff(same, same) == {k: [] for k in diff(same, same)}
    assert "No drift" in render(diff(same, same))


def test_the_rendered_report_leads_with_the_dangerous_category():
    report = diff({"t": {"a": col()}},
                  {"t": {"a": col(), "b": col("uuid", "NO", "")},
                   "extra": {"x": col()}})
    text = render(report)
    assert text.index("REJECTED in production") < text.index("no migration declares")


def test_every_category_the_diff_produces_has_a_heading():
    """A category with no heading is silently dropped from the report — the
    difference would be found and then not shown, which is worse than not
    looking."""
    assert set(diff({}, {})) == set(drift_mod.HEADINGS)
