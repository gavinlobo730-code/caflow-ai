"""
R3.13a — routers/income_tax.py's advance-tax endpoints.

Proves: the compute endpoint validates input and delegates entirely to
domain.income_tax.advance_tax_interest_engine (no client-supplied
due_date/required_percent/interest is ever trusted -- the save request
model has no such fields, and due_date/required_percent are always derived
server-side from the FY's Section 208 schedule); save is firm-scoped.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

PARTNER_F1 = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p1@f1.test"}
PARTNER_F2 = {"id": "u2", "firm_id": "F2", "role": "Partner", "email": "p2@f2.test"}

L = 100_000 * 100
TAX = 10 * L


def _client_for(app: FastAPI, user: dict) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def at_app(monkeypatch):
    import routers.income_tax as income_tax_mod
    db = FakeDB()
    monkeypatch.setattr(income_tax_mod, "_db", lambda: db)
    app = FastAPI()
    app.include_router(income_tax_mod.router)
    return app, db


COMPUTE_BODY = {
    "fy": "2024-25",
    "estimated_tax_paise": TAX,
    "installments": [
        {"installment_number": 1, "paid_amount_paise": 0, "paid_date": None},
        {"installment_number": 2, "paid_amount_paise": 0, "paid_date": None},
        {"installment_number": 3, "paid_amount_paise": 0, "paid_date": None},
        {"installment_number": 4, "paid_amount_paise": 0, "paid_date": None},
    ],
}


class TestComputeEndpoint:
    def test_computes_full_shortfall_interest_when_nothing_paid(self, at_app):
        app, _db = at_app
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/advance-tax/compute", json=COMPUTE_BODY)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["section_ref"] == "Section 234C"
        assert len(data["installments"]) == 4
        assert data["total_interest_paise"] > 0
        inst4 = next(i for i in data["installments"] if i["installment_number"] == 4)
        assert inst4["interest_months"] == 1

    def test_paying_the_12_percent_trigger_avoids_installment_1_interest(self, at_app):
        """The old frontend formula had no trigger tolerance at all -- this
        is the headline behaviour it got wrong."""
        app, _db = at_app
        body = {**COMPUTE_BODY, "installments": [
            {"installment_number": 1, "paid_amount_paise": int(0.12 * TAX), "paid_date": "2024-06-15"},
            {"installment_number": 2, "paid_amount_paise": 0, "paid_date": None},
            {"installment_number": 3, "paid_amount_paise": 0, "paid_date": None},
            {"installment_number": 4, "paid_amount_paise": 0, "paid_date": None},
        ]}
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/advance-tax/compute", json=body)
        assert r.status_code == 200
        inst1 = next(i for i in r.json()["data"]["installments"] if i["installment_number"] == 1)
        assert inst1["is_short"] is False
        assert inst1["interest_paise"] == 0

    def test_rejects_duplicate_installment_number(self, at_app):
        app, _db = at_app
        body = {**COMPUTE_BODY, "installments": [
            {"installment_number": 1, "paid_amount_paise": 0},
            {"installment_number": 1, "paid_amount_paise": 0},
        ]}
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/advance-tax/compute", json=body)
        assert r.status_code == 422

    def test_rejects_future_paid_date(self, at_app):
        app, _db = at_app
        body = {**COMPUTE_BODY, "installments": [
            {"installment_number": 1, "paid_amount_paise": 1000, "paid_date": "2099-01-01"},
        ]}
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/advance-tax/compute", json=body)
        assert r.status_code == 422

    def test_does_not_persist_anything(self, at_app):
        app, db = at_app
        _client_for(app, PARTNER_F1).post("/api/income-tax/advance-tax/compute", json=COMPUTE_BODY)
        assert db.rows("advance_tax_payments") == []


class TestSaveEndpoint:
    def test_server_derives_due_date_and_required_percent_not_trusted_from_client(self, at_app):
        """The request model has no due_date/required_percent field at all --
        proving there is no way for a caller to supply and have persisted a
        value other than what the FY's Section 208 schedule dictates."""
        app, db = at_app
        body = {**COMPUTE_BODY, "client_id": "C1", "installments": [
            {"installment_number": 1, "paid_amount_paise": int(0.15 * TAX), "paid_date": "2024-06-15", "challan_number": "BSR123"},
        ]}
        r = _client_for(app, PARTNER_F1).post("/api/income-tax/advance-tax", json=body)
        assert r.status_code == 200
        rows = db.rows("advance_tax_payments")
        assert len(rows) == 4  # all 4 installments always written, matching the FY schedule
        inst1 = next(row for row in rows if row["installment_number"] == 1)
        assert inst1["due_date"] == "2024-06-15"
        assert inst1["required_percent"] == 15
        assert inst1["paid_amount_paise"] == int(0.15 * TAX)
        assert inst1["challan_number"] == "BSR123"
        assert inst1["firm_id"] == "F1"
        inst4 = next(row for row in rows if row["installment_number"] == 4)
        assert inst4["due_date"] == "2025-03-15"
        assert inst4["required_percent"] == 100
        assert inst4["paid_amount_paise"] == 0  # not supplied -- defaults, never guessed

    def test_save_is_firm_scoped(self, at_app):
        app, db = at_app
        body = {**COMPUTE_BODY, "client_id": "C1"}
        _client_for(app, PARTNER_F2).post("/api/income-tax/advance-tax", json=body)
        rows = db.rows("advance_tax_payments")
        assert all(row["firm_id"] == "F2" for row in rows)


class TestListIsFirmScoped:
    def test_list_only_returns_own_firm(self, at_app):
        app, db = at_app
        db.seed("advance_tax_payments", {
            "firm_id": "F1", "client_id": "C1", "financial_year": "2024-25",
            "installment_number": 1, "paid_amount_paise": 1000,
        })
        db.seed("advance_tax_payments", {
            "firm_id": "F2", "client_id": "C1", "financial_year": "2024-25",
            "installment_number": 1, "paid_amount_paise": 999999,
        })
        r = _client_for(app, PARTNER_F1).get(
            "/api/income-tax/advance-tax", params={"client_id": "C1", "fy": "2024-25"},
        )
        assert r.status_code == 200
        rows = r.json()["data"]
        assert len(rows) == 1
        assert rows[0]["paid_amount_paise"] == 1000
