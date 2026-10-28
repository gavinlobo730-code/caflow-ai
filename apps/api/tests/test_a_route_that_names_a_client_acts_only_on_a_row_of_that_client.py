"""A route that asserts the client the caller named acts only on a row of THAT client (POST-A-337).

WHAT WAS WRONG
    `assert_client_access(current_user, client_id)` proves the caller may act on the client they SENT. A route that then reads or writes a
    client-owned row by its id with the firm alone (`.eq("id", x).eq("firm_id", f)`) acts on the row of ANY client of the firm: a caller
    assigned to client A who sends A's id and B's row id withdrew B's GSTR-4 entry, B's GSTR-9C line, B's e-commerce supply, rewrote B's
    AIS working, issued a reverse-charge document for B's bill, or stored an e-invoice record against B's invoice (and read B's live record
    in the 409 sentence). The 24-10-2026 hardening closed thirty-one such handlers; these sixteen were reported by the review and left.

WHAT IS ASSERTED
    For each route, with a Partner (so no assignment can hide the defect: the mismatch is between the row and the client the request
    NAMES, and it is wrong for anyone): the row of client B named under client A is answered in the words a missing row gets, the row is
    left exactly as it was, and the same request under client B works. That last half is the control: it proves the refusal is the
    client and not something else.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.ais as ais_router
import routers.ecommerce_operator as eco_router
import routers.einvoice as einvoice_router
import routers.gstr4_annual as g4_router
import routers.gstr9c as g9c_router
import routers.rcm_documents as rcm_router
import routers.sales_invoices as sales_router
from core.auth import get_current_user
from services import ais_service
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"      # the client the request names
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"      # the sibling client whose row is named
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


def _app(*routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def world(monkeypatch):
    db = FakeDB()
    # `sales_router` is in the list because the e-invoice route reads ITS mock flag: left alone, the flag is whatever the first import saw,
    # and the test passes in isolation and fails after any test that imported the module with no database configured.
    wire_e2e(monkeypatch, db, [ais_router, eco_router, einvoice_router, g4_router, g9c_router, rcm_router, sales_router])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")          # the GST routers read the environment for mock mode
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _live(db: FakeDB, table: str, row_id: str) -> dict:
    return next(r for r in db.rows(table) if r["id"] == row_id)


# ── the soft deletes ───────────────────────────────────────────────────────────────────────────────────────────────────────
DELETES = [
    ("/api/gstr4-annual/b2b-supplies/", "gstr4_annual_b2b_supplies"),
    ("/api/gstr4-annual/b2b-rc-supplies/", "gstr4_annual_b2b_rc_supplies"),
    ("/api/gstr4-annual/urp-supplies/", "gstr4_annual_urp_supplies"),
    ("/api/gstr4-annual/import-of-services/", "gstr4_annual_import_of_services"),
    ("/api/gstr9c/rate-wise-lines/", "gstr9c_rate_wise_lines"),
    ("/api/gstr9c/expense-lines/", "gstr9c_expense_lines"),
    ("/api/ecommerce-operator/supplies/", "ecommerce_operator_supplies"),
    ("/api/ecommerce-operator/unregistered-supplies/", "ecommerce_operator_unregistered_supplies"),
]


@pytest.mark.parametrize("path,table", DELETES, ids=[t for _, t in DELETES])
def test_a_sibling_clients_entry_named_under_this_client_is_not_withdrawn(world, path, table):
    world.seed(table, {"id": "row-b", "firm_id": FIRM, "client_id": B, "deleted_at": None})
    client = _app(g4_router, g9c_router, eco_router)
    res = client.delete(f"{path}row-b", params={"client_id": A})
    assert res.status_code == 404 and res.json()["detail"] == "Entry not found.", res.text
    assert _live(world, table, "row-b")["deleted_at"] is None, "the sibling's entry must be left as it was"


@pytest.mark.parametrize("path,table", DELETES, ids=[t for _, t in DELETES])
def test_the_same_request_under_the_entrys_own_client_still_withdraws_it(world, path, table):
    world.seed(table, {"id": "row-b", "firm_id": FIRM, "client_id": B, "deleted_at": None})
    res = _app(g4_router, g9c_router, eco_router).delete(f"{path}row-b", params={"client_id": B})
    assert res.status_code == 200, res.text
    assert _live(world, table, "row-b")["deleted_at"] is not None


# ── the AIS working ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _ais_line(db: FakeDB, client: str) -> dict:
    return db.seed("ais_records", {"id": f"rec-{client[:1]}", "firm_id": FIRM, "client_id": client, "upload_id": "up-1",
                                   "amount_paise": 500_000, "source": "parsed", "books_amount_paise": None})


def test_a_sibling_clients_ais_line_cannot_be_reworked_under_this_client(world, monkeypatch):
    monkeypatch.setattr(ais_service, "_USE_MOCK", False)
    monkeypatch.setattr(ais_service, "_supabase", lambda: world)
    line = _ais_line(world, B)
    before = dict(_live(world, "ais_records", line["id"]))
    res = _app(ais_router).put(f"/api/ais/records/{line['id']}/working",
                               json={"client_id": A, "books_amount_paise": 1, "status": None, "note": None})
    assert res.status_code == 400 and res.json()["detail"] == "Record not found", res.text
    assert _live(world, "ais_records", line["id"]) == before


# ── the reverse-charge documents ───────────────────────────────────────────────────────────────────────────────────────────
def test_a_sibling_clients_bill_and_payment_cannot_be_previewed_or_issued_under_this_client(world):
    world.seed("purchase_bills", {"id": "bill-b", "firm_id": FIRM, "client_id": B, "vendor_id": "v-b", "deleted_at": None,
                                  "is_reverse_charge": True})
    world.seed("purchase_payments", {"id": "pay-b", "firm_id": FIRM, "client_id": B, "vendor_id": "v-b"})
    client = _app(rcm_router)

    res = client.get("/api/rcm-documents/preview/self-invoice", params={"client_id": A, "purchase_bill_id": "bill-b"})
    assert res.status_code == 404 and res.json()["detail"] == "Purchase bill not found.", res.text
    res = client.get("/api/rcm-documents/preview/payment-voucher", params={"client_id": A, "purchase_payment_id": "pay-b"})
    assert res.status_code == 404 and res.json()["detail"] == "Payment not found.", res.text
    res = client.post("/api/rcm-documents", json={"client_id": A, "kind": "self_invoice", "purchase_bill_id": "bill-b"})
    assert res.status_code == 404 and res.json()["detail"] == "Purchase bill not found.", res.text
    res = client.post("/api/rcm-documents", json={"client_id": A, "kind": "payment_voucher", "purchase_payment_id": "pay-b"})
    assert res.status_code == 404 and res.json()["detail"] == "Payment not found.", res.text
    assert world.rows("rcm_documents") == [], "no document was issued for the sibling"


def test_the_same_bill_under_its_own_client_gets_past_the_bill_lookup(world):
    """The control: the refusal above is the client. Under the bill's own client the lookup passes (the vendor is not seeded, so
    the request stops at the next lookup, with a different sentence)."""
    world.seed("purchase_bills", {"id": "bill-b", "firm_id": FIRM, "client_id": B, "vendor_id": "v-b", "deleted_at": None})
    res = _app(rcm_router).get("/api/rcm-documents/preview/self-invoice", params={"client_id": B, "purchase_bill_id": "bill-b"})
    assert res.json().get("detail") != "Purchase bill not found.", res.text


# ── the e-invoice record ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_an_einvoice_record_cannot_be_prepared_against_a_sibling_clients_invoice_and_does_not_name_its_record(world):
    world.seed("client_sales_invoices", {"id": "inv-b", "firm_id": FIRM, "client_id": B, "deleted_at": None,
                                         "invoice_no": "B/1", "supply_type": "B2B", "invoice_type": "regular", "igst_paise": 0})
    world.seed("einvoice_records", {"id": "rec-b", "firm_id": FIRM, "client_id": B, "sales_invoice_id": "inv-b",
                                    "invoice_number": "B/1", "status": "draft"})
    body = {"client_id": A, "invoice_number": "A/1", "invoice_date": "2026-06-10", "sales_invoice_id": "inv-b"}
    res = _app(einvoice_router).post("/api/einvoice/records", json=body)
    assert res.status_code == 404 and res.json()["detail"] == "That invoice was not found.", res.text
    assert "rec-b" not in res.text and "B/1" not in res.text, "the refusal must not name the sibling's record"
    assert [r["id"] for r in world.rows("einvoice_records")] == ["rec-b"], "and nothing was created"


# ── a line attached to a reconciliation (GSTR-9C) ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,table,body", [
    ("/api/gstr9c/rate-wise-lines", "gstr9c_rate_wise_lines",
     {"table_ref": "9", "rate_description": "18%", "taxable_value_paise": 100}),
    ("/api/gstr9c/expense-lines", "gstr9c_expense_lines", {"expense_head": "Rent", "value_paise": 100}),
], ids=["rate_wise", "expense"])
def test_a_line_cannot_be_attached_to_a_sibling_clients_reconciliation(world, path, table, body):
    """The foreign key on a line's reconciliation is not client-aware, so client A's line named B's reconciliation and B's statement,
    which lists a reconciliation's lines by its id, carried it."""
    world.seed("gstr9c_reconciliations", {"id": "rec-b", "firm_id": FIRM, "client_id": B, "gstin": "27AAPFU0939F1ZV",
                                          "financial_year": "2025-26"})
    client = _app(g9c_router)
    res = client.post(path, json={"client_id": A, "reconciliation_id": "rec-b", **body})
    assert res.status_code == 404 and res.json()["detail"] == "Reconciliation not found.", res.text
    assert world.rows(table) == [], "nothing was attached to the sibling's reconciliation"
    ok = client.post(path, json={"client_id": B, "reconciliation_id": "rec-b", **body})
    assert ok.status_code == 200, ok.text
    assert [r["reconciliation_id"] for r in world.rows(table)] == ["rec-b"], "the control: under its own client it is attached"

