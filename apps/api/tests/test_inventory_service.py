"""
domain/inventory_service — moving-average costing math and the ledger/cache
read-modify-write cycle. Every arithmetic path here is a financial
calculation (CLAUDE.md: every one needs a unit test), including the rounding
edge cases moving-average costing is prone to.
"""
import uuid
from decimal import Decimal

import pytest

import domain.inventory_service as inventory_service
from domain.inventory_service import (
    _compute_stock_in,
    _compute_stock_out,
    record_stock_in,
    record_stock_out,
    record_stock_out_at_value,
    seed_opening_balance,
    seed_opening_balances_batch,
    get_stock_ledger,
    apply_sale_to_inventory,
    apply_purchase_to_inventory,
    reverse_sale_stock,
    reverse_purchase_stock,
    apply_credit_note_to_inventory,
    apply_debit_note_to_inventory,
    record_stock_adjustment,
    apply_stock_adjustment,
    _compute_nrv_writedown,
    record_nrv_writedown,
    apply_nrv_writedown,
    _movement_journal_ref,
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


# ── Oversold absorb + COGS true-up (task #103) ──────────────────────────────

def test_compute_stock_in_partial_cover_of_oversold_absorbs_entirely_as_trueup():
    # -5 units on hand (oversold, force-closed to Rs 0 value). A purchase of
    # only 3 units @ Rs 100 = Rs 300 doesn't clear the deficit (still -2
    # after) — the WHOLE Rs 300 must be a COGS true-up, none of it "value on
    # hand" (the old bug stranded Rs 300 on a still-negative quantity).
    calc = _compute_stock_in(Decimal("-5"), 0, Decimal("3"), 300_00)
    assert calc["running_qty_units"] == Decimal("-2")
    assert calc["running_value_paise"] == 0
    assert calc["running_avg_cost_paise"] == 0
    assert calc["value_delta_paise"] == 0
    assert calc["trueup_paise"] == 300_00
    assert calc["unit_cost_paise"] == 100_00


def test_compute_stock_in_exact_cover_of_oversold_leaves_zero_value():
    # -5 units on hand; a purchase of exactly 5 units clears the deficit to
    # zero — still no value on hand (nothing left over), whole cost trues up.
    calc = _compute_stock_in(Decimal("-5"), 0, Decimal("5"), 500_00)
    assert calc["running_qty_units"] == Decimal("0")
    assert calc["running_value_paise"] == 0
    assert calc["running_avg_cost_paise"] == 0
    assert calc["trueup_paise"] == 500_00


def test_compute_stock_in_full_cover_with_excess_splits_trueup_and_new_stock():
    # -5 units on hand; a purchase of 8 units @ Rs 100 = Rs 800 clears the
    # deficit (5 units, Rs 500 true-up) AND leaves 3 genuine new units on
    # hand at real cost (Rs 300 value, Rs 100/unit average — not diluted by
    # the true-up portion).
    calc = _compute_stock_in(Decimal("-5"), 0, Decimal("8"), 800_00)
    assert calc["running_qty_units"] == Decimal("3")
    assert calc["trueup_paise"] == 500_00
    assert calc["value_delta_paise"] == 300_00
    assert calc["running_value_paise"] == 300_00
    assert calc["running_avg_cost_paise"] == 100_00


def test_compute_stock_in_no_deficit_has_zero_trueup():
    # prev_qty >= 0 (nothing oversold) must behave exactly as before — the
    # new split logic is a no-op here.
    calc = _compute_stock_in(Decimal("10"), 10_000_00, Decimal("10"), 12_000_00)
    assert calc["trueup_paise"] == 0
    assert calc["value_delta_paise"] == 12_000_00
    assert calc["running_value_paise"] == 22_000_00


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
        self._upsert_rows = None
        self._upsert_key = None

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

    def upsert(self, rows, on_conflict=None):
        self._upsert_rows = rows if isinstance(rows, list) else [rows]
        self._upsert_key = (on_conflict or "id").split(",")
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
                # A real (uuid4-like) id — not a "{table}-{index}" placeholder —
                # matters for task #232's reference_no tests: a long table name
                # (e.g. "inventory_stock_ledger") made every row's id share the
                # SAME first 8 characters regardless of index, which is exactly
                # the kind of accidental collision the fix under test guards
                # against; a real id must actually vary there.
                row = {"id": str(uuid.uuid4()), **r}
                rows_table.append(row)
                out.append(row)
            return _Res(out)
        if self._upsert_rows is not None:
            # Merge-duplicates semantics (matches PostgREST/Supabase upsert):
            # only the columns present in each payload row are written; a
            # match on the conflict key updates in place, otherwise inserts.
            out = []
            for r in self._upsert_rows:
                key_vals = {k: r.get(k) for k in self._upsert_key}
                existing = next((row for row in rows_table if all(row.get(k) == v for k, v in key_vals.items())), None)
                if existing is not None:
                    existing.update(r)
                    out.append(existing)
                else:
                    row = dict(r)
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


def test_record_stock_out_with_no_prior_history_records_as_oversold_at_zero_cost():
    db = _FakeDB()
    _seed_catalogue_item(db)
    result = record_stock_out(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
        movement_date="2026-04-10", quantity=Decimal("1"),
    )
    # No cost basis yet (no opening balance, no prior purchase) — the movement
    # still records from a zero baseline rather than vanishing, so the CA sees
    # this item went to -1 on the Inventory page instead of nothing at all.
    assert result is not None
    assert result["running_qty_units"] == "-1"
    assert result["running_value_paise"] == 0
    assert result["running_avg_cost_paise"] == 0
    assert len(get_stock_ledger(db, "item-1")) == 1


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


# ── seed_opening_balances_batch — bulk import fast path ─────────────────────
# Replaces bulk_create_services' old per-row seed_opening_balance loop (one
# existing-check + one insert + one cache update PER product — ~1,000+
# sequential round trips for a 300-product import, which is what actually
# made a real bulk import hang long enough to trip the frontend's own
# request timeout). This collapses the whole batch to one ledger insert
# and one cache upsert, regardless of row count.

def test_seed_opening_balances_batch_seeds_every_goods_row_in_two_round_trips():
    db = _FakeDB()
    rows = [
        {"id": "item-1", "client_id": "client-1", "kind": "good",
         "opening_qty_units": "10", "opening_cost_paise": 10_000_00, "created_at": "2026-04-01T00:00:00Z"},
        {"id": "item-2", "client_id": "client-1", "kind": "good",
         "opening_qty_units": "4", "opening_cost_paise": 800_00, "created_at": "2026-04-01T00:00:00Z"},
    ]
    for r in rows:
        _seed_catalogue_item(db, item_id=r["id"])

    seed_opening_balances_batch(db, firm_id="firm-1", created_by="user-1", rows=rows)

    ledger = db.store["inventory_stock_ledger"]
    assert len(ledger) == 2
    assert {r["service_catalogue_id"] for r in ledger} == {"item-1", "item-2"}
    assert all(r["movement_type"] == "opening" for r in ledger)

    item1 = next(r for r in db.store["service_catalogue"] if r["id"] == "item-1")
    item2 = next(r for r in db.store["service_catalogue"] if r["id"] == "item-2")
    assert item1["stock_qty_units"] == "10" and item1["avg_cost_paise"] == 1_000_00
    assert item2["stock_qty_units"] == "4" and item2["avg_cost_paise"] == 200_00


def test_seed_opening_balances_batch_cache_upsert_carries_tenant_columns():
    # Regression: the cache upsert conflict-targets "id" (the PK) while
    # firm_id/client_id are NOT part of that conflict target — a payload of
    # just {id, stock_qty_units, avg_cost_paise} leaves firm_id/client_id
    # NULL on the candidate row Postgres's RLS WITH CHECK evaluates for an
    # INSERT ... ON CONFLICT DO UPDATE (even though the row already exists
    # and the statement only ever runs the UPDATE branch), which real
    # Supabase rejects with "new row violates row-level security policy" —
    # silently leaving stock_qty_units/avg_cost_paise at 0 forever, exactly
    # like the products/services import that surfaced this. name is also
    # NOT NULL with no column default, so it must ride along too. FakeDB
    # doesn't enforce RLS, so this only asserts the payload SHAPE is right.
    db = _FakeDB()
    row = {"id": "item-1", "client_id": "client-1", "kind": "good", "name": "Widget",
           "opening_qty_units": "10", "opening_cost_paise": 10_000_00, "created_at": "2026-04-01T00:00:00Z"}
    _seed_catalogue_item(db, item_id="item-1")

    seed_opening_balances_batch(db, firm_id="firm-1", created_by="user-1", rows=[row])

    item = next(r for r in db.store["service_catalogue"] if r["id"] == "item-1")
    assert item["firm_id"] == "firm-1"
    assert item["client_id"] == "client-1"
    assert item["name"] == "Widget"


def test_seed_opening_balances_batch_skips_services_and_rows_missing_qty_or_cost():
    db = _FakeDB()
    rows = [
        {"id": "svc-1", "client_id": "client-1", "kind": "service",
         "opening_qty_units": "10", "opening_cost_paise": 10_000_00},  # not a good — skipped
        {"id": "item-3", "client_id": "client-1", "kind": "good",
         "opening_qty_units": None, "opening_cost_paise": 500_00},     # no qty — skipped
        {"id": "item-4", "client_id": "client-1", "kind": "good",
         "opening_qty_units": "0", "opening_cost_paise": 500_00},      # zero qty — skipped
    ]
    for r in rows:
        _seed_catalogue_item(db, item_id=r["id"])

    seed_opening_balances_batch(db, firm_id="firm-1", created_by="user-1", rows=rows)
    assert db.store.get("inventory_stock_ledger", []) == []


def test_seed_opening_balances_batch_noop_on_empty_list():
    db = _FakeDB()
    seed_opening_balances_batch(db, firm_id="firm-1", created_by="user-1", rows=[])
    assert db.store.get("inventory_stock_ledger", []) == []
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


def test_apply_sale_to_inventory_records_as_oversold_when_item_has_no_stock_history():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    db.store["client_sales_invoice_lines"] = [
        {"id": "line-1", "sales_invoice_id": "inv-1", "description": "Widget", "quantity": "1", "service_catalogue_id": "good-1"},
    ]
    invoice = {"id": "inv-1", "invoice_no": "INV-1", "invoice_date": "2026-04-20", "client_id": "client-1"}
    # No opening balance / prior purchase recorded for good-1 — the sale still
    # records (visible as -1 on hand at Rs 0 cost) instead of vanishing; no
    # COGS journal posts since there's no cost basis to recognise yet.
    apply_sale_to_inventory(db, firm_id="firm-1", client_id="client-1", invoice=invoice)
    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["sale"]
    assert ledger[0]["running_qty_units"] == "-1"
    assert ledger[0]["running_value_paise"] == 0
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "-1"


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


def _capture_journal_calls(monkeypatch, accounts):
    """Shared helper: monkeypatch _find_account/_create_journal to capture
    EVERY _create_journal call (not just the last) as a list of kwargs, since
    apply_purchase_to_inventory can post two independent journals (receipt +
    true-up) for one bill."""
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(pjs.phase2_journal_service, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])
    calls = []
    def _fake_create_journal(db, **kwargs):
        calls.append(kwargs)
        return f"journal-{len(calls)}"
    monkeypatch.setattr(pjs.phase2_journal_service, "_create_journal", _fake_create_journal)
    return calls


