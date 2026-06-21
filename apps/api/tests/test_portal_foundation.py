"""
Phase 4.5.1 — Customer Portal Foundation tests (mock mode).

Covers the multi-contact access model: resolution (active / invited-binds /
deactivated-denied / legacy backward-compat / unknown), multi-user-per-client,
strict client isolation, the invite lifecycle (invite → activate → deactivate →
re-invite), audit logging, and the get_current_portal_client identity layer +
strict (no-staff-privilege) context.
"""
import pytest
from fastapi import HTTPException

import services.portal_access_service as pa
from core.portal_auth import get_current_portal_client

FIRM = "F1"
ACTOR = {"firm_id": FIRM, "auth_user_id": "staff-1", "email": "ca@firm.test"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    pa.reset_mock_stores()
    audit: list = []
    import services.audit_service as au
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audit.append((a, k)))
    # email is best-effort + no-ops without RESEND key, but stub to be safe/silent
    import services.email_service as es
    monkeypatch.setattr(es, "_send", lambda *a, **k: True)
    yield {"audit": audit}
    pa.reset_mock_stores()


# ── Resolution ───────────────────────────────────────────────────────────────

def test_invite_then_first_login_binds_and_activates(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    assert c["status"] == "invited" and not c.get("auth_user_id")
    # first login: resolve by email → binds auth_user_id + activates
    ctx = pa.resolve_portal_client("uid-A", "a@c.test")
    assert ctx is not None
    assert ctx["client_id"] == "CL-1" and ctx["firm_id"] == FIRM
    assert ctx["contact_id"] == c["id"] and ctx["legacy"] is False
    bound = pa.MOCK_PORTAL_CONTACTS[0]
    assert bound["auth_user_id"] == "uid-A" and bound["status"] == "active" and bound["activated_at"]
    # subsequent login resolves directly by auth_user_id
    assert pa.resolve_portal_client("uid-A", "a@c.test")["client_id"] == "CL-1"


def test_deactivated_contact_is_denied(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.resolve_portal_client("uid-A", "a@c.test")          # activate
    pa.deactivate_contact(FIRM, c["id"], actor=ACTOR)
    assert pa.resolve_portal_client("uid-A", "a@c.test") is None   # no access via uid
    assert pa.resolve_portal_client("uid-A", None) is None


def test_legacy_portal_user_id_still_resolves(_isolate):
    # Backward compatibility: the legacy single-user link keeps working.
    pa.MOCK_LEGACY_PORTAL["legacy-uid"] = {"client_id": "CL-9", "firm_id": FIRM}
    ctx = pa.resolve_portal_client("legacy-uid", "old@c.test")
    assert ctx["client_id"] == "CL-9" and ctx["legacy"] is True and ctx["contact_id"] is None


def test_unknown_identity_resolves_to_none(_isolate):
    assert pa.resolve_portal_client("nobody", "nobody@x.test") is None


# ── Multi-user per client + isolation ────────────────────────────────────────

def test_multiple_contacts_per_client(_isolate):
    pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.invite_contact(FIRM, "CL-1", "b@c.test", "Bob", actor=ACTOR)
    a = pa.resolve_portal_client("uid-A", "a@c.test")
    b = pa.resolve_portal_client("uid-B", "b@c.test")
    assert a["client_id"] == "CL-1" and b["client_id"] == "CL-1"
    assert a["contact_id"] != b["contact_id"]              # distinct contacts, same client
    assert len(pa.list_contacts(FIRM, "CL-1")) == 2


def test_client_isolation_between_contacts(_isolate):
    pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.invite_contact(FIRM, "CL-2", "b@c.test", "Bob", actor=ACTOR)
    assert pa.resolve_portal_client("uid-A", "a@c.test")["client_id"] == "CL-1"
    assert pa.resolve_portal_client("uid-B", "b@c.test")["client_id"] == "CL-2"
    # A's identity can never resolve to CL-2
    assert pa.resolve_portal_client("uid-A", "a@c.test")["client_id"] != "CL-2"


# ── Invite lifecycle + audit ─────────────────────────────────────────────────

def test_invite_is_idempotent_per_email(_isolate):
    c1 = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-1", "A@c.test", "Alice R", actor=ACTOR)  # case-insensitive same email
    assert c1["id"] == c2["id"] and len(pa.list_contacts(FIRM, "CL-1")) == 1


def test_reinvite_after_deactivate_reactivates(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.deactivate_contact(FIRM, c["id"], actor=ACTOR)
    again = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    assert again["id"] == c["id"] and again["status"] == "invited" and again["deactivated_at"] is None
    assert pa.resolve_portal_client("uid-A", "a@c.test")["client_id"] == "CL-1"   # can bind again


def test_resend_requires_existing_and_not_deactivated(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    out = pa.resend_invite(FIRM, c["id"], actor=ACTOR)
    assert out["id"] == c["id"]
    with pytest.raises(HTTPException) as ei:
        pa.resend_invite(FIRM, "missing", actor=ACTOR)
    assert ei.value.status_code == 404


def test_mutations_are_audited(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.deactivate_contact(FIRM, c["id"], actor=ACTOR)
    actions = [a[0][3] for a in _isolate["audit"]]
    assert "portal_invite" in actions and "portal_deactivate" in actions


def test_cross_firm_contact_not_found(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    with pytest.raises(HTTPException) as ei:
        pa.deactivate_contact("OTHER_FIRM", c["id"], actor=ACTOR)
    assert ei.value.status_code == 404


# ── Identity layer (get_current_portal_client) ───────────────────────────────

def test_identity_layer_returns_strict_context(_isolate):
    pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    ctx = get_current_portal_client(jwt_user={"auth_user_id": "uid-A", "email": "a@c.test"})
    assert ctx["portal"] is True and ctx["client_id"] == "CL-1" and ctx["role"] == "PortalClient"
    # strict: no firm-staff fields / no RBAC permission surface leaked
    assert "auth_user_id" not in ctx and "access_token" not in ctx and "aal" not in ctx


def test_identity_layer_rejects_non_portal_user(_isolate):
    with pytest.raises(HTTPException) as ei:
        get_current_portal_client(jwt_user={"auth_user_id": "nobody", "email": "nobody@x.test"})
    assert ei.value.status_code == 403
