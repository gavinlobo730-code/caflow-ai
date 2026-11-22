"""A pull request that changes only `docs/` and `CLAUDE.md` runs the tests that read them, and nothing it could not break (the docs lane).

WHAT WAS WRONG
    The backend suite reads the whole repository, so a change to a document had to run all of it: about 45 minutes for a sentence in the
    ledger, because three merges had once taken CLAUDE.md over its size limit before a change that touched the backend ran the test. The
    cost of that safety was paid on every notes change, which is most of what happens between sessions.

WHAT THIS HOLDS
    * `scripts/ci/tests_reading_the_docs.py` finds the test modules that read the documents, by RULE (a path constant outside a docstring,
      a path built with `/`, a walk from the repository root, an import of a module that does), and each rule is shown on a synthetic tests
      directory: the spelling it exists for is selected, and a docstring, a comment and a lookalike word are not. A module that reaches the
      documents only through a test module it imports is selected, and `e2e_harness` is not a way in (it would select the suite).
    * On the real tree the list is not empty, it holds the guards that exist for exactly this (the ledger, the CLAUDE.md size limit and
      design-record index, the coming-soon register), it holds only test modules, and the real-Postgres set holds the one that reads the
      documents. A second, independent look (a constant that names a thing only the documents hold, such as `open-items`) finds no module
      outside the list.
    * The workflow's `detect` step puts a change in the docs lane exactly when every changed file is under `docs/`, is `CLAUDE.md` or is
      under one of the two frontends, with at least one document among them, and only for a pull request: a document plus a line of code,
      a document plus a workflow, a frontend alone (the frontend rule's), an empty diff and a PUSH are not. It is run for real over
      throw-away git histories, like the rule beside it.
    * The workflow gives the docs lane its own steps in both required jobs, under the unchanged job names, and the whole-suite, lint and
      coverage steps are the ones it skips. The lane is the ONLY thing that changed: the whole-suite steps are unchanged for everything else.
    * A SCREEN CHANGE WITH ITS NOTES (22-11-2026). Nearly every change to a screen edits a line of the ledger too, and that line sent it
      through the whole suite, about fifty minutes, for a diff no backend test but the readers of those files can see. It is the lane now,
      and where a frontend is in the diff the lane's steps ADD the modules that read a frontend: the required mock job runs both derived
      lists as one, and the migration job the real-Postgres ones. The two steps' own shell is run for real here, against stand-in finders
      and a stand-in pytest: a document alone runs the document readers, a document with a frontend runs both sets once each, a finder
      that fails stops the step before pytest, and a list that comes out empty never reaches pytest bare.
"""
from __future__ import annotations

import ast
import functools
import re
import subprocess
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "backend-ci.yml"
sys.path.insert(0, str(API / "scripts" / "ci"))
import tests_reading_the_docs as finder  # noqa: E402

from tests.test_the_backend_suite_runs_for_everything_but_a_frontend_only_change import (  # noqa: E402
    _detect_script, _git)


# ── the finder's rules, each on a synthetic tests directory ──────────────────────────────────────────────────────────────────────

def _tests_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "tests"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def _selected(tmp_path: Path, files: dict[str, str]) -> set[str]:
    return {p.name for p in finder.modules_reading_the_docs(_tests_dir(tmp_path, files))}


@pytest.mark.parametrize("spelling", [
    'ROOT = Path(__file__).parents[3]\ntext = (ROOT / "docs" / "open-items" / "README.md").read_text()\n',
    'text = open("docs/open-items/README.md").read()\n',
    'text = open("../../docs/x.md").read()\n',
    'text = (ROOT / "CLAUDE.md").read_text()\n',
    'p = f"{ROOT}/docs/open-items/{name}"\n',
    'DOCS = "docs"\n',
    'from pathlib import Path\nfor f in Path(__file__).parents[3].rglob("*.md"):\n    f.read_text()\n',
])
def test_each_spelling_of_a_read_selects_its_module(tmp_path, spelling):
    assert "test_a.py" in _selected(tmp_path, {"test_a.py": spelling})


