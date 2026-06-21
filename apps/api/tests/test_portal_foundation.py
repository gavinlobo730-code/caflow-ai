"""
Phase 4.5.1 — Customer Portal Foundation tests (mock mode), incl. the multi-client
membership fix.

Covers: membership listing (one→one, one→many, mixed active/deactivated, legacy
backward-compat, unknown), explicit/deterministic active-client selection (single
auto, multiple requires header, non-member denied), the invite lifecycle, audit
logging, strict client/firm isolation, and the get_current_portal_client identity
layer (single, multi-with-header, multi-without-header 409, non-member 403).
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
    import services.email_service as es
    monkeypatch.setattr(es, "_send", lambda *a, **k: True)
    yield {"audit": audit}
    pa.reset_mock_stores()


def _ids(memberships):
    return sorted(m["client_id"] for m in memberships)


# ── Pure selection logic ─────────────────────────────────────────────────────

def test_select_active_membership_pure():
    f = pa.select_active_membership
    m1, m2 = {"client_id": "CL-1"}, {"client_id": "CL-2"}
    assert f([], None) == (None, False)
    assert f([m1], None) == (m1, False)               # single → auto
    assert f([m1, m2], None) == (None, True)           # multiple → must choose (no implicit)
    assert f([m1, m2], "CL-2") == (m2, False)          # explicit selection
    assert f([m1, m2], "CL-9") == (None, False)        # non-member → denied


# ── Membership listing ───────────────────────────────────────────────────────

def test_one_user_one_client(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    ms = pa.list_portal_memberships("uid-A", "a@c.test")     # first login binds + activates
    assert _ids(ms) == ["CL-1"]
    bound = pa.MOCK_PORTAL_CONTACTS[0]
    assert bound["auth_user_id"] == "uid-A" and bound["status"] == "active" and bound["activated_at"]
    assert ms[0]["contact_id"] == c["id"]


def test_one_user_multiple_clients_binds_all(_isolate):
    pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    ms = pa.list_portal_memberships("uid-O", "owner@co.test")
    assert _ids(ms) == ["CL-1", "CL-2"]                # both invites activated on first login
    # subsequent login resolves both directly by auth_user_id
    assert _ids(pa.list_portal_memberships("uid-O", "owner@co.test")) == ["CL-1", "CL-2"]


def test_mixed_active_and_deactivated_memberships(_isolate):
    pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    pa.list_portal_memberships("uid-O", "owner@co.test")     # activate both
    pa.deactivate_contact(FIRM, c2["id"], actor=ACTOR)       # revoke CL-2
    assert _ids(pa.list_portal_memberships("uid-O", "owner@co.test")) == ["CL-1"]


def test_legacy_portal_user_id_backward_compatible(_isolate):
    pa.MOCK_LEGACY_PORTAL["legacy-uid"] = {"client_id": "CL-9", "firm_id": FIRM}
    ms = pa.list_portal_memberships("legacy-uid", "old@c.test")
    assert _ids(ms) == ["CL-9"] and ms[0]["legacy"] is True and ms[0]["contact_id"] is None


def test_unknown_identity_has_no_memberships(_isolate):
    assert pa.list_portal_memberships("nobody", "nobody@x.test") == []


# ── Identity layer: deterministic, explicit active-client selection ──────────

def test_identity_single_membership_no_header(_isolate):
    pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    ctx = get_current_portal_client(jwt_user={"auth_user_id": "uid-A", "email": "a@c.test"},
                                    x_portal_client_id=None)
    assert ctx["portal"] is True and ctx["client_id"] == "CL-1" and ctx["role"] == "PortalClient"
    assert [m["client_id"] for m in ctx["memberships"]] == ["CL-1"]
    # strict: no staff fields leaked
    assert "auth_user_id" not in ctx and "access_token" not in ctx and "aal" not in ctx


def test_identity_multiple_requires_explicit_selection(_isolate):
    pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    jwt = {"auth_user_id": "uid-O", "email": "owner@co.test"}
    # no header → 409 (never implicit), available memberships returned
    with pytest.raises(HTTPException) as ei:
        get_current_portal_client(jwt_user=jwt, x_portal_client_id=None)
    assert ei.value.status_code == 409
    assert sorted(m["client_id"] for m in ei.value.detail["memberships"]) == ["CL-1", "CL-2"]
    # explicit header → that client; scope changes correctly
    assert get_current_portal_client(jwt_user=jwt, x_portal_client_id="CL-1")["client_id"] == "CL-1"
    assert get_current_portal_client(jwt_user=jwt, x_portal_client_id="CL-2")["client_id"] == "CL-2"


def test_identity_cannot_select_non_member_client(_isolate):
    pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    jwt = {"auth_user_id": "uid-O", "email": "owner@co.test"}
    with pytest.raises(HTTPException) as ei:
        get_current_portal_client(jwt_user=jwt, x_portal_client_id="CL-OTHER")  # not a member
    assert ei.value.status_code == 403


def test_identity_deactivated_member_denied(_isolate):
    pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    jwt = {"auth_user_id": "uid-O", "email": "owner@co.test"}
    get_current_portal_client(jwt_user=jwt, x_portal_client_id="CL-1")           # activate both
    pa.deactivate_contact(FIRM, c2["id"], actor=ACTOR)
    # CL-2 now denied; CL-1 still fine (now the sole membership → no header needed)
    with pytest.raises(HTTPException) as ei:
        get_current_portal_client(jwt_user=jwt, x_portal_client_id="CL-2")
    assert ei.value.status_code == 403
    assert get_current_portal_client(jwt_user=jwt, x_portal_client_id=None)["client_id"] == "CL-1"


def test_identity_rejects_non_portal_user(_isolate):
    with pytest.raises(HTTPException) as ei:
        get_current_portal_client(jwt_user={"auth_user_id": "nobody", "email": "nobody@x.test"})
    assert ei.value.status_code == 403


# ── Invite lifecycle + audit + cross-firm isolation ──────────────────────────

def test_invite_idempotent_per_email(_isolate):
    c1 = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-1", "A@c.test", "Alice R", actor=ACTOR)   # same email, case-insensitive
    assert c1["id"] == c2["id"] and len(pa.list_contacts(FIRM, "CL-1")) == 1


def test_reinvite_after_deactivate_reactivates(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.deactivate_contact(FIRM, c["id"], actor=ACTOR)
    again = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    assert again["id"] == c["id"] and again["status"] == "invited" and again["deactivated_at"] is None
    assert _ids(pa.list_portal_memberships("uid-A", "a@c.test")) == ["CL-1"]


def test_resend_guards(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    assert pa.resend_invite(FIRM, c["id"], actor=ACTOR)["id"] == c["id"]
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
