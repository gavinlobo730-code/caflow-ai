"""
Cross-feature isolation: an inventory opening-stock journal
(domain/inventory_service.post_opening_stock_journal_entry) must NEVER be
swept into services/opening_balance_service.py's AR/AP/Bank reconciliation.

Confirmed live (Apex Trading Solutions test client, 2026-07-12): a client
already carrying an inventory opening balance (₹9,89,11,710, posted with
source_type="Opening" — the SAME tag opening_balance_service.py's
_current_opening_net() scans as "the auto-maintained AR/AP/Bank opening
family it manages") imported 40 vendors with opening balances. The vendor
import's post_opening_balances() call summed EVERY account appearing under
source_type="Opening" — including Inventory, which it has no target for
(target defaults to 0 for any account it doesn't explicitly track) — and
posted a single combined delta entry that correctly added the new Trade
Payables balance AND incorrectly credited Inventory down to zero, on top of
whatever had already legitimately happened to that account. The real
Balance Sheet showed Inventory at -₹9,89,11,710 and Opening Balance Equity
at -₹10,29,65,710 as a result.

Fix: domain/inventory_service.py now tags its opening-stock journal with
source_type="InventoryOpening", a distinct family opening_balance_service.py
never queries. These tests assert that isolation directly, at the same
_current_opening_net() layer where the bug actually lived — the cheapest
place to pin it down, and immune to unrelated changes in how vendors/
customers happen to be created.
"""
import routers.service_catalogue as sc
import routers.vendors as vendors_router
import services.opening_balance_service as obs
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "user-1", "auth_user_id": "auth-1", "email": "ca@firma.test", "role": "Partner"}
CLIENT = "CLI-A"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [sc, vendors_router, obs])
    return db


def _seed_coa(db):
    accounts = [
        ("Inventory", "Asset", "inventory"),
        ("Opening Balance Equity", "Equity", None),
        ("Trade Payables", "Liability", "ap"),
        ("Trade Receivables", "Asset", "ar"),
    ]
    for name, typ, key in accounts:
        db.seed("chart_of_accounts", {
            "firm_id": FIRM, "client_id": None, "account_name": name,
            "account_type": typ, "system_account_key": key, "is_active": True,
        })


def test_inventory_opening_journal_is_invisible_to_master_opening_reconciliation(monkeypatch):
    db = _setup(monkeypatch)
    _seed_coa(db)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    from models.service_catalogue import ServiceCatalogueIn
    resp = sc.create_service(
        ServiceCatalogueIn(client_id=CLIENT, name="Widget", kind="good",
                            opening_qty_units=10, opening_cost_paise=98_911_71_000),
        CALLER,
    )
    assert resp["success"] is True

    # The inventory-opening journal must NOT be part of the
    # source_type="Opening" family opening_balance_service.py reconciles.
    current = obs._current_opening_net(db, FIRM, CLIENT)
    inv_account = next(a for a in db.rows("chart_of_accounts") if a["account_name"] == "Inventory")
    assert inv_account["id"] not in current


def test_vendor_opening_balance_sync_never_touches_inventory(monkeypatch):
    db = _setup(monkeypatch)
    _seed_coa(db)
    db.seed("clients", {"id": CLIENT, "financial_year_start": "2025-04-01"})

    from models.service_catalogue import ServiceCatalogueIn
    sc.create_service(
        ServiceCatalogueIn(client_id=CLIENT, name="Widget", kind="good",
                            opening_qty_units=10, opening_cost_paise=98_911_71_000),
        CALLER,
    )
    inv_account = next(a for a in db.rows("chart_of_accounts") if a["account_name"] == "Inventory")
    inventory_ledger_before = [
        (l["debit_paise"], l["credit_paise"]) for l in db.rows("journal_lines")
        if l["account_id"] == inv_account["id"]
    ]
    assert inventory_ledger_before == [(9891171000, 0)]

    from models.parties import VendorIn
    vendor_resp = vendors_router.create_vendor(
        VendorIn(client_id=CLIENT, name="Test Vendor", opening_balance_paise=40_54_000),
        CALLER,
    )
    assert vendor_resp["success"] is True

    # Inventory's own ledger lines must be exactly what they were before the
    # vendor's opening-balance sync ran — no extra credit sweeping it to zero.
    inventory_ledger_after = [
        (l["debit_paise"], l["credit_paise"]) for l in db.rows("journal_lines")
        if l["account_id"] == inv_account["id"]
    ]
    assert inventory_ledger_after == inventory_ledger_before
