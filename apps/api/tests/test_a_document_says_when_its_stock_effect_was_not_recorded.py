"""A document whose stock effect was not all recorded says so on the response that issued it (POST-A-092, the stock half).

`apply_sale_to_inventory` and its three siblings run after the document is committed and swallow every failure, so a refused
ledger row or a chart of accounts with no Inventory or Cost of Goods Sold account left a document that read as complete while
stock and the Inventory account lacked it, and the failure went to Sentry alone. They now RETURN what they did and the four
routes put it on the response. This holds, in order: the sentence module, the four functions on the real e2e harness (the
recorded case, the case stock is not involved in, a journal that could not be posted, a line that raised, and a call that raised
before it could say how far it got), the issue route end to end, and a rule over the four routes.
"""
from __future__ import annotations

import ast
import itertools
import pathlib
import uuid

import pytest

import domain.inventory_service as inv
import routers.sales_invoices as si
from domain.inventory import stock_effect as se
from models.invoices import InvoiceLineIn, SalesInvoiceIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "firm-stock-effect"
CLIENT = "client-stock-effect"
API = pathlib.Path(__file__).resolve().parents[1]


# ── the sentence module ──────────────────────────────────────────────────────────────────────────────────────────

def test_no_goods_line_is_not_a_recorded_one_it_is_no_answer():
    assert se.StockEffect("sales_invoice").as_dict() is None
    assert se.StockEffect("sales_invoice").involves_stock is False
    document = {"id": "x"}
    assert se.attach(document, se.StockEffect("sales_invoice")) == {"id": "x"}, "no key at all, so absent never means all well"
    assert se.attach(document, None) == {"id": "x"}


@pytest.mark.parametrize("kind", sorted(se.DOCUMENTS))
def test_the_problem_is_none_exactly_when_it_was_recorded(kind):
    """Every combination of what the four functions can report: a sentence if and only if something was not recorded, and
    `recorded` on the wire agrees with the sentence."""
    for goods, moved, journal, stopped in itertools.product(range(0, 4), range(0, 4), se.JOURNAL_STATES, (None, "KeyError")):
        if moved > goods:
            continue
        effect = se.StockEffect(kind, goods, moved, journal, stopped)
        answer = effect.as_dict()
        if not effect.involves_stock:
            assert answer is None
            continue
        assert (effect.problem() is None) == effect.recorded == answer["recorded"], (goods, moved, journal, stopped)
        assert answer["problem"] == effect.problem()
        if not effect.recorded:
            assert effect.problem().startswith(f"This {se.DOCUMENTS[kind][0]} was {se.DOCUMENTS[kind][1]}, but "), effect.problem()
            named = se.StockEffect(kind, goods, moved, journal, stopped, reference="REF-9").problem()
            assert named.startswith(f"{se.DOCUMENTS[kind][0].capitalize()} REF-9 was {se.DOCUMENTS[kind][1]}, but "), named


def test_each_failure_shape_has_its_own_sentence_and_none_blames_the_exception():
    nothing = se.StockEffect("sales_invoice", 2, 0).problem()
    part = se.StockEffect("sales_invoice", 2, 1).problem()
    journal = se.StockEffect("sales_invoice", 2, 2, se.JOURNAL_NOT_POSTED).problem()
    late = se.StockEffect("sales_invoice", 2, 2, se.JOURNAL_POSTED, "OSError").problem()
    assert len({nothing, part, journal, late}) == 4
    assert "taken out of stock" in nothing
    assert "only 1 of its goods lines" in part
    assert "journal" in journal and "Inventory account and a Cost of Goods Sold account" in journal
    assert "may be incomplete" in late
    for sentence in (nothing, part, journal, late):
        assert "OSError" not in sentence and "Traceback" not in sentence
    # What was meant to happen differs by document, and the sentence follows it.
    assert "added to stock" in se.StockEffect("purchase_bill", 1, 0).problem()
    assert "added back to stock" in se.StockEffect("credit_note", 1, 0).problem()
    assert "returns to the supplier" in se.StockEffect("debit_note", 1, 0).problem()


def test_a_call_that_raised_before_it_could_count_is_a_failure_and_not_an_absence():
    effect = se.failed("credit_note", "RuntimeError")
    assert effect.involves_stock and not effect.recorded
    assert effect.as_dict()["recorded"] is False and effect.as_dict()["problem"]


def test_an_unknown_kind_or_journal_state_is_refused():
    with pytest.raises(ValueError):
        se.StockEffect("payroll_run")
    with pytest.raises(ValueError):
        se.StockEffect("sales_invoice", journal="maybe")


# ── the four functions, on the real harness ─────────────────────────────────────────────────────────────────────

