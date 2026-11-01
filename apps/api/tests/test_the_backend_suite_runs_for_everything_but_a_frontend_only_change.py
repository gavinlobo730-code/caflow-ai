"""The backend suite is skipped only for a change that touches nothing but the two frontends.

WHAT WAS WRONG
    The scope job of `.github/workflows/backend-ci.yml` ran the backend suite only when a changed file sat under `apps/api/` (or was the
    workflow itself). But the suite reads the WHOLE repository: `CLAUDE.md` (its size limit and the design-record index), `docs/` (the
    open-items ledger, the design records, the compliance notes), `render.yaml`, `shared/` (the parity vectors both suites read) and the
    workflows. A change to any of them reported both required checks green without a test having run. That is how three merges (the
    dialog change, the TDS challan link and the Trial Balance search) each added a line to the CLAUDE.md index and took it from 199,694
    to 200,017 characters, over the 200,000 limit, before the first change that happened to touch the backend failed on it.

WHAT THIS HOLDS
    The detect step's rule is the INVERSE of the old one: the backend suite runs unless the diff is confined to `apps/web/` and
    `apps/marketing/` (the python guards that read those run in the `browser-contract` job). It is read from the workflow itself and
    applied to sample diffs, so the rule, not a spelling of it, is what is tested: a file the old rule skipped (the root document,
    a design record, the render manifest, a shared vector, a workflow) runs the suite, a frontend-only diff does not, and a diff that
    mixes a frontend with anything else does. The old allow-list is gone, and a path with an `apps/api/` prefix still runs it.
"""
import os
import re
import subprocess
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "backend-ci.yml"


def _rule() -> re.Pattern:
    """The pattern the detect step hands to `grep -qvE`: a changed file NOT matching it means the backend suite runs."""
    text = WORKFLOW.read_text(encoding="utf-8")
    found = re.findall(r"grep -qvE '([^']+)'", text)
    assert len(found) == 1, f"the detect step has {len(found)} 'grep -qvE' rules, expected exactly one: {found}"
    return re.compile(found[0])


def runs_the_suite(changed: list[str]) -> bool:
    """What the step does with `grep -qvE <rule> <<<"$changed"`: true when any line does not match the rule."""
    rule = _rule()
    return any(not rule.search(line) for line in (changed or [""]))      # grep matches anywhere in the line, so search and not match


def test_a_file_the_suite_reads_runs_the_suite():
    for path in ("CLAUDE.md", "docs/open-items/README.md", "docs/design-record/frontend.md", "docs/compliance/00-how-to-read-this.md",
                 "render.yaml", "shared/gst-parity-vectors.json", ".github/workflows/backend-ci.yml", "README.md",
                 "apps/api/main.py", "apps/api/tests/test_x.py", "scripts/open_items_counts.py"):
        assert runs_the_suite([path]), f"{path} is read by the backend tests and did not run them"


def test_a_change_confined_to_the_frontends_does_not():
    assert not runs_the_suite(["apps/web/app/page.tsx"])
    assert not runs_the_suite(["apps/marketing/app/page.tsx", "apps/web/lib/x.ts"])


def test_a_frontend_plus_anything_else_runs_it():
    assert runs_the_suite(["apps/web/app/page.tsx", "docs/open-items/post-demo-A-mine.md"])
    assert runs_the_suite(["apps/web/app/page.tsx", "apps/api/main.py"])
    assert runs_the_suite(["apps/marketing/app/page.tsx", "CLAUDE.md"])


def test_the_rule_is_anchored_so_a_lookalike_path_is_not_a_frontend():
    assert runs_the_suite(["apps/webhooks/x.py"]), "apps/webhooks is not apps/web"
    assert runs_the_suite(["docs/apps/web/notes.md"]), "a path that merely contains apps/web is not under it"
    assert runs_the_suite(["apps/marketing-old/x.ts"])


def test_an_empty_diff_runs_the_suite_which_is_the_safe_direction():
    assert runs_the_suite([])


def test_the_old_allow_list_is_gone_and_the_reason_is_written_beside_the_rule():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "grep -qE '^(apps/api/|" not in text, "the allow-list that skipped CLAUDE.md and docs/ is back"
    assert "READS THE WHOLE REPOSITORY" in text


# ── the step itself, run against a real repository ─────────────────────────────────────────────────────────────────────
# The tests above pin the PATTERN. These run the step's own shell text (taken from the workflow, with GitHub's expressions filled
# in) over a throw-away git history, so the wiring around the pattern is what is tested: which diff is read, how the answer is
# written, and what a long list of files does to it.

