"""A SENTENCE THE SERVER WRITES FOR A SCREEN IS WRITTEN FOR THE PERSON READING IT (POST-A-554, 23-11-2026).

Fourteen sentences the API serves, and a screen shows as they come, explained an unverified figure in the words of the
container the code was written in: "this environment refuses outbound requests", "refused at this environment's egress
proxy", "could not be reached from this environment". A CA reading that on the live product is in no such environment, and
the sentence reads as a fault in their own set-up. What each note is for is one fact, that nobody has read the figure or the
layout against the Act, the rule, the form or the portal, and one instruction, to check it before relying on it. Three of
them also told the reader that the figure "is pinned by a test", which is a fact about this repository and not about the law.

THE RULE. No string the server can send (every string literal in `apps/api` outside its tests and migrations, docstrings and
bare-string statements left alone, because nothing sends those) talks about an environment, a container, a sandbox, a proxy
or egress, or says that a figure is pinned by a test. The list of exceptions is empty.

The browser's own copy of this rule is `apps/web/scripts/a-note-on-a-screen-is-written-for-the-person-reading-it.test.ts`.

WHAT THIS DOES NOT SEE: a sentence assembled from pieces at run time, a sentence in SQL (a migration's RAISE), and a comment
or docstring, which say such things freely and rightly: that is where a developer is told why a figure is graded [S].
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API = Path(__file__).resolve().parent.parent

#: The container's words, and the one phrase about the repository's own tests.
BUILD_WORDS = re.compile(
    r"\bthis environment\b|\bthis container\b|\bthis sandbox\b|\begress\b|\benvironment(?:'s)? proxy\b"
    r"|\bpinned (?:exactly )?by a test\b",
    re.I,
)

_SKIP_DIRS = {"tests", "migrations", "venv", ".venv", "__pycache__"}


def _served_strings(source: str):
    """Every string literal that is not a docstring or a bare-string statement, as (line, text)."""
    tree = ast.parse(source)
    silent = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in silent:
            yield node.lineno, node.value


def _hits(source: str):
    return [(line, text) for line, text in _served_strings(source) if BUILD_WORDS.search(text)]


def _sources():
    for path in sorted(API.rglob("*.py")):
        if _SKIP_DIRS.intersection(path.relative_to(API).parts):
            continue
        yield path


def test_no_string_the_server_can_send_talks_about_where_the_code_was_written():
    found = []
    for path in _sources():
        for line, text in _hits(path.read_text(encoding="utf-8")):
            found.append(f"{path.relative_to(API)}:{line}: {text[:140]}")
    assert found == [], (
        "say what the reader needs: that the figure or layout has not been read against its source, and to check it "
        "before relying on it\n" + "\n".join(found)
    )


def test_the_scan_reads_the_server_and_not_an_empty_folder():
    files = list(_sources())
    assert len(files) > 400, f"only {len(files)} source files were read"
    strings = sum(1 for path in files[:50] for _ in _served_strings(path.read_text(encoding="utf-8")))
    assert strings > 500, "the first fifty files hold almost no string literals: the reader is not reading"


def test_the_rule_catches_the_sentences_that_were_served_and_spares_the_ones_that_replace_them():
    was = [
        'NOTE = "recorded from knowledge, not read off the Act — this environment refuses outbound requests."',
        'NOTE = "every .gov.in is refused at this environment\'s egress proxy."',
        'NOTE = "which could not be reached from this environment. Check them against the utility."',
        'NOTE = "Egress is refused here, so the section could not be read against the Act."',
        'NOTE = "egress to the primary specification is blocked in this environment"',
        'NOTE = "Each is pinned exactly by a test. Check the figures."',
        'NOTE = ("It is pinned by a "\n        "test. Check it.")',
    ]
    for source in was:
        assert _hits(source), f"not caught: {source}"
    now = [
        'NOTE = "recorded from knowledge and has not been read off the Act. Check the figures against the Finance Act."',
        'NOTE = "has not been verified against the utility; check it there before uploading."',
        'MESSAGE = "Set SUPABASE_URL in the environment before starting the server."',
    ]
    for source in now:
        assert not _hits(source), f"caught a sentence that says nothing about the container: {source}"


def test_a_docstring_and_a_comment_may_still_say_why_a_figure_is_graded():
    source = (
        '"""Every figure is [S]-graded: egress is refused at this environment\'s proxy."""\n'
        "# this environment cannot reach incometax.gov.in\n"
        "def f():\n"
        '    """Pinned by a test, because this environment cannot read the Act."""\n'
        '    "a bare string: this environment"\n'
        '    return "The figure has not been read against the Act."\n'
    )
    assert _hits(source) == []
