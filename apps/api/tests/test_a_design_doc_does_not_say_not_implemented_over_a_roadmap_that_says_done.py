"""A design record that says "not implemented" must not carry a roadmap that says "done".

WHY THIS EXISTS

    `docs/architecture/06-multi-currency-phase0.md` opened with "FROZEN v1.0 -
    DESIGN ONLY. Not implemented." while its own Roadmap marked Phases 0.5 to 5
    "(done)" and `06a` to `06e` described what was built. The design body is
    change-controlled and rightly frozen, which is exactly why the status line
    over it went stale: nobody reopens a frozen file to correct a sentence. A
    reader of the first paragraph was told the engine is single-currency and
    nothing is built, and was wrong.

    The rule is about the DIRECTORY, not that one file: a document's preamble
    (everything before its first second-level heading) and its own Roadmap
    section are two statements about the same thing, and they may not
    contradict each other. It does not decide which is right; it refuses the
    contradiction, and whoever resolves it reads the code.

    It reads no code and no other document, so it cannot be satisfied by
    editing the wrong side: a banner that says "implemented" is fine, a roadmap
    with no "(done)" is fine, both together are the defect.
"""
from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs" / "architecture"

# The two phrasings a preamble uses to disown the implementation.
UNBUILT_CLAIM = re.compile(r"design\s+only|not\s+implemented", re.IGNORECASE)
DONE_MARK = re.compile(r"\(done\)", re.IGNORECASE)
H2 = re.compile(r"^##\s+\S")
ROADMAP_H2 = re.compile(r"^##\s+.*roadmap", re.IGNORECASE)


def preamble(text: str) -> str:
    """Everything before the first '## ' heading: the title and the status line."""
    lines: list[str] = []
    for line in text.splitlines():
        if H2.match(line):
            break
        lines.append(line)
    return "\n".join(lines)


def roadmap(text: str) -> str:
    """The body of the '## ... Roadmap' section, up to the next '## ' heading."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if H2.match(line):
            if inside:
                break
            inside = bool(ROADMAP_H2.match(line))
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def contradiction(text: str) -> str | None:
    """A sentence naming the contradiction, or None if the document is consistent."""
    claim = UNBUILT_CLAIM.search(preamble(text))
    done = len(DONE_MARK.findall(roadmap(text)))
    if claim and done:
        return (
            f"the status line says {claim.group(0)!r} but the Roadmap marks {done} "
            f"item(s) '(done)'"
        )
    return None


def _docs() -> list[Path]:
    return sorted(DOCS.glob("*.md"))


def test_no_architecture_doc_disowns_what_its_own_roadmap_says_is_done():
    problems = []
    for path in _docs():
        why = contradiction(path.read_text(encoding="utf-8"))
        if why:
            problems.append(f"{path.relative_to(DOCS.parents[1])}: {why}. Resolve it "
                            f"against the code; a frozen design body is not rewritten, "
                            f"its status banner is.")
    assert not problems, "\n".join(problems)


def test_the_collector_is_not_vacuous():
    """The multi-currency record is the one with a roadmap full of '(done)': if the
    parser stops finding it, the test above would pass over an empty set."""
    text = (DOCS / "06-multi-currency-phase0.md").read_text(encoding="utf-8")
    assert len(_docs()) >= 8, "the architecture directory looks emptied"
    assert len(DONE_MARK.findall(roadmap(text))) >= 5, "the 06 roadmap was not parsed"
    assert preamble(text).strip().startswith("# 06"), "the 06 preamble was not parsed"


def test_the_rule_fires_on_the_original_defect_and_stays_quiet_on_its_fixes():
    stale = (
        "# 06 - Multi\n\n**Status: FROZEN v1.0 - DESIGN ONLY. Not implemented.**\n\n"
        "## Scope\n\ntext\n\n## Roadmap\n\n- Phase 1 (done): x\n- Phase 2 (done): y\n"
    )
    assert contradiction(stale) is not None
    # the banner corrected
    assert contradiction(stale.replace("DESIGN ONLY. Not implemented.", "IMPLEMENTED.")) is None
    # or the roadmap corrected
    assert contradiction(stale.replace("(done)", "(planned)")) is None
    # "not implemented" in the BODY (a limitation of one capability) is not the banner
    body = "# T\n\nStatus: implemented.\n\n## Scope\n\nCapability B (not implemented).\n\n## Roadmap\n\n- (done)\n"
    assert contradiction(body) is None
    # a "(done)" outside the Roadmap section is not the roadmap
    elsewhere = "# T\n\nDESIGN ONLY.\n\n## Notes\n\nPhase 1 (done)\n\n## Roadmap\n\n- Phase 1 (planned)\n"
    assert contradiction(elsewhere) is None
