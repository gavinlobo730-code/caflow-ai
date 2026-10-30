"""A document may only name a row of its own client, and a read that fails on a permission or money path does not answer "nothing" (POST-A-338, POST-A-342; 28-10-2026).

POST-A-338. A Bill of Entry carries a vendor and a purchase bill, a fixed asset the bill it was bought on, a delivery challan an order, a
customer, a vendor and an invoice, an order the party. The API reads and writes through the privileged client by firm and id and the
foreign key on each column is not client-aware, so an id of a SIBLING client of the same firm was accepted. The worst case: client A's Bill
of Entry naming client B's purchase bill attached A's customs duty to B's bill and so to B's stock cost.

POST-A-342. `delete_rule` counted the lines a rule posted inside `except Exception: posted = 0`, and that count decides whether an Executive
may delete the rule, so an unreadable count let the deletion through exactly where it is meant to be refused; the two foreign-bank reads of
the revaluation and the FX report answered an empty list on any error and so skipped the foreign accounts without saying so.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from fastapi import HTTPException

import routers.banking as bank
import routers.bills_of_entry as boe_router
import routers.credit_notes as credit_notes
import routers.cwip as cwip_router
import routers.debit_notes as debit_notes
import routers.fixed_assets as fa
import routers.purchase_bills as pb
import routers.purchase_credit_notes as purchase_credit_notes
import routers.sales_debit_notes as sales_debit_notes
import routers.sales_invoices as sales_invoices
from models.accounting import FixedAssetIn
from services import itc_register_service as itc
from services import landed_cost_service as lcs
from services import named_row_ownership as nro
from services import purchase_cycle_service as pcs
from services import sales_cycle_service as scs
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
OTHER_FIRM = "99999999-9999-9999-9999-999999999999"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}
EXEC = {"id": "u2", "firm_id": FIRM, "auth_user_id": "au2", "role": "Executive", "email": "e@example.test",
        "assigned_client_ids": [A, B]}
MANAGER = {**EXEC, "id": "u3", "role": "Manager", "email": "m@example.test"}


def _world() -> FakeDB:
    """Client A and client B of one firm, each with a vendor, a customer, a purchase bill, a sales order and a purchase order."""
    db = FakeDB()
    for client, tag in ((A, "a"), (B, "b")):
        db.seed("clients", {"id": client, "firm_id": FIRM, "financial_year_start": "2025-04-01", "landed_cost_basis": None})
        db.seed("vendors", {"id": f"vendor-{tag}", "firm_id": FIRM, "client_id": client})
        db.seed("customers", {"id": f"customer-{tag}", "firm_id": FIRM, "client_id": client})
        db.seed("purchase_bills", {"id": f"bill-{tag}", "firm_id": FIRM, "client_id": client, "bill_no": f"B-{tag}", "status": "draft"})
        db.seed("sales_orders", {"id": f"sorder-{tag}", "firm_id": FIRM, "client_id": client, "customer_id": f"customer-{tag}",
                                 "document_no": f"SO/{tag}", "document_date": "2026-04-01", "status": "confirmed"})
        db.seed("purchase_orders", {"id": f"porder-{tag}", "firm_id": FIRM, "client_id": client, "vendor_id": f"vendor-{tag}",
                                    "document_no": f"PO/{tag}", "document_date": "2026-04-01", "status": "approved"})
        db.seed("client_sales_invoices", {"id": f"invoice-{tag}", "firm_id": FIRM, "client_id": client})
        db.seed("bank_accounts", {"id": f"bank-{tag}", "firm_id": FIRM, "client_id": client})
        db.seed("sales_quotations", {"id": f"quote-{tag}", "firm_id": FIRM, "client_id": client, "customer_id": f"customer-{tag}",
                                     "document_no": f"QT/{tag}", "document_date": "2026-04-01", "status": "sent"})
    return db


# ── the rule itself ────────────────────────────────────────────────────────────────────────────────────────────────────
RULES = [
    ("vendor", nro.vendor_is_the_clients, "vendor-a", "vendor-b", "That vendor was not found."),
    ("customer", nro.customer_is_the_clients, "customer-a", "customer-b", "That customer was not found."),
    ("bill", nro.purchase_bill_is_the_clients, "bill-a", "bill-b", "That bill was not found."),
    ("invoice", nro.sales_invoice_is_the_clients, "invoice-a", "invoice-b", "That invoice was not found."),
    ("bank account", nro.bank_account_is_the_clients, "bank-a", "bank-b", "That bank account was not found."),
]


@pytest.mark.parametrize("name,rule,own,sibling,words", RULES, ids=[r[0] for r in RULES])
def test_a_row_of_the_clients_own_is_found(name, rule, own, sibling, words):
    assert rule(_world(), FIRM, A, own) is None


@pytest.mark.parametrize("name,rule,own,sibling,words", RULES, ids=[r[0] for r in RULES])
def test_a_sibling_clients_row_a_other_firms_row_and_an_invented_one_say_the_same_words(name, rule, own, sibling, words):
    db = _world()
    for who, firm, row in (("sibling", FIRM, sibling), ("other firm", OTHER_FIRM, own), ("invented", FIRM, "no-such-row")):
        with pytest.raises(HTTPException) as e:
            rule(db, firm, A, row)
        assert (e.value.status_code, e.value.detail) == (404, words), who


@pytest.mark.parametrize("name,rule,own,sibling,words", RULES, ids=[r[0] for r in RULES])
def test_nothing_named_asks_nothing_and_neither_does_a_missing_database(name, rule, own, sibling, words):
    class _Never:
        def table(self, *_):
            raise AssertionError("a read was made although no row was named")

    for named in (None, "", "   "):
        assert rule(_Never(), FIRM, A, named) is None
    assert rule(None, FIRM, A, sibling) is None


# ── a Bill of Entry ────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def boe(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [boe_router])
    monkeypatch.setattr(boe_router, "_mock_enabled", lambda: False)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _boe_in(**kw):
    base = dict(client_id=A, be_number="BE-1", be_date="2026-04-10", basic_customs_duty_paise=10_000_00, igst_paise=18_000_00,
                assessable_value_paise=1_00_000_00, duty_expense_account_id="acct-customs")
    return boe_router.BillOfEntryIn(**{**base, **kw})


def test_a_bill_of_entry_naming_a_sibling_clients_bill_is_refused_and_attaches_no_duty_to_it(boe):
    with pytest.raises(HTTPException) as e:
        boe_router.create_bill_of_entry(_boe_in(purchase_bill_id="bill-b"), USER)
    assert (e.value.status_code, e.value.detail) == (404, "That bill was not found.")
    assert boe.rows("bills_of_entry") == [] and boe.rows("purchase_bill_landed_costs") == []


def test_a_bill_of_entry_naming_a_sibling_clients_vendor_is_refused(boe):
    with pytest.raises(HTTPException) as e:
        boe_router.create_bill_of_entry(_boe_in(vendor_id="vendor-b"), USER)
    assert (e.value.status_code, e.value.detail) == (404, "That vendor was not found.")
    assert boe.rows("bills_of_entry") == []


def test_a_bill_of_entry_naming_the_clients_own_bill_and_vendor_still_carries_its_duty_over(boe):
    out = boe_router.create_bill_of_entry(_boe_in(purchase_bill_id="bill-a", vendor_id="vendor-a"), USER)
    assert out["success"] is True
    charges = boe.rows("purchase_bill_landed_costs")
    assert [(c["bill_id"], c["client_id"], c["amount_paise"]) for c in charges] == [("bill-a", A, 10_000_00)]


def test_a_correction_cannot_re_point_a_bill_of_entry_at_a_sibling_clients_bill_or_vendor(boe):
    created = boe_router.create_bill_of_entry(_boe_in(purchase_bill_id="bill-a"), USER)["data"]
    before = [dict(r) for r in boe.rows("bills_of_entry")]
    for field, value, words in (("purchase_bill_id", "bill-b", "That bill was not found."),
                                ("vendor_id", "vendor-b", "That vendor was not found.")):
        with pytest.raises(HTTPException) as e:
            boe_router.update_bill_of_entry(created["id"], boe_router.BillOfEntryUpdateIn(**{field: value}), client_id=A, current_user=USER)
        assert (e.value.status_code, e.value.detail) == (404, words), field
    assert [dict(r) for r in boe.rows("bills_of_entry")] == before
    assert [c["bill_id"] for c in boe.rows("purchase_bill_landed_costs")] == ["bill-a"]


def test_a_correction_that_changes_neither_id_asks_nothing_about_them(boe):
    """A row written before the check that already names a sibling's bill can still have its notes corrected: only what the request
    CHANGES is asked."""
    created = boe_router.create_bill_of_entry(_boe_in(), USER)["data"]
    boe.rows("bills_of_entry")[0]["purchase_bill_id"] = "bill-b"          # the legacy shape
    out = boe_router.update_bill_of_entry(created["id"], boe_router.BillOfEntryUpdateIn(notes="corrected"), client_id=A, current_user=USER)
    assert out["success"] is True and boe.rows("bills_of_entry")[0]["notes"] == "corrected"
    assert boe.rows("purchase_bill_landed_costs") == [], "and the carry-over still refuses to charge client B's bill"


def test_the_carry_over_reads_the_bill_by_client_whatever_the_route_asked(boe):
    row = boe.seed("bills_of_entry", {"id": "boe-1", "firm_id": FIRM, "client_id": A, "be_number": "BE-9", "be_date": "2026-04-10",
                                      "purchase_bill_id": "bill-b", "basic_customs_duty_paise": 5_000_00, "assessable_value_paise": 1,
                                      "igst_paise": 0, "cess_paise": 0, "ineligible_igst_paise": 0, "ineligible_cess_paise": 0})
    assert lcs.carry_over_from_bill_of_entry(boe, firm_id=FIRM, row=row, actor_id=None) is None
    assert boe.rows("purchase_bill_landed_costs") == []
    row["purchase_bill_id"] = "bill-a"
    assert lcs.carry_over_from_bill_of_entry(boe, firm_id=FIRM, row=row, actor_id=None)["amount_paise"] == 5_000_00


# ── a charge against a bill ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def bills(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [pb])
    monkeypatch.setattr(pb, "_USE_MOCK", False)
    return db


def test_a_charge_cannot_be_recorded_under_one_client_against_anothers_bill(bills):
    body = pb.LandedCostIn(client_id=A, description="Freight", amount_paise=1_000_00)
    with pytest.raises(HTTPException) as e:
        pb.add_landed_cost("bill-b", body, USER)
    assert (e.value.status_code, e.value.detail) == (404, "Purchase bill bill-b not found")
    assert bills.rows("purchase_bill_landed_costs") == []
    assert pb.add_landed_cost("bill-a", body, USER)["success"] is True
    assert [(c["bill_id"], c["client_id"]) for c in bills.rows("purchase_bill_landed_costs")] == [("bill-a", A)]


def test_a_bills_landed_cost_basis_override_is_the_bills_own_clients(bills):
    with pytest.raises(HTTPException) as e:
        pb.put_landed_cost_basis(pb.LandedCostBasisIn(client_id=A, bill_id="bill-b", basis="value"), USER)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        pb.put_landed_cost_basis(pb.LandedCostBasisIn(client_id=A, bill_id="no-such-bill", basis="value"), USER)
    assert e.value.status_code == 404, "an invented bill was answered as a success that changed nothing"
    assert pb.put_landed_cost_basis(pb.LandedCostBasisIn(client_id=A, bill_id="bill-a", basis="value"), USER)["success"] is True
    assert {r["id"]: r.get("landed_cost_basis") for r in bills.rows("purchase_bills")} == {"bill-a": "value", "bill-b": None}


# ── a fixed asset ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def assets(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [fa])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("firms", {"id": FIRM, "name": "Test & Co", "locked_financial_years": []})
    seed_standard_coa(db, FIRM, A)
    for name in ("Plant & Machinery", "Depreciation Expense", "Accumulated Depreciation"):
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": A, "account_name": name, "account_code": f"FA{abs(hash(name)) % 9000 + 1000}",
                                      "account_type": "Expense" if name == "Depreciation Expense" else "Asset", "is_active": True})
    return db


def _asset_in(**kw):
    return FixedAssetIn(client_id=A, asset_name="Lathe", asset_category="Plant & Machinery", purchase_date="2025-04-05",
                        purchase_cost_paise=1_50_000_00, useful_life_years=15, acquisition_mode="paid", **kw)


def test_an_asset_cannot_be_capitalised_from_a_sibling_clients_bill_or_vendor(assets):
    for field, value, words in (("purchase_bill_id", "bill-b", "That bill was not found."), ("vendor_id", "vendor-b", "That vendor was not found.")):
        with pytest.raises(HTTPException) as e:
            fa.create_asset(_asset_in(**{field: value}), USER)
        assert (e.value.status_code, e.value.detail) == (404, words), field
    assert assets.rows("fixed_assets") == [] and assets.rows("journal_entries") == []


def test_an_asset_is_still_capitalised_from_the_clients_own_bill_and_vendor(assets):
    out = fa.create_asset(_asset_in(purchase_bill_id="bill-a", vendor_id="vendor-a"), USER)
    assert out["success"] is True, out
    assert [(r["purchase_bill_id"], r["vendor_id"]) for r in assets.rows("fixed_assets")] == [("bill-a", "vendor-a")]


# ── the purchase cycle ─────────────────────────────────────────────────────────────────────────────────────────────────
_LINE = {"description": "Chairs", "quantity": 1, "rate_paise": 1000, "gst_rate_percent": 18}


def test_a_purchase_order_names_a_vendor_of_its_own_client_only():
    db = _world()
    base = {"client_id": A, "document_no": "PO/1", "document_date": "2026-04-01", "lines": [_LINE]}
    with pytest.raises(HTTPException) as e:
        pcs.create_order(db, FIRM, {**base, "vendor_id": "vendor-b"})
    assert (e.value.status_code, e.value.detail) == (404, "That vendor was not found.")
    assert len(db.rows("purchase_orders")) == 2, "only the two seeded orders exist"
    assert pcs.create_order(db, FIRM, {**base, "vendor_id": "vendor-a"})["vendor_id"] == "vendor-a"


def test_a_goods_receipt_names_a_vendor_and_an_order_of_its_own_client_only():
    db = _world()
    base = {"client_id": A, "document_no": "GRN/1", "received_on": "2026-04-05", "lines": []}
    for extra, words in (({"vendor_id": "vendor-b"}, "That vendor was not found."),
                         ({"vendor_id": "vendor-a", "order_id": "porder-b"}, "That purchase order was not found.")):
        with pytest.raises(HTTPException) as e:
            pcs.create_receipt(db, FIRM, {**base, **extra})
        assert (e.value.status_code, e.value.detail) == (404, words)
    assert db.rows("goods_receipt_notes") == []


def test_a_bill_that_names_a_sibling_clients_order_does_not_match_against_it():
    db = _world()
    db.rows("purchase_bills")[0]["purchase_order_id"] = "porder-b"        # bill-a names client B's order
    with pytest.raises(HTTPException) as e:
        pcs.match_bill(db, FIRM, "bill-a")
    assert (e.value.status_code, e.value.detail) == (404, "That purchase order was not found.")
    db.rows("purchase_bills")[0]["purchase_order_id"] = "porder-a"
    assert pcs.match_bill(db, FIRM, "bill-a")["bill_id"] == "bill-a"


# ── the sales cycle ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_quotation_and_a_sales_order_name_a_customer_of_their_own_client_only():
    db = _world()
    base = {"client_id": A, "document_date": "2026-04-01", "lines": [_LINE]}
    for fn, document_no in ((scs.create_quotation, "QT/1"), (scs.create_order, "SO/1")):
        with pytest.raises(HTTPException) as e:
            fn(db, FIRM, {**base, "document_no": document_no, "customer_id": "customer-b"})
        assert (e.value.status_code, e.value.detail) == (404, "That customer was not found.")
        assert fn(db, FIRM, {**base, "document_no": document_no, "customer_id": "customer-a"})["customer_id"] == "customer-a"


def test_a_delivery_challan_names_only_rows_of_its_own_client():
    db = _world()
    base = {"client_id": A, "document_no": "DC/1", "document_date": "2026-04-05", "reason": "invoice_to_follow", "lines": [_LINE]}
    for extra, words in (({"customer_id": "customer-b"}, "That customer was not found."),
                         ({"vendor_id": "vendor-b"}, "That vendor was not found."),
                         ({"sales_invoice_id": "invoice-b"}, "That invoice was not found."),
                         ({"order_id": "sorder-b"}, "That sales order was not found.")):
        with pytest.raises(HTTPException) as e:
            scs.create_challan(db, FIRM, {**base, **extra})
        assert (e.value.status_code, e.value.detail) == (404, words), extra
    assert db.rows("delivery_challans") == []
    own = scs.create_challan(db, FIRM, {**base, "customer_id": "customer-a", "sales_invoice_id": "invoice-a", "order_id": "sorder-a"})
    assert (own["customer_id"], own["order_id"]) == ("customer-a", "sorder-a")


def test_a_challan_cannot_be_re_pointed_at_a_sibling_clients_invoice():
    db = _world()
    challan = scs.create_challan(db, FIRM, {"client_id": A, "document_no": "DC/2", "document_date": "2026-04-05",
                                            "reason": "invoice_to_follow", "lines": [_LINE]})
    with pytest.raises(HTTPException) as e:
        scs.update_challan(db, FIRM, challan["id"], {"sales_invoice_id": "invoice-b"})
    assert (e.value.status_code, e.value.detail) == (404, "That invoice was not found.")
    assert scs.update_challan(db, FIRM, challan["id"], {"sales_invoice_id": "invoice-a"})["sales_invoice_id"] == "invoice-a"


# ── the shape is a rule, not a list of doors ───────────────────────────────────────────────────────────────────────────
def _lines_of(fn, predicate) -> list[int]:
    """The source lines (inside `fn`) of every call that `predicate(called_name, call_node)` accepts."""
    out = []
    for node in ast.walk(ast.parse(inspect.getsource(fn))):
        if isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if called and predicate(called, node):
                out.append(node.lineno)
    return sorted(out)


def _is_a_write(called: str, node: ast.Call) -> bool:
    """A database write: `insert_numbered_document_with_lines`, or `.insert/.update/.delete/.upsert` on a chain that starts at
    `.table(...)` (a plain dict's `.update` is not one)."""
    if called == "insert_numbered_document_with_lines":
        return True
    if called not in {"insert", "update", "delete", "upsert"} or not isinstance(node.func, ast.Attribute):
        return False
    probe = node.func.value
    while isinstance(probe, (ast.Call, ast.Attribute)):
        if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute) and probe.func.attr == "table":
            return True
        probe = probe.func.value if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute) else getattr(probe, "value", None)
    return False


