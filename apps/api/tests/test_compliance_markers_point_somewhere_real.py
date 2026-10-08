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

    ONE LIST IS CHECKED BOTH WAYS: docs/compliance/README.md names the files
    that carry a marker ("Where the code marks this"). It said "Eleven markers
    today" and named eleven files while fourteen carried one, so a reader
    following it never reached three of them. A count in prose goes stale at
    the next marker; the list is the rule, so every file that carries a marker
    must be named there, and every code file the section names must carry one.
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


# ── the README's list of marker files, checked in both directions ─────────────

README = REPO / "docs" / "compliance" / "README.md"
FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
BACKTICKED = re.compile(r"`([^`\n]+)`")
BRACES = re.compile(r"\{([^{}]+)\}")


def expand_braces(spec: str) -> list[str]:
    """`a/{b,c}.py` -> [`a/b.py`, `a/c.py`]; repeated groups expand left to right."""
    m = BRACES.search(spec)
    if not m:
        return [spec]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(spec[: m.start()] + alt.strip() + spec[m.end():]))
    return out


def named_paths(markdown: str) -> set[str]:
    """Every backticked path in the text with fenced blocks removed first (an
    unbalanced quote inside a fence would otherwise flip the pairing of every
    backtick after it), braces expanded."""
    names: set[str] = set()
    for span in BACKTICKED.findall(FENCE.sub("", markdown)):
        names.update(expand_braces(span))
    return names


def section(markdown: str, heading: str) -> str:
    """The text under a '## <heading>' up to the next '## '."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", markdown, re.MULTILINE)
    if not m:
        return ""
    rest = markdown[m.end():]
    end = re.search(r"^##\s", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def marker_files() -> dict[str, Path]:
    """Path relative to its app (the form the README uses) -> file, for every non-test
    source carrying the marker."""
    found: dict[str, Path] = {}
    for path in _sources():
        if "tests" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "TODO(compliance)" in text:
            root = API if API in path.parents else WEB
            found[path.relative_to(root).as_posix()] = path
    return found


def unlisted(files: set[str], readme_section: str) -> list[str]:
    named = named_paths(readme_section)
    return sorted(f for f in files if f not in named)


def listed_but_not_marked(files: set[str], readme_section: str) -> list[str]:
    """Code files the section names that carry no marker (tests and prose are not code
    the section is claiming a marker in)."""
    return sorted(n for n in named_paths(readme_section)
                  if n.endswith(".py") and not n.startswith("tests/") and n not in files)


def test_every_file_carrying_a_marker_is_named_in_the_compliance_readme():
    files = set(marker_files())
    text = section(README.read_text(encoding="utf-8"), "Where the code marks this")
    assert text, "docs/compliance/README.md lost its 'Where the code marks this' section"
    missing = unlisted(files, text)
    assert not missing, (
        "these files carry a TODO(compliance) marker and docs/compliance/README.md does "
        "not name them (the section lists files, not a count): " + ", ".join(missing))


def test_every_code_file_the_readme_names_as_a_marker_site_carries_one():
    files = set(marker_files())
    text = section(README.read_text(encoding="utf-8"), "Where the code marks this")
    stale = listed_but_not_marked(files, text)
    assert not stale, ("docs/compliance/README.md names these as marker sites and they carry "
                       "no TODO(compliance): " + ", ".join(stale))


def test_the_readme_list_check_is_not_vacuous():
    files = marker_files()
    assert len(files) >= 10, f"only {len(files)} marker files found: collector broken?"
    text = section(README.read_text(encoding="utf-8"), "Where the code marks this")
    assert len(named_paths(text)) >= 10, "the README's list was not parsed"
    # the three the README used to omit: its list is a rule, not a snapshot
    for rel in ("domain/tds/section_rates.py", "services/audit_service.py",
                "domain/dpdp/retention.py"):
        assert rel in files, f"{rel} no longer carries a marker; if intentional, update this"


def test_the_list_check_reads_braces_and_ignores_fences():
    assert expand_braces("domain/payroll/{ecr,esic}.py") == ["domain/payroll/ecr.py",
                                                            "domain/payroll/esic.py"]
    assert expand_braces("a/{b,c}/{d,e}.py") == ["a/b/d.py", "a/b/e.py", "a/c/d.py", "a/c/e.py"]
    # a quote inside a fence must not flip the backtick pairing of what follows it
    md = "```\ngrep -rn 'TODO(compliance)' `apps\n```\nSee `a/{b,c}.py` and `d.py`.\n"
    assert named_paths(md) == {"a/b.py", "a/c.py", "d.py"}
    # a file that carries a marker and is not named fails, and so does a named one with none
    body = "Markers: `x/a.py` and `x/{b}.py`."
    assert unlisted({"x/a.py", "x/b.py", "x/c.py"}, body) == ["x/c.py"]
    assert listed_but_not_marked({"x/a.py"}, body) == ["x/b.py"]
    # tests are not marker sites
    assert listed_but_not_marked(set(), "`tests/test_x.py`") == []
