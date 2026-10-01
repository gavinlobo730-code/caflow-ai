"""A secret committed to this repository fails a check, and the check cannot be quietly weakened (engineering-05).

WHAT WAS WRONG
    Nothing in the repository scanned for a committed secret, in a product whose own rule is that every AI
    key lives in apps/api/.env and never anywhere a browser can reach. The repository is public, so a
    secret that lands in a commit is published the moment it is pushed.

WHAT THIS PINS, AND WHAT IT CANNOT
    Whether gitleaks finds a given token is gitleaks' business. It was measured by hand on 30-09-2026 with
    synthetic tokens (service-role JWT, another project's anon JWT, Groq, Gemini, Razorpay-shaped: all
    caught), and over all 2,519 commits (26 findings before the config, none real, none after). What is
    pinned here is everything around that:

      1. the workflow runs on every pull request and push with no path filter (so it is safe to require),
         verifies its download against a SHA-256 BEFORE running it, and gives the script what it reads;
      2. the script scans what an event introduced — and ALL of history when it cannot tell;
      3. the config's allowlists stay narrow: the public anon key is matched by header + issuer + project +
         role, so a SERVICE-ROLE token in the same place is still caught, and only the noisy generic rule is
         ever silenced by path;
      4. where a real gitleaks is on PATH, the script catches a secret in a pull request's range, is quiet
         about one committed before it, and does not print the token it found;
      5. THE TREE ITSELF IS CLEAN UNDER THE CONFIG. The first draft of this module pinned the rules around
         the scan and never ran the scan over the repository it guards, so the commit that added a fake JWT
         to a test (ops-09) turned the new check red on its own pull request and nothing here noticed. Two
         tests now ask the question directly: one with no binary (every JWT-shaped token in a tracked file
         must be covered by a `jwt` allowlist, so it runs in the required pytest check, where gitleaks is
         not installed) and one with the real binary over a copy of the tracked files.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "secret-scan.yml"
SCRIPT = REPO / ".github" / "scripts" / "secret-scan.sh"
CONFIG = REPO / ".gitleaks.toml"
WRANGLER = REPO / "apps" / "web" / "wrangler.toml"
ZEROS = "0" * 40


def _code(path: Path) -> str:
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#"))


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")


HEADER = _b64({"alg": "HS256", "typ": "JWT"})


def _jwt(role: str, ref: str = "pbgoeyjvmllrafzavkgx") -> str:
    """A synthetic token with the shape of a Supabase key. The signature is arbitrary: nothing here is a credential."""
    payload = _b64({"iss": "supabase", "ref": ref, "role": role, "iat": 1780295902, "exp": 2095871902})
    return f"{HEADER}.{payload}.{'A' * 43}"


# ── the workflow ────────────────────────────────────────────────────────────────

def test_it_runs_on_every_pull_request_and_push_weekly_and_on_demand_with_no_path_filter():
    text = _code(WORKFLOW)
    for trigger in ("pull_request:", "push:", "schedule:", "workflow_dispatch:"):
        assert re.search(rf"^\s*{trigger}", text, re.M), f"no {trigger} trigger"
    # CLAUDE.md: a workflow carrying a required check must not be path-filtered, or the check never reports
    # on a pull request the filter misses and GitHub waits for it for ever.
    assert not re.search(r"^\s*paths(-ignore)?:", text, re.M)
    assert "continue-on-error" not in text


def test_the_job_has_one_fixed_name_so_it_can_be_made_a_required_check():
    assert len(re.findall(r"^\s{4}name: secret scan — gitleaks\s*$", _code(WORKFLOW), re.M)) == 1


def test_history_is_fetched_because_a_pull_requests_range_needs_both_ends():
    assert re.search(r"fetch-depth:\s*0", _code(WORKFLOW))


def test_the_binary_is_pinned_and_checked_against_its_checksum_before_it_is_run():
    text = _code(WORKFLOW)
    version = re.search(r'GITLEAKS_VERSION:\s*"(\d+\.\d+\.\d+)"', text)
    sha = re.search(r'GITLEAKS_SHA256:\s*"([0-9a-f]{64})"', text)
    assert version and sha, "the version and its SHA-256 must both be written down"
    assert "${GITLEAKS_VERSION}" in text.split("curl", 1)[1], "the URL must be built from the pinned version"
    assert text.index("sha256sum --check --strict") < text.index("tar -xzf"), (
        "the tarball must be verified BEFORE it is extracted, let alone executed")
    assert "GITLEAKS_SHA256}" in text, "the check must use the pinned value"


def test_the_scan_step_hands_the_script_every_variable_it_reads():
    workflow = _code(WORKFLOW)
    script = SCRIPT.read_text(encoding="utf-8")
    for name in ("EVENT_NAME", "BASE_SHA", "HEAD_SHA", "BEFORE_SHA", "AFTER_SHA"):
        assert re.search(rf"^\s+{name}:\s*\$\{{\{{", workflow, re.M), f"the workflow does not set {name}"
        assert name in script, f"the script no longer reads {name}; remove it from the workflow"
    assert ".github/scripts/secret-scan.sh" in workflow


def test_the_script_is_executable_and_redacts_because_the_log_of_a_public_repo_is_public():
    assert SCRIPT.stat().st_mode & stat.S_IXUSR, "git would commit it non-executable and the step would fail to run"
    assert "--redact" in SCRIPT.read_text(encoding="utf-8")


# ── the script's range logic ────────────────────────────────────────────────────

def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _repo_with_commits(tmp_path: Path, files: list[dict[str, str]]) -> tuple[Path, list[str]]:
    """A throwaway repository with one commit per entry of `files` ({path: content}); returns the SHAs."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    for n, batch in enumerate(files):
        for name, content in batch.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(content, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"commit {n}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


def _fake_gitleaks(tmp_path: Path, exit_code: int = 0) -> Path:
    """A stand-in binary that records its arguments — so the range logic is tested without gitleaks."""
    fake = tmp_path / "fake-gitleaks"
    fake.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{tmp_path}/args.txt"\nexit {exit_code}\n')
    fake.chmod(0o755)
    return fake


def _run_script(repo: Path, env: dict[str, str], gitleaks: Path):
    full = {"PATH": os.environ["PATH"], "GITLEAKS": str(gitleaks), **env}
    return subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=full, capture_output=True, text=True)


