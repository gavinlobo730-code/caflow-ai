"""A foreign-currency receipt stores the bank account the money was paid into (POST-A-369 review of migration 572, found on the way).

WHAT WAS WRONG
    `create_foreign_receipt` resolved the cash leg of its journal from `data["bank_account_id"]` and then built the receipt row WITHOUT that key, so the
    row the CA reads had no bank account while the journal had debited the bank they chose: the Receipts tab's posting-account notice ("posted to the
    general Bank ledger") was false for every foreign receipt, the same way it was for every rupee receipt through the database function (migration 574).

WHAT THIS PINS
    The stored receipt carries the bank account the request named, a request that names none stores none, and the journal's cash leg is the named
    bank's own ledger (the premise: the key is the one the journal used).
"""
from models.invoices import ReceiptAllocationIn, ReceiptIn
from models.parties import CustomerIn
from tests.test_r227_fx_reversal import CALLER, FIRM, _setup, _usd_invoice


def _bank(db):
    ledger = next(a for a in db.rows("chart_of_accounts") if "bank" in str(a.get("account_name", "")).lower())
    db.seed("bank_accounts", {"id": "BANK-ROW-1", "firm_id": FIRM, "client_id": "CLI", "bank_name": "Test Bank",
                              "account_no": "5740001", "coa_account_id": ledger["id"], "account_type": "current", "is_active": True})
    return "BANK-ROW-1", ledger["id"]


def test_the_stored_foreign_receipt_names_the_bank_it_was_paid_into_and_the_journal_used_it(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    bank_row, bank_ledger = _bank(db)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Co", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"])
    out = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=100000, currency="USD", exchange_rate="83.0",
        bank_account_id=bank_row,
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)["data"]
    stored = next(r for r in db.rows("receipts") if r["id"] == out["id"])
    assert stored["bank_account_id"] == bank_row, "the receipt row lost the bank account the journal used"
    entry = next(e for e in db.rows("journal_entries") if e.get("source_type") == "receipt" and e.get("source_id") == out["id"])
    debited = {ln["account_id"] for ln in db.rows("journal_lines") if ln["journal_entry_id"] == entry["id"] and int(ln.get("debit_paise") or 0) > 0}
    assert bank_ledger in debited, "the premise of the test: the journal's cash leg is the named bank's own ledger"


def test_a_foreign_receipt_that_names_no_bank_stores_none(monkeypatch):
    cu, ve, si, pb, rc, pp, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Co", state_code="27"), CALLER)["data"]
    inv = _usd_invoice(si, cust["id"])
    out = rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=100000, currency="USD", exchange_rate="83.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)["data"]
    stored = next(r for r in db.rows("receipts") if r["id"] == out["id"])
    assert stored.get("bank_account_id") is None
