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


# ── how a grade LOOKS: one table per look, and no page keeps a ladder of its own (POST-A-286, POST-A-287) ───────────────────────

#: Every page that prints a score or a grade. None may define its own colour function or badge table, and the two list pages may not
#: type the grade as the letters A to F, which the engine retired.
_SCORE_PAGES = {
    "health list": _WEB / "app" / "health" / "page.tsx",
    "at-risk list": _WEB / "app" / "health" / "at-risk" / "page.tsx",
    "critical list": _WEB / "app" / "health" / "critical" / "page.tsx",
    "firm-level detail": _WEB / "app" / "health" / "[client_id]" / "HealthDetailClient.tsx",
    "client Health tab": _WEB / "app" / "clients" / "[id]" / "health" / "page.tsx",
}
_GRADES = [band for _, band in scoring.GRADE_BANDS]


def _table(src: str, name: str) -> dict[str, str]:
    body = re.search(rf"export const {name}[^=]*=\s*\{{(.*?)\}};", src, re.S)
    assert body, f"{name} not found — the guard cannot check what it cannot read"
    return dict(re.findall(r'"([A-Za-z ]+)":\s*"([^"]+)"', body.group(1)))


@pytest.mark.parametrize("table", ["GRADE_BADGE_CLASS", "GRADE_TEXT_CLASS", "GRADE_BAR_CLASS", "GRADE_TONE"])
def test_each_look_has_one_entry_per_grade_of_the_engine_and_no_other(vocab, table):
    assert list(_table(vocab, table)) == _GRADES


def test_the_three_tones_read_the_grades_in_order_of_severity(vocab):
    tone = _table(vocab, "GRADE_TONE")
    assert [tone[g] for g in _GRADES] == ["ready", "ready", "attention", "attention", "problem"]


def test_the_classes_are_the_severity_tokens_and_each_look_has_five_different_ones(vocab):
    for table, prefix in (("GRADE_BADGE_CLASS", "bg-sev-"), ("GRADE_TEXT_CLASS", "text-sev-"), ("GRADE_BAR_CLASS", "bg-sev-")):
        classes = list(_table(vocab, table).values())
        assert all(prefix in c for c in classes), table
        assert len(set(classes)) == 5, f"two grades share a look in {table}"


def test_a_number_is_coloured_as_its_badge_is(vocab):
    """The 66 printed amber beside a blue badge, and the 45 printed amber beside a red-orange one."""
    badge, text = _table(vocab, "GRADE_BADGE_CLASS"), _table(vocab, "GRADE_TEXT_CLASS")
    for grade in _GRADES:
        assert re.search(r"text-sev-\w+$", badge[grade]).group(0) == text[grade], grade


@pytest.mark.parametrize("name", sorted(_SCORE_PAGES))
def test_no_score_page_keeps_a_colour_ladder_or_a_badge_table_of_its_own(name):
    code = _strip_comments(_SCORE_PAGES[name].read_text(encoding="utf-8"))
    assert "@/lib/health/vocabulary" in code, f"the {name} does not read the vocabulary"
    for private in ("function scoreColor", "function scoreBg", "function scoreBarColor", "function gradeBadge",
                    "function gradeBadgeColor", 'type Grade = "A"', '"bg-sev-ok-surface'):
        assert private not in code, f"the {name} defines its own: {private}"


def test_the_two_list_pages_ask_for_the_engines_word_whatever_the_stored_grade_is():
    """A stored row can carry a legacy letter or nothing: the page shows the grade of the score then, as the other three do."""
    for name in ("at-risk list", "critical list"):
        code = _strip_comments(_SCORE_PAGES[name].read_text(encoding="utf-8"))
        assert code.count("gradeOf(c.health_grade, c.overall_score)") == 2, f"{name}: the badge's class AND its word ask for the grade of the score"
        assert "{c.health_grade}" not in code, f"{name} prints the stored grade, which can be a legacy letter or nothing"
        assert "scoreTextClass(c.overall_score)" in code, name


def test_the_dashboard_ring_takes_its_colour_from_the_grade_tone_and_not_a_ladder_of_its_own():
    code = _strip_comments(_SCREENS["executive ring"].read_text(encoding="utf-8"))
    assert "gradeTone(gradeForScore(score))" in code
    assert 'band === "Good"' not in code, "the ring still branches on grade words itself"