def test_apply_purchase_to_inventory_partial_cover_posts_trueup_only(monkeypatch):
    # Item is oversold to -5 (Rs 0 cost basis, as with any oversold sale). A
    # purchase bill covering only 3 of those units must post NO receipt/
    # capitalisation journal (nothing becomes on-hand value) — only a COGS
    # true-up for the real cost of the units already sold.
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_out(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
                     movement_date="2026-04-01", quantity=Decimal("5"), movement_type="sale")
    db.store["purchase_bill_lines"] = [
        {"id": "pline-1", "bill_id": "bill-1", "description": "Widget x3", "quantity": "3",
         "taxable_amount_paise": 300_00, "expense_account_id": "acct-expense", "service_catalogue_id": "good-1"},
    ]
    bill = {"id": "bill-1", "bill_no": "BILL-2", "bill_date": "2026-04-10", "client_id": "client-1"}
    # %Purchase% is probed eagerly as the expense-account FALLBACK even though
    # this line's own expense_account_id is set (and wins) — see
    # post_inventory_trueup_journal_entry's account-resolution order.
    calls = _capture_journal_calls(monkeypatch, {"%Cost of Goods Sold%": "acct-cogs", "%Purchase%": "acct-fallback"})

    apply_purchase_to_inventory(db, firm_id="firm-1", client_id="client-1", bill=bill)

    ledger = get_stock_ledger(db, "good-1")
    assert ledger[-1]["running_qty_units"] == "-2"
    assert ledger[-1]["running_value_paise"] == 0

    assert len(calls) == 1  # no receipt journal — nothing capitalised
    trueup = calls[0]
    assert trueup["reference_no"].endswith("-COGSTRUEUP")
    assert any(l["account_id"] == "acct-cogs" and l["debit_paise"] == 300_00 for l in trueup["lines"])
    assert any(l["account_id"] == "acct-expense" and l["credit_paise"] == 300_00 for l in trueup["lines"])