_ASKS = {"vendor_is_the_clients", "customer_is_the_clients", "purchase_bill_is_the_clients", "sales_invoice_is_the_clients",
         "bank_account_is_the_clients", "order_of_client", "row_of_client"}


@pytest.mark.parametrize("fn,asked", [
    (fa.create_asset, {"purchase_bill_is_the_clients", "vendor_is_the_clients", "bank_account_is_the_clients"}),
    (fa.correct_asset, {"purchase_bill_is_the_clients", "vendor_is_the_clients", "bank_account_is_the_clients"}),
    (boe_router.create_bill_of_entry, {"purchase_bill_is_the_clients", "vendor_is_the_clients"}),
    (boe_router.update_bill_of_entry, {"purchase_bill_is_the_clients", "vendor_is_the_clients"}),
    (cwip_router.add_cost, {"purchase_bill_is_the_clients", "vendor_is_the_clients", "bank_account_is_the_clients"}),
    (itc.record_reversal, {"purchase_bill_is_the_clients"}),
    (pcs.create_order, {"vendor_is_the_clients"}),
    (pcs.create_receipt, {"vendor_is_the_clients", "order_of_client"}),
    (pcs.match_bill, {"order_of_client"}),
    (scs.create_quotation, {"customer_is_the_clients"}),
    (scs.create_order, {"customer_is_the_clients", "row_of_client"}),
    (scs.create_challan, {"customer_is_the_clients", "vendor_is_the_clients", "sales_invoice_is_the_clients", "row_of_client"}),
    (scs.update_challan, {"sales_invoice_is_the_clients"}),
    (sales_invoices.update_invoice, {"customer_is_the_clients"}),
    (credit_notes.create_credit_note, {"customer_is_the_clients"}),
    (credit_notes.update_credit_note, {"customer_is_the_clients"}),
    (debit_notes.create_debit_note, {"vendor_is_the_clients"}),
    (debit_notes.update_debit_note, {"vendor_is_the_clients"}),
    (purchase_credit_notes.create_purchase_credit_note, {"vendor_is_the_clients"}),
    (purchase_credit_notes.update_purchase_credit_note, {"vendor_is_the_clients"}),
    (sales_debit_notes.create_sales_debit_note, {"customer_is_the_clients"}),
    (sales_debit_notes.update_sales_debit_note, {"customer_is_the_clients"}),
])
def test_every_door_that_takes_a_named_row_in_its_body_asks_whose_it_is_before_it_writes(fn, asked):
    """A hand-written list of the doors this change covers, and honest about it: it cannot find a NEW door (the ledger holds the
    derived rule). What it does hold is the shape of each listed door: every id it should ask IS asked, and the first ask comes
    BEFORE the first write in the same function, so a check moved below the insert, or into a dead branch, fails here."""
    called_names = {n for n in _ASKS if _lines_of(fn, lambda c, _n, n=n: c == n)}
    missing = asked - called_names
    assert not missing, f"{fn.__module__}.{fn.__name__} does not ask {sorted(missing)}"
    asks = _lines_of(fn, lambda c, _n: c in asked)
    writes = _lines_of(fn, _is_a_write)
    if writes and fn not in {pcs.match_bill}:
        assert min(asks) < min(writes), f"{fn.__module__}.{fn.__name__} writes (line {min(writes)}) before it first asks (line {min(asks)})"


