"""The draft sources are ONE vocabulary in three places, and the places are held to the code (POST-A-272).

`domain/banking/entry.SOURCES` is what the queue proposes. The database CHECK `bank_transactions_draft_source_check` is what a row may
carry; a source the code proposes and the check refuses is a redraft that fails on its first write (the update is refused for the whole
chunk's line, and the line stays un-proposed with nothing saying why). The browser's `Entry.draft_source` type is what the screen
branches on. Migration 322 spelled the check with four words and the type with four; the fifth (`challan`, migration 578) is a word that
had to be added in all three, and the next one will be too.

THE RULE, NOT A SPELLING: the CHECK is read from the LAST migration that defines it, found by number, so a later migration that
narrows or widens it again is the one compared; the browser type is read from the declaration of the field, whatever order its members
are in.
"""
from __future__ import annotations

import re
from pathlib import Path

from domain.banking import entry as E

API = Path(__file__).resolve().parent.parent
WEB = API.parent / "web"


def _last_check_sources() -> tuple[str, set[str]]:
    latest = None
    for path in sorted(API.glob("migrations/*.sql")):
        if path.name.endswith("_rollback.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"bank_transactions_draft_source_check\s+CHECK\s*\(\s*draft_source IS NULL OR draft_source IN\s*\(([^)]*)\)", text, re.S):
            latest = (path.name, set(re.findall(r"'([a-z_]+)'", m.group(1))))
    assert latest is not None, "no migration defines bank_transactions_draft_source_check"
    return latest


def test_the_database_check_admits_exactly_the_sources_the_code_proposes():
    name, admitted = _last_check_sources()
    assert admitted == set(E.SOURCES), (f"{name} admits {sorted(admitted)} but domain/banking/entry.SOURCES is {sorted(E.SOURCES)}: "
                                        "a source the code proposes and the check refuses fails the redraft's first write")


def test_the_screen_types_exactly_the_sources_the_code_proposes():
    src = (WEB / "components" / "banking" / "EntriesTab.tsx").read_text(encoding="utf-8")
    m = re.search(r"draft_source:\s*([^;]+);", src)
    assert m, "EntriesTab no longer declares the draft_source field"
    typed = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert typed == set(E.SOURCES), f"the screen types {sorted(typed)}, the queue proposes {sorted(E.SOURCES)}"


def test_the_scan_is_not_blind():
    """The 322 spelling must be found by the same pattern, or a reworded migration would pass by being invisible."""
    text = ("ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_draft_source_check\n"
            "  CHECK (draft_source IS NULL OR draft_source IN ('rule', 'document', 'history', 'transfer'));")
    m = re.search(r"bank_transactions_draft_source_check\s+CHECK\s*\(\s*draft_source IS NULL OR draft_source IN\s*\(([^)]*)\)", text, re.S)
    assert m and set(re.findall(r"'([a-z_]+)'", m.group(1))) == {"rule", "document", "history", "transfer"}
    assert "challan" in _last_check_sources()[1], "the scan reads the real migrations too"