@pytest.mark.parametrize("prose", [
    '"""Reads nothing: it only says docs/open-items/README.md and CLAUDE.md in its docstring."""\n\ndef test_x():\n    assert True\n',
    "# the ledger lives in docs/open-items and CLAUDE.md names it\n\ndef test_x():\n    assert True\n",
    'def test_x():\n    """A function docstring about docs/ and CLAUDE.md."""\n    assert True\n',
    'def test_x():\n    mydocs = 1\n    docstring = "a docstring is not a document"\n    assert mydocs and docstring\n',
])
def test_prose_a_comment_and_a_lookalike_word_do_not(tmp_path, prose):
    assert _selected(tmp_path, {"test_a.py": prose}) == set()


def test_a_module_that_reaches_the_documents_only_through_an_import_is_selected(tmp_path):
    got = _selected(tmp_path, {
        "test_reader.py": 'text = open("CLAUDE.md").read()\n',
        "test_b.py": "from tests.test_reader import text\n",
        "test_c.py": "import test_b\n",
        "test_unrelated.py": "def test_x():\n    assert 1\n",
    })
    assert got == {"test_reader.py", "test_b.py", "test_c.py"}, "the walk must go through the imports, however long the chain"


def test_a_helper_that_reads_the_documents_selects_the_modules_that_import_it_and_is_not_itself_run(tmp_path):
    got = _selected(tmp_path, {
        "_helper.py": 'DOCS = "docs"\n',
        "test_user.py": "from tests._helper import DOCS\n",
        "test_other.py": "def test_x():\n    assert 1\n",
    })
    assert got == {"test_user.py"}, "a helper is not a test module; the modules that import it are"


def test_a_helper_imported_by_everyone_is_not_a_way_in_unless_it_reads_the_documents_itself(tmp_path):
    files = {"e2e_harness.py": "class FakeDB:\n    pass\n"}
    files.update({f"test_{i}.py": "from tests.e2e_harness import FakeDB\n" for i in range(5)})
    assert _selected(tmp_path, files) == set(), "a closure through a helper that reads nothing would select the whole suite"


def test_a_file_that_cannot_be_parsed_is_run_rather_than_skipped(tmp_path):
    assert "test_broken.py" in _selected(tmp_path, {"test_broken.py": "def (:\n"}), "not known NOT to read the documents: run it"


# ── the real tree ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _real_list() -> tuple[Path, ...]:
    return tuple(finder.modules_reading_the_docs())


def _names() -> set[str]:
    return {p.name for p in _real_list()}


def test_the_guards_that_exist_for_the_documents_are_in_the_list():
    names = _names()
    assert len(names) >= 40, f"only {len(names)} modules read the documents: the finder has stopped seeing them"
    for must in ("test_the_open_items_ledger_is_well_formed.py",
                 "test_the_design_record_index_matches_the_files_and_claude_md_stays_small.py",
                 "test_the_coming_soon_register_is_well_formed.py",
                 "test_claude_md_states_the_facts_the_code_holds.py",
                 "test_a_docs_only_change_runs_every_test_that_reads_the_docs.py"):
        assert must in names, f"{must} reads the documents and the docs lane would not run it"


def test_the_list_holds_only_test_modules_and_both_sets_are_what_the_flags_say():
    names = _names()
    assert all(n.startswith("test_") and n.endswith(".py") for n in names)
    mock = {p.name for p in _real_list() if not p.stem.endswith("_pg")}
    pg = {p.name for p in _real_list() if p.stem.endswith("_pg")}
    assert mock and pg and mock | pg == names and not (mock & pg)
    assert "test_every_client_table_is_assignment_scoped_or_says_why_pg.py" in pg


def test_the_command_line_never_prints_nothing_for_the_mock_or_the_whole_set():
    for flag in ([], ["--mock"]):
        done = subprocess.run([sys.executable, str(API / "scripts" / "ci" / "tests_reading_the_docs.py"), *flag],
                              capture_output=True, text=True)
        assert done.returncode == 0 and done.stdout.strip(), done.stderr
        assert all(line.startswith("tests/test_") for line in done.stdout.splitlines())


