"""A client with live fees is not deleted because the person deleting it cannot read fees (POST-A-231).

WHAT WAS WRONG
    `_check_delete_blockers` read two blockers as the CALLER: the active fee engagements (a `get_supabase()` read inside
    a bare `except: pass`) and the fee invoices on record (`invoice_repo.find_all`, inside another). `client:delete` is a
    Partner's by role but it can be granted to a Manager on the Team screen, and migration 495 makes the fee tables
    unreadable to anyone below `billing:read`, so for that Manager both reads came back EMPTY with no error: a client
    with an active engagement and thirty invoices showed no blocker and was deleted.

    The same function also let a failed read of the engagement letters or of the DSC records read as "nothing blocks
    this", for the same reason in a different spelling.

WHAT THIS PINS
    * the two fee blockers are COUNTS read with the privileged client, scoped by the firm and the client, whatever the
      caller's own sign-in would show;
    * a source that cannot be read REFUSES the delete in words (503) and the client is not touched;
    * the refusal says nothing was changed.

NEGATIVE CONTROL (each fails against the previous code)
    * test_the_fee_blockers_are_counted_with_the_privileged_client
    * test_a_blocker_that_cannot_be_read_refuses_the_delete
    * test_a_failed_blocker_read_does_not_delete_the_client
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

FIRM = "firm-001"
CLIENT = "c-delete-1"
PARTNER = {"id": "u1", "auth_user_id": "a1", "firm_id": FIRM, "role": "Partner", "email": "p@x.in"}


class _Result:
    def __init__(self, data):
        self.data, self.count = data, len(data)


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, []

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def execute(self):
        self.db.seen.append((self.table, tuple(self.filters)))
        if self.table in self.db.fail:
            raise RuntimeError(f"{self.table} unreadable")
        return _Result(self.db.rows.get(self.table, []))


class _Db:
    """A chainable stand-in for a database client that records what it was asked and answers fixed rows."""

    def __init__(self, rows=None, fail=()):
        self.rows, self.fail, self.seen = rows or {}, set(fail), []

    def table(self, name):
        return _Query(self, name)

    def asked(self, table):
        return [f for t, f in self.seen if t == table]


@pytest.fixture
def world(monkeypatch):
    """Database mode, the three ordinary repos empty, and two clients: the caller's own sign-in (`request`) and the
    privileged one (`service`)."""
    import repositories.engagement_repository as er
    import repositories.invoice_repository as ir
    monkeypatch.setenv("SUPABASE_URL", "http://db.invalid")
    monkeypatch.setattr(er, "_USE_MOCK", False)
    monkeypatch.setattr(ir, "_USE_MOCK", False)

    state = {"request": _Db(), "service": _Db()}
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: state["request"])
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: state["service"])

    with patch("routers.clients.compliance_records_repo") as cr, \
         patch("routers.clients.task_repo") as tk, \
         patch("routers.clients.document_repo") as doc:
        cr.find_all.return_value = []
        tk.find_all.return_value = []
        doc.find_all.return_value = []
        yield state


def _blockers(pan=None):
    from routers.clients import _check_delete_blockers
    return _check_delete_blockers(CLIENT, FIRM, client_pan=pan)


def test_the_fee_blockers_are_counted_with_the_privileged_client(world):
    # The caller's own view of the fee tables is empty (what a Manager without billing access gets); the firm's is not.
    world["request"] = _Db()
    world["service"] = _Db(rows={"fee_engagements": [{"id": 1}, {"id": 2}],
                                 "fee_invoices": [{"id": 1}, {"id": 2}, {"id": 3}]})
    blockers = _blockers()
    assert "2 active fee engagement(s)" in blockers, blockers
    assert "3 fee invoice(s) on record" in blockers, blockers

    service = world["service"]
    for table in ("fee_engagements", "fee_invoices"):
        (filters,) = service.asked(table)
        assert ("firm_id", FIRM) in filters and ("client_id", CLIENT) in filters, (table, filters)
    assert ("status", "Active") in service.asked("fee_engagements")[0]
    assert ("is_deleted", False) in service.asked("fee_invoices")[0]
    assert not [t for t, _ in world["request"].seen if t.startswith("fee_")], (
        "the fee tables must not be read as the caller: their sign-in may see none of them")


def test_a_client_with_no_live_fees_has_no_fee_blocker(world):
    world["service"] = _Db(rows={})
    assert not [b for b in _blockers() if "fee" in b]


@pytest.mark.parametrize("source, where, words", [
    ("fee_engagements", "service", "active fee engagements"),
    ("fee_invoices", "service", "fee invoices on record"),
    ("engagements", "request", "active engagement letters"),
    ("dsc_records", "request", "digital signature certificates"),
])
def test_a_blocker_that_cannot_be_read_refuses_the_delete(world, source, where, words):
    world[where] = _Db(fail=(source,))
    with pytest.raises(HTTPException) as refused:
        _blockers(pan="ABCDE1234F")
    assert refused.value.status_code == 503
    detail = refused.value.detail
    assert words in detail and "nothing was changed" in detail, detail


def test_a_failed_blocker_read_does_not_delete_the_client(world):
    """The route level: the refusal reaches the person and `soft_delete` is never called."""
    from routers.clients import delete_client
    world["service"] = _Db(fail=("fee_invoices",))
    client = {"id": CLIENT, "firm_id": FIRM, "client_name": "Acme", "status": "active", "pan": None}
    with patch("routers.clients.client_repo") as repo, patch("routers.clients.log_event") as log, \
         patch("routers.clients.can_access_client", return_value=True):
        repo.find_by_id.return_value = client
        with pytest.raises(HTTPException) as refused:
            delete_client(client_id=CLIENT, current_user=PARTNER)
    assert refused.value.status_code == 503
    repo.soft_delete.assert_not_called()
    log.assert_not_called()


def test_a_completed_compliance_record_is_not_one_that_is_not_yet_filed(world):
    """Filed and Completed are the two settled states (`domain/practice/compliance_overdue`): the blocker counts the others."""
    import routers.clients as rc
    rc.compliance_records_repo.find_all.return_value = [
        {"id": 1, "status": "Filed"}, {"id": 2, "status": "Completed"}, {"id": 3, "status": "In Progress"},
        {"id": 4, "status": "Overdue"}]
    blockers = _blockers()
    assert "2 active compliance record(s) not yet filed" in blockers, blockers
