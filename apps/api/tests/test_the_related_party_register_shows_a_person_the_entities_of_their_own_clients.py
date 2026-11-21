"""POST-A-544: a member of staff who is not firm-wide sees the related-party entities of their own clients, and no others.

WHAT WAS WRONG
    The register of people and companies the firm knows (`entities`) has no client column, by a recorded design: one shared
    register is what makes cross-client match detection possible. So every member of staff read all of it, with PAN and
    email: an Executive assigned to one client could read the directors and shareholders of every other client of the firm.
    An entity's ROLES were already narrowed; the entity was not.

THE RULE
    For a caller who is not firm-wide, an entity is visible if it holds a role at one of the caller's clients, or holds no
    role at all (so that somebody who has just created one can still attach it). A hidden entity is ABSENT: not in the list,
    404 by id in the words a missing one gets, not the other end of an edge, and not something a role, a loan or a property
    can be attached to. A PAN a hidden entity holds cannot be added again (one PAN is one entity), and the refusal says who
    can attach it and nothing else.

HOW IT IS PROVEN
    The real route functions, against the database double the register's own window test uses (it answers at most 1,000 rows
    to one request and says nothing when it cuts one short) and against the in-memory store, with a caller assigned to one
    client. Against the code before this change every assertion about a hidden entity fails: the functions did not ask.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.relationships as rel
from tests.e2e_harness import FakeDB
from tests.test_the_entity_register_and_the_lead_pipeline_read_windows_the_server_will_honour import _CappedDB

FIRM = "FIRM-A"
MINE, THEIRS = "CLIENT-MINE", "CLIENT-THEIRS"
EXECUTIVE = {"firm_id": FIRM, "id": "u-exec", "auth_user_id": "a-exec", "role": "Executive"}
PARTNER = {"firm_id": FIRM, "id": "u-partner", "auth_user_id": "a-partner", "role": "Partner"}

# Four entities: one at my client, one at somebody else's, one at both, one attached to nothing yet.
ENTITIES = [
    {"id": "e-mine", "firm_id": FIRM, "full_name": "Asha (my client's director)", "entity_type": "Individual", "pan": "AAAPA1111A"},
    {"id": "e-theirs", "firm_id": FIRM, "full_name": "Bharat (another client's director)", "entity_type": "Individual", "pan": "BBBPB2222B"},
    {"id": "e-both", "firm_id": FIRM, "full_name": "Chitra (a director at both)", "entity_type": "Individual", "pan": "CCCPC3333C"},
    {"id": "e-new", "firm_id": FIRM, "full_name": "Dev (attached to nothing yet)", "entity_type": "Individual", "pan": None},
]
ROLES = [
    {"id": "r-1", "firm_id": FIRM, "entity_id": "e-mine", "client_id": MINE, "role": "Director"},
    {"id": "r-2", "firm_id": FIRM, "entity_id": "e-theirs", "client_id": THEIRS, "role": "Director"},
    {"id": "r-3", "firm_id": FIRM, "entity_id": "e-both", "client_id": MINE, "role": "Director"},
    {"id": "r-4", "firm_id": FIRM, "entity_id": "e-both", "client_id": THEIRS, "role": "Director"},
]
EDGES = [
    {"id": "x-1", "firm_id": FIRM, "from_entity_id": "e-mine", "to_entity_id": "e-both", "relationship_type": "spouse"},
    {"id": "x-2", "firm_id": FIRM, "from_entity_id": "e-mine", "to_entity_id": "e-theirs", "relationship_type": "sibling"},
]


def _scope(monkeypatch):
    """The assignment scope a real deployment computes: a Partner sees every client, the Executive one. (The mock-mode
    scope is permissive on purpose, so the narrowing is given a real answer here.)"""
    monkeypatch.setattr(rel, "effective_client_ids", lambda user: None if user["role"] == "Partner" else {MINE})
    monkeypatch.setattr(rel, "filter_by_client",
                        lambda user, rows, key="client_id": rows if user["role"] == "Partner" else [r for r in rows if r.get(key) == MINE])


@pytest.fixture(params=["database", "memory"])
def register(request, monkeypatch):
    """The same facts behind both paths the routes have: a database, and the in-memory store of mock mode."""
    _scope(monkeypatch)
    if request.param == "database":
        db = FakeDB()
        for row in ENTITIES:
            db.seed("entities", dict(row))
        for row in ROLES:
            db.seed("entity_roles", dict(row))
        for row in EDGES:
            db.seed("entity_relationships", dict(row))
            db.seed("entity_to_entity_relationships", dict(row))
        monkeypatch.setattr(rel, "_db", lambda: db)
        monkeypatch.setattr(rel, "privileged_for", lambda d: d)
    else:
        monkeypatch.setattr(rel, "_db", lambda: None)
        monkeypatch.setattr(rel, "_MOCK_ENTITIES", [dict(r) for r in ENTITIES])
        monkeypatch.setattr(rel, "_MOCK_ENTITY_ROLES", [dict(r) for r in ROLES])
        monkeypatch.setattr(rel, "_MOCK_RELATIONSHIPS", [dict(r) for r in EDGES])
        monkeypatch.setattr(rel, "_MOCK_ENTITY_TO_ENTITY_RELS", [dict(r) for r in EDGES])
    return request.param


def _listed(user, **kw):
    args = {"entity_type": None, "search": None, "limit": 50, "offset": 0, "current_user": user, **kw}
    return rel.list_entities(**args)["data"]


# ── the list ─────────────────────────────────────────────────────────────────

def test_the_list_is_the_callers_clients_entities_and_the_unattached_ones(register):
    out = _listed(EXECUTIVE)
    assert {e["id"] for e in out["entities"]} == {"e-mine", "e-both", "e-new"}
    assert out["scoped"] is True, "the answer does not say it is part of the register"
    assert out["returned"] == 3 and out["has_more"] is False


def test_a_partner_reads_the_whole_register_and_is_told_it_is_whole(register):
    out = _listed(PARTNER)
    assert {e["id"] for e in out["entities"]} == {"e-mine", "e-theirs", "e-both", "e-new"}
    assert out["scoped"] is False


def test_a_search_for_a_hidden_entitys_pan_finds_nothing(register):
    assert _listed(EXECUTIVE, search="BBBPB2222B")["entities"] == []
    assert [e["id"] for e in _listed(PARTNER, search="BBBPB2222B")["entities"]] == ["e-theirs"]


def test_the_window_is_cut_after_the_narrowing_so_a_page_is_full_and_says_when_more_exist(monkeypatch):
    """Sixty entities in name order, every second one at a client the caller may not reach. A window of 20 is 20 VISIBLE
    rows with more to come, and the next window starts after them: a window cut before the narrowing would come back ten
    long and say it was the end."""
    _scope(monkeypatch)
    db = FakeDB()
    for i in range(60):
        db.seed("entities", {"id": f"e-{i:03d}", "firm_id": FIRM, "full_name": f"Entity {i:03d}", "entity_type": "Individual"})
        db.seed("entity_roles", {"id": f"r-{i:03d}", "firm_id": FIRM, "entity_id": f"e-{i:03d}",
                                 "client_id": MINE if i % 2 == 0 else THEIRS, "role": "Director"})
    capped = _CappedDB(db)
    monkeypatch.setattr(rel, "_db", lambda: capped)
    monkeypatch.setattr(rel, "privileged_for", lambda d: d)
    first = _listed(EXECUTIVE, limit=20)
    assert first["returned"] == 20 and first["has_more"] is True
    second = _listed(EXECUTIVE, limit=20, offset=20)
    assert second["returned"] == 10 and second["has_more"] is False
    ids = [e["id"] for e in first["entities"] + second["entities"]]
    assert ids == [f"e-{i:03d}" for i in range(0, 60, 2)], "a visible entity was skipped, repeated or out of name order"


# ── one entity, by id ────────────────────────────────────────────────────────

def test_a_hidden_entity_is_not_found_by_id_in_the_words_a_missing_one_gets(register):
    with pytest.raises(HTTPException) as hidden:
        rel.get_entity("e-theirs", current_user=EXECUTIVE)
    with pytest.raises(HTTPException) as missing:
        rel.get_entity("e-nobody", current_user=EXECUTIVE)
    assert (hidden.value.status_code, hidden.value.detail) == (missing.value.status_code, missing.value.detail) == (404, "Entity not found")
    assert rel.get_entity("e-theirs", current_user=PARTNER)["data"]["id"] == "e-theirs"


def test_an_entity_at_both_clients_opens_with_only_the_callers_role_and_no_edge_to_a_hidden_one(register):
    data = rel.get_entity("e-mine", current_user=EXECUTIVE)["data"]
    assert [e["id"] for e in data["relationships"]] == ["x-1"], "an edge naming a hidden entity was shown"
    both = rel.get_entity("e-both", current_user=EXECUTIVE)["data"]
    assert {r["client_id"] for r in both["roles"]} == {MINE}


@pytest.mark.parametrize("lister", ["list_relationships", "list_entity_to_entity_relationships"])
def test_the_edge_lists_drop_an_edge_to_a_hidden_entity_and_refuse_a_hidden_one(register, lister):
    assert [e["id"] for e in getattr(rel, lister)(entity_id="e-mine", current_user=EXECUTIVE)["data"]] == ["x-1"]
    assert {e["id"] for e in getattr(rel, lister)(entity_id="e-mine", current_user=PARTNER)["data"]} == {"x-1", "x-2"}
    with pytest.raises(HTTPException) as exc:
        getattr(rel, lister)(entity_id="e-theirs", current_user=EXECUTIVE)
    assert exc.value.status_code == 404


# ── the doors that name an entity ────────────────────────────────────────────

def test_nothing_can_be_attached_to_a_hidden_entity(register, monkeypatch):
    monkeypatch.setattr(rel, "assert_client_access", lambda *a, **k: None)
    attempts = {
        "a role": lambda: rel.add_entity_role("e-theirs", rel.EntityRoleIn(client_id=MINE, role_type="Director"), current_user=EXECUTIVE),
        "an edit": lambda: rel.update_entity("e-theirs", rel.EntityUpdateIn(full_name="Renamed"), current_user=EXECUTIVE),
        "an edge from it": lambda: rel.create_relationship(
            rel.RelationshipIn(from_entity_id="e-theirs", to_entity_id="e-mine", relationship_type="spouse"), current_user=EXECUTIVE),
        "an edge to it": lambda: rel.create_relationship(
            rel.RelationshipIn(from_entity_id="e-mine", to_entity_id="e-theirs", relationship_type="spouse"), current_user=EXECUTIVE),
        "a loan": lambda: rel.create_loan(
            rel.LoanIn(client_id=MINE, entity_id="e-theirs", loan_type="to_director", principal_paise=100, interest_rate=1.0),
            current_user=EXECUTIVE),
        "a property": lambda: rel.create_property(
            rel.PropertyIn(client_id=MINE, entity_id="e-theirs", address="1 Road", property_type="land", cost_paise=100),
            current_user=EXECUTIVE),
    }
    for what, attempt in attempts.items():
        with pytest.raises(HTTPException) as exc:
            attempt()
        assert exc.value.status_code == 404, f"{what} was attached to an entity the caller may not see: {exc.value.detail}"


def test_a_pan_a_hidden_entity_holds_is_refused_with_who_can_attach_it_and_nothing_else(register):
    with pytest.raises(HTTPException) as exc:
        rel.create_entity(rel.EntityIn(full_name="Bharat again", entity_type="Individual", pan="BBBPB2222B"), current_user=EXECUTIVE)
    assert exc.value.status_code == 409 and exc.value.detail == rel.PAN_HELD_OUT_OF_REACH
    for told in ("Bharat", THEIRS, "e-theirs"):
        assert told not in exc.value.detail, "the refusal names the hidden entity or its client"
    assert "Partner" in exc.value.detail


def test_an_entity_just_created_is_still_visible_to_whoever_created_it(register, monkeypatch):
    """Between creating an entity and attaching it, it has no role. It stays visible, or the person who typed it loses it."""
    monkeypatch.setattr(rel.timeline_service, "log", lambda *a, **k: None)
    created = rel.create_entity(rel.EntityIn(full_name="Esha (new)", entity_type="Individual"), current_user=EXECUTIVE)["data"]
    assert created["id"] in {e["id"] for e in _listed(EXECUTIVE)["entities"]}
    assert rel.get_entity(created["id"], current_user=EXECUTIVE)["data"]["full_name"] == "Esha (new)"


# ── the reading of the roles is privileged, and names the firm ───────────────

def test_the_roles_are_read_with_the_privileged_client_and_the_firm_is_named(monkeypatch):
    """The caller's own read of the roles is narrowed by the database to their clients, so it cannot tell "no role anywhere"
    from "roles only where I may not look". The read must be the privileged one, and it must name the firm."""
    _scope(monkeypatch)
    asked = []
    caller_db, privileged_db = FakeDB(), FakeDB()
    caller_db.seed("entities", dict(ENTITIES[1]))                     # the caller's client sees the entity ...
    privileged_db.seed("entity_roles", dict(ROLES[1]))                # ... and only the privileged read sees its role
    privileged_db.seed("entity_roles", {**ROLES[1], "id": "r-other-firm", "firm_id": "FIRM-B", "entity_id": "e-mine", "client_id": "X"})
    monkeypatch.setattr(rel, "_db", lambda: caller_db)
    monkeypatch.setattr(rel, "privileged_for", lambda d: asked.append(d) or privileged_db)
    assert _listed(EXECUTIVE)["entities"] == [], "an entity whose only role the caller cannot read was shown as unattached"
    assert asked and all(d is caller_db for d in asked)
    assert rel._hidden_entity_ids(caller_db, EXECUTIVE) == {"e-theirs"}, "another firm's role decided this firm's answer"