def test_a_second_independent_look_finds_no_module_outside_the_list():
    """A constant that names a thing only the documents hold (`open-items`, `design-record`, a ledger file) in a module the finder did not
    select would be a read it missed. Not the same rule: a different angle on the same question."""
    only_the_documents_hold = re.compile(r"open-items|design-record|checked-closed|owner-list|new-findings|post-demo-|schema-drift\.md")
    names = _names()
    missed = []
    for path in sorted((API / "tests").glob("test_*.py")):
        if path.name in names:
            continue
        tree = ast.parse(path.read_text(errors="ignore"))
        skip = finder._docstring_ids(tree)
        if any(isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and only_the_documents_hold.search(n.value)
               for n in ast.walk(tree)):
            missed.append(path.name)
    assert not missed, f"modules that name a document-only thing and are not in the docs lane: {missed}"


# ── the detect step: what is a docs-only change ───────────────────────────────────────────────────────────────────────────────

BASE = {"docs/a.md": "1", "docs/open-items/x.md": "1", "CLAUDE.md": "1", "apps/api/x.py": "1", "apps/web/a.ts": "1",
        ".github/workflows/backend-ci.yml": "1", "README.md": "1"}


def _docs_only(tmp_path: Path, edit, *, event: str = "pull_request") -> str:
    import os
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    for name, text in BASE.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    edit(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head", "--allow-empty")
    head = _git(repo, "rev-parse", "HEAD")
    out = tmp_path / "out"
    out.write_text("")
    # The step's own text with the event name swapped, so a push is judged by the same lines a pull request is.
    script = _detect_script().replace('[ "pull_request" = "pull_request" ]', f'[ "{event}" = "pull_request" ]')
    done = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "BASE_SHA": base, "HEAD_SHA": head, "GITHUB_OUTPUT": str(out)})
    assert done.returncode == 0, done.stderr
    return dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)["docs_lane"]


def _write(*names: str):
    def edit(repo: Path) -> None:
        for n in names:
            (repo / n).parent.mkdir(parents=True, exist_ok=True)
            (repo / n).write_text("2")
    return edit


@pytest.mark.parametrize("names, expected", [
    (("docs/a.md",), "true"),
    (("CLAUDE.md",), "true"),
    (("docs/a.md", "docs/open-items/x.md", "CLAUDE.md"), "true"),
    (("docs/a.md", "apps/api/x.py"), "false"),                        # a document plus a line of code
    (("CLAUDE.md", ".github/workflows/backend-ci.yml"), "false"),    # a document plus the workflow itself
    (("docs/a.md", "apps/web/a.ts"), "true"),                         # a screen change with its notes (22-11-2026)
    (("CLAUDE.md", "apps/marketing/a.ts"), "true"),                   # ... and the public site with its notes
    (("docs/a.md", "apps/web/a.ts", "apps/marketing/a.ts"), "true"),
    (("docs/a.md", "apps/web/a.ts", "apps/api/x.py"), "false"),       # ... but not with a line of code in it
    (("docs/a.md", "apps/web/a.ts", ".github/workflows/backend-ci.yml"), "false"),
    (("docs/a.md", "apps/web/a.ts", "shared/vectors.json"), "false"), # a shared vector is read by both suites: the whole suite
    (("apps/web/a.ts",), "false"),                                    # a frontend alone is the frontend rule's, not this one
    (("apps/web/a.ts", "apps/marketing/a.ts"), "false"),
    (("README.md",), "false"),                                        # the root README is not CLAUDE.md and not under docs/
    (("apps/api/x.py",), "false"),
])
def test_the_lane_exactly_when_every_changed_file_is_a_document_or_a_frontend_with_a_document_among_them(tmp_path, names, expected):
    assert _docs_only(tmp_path, _write(*names)) == expected


def test_a_lookalike_path_is_not_a_document(tmp_path):
    for i, name in enumerate(("apps/api/docs/x.md", "docsX/a.md", "docs.md", "CLAUDE.md.bak", "apps/web/docs/a.md")):
        assert _docs_only(tmp_path / str(i), _write(name)) == "false", name


def test_a_lookalike_of_a_frontend_beside_a_document_is_not_the_lane(tmp_path):
    """The lane admits `apps/web/` and `apps/marketing/` beside a document and nothing that only looks like them."""
    for i, name in enumerate(("apps/webX/a.ts", "apps/web.ts", "apps/marketing2/a.ts", "apps/api/web/a.ts", "web/a.ts", "apps/a.ts")):
        assert _docs_only(tmp_path / str(i), _write("docs/a.md", name)) == "false", name


