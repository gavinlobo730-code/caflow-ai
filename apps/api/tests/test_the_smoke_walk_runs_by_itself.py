"""The smoke walk runs nightly and on demand, uploads what it found, and is not a check anything waits on (engineering-15).

THE GAP
    apps/web/scripts/smoke-walk.mjs opens every route of the static export in Chromium and fails on an uncaught
    exception, a console error, an empty body, an unexpected redirect or a herd of identical bodies. It was run by
    hand, its header said "NOT A CI CHECK", and no workflow named it. CLAUDE.md records thirteen screens crashing the
    first time it could render them and two more components doing it again afterwards; every static check was green
    on all of them.

THE RULE, NOT A LIST OF TODAY'S STEPS
    The walk must run without a person (a schedule), on demand (a dispatch and a label), never on an ordinary pull
    request and never as a required check, with Playwright installed in ITS job only, and it must leave a report
    behind and say which route broke. Each is asserted from the workflow and the script, because the thing that can
    go wrong is a later edit that quietly takes one of them away: a `pull_request:` with no label filter would put a
    five-minute browser job on every PR, and a `push:` trigger or a `paths:` filter would make it a check somebody
    expects.

WHAT CANNOT BE ASSERTED HERE
    That the nightly run is green, or that a workflow run uploads what it says. The behaviour of the script itself
    (a throw on a page's mount fails the walk and names the route) was demonstrated by building the export with one
    in place and running the walk; the commit message records the output. A browser harness does not exist in the
    mock-mode suite.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "smoke-walk.yml"
SCRIPT = REPO / "apps" / "web" / "scripts" / "smoke-walk.mjs"
PACKAGE = REPO / "apps" / "web" / "package.json"
WORKFLOWS = REPO / ".github" / "workflows"


def _code(path: Path) -> str:
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))


def test_it_runs_on_a_schedule_on_demand_and_for_one_label_and_nothing_else():
    code = _code(WORKFLOW)
    assert re.search(r"^\s+schedule:\s*\n\s+- cron:", code, re.M), "no nightly schedule"
    assert re.search(r"^\s+workflow_dispatch:", code, re.M), "cannot be run on demand"
    on_block = code.split("\njobs:")[0]
    assert re.search(r"^\s+pull_request:", on_block, re.M)
    assert re.search(r"types:\s*\[labeled\]", on_block), (
        "a pull_request trigger without `types: [labeled]` runs a browser job on every push to every PR")
    assert not re.search(r"^\s+push:", on_block, re.M), "a push trigger makes it a check somebody waits on"
    assert not re.search(r"^\s*paths(-ignore)?:", on_block, re.M)


def test_a_pull_request_runs_it_only_for_the_one_label():
    code = _code(WORKFLOW)
    assert re.search(r"if:\s*github\.event_name != 'pull_request' \|\| github\.event\.label\.name == 'smoke-walk'", code)


def test_it_is_not_one_of_the_required_checks():
    """CLAUDE.md names two required checks and both are jobs in backend-ci.yml. A required check that never runs
    on an ordinary PR would be pending forever and make every PR unmergeable."""
    backend = (WORKFLOWS / "backend-ci.yml").read_text(encoding="utf-8")
    for required in ("pytest — mock mode (Python 3.11)", "migration apply — real Postgres 16"):
        assert required in backend
    text = WORKFLOW.read_text(encoding="utf-8")
    name = re.search(r"^name:\s*(.+)$", text, re.M).group(1).strip()
    assert name == "Smoke walk"
    job_name = re.search(r"^  walk:\n\s+name:\s*(.+)$", text, re.M).group(1).strip()
    assert job_name not in ("pytest — mock mode (Python 3.11)", "migration apply — real Postgres 16")


def test_playwright_is_installed_in_the_walks_job_only_and_pinned():
    pkg = json.loads(PACKAGE.read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert "@playwright/test" not in deps and "playwright" not in deps, (
        "Playwright is a ~40 MB install that every frontend CI job would then pay for")
    code = _code(WORKFLOW)
    assert 'PLAYWRIGHT_VERSION: "1.' in code, "the version is not pinned to an exact release"
    # The rule is "added to THIS job, at the pinned version", not one spelling of the command: the walk's job now
    # adds the axe scanner (frontend_ux-03) and playwright-core in the same `pnpm add`, so the install line is
    # asked for the pinned package inside a `pnpm add --save-dev`, wherever the other packages sit.
    assert re.search(r'pnpm add --save-dev[\s\S]*?"@playwright/test@\$\{PLAYWRIGHT_VERSION\}"', code)
    assert not deps.get("@axe-core/playwright") and not deps.get("axe-core"), (
        "the accessibility scanner is the walk's job's, never the product's")
    assert "playwright install --with-deps chromium" in code
    # The frontend job every PR runs must not have grown it.
    frontend = _code(WORKFLOWS / "frontend-ci.yml")
    assert "playwright" not in frontend.lower() and "axe-core" not in frontend.lower()


def test_the_apt_sources_that_broke_a_required_check_are_dropped_before_apt_runs():
    code = _code(WORKFLOW)
    drop = code.index("dl\\.google\\.com")
    assert drop < code.index("playwright install --with-deps"), (
        "`--with-deps` runs apt, and Google's Chrome repository has served an inconsistent index before")


def test_it_builds_the_smoke_export_then_walks_it_with_a_report():
    code = _code(WORKFLOW)
    build, walk = code.index("pnpm smoke:build"), code.index("scripts/smoke-walk.mjs")
    assert build < walk, "the walk needs the export the build makes"
    assert "--report .smoke/report.json" in code
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    assert "smoke:build" in package["scripts"] and "127.0.0.1:4319" in package["scripts"]["smoke:build"]


def test_the_report_is_uploaded_even_when_the_walk_fails_and_the_screens_only_then():
    text = WORKFLOW.read_text(encoding="utf-8")
    report = re.search(r"- name: Keep the report\n\s+if: always\(\)\n\s+uses: actions/upload-artifact@v\d+\n"
                       r"(?:.*\n)*?\s+path: apps/web/\.smoke/report\.json", text)
    assert report, "the report must be uploaded with `if: always()`, or the run that fails leaves no report"
    screens = re.search(r"- name: Keep the screenshots of a failed walk\n\s+if: failure\(\)", text)
    assert screens, "screenshots are kept only for a failed walk"
    assert text.count("retention-days:") == 2


# ── the script ─────────────────────────────────────────────────────────────────

def test_the_script_writes_a_report_and_names_every_broken_route():
    src = SCRIPT.read_text(encoding="utf-8")
    # The WHOLE call, not its first few characters: a write to some other file passes a prefix check.
    assert '"--report"' in src and "fs.writeFileSync(reportPath, JSON.stringify(report" in src
    for key in ("broken", "herds", "redirected", "screen_ms", "routes_walked", "ok"):
        assert re.search(rf"\b{key}\b\s*[:,]", src), f"the report no longer carries `{key}`"
    # Under Actions: one annotation per broken route carrying the ROUTE, and a table on the summary page.
    assert re.search(r"::error title=Smoke walk: \$\{b\.route\} is broken::", src)
    assert "GITHUB_STEP_SUMMARY" in src


def test_the_exit_code_is_still_one_for_a_broken_screen_and_the_report_does_not_change_it():
    src = SCRIPT.read_text(encoding="utf-8")
    # The rule, not one spelling of it: a broken screen and a herd of identical bodies still fail the run (the
    # accessibility scan and the slow-server scenario added further terms to the same `failed`, frontend_ux-03/05),
    # and a failed run still exits non-zero.
    assert re.search(r"const failed = Boolean\(\s*broken\.length \|\| \(!anon && herds\.length\)", src)
    assert "failed ? 1 : 0" in src
    # The report is written BEFORE the final exit, or a failing run would exit without leaving one.
    assert src.index("fs.writeFileSync(reportPath") < src.rindex("process.exit(")


def test_the_script_no_longer_calls_itself_not_a_ci_check_and_says_where_it_runs():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "NOT A CI CHECK" not in src
    assert ".github/workflows/smoke-walk.yml" in src
