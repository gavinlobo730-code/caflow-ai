"""A finding id quoted in a comment names ONE finding, and `GST-16` was being used for two.

WHAT WAS WRONG
    The audit record (deleted on 8 October 2026, recoverable at `git show 315e6a19:docs/audits/findings-status.md`)
    numbers its findings, and the code quotes those numbers in comments so a reader can find the reasoning. `GST-16`
    in that record is "The GSTR-1 validator never runs on the path a CA actually uses", and the web code that quotes
    it for that (`Gstr1Findings`, the two GSTR-1 screens, `a-gstr1-with-errors-is-not-validated`) is right.

    But CLAUDE.md and seven comments in the API and the web used `GST-16` for a DIFFERENT piece of work: attributing
    each invoice, bill and note to a GST registration ("GST-16 is open", "GST-16 retires it"). That work has no id in
    the audit record; it is a line in the open-items ledger. A reader who followed the id to the record found a
    finding about the validator, which is closed, and concluded the registration work was too.

WHAT THIS HOLDS, AND THE SHAPE OF IT
    The rule, not a list of the eight sites: no mention of `GST-16` is within 200 characters of the word
    "registration". It is a proximity rule because that is the exact confusion (an id sitting beside the thing it was
    wrongly used to name), and it is a rule over the tree, so a ninth comment written next year is caught the same
    way. The prose that replaced the id says "attributing each document to a registration" and points at the ledger
    by its title, which carries no id and so cannot be confused with an audit finding.

    It does NOT say that every quoted id is correct. A prose id has no generic detector; this pins the one collision
    that was found.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
THIS_FILE = Path(__file__).resolve()
WEB = REPO / "apps" / "web"

NEIGHBOURHOOD = 200
ID = "GST-16"

#: Never a source file, whatever root the walk reaches them from.
SKIP_PARTS = {"node_modules", "__pycache__", ".next", "out", ".venv", "venv", "site-packages", ".hypothesis"}


def _files() -> list[Path]:
    """Every file where a comment can quote a finding id: the design record, the whole API, and the web's source
    directories. Listed by what they are rather than by name, so a new module is covered the day it is written."""
    found: list[Path] = [REPO / "CLAUDE.md"]
    found += list(API.rglob("*.py"))
    for sub in ("app", "components", "lib", "scripts"):
        root = WEB / sub
        if root.is_dir():
            for pattern in ("*.ts", "*.tsx"):
                found += list(root.rglob(pattern))
    return [p for p in found
            if p.is_file() and p.resolve() != THIS_FILE and not (SKIP_PARTS & set(p.relative_to(REPO).parts))]


@functools.lru_cache(maxsize=1)
def _scan() -> tuple[int, tuple[tuple[Path, str], ...]]:
    """(how many files were read, [(file, its text with whitespace collapsed)] for those that mention the id). Read
    once and shared, because every test below asks the same question of the same tree."""
    read = 0
    mentioning: list[tuple[Path, str]] = []
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        read += 1
        if ID in text:
            mentioning.append((path, re.sub(r"\s+", " ", text)))
    return read, tuple(mentioning)


def _mentions() -> list[tuple[Path, str]]:
    found = []
    for path, flat in _scan()[1]:
        for m in re.finditer(re.escape(ID) + r"\b", flat):
            found.append((path, flat[max(0, m.start() - NEIGHBOURHOOD): m.end() + NEIGHBOURHOOD]))
    return found


def test_the_scan_reads_the_tree_and_finds_the_validator_finding_it_is_allowed_to_find():
    """Not vacuous: `GST-16` still names the GSTR-1 validator finding in the web code, so a scan that found nothing
    would be a scan that read nothing."""
    assert _scan()[0] > 500, "the scan found almost no files; the rule below would pass over nothing"
    assert any("validator" in window.lower() for _path, window in _mentions()), (
        "no mention of GST-16 sits beside the word validator any more; if the web comments were reworded, "
        "update this premise, do not delete the test")


def test_gst_16_is_never_used_for_attributing_documents_to_a_registration():
    offenders = [(p, w) for p, w in _mentions() if re.search(r"registration", w, re.IGNORECASE)]
    assert not offenders, (
        "GST-16 is the audit record's finding that the GSTR-1 validator did not run on the CA's path. It is not "
        "the work of attributing each invoice, bill and note to a GST registration, which has no audit id (it is "
        "an open-items ledger line titled \"Attribute each invoice, bill and note to a GST registration\"). "
        "Say \"attributing each document to a registration\" instead. Found:\n"
        + "\n".join(f"  {p.relative_to(REPO)}: ...{w[:260]}..." for p, w in offenders))


@pytest.mark.parametrize("phrase", ["GST-16 is open", "GST-16 retires", "GST-16's caveat", "GST-16 is what"])
def test_none_of_the_old_phrasings_comes_back(phrase):
    """The four spellings that were in use. They are covered by the rule above whenever 'registration' is nearby;
    this names them so a rewording that moves the word away still fails."""
    hits = [p for p, flat in _scan()[1] if phrase in flat]
    assert not hits, f"{phrase!r} is back in {[str(h.relative_to(REPO)) for h in hits]}"
