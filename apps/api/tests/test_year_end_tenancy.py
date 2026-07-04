"""
Year-end workflow tenancy regression tests (Tier 2 R2.1, same bug class as
R2.4's F1/F4 IDOR fixes).

Two real gaps found while repairing the year-end schema (F9):

1. routers/year_end_checklist.py's list_checklist/update_checklist_item never
   checked that engagement_id belonged to the caller's firm at all -- any
   authenticated year-end user could read/mutate another firm's checklist by
   guessing an engagement_id.
2. routers/year_end_mappings.py's get_mappings accepted a client-supplied
   ?firm_id= query param and used it verbatim, with no ownership check --
   a direct, trivial cross-tenant read of another firm's Schedule III account
   mappings.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

PARTNER_F1 = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p1@f1.test"}
PARTNER_F2 = {"id": "u2", "firm_id": "F2", "role": "Partner", "email": "p2@f2.test"}


def _client_for(app: FastAPI, user: dict) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def checklist_app(monkeypatch):
    import routers.year_end_checklist as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(mod.router)
    return app, db


def test_list_checklist_cross_firm_is_404(checklist_app):
    app, db = checklist_app
    eng = db.seed("year_end_engagements", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    r = _client_for(app, PARTNER_F2).get(f"/year-end/{eng['id']}/checklist")
    assert r.status_code == 404
    assert db.rows("year_end_checklists") == []  # never auto-initialized for the attacker


def test_list_checklist_own_firm_auto_initializes(checklist_app):
    app, db = checklist_app
    eng = db.seed("year_end_engagements", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    r = _client_for(app, PARTNER_F1).get(f"/year-end/{eng['id']}/checklist")
    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 12
    assert all(i["firm_id"] == "F1" for i in items)  # F9 fix: firm_id now populated


def test_update_checklist_item_cross_firm_is_404(checklist_app):
    app, db = checklist_app
    eng = db.seed("year_end_engagements", {"firm_id": "F1", "client_id": "C1", "status": "draft"})
    item = db.seed("year_end_checklists", {"engagement_id": eng["id"], "firm_id": "F1", "status": "pending"})
    r = _client_for(app, PARTNER_F2).patch(
        f"/year-end/{eng['id']}/checklist/{item['id']}", json={"status": "complete"})
    assert r.status_code == 404
    assert db.rows("year_end_checklists")[0]["status"] == "pending"  # untouched


@pytest.fixture
def mappings_app(monkeypatch):
    import routers.year_end_mappings as mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(mod.router)
    return app, db


def test_get_mappings_ignores_client_supplied_firm_id(mappings_app):
    app, db = mappings_app
    db.seed("account_group_mappings", {"firm_id": "F1", "account_id": "A1", "schedule_line": "cash_and_bank"})
    db.seed("account_group_mappings", {"firm_id": "F2", "account_id": "A2", "schedule_line": "trade_payables"})

    # Attacker is a Partner of F1 trying to read F2's mappings via ?firm_id=F2.
    r = _client_for(app, PARTNER_F1).get("/year-end/mappings", params={"firm_id": "F2"})
    assert r.status_code == 200
    rows = r.json()["data"]
    # Must reflect ONLY the caller's own firm (F1), never the requested F2.
    assert all(row["firm_id"] == "F1" for row in rows)
    assert not any(row["firm_id"] == "F2" for row in rows)
