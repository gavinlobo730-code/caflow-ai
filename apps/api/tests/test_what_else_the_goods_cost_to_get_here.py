"""Freight inward, insurance and non-creditable duty in the cost of stock.
INV-05, second half. Migration 396.

WHAT WAS WRONG
    `apply_purchase_to_inventory` costed a receipt at the line's taxable value
    plus its §17(5)-blocked tax (INV-05a) and NOTHING ELSE. AS-2 paragraph 6:
    the cost of purchase "consists of the purchase price including duties and
    taxes ..., FREIGHT INWARDS and OTHER EXPENDITURE DIRECTLY ATTRIBUTABLE TO
    THE ACQUISITION". So a client who paid to bring a consignment in carried
    stock at less than it cost, expensed the freight in the month it was
    billed rather than when the goods sold, and — the cost formula running off
    the same figure — got every later COGS wrong with it.

THE BASIS IS A POLICY, NOT A FIGURE THE STANDARD GIVES
    AS-2 settles what goes IN and not how to split one freight bill across the
    lines it covered. Owner decision of 14-09-2026, taken after reading what
    ships: TallyPrime offers Appropriate by Qty / by Value per expense ledger,
    Zoho Books offers Quantity / Value on save, QuickBooks Enterprise offers
    Quantity / Amount / Percentage, Xero has none. Both bases, default value,
    per-client policy with a per-bill override.

What these tests hold:
  1. The split is exact, on both bases, and they differ where it matters.
  2. The basis chain, and what an unrecorded client gets.
  3. The receipt carries it, and each charge's OWN account is relieved.
  4. What is refused: weight, a service line, nothing to attach to.
  5. `applied_at` is the boundary — after the receipt, the charge is reported.
  6. The Bill of Entry carry-over, which is INV-05's customs third.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from domain.inventory import landed_cost as lc
from domain.inventory_service import apply_purchase_to_inventory
from services import landed_cost_service as svc
from tests.e2e_harness import FakeDB, account_balance

FIRM = "firm-inv05b"
CLIENT = "client-inv05b"


def _line(item_id, *, taxable, qty="10", cgst=0, sgst=0, eligible=True, account=None):
    return {
        "description": "Goods", "quantity": qty,
        "taxable_amount_paise": taxable, "expense_account_id": account,
        "service_catalogue_id": item_id, "itc_eligible": eligible,
        "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": 0, "cess_paise": 0,
    }


def _seed_coa(db):
    out = {}
    for key, name in [("inventory", "Inventory"), ("cogs", "Cost of Goods Sold"),
                      (None, "Purchases"), (None, "Freight Inward"),
                      (None, "Customs Duty")]:
        row = db.seed("chart_of_accounts", {
            "firm_id": FIRM, "client_id": CLIENT, "system_account_key": key,
            "account_name": name, "is_active": True})
        out[name] = row["id"]
        if key:
            out[key] = row["id"]
    return out


def _seed_good(db, item_id):
    db.seed("service_catalogue", {
        "id": item_id, "firm_id": FIRM, "client_id": CLIENT,
        "name": f"Item {item_id}", "kind": "good",
        "stock_qty_units": "0", "avg_cost_paise": 0})


def _seed_service(db, item_id):
    db.seed("service_catalogue", {
        "id": item_id, "firm_id": FIRM, "client_id": CLIENT,
        "name": "Consulting", "kind": "service"})


def _bill(db, lines, *, charges=(), basis=None, client_basis=None, bill_id=None):
    bill_id = bill_id or str(uuid.uuid4())
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "landed_cost_basis": client_basis})
    for l in lines:
        db.seed("purchase_bill_lines", dict(l, bill_id=bill_id))
    for c in charges:
        db.seed("purchase_bill_landed_costs", {
            "firm_id": FIRM, "client_id": CLIENT, "bill_id": bill_id,
            "source": "manual", "bill_of_entry_id": None, "applied_at": None,
            **c})
    return {"id": bill_id, "bill_no": "BILL-1", "bill_date": "2026-04-05",
            "client_id": CLIENT, "landed_cost_basis": basis}


# ── 1. the split ────────────────────────────────────────────────────────────

CHAIRS = lc.Line("l1", "i1", 200 * 20000, Decimal(200))     # 200 @ ₹200
TABLES = lc.Line("l2", "i2", 20 * 500000, Decimal(20))      # 20 @ ₹5,000


def test_the_two_bases_are_far_apart_and_both_sum_exactly():
    # ₹50,000 of freight over 200 chairs (₹40,000) and 20 tables (₹1,00,000).
    by_value = lc.apportion([CHAIRS, TABLES], 50_000_00, basis=lc.BY_VALUE)
    by_qty = lc.apportion([CHAIRS, TABLES], 50_000_00, basis=lc.BY_QUANTITY)
    assert by_value.by_line == {"l1": 14_285_71, "l2": 35_714_29}
    assert by_qty.by_line == {"l1": 45_454_55, "l2": 4_545_45}
    for split in (by_value, by_qty):
        assert sum(split.by_line.values()) == 50_000_00, (
            "largest remainder — the parts sum to the charge exactly, or the "
            "residue has to go somewhere and every place is wrong")
    assert by_value.by_line["l2"] > by_qty.by_line["l2"] * 7, (
        "this is why the basis is a choice rather than a default")


@pytest.mark.parametrize("charge", [1, 3, 7, 99, 100_01, 12_345_67])
@pytest.mark.parametrize("basis", [lc.BY_VALUE, lc.BY_QUANTITY])
def test_every_charge_splits_to_exactly_itself(charge, basis):
    split = lc.apportion([CHAIRS, TABLES], charge, basis=basis)
    assert sum(split.by_line.values()) + split.unapportioned_paise == charge


def test_split_pro_rata_is_exact_when_the_amount_is_the_total():
    # The identity the receipt journal relies on: on an ordinary receipt the
    # movement takes the whole cost, and the credit side must be the
    # contributions themselves with nothing rounded.
    weights = [100001, 250, 4999]
    assert lc.split_pro_rata(sum(weights), weights) == weights


def test_two_charges_are_split_separately_and_still_total():
    both = lc.apportion_many(
        [CHAIRS, TABLES], [("freight", 2_000_00), ("insurance", 1_000_00)],
        basis=lc.BY_VALUE)
    assert sum(both.by_line.values()) == 3_000_00
    assert set(both.per_charge) == {"freight", "insurance"}


# ── 2. the basis chain ──────────────────────────────────────────────────────

def test_the_bill_overrides_the_client_which_overrides_the_default():
    assert lc.basis_for(None, None) == lc.BY_VALUE
    assert lc.basis_for("quantity", None) == lc.BY_QUANTITY
    assert lc.basis_for("quantity", "value") == lc.BY_VALUE, (
        "the bill is the narrower statement — the consignment that differs "
        "from the client's usual is what the override exists for")
    assert lc.basis_for(None, "quantity") == lc.BY_QUANTITY


def test_an_unrecorded_client_gets_value_and_the_answer_says_why():
    assert lc.BASIS_WHEN_UNRECORDED == lc.BY_VALUE
    assert "accounting policy" in lc.UNRECORDED_MEANS


def test_a_rubbish_basis_falls_through_rather_than_raising():
    assert lc.basis_for("weight", None) == lc.BY_VALUE


# ── 3. the receipt carries it ───────────────────────────────────────────────

def test_the_receipt_costs_the_goods_at_price_plus_freight():
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])],
                 charges=[{"description": "Freight inward", "amount_paise": 5_000_00,
                           "expense_account_id": coa["Freight Inward"]}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)

    cost = 100_000_00 + 5_000_00
    assert account_balance(db, coa["inventory"]) == cost, (
        "AS-2 par. 6 puts freight inwards in the cost of purchase")
    assert int(db.rows("inventory_stock_ledger")[0]["value_delta_paise"]) == cost


def test_each_charge_relieves_its_OWN_expense_account():
    # The transporter's bill posted Dr Freight / Cr Transporter. The receipt
    # posts Dr Inventory / Cr Freight, so Freight nets to zero and the
    # transporter stays owed. Crediting the LINE's account instead would leave
    # freight in expense for ever and relieve a purchases account that never
    # carried it.
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])],
                 charges=[{"description": "Freight inward", "amount_paise": 5_000_00,
                           "expense_account_id": coa["Freight Inward"]}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)

    assert account_balance(db, coa["Purchases"]) == -100_000_00
    assert account_balance(db, coa["Freight Inward"]) == -5_000_00


def test_the_receipt_journal_still_balances():
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=33_333_33, account=coa["Purchases"])],
                 charges=[{"description": "Freight", "amount_paise": 1_000_01,
                           "expense_account_id": coa["Freight Inward"]},
                          {"description": "Insurance", "amount_paise": 7,
                           "expense_account_id": coa["Freight Inward"]}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    for entry in db.rows("journal_entries"):
        lines = [l for l in db.rows("journal_lines")
                 if l.get("journal_entry_id") == entry["id"]]
        assert sum(int(l["debit_paise"]) for l in lines) == \
               sum(int(l["credit_paise"]) for l in lines)


def test_a_bill_with_no_charges_is_byte_for_byte_what_it_was():
    """Almost every bill. The change must be invisible to them."""
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert account_balance(db, coa["inventory"]) == 100_000_00
    assert account_balance(db, coa["Purchases"]) == -100_000_00


def test_the_charge_is_split_over_the_lines_on_the_bills_own_basis():
    db = FakeDB()
    coa = _seed_coa(db)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_good(db, a)
    _seed_good(db, b)
    bill = _bill(
        db,
        [_line(a, taxable=40_000_00, qty="200", account=coa["Purchases"]),
         _line(b, taxable=100_000_00, qty="20", account=coa["Purchases"])],
        charges=[{"description": "Freight", "amount_paise": 50_000_00,
                  "expense_account_id": coa["Freight Inward"]}],
        basis="quantity", client_basis="value")
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    by_item = {r["service_catalogue_id"]: int(r["value_delta_paise"])
               for r in db.rows("inventory_stock_ledger")}
    # Quantity, because the BILL said so: 200/220 and 20/220 of ₹50,000.
    assert by_item[a] == 40_000_00 + 45_454_55
    assert by_item[b] == 100_000_00 + 4_545_45


# ── 4. what is refused ──────────────────────────────────────────────────────

def test_weight_and_volume_are_refused_with_the_reason():
    r = lc.basis_refusal("weight")
    assert "no weight" in r.lower() or "holds a weight" in r
    assert lc.basis_refusal("volume")
    assert lc.basis_refusal("value") is None
    assert lc.basis_refusal("quantity") is None


def test_a_service_line_takes_no_share():
    # Only goods reach the stock ledger, so a share given to a service line
    # would simply vanish out of the cost.
    db = FakeDB()
    coa = _seed_coa(db)
    good, service = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_good(db, good)
    _seed_service(db, service)
    bill = _bill(
        db,
        [_line(good, taxable=50_000_00, account=coa["Purchases"]),
         _line(service, taxable=50_000_00, account=coa["Purchases"])],
        charges=[{"description": "Freight", "amount_paise": 1_000_00,
                  "expense_account_id": coa["Freight Inward"]}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    ledger = db.rows("inventory_stock_ledger")
    assert len(ledger) == 1
    assert int(ledger[0]["value_delta_paise"]) == 50_000_00 + 1_000_00, (
        "the WHOLE freight goes on the goods line; half of it allocated to the "
        "service line would disappear")


def test_a_bill_with_no_goods_reports_the_charge_rather_than_dropping_it():
    split = lc.apportion([], 5_000_00, basis=lc.BY_VALUE)
    assert split.unapportioned_paise == 5_000_00
    assert split.by_line == {}
    assert any("no stock-tracked goods" in g for g in split.gaps)


def test_lines_that_weigh_nothing_report_rather_than_divide_by_zero():
    zero = [lc.Line("l1", "i1", 0, Decimal(0))]
    for basis in lc.BASES:
        split = lc.apportion(zero, 1_000_00, basis=basis)
        assert split.unapportioned_paise == 1_000_00
        assert split.gaps


def test_the_quantity_basis_says_it_cannot_see_a_unit():
    # purchase_bill_lines has no UQC, so a bill mixing kilograms and pieces is
    # split on a total that means nothing and nothing here can detect it.
    split = lc.apportion([CHAIRS, TABLES], 1000, basis=lc.BY_QUANTITY)
    assert any("unit of measure" in n for n in split.notes)
    assert not lc.apportion([CHAIRS], 1000, basis=lc.BY_VALUE).notes


def test_freight_outward_is_named_as_not_belonging_here():
    assert "13(d)" in lc.FREIGHT_OUTWARD_IS_NOT_COST
    assert "outward" in lc.FREIGHT_OUTWARD_IS_NOT_COST.lower()


# ── 5. applied_at is the boundary ───────────────────────────────────────────

def test_a_charge_is_stamped_once_the_receipt_has_posted():
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])],
                 charges=[{"description": "Freight", "amount_paise": 5_000_00,
                           "expense_account_id": coa["Freight Inward"]}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert db.rows("purchase_bill_landed_costs")[0]["applied_at"]


def test_an_already_applied_charge_is_not_added_twice():
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])],
                 charges=[{"description": "Freight", "amount_paise": 5_000_00,
                           "expense_account_id": coa["Freight Inward"],
                           "applied_at": "2026-04-01T00:00:00Z"}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert int(db.rows("inventory_stock_ledger")[0]["value_delta_paise"]) == 100_000_00


def test_a_charge_that_could_not_be_split_stays_unapplied():
    # It keeps being reported rather than being marked done and forgotten.
    db = FakeDB()
    coa = _seed_coa(db)
    service = str(uuid.uuid4())
    _seed_service(db, service)
    bill = _bill(db, [_line(service, taxable=50_000_00, account=coa["Purchases"])],
                 charges=[{"description": "Freight", "amount_paise": 1_000_00,
                           "expense_account_id": coa["Freight Inward"]}])
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert db.rows("purchase_bill_landed_costs")[0]["applied_at"] is None


def test_the_preview_covers_the_charges_STILL_TO_COME_only():
    # An applied charge is already in the stock ledger and in a posted
    # journal. Showing it again as "will be added" invites the CA to expect
    # it twice — and it is the figure they check the receipt against.
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])],
                 charges=[{"description": "Freight, already received",
                           "amount_paise": 5_000_00,
                           "expense_account_id": coa["Freight Inward"],
                           "applied_at": "2026-04-01T00:00:00Z"},
                          {"description": "Insurance, recorded since",
                           "amount_paise": 1_000_00,
                           "expense_account_id": coa["Freight Inward"]}])
    db.seed("purchase_bills", {**bill, "firm_id": FIRM, "status": "received"})
    preview = svc.read_for_bill(db, firm_id=FIRM, client_id=CLIENT, bill_id=bill["id"])

    assert preview["total_paise"] == 1_000_00, (
        "the split is over what is still to come, not over everything recorded")
    assert sum(l["landed_cost_paise"] for l in preview["lines"]) == 1_000_00
    # BOTH are still LISTED — the applied one is the working, and dropping it
    # would make the charges column disagree with the ledger.
    assert len(preview["charges"]) == 2
    applied = [c for c in preview["charges"] if c["is_applied"]]
    assert len(applied) == 1 and applied[0]["why_not_in_cost"] is None
    late = [c for c in preview["charges"] if not c["is_applied"]][0]
    assert late["why_not_in_cost"], (
        "a charge recorded after the receipt has to say it is not in the cost")


def test_the_sentence_a_late_charge_carries_says_what_to_do():
    assert "posted" in lc.RECORDED_AFTER_THE_RECEIPT
    assert "reverse" in lc.RECORDED_AFTER_THE_RECEIPT.lower()


def test_an_applied_charge_cannot_be_deleted():
    db = FakeDB()
    row = db.seed("purchase_bill_landed_costs", {
        "firm_id": FIRM, "client_id": CLIENT, "bill_id": "b1",
        "description": "Freight", "amount_paise": 1000, "source": "manual",
        "applied_at": "2026-04-01T00:00:00Z"})
    out = svc.remove_charge(db, firm_id=FIRM, charge_id=row["id"])
    assert out["ok"] is False
    assert "posted" in out["refusal"]
    assert db.rows("purchase_bill_landed_costs"), "nothing was deleted"


def test_an_unapplied_charge_can_be_deleted():
    db = FakeDB()
    row = db.seed("purchase_bill_landed_costs", {
        "firm_id": FIRM, "client_id": CLIENT, "bill_id": "b1",
        "description": "Freight", "amount_paise": 1000, "source": "manual",
        "applied_at": None})
    assert svc.remove_charge(db, firm_id=FIRM, charge_id=row["id"])["ok"] is True


def test_another_firms_charge_is_not_deletable():
    db = FakeDB()
    row = db.seed("purchase_bill_landed_costs", {
        "firm_id": "firm-2", "client_id": CLIENT, "bill_id": "b1",
        "description": "Freight", "amount_paise": 1000, "source": "manual",
        "applied_at": None})
    out = svc.remove_charge(db, firm_id=FIRM, charge_id=row["id"])
    assert out["ok"] is False and "not in this firm" in out["refusal"]


def test_a_charge_on_ANOTHER_bill_is_not_deletable_through_this_door():
    # The router resolves the bill's own client before it gets here, so the
    # bill is the scope that was actually checked — a charge id guessed from a
    # different bill must not ride in on it.
    db = FakeDB()
    row = db.seed("purchase_bill_landed_costs", {
        "firm_id": FIRM, "client_id": CLIENT, "bill_id": "b-other",
        "description": "Freight", "amount_paise": 1000, "source": "manual",
        "applied_at": None})
    out = svc.remove_charge(db, firm_id=FIRM, charge_id=row["id"], bill_id="b1")
    assert out["ok"] is False
    assert len(db.rows("purchase_bill_landed_costs")) == 1, "nothing was deleted"


# ── 6. the Bill of Entry carry-over ─────────────────────────────────────────

def _boe(db, *, bill_id, bcd=0, swc=0, other=0, be_id=None):
    return db.seed("bills_of_entry", {
        "id": be_id or str(uuid.uuid4()),
        "firm_id": FIRM, "client_id": CLIENT, "be_number": "BE-1",
        "be_date": "2026-04-02", "purchase_bill_id": bill_id,
        "assessable_value_paise": 100_000_00,
        "basic_customs_duty_paise": bcd, "social_welfare_surcharge_paise": swc,
        "other_duty_paise": other, "igst_paise": 18_000_00, "cess_paise": 0,
        "ineligible_igst_paise": 0, "ineligible_cess_paise": 0,
        "duty_expense_account_id": "acct-customs"})


def test_the_non_creditable_duty_becomes_a_landed_cost_on_the_linked_bill():
    db = FakeDB()
    row = _boe(db, bill_id="bill-1", bcd=10_000_00, swc=1_000_00)
    out = svc.carry_over_from_bill_of_entry(db, firm_id=FIRM, row=row, actor_id=None)
    assert out and out["amount_paise"] == 11_000_00, (
        "basic customs duty and the social welfare surcharge are recoverable "
        "from nobody, so AS-2 par. 6 makes them cost")
    stored = db.rows("purchase_bill_landed_costs")[0]
    assert stored["source"] == "bill_of_entry"
    assert stored["expense_account_id"] == "acct-customs", (
        "the duty already landed on that account and the receipt relieves it")


def test_BOTH_bill_of_entry_doors_carry_the_duty_over():
    """Create AND correct, asserted on the AST rather than on a substring.

    The create path calling it and the PATCH path not is the shape this
    repository keeps having to undo — the attachment validator (ACC-25), the
    GSTIN check on create but not on edit (GST-29). A correction that raises
    the basic customs duty raises what the goods cost, and a charge nobody
    restated is silently the old figure.

    A source SCAN rather than a call, because the create and update handlers
    reach the live Supabase client and cannot be exercised in mock mode; an
    AST walk cannot be satisfied by the comment above either door explaining
    what it does.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "routers" / "bills_of_entry.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    called_in = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "carry_over_from_bill_of_entry"):
                called_in.add(node.name)
    assert "create_bill_of_entry" in called_in, (
        "a Bill of Entry recording non-creditable duty must put it in the cost "
        "of the goods (AS-2 par. 6)")
    assert "update_bill_of_entry" in called_in, (
        "correcting the duty must restate the landed cost — the service "
        "already refuses to touch an applied one")


