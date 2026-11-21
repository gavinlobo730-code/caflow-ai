"""POST-A-543, the safety step: four reads that every member of staff could make now ask the person who should.

WHAT WAS WRONG
    The owner decided on 21-11-2026 that one rule decides what a person sees and can open: the permission pairs a Partner
    ticks. Before the menu could follow those pairs, every firm-level screen was mapped to the pair its reads ask and to
    whether its list is limited to the caller's assigned clients. Four reads were open to every member of staff, a
    Reviewer included, and were not limited:

      * the PIPELINE: every lead of the firm, read with `client:read`. A lead has no client, so no assignment narrows it;
      * the ENGAGEMENT LETTERS, fees and all, read with `client:read` although an `engagement` pair (Manager and above)
        had been declared for exactly this and no route used it;
      * the WORKFLOW STATISTICS: counts over every run of the firm, read with `task:read`;
      * the RELATED-PARTY LOANS list and the section 185 report: with no client named, the server's own code selected by
        firm only and left the narrowing to the database's rule.

WHAT THESE TESTS HOLD
    The owner's decisions (the pipeline and the engagement letters are a Partner's and a Manager's by default, and
    anybody's a Partner ticks them for), read off the permission table and off the ROUTE TABLE, so a new route under
    either address that asks the old pair fails here; that converting a lead still needs the right to create a client;
    and that the two related-party reads narrow before they answer, count or total.
"""
from __future__ import annotations

import pytest

import main
from core import permissions as perms

STAFF = ("Partner", "Manager", "Executive", "Reviewer")


def _pairs_by_route(prefix: str) -> dict[str, set[tuple[str, str]]]:
    """{'METHOD path': {(resource, action), ...}} for every mounted route under `prefix`, read off the route table."""
    out: dict[str, set[tuple[str, str]]] = {}
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith(prefix):
            continue
        pairs = set()
        for dep in getattr(getattr(route, "dependant", None), "dependencies", []) or []:
            name = getattr(getattr(dep, "call", None), "__name__", "")
            if name.startswith("rbac_"):
                resource, action = name[len("rbac_"):].rsplit("_", 1)
                pairs.add((resource, action))
        for method in sorted((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}):
            out[f"{method} {path}"] = pairs
    return out


# ── the permission table: who holds each pair to start with ──────────────────

@pytest.mark.parametrize("resource,action", [
    ("pipeline", "read"), ("pipeline", "write"), ("engagement", "read"), ("engagement", "write"), ("analytics", "read"),
])
def test_each_pair_is_a_partners_and_a_managers_by_default(resource, action):
    assert {role for role in STAFF if perms.can(role, resource, action)} == {"Partner", "Manager"}


def test_a_partner_can_tick_each_pair_for_one_person_and_only_that_pair_moves():
    executive = {"role": "Executive", "permission_overrides": {"pipeline:read": True}}
    assert perms.can_user(executive, "pipeline", "read") is True
    assert perms.can_user(executive, "pipeline", "write") is False
    assert perms.can_user(executive, "engagement", "read") is False
    assert perms.can_user(executive, "client", "write") is False
    blocked_manager = {"role": "Manager", "permission_overrides": {"engagement:read": False}}
    assert perms.can_user(blocked_manager, "engagement", "read") is False
    assert perms.can_user(blocked_manager, "pipeline", "read") is True


# ── the route table: which pair each door asks ───────────────────────────────

def test_every_leads_route_asks_the_pipeline_pair_and_none_asks_the_clients_pair():
    routes = _pairs_by_route("/api/lifecycle/leads")
    assert len(routes) >= 4, f"the leads routes have moved: {sorted(routes)}"
    for door, pairs in routes.items():
        wanted = "read" if door.startswith("GET ") else "write"
        assert ("pipeline", wanted) in pairs, f"{door} asks {sorted(pairs)}"
        if door.endswith("/convert"):
            continue  # asked BESIDE the right to create a client: the next test
        assert pairs == {("pipeline", wanted)}, f"{door} asks {sorted(pairs)}"


def test_every_engagement_letter_route_asks_the_engagement_pair():
    routes = _pairs_by_route("/api/engagement-letters")
    assert len(routes) >= 15, f"the engagement-letter routes have moved: {sorted(routes)}"
    for door, pairs in routes.items():
        wanted = "read" if door.startswith("GET ") else "write"
        assert pairs == {("engagement", wanted)}, f"{door} asks {sorted(pairs)}"


