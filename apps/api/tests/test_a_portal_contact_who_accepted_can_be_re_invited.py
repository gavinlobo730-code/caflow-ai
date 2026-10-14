"""A portal contact who has already accepted is never locked out by being invited again (POST-A-232).

WHAT WAS WRONG
    `invite_contact` for an EXISTING contact set the status to "invited" and issued a fresh token but kept the sign-in the
    contact was bound to (`auth_user_id`). Two lookups decide whether the contact gets in, and this row matched neither:
    `_find_by_invite_token` finds only an invited contact with NO bound sign-in, and `_find_all_active_by_auth` finds only
    an ACTIVE contact. So for a contact who had ever accepted:
      * re-inviting an ACTIVE contact turned a working portal login into a dead one, with the CA told an invitation had
        been sent;
      * re-inviting a DEACTIVATED one (the docstring promised "reactivates") sent a token that could never be accepted.
    The existing lifecycle test went invite -> deactivate -> re-invite and stopped at the status, which is why it passed:
    it never accepted anything.

NEGATIVE CONTROL (each of these fails against the previous code)
    * test_re_inviting_an_active_contact_changes_nothing_and_says_so
    * test_a_deactivated_contact_can_be_reactivated_and_accept_the_new_invitation
    * test_resending_to_an_active_contact_is_refused
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routers.portal_access import InviteContactBody
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "ca-1", "email": "ca@firma.test", "role": "Partner"}
EMAIL = "owner@acme.test"
SIGN_IN = "supabase-uid-owner"


@pytest.fixture
def world(monkeypatch):
    import routers.portal_access as pa
    import services.portal_access_service as pas
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pa])
    monkeypatch.setattr(pas, "_USE_MOCK", False)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "portal_enabled": False})
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(pas, "_send_invite_email", lambda email, client_id, firm_id, token: sent.append((email, token)))
    return pa, pas, db, sent


def _invite(pa):
    return pa.invite_portal_contact("CLI", InviteContactBody(email=EMAIL, name="Owner"), CALLER)["data"]["contact"]


def _accept(pas, token, email=EMAIL, uid=SIGN_IN):
    return pas.accept_portal_invite(token, uid, email)


def _has_access(pas, uid=SIGN_IN) -> bool:
    return any(str(m["client_id"]) == "CLI" for m in pas.list_portal_memberships(uid, EMAIL))


def test_the_first_invitation_is_accepted_and_gives_access(world):
    pa, pas, db, sent = world
    token = _invite(pa)["invite_token"]
    assert not _has_access(pas), "an invitation is not access until it is accepted"
    _accept(pas, token)
    assert _has_access(pas)


def test_re_inviting_an_active_contact_changes_nothing_and_says_so(world):
    pa, pas, db, sent = world
    _accept(pas, _invite(pa)["invite_token"])
    mails_before = len(sent)

    with pytest.raises(HTTPException) as refused:
        _invite(pa)
    assert refused.value.status_code == 409
    assert "already has portal access" in refused.value.detail and "no invitation was sent" in refused.value.detail
    assert len(sent) == mails_before, "nothing may be mailed for an invitation that was refused"
    assert _has_access(pas), "the contact must still be able to sign in"
    (row,) = db.rows("client_portal_users")
    assert row["status"] == "active" and row["auth_user_id"] == SIGN_IN and row["invite_token"] is None


def test_a_deactivated_contact_can_be_reactivated_and_accept_the_new_invitation(world):
    pa, pas, db, sent = world
    cid = _invite(pa)["id"]
    _accept(pas, db.rows("client_portal_users")[0]["invite_token"])
    pa.deactivate_portal_contact(cid, CALLER)
    assert not _has_access(pas), "deactivation revokes access"

    again = _invite(pa)
    assert again["id"] == cid and again["status"] == "invited"
    assert again["auth_user_id"] is None, "the old sign-in must be released or the new token can never be accepted"

    _accept(pas, again["invite_token"])
    assert _has_access(pas)


def test_the_e_mail_still_decides_who_may_accept_a_re_invitation(world):
    pa, pas, db, sent = world
    cid = _invite(pa)["id"]
    _accept(pas, db.rows("client_portal_users")[0]["invite_token"])
    pa.deactivate_portal_contact(cid, CALLER)
    token = _invite(pa)["invite_token"]
    with pytest.raises(HTTPException) as refused:
        _accept(pas, token, email="someone.else@elsewhere.test", uid="another-uid")
    assert refused.value.status_code == 404
    assert not _has_access(pas, "another-uid")


def test_a_re_invitation_replaces_the_old_token(world):
    pa, pas, db, sent = world
    cid = _invite(pa)["id"]
    first = db.rows("client_portal_users")[0]["invite_token"]
    _accept(pas, first)
    pa.deactivate_portal_contact(cid, CALLER)
    second = _invite(pa)["invite_token"]
    assert second != first
    with pytest.raises(HTTPException):
        _accept(pas, first)


def test_resending_to_an_active_contact_is_refused(world):
    pa, pas, db, sent = world
    cid = _invite(pa)["id"]
    _accept(pas, db.rows("client_portal_users")[0]["invite_token"])
    mails_before = len(sent)
    with pytest.raises(HTTPException) as refused:
        pa.resend_portal_invite(cid, CALLER)
    assert refused.value.status_code == 422 and "already accepted" in refused.value.detail
    assert len(sent) == mails_before
    assert _has_access(pas)


def test_an_invited_contact_is_still_re_invited_and_resent_as_before(world):
    pa, pas, db, sent = world
    first = _invite(pa)
    second = _invite(pa)
    assert second["id"] == first["id"] and second["status"] == "invited"
    assert second["invite_token"] != first["invite_token"]
    cid = first["id"]
    assert pa.resend_portal_invite(cid, CALLER)["data"]["contact"]["status"] == "invited"
    assert len(db.rows("client_portal_users")) == 1
