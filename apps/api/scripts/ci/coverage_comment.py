"""Put the backend coverage figures on the pull request, in ONE comment that every push edits (POST-A-041).

WHAT THIS IS
    `coverage_floor.py` measures `domain/` and `services/` and writes the figures to the job summary, which a reviewer has to go
    looking for. This writes the same table, with the recorded floors, as a comment on the pull request itself. It finds its own
    earlier comment by a hidden marker and EDITS it, so a pull request pushed twenty times carries one comment, not twenty. Every
    body names the commit it was measured on, so a figure from an earlier push is never read as this one's.

    It reads the report and the floors through `coverage_floor.py` itself (`read_floors`, `measure`, `judge`, `render`), so the
    comment and the check cannot disagree about a figure.

IT NEVER FAILS THE JOB
    The floor is held by `coverage_floor.py`, in its own step. Commenting is a courtesy: a pull request from a fork gets a read-only
    token, the API can be down, a rate limit can bite. So every failure here is a `::warning::` and exit 0, and the workflow step
    is `continue-on-error` as well.

AN UNKNOWN IS NOT A FIGURE
    When the tests did not pass, or the report cannot be read, there is no honest number for this commit. The comment is still
    edited, to say so, so that the previous push's figure does not sit there looking current.

Usage (from apps/api, in the pull-request job, after the coverage step):
    GITHUB_TOKEN=... TESTS_OUTCOME=success python3 scripts/ci/coverage_comment.py coverage.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coverage_floor  # noqa: E402

#: How the comment is found again. HTML comments do not render, so a reader never sees it.
MARKER = "<!-- backend-coverage (scripts/ci/coverage_comment.py) -->"

#: Only a comment this workflow's own token wrote is edited: a person who quotes the marker keeps their comment.
BOT_LOGIN = "github-actions[bot]"

#: 100 a page (the API's maximum), and no more pages than this: a pull request with 2,000 comments is not one this looks through.
PAGE_SIZE = 100
MAX_PAGES = 20

Opener = Callable[..., object]


def body(*, sha: str, run_url: str, tests_outcome: str, report: Optional[Path], floors_path: Path) -> str:
    """The comment, marker first. A table of measured figures against floors, or a sentence saying why there is none."""
    head = [MARKER, "### Backend coverage — mock-mode suite", ""]
    where = f"Commit `{sha[:12]}`" + (f" · [run]({run_url})" if run_url else "")
    if tests_outcome != "success":
        return "\n".join([*head, f"{where}: the tests did not pass (`{tests_outcome}`), so no coverage figure is reported for "
                          "this commit. The figure in an earlier version of this comment was for an earlier commit.", ""])
    try:
        floors = coverage_floor.read_floors(floors_path)
        if report is None:
            raise coverage_floor.CoverageError("no coverage report was named")
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise coverage_floor.CoverageError(f"cannot read the coverage report {report}: {exc}") from exc
        measured = coverage_floor.measure(data, sorted(floors))
    except coverage_floor.CoverageError as exc:
        return "\n".join([*head, f"{where}: coverage was not measured ({exc}). No figure is reported for this commit.", ""])
    verdict = coverage_floor.judge(measured, floors)
    below = [p for p, (_, _, holds) in verdict.items() if not holds]
    status = ("**Below the recorded floor:** " + ", ".join(f"`{p}/`" for p in below) + ". The coverage step fails this job."
              if below else "Every package is at or above its recorded floor.")
    return "\n".join([*head, f"{where}. {status}", "", *coverage_floor.render(verdict, measured), "",
                      "Line coverage of `domain/` and `services/` by the mock-mode suite. The real-Postgres tests are not in "
                      "this run, so the lines only they reach count as uncovered. A floor sits a point below what was measured "
                      "and may only be raised (`apps/api/scripts/ci/coverage_floor.py`). This comment is edited on every push.", ""])


def own_comment(comments: list, marker: str = MARKER) -> Optional[int]:
    """The id of the oldest comment this workflow wrote that carries the marker, or None."""
    for c in comments:
        if (isinstance(c, dict) and marker in (c.get("body") or "")
                and (c.get("user") or {}).get("login") == BOT_LOGIN and isinstance(c.get("id"), int)):
            return c["id"]
    return None


def _call(opener: Opener, method: str, url: str, token: str, payload: Optional[dict] = None):
    req = urllib.request.Request(url, method=method, data=None if payload is None else json.dumps(payload).encode("utf-8"))
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    with opener(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def upsert(*, api: str, repo: str, number: int, token: str, text: str, opener: Opener = urllib.request.urlopen) -> str:
    """Edit this workflow's comment on the pull request, or write it if there is none. Returns "edited" or "created"."""
    base = f"{api.rstrip('/')}/repos/{repo}/issues"
    comments: list = []
    for page in range(1, MAX_PAGES + 1):
        batch = _call(opener, "GET", f"{base}/{number}/comments?per_page={PAGE_SIZE}&page={page}", token)
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    found = own_comment(comments)
    if found is not None:
        _call(opener, "PATCH", f"{base}/comments/{found}", token, {"body": text})
        return "edited"
    _call(opener, "POST", f"{base}/{number}/comments", token, {"body": text})
    return "created"


def _pull_request(env) -> tuple[Optional[int], str]:
    """(number, head sha) from the event GitHub wrote for this run, or (None, "") when it is not a pull request."""
    path = env.get("GITHUB_EVENT_PATH")
    if not path:
        return None, ""
    try:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ""
    pr = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
        return None, ""
    return pr["number"], str((pr.get("head") or {}).get("sha") or env.get("GITHUB_SHA") or "")


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None, opener: Opener = urllib.request.urlopen) -> int:
    """Always 0: a comment that could not be written is a warning, never a red job."""
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path, nargs="?")
    ap.add_argument("--floors", type=Path, default=coverage_floor.FLOORS)
    args = ap.parse_args(argv)

    number, sha = _pull_request(env)
    if number is None:
        print("Not a pull request: no coverage comment to write.")
        return 0
    token, repo = env.get("GITHUB_TOKEN", ""), env.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("::warning title=Coverage comment not written::no GITHUB_TOKEN or GITHUB_REPOSITORY in this step's environment")
        return 0
    server, run_id = env.get("GITHUB_SERVER_URL", "https://github.com"), env.get("GITHUB_RUN_ID", "")
    text = body(sha=sha or "unknown", run_url=f"{server}/{repo}/actions/runs/{run_id}" if run_id else "",
                tests_outcome=env.get("TESTS_OUTCOME", "unknown"), report=args.report, floors_path=args.floors)
    try:
        what = upsert(api=env.get("GITHUB_API_URL", "https://api.github.com"), repo=repo, number=number, token=token,
                      text=text, opener=opener)
    except Exception as exc:
        # Deliberately broad, and it swallows nothing silently: the reason is printed as a warning on the run. A 403 from a fork's
        # read-only token (urllib.error.HTTPError), a timeout, a body that is not JSON, all land here; none of them is a reason
        # for a red job, because the floor is held by another step.
        print(f"::warning title=Coverage comment not written::{type(exc).__name__}: {exc}")
        return 0
    print(f"Coverage comment {what} on pull request #{number}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