def test_a_bill_of_entry_with_no_linked_bill_carries_nothing_over():
    # The column is nullable because the duty is owed to customs whether or not
    # the supplier's invoice has been entered. Inventing a link would attach a
    # duty to goods nobody said it was for.
    db = FakeDB()
    row = _boe(db, bill_id=None, bcd=10_000_00)
    assert svc.carry_over_from_bill_of_entry(db, firm_id=FIRM, row=row, actor_id=None) is None
    assert not db.rows("purchase_bill_landed_costs")


def test_a_bill_of_entry_with_no_duty_carries_nothing_over():
    db = FakeDB()
    row = _boe(db, bill_id="bill-1", bcd=0, swc=0, other=0)
    assert svc.carry_over_from_bill_of_entry(db, firm_id=FIRM, row=row, actor_id=None) is None
    assert not db.rows("purchase_bill_landed_costs")


def test_editing_a_bill_of_entry_restates_rather_than_duplicating():
    db = FakeDB()
    row = _boe(db, bill_id="bill-1", bcd=10_000_00, be_id="be-1")
    svc.carry_over_from_bill_of_entry(db, firm_id=FIRM, row=row, actor_id=None)
    row["basic_customs_duty_paise"] = 12_000_00
    svc.carry_over_from_bill_of_entry(db, firm_id=FIRM, row=row, actor_id=None)
    rows = db.rows("purchase_bill_landed_costs")
    assert len(rows) == 1, "UNIQUE (bill_id, bill_of_entry_id) says one"
    assert rows[0]["amount_paise"] == 12_000_00


