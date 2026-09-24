"""A rupee figure written for a person is grouped the Indian way, once.

── THE TWO DEFECTS ──────────────────────────────────────────────────────────
**WESTERN GROUPING.** `f"{1234567:,}"` is `1,234,567`. Decision D6 says Indian
grouping everywhere: **12,34,567**, the last three digits then twos. Seventy-
three figures across forty-one modules used Python's own separator — every
email to a client's customer, every 422 a CA reads about money they are about
to pay, the XLSX export, the timeline sentences, and a dozen domain modules
that explain a statutory computation.

**AND EIGHT OF THEM INVERTED A NEGATIVE.** Python's `//` floors and `%`
follows it, so the sign-and-magnitude split silently inverts:

        -1 paise  ->  "-1.99"     (true: -0.01)
       -99 paise  ->  "-1.01"     (true: -0.99)
      -150 paise  ->  "-2.50"     (true: -1.50)

`domain/reporting/pdf_money` was written to fix exactly this, found it in three
PDF services, fixed those three, and **that was all it reached**. The other
eight copies are the reason this guard is about the rule rather than about the
three files that module knows: `services/email_service` sends to a client's own
customer, `services/time_export_service` writes a spreadsheet cell, and
`domain/banking/matcher` had taken `abs()` on the FRACTION and not on the
rupees, which fixes nothing (-1 paise still read "-1.01").

── THE RULE ─────────────────────────────────────────────────────────────────
No module may render a paise value into text by dividing it itself. The
grouping lives once, in `domain/money_text`, and the UNIT stays the caller's —
a PDF writes "Rs." because ReportLab's core fonts have no U+20B9 glyph, and
everything else writes ₹.

Stated as the RULE and not a spelling of it: the probe looks for the SHAPE of a
hand-rolled render — a `/ 100` or `// 100` inside a format placeholder that
carries a thousands separator — rather than for the particular expressions that
were there on 24 September. A ninth copy written any other way still matches.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from domain.money_text import group_indian, rupees_paise, whole_rupees

API = Path(__file__).resolve().parents[1]
ROOTS = ("domain", "routers", "services", "repositories", "core", "jobs", "models")


def _code(p: Path) -> str:
    """Docstrings and comments blanked IN PLACE, so offsets and line numbers
    survive. A guard that reads its own prose is a guard that passes on a tree
    full of the defect, and three in this repo have done exactly that."""
    s = p.read_text()
    out = list(s)
    for m in re.finditer(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', s):
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "
    t = "".join(out)
    for m in re.finditer(r"(?m)^\s*#.*$", t):
        out[m.start():m.end()] = " " * (m.end() - m.start())
    return "".join(out)


def _files() -> list[Path]:
    out: list[Path] = []
    for r in ROOTS:
        out += sorted((API / r).rglob("*.py"))
    return out


#: A money figure rendered by hand: a division by 100 inside a format
#: placeholder that also carries Python's thousands separator. Both `/` and
#: `//` — the first is the float the money rule forbids, the second the one
#: that inverts a negative.
HAND_ROLLED = re.compile(r"\{[^{}]*?(?<![/])//?\s*100\s*:[^{}]*,[^{}]*\}")

#: The module that IS the rule, and may divide.
AUTHORITY = "domain/money_text.py"


def _offenders() -> list[tuple[str, int, str]]:
    out = []
    for p in _files():
        rel = str(p.relative_to(API))
        if rel == AUTHORITY:
            continue
        for i, line in enumerate(_code(p).split("\n"), 1):
            if HAND_ROLLED.search(line):
                out.append((rel, i, line.strip()[:100]))
    return out


def test_no_module_groups_a_rupee_figure_itself():
    found = _offenders()
    assert not found, (
        f"{len(found)} places render a rupee figure by dividing paise inside a "
        "format placeholder. That groups the WESTERN way (1,234,567 against "
        "D6's 12,34,567) and, with `//` and `%`, inverts a negative: -1 paise "
        "reads '-1.99'. Call domain.money_text.rupees_paise / whole_rupees and "
        "keep your own unit.\n  "
        + "\n  ".join(f"{f}:{i}  {t}" for f, i, t in found[:15]))


def test_the_probe_still_reaches_the_tree_it_is_about():
    """A regex that matches nothing passes for ever. This asserts the scan
    still reads real module bodies — a moved directory or a changed comment
    stripper is what would silence it."""
    files = _files()
    assert len(files) > 300, f"only {len(files)} modules scanned"
    callers = [p for p in files if "rupees_paise(" in _code(p) or "whole_rupees(" in _code(p)]
    assert len(callers) >= 30, (
        f"only {len(callers)} modules call the authority; the sweep has been "
        "reverted, or the scan no longer reads bodies")


def test_the_authority_is_the_only_implementation():
    """`domain/reporting/pdf_money` keeps its name and its no-glyph rule and
    must not keep a SECOND copy of the grouping — two implementations of one
    rule is what this whole class of defect is."""
    body = _code(API / "domain/reporting/pdf_money.py")
    assert "from domain.money_text import" in body, (
        "pdf_money no longer delegates; it has its own grouping again")
    tree = ast.parse((API / "domain/reporting/pdf_money.py").read_text())
    defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert not defs, f"pdf_money defines {defs}; it is a re-export, not a twin"


def test_a_pdf_module_may_not_reach_for_the_rupee_sign_through_this_module():
    """The UNIT is the medium's. ReportLab's core fonts are WinAnsiEncoding and
    have no U+20B9 glyph, so a PDF that prints ₹ prints a black box — that
    shipped twice. The authority emits digits and no unit, which is what makes
    it safe for a PDF and an email alike."""
    src = (API / "domain/money_text.py").read_text()
    body = _code(API / "domain/money_text.py")
    assert "₹" in src, "the docstring should still explain the unit rule"
    assert "₹" not in body, (
        "domain/money_text emits a rupee sign. It must not: every PDF service "
        "calls it, and tests/test_no_pdf_renders_the_rupee_sign.py exists "
        "because a black box shipped twice.")


# ── The behaviour the callers now depend on ──────────────────────────────────

@pytest.mark.parametrize("paise,expected", [
    (-1, "-0.01"), (-99, "-0.99"), (-150, "-1.50"),
    (0, "0.00"), (1, "0.01"), (999, "9.99"),
    (100000, "1,000.00"), (12345678, "1,23,456.78"),
    (100000000, "10,00,000.00"), (10000000000, "10,00,00,000.00"),   # 100 million rupees = 10 crore
    (None, "0.00"),
])
def test_rupees_paise(paise, expected):
    assert rupees_paise(paise) == expected


@pytest.mark.parametrize("paise,expected", [
    (-1, "0"), (-150, "-1"), (-99, "0"), (0, "0"),
    (12345678, "1,23,456"), (None, "0"),
])
def test_whole_rupees_truncates_toward_zero(paise, expected):
    """-150 is -1 and not -2, and a magnitude under a rupee is '0' and never
    '-0' — a minus sign on a nil reads as an amount somebody owes."""
    assert whole_rupees(paise) == expected


# ── The parity half: the browser groups the same way ─────────────────────────

_VECTORS = json.loads(
    (API.parent.parent / "shared" / "money-grouping-vectors.json").read_text()
)["vectors"]


@pytest.mark.parametrize("v", _VECTORS, ids=lambda v: str(v["paise"]))
def test_the_shared_vectors_are_what_this_side_answers(v):
    """`shared/money-grouping-vectors.json` is read by BOTH suites.

    Indian grouping has two implementations and neither language can read the
    other's — this one serves every PDF, email and 422, and
    `apps/web/lib/money/format.ts` serves every screen. A CA reads both on one
    page, so a disagreement is visible at a glance; it WAS one until this
    commit, and nothing would have caught the next one.

    `apps/web/scripts/money-grouping-parity.test.ts` asserts the same file
    against `formatPaiseBare`.
    """
    assert rupees_paise(v["paise"]) == v["grouped"], v["note"]


def test_the_fixture_still_carries_the_cases_that_matter():
    """A fixture quietly emptied of its hard cases passes for ever."""
    seen = {v["paise"] for v in _VECTORS}
    assert len(_VECTORS) >= 15, f"only {len(_VECTORS)} vectors"
    for must in (10_000_000, 1_000_000_000, -150):
        assert must in seen, f"the {must}-paise vector has gone"


def test_whole_rupees_is_deliberately_not_a_parity_vector():
    """The two sides answer DIFFERENT questions here and must not be
    harmonised: this one truncates toward zero because the year-end statements
    present in whole rupees, while the browser's `formatWhole` falls back to
    showing paise so an unrounded row stands out on a return-prep screen.

    The fixture says so in prose; this asserts the fixture still says it, so
    the reason cannot be lost while the file is edited."""
    raw = json.loads(
        (API.parent.parent / "shared" / "money-grouping-vectors.json").read_text())
    assert not any("whole" in v for v in raw["vectors"]), (
        "a `whole` column was added to the shared vectors. The two languages "
        "round differently ON PURPOSE — read the fixture's own note before "
        "pinning them.")
    note = " ".join(k for k in raw if k.startswith("_"))
    assert "whole_rupees" in note, (
        "the fixture no longer records WHY whole rupees is not pinned")


@pytest.mark.parametrize("digits,expected", [
    ("0", "0"), ("1", "1"), ("999", "999"), ("1000", "1,000"),
    ("100000", "1,00,000"), ("1234567", "12,34,567"),
    ("123456789", "12,34,56,789"),
])
def test_group_indian(digits, expected):
    assert group_indian(digits) == expected


def test_the_western_grouping_this_replaced_really_did_differ():
    """A negative control on the PREMISE. If Python's own separator agreed with
    the Indian one above a lakh there would be no defect, and this whole sweep
    would be noise."""
    assert f"{1234567:,}" == "1,234,567"
    assert group_indian("1234567") == "12,34,567"
    # and the sign split really did invert
    assert f"{-1 // 100:,}.{-1 % 100:02d}" == "-1.99"
    assert rupees_paise(-1) == "-0.01"
