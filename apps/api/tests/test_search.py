"""
Global search — H12 coverage for the extended entity sources.

The single GET /api/search endpoint now also searches leads, engagements,
tasks, documents and DSC records (in addition to clients/accounts/journals
covered by test_search_security.py). These tests run in mock mode and verify:

  - a seeded lead surfaces under category "leads"
  - a seeded engagement letter surfaces under category "engagements"
  - a short query (<2 chars) returns no results
  - every result item carries the canonical {id, category, title, subtitle, href}

Pattern mirrors test_search_security.py: a throwaway FastAPI app mounting only
the search router, with get_current_user overridden — no dependency on main.py.
The mock stores (_MOCK_LEADS, _MOCK_ENGAGEMENTS) are seeded and torn down by a
fixture so sibling tests are unaffected.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.search as search_mod
from routers.search import router as search_router
from core.auth import get_current_user
from routers.lifecycle import _MOCK_LEADS
from routers.engagement_letters import _MOCK_ENGAGEMENTS

FIRM_ID = "firm-search-0001"

# Partner ⇒ effective_client_ids returns None (firm-wide); avoids assignment setup.
USER = {"id": "u-search-1", "firm_id": FIRM_ID, "role": "Partner"}

# Unique tokens so matches cannot collide with mock tasks/documents/DSC/clients.
SEEDED_LEAD = {
    "id": "lead-search-1",
    "firm_id": FIRM_ID,
    "company_name": "Zentron Quartz Holdings",
    "contact_name": "Priya Nair",
    "email": "priya@zentron-quartz.example",
    "phone": "9000000001",
    "stage": "Lead",
}

SEEDED_ENGAGEMENT = {
    "id": "eng-search-1",
    "firm_id": FIRM_ID,
    "title": "Zentron Quartz GST Retainer",
    "engagement_number": "EL-2026-9001",
    "recipient_name": "Priya Nair",
    "status": "Sent",
    "client_id": None,
}


def _make_client():
    """Throwaway app with only the search router; clients source stubbed empty
    so results are isolated to the seeded leads/engagements."""
    app = FastAPI()
    app.include_router(search_router)
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(monkeypatch):
    # Keep clients out of results so assertions target the new sources only.
    monkeypatch.setattr(search_mod.client_repo, "find_all", lambda **kw: [])
    # Partner is firm-wide regardless, but pin it for clarity/robustness.
    monkeypatch.setattr(search_mod, "effective_client_ids", lambda u: None)

    _MOCK_LEADS.append(dict(SEEDED_LEAD))
    _MOCK_ENGAGEMENTS.append(dict(SEEDED_ENGAGEMENT))
    try:
        yield _make_client()
    finally:
        # Remove exactly what we appended; leave any pre-existing rows intact.
        for store, seeded in (
            (_MOCK_LEADS, SEEDED_LEAD),
            (_MOCK_ENGAGEMENTS, SEEDED_ENGAGEMENT),
        ):
            for row in [r for r in store if r.get("id") == seeded["id"]]:
                store.remove(row)


def test_lead_is_searchable(client):
    r = client.get("/api/search?q=Zentron").json()
    results = r["data"]["results"]
    leads = [x for x in results if x["category"] == "leads"]
    assert any(x["id"] == "lead-search-1" for x in leads)
    assert any(x["title"] == "Zentron Quartz Holdings" for x in leads)


def test_engagement_is_searchable(client):
    r = client.get("/api/search?q=Retainer").json()
    results = r["data"]["results"]
    engagements = [x for x in results if x["category"] == "engagements"]
    assert any(x["id"] == "eng-search-1" for x in engagements)


def test_lead_and_engagement_both_present_for_shared_token(client):
    # "Zentron Quartz" appears in both the lead and the engagement.
    r = client.get("/api/search?q=Zentron Quartz").json()
    cats = {x["category"] for x in r["data"]["results"]}
    assert "leads" in cats
    assert "engagements" in cats


def test_short_query_returns_empty(client):
    r = client.get("/api/search?q=a").json()
    assert r["data"]["results"] == []


def test_result_items_have_canonical_shape(client):
    r = client.get("/api/search?q=Zentron").json()
    results = r["data"]["results"]
    assert results, "expected at least one result"
    required = {"id", "category", "title", "subtitle", "href"}
    for item in results:
        assert required.issubset(item.keys()), f"missing keys in {item}"
