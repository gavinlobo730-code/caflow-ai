"""Every dependency manifest in the tree is watched by Dependabot and audited on a schedule (engineering-05).

THE RULE, NOT A LIST OF TODAY'S NAMES
    Dependabot reads `directory:` and treats one that names nothing as a silent no-op, and a CI matrix that
    forgets a new app audits everything except it. So each test derives the population from the TREE —
    every `requirements.txt`, every `package.json` beside a lockfile, every workflow directory — and asks
    whether the configuration reaches it. A fourth app added next year fails here until it is covered.

WHAT CANNOT BE TESTED HERE
    That a Dependabot pull request actually appears, or that the audit workflow goes red on GitHub. The first
    needs the file on the default branch and a week; the second needs Actions. What is pinned is everything
    around those: the configuration reaches every manifest, the gate is never wrapped in something that
    swallows its exit code, the baselines parse and only hold what the gate counts, and the scope filter
    matches the files that matter.

    What IS pinned about the baselines' CONTENT is one thing, and it is what made the audit red on the day
    this merged: a baseline is written from a report, and the first one was written from a report that did
    not name every high advisory the lockfile was already carrying (axios GHSA-M8M8-QJ5V-23W3), so the
    workflow the change introduced failed on its own pull request. A recorded snapshot of each report sits in
    tests/fixtures/audit/, and each baseline must name every advisory in it that still applies.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GH = REPO / ".github"
DEPENDABOT = GH / "dependabot.yml"
WORKFLOW = GH / "workflows" / "dependency-audit.yml"
BASELINES = GH / "audit-baseline"
APPS = REPO / "apps"


def _code(path: Path) -> str:
    """The file with full-line comments removed: these files describe their own rules at length, and a scan
    that reads the prose finds the words in the explanation rather than in the configuration."""
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))


def _gate():
    spec = importlib.util.spec_from_file_location("audit_gate", APPS / "api" / "scripts" / "ci" / "audit_gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── the manifests that exist ────────────────────────────────────────────────────

def _npm_apps() -> list[str]:
    return sorted(p.parent.name for p in APPS.glob("*/pnpm-lock.yaml"))


def _pip_apps() -> list[str]:
    # One entry per APP, not per file: apps/api holds the runtime lock requirements.txt (what the image
    # installs) and its dev lock requirements-dev.txt (what the test and lint jobs add, engineering-04), and
    # Dependabot's pip entry is per directory, so counting files would say the same app twice.
    return sorted({p.parent.name for p in APPS.glob("*/requirements*.txt")})


def test_the_tree_has_the_manifests_the_rest_of_this_file_assumes():
    """Vacuity guard. If the layout moved, every rule below would iterate over nothing and pass."""
    assert _pip_apps() == ["api"]
    assert {"web", "marketing"} <= set(_npm_apps())


# The two frontends are named in the spelling `scripts/ci/tests_reading_the_browser.py` derives a module
# from, and that is deliberate rather than decorative. This module DOES read both trees (it globs their
# lockfiles and asks whether Dependabot and the audit matrix reach them), so a frontend-only pull request
# — which skips the whole backend suite — has to run it: adding a fourth app there is exactly the change
# it exists to catch. `test_the_browser_contract_job_sees_every_reader` asks the filesystem and failed this
# module the first time it carried the two paths only inside a list of strings.
WEB = REPO / "apps" / "web"
MARKETING = REPO / "apps" / "marketing"


@pytest.mark.parametrize("frontend", [WEB, MARKETING], ids=lambda p: p.name)
def test_each_frontend_has_the_pair_of_files_pnpm_audit_needs(frontend):
    """`pnpm audit` reads the LOCKFILE and needs no install, so a frontend with a manifest and no lockfile
    would audit nothing — which the gate refuses as 'zero dependencies', failing the job on the weekly run
    rather than at the pull request that removed it."""
    assert (frontend / "package.json").is_file()
    assert (frontend / "pnpm-lock.yaml").is_file(), f"{frontend.name} has no pnpm-lock.yaml to audit"


# ── Dependabot ──────────────────────────────────────────────────────────────────

def _entries() -> list[tuple[str, str]]:
    return re.findall(
        r'package-ecosystem:\s*"?([\w-]+)"?\s*\n\s*directory:\s*"?([^"\n]+?)"?\s*\n', _code(DEPENDABOT))


def test_dependabot_names_a_directory_that_exists_for_every_entry():
    entries = _entries()
    assert len(entries) >= 4, "the scan found no entries — the regex or the file changed"
    for eco, directory in entries:
        target = REPO / directory.lstrip("/")
        assert target.is_dir(), (
            f"Dependabot is told to watch {directory!r} ({eco}), which does not exist. It would do "
            "nothing, without an error.")


def test_every_manifest_in_the_tree_is_watched():
    entries = set(_entries())
    for app in _pip_apps():
        assert ("pip", f"/apps/{app}") in entries, f"apps/{app}/requirements.txt has no pip entry"
    for app in _npm_apps():
        assert ("npm", f"/apps/{app}") in entries, f"apps/{app}/pnpm-lock.yaml has no npm entry"
    assert ("github-actions", "/") in entries and any((GH / "workflows").glob("*.yml"))


def test_every_entry_is_weekly_and_none_is_left_on_the_default():
    text = _code(DEPENDABOT)
    n_entries = len(_entries())
    assert len(re.findall(r'interval:\s*"weekly"', text)) == n_entries, (
        "an entry without an explicit weekly schedule is one Dependabot will not run")
    assert len(re.findall(r'timezone:\s*"Asia/Kolkata"', text)) == n_entries


def _blocks(text: str, key: str) -> list[str]:
    """The body of every `key:` mapping in the file: the lines indented deeper than the key itself."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        m = re.match(rf"^(\s*){key}:\s*$", lines[i])
        if not m:
            i += 1
            continue
        indent, body = len(m.group(1)), []
        i += 1
        while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
            body.append(lines[i])
            i += 1
        out.append("\n".join(body))
    return out


