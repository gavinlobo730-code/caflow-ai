"""The portal's fee-invoice download proves ownership first and only then reads with the privileged client (POST-A-237).

`GET /api/portal/self/invoices/{id}/pdf` used to run every read on the portal contact's own sign-in, where the supplier, the
lines and the e-invoice record are hidden by row security. It now hands the privileged client to `get_sales_invoice_pdf` as
`rest_db`. That is only safe in this order: `invoice_in_scope` (the contact's own fee invoice, issued to them) first, the
privileged reads after. This drives the ROUTE, because deleting the `rest_db=` argument, or moving the gate behind the read,
left every service-level test green.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.portal_data as portal_data
from core import db_provider
from services import invoice_pdf_service, portal_data_service

PORTAL = {"firm_id": "firm-1", "client_id": "client-1"}
PRIVILEGED = object()


@pytest.fixture()
def calls(monkeypatch):
    seen: dict = {"order": []}
    monkeypatch.setattr(portal_data, "_USE_MOCK", False)
    monkeypatch.setattr(db_provider, "service_db", lambda: PRIVILEGED)

    def _pdf(invoice_id, firm_id, *, rest_db=None):
        seen["order"].append("pdf")
        seen.update(invoice_id=invoice_id, firm_id=firm_id, rest_db=rest_db)
        return b"%PDF-1.4 test", "invoice-FEE-1.pdf"

    monkeypatch.setattr(invoice_pdf_service, "get_sales_invoice_pdf", _pdf)
    return seen


def test_an_owned_invoice_is_rendered_with_the_privileged_client_for_the_rest(calls, monkeypatch):
    def _gate(firm_id, client_id, invoice_id):
        calls["order"].append("gate")
        return True

    monkeypatch.setattr(portal_data_service, "invoice_in_scope", _gate)

    response = portal_data.portal_invoice_pdf("inv-1", PORTAL)

    assert response.body.startswith(b"%PDF")
    assert calls["order"] == ["gate", "pdf"], "ownership must be proved before anything is read with privilege"
    assert calls["rest_db"] is PRIVILEGED
    assert (calls["invoice_id"], calls["firm_id"]) == ("inv-1", "firm-1")


def test_an_invoice_that_is_not_theirs_is_a_404_and_nothing_is_read_with_privilege(calls, monkeypatch):
    monkeypatch.setattr(portal_data_service, "invoice_in_scope", lambda *a: False)

    with pytest.raises(HTTPException) as refused:
        portal_data.portal_invoice_pdf("inv-of-somebody-else", PORTAL)

    assert refused.value.status_code == 404
    assert calls["order"] == [], "the renderer must not run for an invoice the gate refused"
