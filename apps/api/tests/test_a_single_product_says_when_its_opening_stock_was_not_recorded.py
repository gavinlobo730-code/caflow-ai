"""A product created or edited one at a time says when its opening stock was not recorded (POST-A-092, the single-product half).

WHAT WAS WRONG
    `create_service` and `update_service` save the product and then seed an opening stock row for a goods line that came with a quantity
    and a cost. The product row already exists by then, so a failure of the seeding was logged and not raised, and the route answered a
    plain success: the catalogue row kept `opening_qty_units` and `opening_cost_paise` over a stock ledger with no opening row, the Stock
    column read 0, and the form said "created". The bulk import was fixed first (`opening_stock` on its response); this is the same
    answer for the one item, asked of the stock ledger and not inferred from the seeding having returned.

WHAT IS HELD
    * a create that asked for an opening balance answers `opening_stock`: recorded says nothing, a refused ledger insert names the
      product in the server's sentence, a ledger that cannot be read is "could not check" and never "recorded";
    * the product is saved in every case;
    * a create with no opening balance, and a service, answer exactly as before (no key);
    * an EDIT answers only when it could be the edit that records the opening stock, because seeding is a no-op for an item that already
      has an opening row; an edit of the quantity on an item that already has one answers nothing and the stock keeps its old figure (said
      here so the day it is fixed the test changes with it, and on the ledger line);
    * a check that itself raises still answers, as "could not check", and never as a clean result.
"""
from __future__ import annotations

import pytest

import routers.service_catalogue as sc
from models.service_catalogue import ServiceCatalogueIn, ServiceCatalogueUpdateIn
from tests.e2e_harness import FakeDB

FIRM = "firm-one-92"
CLIENT = "client-one-92"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


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
    monkeypatch.setattr(sc, "_assert_service_scope", lambda *a, **k: None)
    return fake


def _through(world, monkeypatch, **proxy):
    import core.supabase_client as sc_client
    monkeypatch.setattr(sc_client, "get_supabase", lambda: _Ledger(world, **proxy))


def _create(name="Widget", kind="good", **extra):
    body = {"client_id": CLIENT, "name": name, "kind": kind, **extra}
    return sc.create_service(ServiceCatalogueIn(**body), current_user=PARTNER)


def _goods(**extra):
    return _create(kind="good", opening_qty_units=10, opening_cost_paise=5_000, opening_balance_date="2026-04-01", **extra)


# ── a create ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_create_whose_opening_stock_landed_says_so_without_a_sentence(world, monkeypatch):
    _through(world, monkeypatch)
    out = _goods()
    assert out["success"] is True
    stock = out["data"]["opening_stock"]
    assert stock["asked"] == 1 and stock["recorded"] == 1 and stock["checked"] is True
    assert stock["message"] is None and stock["not_recorded"] == []


def test_a_create_whose_ledger_insert_was_refused_names_the_product_and_still_saves_it(world, monkeypatch):
    _through(world, monkeypatch, refuse_insert=True)
    out = _goods()
    assert out["success"] is True and out["data"]["id"], "the product is saved whatever the stock did"
    stock = out["data"]["opening_stock"]
    assert stock["asked"] == 1 and stock["recorded"] == 0 and stock["checked"] is True
    assert [r["name"] for r in stock["not_recorded"]] == ["Widget"]
    assert "not recorded for 1 of 1 product" in stock["message"] and "“Widget”" in stock["message"]
    assert "The product was created without it" in stock["message"]


def test_a_create_that_cannot_read_the_ledger_back_claims_neither_way(world, monkeypatch):
    _through(world, monkeypatch, fail_reads=True)
    out = _goods()
    assert out["success"] is True
    stock = out["data"]["opening_stock"]
    assert stock["checked"] is False and stock["recorded"] is None and stock["not_recorded"] == []
    assert "could not be read to confirm" in stock["message"]


