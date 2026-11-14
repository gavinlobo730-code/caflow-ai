"""The stock register reads each item's latest stock-ledger row from the database, and lists every good (POST-A-435, migration 588).

WHAT WAS WRONG
    The register shows an item's quantity, average cost and value from its LATEST stock-ledger row. `_last_ledger_rows` found those
    rows by paging the client's movements newest first with an IN list that shrank as items were found, and stopped after eight pages
    of a thousand. Each page finds the items among its rows, so the scan ran out only when page after page was filled by one busy item
    each: with eight items that each had a thousand movements more recent than the next, every item older than those eight was not
    reached, and the register showed it at ZERO quantity and ZERO value, with a log line only. The item list
    beside it was one request, which PostgREST answers with at most a thousand rows, so a client with more goods saw the first thousand.

WHAT IS HELD
    * the items the old scan never reached (nine busy items filling a page each, and a slow one) show their own figures, not zero;
    * the database is asked ONCE, on the privileged client, naming the firm, the client and the items, and nothing is asked for none;
    * an answer that is not a list is a refusal of the whole register in words, never a register of zeros;
    * the item list is read in full, in name order, past one page;
    * the twin's rule: newest recorded first, then the larger id; another firm's or client's rows, and items not asked for, ignored;
    * the posting chain's own read breaks a tie on the recorded-at instant the same way, so the register shows the row the next
      movement will cost from.
"""
from __future__ import annotations

import pytest

import routers.inventory as inv
from core import db_paging
from domain.inventory.latest_rows import latest_rows
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-SR", "CLI-SR"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _register(monkeypatch) -> FakeDB:
    db = FakeDB()
    wire_e2e(monkeypatch, db, [inv])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(inv, "_USE_MOCK", False)
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM})
    return db


def _good(db, item_id, name):
    db.seed("service_catalogue", {"id": item_id, "firm_id": FIRM, "client_id": CLIENT, "name": name, "kind": "good"})


def _row(db, item_id, created_at, qty, value, *, row_id=None, firm=FIRM, client=CLIENT):
    seeded = {"firm_id": firm, "client_id": client, "service_catalogue_id": item_id, "created_at": created_at,
              "movement_date": created_at[:10], "running_qty_units": str(qty), "running_avg_cost_paise": value // max(qty, 1),
              "running_value_paise": value}
    if row_id:
        seeded["id"] = row_id
    db.seed("inventory_stock_ledger", seeded)


def _items(monkeypatch, db):
    out = inv.list_stock_items(client_id=CLIENT, current_user=CALLER)
    assert out["success"] is True, out
    return {r["id"]: r for r in out["data"]}, out["data"]


def test_items_the_old_scan_never_reached_show_their_own_figures_and_not_zero(monkeypatch):
    """The old scan re-asked only for the items not yet found, so it stopped short only when page after page was filled by ONE busy
    item each: nine items with a thousand movements apiece, each more recent than the next, and a slow item older than all of them.
    Eight pages found the eight busiest; the ninth and the slow item were shown at zero quantity and zero value."""
    db = _register(monkeypatch)
    _good(db, "SLOW", "Slow mover")
    _row(db, "SLOW", "2023-01-01T10:00:00+00:00", 7, 70_000)
    for k in range(9):                                               # BUSY0 newest ... BUSY8 oldest, each a full page of its own
        _good(db, f"BUSY{k}", f"Busy {k}")
        for i in range(1000):
            _row(db, f"BUSY{k}", f"{2032 - k}-01-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+00:00", i + 1, (i + 1) * 100)
    by_id, _ = _items(monkeypatch, db)
    assert (by_id["SLOW"]["stock_qty_units"], by_id["SLOW"]["stock_value_paise"]) == (7.0, 70_000), "the old scan showed zero"
    assert by_id["BUSY8"]["stock_qty_units"] == 1000.0, "the old scan showed zero"
    assert all(by_id[f"BUSY{k}"]["stock_qty_units"] == 1000.0 for k in range(9))


def test_the_database_is_asked_once_on_the_privileged_client_naming_the_firm_the_client_and_the_items(monkeypatch):
    db = _register(monkeypatch)
    _good(db, "B", "Bolt")
    _good(db, "A", "Anvil")
    calls = []

    class Privileged:
        def rpc(self, fn, params):
            calls.append((fn, params))

            class R:
                def execute(self_inner):
                    class Res:
                        data = [{"service_catalogue_id": "A", "running_qty_units": "2", "running_avg_cost_paise": 50,
                                 "running_value_paise": 100}]
                    return Res()
            return R()

    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: Privileged())
    monkeypatch.setattr("core.acting_client.acting_as_request_person", lambda client: client)
    by_id, _ = _items(monkeypatch, db)
    assert calls == [("stock_latest_rows", {"p_firm": FIRM, "p_client": CLIENT, "p_items": ["A", "B"]})]
    assert by_id["A"]["stock_value_paise"] == 100 and by_id["B"]["stock_qty_units"] == 0.0, "an item never moved shows nothing received"


def test_no_items_asks_nothing():
    class Refuses:
        def rpc(self, *a, **k):
            raise AssertionError("asked the database about no items")

    assert inv._last_ledger_rows(Refuses(), FIRM, CLIENT, set()) == {}