def test_an_empty_diff_is_not_the_lane(tmp_path):
    assert _docs_only(tmp_path, lambda r: None) == "false"


def test_a_push_is_never_the_lane_so_the_whole_suite_runs_after_every_merge(tmp_path):
    assert _docs_only(tmp_path, _write("docs/a.md"), event="push") == "false"
    assert _docs_only(tmp_path / "with-a-screen", _write("docs/a.md", "apps/web/a.ts"), event="push") == "false"


def test_a_docs_only_change_still_runs_the_suite_it_is_marked_api_true():
    """`api` stays true for a document: the docs lane is a narrower suite, not a skipped one, and the jobs' install steps key on it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "docs_lane=true" in text and "api=false" in text
    detect = text[text.index("- id: detect"):text.index("  test:")]
    assert detect.count('echo "api=false"') == 1, "only the frontend-only branch may set api=false"


# ── the workflow's steps ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# Read from the workflow's own text: PyYAML is not in the locked test set, and a test that needs a new dependency to guard a workflow
# would be the first thing to go red on a lock change.

def _jobs() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("\njobs:\n")
    body = text[start:]
    marks = list(re.finditer(r"^  ([a-z][a-z-]*):[ ]*$", body, re.M))
    return {m.group(1): body[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(body)] for i, m in enumerate(marks)}


def _steps(job: str) -> list[dict]:
    out = []
    for block in re.split(r"^      - ", job, flags=re.M)[1:]:
        name = re.search(r"^(?:name: )(.+)$", block, re.M)
        cond = re.search(r"^ {8}if: (.+)$|^if: (.+)$", block, re.M)
        out.append({"name": (name.group(1).strip() if name else ""),
                    "if": next((g for g in (cond.groups() if cond else ()) if g), "").strip(),
                    "text": block})
    return out


def _step(job: str, starts: str) -> dict:
    found = [s for s in _steps(job) if s["name"].startswith(starts)]
    assert len(found) == 1, f"expected one step starting {starts!r}, found {len(found)}"
    return found[0]


def test_the_required_jobs_keep_their_names_and_the_scope_job_reports_the_new_output():
    text = WORKFLOW.read_text(encoding="utf-8")
    jobs = _jobs()
    assert re.search(r"^    name: pytest — mock mode \(Python 3\.11\)$", jobs["test"], re.M)
    assert re.search(r"^    name: migration apply — real Postgres 16$", jobs["migrations"], re.M)
    assert "docs_lane: ${{ steps.detect.outputs.docs_lane }}" in jobs["scope"]
    # No `paths:` filter on a workflow that carries a required check (the top of the workflow says why).
    on = text[text.index("\non:\n"): text.index("\nconcurrency:")]
    assert "paths" not in on, "a path filter on a workflow carrying a required check"


def test_the_whole_suite_lint_and_coverage_steps_skip_the_docs_lane_and_nothing_else_changed_for_them():
    jobs = _jobs()
    skipping = "needs.scope.outputs.api == 'true' && needs.scope.outputs.docs_lane != 'true'"
    for starts in ("Lint — ruff", "Run tests (in-memory", "Coverage — report", "Keep the coverage report"):
        assert _step(jobs["test"], starts)["if"] == skipping, starts
    assert _step(jobs["migrations"], "Run real-Postgres regression suite")["if"] == skipping
    # Steps both lanes need are unchanged: they key on the backend alone, so the lane has Python and its dependencies.
    assert _step(jobs["test"], "Install dependencies")["if"] == "needs.scope.outputs.api == 'true'"
    assert _step(jobs["migrations"], "Install dependencies")["if"] == "needs.scope.outputs.api == 'true'"
    assert _step(jobs["migrations"], "Install psql client")["if"] == "needs.scope.outputs.api == 'true'"


def test_the_docs_lane_steps_run_the_derived_list_and_only_in_the_lane():
    jobs = _jobs()
    lane = "needs.scope.outputs.api == 'true' && needs.scope.outputs.docs_lane == 'true'"
    mock = _step(jobs["test"], "Run the tests that read docs/")
    assert mock["if"] == lane and "tests_reading_the_docs.py --mock" in mock["text"] and 'pytest "${modules[@]}"' in mock["text"]
    pg = _step(jobs["migrations"], "Run the real-Postgres tests that read docs/")
    assert pg["if"] == lane and "tests_reading_the_docs.py --pg" in pg["text"] and 'pytest "${modules[@]}"' in pg["text"]
    assert "HARNESS_PG" in pg["text"], "the real-Postgres modules need the database the job started"
    # An empty list must end the step, never reach pytest bare (a bare pytest collects the whole suite).
    assert re.search(r'-eq 0 \][\s\S]*exit 0', pg["text"])
    assert "set -euo pipefail" in mock["text"] and "set -euo pipefail" in pg["text"]


def test_the_pull_request_comment_about_coverage_is_not_posted_for_a_lane_that_measured_nothing():
    step = _step(_jobs()["test"], "Post the coverage figures")
    assert "docs_lane != 'true'" in step["if"]


# ── a screen change with its notes: the lane's steps add the modules that read a frontend ─────────────────────────────────────────

def test_the_lane_steps_add_the_frontend_readers_only_where_a_frontend_changed():
    jobs = _jobs()
    mock = _step(jobs["test"], "Run the tests that read docs/")
    pg = _step(jobs["migrations"], "Run the real-Postgres tests that read docs/")
    for step in (mock, pg):
        assert "FRONTEND_CHANGED: ${{ needs.scope.outputs.web }}" in step["text"], "the step must be told whether a frontend changed"
        assert 'if [ "$FRONTEND_CHANGED" = "true" ]; then' in step["text"]
        assert "tests_reading_the_browser.py" in step["text"]
    # The real-Postgres step takes only the real-Postgres readers of a frontend; the mock step takes the list as the frontend job does.
    assert "_pg\\.py$" in pg["text"] or r"_pg\.py$" in pg["text"]
    # The mock list may never be empty when it reaches pytest: an empty one ends the step red.
    assert re.search(r'-eq 0 \][\s\S]*exit 1', mock["text"])
    # The frontend job is still the frontend-only path, so the lane does not run the same modules twice.
    assert re.search(r"^    if: needs\.scope\.outputs\.web == 'true' && needs\.scope\.outputs\.api != 'true'$", jobs["browser-contract"], re.M)


def _run_script(step: dict) -> str:
    """The shell of a step's `run: |`, as the runner would execute it."""
    lines = step["text"].splitlines()
    at = next(i for i, line in enumerate(lines) if line.strip() == "run: |")
    indent = len(lines[at]) - len(lines[at].lstrip())
    body = []
    for line in lines[at + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line[indent + 2:] if line.strip() else "")
    return "\n".join(body)