def test_the_customs_duty_reaches_the_cost_of_the_goods_end_to_end():
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=100_000_00, account=coa["Purchases"])])
    boe = _boe(db, bill_id=bill["id"], bcd=10_000_00, swc=1_000_00)
    boe["duty_expense_account_id"] = coa["Customs Duty"]
    svc.carry_over_from_bill_of_entry(db, firm_id=FIRM, row=boe, actor_id=None)
    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)

    assert account_balance(db, coa["inventory"]) == 100_000_00 + 11_000_00
    assert account_balance(db, coa["Customs Duty"]) == -11_000_00, (
        "migration 389 posted the duty to this account; the receipt relieves it")


# ── the service's own reads ─────────────────────────────────────────────────

def test_the_preview_is_what_the_receipt_will_do():
    db = FakeDB()
    coa = _seed_coa(db)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_good(db, a)
    _seed_good(db, b)
    bill = _bill(
        db,
        [_line(a, taxable=40_000_00, qty="200", account=coa["Purchases"]),
         _line(b, taxable=100_000_00, qty="20", account=coa["Purchases"])],
        charges=[{"description": "Freight", "amount_paise": 50_000_00,
                  "expense_account_id": coa["Freight Inward"]}])
    db.seed("purchase_bills", {"id": bill["id"], "firm_id": FIRM,
                               "client_id": CLIENT, "bill_no": "BILL-1",
                               "status": "draft", "landed_cost_basis": None})
    preview = svc.read_for_bill(db, firm_id=FIRM, client_id=CLIENT, bill_id=bill["id"])
    shown = {l["line_id"]: l["landed_cost_paise"] for l in preview["lines"]}

    apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert sum(shown.values()) == 50_000_00
    ledger = {r["service_catalogue_id"]: int(r["value_delta_paise"])
              for r in db.rows("inventory_stock_ledger")}
    assert ledger[a] == 40_000_00 + 14_285_71
    assert ledger[b] == 100_000_00 + 35_714_29
    assert sorted(shown.values()) == sorted([14_285_71, 35_714_29]), (
        "what the CA is shown before receiving is what gets posted")