def test_apply_purchase_to_inventory_full_cover_with_excess_posts_both_journals(monkeypatch):
    # Item oversold to -5. A purchase of 8 units @ Rs 100 clears the deficit
    # (Rs 500 true-up) AND leaves 3 genuine new units on hand (Rs 300
    # capitalised as Inventory) — both journals must post, independently.
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_out(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
                     movement_date="2026-04-01", quantity=Decimal("5"), movement_type="sale")
    db.store["purchase_bill_lines"] = [
        {"id": "pline-1", "bill_id": "bill-1", "description": "Widget x8", "quantity": "8",
         "taxable_amount_paise": 800_00, "expense_account_id": "acct-expense", "service_catalogue_id": "good-1"},
    ]
    bill = {"id": "bill-1", "bill_no": "BILL-3", "bill_date": "2026-04-10", "client_id": "client-1"}
    calls = _capture_journal_calls(monkeypatch, {
        "%Inventor%": "acct-inventory", "%Purchase%": "acct-expense", "%Cost of Goods Sold%": "acct-cogs",
    })

    apply_purchase_to_inventory(db, firm_id="firm-1", client_id="client-1", bill=bill)

    ledger = get_stock_ledger(db, "good-1")
    assert ledger[-1]["running_qty_units"] == "3"
    assert ledger[-1]["running_value_paise"] == 300_00
    assert ledger[-1]["running_avg_cost_paise"] == 100_00

    assert len(calls) == 2
    receipt = next(c for c in calls if c["reference_no"].endswith("-INV"))
    trueup = next(c for c in calls if c["reference_no"].endswith("-COGSTRUEUP"))
    assert any(l["account_id"] == "acct-inventory" and l["debit_paise"] == 300_00 for l in receipt["lines"])
    assert any(l["account_id"] == "acct-cogs" and l["debit_paise"] == 500_00 for l in trueup["lines"])
    assert any(l["account_id"] == "acct-expense" and l["credit_paise"] == 500_00 for l in trueup["lines"])


