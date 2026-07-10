"""
Products & Services hard-delete guard — real invoice-line link (migration 184).

service_catalogue.py's DELETE endpoint now checks
client_sales_invoice_lines.service_catalogue_id for real usage instead of the
use_count heuristic it used before (see test_service_catalogue.py for the
mock-mode unit tests of that guard). This file exercises the ACTUAL wiring
end-to-end through the real create/update-invoice code paths (FakeDB, not a
hand-rolled mock), since the link has to survive both an initial create AND
an edit (update_invoice deletes and reinserts all lines).
"""
from models.invoices import SalesInvoiceIn, SalesInvoiceUpdateIn, InvoiceLineIn
from models.service_catalogue import ServiceCatalogueIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    import routers.service_catalogue as sc
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, sc])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27",
                          "gstin": "27XYZAB5678C1Z2", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    return si, sc, db


def _create_service(sc, name="Steel Rod 12mm"):
    resp = sc.create_service(ServiceCatalogueIn(client_id="CLI", name=name), CALLER)
    return resp["data"]["id"]


def _linked_line(sid, description="Steel Rod 12mm"):
    return InvoiceLineIn(description=description, hsn_sac="7214", quantity=2,
                          rate_paise=50_000, gst_rate_percent=18.0, service_catalogue_id=sid)


def test_delete_blocked_after_real_invoice_creation(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)

    si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        invoice_no="INV-LINK-1", lines=[_linked_line(sid)],
    ), CALLER)

    # The real INSERT actually carried the link through, not just the model.
    linked = db.table("client_sales_invoice_lines").select("*").eq("service_catalogue_id", sid).execute().data
    assert len(linked) == 1

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
    assert "archive" in resp["error"].lower()


def test_delete_allowed_before_any_invoice_uses_it(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is True


def test_link_survives_a_no_op_invoice_edit(monkeypatch):
    # update_invoice deletes ALL lines and reinserts them from whatever the
    # request sends — if the frontend (or a test) re-sends a line without
    # service_catalogue_id, the link would silently vanish on save, wrongly
    # making an in-use preset look deletable again. This pins that editing
    # an invoice while re-sending the same link keeps the guard intact.
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    created = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        invoice_no="INV-LINK-2", lines=[_linked_line(sid)],
    ), CALLER)
    invoice_id = created["data"]["id"]

    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(
        notes="edited", lines=[_linked_line(sid, description="Steel Rod 12mm (edited)")],
    ), CALLER)

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
