"""
Multi-line inventory journal postings must reach the General Ledger IN FULL,
not just the first line.

apply_purchase_to_inventory / apply_sale_to_inventory used to post a separate
journal entry per stock-tracked LINE, all sharing the same document
reference_no — _create_journal's idempotency guard (keyed on firm+client+
reference_no+entry_date) then mistook lines 2+ for duplicate postings of
line 1 and silently returned line 1's journal id without adding any value,
while the stock ledger still recorded every line's movement correctly. Bug
report: a 3-line purchase bill (cement/tiles/adhesive) posted only the first
line's value (Rs 7,600 of a real Rs 18,350) to the Balance Sheet.

apply_credit_note_to_inventory / apply_debit_note_to_inventory already
aggregated correctly (one combined journal per document) and are unaffected;
not re-tested here.

Uses the real e2e harness (tests/e2e_harness.FakeDB) — not the simplified
_FakeDB in test_inventory_service.py — because it exercises the actual
phase2_journal_service._create_journal idempotency path this bug lived in.
"""
import uuid

from domain.inventory_service import (
    apply_purchase_to_inventory,
    apply_sale_to_inventory,
    record_stock_in,
)
from services.phase2_journal_service import purchase_bill_journal_ref
from tests.e2e_harness import FakeDB, account_balance

FIRM = "firm-multiline-1"
CLIENT = "client-multiline-1"


def _seed_coa(db, firm_id=FIRM, client_id=CLIENT, **extra_accounts):
    inv = db.seed("chart_of_accounts", {
        "firm_id": firm_id, "client_id": client_id, "system_account_key": "inventory",
        "account_name": "Inventory", "is_active": True,
    })
    cogs = db.seed("chart_of_accounts", {
        "firm_id": firm_id, "client_id": client_id, "system_account_key": "cogs",
        "account_name": "Cost of Goods Sold", "is_active": True,
    })
    purchases = db.seed("chart_of_accounts", {
        "firm_id": firm_id, "client_id": client_id, "system_account_key": None,
        "account_name": "Purchases", "is_active": True,
    })
    ids = {"inventory": inv["id"], "cogs": cogs["id"], "Purchases": purchases["id"]}
    for name in extra_accounts:
        row = db.seed("chart_of_accounts", {
            "firm_id": firm_id, "client_id": client_id, "system_account_key": None,
            "account_name": name, "is_active": True,
        })
        ids[name] = row["id"]
    return ids


def _seed_item(db, item_id, client_id=CLIENT):
    db.seed("service_catalogue", {
        "id": item_id, "firm_id": FIRM, "client_id": client_id,
        "name": f"Item {item_id}", "kind": "good", "stock_qty_units": "0", "avg_cost_paise": 0,
    })


def test_purchase_bill_with_three_lines_posts_one_journal_with_full_combined_value():
    db = FakeDB()
    coa = _seed_coa(db)
    cement, tiles, adhesive = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    for item_id in (cement, tiles, adhesive):
        _seed_item(db, item_id)

    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", {
        "bill_id": bill_id, "description": "Cement", "quantity": "20",
        "taxable_amount_paise": 760_000, "expense_account_id": None, "service_catalogue_id": cement,
    })
    db.seed("purchase_bill_lines", {
        "bill_id": bill_id, "description": "Tiles", "quantity": "10",
        "taxable_amount_paise": 850_000, "expense_account_id": None, "service_catalogue_id": tiles,
    })
    db.seed("purchase_bill_lines", {
        "bill_id": bill_id, "description": "Adhesive", "quantity": "5",
        "taxable_amount_paise": 225_000, "expense_account_id": None, "service_catalogue_id": adhesive,
    })
    bill = {"id": bill_id, "bill_no": "BILL-ML-1", "bill_date": "2026-04-05", "client_id": CLIENT}

    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)

    # Journal reference is the system-unique PB-{id} base (vendor bill numbers
    # collide across vendors), suffixed -INV for the capitalisation entry.
    inv_ref = f"{purchase_bill_journal_ref(bill_id)}-INV"
    entries = [e for e in db.rows("journal_entries") if e.get("reference_no") == inv_ref]
    assert len(entries) == 1, "must be exactly one combined journal for the whole bill, not one per line"
    total = 760_000 + 850_000 + 225_000
    assert account_balance(db, coa["inventory"]) == total
    assert account_balance(db, coa["Purchases"]) == -total

    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 3
    assert all(r.get("journal_entry_id") == entries[0]["id"] for r in ledger)


