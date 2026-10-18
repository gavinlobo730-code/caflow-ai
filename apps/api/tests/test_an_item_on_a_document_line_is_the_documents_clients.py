"""A document line may only name a product or service of the document's own client (POST-A-246).

THE GAP
    `require_service_catalogue_id` only tested that the id was not blank, and the sales-invoice, purchase-bill and note routers
    copied it onto the stored row unchecked. A line naming a sibling client's item (or another firm's) was accepted: the document
    issued and posted its revenue or payable and its GST, and the line moved no stock and posted no cost of goods, because the
    posting paths look the item up under the firm AND the client and an id that is not this client's resolves to nothing there.

WHAT IS HELD
    * the helper reads the items under the firm AND the client, once, and refuses by LINE POSITION any line whose item is not
      found there: another client's, another firm's, deleted, malformed or not text; an owned item passes in either letter case;
    * it asks nothing when there is no database (mock mode) or no line names an item, and a bulk import's shared set means a
      batch costs one read per distinct item (only FOUND ids are remembered, never a refused one);
    * every router that builds document lines asks it: a call to a line builder that omits `owner=` fails the scan, and the two
      routes that read the request's lines inline (sales invoice create and update) are checked by name;
    * the whole path is driven through the real routers on the in-memory database for a sales invoice, a purchase bill and a
      credit note: a sibling's item is a 422 naming the line and NOTHING is written; the client's own item passes the check.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.line_item_ownership import ItemOwner, assert_items_are_the_clients, check

API = Path(__file__).resolve().parents[1]
FIRM, CLIENT, OTHER_CLIENT, OTHER_FIRM = "firm-1", "client-1", "client-2", "firm-2"
MINE = "11111111-1111-4111-8111-111111111111"
MINE_TOO = "22222222-2222-4222-8222-222222222222"
SIBLINGS = "33333333-3333-4333-8333-333333333333"
STRANGERS = "44444444-4444-4444-8444-444444444444"


class _Catalogue:
    """Stands in for `service_catalogue`: scoped by the filters the helper chains, and counting its reads."""

    def __init__(self, rows):
        self.rows, self.reads, self.filters = rows, 0, []

    def table(self, name):
        assert name == "service_catalogue"
        return _Query(self)


class _Query:
    def __init__(self, owner):
        self.owner, self.eqs, self.ids = owner, {}, None

    def select(self, _cols):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def in_(self, col, vals):
        assert col == "id"
        self.ids = list(vals)
        return self

    def execute(self):
        self.owner.reads += 1
        self.owner.filters.append((dict(self.eqs), list(self.ids or [])))

        class R:
            pass
        r = R()
        wanted = [i.lower() for i in (self.ids or [])]       # a uuid column compares in lower case
        r.data = [{"id": row["id"]} for row in self.owner.rows
                  if all(row.get(k) == v for k, v in self.eqs.items()) and row["id"] in wanted]
        return r


def _db():
    return _Catalogue([
        {"id": MINE, "firm_id": FIRM, "client_id": CLIENT},
        {"id": MINE_TOO, "firm_id": FIRM, "client_id": CLIENT},
        {"id": SIBLINGS, "firm_id": FIRM, "client_id": OTHER_CLIENT},
        {"id": STRANGERS, "firm_id": OTHER_FIRM, "client_id": CLIENT},
    ])


def _lines(*ids):
    return [{"service_catalogue_id": i, "description": f"line {n}"} for n, i in enumerate(ids, 1)]


def _refused(db, lines, *words, known=None):
    with pytest.raises(HTTPException) as caught:
        assert_items_are_the_clients(db, FIRM, CLIENT, lines, known=known)
    assert caught.value.status_code == 422
    for w in words:
        assert w in caught.value.detail, (w, caught.value.detail)
    return caught.value.detail


# ── the helper ────────────────────────────────────────────────────────────────────────────────────────

def test_the_clients_own_items_pass_with_one_read_scoped_by_firm_and_client():
    db = _db()
    assert_items_are_the_clients(db, FIRM, CLIENT, _lines(MINE, MINE_TOO, MINE))
    assert db.reads == 1
    eqs, ids = db.filters[0]
    assert eqs == {"firm_id": FIRM, "client_id": CLIENT} and ids == sorted({MINE, MINE_TOO})


def test_a_siblings_item_is_refused_and_the_line_is_named():
    detail = _refused(_db(), _lines(MINE, SIBLINGS), "Line 2 names", "not in this client's catalogue")
    assert "Line 1" not in detail


def test_another_firms_item_is_refused():
    _refused(_db(), _lines(STRANGERS), "Line 1 names")


def test_several_lines_are_named_together_and_the_wording_is_plural():
    _refused(_db(), _lines(SIBLINGS, MINE, STRANGERS), "Lines 1, 3 name")


@pytest.mark.parametrize("bad", ["not-an-id", "123", "' or 1=1 --", "SVC-9"])
def test_an_id_the_catalogue_does_not_hold_is_refused(bad):
    """Whatever it is, if it is not found under this firm and client it is not this client's item."""
    db = _db()
    _refused(db, _lines(bad), "Line 1 names")
    assert db.reads == 1 and db.filters[0][1] == [bad]