def test_reverse_purchase_stock_also_reverses_trueup_journal(monkeypatch):
    # Cancelling a bill that fully absorbed into a prior deficit (partial-
    # cover case above) must reverse the true-up journal too — otherwise a
    # COGS correction survives with no purchase behind it.
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_out(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
                     movement_date="2026-04-01", quantity=Decimal("5"), movement_type="sale")
    db.store["purchase_bill_lines"] = [
        {"id": "pline-1", "bill_id": "bill-1", "description": "Widget x3", "quantity": "3",
         "taxable_amount_paise": 300_00, "expense_account_id": "acct-expense", "service_catalogue_id": "good-1"},
    ]
    bill = {"id": "bill-1", "bill_no": "BILL-4", "bill_date": "2026-04-10", "client_id": "client-1"}
    import services.phase2_journal_service as pjs
    accounts = {"%Cost of Goods Sold%": "acct-cogs", "%Purchase%": "acct-fallback"}
    monkeypatch.setattr(pjs.phase2_journal_service, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])

    def _fake_create_journal(db, **k):
        table = db.store.setdefault("journal_entries", [])
        row = {"id": f"je-{len(table)}", "firm_id": k["firm_id"], "client_id": k["client_id"],
               "reference_no": k["reference_no"], "is_posted": True}
        table.append(row)
        return row["id"]
    monkeypatch.setattr(pjs.phase2_journal_service, "_create_journal", _fake_create_journal)
    reversed_calls = []
    monkeypatch.setattr(pjs.phase2_journal_service, "reverse_entry",
                        lambda db, firm_id, journal_id, date, **k: reversed_calls.append(journal_id) or "rev-id")

    apply_purchase_to_inventory(db, firm_id="firm-1", client_id="client-1", bill=bill)
    trueup_entry = next(e for e in db.store["journal_entries"] if e["reference_no"].endswith("-COGSTRUEUP"))

    reverse_purchase_stock(db, firm_id="firm-1", client_id="client-1", bill_id="bill-1", bill_reference="BILL-4")

    assert reversed_calls == [trueup_entry["id"]]


# ── Reversal on cancellation ─────────────────────────────────────────────────

def test_reverse_sale_stock_restores_quantity_and_is_idempotent():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    sale = record_stock_out(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-10", quantity=Decimal("3"), movement_type="sale",
        source_type="sales_invoice", source_id="inv-1", reference_no="INV-1",
    )
    assert sale["running_qty_units"] == "7"

    reverse_sale_stock(db, firm_id="firm-1", client_id="client-1", invoice_id="inv-1", invoice_no="INV-1")

    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "10"  # back to pre-sale quantity
    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["opening", "sale", "sale_reversal"]

    # A second cancellation attempt (e.g. a retried request) must not double-reverse.
    reverse_sale_stock(db, firm_id="firm-1", client_id="client-1", invoice_id="inv-1", invoice_no="INV-1")
    assert len(get_stock_ledger(db, "good-1")) == 3


def test_reverse_sale_stock_never_raises_with_no_sale_to_reverse():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    # No prior sale recorded for this invoice — must complete without raising.
    reverse_sale_stock(db, firm_id="firm-1", client_id="client-1", invoice_id="inv-none", invoice_no="INV-NONE")
    assert get_stock_ledger(db, "good-1") == []


def test_reverse_purchase_stock_removes_quantity_and_is_idempotent():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    purchase = record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-05", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase",
        source_type="purchase_bill", source_id="bill-1", reference_no="BILL-1",
    )
    assert purchase["running_qty_units"] == "10"

    reverse_purchase_stock(db, firm_id="firm-1", client_id="client-1", bill_id="bill-1", bill_reference="BILL-1")

    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "0"
    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["purchase", "purchase_reversal"]

    reverse_purchase_stock(db, firm_id="firm-1", client_id="client-1", bill_id="bill-1", bill_reference="BILL-1")
    assert len(get_stock_ledger(db, "good-1")) == 2


# ── Credit Note / Debit Note inventory wiring ────────────────────────────────
# Same fail-soft, no-chart-of-accounts fake DB as the sale/purchase orchestration
# tests above — the journal posting inside always no-ops here; only the stock
# MOVEMENT is asserted.

def test_apply_credit_note_to_inventory_restocks_goods_line_only():
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
    record_stock_out(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-10", quantity=Decimal("3"), movement_type="sale",
        source_type="sales_invoice", source_id="inv-1", reference_no="INV-1",
    )
    db.store["credit_note_lines"] = [
        {"id": "cnl-1", "credit_note_id": "cn-1", "description": "Widget returned", "quantity": "2",
         "taxable_amount_paise": 2_000_00, "service_catalogue_id": "good-1"},
        {"id": "cnl-2", "credit_note_id": "cn-1", "description": "Consulting credit", "quantity": "1",
         "taxable_amount_paise": 500_00, "service_catalogue_id": "svc-1"},
        {"id": "cnl-3", "credit_note_id": "cn-1", "description": "Rate correction, no catalogue link", "quantity": "1",
         "taxable_amount_paise": 100_00, "service_catalogue_id": None},
    ]
    credit_note = {"id": "cn-1", "credit_note_no": "CN-2526-0001", "credit_note_date": "2026-04-15", "client_id": "client-1"}

    apply_credit_note_to_inventory(db, firm_id="firm-1", client_id="client-1", credit_note=credit_note)

    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["opening", "sale", "sale_return"]
    assert ledger[-1]["quantity_delta"] == "2"
    assert ledger[-1]["value_delta_paise"] == 2_000_00
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "9"  # 10 - 3 + 2
    # Service line and the unlinked line must never touch the ledger.
    assert len(ledger) == 3


def test_apply_credit_note_to_inventory_never_raises_with_no_catalogue_link():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    db.store["credit_note_lines"] = [
        {"id": "cnl-1", "credit_note_id": "cn-1", "description": "Rate correction", "quantity": "1",
         "taxable_amount_paise": 100_00, "service_catalogue_id": None},
    ]
    credit_note = {"id": "cn-1", "credit_note_no": "CN-2526-0002", "credit_note_date": "2026-04-15", "client_id": "client-1"}
    # No goods line at all — must complete without raising and touch nothing.
    apply_credit_note_to_inventory(db, firm_id="firm-1", client_id="client-1", credit_note=credit_note)
    assert db.store.get("inventory_stock_ledger", []) == []


