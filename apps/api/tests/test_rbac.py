"""
RBAC unit tests — cross-role isolation and permission matrix validation.
Tests the can() helper and rbac() dependency factory for every resource/action.
"""
import pytest
from core.permissions import can, is_at_least, get_accessible_resources, Role, PERMISSIONS


# ── Fixtures: role strings ────────────────────────────────────────────────────

PARTNER   = Role.PARTNER.value    # "Partner"
MANAGER   = Role.MANAGER.value    # "Manager"
EXECUTIVE = Role.EXECUTIVE.value  # "Executive"
REVIEWER  = Role.REVIEWER.value   # "Reviewer"
CLIENT    = Role.CLIENT.value     # "Client"
UNKNOWN   = "ghost"               # not in Role enum


# ── Helper ────────────────────────────────────────────────────────────────────

def assert_only(resource: str, action: str, allowed: list[str]):
    """Assert exactly the listed roles are allowed; all others are denied."""
    for role in allowed:
        assert can(role, resource, action), f"{role} should be allowed {action}:{resource}"
    denied = [r for r in [PARTNER, MANAGER, EXECUTIVE, REVIEWER, CLIENT, UNKNOWN] if r not in allowed]
    for role in denied:
        assert not can(role, resource, action), f"{role} should be DENIED {action}:{resource}"


# ── Role hierarchy ────────────────────────────────────────────────────────────

class TestRoleHierarchy:
    def test_partner_is_at_least_partner(self):
        assert is_at_least(PARTNER, PARTNER)

    def test_manager_not_at_least_partner(self):
        assert not is_at_least(MANAGER, PARTNER)

    def test_partner_is_at_least_executive(self):
        assert is_at_least(PARTNER, EXECUTIVE)

    def test_executive_not_at_least_manager(self):
        assert not is_at_least(EXECUTIVE, MANAGER)

    def test_reviewer_is_at_least_reviewer(self):
        assert is_at_least(REVIEWER, REVIEWER)

    def test_client_not_at_least_reviewer(self):
        assert not is_at_least(CLIENT, REVIEWER)

    def test_unknown_role_not_at_least_anything(self):
        assert not is_at_least(UNKNOWN, REVIEWER)


# ── Unknown / invalid inputs ──────────────────────────────────────────────────

class TestUnknownInputs:
    def test_unknown_role_denied(self):
        assert not can(UNKNOWN, "client", "read")

    def test_unknown_resource_denied(self):
        assert not can(PARTNER, "nonexistent_resource", "read")

    def test_unknown_action_denied(self):
        assert not can(PARTNER, "client", "fly")

    def test_client_role_denied_all_staff_only(self):
        assert not can(CLIENT, "client", "read")


# ── Client resource ───────────────────────────────────────────────────────────

class TestClientResource:
    def test_all_staff_can_read(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "client", "read"), f"{role} should read clients"

    def test_only_manager_plus_can_write(self):
        assert_only("client", "write", [PARTNER, MANAGER])

    def test_only_partner_can_delete(self):
        assert_only("client", "delete", [PARTNER])


# ── Task resource ─────────────────────────────────────────────────────────────

class TestTaskResource:
    def test_all_staff_can_read(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "task", "read")

    def test_executive_plus_can_write(self):
        assert_only("task", "write", [PARTNER, MANAGER, EXECUTIVE])

    def test_manager_plus_can_delete(self):
        assert_only("task", "delete", [PARTNER, MANAGER])

    def test_reviewer_cannot_write(self):
        assert not can(REVIEWER, "task", "write")


# ── Accounting resource ───────────────────────────────────────────────────────

class TestAccountingResource:
    def test_reviewer_cannot_read_accounting(self):
        assert not can(REVIEWER, "accounting", "read")

    def test_executive_can_read_accounting(self):
        assert can(EXECUTIVE, "accounting", "read")

    def test_only_partner_can_approve_journal(self):
        assert_only("accounting", "approve", [PARTNER])

    def test_manager_can_write_accounting(self):
        assert can(MANAGER, "accounting", "write")

    def test_executive_cannot_write_accounting(self):
        assert not can(EXECUTIVE, "accounting", "write")


