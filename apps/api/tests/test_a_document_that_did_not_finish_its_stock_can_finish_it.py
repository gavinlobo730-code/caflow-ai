"""A document whose stock effect was not all recorded can be completed, and nothing is recorded twice (POST-A-092, items 1 and 4).

The four per-document functions take `resume=True`. This holds, in order: the pure rule for handing rows back to lines
(`domain/inventory/stock_resume`), each function on the real e2e harness (a line that stopped the rest, a journal that never posted,
a document that is whole, the same item on two lines), the refusal for a line recorded against stock that was already short, the
service that finds and retries a document, and the rule that a first run reads nothing it does not need.
"""
from __future__ import annotations

import uuid

import pytest

import domain.inventory_service as inv
from domain.inventory import stock_effect as se
from domain.inventory import stock_resume as sr
from services import stock_effect_retry_service as svc
from tests.e2e_harness import FakeDB

FIRM = "firm-stock-resume"
CLIENT = "client-stock-resume"


# ── the pure rule ────────────────────────────────────────────────────────────────────────────────────────────────

def _row(item, *, journal=None, qty="2", running="10", value=-1000):
    return {"id": str(uuid.uuid4()), "service_catalogue_id": item, "quantity_delta": qty, "running_qty_units": running,
            "value_delta_paise": value, "journal_entry_id": journal}


def test_rows_are_handed_back_one_per_line_item_by_item_in_the_order_written():
    a, b = "item-a", "item-b"
    first, second, other = _row(a), _row(a), _row(b)
    prior = sr.PriorMovements([first, other, second])
    assert prior.take(a, "2") is first and prior.take(a, 2) is second and prior.take(a, "2.000") is None, "a third line of the item has no row"
    assert prior.take(b, "2") is other and prior.take("item-c", 1) is None
    assert prior.unconsumed == 0


def test_a_row_for_no_item_is_never_handed_to_a_line():
    assert sr.PriorMovements([{"id": "x", "service_catalogue_id": None}]).take("anything", 1) is None


@pytest.mark.parametrize("running,delta,short", [("10", "2", False), ("2", "2", False), ("1", "2", True), ("-3", "2", True),
                                                  ("not a number", "2", True), (None, "2", True)])
def test_a_stock_in_row_is_short_when_the_stock_before_it_was_below_nil(running, delta, short):
    assert sr.was_short_when_recorded(_row("i", running=running, qty=delta)) is short


def test_the_refusal_rules_say_which_stock_in_rows_cannot_be_completed():
    short_unjournalled = _row("i", running="1", qty="2")
    short_journalled = _row("i", running="1", qty="2", journal="je-1")
    for rows, rule, refused in (
        ([short_unjournalled], sr.REFUSE_NONE, False),
        ([short_unjournalled], sr.REFUSE_ANY_SHORT, True),
        ([short_journalled], sr.REFUSE_ANY_SHORT, True),
        ([short_unjournalled], sr.REFUSE_UNJOURNALLED_SHORT, True),
        ([short_journalled], sr.REFUSE_UNJOURNALLED_SHORT, False),
    ):
        prior = sr.PriorMovements([dict(r) for r in rows])
        if refused:
            with pytest.raises(sr.CannotResume):
                prior.take("i", "2", refuse=rule)
        else:
            assert prior.take("i", "2", refuse=rule) is not None, (rows, rule)
    with pytest.raises(ValueError):
        sr.PriorMovements([]).take("i", 1, refuse="sometimes")


# ── the four functions, on the real harness ────────────────────────────────────────────────────────────────────

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


def _stocked(db, item, units=100, cost=1_000_000):
    inv.record_stock_in(db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item, movement_date="2026-04-01",
                        quantity=units, total_cost_paise=cost, movement_type="opening")


def _invoice(db, items, quantity="2"):
    invoice_id = str(uuid.uuid4())
    for n, item in enumerate(items):
        db.seed("client_sales_invoice_lines", {"sales_invoice_id": invoice_id, "description": f"line {n}",
                                               "quantity": quantity, "service_catalogue_id": item})
    return {"id": invoice_id, "invoice_no": f"INV-{invoice_id[:6]}", "invoice_date": "2026-04-20", "client_id": CLIENT}


def _sell(db, invoice, **kw):
    return inv.apply_sale_to_inventory(db, firm_id=FIRM, client_id=CLIENT, invoice=invoice, **kw)


def _rows(db, source_type, source_id):
    return [r for r in db.rows("inventory_stock_ledger") if r.get("source_type") == source_type and r.get("source_id") == source_id]


def _journals(db, suffix):
    return [e for e in db.rows("journal_entries") if str(e.get("reference_no", "")).endswith(suffix)]


def _fail_nth(monkeypatch, name, n):
    real = getattr(inv, name)
    calls = []

    def flaky(*args, **kwargs):
        calls.append(kwargs.get("service_catalogue_id"))
        if len(calls) == n:
            raise RuntimeError("a refused ledger row")
        return real(*args, **kwargs)

    monkeypatch.setattr(inv, name, flaky)
    return lambda: monkeypatch.setattr(inv, name, real)


