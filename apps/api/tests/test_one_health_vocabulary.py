"""The client-health model has ONE set of dimension names and ONE grade table.

WHAT WENT WRONG (sweep-client-misc-04, sweep-health-hub-06, sweep-client-purchases-05)

The seven Product Bible Chapter 16 dimensions were named four ways in the
browser: the firm-level detail page ("Compliance Health … Client
Responsiveness"), the client Health tab's cards — which read the LEGACY flat
columns and so said "Relationship Risk", "Financial Risk" and "Engagement
Health", none of which is a dimension of this model (`relationship_risk_score`
is written as a constant 100) — that tab's Add Override picker, and the
Overview card. A CA wanting to override the card they could see found no entry
of that name to choose.

And the score badge graded on a ladder of its own (80/60/40: Healthy, Fair, At
Risk, Critical) while the Health page one click away rendered the engine's
grade (80/65/50/35, five words). The same 73 read "Fair" and "Good".

WHY THE GUARD IS WRITTEN HERE

`domain/health/scoring.py` owns the model. `apps/web/lib/health/vocabulary.ts`
is the browser's one copy, and it is pinned FROM THIS SIDE — the Schedule III
caption lesson: a guard written in apps/web would assert the browser against a
copy of itself and pass whenever both drifted together.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from domain.health import scoring

_WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
_VOCAB = _WEB / "lib" / "health" / "vocabulary.ts"

#: Every screen that names a dimension or shows a grade. Each must take both
#: from the one module rather than spelling them.
_SCREENS = {
    "client Health tab": _WEB / "app" / "clients" / "[id]" / "health" / "page.tsx",
    "firm-level detail": _WEB / "app" / "health" / "[client_id]" / "HealthDetailClient.tsx",
    "health list": _WEB / "app" / "health" / "page.tsx",
    "score badge": _WEB / "components" / "HealthBadge.tsx",
    "overview labels": _WEB / "lib" / "services" / "health-score-compute.ts",
    "executive ring": _WEB / "app" / "executive-dashboard" / "page.tsx",
}


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


@pytest.fixture(scope="module")
def vocab() -> str:
    assert _VOCAB.exists(), f"{_VOCAB} has moved — update this guard, do not delete it"
    return _strip_comments(_VOCAB.read_text(encoding="utf-8"))


def _dimensions(src: str) -> list[tuple[str, str, int]]:
    body = re.search(r"export const HEALTH_DIMENSIONS[^=]*=\s*\[(.*?)\];", src, re.S)
    assert body, "HEALTH_DIMENSIONS not found — the guard cannot check what it cannot read"
    rows = re.findall(
        r'\{\s*key:\s*"([a-z_]+)",\s*label:\s*"([^"]+)",\s*weightBp:\s*(\d+)', body.group(1))
    return [(k, label, int(bp)) for k, label, bp in rows]


def _bands(src: str) -> list[tuple[int, str]]:
    body = re.search(r"export const HEALTH_GRADE_BANDS[^=]*=\s*\[(.*?)\];", src, re.S)
    assert body, "HEALTH_GRADE_BANDS not found — the guard cannot check what it cannot read"
    return [(int(m), g) for m, g in
            re.findall(r'\{\s*min:\s*(\d+),\s*grade:\s*"([^"]+)"\s*\}', body.group(1))]


# ── the browser module IS the engine's vocabulary ───────────────────────────

def test_the_scan_reads_all_seven_and_all_five(vocab):
    """A regex that stops matching passes while checking nothing — the main way
    a guard like this rots. So the counts are asserted before anything else."""
    assert len(_dimensions(vocab)) == len(scoring.DIMENSION_WEIGHTS_BP) == 7
    assert len(_bands(vocab)) == len(scoring.GRADE_BANDS) == 5


def test_every_dimension_has_the_engines_key_name_and_weight_in_order(vocab):
    engine = [(k, scoring.DIMENSION_LABELS[k], bp)
              for k, bp in scoring.DIMENSION_WEIGHTS_BP.items()]
    assert _dimensions(vocab) == engine


def test_the_engine_names_every_dimension_it_weighs():
    assert set(scoring.DIMENSION_LABELS) == set(scoring.DIMENSION_WEIGHTS_BP)
    assert len(set(scoring.DIMENSION_LABELS.values())) == 7, "two dimensions share a name"


def test_the_browser_bands_are_the_engines_bands(vocab):
    assert _bands(vocab) == list(scoring.GRADE_BANDS)


@pytest.mark.parametrize("score", range(-5, 106))
def test_the_browser_ladder_grades_every_score_as_the_engine_does(vocab, score):
    """Behaviour, not only shape: walk the browser's table the way
    `gradeForScore` does and compare it with the engine's own `grade`. 73 — the
    finding's score — is in here, and is "Good" on both."""
    browser = next((g for floor, g in _bands(vocab) if score >= floor), "Critical")
    assert browser == scoring.grade(score)