def test_apply_debit_note_to_inventory_destocks_goods_line_at_current_average():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase",
        source_type="purchase_bill", source_id="bill-1", reference_no="BILL-1",
    )
    db.store["debit_note_lines"] = [
        {"id": "dnl-1", "debit_note_id": "dn-1", "description": "Widget returned to vendor", "quantity": "2",
         "service_catalogue_id": "good-1"},
    ]
    debit_note = {"id": "dn-1", "debit_note_no": "DN-2526-0001", "debit_note_date": "2026-04-10", "client_id": "client-1"}

    apply_debit_note_to_inventory(db, firm_id="firm-1", client_id="client-1", debit_note=debit_note)

    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["purchase", "purchase_return"]
    # Priced at the CURRENT moving average (Rs 1000/unit), not any value carried
    # on the debit note line itself — debit_note_lines has no taxable_amount_paise
    # read by this path at all, mirroring how a sale prices stock-out.
    assert ledger[-1]["quantity_delta"] == "-2"
    assert ledger[-1]["value_delta_paise"] == -2_000_00
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "8"


def test_apply_debit_note_to_inventory_records_as_oversold_with_no_stock_history():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    db.store["debit_note_lines"] = [
        {"id": "dnl-1", "debit_note_id": "dn-1", "description": "Widget returned", "quantity": "1",
         "service_catalogue_id": "good-1"},
    ]
    debit_note = {"id": "dn-1", "debit_note_no": "DN-2526-0002", "debit_note_date": "2026-04-10", "client_id": "client-1"}
    # No prior stock for good-1 — the return still records (visible as -1 on
    # hand at Rs 0 cost) instead of vanishing; no reclass journal posts since
    # there's no cost basis to move.
    apply_debit_note_to_inventory(db, firm_id="firm-1", client_id="client-1", debit_note=debit_note)
    ledger = get_stock_ledger(db, "good-1")
    assert [r["movement_type"] for r in ledger] == ["purchase_return"]
    assert ledger[0]["running_qty_units"] == "-1"
    assert ledger[0]["running_value_paise"] == 0


# ── journal_entry_id backfill ────────────────────────────────────────────────
# inventory_stock_ledger.journal_entry_id (migration 188) is only knowable
# AFTER the movement row already exists (a movement is always recorded before
# its journal is posted) — these tests monkeypatch the journal-posting call
# to a fixed id (the fake DB has no chart_of_accounts, so the real posting
# functions always no-op) and assert the backfill UPDATE actually lands.

def test_apply_sale_to_inventory_backfills_journal_entry_id_onto_its_movement(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    db.store["client_sales_invoice_lines"] = [
        {"id": "line-1", "sales_invoice_id": "inv-1", "description": "Widget x3", "quantity": "3", "service_catalogue_id": "good-1"},
    ]
    invoice = {"id": "inv-1", "invoice_no": "INV-1", "invoice_date": "2026-04-20", "client_id": "client-1"}
    monkeypatch.setattr(inventory_service, "post_cogs_journal_entry", lambda *a, **k: "journal-cogs-1")

    apply_sale_to_inventory(db, firm_id="firm-1", client_id="client-1", invoice=invoice)

    sale_row = next(r for r in get_stock_ledger(db, "good-1") if r["movement_type"] == "sale")
    assert sale_row["journal_entry_id"] == "journal-cogs-1"


def test_apply_credit_note_to_inventory_backfills_journal_entry_id_onto_every_line_movement(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    _seed_catalogue_item(db, item_id="good-2", kind="good", name="Gadget")
    # Establish a real cost basis — returns are valued at COST (current
    # average here, since this CN has no sales_invoice_id link), never at the
    # CN's taxable/selling value; with no cost basis at all the value is 0
    # and no journal posts.
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="purchase")
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-2",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=2_500_00, movement_type="purchase")
    db.store["credit_note_lines"] = [
        {"id": "cnl-1", "credit_note_id": "cn-1", "description": "Widget returned", "quantity": "2",
         "taxable_amount_paise": 2_000_00, "service_catalogue_id": "good-1"},
        {"id": "cnl-2", "credit_note_id": "cn-1", "description": "Gadget returned", "quantity": "1",
         "taxable_amount_paise": 500_00, "service_catalogue_id": "good-2"},
    ]
    credit_note = {"id": "cn-1", "credit_note_no": "CN-2526-0003", "credit_note_date": "2026-04-15", "client_id": "client-1"}
    monkeypatch.setattr(inventory_service, "post_sale_return_journal_entry", lambda *a, **k: "journal-invret-1")

    apply_credit_note_to_inventory(db, firm_id="firm-1", client_id="client-1", credit_note=credit_note)

    return_rows = [r for r in db.store["inventory_stock_ledger"] if r["movement_type"] == "sale_return"]
    assert len(return_rows) == 2
    assert all(r["journal_entry_id"] == "journal-invret-1" for r in return_rows)
    # Valued at cost (avg ₹1000 and ₹250/unit), not the CN's selling prices.
    assert return_rows[0]["value_delta_paise"] == 2_000_00  # 2 × ₹1000 cost
    assert return_rows[1]["value_delta_paise"] == 250_00    # 1 × ₹250 cost


# ── Backdated movements / insertion-order chaining ──────────────────────────

def test_backdated_purchase_stays_in_the_running_chain():
    """A bill DATED before already-recorded movements must still enter the
    running-total chain (chain is insertion-ordered, not date-ordered) — the
    old movement_date-ordered chain silently dropped a backdated purchase
    from every future running total."""
    db = _FakeDB()
    _seed_catalogue_item(db)
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                    movement_date="2026-07-01", quantity=Decimal("10"), total_cost_paise=1_000_00, movement_type="opening")
    record_stock_out(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                     movement_date="2026-07-10", quantity=Decimal("4"), movement_type="sale")
    # Backdated bill: dated Jul-1 but recorded now (after the Jul-10 sale).
    row = record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                          movement_date="2026-07-01", quantity=Decimal("10"), total_cost_paise=1_200_00, movement_type="purchase")
    assert row["running_qty_units"] == "16"          # 10 - 4 + 10
    assert row["running_value_paise"] == 1_800_00    # 600 + 1200
    # The NEXT movement must chain from the backdated purchase's totals,
    # not from the (later-dated) sale row.
    nxt = record_stock_out(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                           movement_date="2026-07-16", quantity=Decimal("1"), movement_type="sale")
    assert nxt["running_qty_units"] == "15"
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "item-1")
    assert goods_row["stock_qty_units"] == "15"


