"""The notes a person on call reads must agree with what was measured and with the pipeline that exists (ops-33).

THREE STATEMENTS THAT MISLED, AND THE RULE EACH BREAKS
    1. THE COLD START. `docs/plan/THE-PLAN.md` called it "the ten-second cold start" and the wake workflow's own
       comment said "up to ~50s", while `scripts/smoke_api.py` had MEASURED 56.55 s on 2026-09-06 (and its
       docstring and `tests/test_smoke_api_script.py` say so). A stated duration may not be shorter than the
       measured one, and the ping's timeout has to exceed it or the first request reports a healthy service down.
    2. THE MINUTES. Four workflow comments and a CI script's docstring said the account "hit 100% of its 2,000
       included Actions minutes on 16 Aug 2026" and used that to justify how CI is shaped, while the wake
       workflow says the repository is public, where minutes are free — and it is (GitHub's API answers
       `private: false`). A comment may not assert a minutes budget that the repository's own visibility
       refutes. What survives is the real reason: the wait and the stale verdict, not the bill.
    3. THE MIGRATIONS. `core/schema_guard.py` said nothing applies migrations automatically and "that has always
       been a separate, manual step", while backend-ci.yml has had a `deploy-migrations` job that runs
       `apply_migrations.py` on every push to main. A note naming a job must name one that exists.

WHAT THIS DOES NOT DO
    It cannot ask GitHub whether the repository is public — that is a network call and this suite is mock-mode.
    It asserts what the repository's OWN files say about it, so a later change to one without the other fails.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"
WAKE = WORKFLOWS / "wake-before-scheduler.yml"
BACKEND_CI = WORKFLOWS / "backend-ci.yml"
SMOKE = REPO / "apps" / "api" / "scripts" / "smoke_api.py"
PLAN = REPO / "docs" / "plan" / "THE-PLAN.md"
SCHEMA_GUARD = REPO / "apps" / "api" / "core" / "schema_guard.py"
CI_SCRIPTS = REPO / "apps" / "api" / "scripts" / "ci"

_NUMBER_WORDS = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}


def _measured_cold_start_seconds() -> float:
    """The figure `wake()` records in its own docstring — the source, not a copy of it here."""
    m = re.search(r"(\d+\.\d+)s on 2026-09-06", SMOKE.read_text(encoding="utf-8"))
    assert m, "smoke_api.wake() no longer records the measured cold start — this guard has nothing to hold"
    return float(m.group(1))


def _stated_cold_start_durations(text: str) -> list[float]:
    """Every duration `text` attaches to a cold start, in seconds: "56.55s", "~50s", "ten-second cold start"."""
    found = [float(n) for n in re.findall(
        r"(?:cold[- ]start)[^.]{0,120}?(\d+(?:\.\d+)?)\s*(?:s|seconds)\b", text, re.I)]
    found += [float(_NUMBER_WORDS[w.lower()]) for w in re.findall(
        r"\b(" + "|".join(_NUMBER_WORDS) + r")[- ]seconds?\s+(?:cold[- ]start|wake)", text, re.I)]
    found += [float(n) for n in re.findall(r"(\d+)[- ]seconds?\s+cold[- ]start", text, re.I)]
    return found


# ── 1. the cold start ───────────────────────────────────────────────────────────

def test_the_measured_cold_start_is_the_figure_the_smoke_script_recorded():
    assert _measured_cold_start_seconds() > 30, "a 'cold start' under half a minute is not the free-tier wake"


@pytest.mark.parametrize("path", [PLAN, WAKE], ids=lambda p: p.name)
def test_a_stated_cold_start_is_not_shorter_than_the_measured_one(path):
    measured = _measured_cold_start_seconds()
    stated = _stated_cold_start_durations(path.read_text(encoding="utf-8"))
    assert stated, f"{path.name} states no cold-start duration — it used to, and this must still hold one"
    too_short = [s for s in stated if s < measured]
    assert not too_short, (
        f"{path.name} says a cold start takes {too_short} s; scripts/smoke_api.py measured {measured} s")


def test_the_wake_ping_waits_longer_than_the_measured_cold_start():
    """Not a note — the timeout itself. The first ping is the one that pays the cold start, and failing it
    reports a healthy service as down with nobody watching."""
    text = "\n".join(l for l in WAKE.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))
    limits = [int(n) for n in re.findall(r"--max-time\s+(\d+)", text)]
    assert limits, "the wake workflow no longer sets --max-time"
    assert all(l > _measured_cold_start_seconds() for l in limits), limits


# ── 2. the minutes ──────────────────────────────────────────────────────────────

def _ci_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(CI_SCRIPTS.glob("*.py"))


def test_the_repository_says_it_is_public_where_minutes_are_free():
    text = WAKE.read_text(encoding="utf-8")
    assert re.search(r"repository is public", text) and re.search(r"minutes are free", text)


def test_no_ci_file_claims_an_actions_minutes_budget():
    claims = []
    for path in _ci_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"included\s+Actions|hit\s+\d+%\s+of\s+its", line):
                claims.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert not claims, (
        "a file asserts an Actions-minutes budget, which the repository being public refutes:\n  "
        + "\n  ".join(claims))


# ── 3. the migrations ───────────────────────────────────────────────────────────

def _job_block(text: str, job: str) -> str:
    m = re.search(rf"^  {re.escape(job)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text, re.S | re.M)
    assert m, f"backend-ci.yml has no job `{job}`"
    return m.group(1)


def test_the_job_schema_guard_names_exists_and_applies_the_migrations():
    doc = SCHEMA_GUARD.read_text(encoding="utf-8").split('"""')[1]
    named = re.findall(r"`(deploy-migrations)`", doc)
    assert named, "schema_guard no longer names the job that applies migrations"
    block = _job_block(BACKEND_CI.read_text(encoding="utf-8"), named[0])
    assert "apply_migrations.py" in block
    assert "refs/heads/main" in block, "the job must be the one that runs on a push to main"


def test_schema_guard_does_not_call_the_application_of_migrations_a_manual_step_today():
    doc = SCHEMA_GUARD.read_text(encoding="utf-8").split('"""')[1]
    assert not re.search(r"nothing applies", doc)
    assert not re.search(r"(has|have) always been a separate, manual", doc)
