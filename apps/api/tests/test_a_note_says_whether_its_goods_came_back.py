"""A credit note or a purchase debit note says whether the goods it names physically came back (POST-A-371, migration 581).

Until now every goods line that named a catalogue item on a credit note or a debit note moved stock and cost, because the note's reason is
free text and nothing the software could read said whether the note corrected a PRICE or returned GOODS. Now the note carries
`goods_returned`; issuing a note that names goods and has not stated it is refused in a sentence, before anything is posted; "no" issues the
note, moves no stock and says so; "yes" moves stock as before. Mock mode (the in-memory database double), so these prove the ROUTES and the
stock functions' obedience; the migration's finder is proved against a real database in the `_pg` file beside this one.
"""
import pytest
from fastapi import HTTPException

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_bills as pb
import routers.sales_invoices as si
import routers.vendors as ve
from domain import inventory_service
from domain.inventory import note_goods
from models.invoices import InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e, with_lines

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}


def _db(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, cn, pb, dn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
    db.seed("customers", {"id": "CUST1", "firm_id": FIRM, "client_id": "CLI", "name": "Acme", "is_active": True, "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND1", "firm_id": FIRM, "client_id": "CLI", "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False, "opening_balance_paise": 0})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "GOOD", "firm_id": FIRM, "client_id": "CLI", "name": "Materials", "kind": "good"})
    db.seed("service_catalogue", {"id": "SERVICE", "firm_id": FIRM, "client_id": "CLI", "name": "Advice", "kind": "service"})
    return db


@pytest.fixture()
def spy(monkeypatch):
    """What the two stock functions were asked, and what they answered."""
    seen: dict = {"credit_note": [], "debit_note": []}
    for kind, name in (("credit_note", "apply_credit_note_to_inventory"), ("debit_note", "apply_debit_note_to_inventory")):
        real = getattr(inventory_service, name)

        def wrapped(*a, _real=real, _kind=kind, **k):
            effect = _real(*a, **k)
            seen[_kind].append(effect)
            return effect
        monkeypatch.setattr(inventory_service, name, wrapped)
    return seen


_COUNTER = iter(range(1, 10_000))


def _invoice(db):
    inv = db.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": "CLI", "customer_id": "CUST1", "invoice_no": f"INV-{next(_COUNTER)}", "invoice_date": "2025-06-01",
        "status": "draft", "total_paise": 118000, "taxable_amount_paise": 100000, "cgst_paise": 9000, "sgst_paise": 9000,
        "igst_paise": 0, "supply_state_code": "27", "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0, "is_interstate": False})
    with_lines(db, "sales_invoice", inv)
    assert si.issue_invoice(inv["id"], CALLER)["success"] is True
    return inv["id"]


def _bill(db):
    res = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no=f"BILL-{next(_COUNTER)}",
        lines=[PurchaseBillLineIn(description="mat", rate_paise=100000, quantity=1, gst_rate_percent=18.0, service_catalogue_id="GOOD")],
    ), CALLER)
    assert pb.receive_purchase_bill(res["data"]["id"], CALLER)["success"] is True
    return res["data"]["id"]


def _line(item):
    return InvoiceLineIn(description="line", quantity=1, rate_paise=20000, gst_rate_percent=18.0, service_catalogue_id=item)


def _credit_note(db, item="GOOD", **kw):
    res = cn.create_credit_note(cn.CreditNoteIn(client_id="CLI", customer_id="CUST1", credit_note_date="2025-06-05",
                                                sales_invoice_id=_invoice(db), lines=[_line(item)], **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _debit_note(db, item="GOOD", **kw):
    res = dn.create_debit_note(dn.DebitNoteIn(client_id="CLI", vendor_id="VEND1", debit_note_date="2025-06-05",
                                              purchase_bill_id=_bill(db), lines=[_line(item)], **kw), CALLER)
    assert res["success"] is True, res
    return res["data"]["id"]


def _stored(db, table, row_id):
    return next(r for r in db.rows(table) if r["id"] == row_id)


# ── a note that names goods must say ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["credit_note", "debit_note"])
def test_issuing_a_note_that_names_goods_and_does_not_say_is_refused_before_anything_posts(monkeypatch, spy, kind):
    db = _db(monkeypatch)
    note_id = _credit_note(db) if kind == "credit_note" else _debit_note(db)
    journals_before = len(db.rows("journal_entries"))
    issue = cn.issue_credit_note if kind == "credit_note" else dn.issue_debit_note
    with pytest.raises(HTTPException) as refused:
        issue(note_id, CALLER)
    assert refused.value.status_code == 422
    assert refused.value.detail == note_goods.question(kind)
    assert "Goods returned" in refused.value.detail and "No goods returned" in refused.value.detail
    table = "credit_notes" if kind == "credit_note" else "debit_notes"
    assert _stored(db, table, note_id)["status"] == "draft", "the note is still a draft"
    assert len(db.rows("journal_entries")) == journals_before, "nothing was posted"
    assert spy[kind] == [], "the stock function was never reached"


@pytest.mark.parametrize("kind", ["credit_note", "debit_note"])
def test_a_note_that_says_no_goods_came_back_issues_moves_no_stock_and_says_so(monkeypatch, spy, kind):
    db = _db(monkeypatch)
    note_id = _credit_note(db, goods_returned=False) if kind == "credit_note" else _debit_note(db, goods_returned=False)
    out = (cn.issue_credit_note if kind == "credit_note" else dn.issue_debit_note)(note_id, CALLER)
    assert out["success"] is True, out
    data = out["data"]
    assert data["status"] == "issued" and data["journal_entry_id"], "the GST and ledger side of the note went ahead"
    assert "stock_effect" not in data, "no stock answer, because no stock was meant to move"
    assert data["stock_not_moved"] == note_goods.declined(kind, data.get("credit_note_no") or data.get("debit_note_no"))
    assert ("no goods came back" if kind == "credit_note" else "no goods went back to the supplier") in data["stock_not_moved"]
    assert [e.goods_lines for e in spy[kind]] == [0], "the stock function was asked and counted no goods line"
    assert not [r for r in db.rows("inventory_stock_ledger") if r.get("source_type") in ("credit_note", "debit_note")], "no stock row, no cost row for the note"


@pytest.mark.parametrize("kind", ["credit_note", "debit_note"])
def test_a_note_that_says_goods_came_back_still_reaches_stock(monkeypatch, spy, kind):
    db = _db(monkeypatch)
    note_id = _credit_note(db, goods_returned=True) if kind == "credit_note" else _debit_note(db, goods_returned=True)
    out = (cn.issue_credit_note if kind == "credit_note" else dn.issue_debit_note)(note_id, CALLER)
    assert out["success"] is True, out
    assert "stock_not_moved" not in out["data"]
    assert [e.goods_lines for e in spy[kind]] == [1], "the goods line was meant to move, as before"


@pytest.mark.parametrize("kind", ["credit_note", "debit_note"])
def test_a_note_with_no_goods_line_is_not_asked(monkeypatch, spy, kind):
    db = _db(monkeypatch)
    note_id = _credit_note(db, item="SERVICE") if kind == "credit_note" else _debit_note(db, item="SERVICE")
    out = (cn.issue_credit_note if kind == "credit_note" else dn.issue_debit_note)(note_id, CALLER)
    assert out["success"] is True, out
    assert "stock_not_moved" not in out["data"], "stock is not involved, and nothing is said about it"


@pytest.mark.parametrize("kind", ["credit_note", "debit_note"])
def test_a_draft_can_be_given_its_answer_by_editing_it_and_then_issues(monkeypatch, spy, kind):
    db = _db(monkeypatch)
    note_id = _credit_note(db) if kind == "credit_note" else _debit_note(db)
    update, issue = ((cn.update_credit_note, cn.issue_credit_note) if kind == "credit_note" else (dn.update_debit_note, dn.issue_debit_note))
    body = (cn.CreditNoteUpdateIn if kind == "credit_note" else dn.DebitNoteUpdateIn)(goods_returned=False)
    assert update(note_id, body, CALLER)["success"] is True
    assert _stored(db, "credit_notes" if kind == "credit_note" else "debit_notes", note_id)["goods_returned"] is False
    assert issue(note_id, CALLER)["success"] is True


@pytest.mark.parametrize("kind", ["credit_note", "debit_note"])
def test_the_column_is_written_only_when_stated_so_a_note_saves_before_the_migration_is_applied(monkeypatch, spy, kind):
    """The API can be live minutes before migration 581 adds the column; a note that does not say must keep saving in that window."""
    db = _db(monkeypatch)
    unstated = _credit_note(db, item="SERVICE") if kind == "credit_note" else _debit_note(db, item="SERVICE")
    table = "credit_notes" if kind == "credit_note" else "debit_notes"
    assert "goods_returned" not in _stored(db, table, unstated)
    stated = _credit_note(db, goods_returned=False) if kind == "credit_note" else _debit_note(db, goods_returned=False)
    assert _stored(db, table, stated)["goods_returned"] is False


# ── the stock functions obey it wherever they are called from ────────────────────────────────────

@pytest.mark.parametrize("name,kind", [("apply_credit_note_to_inventory", "credit_note"), ("apply_debit_note_to_inventory", "debit_note")])
def test_the_stock_function_does_nothing_for_a_note_that_says_no_goods_came_back_even_on_a_retry(name, kind):
    """The retry (`Complete the stock`) calls these directly with the stored row, so the answer is asked here and not only at the route."""
    class Boom:
        def table(self, *_a, **_k):
            raise AssertionError("a note that says no goods came back must not read a line, an item or a ledger")
    note = {"id": "n1", f"{kind}_no": "N-1", "goods_returned": False, "client_id": "CLI"}
    for resume in (False, True):
        effect = getattr(inventory_service, name)(Boom(), firm_id=FIRM, client_id="CLI", **{kind: note}, resume=resume)
        assert effect.goods_lines == 0 and effect.recorded and effect.as_dict() is None


def test_only_an_explicit_no_is_a_no():
    assert note_goods.says_no_goods_came_back({"goods_returned": False}) is True
    assert note_goods.says_no_goods_came_back({"goods_returned": None}) is False
    assert note_goods.says_no_goods_came_back({}) is False
    assert note_goods.says_no_goods_came_back({"goods_returned": True}) is False
    assert note_goods.must_say({"goods_returned": None}, 1) and note_goods.must_say({}, 2)
    assert not note_goods.must_say({"goods_returned": False}, 1) and not note_goods.must_say({"goods_returned": True}, 1)
    assert not note_goods.must_say({"goods_returned": None}, 0), "a note with no goods line is never asked"