def test_force_close_value_delta_equals_actual_book_relief():
    """Oversell: value_delta must be what the books actually held (so COGS
    journals post the real inventory relief), not qty × avg."""
    calc = _compute_stock_out(Decimal("2"), 2_000_00, 1_000_00, Decimal("5"))
    assert calc["value_delta_paise"] == -2_000_00   # NOT -5,000_00
    assert calc["running_qty_units"] == Decimal("-3")
    assert calc["running_value_paise"] == 0


def test_reverse_purchase_stock_removes_original_value_not_current_average():
    """Cancel after the average moved: the ledger must remove the ORIGINAL
    received value (matching the journal reversal), not qty × current avg."""
    db = _FakeDB()
    _seed_catalogue_item(db)
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=1_000_00, movement_type="opening")
    # Bill B1: 10 units @ ₹200 → avg becomes ₹150.
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                    movement_date="2026-04-05", quantity=Decimal("10"), total_cost_paise=2_000_00, movement_type="purchase",
                    source_type="purchase_bill", source_id="bill-1", reference_no="B1")

    reverse_purchase_stock(db, firm_id="firm-1", client_id="client-1", bill_id="bill-1", bill_reference="B1")

    rev = next(r for r in db.store["inventory_stock_ledger"] if r["movement_type"] == "purchase_reversal")
    assert rev["value_delta_paise"] == -2_000_00     # original ₹2000, not 10 × ₹150 = ₹1500
    assert rev["running_qty_units"] == "10"
    assert rev["running_value_paise"] == 1_000_00    # back to the opening position


def test_record_stock_out_at_value_clamps_to_book_value():
    db = _FakeDB()
    _seed_catalogue_item(db)
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=500_00, movement_type="opening")
    # Ask to remove ₹800 when the books hold only ₹500 with qty remaining.
    row = record_stock_out_at_value(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                                    movement_date="2026-04-10", quantity=Decimal("4"), value_paise=800_00,
                                    movement_type="purchase_reversal")
    assert row["value_delta_paise"] == -500_00
    assert row["running_value_paise"] == 0 or int(row["running_value_paise"]) >= 0


def test_seed_opening_balance_chains_from_existing_movements():
    """Opening stock added AFTER the item already moved (e.g. oversold before
    setup) must chain from the live running totals, not restart at zero."""
    db = _FakeDB()
    _seed_catalogue_item(db)
    record_stock_out(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                     movement_date="2026-06-01", quantity=Decimal("3"), movement_type="sale")  # oversold to -3
    row = seed_opening_balance(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="item-1",
                               movement_date="2026-04-01", opening_qty=10, opening_cost_paise=1_000_00)
    assert row is not None
    assert row["running_qty_units"] == "7"           # -3 + 10, not 10
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "item-1")
    assert goods_row["stock_qty_units"] == "7"


# ── Manual stock adjustment ──────────────────────────────────────────────────

def test_record_stock_adjustment_decrease_prices_at_current_average():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    row = record_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-10", quantity=Decimal("3"), direction="decrease", reference_no="ADJ-1",
    )
    assert row["movement_type"] == "adjustment"
    assert row["running_qty_units"] == "7"
    assert row["running_value_paise"] == 7_000_00
    assert row["running_avg_cost_paise"] == 1_000_00


def test_record_stock_adjustment_increase_keeps_average_stable():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    # A physical count found 5 MORE units than the books show — value it at
    # the CURRENT average (Rs 1000/unit) rather than diluting/inflating the
    # average with an assumed cost for stock of unknown origin.
    row = record_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-10", quantity=Decimal("5"), direction="increase", reference_no="ADJ-2",
    )
    assert row["movement_type"] == "adjustment"
    assert row["running_qty_units"] == "15"
    assert row["running_avg_cost_paise"] == 1_000_00  # unchanged
    assert row["running_value_paise"] == 15_000_00