def test_the_answer_carries_every_field_the_screen_renders():
    """The panel decides nothing, so anything it renders has to arrive.

    Written as the KEYS rather than as one example, because a field silently
    dropped on the way out reads on the screen as a blank rather than as an
    error — which is how a CA comes to believe there is no freight on a
    consignment that carried some.
    """
    db = FakeDB()
    coa = _seed_coa(db)
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=10_000_00, qty="5",
                            account=coa["Purchases"])],
                 charges=[{"description": "Clearing agent", "amount_paise": 2_500_00,
                           "expense_account_id": coa["Freight Inward"]}])
    db.seed("purchase_bills", {**bill, "firm_id": FIRM, "status": "draft"})
    out = svc.read_for_bill(db, firm_id=FIRM, client_id=CLIENT, bill_id=bill["id"])

    for key in ("basis", "basis_label", "bases", "client_basis", "bill_basis",
                "basis_is_recorded", "charges", "lines", "total_paise",
                "unapportioned_paise", "gaps", "notes",
                "weight_and_volume_refused", "freight_outward_is_not_cost"):
        assert key in out, f"the screen renders {key} and nothing sent it"

    # The two basis OPTIONS come from here, values and labels both — a
    # hardcoded pair in the browser is how the Schedule III caption screen
    # came to offer five captions the classifier had never heard of.
    assert [b["value"] for b in out["bases"]] == list(lc.BASES)
    assert all(b["label"] for b in out["bases"])

    charge = out["charges"][0]
    assert charge["description"] == "Clearing agent"
    assert charge["amount_paise"] == 2_500_00
    for key in ("id", "source", "is_applied", "why_not_in_cost"):
        assert key in charge, f"the charges table renders {key}"

    line = out["lines"][0]
    assert line["item_name"], "the preview names the item, not just its id"
    assert line["quantity"] == "5"
    assert line["own_cost_paise"] == 10_000_00
    assert line["landed_cost_paise"] == 2_500_00
    assert line["total_cost_paise"] == 12_500_00, (
        "the screen renders the total rather than adding the two up itself")


