"""
Client-assignment scope on payment_service.py (Phase 4.6 online payments),
reached via routers/payments.py — a set of one-line delegations.

create_link/send_link_email already threaded actor=current_user through
pre-phase, but the service never checked it against anything. list_links/
get_link/history took only invoice_id/link_id and returned whatever the
firm-scoped query found, with no client-assignment check at all.
payment_webhook is EXEMPT (in the ratchet) — a gateway cannot authenticate
as a staff user; it is protected instead by signature verification.
"""
import pytest
from fastapi import HTTPException

import services.payment_service as ps
from tests.test_online_payments import FakeDB, _seed_invoice

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
CUSTOMER = "cust-1"
ACTOR = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches can_access_client on the
    service module, mirroring the other *_client_scope.py test files in this
    sweep."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ps, "can_access_client", _can)
    return seen


def _db_with_invoice(client_id, total=100000, paid=0):
    db = FakeDB()
    _seed_invoice(db, firm=FIRM, client=client_id, customer=CUSTOMER, iid="INV-1", total=total, paid=paid)
    return db


# ══════════════════════════════════════════════════════════════════════════════
# create_link
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_a_link_for_another_clients_invoice_is_refused(deny):
    db = _db_with_invoice(THEIRS)
    with pytest.raises(HTTPException) as e:
        ps.create_link(db, FIRM, "INV-1", actor=ACTOR)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_creating_a_link_for_your_own_clients_invoice_still_works(deny):
    db = _db_with_invoice(MINE)
    link = ps.create_link(db, FIRM, "INV-1", actor=ACTOR)
    assert link["client_id"] == MINE
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# list_links / history
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_links_for_another_clients_invoice_is_refused(deny):
    db = _db_with_invoice(THEIRS)
    with pytest.raises(HTTPException) as e:
        ps.list_links(db, FIRM, "INV-1", ACTOR)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_links_for_your_own_clients_invoice_still_works(deny):
    db = _db_with_invoice(MINE)
    out = ps.list_links(db, FIRM, "INV-1", ACTOR)
    assert out == []
    assert deny == [MINE]


def test_listing_links_for_a_nonexistent_invoice_is_a_harmless_empty_list(deny):
    """No invoice at all — nothing for an assignment check to gate; matches
    the pre-existing behaviour (an empty query result), not a 404."""
    db = FakeDB()
    out = ps.list_links(db, FIRM, "INV-GHOST", ACTOR)
    assert out == []
    assert deny == []


def test_history_for_another_clients_invoice_is_refused(deny):
    db = _db_with_invoice(THEIRS)
    with pytest.raises(HTTPException) as e:
        ps.history(db, FIRM, "INV-1", ACTOR)
    assert e.value.status_code == 404


def test_history_for_your_own_clients_invoice_still_works(deny):
    db = _db_with_invoice(MINE, total=100000, paid=0)
    out = ps.history(db, FIRM, "INV-1", ACTOR)
    assert out["outstanding_paise"] == 100000


# ══════════════════════════════════════════════════════════════════════════════
# get_link / send_link_email
# ══════════════════════════════════════════════════════════════════════════════

def test_getting_another_clients_link_is_refused(deny):
    db = _db_with_invoice(THEIRS)
    db.seed("customer_payment_links", {
        "id": "LINK-1", "firm_id": FIRM, "client_id": THEIRS, "customer_id": CUSTOMER,
        "invoice_id": "INV-1", "amount_paise": 1000,
    })
    assert ps.get_link(db, FIRM, "LINK-1", ACTOR) is None
    assert deny == [THEIRS]


def test_getting_your_own_link_still_works(deny):
    db = _db_with_invoice(MINE)
    link = ps.create_link(db, FIRM, "INV-1", actor=ACTOR)
    out = ps.get_link(db, FIRM, link["id"], ACTOR)
    assert out["id"] == link["id"]


def test_sending_another_clients_link_email_is_refused(deny):
    db = _db_with_invoice(THEIRS)
    # Seed a link directly (bypassing create_link's own guard) to isolate
    # send_link_email's OWN scope check via get_link.
    db.seed("customer_payment_links", {
        "id": "LINK-1", "firm_id": FIRM, "client_id": THEIRS, "customer_id": CUSTOMER,
        "invoice_id": "INV-1", "amount_paise": 1000, "short_url": "https://pay.example/x",
    })
    with pytest.raises(HTTPException) as e:
        ps.send_link_email(db, FIRM, "LINK-1", actor=ACTOR)
    assert e.value.status_code == 404
    assert e.value.detail == "Payment link not found."