def _args(tmp_path: Path) -> list[str]:
    return (tmp_path / "args.txt").read_text().splitlines()


def test_a_pull_request_is_judged_on_the_commits_it_adds(tmp_path):
    repo, (a, b) = _repo_with_commits(tmp_path, [{"x.txt": "1"}, {"x.txt": "2"}])
    r = _run_script(repo, {"EVENT_NAME": "pull_request", "BASE_SHA": a, "HEAD_SHA": b}, _fake_gitleaks(tmp_path))
    assert r.returncode == 0, r.stderr
    args = _args(tmp_path)
    assert f"--log-opts={a}..{b}" in args
    assert args[:2] == ["git", "."] and "--redact" in args
    assert args[args.index("--config") + 1] == ".gitleaks.toml"


def test_a_push_is_judged_on_what_the_push_added(tmp_path):
    repo, (a, b) = _repo_with_commits(tmp_path, [{"x.txt": "1"}, {"x.txt": "2"}])
    _run_script(repo, {"EVENT_NAME": "push", "BEFORE_SHA": a, "AFTER_SHA": b}, _fake_gitleaks(tmp_path))
    assert f"--log-opts={a}..{b}" in _args(tmp_path)


@pytest.mark.parametrize("event,extra", [
    ("schedule", {}),
    ("workflow_dispatch", {}),
    ("push", {"BEFORE_SHA": ZEROS, "AFTER_SHA": "deadbeef"}),                          # a first push
    ("push", {"BEFORE_SHA": "f" * 40, "AFTER_SHA": "e" * 40}),                          # a force-push: the base is gone
    ("pull_request", {"BASE_SHA": "f" * 40, "HEAD_SHA": "e" * 40}),                     # a base that cannot be resolved
    ("pull_request", {}),
])
def test_when_it_cannot_tell_what_changed_it_scans_all_of_history(tmp_path, event, extra):
    """A wasted minute is cheaper than a skipped scan reporting clean (backend-ci.yml's `scope` job reasons the same)."""
    repo, _ = _repo_with_commits(tmp_path, [{"x.txt": "1"}])
    r = _run_script(repo, {"EVENT_NAME": event, **extra}, _fake_gitleaks(tmp_path))
    assert r.returncode == 0, r.stderr
    assert not any(a.startswith("--log-opts") for a in _args(tmp_path)), _args(tmp_path)
    assert "ALL of history" in r.stdout