def test_minor_and_patch_are_grouped_and_a_major_is_left_to_arrive_alone():
    """The rule is about GROUPS: a major update is never folded into the weekly group, because it is the
    one that can break the build and wants its own review. An `ignore` entry that holds a named
    dependency's major back is a different thing (a decision somebody wrote down, with the date and the
    ledger item in the file's header) and is allowed; a wildcard that would hide every major is not."""
    text = _code(DEPENDABOT)
    assert text.count('update-types: ["minor", "patch"]') == len(_entries())
    groups = _blocks(text, "groups")
    assert len(groups) == len(_entries()), "an entry without a groups block would not group anything"
    for body in groups:
        assert "major" not in body, (
            "a MAJOR update must not be grouped: it is the one that can break the build and wants its own review")
    assert 'dependency-name: "*"' not in text, (
        "a wildcard ignore hides every major, including the ones nobody has decided about")
    for body in _blocks(text, "ignore"):
        for entry in re.split(r"\n\s*- ", "\n" + body.strip()):
            if entry.strip():
                assert re.search(r'dependency-name:\s*"[^"*]+"', entry) and "update-types:" in entry, (
                    f"an ignore entry must name one dependency and the update types it holds back: {entry!r}")


# ── the audit workflow ──────────────────────────────────────────────────────────

def test_the_audit_runs_on_pull_request_push_schedule_and_demand_with_no_path_filter():
    text = _code(WORKFLOW)
    for trigger in ("pull_request:", "push:", "schedule:", "workflow_dispatch:"):
        assert re.search(rf"^\s*{trigger}", text, re.M), f"no {trigger} trigger"
    # CLAUDE.md: a path-filtered workflow does not run when the filter misses. The filter lives INSIDE, in
    # the `scope` job, so the check always reports.
    assert not re.search(r"^\s*paths(-ignore)?:", text, re.M)


def test_pip_audit_is_pinned_and_resolves_the_requirements_rather_than_reading_the_file():
    text = _code(WORKFLOW)
    assert re.search(r'pip install[^\n]*pip-audit==\d+\.\d+\.\d+', text), "pip-audit is not pinned to a version"
    # requirements.txt holds ranges and no lockfile, so --no-deps refuses it. Resolving is the point.
    assert "--no-deps" not in text
    assert re.search(r"pip-audit -r apps/api/requirements\.txt", text)


def test_every_pnpm_lockfile_in_the_tree_is_audited_with_its_own_baseline():
    text = _code(WORKFLOW)
    m = re.search(r"app:\s*\[([^\]]+)\]", text)
    assert m, "no audit matrix"
    matrix = {a.strip() for a in m.group(1).split(",")}
    assert set(_npm_apps()) == matrix, (
        f"the audit matrix {sorted(matrix)} is not the set of lockfiles {_npm_apps()} — an app added without "
        "a matrix entry is audited by nothing")
    for app in matrix:
        assert (BASELINES / f"pnpm-{app}.txt").is_file(), f"no baseline for {app}"
    assert "pnpm audit --prod --json" in text, "--prod: a build-tool advisory never reaches a browser or the server"


def test_the_step_that_judges_the_audit_cannot_be_swallowed():
    """`|| true` belongs on the steps that RUN the audit tools — they exit non-zero on any finding, and the gate
    decides — and on nothing else. A gate step ending `|| true`, or marked continue-on-error, is a check that
    can only ever be green."""
    text = _code(WORKFLOW)
    assert "continue-on-error" not in text
    steps = re.split(r"\n\s*- (?:name|uses|if|id):", text)
    swallowed = [s for s in steps if "|| true" in s]
    assert len(swallowed) == 2, f"expected the two audit steps to end `|| true`, found {len(swallowed)}"
    for s in swallowed:
        assert "audit_gate.py" not in s, "the gate's own exit code is being discarded"
    gates = [s for s in steps if "audit_gate.py" in s]
    assert len(gates) == 2 and not any("|| true" in s for s in gates)


