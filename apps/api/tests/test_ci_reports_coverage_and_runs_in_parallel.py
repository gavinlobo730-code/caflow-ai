"""CI reports coverage of domain/ and services/, holds a recorded floor, and runs the suite in parallel (engineering-21).

WHAT WAS MISSING
    No coverage measurement existed anywhere, so "where are the tests thin" had no answer, and the mock suite (about
    twenty thousand tests) ran serially in roughly ten minutes of a required check.

THE PARALLEL HALF WAS CHECKED BEFORE IT WAS TURNED ON
    xdist runs each worker in its own process, so module-level state (the `MOCK_*` fixtures a router keeps, the AI
    rate limiter's in-process windows) is not shared between workers: the risk is the opposite one, a test that
    silently depends on state ANOTHER test left behind, which serial order hides and a different grouping exposes.
    So on 02-10-2026 the whole suite was run serially and under `-n 4 --dist loadfile` with coverage, from the same
    tree, and compared test for test from the junit files: the same 23,703 test ids, 21,584 passed and 2,119
    skipped in both, no failure in either, and no id with a different outcome. Serial took 13 min 34 s and the
    parallel run 10 min 20 s on a machine other work was also using, so the gain is about a quarter of the wall
    time, and how much of the distance to a four-fold gain is the coverage tracer, the shared machine or `loadfile`
    keeping a module on one worker was not separated. `load` mode was not measured. `loadfile` was chosen for the
    workflow, since it keeps a module's tests on one worker in the order they were written. What this file pins is
    the CONFIGURATION that measurement justified, so that the mode cannot drift to one nobody measured, or the
    floor below its recorded value, by an edit nobody reads.

WHAT CANNOT BE PINNED HERE
    That the parallel run is faster on a GitHub runner, or that the floor holds there: both are properties of a run
    this suite cannot make. Both were measured on a development machine, and the first pull request through the
    workflow is the first reading from the runner. Nor can it say the real-Postgres modules are safe in parallel:
    the workflow runs only the mock suite under `-n`, and a test below holds that the migration job does not.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
SCRIPT = API / "scripts" / "ci" / "coverage_floor.py"
FLOORS = API / "scripts" / "ci" / "coverage_floor.json"
WORKFLOW = REPO / ".github" / "workflows" / "backend-ci.yml"

#: The floors as first recorded. A floor may be raised and may not be lowered, so these are the least it can be: a
#: change that lowers one has to edit this line, which is where a reviewer is told.
RECORDED_MINIMUM = {"domain": 92.0, "services": 82.0}


def _gate():
    spec = importlib.util.spec_from_file_location("coverage_floor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["coverage_floor"] = mod
    spec.loader.exec_module(mod)
    return mod


G = _gate()


def _report(**per_file):
    """coverage.py's JSON shape: {"files": {path: {"summary": {covered_lines, num_statements}}}}."""
    return {"files": {path: {"summary": {"covered_lines": c, "num_statements": n}}
                      for path, (c, n) in per_file.items()}}


# ── the script ──────────────────────────────────────────────────────────────────

def test_a_package_is_measured_over_all_its_files_and_nothing_else():
    report = {"files": {
        "domain/a.py": {"summary": {"covered_lines": 90, "num_statements": 100}},
        "domain/gst/b.py": {"summary": {"covered_lines": 10, "num_statements": 100}},
        "services/c.py": {"summary": {"covered_lines": 50, "num_statements": 50}},
        "routers/d.py": {"summary": {"covered_lines": 0, "num_statements": 999}},
    }}
    got = G.measure(report, ["domain", "services"])
    assert got["domain"] == {"covered": 100, "statements": 200, "percent": 50.0}
    assert got["services"]["percent"] == 100.0 and "routers" not in got


@pytest.mark.parametrize("bad", [[], {}, {"files": []}, "text", None, {"totals": {}}])
def test_a_report_that_is_not_coverage_json_is_refused_never_read_as_clean(bad):
    with pytest.raises(G.CoverageError):
        G.measure(bad, ["domain"])


def test_a_package_with_nothing_measured_is_refused_not_scored_as_perfect():
    with pytest.raises(G.CoverageError, match="nothing under services/"):
        G.measure(_report(**{"domain/a.py": (1, 1)}), ["domain", "services"])


def test_below_the_floor_fails_and_at_or_above_it_holds():
    m = G.measure(_report(**{"domain/a.py": (92, 100), "services/b.py": (81, 100)}), ["domain", "services"])
    v = G.judge(m, {"domain": 92.0, "services": 82.0})
    assert v["domain"][2] is True, "exactly on the floor holds"
    assert v["services"][2] is False, "a point under it fails"


def test_raising_lifts_a_floor_that_has_headroom_and_never_lowers_one():
    m = {"domain": {"percent": 96.4}, "services": {"percent": 80.2}}
    assert G.raised(m, {"domain": 92.0, "services": 82.0}) == {"domain": 95.0, "services": 82.0}


def _drive(tmp_path, report, floors=None, *flags):
    rep = tmp_path / "coverage.json"
    rep.write_text(json.dumps(report), encoding="utf-8")
    fl = tmp_path / "floors.json"
    fl.write_text(json.dumps({"floors": floors or {"domain": 92.0, "services": 82.0}}), encoding="utf-8")
    code = G.main([str(rep), "--floors", str(fl), *flags], env={})
    return code, fl