def test_the_script_returns_gitleaks_own_exit_code_so_a_finding_fails_the_job(tmp_path):
    repo, _ = _repo_with_commits(tmp_path, [{"x.txt": "1"}])
    r = _run_script(repo, {"EVENT_NAME": "schedule"}, _fake_gitleaks(tmp_path, exit_code=1))
    assert r.returncode == 1


def test_the_script_refuses_to_run_without_knowing_the_event(tmp_path):
    repo, _ = _repo_with_commits(tmp_path, [{"x.txt": "1"}])
    assert _run_script(repo, {}, _fake_gitleaks(tmp_path)).returncode != 0


# ── the config ──────────────────────────────────────────────────────────────────

CONFIG_TOML = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
ALLOWLISTS = CONFIG_TOML["allowlists"]


def test_the_config_extends_the_default_rules_and_adds_a_groq_rule():
    assert CONFIG_TOML["extend"]["useDefault"] is True
    (groq,) = [r for r in CONFIG_TOML["rules"] if r["id"] == "groq-api-key"]
    assert re.search(groq["regex"], "gsk_" + "a" * 52)
    assert not re.search(groq["regex"], "gsk_tooshort")


def test_every_allowlist_says_why_and_names_the_rules_it_silences():
    """An allowlist with no `targetRules` silences EVERY rule for what it matches."""
    assert len(ALLOWLISTS) >= 4
    for a in ALLOWLISTS:
        assert len(a["description"]) > 40, "say what this is and why it is not a secret"
        assert a["targetRules"], f"{a['description'][:50]}... silences every rule"


def test_only_the_noisy_generic_rule_is_ever_silenced_by_path():
    """The vendor rules — jwt, gcp-api-key, groq-api-key, every cloud token — still apply inside tests."""
    for a in ALLOWLISTS:
        if a.get("paths"):
            assert a["targetRules"] == ["generic-api-key"], a["description"]


def _jwt_allowlists() -> list[dict]:
    return [x for x in ALLOWLISTS if x["targetRules"] == ["jwt"]]


def _jwt_patterns() -> list[re.Pattern]:
    return [re.compile(r) for a in _jwt_allowlists() for r in a["regexes"]]


def _anon_allowlist() -> re.Pattern:
    """The one jwt allowlist that covers wrangler.toml's public anon key. There is more than one jwt allowlist
    (see the fixture one below), so it is found by what it matches and not by being the only one."""
    anon = _wrangler_anon_key()
    (pattern,) = [p for p in _jwt_patterns() if p.match(anon)]
    return pattern


def _wrangler_anon_key() -> str:
    m = re.search(r'NEXT_PUBLIC_SUPABASE_ANON_KEY\s*=\s*"(eyJ[^"]+)"', WRANGLER.read_text(encoding="utf-8"))
    assert m, "wrangler.toml no longer carries the anon key this allowlist exists for"
    return m.group(1)


def test_the_public_anon_key_is_allowlisted_by_value_and_rotating_it_says_so():
    """If the anon key is rotated this fails with a sentence, instead of as a mystery red secret scan."""
    anon = _wrangler_anon_key()
    payload = json.loads(base64.urlsafe_b64decode(anon.split(".")[1] + "==="))
    assert payload["role"] == "anon", "wrangler.toml holds a key that is NOT the public anon key — that is a leak"
    assert _anon_allowlist().match(anon), (
        "the allowlist no longer matches wrangler.toml's anon key (was it rotated?). Re-derive the prefix: "
        "header + base64 of the payload up to and including \"role\":\"anon\".")


