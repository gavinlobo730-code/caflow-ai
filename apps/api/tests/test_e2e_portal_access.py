"""
Phase 5.2 WS-1 — Portal access (CA-side) E2E.

Drives the real router endpoints through the contact lifecycle against the
shared DB:

  invite → list → re-invite (idempotent) → resend → deactivate → re-invite (reactivate)

Asserts the status machine (invited → deactivated → invited), idempotency per
email, the resend-after-deactivate guard (422), and tenant isolation: a
foreign-firm caller sees no contacts and cannot resend/deactivate (404).
"""
import pytest
from fastapi import HTTPException

from routers.portal_access import InviteContactBody
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.portal_access as pa
    import services.portal_access_service as pas
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pa])
    monkeypatch.setattr(pas, "_USE_MOCK", False)         # route service to the shared DB
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "portal_enabled": False})
    return pa, db


def _invite(pa, email="owner@acme.test", name="Owner"):
    return pa.invite_portal_contact("CLI", InviteContactBody(email=email, name=name), CALLER)["data"]["contact"]


def test_portal_contact_lifecycle(monkeypatch):
    pa, db = _setup(monkeypatch)

    c = _invite(pa)
    cid = c["id"]
    assert c["status"] == "invited"

    listed = pa.list_portal_contacts("CLI", CALLER)["data"]["contacts"]
    assert len(listed) == 1 and listed[0]["id"] == cid

    # Idempotent re-invite for the same email ⇒ same contact, still one row.
    again = _invite(pa)
    assert again["id"] == cid
    assert len(pa.list_portal_contacts("CLI", CALLER)["data"]["contacts"]) == 1

    # Resend while invited is allowed.
    assert pa.resend_portal_invite(cid, CALLER)["data"]["contact"]["status"] == "invited"

    # Deactivate revokes access (no hard delete — row remains).
    deact = pa.deactivate_portal_contact(cid, CALLER)["data"]["contact"]
    assert deact["status"] == "deactivated"
    assert len(pa.list_portal_contacts("CLI", CALLER)["data"]["contacts"]) == 1

    # Re-invite reactivates the deactivated contact.
    re = _invite(pa)
    assert re["id"] == cid and re["status"] == "invited"


def test_portal_resend_after_deactivate_blocked(monkeypatch):
    pa, db = _setup(monkeypatch)
    cid = _invite(pa)["id"]
    pa.deactivate_portal_contact(cid, CALLER)
    with pytest.raises(HTTPException) as ei:
        pa.resend_portal_invite(cid, CALLER)             # must re-invite, not resend
    assert ei.value.status_code == 422


def test_portal_invalid_email_rejected(monkeypatch):
    pa, db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        pa.invite_portal_contact("CLI", InviteContactBody(email="not-an-email"), CALLER)
    assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_portal_foreign_firm_sees_no_contacts(monkeypatch):
    pa, db = _setup(monkeypatch)
    _invite(pa)
    assert pa.list_portal_contacts("CLI", OTHER)["data"]["contacts"] == []


def test_portal_foreign_firm_cannot_deactivate_or_resend(monkeypatch):
    pa, db = _setup(monkeypatch)
    cid = _invite(pa)["id"]
    with pytest.raises(HTTPException) as ei:
        pa.deactivate_portal_contact(cid, OTHER)
    assert ei.value.status_code == 404
    with pytest.raises(HTTPException) as ej:
        pa.resend_portal_invite(cid, OTHER)
    assert ej.value.status_code == 404
    # original contact still active/invited under its real firm
    assert pa.list_portal_contacts("CLI", CALLER)["data"]["contacts"][0]["status"] == "invited"