def test_the_command_exits_one_below_a_floor_zero_above_and_two_when_it_did_not_run(tmp_path, capsys):
    ok = _report(**{"domain/a.py": (95, 100), "services/b.py": (90, 100)})
    assert _drive(tmp_path, ok)[0] == 0
    low = _report(**{"domain/a.py": (95, 100), "services/b.py": (70, 100)})
    code, _ = _drive(tmp_path, low)
    assert code == 1 and "services/ is at 70.00%, below its recorded floor of 82%" in capsys.readouterr().out
    assert _drive(tmp_path, {"files": {}})[0] == 2
    assert G.main([str(tmp_path / "missing.json"), "--floors", str(FLOORS)], env={}) == 2


def test_raise_rewrites_the_floors_upward_only(tmp_path):
    report = _report(**{"domain/a.py": (97, 100), "services/b.py": (70, 100)})
    code, floors = _drive(tmp_path, report, None, "--raise")
    assert code == 0 and json.loads(floors.read_text())["floors"] == {"domain": 96.0, "services": 82.0}


def test_the_job_summary_is_written_where_github_provides_one(tmp_path):
    summary = tmp_path / "summary.md"
    rep = tmp_path / "coverage.json"
    rep.write_text(json.dumps(_report(**{"domain/a.py": (95, 100), "services/b.py": (90, 100)})), encoding="utf-8")
    assert G.main([str(rep), "--floors", str(FLOORS)], env={"GITHUB_STEP_SUMMARY": str(summary)}) == 0
    text = summary.read_text()
    assert "Backend coverage" in text and "| domain/ |" in text and "| services/ |" in text


# ── the recorded floors ─────────────────────────────────────────────────────────

def test_the_recorded_floors_cover_domain_and_services_and_never_sit_below_where_they_started():
    data = json.loads(FLOORS.read_text(encoding="utf-8"))
    floors = G.read_floors(FLOORS)
    assert set(floors) == set(RECORDED_MINIMUM) == {"domain", "services"}
    for package, minimum in RECORDED_MINIMUM.items():
        assert floors[package] >= minimum, f"{package}'s floor was lowered from {minimum}: a floor only rises"
        assert floors[package] <= data["measured"][package], "a floor above what was measured fails the first run"


# ── the workflow ────────────────────────────────────────────────────────────────

def _job(fragment: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"name: {fragment}")
    nxt = re.search(r"^  [a-z][a-z-]*:\n", text[start:], re.MULTILINE)
    return text[start: start + nxt.start()] if nxt else text[start:]


def _run_step(job: str, name_fragment: str) -> str:
    start = job.index(f"name: {name_fragment}")
    nxt = re.search(r"^      - ", job[start:], re.MULTILINE)
    return job[start: start + (nxt.start() if nxt else len(job))]


def test_the_test_step_runs_in_parallel_in_the_distribution_mode_that_was_measured():
    job = _job("pytest — mock mode (Python 3.11)")
    step = " ".join(_run_step(job, "Run tests").split())
    assert re.search(r"-n auto\b", step), "the suite is no longer run in parallel"
    assert "--dist loadfile" in step, "`loadfile` is the measured mode; `load` is the weaker promise"
    assert "--dist load " not in step + " "


def test_the_test_step_writes_the_coverage_report_for_exactly_the_two_packages():
    step = " ".join(_run_step(_job("pytest — mock mode (Python 3.11)"), "Run tests").split())
    assert "--cov=domain" in step and "--cov=services" in step
    assert "--cov-report=json:coverage.json" in step
    assert "--cov=routers" not in step, "routers hold no rules; their lines would only dilute the figure"


def test_the_floor_is_checked_after_the_tests_and_only_when_the_backend_changed():
    job = _job("pytest — mock mode (Python 3.11)")
    assert job.index("name: Run tests") < job.index("name: Coverage")
    step = _run_step(job, "Coverage")
    assert "needs.scope.outputs.api == 'true'" in step
    assert "if: always()" not in step and "continue-on-error" not in step and "|| true" not in step, \
        "a floor that cannot fail is a report nobody reads"


def test_the_report_is_kept_with_the_run_and_the_workflow_still_has_no_paths_filter():
    job = _job("pytest — mock mode (Python 3.11)")
    assert "actions/upload-artifact@v4" in job and "apps/api/coverage.json" in job
    assert not re.search(r"^\s+paths(-ignore)?:", WORKFLOW.read_text(encoding="utf-8"), re.MULTILINE)


def test_the_parallel_and_coverage_tools_are_pinned_in_the_dev_requirements_and_not_shipped():
    dev = (API / "requirements-dev.txt").read_text(encoding="utf-8")
    prod = (API / "requirements.txt").read_text(encoding="utf-8").lower()
    for tool in ("pytest-xdist", "pytest-cov"):
        assert re.search(rf"^{tool}==[0-9][^\s#\\]*", dev, re.MULTILINE), f"{tool} is not pinned exactly"
        assert tool not in prod, f"{tool} would ship in the production image"


def test_the_real_postgres_job_is_not_run_in_parallel():
    """Only the mock suite was measured under xdist. Several real-Postgres modules create a database of a fixed
    name, so `-n` over them is a thing nobody has shown safe, and the job that runs them stays serial."""
    job = _job("migration apply — real Postgres 16")
    pytest_lines = [line for line in job.splitlines() if re.search(r"\bpytest\b", line) and not line.lstrip().startswith("#")]
    assert pytest_lines, "the migration job no longer runs pytest where this test looks; update the reading"
    for line in pytest_lines:
        assert not re.search(r"(^|\s)(-n\b|--numprocesses|--dist\b)", line), f"the real-Postgres job runs in parallel: {line.strip()}"