def test_seventy_three_is_good():
    """The finding's own number, pinned so the reason for all this is legible."""
    assert scoring.grade(73) == "Good"


def test_the_engine_grades_by_its_table():
    """`grade` walks GRADE_BANDS rather than restating it, so the table the
    browser is pinned to IS the rule and not a description of it."""
    for floor, band in scoring.GRADE_BANDS:
        assert scoring.grade(floor) == band


# ── no screen keeps a private copy ──────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(_SCREENS))
def test_each_screen_takes_its_words_from_the_one_module(name):
    src = _SCREENS[name].read_text(encoding="utf-8")
    assert "@/lib/health/vocabulary" in src, f"the {name} does not read the vocabulary"


@pytest.mark.parametrize("name", sorted(_SCREENS))
def test_no_screen_maps_a_dimension_to_a_label_of_its_own(name):
    """`compliance_health: "Compliance"` is the shape each private copy had.
    Comments are stripped first: the fix explains itself in prose."""
    code = _strip_comments(_SCREENS[name].read_text(encoding="utf-8"))
    for key in scoring.DIMENSION_WEIGHTS_BP:
        assert not re.search(rf'\b{key}\s*:\s*(\{{\s*label\s*:\s*)?"', code), (
            f"the {name} spells its own label for {key}")


@pytest.mark.parametrize("name", sorted(_SCREENS))
def test_no_screen_offers_a_legacy_column_as_a_dimension(name):
    code = _strip_comments(_SCREENS[name].read_text(encoding="utf-8"))
    for legacy in ("Relationship Risk", "Financial Risk", "Engagement Health", '"Fair"'):
        assert legacy not in code, f"the {name} still says {legacy}"


def test_no_second_ladder_survives_in_the_browser():
    """`scoreToLabel` was the badge's 80/60/40 ladder. Deleted rather than
    re-pointed, so a later import fails to compile instead of quietly grading
    on the wrong table again."""
    offenders = []
    for root in ("app", "components", "lib"):
        for path in (_WEB / root).rglob("*.ts*"):
            if "node_modules" in path.parts:
                continue
            if re.search(r"\bscoreToLabel\b", _strip_comments(path.read_text(encoding="utf-8"))):
                offenders.append(str(path.relative_to(_WEB)))
    assert offenders == []


def test_the_badge_prefers_the_servers_grade():
    """The pill and the page it links to must say the same word, and the page
    shows the SERVER's grade — so the pill takes it too where the caller has
    one, and both callers that hold a fetched score pass it."""
    badge = (_WEB / "components" / "HealthBadge.tsx").read_text(encoding="utf-8")
    assert "gradeOf(grade, score)" in badge
    for caller in (_WEB / "components" / "shell" / "ClientTopBar.tsx",
                   _WEB / "app" / "clients" / "[id]" / "overview" / "page.tsx"):
        src = caller.read_text(encoding="utf-8")
        assert re.search(r"<HealthBadge[^>]*\bgrade=\{", src, re.S), (
            f"{caller.name} renders the badge without the server's grade")