def test_the_anon_allowlist_does_not_shelter_a_service_role_token_or_another_projects_key():
    pattern = _anon_allowlist()
    assert not pattern.match(_jwt("service_role")), "a SERVICE-ROLE token with this project's ref must still be caught"
    assert not pattern.match(_jwt("service_role", ref="zzzzzzzzzzzzzzzzzzzz"))
    assert not pattern.match(_jwt("anon", ref="zzzzzzzzzzzzzzzzzzzz")), "another project's anon key is not this one"
    assert pattern.match(_jwt("anon")), "control: this project's anon-role token IS covered"


def test_the_example_env_placeholder_is_allowlisted_and_a_real_looking_token_is_not():
    (a,) = [x for x in ALLOWLISTS if x["targetRules"] == ["generic-api-key"] and x.get("regexes")
            and x["regexTarget"] == "secret"]
    pattern = re.compile(a["regexes"][0])
    assert pattern.match(HEADER + "...")
    assert not pattern.match(_jwt("service_role"))
    assert not pattern.match(HEADER + "...and-more")


def test_a_storage_label_is_allowlisted_on_its_own_line_and_nothing_wider():
    (a,) = [x for x in ALLOWLISTS if x.get("regexTarget") == "line" and "persistKey" in x["description"]]
    pattern = re.compile(a["regexes"][0])
    assert pattern.search('<DataTable persistKey="bank.entries.v1" />')
    assert not pattern.search('api_key = "abcdef0123456789abcdef0123456789"')
    assert a["targetRules"] == ["generic-api-key"]


def _option_list_allowlist() -> dict:
    (a,) = [x for x in ALLOWLISTS
            if x.get("regexTarget") == "line" and "option" in x["description"].lower() and "label" in x["description"]]
    return a


def test_a_ui_option_id_is_allowlisted_by_its_whole_shape_and_only_for_the_generic_rule():
    """`{ key: "commuted_pension_10_10a", label: "..." }` is a dropdown choice (SalaryWorksheet), and the entropy rule
    reads the id as a key. The allowlist must match that shape and nothing a credential looks like."""
    a = _option_list_allowlist()
    assert a["targetRules"] == ["generic-api-key"], "the vendor rules must still apply to the same line"
    assert not a.get("paths"), "an option list is recognised by its shape, never by where the file is"
    pattern = re.compile(a["regexes"][0])
    for line in (
        '  { key: "commuted_pension_10_10a", label: "Commuted pension — §10(10A)" },',
        '{ key: "official_duty_allowance_10_14_i", label: "Allowance for expenses of official duty — §10(14)(i)" },',
        '    { key: "gratuity_10_10", label: "Gratuity" }',
    ):
        assert pattern.search(line), line
    for line in (
        '  { key: "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY", label: "x" },',                       # mixed case
        '  { key: "0123456789abcdef0123456789abcdef01234567", label: "x" },',               # hexadecimal, no words
        '  { key: "Sk_Live_4eC39HqLyjWDarjtT1zdp7dc", label: "x" },',                        # a vendor-like shape (upper case)
        '  { key: "gratuity_10_10" },',                                                      # not followed by a label
        'const config = { key: "commuted_pension_10_10a", other: "x" };',                    # not an option entry
        'api_key = "abcdef0123456789abcdef0123456789"',
    ):
        assert not pattern.search(line), line


