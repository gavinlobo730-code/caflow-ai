"""No `apt-get update` in a workflow may be taken down by a repository we do not use.

WHAT HAPPENED, TWICE, FOR THE SAME REASON
    `apt-get update` exits 100 if ANY configured source is inconsistent, and the
    GitHub runner image ships several this repository has no use for. On
    2026-09-09 Google's Chrome apt repository served a Packages.gz whose SHA256
    was bc1428ab… while its own Release file said 233e56de…

    First it took down `migration apply — real Postgres 16`, a REQUIRED check,
    on a pull request touching neither Chrome nor apt — twice, byte-identically,
    so not a blip. That was fixed by dropping dl.google.com sources before the
    update.

    The fix went into ONE of the two steps that run apt. The other —
    `apply pending migrations — production`, which runs only on a push to main —
    has its own runner and its own copy, and it failed the same way on the
    Phase 5 merge. Its next step, the one that actually applies migrations to
    the live database, was SKIPPED. So migrations 349, 350 and 351 sat unapplied
    while the code that depends on their columns was already deployed, and
    nothing said so: the failure was in a job nobody watches, on main, after the
    PR had gone green and been merged.

WHY THIS IS A TEST AND NOT A THIRD COMMENT
    Two copies of a rule drift, and this one drifted the same day it was
    written. GitHub Actions has no shared-step primitive short of a composite
    action, so the copies stay — and the RULE is asserted here instead: every
    apt-get update in every workflow drops the third-party sources first.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[3] / ".github" / "workflows").glob("*.yml"))

#: What a hardened step looks like: the sources are removed by CONTENT, so the
#: .list/.sources filename format does not matter, and `xargs -r` keeps grep's
#: exit 1 (no match) from aborting the step under `set -e`.
_DROP = re.compile(r"grep\s+-rlE?\s+'[^']*dl\\?\.google\\?\.com")


def _without_comments(text: str) -> str:
    """Full-line YAML comments removed, blank lines kept so nothing shifts.

    The comments here DESCRIBE apt-get update at length, and a scan that reads
    them finds the words in prose that explains the fix rather than in the step
    that needs it — the same way an apostrophe inside a comment made a whole
    database write invisible to the frontend column scanner (Phase 5).
    """
    return "\n".join("" if ln.lstrip().startswith("#") else ln
                      for ln in text.splitlines())


def _steps_running_apt(text: str) -> list[str]:
    """Each `run:` block that calls apt-get update, as its own chunk of text."""
    blocks, current = [], []
    for line in _without_comments(text).splitlines():
        if re.match(r"\s*- name:", line) or re.match(r"\s*- uses:", line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [b for b in blocks if "apt-get update" in b]


def test_the_workflows_are_where_this_test_thinks_they_are():
    """Vacuity guard. A moved directory would leave every assertion below
    iterating over nothing and reporting green."""
    assert WORKFLOWS, "no workflow files found — this test would check nothing"
    assert any("backend-ci" in p.name for p in WORKFLOWS)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_apt_update_drops_third_party_sources_first(path: Path):
    text = path.read_text(encoding="utf-8")
    unhardened = [
        b.splitlines()[0].strip()
        for b in _steps_running_apt(text)
        if not _DROP.search(b)
    ]
    assert not unhardened, (
        f"{path.name}: these steps run `apt-get update` without dropping the "
        f"third-party sources first, so a repository this project does not use "
        f"can fail them: {unhardened}. Copy the drop from the 'Install psql "
        f"client' step in the migrations job."
    )


def test_the_production_apply_step_is_one_of_the_ones_covered():
    """Named pin. The generic scan above would still pass if the production
    job — the one whose failure is silent, because it runs after the merge —
    stopped calling apt at all AND stopped applying migrations with it."""
    backend = next(p for p in WORKFLOWS if p.name == "backend-ci.yml")
    text = backend.read_text(encoding="utf-8")
    assert "apply pending migrations — production" in text
    apt_steps = _steps_running_apt(text)
    assert len(apt_steps) >= 2, (
        "the production-apply job installs psql of its own, on its own runner. "
        "If that step has gone, check what applies migrations to production now."
    )


def test_the_drop_is_narrow_enough_to_still_fail_on_a_real_problem():
    """The point is NOT to make apt failures non-fatal. postgresql-client comes
    from the Ubuntu archive, and if THAT cannot be fetched these jobs must not
    go on to report a green migration ratchet — or, worse, to apply migrations
    to production with a broken toolchain."""
    backend = next(p for p in WORKFLOWS if p.name == "backend-ci.yml")
    text = backend.read_text(encoding="utf-8")
    for block in _steps_running_apt(text):
        assert "|| true" not in block, "an apt failure has been made non-fatal"
        assert "-y --no-install-recommends postgresql-client" in block
        # The pattern is written for grep -E, so the dots are backslash-escaped
        # in the file; _DROP is what knows that. A plain substring check here
        # would look for `dl.google.com` and never find it.
        assert "sources.list" not in block or _DROP.search(block), (
            "only the third-party sources may be removed — the Ubuntu archive "
            "must be left alone")