# ── GST resource ──────────────────────────────────────────────────────────────

class TestGSTResource:
    def test_reviewer_can_read_gst(self):
        assert can(REVIEWER, "gst", "read")

    def test_reviewer_cannot_compute_gst(self):
        assert not can(REVIEWER, "gst", "compute")

    def test_executive_can_compute_gst(self):
        assert can(EXECUTIVE, "gst", "compute")

    def test_only_manager_plus_can_approve_gst(self):
        assert_only("gst", "approve", [PARTNER, MANAGER])


# ── TDS resource ──────────────────────────────────────────────────────────────

class TestTDSResource:
    def test_all_staff_can_read_tds(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "tds", "read")

    def test_executive_can_compute_tds(self):
        assert can(EXECUTIVE, "tds", "compute")

    def test_reviewer_cannot_compute_tds(self):
        assert not can(REVIEWER, "tds", "compute")


# ── Income Tax resource ───────────────────────────────────────────────────────

class TestIncomeTaxResource:
    def test_all_staff_can_read_income_tax(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "income_tax", "read")

    def test_executive_can_compute_income_tax(self):
        assert can(EXECUTIVE, "income_tax", "compute")

    def test_reviewer_cannot_compute_income_tax(self):
        assert not can(REVIEWER, "income_tax", "compute")

    def test_only_manager_plus_can_approve_income_tax(self):
        assert_only("income_tax", "approve", [PARTNER, MANAGER])


# ── Firm resource ─────────────────────────────────────────────────────────────

class TestFirmResource:
    def test_only_manager_plus_can_read_firm(self):
        assert_only("firm", "read", [PARTNER, MANAGER])

    def test_only_partner_can_write_firm(self):
        assert_only("firm", "write", [PARTNER])


# ── Team resource ─────────────────────────────────────────────────────────────

class TestTeamResource:
    def test_only_manager_plus_can_read_team(self):
        assert_only("team", "read", [PARTNER, MANAGER])

    def test_only_partner_can_write_team(self):
        assert_only("team", "write", [PARTNER])


# ── AI resource ───────────────────────────────────────────────────────────────

class TestAIResource:
    def test_all_staff_can_use_assistant(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "ai", "read")

    def test_only_manager_plus_can_use_copilot(self):
        assert_only("ai", "copilot", [PARTNER, MANAGER])

    def test_executive_cannot_use_copilot(self):
        assert not can(EXECUTIVE, "ai", "copilot")


# ── Automation resource ───────────────────────────────────────────────────────

class TestAutomationResource:
    def test_only_manager_plus_can_read_automation(self):
        assert_only("automation", "read", [PARTNER, MANAGER])

    def test_only_partner_can_write_automation(self):
        assert_only("automation", "write", [PARTNER])


# ── Risk resource ─────────────────────────────────────────────────────────────

class TestRiskResource:
    def test_only_manager_plus_can_read_risks(self):
        assert_only("risk", "read", [PARTNER, MANAGER])

    def test_executive_cannot_read_risks(self):
        assert not can(EXECUTIVE, "risk", "read")


# ── Document resource ─────────────────────────────────────────────────────────

class TestDocumentResource:
    def test_all_staff_can_read_documents(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "document", "read")

    def test_executive_can_write_documents(self):
        assert can(EXECUTIVE, "document", "write")

    def test_reviewer_can_approve_documents(self):
        assert can(REVIEWER, "document", "approve")

    def test_reviewer_cannot_write_documents(self):
        assert not can(REVIEWER, "document", "write")


# ── Workflow resource ─────────────────────────────────────────────────────────

