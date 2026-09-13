"""
Blocked §17(5) GST is capitalised into inventory, not left in expense. INV-05a.

WHAT WAS WRONG
    `apply_purchase_to_inventory` costed a stock receipt at
    `taxable_amount_paise` ALONE. Meanwhile the purchase-bill journal had
    already debited the blocked tax to the line's expense account
    (`phase2_journal_service`, the `blocked_total` block), and the inventory
    receipt journal moved only the taxable value out of that account into
    Inventory. The blocked tax stayed behind:

        Rs 1,000 of goods, Rs 180 of blocked tax
          bill        Dr Expense 1,180              Cr Payables 1,180
          receipt     Dr Inventory 1,000            Cr Expense 1,000
          left with   Inventory 1,000, Expense 180

    So closing stock was understated by the blocked tax and the period's
    expense overstated by it, on every goods purchase carrying blocked credit
    — and because the moving average is computed off the same figure, every
    later COGS was wrong too.

THE STANDARD
    AS-2 (and Ind AS 2) paragraph 6: cost of purchase comprises the price plus
    "duties and taxes (OTHER THAN THOSE SUBSEQUENTLY RECOVERABLE by the
    enterprise from the taxing authorities)". Creditable GST is recoverable, so
    excluding it is right and always was. Credit blocked by CGST Act §17(5) is
    recoverable from nobody, so it is part of what the goods cost.

WHY NO NEW ACCOUNT AND NO MIGRATION
    The expense account already holds the blocked tax, so relieving it in full
    keeps the receipt journal balanced against the account it was posted to.
    And `inventory_stock_ledger.value_delta_paise` and the journal's Inventory
    debit are the same number by construction, so the tie between
    `stock_position_as_at` and the control account survives — both move
    together. `purchase_bill_lines.itc_eligible` has existed since migration
    240 and the per-line tax heads since 050.

WHAT THIS DOES NOT DO
    Freight inward and customs duty — the other two-thirds of INV-05. Both
    need columns that do not exist AND an apportionment basis (by value? by
    quantity? by weight?), which is a decision rather than a derivation. They
    are deliberately left, and the finding records what they are blocked on.
"""
from __future__ import annotations

import uuid

import pytest

from domain.inventory_service import apply_purchase_to_inventory, _blocked_tax_on_line
from services.phase2_journal_service import purchase_bill_journal_ref
from tests.e2e_harness import FakeDB, account_balance

FIRM = "firm-inv05"
CLIENT = "client-inv05"


def _seed_coa(db):
    inv = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "system_account_key": "inventory",
        "account_name": "Inventory", "is_active": True})
    cogs = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "system_account_key": "cogs",
        "account_name": "Cost of Goods Sold", "is_active": True})
    purchases = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "system_account_key": None,
        "account_name": "Purchases", "is_active": True})
    return {"inventory": inv["id"], "cogs": cogs["id"], "Purchases": purchases["id"]}


def _seed_good(db, item_id):
    db.seed("service_catalogue", {
        "id": item_id, "firm_id": FIRM, "client_id": CLIENT,
        "name": f"Item {item_id}", "kind": "good",
        "stock_qty_units": "0", "avg_cost_paise": 0})


def _line(bill_id, item_id, *, taxable, cgst=0, sgst=0, igst=0, cess=0, eligible=True, qty="10"):
    return {
        "bill_id": bill_id, "description": "Goods", "quantity": qty,
        "taxable_amount_paise": taxable, "expense_account_id": None,
        "service_catalogue_id": item_id, "itc_eligible": eligible,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst, "cess_paise": cess,
    }


def _receive(db, lines, bill_id=None):
    bill_id = bill_id or str(uuid.uuid4())
    for l in lines:
        db.seed("purchase_bill_lines", dict(l, bill_id=bill_id))
    bill = {"id": bill_id, "bill_no": "BILL-1", "bill_date": "2026-04-05", "client_id": CLIENT}
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    return bill_id


# ── The rule itself ──────────────────────────────────────────────────────────