def test_an_unknown_but_well_formed_id_is_refused():
    _refused(_db(), _lines("55555555-5555-4555-8555-555555555555"), "Line 1 names")


def test_the_same_item_in_capitals_is_the_same_item():
    assert_items_are_the_clients(_db(), FIRM, CLIENT, _lines(MINE.upper()))


def test_a_line_may_be_a_model_and_not_only_a_dict():
    class Line:
        service_catalogue_id = MINE
    assert_items_are_the_clients(_db(), FIRM, CLIENT, [Line()])

    class Foreign:
        service_catalogue_id = SIBLINGS
    _refused(_db(), [Foreign()], "Line 1 names")


def test_no_database_and_no_named_item_ask_nothing():
    assert_items_are_the_clients(None, FIRM, CLIENT, _lines(SIBLINGS))          # mock mode: no catalogue to read
    db = _db()
    assert_items_are_the_clients(db, FIRM, CLIENT, [{"description": "a"}, {"service_catalogue_id": ""},
                                                    {"service_catalogue_id": None}])
    assert db.reads == 0


def test_a_batch_remembers_only_the_items_it_found():
    db, known = _db(), set()
    assert_items_are_the_clients(db, FIRM, CLIENT, _lines(MINE), known=known)
    assert known == {MINE} and db.reads == 1
    assert_items_are_the_clients(db, FIRM, CLIENT, _lines(MINE, MINE), known=known)
    assert db.reads == 1, "an item already found was asked about again"
    assert_items_are_the_clients(db, FIRM, CLIENT, _lines(MINE, MINE_TOO), known=known)
    assert db.reads == 2 and db.filters[-1][1] == [MINE_TOO], "only the item not yet found is asked about"
    assert known == {MINE, MINE_TOO}
    _refused(db, _lines(SIBLINGS), "Line 1 names", known=known)
    assert SIBLINGS not in known, "a refused id was remembered as the client's"


def test_a_remembered_item_does_not_vouch_for_another_clients_catalogue():
    """The set belongs to ONE client: the routes keep one per client, and a refused id is never in it."""
    known = {MINE}
    _refused(_db(), _lines(SIBLINGS, MINE), "Line 1 names", known=known)


def test_the_owner_wrapper_asks_only_when_there_is_an_owner():
    check(None, _lines(SIBLINGS))                                              # a builder that was handed nothing
    with pytest.raises(HTTPException):
        check(ItemOwner(_db(), FIRM, CLIENT), _lines(SIBLINGS))
    check(ItemOwner(_db(), FIRM, CLIENT), _lines(MINE))
    check(ItemOwner(None, FIRM, CLIENT), _lines(SIBLINGS))                     # an owner with no database: mock mode


# ── every router that builds lines asks ──────────────────────────────────────────────────────────────

BUILDERS = {"_compute_lines", "_compute_bill_lines_and_totals"}
ROUTERS = ("credit_notes", "debit_notes", "sales_debit_notes", "purchase_credit_notes", "purchase_bills")


