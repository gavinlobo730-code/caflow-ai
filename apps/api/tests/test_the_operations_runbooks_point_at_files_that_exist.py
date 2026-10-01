"""A runbook is only as good as the files it names (ops-09, ops-10, ops-32).

`docs/operations/` holds what a person on call follows: which script to run, which test pins a claim, which
file to read. A path that has moved sends them to a 404 at the moment they are least able to go looking, and
a runbook that names a script which was later renamed reads exactly as it did the day it was true. So every
backticked repository path in those documents must resolve to a real file.

The same idea as `test_compliance_markers_point_somewhere_real.py`, applied to the notes that are not
statutory: derive the paths from the text, resolve each against the places this repository keeps files, and
fail on one that does not. A bare file name (`error.tsx`) or an identifier (`core/observability.init_error_
reporting`) is not a path and is not asked.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOCS = sorted((REPO / "docs" / "operations").glob("*.md"))
# Where a path written in a runbook may be rooted: the repository, or the app the sentence is about.
ROOTS = (REPO, REPO / "apps" / "api", REPO / "apps" / "web")


# A path is what it looks like: a known top-level directory of this repository (or of an app), then segments,
# then a file suffix. Found anywhere in the text — prose, a table cell, a backtick, a fenced command — because
# the commands a person pastes are the ones that must not rot.
_PATH = re.compile(
    r"(?<![\w/.\-])((?:apps|docs|scripts|tests|lib|components|app|core|\.github)/[\w./\-]*[\w]\.(?:md|py|sql|tsx|ts|mjs|yml|yaml|json|toml)(?![\w]))"
)


def _paths(text: str) -> list[str]:
    return _PATH.findall(text)


def _resolves(path: str) -> bool:
    return any((root / path).is_file() for root in ROOTS)


def test_there_are_runbooks_and_they_name_paths():
    """Vacuity guard: a glob that finds nothing would make every test below pass over an empty list."""
    assert len(DOCS) >= 3
    assert sum(len(_paths(d.read_text(encoding="utf-8"))) for d in DOCS) >= 10


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_path_a_runbook_names_exists(doc):
    missing = [p for p in dict.fromkeys(_paths(doc.read_text(encoding="utf-8"))) if not _resolves(p)]
    assert not missing, f"{doc.name} names files that do not exist: {missing}"


def test_the_operations_guide_links_to_the_runbooks():
    text = (REPO / "docs" / "BETA_OPERATIONS.md").read_text(encoding="utf-8")
    for runbook in ("docs/operations/error-tracking.md", "docs/operations/database-monitoring.md"):
        assert runbook in text, f"BETA_OPERATIONS.md does not send a reader to {runbook}"
        assert (REPO / runbook).is_file()