def test_the_portfolio_bar_labels_are_built_from_the_engines_grades(vocab):
    """Healthy or Good, Needs Attention, At Risk, Critical: by INDEX into the grade table, so the words cannot drift from it."""
    body = re.search(r"export const PORTFOLIO_BAR_LABELS = \{(.*?)\} as const;", vocab, re.S)
    assert body, "PORTFOLIO_BAR_LABELS not found"
    assert re.search(r"healthy:\s*`\$\{HEALTH_GRADES\[0\]\} or \$\{HEALTH_GRADES\[1\]\}`", body.group(1))
    named = dict(re.findall(r"(\w+):\s*HEALTH_GRADES\[(\d)\]", body.group(1)))
    assert {k: _GRADES[int(i)] for k, i in named.items()} == {
        "needsAttention": "Needs Attention", "atRisk": "At Risk", "critical": "Critical"}
    assert _GRADES[0] == "Healthy" and _GRADES[1] == "Good"
    assert re.search(r"PORTFOLIO_UNSPLIT_HEALTHY_LABEL = `\$\{HEALTH_GRADES\[0\]\}, \$\{HEALTH_GRADES\[1\]\} or \$\{HEALTH_GRADES\[2\]\}`", vocab)


def test_each_portfolio_bar_takes_the_colour_of_its_own_grades_tone():
    """The Needs Attention bar was gold, 2.89:1 on white, and the next edit could put it back or draw At Risk green: the bar's colour is
    the tone of the grade it counts, through the one table, and the table maps each tone to its audited token."""
    code = _strip_comments(_SCREENS["executive ring"].read_text(encoding="utf-8"))
    for key, grade in (("healthy", "Good"), ("needs", "Needs Attention"), ("atRisk", "At Risk"), ("critical", "Critical")):
        assert re.search(rf'key: "{key}", label: [^,]+, count: [^,]+, color: TONE_COLOR\[gradeTone\("{grade}"\)\] \}}', code), (
            f"the {key} bar is not coloured by the tone of {grade}")
    assert "const TONE_COLOR: Record<HealthTone, string> = { ready: READY, attention: ATTENTION, problem: PROBLEM };" in code


def test_the_dashboard_spells_none_of_the_bar_labels_itself():
    code = _strip_comments(_SCREENS["executive ring"].read_text(encoding="utf-8"))
    for label in _GRADES:
        assert not re.search(rf"label=\{{`{label}\b", code), f"the dashboard spells the {label} bar itself"
    assert code.count("PORTFOLIO_BAR_LABELS.") == 4 and "healthyLabel" in code, "all four labels are the vocabulary's: Healthy or Good, Needs Attention, At Risk, Critical"
    for key, label in (("needs", "needsAttention"), ("atRisk", "atRisk"), ("critical", "critical")):
        assert f'key: "{key}", label: PORTFOLIO_BAR_LABELS.{label},' in code, f"the {key} bar's label is not {label}"
    assert 'key: "healthy", label: healthyLabel,' in code
    assert code.count("portfolioBars.map(") == 2, "the stacked bar and the rows are both drawn from the one list, so they cannot disagree"


# ── the Health list's tiles count by the engine's grade and print its ranges (POST-A-292) ─────────────────────────────────────

def test_the_health_list_counts_by_the_engines_grade_and_draws_no_score_line_of_its_own():
    """The tiles counted a score under 35, 35 to 49 and 80 and over, and printed '(0–34)', '(35–49)' and '(80–100)' as text: right
    today, and a second place to change when a band moves. The count is of rows whose grade is that band's word (the grade the server
    stores beside the score, hard override included), the tab filters are the same test, and the ranges are built from the band table."""
    code = _strip_comments(_SCORE_PAGES["health list"].read_text(encoding="utf-8"))
    assert not re.search(r"overall_score\s*(<|<=|>|>=)\s*\d", code), "the Health list compares a score with a line of its own"
    assert not re.search(r"\(\d+\u2013\d+\)", code), "the Health list spells a band's range as text"
    assert code.count('c.grade === "Critical"') == 1 and code.count('c.grade === "At Risk"') == 1 and code.count('c.grade === "Healthy"') == 1
    assert 'countOf("Critical")' in code and 'countOf("At Risk")' in code and 'countOf("Healthy")' in code
    for grade in ("Critical", "At Risk", "Healthy"):
        assert f'{grade} ({{gradeRangeLabel("{grade}")}})' in code, grade


def test_the_browsers_range_text_is_built_from_the_band_table(vocab):
    body = re.search(r"export function gradeRangeLabel\(grade: HealthGrade\): string \{(.*?)\n\}", vocab, re.S)
    assert body, "gradeRangeLabel not found"
    assert "HEALTH_GRADE_BANDS" in body.group(1) and "- 1" in body.group(1)
    # the strings the table yields, worked out here from the engine's own bands
    floors = [m for m, _ in scoring.GRADE_BANDS]
    expected = {g: f"{floor}\u2013{100 if i == 0 else floors[i - 1] - 1}" for i, (floor, g) in enumerate(scoring.GRADE_BANDS)}
    assert expected == {"Healthy": "80\u2013100", "Good": "65\u201379", "Needs Attention": "50\u201364", "At Risk": "35\u201349", "Critical": "0\u201334"}