@pytest.mark.parametrize("answer", [None, {"rows": []}, "oops"])
def test_an_answer_that_is_not_a_list_refuses_the_register_in_words_rather_than_showing_zeros(monkeypatch, answer):
    db = _register(monkeypatch)
    _good(db, "A", "Anvil")
    _row(db, "A", "2025-01-01T00:00:00+00:00", 3, 300)

    class Odd:
        def rpc(self, fn, params):
            class R:
                def execute(self_inner):
                    class Res:
                        data = answer
                    return Res()
            return R()

    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: Odd())
    monkeypatch.setattr("core.acting_client.acting_as_request_person", lambda client: client)
    out = inv.list_stock_items(client_id=CLIENT, current_user=CALLER)
    assert out["success"] is False and out["data"] is None and "Unable to load the stock register" in out["error"]


def _answers_at_most_a_page(db, monkeypatch):
    """PostgREST answers a select with at most `db-max-rows` rows and says nothing; the in-memory double answers everything. Cut every
    select it answers to `db_paging.PAGE`, so a read that does not page loses rows here as it does against the real server."""
    from tests import e2e_harness

    real_execute = e2e_harness._Query.execute

    def capped(self):
        res = real_execute(self)
        if self._op == "select" and isinstance(res.data, list) and len(res.data) > db_paging.PAGE:
            res.data = res.data[:db_paging.PAGE]
        return res

    monkeypatch.setattr(e2e_harness._Query, "execute", capped)


def test_the_item_list_is_read_in_full_and_in_name_order_past_one_page(monkeypatch):
    db = _register(monkeypatch)
    monkeypatch.setattr(db_paging, "PAGE", 3)
    _answers_at_most_a_page(db, monkeypatch)
    names = ["Gear", "Anvil", "Lathe", "Bolt", "Drill", "Clamp", "File"]
    for i, name in enumerate(names):
        _good(db, f"I{i}", name)
    db.seed("service_catalogue", {"id": "S", "firm_id": FIRM, "client_id": CLIENT, "name": "Advice", "kind": "service"})
    _, listed = _items(monkeypatch, db)
    assert [r["name"] for r in listed] == sorted(names), "a service was listed, or a page was dropped, or the order was lost"


def test_the_twin_takes_the_newest_recorded_row_then_the_larger_id_and_nothing_of_anyone_else():
    rows = [
        {"id": "a", "firm_id": "F", "client_id": "C", "service_catalogue_id": "X", "created_at": "2025-01-01T10:00:00+00:00",
         "running_qty_units": "1"},
        {"id": "b", "firm_id": "F", "client_id": "C", "service_catalogue_id": "X", "created_at": "2025-01-01T15:30:00+05:30",
         "running_qty_units": "2"},                                          # the same instant, a larger id: this one
        {"id": "c", "firm_id": "F", "client_id": "C", "service_catalogue_id": "X", "created_at": "2024-12-31T10:00:00+00:00",
         "running_qty_units": "9"},
        {"id": "z", "firm_id": "OTHER", "client_id": "C", "service_catalogue_id": "X", "created_at": "2026-01-01T00:00:00+00:00",
         "running_qty_units": "99"},
        {"id": "y", "firm_id": "F", "client_id": "OTHER", "service_catalogue_id": "X", "created_at": "2026-01-01T00:00:00+00:00",
         "running_qty_units": "98"},
        {"id": "w", "firm_id": "F", "client_id": "C", "service_catalogue_id": "UNASKED", "created_at": "2026-01-01T00:00:00+00:00",
         "running_qty_units": "5"},
    ]
    got = latest_rows(rows, "F", "C", ["X", "NEVER"])
    assert set(got) == {"X"} and got["X"]["running_qty_units"] == "2"
    assert set(got["X"]) == {"service_catalogue_id", "running_qty_units", "running_avg_cost_paise", "running_value_paise"}


def test_the_posting_chain_breaks_a_tie_on_the_recorded_instant_the_way_the_register_does(monkeypatch):
    from domain import inventory_service
    db = FakeDB()
    for row_id, qty in (("0001", "4"), ("0002", "6")):
        db.seed("inventory_stock_ledger", {"id": row_id, "service_catalogue_id": "X", "created_at": "2025-01-01T00:00:00+00:00",
                                           "running_qty_units": qty, "running_value_paise": 1, "running_avg_cost_paise": 1})
    chained = inventory_service._last_ledger_row(db, "X")
    shown = latest_rows([{**r, "firm_id": "F", "client_id": "C"} for r in db.rows("inventory_stock_ledger")], "F", "C", ["X"])["X"]
    assert chained["running_qty_units"] == shown["running_qty_units"] == "6"


def test_the_nightly_cache_check_compares_against_the_same_latest_row(monkeypatch):
    """The drift check read every movement and kept, on a tie of the recorded instant, the SMALLER id: the opposite of the register
    and the posting chain. It now asks the same function, so a cache that matches the chain head is not reported as drift."""
    from services import reconciliation_service
    db = _register(monkeypatch)
    db.seed("service_catalogue", {"id": "A", "firm_id": FIRM, "client_id": CLIENT, "name": "Anvil", "kind": "good",
                                  "stock_qty_units": "6", "avg_cost_paise": 100})
    for row_id, qty in (("0001", 4), ("0002", 6)):
        _row(db, "A", "2025-01-01T00:00:00+00:00", qty, qty * 100, row_id=row_id)
    assert reconciliation_service.check_inventory_cache_drift(db, FIRM, CLIENT, []) == [], "the smaller id was taken as the chain head"
