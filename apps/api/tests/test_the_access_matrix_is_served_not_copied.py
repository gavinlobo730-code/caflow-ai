"""
GET /api/identity/role-matrix — what every role can reach.

A DEFECT WITH NO FINDING, found by sweeping for localStorage rather than for
the instance (ACC-06's own sweep).

`apps/web/app/team/page.tsx` rendered a "Module Access Matrix" headed
"Toggle access per member per module. Changes are saved instantly. Overrides
the role default for that individual." Every clause of that was false:

  * the toggles wrote a member→module→boolean map into
    localStorage["practicesync_permissions_<firm>"], so they reached no other
    user, no other device and no server;
  * `core/permissions.py` has no per-member override concept, so nothing could
    have honoured them even if they had been stored;
  * `rbac()` decides every request from the ROLE alone.

A Partner who unticked Payroll for an Executive believed they had removed
access. They had not, anywhere.

The screen also carried its own ROLE_DEFAULTS — "mirrors permissions.ts logic"
said the comment — and it had drifted in the direction that matters most: it
showed an Executive as reaching Clients and Tasks only, when PERMISSIONS grants
them accounting, gst, income_tax, mca, report and tds besides. The drift tests
below are the ones worth keeping: they fail if the served matrix ever stops
matching PERMISSIONS, which is the only thing that makes serving it better than
copying it.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.permissions import PERMISSIONS, Role, get_accessible_resources

#: The eleven modules the Team screen names, and the backend resource each IS.
#: Mirrored from apps/web/app/team/page.tsx — the LABELS are the screen's, the
#: resources are this module's, and the mapping is what makes the two agree.
SCREEN_MODULES = {
    "Accounting": "accounting", "GST": "gst", "Income Tax": "income_tax",
    "TDS": "tds", "MCA": "mca", "Payroll": "payroll", "Billing": "billing",
    "Reports": "report", "Settings": "settings", "Clients": "client",
    "Tasks": "task",
}


def _client(role: str = "Partner"):
    import routers.identity as identity_mod
    app = FastAPI()
    app.include_router(identity_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": role, "email": "p@f1.test"}
    return TestClient(app, raise_server_exceptions=False)


def _matrix(role: str = "Partner") -> dict:
    r = _client(role).get("/api/identity/role-matrix")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    return body["data"]


def test_it_answers_for_every_role_the_product_has():
    d = _matrix()
    assert d["roles"] == [r.value for r in Role]
    assert set(d["matrix"]) == {r.value for r in Role}


def test_every_answer_IS_get_accessible_resources():
    """Served, not copied — so there is one matrix and it cannot drift."""
    d = _matrix()
    for role in Role:
        assert d["matrix"][role.value] == get_accessible_resources(role.value)


def test_the_roles_come_back_most_privileged_first():
    """A screen rendering columns in this order must not have to know the
    hierarchy itself."""
    assert _matrix()["roles"][0] == "Partner"
    assert _matrix()["roles"][-1] == "Client"


# ── The drift the browser copy had ───────────────────────────────────────────

def test_an_executive_reaches_far_more_than_clients_and_tasks():
    """The browser copy said Clients and Tasks only. This is what a Partner was
    being told about their own staff's access."""
    m = _matrix()["matrix"]["Executive"]
    for resource in ("accounting", "gst", "income_tax", "mca", "report", "tds"):
        assert m.get(resource), f"Executive has no {resource} in PERMISSIONS"


def test_a_manager_has_reports_and_settings_and_no_billing():
    """Three more the browser copy had backwards, in both directions."""
    m = _matrix()["matrix"]["Manager"]
    assert m.get("report")
    assert m.get("settings")
    assert not m.get("billing")


def test_a_reviewer_reaches_more_than_two_modules():
    m = _matrix()["matrix"]["Reviewer"]
    reached = [mod for mod, res in SCREEN_MODULES.items() if m.get(res)]
    assert len(reached) > 2, reached


@pytest.mark.parametrize("module,resource", sorted(SCREEN_MODULES.items()))
def test_every_module_the_screen_names_is_a_real_resource(module, resource):
    """A label pointing at a resource PERMISSIONS does not have renders as an
    empty column for every role — a false statement that nobody can reach it."""
    assert resource in PERMISSIONS, f"{module} maps to {resource!r}, which is not a resource"


# ── Scope ────────────────────────────────────────────────────────────────────

def test_it_is_guarded_and_not_a_security_boundary():
    """`rbac("team", "read")` gates it, and the docstring says plainly that
    rbac() on each endpoint is still the only thing that decides anything.
    Serving the matrix decides what is worth RENDERING."""
    import inspect
    import routers.identity as identity_mod
    src = inspect.getsource(identity_mod.role_matrix)
    assert 'rbac("team", "read")' in src
    assert "NOT A SECURITY BOUNDARY" in src


def test_a_role_that_reaches_nothing_still_appears():
    """A missing key and a role with no access are different facts, and a
    screen rendering the first as the second says something untrue."""
    d = _matrix()
    assert "Client" in d["matrix"]
    assert isinstance(d["matrix"]["Client"], dict)


def test_the_browser_no_longer_holds_its_own_copy():
    """Pinned from the side that owns the matrix. A guard written in apps/web
    would assert the engine against a copy of itself and pass whenever both
    drifted together — which is exactly what ROLE_DEFAULTS did."""
    import pathlib
    team = (pathlib.Path(__file__).resolve().parents[2]
            / "web" / "app" / "team" / "page.tsx").read_text(encoding="utf-8")
    assert "const ROLE_DEFAULTS" not in team
    assert "api.identity.roleMatrix()" in team
    # And it must not be writing permissions to the browser any more.
    assert "localStorage.setItem" not in team
    assert "localStorage.getItem" not in team
