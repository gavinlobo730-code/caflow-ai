"""POST-A-541: the two columns the guided tips used are dropped, and the premise the drop stands on is held.

Migration 774 added `users.guided_tips_on` and `users.guided_tips_seen` for the guided tips. The "Where is…?" guide replaced the
tips the same day (POST-A-538) and removed everything that read or wrote the columns; migration 775 drops them.

A drop is safe only while NOTHING READS WHAT WAS DROPPED, and that is a fact about the code, so it is a test and not a sentence in
the migration's header: no module the API runs names either column. A reader added later (somebody restoring the tips from git
history, say) fails here, beside the reason, before it fails in production as an unknown column.

The other half, that a database built from the migrations no longer has the columns, is asserted by migration 775's own closing
block, which the migration-apply job runs against a real Postgres on every change.
"""
from __future__ import annotations

import re
from pathlib import Path

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"
NAMES = re.compile(r"guided_tips_(on|seen)")


def test_no_module_the_api_runs_names_a_dropped_column():
    offenders = []
    scanned = 0
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if rel.parts[0] in {"tests", "migrations", "venv", ".venv"} or "__pycache__" in rel.parts:
            continue
        scanned += 1
        if NAMES.search(path.read_text(encoding="utf8")):
            offenders.append(str(rel))
    assert scanned > 300, f"only {scanned} modules were read: the scan has lost the API"
    assert offenders == [], f"these modules name a column migration 775 dropped: {offenders}"


def test_the_drop_follows_the_add_and_has_its_rollback():
    drop = MIGRATIONS / "775_the_guided_tips_columns_are_dropped.sql"
    rollback = MIGRATIONS / "775_the_guided_tips_columns_are_dropped_rollback.sql"
    assert drop.is_file() and rollback.is_file()
    sql = drop.read_text(encoding="utf8")
    for column in ("guided_tips_on", "guided_tips_seen"):
        assert re.search(rf"ALTER TABLE public\.users DROP COLUMN IF EXISTS {column};", sql), column
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {column}\b", rollback.read_text(encoding="utf8")), column
    # The migration checks its own result, so a database that still has a column fails the apply and not a later read.
    assert "RAISE EXCEPTION 'migration 775" in sql
    # The add it undoes is still in the history: migrations are never edited or removed once merged.
    assert (MIGRATIONS / "774_a_person_keeps_their_guided_tips.sql").is_file()


def test_the_columns_are_on_no_list_of_columns_production_is_expected_to_have():
    from tests import production_types

    listed = [key for key in production_types.ADDED_AFTER_THE_SNAPSHOT if key[0] == "users" and key[1].startswith("guided_tips_")]
    assert listed == [], "a dropped column is still listed as added after the production snapshot"