def test_apply_stock_adjustment_writeoff_reverses_itc_using_item_gst_rate(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget", gst_rate_bps=1800)
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )

    import services.phase2_journal_service as pjs
    accounts = {"%Inventor%": "acct-inventory", "%Write%off%": "acct-writeoff", "%GST Input%": "acct-gst-input"}
    monkeypatch.setattr(pjs.phase2_journal_service, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])
    captured = {}
    def _fake_create_journal(**kwargs):
        captured.update(kwargs)
        return "journal-woff-1"
    monkeypatch.setattr(pjs.phase2_journal_service, "_create_journal", lambda db, **k: _fake_create_journal(**k))

    movement = apply_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", quantity=Decimal("2"), direction="decrease",
        reverse_itc=True, reference_no="ADJ-3",
    )

    assert movement["running_qty_units"] == "8"
    # 2 units @ Rs 1000 avg = Rs 2000 write-off value; 18% ITC reversal = Rs 360.
    lines = captured["lines"]
    assert any(l["account_id"] == "acct-writeoff" and l["debit_paise"] == 2_000_00 for l in lines)
    assert any(l["account_id"] == "acct-writeoff" and l["debit_paise"] == 360_00 for l in lines)
    gst_credit = next((l for l in lines if l["account_id"] == "acct-gst-input"), None)
    assert gst_credit is not None
    assert gst_credit["credit_paise"] == 360_00
    assert captured["entry_type"] == "Journal"  # journal_entries.entry_type CHECK constraint
    ledger = get_stock_ledger(db, "good-1")
    assert ledger[-1]["journal_entry_id"] == "journal-woff-1"


def test_apply_stock_adjustment_writeoff_skips_itc_reversal_when_not_requested(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget", gst_rate_bps=1800)
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )

    import services.phase2_journal_service as pjs
    accounts = {"%Inventor%": "acct-inventory", "%Write%off%": "acct-writeoff"}
    monkeypatch.setattr(pjs.phase2_journal_service, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])
    captured = {}
    monkeypatch.setattr(pjs.phase2_journal_service, "_create_journal",
                        lambda db, **k: captured.update(k) or "journal-woff-2")

    apply_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", quantity=Decimal("2"), direction="decrease",
        reverse_itc=False, reference_no="ADJ-4",
    )

    assert len(captured["lines"]) == 2  # write-off + inventory only, no ITC lines


def test_apply_stock_adjustment_increase_posts_surplus_journal(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )

    import services.phase2_journal_service as pjs
    accounts = {"%Inventor%": "acct-inventory", "%Miscellaneous Income%": "acct-misc-income"}
    monkeypatch.setattr(pjs.phase2_journal_service, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])
    captured = {}
    monkeypatch.setattr(pjs.phase2_journal_service, "_create_journal",
                        lambda db, **k: captured.update(k) or "journal-surp-1")

    movement = apply_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", quantity=Decimal("5"), direction="increase",
        reverse_itc=False, reference_no="ADJ-5",
    )

    assert movement["running_qty_units"] == "15"
    assert captured["entry_type"] == "Journal"
    lines = captured["lines"]
    assert any(l["account_id"] == "acct-inventory" and l["debit_paise"] == 5_000_00 for l in lines)
    assert any(l["account_id"] == "acct-misc-income" and l["credit_paise"] == 5_000_00 for l in lines)


# ── Lower-of-cost-or-NRV write-down ──────────────────────────────────────────

def test_compute_nrv_writedown_reduces_value_and_avg_cost_qty_unchanged():
    # 10 units at Rs 1000/unit avg (value 10,000); NRV has fallen to Rs 700/unit.
    calc = _compute_nrv_writedown(Decimal("10"), 10_000_00, 700_00)
    assert calc is not None
    assert calc["quantity_delta"] == Decimal("0")
    assert calc["running_qty_units"] == Decimal("10")  # unchanged
    assert calc["running_value_paise"] == 7_000_00
    assert calc["running_avg_cost_paise"] == 700_00
    assert calc["value_delta_paise"] == -3_000_00


def test_compute_nrv_writedown_is_noop_when_nrv_at_or_above_cost():
    # NRV equal to or above the current average cost -> no write-down.
    assert _compute_nrv_writedown(Decimal("10"), 10_000_00, 1_000_00) is None
    assert _compute_nrv_writedown(Decimal("10"), 10_000_00, 1_200_00) is None


def test_compute_nrv_writedown_noop_with_zero_quantity():
    assert _compute_nrv_writedown(Decimal("0"), 0, 500_00) is None


def test_record_nrv_writedown_inserts_value_only_movement():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    row = record_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", nrv_per_unit_paise=700_00, reference_no="NRV-1",
    )
    assert row is not None
    assert row["movement_type"] == "nrv_writedown"
    assert row["running_qty_units"] == "10"
    assert row["running_value_paise"] == 7_000_00
    goods_row = next(r for r in db.store["service_catalogue"] if r["id"] == "good-1")
    assert goods_row["stock_qty_units"] == "10"  # quantity cache unchanged
    assert goods_row["avg_cost_paise"] == 700_00


def test_record_nrv_writedown_returns_none_with_no_stock_history():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    assert record_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", nrv_per_unit_paise=700_00,
    ) is None
    assert db.store.get("inventory_stock_ledger", []) == []


def test_record_nrv_writedown_returns_none_when_nrv_not_below_cost():
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    assert record_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", nrv_per_unit_paise=1_500_00,  # NRV above cost
    ) is None
    # Only the opening row exists — no spurious write-down row inserted.
    assert len(get_stock_ledger(db, "good-1")) == 1


