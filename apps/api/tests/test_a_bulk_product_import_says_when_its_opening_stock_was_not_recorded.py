"""A bulk product import says which products it created without the opening stock the file asked for (POST-A-092, the bulk-import half).

WHAT WAS WRONG
    `bulk_create_services` inserts the products and then seeds an opening stock row for each goods line that came with a quantity and a
    cost. The seeding never raises, by design (one bad opening balance must not fail a 300-product import), and the route answered a
    plain success whatever the seeding did. When the stock ledger refused the rows, the catalogue kept `opening_qty_units` and
    `opening_cost_paise` while the item's stock stayed at 0, and the screen said "imported" for a stock list whose stock was not there.
    The failure reached Sentry only.

WHAT IS HELD
    * the route asks the stock ledger which of the items that came with an opening balance have an opening row, and answers
      `opening_stock` with the count asked, the count recorded, the items that have none by name, and one sentence;
    * a batch that landed in full says nothing (no sentence), and a batch with no opening balances asked for nothing;
    * a ledger that cannot be read is "could not check", never "recorded": the sentence says so and no count is claimed;
    * the products themselves are still created in every case, as before;
    * the sentence is the server's: the screen pushes it into the import result as written (see the web guard).
"""
from __future__ import annotations

import pytest

import routers.service_catalogue as sc
from domain.inventory import opening_stock_report as report
from tests.e2e_harness import FakeDB

FIRM = "firm-bulk-92"
CLIENT = "client-bulk-92"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


# ── the sentence ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _asked(n):
    return [{"id": f"i{k}", "name": f"Item {k}"} for k in range(n)]


def test_nothing_asked_is_nothing_to_say():
    assert report.report([], set()) == {"asked": 0, "recorded": 0, "not_recorded": [], "checked": True, "message": None}


def test_everything_recorded_says_nothing():
    got = report.report(_asked(3), {"i0", "i1", "i2"})
    assert got["message"] is None and got["recorded"] == 3 and got["not_recorded"] == [] and got["checked"] is True


def test_the_items_that_have_no_opening_row_are_named():
    got = report.report(_asked(3), {"i1"})
    assert got["recorded"] == 1 and [r["name"] for r in got["not_recorded"]] == ["Item 0", "Item 2"]
    assert "not recorded for 2 of 3 products" in got["message"]
    assert "“Item 0”, “Item 2”" in got["message"]
    assert "These products were created without it" in got["message"]


def test_one_product_is_singular_and_a_long_list_is_counted_after_five():
    one = report.report(_asked(1), set())
    assert "1 of 1 product:" in one["message"] and "The product was created without it" in one["message"]
    many = report.report(_asked(8), set())
    assert many["message"].count("“") == 5 and "and 3 more" in many["message"]


def test_a_ledger_that_could_not_be_read_claims_nothing():
    got = report.report(_asked(2), None)
    assert got["checked"] is False and got["recorded"] is None and got["not_recorded"] == []
    assert "could not be read to confirm" in got["message"]


def test_an_id_is_compared_as_text():
    assert report.report([{"id": 7, "name": "N"}], {"7"})["message"] is None


# ── the route ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Refused(Exception):
    pass


class _Ledger:
    """The request's client with the stock ledger's INSERT refused and/or its READS failing."""

    def __init__(self, inner, *, refuse_insert=False, fail_reads=False):
        self._inner, self._refuse, self._fail_reads = inner, refuse_insert, fail_reads

    def table(self, name):
        if name != "inventory_stock_ledger":
            return self._inner.table(name)
        owner = self
        query = self._inner.table(name)

        class Table:
            def insert(self, *a, **k):
                if owner._refuse:
                    raise _Refused("ledger insert refused")
                return query.insert(*a, **k)

            def select(self, *a, **k):
                if owner._fail_reads:
                    raise _Refused("ledger unreadable")
                return query.select(*a, **k)

            def __getattr__(self, attr):
                return getattr(query, attr)
        return Table()

    def __getattr__(self, attr):
        return getattr(self._inner, attr)


@pytest.fixture()
def world(monkeypatch):
    fake = FakeDB()
    fake.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2026-04-01"})
    for key, name in (("inventory", "Inventory"), (None, "Opening Balance Equity")):
        fake.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": key, "account_name": name,
                                        "is_active": True})
    import core.supabase_client as sc_client
    monkeypatch.setattr(sc, "_USE_MOCK", False)
    monkeypatch.setattr(sc_client, "get_supabase", lambda: fake)
    monkeypatch.setattr(sc, "assert_client_access", lambda *a, **k: None)
    return fake


def _import(world, monkeypatch, **proxy):
    import core.supabase_client as sc_client
    monkeypatch.setattr(sc_client, "get_supabase", lambda: _Ledger(world, **proxy))
    goods = [{"client_id": CLIENT, "name": f"Widget {k}", "kind": "good", "opening_qty_units": 10, "opening_cost_paise": 5_000,
              "gst_rate_bps": 1800} for k in range(2)]
    services = [{"client_id": CLIENT, "name": "Consulting", "kind": "service"}]
    out = sc.bulk_create_services(sc.ServiceBulkIn(services=goods + services, opening_balance_date="2026-04-01"), current_user=PARTNER)
    assert out["success"] is True, out
    return out["data"]


def test_an_import_whose_opening_stock_landed_says_nothing(world, monkeypatch):
    data = _import(world, monkeypatch)
    assert len(data["created"]) == 3 and data["errors"] == []
    assert data["opening_stock"]["asked"] == 2 and data["opening_stock"]["recorded"] == 2
    assert data["opening_stock"]["message"] is None and data["opening_stock"]["not_recorded"] == []


def test_an_import_whose_ledger_rows_were_refused_names_the_products_it_created_without_stock(world, monkeypatch):
    data = _import(world, monkeypatch, refuse_insert=True)
    assert len(data["created"]) == 3, "the products are created whatever the stock did"
    stock = data["opening_stock"]
    assert stock["asked"] == 2 and stock["recorded"] == 0 and stock["checked"] is True
    assert sorted(r["name"] for r in stock["not_recorded"]) == ["Widget 0", "Widget 1"]
    assert "not recorded for 2 of 2 products" in stock["message"]


def test_an_import_that_cannot_read_the_ledger_back_claims_neither_way(world, monkeypatch):
    data = _import(world, monkeypatch, fail_reads=True)
    stock = data["opening_stock"]
    assert stock["checked"] is False and stock["recorded"] is None and stock["not_recorded"] == []
    assert "could not be read to confirm" in stock["message"]


def test_an_import_with_no_opening_balances_asks_for_nothing(world, monkeypatch):
    import core.supabase_client as sc_client
    monkeypatch.setattr(sc_client, "get_supabase", lambda: world)
    out = sc.bulk_create_services(sc.ServiceBulkIn(services=[{"client_id": CLIENT, "name": "Audit", "kind": "service"}]),
                                  current_user=PARTNER)
    assert out["success"] is True and out["data"]["opening_stock"]["asked"] == 0
    assert out["data"]["opening_stock"]["message"] is None
