"""
Products & Services hard-delete guard — real invoice-line link (migration 184).

service_catalogue.py's DELETE endpoint checks client_sales_invoice_lines.
service_catalogue_id (and purchase_bill_lines / credit_note_lines /
debit_note_lines / inventory_stock_ledger — see test_service_catalogue.py for
the mock-mode unit tests of the full guard) for real usage instead of the
use_count heuristic it used before. Only a NON-draft, non-cancelled document
counts — a draft invoice was never a final financial record (CGST Act §34:
correcting an ISSUED document means a Credit/Debit Note, not silently editing
what it referenced). This file exercises the ACTUAL wiring end-to-end through
the real create/update/issue-invoice code paths (FakeDB, not a hand-rolled
mock), since the link has to survive both an initial create AND an edit
(update_invoice deletes and reinserts all lines).
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


def test_delete_allowed_when_only_used_on_a_draft_invoice(monkeypatch):
    # A draft is never a final financial record — using a preset there
    # doesn't lock it, matching the "issued" framing the guard is built on.
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
    assert resp["success"] is True


def test_delete_blocked_after_invoice_is_issued(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)

    created = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        invoice_no="INV-LINK-1B", lines=[_linked_line(sid)],
    ), CALLER)
    si.issue_invoice(created["data"]["id"], CALLER)

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
    assert "archive" in resp["error"].lower()
    assert "sales invoice" in resp["error"].lower()


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
    # an ISSUED invoice while re-sending the same link keeps the guard intact.
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    created = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        invoice_no="INV-LINK-2", lines=[_linked_line(sid)],
    ), CALLER)
    invoice_id = created["data"]["id"]
    si.issue_invoice(invoice_id, CALLER)

    si.update_invoice(invoice_id, SalesInvoiceUpdateIn(notes="edited"), CALLER)

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False


# ── The other three document types (migration 189) also block deletion —
# these gained a real service_catalogue_id picker link this session, and the
# old guard only ever checked sales invoices. Seeded directly (minimal rows,
# only the fields _find_service_usage actually reads) rather than through the
# full create-bill/note flow, since this is exercising the guard, not those
# routers' own create logic. ─────────────────────────────────────────────────

def test_delete_blocked_when_used_on_an_issued_purchase_bill(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    db.seed("purchase_bills", {"id": "PB-1", "status": "received"})
    db.seed("purchase_bill_lines", {"bill_id": "PB-1", "service_catalogue_id": sid})

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
    assert "purchase bill" in resp["error"].lower()


def test_delete_allowed_when_only_used_on_a_draft_purchase_bill(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    db.seed("purchase_bills", {"id": "PB-1", "status": "draft"})
    db.seed("purchase_bill_lines", {"bill_id": "PB-1", "service_catalogue_id": sid})

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is True


def test_delete_blocked_when_used_on_an_issued_credit_note(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    db.seed("credit_notes", {"id": "CN-1", "status": "issued"})
    db.seed("credit_note_lines", {"credit_note_id": "CN-1", "service_catalogue_id": sid})

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
    assert "credit note" in resp["error"].lower()


def test_delete_blocked_when_used_on_an_issued_debit_note(monkeypatch):
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    db.seed("debit_notes", {"id": "DN-1", "status": "issued"})
    db.seed("debit_note_lines", {"debit_note_id": "DN-1", "service_catalogue_id": sid})

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
    assert "debit note" in resp["error"].lower()


def test_delete_blocked_when_inventory_has_stock_movements(monkeypatch):
    # inventory_stock_ledger.service_catalogue_id cascades on delete
    # (migration 188) — this guard exists so a hard delete never silently
    # wipes real stock movement history, independent of any document link.
    si, sc, db = _setup(monkeypatch)
    sid = _create_service(sc)
    db.seed("inventory_stock_ledger", {"service_catalogue_id": sid, "movement_type": "purchase"})

    resp = sc.delete_service(sid, CALLER)
    assert resp["success"] is False
    assert "inventory" in resp["error"].lower()
