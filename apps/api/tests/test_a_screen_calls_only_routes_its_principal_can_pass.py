"""A screen may only call a route the person looking at it can get through
(payroll-01).

WHAT WAS WRONG
    The employee portal's Download payslip button called
    `GET /api/payroll/salary-slips/{id}/pdf`. That route is
    `rbac("payroll", "read")` — a STAFF principal with a `users` row — and an
    employee has none (CLAUDE.md, "THERE ARE THREE PRINCIPALS"), so `core.auth`
    answered 403 "User not found in firm" to every employee for every payslip.

    Nothing noticed, because both reachability guards ask a different question:
    `test_a_finished_payroll_endpoint_is_reachable` and
    `test_every_mounted_endpoint_has_a_way_in` ask whether SOME screen writes the
    URL down, and this one did. The finding was right that they "match URL
    strings only and could not see this": an endpoint can be reached by a
    screen, satisfy both guards and still be unpassable by the very person the
    screen was built for. `docs/audits/findings-status.json` PAY-29 had marked
    the feature reachable on the strength of the link alone.

THE RULE
    For every screen written FOR one principal, every `/api/` route it calls is
    either open to that principal or to any authenticated identity, or to
    everybody. A route that requires a different principal is a defect in the
    SCREEN, whatever the route itself is right to require.

WHAT "A PRINCIPAL" IS HERE
    Read off the route's own dependency tree, never a list of paths:

      * `core.auth.get_current_user` anywhere in it — STAFF (`rbac()` hangs
        off it, so every `rbac(...)` route is staff);
      * `core.portal_auth.get_current_portal_client` — the CLIENT principal;
      * `core.portal_auth.get_current_portal_employee` — the EMPLOYEE principal;
      * only `get_jwt_user` — any authenticated identity (the invite and
        activation doors are this, because the caller has no principal yet);
      * none of them — public.

WHAT IT DOES NOT SEE, and says so
    It matches PATHS, not (method, path) pairs — the looseness both guards above
    record — and a screen that builds its path from a variable is invisible to
    it. It reads `api.<namespace>.<member>` by resolving the member's first
    `/api/` literal in `lib/api/index.ts`, which is right for every member the
    portal uses and is asserted by a floor rather than trusted.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.auth import get_current_user, get_jwt_user
from core.portal_auth import get_current_portal_client, get_current_portal_employee
from main import app

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
API_CLIENT = WEB / "lib" / "api" / "index.ts"

STAFF, CLIENT, EMPLOYEE, AUTHENTICATED, PUBLIC = (
    "staff", "portal_client", "portal_employee", "authenticated", "public")

#: Screens written for ONE principal, by principal. A screen is listed because
#: a person of that kind is the only one who is ever shown it — the portals.
SCREENS: dict[str, list[str]] = {
    EMPLOYEE: [
        "app/portal/employee/page.tsx",
        "app/portal/employee/activate/page.tsx",
        "components/portal/TaxDeclarationTab.tsx",
        "components/portal/TdsProjectionTab.tsx",
    ],
    CLIENT: [
        "app/portal/dashboard/page.tsx",
        "app/portal/activate/page.tsx",
    ],
}


# ── What a route requires, read off its dependency tree ──────────────────────

def _calls(dependant) -> set:
    found = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            found.add(d.call)
        stack.extend(d.dependencies)
    return found


def principal_required(route) -> str:
    calls = _calls(route.dependant)
    if get_current_user in calls:
        return STAFF
    if get_current_portal_client in calls:
        return CLIENT
    if get_current_portal_employee in calls:
        return EMPLOYEE
    if get_jwt_user in calls:
        return AUTHENTICATED
    return PUBLIC


def admits(route, principal: str) -> bool:
    return principal_required(route) in (principal, AUTHENTICATED, PUBLIC)


# ── What a screen calls, read off its source ─────────────────────────────────

# A `${...}` interpolation is taken whole: `statement${qs ? "?" + qs : ""}`
# holds a `?` and quotes INSIDE the braces, and a scan that stops at the first
# one reads the path as `/api/portal/self/statement${qs`.
_LITERAL = re.compile(r"[\"'`](/api/(?:\$\{[^}]*\}|[^\"'`\s?$])*)")
_MEMBER_CALL = re.compile(r"\bapi\.(\w+)\.(\w+)\b")


def _without_comments(src: str) -> str:
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", ln) for ln in src.split("\n"))


_API_SRC = API_CLIENT.read_text(encoding="utf-8")


def _member_path(namespace: str, member: str) -> str | None:
    """The first `/api/` literal in `api.<namespace>.<member>`'s own body."""
    ns = re.search(rf"\n  {re.escape(namespace)}: \{{", _API_SRC)
    if not ns:
        return None
    start = _API_SRC.find(f"\n    {member}:", ns.end())
    if start < 0:
        return None
    nxt = re.search(r"\n    \w+:", _API_SRC[start + 1:])
    body = _API_SRC[start: start + 1 + (nxt.start() if nxt else 4000)]
    lit = _LITERAL.search(body)
    return lit.group(1) if lit else None


