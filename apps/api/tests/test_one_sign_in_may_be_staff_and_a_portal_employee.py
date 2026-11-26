"""One sign-in may be both a member of staff and an employee on the payslip portal (POST-A-549, decided 22-11-2026).

WHAT WAS OPEN
    A practice that runs its own payroll here invites its own staff to the payslip portal at the address they already sign in
    with. Nothing decided whether that one sign-in may be both, and nothing tested it. Each door reads its own principal off the
    sign-in (a `users` row for staff, a `payroll_employees` row for the portal), so nothing is widened by allowing it; what was
    wrong in practice is that the activation page asked such a person to "set a password", which replaces the password they sign
    in to the practice with.

WHAT IS ASSERTED
    * accepting an invitation answers `staff_sign_in`: True when the caller's own sign-in is linked to a member of staff, False
      when it is not, read from the VERIFIED sign-in and never from the request;
    * a read that fails answers False and is reported, and the invitation is still accepted (the page then offers the password
      step, which is what it always did);
    * the two doors stay two: the employee door resolves its principal from `payroll_employees` by the sign-in's id and carries
      no staff role, and the staff permission table has no entry for it;
    * the activation page asks the answer before it offers the password step, and the staff menu asks the server whether the
      caller is a portal employee only when the menu is opened.
"""
from __future__ import annotations

import pathlib

import pytest

import routers.portal_self as portal_self
import services.employee_portal_service as eps
from core.permissions import PERMISSIONS

API = pathlib.Path(__file__).resolve().parents[1]
WEB = API.parent / "web"
ACTIVATION_PAGE = WEB / "app" / "portal" / "employee" / "activate" / "page.tsx"      # apps/web/app/portal/employee/activate/page.tsx
STAFF_MENU = WEB / "components" / "shell" / "UtilityCluster.tsx"                     # apps/web/components/shell/UtilityCluster.tsx

JWT = {"auth_user_id": "auth-asha", "email": "asha@acme-traders.com"}


@pytest.fixture
def a_pending_invitation(monkeypatch):
    monkeypatch.setattr(eps, "_USE_MOCK", True)
    eps.reset_mock_stores()
    eps.MOCK_EMPLOYEES.append({
        "id": "emp-1", "firm_id": "f1", "client_id": "c1", "name": "Asha", "email": JWT["email"], "auth_user_id": None,
        "portal_invite_token_hash": eps.stored_form("tok-1"), "portal_invite_expires_at": "2099-01-01T00:00:00+00:00"})
    yield
    eps.reset_mock_stores()


def _accept():
    return portal_self.accept_employee_invite(portal_self.AcceptEmployeeInviteBody(token="tok-1"), jwt_user=dict(JWT))


def test_a_member_of_staff_who_accepts_is_answered_as_one(monkeypatch, a_pending_invitation):
    from repositories.user_repository import user_repo
    asked = []
    monkeypatch.setattr(user_repo, "find_linked_member", lambda auth_id: asked.append(auth_id) or {"id": "u-1", "firm_id": "f1"})
    answer = _accept()
    assert answer["success"] is True and answer["data"]["staff_sign_in"] is True
    assert asked == ["auth-asha"], "the staff link was read for something other than the caller's own verified sign-in"
    assert eps.MOCK_EMPLOYEES[0]["auth_user_id"] == "auth-asha" and eps.MOCK_EMPLOYEES[0]["portal_enabled"] is True


def test_somebody_who_is_not_staff_is_answered_as_not(monkeypatch, a_pending_invitation):
    from repositories.user_repository import user_repo
    monkeypatch.setattr(user_repo, "find_linked_member", lambda auth_id: None)
    assert _accept()["data"]["staff_sign_in"] is False


def test_a_read_that_fails_is_reported_and_the_invitation_is_still_accepted(monkeypatch, a_pending_invitation):
    from repositories.user_repository import user_repo
    import core.observability as observability
    reported = []

    def boom(auth_id):
        raise RuntimeError("the staff table could not be read")
    monkeypatch.setattr(user_repo, "find_linked_member", boom)
    monkeypatch.setattr(observability, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw.get("operation"))))
    answer = _accept()
    assert answer["data"]["staff_sign_in"] is False
    assert reported == [("the staff table could not be read", "employee_portal.staff_sign_in_read")]
    assert eps.MOCK_EMPLOYEES[0]["auth_user_id"] == "auth-asha", "a failed read of the staff link undid the acceptance"


def test_the_request_cannot_say_it_is_staff():
    """The body is the token and nothing else, so no field of the request can claim or deny a staff sign-in."""
    assert set(portal_self.AcceptEmployeeInviteBody.model_fields) == {"token"}


def test_the_two_doors_stay_two():
    """The employee principal is resolved from `payroll_employees` by the sign-in's id and is no staff role: the permission
    table has nothing for it, so `rbac()` refuses it everywhere, whoever else the same sign-in is."""
    source = (API / "core" / "portal_auth.py").read_text(encoding="utf-8")
    door = source[source.index("def get_current_portal_employee"):]
    assert '.table("payroll_employees")' in door and '.eq("auth_user_id", auth_user_id)' in door
    assert '"role": "PortalEmployee"' in door
    for resource, actions in PERMISSIONS.items():
        for action, roles in actions.items():
            assert "PortalEmployee" not in {getattr(r, "value", r) for r in roles}, (resource, action)


def test_the_page_asks_before_it_offers_a_password_and_the_menu_asks_only_when_opened():
    page = ACTIVATION_PAGE.read_text(encoding="utf-8")
    assert 'setStage(accepted?.data?.staff_sign_in === true ? "linked" : "form")' in page
    # The linked step is the "all set" step with other words: it is reached straight from the acceptance, and nothing in it sets a
    # password (the password form is the `form` stage, which a staff sign-in never enters).
    step = page[page.index('if (stage === "done" || stage === "linked")'):page.index('if (stage === "reauth")')]
    assert "updateUser" not in step and 'type="password"' not in step and "<input" not in step, "the linked step still sets a password"
    assert "there is no new password to set" in step

    menu = STAFF_MENU.read_text(encoding="utf-8")
    assert "hasEmployeePortalAccess" in menu
    toggle = menu[menu.index("function toggleAvatarMenu()"):menu.index("const pathname")]
    assert "hasEmployeePortalAccess()" in toggle, "the menu asks somewhere other than when it is opened"
    assert menu.count("hasEmployeePortalAccess()") == 1, "the server is asked about the caller's payslips in more than one place"
    assert "useEffect" not in menu, "the menu asks on every screen, not when it is opened"
    assert 'href="/portal/employee"' in menu and "data-my-payslips" in menu
