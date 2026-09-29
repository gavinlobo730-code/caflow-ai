"""
Employee-portal provisioning — the invite → activate → revoke lifecycle.

WHAT THIS GUARDS
    Migration 262 opened the employee portal for reading; this is what decides
    WHO gets to read it. Every assertion below maps to a property that the
    client-portal flow had to learn the hard way (migration 153): binding used
    to happen whenever a session email matched a row, on every page load, with
    no token and no expiry — so a recycled or typo'd address inherited someone
    else's payslips on first login.

    The employee flow is the same shape, so it inherits the same rules and the
    same tests:

      * an expired invite cannot bind
      * a token cannot bind twice (single use)
      * the wrong email cannot bind, even with a valid token
      * every rejection is the SAME 404, so it cannot be used as an oracle
      * revoking clears the identity binding, not just the flag

    Plus one property the client flow does NOT have: the token is never stored,
    only its sha256, so reading the table cannot yield a usable invite.
"""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "ca-1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "ca-2", "email": "ca@firmb.test", "role": "Partner"}
EMP = "EMP-1"
EMP_EMAIL = "asha@acme.test"


def _setup(monkeypatch):
    import routers.payroll as pr
    import services.employee_portal_service as eps
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pr])
    monkeypatch.setattr(eps, "_USE_MOCK", False)
    monkeypatch.setattr(eps, "_db", lambda: db)
    # No real email in tests; the send is best-effort anyway.
    monkeypatch.setattr(eps, "_send_invite_email", lambda *a, **k: None)
    db.seed("payroll_employees", {
        "id": EMP, "firm_id": FIRM, "client_id": "CLI", "name": "Asha",
        "auth_user_id": None, "portal_enabled": False,
    })
    return eps, db


def _invite(eps, email=EMP_EMAIL):
    return eps.invite_employee(FIRM, EMP, email, actor=CALLER)


def _row(db):
    return db.rows("payroll_employees")[0]


# ─── the happy path ─────────────────────────────────────────────────────────

def test_invite_then_activate_grants_access(monkeypatch):
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)

    # Access is NOT granted by inviting — only by accepting.
    assert _row(db)["portal_enabled"] is False
    assert _row(db)["auth_user_id"] is None

    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)

    row = _row(db)
    assert row["auth_user_id"] == "auth-asha"
    assert row["portal_enabled"] is True
    assert row["portal_activated_at"]


def test_the_token_is_never_stored_only_its_hash(monkeypatch):
    """The property that makes a staff member reading this table harmless."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    row = _row(db)

    assert invite["token"] not in str(row), "the plaintext token reached the database"
    assert row["portal_invite_token_hash"] == hashlib.sha256(
        invite["token"].encode()).hexdigest()


def test_the_activation_url_carries_the_token(monkeypatch):
    eps, _ = _setup(monkeypatch)
    invite = _invite(eps)
    assert invite["token"] in invite["activation_url"]
    assert "/portal/employee/activate" in invite["activation_url"]


# ─── the rejections, each a real attack ─────────────────────────────────────

def test_an_expired_invite_cannot_bind(monkeypatch):
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    db.rows("payroll_employees")[0]["portal_invite_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)
    assert e.value.status_code == 404
    assert _row(db)["auth_user_id"] is None


def test_a_token_cannot_be_used_twice(monkeypatch):
    """Single use. Without this, a forwarded link binds a second identity to the
    same employee — and both would then read those payslips."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)

    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite(invite["token"], "auth-mallory", EMP_EMAIL)
    assert e.value.status_code == 404
    assert _row(db)["auth_user_id"] == "auth-asha", "the second identity took over"


def test_the_wrong_email_cannot_bind_even_with_a_valid_token(monkeypatch):
    """Defence in depth: a leaked link alone is not enough."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)

    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite(invite["token"], "auth-mallory", "mallory@evil.test")
    assert e.value.status_code == 404
    assert _row(db)["auth_user_id"] is None


def test_a_made_up_token_is_rejected(monkeypatch):
    eps, _ = _setup(monkeypatch)
    _invite(eps)
    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite("not-a-real-token", "auth-mallory", EMP_EMAIL)
    assert e.value.status_code == 404


def test_every_rejection_is_indistinguishable(monkeypatch):
    """If 'expired' and 'no such token' differed, the error would tell an
    attacker which tokens exist."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)

    details = set()
    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite("nonexistent", "a", EMP_EMAIL)
    details.add(e.value.detail)
    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite(invite["token"], "a", "wrong@test.test")
    details.add(e.value.detail)
    db.rows("payroll_employees")[0]["portal_invite_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite(invite["token"], "a", EMP_EMAIL)
    details.add(e.value.detail)

    assert len(details) == 1, f"rejection reasons are distinguishable: {details}"


# ─── re-invite and revoke ───────────────────────────────────────────────────

def test_re_inviting_invalidates_the_previous_token(monkeypatch):
    eps, _ = _setup(monkeypatch)
    first = _invite(eps)
    second = _invite(eps)
    assert first["token"] != second["token"]

    with pytest.raises(HTTPException):
        eps.accept_employee_invite(first["token"], "auth-asha", EMP_EMAIL)
    eps.accept_employee_invite(second["token"], "auth-asha", EMP_EMAIL)


def test_an_active_employee_cannot_be_silently_re_invited(monkeypatch):
    """Refused loudly (409) rather than issuing a token that changes nothing —
    which would read as success while their existing access continued."""
    eps, _ = _setup(monkeypatch)
    invite = _invite(eps)
    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)

    with pytest.raises(HTTPException) as e:
        _invite(eps)
    assert e.value.status_code == 409


