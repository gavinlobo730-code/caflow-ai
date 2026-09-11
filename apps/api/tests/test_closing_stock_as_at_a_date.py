"""
INV-01 — closing stock as at a date, and a movement ledger whose balance foots.

THE TWO THINGS BEING ASSERTED

1. There is a closing-stock figure for a DATE, summed from the ledger's deltas
   rather than read off its stored running totals, so it is right even when a
   document was entered late.

2. The drill-down's balance column adds up. The finding's own reproduction —
   a 10 July sale recorded first, then a backdated 1 July purchase — printed
   "+20 -> balance 110" above "-10 -> balance 90", neither of which foots. The
   balance is now derived in the order shown.

WHY THE DELTAS AND NOT THE RUNNING TOTALS
   The running totals are chained in INSERTION order, deliberately and for a
   good reason (see _last_ledger_row). That makes the stored total on a row the
   position as at the moment it was RECORDED, not as at its movement_date, so
   reading it off the last row on or before a date answers a different question.
   Addition commutes; the deltas do not have the problem.

THE INVARIANT THAT TIES IT ALL TOGETHER
   Over an item's WHOLE history the two agree exactly, because
   _compute_stock_out force-closes on the last unit out so that "the deltas
   always sum to the running value". test_over_the_whole_history_both_answers_
   agree pins that, and it is what makes the stock statement tie to the
   Inventory control account.
"""
from decimal import Decimal

import pytest

from domain.inventory_service import (
    record_stock_in, record_stock_out, get_stock_ledger, seed_opening_balance,
)
from domain.reporting import stock_position
from tests.test_inventory_service import _FakeDB, _seed_catalogue_item


FIRM, CLIENT, ITEM = "firm-1", "client-1", "item-1"


def _movements(db):
    return db.store.get("inventory_stock_ledger") or []


def _names(db):
    return {str(c["id"]): c for c in db.store.get("service_catalogue") or []}


def _position(db, as_of):
    return stock_position.position(_movements(db), as_of, _names(db))


def _one(db, as_of, item=ITEM):
    for row in _position(db, as_of)["items"]:
        if row["service_catalogue_id"] == item:
            return row
    return None


def _seed_backdated_case():
    """The finding's own reproduction, verbatim.

    Opening 100 units at ₹10 on 1 June. A 10 July sale of 10 recorded FIRST.
    Then a 1 July purchase of 20 recorded AFTER it — a bill received late,
    which the docstring on _last_ledger_row says is routine.
    """
    db = _FakeDB()
    _seed_catalogue_item(db)
    seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-06-01", opening_qty=Decimal("100"),
        opening_cost_paise=100 * 10_00,
    )
    record_stock_out(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-07-10", quantity=Decimal("10"), movement_type="sale",
        source_type="sales_invoice", source_id="inv-1", reference_no="INV-1",
    )
    record_stock_in(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-07-01", quantity=Decimal("20"),
        total_cost_paise=20 * 10_00, movement_type="purchase",
        source_type="purchase_bill", source_id="bill-1", reference_no="BILL-1",
    )
    return db


# ── 1. The position as at a date ─────────────────────────────────────────────

def test_a_date_before_any_movement_holds_nothing():
    db = _seed_backdated_case()
    assert _position(db, "2026-05-31")["items"] == []
    assert _position(db, "2026-05-31")["total_value_paise"] == 0


def test_the_opening_balance_is_the_position_on_its_own_date():
    db = _seed_backdated_case()
    row = _one(db, "2026-06-01")
    assert Decimal(row["qty_units"]) == Decimal("100")
    assert row["value_paise"] == 100 * 10_00
    assert row["avg_cost_paise"] == 10_00


def test_a_backdated_purchase_counts_on_its_own_date_not_when_it_was_typed():
    """The whole point. On 1 July the client held 120 units — the opening 100
    plus the 20 that arrived that day — even though that bill was entered after
    the 10 July sale. The stored running total on that row says 110, because
    when it was RECORDED the sale had already gone through."""
    db = _seed_backdated_case()
    row = _one(db, "2026-07-01")
    assert Decimal(row["qty_units"]) == Decimal("120")
    assert row["value_paise"] == 120 * 10_00

    # And the stored column really does say otherwise — this is not a strawman.
    backdated = [m for m in _movements(db) if m["movement_date"] == "2026-07-01"][0]
    assert Decimal(backdated["running_qty_units"]) == Decimal("110")


def test_a_date_between_the_two_july_movements_excludes_the_later_one():
    db = _seed_backdated_case()
    assert Decimal(_one(db, "2026-07-05")["qty_units"]) == Decimal("120")


def test_after_both_july_movements_the_position_is_110():
    db = _seed_backdated_case()
    row = _one(db, "2026-07-31")
    assert Decimal(row["qty_units"]) == Decimal("110")
    assert row["value_paise"] == 110 * 10_00


def test_over_the_whole_history_both_answers_agree():
    """The invariant the balance sheet rests on: summing every delta gives the
    same figure as the perpetual chain's last row. _compute_stock_out's
    force-close is what makes it true."""
    db = _seed_backdated_case()
    newest = _movements(db)[-1]          # _FakeDB appends in insertion order
    row = _one(db, "2999-12-31")
    assert Decimal(row["qty_units"]) == Decimal(newest["running_qty_units"])
    assert row["value_paise"] == int(newest["running_value_paise"])


