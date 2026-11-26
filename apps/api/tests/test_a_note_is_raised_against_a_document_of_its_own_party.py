"""A credit or debit note is raised against an invoice or a bill of ITS OWN customer or supplier (POST-A-553).

WHAT WAS WRONG
    The four note routes asked whose CLIENT the document a note names is, and nothing more. A note for customer A could name customer B's
    invoice of the same client (the screens offer only the chosen party's documents, so the path was a hand-made request or an import).
    Issuing such a note allocates it against the named document: B's invoice has less open because of A's note, and both parties'
    statements, the ageing and the note tables of GSTR-1 carry a note against a recipient it was not issued to. And a draft whose party
    was changed by a request that named no document went on pointing at the old party's.

WHAT THIS HOLDS, for each of the four kinds
    * a new note that names another party's document is refused in one sentence, and nothing is stored; one that names its own party's
      is stored; one that names a document of another client is still "not found", in the words a missing row gets;
    * a draft edited to name another party's document is refused and the stored note is as it was;
    * a draft whose party is changed with no document named loses the old party's document in the same write, and keeps a document that
      is in fact the new party's; a draft whose party is changed WITH the new party's document keeps what was sent;
    * an edit that touches neither asks nothing and changes neither;
    * the function alone: nothing is asked with no database, with nothing named and nothing left behind, or of an issued note;
    * every one of the eight doors calls the party check, and calls it before its first write.

WHAT IT DOES NOT HOLD. The routes are driven against the in-memory database. A writer that does not come through these routes (an import
that builds rows itself, a database function) is not asked. Production was read on 22-11-2026 (read-only): five notes, three with a
document named, none against another party's.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from fastapi import HTTPException

import routers.credit_notes as cn
import routers.debit_notes as dn
import routers.purchase_credit_notes as pcn
import routers.sales_debit_notes as sdn
import services.named_row_ownership as nro
from models.invoices import InvoiceLineIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


class Kind:
    def __init__(self, module, table, create, update, create_model, update_model, date_key, party_key, link_key, party_table, doc_table, sentence, missing):
        self.module, self.table, self.create, self.update = module, table, create, update
        self.create_model, self.update_model, self.date_key = create_model, update_model, date_key
        self.party_key, self.link_key, self.party_table, self.doc_table = party_key, link_key, party_table, doc_table
        self.sentence, self.missing = sentence, missing

    def __repr__(self):
        return self.table


KINDS = [
    Kind(cn, "credit_notes", "create_credit_note", "update_credit_note", "CreditNoteIn", "CreditNoteUpdateIn", "credit_note_date",
         "customer_id", "sales_invoice_id", "customers", "client_sales_invoices", nro.ANOTHER_CUSTOMERS_INVOICE, "That invoice was not found."),
    Kind(sdn, "sales_debit_notes", "create_sales_debit_note", "update_sales_debit_note", "SalesDebitNoteIn", "SalesDebitNoteUpdateIn", "debit_note_date",
         "customer_id", "sales_invoice_id", "customers", "client_sales_invoices", nro.ANOTHER_CUSTOMERS_INVOICE, "That invoice was not found."),
    Kind(dn, "debit_notes", "create_debit_note", "update_debit_note", "DebitNoteIn", "DebitNoteUpdateIn", "debit_note_date",
         "vendor_id", "purchase_bill_id", "vendors", "purchase_bills", nro.ANOTHER_SUPPLIERS_BILL, "That bill was not found."),
    Kind(pcn, "purchase_credit_notes", "create_purchase_credit_note", "update_purchase_credit_note", "PurchaseCreditNoteIn", "PurchaseCreditNoteUpdateIn",
         "credit_note_date", "vendor_id", "purchase_bill_id", "vendors", "purchase_bills", nro.ANOTHER_SUPPLIERS_BILL, "That bill was not found."),
]
IDS = [k.table for k in KINDS]


def _world(monkeypatch, k: Kind):
    """A client with two parties and a document of each, and a second client with a document of its own."""
    db = FakeDB()
    wire_e2e(monkeypatch, db, [k.module])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    for client in ("CLI", "OTHER"):
        db.seed("clients", {"id": client, "firm_id": FIRM, "gstin": "27AAAAA0000A1Z2", "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Advice", "kind": "service"})
    for party in ("P-A", "P-B"):
        db.seed(k.party_table, {"id": party, "firm_id": FIRM, "client_id": "CLI", "name": f"Party {party}", "state_code": "27", "is_active": True,
                                "opening_balance_paise": 0, "tds_applicable": False})
    doc = {"firm_id": FIRM, "status": "issued", "is_interstate": False, "is_opening": False, "invoice_date": "2026-05-01", "bill_date": "2026-05-01",
           "total_paise": 118000}
    db.seed(k.doc_table, {**doc, "id": "DOC-A", "client_id": "CLI", k.party_key: "P-A"})
    db.seed(k.doc_table, {**doc, "id": "DOC-B", "client_id": "CLI", k.party_key: "P-B"})
    db.seed(k.doc_table, {**doc, "id": "DOC-ELSEWHERE", "client_id": "OTHER", k.party_key: "P-X"})
    return db


def _line():
    return InvoiceLineIn(description="line", quantity=1, rate_paise=20000, gst_rate_percent=18.0, service_catalogue_id="SVC-1")


def _create(k: Kind, party, link):
    model = getattr(k.module, k.create_model)
    body = {"client_id": "CLI", k.party_key: party, k.date_key: "2026-06-05", "lines": [_line()]}
    if link is not None:
        body[k.link_key] = link
    return getattr(k.module, k.create)(model(**body), CALLER)


def _draft(db, k: Kind, party="P-A", link="DOC-A", status="draft"):
    return db.seed(k.table, {"firm_id": FIRM, "client_id": "CLI", "status": status, k.party_key: party, k.link_key: link, k.date_key: "2026-06-05",
                             "reason": "Rate correction", "notes": "n", "total_paise": 100, "deleted_at": None})


def _edit(k: Kind, note_id, **body):
    return getattr(k.module, k.update)(note_id, getattr(k.module, k.update_model)(**body), CALLER)


def _stored(db, table, row_id):
    return next(r for r in db.rows(table) if r["id"] == row_id)


# ── a new note ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_new_note_that_names_another_partys_document_is_refused_and_nothing_is_stored(monkeypatch, k):
    db = _world(monkeypatch, k)
    with pytest.raises(HTTPException) as refused:
        _create(k, "P-A", "DOC-B")
    assert refused.value.status_code == 422 and refused.value.detail == k.sentence
    assert db.rows(k.table) == [], "the note was stored before the question was asked"


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_new_note_against_its_own_partys_document_and_one_against_nothing_are_stored(monkeypatch, k):
    db = _world(monkeypatch, k)
    out = _create(k, "P-A", "DOC-A")
    assert out["success"] is True, out
    assert _stored(db, k.table, out["data"]["id"])[k.link_key] == "DOC-A"
    out = _create(k, "P-B", None)
    assert out["success"] is True, out
    assert _stored(db, k.table, out["data"]["id"])[k.link_key] is None


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_document_of_another_client_is_still_answered_as_it_was_and_never_as_another_partys(monkeypatch, k):
    db = _world(monkeypatch, k)
    # The sales credit note's create has had its own sentence for this since SALES-30 (a 422, held by tests/test_r237_ar_ap_hardening.py);
    # it is asked first and keeps it. The other three answer in the words a missing row gets.
    status, words = (422, "The invoice this credit note refers to is not part of this client's books.") if k.table == "credit_notes" else (404, k.missing)
    for stranger in ("DOC-ELSEWHERE", "DOC-INVENTED"):
        with pytest.raises(HTTPException) as refused:
            _create(k, "P-A", stranger)
        assert refused.value.status_code == status and refused.value.detail == words, stranger
        assert refused.value.detail != k.sentence, "a stranger's document is answered as another party's: the answer says the row exists"
    assert db.rows(k.table) == []


# ── a draft, edited ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_draft_edited_to_name_another_partys_document_is_refused_and_is_as_it_was(monkeypatch, k):
    db = _world(monkeypatch, k)
    note = _draft(db, k)
    with pytest.raises(HTTPException) as refused:
        _edit(k, note["id"], **{k.link_key: "DOC-B"})
    assert refused.value.status_code == 422 and refused.value.detail == k.sentence
    assert _stored(db, k.table, note["id"])[k.link_key] == "DOC-A"


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_draft_whose_party_is_changed_with_no_document_named_drops_the_old_partys_document(monkeypatch, k):
    db = _world(monkeypatch, k)
    note = _draft(db, k)
    out = _edit(k, note["id"], **{k.party_key: "P-B"})
    assert out["success"] is True, out
    stored = _stored(db, k.table, note["id"])
    assert stored[k.party_key] == "P-B"
    assert stored[k.link_key] is None, f"{k.table}: the note is now for P-B and still raised against P-A's document"


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_draft_whose_party_is_corrected_to_the_documents_own_party_keeps_the_document(monkeypatch, k):
    """A note stored for the wrong party over the right document (the state the rule exists to stop) is put right by correcting the
    party, and the document must not be thrown away for it."""
    db = _world(monkeypatch, k)
    note = _draft(db, k, party="P-A", link="DOC-B")
    out = _edit(k, note["id"], **{k.party_key: "P-B"})
    assert out["success"] is True, out
    stored = _stored(db, k.table, note["id"])
    assert stored[k.party_key] == "P-B" and stored[k.link_key] == "DOC-B"


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_draft_whose_party_and_document_are_changed_together_takes_both_or_neither(monkeypatch, k):
    db = _world(monkeypatch, k)
    note = _draft(db, k)
    out = _edit(k, note["id"], **{k.party_key: "P-B", k.link_key: "DOC-B"})
    assert out["success"] is True, out
    stored = _stored(db, k.table, note["id"])
    assert stored[k.party_key] == "P-B" and stored[k.link_key] == "DOC-B"
    # ...and the new party with the OLD party's document is refused: the party in the request is the one the document is judged against.
    with pytest.raises(HTTPException) as refused:
        _edit(k, note["id"], **{k.party_key: "P-A", k.link_key: "DOC-B"})
    assert refused.value.status_code == 422 and refused.value.detail == k.sentence
    assert _stored(db, k.table, note["id"])[k.party_key] == "P-B"


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_an_edit_that_touches_neither_the_party_nor_the_document_changes_neither(monkeypatch, k):
    db = _world(monkeypatch, k)
    for status in ("draft", "issued"):
        note = _draft(db, k, status=status)
        out = _edit(k, note["id"], notes="checked")
        assert out["success"] is True, out
        stored = _stored(db, k.table, note["id"])
        assert stored[k.party_key] == "P-A" and stored[k.link_key] == "DOC-A" and stored["notes"] == "checked"


@pytest.mark.parametrize("k", KINDS, ids=IDS)
def test_a_draft_that_takes_its_document_away_with_a_new_party_is_not_asked_about_the_old_one(monkeypatch, k):
    db = _world(monkeypatch, k)
    note = _draft(db, k)
    out = _edit(k, note["id"], **{k.party_key: "P-B", k.link_key: None})
    assert out["success"] is True, out
    stored = _stored(db, k.table, note["id"])
    assert stored[k.party_key] == "P-B" and stored[k.link_key] is None


# ── the function, alone ───────────────────────────────────────────────────────────

class _NoRead:
    def table(self, name):
        raise AssertionError(f"a read of {name} was made where nothing was to be asked")


@pytest.mark.parametrize("fn,party_key,link_key", [(nro.note_invoice_is_its_customers, "customer_id", "sales_invoice_id"),
                                                   (nro.note_bill_is_its_suppliers, "vendor_id", "purchase_bill_id")])
def test_nothing_is_asked_where_there_is_nothing_to_ask(fn, party_key, link_key):
    stored_draft = {"status": "draft", party_key: "P-A", link_key: "DOC-A"}
    fn(None, FIRM, "CLI", {party_key: "P-A", link_key: "DOC-B"})                                   # no database (mock mode)
    fn(_NoRead(), FIRM, "CLI", {party_key: "P-A"})                                                # a create that names nothing
    fn(_NoRead(), FIRM, "CLI", {"notes": "n"}, stored_draft)                                      # an edit of neither
    fn(_NoRead(), FIRM, "CLI", {party_key: "P-A"}, stored_draft)                                  # the party sent is the party stored
    fn(_NoRead(), FIRM, "CLI", {party_key: "P-B"}, {**stored_draft, link_key: None})              # nothing was stored to leave behind
    fn(_NoRead(), FIRM, "CLI", {party_key: "P-B"}, {**stored_draft, "status": "issued"})          # an issued note's party cannot change
    fn(_NoRead(), FIRM, "CLI", {party_key: "P-B"}, stored_draft, cleared=True)                    # the request takes the link away itself
    data = {party_key: "P-B", link_key: ""}
    fn(_NoRead(), FIRM, "CLI", data, {**stored_draft, link_key: None})                            # a blank names nothing
    assert data == {party_key: "P-B", link_key: ""}


# ── every door asks, before it writes ─────────────────────────────────────────────

def _is_a_write(called: str, node: ast.Call) -> bool:
    """A database write, by the rule `tests/test_a_document_names_only_rows_of_its_own_client.py` uses: the numbering insert, the
    replacement of a draft's lines, or `.insert/.update/.delete/.upsert` on a chain that starts at `.table(...)`. A plain dict's
    `.update` is not one, and neither is anything the branch with no database does (it holds the notes in a list)."""
    if called in {"insert_numbered_document_with_lines", "replace_draft_lines"}:
        return True
    if called not in {"insert", "update", "delete", "upsert"} or not isinstance(node.func, ast.Attribute):
        return False
    probe = node.func.value
    while isinstance(probe, (ast.Call, ast.Attribute)):
        if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute) and probe.func.attr == "table":
            return True
        probe = probe.func.value if isinstance(probe, ast.Call) and isinstance(probe.func, ast.Attribute) else getattr(probe, "value", None)
    return False


def _calls(fn):
    """(line, name called, is it a database write) for every call in the route."""
    out = []
    for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            out.append((node.lineno, name, _is_a_write(name, node)))
    return sorted(out)


@pytest.mark.parametrize("module,name,check", [
    (cn, "create_credit_note", "note_invoice_is_its_customers"), (cn, "update_credit_note", "note_invoice_is_its_customers"),
    (sdn, "create_sales_debit_note", "note_invoice_is_its_customers"), (sdn, "update_sales_debit_note", "note_invoice_is_its_customers"),
    (dn, "create_debit_note", "note_bill_is_its_suppliers"), (dn, "update_debit_note", "note_bill_is_its_suppliers"),
    (pcn, "create_purchase_credit_note", "note_bill_is_its_suppliers"), (pcn, "update_purchase_credit_note", "note_bill_is_its_suppliers"),
])
def test_every_note_door_asks_whose_party_the_document_is_before_it_writes(module, name, check):
    calls = _calls(getattr(module, name))
    asks = [line for line, called, _w in calls if called == check]
    assert len(asks) == 1, f"{module.__name__}.{name} asks {len(asks)} times"
    writes = [line for line, _called, is_write in calls if is_write]
    assert writes, f"{module.__name__}.{name}: the scan found no write, so it proves nothing"
    assert asks[0] < min(writes), f"{module.__name__}.{name} writes (line {min(writes)}) before it asks (line {asks[0]})"
    weaker = {"sales_invoice_is_the_clients", "purchase_bill_is_the_clients"}
    assert not [c for _l, c, _w in calls if c in weaker], f"{module.__name__}.{name} still asks only whose client the document is"


def test_the_edit_doors_hand_the_stored_note_and_say_when_the_request_clears_the_link_itself():
    for module, name, link in [(cn, "update_credit_note", "sales_invoice_id"), (sdn, "update_sales_debit_note", "sales_invoice_id"),
                               (dn, "update_debit_note", "purchase_bill_id"), (pcn, "update_purchase_credit_note", "purchase_bill_id")]:
        src = inspect.getsource(getattr(module, name))
        assert f'cleared="{link}" in draft_clears)' in src, f"{module.__name__}.{name} does not say when the request clears the link itself"