def test_a_sale_that_stopped_after_line_one_is_completed_without_taking_line_one_out_twice(monkeypatch):
    """POST-A-092 item 4: line 1 moved, line 2 was refused, the combined journal was skipped. The retry moves line 2 only and
    journals BOTH lines in the one combined entry, so the stock ledger and the general ledger agree again."""
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    _stocked(db, a)
    _stocked(db, b)
    invoice = _invoice(db, [a, b])
    heal = _fail_nth(monkeypatch, "record_stock_out", 2)
    first = _sell(db, invoice)
    assert (first.moved_lines, first.goods_lines, first.recorded) == (1, 2, False)
    assert len(_rows(db, "sales_invoice", invoice["id"])) == 1 and not _journals(db, "-COGS")
    heal()

    second = _sell(db, invoice, resume=True)
    assert (second.goods_lines, second.moved_lines, second.recorded, second.journal) == (2, 2, True, se.JOURNAL_POSTED)
    rows = _rows(db, "sales_invoice", invoice["id"])
    assert len(rows) == 2, "line one is not taken out of stock a second time"
    assert sorted(r["service_catalogue_id"] for r in rows) == sorted([a, b])
    entry = _journals(db, "-COGS")
    assert len(entry) == 1
    total = sum(abs(int(r["value_delta_paise"])) for r in rows)
    lines = [l for l in db.rows("journal_lines") if l.get("journal_entry_id") == entry[0]["id"]]
    assert sum(int(l["debit_paise"]) for l in lines) == total == sum(int(l["credit_paise"]) for l in lines), (
        "the journal carries BOTH lines' value, the one already recorded and the one added now")
    assert all(r.get("journal_entry_id") == entry[0]["id"] for r in rows), "both rows point at the journal"


def test_a_sale_whose_journal_never_posted_gets_it_when_the_accounts_exist_and_moves_nothing_again():
    db = FakeDB()
    _chart(db, with_cost_accounts=False)
    item = _good(db)
    _stocked(db, item)
    invoice = _invoice(db, [item])
    first = _sell(db, invoice)
    assert first.moved_lines == 1 and first.journal == se.JOURNAL_NOT_POSTED
    before = list(_rows(db, "sales_invoice", invoice["id"]))
    for key, name in (("inventory", "Inventory"), ("cogs", "Cost of Goods Sold")):
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": key,
                                      "account_name": name, "is_active": True})
    second = _sell(db, invoice, resume=True)
    assert second.recorded and second.journal == se.JOURNAL_POSTED and second.moved_lines == 1
    after = _rows(db, "sales_invoice", invoice["id"])
    assert [r["id"] for r in after] == [r["id"] for r in before], "no second stock row"
    assert len(_journals(db, "-COGS")) == 1 and after[0].get("journal_entry_id")


def test_a_document_that_is_whole_is_left_alone_and_says_recorded():
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    _stocked(db, a)
    _stocked(db, b)
    invoice = _invoice(db, [a, b])
    assert _sell(db, invoice).recorded
    rows_before = [r["id"] for r in _rows(db, "sales_invoice", invoice["id"])]
    journals_before = len(db.rows("journal_entries"))
    again = _sell(db, invoice, resume=True)
    assert again.recorded and again.goods_lines == 2 and again.moved_lines == 2
    assert [r["id"] for r in _rows(db, "sales_invoice", invoice["id"])] == rows_before
    assert len(db.rows("journal_entries")) == journals_before, "no second journal"


def test_the_same_item_on_two_lines_resumes_the_second_line_only(monkeypatch):
    """A row names its item and not its line, so the first row goes to the item's first line and the second line is still owed."""
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice = _invoice(db, [item, item], quantity="3")
    heal = _fail_nth(monkeypatch, "record_stock_out", 2)
    assert _sell(db, invoice).moved_lines == 1
    heal()
    done = _sell(db, invoice, resume=True)
    assert (done.goods_lines, done.moved_lines, done.recorded) == (2, 2, True)
    assert len(_rows(db, "sales_invoice", invoice["id"])) == 2


def test_a_first_run_reads_no_prior_rows(monkeypatch):
    """`resume=False` is the ordinary issue and must not pay for, or be changed by, a read of what is already recorded."""
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    monkeypatch.setattr(sr.PriorMovements, "load", classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(AssertionError("read"))))
    assert _sell(db, _invoice(db, [item])).recorded


def test_a_retry_that_cannot_read_what_is_recorded_writes_nothing(monkeypatch):
    """Writing a line twice takes the goods out of stock twice, so a failed read stops the retry before any write."""
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice = _invoice(db, [item])
    monkeypatch.setattr(sr.PriorMovements, "load", classmethod(lambda cls, *a, **k: (_ for _ in ()).throw(RuntimeError("no read"))))
    effect = _sell(db, invoice, resume=True)
    assert not effect.recorded and effect.stopped_by == "RuntimeError"
    assert _rows(db, "sales_invoice", invoice["id"]) == []