def test_the_path_allowlists_match_a_relative_and_an_absolute_path():
    """A history scan reports repo-relative paths and a working-tree scan reports absolute ones; a pattern
    anchored for one matches nothing in the other — which is exactly how three test-file findings survived
    the first draft of this config."""
    (a,) = [x for x in ALLOWLISTS if x.get("paths")]
    patterns = [re.compile(p) for p in a["paths"]]
    for path in ("apps/api/tests/test_x.py", "/home/runner/work/r/r/apps/api/tests/test_x.py",
                 "apps/web/lib/foo.test.ts", "/abs/apps/web/lib/foo.test.tsx"):
        assert any(p.search(path) for p in patterns), path
    for path in ("apps/api/core/config.py", "apps/web/lib/foo.ts", "apps/web/wrangler.toml"):
        assert not any(p.search(path) for p in patterns), path


# ── the tree itself ─────────────────────────────────────────────────────────────

# The scrub tests' own fake token (apps/web/lib/monitoring/scrub.test.ts): header {"alg":"HS256"}, payload
# {"sub":"1234567890"}, signature the word "signature". Built here and not written out, so this file does not
# carry the literal it is about.
def _fixture_jwt() -> str:
    return f"{_b64({'alg': 'HS256'})}.{_b64({'sub': '1234567890'})}.{base64.urlsafe_b64encode(b'signature').decode().rstrip('=')}"


# gitleaks' own `jwt` rule shape (v8.30.0). Kept loose on purpose: a token this matches and gitleaks does not is
# a harmless extra question, and one gitleaks matches and this does not is what the binary-backed test below
# is there to catch.
JWT_SHAPE = re.compile(r"\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/\\_-]{17,}\.(?:[a-zA-Z0-9/\\_-]{10,}={0,2})?)(?:['\"|\n\r\s`;]|$)")


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True, capture_output=True, text=True).stdout
    return [REPO / name for name in out.split("\0") if name]


def _uncovered_jwts(texts: dict[str, str]) -> list[tuple[str, int]]:
    """(path, line) of every JWT-shaped token that no `jwt` allowlist in the config matches."""
    patterns = _jwt_patterns()
    found = []
    for path, text in texts.items():
        for m in JWT_SHAPE.finditer(text):
            if not any(p.search(m.group(1)) for p in patterns):
                found.append((path, text.count("\n", 0, m.start()) + 1))
    return found


def test_the_fixture_token_allowlist_is_by_value_and_shelters_nothing_else():
    """The first draft of the config allowlisted the public anon key and nothing else, and the scrub test's fake
    JWT went through as a finding. Allowlisting `jwt` by PATH is forbidden (only the generic rule may be silenced
    by path), so the exception is the token's own value, anchored at both ends: nothing longer, nothing shorter,
    and nothing whose payload says it is a real credential."""
    fixture = _fixture_jwt()
    (pattern,) = [p for p in _jwt_patterns() if p.search(fixture)]
    assert pattern.pattern.startswith("^") and pattern.pattern.endswith("$"), "a value allowlist must be anchored both ends"
    assert not pattern.search(_jwt("service_role")), "a service-role token must still be caught"
    assert not pattern.search(_jwt("anon")) and not pattern.search(_jwt("anon", ref="zzzzzzzzzzzzzzzzzzzz"))
    assert not pattern.search(fixture + "x") and not pattern.search("x" + fixture)
    assert not pattern.search(fixture.rsplit(".", 1)[0] + "." + "A" * 43), "same header and payload, a different signature"
    assert not pattern.search(_wrangler_anon_key()), "the anon key has its own allowlist and is not this one"


def test_a_jwt_shaped_token_nothing_allowlists_is_reported_by_the_binary_free_check():
    """Control for the test below: it must be able to fail. A service-role token is uncovered, the two tokens the
    repository legitimately holds are not."""
    assert _uncovered_jwts({"apps/api/settings.py": f'KEY = "{_jwt("service_role")}"\n'}) == [("apps/api/settings.py", 1)]
    assert _uncovered_jwts({"a.ts": f"const t = '{_fixture_jwt()}'\n", "wrangler.toml": f'K = "{_wrangler_anon_key()}"\n'}) == []


