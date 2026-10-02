"""Report the backend's coverage of domain/ and services/, and hold it above a recorded floor (engineering-21).

WHAT THIS IS, AND WHAT IT IS NOT
    pytest-cov measures which lines of `domain/` and `services/` the mock-mode suite executes, in the same CI run
    that already runs the suite: no second pass. This script reads the JSON that run wrote, prints one row per
    package (and writes it to the job summary, which is where a reviewer sees it for a pull request), and fails if
    a package is below its FLOOR in `coverage_floor.json`.

    It is a number about the MOCK suite. The `*_pg.py` tests that need a real Postgres are not part of this run,
    so the lines only they reach count as uncovered, and the floors are measured on that basis. It says where the
    tests are thin; it does not say the covered lines are right.

THE FLOOR IS A RATCHET, AND IT SITS BELOW WHAT WAS MEASURED ON PURPOSE
    Measured on 02-10-2026 on the 21,584-passing suite as it stood: domain/ 93.72%, services/ 83.72%. The recorded
    floors are the whole-number part minus one (92 and 82), so a run that skips a handful of tests on a different
    runner, or a coverage engine that counts a decorator line differently, does not turn a required check red; and
    a change that removes tests for a real slice of code does. Raise a floor, never lower one: `--raise` rewrites
    the file to the current figure's whole-number part minus one and only where that is HIGHER, and a floor that
    is lowered by hand is a decision somebody has to write down in the commit.

A TOOL THAT DID NOT RUN IS NOT A CLEAN RESULT
    Exit 0 means "measured, above the floor". Exit 1 means "measured, below it". Exit 2 means the report is missing,
    is not coverage.py's JSON, or measured NOTHING under a package it is asked about (an empty report from a run
    that imported nothing would otherwise be 100% of zero statements).

Usage (from apps/api, after `pytest --cov=domain --cov=services --cov-report=json:coverage.json`):
    python scripts/ci/coverage_floor.py coverage.json
    python scripts/ci/coverage_floor.py coverage.json --raise       # lift floors that have headroom; never lowers
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Optional

FLOORS = Path(__file__).resolve().with_name("coverage_floor.json")

#: How far below the measured figure a floor is recorded: whole-number part, minus this.
MARGIN = 1


class CoverageError(Exception):
    """The report cannot be trusted to mean what it says. Exit code 2."""


def measure(report: object, packages: list[str]) -> dict[str, dict]:
    """{package: {"covered": n, "statements": n, "percent": float}} from coverage.py's JSON report."""
    if not isinstance(report, dict) or not isinstance(report.get("files"), dict):
        raise CoverageError("the report has no `files` object: it is not coverage.py's JSON, or the run did not "
                            "write one")
    totals = {p: [0, 0] for p in packages}
    for path, entry in report["files"].items():
        top = path.replace("\\", "/").split("/")[0]
        if top in totals:
            summary = entry.get("summary") or {}
            totals[top][0] += int(summary.get("covered_lines", 0))
            totals[top][1] += int(summary.get("num_statements", 0))
    out: dict[str, dict] = {}
    for package, (covered, statements) in totals.items():
        if statements == 0:
            raise CoverageError(f"nothing under {package}/ was measured: an empty report from a run that "
                                "imported nothing is not 100% of anything")
        out[package] = {"covered": covered, "statements": statements, "percent": 100.0 * covered / statements}
    return out


def judge(measured: dict[str, dict], floors: dict[str, float]) -> dict[str, tuple[float, float, bool]]:
    """{package: (percent, floor, holds)}."""
    return {p: (m["percent"], float(floors[p]), m["percent"] >= float(floors[p])) for p, m in measured.items()}


def raised(measured: dict[str, dict], floors: dict[str, float]) -> dict[str, float]:
    """The floors after `--raise`: each lifted to floor(percent) - MARGIN where that is higher, never lowered."""
    out = dict(floors)
    for package, m in measured.items():
        candidate = float(math.floor(m["percent"]) - MARGIN)
        out[package] = max(float(floors[package]), candidate)
    return out


def read_floors(path: Path = FLOORS) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        floors = {k: float(v) for k, v in data["floors"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CoverageError(f"cannot read the floors in {path}: {exc}") from exc
    if not floors:
        raise CoverageError(f"{path} records no floors")
    return floors


def render(verdict: dict[str, tuple[float, float, bool]], measured: dict[str, dict]) -> list[str]:
    rows = ["| package | statements | covered | coverage | floor | headroom |", "|---|---:|---:|---:|---:|---:|"]
    for package, (percent, floor, holds) in verdict.items():
        m = measured[package]
        mark = "" if holds else " **below the floor**"
        rows.append(f"| {package}/ | {m['statements']:,} | {m['covered']:,} | {percent:.2f}%{mark} | "
                    f"{floor:.0f}% | {percent - floor:+.2f} |")
    return rows


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    ap.add_argument("--floors", type=Path, default=FLOORS)
    ap.add_argument("--raise", dest="raise_", action="store_true", help="lift floors that have headroom; never lowers")
    args = ap.parse_args(argv)
    github = env.get("GITHUB_ACTIONS") == "true"

    try:
        floors = read_floors(args.floors)
        try:
            report = json.loads(args.report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CoverageError(f"cannot read the coverage report {args.report}: {exc}") from exc
        measured = measure(report, sorted(floors))
    except CoverageError as exc:
        print(f"{'::error title=Coverage did not run::' if github else 'ERROR '}{exc}")
        return 2

    verdict = judge(measured, floors)
    table = render(verdict, measured)
    print("\n".join(table))

    if args.raise_:
        new = raised(measured, floors)
        data = json.loads(args.floors.read_text(encoding="utf-8"))
        data["floors"] = new
        args.floors.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"floors: {floors} -> {new}")
        return 0

    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(["### Backend coverage — mock-mode suite", "", *table, "",
                                "Line coverage of `domain/` and `services/`. The real-Postgres tests are not in this "
                                "run, so the lines only they reach count as uncovered. The floor sits a point below "
                                "what was measured and may only be raised (`scripts/ci/coverage_floor.py`).", ""]))

    failing = [p for p, (_, _, holds) in verdict.items() if not holds]
    for p in failing:
        percent, floor, _ = verdict[p]
        msg = (f"{p}/ is at {percent:.2f}%, below its recorded floor of {floor:.0f}%. Tests that covered it were "
               "removed or stopped running; add them back, or say in the commit why the floor moves.")
        print(f"::error title=Coverage below the floor::{msg}" if github else f"FAIL {msg}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
