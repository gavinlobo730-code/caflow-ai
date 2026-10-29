"""The practice's customer for a client follows the client's record (POST-A-216).

WHAT WAS WRONG
    Billing a client's fee raises an invoice on a customer in the practice's own books, linked to the client (guardrail G3). The
    customer's name, GSTIN, PAN and state code were copied from the client when the link was first made and never again, so a client
    that changed its name or registered for GST was billed under what it was called the first day it was billed.

WHAT IS HELD
    * `ensure_customer_link`, when the link already exists, brings the customer's name, GSTIN, PAN and state code back to the
      client's current ones, writing only the columns that differ;
    * the client's record is the truth: a GSTIN the client no longer carries is cleared on the customer;
    * nothing is written when nothing differs, and the write names the firm and the practice's own client;
    * a refresh that fails is REPORTED and does not stop the run (the link's id is still returned);
    * another firm's client or customer is never touched.
"""
from __future__ import annotations

import pytest

import services.billing_service as billing_service
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(billing_service, "_USE_MOCK", False)
    db = FakeDB()
    monkeypatch.setattr(billing_service, "_db", lambda: db)
    db.seed("clients", {"id": "PC-1", "firm_id": FIRM, "client_name": "Old Name Traders", "gstin": None, "pan": "AAAAA0000A", "state_code": "27"})
    first = billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A")
    return db, first


def _customer(db):
    return [c for c in db.rows("customers") if c["client_id"] == "INTERNAL-A"][0]


def test_a_renamed_client_is_billed_under_its_new_name(world):
    db, first = world
    assert _customer(db)["name"] == "Old Name Traders"
    db.rows("clients")[0]["client_name"] = "New Name Traders Pvt Ltd"
    assert billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A") == first, "the link is the same customer"
    assert _customer(db)["name"] == "New Name Traders Pvt Ltd" and len(db.rows("customers")) == 1


def test_a_client_that_registered_for_gst_and_moved_state_is_followed(world):
    db, _ = world
    db.rows("clients")[0].update(gstin="29AAAAA0000A1Z5", state_code="29")
    billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A")
    assert (_customer(db)["gstin"], _customer(db)["state_code"]) == ("29AAAAA0000A1Z5", "29")


def test_a_gstin_the_client_no_longer_carries_is_cleared_not_kept(world):
    db, _ = world
    db.rows("clients")[0]["gstin"] = "29AAAAA0000A1Z5"
    billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A")
    db.rows("clients")[0]["gstin"] = None
    billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A")
    assert _customer(db)["gstin"] is None


def test_nothing_is_written_when_nothing_differs(world, monkeypatch):
    db, _ = world
    writes = []
    real = db.table

    def spy(name):
        t = real(name)
        if name == "customers":
            original = t.update
            t.update = lambda *a, **k: writes.append(a) or original(*a, **k)
        return t

    monkeypatch.setattr(db, "table", spy)
    billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A")
    assert writes == []


def test_a_refresh_that_fails_is_reported_and_the_run_goes_on(world, monkeypatch):
    db, first = world
    db.rows("clients")[0]["client_name"] = "Changed"
    seen = []
    monkeypatch.setattr("core.observability.capture_soft_failure", lambda exc, **ctx: seen.append(ctx.get("operation")))
    real = db.table

    def table(name):
        t = real(name)
        if name == "customers":
            def boom(*a, **k):
                raise RuntimeError("write refused")
            t.update = boom
        return t

    monkeypatch.setattr(db, "table", table)
    assert billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A") == first
    assert seen == ["billing.refresh_customer_snapshot"]


def test_another_firms_customer_with_the_same_id_is_not_touched(world):
    db, first = world
    db.seed("customers", {"id": first, "firm_id": "FIRM-B", "client_id": "INTERNAL-B", "name": "Theirs", "gstin": None, "pan": None, "state_code": None})
    db.rows("clients")[0]["client_name"] = "Changed"
    billing_service.ensure_customer_link(FIRM, "PC-1", "INTERNAL-A")
    theirs = [c for c in db.rows("customers") if c["firm_id"] == "FIRM-B"][0]
    assert theirs["name"] == "Theirs"