def test_the_scope_filter_matches_what_the_audit_reads_and_nothing_else():
    text = _code(WORKFLOW)
    m = re.search(r"grep -qE \\\s*\n\s*'([^']+)'", text)
    assert m, "the scope job's pattern was not found"
    pattern = re.compile(m.group(1))
    for changed in ("apps/api/requirements.txt", "apps/web/package.json", "apps/web/pnpm-lock.yaml",
                    "apps/marketing/package.json", "apps/marketing/pnpm-lock.yaml",
                    ".github/audit-baseline/pip-api.txt", "apps/api/scripts/ci/audit_gate.py",
                    ".github/workflows/dependency-audit.yml"):
        assert pattern.search(changed), f"a change to {changed} would not trigger the audit on a pull request"
    for unrelated in ("apps/web/app/page.tsx", "apps/api/routers/clients.py", "docs/plan/THE-PLAN.md",
                      "apps/api/requirements-dev.txt.bak"):
        assert not pattern.search(unrelated), f"{unrelated} should not trigger a dependency audit"


def test_a_non_pull_request_event_always_audits():
    """The schedule exists to find an advisory nobody's diff touched. If the scope job could answer 'no' for it,
    the weekly run would be the most expensive way to do nothing."""
    text = _code(WORKFLOW)
    assert re.search(r'if \[ "\$\{\{ github\.event_name \}\}" != "pull_request" \]; then\s*\n\s*echo "audit=true"', text)


# ── the committed baselines ─────────────────────────────────────────────────────

def _baseline_files() -> list[Path]:
    return sorted(BASELINES.glob("*.txt"))


def test_the_baselines_exist_one_per_audit():
    names = {p.name for p in _baseline_files()}
    assert names == {"pip-api.txt", *(f"pnpm-{a}.txt" for a in _npm_apps())}


@pytest.mark.parametrize("path", _baseline_files(), ids=lambda p: p.name)
def test_a_baseline_parses_holds_one_id_per_line_and_says_it_may_only_shrink(path):
    gate = _gate()
    text = path.read_text(encoding="utf-8")
    base = gate.read_baseline(text)     # raises on a duplicate or a line that is not an id
    assert len(base) > 0
    assert "MAY ONLY SHRINK" in text, "the header that stops this file growing into an allowlist is missing"
    for advisory, note in base.items():
        assert note and "—" in note, f"{advisory} has no `package version [severity] — title` note"


@pytest.mark.parametrize("path", [p for p in _baseline_files() if p.name.startswith("pnpm-")], ids=lambda p: p.name)
def test_a_pnpm_baseline_holds_only_what_the_gate_counts(path):
    """The gate counts high and critical. A moderate line would be a line that is never read — and would
    read as stale forever."""
    gate = _gate()
    severities = set(re.findall(r"\[(\w+)\]", "\n".join(gate.read_baseline(path.read_text(encoding="utf-8")).values())))
    assert severities <= {"high", "critical"}, severities


def test_the_pip_baseline_names_no_severity_because_pip_audit_reports_none():
    gate = _gate()
    notes = "\n".join(gate.read_baseline((BASELINES / "pip-api.txt").read_text(encoding="utf-8")).values())
    assert not re.search(r"\[(low|moderate|high|critical)\]", notes)


# ── the baselines cover the reports they were written from ──────────────────────

SNAPSHOT = json.loads((Path(__file__).resolve().parent / "fixtures" / "audit" / "pnpm-reports-2026-09-30.json")
                      .read_text(encoding="utf-8"))


def _locked(lockfile: str, package: str, version: str) -> bool:
    """Does the lockfile still resolve `package@version`? pnpm writes the key as `name@1.2.3:` (scoped names in
    quotes), and again with a peer suffix — `name@1.2.3(peer@4):` — under `snapshots:`."""
    text = (REPO / lockfile).read_text(encoding="utf-8")
    return re.search(rf"(?m)^\s+['\"]?{re.escape(package)}@{re.escape(version)}['\"]?[(:]", text) is not None


