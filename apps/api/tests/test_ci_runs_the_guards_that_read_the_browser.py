"""The CI selector must find the guards an apps/web-only PR can break.

WHY. `.github/workflows/backend-ci.yml` skipped every python guard on a diff
that touched no `apps/api` file, and announced it: "the required jobs will
report green without running". A module conversion during the redesign is
exactly that diff, so the guard written to catch a screen that stops calling
its engine was switched off by the PR that would do it. The
`browser-contract` job closes that, and it decides what to run by calling
`scripts/ci/tests_reading_the_browser.py`.

That script is now load-bearing, so it gets a guard of its own. Two properties
matter and each has failed somewhere in this repo before:

  * IT MUST FOLLOW IMPORTS. `test_the_redesign_cannot_orphan_an_endpoint.py`
    builds no path of its own — it imports `_sources`, `_routes` and
    `_pattern` from `test_every_mounted_endpoint_has_a_way_in`. A selector
    that greps for the path expression misses the single most important guard
    in the set while looking like it works.

  * IT MUST NEVER RETURN NOTHING. An empty list handed to pytest collects the
    WHOLE suite, which is the cost this job exists to avoid, and it would pass
    — so "found nothing" has to be a loud failure, not a quiet one.

Deliberately NOT asserted: an exact module count. The list is derived so a
guard added later joins it, and pinning the number would fail every time
somebody writes a test — which teaches people to edit the number rather than
read the failure.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

API_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = API_ROOT / "scripts" / "ci" / "tests_reading_the_browser.py"


def _load():
    spec = importlib.util.spec_from_file_location("_selector", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_selector_script_exists() -> None:
    assert SCRIPT.is_file(), (
        f"{SCRIPT} has moved — backend-ci.yml's browser-contract job calls it by "
        "path and would fail the run. Update the workflow, do not delete this test."
    )


def test_it_finds_the_guard_that_builds_the_path_itself() -> None:
    names = {p.name for p in _load().modules_reading_the_browser()}
    assert "test_every_mounted_endpoint_has_a_way_in.py" in names


def test_it_follows_imports_to_a_guard_with_no_path_of_its_own() -> None:
    """The orphan-endpoint guard is reached only through its import."""
    module = _load()
    names = {p.name for p in module.modules_reading_the_browser()}

    target = "test_the_redesign_cannot_orphan_an_endpoint.py"
    assert target in names, (
        f"{target} is missing from the CI selection. It is THE guard for the "
        "redesign and it has no apps/web path of its own — it imports one. A "
        "selector that stopped following imports would drop it silently."
    )

    # Prove the import step is what puts it there, so this test fails if the
    # transitive walk is removed even when the result happens to look right.
    source = (API_ROOT / "tests" / target).read_text()
    assert not module._BUILDS_WEB_PATH.search(source), (
        f"{target} now builds the apps/web path directly, so it would be found "
        "without the import walk. That is fine, but this test no longer proves "
        "the walk works — point it at another importer or delete it."
    )


def test_a_comment_mentioning_apps_web_is_not_a_read() -> None:
    """Matching the bare string finds ~89 modules; most only talk about it."""
    selected = _load().modules_reading_the_browser()
    mentions = [
        p
        for p in (API_ROOT / "tests").glob("test_*.py")
        if "apps/web" in p.read_text(errors="ignore")
    ]
    assert len(selected) < len(mentions), (
        "The selector is matching prose rather than the path expression, which "
        "would pull most of the suite into a job that exists to stay small."
    )


def test_finding_nothing_is_a_failure_not_an_empty_run() -> None:
    """An empty argv makes pytest collect everything — that must not happen."""
    broken = SCRIPT.read_text().replace(
        '_BUILDS_WEB_PATH = re.compile(r\'/\\s*"apps"\\s*/\\s*"web"\')',
        "_BUILDS_WEB_PATH = re.compile(r'ZZZ_MATCHES_NOTHING')",
    )
    assert "ZZZ_MATCHES_NOTHING" in broken, "patch did not apply — rewrite this test"

    tmp = API_ROOT / "tests" / "_selector_negative_control.py"
    tmp.write_text(broken)
    try:
        run = subprocess.run(
            [sys.executable, str(tmp)], capture_output=True, text=True
        )
    finally:
        tmp.unlink(missing_ok=True)

    assert run.returncode != 0, "a selector that finds nothing must exit non-zero"
    assert not run.stdout.strip(), "it must print no module names"
