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

import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]

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
    provably removable the moment the snapshot is refreshed.

    Driven by the list rather than naming one column, because naming one is a
    claim that goes stale: this test pinned payroll_slips.pf_wages_paise, and
    the 9 September refresh — which put that column IN the snapshot and
    correctly removed its entry — broke the test rather than passing it. What
    is being asserted is the RULE (a named column is let through, an unnamed
    one is not), and the rule survives every refresh.
    """
    for (table, column), migration in ADDED_AFTER_THE_SNAPSHOT.items():
        check(table, {column: object()})
        assert migration.startswith("migration "), (table, column, migration)

    # The other half, and the one that matters: a column NOT on the list, in a
    # table the snapshot does hold, is still refused.
    with pytest.raises(AssertionError):
        check("payroll_slips", {"invented_by_this_test_paise": 1})


def _snapshot_mark() -> int:
    """The highest migration production had when the snapshot was captured.

    Read from the snapshot's own `.meta.json` rather than hard-coded, so
    refreshing the fixture moves the line by itself. Absent (an older fixture
    with no metadata) reads as 0, which makes the staleness test vacuous rather
    than wrong — and the fixture beside it is what a refresh replaces anyway.
    """
    if SCHEMA_FILE is None:
        return 0
    meta = SCHEMA_FILE.with_suffix("").with_suffix(".meta.json")
    if not meta.exists():
        meta = SCHEMA_FILE.parent / (SCHEMA_FILE.stem + ".meta.json")
    if not meta.exists():
        return 0
    return int(json.loads(meta.read_text()).get("applied_through_migration") or 0)


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
    numbers = {int(re.search(r"(\d+)", m).group(1)) for m in migrations
               if re.search(r"(\d+)", m)}
    assert len(numbers) == len(migrations), (
        f"every entry must name a numbered migration: {sorted(migrations)}")

    # THE DIRECT MEASURE, replacing a flat cap of 8.
    #
    # The cap was a PROXY for "the snapshot needs refreshing", and it fired on
    # the wrong signal for exactly the reason this docstring already records
    # about the column cap it replaced: migrations reach production only on
    # merge to main, so a branch carrying a tranche of work legitimately has
    # several in flight at once and the cap told a developer to refresh a
    # snapshot from a database that does not have them.
    #
    # What the cap was really trying to catch is a column DECLARED FOR MONTHS
    # that never reached production, and the snapshot's own metadata already
    # says which those are: `applied_through_migration` is the highest
    # migration in production's schema_migrations when it was captured, and its
    # note states the rule — "the migrations in the repo are ALLOWED to be
    # ahead of it by exactly the migrations not yet merged". So an entry AT OR
    # BELOW that mark is stale by definition and one is already too many, while
    # an entry above it is precisely what the list is for.
    #
    # This is strictly stronger: it fires on one genuinely stale entry rather
    # than on nine entries of any kind, and it cannot be satisfied by raising
    # a number.
    mark = _snapshot_mark()
    stale = sorted(n for n in numbers if n <= mark)
    assert not stale, (
        f"migration(s) {stale} are at or below the snapshot's own mark of "
        f"{mark}, so production already has them and "
        f"{SCHEMA_FILE.name if SCHEMA_FILE else 'the snapshot'} is stale. "
        f"Refresh tests/fixtures/production_schema_*.json (and the guards "
        f"fixture beside it) rather than working around a column that IS in "
        f"production. docs/schema-drift.md says how."
    )

    # AND NOTHING MAY NAME A MIGRATION THAT DOES NOT EXIST. A dead entry —
    # left behind by a renumbered or deleted migration — reads as a live
    # work-around and quietly widens the write guard for a column nothing adds.
    present = {int(n.name[:3]) for n in (API / "migrations").glob("[0-9][0-9][0-9]_*.sql")}
    invented = sorted(n for n in numbers if n not in present)
    assert not invented, (
        f"migration(s) {invented} are named here and are not in "
        f"apps/api/migrations. Delete the entry — a work-around for a "
        f"migration that does not exist widens the write guard for nothing.")
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
