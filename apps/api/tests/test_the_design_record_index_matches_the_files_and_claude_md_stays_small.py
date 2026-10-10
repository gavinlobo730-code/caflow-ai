"""CLAUDE.md is loaded at the start of every session, so its size is a recurring cost, and the long per-area write-ups
live in docs/design-record/ behind an index of one-line headlines (moved verbatim on 10 October 2026). Two rules keep
that arrangement honest: every entry the index lists is really in the file it names (a stale index would send a reader
to a rule that is not there), and CLAUDE.md does not grow back into the file it was. The rule is stated here, not a
list of today's files: a new long write-up goes into a record file and gets an index line."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLAUDE_MD = REPO / "CLAUDE.md"
RECORD = REPO / "docs" / "design-record"

#: The slimmed file was about 170,000 characters; the one it replaced was about 635,000. A margin lets ordinary rules
#: be added, and the failure message says where a long write-up belongs.
MAX_CLAUDE_MD_CHARS = 200_000

pytestmark = pytest.mark.skipif(not CLAUDE_MD.is_file(), reason="CLAUDE.md is not in this checkout")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _index() -> dict[str, list[str]]:
    """{record file name: [headline, ...]} read from the 'Design record index' section of CLAUDE.md."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.index("## Design record index")
    end = text.index("\n## ", start + 5)
    found: dict[str, list[str]] = {}
    current = None
    for line in text[start:end].split("\n"):
        head = re.match(r"### `docs/design-record/([\w.-]+\.md)`", line)
        if head:
            current = head.group(1)
            found[current] = []
        elif line.startswith("- ") and current:
            found[current].append(line[2:].strip())
    return found


def test_claude_md_stays_small_enough_to_load_every_session():
    size = len(CLAUDE_MD.read_text(encoding="utf-8"))
    assert size <= MAX_CLAUDE_MD_CHARS, (
        f"CLAUDE.md is {size:,} characters (limit {MAX_CLAUDE_MD_CHARS:,}) and every session reads all of it. Put a long "
        "design write-up in the matching file under docs/design-record/ and add its one-line headline to the 'Design "
        "record index'; keep only the rule itself here.")


def test_every_indexed_headline_is_in_the_record_file_it_names():
    index = _index()
    assert index, "the Design record index lists no file"
    for name, headlines in index.items():
        path = RECORD / name
        assert path.is_file(), f"the index names docs/design-record/{name} and it does not exist"
        body = _flat(path.read_text(encoding="utf-8"))
        for headline in headlines:
            assert _flat(headline) in body, (
                f"the index lists '{headline[:80]}' under {name} but that text is not in the file")


def test_every_record_file_is_in_the_index():
    named = set(_index())
    on_disk = {p.name for p in RECORD.glob("*.md") if p.name != "README.md"}
    assert on_disk == named, (
        f"docs/design-record/ and the index disagree: only on disk {sorted(on_disk - named)}, only in the index "
        f"{sorted(named - on_disk)}")