def test_purchase_bill_lines_with_different_expense_accounts_group_the_credit_side():
    db = FakeDB()
    coa = _seed_coa(db, **{"Consumables Expense": None, "Office Expense": None})
    item_a, item_b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_item(db, item_a)
    _seed_item(db, item_b)

    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", {
        "bill_id": bill_id, "description": "A", "quantity": "1",
        "taxable_amount_paise": 100_000, "expense_account_id": coa["Consumables Expense"],
        "service_catalogue_id": item_a,
    })
    db.seed("purchase_bill_lines", {
        "bill_id": bill_id, "description": "B", "quantity": "1",
        "taxable_amount_paise": 50_000, "expense_account_id": coa["Office Expense"],
        "service_catalogue_id": item_b,
    })
    bill = {"id": bill_id, "bill_no": "BILL-ML-2", "bill_date": "2026-04-05", "client_id": CLIENT}

    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)

    inv_ref = f"{purchase_bill_journal_ref(bill_id)}-INV"
    entries = [e for e in db.rows("journal_entries") if e.get("reference_no") == inv_ref]
    assert len(entries) == 1
    assert account_balance(db, coa["inventory"]) == 150_000
    assert account_balance(db, coa["Consumables Expense"]) == -100_000
    assert account_balance(db, coa["Office Expense"]) == -50_000


def test_sales_invoice_with_two_lines_posts_one_combined_cogs_journal():
    db = FakeDB()
    coa = _seed_coa(db)
    good_a, good_b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_item(db, good_a)
    _seed_item(db, good_b)
    # Opening stock so each sale has a real cost basis to recognise as COGS.
    record_stock_in(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=good_a,
                     movement_date="2026-04-01", quantity=10, total_cost_paise=1_000_00, movement_type="opening")
    record_stock_in(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=good_b,
                     movement_date="2026-04-01", quantity=10, total_cost_paise=2_000_00, movement_type="opening")

    invoice_id = str(uuid.uuid4())
    db.seed("client_sales_invoice_lines", {
        "sales_invoice_id": invoice_id, "description": "A x3", "quantity": "3", "service_catalogue_id": good_a,
    })
    db.seed("client_sales_invoice_lines", {
        "sales_invoice_id": invoice_id, "description": "B x4", "quantity": "4", "service_catalogue_id": good_b,
    })
    invoice = {"id": invoice_id, "invoice_no": "INV-ML-1", "invoice_date": "2026-04-20", "client_id": CLIENT}

    apply_sale_to_inventory(db, firm_id=FIRM, client_id=CLIENT, invoice=invoice)

    entries = [e for e in db.rows("journal_entries") if e.get("reference_no") == "INV-ML-1-COGS"]
    assert len(entries) == 1, "must be exactly one combined COGS journal for the whole invoice, not one per line"
    # good_a: 3 units @ Rs 100 avg = 300; good_b: 4 units @ Rs 200 avg = 800 -> 1,100 total.
    expected_total = 300_00 + 800_00
    assert account_balance(db, coa["cogs"]) == expected_total
    assert account_balance(db, coa["inventory"]) == -expected_total

    sale_rows = [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "sale"]
    assert len(sale_rows) == 2
    assert all(r.get("journal_entry_id") == entries[0]["id"] for r in sale_rows)
