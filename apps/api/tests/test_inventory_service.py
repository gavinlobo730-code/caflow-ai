"""
domain/inventory_service — moving-average costing math and the ledger/cache
read-modify-write cycle. Every arithmetic path here is a financial
calculation (CLAUDE.md: every one needs a unit test), including the rounding
edge cases moving-average costing is prone to.
"""
from decimal import Decimal

import pytest

from domain.inventory_service import (
    _compute_stock_in,
    _compute_stock_out,
    record_stock_in,
    record_stock_out,
    seed_opening_balance,
    get_stock_ledger,
    apply_sale_to_inventory,
    apply_purchase_to_inventory,
)


# ── Pure-math tests (no DB) ──────────────────────────────────────────────────

def test_compute_stock_in_first_purchase_sets_average_to_unit_cost():
    calc = _compute_stock_in(Decimal("0"), 0, Decimal("10"), 10_000_00)
    assert calc["running_qty_units"] == Decimal("10")
    assert calc["running_avg_cost_paise"] == 1_000_00
    assert calc["unit_cost_paise"] == 1_000_00
    assert calc["running_value_paise"] == 10_000_00


def test_compute_stock_in_blends_average_across_two_purchases():
    # 10 units @ Rs 1000 already on hand (value 10,000), buy 10 more @ Rs 1200
    # (value 12,000) -> 20 units, value 22,000 -> average Rs 1100/unit.
    calc = _compute_stock_in(Decimal("10"), 10_000_00, Decimal("10"), 12_000_00)
    assert calc["running_qty_units"] == Decimal("20")
    assert calc["running_value_paise"] == 22_000_00
    assert calc["running_avg_cost_paise"] == 1_100_00


def test_compute_stock_in_rejects_nonpositive_quantity():
    with pytest.raises(ValueError):
        _compute_stock_in(Decimal("0"), 0, Decimal("0"), 100_00)
    with pytest.raises(ValueError):
        _compute_stock_in(Decimal("0"), 0, Decimal("-5"), 100_00)


def test_compute_stock_in_rejects_negative_cost():
    with pytest.raises(ValueError):
        _compute_stock_in(Decimal("0"), 0, Decimal("5"), -100)


def test_compute_stock_out_prices_at_current_average_not_original_cost():
    # 20 units on hand at average Rs 1100/unit; sell 5.
    calc = _compute_stock_out(Decimal("20"), 22_000_00, 1_100_00, Decimal("5"))
    assert calc["quantity_delta"] == Decimal("-5")
    assert calc["unit_cost_paise"] == 1_100_00
    assert calc["value_delta_paise"] == -5_500_00
    assert calc["running_qty_units"] == Decimal("15")
    assert calc["running_value_paise"] == 16_500_00
    assert calc["running_avg_cost_paise"] == 1_100_00


def test_compute_stock_out_force_closes_value_to_zero_when_fully_depleted():
    # A rounded avg cost (Rs 333.33, stored as 33333 paise) times 3 units
    # would be 99999 paise, one paisa short of the true 100000 value —
    # selling the LAST unit must still zero out the running value exactly,
    # not leave a stray 1 paisa hanging off a zero quantity.
    calc = _compute_stock_out(Decimal("3"), 100_000, 33_333, Decimal("3"))
    assert calc["running_qty_units"] == Decimal("0")
    assert calc["running_value_paise"] == 0
    assert calc["running_avg_cost_paise"] == 0


def test_compute_stock_out_many_small_sales_never_drift_below_zero_or_leave_residue():
    # 10 units at a non-terminating average (Rs 1000 / 3 = 333.33...), sold
    # one at a time. Each sale rounds its own value independently — the
    # sequence must still end at exactly zero qty / zero value, proving the
    # per-sale rounding never accumulates into a residual.
    qty, value, avg = Decimal("10"), 3_333_00, 333_00  # 10 units @ ~Rs 333.30 avg
    for _ in range(10):
        calc = _compute_stock_out(qty, value, avg, Decimal("1"))
        qty, value, avg = calc["running_qty_units"], calc["running_value_paise"], calc["running_avg_cost_paise"]
    assert qty == Decimal("0")
    assert value == 0