def _run_lane_step(tmp_path: Path, job: str, starts: str, *, frontend_changed: str, docs: str, browser: str,
                   docs_exit: int = 0, browser_exit: int = 0) -> tuple[int, list[str], str]:
    """Run a lane step's own shell in a throw-away `apps/api`: stand-in finders print what the test says, and a stand-in `pytest`
    records its arguments. Returns the exit code, the modules pytest was handed (in order) and the step's output."""
    import os
    api = tmp_path / "api"
    ci = api / "scripts" / "ci"
    ci.mkdir(parents=True)
    # `--mock` / `--pg` are accepted and ignored: which set a flag selects is the finder's own test, above. What is held here is what the
    # STEP does with the answer.
    (ci / "tests_reading_the_docs.py").write_text(f"import sys\nsys.stdout.write({docs!r})\nsys.exit({docs_exit})\n")
    (ci / "tests_reading_the_browser.py").write_text(f"import sys\nsys.stdout.write({browser!r})\nsys.exit({browser_exit})\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "pytest-args"
    (bin_dir / "pytest").write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{seen}"\n')
    (bin_dir / "pytest").chmod(0o755)
    (bin_dir / "python3").write_text(f'#!/usr/bin/env bash\nexec "{sys.executable}" "$@"\n')
    (bin_dir / "python3").chmod(0o755)
    step = _step(_jobs()[job], starts)
    done = subprocess.run(["bash", "-c", _run_script(step)], cwd=api, capture_output=True, text=True,
                          env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FRONTEND_CHANGED": frontend_changed})
    handed = [a for a in (seen.read_text().splitlines() if seen.exists() else []) if a.startswith("tests/")]
    return done.returncode, handed, done.stdout + done.stderr


MOCK = ("test", "Run the tests that read docs/")
PG = ("migrations", "Run the real-Postgres tests that read docs/")
# Stand-in module names, deliberately NOT shaped like a test's name: `test_a_test_named_in_a_test_exists.py` reads every such word in a test
# file as a claim that the test exists.
DOCS_LIST = "tests/ledger_reader.py\ntests/both_reader.py\n"
BROWSER_LIST = "tests/screen_reader.py\ntests/both_reader.py\ntests/columns_reader_pg.py\n"


def test_the_mock_step_runs_the_document_readers_alone_for_a_document(tmp_path):
    code, handed, out = _run_lane_step(tmp_path, *MOCK, frontend_changed="false", docs=DOCS_LIST, browser=BROWSER_LIST)
    assert code == 0, out
    assert handed == ["tests/both_reader.py", "tests/ledger_reader.py"], "a document alone must not run the frontend's readers"


def test_the_mock_step_runs_both_sets_once_each_for_a_screen_change_with_its_notes(tmp_path):
    code, handed, out = _run_lane_step(tmp_path, *MOCK, frontend_changed="true", docs=DOCS_LIST, browser=BROWSER_LIST)
    assert code == 0, out
    assert handed == ["tests/both_reader.py", "tests/columns_reader_pg.py", "tests/ledger_reader.py", "tests/screen_reader.py"], \
        "the two derived lists, as one, with a module that reads both run once"


@pytest.mark.parametrize("failing", ["docs", "browser"])
def test_a_finder_that_fails_stops_the_mock_step_before_pytest(tmp_path, failing):
    code, handed, out = _run_lane_step(tmp_path, *MOCK, frontend_changed="true", docs=DOCS_LIST, browser=BROWSER_LIST,
                                       docs_exit=1 if failing == "docs" else 0, browser_exit=1 if failing == "browser" else 0)
    assert code != 0 and handed == [], f"a finder that failed must end the step red with nothing run: {out}"


def test_an_empty_mock_list_never_reaches_pytest(tmp_path):
    """A bare `pytest` collects the whole suite, which would look like the lane and cost the budget it exists to save."""
    code, handed, out = _run_lane_step(tmp_path, *MOCK, frontend_changed="false", docs="", browser=BROWSER_LIST)
    assert code == 1 and handed == [], out


def test_the_real_postgres_step_takes_only_the_real_postgres_readers_of_a_frontend(tmp_path):
    code, handed, out = _run_lane_step(tmp_path, *PG, frontend_changed="true", docs="tests/scoped_reader_pg.py\n", browser=BROWSER_LIST)
    assert code == 0, out
    assert handed == ["tests/columns_reader_pg.py", "tests/scoped_reader_pg.py"]
    code, handed, out = _run_lane_step(tmp_path / "doc", *PG, frontend_changed="false", docs="tests/scoped_reader_pg.py\n", browser=BROWSER_LIST)
    assert code == 0 and handed == ["tests/scoped_reader_pg.py"], out


def test_the_real_postgres_step_with_nothing_to_run_ends_clean_and_runs_nothing(tmp_path):
    code, handed, out = _run_lane_step(tmp_path, *PG, frontend_changed="true", docs="", browser="tests/screen_reader.py\n")
    assert code == 0 and handed == [], out
    assert "nothing to run" in out


def test_the_real_frontend_finder_has_real_postgres_modules_for_the_lane_to_take():
    """Not vacuous on the real tree: the three frontend guards that need a database are in the derived list, so a screen change with its
    notes gets them in the migration job."""
    done = subprocess.run([sys.executable, str(API / "scripts" / "ci" / "tests_reading_the_browser.py")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    pg = [line for line in done.stdout.splitlines() if line.endswith("_pg.py")]
    assert "tests/test_frontend_columns_exist_pg.py" in pg, pg