def _detect_script() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(lines) if line.strip() == "- id: detect")
    run = next(i for i in range(at, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip())
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    script = "\n".join(body)
    script = script.replace("${{ github.event_name }}", "pull_request")
    script = script.replace("${{ github.event.pull_request.base.sha }}", "$BASE_SHA")
    script = script.replace("${{ github.event.pull_request.head.sha }}", "$HEAD_SHA")
    script = script.replace("${{ github.event.before }}", "$BASE_SHA").replace("${{ github.sha }}", "$HEAD_SHA")      # the push branch
    assert "${{" not in script, "the detect step uses an expression this test does not fill in"
    return script


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True,
                         env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
                              "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"})
    return out.stdout.strip()


def _outputs_for(tmp_path: Path, before: dict[str, str], change) -> dict[str, str]:
    """Commit `before`, let `change(repo)` edit the tree, commit again, and run the detect step over the two commits."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    for name, text in before.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    change(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD")
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    done = subprocess.run(["bash", "-c", _detect_script()], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "BASE_SHA": base, "HEAD_SHA": head, "GITHUB_OUTPUT": str(out_file)})
    assert done.returncode == 0, done.stderr
    return dict(line.split("=", 1) for line in out_file.read_text().splitlines() if "=" in line)


def test_the_step_skips_a_frontend_only_diff_and_runs_for_a_document(tmp_path):
    base = {"apps/web/a.ts": "1", "apps/api/x.py": "1", "CLAUDE.md": "1"}
    got = _outputs_for(tmp_path / "web", base, lambda r: (r / "apps/web/a.ts").write_text("2"))
    assert got == {"api": "false", "web": "true"}
    got = _outputs_for(tmp_path / "doc", base, lambda r: (r / "CLAUDE.md").write_text("2"))
    assert got == {"api": "true", "web": "false"}
    got = _outputs_for(tmp_path / "both", base, lambda r: ((r / "CLAUDE.md").write_text("2"), (r / "apps/web/a.ts").write_text("2")))
    assert got == {"api": "true", "web": "true"}


def test_a_backend_file_moved_into_a_frontend_still_runs_the_suite(tmp_path):
    """Rename detection lists only the NEW path of a moved file; the old one, under apps/api, is what makes this a backend change."""
    text = "def f():\n    return 'a body long enough for git to see the same file moved'\n" * 10

    def move(repo: Path) -> None:
        (repo / "apps/web").mkdir(parents=True, exist_ok=True)
        (repo / "apps/api/x.py").rename(repo / "apps/web/x.py")

    got = _outputs_for(tmp_path, {"apps/api/x.py": text, "apps/web/a.ts": "1"}, move)
    assert got["api"] == "true", "a file deleted from apps/api read as a frontend-only change"


def test_a_long_list_of_changed_files_does_not_make_the_step_skip_the_suite(tmp_path):
    """With `printf | grep -q` under pipefail the answer for a list longer than a pipe buffer depended on a race with SIGPIPE."""
    def many(repo: Path) -> None:
        (repo / "docs").mkdir(exist_ok=True)
        for i in range(3000):
            (repo / "docs" / f"{'n' * 40}-{i:05d}.md").write_text(str(i))

    for attempt in range(3):
        got = _outputs_for(tmp_path / str(attempt), {"apps/web/a.ts": "1"}, many)
        assert got["api"] == "true", f"attempt {attempt}: a long list of documents skipped the suite"


def test_the_step_reads_the_diff_without_rename_detection_and_without_a_pipe_into_grep():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'git diff --name-only --no-renames "$base" "$head"' in text
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))      # the comment beside it names the pipe
    assert not re.search(r'printf [^\n]*\| *grep', code), "a printf piped into grep -q is back in the detect step"


def test_the_frontend_suite_runs_for_a_change_to_a_shared_vector_and_reads_the_diff_the_same_way():
    """`shared/` holds the vectors the browser's tests read; the frontend job used to look at `apps/web/` alone."""
    text = (WORKFLOW.parent / "frontend-ci.yml").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    rule = re.search(r"grep -qE '([^']+)' <<<\"\$changed\"", code)
    assert rule, "the frontend detect step no longer reads the changed list with a here-string"
    pattern = re.compile(rule.group(1))
    for path in ("apps/web/app/page.tsx", "shared/gst-parity-vectors.json", ".github/workflows/frontend-ci.yml"):
        assert pattern.search(path), f"{path} is read by the frontend job and did not run it"
    for path in ("apps/api/main.py", "CLAUDE.md", "apps/webhooks/x.py", "docs/shared/x.md"):
        assert not pattern.search(path), f"{path} ran the frontend job for nothing"
    assert "git diff --name-only --no-renames" in code and not re.search(r"git diff[^\n]*\\\n[^\n]*\| *grep", text)
