"""
R3.1b — routers/income_tax.py's capital-gains endpoints.

Proves: the calculator endpoint validates input and delegates to
domain.income_tax.capital_gains_engine (no client-supplied gain_type/
tax_rate/indexed_cost is ever trusted -- the create-record request model
doesn't even accept those fields); list/create/delete are firm-scoped, same
IDOR-backstop discipline as every other Tier 2/3 tenancy fix this session.
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
def cg_app(monkeypatch):
    import routers.income_tax as income_tax_mod
    db = FakeDB()
    monkeypatch.setattr(income_tax_mod, "_db", lambda: db)
    app = FastAPI()
    app.include_router(income_tax_mod.router)
    return app, db


COMPUTE_BODY = {
    "asset_type": "equity",
    "purchase_date": "2020-01-01",
    "sale_date": "2023-01-01",
    "purchase_cost_paise": 10_000_000,   # ₹1,00,000
    "sale_value_paise": 40_000_000,      # ₹4,00,000
    "improvement_cost_paise": 0,
}


class TestComputeEndpoint:
    def test_computes_equity_ltcg_correctly(self, cg_app):
        app, _db = cg_app
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/capital-gains/compute", json=COMPUTE_BODY)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["gain_type"] == "LTCG"
        assert data["section_ref"] == "Section 112A"
        assert data["tax_rate_percent"] == 12.5

    def test_rejects_unknown_asset_type(self, cg_app):
        app, _db = cg_app
        body = {**COMPUTE_BODY, "asset_type": "bitcoin_futures"}
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/capital-gains/compute", json=body)
        assert r.status_code == 422

    def test_rejects_sale_before_purchase(self, cg_app):
        app, _db = cg_app
        body = {**COMPUTE_BODY, "purchase_date": "2023-01-01", "sale_date": "2020-01-01"}
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/capital-gains/compute", json=body)
        assert r.status_code == 422

    def test_does_not_persist_anything(self, cg_app):
        app, db = cg_app
        _client_for(app, PARTNER_F1).post("/api/income-tax/capital-gains/compute", json=COMPUTE_BODY)
        assert db.rows("capital_gains") == []


class TestCreateEndpoint:
    def test_server_computes_gain_type_and_tax_rate_not_trusted_from_client(self, cg_app):
        """The request model has no gain_type/tax_rate_percent/indexed_cost_paise
        field at all -- proving there is no way for a caller to supply and
        have persisted a value the engine itself didn't compute."""
        app, db = cg_app
        body = {
            "client_id": "C1", "asset_description": "Reliance Industries — 100 shares",
            "asset_type": "equity_shares",
            "purchase_date": "2020-01-01", "sale_date": "2023-01-01",
            "purchase_cost_paise": 10_000_000, "sale_value_paise": 40_000_000,
        }
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/capital-gains", json=body)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["gain_type"] == "LTCG"
        assert data["tax_rate_percent"] == 12.5
        row = db.rows("capital_gains")[0]
        assert row["gain_type"] == "LTCG"
        assert row["tax_rate_percent"] == 12.5
        assert row["firm_id"] == "F1"

    def test_rejects_calculator_only_asset_type_for_register(self, cg_app):
        """'unlisted'/'vda'/'gold'/'debt_mf' are calculator-only types (the
        real table's CHECK constraint doesn't accept them) -- must 422, not
        succeed with a value the DB would then reject at insert time."""
        app, _db = cg_app
        body = {
            "client_id": "C1", "asset_description": "Some crypto",
            "asset_type": "vda",
            "purchase_date": "2023-01-01", "sale_date": "2024-01-01",
            "purchase_cost_paise": 10_000_000, "sale_value_paise": 40_000_000,
        }
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/capital-gains", json=body)
        assert r.status_code == 422


class TestListAndDeleteAreFirmScoped:
    def test_list_only_returns_own_firm(self, cg_app):
        app, db = cg_app
        db.seed("capital_gains", {"firm_id": "F1", "client_id": "C1", "asset_description": "F1 asset"})
        db.seed("capital_gains", {"firm_id": "F2", "client_id": "C1", "asset_description": "F2 asset"})
        r = _client_for(app, PARTNER_F1).get("/api/income-tax/capital-gains", params={"client_id": "C1"})
        assert r.status_code == 200
        rows = r.json()["data"]
        assert len(rows) == 1
        assert rows[0]["asset_description"] == "F1 asset"

    def test_delete_cross_firm_is_404(self, cg_app):
        app, db = cg_app
        row = db.seed("capital_gains", {"firm_id": "F1", "client_id": "C1", "asset_description": "F1 asset"})
        r = _client_for(app, PARTNER_F2).delete(f"/api/income-tax/capital-gains/{row['id']}")
        assert r.status_code == 404
        assert len(db.rows("capital_gains")) == 1  # untouched

    def test_delete_own_firm_succeeds(self, cg_app):
        app, db = cg_app
        row = db.seed("capital_gains", {"firm_id": "F1", "client_id": "C1", "asset_description": "F1 asset"})
        r = _client_for(app, PARTNER_F1).delete(f"/api/income-tax/capital-gains/{row['id']}")
        assert r.status_code == 200
