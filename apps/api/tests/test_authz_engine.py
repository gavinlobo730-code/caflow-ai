"""
Module 9.0 / M2 — central authorization engine tests.

Covers all five roles × allowed/denied × assignment scope. The engine is
mock-permissive in dev (no DB), so these tests force the enforced path by
disabling mock mode and stubbing the assignment lookup.
"""
import pytest
from fastapi import HTTPException

import core.authz as authz

PARTNER = {"id": "u-p", "firm_id": "F1", "role": "Partner"}
MANAGER = {"id": "u-m", "firm_id": "F1", "role": "Manager"}
EXECUTIVE = {"id": "u-e", "firm_id": "F1", "role": "Executive"}
REVIEWER = {"id": "u-r", "firm_id": "F1", "role": "Reviewer"}
CLIENT = {"id": "u-c", "firm_id": "F1", "role": "Client"}


@pytest.fixture
def enforced(monkeypatch):
    """Force the real (non-mock) enforcement path with a fixed assignment set.
    Executive u-e is assigned to {C1}; everyone else has no assignments."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)

    def fake_assigned(user):
        return {"C1"} if user.get("id") == "u-e" else set()
    monkeypatch.setattr(authz, "assigned_client_ids", fake_assigned)


# ── Role tier ────────────────────────────────────────────────────────────────

def test_firmwide_roles():
    assert authz.is_firmwide(PARTNER) is True
    assert authz.is_firmwide(MANAGER) is True
    assert authz.is_firmwide(EXECUTIVE) is False
    assert authz.is_firmwide(REVIEWER) is False
    assert authz.is_firmwide(CLIENT) is False


# ── effective_client_ids ──────────────────────────────────────────────────────

def test_effective_ids_firmwide_is_none(enforced):
    assert authz.effective_client_ids(PARTNER) is None
    assert authz.effective_client_ids(MANAGER) is None


def test_effective_ids_assignment_scoped(enforced):
    assert authz.effective_client_ids(EXECUTIVE) == {"C1"}
    assert authz.effective_client_ids(REVIEWER) == set()


# ── can_access_client ──────────────────────────────────────────────────────────

def test_partner_manager_access_any_client(enforced):
    assert authz.can_access_client(PARTNER, "C9") is True
    assert authz.can_access_client(MANAGER, "C9") is True


def test_executive_only_assigned(enforced):
    assert authz.can_access_client(EXECUTIVE, "C1") is True
    assert authz.can_access_client(EXECUTIVE, "C2") is False


def test_reviewer_and_client_denied_unassigned(enforced):
    assert authz.can_access_client(REVIEWER, "C1") is False
    assert authz.can_access_client(CLIENT, "C1") is False


def test_no_client_scope_is_allowed(enforced):
    # Firm-level resource (no client_id) is not gated by assignment.
    assert authz.can_access_client(EXECUTIVE, None) is True


def test_assert_client_access_raises_404(enforced):
    authz.assert_client_access(EXECUTIVE, "C1")  # no raise
    with pytest.raises(HTTPException) as ei:
        authz.assert_client_access(EXECUTIVE, "C2")
    assert ei.value.status_code == 404


# ── authorize() combines RBAC + scope ──────────────────────────────────────────

def test_authorize_rbac_then_scope(enforced):
    # Executive may read clients (RBAC) but only assigned ones (scope).
    assert authz.authorize(EXECUTIVE, "client", "read", client_id="C1") is True
    assert authz.authorize(EXECUTIVE, "client", "read", client_id="C2") is False
    # Executive cannot delete a client at all (RBAC denies regardless of scope).
    assert authz.authorize(EXECUTIVE, "client", "delete", client_id="C1") is False
    # Partner can delete (RBAC) any client (firm-wide scope).
    assert authz.authorize(PARTNER, "client", "delete", client_id="C9") is True


def test_authorize_denies_unknown_role(enforced):
    assert authz.authorize({"id": "x", "role": "Wizard"}, "client", "read") is False


def test_mock_mode_is_permissive(monkeypatch):
    # In dev/test (mock) mode, assignment checks are permissive (no DB).
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    assert authz.can_access_client(EXECUTIVE, "anything") is True
    assert authz.effective_client_ids(EXECUTIVE) is None


def test_filter_by_client(enforced):
    rows = [{"client_id": "C1"}, {"client_id": "C2"}, {"client_id": None}]
    # Executive sees only C1 rows + firm-level (client_id None) rows.
    out = authz.filter_by_client(EXECUTIVE, rows)
    assert {r.get("client_id") for r in out} == {"C1", None}
    # Partner sees everything.
    assert authz.filter_by_client(PARTNER, rows) == rows