def _calls(source: str, names: set[str]) -> list[ast.Call]:
    return [n for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names]


def _without_owner(source: str) -> list[int]:
    return [c.lineno for c in _calls(source, BUILDERS) if not any(k.arg == "owner" for k in c.keywords)]


def _router(name: str) -> str:
    return (API / "routers" / f"{name}.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ROUTERS)
def test_no_router_call_to_a_line_builder_omits_the_owner(name):
    assert not _without_owner(_router(name)), (
        f"routers/{name}.py builds document lines without saying whose catalogue they are checked against (POST-A-246)")


def test_the_scan_has_something_to_scan():
    total = sum(len(_calls(_router(n), BUILDERS)) for n in ROUTERS)
    assert total >= 16, f"expected the sixteen builder calls across the routers, found {total}: the scan has gone vacuous"


def test_negative_control_a_call_without_the_owner_is_found():
    assert _without_owner("def f():\n    return _compute_lines(lines, True)\n") == [2]
    assert _without_owner("def f():\n    return _compute_lines(lines, True, owner=None)\n") == []


def _function(source: str, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)


@pytest.mark.parametrize("fn", ["_create_invoice_core", "update_invoice"])
def test_the_two_inline_sales_invoice_paths_ask_by_name(fn):
    node = _function(_router("sales_invoices"), fn)
    asked = [c for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == "assert_items_are_the_clients"]
    assert asked, f"{fn} copies a line's service_catalogue_id onto a stored row without asking whose item it is"


def test_every_line_builder_asks_the_helper_itself():
    for name in ROUTERS:
        src = _router(name)
        for builder in BUILDERS:
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.FunctionDef) and node.name == builder:
                    asks = [c for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                            and c.func.id == "check_items_are_the_clients"]
                    assert asks, f"routers/{name}.py::{builder} takes an owner and never uses it"


# ── the real routers on the in-memory database ───────────────────────────────────────────────────────

import routers.credit_notes as cn  # noqa: E402
import routers.debit_notes as dn  # noqa: E402
import routers.purchase_bills as pb  # noqa: E402
import routers.purchase_credit_notes as pcn  # noqa: E402
import routers.sales_debit_notes as sdn  # noqa: E402
import routers.sales_invoices as si  # noqa: E402
import routers.vendors as ve  # noqa: E402
from models.invoices import (InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn, PurchaseBillUpdateIn,  # noqa: E402
                             SalesInvoiceIn, SalesInvoiceLineIn, SalesInvoiceUpdateIn)
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e  # noqa: E402