def test_a_purchase_that_stopped_after_line_one_is_completed_with_one_receipt_journal(monkeypatch):
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    bill_id = str(uuid.uuid4())
    for item in (a, b):
        db.seed("purchase_bill_lines", {"bill_id": bill_id, "description": "x", "quantity": "4", "taxable_amount_paise": 400_000,
                                        "expense_account_id": None, "service_catalogue_id": item})
    bill = {"id": bill_id, "bill_no": "B-RES", "bill_date": "2026-04-05", "client_id": CLIENT}
    heal = _fail_nth(monkeypatch, "record_stock_in", 2)
    first = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert (first.moved_lines, first.goods_lines, first.recorded) == (1, 2, False)
    heal()
    second = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill, resume=True)
    assert (second.moved_lines, second.goods_lines, second.recorded, second.journal) == (2, 2, True, se.JOURNAL_POSTED)
    rows = _rows(db, "purchase_bill", bill_id)
    assert len(rows) == 2 and all(r.get("journal_entry_id") for r in rows)
    entries = [e for e in db.rows("journal_entries") if str(e.get("reference_no", "")).endswith("-INV")]
    assert len(entries) == 1
    lines = [l for l in db.rows("journal_lines") if l.get("journal_entry_id") == entries[0]["id"]]
    assert sum(int(l["debit_paise"]) for l in lines) == 800_000, "both lines' cost, one already in stock and one added now"


def test_a_purchase_line_recorded_while_the_item_was_oversold_is_refused_on_a_retry_and_nothing_is_written():
    """The cost split between stock on hand and the cost-of-goods-sold true-up is not on the row, so it is not rebuilt."""
    db = FakeDB()
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": "inventory",
                                  "account_name": "Inventory", "is_active": True})
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": None,
                                  "account_name": "Purchases", "is_active": True})
    item = _good(db)
    assert _sell(db, _invoice(db, [item], quantity="5")).moved_lines == 1  # sold before any stock: a deficit is owed
    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", {"bill_id": bill_id, "description": "x", "quantity": "5", "taxable_amount_paise": 500_000,
                                    "expense_account_id": None, "service_catalogue_id": item})
    bill = {"id": bill_id, "bill_no": "B-SHORT", "bill_date": "2026-04-05", "client_id": CLIENT}
    first = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert first.journal == se.JOURNAL_NOT_POSTED  # the true-up needed the cost account that does not exist
    rows_before = [r["id"] for r in db.rows("inventory_stock_ledger")]
    retry = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill, resume=True)
    assert not retry.recorded and retry.cannot_resume == sr.CANNOT_RESUME_SENTENCE and retry.stopped_by == "CannotResume"
    assert retry.problem().startswith("Purchase bill B-SHORT was received, but a line of it was recorded while the item's stock was")
    assert "Adjust stock by hand" in retry.problem()
    assert [r["id"] for r in db.rows("inventory_stock_ledger")] == rows_before, "a refusal writes nothing"


def test_a_credit_note_is_completed_from_the_row_it_already_has(monkeypatch):
    db = FakeDB()
    _chart(db, with_cost_accounts=False)
    item = _good(db)
    _stocked(db, item)
    cn_id = str(uuid.uuid4())
    db.seed("credit_note_lines", {"credit_note_id": cn_id, "description": "return", "quantity": "2",
                                  "taxable_amount_paise": 50_000, "service_catalogue_id": item})
    note = {"id": cn_id, "credit_note_no": "CN-RES", "credit_note_date": "2026-04-22", "client_id": CLIENT}
    first = inv.apply_credit_note_to_inventory(db, firm_id=FIRM, client_id=CLIENT, credit_note=note)
    assert first.moved_lines == 1 and first.journal == se.JOURNAL_NOT_POSTED
    row = _rows(db, "credit_note", cn_id)[0]
    for key, name in (("inventory", "Inventory"), ("cogs", "Cost of Goods Sold")):
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "system_account_key": key,
                                      "account_name": name, "is_active": True})
    second = inv.apply_credit_note_to_inventory(db, firm_id=FIRM, client_id=CLIENT, credit_note=note, resume=True)
    assert second.recorded and second.journal == se.JOURNAL_POSTED
    assert [r["id"] for r in _rows(db, "credit_note", cn_id)] == [row["id"]]
    entry = [e for e in db.rows("journal_entries") if e.get("source_id") == cn_id]
    assert len(entry) == 1
    lines = [l for l in db.rows("journal_lines") if l.get("journal_entry_id") == entry[0]["id"]]
    assert sum(int(l["debit_paise"]) for l in lines) == int(row["value_delta_paise"]) > 0, "the row's own value, not a re-priced one"


def test_a_debit_note_that_stopped_is_completed(monkeypatch):
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    _stocked(db, a)
    _stocked(db, b)
    dn_id = str(uuid.uuid4())
    for item in (a, b):
        db.seed("debit_note_lines", {"debit_note_id": dn_id, "description": "return", "quantity": "1", "service_catalogue_id": item})
    note = {"id": dn_id, "debit_note_no": "DN-RES", "debit_note_date": "2026-04-23", "client_id": CLIENT}
    heal = _fail_nth(monkeypatch, "record_stock_out", 2)
    first = inv.apply_debit_note_to_inventory(db, firm_id=FIRM, client_id=CLIENT, debit_note=note)
    assert (first.moved_lines, first.recorded) == (1, False)
    heal()
    second = inv.apply_debit_note_to_inventory(db, firm_id=FIRM, client_id=CLIENT, debit_note=note, resume=True)
    assert (second.moved_lines, second.goods_lines, second.recorded) == (2, 2, True)
    assert len(_rows(db, "debit_note", dn_id)) == 2


