"""Every directory under docs/compliance/sources/ says where it came from and on what date.

WHY THIS EXISTS

    `docs/compliance/sources/README.md` states the repository's rule for primary
    sources in its last sentence: "A file with no provenance is worth less than no
    file, because it reads as authoritative." It documented two directories
    (`e-invoice/`, `gst-notifications/`) and was silent about a third,
    `gst-offline-utilities/` - twenty-one extracted VBA modules that four domain
    modules and two tests cite as their primary source. A reader following any of
    those citations arrived at a directory the index did not mention.

    The rule is over the directory, not the three names: each immediate
    subdirectory of `sources/` is named as `` `<dir>/` `` in a `### ` section of
    the README, and that section carries a DD-MM-YYYY date (the day it was fetched
    or extracted). It checks that a date is PRESENT, not that it is right, and it
    does not require a URL: a directory whose page address was never written down
    must say so rather than have one invented.

    The reverse direction is checked too - a section naming a directory that is
    not there is a stale entry - because an index that lists a vanished source is
    the same kind of wrong.
"""
from __future__ import annotations

import re
from pathlib import Path

SOURCES = Path(__file__).resolve().parents[3] / "docs" / "compliance" / "sources"
README = SOURCES / "README.md"

DATE = re.compile(r"\b\d{2}-\d{2}-\d{4}\b")
HEADING_DIR = re.compile(r"`([A-Za-z0-9._-]+)/`")


def sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) for every '### ' section, the body running to the next '#' heading."""
    out: list[tuple[str, str]] = []
    head: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if head is not None:
                out.append((head, "\n".join(body)))
            head = line if line.startswith("### ") else None
            body = []
        elif head is not None:
            body.append(line)
    if head is not None:
        out.append((head, "\n".join(body)))
    return out


def directories() -> list[str]:
    return sorted(p.name for p in SOURCES.iterdir() if p.is_dir() and not p.name.startswith("."))


def problems(text: str, dirs: list[str]) -> list[str]:
    secs = sections(text)
    found: list[str] = []
    for d in dirs:
        owners = [(h, b) for h, b in secs if f"`{d}/`" in h]
        if not owners:
            found.append(f"{d}/ has no '### `{d}/`' section in sources/README.md - say where "
                         f"it came from and on what date")
        elif not any(DATE.search(b) for _, b in owners):
            found.append(f"the section for {d}/ carries no DD-MM-YYYY date")
    for h, _ in secs:
        for named in HEADING_DIR.findall(h):
            if named not in dirs:
                found.append(f"the README has a section for {named}/ but no such directory exists")
    return found


def test_every_source_directory_has_a_dated_provenance_section():
    found = problems(README.read_text(encoding="utf-8"), directories())
    assert not found, "\n".join(found)


def test_the_collector_is_not_vacuous():
    dirs = directories()
    assert len(dirs) >= 3, f"expected e-invoice, gst-notifications and gst-offline-utilities, found {dirs}"
    # Two sections existed before the third directory was documented; the floor is the parser
    # finding what was always there, so it cannot fail for the very omission the test above names.
    assert len(sections(README.read_text(encoding="utf-8"))) >= 2, "the README sections were not parsed"
    for d in dirs:
        assert any(p.is_file() for p in (SOURCES / d).rglob("*")), f"{d}/ holds no file"


def test_the_rule_fires_on_each_way_an_entry_can_be_wrong():
    ok = "# T\n\n### `a/` - A\nFetched 18-09-2026.\n\n### `b/` - B\nExtracted 26-09-2026.\n"
    assert problems(ok, ["a", "b"]) == []
    # a directory the index never names (the original defect)
    assert len(problems(ok, ["a", "b", "c"])) == 1
    # a section with no date
    undated = ok.replace("Extracted 26-09-2026.", "Extracted recently.")
    assert len(problems(undated, ["a", "b"])) == 1
    # a date written the other way round is not a DD-MM-YYYY date
    assert len(problems(ok.replace("18-09-2026", "2026-09-18"), ["a", "b"])) == 1
    # a date in ANOTHER section does not rescue this one
    assert len(problems("### `a/`\nno date\n\n### `b/`\n26-09-2026\n", ["a", "b"])) == 1
    # a section for a directory that is gone
    assert len(problems(ok, ["a"])) == 1
