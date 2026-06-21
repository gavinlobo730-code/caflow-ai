"""
Phase 5.2 WS-1 — Recurring invoices E2E.

Drives the recurring engine against the shared DB, reusing the REAL sales-invoice
create engine for generation:

  create_template → preview occurrences → run (generates DRAFT invoices) →
  idempotent re-run → pause → run blocked

Asserts the deterministic cadence, that generation creates DRAFT invoices ONLY
(never issued/posted/emailed — the locked decision), idempotency (one occurrence
⇒ one invoice), and tenant isolation (foreign firm: template not found, cannot run).
"""
import pytest
from fastapi import HTTPException

import services.recurring_invoice_service as ris
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
OTHER = {"firm_id": "FIRM-B"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])           # generation reuses sales create_invoice
    monkeypatch.setattr(ris, "_USE_MOCK", False)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme", "state_code": "27", "credit_days": 15, "is_active": True})
    return db


def _template(db):
    return ris.create_template(FIRM, {
        "client_id": "CLI", "customer_id": "CUST", "title": "Monthly retainer",
        "frequency": "monthly", "start_date": "2026-04-01",
        "lines": [{"description": "Retainer", "hsn_sac": "9982",
                   "rate_paise": 1_000_000, "gst_rate_percent": 18.0}],
    }, "u1", db=db)


def test_recurring_cadence_preview_is_deterministic(monkeypatch):
    db = _setup(monkeypatch)
    t = _template(db)
    assert t["status"] == "active" and t["next_run_date"] == "2026-04-01"
    assert ris.preview_occurrences(t, count=3) == ["2026-04-01", "2026-05-01", "2026-06-01"]


def test_recurring_generates_drafts_and_is_idempotent(monkeypatch):
    db = _setup(monkeypatch)
    t = _template(db)

    res = ris.run_for_template(FIRM, t["id"], as_of="2026-06-15", db=db)
    assert res["generated_count"] == 3                      # Apr, May, Jun occurrences

    invs = db.rows("client_sales_invoices")
    assert len(invs) == 3
    assert all(i["status"] == "draft" for i in invs)        # NEVER auto-issued
    assert all(i["recurring_template_id"] == t["id"] for i in invs)
    assert {i["invoice_date"] for i in invs} == {"2026-04-01", "2026-05-01", "2026-06-01"}

    # Re-run with the same as_of ⇒ nothing new (next_run advanced past as_of).
    res2 = ris.run_for_template(FIRM, t["id"], as_of="2026-06-15", db=db)
    assert res2["generated_count"] == 0
    assert len(db.rows("client_sales_invoices")) == 3       # idempotent


def test_recurring_paused_template_cannot_run(monkeypatch):
    db = _setup(monkeypatch)
    t = _template(db)
    ris.set_status(FIRM, t["id"], "paused", db=db)
    with pytest.raises(HTTPException) as ei:
        ris.run_for_template(FIRM, t["id"], as_of="2026-06-15", db=db)
    assert ei.value.status_code == 422
    assert db.rows("client_sales_invoices") == []           # nothing generated


def test_recurring_invalid_frequency_rejected(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        ris.create_template(FIRM, {
            "client_id": "CLI", "customer_id": "CUST", "title": "x",
            "frequency": "fortnightly", "start_date": "2026-04-01",
            "lines": [{"description": "x", "rate_paise": 1000}],
        }, "u1", db=db)
    assert ei.value.status_code == 422


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_recurring_foreign_firm_cannot_see_or_run(monkeypatch):
    db = _setup(monkeypatch)
    t = _template(db)
    assert ris.get_template("FIRM-B", t["id"], db=db) is None       # not visible
    with pytest.raises(HTTPException) as ei:
        ris.run_for_template("FIRM-B", t["id"], as_of="2026-06-15", db=db)
    assert ei.value.status_code == 404
    assert db.rows("client_sales_invoices") == []                   # no generation
