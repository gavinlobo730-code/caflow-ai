#!/usr/bin/env python3
"""
Turn a directory of smoke timings files into the table the service-level targets are judged by (ops-12).

WHY THIS EXISTS
    `scripts/smoke_api.py` fails ONE run when an endpoint is over its budget, and a budget is a tripwire
    for "something is badly wrong" (20 s for the P&L). It cannot say that the P&L has crept from 1.5 s to
    4 s over a month, which is the thing a CA notices first and the team notices last. Each run keeps its
    measurements (`write_timings`) and `.github/workflows/smoke.yml` uploads them as an artifact; this reads
    a month of those and answers, per endpoint, the question a target is about: what is the 95th percentile,
    and is it under the target?

    A TARGET IS NOT A GATE. This script exits 0 whatever it finds. A number that fails a build on one
    unlucky sample is a number that gets ignored, and nothing here may flap. The budget is the gate.

USAGE
    python3 scripts/smoke_timings_report.py DIR [DIR ...] [--days 30] [--now 2026-10-31T00:00:00+00:00]

    Prints Markdown (the workflow appends it to the run's summary page). Every `*.json` under each DIR is
    read; the same run found twice (the artifact of this run and the listing's copy of it) is counted once.

WHAT IT REFUSES TO CLAIM
    * Coverage is stated in days, from the first sample to the last. With less than the window it says so
      and says that a reading over the whole window is not available yet. It never presents four days as a
      month.
    * Latency percentiles are taken over samples where the endpoint ANSWERED (a 2xx, or the MFA guard
      refusing an aal1 token, which is the policy working). A 503 that returns in 50 ms is not a fast
      response; failures are counted beside the percentiles, not mixed into them. An over-budget answer
      stays in, because it is the sample that matters most.
    * With fewer than `MIN_SAMPLES` answered samples the verdict is "not enough samples", not met or over:
      with n of 5 the 95th percentile is the maximum, and calling it a percentile would overstate it.
    * The percentile is the nearest-rank one (the smallest value with at least 95 % of samples at or below
      it), which never invents a value no run measured.
    * A file that cannot be read, or that is of another schema, is counted and named, never skipped quietly
      and never allowed to stop the report.
    * A run aimed at a candidate deployment (`deployment` other than `live`) is excluded and counted.

No dependency beyond the standard library: it runs on a bare runner.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

# Must equal smoke_api.TIMINGS_SCHEMA. A test holds the two together; the script cannot import its sibling
# because it is run standalone on a runner with nothing installed.
SCHEMA = 1

# Below this many answered samples a 95th percentile is not a percentile. A month of 6-hourly runs is about
# 120; twenty is five days.
MIN_SAMPLES = 20

DEFAULT_DAYS = 30


# ── reading ────────────────────────────────────────────────────────────────────

def _when(text: object) -> Optional[datetime]:
    """An ISO instant as an aware UTC datetime, or None. A naive stamp is read as UTC."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _usable(raw: object) -> Optional[dict]:
    """The run as a dict with `at` parsed, or None when it is not a schema-1 timings file."""
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    at = _when(raw.get("generated_at"))
    if at is None or not isinstance(raw.get("checks"), list):
        return None
    return {**raw, "at": at}