def test_the_read_says_whether_a_basis_was_CHOSEN():
    db = FakeDB()
    item = str(uuid.uuid4())
    _seed_good(db, item)
    bill = _bill(db, [_line(item, taxable=1000)])
    db.seed("purchase_bills", {"id": bill["id"], "firm_id": FIRM,
                               "client_id": CLIENT, "status": "draft",
                               "landed_cost_basis": None})
    out = svc.read_for_bill(db, firm_id=FIRM, client_id=CLIENT, bill_id=bill["id"])
    assert out["basis"] == lc.BY_VALUE
    assert out["basis_is_recorded"] is False
    assert any("accounting policy" in n for n in out["notes"])


def test_a_bill_in_another_firm_is_not_read():
    db = FakeDB()
    db.seed("purchase_bills", {"id": "b9", "firm_id": "firm-2",
                               "client_id": CLIENT, "status": "draft"})
    out = svc.read_for_bill(db, firm_id=FIRM, client_id=CLIENT, bill_id="b9")
    assert out["found"] is False


def test_a_clients_basis_is_not_cleared_once_recorded():
    db = FakeDB()
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "landed_cost_basis": "value"})
    out = svc.set_basis(db, firm_id=FIRM, client_id=CLIENT, basis=None)
    assert out["ok"] is False and "accounting policy" in out["refusal"]


