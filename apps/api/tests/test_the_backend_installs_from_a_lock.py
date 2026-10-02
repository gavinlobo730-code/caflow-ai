"""The backend is built from a hash-pinned lock, and the production image holds neither the tests nor the test runner (engineering-04, ops-27).

WHAT WAS WRONG
    requirements.txt held fifteen floating `>=` lines among its pins and there was no lock, so a build next month
    could resolve to different versions from the ones the suite passed on (the environment the review ran in had
    resolved pandas to a major, 3.x, that the `>=2.0.0` was never written against). pytest sat in the production
    requirements. The Dockerfile did `COPY . .` and the build context held the whole tests/ directory and every
    production-schema snapshot in tests/fixtures.

THE SHAPE
    requirements.in            what a person edits: the direct runtime dependencies, with the ranges the old file had
    requirements.txt           pip-compile's output for it: EVERY package, pinned, with the hash of each file
    requirements-dev.in/.txt   what only the suite needs (pytest), constrained to the runtime lock's versions
    Dockerfile                 `pip install --require-hashes -r requirements.txt`; nothing else
    .dockerignore              leaves tests/ and the dev files out of the context
    .github/workflows          every pip install of the project's requirements is the same hashed command

WHAT THIS CANNOT PROVE, and what does
    That the lock is the lock pip-compile WOULD write today needs the network and PyPI, so it is not asserted here.
    What is asserted is everything that makes a lock a lock: each pin exact and hashed, the .in file satisfied by it,
    the dev lock agreeing with it, and nothing else able to install a different set. The first run of the `docker
    image` workflow builds the Dockerfile and inspects the result (no tests/, no pytest, the installed set equal to
    the lock), which is the half a unit test cannot reach.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
WORKFLOWS = REPO / ".github" / "workflows"


def _logical_lines(path: Path) -> list[str]:
    """requirements lines with their backslash continuations joined, comments and blanks dropped."""
    out: list[str] = []
    buf = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not buf and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.lstrip().startswith("#") and buf:
            continue            # a `# via` comment between a pin's hash lines
        if line.endswith("\\"):
            buf += line[:-1].strip() + " "
            continue
        out.append((buf + line.strip()).strip())
        buf = ""
    assert not buf, f"{path.name} ends inside a continuation"
    return out


def _pins(path: Path) -> dict[str, tuple[str, list[str]]]:
    """canonical name -> (version, [hashes]) for every requirement in a compiled lock."""
    pins: dict[str, tuple[str, list[str]]] = {}
    for line in _logical_lines(path):
        if line.startswith("-"):
            continue
        hashes = re.findall(r"--hash=sha256:([0-9a-f]+)", line)
        body = re.sub(r"\s*--hash=\S+", "", line).strip()
        req = Requirement(body)
        specs = list(req.specifier)
        assert len(specs) == 1 and specs[0].operator == "==", (
            f"{path.name}: {line[:80]!r} is not pinned with ==. A lock holds nothing else.")
        pins[canonicalize_name(req.name)] = (specs[0].version, hashes)
    return pins


RUNTIME = API / "requirements.txt"
DEV = API / "requirements-dev.txt"


def test_the_lock_files_exist_beside_the_files_they_are_compiled_from():
    for name in ("requirements.in", "requirements.txt", "requirements-dev.in", "requirements-dev.txt"):
        assert (API / name).is_file(), name


@pytest.mark.parametrize("lock", [RUNTIME, DEV], ids=lambda p: p.name)
def test_every_requirement_is_pinned_exactly_and_carries_a_hash_of_every_file(lock):
    pins = _pins(lock)
    assert len(pins) >= (80 if lock is RUNTIME else 4), "the parse found almost nothing"
    unhashed = [n for n, (_, hashes) in pins.items() if not hashes]
    assert not unhashed, f"pinned but not hashed (pip --require-hashes would refuse the file): {unhashed}"
    bad = [(n, h) for n, (_, hs) in pins.items() for h in hs if not re.fullmatch(r"[0-9a-f]{64}", h)]
    assert not bad, bad


def test_the_lock_says_it_was_compiled_for_the_version_of_python_the_image_runs():
    dockerfile = (API / "Dockerfile").read_text(encoding="utf-8")
    image = re.search(r"^FROM python:(\d+\.\d+)", dockerfile, re.M)
    assert image, "the Dockerfile no longer starts from a python:X.Y image"
    for lock in (RUNTIME, DEV):
        head = lock.read_text(encoding="utf-8")[:400]
        assert f"pip-compile with Python {image.group(1)}" in head, (
            f"{lock.name} was compiled for a different Python from the image's {image.group(1)}; the resolution "
            "of a package with a version-specific dependency can differ")


# ── the .in file and the lock agree ────────────────────────────────────────────

def test_every_direct_dependency_is_in_the_lock_at_a_version_the_range_allows():
    pins = _pins(RUNTIME)
    direct = [Requirement(line) for line in _logical_lines(API / "requirements.in")]
    assert len(direct) >= 20
    for req in direct:
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is in requirements.in and not in the lock: recompile (see requirements.in)"
        version = pins[name][0]
        assert req.specifier.contains(version, prereleases=True), (
            f"{req.name}{req.specifier} does not allow the locked {version}: the two files disagree")


def test_the_ranges_the_old_file_had_are_the_ranges_the_in_file_has():
    """The lock records what the ranges resolve to; it must not quietly tighten or loosen them. The old file's
    `>=`/`<` lines are quoted here from before the change."""
    text = "\n".join(_logical_lines(API / "requirements.in"))
    for line in ("httpx>=0.27.0,<0.28.0", "pydantic>=2.0.0", "pandas>=2.0.0", "reportlab>=4.0.0",
                 "google-genai>=1.0.0,<2.0.0", "fastapi==0.109.2", "gunicorn==21.2.0", "python-multipart==0.0.9"):
        assert line in text, f"{line} changed: this change adds a lock and bumps nothing"


def test_the_runtime_set_holds_no_test_only_package():
    runtime, dev = _pins(RUNTIME), _pins(DEV)
    assert "pytest" in dev and "pytest" not in runtime
    for name in ("pytest", "pluggy", "iniconfig"):
        assert name not in runtime, f"{name} is test-only and is in the production lock"
    direct = {canonicalize_name(Requirement(l).name) for l in _logical_lines(API / "requirements.in")}
    assert "pytest" not in direct


def test_the_dev_lock_never_disagrees_with_the_runtime_lock():
    """The suite must run against the versions production runs. A package in both is pinned once, to one version."""
    runtime, dev = _pins(RUNTIME), _pins(DEV)
    differ = {n: (runtime[n][0], dev[n][0]) for n in runtime.keys() & dev.keys() if runtime[n][0] != dev[n][0]}
    assert not differ, f"CI would test a different version from the one the image installs: {differ}"
    assert "-c requirements.txt" in (API / "requirements-dev.in").read_text(encoding="utf-8")


# ── the image ──────────────────────────────────────────────────────────────────

def test_the_dockerfile_installs_the_runtime_lock_with_hashes_and_nothing_else():
    text = (API / "Dockerfile").read_text(encoding="utf-8")
    installs = [l for l in text.splitlines() if re.match(r"\s*RUN\s+.*pip install", l)]
    assert installs, "the Dockerfile no longer installs anything with pip"
    for line in installs:
        assert "--require-hashes" in line, f"an unhashed install in the image: {line.strip()}"
        assert "-r requirements.txt" in line and "requirements-dev" not in line
    assert "requirements-dev" not in "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_the_build_context_leaves_out_the_tests_and_the_dev_files():
    entries = {l.strip() for l in (API / ".dockerignore").read_text(encoding="utf-8").splitlines()
               if l.strip() and not l.startswith("#")}
    assert "tests/" in entries or "tests" in entries, "the image would carry the whole test suite and its fixtures"
    for dev in ("requirements-dev.txt", "requirements-dev.in", "requirements.in"):
        assert dev in entries, dev
    # And the three things the image DOES need are not caught by an over-eager pattern.
    for needed in ("requirements.txt", "migrations", "migrations/", "main.py"):
        assert needed not in entries, f"{needed} is excluded from the image"


def test_nothing_the_image_runs_imports_the_test_suite_or_its_runner():
    """tests/ and pytest are not in the image, so a runtime module that imported either would fail on Render and
    pass here. Source scan over what `COPY . .` leaves: every top-level module and package except tests/, scripts/
    (not imported by the app) and migrations/."""
    skip = {"tests", "scripts", "migrations", "__pycache__"}
    offenders = []
    scanned = 0
    for path in API.rglob("*.py"):
        rel = path.relative_to(API)
        if rel.parts[0] in skip or any(p.startswith(".") for p in rel.parts):
            continue
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            if any(n.split(".")[0] in {"pytest", "tests", "_pytest"} for n in names):
                offenders.append(f"{rel}:{node.lineno}")
    assert scanned > 300, "the walk found almost nothing"
    assert not offenders, f"the image would not start: {offenders}"


# ── CI ─────────────────────────────────────────────────────────────────────────

def _project_installs(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if re.search(r"pip install\b.*-r\s+\S*requirements\S*\.txt", line):
            out.append(line)
    return out


def test_every_workflow_install_of_the_project_requirements_is_hashed_and_names_the_dev_lock():
    seen = 0
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for line in _project_installs(wf):
            seen += 1
            assert "--require-hashes" in line, f"{wf.name}: an install that checks no hashes: {line}"
            assert "requirements.txt" in line
            if wf.name == "backend-ci.yml":
                assert "requirements-dev.txt" in line, f"{wf.name}: CI would have no test runner: {line}"
    assert seen >= 3, "the backend CI no longer installs from the requirements files at all"


def test_the_backend_ci_cache_is_keyed_on_both_locks():
    text = (WORKFLOWS / "backend-ci.yml").read_text(encoding="utf-8")
    keyed = re.findall(r"cache-dependency-path: \|\n\s+apps/api/requirements\.txt\n\s+apps/api/requirements-dev\.txt", text)
    assert len(keyed) == text.count("cache: \"pip\""), (
        "a setup-python cache keyed on only one lock restores a stale environment when the other changes")


def test_the_image_workflow_builds_the_dockerfile_and_inspects_what_came_out():
    text = (WORKFLOWS / "docker-image.yml").read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "docker build" in code and "apps/api" in code
    assert re.search(r"test ! -e /app/tests|! test -e /app/tests|\[ ! -e /app/tests \]", code), "no check for tests/"
    assert "import pytest" in code, "no check that the test runner is absent"
    assert re.search(r"--entrypoint pip\b.*\bfreeze\b", code) and "compare_freeze_to_lock.py" in code, (
        "no check that the installed set is the lock")
    assert "import main" in code, "no check that the app starts with only the locked set"
    # Not a required check, and not on every pull request.
    assert not re.search(r"^\s*paths(-ignore)?:", code, re.M)


# ── the comparison the image workflow runs ─────────────────────────────────────

def _compare_module():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "compare_freeze_to_lock_under_test", API / "scripts" / "ci" / "compare_freeze_to_lock.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["compare_freeze_to_lock_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _freeze_of(pins: dict[str, str]) -> str:
    return "\n".join(f"{name}=={version}" for name, version in sorted(pins.items())) + "\n"


def test_a_freeze_that_is_exactly_the_lock_passes():
    cmp = _compare_module()
    lock = cmp.pins_in_lock(RUNTIME.read_text(encoding="utf-8"))
    assert len(lock) >= 80
    assert cmp.compare(lock, cmp.pins_in_freeze(_freeze_of(lock))) == []


def test_the_two_spellings_of_a_name_are_the_same_package():
    cmp = _compare_module()
    assert cmp.normalise("pdfminer.six") == cmp.normalise("pdfminer-six") == "pdfminer-six"
    assert cmp.normalise("PyJWT") == "pyjwt" and cmp.normalise("typing_extensions") == "typing-extensions"
    assert cmp.pins_in_freeze("pdfminer.six==20260107\nPyJWT==2.8.0\n") == {
        "pdfminer-six": "20260107", "pyjwt": "2.8.0"}


def test_pip_and_setuptools_are_not_the_locks_business():
    cmp = _compare_module()
    assert cmp.pins_in_freeze("pip==24.0\nsetuptools==65.5.1\nwheel==0.42.0\nsix==1.17.0\n") == {"six": "1.17.0"}


@pytest.mark.parametrize("change, expect", [
    (lambda d: d.pop("six"), "in the lock and NOT installed: six"),
    (lambda d: d.update(pytest="9.1.1"), "installed and NOT in the lock: pytest"),
    (lambda d: d.update(six="9.9.9"), "six: lock says"),
])
def test_every_kind_of_difference_is_named(change, expect):
    cmp = _compare_module()
    lock = {"six": "1.17.0", "idna": "3.20"}
    installed = dict(lock)
    change(installed)
    problems = cmp.compare(lock, installed)
    assert any(expect in p for p in problems), problems


def test_an_empty_comparison_is_refused_not_passed(tmp_path, monkeypatch):
    import io
    cmp = _compare_module()
    lock = tmp_path / "requirements.txt"
    lock.write_text("six==1.17.0 \\\n    --hash=sha256:" + "0" * 64 + "\n")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cmp.main(["compare", str(lock)]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO("six==1.17.0\n"))
    assert cmp.main(["compare", str(lock)]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("six==1.17.1\n"))
    assert cmp.main(["compare", str(lock)]) == 1