def test_a_blocked_line_capitalises_its_whole_tax():
    assert _blocked_tax_on_line(
        {"itc_eligible": False, "cgst_paise": 9000, "sgst_paise": 9000,
         "igst_paise": 0, "cess_paise": 500}) == 18500


def test_an_eligible_line_capitalises_nothing():
    assert _blocked_tax_on_line(
        {"itc_eligible": True, "cgst_paise": 9000, "sgst_paise": 9000}) == 0


def test_a_line_nobody_flagged_capitalises_nothing():
    """Migration 240 made the column NOT NULL DEFAULT true. A row with the key
    absent is the pre-existing behaviour and must not start capitalising."""
    assert _blocked_tax_on_line({"cgst_paise": 9000, "sgst_paise": 9000}) == 0
    assert _blocked_tax_on_line({"itc_eligible": None, "cgst_paise": 9000}) == 0


def test_igst_and_cess_count_too():
    assert _blocked_tax_on_line(
        {"itc_eligible": False, "igst_paise": 18000, "cess_paise": 1200}) == 19200


# ── End to end: the ledger and the control account move together ─────────────

def test_blocked_tax_reaches_both_the_stock_ledger_and_the_inventory_account():
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)

    bill_id = _receive(db, [_line(bill_id=None, item_id=item, taxable=100000,
                                  cgst=9000, sgst=9000, eligible=False)])

    cost = 100000 + 18000
    assert account_balance(db, coa["inventory"]) == cost, (
        "the Inventory control account must carry the blocked tax — AS-2 par. 6 "
        "puts non-recoverable tax in the cost of the goods")
    assert account_balance(db, coa["Purchases"]) == -cost, (
        "the expense account already held the blocked tax and must be relieved "
        "in full, or the two sides of the receipt journal disagree")

    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 1
    assert int(ledger[0]["value_delta_paise"]) == cost, (
        "stock_position_as_at sums value_delta_paise; if it and the journal "
        "debit differ, closing stock stops tying to the control account")


def test_an_eligible_purchase_is_byte_for_byte_what_it_was():
    """The change must be invisible to every client with no blocked credit,
    which is almost all of them."""
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)

    _receive(db, [_line(bill_id=None, item_id=item, taxable=100000,
                        cgst=9000, sgst=9000, eligible=True)])

    assert account_balance(db, coa["inventory"]) == 100000
    assert int(db.rows("inventory_stock_ledger")[0]["value_delta_paise"]) == 100000


def test_a_bill_mixing_a_blocked_line_and_an_eligible_one_splits_correctly():
    db = FakeDB()
    coa = _seed_coa(db)
    blocked_item, clean_item = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_good(db, blocked_item)
    _seed_good(db, clean_item)

    _receive(db, [
        _line(None, blocked_item, taxable=100000, cgst=9000, sgst=9000, eligible=False),
        _line(None, clean_item, taxable=200000, cgst=18000, sgst=18000, eligible=True),
    ])

    assert account_balance(db, coa["inventory"]) == 118000 + 200000
    by_value = sorted(int(r["value_delta_paise"]) for r in db.rows("inventory_stock_ledger"))
    assert by_value == [118000, 200000]


def test_the_moving_average_carries_the_blocked_tax_into_later_cogs():
    """The whole reason this is not merely a presentation fix: the average is
    computed off value_delta_paise, so understating the receipt understates
    every subsequent cost of sale as well."""
    db = FakeDB()
    _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)

    _receive(db, [_line(None, item, taxable=100000, cgst=9000, sgst=9000,
                        eligible=False, qty="10")])

    row = db.rows("inventory_stock_ledger")[0]
    # 118,000 paise over 10 units = 11,800 a unit, not 10,000.
    assert int(row["running_value_paise"]) == 118000
    assert int(row["running_avg_cost_paise"]) == 11800


