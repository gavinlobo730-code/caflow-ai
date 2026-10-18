"""The authenticator reset has ONE door to the sign-in service and ONE spelling in the browser (POST-A-006).

WHAT IS HELD, AS RULES AND NOT AS SPELLINGS OF ONE CALL
    * only `core/auth_admin.py` talks to the sign-in service's factor API (`list_factors`, `delete_factor`, `.admin.mfa`, or
      a request built on the path `admin/users/<id>/factors`): the call lowers a person's sign-in protection and is made
      with the service-role key, so a second caller is a second place to get the library's traps wrong (the delete URL
      built from a key its own type does not declare, the listing parsed as an object when the service sends an array) and
      a second thing to audit;
    * the browser spells the request type once, in `lib/auth/authenticatorReset.ts`, and that spelling is the server's
      registered type;
    * the approvals route a LOCKED-OUT person uses is not behind the second factor, and the routes that decide are: moving
      `mfa_guard` onto the create route would silently turn the recovery path off for exactly the people it is for, and
      leaving it off the decision routes would let a password alone remove somebody's authenticator.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import services.mfa_reset_service as mfa
from core.auth import mfa_guard
from routers.approvals import router as approvals_router
from services.approval_service import REQUEST_TYPES

API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
DOOR = API / "core" / "auth_admin.py"
FACTOR_API = {"list_factors", "delete_factor"}


def _uses_factor_api(source: str) -> list[int]:
    """Lines that call the factor API: a method named as one, any access to `.mfa` on an `admin` object, or a path literal
    that begins `admin/users/` and names `/factors` (how the one door spells it now that it builds the requests itself)."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            if node.attr in FACTOR_API:
                hits.append(node.lineno)
            elif node.attr == "mfa" and isinstance(node.value, ast.Attribute) and node.value.attr == "admin":
                hits.append(node.lineno)
        elif isinstance(node, (ast.Constant, ast.JoinedStr)):
            text = node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else (
                "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
                if isinstance(node, ast.JoinedStr) else "")
            if text.startswith("admin/users/") and "/factors" in text:
                hits.append(node.lineno)
    return hits


def _production_sources() -> dict[Path, str]:
    skip = {"tests", "venv", ".venv", "node_modules", "__pycache__"}
    return {p: p.read_text(encoding="utf-8") for p in API.rglob("*.py") if not skip.intersection(p.relative_to(API).parts)}


def test_only_the_one_module_calls_the_factor_api():
    offenders = {str(p.relative_to(API)): lines for p, src in _production_sources().items()
                 if p != DOOR and (lines := _uses_factor_api(src))}
    assert not offenders, f"the sign-in service's factor API is called outside core/auth_admin.py: {offenders}"


def test_the_scan_has_something_to_scan():
    assert _uses_factor_api(DOOR.read_text(encoding="utf-8")), "the one door no longer calls the factor API: the scan is vacuous"
    assert len(_production_sources()) > 100


def test_negative_control_a_second_caller_is_found():
    assert _uses_factor_api("client.auth.admin.mfa.delete_factor({})\n") == [1, 1]  # the method and the .admin.mfa access
    assert _uses_factor_api("m = client.auth.admin.mfa\n") == [1]
    assert _uses_factor_api("x = svc.list_factors(u)\n") == [1]
    assert _uses_factor_api("x = svc.something_else(u)\n") == []
    assert _uses_factor_api('admin._request("GET", f"admin/users/{u}/factors")\n') == [1]
    assert _uses_factor_api('admin._request("DELETE", "admin/users/u/factors/f")\n') == [1]
    assert _uses_factor_api('admin._request("GET", "admin/users/u")\n') == [], "the user record is not the factor API"


# ── one spelling in the browser ───────────────────────────────────────────────────────────────────────

def test_the_browsers_request_type_is_the_servers():
    ts = (WEB / "lib" / "auth" / "authenticatorReset.ts").read_text(encoding="utf-8")
    spelled = re.search(r'AUTHENTICATOR_RESET\s*=\s*"([a-z_]+)"', ts)
    assert spelled, "the browser no longer names the request type in one constant"
    assert spelled.group(1) == mfa.REQUEST_TYPE
    assert mfa.REQUEST_TYPE in REQUEST_TYPES


def test_no_screen_spells_the_request_type_itself():
    offenders = []
    for root in ("app", "components", "lib"):
        for p in (WEB / root).rglob("*"):
            if p.suffix not in {".ts", ".tsx"} or ".test." in p.name:
                continue
            if f'"{mfa.REQUEST_TYPE}"' in p.read_text(encoding="utf-8") and p.name != "authenticatorReset.ts":
                offenders.append(str(p.relative_to(WEB)))
    assert not offenders, f"a screen names the request type itself instead of importing AUTHENTICATOR_RESET: {offenders}"


# ── the Approvals screen asks before it removes a second factor ────────────────────────────────────────

def _approvals_page() -> str:
    return (WEB / "app" / "approvals" / "page.tsx").read_text(encoding="utf-8")


def test_the_approvals_screen_asks_a_partner_before_a_reset_is_approved():
    page = _approvals_page()
    act = page[page.index("async function act("):]
    act = act[:act.index("setBusy(id)")]
    assert "AUTHENTICATOR_RESET" in act and "confirmDialog(" in act, \
        "approving a reset must be confirmed before anything is sent"
    assert "danger: true" in act, "removing somebody's second factor is a destructive act and is styled as one"
    assert "if (!ok) return;" in act, "a 'no' must leave the request exactly as it was"
    assert "approve" in act.split("confirmDialog(")[0], "the question is asked for an approval, not for a reject"


def test_a_reason_a_person_typed_is_shown_only_for_the_type_whose_screen_wrote_it():
    page = _approvals_page()
    shown = page[page.index("Reason given:") - 200:page.index("Reason given:")]
    assert "AUTHENTICATOR_RESET" in shown, "another request type's free text would be shown as a reason a Partner can trust"


def test_the_screen_says_how_the_asker_signed_in():
    page = _approvals_page()
    assert "askedWithText(" in page and "asker_aal" in page


def test_negative_control_the_page_scan_fails_when_the_question_is_removed():
    page = _approvals_page()
    stripped = page.replace("confirmDialog(", "noQuestion(")
    act = stripped[stripped.index("async function act("):]
    act = act[:act.index("setBusy(id)")]
    assert "confirmDialog(" not in act


# ── which approvals routes sit behind the second factor ───────────────────────────────────────────────

def _guarded(route) -> bool:
    return any(d.call is mfa_guard for d in route.dependant.dependencies)


def _route(path_end: str, method: str):
    return next(r for r in approvals_router.routes
                if r.path.endswith(path_end) and method in r.methods)


@pytest.mark.parametrize("path_end, method, guarded", [
    ("/approvals", "POST", False),            # a locked-out person is at the password level and must be able to ask
    ("/{request_id}/approve", "POST", True),  # the act that removes an authenticator needs the second factor
    ("/{request_id}/reject", "POST", True),
])
def test_the_second_factor_sits_on_the_deciding_routes_and_not_on_asking(path_end, method, guarded):
    assert _guarded(_route(path_end, method)) is guarded