def load(dirs: Iterable[Path]) -> tuple[list[dict], list[str]]:
    """(the runs, the names of the files that could not be used). The same run twice is one."""
    runs: dict[tuple, dict] = {}
    unreadable: list[str] = []
    for root in dirs:
        for path in sorted(Path(root).rglob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                unreadable.append(path.name)
                continue
            run = _usable(raw)
            if run is None:
                unreadable.append(path.name)
                continue
            runs[(run.get("run_id"), run["generated_at"])] = run
    return sorted(runs.values(), key=lambda r: r["at"]), unreadable


# ── arithmetic ─────────────────────────────────────────────────────────────────

def percentile(values: list[float], p: float) -> Optional[float]:
    """The nearest-rank percentile: the smallest value with at least p of the samples at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p * len(ordered)))
    return ordered[rank - 1]


def _week(moment: datetime) -> str:
    iso = moment.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def summarise(runs: list[dict], *, now: Optional[datetime] = None, days: int = DEFAULT_DAYS,
              unreadable: Optional[list[str]] = None) -> dict:
    """Everything the table says, as data, so a test can read it without parsing Markdown."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    live = [r for r in runs if r.get("deployment", "live") == "live"]
    candidates = len(runs) - len(live)
    inside = [r for r in live if cutoff <= r["at"] <= now]

    per: dict[str, dict] = {}
    by_week: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for run in inside:
        for s in run["checks"]:
            if not isinstance(s, dict) or not isinstance(s.get("name"), str):
                continue
            row = per.setdefault(s["name"], {"answered": [], "failed": 0, "over_budget": 0,
                                             "budget_s": None, "target_s": None})
            # The newest run's budget and target are the ones in force.
            row["budget_s"] = s.get("budget_s", row["budget_s"])
            row["target_s"] = s.get("target_s", row["target_s"])
            elapsed = s.get("elapsed_s")
            if s.get("answered") and isinstance(elapsed, (int, float)):
                row["answered"].append(float(elapsed))
                by_week[s["name"]][_week(run["at"])].append(float(elapsed))
                if isinstance(s.get("budget_s"), (int, float)) and elapsed > s["budget_s"]:
                    row["over_budget"] += 1
            else:
                row["failed"] += 1

    endpoints = []
    for name, row in per.items():
        n = len(row["answered"])
        p95 = percentile(row["answered"], 0.95)
        target = row["target_s"]
        if target is None:
            verdict = "no target"
        elif n < MIN_SAMPLES:
            verdict = "not enough samples"
        elif p95 is not None and p95 <= target:
            verdict = "within target"
        else:
            verdict = "OVER target"
        endpoints.append({
            "name": name, "answered": n, "failed": row["failed"], "over_budget": row["over_budget"],
            "p50": percentile(row["answered"], 0.50), "p95": p95,
            "max": max(row["answered"]) if row["answered"] else None,
            "target_s": target, "budget_s": row["budget_s"], "verdict": verdict,
            "weekly_p95": {w: percentile(v, 0.95) for w, v in sorted(by_week[name].items())},
        })

    first = inside[0]["at"] if inside else None
    last = inside[-1]["at"] if inside else None
    covered = ((last - first).total_seconds() / 86400.0) if inside else 0.0
    wakes = [r.get("wake_s") for r in inside if isinstance(r.get("wake_s"), (int, float))]
    return {
        "days_asked": days,
        "runs": len(inside),
        "first": first,
        "last": last,
        "days_covered": covered,
        "complete_window": covered >= days - 1,
        "runs_api_never_answered": sum(1 for r in inside if r.get("awake") is False),
        "cold_starts": sum(1 for r in inside if r.get("cold_start")),
        "longest_wake_s": max(wakes) if wakes else None,
        "candidate_runs_excluded": candidates,
        "unreadable_files": list(unreadable or []),
        "endpoints": endpoints,
    }


# ── rendering ──────────────────────────────────────────────────────────────────

def _s(value: Optional[float]) -> str:
    return "–" if value is None else f"{value:.2f}"


def render(summary: dict) -> str:
    """The summary as Markdown for the run's summary page."""
    days = summary["days_asked"]
    lines = [f"### Smoke timings, last {days} days", ""]

    if not summary["runs"]:
        lines += [f"No smoke run of the live deployment in the last {days} days has left a timings file "
                  "(a run with no credentials configured measures nothing and leaves none).", ""]
    else:
        first, last = summary["first"], summary["last"]
        lines += [
            f"{summary['runs']} runs, {first:%d-%m-%Y} to {last:%d-%m-%Y} UTC, "
            f"{summary['days_covered']:.1f} days apart.",
            "",
        ]
        if not summary["complete_window"]:
            lines += [f"**This covers {summary['days_covered']:.1f} of the {days} days asked for. A {days}-day "
                      "reading is not available yet**; what follows is what the runs so far say, "
                      "and a verdict needs at least "
                      f"{MIN_SAMPLES} answered samples of an endpoint.", ""]

    if summary["endpoints"]:
        lines += ["| endpoint | answered | p50 s | p95 s | max s | target s | budget s | over budget | failed | verdict |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for e in sorted(summary["endpoints"], key=lambda e: e["name"]):
            target = "–" if e["target_s"] is None else f"{e['target_s']:g}"
            budget = "–" if e["budget_s"] is None else f"{e['budget_s']:g}"
            lines.append(f"| {e['name']} | {e['answered']} | {_s(e['p50'])} | {_s(e['p95'])} | {_s(e['max'])} "
                         f"| {target} | {budget} | {e['over_budget']} | {e['failed']} | {e['verdict']} |")
        lines.append("")

        weeks = sorted({w for e in summary["endpoints"] for w in e["weekly_p95"]})
        if weeks:
            lines += ["95th percentile by ISO week, seconds (a drift shows here before it shows in the total):",
                      "",
                      "| endpoint | " + " | ".join(weeks) + " |",
                      "|---|" + "---:|" * len(weeks)]
            for e in sorted(summary["endpoints"], key=lambda e: e["name"]):
                cells = [_s(e["weekly_p95"].get(w)) for w in weeks]
                lines.append(f"| {e['name']} | " + " | ".join(cells) + " |")
            lines.append("")

    facts = []
    if summary["runs"]:
        facts.append(f"The instance was asleep (wake over 5 s) in {summary['cold_starts']} of "
                     f"{summary['runs']} runs; longest wake {_s(summary['longest_wake_s'])} s "
                     "(never counted against a budget).")
        if summary["runs_api_never_answered"]:
            facts.append(f"**The API never answered /health in {summary['runs_api_never_answered']} run(s).**")
    if summary["candidate_runs_excluded"]:
        facts.append(f"{summary['candidate_runs_excluded']} run(s) aimed at a candidate deployment were excluded.")
    if summary["unreadable_files"]:
        shown = ", ".join(summary["unreadable_files"][:5])
        more = len(summary["unreadable_files"]) - 5
        facts.append(f"{len(summary['unreadable_files'])} file(s) could not be read or are of another schema "
                     f"and were not counted: {shown}{f' and {more} more' if more > 0 else ''}.")
    lines += facts + ([""] if facts else [])
    lines += ["A target is judged on this table and never fails a run; a budget fails the run it is exceeded in. "
              "`docs/operations/service-levels.md` has the targets and how a budget is tightened."]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    days = DEFAULT_DAYS
    now: Optional[datetime] = None
    dirs: list[Path] = []
    it = iter(argv)
    for arg in it:
        if arg == "--days":
            days = int(next(it))
        elif arg == "--now":
            now = _when(next(it))
            if now is None:
                print("--now needs an ISO timestamp", file=sys.stderr)
                return 2
        else:
            dirs.append(Path(arg))
    if not dirs:
        print("usage: smoke_timings_report.py DIR [DIR ...] [--days N] [--now ISO]", file=sys.stderr)
        return 2
    runs, unreadable = load(dirs)
    sys.stdout.write(render(summarise(runs, now=now, days=days, unreadable=unreadable)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
