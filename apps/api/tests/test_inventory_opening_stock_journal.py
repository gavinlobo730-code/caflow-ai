"""
Opening stock must reach the General Ledger — every OTHER inventory movement
type (purchase receipt, sale/COGS, returns, write-off, NRV write-down) posts
its own Dr/Cr journal; seed_opening_balance / seed_opening_balances_batch were
the one gap, silently leaving the Inventory page and the Trial Balance/Balance
Sheet out of sync (bug report: opening stock seeded via product import never
showed up as an asset anywhere in the GL).
"""
import uuid

import pytest

from domain.inventory_service import seed_opening_balance, seed_opening_balances_batch, record_stock_out
from tests.e2e_harness import FakeDB, account_balance, trial_balance

FIRM = "firm-inv-1"
CLIENT = "client-inv-1"


def _wire(monkeypatch, db):
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: db)


def _seed_coa(db, firm_id=FIRM, client_id=CLIENT):
    inv = db.seed("chart_of_accounts", {
        "firm_id": firm_id, "client_id": client_id, "system_account_key": "inventory",
        "account_name": "Inventory", "is_active": True,
    })
    obe = db.seed("chart_of_accounts", {
        "firm_id": firm_id, "client_id": client_id, "system_account_key": None,
        "account_name": "Opening Balance Equity", "is_active": True,
    })
    return inv["id"], obe["id"]


def _seed_item(db, item_id, client_id=CLIENT):
    db.seed("service_catalogue", {
        "id": item_id, "firm_id": FIRM, "client_id": client_id,
        "name": f"Item {item_id}", "kind": "good", "stock_qty_units": "0", "avg_cost_paise": 0,
    })


def test_single_row_opening_balance_posts_a_journal(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    inv_id, obe_id = _seed_coa(db)
    item_id = str(uuid.uuid4())
    _seed_item(db, item_id)

    row = seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item_id,
        movement_date="2026-04-01", opening_qty=10, opening_cost_paise=100_00,
    )

    assert row is not None
    # value_delta_paise is the TOTAL cost of the opening quantity (see
    # _compute_stock_in), so opening_cost_paise=100_00 (Rs 100) is the whole
    # movement's value here, not a per-unit rate.
    ledger_row = next(r for r in db.rows("inventory_stock_ledger") if r["id"] == row["id"])
    assert ledger_row.get("journal_entry_id")
    assert account_balance(db, inv_id) == 100_00          # Dr Inventory
    assert account_balance(db, obe_id) == -100_00          # Cr Opening Balance Equity
    entries = [e for e in db.rows("journal_entries") if e.get("firm_id") == FIRM]
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "Opening"


def test_opening_balance_covering_prior_oversold_position_splits_inventory_and_cogs(monkeypatch):
    """task #103: opening stock entered for an item ALREADY oversold in the
    ledger (a sale recorded before its opening balance was set up) must
    split between real on-hand Inventory value and a COGS true-up for the
    portion covering the earlier sale's now-known real cost — not silently
    drop that cost, and not capitalise value for units that no longer exist."""
    db = FakeDB()
    _wire(monkeypatch, db)
    inv_id, obe_id = _seed_coa(db)
    cogs_id = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "system_account_key": "cogs",
        "account_name": "Cost of Goods Sold", "is_active": True,
    })["id"]
    item_id = str(uuid.uuid4())
    _seed_item(db, item_id)

    # Sell 3 units before any stock exists — oversold to -3, Rs 0 cost basis.
    record_stock_out(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item_id,
                     movement_date="2026-04-01", quantity=3, movement_type="sale")

    # Opening balance: 10 units @ Rs 100 = Rs 1,000. 3 of those cover the
    # deficit (Rs 300 true-up to COGS); 7 are genuine on-hand stock (Rs 700).
    row = seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item_id,
        movement_date="2026-04-01", opening_qty=10, opening_cost_paise=1_000_00,
    )

    assert row is not None
    assert row["running_qty_units"] == "7"
    assert account_balance(db, inv_id) == 700_00        # Dr Inventory (excess only)
    assert account_balance(db, cogs_id) == 300_00        # Dr COGS (true-up)
    assert account_balance(db, obe_id) == -1_000_00      # Cr OBE — combined, full Rs 1,000
    tb = trial_balance(db, FIRM, CLIENT)
    assert tb["total_debit_paise"] == tb["total_credit_paise"]


def test_single_row_still_seeds_ledger_when_coa_missing(monkeypatch):
    # No chart_of_accounts seeded — journal posting must degrade silently,
    # never block the opening balance itself from being recorded.
    db = FakeDB()
    _wire(monkeypatch, db)
    item_id = str(uuid.uuid4())
    _seed_item(db, item_id)

    row = seed_opening_balance(
        db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item_id,
        movement_date="2026-04-01", opening_qty=10, opening_cost_paise=100_00,
    )

    assert row is not None
    assert row.get("journal_entry_id") is None
    assert db.rows("journal_entries") == []


def test_batch_posts_one_combined_journal_per_client_not_per_item(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    inv_id, obe_id = _seed_coa(db)

    rows = []
    for i in range(5):
        item_id = str(uuid.uuid4())
        _seed_item(db, item_id)
        rows.append({
            "id": item_id, "client_id": CLIENT, "kind": "good",
            "opening_qty_units": "10", "opening_cost_paise": 100_00,
            "created_at": "2026-04-01T00:00:00Z",
        })

    seed_opening_balances_batch(db, firm_id=FIRM, created_by="user-1", rows=rows)

    entries = [e for e in db.rows("journal_entries") if e.get("firm_id") == FIRM]
    assert len(entries) == 1                              # one journal for the WHOLE batch
    assert entries[0]["entry_type"] == "Opening"
    assert account_balance(db, inv_id) == 500_00           # 5 items x Rs 100 each
    assert account_balance(db, obe_id) == -500_00

    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 5
    assert all(r.get("journal_entry_id") == entries[0]["id"] for r in ledger)


def test_batch_posts_separate_journal_per_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    client_b = "client-inv-2"
    _seed_coa(db, client_id=CLIENT)
    _seed_coa(db, client_id=client_b)

    item_a, item_b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_item(db, item_a, client_id=CLIENT)
    _seed_item(db, item_b, client_id=client_b)
    rows = [
        {"id": item_a, "client_id": CLIENT, "kind": "good",
         "opening_qty_units": "10", "opening_cost_paise": 100_00, "created_at": "2026-04-01T00:00:00Z"},
        {"id": item_b, "client_id": client_b, "kind": "good",
         "opening_qty_units": "20", "opening_cost_paise": 50_00, "created_at": "2026-04-01T00:00:00Z"},
    ]

    seed_opening_balances_batch(db, firm_id=FIRM, created_by="user-1", rows=rows)

    entries = [e for e in db.rows("journal_entries") if e.get("firm_id") == FIRM]
    assert len(entries) == 2
    assert {e["client_id"] for e in entries} == {CLIENT, client_b}


def test_batch_skips_journal_when_no_goods_rows_have_opening_balance(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _seed_coa(db)
    rows = [{"id": str(uuid.uuid4()), "client_id": CLIENT, "kind": "service",
             "opening_qty_units": "10", "opening_cost_paise": 100_00}]

    seed_opening_balances_batch(db, firm_id=FIRM, created_by="user-1", rows=rows)

    assert db.rows("journal_entries") == []