def _chart(db, with_cost_accounts=True):
    for key, name in (("inventory", "Inventory"), ("cogs", "Cost of Goods Sold")) if with_cost_accounts else ():
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": key,
                                      "account_name": name, "is_active": True})
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": None,
                                  "account_name": "Purchases", "is_active": True})


def _good(db, name="A"):
    item = str(uuid.uuid4())
    db.seed("service_catalogue", {"id": item, "firm_id": FIRM, "client_id": CLIENT, "name": name, "kind": "good",
                                  "stock_qty_units": "0", "avg_cost_paise": 0})
    return item


def _stocked(db, item, units=10, cost=100_000):
    inv.record_stock_in(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item, movement_date="2026-04-01",
                        quantity=units, total_cost_paise=cost, movement_type="opening")


def _invoice(db, items, quantity="2"):
    invoice_id = str(uuid.uuid4())
    for n, item in enumerate(items):
        db.seed("client_sales_invoice_lines", {"sales_invoice_id": invoice_id, "description": f"line {n}",
                                               "quantity": quantity, "service_catalogue_id": item})
    return {"id": invoice_id, "invoice_no": f"INV-{invoice_id[:6]}", "invoice_date": "2026-04-20", "client_id": CLIENT}


def _sell(db, invoice):
    return inv.apply_sale_to_inventory(db, firm_id=FIRM, client_id=CLIENT, invoice=invoice)


def test_a_sale_that_moved_every_line_and_posted_its_journal_is_recorded():
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    _stocked(db, a)
    _stocked(db, b)
    effect = _sell(db, _invoice(db, [a, b]))
    assert effect.as_dict() == {"recorded": True, "goods_lines": 2, "moved_lines": 2, "journal": "posted",
                                 "reference": effect.reference, "problem": None}


def test_a_sale_with_no_goods_line_has_no_stock_effect_to_report():
    db = FakeDB()
    _chart(db)
    invoice_id = str(uuid.uuid4())
    db.seed("client_sales_invoice_lines", {"sales_invoice_id": invoice_id, "description": "consulting", "quantity": "1"})
    assert _sell(db, {"id": invoice_id, "invoice_no": "INV-S", "invoice_date": "2026-04-20"}).as_dict() is None
    service = str(uuid.uuid4())
    db.seed("service_catalogue", {"id": service, "firm_id": FIRM, "client_id": CLIENT, "name": "Audit", "kind": "service"})
    assert _sell(db, _invoice(db, [service])).as_dict() is None, "a service is not a goods line"


def test_an_oversold_line_with_no_cost_basis_posts_no_journal_and_that_is_not_a_failure():
    db = FakeDB()
    _chart(db)
    item = _good(db)  # nothing in stock yet: the movement exists at Rs 0 and no COGS is owed
    effect = _sell(db, _invoice(db, [item]))
    assert effect.journal == se.JOURNAL_NOT_OWED and effect.recorded and effect.moved_lines == 1


def test_a_sale_whose_chart_has_no_cost_accounts_moved_stock_and_could_not_post_its_journal():
    db = FakeDB()
    _chart(db, with_cost_accounts=False)
    item = _good(db)
    _stocked(db, item)
    invoice = _invoice(db, [item])
    effect = _sell(db, invoice)
    assert effect.moved_lines == 1 and effect.journal == se.JOURNAL_NOT_POSTED and not effect.recorded
    assert "journal" in effect.problem()
    # The stock ledger is ahead of the general ledger, which is exactly what the sentence says.
    assert [r for r in db.rows("inventory_stock_ledger") if r.get("movement_type") == "sale"]
    assert not [e for e in db.rows("journal_entries") if str(e.get("reference_no", "")).endswith("-COGS")]


def test_a_line_that_raised_stops_the_rest_and_the_effect_says_how_far_it_got(monkeypatch):
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    _stocked(db, a)
    _stocked(db, b)
    real = inv.record_stock_out
    calls = []

    def second_one_fails(*args, **kwargs):
        calls.append(kwargs["service_catalogue_id"])
        if len(calls) == 2:
            raise RuntimeError("a refused ledger row")
        return real(*args, **kwargs)

    monkeypatch.setattr(inv, "record_stock_out", second_one_fails)
    effect = _sell(db, _invoice(db, [a, b]))
    assert (effect.goods_lines, effect.moved_lines, effect.stopped_by) == (2, 1, "RuntimeError")
    assert "only 1 of its goods lines" in effect.problem()
    assert "refused ledger row" not in effect.problem(), "the exception's message is for the log, not for a screen"
    # What the function writes is unchanged: the combined COGS journal is posted from a total reached only when every line moved,
    # so it is skipped, and the nightly check still finds the stock ledger ahead of the general ledger.
    assert not [e for e in db.rows("journal_entries") if str(e.get("reference_no", "")).endswith("-COGS")]


