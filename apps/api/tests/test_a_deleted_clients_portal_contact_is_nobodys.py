"""POST-A-447, the portal half: a contact of a client the practice has DELETED is not a portal member.

Deleting a client sets `clients.deleted_at` and hides it from every staff screen; nothing touched its
`client_portal_users` rows, so an active contact kept signing in to the deleted client's portal, read its fee invoices,
documents and compliance list, and posted messages that notified staff about a client none of them could open. Every
portal route resolves its principal through `list_portal_memberships`, so that one function is where the rule holds,
on both paths (the multi-contact rows and the legacy `clients.portal_user_id` link) and in mock and real mode.
"""
import pytest
from fastapi import HTTPException

import services.portal_access_service as pa
from core.portal_auth import get_current_portal_client
from mock_data import CLIENT_INDEX

FIRM = "F-DEL"
ACTOR = {"firm_id": FIRM, "auth_user_id": "staff-1", "email": "ca@firm.test"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    pa.reset_mock_stores()
    import services.audit_service as au
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    import services.email_service as es
    monkeypatch.setattr(es, "_send", lambda *a, **k: True)
    for cid in ("CL-DEL-1", "CL-DEL-2"):
        CLIENT_INDEX[cid] = {"id": cid, "firm_id": FIRM, "client_name": cid}
    yield
    for cid in ("CL-DEL-1", "CL-DEL-2"):
        CLIENT_INDEX.pop(cid, None)
    pa.reset_mock_stores()


def _member_of_both():
    for cid in ("CL-DEL-1", "CL-DEL-2"):
        c = pa.invite_contact(FIRM, cid, "owner@co.test", "Owner", actor=ACTOR)
        pa.accept_portal_invite(c["invite_token"], "uid-D", "owner@co.test")


def test_a_deleted_client_is_not_a_membership_and_the_live_one_still_is():
    _member_of_both()
    CLIENT_INDEX["CL-DEL-2"]["deleted_at"] = "2026-11-18T05:00:00+00:00"
    assert [m["client_id"] for m in pa.list_portal_memberships("uid-D", "owner@co.test")] == ["CL-DEL-1"]
    # With one live membership left, the portal resolves to it without asking which client.
    assert get_current_portal_client({"auth_user_id": "uid-D", "email": "owner@co.test"}, None)["client_id"] == "CL-DEL-1"
    with pytest.raises(HTTPException) as e:
        get_current_portal_client({"auth_user_id": "uid-D", "email": "owner@co.test"}, "CL-DEL-2")
    assert e.value.status_code == 403


def test_a_contact_whose_only_client_was_deleted_is_not_a_portal_user():
    c = pa.invite_contact(FIRM, "CL-DEL-1", "a@co.test", "A", actor=ACTOR)
    pa.accept_portal_invite(c["invite_token"], "uid-A", "a@co.test")
    CLIENT_INDEX["CL-DEL-1"]["deleted_at"] = "2026-11-18T05:00:00+00:00"
    with pytest.raises(HTTPException) as e:
        get_current_portal_client({"auth_user_id": "uid-A", "email": "a@co.test"}, None)
    assert e.value.status_code == 403


def test_the_legacy_link_to_a_deleted_client_is_not_a_membership():
    pa.MOCK_LEGACY_PORTAL["legacy-uid"] = {"client_id": "CL-DEL-1", "firm_id": FIRM}
    assert [m["client_id"] for m in pa.list_portal_memberships("legacy-uid", None)] == ["CL-DEL-1"]
    CLIENT_INDEX["CL-DEL-1"]["deleted_at"] = "2026-11-18T05:00:00+00:00"
    assert pa.list_portal_memberships("legacy-uid", None) == []


class _Q:
    """A recording stand-in for one PostgREST query: what was asked, and the rows the stand-in database holds."""
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, []

    def select(self, *_a):
        return self

    def eq(self, k, v):
        self.filters.append(("eq", k, v)); return self

    def in_(self, k, v):
        self.filters.append(("in", k, tuple(v))); return self

    def is_(self, k, v):
        self.filters.append(("is", k, v)); return self

    def limit(self, *_a):
        return self

    def execute(self):
        self.db.asked.append((self.table, self.filters))
        rows = self.db.rows[self.table]
        for op, k, v in self.filters:
            if op == "eq":
                rows = [r for r in rows if r.get(k) == v]
            elif op == "in":
                rows = [r for r in rows if r.get(k) in v]
            elif op == "is" and v == "null":
                rows = [r for r in rows if r.get(k) is None]
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def table(self, name):
        return _Q(self, name)


def test_the_real_path_reads_the_clients_row_by_firm_and_client_and_drops_a_deleted_one(monkeypatch):
    monkeypatch.setattr(pa, "_USE_MOCK", False)
    db = _DB({
        "client_portal_users": [
            {"id": "c1", "auth_user_id": "u", "status": "active", "client_id": "K1", "firm_id": "F1"},
            {"id": "c2", "auth_user_id": "u", "status": "active", "client_id": "K2", "firm_id": "F1"},
            # A contact row naming a client of another firm is not a membership of that client.
            {"id": "c3", "auth_user_id": "u", "status": "active", "client_id": "K3", "firm_id": "F1"},
        ],
        "clients": [
            {"id": "K1", "firm_id": "F1", "deleted_at": None, "portal_user_id": None},
            {"id": "K2", "firm_id": "F1", "deleted_at": "2026-11-18T05:00:00+00:00", "portal_user_id": None},
            {"id": "K3", "firm_id": "F2", "deleted_at": None, "portal_user_id": None},
        ],
    })
    assert [m["client_id"] for m in pa.list_portal_memberships("u", None, db=db)] == ["K1"]
    legacy = [f for t, f in db.asked if t == "clients" and ("eq", "portal_user_id", "u") in f]
    assert legacy and ("is", "deleted_at", "null") in legacy[0]
