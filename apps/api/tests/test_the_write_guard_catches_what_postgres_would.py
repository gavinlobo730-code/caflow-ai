"""The write guard has to fail on the real defects, and only on them.

WHY A TEST FOR A TEST HELPER
    tests/production_types.py is wired into the shared e2e harness, so every
    FakeDB write in ~144 test files passes through it. A guard that silently
    checks nothing is worse than no guard: it makes the suite look like it
    covers the schema when it does not, which is the exact failure mode the
    guard exists to end.

    So this asserts BOTH directions. It fails on the five shapes that reached
    production, and it passes the shapes that are legitimately fine — a
    numeric sent as a string, a table the snapshot predates, a column a later
    migration added.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from tests.production_types import (
    ADDED_AFTER_THE_SNAPSHOT,
    SCHEMA_FILE,
    _SCHEMA,
    assert_write_fits_production_types as check,
    known_table,
)


# ── vacuity guard: the snapshot has to have loaded ───────────────────────────

def test_the_snapshot_loaded_and_is_the_schema_not_its_metadata():
    """The sibling *.meta.json describes the snapshot rather than being one.
    Globbing it up gives six 'tables' and a guard that checks nothing."""
    assert SCHEMA_FILE is not None and not SCHEMA_FILE.name.endswith(".meta.json")
    assert len(_SCHEMA) > 200, f"only {len(_SCHEMA)} tables — wrong file?"
    assert known_table("journal_entries") and known_table("compliance_records")


# ── the five shapes that reached production ──────────────────────────────────

def test_a_month_label_into_a_date_column_is_refused():
    """routers/fixed_assets.py wrote '2026-04' into
    fixed_assets.depreciation_posted_through. Postgres answers 22007 and
    rejects the WHOLE update, so every other column in it silently stays as it
    was. Posting depreciation had never worked against the real database."""
    with pytest.raises(AssertionError, match="22007"):
        check("fixed_assets", {"depreciation_posted_through": "2026-04"})


def test_an_empty_string_into_a_date_column_is_refused():
    """domain/compliance_record_service wrote "" for a missing period."""
    with pytest.raises(AssertionError, match="DATE"):
        check("compliance_records", {"period_start": ""})


def test_a_column_production_does_not_have_is_refused():
    """PostgREST answers PGRST204 to the whole write, so nothing lands."""
    with pytest.raises(AssertionError, match="PGRST204"):
        check("compliance_records", {"no_such_column_anywhere": "x"})


def test_a_bare_date_into_a_timestamptz_column_is_refused():
    """This one is NOT a rejected write, which is why it is the subtle one:
    Postgres parses '2026-09-08' as midnight in the session's timezone and
    stores an instant nobody chose."""
    with pytest.raises(AssertionError, match="midnight"):
        check("compliance_records", {"completed_at": "2026-09-08"})


def test_a_float_into_an_integer_paise_column_is_refused():
    """Money crosses this boundary as integer paise (CLAUDE.md). A float here
    is both a type error and a rounding one."""
    with pytest.raises(AssertionError):
        check("journal_lines", {"debit_paise": 1234.5})


# ── and what is legitimately fine ────────────────────────────────────────────

def test_a_numeric_sent_as_a_string_is_accepted():
    """Postgres parses a numeric literal out of a string on input, and the
    codebase sends exchange rates that way on purpose — a rate is decimal and a
    float round-trip is what the money rules forbid."""
    check("purchase_bills", {"exchange_rate": "1"})
    check("purchase_bills", {"exchange_rate": "83.2517"})
    with pytest.raises(AssertionError, match="cannot parse"):
        check("purchase_bills", {"exchange_rate": "about eighty-three"})


def test_a_real_date_or_timestamp_object_is_accepted():
    check("compliance_records", {"period_start": date(2026, 10, 1)})
    check("compliance_records", {"completed_at": datetime(2026, 9, 8, 14, 30)})
    check("compliance_records", {"completed_at": "2026-09-08T14:30:00+05:30"})


def test_none_is_accepted_for_any_type():
    """A nullable column takes NULL, and the repositories filter None out
    before the insert anyway — refusing it here would fail correct code."""
    check("compliance_records", {"period_start": None, "completed_at": None,
                                 "notes": None})


def test_a_table_the_snapshot_predates_is_skipped_not_failed():
    """The snapshot goes stale by design (docs/schema-drift.md). A test that
    failed because a NEW table is new would be noise, not a finding."""
    check("a_table_invented_for_this_test", {"anything": object()})


def test_a_column_a_later_migration_added_is_allowed_by_name():
    """...but only by name, with the migration recorded, so the entry becomes
    provably removable the moment the snapshot is refreshed."""
    check("payroll_slips", {"pf_wages_paise": 1_400_000})
    assert ("payroll_slips", "pf_wages_paise") in ADDED_AFTER_THE_SNAPSHOT


def test_the_post_snapshot_list_stays_short_and_names_its_migrations():
    """A long list means the snapshot needs refreshing, not that the list needs
    another entry.

    COUNTED BY MIGRATION, not by column, and the difference matters. One
    migration adding sixteen columns to one table (340 does) is ONE thing to
    remember and one thing the next snapshot refresh clears. Sixteen migrations
    each adding a column is the drift this guard exists to catch — the schema
    moving faster than anybody is looking at it.

    A column cap alone made the guard fire on the wrong signal: it told a
    developer to refresh a production snapshot from a database that does not
    yet have the migration, because migrations reach production only on merge
    to main.
    """
    migrations = set(ADDED_AFTER_THE_SNAPSHOT.values())
    assert len(migrations) <= 8, (
        f"{len(migrations)} unapplied migrations are being worked around "
        f"({sorted(migrations)}). Refresh tests/fixtures/production_schema_*.json "
        f"once they are on main, instead of adding more."
    )
    assert len(ADDED_AFTER_THE_SNAPSHOT) <= 40, (
        "refresh tests/fixtures/production_schema_*.json instead of adding more"
    )
    for (table, column), why in ADDED_AFTER_THE_SNAPSHOT.items():
        assert "migration" in why.lower(), f"{table}.{column}: say which migration"
        # If it is in the snapshot now, the entry is dead and should go.
        cols = _SCHEMA.get(table)
        if cols is not None:
            assert column not in cols, (
                f"{table}.{column} is in {SCHEMA_FILE.name} now — delete its line "
                f"from ADDED_AFTER_THE_SNAPSHOT."
            )


# ── the harness really does route writes through it ─────────────────────────

def test_the_shared_harness_checks_its_writes():
    """The wiring, not the function. Without this, moving the call out of
    _Query.insert would disarm the guard for all ~144 files that use FakeDB and
    every one of them would still pass."""
    from tests.e2e_harness import FakeDB

    db = FakeDB()
    with pytest.raises(AssertionError, match="22007"):
        db.table("fixed_assets").insert({"depreciation_posted_through": "2026-04"}).execute()
    with pytest.raises(AssertionError, match="PGRST204"):
        db.table("compliance_records").update({"no_such_column_anywhere": 1}).execute()


def test_seeding_is_deliberately_not_checked():
    """seed() writes the in-memory dict directly. Fixtures state what the world
    looks like, which is the test's own business; the guard is about what the
    CODE writes."""
    from tests.e2e_harness import FakeDB

    db = FakeDB()
    db.seed("fixed_assets", {"depreciation_posted_through": "2026-04"})
    assert db.rows("fixed_assets")[0]["depreciation_posted_through"] == "2026-04"


def test_the_escape_hatch_cannot_leak_into_the_next_test():
    """It is a context manager rather than a setter on purpose.

    A plain `enforce(False)` that a test forgets to undo disarms the guard for
    every test after it in the same process, silently — which is exactly the
    class of failure this module exists to catch. It would be catching it in
    itself, and nothing would say so.
    """
    from tests.e2e_harness import FakeDB, production_types_unenforced

    db = FakeDB()
    with production_types_unenforced():
        db.table("fixed_assets").insert({"depreciation_posted_through": "2026-04"}).execute()

    with pytest.raises(AssertionError, match="22007"):
        db.table("fixed_assets").insert({"depreciation_posted_through": "2026-04"}).execute()


def test_the_escape_hatch_restores_even_when_the_block_raises():
    from tests.e2e_harness import FakeDB, production_types_unenforced

    db = FakeDB()
    with pytest.raises(RuntimeError):
        with production_types_unenforced():
            raise RuntimeError("boom")

    with pytest.raises(AssertionError, match="22007"):
        db.table("fixed_assets").insert({"depreciation_posted_through": "2026-04"}).execute()