E2E_FIRM = "FIRM-A"
CALLER = {"firm_id": E2E_FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
OWN, SIBLING, STRANGER = "SVC-1", "SVC-2", "SVC-3"   # this client's item, a sibling client's, another firm's


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, pb, cn, dn, sdn, pcn, ve])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    for cid in ("CLI", "CLI2"):
        db.seed("clients", {"id": cid, "firm_id": E2E_FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2025-04-01"})
        seed_standard_coa(db, E2E_FIRM, cid)
    db.seed("customers", {"id": "CUST1", "firm_id": E2E_FIRM, "client_id": "CLI", "name": "Acme", "state_code": "27",
                          "is_active": True, "opening_balance_paise": 0})
    db.seed("vendors", {"id": "VEND1", "firm_id": E2E_FIRM, "client_id": "CLI", "name": "Supplier", "state_code": "27",
                        "gstin": "27CCCCC2222C1Z5", "tds_applicable": False, "opening_balance_paise": 0})
    db.seed("service_catalogue", {"id": OWN, "firm_id": E2E_FIRM, "client_id": "CLI", "name": "Mine", "kind": "service"})
    db.seed("service_catalogue", {"id": SIBLING, "firm_id": E2E_FIRM, "client_id": "CLI2", "name": "Sibling's", "kind": "service"})
    db.seed("service_catalogue", {"id": STRANGER, "firm_id": "FIRM-B", "client_id": "CLI", "name": "Stranger's", "kind": "service"})
    return db


def _inv_line(item, cls=InvoiceLineIn):
    return cls(service_catalogue_id=item, description="work", rate_paise=100000, quantity=1, gst_rate_percent=18.0)


def _bill_line(item):
    return PurchaseBillLineIn(service_catalogue_id=item, description="mat", rate_paise=100000, quantity=1, gst_rate_percent=18.0)


# kind -> (create(items), update(document_id, items), the table the document lands in, the lines table, its parent key)
KINDS = {
    "sales invoice": (
        lambda items: si.create_invoice(SalesInvoiceIn(
            client_id="CLI", customer_id="CUST1", invoice_no="INV-1", invoice_date="2025-06-01",
            lines=[_inv_line(i, SalesInvoiceLineIn) for i in items]), CALLER),
        lambda doc, items: si.update_invoice(doc, SalesInvoiceUpdateIn(lines=[_inv_line(i, SalesInvoiceLineIn) for i in items]), CALLER),
        "client_sales_invoices", "client_sales_invoice_lines", "sales_invoice_id"),
    "purchase bill": (
        lambda items: pb.create_purchase_bill(PurchaseBillIn(
            client_id="CLI", vendor_id="VEND1", bill_date="2025-06-01", bill_no="BILL-1",
            lines=[_bill_line(i) for i in items]), CALLER),
        lambda doc, items: pb.update_purchase_bill(doc, PurchaseBillUpdateIn(lines=[_bill_line(i) for i in items]), CALLER),
        "purchase_bills", "purchase_bill_lines", "bill_id"),
    "credit note": (
        lambda items: cn.create_credit_note(cn.CreditNoteIn(
            client_id="CLI", customer_id="CUST1", credit_note_date="2025-06-05", reason="Goods returned",
            lines=[_inv_line(i) for i in items]), CALLER),
        lambda doc, items: cn.update_credit_note(doc, cn.CreditNoteUpdateIn(lines=[_inv_line(i) for i in items]), CALLER),
        "credit_notes", "credit_note_lines", "credit_note_id"),
    "debit note": (
        lambda items: dn.create_debit_note(dn.DebitNoteIn(
            client_id="CLI", vendor_id="VEND1", debit_note_date="2025-06-05", lines=[_inv_line(i) for i in items]), CALLER),
        lambda doc, items: dn.update_debit_note(doc, dn.DebitNoteUpdateIn(lines=[_inv_line(i) for i in items]), CALLER),
        "debit_notes", "debit_note_lines", "debit_note_id"),
    "sales debit note": (
        lambda items: sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
            client_id="CLI", customer_id="CUST1", debit_note_date="2025-06-05", reason="Undercharged",
            lines=[_inv_line(i) for i in items]), CALLER),
        lambda doc, items: sdn.update_sales_debit_note(doc, sdn.SalesDebitNoteUpdateIn(lines=[_inv_line(i) for i in items]), CALLER),
        "sales_debit_notes", "sales_debit_note_lines", "debit_note_id"),
    "purchase credit note": (
        lambda items: pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
            client_id="CLI", vendor_id="VEND1", credit_note_date="2025-06-05", reason="Undercharged",
            lines=[_inv_line(i) for i in items]), CALLER),
        lambda doc, items: pcn.update_purchase_credit_note(doc, pcn.PurchaseCreditNoteUpdateIn(lines=[_inv_line(i) for i in items]), CALLER),
        "purchase_credit_notes", "purchase_credit_note_lines", "credit_note_id"),
}


