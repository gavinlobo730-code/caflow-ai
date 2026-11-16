"""The backend coverage figures are posted on the pull request, in one comment that every push edits (POST-A-041).

WHAT WAS MISSING
    `scripts/ci/coverage_floor.py` writes the measured figures and the floors to the job summary and keeps the report as an
    artifact; nothing put them where a reviewer reads a pull request. `scripts/ci/coverage_comment.py` now writes the same table
    as a comment, found again by a hidden marker and EDITED on every later push, from a step that cannot turn the job red.

WHAT IS HELD HERE
    The comment's text (figures against floors, the commit it is for, and a sentence instead of a figure when there is none), which
    comment is edited (only this workflow's own, by its marker), edit-or-create against a stand-in for the GitHub API (paging
    included), that every failure is a warning and exit 0, and the workflow: the step's place, its condition, its token, the job's
    two permissions and nothing wider anywhere else.

WHAT CANNOT BE HELD HERE
    That GitHub accepts the call with this job's token. That is a property of a run on a real pull request; the first one through
    the workflow is the reading, and a refusal there is a warning on the run, not a red check.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
SCRIPT = API / "scripts" / "ci" / "coverage_comment.py"
WORKFLOW = REPO / ".github" / "workflows" / "backend-ci.yml"


def _load():
    spec = importlib.util.spec_from_file_location("coverage_comment", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["coverage_comment"] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load()


def _report(tmp_path, domain=(95, 100), services=(90, 100)) -> Path:
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps({"files": {
        "domain/a.py": {"summary": {"covered_lines": domain[0], "num_statements": domain[1]}},
        "services/b.py": {"summary": {"covered_lines": services[0], "num_statements": services[1]}},
    }}), encoding="utf-8")
    return p


def _floors(tmp_path) -> Path:
    p = tmp_path / "floors.json"
    p.write_text(json.dumps({"floors": {"domain": 92.0, "services": 82.0}}), encoding="utf-8")
    return p


# ── the text ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_comment_carries_the_marker_the_commit_and_each_figure_against_its_floor(tmp_path):
    text = C.body(sha="0123456789abcdef", run_url="https://github.com/o/r/actions/runs/7", tests_outcome="success",
                  report=_report(tmp_path), floors_path=_floors(tmp_path))
    assert text.startswith(C.MARKER), "the marker is how the next push finds this comment"
    assert "`0123456789ab`" in text and "actions/runs/7" in text
    assert "| domain/ | 100 | 95 | 95.00% | 92% | +3.00 |" in text
    assert "| services/ | 100 | 90 | 90.00% | 82% | +8.00 |" in text
    assert "at or above its recorded floor" in text and "Below" not in text


def test_a_package_below_its_floor_is_named_in_words_and_in_the_table(tmp_path):
    text = C.body(sha="abc", run_url="", tests_outcome="success", report=_report(tmp_path, services=(70, 100)),
                  floors_path=_floors(tmp_path))
    assert "**Below the recorded floor:** `services/`" in text
    assert "70.00% **below the floor**" in text


def test_no_figure_is_shown_for_a_commit_whose_tests_did_not_pass_or_whose_report_cannot_be_read(tmp_path):
    failed = C.body(sha="abc", run_url="", tests_outcome="failure", report=_report(tmp_path), floors_path=_floors(tmp_path))
    assert "the tests did not pass (`failure`)" in failed and "%" not in failed
    missing = C.body(sha="abc", run_url="", tests_outcome="success", report=tmp_path / "absent.json",
                     floors_path=_floors(tmp_path))
    assert "coverage was not measured" in missing and "%" not in missing
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"files": {}}), encoding="utf-8")
    nothing = C.body(sha="abc", run_url="", tests_outcome="success", report=empty, floors_path=_floors(tmp_path))
    assert "coverage was not measured" in nothing and "nothing under domain/" in nothing
    for text in (failed, missing, nothing):
        assert text.startswith(C.MARKER), "the comment is still edited, so the last good figure stops looking current"


# ── which comment ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_only_this_workflows_own_marked_comment_is_edited_and_the_oldest_wins():
    bot, person = {"login": C.BOT_LOGIN}, {"login": "a-reviewer"}
    comments = [
        {"id": 1, "user": person, "body": f"quoting {C.MARKER}"},
        {"id": 2, "user": bot, "body": "some other bot note"},
        {"id": 3, "user": bot, "body": f"{C.MARKER}\nold figures"},
        {"id": 4, "user": bot, "body": f"{C.MARKER}\na duplicate"},
    ]
    assert C.own_comment(comments) == 3
    assert C.own_comment(comments[:2]) is None


# ── edit or create, against a stand-in for the API ───────────────────────────────────────────────────────────────────────

class _FakeApi:
    """Records each request and answers from a list of pages of comments."""

    def __init__(self, pages, fail_with=None):
        self.pages, self.fail_with, self.calls = pages, fail_with, []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        self.calls.append((req.get_method(), req.full_url, body, req.get_header("Authorization")))
        if self.fail_with:
            raise self.fail_with
        if req.get_method() == "GET":
            page = int(re.search(r"[?&]page=(\d+)", req.full_url).group(1))
            return io.BytesIO(json.dumps(self.pages[page - 1] if page <= len(self.pages) else []).encode())
        return io.BytesIO(json.dumps({"id": 99}).encode())


def test_an_existing_comment_is_edited_and_none_is_added():
    api = _FakeApi([[{"id": 41, "user": {"login": C.BOT_LOGIN}, "body": C.MARKER + " old"}]])
    assert C.upsert(api="https://api.example", repo="o/r", number=12, token="t", text="new", opener=api) == "edited"
    assert [(m, u) for m, u, _, _ in api.calls] == [
        ("GET", "https://api.example/repos/o/r/issues/12/comments?per_page=100&page=1"),
        ("PATCH", "https://api.example/repos/o/r/issues/comments/41"),
    ]
    assert api.calls[-1][2] == {"body": "new"} and api.calls[-1][3] == "Bearer t"


def test_the_first_push_creates_the_comment():
    api = _FakeApi([[{"id": 5, "user": {"login": "someone"}, "body": "LGTM"}]])
    assert C.upsert(api="https://api.example", repo="o/r", number=12, token="t", text="new", opener=api) == "created"
    assert api.calls[-1][:3] == ("POST", "https://api.example/repos/o/r/issues/12/comments", {"body": "new"})


def test_a_comment_on_the_second_page_is_still_found():
    full = [{"id": i, "user": {"login": "someone"}, "body": "chatter"} for i in range(C.PAGE_SIZE)]
    api = _FakeApi([full, [{"id": 777, "user": {"login": C.BOT_LOGIN}, "body": C.MARKER}]])
    assert C.upsert(api="https://api.example", repo="o/r", number=3, token="t", text="x", opener=api) == "edited"
    assert api.calls[-1][1].endswith("/issues/comments/777")
    assert sum(1 for m, *_ in api.calls if m == "GET") == 2


# ── it never fails the job ───────────────────────────────────────────────────────────────────────────────────────────────

def _event(tmp_path, number=12) -> dict:
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"pull_request": {"number": number, "head": {"sha": "feedface" * 5}}}), encoding="utf-8")
    return {"GITHUB_EVENT_PATH": str(p), "GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "9",
            "TESTS_OUTCOME": "success", "GITHUB_API_URL": "https://api.example"}


def test_a_refusal_from_a_forks_read_only_token_is_a_warning_and_exit_zero(tmp_path, capsys):
    refused = urllib.error.HTTPError("https://api.example", 403, "Resource not accessible by integration", {}, None)
    api = _FakeApi([], fail_with=refused)
    code = C.main([str(_report(tmp_path)), "--floors", str(_floors(tmp_path))], env=_event(tmp_path), opener=api)
    assert code == 0 and api.calls, "it tried, and the refusal did not turn the step red"
    assert "::warning title=Coverage comment not written::HTTPError" in capsys.readouterr().out


def test_anything_unexpected_is_a_warning_too(tmp_path, capsys):
    api = _FakeApi([], fail_with=RuntimeError("the API answered nonsense"))
    assert C.main([str(_report(tmp_path)), "--floors", str(_floors(tmp_path))], env=_event(tmp_path), opener=api) == 0
    assert "RuntimeError: the API answered nonsense" in capsys.readouterr().out


def test_outside_a_pull_request_or_without_a_token_nothing_is_called(tmp_path, capsys):
    api = _FakeApi([])
    assert C.main([str(_report(tmp_path))], env={}, opener=api) == 0
    push = tmp_path / "push.json"
    push.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
    assert C.main([str(_report(tmp_path))], env={"GITHUB_EVENT_PATH": str(push), "GITHUB_TOKEN": "t"}, opener=api) == 0
    env = _event(tmp_path)
    env.pop("GITHUB_TOKEN")
    assert C.main([str(_report(tmp_path))], env=env, opener=api) == 0
    assert api.calls == []
    assert "no GITHUB_TOKEN" in capsys.readouterr().out


def test_the_whole_path_writes_the_head_commit_and_the_run_link(tmp_path, capsys):
    api = _FakeApi([[]])
    code = C.main([str(_report(tmp_path)), "--floors", str(_floors(tmp_path))], env=_event(tmp_path), opener=api)
    assert code == 0 and "created on pull request #12" in capsys.readouterr().out
    method, url, body, _ = api.calls[-1]
    assert (method, url) == ("POST", "https://api.example/repos/o/r/issues/12/comments")
    assert body["body"].startswith(C.MARKER) and "`feedfacefeed`" in body["body"]
    assert "https://github.com/o/r/actions/runs/9" in body["body"]


# ── the workflow ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _job(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"name: {name}")
    nxt = re.search(r"^  [a-z][a-z-]*:\n", text[start:], re.MULTILINE)
    return text[start: start + nxt.start()] if nxt else text[start:]


def _step(job: str, name: str) -> str:
    start = job.index(f"name: {name}")
    nxt = re.search(r"^      - ", job[start:], re.MULTILINE)
    return job[start: start + (nxt.start() if nxt else len(job))]


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_comment_step_follows_the_floor_and_cannot_fail_the_job():
    job = _job("pytest — mock mode (Python 3.11)")
    assert job.index("name: Coverage — report it") < job.index("name: Post the coverage figures on the pull request")
    step = _uncommented(_step(job, "Post the coverage figures on the pull request"))
    assert "continue-on-error: true" in step
    cond = re.search(r"^\s+if: (.+)$", step, re.MULTILINE).group(1)
    for part in ("!cancelled()", "needs.scope.outputs.api == 'true'", "github.event_name == 'pull_request'"):
        assert part in cond, f"the step's condition lost {part!r}: {cond}"
    assert "always()" not in cond, "a cancelled run must not edit the comment"
    assert "GITHUB_TOKEN: ${{ github.token }}" in step and "TESTS_OUTCOME: ${{ steps.tests.outcome }}" in step
    assert "scripts/ci/coverage_comment.py coverage.json" in step
    assert re.search(r"^\s+id: tests$", _step(job, "Run tests"), re.MULTILINE), "TESTS_OUTCOME reads the tests step by its id"


def test_the_job_asks_for_exactly_the_two_permissions_and_no_other_job_or_the_file_asks_for_a_write():
    text = _uncommented(WORKFLOW.read_text(encoding="utf-8"))
    job = _uncommented(_job("pytest — mock mode (Python 3.11)"))
    block = re.search(r"^    permissions:\n((?:      [a-z-]+: [a-z]+\n)+)", job, re.MULTILINE)
    assert block, "the test job declares no permissions block"
    assert dict(re.findall(r"([a-z-]+): ([a-z]+)", block.group(1))) == {"contents": "read", "pull-requests": "write"}
    assert not re.search(r"^permissions:", text, re.MULTILINE), "a file-wide block would widen every job"
    writes = re.findall(r"^\s+[a-z-]+: write$", text, re.MULTILINE)
    assert writes == ["      pull-requests: write"], f"a write permission appeared elsewhere: {writes}"


def test_the_required_check_names_are_unchanged_and_there_is_still_no_paths_filter():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "    name: pytest — mock mode (Python 3.11)\n" in text
    assert "    name: migration apply — real Postgres 16\n" in text
    assert not re.search(r"^\s+paths(-ignore)?:", text, re.MULTILINE)