def test_every_jwt_shaped_token_in_a_tracked_file_is_covered_by_a_jwt_allowlist():
    """THE TEST THE FIRST DRAFT LACKED. Needs no binary, so it runs in the required pytest check; gitleaks itself
    is exercised over the same tree by the test in the next section when it is installed."""
    texts = {}
    for path in _tracked_files():
        try:
            texts[str(path.relative_to(REPO))] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue          # a binary or a deleted file holds no token a person typed
    assert len(texts) > 1000, "the tree was not read, so this test would pass having looked at nothing"
    assert _uncovered_jwts(texts) == [], (
        "a JWT-shaped token is committed and no allowlist in .gitleaks.toml covers it, so the Secret scan check "
        "fails on the pull request that adds it. If it is a fake, build it at run time or allowlist its exact "
        "value (and mind that it stays in HISTORY: removing it later does not clear the finding). If it is real, "
        "it is a leak and has to be rotated.")


# ── with a real gitleaks ────────────────────────────────────────────────────────

needs_gitleaks = pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not on PATH")


@needs_gitleaks
def test_end_to_end_a_secret_in_the_range_fails_one_before_it_does_not_and_it_is_not_printed(tmp_path):
    token = _jwt("service_role")
    repo, (c1, c2, c3) = _repo_with_commits(tmp_path, [
        {"README.md": "clean"},
        {"apps/api/settings.py": f'SUPABASE_SERVICE_ROLE_KEY = "{token}"\n'},
        {"README.md": "still clean"},
    ])
    shutil.copy(CONFIG, repo / ".gitleaks.toml")
    gitleaks = Path(shutil.which("gitleaks"))

    in_range = _run_script(repo, {"EVENT_NAME": "pull_request", "BASE_SHA": c1, "HEAD_SHA": c2}, gitleaks)
    assert in_range.returncode == 1, in_range.stdout + in_range.stderr
    log = in_range.stdout + in_range.stderr
    assert token not in log, "--redact did not hide the secret in a PUBLIC log"
    assert token.split(".")[2] not in log and token.split(".")[1] not in log, "a fragment of the token is in the log"
    # A red run has to say WHAT to fix: the rule, the file and the commit, not only "leaks found: 1".
    assert "RuleID:      jwt" in log and "apps/api/settings.py" in log and "Commit:" in log, log

    after_it = _run_script(repo, {"EVENT_NAME": "pull_request", "BASE_SHA": c2, "HEAD_SHA": c3}, gitleaks)
    assert after_it.returncode == 0, "a pull request must not be red for a secret committed before it"

    weekly = _run_script(repo, {"EVENT_NAME": "schedule"}, gitleaks)
    assert weekly.returncode == 1, "the weekly full-history scan must still find it"


@needs_gitleaks
def test_end_to_end_the_public_anon_key_and_a_placeholder_pass_but_a_service_role_key_in_wrangler_does_not(tmp_path):
    anon = _wrangler_anon_key()
    clean_repo, _ = _repo_with_commits(tmp_path / "clean", [{
        "apps/web/wrangler.toml": f'NEXT_PUBLIC_SUPABASE_ANON_KEY = "{anon}"\n',
        ".env.example": f"SUPABASE_ANON_KEY={HEADER}...\n",
    }])
    shutil.copy(CONFIG, clean_repo / ".gitleaks.toml")
    gitleaks = Path(shutil.which("gitleaks"))
    assert _run_script(clean_repo, {"EVENT_NAME": "schedule"}, gitleaks).returncode == 0

    bad_repo, _ = _repo_with_commits(tmp_path / "bad", [{
        "apps/web/wrangler.toml": f'NEXT_PUBLIC_SUPABASE_ANON_KEY = "{_jwt("service_role")}"\n',
    }])
    shutil.copy(CONFIG, bad_repo / ".gitleaks.toml")
    assert _run_script(bad_repo, {"EVENT_NAME": "schedule"}, gitleaks).returncode == 1


@needs_gitleaks
def test_end_to_end_a_groq_key_is_caught_even_inside_a_test_file(tmp_path):
    repo, _ = _repo_with_commits(tmp_path, [{"apps/api/tests/test_x.py": f'KEY = "gsk_{"aB3" * 18}"\n'}])
    shutil.copy(CONFIG, repo / ".gitleaks.toml")
    assert _run_script(repo, {"EVENT_NAME": "schedule"}, Path(shutil.which("gitleaks"))).returncode == 1