def paths_called_by(src: str) -> set[str]:
    code = _without_comments(src)
    out = {m.group(1) for m in _LITERAL.finditer(code)}
    for ns, member in _MEMBER_CALL.findall(code):
        path = _member_path(ns, member)
        if path:
            out.add(path)
    normalised = {re.sub(r"\$\{[^}]*\}", "{}", p) for p in out}
    # An interpolation glued to the end of a segment is a query string or a
    # suffix (`/statement${qs}`), not a path segment of its own.
    return {re.sub(r"(?<=[^/])\{\}$", "", p) for p in normalised}


def routes_for(path: str) -> list:
    """Every mounted route whose path this literal could be."""
    concrete = path.replace("{}", "X").rstrip("/")
    hits = []
    for route in app.routes:
        rp = getattr(route, "path", None)
        if not rp or not hasattr(route, "dependant"):
            continue
        pattern = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(rp.rstrip("/"))) + "$"
        if re.match(pattern, concrete):
            hits.append(route)
    return hits


def _calls_of(screen: str) -> list[str]:
    return sorted(paths_called_by((WEB / screen).read_text(encoding="utf-8")))


CASES = [(principal, screen, path)
         for principal, screens in SCREENS.items()
         for screen in screens
         for path in _calls_of(screen)]


# ── The rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("principal,screen,path", CASES,
                         ids=[f"{p}:{Path(s).name}:{u}" for p, s, u in CASES])
def test_a_screen_calls_only_routes_its_principal_can_pass(principal, screen, path):
    routes = routes_for(path)
    if not routes:
        pytest.skip(f"{path} names no mounted route (another guard's question)")
    assert any(admits(r, principal) for r in routes), (
        f"{screen} is shown to a {principal} and calls {path}, which requires "
        f"{sorted({principal_required(r) for r in routes})}. A {principal} cannot "
        f"pass it, so the control on that screen fails for exactly the person it "
        f"was built for. Give the {principal} its own route (see "
        f"routers/portal_employee.py) — do not loosen the route's own guard.")


# ── The guard is not vacuous ─────────────────────────────────────────────────

def test_every_listed_screen_exists_and_was_read():
    for screens in SCREENS.values():
        for screen in screens:
            assert (WEB / screen).is_file(), f"{screen} moved — restate the list"


def test_the_employee_portals_calls_were_actually_found():
    """A floor: a resolver that found nothing would pass every case above."""
    found = set().union(*(paths_called_by((WEB / s).read_text(encoding="utf-8"))
                          for s in SCREENS[EMPLOYEE]))
    assert any("/api/portal/employee/tds-projection" in p for p in found), found
    assert any("payslips" in p and p.endswith("/pdf") for p in found), found


def test_the_client_portals_calls_were_actually_found():
    found = set().union(*(paths_called_by((WEB / s).read_text(encoding="utf-8"))
                          for s in SCREENS[CLIENT]))
    assert any(p.startswith("/api/portal/self/") for p in found), found


def test_the_classifier_tells_the_three_principals_apart():
    staff = routes_for("/api/payroll/salary-slips/{}/pdf")
    employee = routes_for("/api/portal/employee/tds-projection")
    client = routes_for("/api/portal/self/dues")
    assert staff and employee and client
    assert {principal_required(r) for r in staff} == {STAFF}
    assert {principal_required(r) for r in employee} == {EMPLOYEE}
    assert {principal_required(r) for r in client} == {CLIENT}
    assert not any(admits(r, EMPLOYEE) for r in staff)
    assert not any(admits(r, CLIENT) for r in employee)


def test_the_rule_would_have_caught_the_original_defect():
    """The exact call the employee page used to make, through the same rule."""
    old = "await api.payroll.downloadPayslip(slip.id, `payslip-${period}.pdf`);"
    paths = paths_called_by(old)
    assert any(p.startswith("/api/payroll/salary-slips/") for p in paths), paths
    routes = [r for p in paths for r in routes_for(p)]
    assert routes and not any(admits(r, EMPLOYEE) for r in routes)