def test_the_public_signing_door_is_not_behind_a_staff_pair():
    """The client who signs an engagement letter has no login: that door is a bearer link and asks no staff pair. It is
    asserted so that moving the staff routes to the engagement pair is seen not to have touched it."""
    routes = _pairs_by_route("/api/public/engagement-letters")
    assert routes, "the public signing routes are gone"
    assert all(pairs == set() for pairs in routes.values()), routes


def test_the_workflow_statistics_ask_the_analytics_pair():
    assert _pairs_by_route("/api/workflows/analytics") == {"GET /api/workflows/analytics": {("analytics", "read")}}


# ── converting a lead still needs the right to create a client ───────────────

def test_converting_a_lead_asks_the_pipeline_pair_and_the_right_to_create_a_client():
    """Converting a lead creates a client. The route asked `client:write` alone before; the pipeline pair was added beside
    it and not in its place, so somebody ticked for the pipeline only cannot make a client through this door."""
    routes = _pairs_by_route("/api/lifecycle/leads/{lead_id}/convert")
    assert routes == {"POST /api/lifecycle/leads/{lead_id}/convert": {("pipeline", "write"), ("client", "write")}}
    only_pipeline = {"role": "Executive", "permission_overrides": {"pipeline:read": True, "pipeline:write": True}}
    assert perms.can_user(only_pipeline, "pipeline", "write") is True
    assert perms.can_user(only_pipeline, "client", "write") is False, "the pipeline tick alone would pass both guards"


def test_a_person_ticked_for_the_pipeline_alone_is_refused_at_the_door_when_converting():
    from fastapi.testclient import TestClient

    from core.auth import get_current_user

    only_pipeline = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1", "role": "Executive", "email": "e@f",
                     "permission_overrides": {"pipeline:read": True, "pipeline:write": True}}
    main.app.dependency_overrides[get_current_user] = lambda: only_pipeline
    try:
        res = TestClient(main.app, raise_server_exceptions=False).post("/api/lifecycle/leads/L-1/convert", json={"name": "New Client"})
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
    assert res.status_code == 403, res.text


# ── the related-party loans: narrowed before they answer, count or total ─────

@pytest.fixture
def loans(monkeypatch):
    import routers.relationships as rel

    monkeypatch.setattr(rel, "_db", lambda: None)
    rows = [
        {"id": "L-A", "firm_id": "F1", "client_id": "MINE", "principal_paise": 1_00_000, "section_185_flagged": True},
        {"id": "L-B", "firm_id": "F1", "client_id": "NOT-MINE", "principal_paise": 9_00_000, "section_185_flagged": True},
        {"id": "L-C", "firm_id": "F2", "client_id": "OTHER-FIRM", "principal_paise": 5_00_000, "section_185_flagged": True},
    ]
    monkeypatch.setattr(rel, "_MOCK_LOANS", rows)
    # The mock path is permissive about assignments, so the narrowing is given a person assigned to one client.
    monkeypatch.setattr(rel, "filter_by_client",
                        lambda user, items, key="client_id": [i for i in items if i.get(key) in user["mine"]])
    return rel


def test_the_loans_list_with_no_client_named_is_the_callers_clients_only(loans):
    user = {"firm_id": "F1", "role": "Executive", "mine": {"MINE"}}
    res = loans.list_loans(client_id=None, flagged_only=False, current_user=user)
    assert [row["id"] for row in res["data"]] == ["L-A"]
    partner_like = {"firm_id": "F1", "role": "Partner", "mine": {"MINE", "NOT-MINE"}}
    assert [row["id"] for row in loans.list_loans(client_id=None, flagged_only=False, current_user=partner_like)["data"]] == ["L-A", "L-B"]


def test_the_section_185_report_counts_and_totals_only_what_the_caller_may_see(loans):
    user = {"firm_id": "F1", "role": "Executive", "mine": {"MINE"}}
    data = loans.section_185_report(client_id=None, current_user=user)["data"]
    assert [row["id"] for row in data["flagged_loans"]] == ["L-A"]
    assert data["count"] == 1 and data["total_principal_paise"] == 1_00_000, \
        "the count or the total still includes a client the caller is not assigned to"
