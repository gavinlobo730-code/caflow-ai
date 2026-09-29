"""`POST /api/portal/employee/activation-session` is reachable with NO session
at all — that is the whole point of it — and this proves both halves: the
router wires no auth dependency onto it, and calling it end to end (through
the router function, not just the domain layer — see
test_new_payroll_endpoints_are_callable.py for why that distinction matters)
actually returns something the frontend can redeem.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import Depends

import routers.portal_self as portal_self
import services.employee_portal_service as eps


def test_the_endpoint_takes_no_auth_dependency():
    """Every OTHER function in this router takes a Depends(...) principal —
    get_jwt_user, get_current_portal_client. This one deliberately does not:
    before it succeeds there is no session to depend ON. A Depends() added
    here later (by someone reflexively guarding an endpoint) would 401 every
    legitimate caller, since the whole reason this exists is that they have
    no session yet."""
    sig = inspect.signature(portal_self.mint_employee_activation_session)
    for name, param in sig.parameters.items():
        assert not isinstance(param.default, type(Depends())), (
            f"mint_employee_activation_session takes a Depends() on '{name}' — "
            f"this endpoint must be callable with no session at all"
        )


def test_the_sibling_accept_invite_endpoint_still_does(monkeypatch):
    """The contrast that makes the assertion above meaningful: accept-invite
    DOES require a JWT (any valid one — the token authorises the bind, the
    JWT says which identity to bind it to), so a Depends() being absent from
    mint_employee_activation_session is a deliberate asymmetry, not an
    oversight that happens to also be missing here."""
    sig = inspect.signature(portal_self.accept_employee_invite)
    found = [name for name, param in sig.parameters.items()
             if isinstance(param.default, type(Depends()))]
    assert found, "accept_employee_invite lost its auth dependency"


def test_calling_it_end_to_end_returns_something_the_browser_can_redeem(monkeypatch):
    """Through the ROUTER function, not employee_portal_service directly —
    a wiring mistake (a renamed field on the request body, say) is invisible
    to a test that only calls the service."""
    monkeypatch.setattr(eps, "_USE_MOCK", True)
    eps.reset_mock_stores()
    eps.MOCK_EMPLOYEES.append({
        "id": "emp-1", "firm_id": "f1", "client_id": "c1", "name": "Test Employee",
        "email": "employee@example.test", "auth_user_id": None,
        "portal_invite_token_hash": eps.token_hash("tok-1"),
        "portal_invite_expires_at": "2099-01-01T00:00:00+00:00",
    })
    body = portal_self.MintEmployeeActivationSessionBody(token="tok-1")
    resp = portal_self.mint_employee_activation_session(body)
    assert resp["success"] is True
    assert resp["data"]["token_hash"]
    assert resp["data"]["verification_type"]


def test_an_unknown_token_still_answers_the_generic_404(monkeypatch):
    monkeypatch.setattr(eps, "_USE_MOCK", True)
    eps.reset_mock_stores()
    from fastapi import HTTPException
    body = portal_self.MintEmployeeActivationSessionBody(token="not-a-real-token")
    with pytest.raises(HTTPException) as exc:
        portal_self.mint_employee_activation_session(body)
    assert exc.value.status_code == 404