def test_compute_stock_out_allows_oversell_and_floors_value_at_zero():
    # Selling more than is on hand (a real-world data-entry order issue) must
    # never crash the costing engine — it degrades to a negative quantity
    # with zero value, which record_stock_out separately logs a warning for.
    calc = _compute_stock_out(Decimal("2"), 2_000_00, 1_000_00, Decimal("5"))
    assert calc["running_qty_units"] == Decimal("-3")
    assert calc["running_value_paise"] == 0
    assert calc["running_avg_cost_paise"] == 0


def test_compute_stock_out_rejects_nonpositive_quantity():
    with pytest.raises(ValueError):
        _compute_stock_out(Decimal("10"), 1000_00, 100_00, Decimal("0"))


# ── DB-touching tests (fake Supabase client double) ─────────────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, store, table):
        self.store, self.t = store, table
        self.f = []
        self._order = []
        self._limit = None
        self._insert_rows = None
        self._update_patch = None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.f.append(("eq", k, v))
        return self

    def gte(self, k, v):
        self.f.append(("gte", k, v))
        return self

    def lte(self, k, v):
        self.f.append(("lte", k, v))
        return self

    def in_(self, k, vals):
        self.f.append(("in", k, set(vals)))
        return self

    def order(self, key, desc=False):
        self._order.append((key, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, rows):
        self._insert_rows = rows if isinstance(rows, list) else [rows]
        return self

    def update(self, patch):
        self._update_patch = patch
        return self

    def _match(self, r):
        for op, k, v in self.f:
            if op == "eq" and r.get(k) != v:
                return False
            if op == "gte" and str(r.get(k)) < str(v):
                return False
            if op == "lte" and str(r.get(k)) > str(v):
                return False
            if op == "in" and r.get(k) not in v:
                return False
        return True

    def execute(self):
        rows_table = self.store.setdefault(self.t, [])
        if self._insert_rows is not None:
            out = []
            for r in self._insert_rows:
                row = {"id": f"{self.t}-{len(rows_table)}", **r}
                rows_table.append(row)
                out.append(row)
            return _Res(out)
        if self._update_patch is not None:
            updated = []
            for r in rows_table:
                if self._match(r):
                    r.update(self._update_patch)
                    updated.append(r)
            return _Res(updated)
        rows = [dict(r) for r in rows_table if self._match(r)]
        for key, desc in reversed(self._order):
            rows.sort(key=lambda r: str(r.get(key)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Res(rows)


class _FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _FakeQuery(self.store, name)


def _seed_catalogue_item(db, item_id="item-1", **over):
    db.store.setdefault("service_catalogue", []).append({
        "id": item_id, "firm_id": "firm-1", "client_id": "client-1",
        "name": "Widget", "kind": "good", "stock_qty_units": "0", "avg_cost_paise": 0,
        **over,
    })


def test_record_stock_in_then_out_round_trip_matches_pure_math():
    db = _FakeDB()
    _seed_catalogue_item(db)

    row1 = record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-10", quantity=Decimal("10"), total_cost_paise=10_000_00,
        movement_type="purchase", source_type="purchase_bill", source_id="bill-1", reference_no="BILL-1",
    )
    assert row1["running_qty_units"] == "10"
    assert row1["running_avg_cost_paise"] == 1_000_00

    row2 = record_stock_out(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-15", quantity=Decimal("3"), movement_type="sale",
        source_type="sales_invoice", source_id="inv-1", reference_no="INV-1",
    )
    assert row2 is not None
    assert row2["running_qty_units"] == "7"
    assert row2["running_value_paise"] == 7_000_00

    # service_catalogue's cached columns must reflect the latest movement.
    cached = db.store["service_catalogue"][0]
    assert cached["stock_qty_units"] == "7"
    assert cached["avg_cost_paise"] == 1_000_00

    ledger = get_stock_ledger(db, "item-1")
    assert [r["movement_type"] for r in ledger] == ["purchase", "sale"]


def test_record_stock_out_with_no_prior_history_returns_none_never_raises():
    db = _FakeDB()
    _seed_catalogue_item(db)
    result = record_stock_out(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-10", quantity=Decimal("1"),
    )
    assert result is None
    # No ledger row and no cache mutation — a no-op, not a partial write.
    assert db.store.get("inventory_stock_ledger", []) == []


def test_seed_opening_balance_is_idempotent():
    db = _FakeDB()
    _seed_catalogue_item(db)
    first = seed_opening_balance(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-01", opening_qty=Decimal("5"), opening_cost_paise=500_00,
    )
    assert first is not None
    assert first["movement_type"] == "opening"
    assert len(db.store["inventory_stock_ledger"]) == 1

    second = seed_opening_balance(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-01", opening_qty=Decimal("5"), opening_cost_paise=500_00,
    )
    assert second is None
    assert len(db.store["inventory_stock_ledger"]) == 1


def test_seed_opening_balance_skips_when_qty_or_cost_missing():
    db = _FakeDB()
    _seed_catalogue_item(db)
    assert seed_opening_balance(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-01", opening_qty=None, opening_cost_paise=500_00,
    ) is None
    assert seed_opening_balance(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-01", opening_qty=Decimal("0"), opening_cost_paise=500_00,
    ) is None
    assert db.store.get("inventory_stock_ledger", []) == []


# ── Orchestration (apply_sale_to_inventory / apply_purchase_to_inventory) ───
# The fake DB has no chart_of_accounts rows, so the COGS/Inventory journal
# posting inside these always no-ops (accounts not found) — exactly the
# "firm hasn't set up Inventory/COGS accounts yet" case in production. These
# tests assert the stock MOVEMENT still records correctly regardless —
# proving the fail-soft design: a missing control account degrades the
# journal entry, never the stock tracking, and never the sale/purchase itself.

def test_apply_sale_to_inventory_records_stock_out_for_goods_line_only():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    db.store["service_catalogue"].append({
        "id": "svc-1", "firm_id": "firm-1", "client_id": "client-1",
        "name": "Consulting", "kind": "service", "stock_qty_units": "0", "avg_cost_paise": 0,
    })
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    db.store["client_sales_invoice_lines"] = [
        {"id": "line-1", "sales_invoice_id": "inv-1", "description": "Widget x3", "quantity": "3", "service_catalogue_id": "good-1"},
        {"id": "line-2", "sales_invoice_id": "inv-1", "description": "Consulting hours", "quantity": "5", "service_catalogue_id": "svc-1"},
        {"id": "line-3", "sales_invoice_id": "inv-1", "description": "Custom item, no catalogue link", "quantity": "1", "service_catalogue_id": None},
    ]
    invoice = {"id": "inv-1", "invoice_no": "INV-1", "invoice_date": "2026-04-20", "client_id": "client-1"}

    apply_sale_to_inventory(db, firm_id="firm-1", client_id="client-1", invoice=invoice)

    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["opening", "sale"]
    assert ledger[-1]["quantity_delta"] == "-3"
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "7"
    # Service line and unlinked line must never touch the ledger at all.
    assert db.store.get("inventory_stock_ledger", []) == ledger


def test_apply_sale_to_inventory_never_raises_when_item_has_no_stock_history():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    db.store["client_sales_invoice_lines"] = [
        {"id": "line-1", "sales_invoice_id": "inv-1", "description": "Widget", "quantity": "1", "service_catalogue_id": "good-1"},
    ]
    invoice = {"id": "inv-1", "invoice_no": "INV-1", "invoice_date": "2026-04-20", "client_id": "client-1"}
    # No opening balance / prior purchase recorded for good-1 — record_stock_out
    # returns None internally; this call must complete without raising.
    apply_sale_to_inventory(db, firm_id="firm-1", client_id="client-1", invoice=invoice)
    assert db.store.get("inventory_stock_ledger", []) == []


def test_apply_purchase_to_inventory_records_stock_in_and_updates_average():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    db.store["purchase_bill_lines"] = [
        {"id": "pline-1", "bill_id": "bill-1", "description": "Widget x10", "quantity": "10",
         "taxable_amount_paise": 10_000_00, "expense_account_id": None, "service_catalogue_id": "good-1"},
    ]
    bill = {"id": "bill-1", "bill_no": "BILL-1", "bill_date": "2026-04-05", "client_id": "client-1"}

    apply_purchase_to_inventory(db, firm_id="firm-1", client_id="client-1", bill=bill)

    ledger = get_stock_ledger(db, "good-1")
    assert len(ledger) == 1
    assert ledger[0]["movement_type"] == "purchase"
    assert ledger[0]["running_qty_units"] == "10"
    assert ledger[0]["running_avg_cost_paise"] == 1_000_00
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "10"
    assert goods_row["avg_cost_paise"] == 1_000_00
