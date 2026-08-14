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
