"""The customer and supplier pickers put the parties a client used last at the top (POST-A-155)."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from domain import party_recent
from domain.party_recent import recent_party_ids, read_recent

pytestmark = pytest.mark.usefixtures("dev_header_auth")
ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_each_party_once_newest_first_without_carried_over_or_deleted_documents():
    rows = [
        {"customer_id": "c3"},
        {"customer_id": "c1", "is_opening": True},          # carried over: not a use here
        {"customer_id": "c2", "deleted_at": "2026-11-01"},  # deleted: not a use
        {"customer_id": "c3"},
        {"customer_id": None},
        {"customer_id": "c2"},
        {"customer_id": "c1"},
    ]
    assert recent_party_ids(rows, "customer_id") == ["c3", "c2", "c1"]
    assert recent_party_ids(rows, "customer_id", limit=2) == ["c3", "c2"]
    assert recent_party_ids([], "customer_id") == []


class _Q:
    def __init__(self, log, rows):
        self.log, self.rows = log, rows

    def __getattr__(self, name):
        def call(*a, **k):
            self.log.append((name, a, k))
            return self
        return call

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _DB:
    def __init__(self, rows):
        self.log, self.rows = [], rows

    def table(self, name):
        self.log.append(("table", (name,), {}))
        return _Q(self.log, self.rows)


def test_the_read_is_firm_and_client_scoped_newest_first_and_bounded():
    db = _DB([{"vendor_id": "v1"}, {"vendor_id": "v2"}])
    out = read_recent(db, "vendors", "firm-1", "cl-1")
    assert out == {"ids": ["v1", "v2"], "documents_read": 2, "window": party_recent.WINDOW}
    calls = [(n, a, k) for n, a, k in db.log]
    assert ("table", ("purchase_bills",), {}) in calls
    assert ("eq", ("firm_id", "firm-1"), {}) in calls
    assert ("eq", ("client_id", "cl-1"), {}) in calls
    assert ("order", ("created_at",), {"desc": True}) in calls
    assert ("order", ("id",), {"desc": True}) in calls, "a stated order that ends in id"
    assert ("limit", (party_recent.WINDOW,), {}) in calls
    with pytest.raises(ValueError):
        read_recent(db, "accounts", "firm-1", "cl-1")
    select = next(a[0] for n, a, k in calls if n == "select")
    for col in ("vendor_id", "is_opening", "deleted_at"):
        assert col in select, "the filter reads the key off the row, so the read must fetch it"


@pytest.mark.parametrize("path", ["/api/customers/recent", "/api/vendors/recent"])
def test_the_routes_answer_ids_and_ask_the_clients_scope(path):
    from main import app
    c = TestClient(app)
    h = {"X-User-Email": "p@test.com", "X-User-Role": "partner", "X-Firm-ID": "firm-1"}
    r = c.get(path, params={"client_id": "client-123"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True and r.json()["data"]["ids"] == []
    assert c.get(path, headers=h).status_code == 422, "the client is required"
    assert c.get(path, params={"client_id": "client-123", "limit": 99}, headers=h).status_code == 422


def test_the_route_is_declared_before_the_one_that_takes_an_id():
    for f, idroute in (("customers.py", '"/{customer_id}"'), ("vendors.py", '"/{vendor_id}"')):
        src = (ROOT / "apps/api/routers" / f).read_text(encoding="utf-8")
        assert src.index('@router.get("/recent")') < src.index(f"@router.get({idroute})"), f


def test_the_invoice_and_bill_pickers_take_the_recent_parties_and_preselect_nothing():
    web = ROOT / "apps/web"
    inv = (web / "components/invoices/InvoiceEditor.tsx").read_text(encoding="utf-8")
    bill = (web / "components/purchases/PurchaseBillEditor.tsx").read_text(encoding="utf-8")
    assert "useRecentPartyIds(api.customers.recent" in inv and "recent={recentCustomers}" in inv
    assert "useRecentPartyIds(api.vendors.recent" in bill and "recent={recentVendors}" in bill
    for f, read, prop in (("components/sales/SalesDebitNoteEditor.tsx", "customers", "recentCustomers"),
                          ("components/sales/SalesCreditNoteEditor.tsx", "customers", "recentCustomers"),
                          ("components/purchases/DebitNoteEditor.tsx", "vendors", "recentVendors"),
                          ("components/purchases/PurchaseCreditNoteEditor.tsx", "vendors", "recentVendors")):
        src = (web / f).read_text(encoding="utf-8")
        assert f"useRecentPartyIds(api.{read}.recent" in src and f"recent={{{prop}}}" in src, f
    helper = (web / "lib/lookups/recentParties.ts").read_text(encoding="utf-8")
    assert "onChange" not in helper and "setCustomerId" not in helper, "the helper orders a list and chooses nothing"