def test_apply_nrv_writedown_posts_journal_with_valid_entry_type(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )

    import services.phase2_journal_service as pjs
    accounts = {"%Inventor%": "acct-inventory", "%Write%down%": "acct-writedown"}
    monkeypatch.setattr(pjs.phase2_journal_service, "_find_account",
                        lambda db, firm_id, client_id, pattern, system_key=None: accounts[pattern])
    captured = {}
    monkeypatch.setattr(pjs.phase2_journal_service, "_create_journal",
                        lambda db, **k: captured.update(k) or "journal-nrv-1")

    movement = apply_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", nrv_per_unit_paise=700_00, reference_no="NRV-2",
    )

    assert movement["running_value_paise"] == 7_000_00
    assert captured["entry_type"] == "Journal"  # journal_entries.entry_type CHECK constraint
    lines = captured["lines"]
    assert any(l["account_id"] == "acct-writedown" and l["debit_paise"] == 3_000_00 for l in lines)
    assert any(l["account_id"] == "acct-inventory" and l["credit_paise"] == 3_000_00 for l in lines)
    ledger = get_stock_ledger(db, "good-1")
    assert ledger[-1]["journal_entry_id"] == "journal-nrv-1"


def test_apply_nrv_writedown_returns_none_without_posting_when_not_needed(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    record_stock_in(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening",
    )
    result = apply_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", nrv_per_unit_paise=1_500_00,
    )
    assert result is None
    assert len(get_stock_ledger(db, "good-1")) == 1  # only the opening row


# ── Task #232: manual-adjustment/NRV journal reference_no collision ─────────
# routers/inventory.py defaults reference_no to just the date when the CA
# doesn't supply one ("ADJ-2026-04-15") — with no item/movement identifier,
# two same-day adjustments (different items, or the same item twice) produced
# IDENTICAL journal reference_no values, and _create_journal's (firm, client,
# reference_no, entry_date) idempotency guard silently deduped the second
# journal onto the first: its value never posted to the General Ledger even
# though the stock ledger recorded the movement correctly. The fix derives
# the JOURNAL reference from the ledger row's own unique id (mirrors
# apply_purchase_to_inventory / purchase_bill_journal_ref's existing fix for
# the identical bug class) while the human-facing reference_no (CA-supplied
# or the router's date-based default) still lands on the ledger row itself.

def test_movement_journal_ref_is_unique_per_movement_id():
    assert _movement_journal_ref("ADJ", "abcdef12-3456") == "ADJ-ABCDEF12"
    assert _movement_journal_ref("ADJ", "abcdef12-3456") != _movement_journal_ref("ADJ", "00000000-0000")


def test_two_same_day_adjustments_for_different_items_get_distinct_journal_refs(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    _seed_catalogue_item(db, item_id="good-2", kind="good", name="Gadget")
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening")
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-2",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=5_000_00, movement_type="opening")

    calls = _capture_journal_calls(monkeypatch, {"%Inventor%": "acct-inventory", "%Miscellaneous Income%": "acct-income"})

    # Both adjustments share the SAME router-supplied reference_no (as they
    # would with the router's date-only default, "ADJ-2026-04-15", for two
    # different items adjusted the same day) — the journal ref must still differ.
    apply_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", quantity=Decimal("1"), direction="increase",
        reference_no="ADJ-2026-04-15",
    )
    apply_stock_adjustment(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-2",
        movement_date="2026-04-15", quantity=Decimal("1"), direction="increase",
        reference_no="ADJ-2026-04-15",
    )

    assert len(calls) == 2, "both adjustments must post their OWN journal, not dedupe onto one"
    refs = [c["reference_no"] for c in calls]
    assert refs[0] != refs[1]

    # The ledger rows themselves still keep the human-facing (colliding)
    # reference_no — only the JOURNAL reference had to become unique.
    ledger1 = get_stock_ledger(db, "good-1")
    ledger2 = get_stock_ledger(db, "good-2")
    assert ledger1[-1]["reference_no"] == "ADJ-2026-04-15"
    assert ledger2[-1]["reference_no"] == "ADJ-2026-04-15"


def test_two_same_day_nrv_writedowns_for_different_items_get_distinct_journal_refs(monkeypatch):
    db = _FakeDB()
    _seed_catalogue_item(db, item_id="good-1", kind="good", name="Widget")
    _seed_catalogue_item(db, item_id="good-2", kind="good", name="Gadget")
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening")
    record_stock_in(db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-2",
                    movement_date="2026-04-01", quantity=Decimal("10"), total_cost_paise=10_000_00, movement_type="opening")

    calls = _capture_journal_calls(monkeypatch, {"%Inventor%": "acct-inventory", "%Write%down%": "acct-writedown"})

    apply_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-1",
        movement_date="2026-04-15", nrv_per_unit_paise=700_00, reference_no="NRV-2026-04-15",
    )
    apply_nrv_writedown(
        db, firm_id="firm-1", client_id="client-1", service_catalogue_id="good-2",
        movement_date="2026-04-15", nrv_per_unit_paise=700_00, reference_no="NRV-2026-04-15",
    )

    assert len(calls) == 2, "both write-downs must post their OWN journal, not dedupe onto one"
    refs = [c["reference_no"] for c in calls]
    assert refs[0] != refs[1]