def _created(result):
    assert result["success"] is True, result
    return result["data"]["id"]


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("foreign", [SIBLING, STRANGER], ids=["a sibling client's item", "another firm's item"])
def test_a_document_naming_another_clients_item_is_refused_and_nothing_is_written(world, kind, foreign):
    create, _update, table, lines_table, _fk = KINDS[kind]
    with pytest.raises(HTTPException) as caught:
        create([OWN, foreign])
    assert caught.value.status_code == 422
    assert "Line 2 names a product or service that is not in this client's catalogue" in caught.value.detail
    assert world.rows(table) == [] and world.rows(lines_table) == [], "a refused document left rows behind"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_document_naming_only_the_clients_own_items_is_written(world, kind):
    create, _update, table, lines_table, _fk = KINDS[kind]
    _created(create([OWN, OWN]))
    assert len(world.rows(table)) == 1 and len(world.rows(lines_table)) == 2


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_editing_a_draft_to_name_another_clients_item_is_refused_and_the_lines_are_untouched(world, kind):
    create, update, _table, lines_table, fk = KINDS[kind]
    doc = _created(create([OWN]))
    before = [dict(r) for r in world.rows(lines_table)]
    with pytest.raises(HTTPException) as caught:
        update(doc, [OWN, SIBLING])
    assert caught.value.status_code == 422 and "Line 2 names" in caught.value.detail
    assert [dict(r) for r in world.rows(lines_table)] == before, "a refused edit rewrote the lines"
    update(doc, [OWN, OWN])                       # the same edit with the client's own item goes through
    assert len([r for r in world.rows(lines_table) if r.get(fk) == doc]) == 2


def test_a_bulk_import_asks_once_per_distinct_item_and_not_once_per_invoice(world, monkeypatch):
    """The shared set a bulk import keeps: ten invoices naming two items cost two items' worth of reads, not ten."""
    reads = []
    real = world.table

    def counting(name):
        if name == "service_catalogue":
            reads.append(name)
        return real(name)
    monkeypatch.setattr(world, "table", counting)
    owned = {}
    for n in range(10):
        data = SalesInvoiceIn(client_id="CLI", customer_id="CUST1", invoice_no=f"INV-{n}", invoice_date="2025-06-01",
                              lines=[_inv_line(OWN, SalesInvoiceLineIn)]).model_dump()
        si._create_invoice_core(data, CALLER, bulk_cache={
            "customer": world.rows("customers")[0], "client_rec": world.rows("clients")[0],
            "existing_invoice_nos": set(), "owned_items": owned})
    assert len(reads) == 1, f"the catalogue was read {len(reads)} times for ten invoices naming one item"
    assert owned == {"CLI": {OWN.lower()}}


# ── recurring templates: refused now, because every run would refuse them later ──────────────────────

import services.recurring_invoice_service as ris  # noqa: E402
import services.recurring_purchase_bill_service as rpbs  # noqa: E402


def _template_data(kind, item):
    base = {"client_id": "CLI", "title": "Monthly", "frequency": "monthly", "start_date": "2026-04-01",
            "lines": [{"service_catalogue_id": item, "description": "Retainer", "hsn_sac": "9982",
                       "rate_paise": 100000, "gst_rate_percent": 18.0}]}
    base["customer_id" if kind == "invoice" else "vendor_id"] = "CUST1" if kind == "invoice" else "VEND1"
    return base


@pytest.mark.parametrize("kind, svc, table, lines_table", [
    ("invoice", ris, "recurring_invoice_templates", "recurring_invoice_template_lines"),
    ("bill", rpbs, "recurring_purchase_bill_templates", "recurring_purchase_bill_template_lines"),
])
def test_a_template_naming_another_clients_item_is_refused_at_create_and_at_edit(world, monkeypatch, kind, svc, table, lines_table):
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    with pytest.raises(HTTPException) as caught:
        svc.create_template(E2E_FIRM, _template_data(kind, SIBLING), "u1", db=world)
    assert caught.value.status_code == 422 and "Line 1 names" in caught.value.detail
    assert world.rows(table) == [] and world.rows(lines_table) == [], "a refused template left rows behind"

    template = svc.create_template(E2E_FIRM, _template_data(kind, OWN), "u1", db=world)
    before = [dict(r) for r in world.rows(lines_table)]
    with pytest.raises(HTTPException) as edit:
        svc.update_template(E2E_FIRM, template["id"], {"lines": _template_data(kind, STRANGER)["lines"]}, db=world)
    assert edit.value.status_code == 422
    assert [dict(r) for r in world.rows(lines_table)] == before, "a refused edit rewrote the template's lines"
    svc.update_template(E2E_FIRM, template["id"], {"title": "Renamed"}, db=world)   # an edit with no lines asks nothing
