"""The knowledge-base search's like pattern means the typed words on a real database (POST-A-216).

The mock-mode file (`test_a_knowledge_search_reads_the_current_text_as_well_as_the_title.py`) asserts the pattern's spelling; only
Postgres can say what `ILIKE` makes of it. A typed `%`, `_` or backslash must match itself and nothing else, the words must be found
anywhere in the text in any case, and an empty search would never reach here (the service treats blank words as no search).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from services.knowledge_service import _like_pattern

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")


def _ilike(text: str, pattern: str) -> bool:
    for s in (text, pattern):
        assert "$k$" not in s
    r = subprocess.run(["psql", _ADMIN, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-c",
                        f"SELECT $k${text}$k$ ILIKE $k${pattern}$k$"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip() == "t"


@pytest.mark.parametrize("words,text,found", [
    ("15CA", "Form 15ca is filed before the remittance.", True),
    ("15CA", "Form 15CB only.", False),
    ("50%", "TDS at 50% of the excess", True),
    ("50%", "TDS at 50 rupees", False),                      # unescaped, % matched anything after 50
    ("TDS_rate", "the TDS_rate table", True),
    ("TDS_rate", "the TDS-rate table", False),               # unescaped, _ matched any one character
    ("C:\\docs", "saved under C:\\docs\\2026", True),
    ("C:\\docs", "saved under C:docs", False),
    ("\\%_", "a \\%_ b", True),
    ("\\%_", "a \\x b", False),
    ("Being salary payable", "being SALARY payable for the month", True),
])
def test_the_pattern_finds_the_typed_words_anywhere_in_any_case_and_a_wildcard_character_matches_itself(words, text, found):
    assert _ilike(text, _like_pattern(words)) is found