def test_the_ownership_module_reads_each_table_by_a_literal_name():
    """A table read through a variable is invisible to the column check, which resolves no name."""
    tree = ast.parse(pathlib.Path(nro.__file__).read_text(encoding="utf-8"))
    tables = [n.args[0] for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "table"]
    assert len(tables) == 7 and all(isinstance(t, ast.Constant) and isinstance(t.value, str) for t in tables)


# ── POST-A-342: a count that cannot be read is not zero ────────────────────────────────────────────────────────────────
class _CountFails:
    """A database whose count of the lines a rule posted cannot be taken, over the rule rows of the world."""

    def __init__(self, inner, fails=True):
        self.inner, self.fails = inner, fails

    def table(self, name):
        if name == "bank_transactions" and self.fails:
            raise RuntimeError("the database is unreachable")
        return self.inner.table(name)

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


@pytest.fixture
def rule_world(monkeypatch):
    db = FakeDB()
    db.seed("bank_matching_rules", {"id": "RULE-1", "firm_id": FIRM, "client_id": A, "description_pattern": "netflix",
                                    "suggested_account_id": "ACC-1", "is_trusted": True, "trusted_by": "u3"})
    db.seed("bank_transactions", {"id": "TXN-1", "firm_id": FIRM, "client_id": A, "posted_by_rule_id": "RULE-1", "transaction_date": "2026-04-10"})
    wire_e2e(monkeypatch, db, [bank])
    wrapped = _CountFails(db)
    monkeypatch.setattr(bank, "_db", lambda: wrapped)
    monkeypatch.setattr(bank, "privileged_for", lambda d: d)
    seen = []
    monkeypatch.setattr(bank, "log_event", lambda *a, **k: seen.append(k))
    return db, seen