def test_a_create_with_no_opening_balance_answers_as_it_always_did(world, monkeypatch):
    _through(world, monkeypatch)
    for out in (_create(name="Plain goods", kind="good"), _create(name="Audit", kind="service")):
        assert out["success"] is True
        assert "opening_stock" not in out["data"], "a response with nothing asked of the stock must not grow a key"


def test_a_check_that_raises_is_could_not_check_and_never_a_clean_answer(world, monkeypatch):
    _through(world, monkeypatch)

    def _boom(*a, **k):
        raise _Refused("the check itself failed")
    monkeypatch.setattr(sc, "_opening_stock_answer", _boom)
    out = _goods()
    assert out["success"] is True, "the product is saved either way"
    stock = out["data"]["opening_stock"]
    assert stock["checked"] is False and stock["message"] and "could not be read to confirm" in stock["message"]


# ── an edit ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _edit(item_id, **fields):
    return sc.update_service(item_id, ServiceCatalogueUpdateIn(**fields), current_user=PARTNER)


def test_an_edit_that_gives_a_product_its_first_opening_balance_says_whether_it_landed(world, monkeypatch):
    _through(world, monkeypatch)
    item = _create(name="Late stock", kind="good")["data"]
    out = _edit(item["id"], opening_qty_units=4, opening_cost_paise=2_500, opening_balance_date="2026-04-01")
    assert out["success"] is True
    stock = out["data"]["opening_stock"]
    assert stock["recorded"] == 1 and stock["message"] is None


def test_an_edit_whose_ledger_insert_is_refused_names_the_product(world, monkeypatch):
    item = _create(name="Refused late", kind="good")["data"]
    _through(world, monkeypatch, refuse_insert=True)
    out = _edit(item["id"], opening_qty_units=4, opening_cost_paise=2_500, opening_balance_date="2026-04-01")
    assert out["success"] is True
    stock = out["data"]["opening_stock"]
    assert stock["recorded"] == 0 and "“Refused late”" in stock["message"]
    # an edit is not a creation, and the Stock column need not read 0: the sentence says only what is true of a product saved again
    assert "created" not in stock["message"] and "shows 0" not in stock["message"]
    assert "saved without it" in stock["message"] and "no opening stock row" in stock["message"]


def test_an_edit_of_an_item_that_already_has_an_opening_row_answers_nothing_and_the_old_figure_stays(world, monkeypatch):
    """Seeding is a no-op once an opening row exists, so an edited quantity is not applied. That is a real gap and is NOT this change: it is
    named on the ledger line. What is held here is that the edit does not claim a record it did not make."""
    _through(world, monkeypatch)
    item = _goods()["data"]
    before = [dict(r) for r in world.rows("inventory_stock_ledger")]
    out = _edit(item["id"], opening_qty_units=99, opening_cost_paise=7_000)
    assert out["success"] is True
    assert "opening_stock" not in out["data"]
    assert [dict(r) for r in world.rows("inventory_stock_ledger")] == before, "the existing opening row must be left exactly as it was"


def test_an_edit_that_does_not_touch_the_opening_balance_answers_as_it_always_did(world, monkeypatch):
    _through(world, monkeypatch)
    item = _goods()["data"]
    out = _edit(item["id"], description="renamed text only")
    assert out["success"] is True and "opening_stock" not in out["data"]


def test_the_sentence_for_a_product_saved_again_does_not_say_it_was_created():
    from domain.inventory import opening_stock_report as report
    created = report.report([{"id": "i1", "name": "Widget"}], set())
    edited = report.report([{"id": "i1", "name": "Widget"}], set(), edited=True)
    assert "created without it" in created["message"] and "shows 0" in created["message"]
    assert "created" not in edited["message"] and "shows 0" not in edited["message"] and "saved without it" in edited["message"]
    assert edited["not_recorded"] == created["not_recorded"] and edited["recorded"] == created["recorded"]

