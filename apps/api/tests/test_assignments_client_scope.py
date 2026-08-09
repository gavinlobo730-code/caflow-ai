"""
Client-assignment scope on the assignments router — M3 assignment
administration, the surface that decides what everyone ELSE can see.

This router mounts the MFA guard, not main.py's mount-level client guard, so
nothing was checking client_id for it at all.

list_client_assignments (assignment:read = Manager+) let a Manager enumerate
the staff roster of any client in the firm. list_user_assignments was the
sharper one: it is addressed by a STAFF user_id, so there is no client_id for
assert_client_access to gate — a Manager could pass a colleague's user_id and
read back that person's ENTIRE client book, which is precisely the "one manager
cannot see another manager's book" decision core.authz's _FIRMWIDE_ROLES is
built around. It is narrowed with effective_client_ids (None for the Partner,
who still sees the full list) rather than refused outright, so the legitimate
"who else works on MY clients" question still answers.

create/bulk/remove are Partner-only by RBAC — the sole firm-wide role — so
their assert_client_access can never deny a real caller today; it is the
fail-closed default for if assignment administration is ever opened to Manager.
"""
import pytest
from fastapi import HTTPException

import routers.assignments as asg

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}
PARTNER = {"id": "p1", "firm_id": FIRM, "auth_user_id": "p1", "role": "Partner"}


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

    monkeypatch.setattr(asg, "assert_client_access", _assert)
    return seen


@pytest.fixture
def scoped(monkeypatch):
    """effective_client_ids: {MINE} for a Manager, None (firm-wide) for a
    Partner — the real core.authz behaviour, without a database."""
    monkeypatch.setattr(asg, "effective_client_ids",
                        lambda user: None if user.get("role") == "Partner" else {MINE})


# ══════════════════════════════════════════════════════════════════════════════
# list_user_assignments — the cross-book read
# ══════════════════════════════════════════════════════════════════════════════

def test_a_manager_cannot_read_a_colleagues_whole_client_book(scoped, monkeypatch):
    monkeypatch.setattr(asg.assignment_repo, "list_for_user",
                        lambda firm_id, user_id: [MINE, THEIRS])
    out = asg.list_user_assignments("some-other-staff-member", current_user=USER)
    assert out["data"]["client_ids"] == [MINE]


def test_a_manager_still_sees_the_shared_clients(scoped, monkeypatch):
    """The legitimate question — 'who else works on MY clients' — must keep
    answering; this is a narrowing, not a refusal."""
    monkeypatch.setattr(asg.assignment_repo, "list_for_user",
                        lambda firm_id, user_id: [MINE])
    out = asg.list_user_assignments("colleague", current_user=USER)
    assert out["data"] == {"user_id": "colleague", "client_ids": [MINE]}


def test_a_partner_still_sees_the_whole_book(scoped, monkeypatch):
    monkeypatch.setattr(asg.assignment_repo, "list_for_user",
                        lambda firm_id, user_id: [MINE, THEIRS])
    out = asg.list_user_assignments("colleague", current_user=PARTNER)
    assert out["data"]["client_ids"] == [MINE, THEIRS]


def test_narrowing_compares_as_strings(scoped, monkeypatch):
    """client_id is a UUID column — the repo may hand back a non-str. The
    filter must not silently drop everything because of a type mismatch."""
    class _Uuidish(str):
        pass

    monkeypatch.setattr(asg.assignment_repo, "list_for_user",
                        lambda firm_id, user_id: [_Uuidish(MINE)])
    out = asg.list_user_assignments("colleague", current_user=USER)
    assert out["data"]["client_ids"] == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# list_client_assignments — client_id in the path
# ══════════════════════════════════════════════════════════════════════════════

def test_reading_another_clients_staff_roster_is_refused(deny, monkeypatch):
    called = []
    monkeypatch.setattr(asg.assignment_repo, "list_for_client",
                        lambda firm_id, cid: called.append(cid) or [])
    with pytest.raises(HTTPException) as e:
        asg.list_client_assignments(THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert not called


def test_reading_your_own_clients_staff_roster_still_works(deny, monkeypatch):
    monkeypatch.setattr(asg.assignment_repo, "list_for_client",
                        lambda firm_id, cid: ["u1", "u2"])
    out = asg.list_client_assignments(MINE, current_user=USER)
    assert out["data"]["user_ids"] == ["u1", "u2"]
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# create / bulk / remove — Partner-only, guarded fail-closed
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_an_assignment_to_an_out_of_scope_client_is_refused(deny, monkeypatch):
    monkeypatch.setattr(asg, "_validate_user_in_firm", lambda *a: None)
    monkeypatch.setattr(asg, "_validate_client_in_firm", lambda *a: None)
    created = []
    monkeypatch.setattr(asg.assignment_repo, "create",
                        lambda *a: created.append(a) or {})
    with pytest.raises(HTTPException) as e:
        asg.create_assignment(asg.AssignmentBody(user_id="u2", client_id=THEIRS),
                              current_user=USER)
    assert e.value.status_code == 404
    assert not created   # refused BEFORE the grant was written


def test_creating_an_assignment_in_scope_still_works(deny, monkeypatch):
    monkeypatch.setattr(asg, "_validate_user_in_firm", lambda *a: None)
    monkeypatch.setattr(asg, "_validate_client_in_firm", lambda *a: None)
    monkeypatch.setattr(asg.assignment_repo, "create", lambda *a: {"id": "asg-1"})
    monkeypatch.setattr(asg, "log_event", lambda *a, **kw: None)
    out = asg.create_assignment(asg.AssignmentBody(user_id="u2", client_id=MINE),
                                current_user=USER)
    assert out["data"]["id"] == "asg-1"
    assert deny == [MINE]


def test_a_bulk_grant_stops_at_the_first_out_of_scope_client(deny, monkeypatch):
    monkeypatch.setattr(asg, "_validate_user_in_firm", lambda *a: None)
    monkeypatch.setattr(asg, "_validate_client_in_firm", lambda *a: None)
    created = []
    monkeypatch.setattr(asg.assignment_repo, "create",
                        lambda firm, uid, cid: created.append(cid) or {"id": cid})
    with pytest.raises(HTTPException):
        asg.create_bulk(asg.BulkAssignmentBody(user_id="u2", client_ids=[MINE, THEIRS]),
                        current_user=USER)
    assert created == [MINE]   # the in-scope one landed, the refused one did not


def test_removing_an_assignment_on_an_out_of_scope_client_is_refused(deny, monkeypatch):
    removed = []
    monkeypatch.setattr(asg.assignment_repo, "remove",
                        lambda firm, uid, cid: removed.append(cid) or True)
    with pytest.raises(HTTPException) as e:
        asg.remove_assignment(user_id="u2", client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert not removed


def test_removing_an_assignment_in_scope_still_works(deny, monkeypatch):
    monkeypatch.setattr(asg.assignment_repo, "remove", lambda *a: True)
    monkeypatch.setattr(asg, "log_event", lambda *a, **kw: None)
    out = asg.remove_assignment(user_id="u2", client_id=MINE, current_user=USER)
    assert out["data"]["removed"] is True
    assert deny == [MINE]


def test_the_validator_does_not_carry_the_scope_check(monkeypatch):
    """_validate_client_in_firm is deliberately a plain firm/internal-client
    validator: it would still exist with the assignment check stripped out, so
    holding the guard there would let the scope sweep pass on its name alone.
    Pinned so nobody 'tidies' the check back into it."""
    import inspect
    src = inspect.getsource(asg._validate_client_in_firm)
    assert "assert_client_access" not in src.split('"""')[-1]