def test_an_executive_cannot_delete_a_rule_whose_posted_lines_cannot_be_counted(rule_world):
    db, seen = rule_world
    with pytest.raises(HTTPException) as e:
        bank.delete_rule("RULE-1", EXEC)
    assert e.value.status_code == 503 and "nothing was deleted" in e.value.detail and "Manager or Partner" in e.value.detail
    assert [r["id"] for r in db.rows("bank_matching_rules")] == ["RULE-1"] and seen == []


def test_someone_who_may_delete_it_whatever_the_count_is_not_held_up_and_the_answer_says_the_count_is_unknown(rule_world):
    db, seen = rule_world
    out = bank.delete_rule("RULE-1", MANAGER)
    assert out["success"] is True and out["data"]["deleted"] is True and out["data"]["posted_lines"] is None
    assert db.rows("bank_matching_rules") == []
    assert seen and seen[0]["old_data"]["posted_lines_at_delete"] is None, "the audit entry says unknown, not none"


def test_a_count_that_can_be_read_still_decides_as_before(rule_world, monkeypatch):
    db, _ = rule_world
    monkeypatch.setattr(bank, "_db", lambda: _CountFails(db, fails=False))
    with pytest.raises(HTTPException) as e:
        bank.delete_rule("RULE-1", EXEC)
    assert e.value.status_code == 403 and "1 bank line " in e.value.detail