@needs_gitleaks
def test_end_to_end_a_ui_option_id_passes_but_a_mixed_case_secret_in_the_same_shape_does_not(tmp_path):
    """The allowlist exists because an option list tripped the entropy rule on its own pull request, and the commit
    stays in the range whatever a later commit does. The control is the same line shape with a value that is a
    credential and not a word: it must still be found."""
    gitleaks = Path(shutil.which("gitleaks"))
    ok, _ = _repo_with_commits(tmp_path / "ok", [{
        "apps/web/components/tax/Options.tsx":
            'const OPTIONS = [\n  { key: "commuted_pension_10_10a", label: "Commuted pension — §10(10A)" },\n];\n'}])
    shutil.copy(CONFIG, ok / ".gitleaks.toml")
    assert _run_script(ok, {"EVENT_NAME": "schedule"}, gitleaks).returncode == 0

    control, _ = _repo_with_commits(tmp_path / "control", [{
        "apps/web/components/tax/Options.tsx":
            'const OPTIONS = [\n  { key: "Zk3Qm9Xv2Lp7Rt5Wy8Bn4Hc6Jd1Fs0Ag", label: "x" },\n];\n'}])
    shutil.copy(CONFIG, control / ".gitleaks.toml")
    assert _run_script(control, {"EVENT_NAME": "schedule"}, gitleaks).returncode == 1


def _copy_tracked_tree(dest: Path) -> Path:
    """The tracked files as they are NOW (uncommitted edits included), without the untracked clutter of a worktree
    (node_modules, .next, sibling worktrees) that `gitleaks dir .` would wander into."""
    for path in _tracked_files():
        if not path.is_file():
            continue
        target = dest / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy(CONFIG, dest / ".gitleaks.toml")
    return dest


@needs_gitleaks
def test_end_to_end_the_real_tree_is_clean_under_the_real_config(tmp_path):
    """Run the actual binary over the actual repository. This is the check that was red on its own pull request."""
    tree = _copy_tracked_tree(tmp_path / "tree")
    r = subprocess.run([shutil.which("gitleaks"), "dir", str(tree), "--config", str(tree / ".gitleaks.toml"),
                        "--redact", "--verbose", "--no-banner"], capture_output=True, text=True)
    assert r.returncode == 0, "gitleaks reports a finding in the tracked tree:\n" + r.stdout + r.stderr


@needs_gitleaks
def test_end_to_end_a_fixture_token_committed_and_later_removed_is_still_allowlisted_in_history(tmp_path):
    """Why the fix is in the CONFIG and not in the test file: a pull request is judged on the commits it adds, and
    the commit that introduced the literal stays in that range however the next commit tidies it, as does the
    weekly full-history scan. Removing the token from the tree clears nothing; only an allowlist does."""
    repo, _ = _repo_with_commits(tmp_path / "fixture", [
        {"apps/web/lib/x.test.ts": f'const t = "{_fixture_jwt()}";\n'},
        {"apps/web/lib/x.test.ts": "const t = 1;\n"},
    ])
    shutil.copy(CONFIG, repo / ".gitleaks.toml")
    gitleaks = Path(shutil.which("gitleaks"))
    assert _run_script(repo, {"EVENT_NAME": "schedule"}, gitleaks).returncode == 0

    control, _ = _repo_with_commits(tmp_path / "control", [
        {"apps/web/lib/x.test.ts": f'const t = "{_jwt("service_role")}";\n'},
        {"apps/web/lib/x.test.ts": "const t = 1;\n"},
    ])
    shutil.copy(CONFIG, control / ".gitleaks.toml")
    assert _run_script(control, {"EVENT_NAME": "schedule"}, gitleaks).returncode == 1, (
        "a service-role token in a test file, removed the next commit, must still be found in history")
