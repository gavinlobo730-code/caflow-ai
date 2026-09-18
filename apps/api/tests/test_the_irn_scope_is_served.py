"""The invoice detail carries the Rule 48(4) answer, so the browser need not decide it.

SALES-18's fix put the rule in domain/gst/irn_scope.py, but a domain module
nothing calls is not a fix — it is a second opinion the product never asks for.
The Compliance panel would have gone on deciding for itself and the parity
vectors would have pinned the browser to a module with no live caller. This is
the same guard `test_the_eway_assessment_is_served.py` holds for Rule 138, and
it exists for the same reason.

IT MATTERS MORE HERE THAN IT DID THERE, because one limb of Rule 48(4) is
answerable ONLY on the server. CGST §2(6) aggregate turnover is recorded per
financial year on `client_gst_turnover` (migration 401, GST-17) and no screen
holds it, which is why the panel used to decline the whole person-side limb
with a fixed sentence on every invoice. If the endpoint stops serving this, the
browser falls back to its mirror, the mirror passes `null` for the turnover,
and every client silently goes back to the strictest reading.
"""
from __future__ import annotations

import unittest.mock as m

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
import routers.sales_invoices as mod

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner",
           "email": "p@f1.test", "auth_user_id": "auth-p"}


def _client() -> TestClient:
    # NO prefix here: routers.sales_invoices declares its own.
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _detail(*, gstin="27AAAAA0000A1Z5", invoice_date="2026-06-01",
            turnover_rows=(), supply_type=None, invoice_type=None) -> dict:
    """The LIVE branch, with a stub database. Mock mode returns fixed invoices,
    so a test that did not turn it off would assert against a constant."""
    invoice = {
        "id": "INV-1", "firm_id": "F1", "client_id": "C1",
        "invoice_no": "INV/2026-27/0001", "created_by": None,
        "invoice_date": invoice_date,
        "supply_type": supply_type, "invoice_type": invoice_type,
        "igst_paise": 0,
        "customers": {"id": "CUS-1", "name": "Acme", "email": None,
                      "gstin": gstin, "phone": None},
    }

    class _DB:
        def table(self, name):
            self._t = name
            return self
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def is_(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            if self._t == "client_sales_invoices":
                return type("R", (), {"data": [dict(invoice)]})()
            if self._t == "client_gst_turnover":
                return type("R", (), {"data": [dict(r) for r in turnover_rows]})()
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


def test_the_scope_is_served_with_the_invoice():
    data = _detail(turnover_rows=[
        {"financial_year": "2024-25", "aggregate_turnover_paise": 10_00_00_000_00},
    ])
    assert "irn_assessment" in data, (
        "the invoice detail carries no Rule 48(4) answer, so the Compliance "
        "panel is deciding it in the browser again")
    got = data["irn_assessment"]
    assert got["verdict"] == "required"
    assert got["supply_in_scope"] is True
    assert got["turnover_exceeds"] is True
    assert got["turnover_paise"] == 10_00_00_000_00


def test_the_served_shape_is_the_whole_assessment():
    """The browser renders the reason and the gaps, not just the verdict. A
    partial payload would leave the panel silently falling back to its mirror
    for the parts it could not find."""
    got = _detail()["irn_assessment"]
    assert set(got) == {
        "verdict", "supply_in_scope", "supply_reason", "threshold_paise",
        "threshold_citation", "turnover_paise", "turnover_exceeds",
        "turnover_unknown", "reason", "gaps",
        # GST-32: what the PORTAL would refuse, beside whether Rule 48(4)
        # requires the IRN at all. Two authorities on one payload — the Act's
        # scope test and the IRP's own acceptance rules — and the panel has to
        # be able to tell them apart, so they are separate keys rather than
        # more entries in `gaps`.
        "irp_findings",
    }, sorted(got)
    assert isinstance(got["reason"], str) and got["reason"]
    assert isinstance(got["gaps"], list)
    assert isinstance(got["irp_findings"], list)


def test_the_turnover_is_read_from_the_register_not_defaulted_to_zero():
    """0 is a real turnover meaning "below every threshold". Defaulting to it
    is exactly the bug GST-17 closed on the HSN side, where every client was
    silently told HSN was optional. No row means None, and None takes the
    strict reading and NAMES it."""
    got = _detail(turnover_rows=[])["irn_assessment"]
    assert got["turnover_paise"] is None
    assert got["turnover_unknown"] is True
    assert got["verdict"] == "required"
    assert any("aggregate turnover" in g for g in got["gaps"])


def test_the_register_read_takes_the_HIGHEST_qualifying_year_not_the_latest():
    """Rule 48(4) latches: "any preceding financial year from 2017-18 onwards".
    A client who crossed ₹20 crore in 2022-23 and has turned over ₹4 crore
    since is still within it, so taking the newest row would let them out."""
    got = _detail(turnover_rows=[
        {"financial_year": "2024-25", "aggregate_turnover_paise": 4_00_00_000_00},
        {"financial_year": "2022-23", "aggregate_turnover_paise": 20_00_00_000_00},
    ])["irn_assessment"]
    assert got["turnover_paise"] == 20_00_00_000_00
    assert got["verdict"] == "required"


def test_a_b2c_invoice_is_out_of_scope_however_large_the_client():
    got = _detail(gstin=None, turnover_rows=[
        {"financial_year": "2024-25", "aggregate_turnover_paise": 1000_00_00_000_00},
    ])["irn_assessment"]
    assert got["supply_in_scope"] is False
    assert got["verdict"] == "not_required"


def test_an_export_with_no_recipient_gstin_is_in_scope():
    """The supply limb reads "to a registered person, OR for export". The
    treatment comes from the invoice's own supply_type + invoice_type through
    domain/gst/treatment (SALES-19), which the endpoint already resolves — this
    asserts the two are wired to each other."""
    got = _detail(gstin=None, supply_type="zero_rated", turnover_rows=[
        {"financial_year": "2024-25", "aggregate_turnover_paise": 10_00_00_000_00},
    ])["irn_assessment"]
    assert got["supply_in_scope"] is True
    assert got["verdict"] == "required"


def test_the_threshold_served_is_the_one_in_force_on_the_invoices_own_date():
    """The fork. A 2021 invoice keeps 2021's ₹50 crore threshold, so the same
    ₹10 crore client is out of scope there and in scope today."""
    old = _detail(invoice_date="2021-06-01", turnover_rows=[
        {"financial_year": "2019-20", "aggregate_turnover_paise": 10_00_00_000_00},
    ])["irn_assessment"]
    assert old["threshold_paise"] == 50_00_00_000_00
    assert old["verdict"] == "not_required"

    new = _detail(invoice_date="2026-06-01", turnover_rows=[
        {"financial_year": "2024-25", "aggregate_turnover_paise": 10_00_00_000_00},
    ])["irn_assessment"]
    assert new["threshold_paise"] == 5_00_00_000_00
    assert new["verdict"] == "required"


def test_a_null_turnover_column_is_read_as_zero_not_as_a_crash():
    """PostgREST returns a nullable bigint as None. A row that exists with a
    NULL figure is a recorded zero, which is different from no row at all."""
    got = _detail(turnover_rows=[
        {"financial_year": "2024-25", "aggregate_turnover_paise": None},
    ])["irn_assessment"]
    assert got["turnover_paise"] == 0
    assert got["turnover_unknown"] is False
    assert got["verdict"] == "not_required"
