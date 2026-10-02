"""The Python lint is a ratchet, and its baseline may only shrink (engineering-01).

THE RULE, NOT A LIST OF TODAY'S FINDINGS
    `ruff check` over apps/api reports 1,154 findings on the day this was written, so the lint cannot simply fail
    on any: it would be red for ever. `scripts/ci/ruff_ratchet.py` therefore compares the findings with a committed
    baseline and fails on a finding the baseline does not cover, and on a baseline line that no longer fires. This
    module holds the three things that make that more than a script:

      * the COMPARISON is right, on synthetic findings, so it needs no ruff and runs everywhere — a new finding, a
        grown one, a moved one, a fixed one, and a function already over the size limit getting longer;
      * the TOOL is configured to see what the finding names (an unused import, a bare `except:`, a four-hundred
        line function) and the ratchet reads each as new, which is the item's own "turns the check red";
      * the CI step exists, sits in the required job, has no `paths:` filter, and the limits cannot be loosened
        without this file saying so.

WHAT DOES NOT RUN WITHOUT RUFF
    The two tests that call the real tool skip where ruff is not installed, and FAIL where `CI` is set: a lint that
    did not run is not a clean lint (the same rule the script's exit code 2 states). requirements-dev.txt pins it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
SCRIPT = API / "scripts" / "ci" / "ruff_ratchet.py"
BASELINE = API / "scripts" / "ci" / "ruff_baseline.txt"
WORKFLOW = REPO / ".github" / "workflows" / "backend-ci.yml"


def _ratchet():
    spec = importlib.util.spec_from_file_location("ruff_ratchet", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ruff_ratchet"] = mod
    spec.loader.exec_module(mod)
    return mod


R = _ratchet()


def _ruff_command() -> str | None:
    if shutil.which("ruff"):
        return "ruff"
    probe = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True)
    return f"{sys.executable} -m ruff" if probe.returncode == 0 else None


def _need_ruff() -> str:
    cmd = _ruff_command()
    if cmd is None:
        if os.environ.get("CI"):
            pytest.fail("ruff is not installed in CI — `pip install -r requirements-dev.txt`. A lint that did not "
                        "run is not a clean lint.")
        pytest.skip("ruff is not installed here (requirements-dev.txt pins it)")
    return cmd


def d(path, row, code, message="m", col=1):
    return R.Diagnostic(path, row, col, code, message)


# ── which scope a finding belongs to ────────────────────────────────────────────

SOURCE = textwrap.dedent('''\
    import os                       # 1  module scope

    def outer():                    # 3
        x = 1                       # 4
        def inner():                # 5
            y = 2                   # 6
            return y                # 7
        return inner                # 8

    class Box:                      # 10
        z = 1                       # 11
        def method(self):           # 12
            w = 3                   # 13
            return w                # 14

    async def later():              # 16
        v = 4                       # 17
        return v                    # 18
''')


@pytest.mark.parametrize("row,scope", [
    (1, "<module>"), (4, "outer"), (6, "outer.inner"), (8, "outer"),
    (11, "Box"), (13, "Box.method"), (17, "later"), (9, "<module>"),
])
def test_a_finding_is_scoped_to_the_innermost_def_or_class_holding_its_line(row, scope):
    assert R.scope_of(R.scope_spans(SOURCE), row) == scope


def test_a_file_that_does_not_parse_is_scoped_to_the_module_rather_than_crashing():
    assert R.scope_spans("def broken(:\n") == []
    assert R.scope_of([], 3) == R.MODULE_SCOPE


def test_the_scope_survives_the_lines_above_it_moving():
    """The reason a finding is not keyed on its line number: add a blank line above and nothing is new."""
    before = R.to_counts([d("a.py", 4, "F841")], lambda p: SOURCE)
    after = R.to_counts([d("a.py", 5, "F841")], lambda p: "\n" + SOURCE)
    assert before == after == {("a.py", "F841", "outer"): 1}


# ── counting ────────────────────────────────────────────────────────────────────

def test_findings_of_one_rule_in_one_scope_are_counted_and_other_scopes_are_kept_apart():
    counts = R.to_counts([d("a.py", 4, "F841"), d("a.py", 4, "F841"), d("a.py", 6, "F841"), d("a.py", 1, "F401")],
                         lambda p: SOURCE)
    assert counts == {("a.py", "F841", "outer"): 2, ("a.py", "F841", "outer.inner"): 1,
                      ("a.py", "F401", "<module>"): 1}


def test_a_size_rule_stores_the_measured_size_not_a_count():
    counts = R.to_counts([d("a.py", 3, "C901", "`outer` is too complex (23 > 15)"),
                          d("a.py", 12, "PLR0915", "Too many statements (91 > 75)")], lambda p: SOURCE)
    assert counts == {("a.py", "C901", "outer"): 23, ("a.py", "PLR0915", "Box.method"): 91}


def test_a_size_that_cannot_be_read_is_refused_not_counted_as_one():
    """Reading it as 1 would let a function grow without limit, which is the thing the ratchet is for."""
    with pytest.raises(R.RatchetError):
        R.to_counts([d("a.py", 3, "C901", "this message has no figures")], lambda p: SOURCE)


# ── the verdict ─────────────────────────────────────────────────────────────────

BASE = {("a.py", "F401", "<module>"): 2, ("a.py", "C901", "big"): 20}


def test_the_baseline_itself_is_clean():
    assert R.judge(dict(BASE), BASE).clean


def test_a_finding_in_a_new_place_is_new():
    v = R.judge({**BASE, ("b.py", "F401", "<module>"): 1}, BASE)
    assert set(v.new) == {("b.py", "F401", "<module>")} and not v.stale


def test_one_more_finding_where_there_already_are_some_is_new():
    """The case a per-file or per-rule count lets through: an unused import in a file that has two already."""
    v = R.judge({**BASE, ("a.py", "F401", "<module>"): 3}, BASE)
    assert v.new == {("a.py", "F401", "<module>"): (3, 2)}


def test_a_function_already_over_the_limit_may_not_get_longer():
    v = R.judge({**BASE, ("a.py", "C901", "big"): 21}, BASE)
    assert v.new == {("a.py", "C901", "big"): (21, 20)}


def test_a_new_function_over_the_limit_is_new():
    v = R.judge({**BASE, ("a.py", "PLR0915", "fresh"): 400}, BASE)
    assert ("a.py", "PLR0915", "fresh") in v.new


def test_a_fixed_finding_is_stale_and_so_is_a_function_that_got_shorter():
    gone = R.judge({("a.py", "C901", "big"): 20}, BASE)
    assert set(gone.stale) == {("a.py", "F401", "<module>")} and not gone.new
    shorter = R.judge({**BASE, ("a.py", "C901", "big"): 17}, BASE)
    assert shorter.stale == {("a.py", "C901", "big"): (17, 20)} and not shorter.clean


def test_moving_a_finding_to_another_scope_is_new_and_stale_never_a_quiet_pass():
    v = R.judge({("a.py", "F401", "<module>"): 1, ("a.py", "F401", "other"): 1, ("a.py", "C901", "big"): 20}, BASE)
    assert ("a.py", "F401", "other") in v.new and ("a.py", "F401", "<module>") in v.stale


def test_lowering_removes_and_shrinks_and_never_adds_or_raises():
    """`--update` is the only writer after the first baseline, and it must not be able to absorb a finding."""
    current = {("a.py", "F401", "<module>"): 1, ("a.py", "C901", "big"): 25, ("new.py", "F841", "f"): 4}
    after = R.lowered(current, BASE)
    assert after == {("a.py", "F401", "<module>"): 1, ("a.py", "C901", "big"): 20}
    assert all(after[k] <= BASE[k] for k in after) and set(after) <= set(BASE)


def test_the_baseline_text_round_trips_and_is_sorted_so_a_diff_shows_only_what_changed():
    text = R.render_baseline({("z.py", "F401", "<module>"): 1, ("a.py", "B904", "f"): 2, ("a.py", "B904", "e"): 1})
    assert R.read_baseline(text) == {("z.py", "F401", "<module>"): 1, ("a.py", "B904", "f"): 2,
                                     ("a.py", "B904", "e"): 1}
    rows = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert rows == sorted(rows)


@pytest.mark.parametrize("line", ["a.py :: F401 :: <module>", "a.py :: F401 :: <module> :: 0",
                                  "a.py :: nonsense :: <module> :: 1", "just words"])
def test_a_malformed_baseline_line_is_refused(line):
    with pytest.raises(R.RatchetError):
        R.read_baseline(line + "\n")


def test_a_baseline_line_listed_twice_is_refused():
    with pytest.raises(R.RatchetError):
        R.read_baseline("a.py :: F401 :: <module> :: 1\na.py :: F401 :: <module> :: 2\n")


# ── the command line, with ruff replaced by what it would have said ─────────────

def _drive(monkeypatch, tmp_path, findings, baseline, *flags):
    """main() against a baseline in tmp_path and a ruff that reports `findings` for source `SOURCE`."""
    path = tmp_path / "baseline.txt"
    if baseline is not None:
        path.write_text(R.render_baseline(baseline), encoding="utf-8")
    monkeypatch.setattr(R, "run_ruff", lambda ruff="ruff": findings)
    monkeypatch.setattr(R, "_source", lambda p: SOURCE)
    code = R.main(["--baseline", str(path), *flags])
    return code, path


def test_a_new_finding_fails_the_gate_and_is_not_written_into_the_baseline(monkeypatch, tmp_path, capsys):
    base = {("a.py", "F841", "outer"): 1}
    code, path = _drive(monkeypatch, tmp_path, [d("a.py", 4, "F841"), d("a.py", 17, "F401", "unused")], base)
    out = capsys.readouterr().out
    assert code == 1 and "NEW" in out and "a.py:17:1: F401 unused" in out
    assert R.read_baseline(path.read_text()) == base


def test_update_refuses_to_write_while_there_is_a_new_finding(monkeypatch, tmp_path):
    base = {("a.py", "F841", "outer"): 1, ("a.py", "F841", "later"): 1}
    before = R.render_baseline(base)
    code, path = _drive(monkeypatch, tmp_path, [d("a.py", 4, "F841"), d("a.py", 6, "F841")], base, "--update")
    assert code == 1 and path.read_text() == before


def test_a_fixed_finding_fails_the_gate_until_update_removes_it_and_then_passes(monkeypatch, tmp_path):
    base = {("a.py", "F841", "outer"): 1, ("a.py", "F841", "later"): 1}
    findings = [d("a.py", 4, "F841")]
    code, path = _drive(monkeypatch, tmp_path, findings, base)
    assert code == 1, "a baseline line that no longer fires has to fail, or the baseline is only a ceiling"
    code, path = _drive(monkeypatch, tmp_path, findings, base, "--update")
    assert code == 0 and R.read_baseline(path.read_text()) == {("a.py", "F841", "outer"): 1}
    code, _ = _drive(monkeypatch, tmp_path, findings, None)
    assert code == 0


def test_init_refuses_when_a_baseline_exists_so_regenerating_cannot_absorb_a_finding(monkeypatch, tmp_path):
    code, path = _drive(monkeypatch, tmp_path, [d("a.py", 4, "F841")], {("a.py", "F401", "<module>"): 1}, "--init")
    assert code == 2 and R.read_baseline(path.read_text()) == {("a.py", "F401", "<module>"): 1}
    path.unlink()
    code, path = _drive(monkeypatch, tmp_path, [d("a.py", 4, "F841")], None, "--init")
    assert code == 0 and R.read_baseline(path.read_text()) == {("a.py", "F841", "outer"): 1}


def test_a_ruff_that_is_not_there_is_exit_two_and_never_a_clean_result(tmp_path, capsys):
    code = R.main(["--baseline", str(BASELINE), "--ruff", str(tmp_path / "no-such-ruff")])
    assert code == 2 and "did not run" in capsys.readouterr().out


def _fake_ruff(tmp_path: Path, files: list[str], report: str = "[]") -> str:
    script = tmp_path / "fake_ruff.py"
    script.write_text(textwrap.dedent(f"""\
        import sys
        if "--show-files" in sys.argv:
            print("\\n".join({files!r}))
        else:
            print({report!r})
    """), encoding="utf-8")
    return f"{sys.executable} {script}"


def test_a_ruff_that_looked_at_the_wrong_tree_is_refused_even_though_its_report_is_empty(tmp_path):
    """An empty report from a run that checked nothing is the false clean this exists to refuse."""
    wrong = _fake_ruff(tmp_path, [str(API / "main.py")])
    with pytest.raises(R.RatchetError, match="wrong tree"):
        R.run_ruff(wrong)
    right = _fake_ruff(tmp_path, [str(API / p) for p in ("core/x.py", "domain/x.py", "routers/x.py",
                                                       "services/x.py", "tests/x.py")])
    assert R.run_ruff(right) == []


def test_a_ruff_that_prints_something_that_is_not_json_is_refused(tmp_path):
    files = [str(API / p) for p in ("core/x.py", "domain/x.py", "routers/x.py", "services/x.py", "tests/x.py")]
    with pytest.raises(R.RatchetError, match="not JSON"):
        R.run_ruff(_fake_ruff(tmp_path, files, report="Traceback (most recent call last)"))


# ── the committed baseline ──────────────────────────────────────────────────────

def test_the_committed_baseline_parses_is_sorted_and_names_files_that_exist():
    text = BASELINE.read_text(encoding="utf-8")
    baseline = R.read_baseline(text)
    assert len(baseline) > 100, "the baseline is empty — the gate would be passing on nothing"
    rows = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert rows == sorted(rows), "the baseline is kept sorted so a diff shows only what changed"
    missing = sorted({p for p, _, _ in baseline if not (API / p).is_file()})
    assert not missing, f"baseline lines name files that are gone — run --update: {missing[:5]}"


def test_the_committed_baseline_holds_only_rules_the_config_selects():
    selected = tomllib.loads((API / "pyproject.toml").read_text())["tool"]["ruff"]["lint"]["select"]
    for _, code, _ in R.read_baseline(BASELINE.read_text(encoding="utf-8")):
        assert any(code.startswith(prefix) for prefix in selected), f"{code} is in the baseline but not selected"


# ── the real tool ───────────────────────────────────────────────────────────────

def test_the_tree_is_clean_against_the_baseline_with_the_real_ruff():
    """The same check the CI step makes. A new finding, or a fixed one still on the books, fails it."""
    ruff = _need_ruff()
    diags = R.run_ruff(ruff)
    current = R.to_counts(diags, R._source)
    verdict = R.judge(current, R.read_baseline(BASELINE.read_text(encoding="utf-8")))
    assert not verdict.new, f"new lint findings (fix them, the baseline does not grow): {sorted(verdict.new)[:5]}"
    assert not verdict.stale, ("fixed findings are still in the baseline — "
                               f"run `python scripts/ci/ruff_ratchet.py --update`: {sorted(verdict.stale)[:5]}")


def _findings_in(tmp_path: Path, name: str, source: str):
    """What the repository's own ruff configuration reports for one synthetic module outside the tree."""
    ruff = _need_ruff()
    (tmp_path / name).write_text(source, encoding="utf-8")
    proc = subprocess.run([*shlex.split(ruff), "check", "--config", str(API / "pyproject.toml"), "--no-cache",
                           "--exit-zero", "--output-format", "json", str(tmp_path / name)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return R.diagnostics_from_json(json.loads(proc.stdout), tmp_path)


def test_an_unused_import_a_bare_except_and_a_four_hundred_line_function_each_reach_the_ratchet_as_new(tmp_path):
    """The item's own verify line, run: each of these turns the backend check red against the real baseline."""
    long_body = "\n".join(f"    x{i} = {i}" for i in range(400))
    cases = {
        "unused_import.py": ("import os\n", "F401"),
        "bare_except.py": ("def f():\n    try:\n        return 1\n    except:\n        return 2\n", "E722"),
        "long_function.py": (f"def f():\n{long_body}\n    return x0\n", "PLR0915"),
    }
    baseline = R.read_baseline(BASELINE.read_text(encoding="utf-8"))
    for name, (source, code) in cases.items():
        diags = _findings_in(tmp_path, name, source)
        assert code in {x.code for x in diags}, f"{name}: the configuration does not report {code}: {diags}"
        verdict = R.judge(R.to_counts(diags, lambda p: (tmp_path / p).read_text()), baseline)
        assert verdict.new, f"{name}: the ratchet would let this through"


def test_a_complex_function_is_reported_by_the_complexity_limit(tmp_path):
    branches = "\n".join(f"    if n == {i}:\n        return {i}" for i in range(30))
    diags = _findings_in(tmp_path, "complex.py", f"def f(n):\n{branches}\n    return -1\n")
    assert "C901" in {x.code for x in diags}


def test_fastapi_dependencies_in_a_default_are_not_a_finding_but_a_real_call_there_is(tmp_path):
    """B008 would flag every `Depends(...)` in the application: 1,144 findings that are the framework's idiom."""
    ok = "from fastapi import Depends, Query\n\ndef dep():\n    return 1\n\ndef route(a=Depends(dep), b=Query(None)):\n    return a, b\n"
    assert "B008" not in {x.code for x in _findings_in(tmp_path, "ok.py", ok)}
    bad = "import time\n\ndef f(stamp=time.time()):\n    return stamp\n"
    assert "B008" in {x.code for x in _findings_in(tmp_path, "bad.py", bad)}


# ── the configuration and the workflow ──────────────────────────────────────────

def _config():
    return tomllib.loads((API / "pyproject.toml").read_text())["tool"]["ruff"]


def test_the_configuration_selects_pyflakes_bugbear_bare_except_and_both_size_limits():
    lint = _config()["lint"]
    selected = set(lint["select"])
    assert {"F", "B", "E722", "C901", "PLR0915"} <= selected
    assert "F401" not in lint.get("ignore", []) and "E722" not in lint.get("ignore", [])


def test_the_size_limits_are_set_and_cannot_be_loosened_without_this_test_saying_so():
    """Raising a limit absorbs every function between the old and new figure into 'fine', which is exactly what
    the baseline is meant to prevent. Changing these two numbers is a decision, so it is a test edit."""
    cfg = _config()["lint"]
    assert cfg["mccabe"]["max-complexity"] <= 15
    assert cfg["pylint"]["max-statements"] <= 75


def test_the_migrations_directory_is_not_linted_and_nothing_else_is_excluded():
    cfg = _config()
    assert cfg.get("extend-exclude") == ["migrations"]
    assert "exclude" not in cfg, "`exclude` replaces ruff's defaults; `extend-exclude` adds to them"


def _job(name_fragment: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index(f"name: {name_fragment}")
    nxt = re.search(r"^  [a-z][a-z-]*:\n", text[start:], re.MULTILINE)
    return text[start: start + nxt.start()] if nxt else text[start:]


def test_the_lint_runs_inside_the_required_pytest_job_before_the_tests_and_gated_on_scope():
    job = _job("pytest — mock mode (Python 3.11)")
    assert "scripts/ci/ruff_ratchet.py" in job
    assert job.index("ruff_ratchet.py") < job.index("pytest tests/"), "the lint is cheap and should fail first"
    step = job[job.index("name: Lint"):job.index("name: Run tests")]
    assert "needs.scope.outputs.api == 'true'" in step, "a frontend-only diff must not pay for the lint"
    assert "|| true" not in step and "continue-on-error" not in step, "the gate's exit code is being discarded"


def test_the_workflow_still_has_no_paths_filter_and_installs_the_dev_requirements():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"^\s+paths(-ignore)?:", text, re.MULTILINE), \
        "a path-filtered workflow does not report its required checks"
    job = _job("pytest — mock mode (Python 3.11)")
    # The dev requirements are a LOCK with hashes (engineering-04), installed beside the runtime lock in one
    # command, so what is asserted is that the job installs them, not how the install is spelled.
    assert re.search(r"pip install .*-r requirements-dev\.txt", job), "the job no longer installs the dev lock"


def test_the_dev_requirements_pin_the_tools_exactly_and_the_image_does_not_install_them():
    dev = (API / "requirements-dev.txt").read_text()
    pins = {m.group(1).lower(): m.group(2) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s#\\]+)", dev, re.MULTILINE)}
    assert {"ruff", "hypothesis", "pytest-cov"} <= set(pins), pins
    # The dev lock is compiled AGAINST the runtime lock (`-c requirements.txt` in the .in file), so whatever the
    # two share is the version production runs, and its tools are hashed like everything else in it.
    assert re.search(r"^-c requirements\.txt$", (API / "requirements-dev.in").read_text(), re.MULTILINE)
    assert "--hash=sha256:" in dev
    prod = (API / "requirements.txt").read_text().lower()
    for tool in ("ruff", "hypothesis", "pytest-cov", "pytest-xdist"):
        assert tool not in prod, f"{tool} would ship in the production image"
    # The Dockerfile's own comment explains that the dev lock is not copied (ops-pipeline's), so the rule is that no
    # INSTRUCTION names it, not that the words never appear.
    instructions = [ln for ln in (API / "Dockerfile").read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert not any("requirements-dev" in ln for ln in instructions), "the image installs or copies the dev lock"
