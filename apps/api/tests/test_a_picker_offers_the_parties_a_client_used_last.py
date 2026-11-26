"""The customer and supplier pickers put the parties a client used last at the top (POST-A-155)."""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from domain import party_recent
from domain.party_recent import recent_party_ids, read_recent

pytestmark = pytest.mark.usefixtures("dev_header_auth")
ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_each_party_once_newest_first():
    rows = [{"customer_id": "c3"}, {"customer_id": "c3"}, {"customer_id": None}, {"customer_id": "c2"}, {"customer_id": "c1"}]
    assert recent_party_ids(rows, "customer_id") == ["c3", "c2", "c1"]
    assert recent_party_ids(rows, "customer_id", limit=2) == ["c3", "c2"]
    assert recent_party_ids([], "customer_id") == []


class _Query:
    """A PostgREST chain over in-memory rows, applied as the database applies it: every filter, then the order, then
    the limit, whatever order the calls were written in."""

    def __init__(self, db, rows):
        self.db, self.rows, self.filters, self.orders, self.cap = db, rows, [], [], None

    def select(self, cols):
        self.db.log.append(("select", (cols,), {}))
        return self

    def eq(self, col, val):
        self.db.log.append(("eq", (col, val), {}))
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def is_(self, col, val):
        self.db.log.append(("is_", (col, val), {}))
        assert val in ("null", None)
        self.filters.append(lambda r: r.get(col) is None)
        return self

    def order(self, col, desc=False):
        self.db.log.append(("order", (col,), {"desc": desc}))
        self.orders.append((col, desc))
        return self

    def limit(self, n):
        self.db.log.append(("limit", (n,), {}))
        self.cap = n
        return self

    def execute(self):
        rows = [r for r in self.rows if all(f(r) for f in self.filters)]
        for col, desc in reversed(self.orders):  # the first order() is the primary key
            rows.sort(key=lambda r: r[col], reverse=desc)
        if self.cap is not None:
            rows = rows[: self.cap]
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, rows):
        self.log, self.rows = [], rows

    def table(self, name):
        self.log.append(("table", (name,), {}))
        return _Query(self, self.rows)


def _bill(i, vendor, *, opening=False, deleted=False, client="cl-1", firm="firm-1"):
    return {"id": f"b{i:04d}", "vendor_id": vendor, "is_opening": opening, "deleted_at": "2026-11-01" if deleted else None,
            "created_at": f"2026-01-01T00:00:00.{i:06d}+00:00", "client_id": client, "firm_id": firm}


def test_a_client_whose_newest_documents_are_carried_over_still_gets_its_recent_suppliers():
    # Two older live bills, then 200 newer opening bills and 50 newer deleted ones: a filter applied after the window
    # is cut would find nothing.
    rows = [_bill(1, "v-old-1"), _bill(2, "v-old-2")]
    rows += [_bill(10 + i, f"v-open-{i}", opening=True) for i in range(party_recent.WINDOW)]
    rows += [_bill(500 + i, f"v-del-{i}", deleted=True) for i in range(50)]
    rows += [_bill(900, "v-other-client", client="cl-2"), _bill(901, "v-other-firm", firm="firm-2")]
    out = read_recent(_DB(rows), "vendors", "firm-1", "cl-1")
    assert out["ids"] == ["v-old-2", "v-old-1"]


def test_the_read_is_firm_and_client_scoped_live_and_not_carried_over_newest_first_and_bounded():
    db = _DB([_bill(1, "v1"), _bill(2, "v2")])
    out = read_recent(db, "vendors", "firm-1", "cl-1")
    assert out == {"ids": ["v2", "v1"], "documents_read": 2, "window": party_recent.WINDOW}
    calls = db.log
    assert ("table", ("purchase_bills",), {}) in calls
    assert ("eq", ("firm_id", "firm-1"), {}) in calls
    assert ("eq", ("client_id", "cl-1"), {}) in calls
    assert ("eq", ("is_opening", False), {}) in calls
    assert ("is_", ("deleted_at", "null"), {}) in calls
    assert ("order", ("created_at",), {"desc": True}) in calls
    assert ("order", ("id",), {"desc": True}) in calls, "a stated order that ends in id"
    assert ("limit", (party_recent.WINDOW,), {}) in calls
    with pytest.raises(ValueError):
        read_recent(db, "accounts", "firm-1", "cl-1")
    db2 = _DB([])
    read_recent(db2, "customers", "firm-1", "cl-1")
    assert ("table", ("client_sales_invoices",), {}) in db2.log
    assert ("eq", ("is_opening", False), {}) in db2.log and ("is_", ("deleted_at", "null"), {}) in db2.log


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


#: Party pickers that choose what a LIST shows, not the party of a document or record, so recent-first does not apply.
#: (file, how many such pickers it holds): the customer statement chooser and the invoice list's customer filter.
NOT_A_DOCUMENTS_PARTY = {"app/clients/[id]/sales/page.tsx": 2}


def _party_pickers(src: str) -> list[str]:
    out = []
    for m in re.finditer(r"<(CustomerLookup|VendorLookup)\b", src):
        end = src.index("/>", m.end())
        out.append(src[m.start(): end + 2])
    return out


def test_every_party_picker_on_a_document_or_record_takes_the_recent_parties():
    web = ROOT / "apps/web"
    missing, seen = [], 0
    for path in sorted(list((web / "app").rglob("*.tsx")) + list((web / "components").rglob("*.tsx"))):
        rel = path.relative_to(web).as_posix()
        if rel.startswith("components/lookups/"):
            continue
        pickers = _party_pickers(path.read_text(encoding="utf-8"))
        seen += len(pickers)
        without = [p for p in pickers if "recent={" not in p]
        if len(without) != NOT_A_DOCUMENTS_PARTY.get(rel, 0):
            missing.append(f"{rel}: {len(without)} picker(s) without recent=, {NOT_A_DOCUMENTS_PARTY.get(rel, 0)} allowed")
    assert seen >= 15, f"only {seen} party pickers found: the scan has gone blind"
    assert missing == [], missing


def test_the_helper_orders_a_list_and_chooses_nothing():
    helper = (ROOT / "apps/web/lib/lookups/recentParties.ts").read_text(encoding="utf-8")
    assert "onChange" not in helper and "setCustomerId" not in helper