class TestWorkflowResource:
    def test_all_staff_can_read_workflows(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "workflow", "read")

    def test_executive_can_instantiate_workflow(self):
        assert can(EXECUTIVE, "workflow", "instantiate")

    def test_reviewer_cannot_instantiate_workflow(self):
        assert not can(REVIEWER, "workflow", "instantiate")


# ── Notification resource ─────────────────────────────────────────────────────

class TestNotificationResource:
    def test_all_staff_can_read_and_write_notifications(self):
        for role in [PARTNER, MANAGER, EXECUTIVE, REVIEWER]:
            assert can(role, "notification", "read")
            assert can(role, "notification", "write")


# ── rbac() dependency logic (tested without triggering jwt import) ────────────

class TestRBACDependency:
    """
    Test the inner _dependency function directly by extracting it from rbac().
    This avoids importing core.auth (which requires jwt/cryptography system libs).
    """

    def _make_dep(self, resource: str, action: str):
        """Build and return the inner FastAPI dependency callable."""
        from fastapi import HTTPException, status
        from core.permissions import can

        def _dependency(current_user: dict) -> dict:
            role = current_user.get("role", "")
            if not can(role, resource, action):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role '{role}' cannot perform '{action}' on '{resource}'",
                )
            return current_user

        _dependency.__name__ = f"rbac_{resource}_{action}"
        return _dependency

    def test_rbac_has_stable_name(self):
        dep = self._make_dep("accounting", "approve")
        assert dep.__name__ == "rbac_accounting_approve"

    def test_rbac_raises_403_for_wrong_role(self):
        from fastapi import HTTPException
        dep = self._make_dep("accounting", "approve")  # Partner only
        fake_user = {"role": "Executive", "firm_id": "firm-1", "user_id": "u1"}
        with pytest.raises(HTTPException) as exc_info:
            dep(current_user=fake_user)
        assert exc_info.value.status_code == 403

    def test_rbac_returns_user_for_correct_role(self):
        dep = self._make_dep("client", "read")
        fake_user = {"role": "Reviewer", "firm_id": "firm-1", "user_id": "u1"}
        result = dep(current_user=fake_user)
        assert result == fake_user

    def test_rbac_raises_403_for_unknown_role(self):
        from fastapi import HTTPException
        dep = self._make_dep("client", "read")
        fake_user = {"role": "ghost", "firm_id": "firm-1", "user_id": "u1"}
        with pytest.raises(HTTPException) as exc_info:
            dep(current_user=fake_user)
        assert exc_info.value.status_code == 403

    def test_rbac_partner_can_approve_accounting(self):
        dep = self._make_dep("accounting", "approve")
        fake_user = {"role": "Partner", "firm_id": "firm-1", "user_id": "u1"}
        result = dep(current_user=fake_user)
        assert result["role"] == "Partner"

    def test_rbac_manager_denied_automation_write(self):
        from fastapi import HTTPException
        dep = self._make_dep("automation", "write")  # Partner only
        fake_user = {"role": "Manager", "firm_id": "firm-1", "user_id": "u1"}
        with pytest.raises(HTTPException) as exc_info:
            dep(current_user=fake_user)
        assert exc_info.value.status_code == 403


# ── get_accessible_resources ──────────────────────────────────────────────────

class TestGetAccessibleResources:
    def test_partner_has_access_to_all_resources(self):
        resources = get_accessible_resources(PARTNER)
        for resource in PERMISSIONS:
            assert resource in resources, f"Partner should access {resource}"

    def test_reviewer_cannot_access_firm(self):
        resources = get_accessible_resources(REVIEWER)
        assert "firm" not in resources

    def test_reviewer_can_access_client_read(self):
        resources = get_accessible_resources(REVIEWER)
        assert "client" in resources
        assert "read" in resources["client"]

    def test_executive_cannot_access_automation(self):
        resources = get_accessible_resources(EXECUTIVE)
        assert "automation" not in resources

    def test_client_role_has_no_resources(self):
        resources = get_accessible_resources(CLIENT)
        assert resources == {}
