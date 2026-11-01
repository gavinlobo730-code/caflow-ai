"""A receipt just created is reported with the allocated total the database now holds, not the 0 it was inserted with (POST-A-369, migration 572's companion).

THE DEFECT: migration 571 made `receipts.allocated_paise` the sum of the receipt's live allocation rows, kept by a trigger on those rows. The
settlement function inserts the receipt FIRST (with the column at its default of 0) and the allocations after it, and returns the receipt as it
was inserted. `receipt_service` built both the create response and the receipt's own `audit_log` event from that returned row, so a receipt
created with allocations came back, and was logged, with `allocated_paise` 0 beside allocation lines that covered it, while the stored row
(and every later read) said otherwise. The same was true of the foreign-currency path and the plain fallback path, which insert the allocation
rows after the receipt.

THE RULE HELD HERE: whatever the receipt's own figure is, the response and the edit-log event carry the sum of the allocations that were written,
and a receipt created with none still says 0.

Mock mode; no database.
"""
from __future__ import annotations

import os

os.environ.pop("SUPABASE_URL", None)

from types import SimpleNamespace

import pytest


def _rpc_db(result_data: dict):
    class _Rpc:
        def execute(self):
            return SimpleNamespace(data=result_data)

    class _DB:
        def rpc(self, _fn, _params):
            return _Rpc()

    return _DB()


@pytest.fixture()
def settle(monkeypatch):
    import services.receipt_service as mod
    import services.phase2_journal_service as journal_mod

    events: list[dict] = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "receipt_journal_lines",
        lambda *a, **k: [{"account_id": "acc-1", "debit_paise": 100, "credit_paise": 0}],
    )
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: events.append({"args": a, "kwargs": k}))
    monkeypatch.setattr(mod.timeline_service, "log_timeline_event", lambda *a, **k: None)

    def run(allocations_returned: list[dict], inserted_allocated: int = 0):
        db = _rpc_db({
            "receipt_id": "r1", "journal_entry_id": "j1", "allocations": allocations_returned,
            "receipt": {"id": "r1", "allocated_paise": inserted_allocated, "unallocated_paise": 0},
        })
        payload = {"id": "r1", "receipt_no": "RCPT-1", "receipt_date": "2026-04-05", "amount_paise": 100_000}
        receipt = mod._settle_receipt_via_atomic_rpc(db, "firm-1", "client-1", payload, [], {"id": "u1"})
        return receipt, events

    return run


def test_a_receipt_created_with_allocations_is_reported_with_their_sum(settle):
    receipt, events = settle([
        {"sales_invoice_id": "inv-a", "allocated_paise": 40_000},
        {"sales_invoice_id": "inv-b", "allocated_paise": 60_000},
    ])
    assert receipt["allocated_paise"] == 100_000, "the response still carries the 0 the receipt was inserted with"
    logged = events[0]["kwargs"]["new_data"]
    assert logged["allocated_paise"] == 100_000, "the receipt's own edit-log event still carries the inserted 0"


def test_a_receipt_created_with_no_allocation_still_says_nothing_allocated(settle):
    receipt, events = settle([])
    assert receipt["allocated_paise"] == 0
    assert events[0]["kwargs"]["new_data"]["allocated_paise"] == 0


def test_a_receipt_created_through_the_route_reports_what_it_allocated_in_the_response_and_the_edit_log(monkeypatch):
    """The whole route against the shared in-memory database: a customer, an issued invoice, then a receipt allocating part of it. Whichever
    settlement path the route takes, the response and the receipt's own audit event carry the sum of the allocation lines."""
    from models.invoices import InvoiceLineIn, ReceiptAllocationIn, ReceiptIn, SalesInvoiceIn
    from models.parties import CustomerIn
    from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e
    import routers.customers as cu
    import routers.receipts as rc
    import routers.sales_invoices as si
    import services.receipt_service as rs

    firm = "FIRM-A"
    caller = {"firm_id": firm, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, si, rc, rs])
    db.seed("clients", {"id": "CLI", "firm_id": firm, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, firm, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": firm, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    events: list[dict] = []
    monkeypatch.setattr(rs, "log_event", lambda *a, **k: events.append(k.get("new_data") or {}))

    customer = cu.create_customer(CustomerIn(client_id="CLI", name="Acme Buyer", state_code="27"), caller)["data"]
    invoice = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=customer["id"], invoice_date="2020-01-10", due_date="2020-01-25", invoice_no="CC-572-001",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Consulting", hsn_sac="9982", quantity=1,
                             rate_paise=1_000_000, gst_rate_percent=18.0)]), caller)["data"]
    assert si.issue_invoice(invoice["id"], caller)["data"]["status"] == "issued"

    out = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=customer["id"], receipt_date="2020-02-01", amount_paise=1_000_000,
        allocations=[ReceiptAllocationIn(sales_invoice_id=invoice["id"], allocated_paise=700_000)]), caller)["data"]

    assert out["allocated_paise"] == 700_000, f"the response says {out.get('allocated_paise')} allocated beside allocation lines of 700000"
    assert out["unallocated_paise"] == 300_000
    created = [e for e in events if e.get("receipt_no") or e.get("amount_paise")]
    assert created and all(e.get("allocated_paise") == 700_000 for e in created), (
        f"the receipt's edit-log event does not carry the allocated total: {created}")
