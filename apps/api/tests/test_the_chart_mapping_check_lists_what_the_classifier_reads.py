"""The CHECK on `chart_of_accounts.schedule_iii_mapping` lists exactly what the classifier can read (POST-A-164, migration 520).

A second copy of the caption vocabulary in SQL is what the posting-kernel rule exists to prevent, so the copy is pinned here, in the
mock-mode suite that CI's first required check runs, as well as by the real-Postgres test beside the migration (which reads the
constraint back from a migration-built database). Three places must agree and this holds all three:

    domain.reporting.schedule_iii.accepted_stored_spellings()   what `canonical_caption` can read
    migration 520's IN (...) list                                what the database accepts
    GET /api/accounting/schedule-iii/captions                    the menu plus `also_accepted`, what the import screen accepts
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.reporting import schedule_iii as s

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(p for p in (API_ROOT / "migrations").glob("520_*.sql") if not p.name.endswith("_rollback.sql"))


def _migration_list() -> set[str]:
    text = MIGRATION.read_text(encoding="utf-8")
    block = text[text.index("schedule_iii_mapping IN ("):]
    block = block[:block.index(")) NOT VALID")]
    return {v.replace("''", "'") for v in re.findall(r"'((?:[^']|'')*)'", block)}


def test_the_migrations_list_is_the_vocabulary_the_classifier_reads():
    assert _migration_list() == set(s.accepted_stored_spellings()), (
        sorted(_migration_list() ^ set(s.accepted_stored_spellings())))


def test_every_accepted_spelling_is_readable_and_a_made_up_one_is_not():
    for value in s.accepted_stored_spellings():
        assert s.canonical_caption(value) is not None, value
    assert s.canonical_caption("Miscellaneous") is None


def test_the_vocabulary_is_the_captions_the_aliases_and_the_heading_and_nothing_else():
    assert s.accepted_stored_spellings() == frozenset(s.CAPTIONS) | frozenset(s.CAPTION_ALIASES) | {s._FIXED_ASSETS_HEADING}


def test_the_served_menu_plus_also_accepted_is_exactly_what_the_database_accepts():
    from routers.accounting import schedule_iii_captions
    payload = schedule_iii_captions(current_user={"id": "u", "firm_id": "f", "role": "Partner"})["data"]
    menu = {item for section in payload["sections"] for item in section["items"]}
    assert menu | set(payload["also_accepted"]) == _migration_list()
    assert not (menu & set(payload["also_accepted"])), "a spelling is either on the menu or an older one, not both"
    assert payload["also_accepted"] == sorted(payload["also_accepted"])


@pytest.mark.parametrize("old", ["Employee Benefit Expense", "Long Term Borrowings", "Fixed Assets"])
def test_the_older_spellings_are_not_offered_on_the_menu_but_are_accepted(old):
    from routers.accounting import schedule_iii_captions
    payload = schedule_iii_captions(current_user={"id": "u", "firm_id": "f", "role": "Partner"})["data"]
    assert old not in {item for section in payload["sections"] for item in section["items"]}
    assert old in payload["also_accepted"]
