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
    # F22 fix: membership requires the invite to be explicitly accepted by token —
    # it no longer auto-binds just because list_portal_memberships is called.
    pa.accept_portal_invite(c["invite_token"], "uid-A", "a@c.test")
    ms = pa.list_portal_memberships("uid-A", "a@c.test")
    assert _ids(ms) == ["CL-1"]
    bound = pa.MOCK_PORTAL_CONTACTS[0]
    assert bound["auth_user_id"] == "uid-A" and bound["status"] == "active" and bound["activated_at"]
    assert bound["invite_token"] is None and bound["invite_expires_at"] is None  # single-use, cleared
    assert ms[0]["contact_id"] == c["id"]


def test_one_user_multiple_clients_requires_accepting_each(_isolate):
    c1 = pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    # F22 fix: NEITHER shows up until its OWN token is accepted (no more
    # any-matching-email-binds-everything) — a multi-company owner still ends up
    # with all their clients, but each relationship was individually proven.
    assert pa.list_portal_memberships("uid-O", "owner@co.test") == []
    pa.accept_portal_invite(c1["invite_token"], "uid-O", "owner@co.test")
    assert _ids(pa.list_portal_memberships("uid-O", "owner@co.test")) == ["CL-1"]
    pa.accept_portal_invite(c2["invite_token"], "uid-O", "owner@co.test")
    assert _ids(pa.list_portal_memberships("uid-O", "owner@co.test")) == ["CL-1", "CL-2"]


def test_mixed_active_and_deactivated_memberships(_isolate):
    c1 = pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    pa.accept_portal_invite(c1["invite_token"], "uid-O", "owner@co.test")
    pa.accept_portal_invite(c2["invite_token"], "uid-O", "owner@co.test")
    pa.deactivate_contact(FIRM, c2["id"], actor=ACTOR)       # revoke CL-2
    assert _ids(pa.list_portal_memberships("uid-O", "owner@co.test")) == ["CL-1"]


# ── F22 regression: no auto-bind, token/expiry/email checks ──────────────────

def test_membership_listing_never_auto_binds_a_matching_email(_isolate):
    """The core F22 regression lock: a pending invite must NEVER activate just
    because list_portal_memberships (or get_current_portal_client) is called
    with a matching email — that was the entire vulnerability."""
    pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    for _ in range(3):   # repeated calls — still must not bind
        assert pa.list_portal_memberships("uid-STRANGER", "a@c.test") == []
    bound = pa.MOCK_PORTAL_CONTACTS[0]
    assert bound.get("auth_user_id") is None and bound["status"] == "invited"


def test_accept_invite_wrong_token_rejected(_isolate):
    pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    with pytest.raises(HTTPException) as ei:
        pa.accept_portal_invite("not-the-real-token", "uid-A", "a@c.test")
    assert ei.value.status_code == 404


def test_accept_invite_email_mismatch_rejected(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    with pytest.raises(HTTPException) as ei:
        pa.accept_portal_invite(c["invite_token"], "uid-STRANGER", "stranger@evil.test")
    assert ei.value.status_code == 404
    assert pa.MOCK_PORTAL_CONTACTS[0].get("auth_user_id") is None   # not bound


def test_accept_invite_expired_rejected(_isolate, monkeypatch):
    from datetime import datetime, timedelta, timezone
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    # Simulate an invite issued 15 days ago (TTL is 14 days).
    for row in pa.MOCK_PORTAL_CONTACTS:
        if row["id"] == c["id"]:
            row["invite_expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(HTTPException) as ei:
        pa.accept_portal_invite(c["invite_token"], "uid-A", "a@c.test")
    assert ei.value.status_code == 404


def test_accept_invite_is_single_use(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.accept_portal_invite(c["invite_token"], "uid-A", "a@c.test")
    with pytest.raises(HTTPException) as ei:
        pa.accept_portal_invite(c["invite_token"], "uid-A", "a@c.test")   # replay
    assert ei.value.status_code == 404


def test_legacy_portal_user_id_backward_compatible(_isolate):
    pa.MOCK_LEGACY_PORTAL["legacy-uid"] = {"client_id": "CL-9", "firm_id": FIRM}
    ms = pa.list_portal_memberships("legacy-uid", "old@c.test")
    assert _ids(ms) == ["CL-9"] and ms[0]["legacy"] is True and ms[0]["contact_id"] is None


def test_unknown_identity_has_no_memberships(_isolate):
    assert pa.list_portal_memberships("nobody", "nobody@x.test") == []


# ── Identity layer: deterministic, explicit active-client selection ──────────

def test_identity_single_membership_no_header(_isolate):
    c = pa.invite_contact(FIRM, "CL-1", "a@c.test", "Alice", actor=ACTOR)
    pa.accept_portal_invite(c["invite_token"], "uid-A", "a@c.test")
    ctx = get_current_portal_client(jwt_user={"auth_user_id": "uid-A", "email": "a@c.test"},
                                    x_portal_client_id=None)
    assert ctx["portal"] is True and ctx["client_id"] == "CL-1" and ctx["role"] == "PortalClient"
    assert [m["client_id"] for m in ctx["memberships"]] == ["CL-1"]
    # strict: no staff fields leaked
    assert "auth_user_id" not in ctx and "access_token" not in ctx and "aal" not in ctx


def test_identity_multiple_requires_explicit_selection(_isolate):
    c1 = pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    pa.accept_portal_invite(c1["invite_token"], "uid-O", "owner@co.test")
    pa.accept_portal_invite(c2["invite_token"], "uid-O", "owner@co.test")
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
    c1 = pa.invite_contact(FIRM, "CL-1", "owner@co.test", "Owner", actor=ACTOR)
    c2 = pa.invite_contact(FIRM, "CL-2", "owner@co.test", "Owner", actor=ACTOR)
    jwt = {"auth_user_id": "uid-O", "email": "owner@co.test"}
    pa.accept_portal_invite(c1["invite_token"], "uid-O", "owner@co.test")
    pa.accept_portal_invite(c2["invite_token"], "uid-O", "owner@co.test")        # activate both
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
    # Re-inviting rotates the token (a stale/leaked prior link must stop working).
    assert again["invite_token"] and again["invite_token"] != c.get("invite_token")
    pa.accept_portal_invite(again["invite_token"], "uid-A", "a@c.test")
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