def test_selling_the_last_unit_leaves_no_value_behind():
    """Force-close, seen from the date side: many small sales at a rounded
    per-unit cost must not strand paise on a zero quantity."""
    db = _FakeDB()
    _seed_catalogue_item(db)
    seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-01", opening_qty=Decimal("3"), opening_cost_paise=1_000,
    )
    for n, day in enumerate(("2026-04-02", "2026-04-03", "2026-04-04")):
        record_stock_out(
            db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
            movement_date=day, quantity=Decimal("1"), movement_type="sale",
            source_type="sales_invoice", source_id=f"inv-{n}", reference_no=f"INV-{n}",
        )
    row = _one(db, "2026-04-30")
    assert Decimal(row["qty_units"]) == Decimal("0")
    assert row["value_paise"] == 0
    assert row["avg_cost_paise"] == 0      # not value/qty — that would divide by zero


def test_the_total_is_summed_from_the_deltas_not_from_the_rounded_averages():
    """qty * avg_cost re-rounds an already-rounded average. Across a register
    that drifts, and the drift is exactly what stops it tying to the Inventory
    control account. 1,000 paise over 3 units is 333.33/unit."""
    db = _FakeDB()
    _seed_catalogue_item(db)
    seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-01", opening_qty=Decimal("3"), opening_cost_paise=1_000,
    )
    out = _position(db, "2026-04-30")
    row = out["items"][0]
    assert out["total_value_paise"] == 1_000
    # The per-unit average rounds; 3 x 333 is 999, and the total is not that.
    assert row["avg_cost_paise"] == 333
    assert out["total_value_paise"] != row["avg_cost_paise"] * 3


def test_a_nil_item_is_reported_rather_than_dropped():
    """A register that silently omits rows cannot be tied to a control account
    by somebody who does not know which rows it dropped."""
    db = _FakeDB()
    _seed_catalogue_item(db)
    seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-01", opening_qty=Decimal("5"), opening_cost_paise=5_00,
    )
    record_stock_out(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=ITEM,
        movement_date="2026-04-02", quantity=Decimal("5"), movement_type="sale",
        source_type="sales_invoice", source_id="inv-1", reference_no="INV-1",
    )
    out = _position(db, "2026-04-30")
    assert len(out["items"]) == 1
    assert Decimal(out["items"][0]["qty_units"]) == Decimal("0")


def test_two_items_are_two_rows_and_one_total():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="item-1", name="Widget")
    _seed_catalogue_item(db, item_id="item-2", name="Bracket")
    for item, qty, cost in (("item-1", 10, 10_000), ("item-2", 4, 2_000)):
        seed_opening_balance(
            db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item,
            movement_date="2026-04-01", opening_qty=Decimal(qty), opening_cost_paise=cost,
        )
    out = _position(db, "2026-04-30")
    assert [r["name"] for r in out["items"]] == ["Bracket", "Widget"]   # by name
    assert out["total_value_paise"] == 12_000
    assert out["total_items"] == 2


# ── 2. The balance column foots ──────────────────────────────────────────────

def test_the_stored_running_columns_do_not_foot_in_display_order():
    """The defect, stated as a test so the fix cannot be mistaken for a
    no-op. Delete this only when the chain itself changes."""
    db = _seed_backdated_case()
    rows = get_stock_ledger(db, ITEM)
    assert [r["movement_date"] for r in rows] == [
        "2026-06-01", "2026-07-01", "2026-07-10"]

    prev = Decimal(rows[0]["running_qty_units"])
    delta = Decimal(rows[1]["quantity_delta"])
    assert prev + delta != Decimal(rows[1]["running_qty_units"])   # 100 + 20 != 110


def test_every_row_foots_once_the_balance_is_derived_in_display_order():
    db = _seed_backdated_case()
    rows = stock_position.ledger_with_balances(
        get_stock_ledger(db, ITEM), Decimal("0"), 0)

    running_qty, running_value = Decimal("0"), 0
    for r in rows:
        running_qty += Decimal(r["quantity_delta"])
        running_value += int(r["value_delta_paise"])
        assert Decimal(r["balance_qty_units"]) == running_qty
        assert r["balance_value_paise"] == running_value

    assert [str(Decimal(r["balance_qty_units"])) for r in rows] == ["100", "120", "110"]


def test_the_derived_balance_leaves_the_stored_columns_alone():
    """New keys, not a relabelling: running_qty_units is what the database
    holds and what every future movement costs off."""
    db = _seed_backdated_case()
    raw = get_stock_ledger(db, ITEM)
    rows = stock_position.ledger_with_balances(raw, Decimal("0"), 0)
    for before, after in zip(raw, rows):
        assert after["running_qty_units"] == before["running_qty_units"]
        assert after["running_value_paise"] == before["running_value_paise"]


def test_a_filtered_range_runs_forward_from_its_opening():
    """A drill-down filtered to July opens at the 30 June position, so the
    closing figure still equals the position as at 31 July."""
    db = _seed_backdated_case()
    opening = _one(db, "2026-06-30")
    rows = stock_position.ledger_with_balances(
        get_stock_ledger(db, ITEM, "2026-07-01", "2026-07-31"),
        Decimal(opening["qty_units"]), opening["value_paise"])

    assert [r["movement_date"] for r in rows] == ["2026-07-01", "2026-07-10"]
    closing = _one(db, "2026-07-31")
    assert Decimal(rows[-1]["balance_qty_units"]) == Decimal(closing["qty_units"])
    assert rows[-1]["balance_value_paise"] == closing["value_paise"]


def test_an_empty_range_still_carries_its_opening():
    db = _seed_backdated_case()
    opening = _one(db, "2026-06-30")
    rows = stock_position.ledger_with_balances(
        get_stock_ledger(db, ITEM, "2026-08-01", "2026-08-31"),
        Decimal(opening["qty_units"]), opening["value_paise"])
    assert rows == []
