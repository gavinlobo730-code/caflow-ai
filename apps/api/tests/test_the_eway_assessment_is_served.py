"""The invoice detail carries the Rule 138 answer, so the browser need not decide it.

SALES-17's fix put the rule in domain/gst/eway.py, but a domain module nothing
calls is not a fix — it is a second opinion the product never asks for. The
Compliance panel would have gone on deciding for itself, and the parity vectors
would have pinned the browser to a module with no live caller.

So GET /api/sales-invoices/{id} serves `eway_assessment`, computed here, and
apps/web/lib/invoices/compliance.assessEway is reached only through a `??` for
the window where the frontend has redeployed ahead of the backend — the same
arrangement as the Schedule III captions, and for the same reason.
"""
from __future__ import annotations

import unittest.mock as m

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
import routers.sales_invoices as mod

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-p"}


def _client() -> TestClient:
    app = FastAPI()
    # NO prefix here: routers.sales_invoices declares `prefix="/api/sales-invoices"`
    # itself. Adding one gives /api/api/sales-invoices and a 404 that reads
    # exactly like "the endpoint does not exist".
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _detail(lines: list) -> dict:
    """The LIVE branch, with a stub database. Mock mode returns fixed invoices,
    so a test that did not turn it off would assert against a constant."""
    invoice = {"id": "INV-1", "firm_id": "F1", "client_id": "C1",
               "invoice_no": "INV/2026-27/0001", "created_by": None}

    class _DB:
        def table(self, name):
            self._t = name
            return self
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def is_(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            if self._t == "client_sales_invoices":
                return type("R", (), {"data": [dict(invoice)]})()
            if self._t == "client_sales_invoice_lines":
                return type("R", (), {"data": list(lines)})()
            return type("R", (), {"data": []})()

    import core.supabase_client as sc
    with m.patch.object(mod, "_USE_MOCK", False), \
         m.patch.object(sc, "get_supabase", lambda: _DB()), \
         m.patch.object(mod, "_assert_invoice_scope", lambda *a, **k: None), \
         m.patch.object(mod, "_resolve_creator_name", lambda *a, **k: None):
        res = _client().get("/api/sales-invoices/INV-1")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True, body
    return body["data"]


def test_the_assessment_is_served_with_the_invoice():
    data = _detail([{
        "hsn_sac": "7306", "taxable_amount_paise": 48_000_00,
        "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 8_640_00,
        "gst_rate_bps": 1800,
    }])
    assert "eway_assessment" in data, (
        "the invoice detail carries no Rule 138 answer, so the Compliance "
        "panel is deciding it in the browser again")
    ass = data["eway_assessment"]
    # ₹48,000 taxable, ₹56,640 consignment. The taxable value is below the
    # limit and the consignment value is not — SALES-17's own case.
    assert ass["consignment_value_paise"] == 56_640_00
    assert ass["verdict"] == "required"
    assert ass["exceeds_threshold"] is True


def test_the_served_shape_is_the_whole_assessment():
    """The browser renders the reason and the gaps, not just the verdict. A
    partial payload would leave the panel silently falling back to its mirror
    for the parts it could not find."""
    data = _detail([{"hsn_sac": "7306", "taxable_amount_paise": 10_00_000_00,
                     "gst_rate_bps": 1800}])
    ass = data["eway_assessment"]
    assert set(ass) == {
        "consignment_value_paise", "threshold_paise", "exceeds_threshold",
        "goods_lines", "service_lines", "unclassified_lines",
        "excluded_exempt_paise", "verdict", "reason", "gaps",
    }, sorted(ass)
    assert isinstance(ass["reason"], str) and ass["reason"]
    assert isinstance(ass["gaps"], list)


def test_an_invoice_with_no_lines_does_not_raise():
    """A draft can have none, and the detail endpoint serves drafts."""
    ass = _detail([])["eway_assessment"]
    assert ass["verdict"] == "not_required"
    assert ass["consignment_value_paise"] == 0


def test_a_line_with_null_amounts_is_read_as_zero_not_as_a_crash():
    """PostgREST returns a nullable bigint as None, and every sales line column
    but the taxable value is nullable in migration 050."""
    ass = _detail([{"hsn_sac": "7306", "taxable_amount_paise": 60_000_00,
                    "cgst_paise": None, "sgst_paise": None, "igst_paise": None,
                    "gst_rate_bps": None}])["eway_assessment"]
    # gst_rate_bps None reads as 0 — a nil-rated goods line — so this is the
    # wholly exempt branch, which refuses rather than guessing.
    assert ass["verdict"] == "undetermined"
    assert ass["consignment_value_paise"] == 60_000_00