def test_a_call_that_raised_after_every_line_moved_says_the_journal_was_not_posted(monkeypatch):
    """The journal helpers swallow their own failures, but a raise from anywhere after the last line moved is the same fact: the
    stock ledger is ahead of the general ledger."""
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    monkeypatch.setattr(inv, "post_cogs_journal_entry", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("late")))
    effect = _sell(db, _invoice(db, [item]))
    assert (effect.goods_lines, effect.moved_lines, effect.journal, effect.stopped_by) == (1, 1, se.JOURNAL_NOT_POSTED, "RuntimeError")
    assert "stock ledger is ahead of the general ledger" in effect.problem()


def test_a_call_that_raised_before_it_could_count_a_line_is_still_a_failure(monkeypatch):
    db = FakeDB()
    _chart(db)
    item = _good(db)
    monkeypatch.setattr(inv, "resolve_costing_policy", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no policy")))
    effect = _sell(db, _invoice(db, [item]))
    assert effect.involves_stock and not effect.recorded and effect.goods_lines == 0
    assert "taken out of stock" in effect.problem()


def test_a_purchase_reports_the_same_way():
    db = FakeDB()
    _chart(db)
    item = _good(db)
    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", {"bill_id": bill_id, "description": "cement", "quantity": "5",
                                    "taxable_amount_paise": 500_000, "expense_account_id": None, "service_catalogue_id": item})
    bill = {"id": bill_id, "bill_no": "B-1", "bill_date": "2026-04-05", "client_id": CLIENT}
    effect = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert effect.as_dict() == {"recorded": True, "goods_lines": 1, "moved_lines": 1, "journal": "posted",
                                 "reference": "B-1", "problem": None}

    db2 = FakeDB()
    _chart(db2, with_cost_accounts=False)
    item2 = _good(db2)
    bill_id2 = str(uuid.uuid4())
    db2.seed("purchase_bill_lines", {"bill_id": bill_id2, "description": "cement", "quantity": "5",
                                     "taxable_amount_paise": 500_000, "expense_account_id": None, "service_catalogue_id": item2})
    bad = inv.apply_purchase_to_inventory(db2, firm_id=FIRM, client_id=CLIENT,
                                          bill={"id": bill_id2, "bill_no": "B-2", "bill_date": "2026-04-05", "client_id": CLIENT})
    assert bad.moved_lines == 1 and bad.journal == se.JOURNAL_NOT_POSTED and not bad.recorded


def test_a_credit_note_and_a_debit_note_report_the_same_way():
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    cn_id, dn_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.seed("credit_note_lines", {"credit_note_id": cn_id, "description": "return", "quantity": "1",
                                  "taxable_amount_paise": 50_000, "service_catalogue_id": item})
    db.seed("debit_note_lines", {"debit_note_id": dn_id, "description": "return", "quantity": "1", "service_catalogue_id": item})
    credit = inv.apply_credit_note_to_inventory(
        db, firm_id=FIRM, client_id=CLIENT,
        credit_note={"id": cn_id, "credit_note_no": "CN-1", "credit_note_date": "2026-04-22", "client_id": CLIENT})
    debit = inv.apply_debit_note_to_inventory(
        db, firm_id=FIRM, client_id=CLIENT,
        debit_note={"id": dn_id, "debit_note_no": "DN-1", "debit_note_date": "2026-04-23", "client_id": CLIENT})
    assert credit.kind == "credit_note" and credit.recorded and credit.moved_lines == 1
    assert debit.kind == "debit_note" and debit.recorded and debit.moved_lines == 1

    bare = FakeDB()
    _chart(bare, with_cost_accounts=False)
    bare_item = _good(bare)
    _stocked(bare, bare_item)
    bare.seed("debit_note_lines", {"debit_note_id": "dn-bare", "description": "return", "quantity": "1",
                                   "service_catalogue_id": bare_item})
    broken = inv.apply_debit_note_to_inventory(
        bare, firm_id=FIRM, client_id=CLIENT,
        debit_note={"id": "dn-bare", "debit_note_no": "DN-2", "debit_note_date": "2026-04-23", "client_id": CLIENT})
    assert broken.journal == se.JOURNAL_NOT_POSTED and not broken.recorded


# ── the issue route, end to end ─────────────────────────────────────────────────────────────────────────────────

CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _route_setup(monkeypatch, with_cost_accounts):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme", "is_active": True,
                          "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, CLIENT)
    if with_cost_accounts:
        for key, name in (("inventory", "Inventory"), ("cogs", "Cost of Goods Sold")):
            db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": key,
                                          "account_name": name, "is_active": True})
    item = _good(db)
    _stocked(db, item)
    line = InvoiceLineIn(description="item", quantity=1, rate_paise=100_000, gst_rate_percent=18.0, service_catalogue_id=item)
    created = si.create_invoice(SalesInvoiceIn(client_id=CLIENT, customer_id="CUST", invoice_no="INV-STK-1",
                                               invoice_date="2025-06-01", supply_state_code="27", lines=[line]), CALLER)
    assert created["success"] is True, created
    return db, created["data"]["id"]


def test_issuing_an_invoice_whose_stock_journal_could_not_post_says_so_on_the_same_response(monkeypatch):
    db, invoice_id = _route_setup(monkeypatch, with_cost_accounts=False)
    res = si.issue_invoice(invoice_id, CALLER)
    assert res["success"] is True, "the invoice is issued all the same: the stock effect never blocks it"
    effect = res["data"]["stock_effect"]
    assert effect["recorded"] is False and effect["journal"] == "not_posted" and effect["moved_lines"] == 1
    assert effect["reference"] == "INV-STK-1"
    assert effect["problem"].startswith("Sales invoice INV-STK-1 was issued, but ")
    assert next(r for r in db.rows("client_sales_invoices") if r["id"] == invoice_id)["status"] == "issued"
    assert "stock_effect" not in next(r for r in db.rows("client_sales_invoices") if r["id"] == invoice_id), "the answer is not stored"


def test_issuing_an_invoice_whose_stock_was_all_recorded_says_recorded(monkeypatch):
    _db, invoice_id = _route_setup(monkeypatch, with_cost_accounts=True)
    res = si.issue_invoice(invoice_id, CALLER)
    assert res["success"] is True
    assert res["data"]["stock_effect"]["recorded"] is True and res["data"]["stock_effect"]["problem"] is None


def test_the_belt_and_braces_catch_in_the_route_reports_a_failure_and_not_silence(monkeypatch):
    _db, invoice_id = _route_setup(monkeypatch, with_cost_accounts=True)

    def boom(*a, **k):
        raise RuntimeError("the function itself broke its promise")

    monkeypatch.setattr(inv, "apply_sale_to_inventory", boom)
    res = si.issue_invoice(invoice_id, CALLER)
    assert res["success"] is True
    assert res["data"]["stock_effect"]["recorded"] is False and res["data"]["stock_effect"]["problem"]


# ── the rule, over the four routes ─────────────────────────────────────────────────────────────────────────────

ROUTES = {
    "sales_invoices.py": ("apply_sale_to_inventory", "sales_invoice"),
    "purchase_bills.py": ("apply_purchase_to_inventory", "purchase_bill"),
    "credit_notes.py": ("apply_credit_note_to_inventory", "credit_note"),
    "debit_notes.py": ("apply_debit_note_to_inventory", "debit_note"),
}


@pytest.mark.parametrize("router", sorted(ROUTES))
def test_a_route_that_moves_stock_runs_it_through_guarded_and_attaches_what_it_did(router):
    """A route that called the function and dropped its return would leave the failure where it was, in Sentry alone. The call
    sits inside `stock_effects.guarded(<kind>, <number>, lambda: <function>(...), <log>)`, whose result is bound and attached."""
    function, kind = ROUTES[router]
    text = (API / "routers" / router).read_text()
    tree = ast.parse(text)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == function]
    assert len(calls) == 1, f"{router} calls {function} {len(calls)} times"
    guarded = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "stock_effects.guarded"]
    assert len(guarded) == 1, f"{router} does not run it through stock_effects.guarded"
    kind_arg, _reference, work, _log = guarded[0].args
    assert isinstance(kind_arg, ast.Constant) and kind_arg.value == kind, router
    assert isinstance(work, ast.Lambda) and calls[0] in list(ast.walk(work)), f"{router}: the call is not what guarded runs"
    bound = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and n.value is guarded[0]]
    assert bound, f"{router} drops what guarded returns"
    assert "stock_effects.attach(" in text, router


def test_every_function_that_moves_a_documents_stock_returns_a_stock_effect():
    tree = ast.parse((API / "domain" / "inventory_service.py").read_text())
    wanted = {name for name, _kind in ROUTES.values()}
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            found[node.name] = node
    assert set(found) == wanted
    for name, node in found.items():
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        assert returns and all(r.value is not None for r in returns), f"{name} has a bare return: the caller cannot tell what it did"
        assert "StockEffect" in ast.unparse(node.returns), name
