"""The reorder report is CALLED with a database, which it never was.

`test_an_item_has_a_second_unit_and_a_level_to_reorder_at.py` exercises
`domain/inventory/reorder.assess` thoroughly and then checks
`services/reorder_service.py` by reading its SOURCE. Nothing anywhere called
`reorder_service.assess(db, ...)`, and it could not have worked: `_catalogue`
handed `core.db_paging.fetch_all` a query BUILDER where it takes a callable, so
the first page raised `TypeError: '_Query' object is not callable`.

The feature was therefore dead from the day it shipped, and invisibly:

  * `routers/inventory.reorder_report` wraps the call in `except Exception` and
    answers `success: false` with "Unable to load the reorder report. Please
    try again." — which reads as a transient failure, not a permanent one.
  * The mock suite could not reach it. That router's `_USE_MOCK` branch passes
    `db=None`, and `assess` short-circuits to an empty answer BEFORE the fetch.
    So every test of the service ran the branch with no database in it.

That second point is the durable lesson and is why this module exists rather
than a one-line fix: a service whose job is to FETCH needs a test that fetches.
A source scan cannot see an arity error, and the mock-mode branch is not the
code that runs in production.

`tests/test_fetch_all_is_given_something_it_can_call.py` states the general
rule; this states the specific claim — that the report answers.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import FakeDB

from services import reorder_service


FIRM = "44444444-4444-4444-8444-444444444444"
CLIENT = "55555555-5555-4555-8555-555555555555"


def _item(db, name, *, level, on_hand, category=None, kind="good", active=True):
    row = db.seed("service_catalogue", {
        "firm_id": FIRM, "client_id": CLIENT, "name": name, "unit": "NOS",
        "kind": kind, "category": category, "is_active": active,
        "reorder_level_units": level,
        "alternate_unit": None, "units_per_alternate": None,
    })
    if on_hand:
        db.seed("inventory_stock_ledger", {
            "firm_id": FIRM, "client_id": CLIENT,
            "service_catalogue_id": row["id"],
            "movement_date": "2026-04-01",
            "quantity_delta": on_hand, "value_delta_paise": 0,
        })
    return row


@pytest.fixture()
def db():
    d = FakeDB()
    # below: 5 on hand against a level of 10
    _item(d, "Cement", level="10", on_hand="5", category="Raw Material")
    # at: the level itself counts — a reorder level is the point you reorder
    _item(d, "Sand", level="20", on_hand="20", category="Raw Material")
    # above: comfortably stocked
    _item(d, "Steel", level="10", on_hand="90", category="Raw Material")
    # no level recorded: NOT a zero, and NOT in the buy list
    _item(d, "Tarpaulin", level=None, on_hand="0", category="Consumable")
    # a SERVICE is not stock at all
    _item(d, "Site supervision", level="1", on_hand=None, kind="service")
    return d


def test_the_report_answers_at_all(db):
    """The headline. Against a real database this raised TypeError."""
    out = reorder_service.assess(db, FIRM, CLIENT)
    assert isinstance(out, dict)
    assert "groups" in out and "to_reorder" in out


def test_it_counts_what_is_at_or_below_the_level(db):
    """Cement is below, Sand is AT — and at the level is below it, because a
    reorder level is the point at which you reorder."""
    assert reorder_service.assess(db, FIRM, CLIENT)["to_reorder"] == 2


def test_an_item_with_no_level_is_named_rather_than_counted(db):
    out = reorder_service.assess(db, FIRM, CLIENT)
    assert out["no_level_recorded"] == 1
    assert out["to_reorder"] == 2, "an absent level is not zero, so it is not a buy"


def test_a_service_line_is_not_stock(db):
    """`kind = 'good'` is in the query, so a service never reaches the rule."""
    names = {ln["name"]
             for g in reorder_service.assess(db, FIRM, CLIENT)["groups"]
             for ln in g["lines"]}
    assert "Site supervision" not in names
    assert reorder_service.assess(db, FIRM, CLIENT)["items_considered"] == 4


def test_the_on_hand_figure_is_the_ledger_and_not_the_cached_column(db):
    """Migration 188 documents `stock_qty_units` as a CACHE. A prompt to buy,
    computed off a drifted cache, says there is stock there is not — so the
    report must ignore a cache that disagrees with the ledger."""
    for row in db.rows("service_catalogue"):
        row["stock_qty_units"] = "9999"          # a cache claiming plenty
    assert reorder_service.assess(db, FIRM, CLIENT)["to_reorder"] == 2


def test_an_unrecorded_group_is_its_own_row(db):
    _item(db, "Nails", level="5", on_hand="1", category=None)
    groups = {g["group"] for g in reorder_service.assess(db, FIRM, CLIENT)["groups"]}
    assert "Raw Material" in groups
    assert any("no item group" in g for g in groups), groups


def test_another_firms_stock_is_not_in_the_answer(db):
    """The app-layer firm filter is the primary isolation control — the
    service-role key bypasses RLS."""
    other = db.seed("service_catalogue", {
        "firm_id": "99999999-9999-4999-8999-999999999999", "client_id": CLIENT,
        "name": "Somebody else's cement", "unit": "NOS", "kind": "good",
        "is_active": True, "reorder_level_units": "1000", "category": "Raw Material",
    })
    db.seed("inventory_stock_ledger", {
        "firm_id": "99999999-9999-4999-8999-999999999999", "client_id": CLIENT,
        "service_catalogue_id": other["id"], "movement_date": "2026-04-01",
        "quantity_delta": "0", "value_delta_paise": 0,
    })
    out = reorder_service.assess(db, FIRM, CLIENT)
    assert out["items_considered"] == 4
    assert out["to_reorder"] == 2


def test_no_database_is_an_empty_answer_and_not_a_fabricated_one(db):
    """The mock-mode branch, asserted so its existence stays deliberate — it is
    what hid the defect, and it is still the right behaviour."""
    out = reorder_service.assess(None, FIRM, CLIENT)
    assert out["to_reorder"] == 0
    assert out["items_considered"] == 0
    assert out["groups"] == []