# ── POST-A-342: the foreign-bank reads raise ───────────────────────────────────────────────────────────────────────────
class _BankReadFails:
    def table(self, name):
        raise RuntimeError("the database is unreachable")


def test_a_foreign_bank_read_that_fails_is_not_an_empty_list(monkeypatch):
    from domain.currency.fx_revaluation_service import FXRevaluationService
    from services import fx_reporting_service as fxr

    for module in (fxr, __import__("domain.currency.fx_revaluation_service", fromlist=["x"])):
        monkeypatch.setattr(module, "privileged_for", lambda d: d)
    with pytest.raises(RuntimeError):
        FXRevaluationService()._open_bank_balances(_BankReadFails(), FIRM, A, "2026-03-31")
    with pytest.raises(RuntimeError):
        fxr.FXReportingService()._foreign_bank_balances_python(_BankReadFails(), FIRM, A)


def test_no_read_in_the_two_fx_modules_answers_empty_on_any_error():
    for rel in ("domain/currency/fx_revaluation_service.py", "services/fx_reporting_service.py"):
        tree = ast.parse((pathlib.Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and (node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")):
                body = [n for n in node.body if not isinstance(n, ast.Expr)]
                assert not (len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.List)
                            and not body[0].value.elts), f"{rel}:{node.lineno} answers an empty list on any error"


# ── what the independent review of this change found, each with the scenario that reproduced it ──────────────────────────
def test_a_sales_order_cannot_convert_a_sibling_clients_quotation():
    db = _world()
    base = {"client_id": A, "document_no": "SO/9", "document_date": "2026-04-01", "customer_id": "customer-a", "lines": [_LINE]}
    with pytest.raises(HTTPException) as e:
        scs.create_order(db, FIRM, {**base, "quotation_id": "quote-b"})
    assert (e.value.status_code, e.value.detail) == (404, "That quotation was not found.")
    assert {r["id"]: r["status"] for r in db.rows("sales_quotations")} == {"quote-a": "sent", "quote-b": "sent"}
    out = scs.create_order(db, FIRM, {**base, "quotation_id": "quote-a"})
    assert {r["id"]: r["status"] for r in db.rows("sales_quotations")} == {"quote-a": "converted", "quote-b": "sent"}
    assert db.rows("sales_quotations")[0]["converted_to_order_id"] == out["id"]


def test_a_correction_cannot_re_point_a_fixed_asset_at_a_sibling_clients_bill_vendor_or_bank_account(assets):
    asset = fa.create_asset(_asset_in(), USER)["data"]
    before = [dict(r) for r in assets.rows("fixed_assets")]
    for field, value, words in (("purchase_bill_id", "bill-b", "That bill was not found."), ("vendor_id", "vendor-b", "That vendor was not found."),
                                ("bank_account_id", "bank-b", "That bank account was not found.")):
        with pytest.raises(HTTPException) as e:
            fa.correct_asset(asset["id"], fa.FixedAssetUpdateIn(**{field: value}), USER)
        assert (e.value.status_code, e.value.detail) == (404, words), field
    assert [dict(r) for r in assets.rows("fixed_assets")] == before


def test_an_asset_is_refused_a_sibling_clients_bank_account_at_creation_too(assets):
    with pytest.raises(HTTPException) as e:
        fa.create_asset(_asset_in(bank_account_id="bank-b"), USER)
    assert (e.value.status_code, e.value.detail) == (404, "That bank account was not found.")
    assert assets.rows("fixed_assets") == []


def test_a_draft_invoice_cannot_be_re_pointed_at_a_sibling_clients_customer(monkeypatch):
    db = _world()
    db.rows("client_sales_invoices")[0].update({"status": "draft", "invoice_date": "2026-04-01", "customer_id": "customer-a"})
    wire_e2e(monkeypatch, db, [sales_invoices])
    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)
    body = sales_invoices.SalesInvoiceUpdateIn
    with pytest.raises(HTTPException) as e:
        sales_invoices.update_invoice("invoice-a", body(customer_id="customer-b"), USER)
    assert (e.value.status_code, e.value.detail) == (404, "That customer was not found.")
    assert db.rows("client_sales_invoices")[0]["customer_id"] == "customer-a"


_NOTE_LINE = {"description": "Returned goods", "quantity": 1, "rate_paise": 1_000_00, "gst_rate_percent": 18.0,
              "service_catalogue_id": "item-a"}


@pytest.mark.parametrize("module,builder,fn,party,sibling,words", [
    (credit_notes, lambda **kw: credit_notes.CreditNoteIn(**kw), "create_credit_note", "customer_id", "customer-b", "That customer was not found."),
    (debit_notes, lambda **kw: debit_notes.DebitNoteIn(**kw), "create_debit_note", "vendor_id", "vendor-b", "That vendor was not found."),
    (purchase_credit_notes, lambda **kw: purchase_credit_notes.PurchaseCreditNoteIn(**kw), "create_purchase_credit_note", "vendor_id", "vendor-b",
     "That vendor was not found."),
    (sales_debit_notes, lambda **kw: sales_debit_notes.SalesDebitNoteIn(**kw), "create_sales_debit_note", "customer_id", "customer-b",
     "That customer was not found."),
], ids=["credit note", "debit note", "purchase credit note", "sales debit note"])
def test_a_note_names_a_party_of_its_own_client_only(monkeypatch, module, builder, fn, party, sibling, words):
    db = _world()
    db.seed("service_catalogue", {"id": "item-a", "firm_id": FIRM, "client_id": A, "name": "Goods"})
    wire_e2e(monkeypatch, db, [module])
    monkeypatch.setattr(module, "_USE_MOCK", False)
    date_field = "credit_note_date" if module in (credit_notes, purchase_credit_notes) else "debit_note_date"
    with pytest.raises(HTTPException) as e:
        getattr(module, fn)(builder(client_id=A, **{party: sibling}, **{date_field: "2026-04-10"}, lines=[_NOTE_LINE]), USER)
    assert (e.value.status_code, e.value.detail) == (404, words)
    table = {credit_notes: "credit_notes", debit_notes: "debit_notes", purchase_credit_notes: "purchase_credit_notes",
             sales_debit_notes: "sales_debit_notes"}[module]
    assert db.rows(table) == []


def test_a_cwip_cost_names_a_vendor_bill_and_bank_account_of_its_own_client_only(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [cwip_router])
    monkeypatch.setattr(cwip_router, "_mock_enabled", lambda: False)
    monkeypatch.setattr(cwip_router, "_db", lambda: db)
    for field, value, words in (("vendor_id", "vendor-b", "That vendor was not found."), ("purchase_bill_id", "bill-b", "That bill was not found."),
                                ("bank_account_id", "bank-b", "That bank account was not found.")):
        body = cwip_router.CostIn(client_id=A, incurred_on="2026-04-10", description="Civil work", amount_paise=1_000_00, **{field: value})
        with pytest.raises(HTTPException) as e:
            cwip_router.add_cost("cwip-1", body, USER)
        assert (e.value.status_code, e.value.detail) == (404, words), field


def test_an_input_credit_reversal_names_a_bill_of_its_own_client_only(monkeypatch):
    db = _world()
    monkeypatch.setattr(itc, "_posted_journal", lambda *a, **k: {"id": "J-1"})
    with pytest.raises(HTTPException) as e:
        itc.record_reversal(db, FIRM, A, journal_entry_id="J-1", period="042026", reason_code="rule_37",
                            amounts={"igst_paise": 100}, purchase_bill_id="bill-b")
    assert (e.value.status_code, e.value.detail) == (404, "That bill was not found.")


def test_a_line_cannot_name_an_order_line_when_the_document_names_no_order():
    db = _world()
    receipt = {"client_id": A, "document_no": "GRN/7", "received_on": "2026-04-05", "vendor_id": "vendor-a",
               "lines": [{"description": "Chairs", "quantity": 5, "order_line_id": "pol-b"}]}
    with pytest.raises(HTTPException) as e:
        pcs.create_receipt(db, FIRM, receipt)
    assert e.value.status_code == 422 and "names an order line but the receipt names no order" in e.value.detail
    assert db.rows("goods_receipt_notes") == []
    challan = {"client_id": A, "document_no": "DC/7", "document_date": "2026-04-05", "reason": "invoice_to_follow",
               "lines": [{**_LINE, "order_line_id": "sol-b"}]}
    with pytest.raises(HTTPException) as e:
        scs.create_challan(db, FIRM, challan)
    assert e.value.status_code == 422 and "names an order line but the challan names no order" in e.value.detail
    assert db.rows("delivery_challans") == []


# ── a response with no count is unknown, not zero ────────────────────────────────────────────────────────────────────────
class _NoCount:
    """Answers the count read with rows but no `count` attribute, as a response without a Content-Range does."""

    def __init__(self, inner):
        self.inner = inner

    def table(self, name):
        real = self.inner.table(name)
        if name != "bank_transactions":
            return real

        class _Q:
            def __getattr__(self, attr):
                attribute = getattr(real, attr)
                if attr == "execute":
                    return lambda: type("R", (), {"data": []})()
                return lambda *a, **k: (attribute(*a, **k) and self) or self
        return _Q()

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


def test_a_count_response_without_a_count_is_unknown_and_not_zero(rule_world, monkeypatch):
    db, _ = rule_world
    monkeypatch.setattr(bank, "_db", lambda: _NoCount(db))
    with pytest.raises(HTTPException) as e:
        bank.delete_rule("RULE-1", EXEC)
    assert e.value.status_code == 503 and [r["id"] for r in db.rows("bank_matching_rules")] == ["RULE-1"]
