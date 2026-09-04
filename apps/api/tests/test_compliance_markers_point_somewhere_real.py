"""Every TODO(compliance) marker names a doc section that exists.

WHY THIS EXISTS

    The codebase had ZERO TODO/FIXME markers before 2026-09-04 — backend and
    frontend alike — and that was deliberate: it explains things in prose
    comments beside the code rather than leaving undated stubs.

    `TODO(compliance)` is a deliberate exception, and it earns the exception
    only by being scoped: each marker names the file under docs/compliance/
    that explains the registration, empanelment or licence gating that piece
    of work. A marker with no destination is the thing this convention exists
    to avoid — it decays into the usual undifferentiated TODO sludge that
    nobody can act on and nobody dares delete.

    So the rule this test enforces is narrow and mechanical: if you write the
    marker, it must point at a doc file that is really there. Renaming a doc
    without repointing its markers fails here rather than silently orphaning
    them, which is the failure mode a grep-based convention actually has.

    It deliberately does NOT check the reverse direction. A doc section with
    no marker is fine — several describe things with no natural code anchor
    at all (DPDP obligations, GSP commercial terms).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
API = REPO / "apps" / "api"
WEB = REPO / "apps" / "web"

MARKER = re.compile(r"TODO\(compliance\):\s*(\S+)")


def _sources():
    for root, patterns in ((API, ("**/*.py",)), (WEB, ("**/*.ts", "**/*.tsx"))):
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.glob(pattern):
                parts = set(path.parts)
                if parts & {"node_modules", ".next", "out", "__pycache__", ".venv"}:
                    continue
                if path.name == Path(__file__).name:
                    continue
                yield path


def test_every_compliance_marker_names_a_doc_that_exists():
    problems: list[str] = []
    found = 0
    for path in _sources():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "TODO(compliance)" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "TODO(compliance)" not in line:
                continue
            found += 1
            m = MARKER.search(line)
            rel = path.relative_to(REPO)
            if not m:
                problems.append(
                    f"{rel}:{lineno} — TODO(compliance) with no doc path. "
                    f"Write `TODO(compliance): docs/compliance/NN-name.md`."
                )
                continue
            target = m.group(1).rstrip(".,;:")
            if not target.startswith("docs/compliance/"):
                problems.append(
                    f"{rel}:{lineno} — points at {target!r}, which is not under "
                    f"docs/compliance/."
                )
            elif not (REPO / target).is_file():
                problems.append(
                    f"{rel}:{lineno} — points at {target!r}, which does not exist. "
                    f"If a doc was renamed, repoint the marker."
                )
    assert not problems, "\n".join(problems)
    # A bare-zero result would pass vacuously and hide a broken collector.
    assert found > 0, "no TODO(compliance) markers found at all — collector broken?"


def test_the_docs_directory_is_actually_there():
    """The markers are worthless if the directory they point into is gone."""
    docs = REPO / "docs" / "compliance"
    assert docs.is_dir(), f"{docs} is missing"
    assert (docs / "README.md").is_file(), "docs/compliance/README.md is the index"
