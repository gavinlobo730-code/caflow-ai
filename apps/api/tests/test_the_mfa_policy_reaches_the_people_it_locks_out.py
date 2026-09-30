"""A Partner or Manager with no authenticator is TOLD, before mfa_guard refuses them.

WHAT WAS WRONG
    With REQUIRE_MFA on, `mfa_guard` 403s an aal1 token for every role in
    MFA_REQUIRED_ROLES, on firms, assignments, identity, practice, billing and
    payroll. A brand-new practice owner has no factor, so the sign-in challenge
    rightly asks for nothing — and nothing asked them to enrol either. The first
    they heard was "Multi-factor authentication required for this action." on a
    blank firm-profile form, and GET /api/identity/permissions (behind the same
    guard) failed, so every permission-gated button vanished.

    The browser cannot know who the guard covers: the roles are environment
    variables. So `GET /api/security/mfa-policy` serves it, OUTSIDE the guard,
    and `applies_to_caller` is the guard's own comparison.

WHAT THESE PIN
    * the policy answers for REQUIRE_MFA on and off, the default roles and a
      custom MFA_REQUIRED_ROLES;
    * the nudge and the refusal agree for every role — the endpoint and
      mfa_guard ask one function;
    * the endpoint is mounted and NOT behind mfa_guard (behind it, it would
      answer only people who no longer need it);
    * the browser's translation is keyed on the guard's exact sentence, and
      every place the browser turns a refusal body into text asks it.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi import HTTPException

import core.auth as auth
from core.permissions import Role
from routers.security_policy import mfa_policy

_WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
ROLES = [r.value for r in Role]


def _ask(role: str) -> dict:
    body = mfa_policy(current_user={"id": "u", "firm_id": "f", "role": role, "aal": "aal1"})
    assert body["success"] is True and body["error"] is None
    return body["data"]


def _guard_refuses(role: str) -> bool:
    try:
        auth.mfa_guard({"role": role, "aal": "aal1"})
    except HTTPException as e:
        assert e.status_code == 403
        return True
    return False


def test_with_mfa_off_nobody_is_covered(monkeypatch):
    monkeypatch.delenv("REQUIRE_MFA", raising=False)
    for role in ROLES:
        data = _ask(role)
        assert data["required"] is False
        assert data["applies_to_caller"] is False, role


def test_with_mfa_on_the_default_roles_are_partner_and_manager(monkeypatch):
    monkeypatch.setenv("REQUIRE_MFA", "true")
    monkeypatch.delenv("MFA_REQUIRED_ROLES", raising=False)
    assert _ask("Partner") == {"required": True, "roles": ["Manager", "Partner"], "applies_to_caller": True}
    assert _ask("Manager")["applies_to_caller"] is True
    for role in ("Executive", "Reviewer"):
        assert _ask(role)["applies_to_caller"] is False, role


def test_a_custom_role_list_is_what_is_served(monkeypatch):
    monkeypatch.setenv("REQUIRE_MFA", "on")
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "Partner")
    assert _ask("Partner")["applies_to_caller"] is True
    assert _ask("Manager")["applies_to_caller"] is False
    assert _ask("Manager")["roles"] == ["Partner"]


@pytest.mark.parametrize("flag", ["true", "false"])
@pytest.mark.parametrize("roles", ["Partner,Manager", "Partner", "Executive"])
def test_the_nudge_and_the_refusal_never_disagree(monkeypatch, flag, roles):
    """The browser banners exactly the people the guard will refuse at aal1."""
    monkeypatch.setenv("REQUIRE_MFA", flag)
    monkeypatch.setenv("MFA_REQUIRED_ROLES", roles)
    for role in ROLES + ["partner", "owner"]:  # legacy spellings the guard compares raw
        assert _ask(role)["applies_to_caller"] is _guard_refuses(role), role


def test_the_guard_still_lets_aal2_through(monkeypatch):
    monkeypatch.setenv("REQUIRE_MFA", "true")
    monkeypatch.delenv("MFA_REQUIRED_ROLES", raising=False)
    user = {"role": "Partner", "aal": "aal2"}
    assert auth.mfa_guard(user) is user


def test_the_policy_is_mounted_outside_the_mfa_guard():
    import main

    routes = [r for r in main.app.routes if getattr(r, "path", "") == "/api/security/mfa-policy"]
    assert len(routes) == 1, "GET /api/security/mfa-policy is not mounted"
    deps = {getattr(d, "call", None) for d in routes[0].dependant.dependencies}
    assert auth.mfa_guard not in deps, (
        "the MFA policy is behind mfa_guard, so the aal1 caller who needs it is refused")
    assert auth.get_current_user in deps, "the policy must still need an authenticated user"


def _guard_detail() -> str:
    import os
    old = os.environ.get("REQUIRE_MFA")
    os.environ["REQUIRE_MFA"] = "true"
    try:
        auth.mfa_guard({"role": "Partner", "aal": "aal1"})
    except HTTPException as e:
        return e.detail
    finally:
        if old is None:
            os.environ.pop("REQUIRE_MFA", None)
        else:
            os.environ["REQUIRE_MFA"] = old
    raise AssertionError("mfa_guard did not refuse an aal1 Partner with REQUIRE_MFA on")


def test_the_browser_translates_the_guards_exact_sentence():
    src = (_WEB / "lib" / "auth" / "mfaRefusal.ts").read_text()
    m = re.search(r'export const MFA_REQUIRED_DETAIL\s*=\s*"([^"]+)"', src)
    assert m, "lib/auth/mfaRefusal.ts no longer declares MFA_REQUIRED_DETAIL"
    assert m.group(1) == _guard_detail(), (
        "the browser keys its MFA translation on a sentence mfa_guard does not send")


def _code(src: str) -> str:
    return re.sub(r"/\*[\s\S]*?\*/", " ", re.sub(r"(?m)^\s*//.*$", " ", src))


def _guarded_prefixes() -> set[str]:
    import main

    out = set()
    for route in main.app.routes:
        deps = {getattr(d, "call", None) for d in getattr(getattr(route, "dependant", None), "dependencies", [])}
        if auth.mfa_guard in deps:
            parts = str(route.path).split("/")
            out.add("/".join(parts[:3]))  # "/api/<prefix>"
    return out


def _browser_sources() -> list[pathlib.Path]:
    out = []
    for top in ("app", "components", "lib"):
        for path in (_WEB / top).rglob("*"):
            if path.suffix not in (".ts", ".tsx") or re.search(r"\.test\.tsx?$", path.name):
                continue
            if "node_modules" in path.parts or path == _WEB / "lib" / "api" / "index.ts":
                continue
            out.append(path)
    return out


def test_every_browser_reader_of_a_guarded_refusal_translates_it():
    """A screen or helper that fetches an MFA-guarded path itself and reads
    `.detail` off the refusal must pass it through explainMfaRefusal — or the
    raw sentence reaches the CA again. lib/api/index.ts is held by the next
    test. The path counts however the URL is built — a quoted literal, a
    template after `${API}`, a concatenation — so the prefix is matched
    anywhere, bounded only so /api/firms does not match /api/firmsomething."""
    prefixes = _guarded_prefixes()
    assert {"/api/firms", "/api/identity", "/api/payroll"} <= prefixes, prefixes
    sources = _browser_sources()
    assert any(p.suffix == ".ts" for p in sources) and any(p.suffix == ".tsx" for p in sources)
    offenders = []
    for path in sources:
        src = _code(path.read_text())
        names_a_guarded_path = any(re.search(re.escape(p) + r"(?![\w-])", src) for p in prefixes)
        if names_a_guarded_path and re.search(r"\.detail\b", src) and "explainMfaRefusal" not in src:
            offenders.append(str(path.relative_to(_WEB)))
    assert not offenders, f"these read a guarded refusal's detail without translating it: {offenders}"


# A read of `.detail` off a parsed body: `parsed?.detail`, `body.detail`,
# `JSON.parse(body)?.detail`.
_DETAIL_READ = re.compile(r"[\w\])]\s*\??\.\s*detail\b")
# Calls whose argument is inspected or translated, not turned into text.
_CALLS_THAT_INSPECT = {"if", "while", "isArray", "explainMfaRefusal"}


def _reaches_text(src: str, start: int, end: int) -> str | None:
    """Why the value at src[start:end] reaches text untranslated, or None."""
    tail = src[end:]
    trimmed = re.match(r"\s*\.\s*trim\(\s*\)", tail)
    if trimmed:
        tail = tail[trimmed.end():]
    if re.match(r"\s*(\??\.|\[)", tail):
        return None  # a property of it (`.message`, `.map`), not the string itself
    head = src[:start].rstrip()
    if re.search(r"(?:^|[^=!<>])=$", head) or re.search(r"\breturn$", head):
        return "returned or assigned"
    if head.endswith(("??", "||", "?", ":", "${", ",")):
        return "used as a value"
    call = re.search(r"(\w+)\s*\($", head)
    if call and call.group(1) not in _CALLS_THAT_INSPECT:
        return f"passed to {call.group(1)}()"
    return None


def untranslated_detail_reads(src: str) -> tuple[int, list[str]]:
    """Every read of a refusal's `detail` in `src`, and the ones that turn it
    into text without explainMfaRefusal — read straight into a return or an
    assignment, or bound to a name that is then returned, assigned,
    interpolated or passed on."""
    src = _code(src)
    reads, offenders = 0, []
    for m in _DETAIL_READ.finditer(src):
        reads += 1
        read_start = m.start() + 1  # the match begins on the character before the dot
        line_start = src.rfind("\n", 0, read_start) + 1
        bound = re.match(r"\s*(?:const|let|var)\s+(\w+)\s*=", src[line_start:read_start])
        if bound:
            name = bound.group(1)
            stmt_end = src.find(";", read_start)
            stmt_end = len(src) if stmt_end < 0 else stmt_end
            for use in re.finditer(r"(?<![\w.$])" + re.escape(name) + r"\b", src[stmt_end:]):
                at = stmt_end + use.start()
                why = _reaches_text(src, at, at + len(name))
                if why:
                    line_end = src.find("\n", at)
                    offenders.append(f"{name} {why}: {src[src.rfind(chr(10), 0, at) + 1:line_end if line_end >= 0 else None].strip()}")
            continue
        head = src[line_start:read_start]
        receiver = re.search(r"[\w$.?()\[\]]+$", head.rstrip())
        value_start = line_start + (receiver.start() if receiver else len(head))
        why = _reaches_text(src, value_start, m.end())
        if why and "explainMfaRefusal(" not in head:
            line_end = src.find("\n", read_start)
            offenders.append(f"detail {why}: {src[line_start:line_end if line_end >= 0 else None].strip()}")
    return reads, offenders


def test_every_refusal_reader_in_lib_api_translates_the_detail():
    reads, offenders = untranslated_detail_reads((_WEB / "lib" / "api" / "index.ts").read_text())
    assert reads >= 2, "no refusal reader found in lib/api — the scan is looking at nothing"
    assert not offenders, f"lib/api turns a refusal into text without explainMfaRefusal: {offenders}"


@pytest.mark.parametrize("snippet", [
    "const d = parsed?.detail;\nif (typeof d === 'string') return d;",
    "const detail = JSON.parse(body)?.detail;\nmessage = detail;",
    "const detail = parsed?.detail ?? parsed?.error;\nthrow new Error(detail);",
    "const detail = parsed.detail;\nreturn `API error: ${detail}`;",
    "return parsed.detail;",
    "message = JSON.parse(body)?.detail ?? 'x';",
])
def test_the_lib_api_scan_catches_an_untranslated_reader(snippet):
    reads, offenders = untranslated_detail_reads(snippet)
    assert reads == 1 and offenders, snippet


@pytest.mark.parametrize("snippet", [
    "const detail = parsed?.detail;\nif (typeof detail === 'string' && detail.trim()) return explainMfaRefusal(detail.trim());",
    "const detail = parsed?.detail;\nif (detail && typeof detail === 'object') return detail.message;",
    "const detail = parsed?.detail;\nif (Array.isArray(detail)) return detail.map((d) => d.msg).join(' ');",
    "return explainMfaRefusal(parsed.detail);",
])
def test_the_lib_api_scan_passes_a_translated_reader(snippet):
    reads, offenders = untranslated_detail_reads(snippet)
    assert reads == 1 and not offenders, (snippet, offenders)
