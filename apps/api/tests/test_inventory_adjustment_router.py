"""
POST /api/inventory/items/{id}/adjust — the manual stock-adjustment endpoint
(routers/inventory.py). Driven through the real endpoint function with
tests/e2e_harness.py's FakeDB, so these exercise the actual guard rails
(validation, 404, kind check) and the real journal-posting call, not just
the pure domain math already covered in test_inventory_service.py.
"""
import pytest
from fastapi import HTTPException

import routers.inventory as inv
from models.inventory import StockAdjustmentIn, NrvWritedownIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [inv])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    # Accounts the standard test COA doesn't include but the adjustment
    # journal needs — mirrors how a real firm's own COA would be set up.
    for name in ("Inventory", "Stock Write-off Expense", "Miscellaneous Income", "Inventory Write-down Expense"):
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI", "account_name": name, "is_active": True})
    db.seed("service_catalogue", {"id": "PROD-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Steel Rod", "kind": "good", "gst_rate_bps": 1800})
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return db


def _seed_opening_stock(db, qty="10", avg_cost_paise=100000):
    db.seed("inventory_stock_ledger", {
        "firm_id": FIRM, "client_id": "CLI", "service_catalogue_id": "PROD-1",
        "movement_date": "2026-04-01", "movement_type": "opening",
        "quantity_delta": qty, "unit_cost_paise": avg_cost_paise, "value_delta_paise": int(qty) * avg_cost_paise,
        "running_qty_units": qty, "running_avg_cost_paise": avg_cost_paise,
        "running_value_paise": int(qty) * avg_cost_paise,
    })


def test_adjust_rejects_reverse_itc_on_increase(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        inv.adjust_stock("PROD-1", StockAdjustmentIn(
            client_id="CLI", adjustment_date="2026-04-15", quantity=2,
            direction="increase", reason="physical_count_surplus", reverse_itc=True,
        ), CALLER)
    assert exc.value.status_code == 422


def test_adjust_rejects_unknown_item(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        inv.adjust_stock("NOPE", StockAdjustmentIn(
            client_id="CLI", adjustment_date="2026-04-15", quantity=2,
            direction="decrease", reason="damage",
        ), CALLER)
    assert exc.value.status_code == 404


def test_adjust_rejects_service_kind_items(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        inv.adjust_stock("SVC-1", StockAdjustmentIn(
            client_id="CLI", adjustment_date="2026-04-15", quantity=1,
            direction="decrease", reason="damage",
        ), CALLER)
    assert exc.value.status_code == 422
    assert "stock-tracked" in exc.value.detail


def test_adjust_writeoff_records_movement_and_posts_journal_with_valid_entry_type(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db)

    resp = inv.adjust_stock("PROD-1", StockAdjustmentIn(
        client_id="CLI", adjustment_date="2026-04-20", quantity=3,
        direction="decrease", reason="destroyed", reverse_itc=True, notes="Warehouse fire",
    ), CALLER)

    assert resp["success"] is True
    ledger = [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "adjustment"]
    assert len(ledger) == 1
    assert float(ledger[0]["running_qty_units"]) == 7

    # journal_entries.entry_type has a live CHECK constraint (Sales/Purchase/
    # Payment/Receipt/Journal/Contra/Opening) — this is a real regression
    # guard for that bug, not just a happy-path check.
    journals = db.rows("journal_entries")
    assert journals, "the write-off journal must actually post, not silently fail"
    valid_types = {"Sales", "Purchase", "Payment", "Receipt", "Journal", "Contra", "Opening"}
    assert all(j["entry_type"] in valid_types for j in journals)

    lines = db.rows("journal_lines")
    total_debit = sum(int(l["debit_paise"]) for l in lines)
    total_credit = sum(int(l["credit_paise"]) for l in lines)
    assert total_debit == total_credit  # double-entry must balance


# ── POST /api/inventory/items/{id}/writedown (AS-2/ICDS-II lower-of-cost-or-NRV) ─

def test_writedown_rejects_service_kind_items(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        inv.writedown_stock_to_nrv("SVC-1", NrvWritedownIn(
            client_id="CLI", writedown_date="2026-04-15", nrv_per_unit_paise=50_00,
        ), CALLER)
    assert exc.value.status_code == 422


def test_writedown_rejects_unknown_item(monkeypatch):
    db = _setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        inv.writedown_stock_to_nrv("NOPE", NrvWritedownIn(
            client_id="CLI", writedown_date="2026-04-15", nrv_per_unit_paise=50_00,
        ), CALLER)
    assert exc.value.status_code == 404


def test_writedown_records_value_only_movement_and_posts_balanced_journal(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db, qty="10", avg_cost_paise=100000)  # Rs 1000/unit

    resp = inv.writedown_stock_to_nrv("PROD-1", NrvWritedownIn(
        client_id="CLI", writedown_date="2026-04-20", nrv_per_unit_paise=70000,  # Rs 700/unit
        notes="Market price dropped",
    ), CALLER)

    assert resp["success"] is True
    ledger = [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "nrv_writedown"]
    assert len(ledger) == 1
    assert float(ledger[0]["running_qty_units"]) == 10  # quantity unchanged
    assert int(ledger[0]["running_value_paise"]) == 7_000_00

    journals = db.rows("journal_entries")
    assert journals, "the write-down journal must actually post, not silently fail"
    valid_types = {"Sales", "Purchase", "Payment", "Receipt", "Journal", "Contra", "Opening"}
    assert all(j["entry_type"] in valid_types for j in journals)

    lines = db.rows("journal_lines")
    total_debit = sum(int(l["debit_paise"]) for l in lines)
    total_credit = sum(int(l["credit_paise"]) for l in lines)
    assert total_debit == total_credit
    assert total_debit == 3_000_00  # Rs 1000 -> Rs 700, 10 units -> Rs 3,000 write-down


def test_writedown_is_noop_when_nrv_not_below_cost(monkeypatch):
    db = _setup(monkeypatch)
    _seed_opening_stock(db, qty="10", avg_cost_paise=100000)

    resp = inv.writedown_stock_to_nrv("PROD-1", NrvWritedownIn(
        client_id="CLI", writedown_date="2026-04-20", nrv_per_unit_paise=150000,  # above cost
    ), CALLER)

    assert resp["success"] is True
    assert resp["data"] is None
    assert [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "nrv_writedown"] == []
    assert db.rows("journal_entries") == []
