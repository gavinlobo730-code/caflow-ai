"""A BLANK dashboard value is "not set", and no server read may treat it as a value.

Found on 8 October 2026 from a screenshot of the Render dashboard: `PAYMENT_PROVIDER` was present and blank.
Render lists every `sync: false` key of render.yaml whether or not anyone has filled it in, and the process
receives the empty box as an empty STRING. `os.environ.get("PAYMENT_PROVIDER", "mock")` returns that string (the
default only covers a variable that is absent), so the provider became "" and creating a payment link raised
`Unsupported PAYMENT_PROVIDER` instead of falling back to the mock. The same shape was one edit away from three
more: a blank `EMAIL_FROM` is an empty sender the mail provider refuses, a blank `MFA_REQUIRED_ROLES` required MFA of
nobody, and a blank `SENTRY_TRACES_SAMPLE_RATE` crashed start-up on `float("")`.

THE RULE, not a list of today's reads: `core/env.env_or_default` is the way to read a setting that has a default,
and no server code gives `os.environ.get` / `os.getenv` a non-empty default of its own. The scan is the AST, so a
call split over several lines, a default held in a constant and a call under any alias of `os` are all seen.
Tests, scripts (they run stand-alone against a deployed API) and migrations are not server code.

ONE READ IS DELIBERATELY THE OTHER WAY AND IS NAMED, NOT HIDDEN: `ENABLE_FILING_SIMULATION` is a KILL SWITCH, and
its own test (test_filing_simulation_never_files) pins that anything that is not an explicit yes, a blank included,
turns it OFF, because on a deployment that records real filings "off" is the safe reading. `KILL_SWITCHES` below is an
equality in both directions: an entry whose read has gone fails as stale, so it cannot outlive its reason.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.env import env_or_default

API_ROOT = Path(__file__).resolve().parents[1]
_NOT_SERVER = {"tests", "scripts", "migrations", "__pycache__", ".venv", "venv", "node_modules"}


def _reads_with_a_default_of_their_own(source: str) -> list[tuple[int, str, str]]:
    """(line, variable, default) for every `os.environ.get("X", d)` / `os.getenv("X", d)` whose default is neither
    absent, `None` nor the empty string: the reads on which a blank value overrides the default."""
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and len(node.args) >= 2):
            continue
        fn = node.func
        direct_get = fn.attr == "get" and isinstance(fn.value, ast.Attribute) and fn.value.attr == "environ"
        getenv = fn.attr == "getenv" and isinstance(fn.value, ast.Name)
        name, default = node.args[0], node.args[1]
        if not (direct_get or getenv) or not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
            continue
        if isinstance(default, ast.Constant) and default.value in ("", None):
            continue
        out.append((node.lineno, name.value, ast.unparse(default)))
    return out


#: (file, variable) -> why a blank is allowed to override the default there. A switch that turns a capability OFF
#: reads "off" for anything that is not an explicit yes, so an operator who blanks it has switched it off.
KILL_SWITCHES: dict[tuple[str, str], str] = {
    ("services/filing_demo/common.py", "ENABLE_FILING_SIMULATION"):
        "the kill switch for the filing walk-throughs: anything that is not an explicit yes is OFF "
        "(tests/test_filing_simulation_never_files.py pins '' and '  ' as off)",
}


def _server_files() -> list[Path]:
    return [p for p in API_ROOT.rglob("*.py") if not set(p.relative_to(API_ROOT).parts) & _NOT_SERVER]


# ── the helper ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (None, "fallback"),
    ("", "fallback"),
    ("   ", "fallback"),
    ("\t\n", "fallback"),
    ("razorpay", "razorpay"),
    ("  razorpay  ", "razorpay"),
    ("0", "0"),
    ("false", "false"),
])
def test_a_value_that_is_unset_empty_or_blank_is_not_set(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("A_SETTING_NOBODY_HAS_FILLED_IN", raising=False)
    else:
        monkeypatch.setenv("A_SETTING_NOBODY_HAS_FILLED_IN", raw)
    assert env_or_default("A_SETTING_NOBODY_HAS_FILLED_IN", "fallback") == expected


# ── the scan itself: a guard that cannot see the old spelling guards nothing ──────────────────────────────

def test_the_scan_sees_the_old_spelling_in_every_form_it_takes():
    seen = _reads_with_a_default_of_their_own(
        'import os\n'
        'a = os.environ.get("A", "mock")\n'
        'b = os.getenv("B", "on")\n'
        'c = os.environ.get(\n    "C",\n    DEFAULT_C,\n)\n'
        'd = os.environ.get("D", "0").strip()\n')
    assert [(name, default) for _, name, default in seen] == [
        ("A", "'mock'"), ("B", "'on'"), ("C", "DEFAULT_C"), ("D", "'0'")]


def test_the_scan_leaves_alone_what_a_blank_cannot_hurt():
    assert _reads_with_a_default_of_their_own(
        'import os\n'
        'a = os.environ.get("A")\n'
        'b = os.environ.get("B", "")\n'
        'c = os.environ.get("C", None)\n'
        'd = (os.environ.get("D") or "").strip()\n'
        'e = env_or_default("E", "mock")\n'
        'f = os.environ["F"]\n') == []


def test_the_scan_covers_the_server_and_finds_something_to_read():
    files = _server_files()
    assert len(files) >= 300, "the walk found almost nothing; the rule below would pass over an empty tree"
    assert not any(p.name.startswith("test_") for p in files)
    assert any(p.name == "email_service.py" for p in files) and any(p.name == "factory.py" for p in files)


# ── the rule ──────────────────────────────────────────────────────────────────────────────────────────────

def test_no_server_read_gives_an_environment_variable_a_default_that_a_blank_value_would_override():
    offenders, named = [], set()
    for path in _server_files():
        rel = path.relative_to(API_ROOT).as_posix()
        for line, name, default in _reads_with_a_default_of_their_own(path.read_text(encoding="utf-8")):
            if (rel, name) in KILL_SWITCHES:
                named.add((rel, name))
                continue
            offenders.append(f"{rel}:{line}  {name} (default {default})")
    assert named == set(KILL_SWITCHES), (
        f"a named kill switch no longer has that read, so its entry is stale: {sorted(set(KILL_SWITCHES) - named)}")
    assert not offenders, (
        "read these through core.env.env_or_default(name, default): Render shows every dashboard-only variable "
        "whether or not anybody filled it in, and an empty box reaches the process as '' and not as unset, so the "
        "default would never apply:\n  " + "\n  ".join(offenders))


# ── the sites that were wrong, driven with the value a deployment really has ──────────────────────────────

@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_payment_provider_is_the_mock_and_online_payment_says_it_is_not_switched_on(monkeypatch, blank):
    """The default still applies to a blank (the factory builds the test double instead of raising). What the
    deployment then SAYS has changed (PRE-B-002 part 2): the double is not a way to collect money, so the
    availability rule answers `not_switched_on` and the routes refuse to make or send a link
    (test_a_payment_link_is_never_made_or_sent_while_online_payment_is_off.py). The factory half of this rule is
    unchanged; the rule is that a blank is read as the default, not as a provider called ''."""
    from services.payments import availability, factory
    from services.payments.mock import MockProvider
    monkeypatch.setenv("PAYMENT_PROVIDER", blank)
    assert factory.configured_provider() == "mock"
    assert isinstance(factory.get_provider(), MockProvider)
    assert availability.current().state == "not_switched_on" and availability.current().available is False


def test_an_explicit_payment_provider_still_wins_and_a_wrong_one_is_still_refused(monkeypatch):
    from services.payments import factory
    monkeypatch.setenv("PAYMENT_PROVIDER", " RazorPay ")
    assert factory.configured_provider() == "razorpay"
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")
    with pytest.raises(ValueError, match="Unsupported PAYMENT_PROVIDER"):
        factory.get_provider()


def test_the_kill_switch_is_still_the_other_way_round(monkeypatch):
    """The named exception is real: a blank filing-simulation switch is OFF, an explicit yes is ON, and unset is ON."""
    from services.filing_demo.common import filing_simulation_enabled
    monkeypatch.delenv("ENABLE_FILING_SIMULATION", raising=False)
    assert filing_simulation_enabled() is True
    monkeypatch.setenv("ENABLE_FILING_SIMULATION", "  ")
    assert filing_simulation_enabled() is False


@pytest.mark.parametrize("blank", ["", "  "])
def test_a_blank_mfa_role_list_does_not_mean_mfa_is_required_of_nobody(monkeypatch, blank):
    from core.security_config import mfa_required_roles
    monkeypatch.setenv("MFA_REQUIRED_ROLES", blank)
    assert mfa_required_roles() == {"Partner", "Manager"}
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "Partner")
    assert mfa_required_roles() == {"Partner"}


def test_a_blank_sender_is_the_default_sender_not_an_empty_from_field():
    """EMAIL_FROM is read once at import, so this is driven in a fresh interpreter with the value a deployment has."""
    out = subprocess.run(
        [sys.executable, "-c", "import services.email_service as m; print(m._FROM_EMAIL)"],
        cwd=API_ROOT, env={**os.environ, "EMAIL_FROM": "   "}, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip().splitlines()[-1] == "PracticeSync AI <noreply@caflow.ai>"