def test_revoke_clears_the_identity_not_just_the_flag(monkeypatch):
    """Leaving auth_user_id set would mean flipping portal_enabled back on later
    silently restored an ex-employee's access."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)

    eps.revoke_employee_portal(FIRM, EMP, actor=CALLER)
    row = _row(db)
    assert row["portal_enabled"] is False
    assert row["auth_user_id"] is None
    assert row["portal_invite_token_hash"] is None


def test_the_original_invite_cannot_re_bind_after_a_revoke(monkeypatch):
    """The scenario: an employee leaves, their access is revoked — but the
    original invite email is still in their inbox.

    Revoke clears auth_user_id, which is what the token lookup filters on — so
    if the token hash also survived, that old link would bind again.

    The hash is cleared in TWO places, accept() and revoke(), and mutation
    testing showed they are mutually redundant: removing either one alone
    changes nothing observable, because whichever runs first has already
    cleared it. Only removing BOTH reopens the hole, and that is what this test
    catches. Stated precisely because the tempting summary — "revoke's clear is
    the load-bearing one" — is what I first wrote, and it is wrong."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)
    eps.revoke_employee_portal(FIRM, EMP, actor=CALLER)

    with pytest.raises(HTTPException) as e:
        eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)
    assert e.value.status_code == 404
    assert _row(db)["auth_user_id"] is None, "a revoked employee let themselves back in"


def test_revoke_then_reinvite_works(monkeypatch):
    eps, _ = _setup(monkeypatch)
    first = _invite(eps)
    eps.accept_employee_invite(first["token"], "auth-asha", EMP_EMAIL)
    eps.revoke_employee_portal(FIRM, EMP, actor=CALLER)

    second = _invite(eps, "newasha@acme.test")
    eps.accept_employee_invite(second["token"], "auth-asha-2", "newasha@acme.test")


# ─── tenant isolation ───────────────────────────────────────────────────────

def test_another_firm_cannot_invite_your_employee(monkeypatch):
    eps, db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        eps.invite_employee("FIRM-B", EMP, "attacker@evil.test", actor=OTHER)
    assert e.value.status_code == 404
    assert _row(db).get("email") is None


def test_another_firm_cannot_revoke_your_employee(monkeypatch):
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)

    with pytest.raises(HTTPException) as e:
        eps.revoke_employee_portal("FIRM-B", EMP, actor=OTHER)
    assert e.value.status_code == 404
    assert _row(db)["portal_enabled"] is True


# ─── validation + status ────────────────────────────────────────────────────

def test_an_invalid_email_is_refused_before_anything_is_written(monkeypatch):
    eps, db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        eps.invite_employee(FIRM, EMP, "not-an-email", actor=CALLER)
    assert e.value.status_code == 422
    assert _row(db).get("portal_invite_token_hash") is None


def test_portal_status_never_returns_the_hash(monkeypatch):
    eps, _ = _setup(monkeypatch)
    _invite(eps)
    status = eps.portal_status(FIRM, EMP)
    assert status["invite_pending"] is True
    assert status["activated"] is False
    assert "portal_invite_token_hash" not in status
    # No VALUE is the hash either — a renamed key would still be a leak.
    import hashlib as _h
    leaked = _h.sha256(b"x").hexdigest()[:0]  # length probe only
    assert not any(isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)
                   for v in status.values()), "a sha256-shaped value is in the status payload"


# ─── mint_activation_session — bootstrapping a session from a bare token ────
#
# The bug this closes: neither the emailed activation link nor its
# copy-paste fallback ever carried a real Supabase session (nothing had ever
# called Supabase's Auth API for that email), so the activation page's
# "wait for the magic-link session" step polled forever and always landed on
# "invalid" — regardless of which of the two links was opened. This is the
# other half of accept_employee_invite: it does not bind anything, it only
# proves the token is genuine and asks Supabase's ADMIN API for the
# ingredients of a session the BROWSER then establishes for itself with
# supabase.auth.verifyOtp({token_hash, type}).

