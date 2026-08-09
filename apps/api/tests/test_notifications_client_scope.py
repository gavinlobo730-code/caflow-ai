"""
Client-assignment scope on the notifications router.

notifications.client_id is nullable (migration 004): a notification is EITHER
about a client or firm-level. This router mounts no client guard at all, and
create_notification wrote body.client_id straight into the row with no check
anywhere — an unassigned Executive/Manager could plant a notification against
another staff member's client, which then surfaces in that client's feed and
in every downstream digest.

list_notifications is recipient-scoped (user_id=the caller) and so was never
cross-USER, but a notification about a client the recipient has since been
UNASSIGNED from should stop being readable, the same rule the underlying
record obeys — hence filter_by_client. The five remaining routes are
recipient-owned tallies and transitions with no client_id in them at all.
"""
import pytest
from fastapi import HTTPException

import routers.notifications as nt

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access on
    the router module, mirroring the other *_client_scope.py test files in
    this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(nt, "assert_client_access", _assert)
    return seen


def _body(**kw):
    return nt.NotificationCreate(type="alert", title="t", body="b", **kw)


# ══════════════════════════════════════════════════════════════════════════════
# create_notification — client_id in the body
# ══════════════════════════════════════════════════════════════════════════════

def test_planting_a_notification_on_another_clients_is_refused(deny, monkeypatch):
    written = []
    monkeypatch.setattr(nt.notifications_repo, "create",
                        lambda row: written.append(row) or row)
    with pytest.raises(HTTPException) as e:
        nt.create_notification(_body(client_id=THEIRS), current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]
    assert not written   # refused BEFORE the row was written


def test_creating_a_notification_for_your_own_client_still_works(deny, monkeypatch):
    monkeypatch.setattr(nt.notifications_repo, "create", lambda row: {**row, "id": "N1"})
    out = nt.create_notification(_body(client_id=MINE), current_user=USER)
    assert out["data"]["notification"]["client_id"] == MINE
    assert deny == [MINE]


def test_a_firm_level_notification_needs_no_client(deny, monkeypatch):
    """client_id is nullable — assert_client_access(user, None) is a no-op, so
    the guard must not have broken firm-level notifications."""
    monkeypatch.setattr(nt.notifications_repo, "create", lambda row: {**row, "id": "N1"})
    out = nt.create_notification(_body(), current_user=USER)
    assert out["data"]["notification"]["client_id"] is None
    assert deny == [None]


# ══════════════════════════════════════════════════════════════════════════════
# list_notifications — narrowing to the caller's current book
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_drops_notifications_about_clients_youre_no_longer_assigned(monkeypatch):
    rows = [{"id": "N1", "client_id": MINE},
            {"id": "N2", "client_id": THEIRS},
            {"id": "N3", "client_id": None}]
    monkeypatch.setattr(nt.notifications_repo, "find_all", lambda **kw: rows)
    monkeypatch.setattr(nt.notifications_repo, "count_unread", lambda **kw: 3)
    monkeypatch.setattr(nt, "filter_by_client",
                        lambda user, items, key="client_id":
                        [r for r in items if r.get(key) != THEIRS])
    out = nt.list_notifications(current_user=USER)
    assert [r["id"] for r in out["data"]["notifications"]] == ["N1", "N3"]
    assert out["data"]["total"] == 2


def test_listing_keeps_firm_level_notifications(monkeypatch):
    """A client-less notification belongs to nobody's book and must survive
    the narrowing — that is filter_by_client's documented behaviour, pinned
    here because this router is the one place it matters for a nullable
    column."""
    from core.authz import filter_by_client
    rows = [{"id": "N3", "client_id": None}]
    monkeypatch.setattr(nt.notifications_repo, "find_all", lambda **kw: rows)
    monkeypatch.setattr(nt.notifications_repo, "count_unread", lambda **kw: 0)
    monkeypatch.setattr(nt, "filter_by_client", filter_by_client)
    out = nt.list_notifications(current_user=USER)
    assert [r["id"] for r in out["data"]["notifications"]] == ["N3"]


# ══════════════════════════════════════════════════════════════════════════════
# The recipient-owned routes stay recipient-owned (EXEMPT in the ratchet on
# exactly this ground — pinned so the reason cannot quietly stop being true).
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("call", [
    lambda: nt.read_one("N1", current_user=USER),
    lambda: nt.archive_one("N1", current_user=USER),
])
def test_a_row_addressed_transition_is_scoped_to_the_caller(call, monkeypatch):
    seen = {}

    def _capture(nid, firm_id=None, user_id=None):
        seen.update(notification_id=nid, firm_id=firm_id, user_id=user_id)
        return {"id": nid}

    monkeypatch.setattr(nt.notifications_repo, "mark_read", _capture)
    monkeypatch.setattr(nt.notifications_repo, "archive", _capture)
    call()
    assert seen["firm_id"] == FIRM
    assert seen["user_id"] == USER["id"]   # the recipient, not just the firm


def test_read_all_only_touches_the_callers_own_inbox(monkeypatch):
    seen = {}
    monkeypatch.setattr(nt.notifications_repo, "mark_all_read",
                        lambda firm_id=None, user_id=None:
                        seen.update(firm_id=firm_id, user_id=user_id) or 3)
    nt.read_all(current_user=USER)
    assert seen == {"firm_id": FIRM, "user_id": USER["id"]}