# ── the service ─────────────────────────────────────────────────────────────────────────────────────────────────

def _issued_invoice_in(db, items, *, status="issued", **extra):
    invoice = _invoice(db, items)
    db.seed("client_sales_invoices", {"id": invoice["id"], "firm_id": FIRM, "client_id": CLIENT, "invoice_no": invoice["invoice_no"],
                                      "invoice_date": invoice["invoice_date"], "status": status, **extra})
    return invoice


def _retry(db, invoice, **kw):
    return svc.retry(db, firm_id=kw.pop("firm_id", FIRM), client_id=kw.pop("client_id", CLIENT), kind=kw.pop("kind", "sales_invoice"),
                     document_id=invoice["id"], created_by=None)


def test_the_service_completes_an_issued_invoice_and_says_so_in_words(monkeypatch):
    db = FakeDB()
    _chart(db)
    a, b = _good(db, "A"), _good(db, "B")
    _stocked(db, a)
    _stocked(db, b)
    invoice = _issued_invoice_in(db, [a, b])
    heal = _fail_nth(monkeypatch, "record_stock_out", 2)
    assert not _sell(db, invoice).recorded
    heal()
    answer = _retry(db, invoice)
    assert answer["recorded"] is True and answer["stock_effect"]["moved_lines"] == 2
    assert answer["message"] == f"The stock for sales invoice {invoice['invoice_no']} is recorded in full."
    assert len(_rows(db, "sales_invoice", invoice["id"])) == 2


def test_the_service_says_so_when_the_retry_could_not_finish_either(monkeypatch):
    db = FakeDB()
    _chart(db, with_cost_accounts=False)
    item = _good(db)
    _stocked(db, item)
    invoice = _issued_invoice_in(db, [item])
    answer = _retry(db, invoice)
    assert answer["recorded"] is False and answer["message"] == answer["stock_effect"]["problem"]
    assert answer["stock_effect"]["journal"] == "not_posted"


@pytest.mark.parametrize("extra,words", [
    ({"status": "draft"}, "is still a draft"),
    ({"status": "cancelled"}, "was cancelled"),
    ({"deleted_at": "2026-04-30T00:00:00+00:00"}, "was deleted"),
    ({"is_opening": True}, "opening balance"),
])
def test_a_document_a_retry_would_be_wrong_for_is_refused_in_words(extra, words):
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice = _issued_invoice_in(db, [item], **extra)
    with pytest.raises(svc.Refused) as refusal:
        _retry(db, invoice)
    assert words in str(refusal.value) and str(refusal.value).startswith(f"Sales invoice {invoice['invoice_no']} ")
    assert _rows(db, "sales_invoice", invoice["id"]) == [], "a refusal moves no stock"


def test_a_missing_document_and_another_clients_document_are_the_same_not_found():
    db = FakeDB()
    _chart(db)
    item = _good(db)
    invoice = _issued_invoice_in(db, [item])
    with pytest.raises(svc.NotFound):
        svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=str(uuid.uuid4()), created_by=None)
    with pytest.raises(svc.NotFound):
        _retry(db, invoice, client_id="another-client")
    with pytest.raises(svc.NotFound):
        _retry(db, invoice, firm_id="another-firm")


