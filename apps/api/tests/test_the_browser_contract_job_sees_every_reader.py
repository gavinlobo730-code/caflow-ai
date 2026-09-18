"""No guard that opens the frontend tree may be invisible to the job that runs it.

WHY THIS EXISTS
    `.github/workflows/backend-ci.yml` skips the whole backend suite on a diff
    that touches no `apps/api` file — a redesign PR is exactly that shape — and
    the `browser contract` job exists to run, on such a PR, the modules that CAN
    see the change. `scripts/ci/tests_reading_the_browser.py` names them.

    On 18 September 2026 it named 40 and there were 44. The four it missed all
    spell the path the other way:

        _SCREEN = "web/app/income-tax/advance-tax/page.tsx"
        pathlib.Path(__file__).resolve().parents[2] / _SCREEN

    against the `/ "apps" / "web"` expression the script matched. So a
    frontend-only PR skipped them, which is precisely the defect that script's
    own docstring says it exists to prevent — and it is how a gap-callout
    adoption broke `test_the_panel_tells_a_gap_from_a_caveat` with the
    browser-contract job reporting green.

WHY THIS IS NOT CIRCULAR
    Asserting the selector against a THIRD regex would only add a third
    spelling to miss. This asks the FILESYSTEM instead: take every string
    constant in every test module, try to resolve it under the repo root and
    under `apps/`, and a module that lands on a real file inside `apps/web` or
    `apps/marketing` reads a frontend — however it spells the path. That test
    shares no pattern with either of the script's.
"""
from __future__ import annotations

import ast
import pathlib
import sys

_API = pathlib.Path(__file__).resolve().parents[1]
TESTS = _API / "tests"
REPO = _API.parent.parent
FRONTENDS = (REPO / "apps" / "web", REPO / "apps" / "marketing")

sys.path.insert(0, str(_API / "scripts" / "ci"))
import tests_reading_the_browser as selector  # noqa: E402


def _opens_a_frontend_file(path: pathlib.Path) -> str | None:
    """The first string constant in this module that IS a frontend file."""
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        raw = node.value
        # A DOCSTRING IS A STRING CONSTANT. Several of these modules carry a
        # 1,500-character one with a slash in it, and handing that to `is_file`
        # raises ENAMETOOLONG rather than answering False. Bound it to
        # something that could be a path: one line, no spaces, a real suffix.
        if (
            "/" not in raw
            or len(raw) > 200
            or "\n" in raw
            or " " in raw
            or raw.startswith(("http", "/api/"))
            or not pathlib.PurePosixPath(raw).suffix
        ):
            continue
        for base in (REPO, REPO / "apps"):
            try:
                candidate = base / raw
                if not candidate.is_file():
                    continue
            except OSError:
                continue
            if any(fe in candidate.parents for fe in FRONTENDS):
                return raw
    return None


def test_every_module_that_opens_a_frontend_file_is_in_the_list():
    listed = {p.name for p in selector.modules_reading_the_browser()}
    missing = {
        p.name: hit
        for p in sorted(TESTS.glob("test_*.py"))
        if (hit := _opens_a_frontend_file(p)) and p.name not in listed
    }
    assert not missing, (
        "these modules read a real file under apps/web or apps/marketing and "
        "are NOT in the browser-contract job's list, so a frontend-only PR "
        "never runs them:\n  "
        + "\n  ".join(f"{k} → {v}" for k, v in sorted(missing.items()))
        + "\nWiden scripts/ci/tests_reading_the_browser.py rather than "
          "listing them by hand — it derives the set on purpose."
    )


def test_the_filesystem_probe_actually_finds_something():
    """A probe that resolves nothing would make the test above vacuous — which
    is how the money-formatter guard passed on a tree full of the defect."""
    found = [p.name for p in sorted(TESTS.glob("test_*.py"))
             if _opens_a_frontend_file(p)]
    assert len(found) >= 4, (
        f"only {len(found)} modules resolve to a real frontend file; the probe "
        "has stopped working (a moved directory, or paths built some third way)")


def test_the_two_spellings_are_both_matched_by_the_selector():
    """Stated as the two REAL shapes rather than as regexes, so a rewrite of
    the script that keeps both behaviours passes and one that drops either
    fails."""
    both = {p.name for p in selector.modules_reading_the_browser()}
    # `/ "apps" / "web"` — the common spelling.
    assert "test_every_mounted_endpoint_has_a_way_in.py" in both
    # `parents[2] / "web/app/…"` — the one missed until 18 Sep 2026.
    assert "test_a_short_self_assessment_challan_lands_fee_first.py" in both