@pytest.mark.parametrize("app", sorted(SNAPSHOT["apps"]))
def test_a_pnpm_baseline_names_every_high_advisory_its_own_report_carried_against_a_version_still_locked(app):
    """THE DEFECT: `.github/audit-baseline/pnpm-web.txt` was short by one advisory, so the dependency-audit job
    exited 1 on the very pull request that added it, and "it starts green" was false on the day of merge.

    WHY THIS ASKS ABOUT VERSIONS STILL LOCKED, AND DOES NOT PIN THE LOCKFILE'S HASH: a Dependabot bump is
    supposed to make baseline lines stale (the gate prints them, and the file may only shrink), and it must not
    turn a required check red to do it. An advisory whose affected version has left the lockfile is no longer
    this baseline's to name; one that is still there must be, or the gate fails on it.
    """
    entry = SNAPSHOT["apps"][app]
    baseline = _gate().read_baseline((REPO / entry["baseline"]).read_text(encoding="utf-8"))
    applies = [a for a in entry["advisories"] if _locked(entry["lockfile"], a["package"], a["version"])]
    assert len(applies) >= 10, (
        f"only {len(applies)} of {len(entry['advisories'])} snapshot advisories still match a version in "
        f"{entry['lockfile']}: the snapshot has gone stale (regenerate it, see the fixture's how_to_regenerate) "
        "and this test would otherwise pass having looked at almost nothing")
    missing = [f"{a['package']} {a['version']} {a['id']} [{a['severity']}]" for a in applies if a["id"].upper() not in baseline]
    assert not missing, (
        f"{entry['baseline']} does not name {missing}. The dependency-audit job fails on each of these as NEW. "
        "Add the line (with its `package version [severity] — title` note and the reason it is carried) or upgrade "
        "the package so it leaves the lockfile.")


def test_the_snapshot_covers_the_population_and_is_not_an_empty_shell():
    """Vacuity guard for the test above: every pnpm app in the tree has a snapshot, each with real rows."""
    assert sorted(SNAPSHOT["apps"]) == _npm_apps()
    for app, entry in SNAPSHOT["apps"].items():
        assert entry["advisories"], app
        assert {a["severity"] for a in entry["advisories"]} <= {"high", "critical"}, app
        assert all(a["id"].upper().startswith("GHSA-") for a in entry["advisories"]), app


# ── the image the backend runs in (POST-A-175, POST-A-176) ───────────────────────

DOCKERFILE = APPS / "api" / "Dockerfile"


def test_the_base_image_is_pinned_by_digest_and_something_moves_the_pin():
    """`FROM python:3.11-slim` is a moving tag, so a build next month starts from an image the lock was never tested on. A digest fixes
    that and creates the opposite problem: a pin nothing moves is an unpatched base. So the rule has two halves and they are asserted
    together: every `FROM` carries a sha256 digest, and Dependabot has a docker entry for the directory the Dockerfile is in."""
    froms = re.findall(r"^FROM\s+(\S+)", _code(DOCKERFILE), flags=re.M)
    assert froms, "the scan found no FROM line: the Dockerfile moved or the pattern did"
    for ref in froms:
        assert re.fullmatch(r"[\w./-]+(:[\w.-]+)?@sha256:[0-9a-f]{64}", ref), (
            f"{ref!r} is not pinned by a sha256 digest: a moving tag is a different image next month")
    assert ("docker", "/apps/api") in set(_entries()), (
        "the base image is pinned by digest and Dependabot is not told to move the pin, so it would never be patched")


def test_the_python_the_lock_is_compiled_for_is_held_back_in_the_docker_entry():
    """The lock is compiled for Python 3.11 (its header says so), and a docker proposal of 3.12 would build an image the lock was not
    made for. The entry holds the minor and the major of `python` back; the digest and the patch releases still arrive."""
    ignores = [b for b in _blocks(_code(DEPENDABOT), "ignore") if 'dependency-name: "python"' in b]
    assert len(ignores) == 1, "the docker entry must hold the python minor and major back"
    assert "version-update:semver-minor" in ignores[0] and "version-update:semver-major" in ignores[0]


def test_the_web_server_worker_comes_from_its_own_package_and_is_locked():
    """`uvicorn.workers` is deprecated in favour of the separate `uvicorn-worker` package. The Dockerfile's command names the new class,
    the package is a direct dependency, and the lock holds it with its hashes (the lock test recompiles nothing, so this is the check
    that the command and the lock agree)."""
    cmd = re.search(r'^CMD\s*(\[.*\])\s*$', _code(DOCKERFILE), flags=re.M)
    assert cmd, "the Dockerfile has no CMD in exec form"
    args = json.loads(cmd.group(1))
    worker = args[args.index("--worker-class") + 1]
    assert worker == "uvicorn_worker.UvicornWorker", f"the worker class is {worker!r}: uvicorn.workers is the deprecated spelling"
    assert re.search(r"^uvicorn-worker==\d", (APPS / "api" / "requirements.in").read_text(encoding="utf-8"), flags=re.M)
    lock = (APPS / "api" / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^uvicorn-worker==\d[\d.]*\s*\\\n\s+--hash=sha256:[0-9a-f]{64}", lock, flags=re.M)