def test_the_receipt_journal_still_balances():
    db = FakeDB()
    _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill_id = _receive(db, [_line(None, item, taxable=100000, cgst=9000, sgst=9000,
                                  eligible=False)])

    ref = f"{purchase_bill_journal_ref(bill_id)}-INV"
    entry = [e for e in db.rows("journal_entries") if e.get("reference_no") == ref]
    assert len(entry) == 1
    lines = [l for l in db.rows("journal_lines") if l["journal_entry_id"] == entry[0]["id"]]
    assert sum(int(l.get("debit_paise") or 0) for l in lines) == \
           sum(int(l.get("credit_paise") or 0) for l in lines)


# ── A service line is not stock and is untouched ─────────────────────────────

def test_a_blocked_service_line_capitalises_nothing_because_it_is_not_stock():
    """`kind != "good"` never reaches the stock ledger at all, so a blocked
    professional fee stays an expense — which is right: there is no asset to
    carry it."""
    db = FakeDB()
    coa = _seed_coa(db)
    svc = str(uuid.uuid4())
    db.seed("service_catalogue", {
        "id": svc, "firm_id": FIRM, "client_id": CLIENT, "name": "Consultancy",
        "kind": "service"})

    _receive(db, [_line(None, svc, taxable=100000, cgst=9000, sgst=9000, eligible=False)])

    assert db.rows("inventory_stock_ledger") == []
    assert account_balance(db, coa["inventory"]) == 0


# ── The coupling with the bill journal, which is what makes this balance ─────

def test_the_expense_account_nets_to_zero_across_the_two_journals(monkeypatch):
    """The whole argument in one assertion.

    PUR-04 made `journal_for_purchase_bill` debit a blocked line's tax to that
    line's OWN expense account (per-line, with the fallback order
    explicit -> "%Purchase%" -> "%Expense%"). The inventory receipt journal
    resolves its credit side with the SAME fallback order. So capitalising the
    blocked tax relieves exactly the account that received it, and the expense
    account is left holding nothing: the whole landed cost sits in Inventory,
    which is where AS-2 par. 6 puts it.

    Before this change the same two journals left the blocked tax stranded in
    expense for ever — nothing else ever visits that account for this bill.
    """
    from services.phase2_journal_service import phase2_journal_service
    from tests.e2e_harness import seed_standard_coa, trial_balance

    db = FakeDB()
    ids = seed_standard_coa(db, FIRM, CLIENT)
    inventory_id = db.seed("chart_of_accounts", {
        "firm_id": FIRM, "client_id": CLIENT, "system_account_key": "inventory",
        "account_name": "Inventory", "is_active": True})["id"]
    item = str(uuid.uuid4())
    _seed_good(db, item)

    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", _line(bill_id, item, taxable=100000,
                                         cgst=9000, sgst=9000, eligible=False))
    bill = {
        "id": bill_id, "bill_no": "PB-INV05", "bill_date": "2026-04-05",
        "client_id": CLIENT, "taxable_amount_paise": 100000,
        "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0, "cess_paise": 0,
        "total_paise": 118000, "net_payable_paise": 118000, "tds_paise": 0,
        # Migration 240's header, computed off the same lines by
        # routers/purchase_bills._compute_bill_totals.
        "ineligible_itc_cgst_paise": 9000, "ineligible_itc_sgst_paise": 9000,
        "ineligible_itc_igst_paise": 0, "ineligible_itc_cess_paise": 0,
    }

    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr("services.phase2_journal_service._USE_MOCK", False)
    phase2_journal_service.journal_for_purchase_bill(bill, FIRM, CLIENT)
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)

    purchases_id = ids["Purchases"]
    assert account_balance(db, purchases_id) == 0, (
        "the blocked tax was debited here by the bill journal and must be "
        "relieved here by the receipt journal — anything left is the INV-05 "
        "stranding this change exists to end")
    assert account_balance(db, inventory_id) == 118000
    assert account_balance(db, ids["gst_input"]) == 0, (
        "PUR-04: no part of a blocked line's tax is a recoverable asset")
    assert account_balance(db, ids["ap"]) == -118000
    tb = trial_balance(db, FIRM, CLIENT)
    assert tb["total_debit_paise"] == tb["total_credit_paise"]