def test_a_bill_override_CAN_be_cleared():
    db = FakeDB()
    db.seed("purchase_bills", {"id": "b1", "firm_id": FIRM, "client_id": CLIENT,
                               "landed_cost_basis": "quantity"})
    out = svc.set_basis(db, firm_id=FIRM, client_id=CLIENT, basis=None, bill_id="b1")
    assert out["ok"] is True
    assert db.rows("purchase_bills")[0]["landed_cost_basis"] is None


def test_setting_a_basis_the_standard_does_not_offer_is_refused():
    db = FakeDB()
    out = svc.set_basis(db, firm_id=FIRM, client_id=CLIENT, basis="weight")
    assert out["ok"] is False and "weight" in out["refusal"].lower()


def test_EVERY_read_and_write_in_the_service_carries_the_firm_filter():
    """The service-role key bypasses RLS, so the app-layer filter is the
    isolation control (CLAUDE.md). `purchase_bill_lines` has no `firm_id` and
    is scoped through its parent bill, which `read_for_bill` reads first."""
    import ast
    import inspect
    SCOPED_THROUGH_A_PARENT = {"purchase_bill_lines", "service_catalogue"}
    tree = ast.parse(inspect.getsource(svc))
    unscoped = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = ast.unparse(node)
        if ".table(" not in chain or ".execute()" not in chain:
            continue
        table = None
        for n in ast.walk(node):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "table" and n.args
                    and isinstance(n.args[0], ast.Constant)):
                table = n.args[0].value
        if table in SCOPED_THROUGH_A_PARENT:
            continue
        if ".insert(" in chain:
            scoped = "'firm_id'" in chain or '"firm_id"' in chain
        else:
            scoped = "eq('firm_id'" in chain or 'eq("firm_id"' in chain
        if not scoped:
            unscoped.append(f"{table}: {chain[:110]}")
    assert not unscoped, (
        "these omit the tenant filter:\n  " + "\n  ".join(unscoped))