def test_a_second_retry_while_one_runs_is_refused_and_the_lock_is_released_afterwards(monkeypatch):
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice = _issued_invoice_in(db, [item])
    seen = {}

    def during(*args, **kwargs):
        try:
            _retry(db, invoice)
        except svc.Refused as refusal:
            seen["second"] = str(refusal)
        return se.StockEffect("sales_invoice", 1, 1, se.JOURNAL_POSTED, lines_done=True)

    monkeypatch.setattr(inv, "apply_sale_to_inventory", during)
    assert _retry(db, invoice)["recorded"] is True
    assert "already running" in seen["second"]
    assert not svc._in_flight, "the claim is released"
    monkeypatch.setattr(inv, "apply_sale_to_inventory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert _retry(db, invoice)["recorded"] is False  # guarded turns a broken promise into an answer
    assert not svc._in_flight, "the claim is released after a failure too"


def test_a_document_with_no_goods_line_has_nothing_to_complete():
    db = FakeDB()
    _chart(db)
    invoice = _issued_invoice_in(db, [])
    answer = _retry(db, invoice)
    assert answer["recorded"] is None and answer["stock_effect"] is None and "nothing to complete" in answer["message"]


def test_every_kind_the_sentences_know_has_a_retry_and_names_a_real_function():
    assert set(svc.KINDS) == set(se.DOCUMENTS)
    for kind, spec in svc.KINDS.items():
        assert callable(getattr(inv, spec.apply_name)), kind
        import inspect
        assert "resume" in inspect.signature(getattr(inv, spec.apply_name)).parameters, kind


# ── finding them ────────────────────────────────────────────────────────────────────────────────────────────────

class _Rpc:
    def __init__(self, data=None, boom=False):
        self.data, self.boom, self.asked = data, boom, None

    def rpc(self, name, params):
        self.asked = (name, params)
        outer = self

        class _Call:
            def execute(self_inner):
                if outer.boom:
                    raise RuntimeError("down")
                return type("R", (), {"data": outer.data})()
        return _Call()


def test_the_finder_asks_the_database_function_for_this_firm_and_client():
    answer = {"total": 1, "documents": [{"kind": "sales_invoice", "document_id": "d", "reference": "I-1", "owed_lines": 2,
                                         "moved_lines": 0, "unjournalled_rows": 0}]}
    db = _Rpc(answer)
    assert svc.unrecorded_documents(db, firm_id=FIRM, client_id=CLIENT) == answer
    assert db.asked == ("documents_with_unrecorded_stock", {"p_firm": FIRM, "p_client": CLIENT})
    assert svc.unrecorded_documents(_Rpc([answer]), firm_id=FIRM, client_id=CLIENT) == answer


@pytest.mark.parametrize("db", [_Rpc(boom=True), _Rpc(None), _Rpc("nope"), _Rpc({"documents": "x", "total": 1}),
                                _Rpc({"documents": [], "total": "many"})])
def test_a_read_that_failed_or_came_back_wrong_is_not_an_empty_list(db):
    assert svc.unrecorded_documents(db, firm_id=FIRM, client_id=CLIENT) is None


def test_the_finder_will_not_ask_without_a_firm_and_a_client():
    db = _Rpc({"total": 0, "documents": []})
    assert svc.unrecorded_documents(db, firm_id="", client_id=CLIENT) is None
    assert svc.unrecorded_documents(db, firm_id=FIRM, client_id="") is None
    assert db.asked is None


# ── the two routes ──────────────────────────────────────────────────────────────────────────────────────────────

import ast  # noqa: E402
import pathlib  # noqa: E402
import re  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import routers.inventory as inv_router  # noqa: E402
from models.inventory import StockEffectRetryIn  # noqa: E402

API = pathlib.Path(__file__).resolve().parents[1]
WEB = API.parents[1] / "apps" / "web"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _handler(name):
    tree = ast.parse((API / "routers" / "inventory.py").read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


@pytest.mark.parametrize("handler", ["documents_with_unrecorded_stock", "retry_stock_effect"])
def test_both_routes_prove_the_callers_access_to_the_client_before_they_touch_anything(handler):
    body = [n for n in _handler(handler).body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    first = ast.unparse(body[0])
    assert first.startswith("assert_client_access(current_user, ") and first.endswith("client_id)"), first


def test_the_retry_asks_for_the_write_tier_and_the_list_for_the_read_tier():
    def asked(name):
        return [ast.unparse(d) for d in _handler(name).args.defaults]

    assert "Depends(rbac('accounting', 'write'))" in asked("retry_stock_effect")
    assert "Depends(rbac('accounting', 'read'))" in asked("documents_with_unrecorded_stock")


def test_a_missing_document_is_404_and_a_refusal_is_409_with_the_sentence(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(inv_router, "_USE_MOCK", False)
    monkeypatch.setattr(inv_router, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    DOC_ID = str(uuid.uuid4())
    body = StockEffectRetryIn(client_id=CLIENT, kind="sales_invoice", document_id=DOC_ID)

    def not_found(*a, **k):
        raise svc.NotFound("d")

    monkeypatch.setattr(svc, "retry", not_found)
    with pytest.raises(HTTPException) as gone:
        inv_router.retry_stock_effect(body, CALLER)
    assert gone.value.status_code == 404 and gone.value.detail == "Document not found."

    def refused(*a, **k):
        raise svc.Refused("Sales invoice X was cancelled, so it has no stock effect to complete.")

    monkeypatch.setattr(svc, "retry", refused)
    with pytest.raises(HTTPException) as no:
        inv_router.retry_stock_effect(body, CALLER)
    assert no.value.status_code == 409 and "was cancelled" in no.value.detail


def test_an_answer_is_returned_and_the_retry_is_audited(monkeypatch):
    monkeypatch.setattr(inv_router, "_USE_MOCK", False)
    monkeypatch.setattr(inv_router, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr(svc, "retry", lambda *a, **k: {"recorded": True, "message": "ok", "stock_effect": None})
    events = []
    monkeypatch.setattr(inv_router, "log_event", lambda *a, **k: events.append((a, k)))
    doc_id = str(uuid.uuid4())
    res = inv_router.retry_stock_effect(StockEffectRetryIn(client_id=CLIENT, kind="credit_note", document_id=doc_id), CALLER)
    assert res["success"] is True and res["data"]["message"] == "ok"
    assert events and events[0][0][1:4] == ("stock_effect", doc_id, "retry") and events[0][1]["new_data"] == {"kind": "credit_note", "recorded": True}


def test_a_list_that_could_not_be_read_is_a_failure_and_never_an_empty_list(monkeypatch):
    monkeypatch.setattr(inv_router, "_USE_MOCK", False)
    monkeypatch.setattr(inv_router, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr(svc, "unrecorded_documents", lambda *a, **k: None)
    res = inv_router.documents_with_unrecorded_stock(CLIENT, CALLER)
    assert res["success"] is False and res["data"] is None and "not the same as there being none" in res["error"]
    monkeypatch.setattr(svc, "unrecorded_documents", lambda *a, **k: {"total": 0, "documents": []})
    assert inv_router.documents_with_unrecorded_stock(CLIENT, CALLER)["data"] == {"total": 0, "documents": []}


def test_an_unknown_kind_cannot_reach_the_service():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StockEffectRetryIn(client_id=CLIENT, kind="payroll_run", document_id="d")


# ── the screen speaks the server's vocabulary ───────────────────────────────────────────────────────────────────

def test_the_panels_words_for_the_four_kinds_are_the_servers_kinds():
    """A guard on the side that owns the vocabulary: a panel with its own list would agree with itself and pass."""
    panel = (WEB / "components" / "inventory" / "UnrecordedStockPanel.tsx").read_text()
    block = re.search(r"STOCK_DOCUMENT_WORDS[^{]*\{(.*?)\};", panel, re.S).group(1)
    words = dict(re.findall(r'(\w+):\s*"([^"]+)"', block))
    assert set(words) == set(se.DOCUMENTS)
    for kind, spoken in words.items():
        assert spoken == se.DOCUMENTS[kind][0].capitalize(), kind
    client = (WEB / "lib" / "api" / "index.ts").read_text()
    union = re.search(r"export type UnrecordedStockDocument = \{\s*kind:([^;]+);", client, re.S).group(1)
    assert set(re.findall(r'"(\w+)"', union)) == set(se.DOCUMENTS)



# ── what the independent review found (3-11-2026) ──────────────────────────────────────────────────────────────

def test_a_row_is_handed_only_to_the_line_it_is_for_and_a_mismatch_refuses_in_words():
    out = _row("i", qty="-2")  # a stock-out row carries a negative quantity: the line's quantity is its size
    assert sr.PriorMovements([out]).take("i", "2") is out
    with pytest.raises(sr.CannotResume) as differs:
        sr.PriorMovements([_row("i", qty="2")]).take("i", "3")
    assert str(differs.value) == sr.LINES_CHANGED_SENTENCE
    with pytest.raises(sr.CannotResume):
        sr.PriorMovements([_row("i", qty="not a number")]).take("i", "2")
    # a purchase also holds the line's cost: a stock-in not recorded short carries the whole cost
    bought = _row("i", qty="2", value=500_000)
    assert sr.PriorMovements([dict(bought)]).take("i", "2", refuse=sr.REFUSE_ANY_SHORT, cost_paise=500_000) is not None
    with pytest.raises(sr.CannotResume):
        sr.PriorMovements([dict(bought)]).take("i", "2", refuse=sr.REFUSE_ANY_SHORT, cost_paise=400_000)


def test_a_rehearsal_raises_the_first_refusal_and_consumes_nothing():
    rows = [_row("a", qty="2"), _row("a", qty="9")]
    prior = sr.PriorMovements([dict(r) for r in rows])
    with pytest.raises(sr.CannotResume):
        prior.rehearse([("a", "2"), ("a", "3")])  # the second line's quantity is not the second row's
    assert prior.unconsumed == 2, "a rehearsal walks a copy"
    prior.rehearse([("a", "2"), ("a", "9")])
    assert prior.take("a", "2") is not None and prior.take("a", "9") is not None


def test_a_sale_whose_lines_were_edited_after_the_stock_was_recorded_is_refused_before_anything_is_written(monkeypatch):
    """Line a moved and line b was refused; then line a's quantity was edited and a NEW line was added that sorts before it. The walk
    meets the new line (owed, no row) first and the edited one second. Without the rehearsal the new line's stock would already be out
    when the edited line refuses; with it the retry refuses having written nothing."""
    db = FakeDB()
    _chart(db)
    a, b, c = _good(db, "A"), _good(db, "B"), _good(db, "C")
    for item in (a, b, c):
        _stocked(db, item)
    invoice_id = str(uuid.uuid4())
    for line_id, item in (("a-line", a), ("b-line", b)):
        db.seed("client_sales_invoice_lines", {"id": line_id, "sales_invoice_id": invoice_id, "description": line_id, "quantity": "2",
                                               "service_catalogue_id": item})
    invoice = {"id": invoice_id, "invoice_no": "INV-EDIT", "invoice_date": "2026-04-20", "client_id": CLIENT}
    heal = _fail_nth(monkeypatch, "record_stock_out", 2)
    assert _sell(db, invoice).moved_lines == 1
    heal()
    for row in db.rows("client_sales_invoice_lines"):
        if row["id"] == "a-line":
            row["quantity"] = "7"
    db.seed("client_sales_invoice_lines", {"id": "0-line", "sales_invoice_id": invoice_id, "description": "new", "quantity": "1",
                                           "service_catalogue_id": c})
    before = [r["id"] for r in db.rows("inventory_stock_ledger")]
    effect = _sell(db, invoice, resume=True)
    assert not effect.recorded and effect.cannot_resume == sr.LINES_CHANGED_SENTENCE
    assert [r["id"] for r in db.rows("inventory_stock_ledger")] == before, "a refusal comes before the first write, the new line's included"


def test_the_lines_are_read_in_one_order_so_a_second_line_of_the_same_item_is_matched_the_same_way_twice(monkeypatch):
    """The two lines of one item have different quantities and are stored in the opposite order to their ids. Both runs read them by id,
    so the row written for the first of them on the first run is that line's row on the retry, and the stock booked is 3 and 5."""
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice_id = str(uuid.uuid4())
    db.seed("client_sales_invoice_lines", {"id": "b-line", "sales_invoice_id": invoice_id, "description": "later", "quantity": "5",
                                           "service_catalogue_id": item})
    db.seed("client_sales_invoice_lines", {"id": "a-line", "sales_invoice_id": invoice_id, "description": "first", "quantity": "3",
                                           "service_catalogue_id": item})
    invoice = {"id": invoice_id, "invoice_no": "INV-ORD", "invoice_date": "2026-04-20", "client_id": CLIENT}
    heal = _fail_nth(monkeypatch, "record_stock_out", 2)
    assert _sell(db, invoice).moved_lines == 1
    heal()
    # An UPDATE of a line (a catalogue link edited) can move its tuple, so the unordered read comes back the other way round.
    db.rows("client_sales_invoice_lines").reverse()
    done = _sell(db, invoice, resume=True)
    assert done.recorded and done.moved_lines == 2
    booked = sorted(abs(float(r["quantity_delta"])) for r in _rows(db, "sales_invoice", invoice_id))
    assert booked == [3.0, 5.0], booked


@pytest.fixture()
def real_kernel(monkeypatch):
    """The posting kernel out of its mock mode, as `wire_e2e` puts it: only then does it look for an entry already live under the number
    and date and compare the figures when asked to."""
    import services.phase2_journal_service as pjs
    monkeypatch.setattr(pjs, "_USE_MOCK", False)


def test_a_retry_hands_the_journal_a_document_to_match_and_a_first_run_does_not(monkeypatch, real_kernel):
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    asked = []
    real = inv.post_cogs_journal_entry
    monkeypatch.setattr(inv, "post_cogs_journal_entry", lambda *a, **k: (asked.append(k.get("must_match")), real(*a, **k))[1])
    invoice = _invoice(db, [item])
    assert _sell(db, invoice).recorded
    assert asked == [None], "a first run reuses an entry as it always did"
    for row in db.rows("inventory_stock_ledger"):
        if row.get("source_id") == invoice["id"]:
            row["journal_entry_id"] = None  # the stamp was lost after the journal posted
    again = _sell(db, invoice, resume=True)
    assert asked[-1] == f"invoice {invoice['invoice_no']}"
    assert again.recorded, "the journal is there with the very figures the rows hold, so it is reused and the rows are stamped again"
    assert all(r.get("journal_entry_id") for r in _rows(db, "sales_invoice", invoice["id"]))


def test_an_existing_journal_with_different_figures_is_not_stamped_onto_the_rows(monkeypatch, real_kernel):
    """The review's second finding: the kernel returned any live entry under the same number and date, so a row worth more than the entry
    was stamped as journalled and never found again. With the document to match, the entry is refused and the rows stay unjournalled."""
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice = _invoice(db, [item])
    assert _sell(db, invoice).recorded
    for row in db.rows("inventory_stock_ledger"):
        if row.get("source_id") == invoice["id"]:
            row["journal_entry_id"] = None
            row["value_delta_paise"] = int(row["value_delta_paise"]) - 100  # the row now holds more than the entry does
    entries_before = len(db.rows("journal_entries"))
    effect = _sell(db, invoice, resume=True)
    assert effect.journal == se.JOURNAL_NOT_POSTED and not effect.recorded
    assert all(not r.get("journal_entry_id") for r in _rows(db, "sales_invoice", invoice["id"])), "nothing was stamped"
    assert len(db.rows("journal_entries")) == entries_before


def _bill_with_freight(db, item, *, charge_applied=False):
    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", {"id": "l1", "bill_id": bill_id, "description": "x", "quantity": "4", "taxable_amount_paise": 400_000,
                                    "expense_account_id": None, "service_catalogue_id": item})
    db.seed("purchase_bill_landed_costs", {"id": "c1", "firm_id": FIRM, "client_id": CLIENT, "bill_id": bill_id,
                                           "description": "freight", "amount_paise": 10_000,
                                           "expense_account_id": None, "source": "manual",
                                           "applied_at": "2026-04-05T00:00:00+00:00" if charge_applied else None})
    return {"id": bill_id, "bill_no": "B-FRT", "bill_date": "2026-04-05", "client_id": CLIENT}


def test_a_bill_with_freight_is_marked_applied_only_when_its_receipt_journal_posted():
    """The review's third finding. A receipt that did not post used to consume the charge all the same, and a retry then credited the
    whole row to the line's own account with the freight account left debited."""
    failed, ok = FakeDB(), FakeDB()
    _chart(failed, with_cost_accounts=False)
    _chart(ok)
    item_f, item_o = _good(failed), _good(ok)
    bill_f = _bill_with_freight(failed, item_f)
    bill_o = _bill_with_freight(ok, item_o)
    # Without an Inventory account the receipt journal cannot post.
    failed.rows("chart_of_accounts")[:] = [r for r in failed.rows("chart_of_accounts") if r.get("system_account_key") != "inventory"]
    assert inv.apply_purchase_to_inventory(failed, firm_id=FIRM, client_id=CLIENT, bill=bill_f).journal == se.JOURNAL_NOT_POSTED
    assert failed.rows("purchase_bill_landed_costs")[0]["applied_at"] is None, "a charge is not spent by a receipt that did not post"
    assert inv.apply_purchase_to_inventory(ok, firm_id=FIRM, client_id=CLIENT, bill=bill_o).recorded
    assert ok.rows("purchase_bill_landed_costs")[0]["applied_at"], "a charge the receipt carried is spent"


def test_a_bill_with_freight_and_stock_that_has_no_journal_is_refused_on_a_retry_and_nothing_is_written():
    db = FakeDB()
    _chart(db, with_cost_accounts=False)
    db.rows("chart_of_accounts")[:] = [r for r in db.rows("chart_of_accounts") if r.get("system_account_key") != "inventory"]
    item = _good(db)
    bill = _bill_with_freight(db, item)
    assert inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill).journal == se.JOURNAL_NOT_POSTED
    before = [r["id"] for r in db.rows("inventory_stock_ledger")]
    retry = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill, resume=True)
    assert not retry.recorded and retry.cannot_resume == sr.LANDED_COSTS_SENTENCE
    assert "freight, insurance or duty" in retry.problem() and "Adjust stock by hand" in retry.problem()
    assert [r["id"] for r in db.rows("inventory_stock_ledger")] == before


def test_a_bill_with_freight_whose_stock_is_whole_is_not_refused():
    db = FakeDB()
    _chart(db)
    item = _good(db)
    bill = _bill_with_freight(db, item)
    assert inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill).recorded
    assert inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill, resume=True).recorded


def test_a_retry_in_a_closed_year_is_refused_with_the_closures_sentence_before_anything_is_written(monkeypatch):
    """The review's first finding: nothing asked whether the document's year was closed, so a line's stock row landed in a finalised year
    and the journal behind it was refused by the kernel."""
    from fastapi import HTTPException
    from services import period_lock_service
    db = FakeDB()
    _chart(db)
    item = _good(db)
    _stocked(db, item)
    invoice = _issued_invoice_in(db, [item])
    asked = []

    def closed(_db, firm, client, date, cache=None):
        asked.append((firm, client, date))
        raise HTTPException(status_code=422, detail="The financial year 2025-26 is locked for posting.")

    monkeypatch.setattr(period_lock_service, "assert_not_closed", closed)
    with pytest.raises(HTTPException) as refusal:
        _retry(db, invoice)
    assert refusal.value.status_code == 422 and "locked for posting" in refusal.value.detail
    assert asked == [(FIRM, CLIENT, invoice["invoice_date"])], "the document's own date is what is asked"
    assert _rows(db, "sales_invoice", invoice["id"]) == []
    assert not svc._in_flight, "the claim was never taken"


def test_the_retry_asks_the_closures_before_it_claims_or_writes():
    import ast as _ast
    tree = _ast.parse((API / "services" / "stock_effect_retry_service.py").read_text())
    retry_fn = next(n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name == "retry")
    calls = {}
    for node in _ast.walk(retry_fn):
        if isinstance(node, _ast.Call):
            calls.setdefault(_ast.unparse(node.func), node.lineno)
    assert calls["period_lock_service.assert_not_closed"] < calls["_claim"] < calls["stock_effects.guarded"]


def test_an_id_the_database_cannot_read_is_a_422_at_the_model():
    with pytest.raises(Exception) as bad:
        StockEffectRetryIn(client_id=CLIENT, kind="sales_invoice", document_id="not-an-id")
    assert "document_id" in str(bad.value)
    assert StockEffectRetryIn(client_id=CLIENT, kind="sales_invoice", document_id=str(uuid.uuid4()))


def test_a_purchase_whose_lines_were_edited_after_its_stock_was_recorded_is_refused_before_anything_is_written():
    """The purchase's own rehearsal: a new line that sorts before the edited one is owed and would be written first, so without the
    rehearsal the refusal would come after a stock-in had already been recorded for it."""
    db = FakeDB()
    _chart(db, with_cost_accounts=False)
    db.rows("chart_of_accounts")[:] = [r for r in db.rows("chart_of_accounts") if r.get("system_account_key") != "inventory"]
    a, c = _good(db, "A"), _good(db, "C")
    bill_id = str(uuid.uuid4())
    db.seed("purchase_bill_lines", {"id": "a-line", "bill_id": bill_id, "description": "x", "quantity": "4", "taxable_amount_paise": 400_000,
                                    "expense_account_id": None, "service_catalogue_id": a})
    bill = {"id": bill_id, "bill_no": "B-EDIT", "bill_date": "2026-04-05", "client_id": CLIENT}
    first = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    assert first.moved_lines == 1 and first.journal == se.JOURNAL_NOT_POSTED
    for row in db.rows("purchase_bill_lines"):
        row["quantity"] = "9"
    db.seed("purchase_bill_lines", {"id": "0-line", "bill_id": bill_id, "description": "new", "quantity": "2",
                                    "taxable_amount_paise": 200_000, "expense_account_id": None, "service_catalogue_id": c})
    before = [r["id"] for r in db.rows("inventory_stock_ledger")]
    retry = inv.apply_purchase_to_inventory(db, firm_id=FIRM, client_id=CLIENT, bill=bill, resume=True)
    assert not retry.recorded and retry.cannot_resume == sr.LINES_CHANGED_SENTENCE
    assert [r["id"] for r in db.rows("inventory_stock_ledger")] == before, "the new line's stock-in was not written first"