class _FakeLinkProperties:
    def __init__(self, hashed_token: str, verification_type: str):
        self.hashed_token = hashed_token
        self.verification_type = verification_type


class _FakeLinkResponse:
    def __init__(self, hashed_token: str, verification_type: str):
        self.properties = _FakeLinkProperties(hashed_token, verification_type)


class _FakeAdminAuthAPI:
    """Stands in for db.auth.admin. `calls` records every generate_link
    invocation so a test can assert exactly which types were tried and in
    what order, without needing a real Supabase project."""

    def __init__(self, invite_fails: bool = False, magiclink_fails: bool = False):
        self.invite_fails = invite_fails
        self.magiclink_fails = magiclink_fails
        self.calls: list[dict] = []

    def generate_link(self, params: dict):
        self.calls.append(dict(params))
        kind = params["type"]
        if kind == "invite" and self.invite_fails:
            raise RuntimeError("email_exists: A user with this email address has already been registered")
        if kind == "magiclink" and self.magiclink_fails:
            raise RuntimeError("Supabase Auth is unreachable")
        return _FakeLinkResponse(f"th-{kind}", kind)


def _wire_admin(db, **kwargs):
    from types import SimpleNamespace
    admin = _FakeAdminAuthAPI(**kwargs)
    db.auth = SimpleNamespace(admin=admin)
    return admin


def test_a_fresh_invite_mints_a_session_via_type_invite(monkeypatch):
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    admin = _wire_admin(db)

    result = eps.mint_activation_session(invite["token"])

    assert admin.calls == [{"type": "invite", "email": EMP_EMAIL}]
    assert result == {"token_hash": "th-invite", "verification_type": "invite"}


def test_an_already_registered_email_falls_back_to_magiclink(monkeypatch):
    """The re-invite-after-revoke case: the Supabase Auth user from the first
    activation still exists (revoke clears the BINDING, not the identity),
    so `type=invite` refuses and `type=magiclink` is what actually works."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    admin = _wire_admin(db, invite_fails=True)

    result = eps.mint_activation_session(invite["token"])

    assert [c["type"] for c in admin.calls] == ["invite", "magiclink"]
    assert result == {"token_hash": "th-magiclink", "verification_type": "magiclink"}


def test_both_admin_calls_failing_is_a_503_not_an_invalid_invite(monkeypatch):
    """A caller here already holds a token proven pending and unexpired — the
    failure is Supabase's, not the token's, and saying so plainly poses no
    probing risk (there is nothing left to probe for)."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    _wire_admin(db, invite_fails=True, magiclink_fails=True)

    with pytest.raises(HTTPException) as e:
        eps.mint_activation_session(invite["token"])
    assert e.value.status_code == 503


def test_minting_a_session_for_a_bad_token_never_calls_the_admin_api(monkeypatch):
    """The same probing-resistance property accept_employee_invite has: an
    unknown token is refused before it can cause any side effect at all."""
    eps, db = _setup(monkeypatch)
    _invite(eps)
    admin = _wire_admin(db)

    with pytest.raises(HTTPException) as e:
        eps.mint_activation_session("not-a-real-token")
    assert e.value.status_code == 404
    assert admin.calls == []


def test_minting_a_session_for_an_expired_invite_is_refused(monkeypatch):
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    db.rows("payroll_employees")[0]["portal_invite_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    admin = _wire_admin(db)

    with pytest.raises(HTTPException) as e:
        eps.mint_activation_session(invite["token"])
    assert e.value.status_code == 404
    assert admin.calls == []


def test_minting_does_not_consume_the_invite(monkeypatch):
    """Only accept_employee_invite spends the token — minting a session is a
    read, so the SAME token still has to work for the bind that follows it."""
    eps, db = _setup(monkeypatch)
    invite = _invite(eps)
    _wire_admin(db)

    eps.mint_activation_session(invite["token"])
    row = _row(db)
    assert row["portal_invite_token_hash"] is not None, "minting must not have spent the invite"
    assert row["auth_user_id"] is None

    # The token still works for the real bind, exactly as if minting had
    # never happened — this is the sequence the activation page now runs.
    eps.accept_employee_invite(invite["token"], "auth-asha", EMP_EMAIL)
    assert _row(db)["auth_user_id"] == "auth-asha"


def test_minting_reads_the_invites_own_email_never_a_caller_supplied_one(monkeypatch):
    """mint_activation_session takes only a token — there is no email
    parameter for a caller to substitute, unlike accept_employee_invite's
    defence-in-depth check. This pins that there is nothing to substitute."""
    import inspect
    import services.employee_portal_service as eps
    assert "email" not in inspect.signature(eps.mint_activation_session).parameters
